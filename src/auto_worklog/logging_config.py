"""Logging configuration for auto-worklog."""

import logging
import os
import sys
from pathlib import Path

_SYSTEMD_FMT = "[%(levelname)s] %(name)s - %(message)s"
_DEFAULT_FMT = "%(asctime)s " + _SYSTEMD_FMT
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _running_under_systemd() -> bool:
    """Detect whether stdout/stderr is connected to the systemd journal."""
    return "JOURNAL_STREAM" in os.environ


def _parse_level(level: str) -> int | None:
    """Convert a level name to its numeric value.

    Returns ``None`` for ``"OFF"`` (meaning: do not create the handler).
    """
    if level.upper() == "OFF":
        return None
    numeric = getattr(logging, level.upper(), None)
    if not isinstance(numeric, int):
        return logging.INFO
    return numeric


def setup_logging(
    console_level: str = "INFO",
    log_file: str | None = None,
    file_level: str = "DEBUG",
) -> None:
    """Configure logging for the application.

    Two independent outputs are supported, each with its own level:

    * **Console** (stderr) – omits the timestamp when running under systemd
      (``JOURNAL_STREAM`` set) because journald already records it.
      Pass ``"OFF"`` as *console_level* to disable console output entirely.
    * **File** – always includes the timestamp regardless of environment.
      Only created when *log_file* is not ``None``.

    Args:
        console_level: Log level for stderr output, or ``"OFF"`` to disable.
        log_file: Optional path to a log file (parent dirs created automatically).
        file_level: Log level for the file handler.
    """
    root = logging.getLogger()
    root.handlers.clear()

    # -- console (stderr) handler --
    numeric_console = _parse_level(console_level)
    if numeric_console is not None:
        fmt = _SYSTEMD_FMT if _running_under_systemd() else _DEFAULT_FMT
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(numeric_console)
        console_handler.setFormatter(logging.Formatter(fmt, datefmt=_DEFAULT_DATEFMT))
        root.addHandler(console_handler)

    # -- file handler (always with timestamps) --
    if log_file is not None:
        numeric_file = _parse_level(file_level)
        if numeric_file is not None:
            file_path = Path(log_file)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(file_path))
            file_handler.setLevel(numeric_file)
            file_handler.setFormatter(logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))
            root.addHandler(file_handler)

    # Set root level to the minimum across active handlers so records reach them.
    if root.handlers:
        root.setLevel(min(h.level for h in root.handlers))
    else:
        root.setLevel(logging.WARNING)
