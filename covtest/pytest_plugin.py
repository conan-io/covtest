import builtins
import logging
import os

import pytest

from covtest.config import read_server_url
from covtest.covtest import covtest_postprocess, predict_tests, sync_covtest_data
from covtest.git import git_dirty

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--covtest-process",
        action="store_true",
        default=False,
        help="Run covtest post-processing after the test session (requires a clean git commit)",
    )


@pytest.fixture(autouse=True)
def patch_open(request):
    # When the plugin is loaded, only track file opens when --covtest-process is
    # requested.  When patch_open is imported directly in a conftest.py the
    # option is not registered, so getoption raises ValueError — in that case
    # we treat it as always-active (the user opted in explicitly).
    try:
        do_process = request.config.getoption("--covtest-process")
    except ValueError:
        do_process = True  # option not registered: direct conftest import, always active
    if not do_process:
        yield
        return

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


def pytest_collection_modifyitems(session, config, items):
    return covtest_modifyitems(session, config, items)


def covtest_modifyitems(session, config, items):
    case_folder = session.startpath
    context = config.getoption("covtest_context", default=None)
    server_url = read_server_url(str(case_folder))
    if server_url and not context:
        sync_covtest_data(str(case_folder), server_url)
    optimized_tests = predict_tests(case_folder, context)
    if optimized_tests == -1:
        logger.info("No covtest base folder found, cannot filter, "
                    "make sure to run 'process' first to collect"
                    " information from coverage data")
        return
    if optimized_tests is None:
        print("covtest test prediction returned None, not filtering")
        return

    items[:] = [t for t in items if t.nodeid in optimized_tests]


def pytest_sessionfinish(session, exitstatus):
    case_folder = str(session.startpath)
    if not session.config.getoption("--covtest-process", default=False):
        return
    if git_dirty(case_folder):
        print("\ncovtest: --covtest-process requested but the working tree has uncommitted changes"
              " — snapshot not saved")
        return
    print("\nProcessing coverage data")
    covtest_postprocess(case_folder)
    print("Processing done")
