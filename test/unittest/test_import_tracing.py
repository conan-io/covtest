"""Unit tests for the core sys.settrace tracing mechanism in import_graph."""
import ast as _ast
import os
import sys
import textwrap
from collections import defaultdict
from os.path import normcase

import pytest

from covtest.import_graph import _single_pass_trace
from test.e2e.client import TestClient


@pytest.fixture(autouse=True)
def _clean_modules():
    before = set(sys.modules)
    yield
    for key in list(sys.modules):
        if key not in before:
            del sys.modules[key]


def _client(files):
    tc = TestClient()
    tc.save(files)
    return tc


def _run_trace(dotpath, folder):
    raw, errors = _single_pass_trace([dotpath], folder)
    return raw.get(dotpath, {}), errors.get(dotpath)


def test_simple_module():
    tc = _client({"mypkg/simple.py": "X = 1\nY = X + 2\n"})
    lines, error = _run_trace("mypkg.simple", tc.cwd)
    assert error is None
    assert lines["mypkg/simple.py"] == {1, 2}


def test_init_imports_submodule():
    tc = _client({
        "mypkg/__init__.py": "from mypkg.sub import VALUE\n",
        "mypkg/sub.py": "VALUE = 42\n",
    })
    lines, error = _run_trace("mypkg", tc.cwd)
    assert error is None
    assert lines["mypkg/__init__.py"] == {1}
    assert lines["mypkg/sub.py"] == {1}


def test_import_time_function_call():
    """Function body lines are captured when the function is called at import time."""
    tc = _client({
        "mypkg/eager.py": (
            "def helper(x):\n"      # line 1
            "    return x * 2\n"    # line 2
            "\n"                     # line 3  — blank
            "RESULT = helper(5)\n"  # line 4
        ),
    })
    lines, error = _run_trace("mypkg.eager", tc.cwd)
    assert error is None
    assert lines["mypkg/eager.py"] == {1, 2, 4}  # blank line 3 not captured


def test_three_level_transitive_chain():
    tc = _client({
        "mypkg/__init__.py": "from mypkg.mod1 import A\n",
        "mypkg/mod1.py": "from mypkg.mod2 import B\nA = B + 1\n",
        "mypkg/mod2.py": "B = 100\n",
    })
    lines, error = _run_trace("mypkg", tc.cwd)
    assert error is None
    assert lines["mypkg/__init__.py"] == {1}
    assert lines["mypkg/mod1.py"] == {1, 2}
    assert lines["mypkg/mod2.py"] == {1}


def test_sys_modules_restored_after_trace():
    """_run_trace restores sys.modules to its pre-trace state."""
    tc = _client({
        "mypkg/__init__.py": "from mypkg.sub import VALUE\n",
        "mypkg/sub.py": "VALUE = 42\n",
    })
    snapshot = dict(sys.modules)
    _run_trace("mypkg", tc.cwd)
    assert set(sys.modules) == set(snapshot)
    for key in snapshot:
        assert sys.modules[key] is snapshot[key]


