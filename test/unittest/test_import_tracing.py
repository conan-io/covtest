"""Unit tests for the core sys.settrace tracing mechanism in import_graph."""

import sys

import pytest

from covtest.import_graph import _run_trace, trace_import
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
    """trace_import (not _run_trace) restores sys.modules to its pre-trace state."""
    tc = _client({
        "mypkg/__init__.py": "from mypkg.sub import VALUE\n",
        "mypkg/sub.py": "VALUE = 42\n",
    })
    snapshot = dict(sys.modules)
    trace_import("mypkg", tc.cwd)
    assert set(sys.modules) == set(snapshot)
    for key in snapshot:
        assert sys.modules[key] is snapshot[key]
