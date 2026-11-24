"""Logging configuration for auto-worklog."""

import logging
import os
import socket
import struct
import sys
from pathlib import Path

_SYSTEMD_FMT = "[%(levelname)s] %(name)s - %(message)s"
_DEFAULT_FMT = "%(asctime)s " + _SYSTEMD_FMT
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

JOURNAL_SOCKET = "/run/systemd/journal/socket"

# syslog priorities, which is what journald's PRIORITY field (and so the
# `level` field downstream) is made of.
_JOURNAL_PRIORITY = {
    logging.DEBUG: 7,
    logging.INFO: 6,
    logging.WARNING: 4,
    logging.ERROR: 3,
    logging.CRITICAL: 2,
}

# Their DEBUG chatter (one line per HTTP request and per API call) buried the
# app's own logs: ~150k lines in two days during one outage.
_QUIET_LIBRARIES = ("urllib3", "toggl")


class JournalHandler(logging.Handler):
    """Send each record to journald's native socket as ONE entry.

    Writing to stdout instead makes journald split multi-line messages
    (tracebacks) into one entry per line, and gives every entry priority
    "info" regardless of the Python level.
    """

    def __init__(self, path: str = JOURNAL_SOCKET, identifier: str = "auto-worklog") -> None:
        super().__init__()
        self._path = path
        self._identifier = identifier
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    @staticmethod
    def _encode(fields: dict[str, str]) -> bytes:
        out = b""
        for key, value in fields.items():
            raw = value.encode("utf-8", "replace")
            if b"\n" in raw:
                # Binary-safe form: KEY \n <uint64 LE length> <value> \n
                out += key.encode() + b"\n" + struct.pack("<Q", len(raw)) + raw + b"\n"
            else:
                out += key.encode() + b"=" + raw + b"\n"
        return out

    def emit(self, record: logging.LogRecord) -> None:
        try:
            fields = {
                "PRIORITY": str(_JOURNAL_PRIORITY.get(record.levelno, 6)),
                "SYSLOG_IDENTIFIER": self._identifier,
                "MESSAGE": self.format(record),
            }
            self._socket.sendto(self._encode(fields), self._path)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        self._socket.close()
        super().close()


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

    # -- console handler: journald's native socket under systemd, else stderr --
    numeric_console = _parse_level(console_level)
    if numeric_console is not None:
        if _running_under_systemd() and os.path.exists(JOURNAL_SOCKET):
            console_handler: logging.Handler = JournalHandler(JOURNAL_SOCKET)
            fmt = _SYSTEMD_FMT
        else:
            console_handler = logging.StreamHandler(sys.stderr)
            fmt = _SYSTEMD_FMT if _running_under_systemd() else _DEFAULT_FMT
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

    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
