import fnmatch
import json
import os
import subprocess
import time

import coverage

from covtest.covtest_data import CovTestData
from covtest.ast_parser import ParsedData
from covtest.diff import diff
from covtest.errors import CovTestException
from covtest.import_graph import get_all_sources_by_file, build_import_graph
from covtest.util.git import git_commits, git_diff, git_dirty
from covtest.output import out_verbose, out_info
from covtest.util.files import load, save

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


def extract_coverage(folder):
    """ Parse the .coverage DB to get the info we want
    which is a dict {file: {line: [pytest cov context]}}
    """
    out_info(f"Extracting coverage data from coverage DB: {folder}")
    file = os.path.join(folder, ".coverage")
    if not os.path.isfile(file):
        raise CovTestException(f"Coverage file {file} not found")
    cov = coverage.CoverageData(basename=file)
    cov.read()
    result = {}
    real_folder = os.path.realpath(folder)

    for f in cov.measured_files():
        real_f = os.path.realpath(f)
        # Skip files that are not physically inside the project folder.
        # This excludes stdlib, globally-installed packages, and any other
        # paths that happen to be measured but cannot be part of this project.
        if not real_f.startswith(real_folder + os.sep):
            continue
        rel = os.path.relpath(real_f, real_folder).replace("\\", "/")
        # Skip virtual-environment packages.  All venv layouts (Windows and
        # Unix) place installed packages under a directory named site-packages,
        # so this single check covers .venv/Lib/site-packages/ (Windows),
        # .venv/lib/python3.x/site-packages/ (Unix), and any custom venv name.
        if "site-packages" in rel:
            continue

        contexts = cov.contexts_by_lineno(f)
        clean_contexts = {}
        for line, context in sorted(contexts.items()):
            def _parse_context(c):
                parts = c.rsplit("|", 1)
                if len(parts) > 1:
                    return parts[0]
            clean = [_parse_context(c) for c in context]
            clean = [c for c in clean if c]
            clean_contexts[line] = set(clean)
        result[rel] = clean_contexts
    return result


def suite_to_run(covdata, diff_result, folder):
    """Compute which tests to run given the coverage snapshot and the diff result.

    diff_result: {filename: {"modified": [...], "deleted": [...], "inserted": {...}}}
      modified  — source-side line numbers of replacements
      deleted   — source-side line numbers of pure removals
      inserted  — dict mapping old-file positions to the count of lines inserted
                  after that position, e.g. {4: 3} means 3 lines after old line 4
    """
    data_files = covdata.data_files
    py_files = covdata.py_files
    scopes = covdata.scopes
    result = set()

    for filename, file_diff in diff_result.items():
        # Source-side changes: both replacements and deletions need their covering tests.
        source_lines = sorted(set(file_diff["modified"] + file_diff["deleted"]))
        inserted_lines = file_diff["inserted"]

        if data_files:
            tests = data_files.get(filename)
            if tests is not None:
                result.update(tests)
                continue

        m = py_files.get(filename)
        if m is None:
            out_verbose("FILE %s does not contain test data" % filename)
            continue

        # Tests covering the changed source lines
        for line in source_lines:
            tests = m.get(line, ())
            out_verbose(f"      {filename}:{line} => {tests}")
            for t in tests:
                if t:
                    result.add(t)

        # Inserted lines: find covering tests using old-file coordinates.
        # inserted_lines is {old_pos: count} — lines were inserted after old_pos.
        #
        # Algorithm:
        #   1. Find all scopes that contain old_pos (start <= old_pos <= end).
        #   2. Pick the innermost (smallest range).
        #   3. Collect tests from every line in that scope except the opening line
        #      (scope_start+1 .. scope_end).  Any test that exercised any part of
        #      that scope could be affected by code inserted into it.
        if inserted_lines:
            scope = scopes.get(filename)
            if scope is not None:
                for old_pos in sorted(inserted_lines):
                    # Scopes that strictly contain old_pos (end > old_pos) — this
                    # excludes scopes that END at old_pos, which means the
                    # insertion is exiting that scope, not inside it.
                    containing = [
                        (start, end)
                        for start, end in scope.items()
                        if start <= old_pos < end
                    ]
                    if not containing:
                        continue
                    # Innermost scope — smallest range
                    inner_start, inner_end = min(containing,
                                                  key=lambda s: s[1] - s[0])
                    # Lines after the insertion point up to the scope end.
                    # Tests covering those lines can actually reach the new code.
                    for line in range(old_pos + 1, inner_end + 1):
                        tests = m.get(line, ())
                        out_verbose(f"      {filename}:{line} (inserted scope) => {tests}")
                        result.update(t for t in tests if t)

        # New tests in test files that didn't exist in the snapshot
        # TODO: Better filtering of test files, in case some production code is named "test"
        if "test" in filename:
            parsed_tests = extract_tests(folder, filename)
            existing_tests = set()
            for v in m.values():
                existing_tests.update(v)
            for file_test in parsed_tests:
                if file_test not in existing_tests:
                    result.add(file_test)

    return result


