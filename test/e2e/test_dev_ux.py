import os

import pytest

from test.e2e.client import TestClient
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


@pytest.mark.parametrize("user_location", [False, True])
def test_dev_ux_cmd(user_location):
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    file_arg = "--covtest-file=mycvfile" if user_location else ""
    c.run(f"process . {file_arg}")
    assert "Processing coverage data" in c.out
    assert "Processing done" in c.out
    if user_location:
        assert not os.path.isdir(os.path.join(src_folder, ".covtest"))
    else:
        assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    do_code_changes(src_folder, "mymath/fix_add")

    c.run(f"predict . {file_arg}")
    # Predicted files look ok
    assert "mymath_test.py::MyMathTest::test_add" == c.load("covtests.tests")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest @covtests.tests")
    assert "1 passed in" in out  # Only 1 test!
