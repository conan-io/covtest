import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

CONAN_TAG = "2.27.0"
CONAN_REPO_URL = "https://github.com/conan-io/conan"
COVTEST_ROOT = Path(__file__).parent.parent.parent  # covtest project root

# Breaking changes: each entry defines a single-line mutation.
# The 'original' field is asserted before applying the change — any line-number
# drift in a future Conan version will surface as a clear AssertionError.
BREAKING_CHANGES = [
    {
        "id": "version_lt_invert",
        "file": "conan/internal/model/version.py",
        "line": 44,
        "original": "            return self._v < other._v\n",
        "replacement": "            return kk\n",
        "description": "Invert _VersionItem.__lt__ numeric comparison",
    },
    {
        "id": "manifest breaking",
        "file": "conan/internal/model/manifest.py",
        "line": 93,
        "original": '        files, _ = gather_files(folder)\n',
        "replacement": '        files, _ = gather_files(folder)\n        kk\n',
        "description": "Breaking Manifest",
    },
    {
        "id": "restapi breaking",
        "file": "conan/internal/rest/rest_client_v2.py",
        "line": 113,
        "original": '        auth = self.auth\n',
        "replacement": '        auth = self.auth2\n',
        "description": "Breaking restv2",
    },
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conan_repo(tmp_path_factory):
    """Clone Conan, build a dedicated venv, collect coverage, run covtest process.
    Yields {"repo_dir": str, "venv_python": str}.
    """
    repo_dir = str(tmp_path_factory.mktemp("conan"))

    print("REPO DIR", repo_dir)
    # 1. Shallow clone at pinned tag
    print(f"\nCloning conan {CONAN_TAG} …")
    subprocess.run(
        ["git", "clone", "--depth=1", f"--branch={CONAN_TAG}",
         CONAN_REPO_URL, repo_dir],
        check=True,
    )

    # 2. Dedicated venv — mirrors a real Conan developer environment
    print("Creating venv …")
    venv_dir = os.path.join(repo_dir, ".venv")
    venv.create(venv_dir, with_pip=True)
    if sys.platform == "win32":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    def _pip(*args):
        subprocess.run([venv_python, "-m", "pip", "install", *args], check=True, cwd=repo_dir)

    # Upgrade pip inside the venv — venv.create seeds it from ensurepip which is outdated
    _pip("--upgrade", "pip")

    # 3. Install covtest first so all its dependencies (e.g. unidiff) are already
    #    present when the Conan requirements are resolved, avoiding resolver warnings.
    print("Installing covtest (editable) …")
    _pip("-e", str(COVTEST_ROOT))
    _pip("pytest-json-report")

    # 4. Install Conan runtime + dev requirements
    print("Installing Conan requirements …")
    _pip("-r", "conans/requirements.txt")
    _pip("-r", "conans/requirements_dev.txt")

    # 5. Locally git-ignore generated artifacts so git_dirty() stays False.
    #    We write to .git/info/exclude rather than modifying any tracked file.
    exclude_file = os.path.join(repo_dir, ".git", "info", "exclude")
    with open(exclude_file, "a") as f:
        f.write("\n.coverage\n.covtest\n.venv\ncovtests.tests\n.report.json\n")

    # 6. Run pytest with coverage in parallel (pytest-xdist is in requirements_dev)
    print("Running pytest with coverage …")
    subprocess.run(
        [venv_python, "-m", "pytest", "test/unittests/",
         "-n", "auto",
         "--cov=conan", "--cov-context=test",
         "--tb=no", "-q"],
        cwd=repo_dir,
        check=False,  # some pre-existing failures are acceptable
    )

    # 7. Process coverage into covtest DB (repo must be clean — ensured by step 5)
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
    """Run the full unit suite in parallel and return node IDs with failed/error outcome."""
    report_file = os.path.join(repo_dir, ".report.json")
    subprocess.run(
        [venv_python, "-m", "pytest", "test/unittests/",
         "-n", "auto",
         "--tb=no", "-q",
         "--json-report", f"--json-report-file={report_file}"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if not os.path.exists(report_file):
        return set()
    with open(report_file) as f:
        report = json.load(f)
    failed = {t["nodeid"] for t in report.get("tests", [])
              if t["outcome"] in ("failed", "error")}
    print("FAILED TESTS:", failed)
    return failed


def _get_predicted_tests(repo_dir, venv_python):
    """Run covtest predict and return the set of predicted test node IDs."""
    # Remove stale output file if present
    tests_file = os.path.join(repo_dir, "covtests.tests")
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
def test_covtest_predicts_broken_tests(conan_repo, change):
    repo_dir = conan_repo["repo_dir"]
    venv_python = conan_repo["venv_python"]
    try:
        _apply_change(repo_dir, change)

        broken = _get_broken_tests(repo_dir, venv_python)
        predicted = _get_predicted_tests(repo_dir, venv_python)

        tp = predicted & broken
        fn = broken - predicted
        fp = predicted - broken
        recall = len(tp) / len(broken) if broken else 1.0
        precision = len(tp) / len(predicted) if predicted else 0.0

        print(f"\n[{change['id']}] broken={len(broken)} predicted={len(predicted)} "
              f"recall={recall:.2f} precision={precision:.2f}")
        print(f"  True positives:          {len(tp)}")
        print(f"  FN (missed by covtest):  {len(fn)}: {fn}")
        print(f"  FP (extra predictions):  {len(fp)}: {fp}")

        assert broken, (
            f"No tests failed after applying '{change['id']}' — "
            f"check that line {change['line']} is correct"
        )
        assert recall >= 0.9, (
            f"Recall {recall:.2f} < 0.9 for '{change['id']}'\n"
            f"  Tests broken but not predicted: {fn}"
        )
    finally:
        _revert_change(repo_dir, change)
