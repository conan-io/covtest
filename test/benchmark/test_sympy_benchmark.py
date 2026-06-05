import pytest

from test.benchmark.benchmark_utils import (
    setup_repo,
    apply_change,
    revert_change,
    get_broken_tests,
    get_predicted_tests,
    assert_benchmark,
)

SYMPY_TAG = "1.14.0"
SYMPY_REPO_URL = "https://github.com/sympy/sympy"

# Logical mutations (return wrong value, no exception) rather than crash
# mutations (NameError).  Rationale: crash mutations cascade through pytest's
# collection phase — every test in every file that imports the broken chain
# fails as a collateral error, not because it exercises the changed logic.
# Logical mutations only break tests whose *observed output* changes, which
# is exactly what a test-impact prediction tool should target.
#
# pytest-timeout is installed by setup_repo so that logical mutations which
# cause infinite loops in sympy algorithms (e.g. iterating until convergence)
# are caught as test errors instead of hanging the suite forever.
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


@pytest.fixture(scope="module")
def sympy_repo(tmp_path_factory):
    return setup_repo(
        tmp_path_factory,
        tag=SYMPY_TAG,
        url=SYMPY_REPO_URL,
        pip_deps=[
            ("-e", "."),          # editable install so sympy is importable
            "pytest-xdist",
            "hypothesis",
            # pytest-timeout guards against infinite loops from logical
            # mutations in iterative sympy algorithms
            "pytest-timeout",
        ],
        test_scope="sympy/core/tests/",
        cov_target="sympy",
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("change", BREAKING_CHANGES, ids=lambda c: c["id"])
def test_covtest_predicts_broken_tests(sympy_repo, change):
    repo_dir = sympy_repo["repo_dir"]
    venv_python = sympy_repo["venv_python"]
    try:
        apply_change(repo_dir, change)
        broken, total = get_broken_tests(
            repo_dir, venv_python, "sympy/core/tests/",
            timeout_per_test=30,
            wall_timeout=20 * 60,
        )
        predicted = get_predicted_tests(repo_dir, venv_python)
        assert_benchmark(change, broken, total, predicted)
    finally:
        revert_change(repo_dir, change)
