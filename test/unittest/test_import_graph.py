from covtest.import_graph import build_import_graph
from test.e2e.client import TestClient


def test_build_import_graph_two_levels_with_call():
    """
    Verify that build_import_graph captures import-time lines through two levels
    of transitivity, including lines inside a function body that is *called* at
    import time (not just defined).

    Chain:
        test_pkg.py      →  from pkg import RESULT          (local import in test fn)
        pkg/__init__.py  →  from pkg.sub import RESULT      (level 1 transitivity)
        pkg/sub.py       →  from pkg.leaf import compute
                            RESULT = compute()               (level 2 + function call)
        pkg/leaf.py      →  def compute(): return 42        (body executed at import!)
                            LEAF_VALUE = 10

    Expected lines per file
    -----------------------
    pkg/__init__.py : {1}       — the import statement
    pkg/sub.py      : {1, 2}    — import stmt + function call
    pkg/leaf.py     : {1, 2, 3} — def line, return (called at import!), module assignment
                                  Line 2 lives inside a function body but IS executed
                                  because compute() is called at import time from sub.py.
                                  Static AST analysis would miss it.
    """
    tc = TestClient()
    tc.save({
        "pkg/__init__.py": "from pkg.sub import RESULT\n",
        "pkg/sub.py": (
            "from pkg.leaf import compute\n"
            "RESULT = compute()\n"
        ),
        "pkg/leaf.py": (
            "def compute():\n"
            "    return 42\n"
            "LEAF_VALUE = 10\n"
        ),
        "test_pkg.py": (
            "def test_something():\n"
            "    from pkg import RESULT\n"
        ),
    })

    result = build_import_graph(tc.cwd, {"test_pkg.py": ["pkg"]})

    assert result == {
        "pkg": {
            "pkg/__init__.py": {1},
            "pkg/sub.py":      {1, 2},
            "pkg/leaf.py":     {1, 2, 3},
        }
    }