def extract_tests(folder, filename):
    # Tests deduced by pytest
    out_verbose(f"Running pytest -co -q collection to gather tests from {folder}/{filename}")
    t = time.time()
    result = subprocess.run(["pytest", filename, "--collect-only", "-q"],
                            capture_output=True, text=True, cwd=folder)
    stdout = result.stdout
    file_tests = stdout.splitlines()
    idx = file_tests.index("") if "" in file_tests else len(file_tests)
    out_verbose(f"Extracted tests : {time.time() - t:5.1f}s  ({idx} tests found)")
    return file_tests[:idx]


def process(folder, covtest_file=None):
    """
    process the .coverage file and saves a .covtest
    it will keep the information already existing in .covtest
    from the data_files (captured while running the suite)
    :param folder: containing the .coverage file
    :param covtest_file: file with covtest information
    """
    t0 = time.time()

    out_info("extracting coverage data from .coverage DB")
    t = time.time()
    cov_data = extract_coverage(folder)
    out_info(f"extract coverage : {time.time() - t:5.1f}s  ({len(cov_data)} files)")

    out_info("parsing source files ...")
    t = time.time()
    parse_results = ParsedData(folder, cov_data.keys())
    out_info(f"parse sources    : {time.time() - t:5.1f}s  ({len(parse_results.files)} files)")

    out_info("tracing import-time lines ...")
    t = time.time()
    all_import_sources = get_all_sources_by_file(cov_data, parse_results, folder)
    import_time_lines = build_import_graph(folder, all_import_sources)
    out_info(f"trace imports    : {time.time() - t:5.1f}s  ({len(import_time_lines)} dotpaths traced)")

    opened_files = os.path.join(folder, ".covtest", "file_open")
    out_info("processing opened files")
    if os.path.exists(opened_files):
        opened_files = load(opened_files).splitlines()
        opened_files = [o.split("=") for o in opened_files]
        opened_files = [[t, os.path.relpath(os.path.realpath(f), os.path.realpath(folder))]
                        for (t, f) in opened_files]
    else:
        opened_files = None

    out_info("building coverage mappings ...")
    t = time.time()
    # TODO: incremental update of covtestdata
    cov_test_data = CovTestData.create(cov_data, parse_results, opened_files, import_time_lines)
    out_info(f"build mappings   : {time.time() - t:5.1f}s")
    out_info(f"Coverage covtest summary:\n{cov_test_data.summary()}")

    base_commit = git_commits(folder, 1)[0]
    if git_dirty(folder):  # In case it is dirty
        out_info(f"WARNING: Covtest not storing data because repo is dirty: {folder}")
        out_info(f"total            : {time.time() - t0:5.1f}s  (dirty repo, snapshot not saved)")
        return

    if covtest_file is None:
        covtest_file = os.path.join(folder, COVTEST_FOLDER, base_commit + ".covtest")
    covtest_file = os.path.abspath(covtest_file)

    out_info("saving snapshot ...")
    t = time.time()
    cov_test_data.save(covtest_file)
    out_info(f"save snapshot    : {time.time() - t:5.1f}s  ({covtest_file})")
    out_info(f"total            : {time.time() - t0:5.1f}s")


