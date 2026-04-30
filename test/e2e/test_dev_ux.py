import json
import os
import textwrap

import pytest

from test.e2e.client import TestClient
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


@pytest.mark.parametrize("user_location", [False, True])
def test_dev_ux_cmd(user_location):
    # Explicit commands
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    file_arg = "--covtest-file=mycvfile" if user_location else ""
    c.run(f"process . {file_arg}")
    assert "Processing coverage data" in c.out
    assert "Processing done" in c.out
    if user_location:
        assert not os.path.isdir(os.path.join(src_folder, ".covtest", commit))
        assert os.path.isfile(os.path.join(src_folder, "mycvfile"))
    else:
        assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    do_code_changes(src_folder, "mymath/fix_add")

    c.run(f"predict . {file_arg}")
    # Predicted files look ok
    assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.tests")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest @.covtest/covtests.tests")
    assert "1 passed in" in out  # Only 1 test!


@pytest.mark.parametrize("method", ["conftest", "plugin"])
def test_dev_ux_conf_test_files(method):
    # TODO: How to merge different file-open data from different
    #  contexts?
    src_folder = prepare_src_folder("files")
    c = TestClient(src_folder)
    if method == "conftest":
        conftest = textwrap.dedent("""\
            from covtest.pytest_plugin import patch_open
           """)
        c.save({"conftest.py": conftest})
    git_init_repo(src_folder)

    cmd_args = "-p covtest.pytest_plugin" if method == "plugin" else ""
    out, err = c.run_cmd(f"pytest --cov=. --cov-context=test {cmd_args}")
    assert "3 passed" in out
    file_open = c.load(".covtest/file_open")
    assert "cities.txt" in file_open

    c.run(f"process .")
    assert "Processing coverage data" in c.out
    assert "Processing done" in c.out

    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    do_code_changes(src_folder, "files/new_city")

    c.run(f"predict .")
    # Predicted files look ok
    assert "data_test.py::DataTest::test_cities" == c.load(".covtest/covtests.tests")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest @.covtest/covtests.tests", assert_error=True)
    assert "1 failed in" in out  # Only 1 test!


def test_dev_ux_split_testing():
    src_folder = prepare_src_folder("contexts")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    coveragerc = textwrap.dedent("""\
        [run]
        context = windows
        """)
    c.save({".coveragerc": coveragerc})
    out, err = c.run_cmd("pytest -m windows --cov=. --cov-context=test")
    assert "1 passed" in out

    # Check parsing the partial with contexts
    c.run(f"process . --covtest-file=mycvfile")
    content = c.load("mycvfile")
    content = json.loads(content)
    assert content["tests"] == ['windows|mymath_test.py::MyMathTest::test_add']
    c.rm("mycvfile")

    # So it is not removed by next pytest
    c.mv(".coverage", "tmp/.coverage.win")

    coveragerc = textwrap.dedent("""\
        [run]
        context = linux
        """)
    c.save({".coveragerc": coveragerc})
    out, err = c.run_cmd("pytest -m linux --cov=. --cov-append --cov-context=test")
    assert "1 passed" in out
    c.mv(".coverage", "tmp/.coverage.nix")

    with c.chdir("tmp"):
        out, err, c.run_cmd("coverage combine")

    c.mv("tmp/.coverage", ".coverage")
    c.run("process . ")
    assert "Processing coverage data" in c.out
    assert "Processing done" in c.out

    do_code_changes(src_folder, "contexts/fix_add_win")

    c.run(f"predict .")
    # Predicted files look ok
    assert "mymath_test.py::MyMathTest::test_add" == c.load(".covtest/covtests.windows.tests")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest @.covtest/covtests.windows.tests -m windows")
    assert "1 passed in" in out  # Only 1 test!

    out, err = c.run_cmd("pytest @.covtest/covtests.windows.tests -m linux", assert_error=True)
    assert "1 deselected in" in out


@pytest.mark.parametrize("method", ["conftest", "plugin"])
def test_dev_ux_plugin(method):
    # How a dev can run pytest easily via plugin
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    if method == "conftest":
        conftest = textwrap.dedent("""\
            from covtest.pytest_plugin import covtest_modifyitems
    
            def pytest_collection_modifyitems(session, config, items):
                return covtest_modifyitems(session, config, items)
        """)
        c.save({"conftest.py": conftest})
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    c.run(f"process .")
    assert "Processing coverage data" in c.out
    assert "Processing done" in c.out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    cmd_args = "-p covtest.pytest_plugin" if method == "plugin" else ""
    # Run optimized tests only predicted
    # Without changes, no tests to run
    out, err = c.run_cmd(f"pytest {cmd_args}", assert_error=True)
    assert "no tests ran" in out

    # Modify the add
    do_code_changes(src_folder, "mymath/fix_add")

    # Run optimized tests only predicted
    out, err = c.run_cmd(f"pytest {cmd_args}")
    assert "1 passed in" in out  # Only 1 test!


def test_dev_ux_full_plugin():
    # How a dev can run pytest easily via plugin
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test -p covtest.pytest_plugin")
    assert "2 passed" in out
    assert "Processing coverage data" in out
    assert "Processing done" in out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    # Run optimized tests only predicted
    # Without changes, no tests to run
    out, err = c.run_cmd("pytest -p covtest.pytest_plugin", assert_error=True)
    assert "no tests ran" in out

    # Modify the add
    do_code_changes(src_folder, "mymath/fix_add")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest -p covtest.pytest_plugin")
    assert "1 passed in" in out  # Only 1 test!
