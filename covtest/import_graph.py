"""Import-time line tracing for covtest.

For each source-module dotpath that appears as an import source in any covered
file, this module computes which lines execute when that module is imported
from scratch (clean sys.modules).  CovTestData._extend_mappings uses the result
to project test coverage through import chains that are invisible to direct
line-coverage tracking (because Python caches modules in sys.modules — only
the FIRST test that imports a given module sees its module-level lines).

Key design decisions
--------------------
* **In-process, no subprocess**: imports run in the current interpreter via
  importlib — no subprocess-spawn overhead.
* **Module-level closure cache**: each dotpath is traced once; the result is
  reused for every test that imports it.  Tracing cost is O(unique dotpaths),
  not O(test files × imports per file).
* **sys.modules restored after each trace**: so the next trace starts fresh.
* **sys.settrace line filter**: only events from files under ``folder`` are
  captured (stdlib/site-packages are dropped at trace time).
* **Two-stage eviction with retry**: Stage 1 evicts only the dotpath's subtree
  (cheap); Stage 2 (run only on Stage 1 failure) evicts the entire top-level
  package and re-imports it fresh — handles cached-state conflicts like
  RecursionError or class-layout errors that arise when re-importing a
  subpackage with stale references in cached parents.
"""

import importlib
import os
import sys
from collections import defaultdict

from covtest.output import out_verbose, out_info

# Sentinel used in the tracer's per-filename memoization cache: distinguishes
# "not yet checked" from "checked, not under project folder".  A plain
# dict.get() would conflate those two when the stored value is None/False.
_SENTINEL = object()


def get_all_sources_by_file(cov_data, parse_results, folder):
    # Include ALL project files (not just test files): source files like leaf.py
    # may import a package with a test-attributed line, which is exactly the
    # trigger the projection needs.  Only add a dotpath if at least one of its
    # declaration lines has direct test attribution — dotpaths whose lines are
    # only covered at collection time (empty test set) produce no projection.
    all_import_sources = {}
    for f in cov_data:
        if f not in parse_results.files:
            continue
        file_cov = cov_data[f]
        # Use local_import_sources (function-body imports only) so that only tests
        # which *directly execute* an import statement at run-time are projected
        # onto the imported module's lines.  Module-level imports run at collection
        # time and are often shared across many tests, leading to massive
        # over-prediction when the transitive import chain is large (e.g. any
        # Django test file that imports from django.db ends up attributing every
        # test to django.utils.translation.trans_real).
        for dotpath, decl_lines in parse_results.files[f].local_import_sources.items():
            if any(file_cov.get(line) for line in decl_lines):
                all_import_sources.setdefault(f, []).append(dotpath)
                # Also include every ancestor package so that the transitive
                # import chain (e.g. physics/__init__ → units → si.py) gets
                # traced even when only a deep leaf is imported directly.
                parts = dotpath.split(".")
                for i in range(1, len(parts)):
                    ancestor = ".".join(parts[:i])
                    if _is_project_dotpath(ancestor, folder):
                        all_import_sources.setdefault(f, []).append(ancestor)
    return all_import_sources


def build_import_graph(folder, import_sources_by_file):
    """Compute import-time line coverage for every dotpath found in test files.

    Parameters
    ----------
    folder : str
        Absolute path to the project root.  Used both to filter line events to
        only project files (anything under this folder) and to compute relative
        paths in the result.
    import_sources_by_file : dict[str, list[str]]
        {relative_file_path: [dotpath, …]} — collected from ParsedData.

    Returns
    -------
    dict[str, dict[str, set[int]]]
        {source_dotpath: {relative_file_path: set(lines)}}
        Empty dict for dotpaths whose import failed or produced no project lines.
    """
    folder = os.path.realpath(folder)
    # normcase folder once so the tracer's hot-path is just a startswith check.
    # This handles Windows case-insensitivity: frame.f_code.co_filename has the
    # case used by the loader (sys.path + .pth file + pip), which may differ
    # from the canonical case returned by realpath.
    folder_norm = os.path.normcase(folder) + os.sep

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
            _trace_module(dotpath, folder, folder_norm, closure_cache)
    finally:
        sys.path.remove(folder)

    # Summary: how many dotpaths captured at least one project line.  Useful for
    # spotting cases where a critical ancestor silently produced 0 lines (which
    # would invisibly cripple recall).
    n_with_lines = sum(1 for res in closure_cache.values() if res)
    out_info(f"import_graph: {n_with_lines}/{len(closure_cache)} dotpaths produced lines")

    return closure_cache


