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


# ---------------------------------------------------------------------------
# Global-usages + scope-downward projection
# ---------------------------------------------------------------------------
# The 2nd projection (run twice) propagates tests from usage sites back to the
# definition line via global_definitions. _parse_globals_defs records only the
# `def` header (not the body), so after global_usages only line 1 has tests.
#
# The 3rd projection (scope-downward) then pushes those tests from the def line
# down into every body line that lacks direct coverage, so that changing any
# body line of a module-level-called function correctly predicts tests.
#
# Projection chain for a function called at module level:
#   1. cross-file imports projection puts test_T on line N (usage site) in src.py
#   2. second-pass global_usages: N has test_T → propagated to def line (line 1)
#   3. scope-downward: line 1 starts a scope → tests pushed to uncovered lines 2-4
# ---------------------------------------------------------------------------

class TestGlobalUsagesProjection:

    def test_only_def_line_gets_tests_body_stays_empty(self):
        """
        global_definitions records only the def header line.  The global_usages
        chain propagates tests to that line; the function body stays empty.

        src.py:
            def somefunction(x):      # line 1  ← global_definitions["somefunction"]
                a = x + 1             # line 2  ← no coverage → stays empty
                b = a * 2             # line 3  ← no coverage → stays empty
                return b              # line 4  ← no coverage → stays empty
                                      # line 5  (blank)
            RESULT = somefunction(5)  # line 6

        test_src.py:
            from src import RESULT   # line 1
            def test_result():       # line 3
                assert RESULT == 10  # line 4

        Flow:
          cross-file imports: test_result → src.py line 6 (RESULT definition)
          global_usages 2nd pass: line 6 has tests → somefunction at line 6
                                  → tests propagated to global_definitions = [1]
          lines 2-4 receive no projection → changing any body line predicts 0 tests
        """
        src_code = (
            "def somefunction(x):\n"      # line 1
            "    a = x + 1\n"             # line 2
            "    b = a * 2\n"             # line 3
            "    return b\n"              # line 4
            "\n"                          # line 5
            "RESULT = somefunction(5)\n"  # line 6
        )
        test_code = (
            "from src import RESULT\n"    # line 1
            "\n"
            "def test_result():\n"        # line 3
            "    assert RESULT == 10\n"   # line 4
        )
        py = _run_projection(
            {"src.py": src_code, "test_src.py": test_code},
            {
                "src.py": {1: set(), 2: set(), 3: set(), 4: set(), 6: set()},
                "test_src.py": {4: {"test_result"}},
            },
            {"src": {"src.py": {1, 2, 3, 4, 6}}}
        )
        # Only the def line gets test_result via the global_usages chain
        for line in range(1, 5):
            assert py["src.py"][line] == {"test_result"}


# ---------------------------------------------------------------------------
# Import-time projection
# ---------------------------------------------------------------------------
# The 3rd pass in _extend_mappings: for each LOCAL import (inside a test
# function body) that has test coverage, propagate those tests to every line
# that executes when that module is imported from scratch.
#
# This is the mechanism that SHOULD label function body lines when the
# function is called at module-load time — but only fires when the importing
# test uses a local import (not a module-level import).
# ---------------------------------------------------------------------------

class TestImportTimeProjection:

    def test_local_import_projects_onto_function_body_called_at_import(self):
        """
        A function whose body executes at module load time (called at module
        level) should have its body lines attributed to tests that locally
        import that module.

        mymodule.py:
            def compute(x):       # line 1  ← only `def` runs at import
                return x * 2      # line 2  ← body runs when compute() is called
                                  # line 3  (blank)
            RESULT = compute(5)   # line 4  ← calls compute at import time

        test_mymodule.py:
            def test_result():
                from mymodule import RESULT  # line 2 — LOCAL import

        import_time_lines["mymodule"] = {"mymodule.py": {1, 2, 4}}
        coverage: test_mymodule.py line 2 attributed to test_result

        Expected: all three lines (1, 2, 4) in mymodule.py get test_result.
        """
        module_code = (
            "def compute(x):\n"       # line 1
            "    return x * 2\n"      # line 2
            "\n"                      # line 3
            "RESULT = compute(5)\n"   # line 4
        )
        test_code = (
            "def test_result():\n"               # line 1
            "    from mymodule import RESULT\n"  # line 2 — local import
        )
        py = _run_projection(
            {"mymodule.py": module_code, "test_mymodule.py": test_code},
            {"test_mymodule.py": {2: {"test_result"}}},
            import_time_lines={"mymodule": {"mymodule.py": {1, 2, 4}}},
        )
        assert py["mymodule.py"][1] == {"test_result"}  # def line
        assert py["mymodule.py"][2] == {"test_result"}  # body line — the key assertion
        assert py["mymodule.py"][4] == {"test_result"}  # module-level call

    def test_module_level_import_does_not_trigger_import_time_projection(self):
        """
        A MODULE-LEVEL import in the test file carries no test context (it runs
        at collection time), so the import line has no test attribution and the
        import-time projection is NOT triggered.

        This is the root cause of the over-projection symptom: the def line may
        accumulate tests via global-usages / cross-file imports projection, while
        the body lines remain empty because import-time projection never ran.
        """
        test_code = (
            "from mymodule import RESULT\n"  # line 1 — module-level, no test context
            "\n"
            "def test_result():\n"           # line 3
            "    assert RESULT == 10\n"      # line 4
        )
        py = _run_projection(
            {"mymodule.py": "", "test_mymodule.py": test_code},
            {"test_mymodule.py": {4: {"test_result"}}},
            import_time_lines={"mymodule": {"mymodule.py": {1, 2, 4}}},
        )
        # The import line (1) has no test attribution in coverage data, so
        # local_import_sources["mymodule"] never fires — mymodule.py gets nothing.
        assert "mymodule.py" in py
