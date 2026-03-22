import io
import logging


from covtest.cli import main
from covtest.git import git_diff
from covtest.util.run import run
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


def run_covtest(cmd):
    if isinstance(cmd, str):
        cmd = cmd.split(" ")

    # Get the ROOT logger (no name)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    root_logger.handlers = []
    root_logger.addHandler(handler)

    result = main(cmd)

    return result, log_buffer.getvalue()


def test_dev_ux():
    src_folder = prepare_src_folder("mymath")
    print(src_folder)
    git_init_repo(src_folder)

    out, err = run("pytest --cov=. --cov-context=test", cwd=src_folder)
    # print(out)
    assert "2 passed" in out

    _, out = run_covtest("process .")
    assert "Processing coverage data" in out
    assert "Processing done" in out

    do_code_changes(src_folder, "mymath/fix_add")

    out = git_diff(src_folder, ".")
    #print(out)
