import pytest

from covtest.cli import _split_context_test


@pytest.mark.parametrize("t, expected", [
    # plain test, no context, no params
    ("test_file.py::test_func",
     (None, "test_file.py::test_func")),
    # plain test with params that contain |
    ("test_file.py::test_func[a | b]",
     (None, "test_file.py::test_func[a | b]")),
    # context + plain test
    ("windows|test_file.py::test_func",
     ("windows", "test_file.py::test_func")),
    # context + test whose params contain |  (the fragile case)
    ("windows|test_file.py::test_func[a | b]",
     ("windows", "test_file.py::test_func[a | b]")),
    # context + test with multiple | inside params
    ("linux|test_file.py::Test::test_x[foo | bar || baz]",
     ("linux", "test_file.py::Test::test_x[foo | bar || baz]")),
])
def test_split_context_test(t, expected):
    assert _split_context_test(t) == expected
