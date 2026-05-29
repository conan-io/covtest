import logging

from covtest.config import read_config
from covtest.covtest import predict_tests, get_base_commit
from covtest.covtest_data import PartialData
from covtest.git import git_dirty
from covtest.output import out_info, set_level, INFO, VERBOSE, DEBUG, TRACE

logger = logging.getLogger(__name__)


def _covtest_level(config):
    if config.getoption("--covtest-vvv", default=False):
        return TRACE
    if config.getoption("--covtest-vv", default=False):
        return DEBUG
    if config.getoption("--covtest-verbose", default=False):
        return VERBOSE
    return INFO


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--covtest-verbose",
            action="store_true",
            default=False,
            help="Show covtest timing/detail output (VERBOSE)",
        )
    except ValueError:
        pass
    try:
        parser.addoption(
            "--covtest-vv",
            action="store_true",
            default=False,
            help="Show covtest debug output (DEBUG)",
        )
    except ValueError:
        pass
    try:
        parser.addoption(
            "--covtest-vvv",
            action="store_true",
            default=False,
            help="Show covtest trace output (TRACE)",
        )
    except ValueError:
        pass


def pytest_collection_modifyitems(session, config, items):
    set_level(_covtest_level(config))
    return covtest_modifyitems(session, config, items)


def covtest_modifyitems(session, config, items):
    project_folder = session.config.rootpath
    context = config.getoption("covtest_context", default=None)
    out_info("predicting tests")

    cfg = read_config(project_folder)
    base_commit = get_base_commit(project_folder, cfg)
    if base_commit is None:
        out_info("no covtest data found — running all tests")
        return

    optimized_tests = predict_tests(project_folder, base_commit)
    if optimized_tests is None:
        out_info("configuration file changed — running all tests")
        return
    selected = [t for t in items if t.nodeid in optimized_tests]
    deselected = [t for t in items if t.nodeid not in optimized_tests]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
    out_info(f"selected {len(items)} test(s)")

    session._covtest_base_commit = base_commit
    session._covtest_selected = [t.nodeid for t in selected]


def pytest_sessionfinish(session, exitstatus):
    """Save partial snapshot so covtest merge can forward it to the next commit."""
    base_commit = getattr(session, "_covtest_base_commit", None)
    if base_commit is None:
        return

    case_folder = str(session.startpath)

    if not git_dirty(case_folder):
        return

    selected_tests = getattr(session, "_covtest_selected", [])

    PartialData(base_commit, selected_tests).save(case_folder)
    out_info("partial snapshot saved")
