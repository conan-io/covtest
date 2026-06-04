import mymodule  # pre-load at collection time (before any test context is active),
                 # so mymodule's module-level lines — including _compute()'s body —
                 # get NO direct test attribution in coverage.


def test_with_local_import():
    from mymodule import MODULE_DATA   # local import: this line IS covered by this test
    assert MODULE_DATA == "original"   # _compute() body (line 2) only reachable via
                                       # import-time tracing, not static AST


def test_without_local_import():
    assert 1 + 1 == 2
