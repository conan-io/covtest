"""Unit tests for CovTestData projections.

Each test calls _run_projection(files, coverage_data) which:
  1. Writes source files to a temp directory
  2. Parses them with ParsedData
  3. Runs CovTestData.create() to apply all projections
  4. Returns the enriched py_files dict

This lets each projection pass be verified in isolation by crafting
minimal source files and coverage data, without running a full pytest suite.
"""

from covtest.ast_parser import ParsedData
from covtest.covtest_data import CovTestData
from test.e2e.client import TestClient


def _run_projection(files, coverage_data, import_time_lines=None):
    """Write files to a temp dir, parse, project, return enriched py_files."""
    tc = TestClient()
    tc.save(files)
    parse_data = ParsedData(tc.cwd, list(files.keys()))
    result = CovTestData.create(coverage_data, parse_data, None, import_time_lines or {})
    return result.py_files


class TestScopeProjection:
    """1st projection in _extend_mappings: when a line is covered but has no
    tests, and that line starts a scope (function/class body), tests attributed
    to any line inside that scope are propagated UP to the opening line.
    Typical trigger: the `def` line executes at module import time (no test
    context), but the function body is later called during a test.
    """

    def test_body_tests_propagate_to_def_line(self):
        """Body tests propagate to the def line when def has no direct attribution.

        def fn(x):       # line 1 — covered at module load, no tests
            return x * 2 # line 2 — covered during test_foo

        scopes: {1: 2}
        After projection: line 1 → {test_foo}
        """
        code = (
            "def fn(x):\n"        # line 1
            "    return x * 2\n"  # line 2
        )
        py = _run_projection(
            {"src.py": code},
            {"src.py": {1: set(), 2: {"test_foo"}}},
        )
        assert py["src.py"][1] == {"test_foo"}
        assert py["src.py"][2] == {"test_foo"}

    def test_collects_tests_from_multiple_body_lines(self):
        """Tests from different body lines are all collected into the def line."""
        code = (
            "def fn(x, y):\n"     # line 1 — no tests
            "    a = x + 1\n"     # line 2 — test_foo
            "    b = y + 2\n"     # line 3 — test_bar
            "    return a + b\n"  # line 4 — test_foo, test_bar
        )
        py = _run_projection(
            {"src.py": code},
            {"src.py": {1: set(), 2: {"test_foo"}, 3: {"test_bar"}, 4: {"test_foo", "test_bar"}}},
        )
        assert py["src.py"][1] == {"test_foo", "test_bar"}

    def test_does_not_overwrite_existing_tests_on_def_line(self):
        """A def line that already has tests is skipped by the scope projection."""
        code = (
            "def fn(x):\n"        # line 1 — already has test_direct
            "    return x * 2\n"  # line 2 — test_body
        )
        py = _run_projection(
            {"src.py": code},
            {"src.py": {1: {"test_direct"}, 2: {"test_body"}}},
        )
        # scope projection skips line 1 because it already has tests
        assert "test_body" not in py["src.py"][1]
        assert py["src.py"][1] == {"test_direct"}

    def test_class_body_propagates_to_class_line(self):
        """Same projection applies to class definitions."""
        code = (
            "class MyClass:\n"         # line 1 — no tests
            "    def method(self):\n"  # line 2 — no tests
            "        return 42\n"      # line 3 — test_foo
        )
        py = _run_projection(
            {"src.py": code},
            {"src.py": {1: set(), 2: set(), 3: {"test_foo"}}},
        )
        assert "test_foo" in py["src.py"][1]
        assert "test_foo" in py["src.py"][2]
