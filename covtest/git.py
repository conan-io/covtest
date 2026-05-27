import logging

from covtest.util.files import chdir
from covtest.util.run import run

logger = logging.getLogger(__name__)


def git_commits(folder, n=1):
    try:
        with chdir(folder):
            stdout, _ = run(f'git rev-list HEAD -n {n}')
            return stdout.splitlines()
    except Exception as e:
        raise Exception("Unable to get git commit in '%s': %s" % (folder, str(e)))


def git_dirty(folder):
    with chdir(folder):
        status, stderr = run("git status -s")
    return bool(status.strip())


def git_diff(folder, base):
    with chdir(folder):
        # TODO: Define better the diff
        out, err = run(f'git diff {base}')
    return out
