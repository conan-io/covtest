"""Unit tests for extract_coverage filtering."""

import os

import coverage as cov_module
import pytest

from covtest.covtest import extract_coverage


def _make_coverage_db(db_path, entries):
    """Write a .coverage DB where entries = {abs_filename: [linenos]}."""
    cov_data = cov_module.CoverageData(basename=db_path)
    cov_data.set_context("test_module.py::test_foo|run")
    cov_data.add_lines(entries)
    cov_data.write()


def test_project_file_included(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "mymodule.py").write_text("X = 1\n")

    _make_coverage_db(
        str(project / ".coverage"),
        {str(project / "mymodule.py"): [1]},
    )

    result = extract_coverage(str(project))
    assert "mymodule.py" in result


def test_venv_site_packages_excluded(tmp_path):
    """Files under .venv/Lib/site-packages/ (Windows venv layout) must be excluded."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mymodule.py").write_text("X = 1\n")

    venv_pkg = project / ".venv" / "Lib" / "site-packages" / "requests.py"
    venv_pkg.parent.mkdir(parents=True)
    venv_pkg.write_text("VERSION = 1\n")

    _make_coverage_db(
        str(project / ".coverage"),
        {
            str(project / "mymodule.py"): [1],
            str(venv_pkg): [1],
        },
    )

    result = extract_coverage(str(project))
    assert "mymodule.py" in result
    assert not any("site-packages" in k for k in result)
    assert not any(".venv" in k for k in result)


def test_unix_venv_site_packages_excluded(tmp_path):
    """Files under .venv/lib/pythonX.Y/site-packages/ (Unix venv layout) must be excluded."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mymodule.py").write_text("X = 1\n")

    venv_pkg = project / ".venv" / "lib" / "python3.12" / "site-packages" / "requests.py"
    venv_pkg.parent.mkdir(parents=True)
    venv_pkg.write_text("VERSION = 1\n")

    _make_coverage_db(
        str(project / ".coverage"),
        {
            str(project / "mymodule.py"): [1],
            str(venv_pkg): [1],
        },
    )

    result = extract_coverage(str(project))
    assert "mymodule.py" in result
    assert not any("site-packages" in k for k in result)


def test_outside_project_excluded(tmp_path):
    """Files physically outside the project folder must be excluded."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mymodule.py").write_text("X = 1\n")

    outside = tmp_path / "other_project" / "other.py"
    outside.parent.mkdir()
    outside.write_text("Y = 2\n")

    _make_coverage_db(
        str(project / ".coverage"),
        {
            str(project / "mymodule.py"): [1],
            str(outside): [1],
        },
    )

    result = extract_coverage(str(project))
    assert "mymodule.py" in result
    assert not any(k.startswith("..") for k in result)
    assert "other.py" not in result


def test_context_preserved(tmp_path):
    """The test name from the coverage context must appear in the result."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "mymodule.py").write_text("X = 1\n")

    _make_coverage_db(
        str(project / ".coverage"),
        {str(project / "mymodule.py"): [1]},
    )

    result = extract_coverage(str(project))
    # Context "test_module.py::test_foo|run" → test name "test_module.py::test_foo"
    assert result["mymodule.py"][1] == {"test_module.py::test_foo"}
