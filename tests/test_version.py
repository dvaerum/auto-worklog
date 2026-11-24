"""pyproject.toml is the one place the version is written down.

nix/deps.nix reads it from there for the derivation, and auto_worklog.__version__
reads the installed package metadata, which setuptools builds from it.
"""

import re
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

import auto_worklog

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

# Files that must not spell the version out; each would be a second source of truth.
_SCANNED = [
    *ROOT.joinpath("src").rglob("*.py"),
    *ROOT.joinpath("nix").glob("*.nix"),
    *ROOT.joinpath("homeManagerModules").glob("*.nix"),
    ROOT / "flake.nix",
]


def test_pyproject_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", PYPROJECT_VERSION)


def test_version_is_not_written_down_anywhere_else():
    offenders = [
        str(path.relative_to(ROOT))
        for path in _SCANNED
        if PYPROJECT_VERSION in path.read_text()
    ]
    assert offenders == []


def test_runtime_version_is_the_installed_package_version():
    try:
        installed = version("auto-worklog")
    except PackageNotFoundError:
        pytest.skip("not installed (running from a source checkout)")
    assert auto_worklog.__version__ == installed


def test_version_is_never_empty():
    assert auto_worklog.__version__
