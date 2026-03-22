import io
import logging


from covtest.cli import main
from covtest.git import git_diff
from covtest.util.run import run
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


def run_covtest(cmd):
    if isinstance(cmd, str):
        cmd = cmd.split(" ")

    log_capture_string = io.StringIO()
    ch = logging.StreamHandler(log_capture_string)
    ch.setLevel(logging.INFO)

    result = main(cmd)

    return result, log_capture_string.getvalue()


def test_dev_ux():
    src_folder = prepare_src_folder("mymath")
    print(src_folder)
    git_init_repo(src_folder)

    out, err = run("pytest --cov=. --cov-context=test", cwd=src_folder)
    # print(out)
    assert "2 passed" in out
    # out, err = run("covtest process . ")
    _, out = run_covtest("process .")
    # assert "Processing coverage data" in out
    #assert "Processing done" in out
    print("----------------")
    print(out)
    print("+++++++++++++++++")

    do_code_changes(src_folder, "mymath/fix_add")

    out = git_diff(src_folder, ".")
    #print(out)
