import logging

from covtest.config import read_server_url
from covtest.covtest import covtest_file_location, predict_tests, sync_covtest_data
from covtest.covtest_data import PartialData
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

    # Locate snapshot; keep base_commit for the partial save below
    base = covtest_file_location(str(case_folder))
    if base is None:
        out_info("no covtest data found — running all tests")
        return
    covtest_file, base_commit = base

    optimized_tests = predict_tests(str(case_folder), covtest_file, base_commit)
    if optimized_tests is None:
        out_info("configuration file changed — running all tests")
        return
    selected = [t for t in items if t.nodeid in optimized_tests]
    deselected = [t for t in items if t.nodeid not in optimized_tests]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
    out_info(f"selected {len(items)} test(s)")

    # Stash state for pytest_sessionfinish
    session._covtest_base_commit = base_commit
    session._covtest_selected = [t.nodeid for t in selected]


def pytest_sessionfinish(session, exitstatus):
    """Save partial snapshot so covtest merge can forward it to the next commit."""
    # Only the controller (or a plain non-distributed session) writes the
    # partial; workers must not write it or they race each other on disk.
    base_commit = getattr(session, "_covtest_base_commit", None)
    if base_commit is None:
        return  # prediction didn't run (no snapshot found or config-file change)

    case_folder = str(session.startpath)

    # Only save partial during active development (dirty working tree).
    # A clean tree means we are in a full-process CI run — skip.
    if not git_dirty(case_folder):
        return

    selected_tests = getattr(session, "_covtest_selected", [])

    PartialData(base_commit, selected_tests).save(case_folder)
    out_info("partial snapshot saved")
