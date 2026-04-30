import logging

from covtest.config import read_server_url
from covtest.covtest import predict_tests, sync_covtest_data
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
        pass  # already registered by covtest.process when both plugins are loaded


def pytest_collection_modifyitems(session, config, items):
    set_verbose(config.getoption("--covtest-verbose", default=False))
    return covtest_modifyitems(session, config, items)


def covtest_modifyitems(session, config, items):
    case_folder = session.startpath
    context = config.getoption("covtest_context", default=None)
    server_url = read_server_url(str(case_folder))
    if server_url and not context:
        sync_covtest_data(str(case_folder), server_url)
    out_info("predicting tests")
    optimized_tests = predict_tests(case_folder, context, tests=items)
    if optimized_tests == -1:
        out_info("no covtest data found — running all tests")
        return
    if optimized_tests is None:
        out_info("configuration file changed — running all tests")
        return
    selected = [t for t in items if t.nodeid in optimized_tests]
    deselected = [t for t in items if t.nodeid not in optimized_tests]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
    out_info(f"selected {len(items)} test(s)")
