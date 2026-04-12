import json
import logging
import os
import subprocess
import time

import coverage

from covtest.covtest_data import CovTestData
from covtest.ast_parser import ParsedData
from covtest.diff import diff
from covtest.errors import CovTestException
from covtest.git import git_commits, git_diff, git_dirty
from covtest.util.files import load, chdir

logger = logging.getLogger(__name__)
COVTEST_FOLDER = ".covtest"


def str_nested_dict(files):
    result = []
    for f, contexts in files.items():
        result.append(f)
        read_lines = load(f).splitlines()
        if not read_lines:  # Completely empty file
            continue
        for line, tests in sorted(contexts.items()):
            result.append(f"   {line:<2}: {read_lines[line-1][:49]:<50} -> {tests}")
    return "\n".join(result)


def extract_coverage(folder):
    """ Parse the .coverage DB to get the info we want
    which is a dict {file: {line: [pytest cov context]}}
    """
    logger.info(f"Extracting coverage data from coverage DB: {folder}")
    file = os.path.join(folder, ".coverage")
    if not os.path.isfile(file):
        raise CovTestException(f"Coverage file {file} not found")
    cov = coverage.CoverageData()
    with chdir(folder):
        cov.read()
    result = {}

    for f in cov.measured_files():
        contexts = cov.contexts_by_lineno(f)
        # print(f, contexts)
        clean_contexts = {}  # for pytest
        for line, context in sorted(contexts.items()):
            def _parse_context(c):
                parts = c.rsplit("|", 1)
                if len(parts) > 1:
                    return parts[0]
            clean = [_parse_context(c) for c in context]
            clean = [c for c in clean if c]
            clean_contexts[line] = set(clean)
        f = os.path.relpath(f, folder)
        result[f.replace("\\", "/")] = clean_contexts
    return result


def suite_to_run(covdata, modified, folder):
    """ compute which tests to run given the conandata and the
    modified files and lines
    """
    data_files = covdata.data_files
    py_files = covdata.py_files
    result = set()
    for filename, modified_lines in modified.items():
        if data_files:
            tests = data_files.get(filename)
            if tests is not None:
                result.update(tests)
                continue
        m = py_files.get(filename)
        if m is None:
            logger.debug("FILE %s does not contain test data" % filename)
            continue
        for line in modified_lines:
            tests = m.get(line, ())
            logger.debug(f"      {filename}:{line} => {tests}")
            for t in tests:
                if t:
                    result.add(t)
        # Now we need to check if modified lines are new tests
        if "test" in filename:
            parsed_tests = extract_tests(folder, filename)
            # The previously existing tests run by this unit
            existing_tests = set()
            for v in m.values():
                existing_tests.update(v)
            # Tests that are new, not previously existing, need to be run
            for file_test in parsed_tests:
                if file_test not in existing_tests:
                    result.add(file_test)

    return result


def extract_tests(folder, filename):
    # Tests deduced by pytest
    result = subprocess.run(f"pytest {filename} --co -q",
                            capture_output=True, text=True, cwd=folder)
    stdout = result.stdout
    file_tests = stdout.splitlines()
    file_tests = file_tests[:file_tests.index("")]
    return file_tests


def covtest_postprocess(folder, covtest_file=None):
    """
    process the .coverage file and saves a .covtest
    it will keep the information already existing in .covtest
    from the data_files (captured while running the suite)
    :param folder: containing the .coverage file
    :param covtest_file: file with covtest information
    :return: None
    """
    t = time.time()
    cov_data = extract_coverage(folder)
    logger.debug(f"Coverage results:\n{str_nested_dict(cov_data)}")
    parse_results = ParsedData(folder)
    # logger.debug(f"Parse results mappings:\n{str_nested_dict(parse_results.line_mappings())}")
    last_failed_file = os.path.join(folder, ".pytest_cache", "v", "cache", "lastfailed")
    last_failed = None
    if os.path.exists(last_failed_file):
        last_failed = json.loads(load(last_failed_file))
        last_failed = [v for v in last_failed.keys()]

    opened_files = os.path.join(folder, ".covtest", "file_open")
    if os.path.exists(opened_files):
        opened_files = load(opened_files).splitlines()
        opened_files = [o.split("=") for o in opened_files]
        opened_files = [[t, os.path.relpath(f, folder)] for (t, f) in opened_files]
    else:
        opened_files = None

    # TODO: incremental update of covtestdata
    cov_test_data = CovTestData.create(cov_data, parse_results, last_failed, opened_files)
    logger.debug(f"Coverage after applied mappings\n{str_nested_dict(cov_test_data.py_files)}")

    base_commit = git_commits(folder, 1)[0]
    if git_dirty(folder):  # In case it is dirty
        logger.debug(f"Covtest not storing data because repo is dirty: {folder}")
        return

    if covtest_file is None:
        covtest_file = os.path.join(folder, COVTEST_FOLDER, base_commit)
    covtest_file = os.path.abspath(covtest_file)
    logger.info(f"Covtest storing data: {covtest_file}")
    cov_test_data.save(covtest_file)
    logger.debug(f"TIME: covtest_post_process {time.time() - t}")


def covtest_base_folder(folder):
    base_commits = git_commits(folder, 10)
    base_folder = os.path.join(folder, COVTEST_FOLDER)
    for base_commit in base_commits:
        covtest_folder = os.path.join(base_folder, base_commit)
        if os.path.exists(covtest_folder):
            logger.debug(f"Covtest using folder: {covtest_folder}")
            return covtest_folder, base_commit
    else:
        logger.debug("Covtest couldn't find data for previous commits")


def predict_tests(folder, covtest_file=None, base_diff=""):
    """ get the stored coverage data in our DB,
    feeding the modified lines from git diff, will output the
    tests that need to be run
    """
    if covtest_file is None:
        assert base_diff == ""
        # Looking for the covtest data file in the default locations
        # At the moment only local .covtest folder
        base = covtest_base_folder(folder)
        if base is None:
            logger.info("No covtest base folder found")
            return
        covtest_file, base_diff = base

    covdata = CovTestData.load(covtest_file)

    logger.info("Computing current diff")
    text_diff = git_diff(folder, base_diff)
    logger.debug(f"git diff\n{text_diff}")
    modified_lines = diff(text_diff)
    logger.debug(f"Modified lines\n{modified_lines}")
    # Make it absolute paths to match with the DB
    modified_lines = {f.replace("\\", "/"): lines for f, lines in modified_lines.items()}
    logger.info("Computing tests to run")
    tests = suite_to_run(covdata, modified_lines, folder)
    logger.info(f"Tests to run: {tests}")
    return tests
