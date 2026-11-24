"""journald integration: real PRIORITY, one entry per record, quiet libraries."""

import logging
import socket
import struct
import sys

import pytest

from auto_worklog import logging_config
from auto_worklog.logging_config import JournalHandler, setup_logging


def parse_journal_datagram(data: bytes) -> dict:
    """Decode journald's native protocol (the receiving side of JournalHandler)."""
    fields, pos = {}, 0
    while pos < len(data):
        eol = data.index(b"\n", pos)
        line = data[pos:eol]
        if b"=" in line:
            key, _, value = line.partition(b"=")
            pos = eol + 1
        else:
            (size,) = struct.unpack("<Q", data[eol + 1 : eol + 9])
            key, value = line, data[eol + 9 : eol + 9 + size]
            pos = eol + 9 + size + 1
        fields[key.decode()] = value.decode()
    return fields


@pytest.fixture
def journal_socket(tmp_path):
    path = str(tmp_path / "journal.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(path)
    server.settimeout(2)
    yield server, path
    server.close()


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    levels = {n: logging.getLogger(n).level for n in ("urllib3", "toggl")}
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, lvl in levels.items():
        logging.getLogger(name).setLevel(lvl)


def _emit(path, level, msg, *args, exc_info=None):
    logger = logging.getLogger("t.emit")
    handler = JournalHandler(path, identifier="auto-worklog")
    handler.setFormatter(logging.Formatter(logging_config._SYSTEMD_FMT))
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.log(level, msg, *args, exc_info=exc_info)


@pytest.mark.parametrize(
    "level, priority",
    [
        (logging.DEBUG, "7"),
        (logging.INFO, "6"),
        (logging.WARNING, "4"),
        (logging.ERROR, "3"),
        (logging.CRITICAL, "2"),
    ],
)
def test_priority_matches_python_level(journal_socket, level, priority):
    server, path = journal_socket
    _emit(path, level, "hello %s", "world")
    fields = parse_journal_datagram(server.recv(65536))
    assert fields["PRIORITY"] == priority
    assert fields["SYSLOG_IDENTIFIER"] == "auto-worklog"
    assert fields["MESSAGE"] == "[%s] t.emit - hello world" % logging.getLevelName(level)


def test_traceback_is_one_entry(journal_socket):
    server, path = journal_socket
    try:
        raise ValueError("boom")
    except ValueError:
        _emit(path, logging.ERROR, "trigger failed", exc_info=sys.exc_info())

    fields = parse_journal_datagram(server.recv(65536))
    assert fields["PRIORITY"] == "3"
    assert "Traceback (most recent call last):" in fields["MESSAGE"]
    assert "ValueError: boom" in fields["MESSAGE"]
    server.settimeout(0.2)
    with pytest.raises(socket.timeout):  # nothing else was sent
        server.recv(65536)


def test_setup_under_systemd_uses_journal_not_stderr(journal_socket, monkeypatch):
    _server, path = journal_socket
    monkeypatch.setenv("JOURNAL_STREAM", "8:12345")
    monkeypatch.setattr(logging_config, "JOURNAL_SOCKET", path)

    setup_logging(console_level="INFO")

    kinds = [type(h) for h in logging.getLogger().handlers]
    assert JournalHandler in kinds
    assert logging.StreamHandler not in kinds


def test_setup_falls_back_to_stderr_without_journal_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("JOURNAL_STREAM", "8:12345")
    monkeypatch.setattr(logging_config, "JOURNAL_SOCKET", str(tmp_path / "missing.sock"))

    setup_logging(console_level="INFO")

    kinds = [type(h) for h in logging.getLogger().handlers]
    assert JournalHandler not in kinds
    assert logging.StreamHandler in kinds


def test_setup_outside_systemd_keeps_stderr(monkeypatch):
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    setup_logging(console_level="INFO")
    assert [type(h) for h in logging.getLogger().handlers] == [logging.StreamHandler]


def test_noisy_libraries_stay_quiet_even_at_debug(monkeypatch):
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    setup_logging(console_level="DEBUG")
    assert logging.getLogger("urllib3").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("toggl").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("auto_worklog").getEffectiveLevel() == logging.DEBUG
