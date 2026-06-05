import pytest

from test.benchmark.benchmark_utils import (
    setup_repo,
    apply_change,
    revert_change,
    get_broken_tests,
    get_predicted_tests,
    assert_benchmark,
)

CONAN_TAG = "2.27.0"
CONAN_REPO_URL = "https://github.com/conan-io/conan"

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


@pytest.fixture(scope="module")
def conan_repo(tmp_path_factory):
    return setup_repo(
        tmp_path_factory,
        tag=CONAN_TAG,
        url=CONAN_REPO_URL,
        pip_deps=[
            ("-r", "conans/requirements.txt"),
            ("-r", "conans/requirements_dev.txt"),
        ],
        test_scope="test/unittests/",
        cov_target="conan",
    )


@pytest.mark.benchmark
@pytest.mark.parametrize("change", BREAKING_CHANGES, ids=lambda c: c["id"])
def test_covtest_predicts_broken_tests(conan_repo, change):
    repo_dir = conan_repo["repo_dir"]
    venv_python = conan_repo["venv_python"]
    try:
        apply_change(repo_dir, change)
        broken, total = get_broken_tests(
            repo_dir, venv_python, "test/unittests/",
        )
        predicted = get_predicted_tests(repo_dir, venv_python)
        assert_benchmark(change, broken, total, predicted)
    finally:
        revert_change(repo_dir, change)
