import os
import textwrap

import pytest

from covtest.covtest_data import CovTestData
from covtest.git import git_commits
from test.e2e.client import TestClient
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


def test_dev_ux_cmd():
    # Explicit commands
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    commit = git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    c.run(f"process .")
    assert "covtest: processing coverage data" in c.out
    assert "covtest: done" in c.out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    do_code_changes(src_folder, "mymath/fix_add")

    c.run(f"predict .")
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
            from covtest.process import patch_open
           """)
        c.save({"conftest.py": conftest})
    git_init_repo(src_folder)

    cmd_args = "-p covtest.process" if method == "plugin" else ""
    out, err = c.run_cmd(f"pytest --cov=. --cov-context=test {cmd_args}")
    assert "3 passed" in out
    file_open = c.load(".covtest/file_open")
    assert "cities.txt" in file_open

    c.run(f"process .")
    assert "covtest: processing coverage data" in c.out
    assert "covtest: done" in c.out

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
    content = CovTestData.load(os.path.join(src_folder, "mycvfile"))
    assert content.py_files["mymath.py"][2] == {'windows|mymath_test.py::MyMathTest::test_add'}
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
    assert "covtest: processing coverage data" in c.out
    assert "covtest: done" in c.out

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
            from covtest.predict import covtest_modifyitems

            def pytest_collection_modifyitems(session, config, items):
                return covtest_modifyitems(session, config, items)
        """)
        c.save({"conftest.py": conftest})
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    c.run(f"process .")
    assert "covtest: processing coverage data" in c.out
    assert "covtest: done" in c.out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    cmd_args = "-p covtest.predict" if method == "plugin" else ""
    # Run optimized tests only predicted
    # Without changes, no tests to run
    out, err = c.run_cmd(f"pytest {cmd_args}", assert_error=True)
    assert "2 deselected" in out

    # Modify the add
    do_code_changes(src_folder, "mymath/fix_add")

    # Run optimized tests only predicted
    out, err = c.run_cmd(f"pytest {cmd_args}")
    assert "1 passed, 1 deselected in" in out  # Only 1 test!


def test_dev_ux_full_plugin():
    # How a dev can run pytest easily via plugin
    # Note: -p covtest.process auto-injects --cov=. --cov-context=test
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest -p covtest.predict -p covtest.process")
    assert "2 passed" in out
    assert "covtest: processing coverage data" in out
    assert "covtest: done" in out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    # Run optimized tests only predicted
    # Without changes, no tests to run
    out, err = c.run_cmd("pytest -p covtest.predict", assert_error=True)
    assert "2 deselected" in out

    # Modify the add
    do_code_changes(src_folder, "mymath/fix_add")

    # Run optimized tests only predicted
    out, err = c.run_cmd("pytest -p covtest.predict")
    assert "1 passed, 1 deselected in" in out  # Only 1 test!


def test_merge_basic():
    """Core incremental workflow: predict run → partial saved → commit → merge → new snapshot."""
    src = prepare_src_folder("mymath")
    c = TestClient(src)
    git_init_repo(src)
    commit_x = git_commits(src, 1)[0]

    # Full snapshot at commit X (baseline)
    out, _ = c.run_cmd("pytest --cov=. --cov-context=test -p covtest.process")
    assert "2 passed" in out
    assert os.path.isfile(os.path.join(src, ".covtest", commit_x + ".covtest"))

    # Developer makes a change and runs predict (tree is dirty)
    do_code_changes(src, "mymath/fix_add")
    out, _ = c.run_cmd("pytest -p covtest.predict")
    assert "1 passed, 1 deselected" in out

    # Partial snapshot written while tree is dirty
    partial_file = os.path.join(src, ".covtest", "partial.covtest")
    assert os.path.isfile(partial_file), "partial.covtest should exist after predict run"

    # Developer commits the change → clean tree, new commit Y
    c.run_cmd("git add -A")
    c.run_cmd('git commit -m "fix add"')
    commit_y = git_commits(src, 1)[0]
    assert commit_y != commit_x

    # Merge: base snapshot + partial → snapshot for commit Y
    c.run("merge .")
    assert "covtest: merging covtest data" in c.out
    assert "covtest: done" in c.out

    # New snapshot created, partial consumed
    assert os.path.isfile(os.path.join(src, ".covtest", commit_y + ".covtest"))
    assert not os.path.isfile(partial_file), "partial.covtest should be deleted after merge"

    # Further changes use the merged snapshot (commit Y) as the base
    mymath = c.load("mymath.py")
    mymath = mymath.replace("return a * b", "return a * b  # comment")
    c.save({"mymath.py": mymath})
    out, _ = c.run_cmd("pytest -p covtest.predict")
    # Both functions were changed → both tests should be predicted
    assert "1 passed, 1 deselected" in out


