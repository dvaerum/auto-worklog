"""Auto Worklog - Automatic work time tracking with screen lock detection."""

from importlib.metadata import PackageNotFoundError, version

# pyproject.toml is the only place the version is written; this reads it back
# from the installed package metadata.
try:
    __version__ = version("auto-worklog")
except PackageNotFoundError:
    # Running straight from a source checkout that was never installed (pytest
    # via pythonpath = src); a placeholder is the honest answer there.
    __version__ = "0+unknown"
