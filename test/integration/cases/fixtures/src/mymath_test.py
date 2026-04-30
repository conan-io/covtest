import pytest
from mymath import add, mult


@pytest.fixture
def my_value():
    return 10


def test_add(my_value):
    assert add(my_value, 1) == 11


def test_mult():
    assert mult(2, 3) == 6
