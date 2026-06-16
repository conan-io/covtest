"""Shared infrastructure for covtest benchmark tests.

Each benchmark (Conan, Sympy, Django, …) clones a real project, runs the full
test suite with coverage, processes the snapshot, then applies a series of
mutations and checks that covtest's recall ≥ 99 % and selection ≤ 70 %.

This module provides:
  - setup_repo()         — clone + venv + install + coverage run + covtest process
  - apply_change()       — apply one mutation to the repo
  - revert_change()      — git checkout to undo the mutation
  - get_broken_tests()   — run the test suite under the mutation, return failures
  - get_predicted_tests() — run covtest predict, return predicted test IDs
  - assert_benchmark()   — compute metrics, print them, assert thresholds
"""

import json
import os
import subprocess
import sys
import venv as _venv
from pathlib import Path

COVTEST_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Repo setup
# ---------------------------------------------------------------------------

def setup_repo(
    tmp_path_factory,
    *,
    tag: str,
    url: str,
    pip_deps: list,
    test_scope: "str | list[str]",
    cov_target: str,
    setup_hook: "callable | None" = None,
    run_test_parallel=True
) -> dict:
    """Clone *url* at *tag*, create a dedicated venv, run the initial coverage
    suite, and process the snapshot with covtest.

    Parameters
    ----------
    tmp_path_factory : pytest TempPathFactory
        Provided by the ``tmp_path_factory`` fixture.
    tag : str
        Git tag to clone (shallow, e.g. ``"2.27.0"``).
    url : str
        Remote repository URL.
    pip_deps : list[str | tuple[str, ...]]
        Packages to ``pip install`` inside the venv **after** covtest itself.
        Each entry is either a plain string (single argument, e.g.
        ``"pytest-xdist"``) or a tuple of strings (multiple arguments, e.g.
        ``("-r", "requirements.txt")`` or ``("-e", ".")``).
    test_scope : str | list[str]
        Pytest collection path(s) for the initial coverage run.  Either a
        single string (e.g. ``"test/unittests/"``) or a list of paths.
    cov_target : str
        ``--cov=`` argument (the importable package name, e.g. ``"conan"``).
    setup_hook : callable | None
        Optional ``(repo_dir: str, venv_python: str) -> None`` called once
        after all pip installs but before the initial coverage run.  Use this
        to write config files (e.g. ``pytest.ini``) that the target project
        needs when invoked via plain ``pytest`` instead of its own test runner.
    run_test_parallel:
        Whether to run the test suite in parallel or not.

    Returns
    -------
    dict
        ``{"repo_dir": str, "venv_python": str}``
    """
    repo_dir = str(tmp_path_factory.mktemp("repo"))

    print(f"\nCloning {url} @ {tag} …")
    subprocess.run(
        ["git", "clone", "--depth=1", f"--branch={tag}", url, repo_dir],
        check=True,
    )

    print("Creating venv …")
    venv_dir = os.path.join(repo_dir, ".venv")
    _venv.create(venv_dir, with_pip=True)
    if sys.platform == "win32":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    def _pip(*args):
        subprocess.run([venv_python, "-m", "pip", "install", *args],
                       check=True, cwd=repo_dir)

    _pip("--upgrade", "pip")

    # Install covtest first so its deps are resolved before the project's.
    print("Installing covtest (editable) …")
    _pip("-e", str(COVTEST_ROOT))
    _pip("pytest-json-report")

    print(f"Installing project deps ({len(pip_deps)} packages) …")
    for dep in pip_deps:
        _pip(dep) if isinstance(dep, str) else _pip(*dep)

    if setup_hook is not None:
        setup_hook(repo_dir, venv_python)

    # Keep generated artefacts out of git so git_dirty() stays False.
    exclude_file = os.path.join(repo_dir, ".git", "info", "exclude")
    with open(exclude_file, "a") as f:
        f.write("\n.coverage\n.covtest\n.venv\ncovtests.tests\n.report.json\n")

    # Initial coverage run.
    scope_args = [test_scope] if isinstance(test_scope, str) else list(test_scope)
    print(f"Running pytest with coverage over {scope_args} …")
    parallel_args = ["-n", "auto"] if run_test_parallel else []
    result = subprocess.run(
        [venv_python, "-m", "pytest", *scope_args,
         *parallel_args,
         f"--cov={cov_target}", "--cov-context=test",
         "--tb=no", "-q"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout
    print(stdout[-3000:] if len(stdout) > 3000 else stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-2000:])
    coverage_file = os.path.join(repo_dir, ".coverage")
    if not os.path.exists(coverage_file):
        raise RuntimeError(
            f"pytest exited {result.returncode} with no .coverage file — "
            "check the output above."
        )

    print("Running covtest process …")
    subprocess.run(
        [venv_python, "-m", "covtest", "process", "."],
        cwd=repo_dir,
        check=True,
    )

    return {"repo_dir": repo_dir, "venv_python": venv_python}


# ---------------------------------------------------------------------------
# Per-mutation helpers
# ---------------------------------------------------------------------------

def apply_change(repo_dir: str, change: dict) -> None:
    """Apply one single-line mutation, asserting the original text first.

    Parameters
    ----------
    repo_dir : str
        Root of the cloned project.
    change : dict
        Mutation descriptor with keys ``"file"`` (repo-relative path),
        ``"line"`` (1-based), ``"original"`` (expected text), and
        ``"replacement"`` (new text).
    """
    path = os.path.join(repo_dir, change["file"])
    lines = open(path).readlines()
    actual = lines[change["line"] - 1]
    assert actual == change["original"], (
        f"Line mismatch at {change['file']}:{change['line']}\n"
        f"  Expected: {change['original']!r}\n"
        f"  Got:      {actual!r}"
    )
    lines[change["line"] - 1] = change["replacement"]
    open(path, "w").writelines(lines)


def revert_change(repo_dir: str, change: dict) -> None:
    """Undo the mutation via ``git checkout``.

    Parameters
    ----------
    repo_dir : str
        Root of the cloned project.
    change : dict
        Mutation descriptor — only ``"file"`` is used.
    """
    subprocess.run(
        ["git", "checkout", "--", change["file"]],
        cwd=repo_dir,
        check=True,
    )


def get_broken_tests(
    repo_dir: str,
    venv_python: str,
    test_scope: "str | list[str]",
    *,
    timeout_per_test: "int | None" = None,
    wall_timeout: "int | None" = None,
    run_test_parallel=True
) -> tuple:
    """Run the test suite under the mutation and return ``(failed_ids, total)``.

    Parameters
    ----------
    repo_dir : str
        Root of the cloned project.
    venv_python : str
        Path to the venv's Python executable.
    test_scope : str | list[str]
        Pytest collection path(s) (e.g. ``"test/unittests/"``).
    timeout_per_test : int | None
        Per-test timeout in seconds passed to ``pytest-timeout`` via
        ``--timeout``.  Pass ``None`` to skip (safe for projects whose
        mutations cannot cause infinite loops).
    wall_timeout : int | None
        Hard wall-clock cap in seconds for the entire subprocess.  If pytest
        does not finish within this limit it is killed and whatever partial
        results exist are used.  ``None`` means no limit.
    run_test_parallel : bool
        Whether to run tests in parallel.

    Returns
    -------
    tuple[set[str], int]
        ``(failed_node_ids, total_test_count)``
    """
    scope_args = [test_scope] if isinstance(test_scope, str) else list(test_scope)
    report_file = os.path.join(repo_dir, ".report.json")
    parallel_args = ["-n", "auto"] if run_test_parallel else []
    cmd = [
        venv_python, "-m", "pytest", *scope_args,
        *parallel_args,
        "--tb=no", "-q",
        "--json-report", f"--json-report-file={report_file}",
    ]
    if timeout_per_test is not None:
        cmd += [f"--timeout={timeout_per_test}", "--timeout-method=thread"]

    print("Running cmd to check broken tests", cmd)
    if os.path.exists(report_file):
        os.remove(report_file)
    try:
        subprocess.run(
            cmd,
            cwd=repo_dir,
            # capture_output=True,
            text=True,
            timeout=wall_timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"WARNING: pytest exceeded the {wall_timeout}s wall-clock cap and was killed.")

    if not os.path.exists(report_file):
        raise Exception("Error: No report file found.")
    with open(report_file) as f:
        report = json.load(f)
    print("Report:", json.dumps(report, indent=2))
    tests = report.get("tests", [])
    failed = {t["nodeid"] for t in tests if t["outcome"] in ("failed", "error")}
    total = len(tests)
    print(f"FAILED TESTS: {len(failed)}/{total}")
    return failed, total


def get_predicted_tests(repo_dir: str, venv_python: str) -> set:
    """Run ``covtest predict`` and return the set of predicted test node IDs.

    Parameters
    ----------
    repo_dir : str
        Root of the cloned project (must contain a ``.covtest/`` snapshot).
    venv_python : str
        Path to the venv's Python executable.

    Returns
    -------
    set[str]
        Predicted test node IDs, or an empty set if covtest produced no output.
    """
    from covtest.covtest import COVTEST_FOLDER

    tests_file = os.path.join(repo_dir, COVTEST_FOLDER, "covtests.tests")
    if os.path.exists(tests_file):
        os.remove(tests_file)

    subprocess.run(
        [venv_python, "-m", "covtest", "predict", ".", "-vvv"],
        cwd=repo_dir,
        check=False,
    )

    if not os.path.exists(tests_file):
        return set()
    content = open(tests_file).read().strip()
    return set(content.splitlines()) if content else set()


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------

def assert_benchmark(
    change: dict,
    broken: set,
    total: int,
    predicted: set,
    *,
    min_recall: float = 0.99,
    max_selection: float = 0.70,
) -> None:
    """Compute metrics, print a summary, and assert recall / selection thresholds.

    Parameters
    ----------
    change : dict
        Mutation descriptor (used for the ``"id"`` and ``"line"`` fields in
        error messages).
    broken : set[str]
        Test node IDs that failed when the mutation was applied.
    total : int
        Total number of tests that ran (used to compute the selection ratio).
    predicted : set[str]
        Test node IDs that covtest predicted would be affected.
    min_recall : float
        Minimum acceptable recall (TP / broken).  Default 0.99.  Use logical
        mutations (not crash/NameError ones) to get a meaningful signal: crash
        mutations cascade through pytest's collection phase and inflate the
        broken set with collateral failures, making recall trivially achievable.
    max_selection : float
        Maximum acceptable selection ratio (predicted / total).  Ensures the
        tool provides a real CI speedup — default 0.70 means covtest must skip
        at least 30 % of the suite.
    """
    tp = predicted & broken
    fn = broken - predicted
    fp = predicted - broken
    recall = len(tp) / len(broken) if broken else 1.0
    precision = len(tp) / len(predicted) if predicted else 0.0
    selection = len(predicted) / total if total else 1.0

    print(f"\n[{change['id']}] broken={len(broken)}/{total} predicted={len(predicted)} "
          f"recall={recall:.3f} precision={precision:.3f} selection={selection:.3f}")
    print(f"  True positives:   {len(tp)}")
    print(f"  FN (missed):      {len(fn)}: {sorted(fn)[:20]}"
          f"{' …' if len(fn) > 20 else ''}")
    print(f"  FP (extra):       {len(fp)}")

    assert broken, (
        f"No tests failed after applying '{change['id']}' — "
        f"check that line {change['line']} is correct"
    )
    assert recall >= min_recall, (
        f"Recall {recall:.3f} < {min_recall} for '{change['id']}'\n"
        f"  Tests broken but not predicted: {sorted(fn)}"
    )
    assert selection <= max_selection, (
        f"Selection {selection:.3f} > {max_selection} for '{change['id']}' — "
        f"covtest selected too much of the suite to be useful"
    )
