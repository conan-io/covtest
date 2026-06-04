def test_first():
    # This test imports mypkg first.  helper.py:3 (compute body) runs at
    # mypkg.sub module-load time, so it is attributed to THIS test in coverage.
    # covtest correctly predicts test_first when helper.py changes.
    import mypkg
    assert mypkg.RESULT == 3


def test_leaf():
    # By the time this runs, mypkg is cached (imported by test_first above).
    # mypkg.leaf is a NEW import here, so leaf.py executes with test_leaf context.
    # leaf.py:1  "from mypkg import RESULT"  →  raw_coverage test_leaf ✓
    # But the import tracing for "mypkg" only evicts mypkg itself (not mypkg.sub),
    # so sub.py never re-executes and helper.py:3 is NOT captured in the trace.
    # Result: covtest misses test_leaf  ←  the false negative this case documents.
    from mypkg.leaf import LEAF_DATA
    assert LEAF_DATA == 3


def test_other():
    assert True
