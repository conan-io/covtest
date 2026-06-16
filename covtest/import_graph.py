"""Import-time line tracing for covtest.

For each source-module dotpath that appears as an import source in any covered
file, this module computes which lines execute when that module is imported.
CovTestData._extend_mappings uses the result to project test coverage through
import chains that are invisible to direct line-coverage tracking.

Algorithm
---------
1. **Single monitoring pass** — all dotpaths are imported in one session with
   the executed-line buffer cleared between each.  First-touched modules run
   fresh and capture lines (including transitive deps); later imports of the
   same already-cached module capture nothing.

2. **Flat accumulation** — all raw windows are merged into a single
   ``{rel_file: set(lines)}`` map.  Every file that executed during the trace
   session ends up here, regardless of which dotpath's window captured it.

3. **Import closure per dotpath** — for each dotpath D, BFS from D's source
   file through ``import_sources`` (absolute and relative, pre-resolved by
   ``ParsedData``), collecting every reachable file that appears in the flat
   map.  Only files actually captured during tracing are included.

No two-stage retry, no closure cache, no empty-window special cases.
"""

import importlib
import os
import sys
from collections import defaultdict

from covtest.output import out_info


def get_all_sources_by_file(cov_data, parse_results, folder):
    # Include ALL project files (not just test files): source files like leaf.py
    # may import a package with a test-attributed line, which is exactly the
    # trigger the projection needs.  Only add a dotpath if at least one of its
    # declaration lines has direct test attribution — dotpaths whose lines are
    # only covered at collection time (empty test set) produce no projection.
    all_import_sources = {}
    for f, file_cov in cov_data.items():
        parsed_file_data = parse_results.files.get(f)
        if parsed_file_data is None:
            continue
        # Use local_import_sources (function-body imports only) so that only tests
        # which *directly execute* an import statement at run-time are projected
        # onto the imported module's lines.  Module-level imports run at collection
        # time and are often shared across many tests, leading to massive
        # over-prediction when the transitive import chain is large.
        for dotpath, decl_lines in parsed_file_data.import_sources.items():
            all_import_sources.setdefault(f, []).append(dotpath)
            # Also include every ancestor package so that the transitive
            # import chain (e.g. physics/__init__ → units → si.py) gets
            # traced even when only a deep leaf is imported directly.
            parts = dotpath.split(".")
            for i in range(1, len(parts)):
                ancestor = ".".join(parts[:i])
                if _source_file(ancestor, folder) is not None:
                    all_import_sources.setdefault(f, []).append(ancestor)
    return all_import_sources


def build_import_graph(folder, import_sources_by_file, parse_results):
    """Compute import-time line coverage for every dotpath found in test files.

    Parameters
    ----------
    folder : str
        Absolute path to the project root.
    import_sources_by_file : dict[str, list[str]]
        {relative_file_path: [dotpath, …]} — collected from ParsedData.
    parse_results : ParsedData
        Pre-parsed AST data for all covered files; used by Pass 2 to resolve
        import edges without re-reading source files.

    Returns
    -------
    dict[str, dict[str, set[int]]]
        {source_dotpath: {relative_file_path: set(lines)}}
    """
    folder = os.path.realpath(folder)

    all_dotpaths = {
        dp
        for dotpaths in import_sources_by_file.values()
        for dp in dotpaths
        if _source_file(dp, folder) is not None
    }

    out_info(f"tracing imports  : {len(all_dotpaths)} unique dotpaths from "
             f"{len(import_sources_by_file)} test files")

    raw, _errors = _single_pass_trace(sorted(all_dotpaths), folder)

    file_lines_seen = defaultdict(set)
    for dp_result in raw.values():
        for rel_file, lines in dp_result.items():
            file_lines_seen[rel_file].update(lines)

    result = _compute_import_closure(file_lines_seen, all_dotpaths, parse_results)

    n_with_lines = sum(1 for res in result.values() if res)
    out_info(f"import_graph: {n_with_lines}/{len(result)} dotpaths produced lines")

    return result