def get_base_commit(project_folder, cfg):
    """ obtain the base commit to diff against, checking in the local cache
    and retrieving from server if necessary
    """
    max_commits = cfg["max_commits"]
    cache_ttl = cfg["server_cache_ttl"]
    server_url = cfg.get("server_url")

    if not server_url:
        out_info("server not configured — skipping remote snapshot check")

    commits = git_commits(project_folder, max_commits)

    covtest_folder = project_folder / COVTEST_FOLDER
    not_found_path = os.path.join(covtest_folder, "server_not_found.json")
    not_found = json.loads(load(not_found_path)) if server_url and os.path.isfile(not_found_path) else {}
    now = time.time()

    result = None
    for gap, commit in enumerate(commits):
        local_file = covtest_folder / (commit + ".covtest")

        if os.path.exists(local_file):
            out_info(f"Covtest data found locally for commit {commit} ({gap} commit(s) back)")
            result = commit
            break

        if not server_url:
            continue

        cached_at = not_found.get(commit)
        if cached_at is not None and (now - cached_at) < cache_ttl:
            out_verbose(f"Skipping server check for {commit} (cached not-found, "
                        f"expires in {int(cache_ttl - (now - cached_at))}s)")
            continue

        out_info(f"Checking server for covtest data: commit {commit} ({gap} commit(s) back)")
        from covtest.remote import download
        downloaded = download(server_url, commit, covtest_folder, user=cfg.get("auth_user"),
                              password=cfg.get("auth_password"), token=cfg.get("auth_token"))
        if downloaded is not None:
            out_info(f"Downloaded covtest data for commit {commit} ({gap} commit(s) back)")
            result = commit
            break

        not_found[commit] = now

    if not result and not server_url:
        out_info("No covtest information found locally, but 'server_url' not defined\n"
                 "Remember to define 'server_url' in conf ('covtest config list') if covtest data"
                 "was computed in CI")
    # prune the not_found cache to 100
    not_found = dict(list(not_found.items())[-100:])
    save(not_found_path, json.dumps(not_found))
    return result


def predict_tests(project_folder, base_commit):
    """ get the stored coverage data in our DB,
    feeding the modified lines from git diff, will output the
    tests that need to be run
    """
    t0 = time.time()
    assert base_commit

    covtest_file = project_folder / COVTEST_FOLDER / (base_commit + ".covtest")
    out_verbose("loading snapshot ...")
    t = time.time()
    covdata = CovTestData.load(covtest_file)
    out_verbose(f"load snapshot    : {time.time() - t:5.1f}s  ({covtest_file})")

    out_verbose("computing git diff ...")
    t = time.time()
    text_diff = git_diff(project_folder, base_commit)
    out_verbose(f"git diff\n{text_diff}")
    diff_result = diff(text_diff)
    # Normalise path separators to match the coverage DB
    # TODO: Normalise paths more robustly
    diff_result = {f.replace("\\", "/"): data for f, data in diff_result.items()}
    out_verbose(f"Diff result\n{diff_result}")
    n_changed = sum(
        len(d["modified"]) + len(d["deleted"]) + len(d["inserted"])
        for d in diff_result.values()
    )
    out_verbose(f"compute diff     : {time.time() - t:5.1f}s  ({len(diff_result)} files, {n_changed} lines changed)")

    def _is_config_file(filepath):
        name = os.path.basename(filepath)
        return any(fnmatch.fnmatch(name, pat) for pat in _CONFIG_FILE_PATTERNS)

    config_files = [f for f in diff_result if _is_config_file(f)]
    if config_files:
        out_info(f"Pytest or project configuration files modified {config_files} — all tests must run")
        return None

    out_verbose("selecting tests ...")
    t = time.time()
    tests = suite_to_run(covdata, diff_result, project_folder)
    out_verbose(f"select tests     : {time.time() - t:5.1f}s  ({len(tests)} tests selected)")

    out_verbose(f"total            : {time.time() - t0:5.1f}s")
    return tests

