import builtins
import logging
import os

import pytest

from covtest.covtest import covtest_postprocess, predict_tests

logger = logging.getLogger(__name__)


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
    print("covtest context", context)
    optimized_tests = predict_tests(case_folder, context)
    if optimized_tests is None:
        print("covtest test prediction returned None, not filtering")
        return

    print(f"Filtered tests to run:\n{optimized_tests}")
    items[:] = [t for t in items if t.nodeid in optimized_tests]


def pytest_sessionfinish(session, exitstatus):
    case_folder = session.startpath
    covtest_postprocess(case_folder)