def test():
    mod1 = textwrap.dedent("""\
        from mod2 import mod2_function
        class Potato1:
            def __init__(self):
                pass
            def __str__(self):
                return "Potato1"

        def mod1_function():
            B = 3

        mod1_A = 14
        """)
    mod2 = textwrap.dedent("""\
        import mod3
        class Potato2:
            def __init__(self):
                pass
            def __str__(self):
                return "Potato2"

        def mod2_function():
            B = 3

        mod2_A = 14
        """)
    mod3 = textwrap.dedent("""\
        from folder.mod4 import mod4_function
        class Potato3:
            def __init__(self):
                pass
            def __str__(self):
                return "Potato3"

        def mod3_function():
            B = 3

        mod3_A = 14
        """)
    mod4 = textwrap.dedent("""\
        def mod4_function():
            return 42

        mod4_A = 100
        """)
    tc = _client({
        "mod1.py": mod1,
        "mod2.py": mod2,
        "mod3.py": mod3,
        "folder/__init__.py": "",
        "folder/mod4.py": mod4,
    })

    folder = tc.cwd
    folder_norm = os.path.normcase(folder) + os.sep
    _norm = {}  # co_filename → rel_path (str) if under folder, False otherwise
    executed = {}

    def _line_handler(code, line_number):
        fn = code.co_filename
        rel = _norm.get(fn)
        if rel is None:
            fn_norm = normcase(fn)
            if fn_norm.startswith(folder_norm) and "site-packages" not in fn_norm:
                rel = os.path.relpath(fn, folder).replace("\\", "/")
            else:
                rel = False
            _norm[fn] = rel
        if not rel:
            return sys.monitoring.DISABLE
        executed.setdefault(rel, set()).add(line_number)

    tool_id = None
    for tid in (sys.monitoring.COVERAGE_ID, 3, 4,
                sys.monitoring.PROFILER_ID, sys.monitoring.DEBUGGER_ID,
                sys.monitoring.OPTIMIZER_ID):
        if sys.monitoring.get_tool(tid) is None:
            sys.monitoring.use_tool_id(tid, "covtest")
            tool_id = tid
            break
    if tool_id is None:
        raise RuntimeError("No free sys.monitoring tool ID available")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.LINE, _line_handler)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.LINE)
    sys.path.insert(0, folder)
    final_result = {}
    import importlib
    try:
        for i in ("folder.mod4", "mod3", "mod2", "mod1"):
            executed.clear()
            importlib.import_module(i)
            final_result[i] = executed.copy()
    except Exception as e:
        print("ERROR ", e)
        raise
    finally:
        sys.path.remove(folder)
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.LINE, None)
        sys.monitoring.free_tool_id(tool_id)

    from pprint import pprint
    print()
    pprint(final_result)

    # --- Pass 1: direct attribution -------------------------------------------
    # Collect the union of all lines ever seen, keyed by relative file path.
    # Any module that ran transitively (before its own explicit trace) will have
    # its lines captured in whichever dotpath first imported it.
    file_lines_seen = defaultdict(set)
    for dp_result in final_result.values():
        for rel_file, lines in dp_result.items():
            file_lines_seen[rel_file].update(lines)

    # Each dotpath gets its lines based on whether its window was non-empty:
    # - non-empty window (ran fresh): keep the full raw window
    # - empty window (was cached): recover own source-file lines from file_lines_seen
    pass1 = {}
    for dp, dp_result in final_result.items():
        if dp_result:
            pass1[dp] = {f: set(lines) for f, lines in dp_result.items()}
        else:
            rel_mod = dp.replace(".", "/") + ".py"
            rel_pkg = dp.replace(".", "/") + "/__init__.py"
            if rel_mod in file_lines_seen:
                pass1[dp] = {rel_mod: set(file_lines_seen[rel_mod])}
            elif rel_pkg in file_lines_seen:
                pass1[dp] = {rel_pkg: set(file_lines_seen[rel_pkg])}
            else:
                pass1[dp] = {}

    # --- Pass 2: AST transitive closure ----------------------------------------
    # For each dotpath D, find what D imports (via AST), then merge those
    # dotpaths' results into D's result. Iterate to fixpoint so multi-hop
    # chains (D → E → F) propagate correctly.
    def _get_direct_imports(abs_src, known_dotpaths):
        with open(abs_src) as f:
            tree = _ast.parse(f.read())
        found = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ImportFrom) and node.module in known_dotpaths:
                found.append(node.module)
            elif isinstance(node, _ast.Import):
                for alias in node.names:
                    if alias.name in known_dotpaths:
                        found.append(alias.name)
        return found

    pass2 = {dp: {f: set(lines) for f, lines in files.items()} for dp, files in pass1.items()}
    changed = True
    while changed:
        changed = False
        for dp in pass2:
            abs_src = os.path.join(folder, dp.replace(".", os.sep) + ".py")
            for imported_dp in _get_direct_imports(abs_src, pass2):
                for rel_file, lines in pass2[imported_dp].items():
                    bucket = pass2[dp].setdefault(rel_file, set())
                    before = len(bucket)
                    bucket.update(lines)
                    if len(bucket) > before:
                        changed = True

    print("\npass2 (relative paths):")
    pprint(pass2)

    # folder/__init__.py runs as part of importing folder.mod4 (Python imports the
    # package before the submodule), so it correctly appears in all results that
    # transitively reach folder.mod4.
    assert set(pass2["mod1"]) == {"mod1.py", "mod2.py", "mod3.py", "folder/__init__.py", "folder/mod4.py"}
    assert set(pass2["mod2"]) == {"mod2.py", "mod3.py", "folder/__init__.py", "folder/mod4.py"}
    assert set(pass2["mod3"]) == {"mod3.py", "folder/__init__.py", "folder/mod4.py"}
    assert set(pass2["folder.mod4"]) == {"folder/__init__.py", "folder/mod4.py"}
