import fnmatch
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

# Sentinel returned by predict_tests when a project configuration file was
# modified.  The caller must run all tests — impact prediction is not possible.

# File name patterns whose modification forces a full test run.
_CONFIG_FILE_PATTERNS = (
    "requirements*.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pytest.ini",
    "tox.ini",
    ".coveragerc",
    "conftest.py",
)


def _is_config_file(filepath):
    """Return True when *filepath* is a project configuration file.

    Modifications to these files can affect the test environment or test
    collection in ways that are impossible to predict from coverage data alone.
    """
    name = os.path.basename(filepath)
    return any(fnmatch.fnmatch(name, pat) for pat in _CONFIG_FILE_PATTERNS)


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
        f = os.path.relpath(os.path.realpath(f), os.path.realpath(folder))
        result[f.replace("\\", "/")] = clean_contexts
    return result


def suite_to_run(covdata, modified, inserted, folder):
    """ compute which tests to run given the conandata and the
    modified files and lines
    """
    data_files = covdata.data_files
    py_files = covdata.py_files
    scopes = covdata.scopes
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
        # TODO: Better filtering of test files, in case some production code is named "test"
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

    for filename, inserted_lines in inserted.items():
        m = py_files.get(filename)
        if m is None:
            logger.debug("FILE %s does not contain test data" % filename)
            continue

        scope = scopes.get(filename)
        if scope is None:
            continue

        for line in inserted_lines:
            for s in range(line, 0, -1):
                max_line = scope.get(s)
                if max_line is not None and s < line <= max_line:
                    tests = m.get(s, ())
                    # Find the line in the scope
                    for t in tests:
                        if t:
                            result.add(t)
                    break
        # Now we need to check if modified lines are new tests
        # TODO: Repeated from above
        if "test" in filename:
            # TODO: do not repeat this
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
    result = subprocess.run(["pytest", filename, "--co", "-q"],
                            capture_output=True, text=True, cwd=folder)
    stdout = result.stdout
    file_tests = stdout.splitlines()
    idx = file_tests.index("") if "" in file_tests else len(file_tests)
    return file_tests[:idx]


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
    # print_data = {f: d for f, d in cov_data.items() if "rest_client_v2" in f}
    # print(f"Coverage results:\n{str_nested_dict(print_data)}")
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
        covtest_file = os.path.join(folder, COVTEST_FOLDER, base_commit + ".covtest")
    covtest_file = os.path.abspath(covtest_file)
    logger.info(f"Covtest storing data: {covtest_file}")
    cov_test_data.save(covtest_file)
    logger.debug(f"TIME: covtest_post_process {time.time() - t}")


_NOT_FOUND_CACHE_FILE = "server_not_found.json"


def _load_not_found_cache(base_folder):
    path = os.path.join(base_folder, _NOT_FOUND_CACHE_FILE)
    if os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_not_found_cache(base_folder, cache):
    path = os.path.join(base_folder, _NOT_FOUND_CACHE_FILE)
    os.makedirs(base_folder, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f)


def covtest_file_location(folder):
    from covtest.config import read_config
    max_commits = read_config(folder)["max_commits"]
    base_commits = git_commits(folder, max_commits)
    base_folder = os.path.join(folder, COVTEST_FOLDER)
    for base_commit in base_commits:
        covtest_file = os.path.join(base_folder, base_commit + ".covtest")
        if os.path.exists(covtest_file):
            logger.debug(f"Covtest using file: {covtest_file}")
            return covtest_file, base_commit
    logger.debug("Covtest couldn't find data for previous commits")


def sync_covtest_data(folder, server_url):
    """Download covtest data for the nearest base commit from server_url into
    the local .covtest folder, skipping commits that are already present.

    Commits not found on the server are recorded in a negative cache inside
    .covtest/ so repeated invocations skip them immediately.  Each cache entry
    expires after server_cache_ttl seconds (from covtest.ini, default 3600),
    after which the server is queried again.

    Returns (local_path, commit) on success, None if nothing was found.
    """
    from covtest.config import read_config
    from covtest.remote import download

    cfg = read_config(folder)
    max_commits = cfg["max_commits"]
    cache_ttl = cfg["server_cache_ttl"]

    base_commits = git_commits(folder, max_commits)
    base_folder = os.path.join(folder, COVTEST_FOLDER)

    not_found = _load_not_found_cache(base_folder)
    now = time.time()
    cache_modified = False

    # Prune entries for commits no longer in recent history
    active = set(base_commits)
    stale = [c for c in not_found if c not in active]
    if stale:
        for c in stale:
            del not_found[c]
        cache_modified = True

    for gap, base_commit in enumerate(base_commits):
        local_file = os.path.join(base_folder, base_commit + ".covtest")
        if os.path.exists(local_file):
            if gap:
                logger.info(f"Covtest data found locally for commit {base_commit} ({gap} commit(s) back)")
            else:
                logger.debug(f"Covtest data already present locally for {base_commit}")
            if cache_modified:
                _save_not_found_cache(base_folder, not_found)
            return local_file, base_commit

        cached_at = not_found.get(base_commit)
        if cached_at is not None and (now - cached_at) < cache_ttl:
            logger.debug(f"Skipping server check for {base_commit} (cached not-found, "
                         f"expires in {int(cache_ttl - (now - cached_at))}s)")
            continue

        logger.info(f"Checking server for covtest data: commit {base_commit} ({gap} commit(s) back)")
        downloaded = download(server_url, base_commit, base_folder)
        if downloaded is not None:
            logger.info(f"Downloaded covtest data for commit {base_commit} ({gap} commit(s) back)")
            if base_commit in not_found:
                del not_found[base_commit]
                cache_modified = True
            if cache_modified:
                _save_not_found_cache(base_folder, not_found)
            return downloaded, base_commit

        not_found[base_commit] = now
        cache_modified = True

    if cache_modified:
        _save_not_found_cache(base_folder, not_found)

    logger.info(f"Covtest data not found on server for the last {len(base_commits)} commit(s)")
    return None


def predict_tests(folder, covtest_file=None, base_diff=""):
    """ get the stored coverage data in our DB,
    feeding the modified lines from git diff, will output the
    tests that need to be run
    """
    if covtest_file is None:
        assert base_diff == ""
        # Looking for the covtest data file in the default locations
        # At the moment only local .covtest folder
        base = covtest_file_location(folder)
        if base is None:
            return -1
        covtest_file, base_diff = base

    covdata = CovTestData.load(covtest_file)

    logger.info("Computing current diff")
    text_diff = git_diff(folder, base_diff)
    logger.debug(f"git diff\n{text_diff}")
    modified_lines, inserted_lines = diff(text_diff)
    logger.debug(f"Modified lines\n{modified_lines}")
    # Make it absolute paths to match with the DB
    # TODO: Normalize paths
    modified_lines = {f.replace("\\", "/"): lines for f, lines in modified_lines.items()}
    inserted_lines = {f.replace("\\", "/"): lines for f, lines in inserted_lines.items()}

    config_files = [f for f in {**modified_lines, **inserted_lines}
                    if _is_config_file(f)]
    if config_files:
        logger.info(f"Pytest or project configuration files modified {config_files} — all tests must run")
        return None

    logger.info("Computing tests to run")
    tests = suite_to_run(covdata, modified_lines, inserted_lines, folder)
    logger.info(f"Tests to run: {tests}")
    return tests
