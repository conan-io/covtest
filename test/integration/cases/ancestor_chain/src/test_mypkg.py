import mypkg  # pre-load at collection time — mypkg lines get NO direct test
              # attribution (empty coverage context).  This is the key constraint:
              # when test_state runs, mypkg is already in sys.modules and
              # mypkg/__init__.py does NOT re-execute.  util.py:2 is invisible to
              # direct coverage for test_state.


def test_state():
    # STATE_VALUE is always 3, but mypkg.VALUE = compute(1, 2).
    # When compute is mutated (+ → -), mypkg.VALUE = -1 and this fails.
    # Covtest must predict test_state by tracing the ancestor "mypkg" and
    # projecting util.py:2 to this test through the ancestor chain.
    from mypkg.quantum.state import STATE_VALUE
    assert STATE_VALUE == mypkg.VALUE


def test_other():
    assert True
