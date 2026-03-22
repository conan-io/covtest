from mymath import MyMath, some_math


class TestMyMath:
    def test_add(self):
        b = MyMath.add(2, 3)
        assert b == 5

    def test_mult(self):
        b = MyMath.mult(2, 3)
        assert b == 6


def test_license():
    m = MyMath()
    m.license()
    assert "Some license" in m.msg


def test_some_math():
    b = some_math(1, 2)
    assert b == 8
