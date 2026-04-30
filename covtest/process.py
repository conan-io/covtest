import builtins
import logging
import os

import pytest

from covtest.covtest import covtest_postprocess
from covtest.git import git_dirty
from covtest.output import out_info, set_verbose

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--covtest-verbose",
            action="store_true",
            default=False,
            help="Show covtest per-step timing output",
        )
    except ValueError:
        pass  # already registered by covtest.predict when both plugins are loaded


@pytest.fixture(autouse=True)
def patch_open(request):
    context = request.config.getoption("covtest_context", default=None)
    filename = ".covtest/{}file_open".format(context or "")
    original_open = builtins.open
    f = os.path.join(os.getcwd(), filename)
    os.makedirs(os.path.dirname(f), exist_ok=True)

    def myopen(*args, **kwargs):
        original_open(f, "a").write(f"{request.node.nodeid}={args[0]}\n")
        return original_open(*args, **kwargs)

    try:
        builtins.open = myopen
        yield
    finally:
        builtins.open = original_open


def pytest_sessionfinish(session, exitstatus):
    set_verbose(session.config.getoption("--covtest-verbose", default=False))
    case_folder = str(session.startpath)
    if git_dirty(case_folder):
        out_info("working tree has uncommitted changes — snapshot not saved")
        return
    out_info("processing coverage data")
    covtest_postprocess(case_folder)
    out_info("done")
