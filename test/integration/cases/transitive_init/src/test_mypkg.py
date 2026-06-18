def test_first():
    # This test imports mypkg first.  helper.py:3 (compute body) runs at
    # mypkg.sub module-load time, so it is attributed to THIS test in coverage.
    # covtest correctly predicts test_first when helper.py changes.
    import mypkg
    assert mypkg.RESULT == 3


def test_leaf():
    # By the time this runs, mypkg is cached (imported by test_first above), so
    # helper.py:3 is NOT in this test's raw coverage.  The static projection
    # threads attribution through the re-export chain down to the Helper class
    # declaration, but cannot push it into compute()'s body: that body already
    # carries test_first (from test_first's import), so the empty-body scope-down
    # guard skips it, and there is no attribute/type tracking to know the value
    # flows specifically through compute.  Result: covtest misses test_leaf —
    # the false negative this case documents.
    from mypkg.leaf import LEAF_DATA
    assert LEAF_DATA == 3


def test_other():
    assert True