def _is_project_dotpath(dotpath, folder):
    """Return True if *dotpath* plausibly maps to a source file under *folder*.

    This pre-filter skips stdlib / site-packages dotpaths before we even touch
    sys.modules, avoiding both the eviction cost and the settrace overhead.
    """
    parts = dotpath.replace(".", os.sep)
    return (os.path.isfile(os.path.join(folder, parts + ".py")) or
            os.path.isfile(os.path.join(folder, parts, "__init__.py")))


def _trace_module(dotpath, folder, folder_norm, closure_cache):
    """Trace one module import and cache the result.

    If *dotpath* is already in *closure_cache* this is a no-op.
    On return, ``closure_cache[dotpath]`` is set (possibly to ``{}`` on failure).

    Strategy
    --------
    Two-stage attempt with progressively broader eviction:

    1. **Stage 1 — local eviction**: evict ``dotpath`` and its subtree.  This
       handles the common case where re-importing the package alone is enough.
       Cheap (only a few modules re-run).

    2. **Stage 2 — full top-level eviction**: if Stage 1 raises an exception
       or captures zero lines, retry by also evicting the entire top-level
       package subtree (e.g. evict all of ``sympy.*`` for a ``sympy.physics``
       trace).  This bypasses cached-state conflicts (RecursionError, TypeError
       on class layout, etc.) at the cost of re-importing the whole top-level
       package from scratch — slow but correct.  The result is memoized so
       the cost is paid only once per dotpath.
    """
    if dotpath in closure_cache:
        return

    # Pre-filter: if dotpath has no corresponding source file under folder,
    # it is a stdlib / site-packages module whose lines we can never project.
    if not _is_project_dotpath(dotpath, folder):
        closure_cache[dotpath] = {}
        return

    # --- Stage 1: local eviction (cheap) --------------------------------------
    result = _attempt_trace(
        dotpath, folder, folder_norm,
        evict_keys={dotpath} | {k for k in sys.modules if k.startswith(dotpath + ".")},
    )
    if result.get("ok") and result["n_lines"] > 0:
        closure_cache[dotpath] = result["lines"]
        out_verbose(f"import_graph: traced '{dotpath}' → "
                    f"{len(result['lines'])} files, {result['n_lines']} lines")
        return

    # --- Decision: should we do the expensive Stage 2 retry? -----------------
    # Skip Stage 2 only for DEEP subpackages (depth > 2) where a shorter
    # ancestor already has substantial data.  Top-level subpackages (depth 2,
    # e.g. "sympy.physics") are where the deep import chains LIVE — skipping
    # them would miss the lines they uniquely trigger (such as the si.py →
    # numbers.py:1457 chain reached only when sympy.physics is fully re-imported).
    parts = dotpath.split(".")
    if len(parts) > 2:
        for depth in range(len(parts) - 1, 1, -1):  # skip top-level ancestor
            ancestor = ".".join(parts[:depth])
            anc_lines = closure_cache.get(ancestor)
            # Require ancestor to have substantial data — at least 50 files
            # captured — otherwise it's likely a thin trace that won't cover
            # what we'd capture with our own retry.
            if anc_lines and len(anc_lines) >= 50:
                closure_cache[dotpath] = result.get("lines", {})
                out_verbose(f"import_graph: '{dotpath}' Stage 1 failed; ancestor "
                            f"'{ancestor}' has {len(anc_lines)} files, skipping Stage 2")
                return

    # --- Stage 2: full top-level eviction (expensive fallback) ----------------
    top_level = parts[0]
    if top_level == dotpath:
        # Already a top-level package — Stage 1 already evicted everything we can.
        # No point retrying with the same eviction set.
        closure_cache[dotpath] = result.get("lines", {})
        n = result.get("n_lines", 0)
        if n == 0:
            out_info(f"import_graph: WARNING — '{dotpath}' produced 0 lines after "
                     f"local eviction; reason: {result.get('error', 'no project lines')}")
        return

    out_info(f"import_graph: '{dotpath}' Stage 1 failed "
             f"({result.get('error', '0 lines')}); retrying with full '{top_level}' eviction")
    result2 = _attempt_trace(
        dotpath, folder, folder_norm,
        evict_keys={top_level} | {k for k in sys.modules if k.startswith(top_level + ".")},
    )
    closure_cache[dotpath] = result2.get("lines", {})
    if result2.get("ok") and result2["n_lines"] > 0:
        out_info(f"import_graph: '{dotpath}' Stage 2 succeeded "
                 f"({len(result2['lines'])} files, {result2['n_lines']} lines)")
    else:
        out_info(f"import_graph: WARNING — '{dotpath}' Stage 2 also failed "
                 f"({result2.get('error', '0 lines')}); giving up")


