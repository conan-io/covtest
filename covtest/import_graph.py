"""Import-time line tracing for covtest.

For each source-module dotpath that appears as an import source in test files,
this module computes which lines are executed when that module is imported from
scratch (clean sys.modules).  The result is used by CovTestData._extend_mappings
to project test coverage through import chains that are invisible to direct
line-coverage tracking (because Python caches modules in sys.modules).

Key design decisions
--------------------
* **In-process, no subprocess**: imports are performed in the current interpreter
  using importlib.  This avoids subprocess-spawn overhead.
* **Module-level closure cache**: once a dotpath has been traced, the result is
  reused for every subsequent test file that imports the same dotpath.  Total
  tracing work is O(unique import sources), not O(test files × imports per file).
* **sys.modules reset after each trace**: after tracing dotpath M we restore
  sys.modules to the pre-import state so the next trace starts fresh.
* **sys.settrace integration**: a lightweight line tracer records every (file, lineno)
  pair executed during the import, giving exact import-time line sets.
* **Graceful failure**: import errors (missing deps, syntax errors, pytest fixtures
  required at collection time, …) are silently skipped.
"""

import importlib
import importlib.util
import os
import sys
from collections import defaultdict

from covtest.output import out_verbose, out_info


def build_import_graph(folder, import_sources_by_file):
    """Compute import-time line coverage for every dotpath found in test files.

    Parameters
    ----------
    folder : str
        Absolute path to the project root (used to relativise file paths and to
        filter out stdlib / site-packages lines).
    import_sources_by_file : dict[str, list[str]]
        {relative_file_path: [dotpath, …]} — collected from ParsedData for test
        files only.

    Returns
    -------
    dict[str, dict[str, set[int]]]
        {source_dotpath: {relative_file_path: set(lines)}}
        Empty dict for dotpaths whose import failed or produced no project lines.
    """
    folder = os.path.realpath(folder)

    # Deduplicate: collect every unique dotpath across all test files
    all_dotpaths = {
        dp
        for dotpaths in import_sources_by_file.values()
        for dp in dotpaths
    }

    out_info(f"tracing imports  : {len(all_dotpaths)} unique dotpaths from "
             f"{len(import_sources_by_file)} test files")

    closure_cache = {}  # dotpath → {rel_path: set(lines)}
    sys.path.insert(0, folder)
    try:
        for dotpath in sorted(all_dotpaths):
            _trace_module(dotpath, folder, closure_cache)
    finally:
        sys.path.remove(folder)

    return closure_cache


def _trace_module(dotpath, folder, closure_cache):
    """Trace one module import and cache the result.

    If *dotpath* is already in *closure_cache* this is a no-op.
    On return, ``closure_cache[dotpath]`` is set (possibly to ``{}`` on failure).
    """
    if dotpath in closure_cache:
        return

    # --- snapshot sys.modules so we can restore it afterwards -----------------
    modules_snapshot = dict(sys.modules)

    executed = defaultdict(set)  # abs_filename → {linenos}

    def _tracer(frame, event, _arg):
        if event == "line":
            executed[frame.f_code.co_filename].add(frame.f_lineno)
        return _tracer

    # --- run the import under our tracer --------------------------------------
    old_tracer = sys.gettrace()
    sys.settrace(_tracer)
    try:
        importlib.import_module(dotpath)
    except Exception as exc:
        out_verbose(f"import_graph: skipping '{dotpath}' — {type(exc).__name__}: {exc}")
    finally:
        sys.settrace(old_tracer)

    # --- convert abs paths → project-relative, filter to project files --------
    folder_prefix = folder + os.sep
    result = {}
    for abs_path, lines in executed.items():
        real_path = os.path.realpath(abs_path)
        if not real_path.startswith(folder_prefix):
            continue  # stdlib / site-packages / outside project
        rel = os.path.relpath(real_path, folder).replace("\\", "/")
        result[rel] = lines

    closure_cache[dotpath] = result

    # --- restore sys.modules --------------------------------------------------
    # Remove modules that were newly imported so the next trace starts fresh.
    for key in list(sys.modules):
        if key not in modules_snapshot:
            del sys.modules[key]
