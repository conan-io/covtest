"""Incremental snapshot merge — remap an existing snapshot to a new commit.

After a partial run (covtest predict + selective test execution), this module
merges the base snapshot forward to HEAD by:

  1. Loading the base snapshot (base_commit.covtest)
  2. Computing the diff from base_commit → HEAD
  3. Remapping every line number in py_files and scopes for modified files
  4. Dropping entries for deleted files
  5. Saving the result as HEAD_commit.covtest and deleting partial.covtest

Public API
----------
covtest_merge(folder)
    Entry point called by ``covtest merge``.
"""

import os
import time

from unidiff import PatchSet

from covtest.covtest import COVTEST_FOLDER
from covtest.covtest_data import CovTestData, PartialData
from covtest.errors import CovTestException
from covtest.output import out_verbose
from covtest.util.git import git_dirty, git_commits, git_diff


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
        removed = [line for line in hunk if line.is_removed]
        added = [line for line in hunk if line.is_added]

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
    5. Save HEAD_commit.covtest and delete partial.covtest
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
