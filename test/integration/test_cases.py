import logging
import os

import pytest

from covtest.covtest import predict_tests
from covtest.util.run import run
from test.integration.test_cases_utils import prepare_src_folder, do_code_changes, git_init_repo, \
    run_pytest

logger = logging.getLogger(__name__)


def collect_cases(group):
    """ collect all cases, those are folders containing a "src"
    """
    cases_folder = os.path.realpath(os.path.join(os.path.dirname(__file__), "cases", group))
    cases_folder = str(cases_folder)  # to avoid warning because of bytes
    cases = []
    for root, dirs, files in os.walk(cases_folder):
        if "src" in dirs:
            cases.extend(os.path.join(root, d).replace("\\", "/") for d in dirs if d != "src")
    return cases


@pytest.fixture(scope="module")
def prepare_case():
    cached = {}

    def case_generator(group):
        try:
            return cached[group]
        except KeyError:
            pass
        case_folder = prepare_src_folder(group)  # copy files to a temporary test folder
        base_commit = git_init_repo(case_folder)  # git init

        logger.debug(f"\n\n\n---- RUNNING PYTEST FOR THE FIRST TIME -----------")
        # This does everything, run pytest with covtest plugin, parse code, stores DB
        run_pytest(case_folder)

        cached[group] = case_folder, base_commit
        return case_folder, base_commit

    return case_generator


def change_and_predict(case, case_folder, base_commit):
    logger.debug(f"\n\n\n---- DOING CODE CHANGES -----------")
    run("git checkout -- .", cwd=case_folder)
    expected_tests = do_code_changes(case_folder, case)

    logger.debug(f"\n\n\n---- PREDICT TESTS -----------")
    predicted_tests = predict_tests(case_folder, base_commit)
    logger.debug(f"Predicted tests: {predicted_tests}")
    assert predicted_tests == expected_tests


@pytest.mark.parametrize("case", collect_cases("mymath"), ids=os.path.basename)
def test_mymath(prepare_case, case):
    """ test basic cases
    """
    case_folder, base_commit = prepare_case("mymath")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("structs"), ids=os.path.basename)
def test_structs(prepare_case, case):
    """ test advanced cases
    """
    case_folder, base_commit = prepare_case("structs")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("files"), ids=os.path.basename)
def test_files(prepare_case, case):
    """ tests that file assests included in the test suite also fire tests if modified
    """
    case_folder, base_commit = prepare_case("files")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("globals"), ids=os.path.basename)
def test_globals(prepare_case, case):
    """ tests using global methods and variables
    """
    case_folder, base_commit = prepare_case("globals")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("imports"), ids=os.path.basename)
def test_imports(prepare_case, case):
    """ Test with imports over files
    """
    case_folder, base_commit = prepare_case("imports")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("contexts"), ids=os.path.basename)
def test_contexts(case):
    """
    """
    pass


@pytest.mark.parametrize("case", collect_cases("insert_scope"), ids=os.path.basename)
def test_insert_scope(prepare_case, case):
    """Inserted lines pick tests via same-indentation heuristic, not the whole enclosing scope."""
    case_folder, base_commit = prepare_case("insert_scope")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("local_imports"), ids=os.path.basename)
def test_local_imports(prepare_case, case):
    """A test with a local (function-body) import must be predicted when the imported
    module changes at a line that is never directly called — only reachable via
    import-time tracing, not direct line coverage."""
    case_folder, base_commit = prepare_case("local_imports")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("ancestor_chain"), ids=os.path.basename)
def test_ancestor_chain(prepare_case, case):
    """A test that imports a deep leaf module (mypkg.quantum.state) must be predicted
    when a function called by the top-level package __init__.py (mypkg.util.compute)
    is mutated — even though state.py has no import from mypkg and the mypkg lines
    carry no direct test attribution (covered at collection time via module-level import).

    The static projection (covtest/ast_mappings.py:project_imports) handles this:
    the local import of 'mypkg.quantum.state' projects test_state onto the
    import-time lines of each ancestor package — including mypkg/__init__.py's
    'VALUE = compute(1, 2)'.  From there the within-file passes flow it through
    'from .util import compute' to util.py's compute declaration, and scope-down
    fills the (otherwise empty) compute body line — attributing util.py:2 to
    test_state.  No module is imported at analysis time."""
    case_folder, base_commit = prepare_case("ancestor_chain")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("transitive_init"), ids=os.path.basename)
def test_transitive_init(prepare_case, case):
    """A test with a local import of a leaf module must be predicted when a utility
    function called by the parent package's __init__.py (at import time) is mutated.

    This exercises the transitive-init chain:
        test imports mypkg.leaf
        → mypkg/__init__.py re-exports RESULT from mypkg.sub
        → mypkg/sub.py computes RESULT = Helper().compute(1, 2) at import time
        → Helper.compute lives in mypkg/helper.py  ← mutation target

    The static projection threads attribution through the re-export chain down to
    the Helper class declaration, but cannot reach compute()'s body: that body is
    already attributed to test_first (it ran during test_first's import), so the
    empty-body scope-down guard skips it, and there is no attribute/type tracking
    to know the value flows specifically through compute.  This test documents that
    remaining false negative (only test_first is predicted)."""
    case_folder, base_commit = prepare_case("transitive_init")
    change_and_predict(case, case_folder, base_commit)


@pytest.mark.parametrize("case", collect_cases("pyfiles"), ids=os.path.basename)
def test_pyfiles(prepare_case, case):
    """Modifying a project configuration file must cause predict_tests to return
    None, signalling that all tests must run (impact prediction is not possible)."""
    case_folder, base_commit = prepare_case("pyfiles")
    run("git checkout -- .", cwd=case_folder)
    do_code_changes(case_folder, case)
    predicted_tests = predict_tests(case_folder, base_commit)
    assert predicted_tests is None
