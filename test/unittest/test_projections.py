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


def _run_projection(files, coverage_data):
    """Write files to a temp dir, parse, project, return enriched py_files."""
    tc = TestClient()
    tc.save(files)
    parse_data = ParsedData(tc.cwd, list(files.keys()))
    result = CovTestData.create(coverage_data, parse_data, None)
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
# Global-usages + scope-downward projection (no import tracing — static only)
# ---------------------------------------------------------------------------
# global_declarations records only the `def`/`class` header (not the body).
# The fixpoint loop:
#   1. cross-file import projection puts test_T on the RESULT definition (src.py)
#   2. global_usages: somefunction used at the RESULT line → propagated to its
#      def header line
#   3. scope-downward: the def line starts a scope → tests pushed to the
#      uncovered body lines
# All of this is derived from the parsed AST — NO import_time_lines is passed in.
# ---------------------------------------------------------------------------

class TestGlobalUsagesProjection:

    def test_def_and_body_get_tests_via_static_chain(self):
        """
        A module-level call (RESULT = somefunction(5)) whose function body has no
        direct coverage still gets fully attributed, purely from the static chain:
        cross-file import → global_usages → scope-down.

        src.py:
            def somefunction(x):      # line 1  ← global_declarations["somefunction"]
                a = x + 1             # line 2  ← no coverage
                b = a * 2             # line 3  ← no coverage
                return b              # line 4  ← no coverage
                                      # line 5  (blank)
            RESULT = somefunction(5)  # line 6  ← global_objects["RESULT"]

        test_src.py:
            from src import RESULT   # line 1
            def test_result():       # line 3
                assert RESULT == 10  # line 4

        Flow:
          cross-file imports: RESULT used at test_src line 4 → src.py line 6 (def of RESULT)
          global_usages: somefunction used at line 6 → propagated to its def line 1
          scope-down: line 1 starts a scope → tests pushed to uncovered lines 2-4
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
        )
        # def line, full body, and the module-level call all get test_result
        for line in (1, 2, 3, 4, 6):
            assert py["src.py"][line] == {"test_result"}


# ---------------------------------------------------------------------------
# Static cross-file import projection
# ---------------------------------------------------------------------------
# project_imports walks each file's import_bindings and projects the tests
# attributed to each imported name's usages onto that name's definition in the
# source module (plus ancestor package __init__ lines). Single-name statements
# additionally follow the import line's own tests, threading re-export chains.
# No modules are imported; everything is derived from the parsed AST.
# ---------------------------------------------------------------------------

class TestImportProjection:

    def test_local_import_projects_onto_function_body_called_at_import(self):
        """
        A function whose body executes only at module-load time (called at module
        level) gets its body lines attributed to a test that imports the module —
        even though the imported name is never *used* after the local import,
        because the single-name import line itself carries the test.

        mymodule.py:
            def compute(x):       # line 1  ← only `def` runs at import
                return x * 2      # line 2  ← body runs when compute() is called
                                  # line 3  (blank)
            RESULT = compute(5)   # line 4  ← calls compute at import time

        test_mymodule.py:
            def test_result():
                from mymodule import RESULT  # line 2 — LOCAL import, single name

        Expected: lines 1, 2, 4 in mymodule.py get test_result.
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
        )
        assert py["mymodule.py"][1] == {"test_result"}  # def line
        assert py["mymodule.py"][2] == {"test_result"}  # body line — the key assertion
        assert py["mymodule.py"][4] == {"test_result"}  # module-level call

    def test_per_name_projection_does_not_cross_contaminate(self):
        """
        Two names imported (on separate lines) from the same module project only
        onto their own definitions — a test using one name must not be attributed
        to the other name's source.  This is the precision the `imports`
        integration case depends on.

        provider.py:
            cities_data = "A"      # line 1
            countries_data = "B"   # line 2

        consumer.py:
            from provider import cities_data     # line 1
            from provider import countries_data  # line 2
            def use_cities():    # line 4
                return cities_data       # line 5  ← test_cities
            def use_countries(): # line 7
                return countries_data    # line 8  ← test_countries
        """
        provider = (
            'cities_data = "A"\n'      # line 1
            'countries_data = "B"\n'   # line 2
        )
        consumer = (
            "from provider import cities_data\n"     # line 1
            "from provider import countries_data\n"  # line 2
            "\n"
            "def use_cities():\n"                    # line 4
            "    return cities_data\n"               # line 5
            "\n"
            "def use_countries():\n"                 # line 7
            "    return countries_data\n"            # line 8
        )
        py = _run_projection(
            {"provider.py": provider, "consumer.py": consumer},
            {
                "provider.py": {1: set(), 2: set()},
                "consumer.py": {5: {"test_cities"}, 8: {"test_countries"}},
            },
        )
        assert py["provider.py"][1] == {"test_cities"}      # cities_data — only test_cities
        assert py["provider.py"][2] == {"test_countries"}   # countries_data — only test_countries

    def test_ancestor_package_init_projection(self):
        """
        Importing a submodule attributes the test to the ancestor package's
        __init__ import-time lines, then the chain reaches a helper called there.

        pkg/__init__.py:
            from pkg.util import compute   # line 1
            VALUE = compute(1, 2)          # line 2  ← runs util.compute at init

        pkg/util.py:
            def compute(a, b):    # line 1
                return a + b      # line 2  ← mutation target

        pkg/leaf.py:
            LEAF = 3              # line 1  (no dependency on util)

        test_pkg.py:
            def test_leaf():
                from pkg.leaf import LEAF   # line 2 — importing pkg.leaf runs pkg/__init__
        """
        files = {
            "pkg/__init__.py": (
                "from pkg.util import compute\n"  # line 1
                "VALUE = compute(1, 2)\n"         # line 2
            ),
            "pkg/util.py": (
                "def compute(a, b):\n"  # line 1
                "    return a + b\n"    # line 2
            ),
            "pkg/leaf.py": "LEAF = 3\n",  # line 1
            "test_pkg.py": (
                "def test_leaf():\n"               # line 1
                "    from pkg.leaf import LEAF\n"  # line 2
            ),
        }
        py = _run_projection(
            files,
            {"test_pkg.py": {2: {"test_leaf"}}},
        )
        # ancestor pkg/__init__ ran compute() → util.compute body attributed to test_leaf
        assert py["pkg/util.py"][2] == {"test_leaf"}

    def test_reexport_chain_single_name(self):
        """
        A pure re-export (`from .sub import RESULT`, RESULT unused locally) still
        threads attribution to the original definition, via the single-name
        import-line rule.

        pkg/__init__.py:  from pkg.sub import RESULT     # line 1  (re-export)
        pkg/sub.py:       VALUE = 7                      # line 1
                          RESULT = VALUE                 # line 2
        test_pkg.py:      def test_x():
                              from pkg import RESULT      # line 2
                              assert RESULT == 7          # line 3
        """
        files = {
            "pkg/__init__.py": "from pkg.sub import RESULT\n",  # line 1
            "pkg/sub.py": (
                "VALUE = 7\n"      # line 1
                "RESULT = VALUE\n"  # line 2
            ),
            "test_pkg.py": (
                "def test_x():\n"                 # line 1
                "    from pkg import RESULT\n"    # line 2
                "    assert RESULT == 7\n"        # line 3
            ),
        }
        py = _run_projection(
            files,
            {"test_pkg.py": {2: {"test_x"}, 3: {"test_x"}}},
        )
        # RESULT's definition in sub.py is reached through the re-export
        assert py["pkg/sub.py"][2] == {"test_x"}
