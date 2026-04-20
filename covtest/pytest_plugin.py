import builtins
import logging
import os

import pytest

from covtest.covtest import covtest_postprocess, predict_tests, sync_covtest_data

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addini("covtest_server", help="URL of the covtest HTTP server", default=None)


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


def pytest_collection_modifyitems(session, config, items):
    return covtest_modifyitems(session, config, items)


def covtest_modifyitems(session, config, items):
    case_folder = session.startpath
    context = config.getoption("covtest_context", default=None)
    try:
        server_url = config.getini("covtest_server") or None
    except ValueError:
        server_url = None
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
    print("\nProcessing coverage data")
    covtest_postprocess(case_folder)
    print("Processing done")
