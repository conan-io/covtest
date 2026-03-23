import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import textwrap
import time

from covtest.util.files import chdir, save, load
from covtest.util.run import run

logger = logging.getLogger(__name__)


def prepare_src_folder(folder):
    """ copy the assets "folder" date into a temporary testing folder
    :return: the temporary test folder
    """
    temp = tempfile.mkdtemp()
    cases_folder = os.path.realpath(os.path.join(os.path.dirname(__file__), "cases", folder))
    src = os.path.join(cases_folder, "src")
    dst = os.path.join(temp, "dst")
    shutil.copytree(src, dst)
    # Do not diff our file
    save(os.path.join(dst, ".gitignore"), ".coverage\n.covtest\n.covtest/*\n__pycache__\n.pytest_cache")
    return dst


def git_init_repo(folder):
    t = time.time()
    with chdir(folder):
        run("git init .")
        run("git add .")
        run("git commit -m initial")
    logger.debug(f"TIME: init_repo {time.time() - t}")


def do_code_changes(target, folder):
    """ copy the files from "folder" onto "target" and compute the diff
    """
    folder = os.path.realpath(os.path.join(os.path.dirname(__file__), "cases", folder))

    # FIXME: Not nested folders
    for f in os.listdir(folder):
        if f == "test.json":
            continue
        f = os.path.join(folder, str(f))
        shutil.copy(f, target)

    tests_def = json.loads(load(os.path.join(folder, "test.json")))
    return set(tests_def["tests"])


@contextlib.contextmanager
def environment_update(variables):
    if variables is None:
        yield
        return
    _environ = dict(os.environ)  # or os.environ.copy()
    try:
        os.environ.update(variables)
        yield
    finally:
        os.environ.clear()
        os.environ.update(_environ)


def run_pytest(folder, tests=None,  env=None, context=None):
    tests = tests or folder
    t = time.time()
    logger.debug("++++++ Launching pytest %s", tests)

    folder = folder.replace("\\", "/")
    context = f"--covtest-context={context}" if context else ""
    args = [tests, "-p covtest.pytest_plugin", "--log-cli-level=DEBUG",
            "-v", f'--cov={folder}', "--cov-context=test", context]
    with environment_update(env):
        result = subprocess.run("pytest %s" % " ".join(args), capture_output=True,
                                cwd=folder)
    stdout = result.stdout.decode()
    stderr = result.stderr.decode()

    logger.debug("\n" + textwrap.indent(stdout, "       "))
    if stderr:
        logger.debug("\n" + textwrap.indent(stderr, "       "))
    logger.debug("+++++++ Finalized pytest %s", tests)
    logger.debug(f"+++++++ TIME: run_pytest {time.time() - t}")
    return stdout, stderr
