import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

import nose
import coverage

from covtest.util.run import run
from covtest.nose_plugin import CovTestNosePlugin
from covtest.util.files import chdir, save

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
    save(os.path.join(dst, ".gitignore"), "test.json\n.coverage\n.covtest\n.covtest/*")
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


def run_nose(folder, tests=None, failing=0):

    os.chdir(folder)
    if tests:
        tests_path = " ".join(tests)
    else:
        tests_path = folder
    old_modules = list(sys.modules.keys())
    cov = coverage.Coverage(cover_pylib=False, source=[folder])
    cov.start()
    try:
        logger.debug("Launching nose %s", tests_path)

        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            plugin = CovTestNosePlugin(cov)
            result = nose.run(addplugins=[plugin], argv=[os.path.abspath(__file__), tests_path,
                                                         "--verbosity=3", "--nocapture"])
        plugin.save_opened_files(folder)
        stdout = stdout.getvalue()
        stderr = stderr.getvalue()
        # print("STD ", stdout, stderr)
        logger.debug("Launched nose %s", tests_path)
        if failing == 0:
            if not result:
                raise Exception("Unexpected error running nose: ", stdout, stderr)
        else:
            assert ("FAILED (failures=%s)" % failing) in stderr
            if result:
                raise Exception("Unexpected success running nose: ", stdout, stderr)
    finally:
        cov.stop()
        cov.save()
    added_modules = set(sys.modules).difference(old_modules)
    for added in added_modules:
        sys.modules.pop(added, None)
    return stdout, stderr


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


def run_pytest(folder, tests=None, collect_only=False, env=None, context=None):
    tests = tests or folder
    t = time.time()
    logger.debug("++++++ Launching pytest %s", tests)

    folder = folder.replace("\\", "/")
    context = f"--covtest-context={context}" if context else ""
    if collect_only:
        args = ["--co", "-q"]
    else:
        args = [tests, "-p covtest.pytest_plugin", "--log-cli-level=DEBUG",
                "-v", f'--cov={folder}', "--cov-context=test", context]
    with environment_update(env):
        result = subprocess.run("pytest %s" % " ".join(args), capture_output=True,
                                cwd=folder)
    stdout = result.stdout.decode()
    stderr = result.stderr.decode()

    logger.debug(textwrap.indent(stdout, "       "))
    if stderr:
        logger.debug(textwrap.indent(stderr, "       "))
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
