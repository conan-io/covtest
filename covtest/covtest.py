import fnmatch
import json
import logging
import os
import subprocess
import time

import coverage
from unidiff import PatchSet

from covtest.covtest_data import CovTestData, PartialData
from covtest.ast_parser import ParsedData
from covtest.diff import diff
from covtest.errors import CovTestException
from covtest.git import git_commits, git_diff, git_dirty
from covtest.output import out_info, out_verbose
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
    out_verbose(f"Running pytest -co -q collection to gather tests from {folder}/{filename}")
    t = time.time()
    result = subprocess.run(["pytest", filename, "--collect-only", "-q"],
                            capture_output=True, text=True, cwd=folder)
    stdout = result.stdout
    file_tests = stdout.splitlines()
    idx = file_tests.index("") if "" in file_tests else len(file_tests)
    out_verbose(f"Extracted tests : {time.time() - t:5.1f}s  ({idx} tests found)")
    return file_tests[:idx]


def covtest_postprocess(folder, covtest_file=None):
    """
    process the .coverage file and saves a .covtest
    it will keep the information already existing in .covtest
    from the data_files (captured while running the suite)
    :param folder: containing the .coverage file
    :param covtest_file: file with covtest information
    """
    t0 = time.time()

    out_verbose("extracting coverage data ...")
    t = time.time()
    cov_data = extract_coverage(folder)
    logger.debug(f"Coverage results:\n{str_nested_dict(cov_data)}")
    out_verbose(f"extract coverage : {time.time() - t:5.1f}s  ({len(cov_data)} files)")

    out_verbose("parsing source files ...")
    t = time.time()
    parse_results = ParsedData(folder)
    out_verbose(f"parse sources    : {time.time() - t:5.1f}s  ({len(parse_results.files)} files)")

    last_failed_file = os.path.join(folder, ".pytest_cache", "v", "cache", "lastfailed")
    last_failed = None
    if os.path.exists(last_failed_file):
        last_failed = json.loads(load(last_failed_file))
        last_failed = [v for v in last_failed.keys()]

    opened_files = os.path.join(folder, ".covtest", "file_open")
    if os.path.exists(opened_files):
        opened_files = load(opened_files).splitlines()
        opened_files = [o.split("=") for o in opened_files]
        opened_files = [[t, os.path.relpath(os.path.realpath(f), os.path.realpath(folder))]
                        for (t, f) in opened_files]
    else:
        opened_files = None

    out_verbose("building coverage mappings ...")
    t = time.time()
    # TODO: incremental update of covtestdata
    cov_test_data = CovTestData.create(cov_data, parse_results, last_failed, opened_files)
    logger.debug(f"Coverage after applied mappings\n{str_nested_dict(cov_test_data.py_files)}")
    out_verbose(f"build mappings   : {time.time() - t:5.1f}s")

    base_commit = git_commits(folder, 1)[0]
    if git_dirty(folder):  # In case it is dirty
        logger.debug(f"Covtest not storing data because repo is dirty: {folder}")
        out_verbose(f"total            : {time.time() - t0:5.1f}s  (dirty repo, snapshot not saved)")
        return

    if covtest_file is None:
        covtest_file = os.path.join(folder, COVTEST_FOLDER, base_commit + ".covtest")
    covtest_file = os.path.abspath(covtest_file)

    out_verbose("saving snapshot ...")
    t = time.time()
    cov_test_data.save(covtest_file)
    out_verbose(f"save snapshot    : {time.time() - t:5.1f}s  ({covtest_file})")

    out_verbose(f"total            : {time.time() - t0:5.1f}s")


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


