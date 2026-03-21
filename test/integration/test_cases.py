import json
import logging
import os

import pytest

from covtest.covtest import covtest_preprocess
from covtest.util.files import load
from covtest.util.run import run
from test.integration.test_cases_utils import prepare_folder, prepare_patch_diff, init_repo, \
    run_pytest, validate_tests

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
        cases_folder = os.path.realpath(os.path.join(os.path.dirname(__file__), "cases", group))
        cases_folder = str(cases_folder)  # to avoid warning because of bytes
        src = os.path.join(cases_folder, "src")
        case_folder = prepare_folder(src)  # copy files to a temporary test folder
        init_repo(case_folder)  # git init

        logger.debug(f"\n\n\n---- RUNNING PYTEST FOR THE FIRST TIME -----------")
        # This does everything, run pytest with covtest plugin, parse code, stores DB
        run_pytest(case_folder)

        cached[group] = case_folder
        return case_folder

    return case_generator


def change_and_predict(case, case_folder):
    logger.debug(f"\n\n\n---- DOING CODE CHANGES -----------")
    run("git checkout -- .", cwd=case_folder)
    prepare_patch_diff(case_folder, case)

    logger.debug(f"\n\n\n---- PREDICT TESTS -----------")
    predicted_tests = covtest_preprocess(case_folder, None)
    logger.debug(f"Predicted tests: {predicted_tests}")
    tests_def = json.loads(load(os.path.join(case_folder, "test.json")))
    assert predicted_tests == set(tests_def["tests"])


@pytest.mark.parametrize("case", collect_cases("mymath"), ids=os.path.basename)
def test_mymath(prepare_case, case):
    """ test basic cases
    """
    case_folder = prepare_case("mymath")
    change_and_predict(case, case_folder)


@pytest.mark.parametrize("case", collect_cases("files"), ids=os.path.basename)
def test_files(prepare_case, case):
    """ tests that file assests included in the test suite also fire tests if modified
    """
    case_folder = prepare_case("files")
    change_and_predict(case, case_folder)


@pytest.mark.parametrize("case", collect_cases("globals"), ids=os.path.basename)
def test_globals(prepare_case, case):
    """ tests using global methods and variables
    """
    case_folder = prepare_case("globals")
    change_and_predict(case, case_folder)


@pytest.mark.parametrize("case", collect_cases("imports"), ids=os.path.basename)
def test_imports(prepare_case, case):
    """ Test with imports over files
    """
    case_folder = prepare_case("imports")
    change_and_predict(case, case_folder)


@pytest.mark.parametrize("case", collect_cases("contexts"), ids=os.path.basename)
def test_contexts(case):
    """
    """
    pass


def test_developer_changes():
    cases = collect_cases("mymath")
    src = os.path.join(os.path.dirname(cases[0]), "src")
    case_folder = prepare_folder(src)
    init_repo(case_folder)

    def _run_pytest():
        tests_def = json.loads(load(os.path.join(case_folder, "test.json")))
        tests_def = [tests_def] if not isinstance(tests_def, list) else tests_def
        for test_def in tests_def:
            context = test_def.get("name")
            stdout, _ = run_pytest(case_folder, env=test_def.get("env"), context=context)
            validate_tests(test_def, stdout)

    run_pytest(case_folder)

    for case in cases:
        logger.debug(f"CASE: {case}")
        prepare_patch_diff(case_folder, src)  # restore things
        prepare_patch_diff(case_folder, case)
        _run_pytest()


def _run_case(case):
    src = os.path.join(os.path.dirname(case), "src")
    case_folder = prepare_folder(src)  # copy files to a temporary test folder
    init_repo(case_folder)  # git init

    logger.debug(f"\n\n\n---- RUNNING PYTEST FOR THE FIRST TIME -----------")
    # This does everything, run pytest with covtest plugin, parse code, stores DB
    run_pytest(case_folder)

    logger.debug(f"\n\n\n---- DOING CODE CHANGES -----------")
    prepare_patch_diff(case_folder, case)

    logger.debug(f"\n\n\n---- PREDICT TESTS -----------")
    predicted_tests = covtest_preprocess(case_folder, None)
    logger.debug(f"Predicted tests: {predicted_tests}")
    tests_def = json.loads(load(os.path.join(case_folder, "test.json")))
    assert predicted_tests == set(tests_def["tests"])
