from mymath import process


def test_negative():
    assert process(-1) == 0


def test_positive():
    assert process(1) == 2