def predict_tests(folder, covtest_file=None, base_diff="", tests=None):
    """ get the stored coverage data in our DB,
    feeding the modified lines from git diff, will output the
    tests that need to be run
    """
    t0 = time.time()

    if covtest_file is None:
        assert base_diff == ""
        # Looking for the covtest data file in the default locations
        # At the moment only local .covtest folder
        base = covtest_file_location(folder)
        if base is None:
            return -1
        covtest_file, base_diff = base

    out_verbose("loading snapshot ...")
    t = time.time()
    covdata = CovTestData.load(covtest_file)
    out_verbose(f"load snapshot    : {time.time() - t:5.1f}s  ({covtest_file})")

    out_verbose("computing git diff ...")
    t = time.time()
    text_diff = git_diff(folder, base_diff)
    logger.debug(f"git diff\n{text_diff}")
    modified_lines, inserted_lines = diff(text_diff)
    logger.debug(f"Modified lines\n{modified_lines}")
    # Make it absolute paths to match with the DB
    # TODO: Normalize paths
    modified_lines = {f.replace("\\", "/"): lines for f, lines in modified_lines.items()}
    inserted_lines = {f.replace("\\", "/"): lines for f, lines in inserted_lines.items()}
    n_changed = sum(len(l) for l in modified_lines.values()) + sum(len(l) for l in inserted_lines.values())
    out_verbose(f"compute diff     : {time.time() - t:5.1f}s  ({len({**modified_lines, **inserted_lines})} files, {n_changed} lines changed)")

    config_files = [f for f in {**modified_lines, **inserted_lines}
                    if _is_config_file(f)]
    if config_files:
        logger.info(f"Pytest or project configuration files modified {config_files} — all tests must run")
        return None

    out_verbose("selecting tests ...")
    t = time.time()
    tests = suite_to_run(covdata, modified_lines, inserted_lines, folder)
    out_verbose(f"select tests     : {time.time() - t:5.1f}s  ({len(tests)} tests selected)")

    out_verbose(f"total            : {time.time() - t0:5.1f}s")
    return tests


# ---------------------------------------------------------------------------
# Incremental merge helpers
# ---------------------------------------------------------------------------

def _build_line_mapping(patched_file):
    """Return (explicit, final_offset) for one file's diff.

    explicit      — {source_lineno: target_lineno | None}  for every line
                    covered by the diff hunks (context + removed + inter-hunk
                    gaps).  None means the source line was truly deleted (no
                    corresponding added line).
    final_offset  — net offset to apply to source lines that come AFTER the
                    last hunk (i.e. not present in *explicit*).

    **Modification vs deletion**: within each hunk we pair removed lines with
    added lines in order.  A paired removal is a *modification* — the old
    source line maps to the new target line and its coverage data is
    preserved.  An unpaired removal is a *true deletion* — it maps to None
    and its coverage data is dropped.
    """
    explicit = {}
    offset = 0
    last_source_end = 1  # 1-indexed; tracks start of the next unprocessed gap

    for hunk in patched_file:
        # Lines in the gap before this hunk: shift by accumulated offset
        for lineno in range(last_source_end, hunk.source_start):
            explicit[lineno] = lineno + offset

        # Separate removed and added lines within this hunk
        removed = [l for l in hunk if l.is_removed]
        added = [l for l in hunk if l.is_added]

        # Context lines: exact source→target mapping
        for line in hunk:
            if line.is_context:
                explicit[line.source_line_no] = line.target_line_no

        # Pair removals with additions (in order).
        # Paired  → modification: remap to corresponding added line's position.
        # Unpaired → true deletion: mark as None (coverage data discarded).
        for i, rm in enumerate(removed):
            explicit[rm.source_line_no] = added[i].target_line_no if i < len(added) else None

        last_source_end = hunk.source_start + hunk.source_length
        offset += hunk.target_length - hunk.source_length

    return explicit, offset


def _remap_lineno(lineno, explicit, final_offset):
    """Map one source line number to its target equivalent (or None if deleted)."""
    if lineno in explicit:
        return explicit[lineno]
    return lineno + final_offset   # line is after all hunks


def _remap_lines(line_map, patched_file):
    """Remap a {source_lineno: tests} coverage dict to target line numbers."""
    explicit, offset = _build_line_mapping(patched_file)
    new_map = {}
    for old_lineno, tests in line_map.items():
        new_lineno = _remap_lineno(old_lineno, explicit, offset)
        if new_lineno is not None and tests:
            new_map[new_lineno] = tests
    return new_map


