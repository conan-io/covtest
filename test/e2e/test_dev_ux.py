from covtest.git import git_diff
from covtest.util.run import run
from test.integration.test_cases_utils import prepare_src_folder, git_init_repo, do_code_changes


def test_dev_ux():
    src_folder = prepare_src_folder("mymath")
    print(src_folder)
    git_init_repo(src_folder)

    out, err = run("pytest --cov=. --cov-context=test", cwd=src_folder)
    print(out)
    assert "2 passed" in out
    # out, err = run("covtest process . ")

    do_code_changes(src_folder, "mymath/fix_add")

    out = git_diff(src_folder, ".")
    print(out)