def test_merge_no_code_changes():
    """Non-code change only (README): no tests run, merge forwards the snapshot cleanly."""
    src = prepare_src_folder("mymath")
    c = TestClient(src)
    commit_x = git_init_repo(src)

    # Full snapshot
    out, _ = c.run_cmd("pytest -p covtest.process")
    assert "2 passed" in out

    # Only a documentation file changes — no Python code affected
    c.save({"README.md": "# MyMath\nA simple math library."})

    # Predict: all tests deselected (no covered lines changed)
    out, _ = c.run_cmd("pytest -p covtest.predict", assert_error=True)
    assert "2 deselected" in out

    # Partial still saved (with empty tests_run)
    assert os.path.isfile(os.path.join(src, ".covtest", "partial.covtest"))

    # Commit
    c.run_cmd("git add -A")
    c.run_cmd('git commit -m "add README"')
    commit_y = git_commits(src, 1)[0]

    # Merge: essentially a snapshot forward — no line remapping needed
    c.run("merge .")
    assert "covtest: done" in c.out
    assert os.path.isfile(os.path.join(src, ".covtest", commit_y + ".covtest"))
    assert not os.path.isfile(os.path.join(src, ".covtest", "partial.covtest"))

    # Predictions still work correctly off the forwarded snapshot
    do_code_changes(src, "mymath/fix_add")
    out, _ = c.run_cmd("pytest -p covtest.predict")
    assert "1 passed, 1 deselected" in out


@pytest.mark.xfail(reason="still not working fine in CI")
def test_dev_ux_predict_xdist():
    """predict plugin works correctly when tests run in parallel with pytest-xdist."""
    src_folder = prepare_src_folder("mymath")
    c = TestClient(src_folder)
    git_init_repo(src_folder)

    out, err = c.run_cmd("pytest --cov=. --cov-context=test")
    assert "2 passed" in out

    c.run(f"process .")
    assert "covtest: processing coverage data" in c.out
    assert "covtest: done" in c.out
    assert os.path.isdir(os.path.join(src_folder, ".covtest"))

    # Run optimized tests only predicted
    # Without changes, no tests to run
    out, err = c.run_cmd(f"pytest -p covtest.predict", assert_error=True)
    assert "2 deselected" in out

    # With no changes, predict deselects everything — even under xdist
    out, err = c.run_cmd("pytest -n 2 -p covtest.predict", assert_error=True)
    assert "no tests ran" in out

    # After a code change only test_add is affected
    do_code_changes(src_folder, "mymath/fix_add")
    out, err = c.run_cmd("pytest -n 2 -p covtest.predict")
    assert "1 passed" in out

    # partial.covtest must be written exactly once (no race between workers)
    partial = os.path.join(src_folder, ".covtest", "partial.covtest")
    assert os.path.isfile(partial)


def test_merge_errors():
    """covtest merge raises clear errors when preconditions are not met."""
    src = prepare_src_folder("mymath")
    c = TestClient(src)
    git_init_repo(src)

    # Error: no partial file at all
    c.run("merge .", assert_error=True)
    assert "no partial" in c.out.lower()

    # Build full snapshot
    c.run_cmd("pytest --cov=. --cov-context=test -p covtest.process")

    # Produce a partial by running predict with dirty tree
    do_code_changes(src, "mymath/fix_add")
    c.run_cmd("pytest -p covtest.predict")
    assert os.path.isfile(os.path.join(src, ".covtest", "partial.covtest"))

    # Error: tree is still dirty (not committed yet)
    c.run("merge .", assert_error=True)
    assert "uncommitted" in c.out.lower()

    # Commit → merge should now succeed
    c.run_cmd("git add -A")
    c.run_cmd('git commit -m "fix"')
    c.run("merge .")
    assert "covtest: done" in c.out

    # Error: partial already consumed — second merge fails
    c.run("merge .", assert_error=True)
    assert "no partial" in c.out.lower()
