import logging

from covtest.config import read_server_url
from covtest.covtest import predict_tests, sync_covtest_data

logger = logging.getLogger(__name__)


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
        print("covtest: configuration file changed — running all tests")
        return
    items[:] = [t for t in items if t.nodeid in optimized_tests]