def _source_file(dotpath, folder):
    """Return abs path to dotpath's source file under folder, or None.

    Handles both plain modules (``a/b/c.py``) and packages (``a/b/__init__.py``).
    Returns None for stdlib / site-packages dotpaths that have no source under folder.
    """
    parts = dotpath.replace(".", os.sep)
    f = os.path.join(folder, parts + ".py")
    if os.path.isfile(f):
        return f
    f = os.path.join(folder, parts, "__init__.py")
    if os.path.isfile(f):
        return f
    return None


def _single_pass_trace(dotpaths, folder):
    """One sys.monitoring session — import each dotpath with a fresh line buffer.

    The ``executed`` dict is cleared between dotpaths so each window captures
    only lines that ran during that specific import call.  Modules already in
    sys.modules are no-ops and produce empty windows — Pass 1 recovers them.

    All traced dotpaths (and their submodules) are evicted from sys.modules
    before the loop so that the first import always runs fresh even when called
    from inside a process that has already imported those modules (e.g. pytest).
    sys.modules is restored to its original state after the trace.

    Parameters
    ----------
    dotpaths : list[str]
        Dotpaths to import, in order.
    folder : str
        Realpath of the project root (already resolved by caller).

    Returns
    -------
    tuple[dict, dict]
        ``(raw, errors)`` where raw is ``{dotpath: {rel_file: set(lines)}}``
        and errors is ``{dotpath: error_string}`` for failed imports.
    """
    folder_norm = os.path.normcase(folder) + os.sep
    _norm = {}   # co_filename → rel_path (str) if under folder, False otherwise
    executed = {}

    def _line_handler(code, line_number):
        fn = code.co_filename
        rel = _norm.get(fn)
        if rel is None:
            fn_norm = os.path.normcase(fn)
            if fn_norm.startswith(folder_norm) and "site-packages" not in fn_norm:
                rel = os.path.relpath(fn, folder).replace("\\", "/")
            else:
                rel = False
            _norm[fn] = rel
        if not rel:
            return sys.monitoring.DISABLE
        executed.setdefault(rel, set()).add(line_number)

    # Evict traced dotpaths so each importlib.import_module runs fresh even
    # when called from inside a process (e.g. pytest) that already imported them.
    evict_keys = {k for k in sys.modules
                  for dp in dotpaths
                  if k == dp or k.startswith(dp + ".")}
    saved = {k: sys.modules.pop(k) for k in list(evict_keys)}

    tool_id = None
    for tid in (sys.monitoring.COVERAGE_ID, 3, 4,
                sys.monitoring.PROFILER_ID, sys.monitoring.DEBUGGER_ID,
                sys.monitoring.OPTIMIZER_ID):
        if sys.monitoring.get_tool(tid) is None:
            sys.monitoring.use_tool_id(tid, "covtest")
            tool_id = tid
            break
    if tool_id is None:
        sys.modules.update(saved)
        raise RuntimeError("No free sys.monitoring tool ID available")

    sys.monitoring.register_callback(tool_id, sys.monitoring.events.LINE, _line_handler)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.LINE)
    sys.path.insert(0, folder)
    raw = {}
    errors = {}
    try:
        for dotpath in dotpaths:
            executed.clear()
            try:
                importlib.import_module(dotpath)
            except BaseException as exc:
                errors[dotpath] = f"{type(exc).__name__}: {exc}"
            raw[dotpath] = dict(executed)
    finally:
        sys.path.remove(folder)
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.LINE, None)
        sys.monitoring.free_tool_id(tool_id)
        # Remove newly imported traced modules, restore originals.
        for key in list(sys.modules):
            for dp in dotpaths:
                if key == dp or key.startswith(dp + "."):
                    del sys.modules[key]
                    break
        sys.modules.update(saved)

    return raw, errors


def _compute_import_closure(file_lines_seen, all_dotpaths, parse_results):
    """For each dotpath, return only its own source file's captured lines.

    Returns
    -------
    dict[str, dict[str, set[int]]]
        ``{dotpath: {rel_file: set(lines)}}``
    """
    result = {}
    for dp in all_dotpaths:
        prefix = dp.replace(".", "/")
        own = {}
        for suffix in (".py", "/__init__.py"):
            rel = prefix + suffix
            if rel in file_lines_seen:
                own[rel] = set(file_lines_seen[rel])
        result[dp] = own
    return result

