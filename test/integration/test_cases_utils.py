import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
import textwrap
import time

from covtest.util.files import chdir, save
from covtest.util.run import run

logger = logging.getLogger(__name__)


def prepare_folder(folder):
    """ copy the assets "folder" date into a temporary testing folder
    :return: the temporary test folder
    """
    temp = tempfile.mkdtemp()
    folder = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", folder))
    dst = os.path.join(temp, "dst")
    shutil.copytree(folder, dst)
    # Do not diff our file
    save(os.path.join(dst, ".gitignore"), "test.json\n.coverage\n.covtest\n.covtest/*\n__pycache__")
    return dst


def init_repo(folder):
    t = time.time()
    with chdir(folder):
        run("git init .")
        run("git add .")
        run("git commit -m initial")
    logger.debug(f"TIME: init_repo {time.time() - t}")


def prepare_patch_diff(target, folder):
    """ copy the files from "folder" onto "target" and compute the diff
    """
    # FIXME: Not nested folders
    for f in os.listdir(folder):
        f = os.path.join(folder, str(f))
        shutil.copy(f, target)


def add_noserc_plugin(folder):
    coveragerc = textwrap.dedent("""
        [nosetests]
        plugins=MyCovTestPlugin
    """)
    with open(os.path.join(folder, "setup.cfg"), "w") as f:
        f.write(coveragerc)


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


def validate_tests(context, stdout):
    passing = context["pass"]
    fail = context["fail"]
    for f in fail:
        assert f"{f} FAILED" in stdout, f
    for p in passing:
        assert f"{p} PASSED" in stdout, p

    if not fail and not passing:
        assert "no tests ran" in stdout
    else:
        if fail:
            assert f"{len(fail)} failed" in stdout
        if passing:
            assert f"{len(passing)} passed" in stdout
