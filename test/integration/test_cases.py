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


@pytest.mark.parametrize("case", collect_cases("pyfiles"), ids=os.path.basename)
def test_pyfiles(prepare_case, case):
    """Modifying a project configuration file must cause predict_tests to return
    None, signalling that all tests must run (impact prediction is not possible)."""
    case_folder, base_commit = prepare_case("pyfiles")
    run("git checkout -- .", cwd=case_folder)
    do_code_changes(case_folder, case)
    predicted_tests = predict_tests(case_folder, base_commit)
    assert predicted_tests is None