def _remap_scope(scope_map, patched_file):
    """Remap a {start_line: end_line} scope dict to target line numbers."""
    explicit, offset = _build_line_mapping(patched_file)
    new_scope = {}
    for start, end in scope_map.items():
        new_start = _remap_lineno(start, explicit, offset)
        new_end = _remap_lineno(end, explicit, offset)
        if new_start is not None and new_end is not None:
            new_scope[new_start] = new_end
    return new_scope


def covtest_merge(folder):
    """Merge the partial covtest snapshot with the base snapshot.

    Preconditions (all must hold — raises CovTestException otherwise):
    - Working tree is clean (already committed)
    - HEAD commit differs from the partial's base_commit
    - partial.covtest exists in .covtest/
    - <base_commit>.covtest exists in .covtest/

    Algorithm:
    1. Load base snapshot
    2. Compute diff base_commit → HEAD
    3. Remap line numbers in py_files / scopes for every modified file
    4. Drop entries for deleted files
    5. Apply last_failed from partial
    6. Save HEAD_commit.covtest and delete partial.covtest
    """
    # --- preconditions -------------------------------------------------------
    if git_dirty(folder):
        raise CovTestException(
            "working tree has uncommitted changes — commit first, then run 'covtest merge'"
        )

    if not PartialData.exists(folder):
        raise CovTestException(
            "no partial covtest data found — run 'pytest -p covtest.predict' first"
        )

    partial = PartialData.load(folder)

    head_commit = git_commits(folder, 1)[0]
    if head_commit == partial.base_commit:
        raise CovTestException(
            f"HEAD ({head_commit[:8]}) matches the base snapshot commit — no new commit to merge"
        )

    base_file = os.path.join(folder, COVTEST_FOLDER, partial.base_commit + ".covtest")
    if not os.path.exists(base_file):
        raise CovTestException(
            f"base snapshot not found: {base_file} — run 'covtest process' first"
        )

    # --- merge ---------------------------------------------------------------
    t0 = time.time()

    out_verbose("loading base snapshot ...")
    t = time.time()
    base = CovTestData.load(base_file)
    out_verbose(f"load snapshot    : {time.time() - t:5.1f}s")

    out_verbose("computing diff ...")
    t = time.time()
    text_diff = git_diff(folder, partial.base_commit)
    patch = PatchSet(str(text_diff))
    n_modified = len(patch.modified_files)
    n_removed = len(patch.removed_files)
    out_verbose(f"compute diff     : {time.time() - t:5.1f}s  "
                f"({n_modified} modified, {n_removed} removed)")

    out_verbose("remapping lines ...")
    t = time.time()
    new_py_files = dict(base.py_files)
    new_scopes = dict(base.scopes)
    new_data_files = dict(base.data_files)

    for pf in patch.modified_files:
        fp = pf.path.replace("\\", "/")
        if fp in base.py_files:
            new_py_files[fp] = _remap_lines(base.py_files[fp], pf)
        if fp in base.scopes:
            new_scopes[fp] = _remap_scope(base.scopes[fp], pf)

    for pf in patch.removed_files:
        fp = pf.path.replace("\\", "/")
        new_py_files.pop(fp, None)
        new_scopes.pop(fp, None)
        new_data_files.pop(fp, None)

    out_verbose(f"remap lines      : {time.time() - t:5.1f}s")

    merged = CovTestData(
        data_files=new_data_files,
        py_files=new_py_files,
        last_failed=partial.last_failed,
        scopes=new_scopes,
    )

    new_file = os.path.join(folder, COVTEST_FOLDER, head_commit + ".covtest")
    out_verbose("saving snapshot ...")
    t = time.time()
    merged.save(new_file)
    out_verbose(f"save snapshot    : {time.time() - t:5.1f}s  ({new_file})")
    out_verbose(f"total            : {time.time() - t0:5.1f}s")

    partial.delete(folder)
    return new_file
