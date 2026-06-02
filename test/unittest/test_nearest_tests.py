import pytest


def test_suite_to_run_nearest_not_applied_to_test_files():
    """_nearest_tests fallback must NOT fire for test files — new lines
    inside a test file should not inherit tests from neighbouring lines."""
    from covtest.covtest import suite_to_run
    from covtest.covtest_data import CovTestData

    # A minimal coverage map: line 3 has no entry (simulates a newly inserted line)
    py_files = {"mymath_test.py": {2: {"mymath_test.py::test_a"},
                                   5: {"mymath_test.py::test_b"}}}
    covdata = CovTestData(data_files=None, py_files=py_files)
    diff_result = {"mymath_test.py": {"modified": [], "deleted": [], "inserted": {2: 1}}}
    result = suite_to_run(covdata, diff_result, folder=".")
    assert result == set()
