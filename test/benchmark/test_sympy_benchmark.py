import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from covtest.covtest import COVTEST_FOLDER

SYMPY_TAG = "1.14.0"
SYMPY_REPO_URL = "https://github.com/sympy/sympy"
COVTEST_ROOT = Path(__file__).parent.parent.parent

# Breaking changes: each entry defines a single-line mutation.
# The 'original' field is asserted before applying the change — any line-number
# drift in a future SymPy version will surface as a clear AssertionError.
# Breaking changes use LOGICAL mutations (return wrong value, no exception)
# rather than crash mutations (NameError).  Rationale: crash mutations cascade
# through pytest's collection phase, making every test in every file that imports
# the chain fail — these are collateral failures, not real test-impact signals.
# Logical mutations only break tests whose OBSERVED OUTPUT changes, which is
# exactly what a test-impact prediction tool should target.
BREAKING_CHANGES = [
    {
        "id": "integer_add_invert",
        "file": "sympy/core/numbers.py",
        "line": 1891,
        "original": "                return Integer(self.p + other.p)\n",
        "replacement": "                return Integer(self.p - other.p)\n",
        "description": "Integer.__add__ returns p - other.p instead of p + other.p",
    },
    {
        "id": "rational_add_invert",
        "file": "sympy/core/numbers.py",
        "line": 1457,
        "original": "                return Rational(self.p*other.q + self.q*other.p, self.q*other.q)\n",
        "replacement": "                return Rational(self.p*other.q - self.q*other.p, self.q*other.q)\n",
        "description": "Rational.__add__ uses subtraction instead of addition in numerator",
    },
    {
        "id": "symbol_free_symbols_break",
        "file": "sympy/core/symbol.py",
        "line": 448,
        "original": "        return {self}\n",
        "replacement": "        return set()\n",
        "description": "Symbol.free_symbols returns empty set instead of {self}",
    },
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sympy_repo(tmp_path_factory):
    """Clone SymPy, build a dedicated venv, collect coverage, run covtest process.
    Yields {"repo_dir": str, "venv_python": str}.
    """
    repo_dir = str(tmp_path_factory.mktemp("sympy"))

    print("REPO DIR", repo_dir)
    print(f"\nCloning sympy {SYMPY_TAG} …")
    subprocess.run(
        ["git", "clone", "--depth=1", f"--branch={SYMPY_TAG}",
         SYMPY_REPO_URL, repo_dir],
        check=True,
    )

    print("Creating venv …")
    venv_dir = os.path.join(repo_dir, ".venv")
    venv.create(venv_dir, with_pip=True)
    if sys.platform == "win32":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    def _pip(*args):
        subprocess.run([venv_python, "-m", "pip", "install", *args], check=True, cwd=repo_dir)

    _pip("--upgrade", "pip")

    # Install covtest first so its dependencies are already present when
    # SymPy requirements are resolved, avoiding resolver warnings.
    print("Installing covtest (editable) …")
    _pip("-e", str(COVTEST_ROOT))
    _pip("pytest-json-report")

    # Install SymPy (editable) and all required test dependencies.
    # pytest-cov is already a covtest dependency; the rest are for SymPy's suite.
    print("Installing SymPy …")
    _pip("-e", ".")
    # pytest-timeout is critical with LOGICAL mutations: some sympy algorithms
    # iterate based on intermediate results (e.g., `while expr.free_symbols`).
    # When a mutation produces wrong values, those loops can run forever instead
    # of failing cleanly.  --timeout per-test makes any such hang surface as a
    # test failure within seconds.
    _pip("pytest-xdist", "hypothesis", "pytest-timeout")

    # Locally git-ignore generated artifacts so git_dirty() stays False.
    # We write to .git/info/exclude rather than modifying any tracked file.
    exclude_file = os.path.join(repo_dir, ".git", "info", "exclude")
    with open(exclude_file, "a") as f:
        f.write("\n.coverage\n.covtest\n.venv\ncovtests.tests\n.report.json\n")

    # Run pytest with coverage over sympy/core/tests/ — this covers numbers.py
    # and symbol.py (the files targeted by BREAKING_CHANGES) while keeping the
    # initial run to a manageable scope.
    print("Running pytest with coverage …")
    result = subprocess.run(
        [venv_python, "-m", "pytest", "sympy/core/tests/",
         "-n", "auto",
         "--cov=sympy", "--cov-context=test",
         "--tb=no", "-q"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
    coverage_file = os.path.join(repo_dir, ".coverage")
    if not os.path.exists(coverage_file):
        raise RuntimeError(
            f"pytest exited with code {result.returncode} and produced no .coverage file — "
            f"the test run likely failed at collection. Check output above."
        )

    print("Running covtest process …")
    subprocess.run(
        [venv_python, "-m", "covtest", "process", "."],
        cwd=repo_dir,
        check=True,
    )

    yield {"repo_dir": repo_dir, "venv_python": venv_python}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_change(repo_dir, change):
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


def _revert_change(repo_dir, change):
    subprocess.run(
        ["git", "checkout", "--", change["file"]],
        cwd=repo_dir,
        check=True,
    )


def _get_broken_tests(repo_dir, venv_python):
    """Run sympy/core/tests/ in parallel and return (failed_set, total_count).

    total_count is the total number of tests pytest ran — used to compute the
    selection ratio (what fraction of the suite covtest predicted).

    Per-test --timeout protects against logical mutations that cause infinite
    loops in sympy algorithms instead of clean failures.  The subprocess-level
    timeout is a final safety net for pathological cases (collection hangs,
    pytest-xdist worker deadlocks, …).
    """
    report_file = os.path.join(repo_dir, ".report.json")
    try:
        subprocess.run(
            [venv_python, "-m", "pytest", "sympy/core/tests/",
             "-n", "auto",
             "--timeout=30", "--timeout-method=thread",
             "--tb=no", "-q",
             "--json-report", f"--json-report-file={report_file}"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=20 * 60,  # 20-minute wall-clock cap
        )
    except subprocess.TimeoutExpired:
        print("WARNING: pytest exceeded the 20-minute wall-clock cap and was killed.")
    if not os.path.exists(report_file):
        return set(), 0
    with open(report_file) as f:
        report = json.load(f)
    tests = report.get("tests", [])
    failed = {t["nodeid"] for t in tests
              if t["outcome"] in ("failed", "error")}
    total = len(tests)
    print(f"FAILED TESTS: {len(failed)}/{total}")
    return failed, total


def _get_predicted_tests(repo_dir, venv_python):
    """Run covtest predict and return the set of predicted test node IDs."""
    tests_file = os.path.join(repo_dir, COVTEST_FOLDER, "covtests.tests")
    if os.path.exists(tests_file):
        os.remove(tests_file)

    subprocess.run(
        [venv_python, "-m", "covtest", "predict", "."],
        cwd=repo_dir,
        check=False,
    )

    if not os.path.exists(tests_file):
        return set()
    content = open(tests_file).read().strip()
    return set(content.splitlines()) if content else set()


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@pytest.mark.benchmark
@pytest.mark.parametrize("change", BREAKING_CHANGES, ids=lambda c: c["id"])
def test_covtest_predicts_broken_tests(sympy_repo, change):
    repo_dir = sympy_repo["repo_dir"]
    venv_python = sympy_repo["venv_python"]
    try:
        _apply_change(repo_dir, change)

        broken, total = _get_broken_tests(repo_dir, venv_python)
        predicted = _get_predicted_tests(repo_dir, venv_python)

        tp = predicted & broken
        fn = broken - predicted
        fp = predicted - broken
        recall = len(tp) / len(broken) if broken else 1.0
        precision = len(tp) / len(predicted) if predicted else 0.0
        # Selection ratio: what fraction of the entire suite covtest selected.
        # A perfect predictor selects a tiny subset (low selection) that still
        # catches all real breakages (high recall).  A trivial "run everything"
        # predictor scores recall=1.0 but selection=1.0 → no CI speedup.
        selection = len(predicted) / total if total else 1.0

        print(f"\n[{change['id']}] broken={len(broken)}/{total} predicted={len(predicted)} "
              f"recall={recall:.3f} precision={precision:.3f} selection={selection:.3f}")
        print(f"  True positives:          {len(tp)}")
        print(f"  FN (missed by covtest):  {len(fn)}: {sorted(fn)[:20]}"
              f"{' …' if len(fn) > 20 else ''}")
        print(f"  FP (extra predictions):  {len(fp)}")

        assert broken, (
            f"No tests failed after applying '{change['id']}' — "
            f"check that line {change['line']} is correct"
        )
        assert recall >= 0.99, (
            f"Recall {recall:.3f} < 0.99 for '{change['id']}'\n"
            f"  Tests broken but not predicted: {sorted(fn)}"
        )
        # Soundness check: covtest must provide real CI speedup, not rubber-stamp
        # the suite.  A 70% selection ceiling means covtest skipped at least 30%.
        assert selection <= 0.70, (
            f"Selection {selection:.3f} > 0.70 for '{change['id']}' — "
            f"covtest selected too much of the suite to be useful"
        )
    finally:
        _revert_change(repo_dir, change)