def _attempt_trace(dotpath, folder, folder_norm, evict_keys):
    """Run one trace attempt with the given eviction set.

    Returns a dict with keys:
        ok       : bool — whether import_module raised no exception
        n_lines  : int  — total project lines captured
        lines    : dict[rel_path, set[int]] — captured line map
        error    : str  — present only when ok is False
    """
    # Evict and remember original modules so sys.modules can be restored.
    evicted = {}
    for key in evict_keys:
        module = sys.modules.pop(key, None)
        if module is not None:
            evicted[key] = module

    executed = defaultdict(set)  # abs_filename → {linenos}
    normcase = os.path.normcase
    _norm = {}  # co_filename → True (under folder) | False (outside)

    def _tracer(frame, event, _arg):
        if event == "line":
            fn = frame.f_code.co_filename
            under = _norm.get(fn, _SENTINEL)
            if under is _SENTINEL:
                under = normcase(fn).startswith(folder_norm)
                _norm[fn] = under
            if under:
                executed[fn].add(frame.f_lineno)
        return _tracer

    # Bump recursion limit: sys.settrace doubles per-frame overhead and deep
    # packages (sympy.physics) easily exceed the default 1000-frame limit.
    old_tracer = sys.gettrace()
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 50000))
    sys.settrace(_tracer)
    error = None
    try:
        importlib.import_module(dotpath)
    except BaseException as exc:  # includes RecursionError, KeyboardInterrupt
        error = f"{type(exc).__name__}: {exc}"
    finally:
        sys.settrace(old_tracer)
        sys.setrecursionlimit(old_limit)

    # Build result map (project paths only — files under folder).
    folder_prefix = folder + os.sep
    lines_map = {}
    for abs_path, lines in executed.items():
        real_path = os.path.realpath(abs_path)
        if not real_path.startswith(folder_prefix):
            continue
        rel = os.path.relpath(real_path, folder).replace("\\", "/")
        lines_map[rel] = lines

    # Restore sys.modules — remove anything added during the trace, reinstate
    # everything that was evicted.  This is essential so that subsequent
    # traces aren't perturbed by leftover state from this attempt.
    for key in list(sys.modules):
        if key in evicted:
            continue  # will be reinstated below
        if any(key == ek or key.startswith(ek + ".") for ek in evict_keys):
            del sys.modules[key]
    sys.modules.update(evicted)

    result = {
        "ok": error is None,
        "n_lines": sum(len(v) for v in lines_map.values()),
        "lines": lines_map,
    }
    if error is not None:
        result["error"] = error
    return result
