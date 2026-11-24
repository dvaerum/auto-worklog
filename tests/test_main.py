"""Trigger wrapper: a failing trigger is logged and swallowed, never fatal."""

import logging

from auto_worklog.__main__ import run_trigger
from auto_worklog.toggl_handler import TogglUnavailableError


def test_toggl_unavailable_is_a_warning_without_traceback(caplog):
    def trigger():
        raise TogglUnavailableError("no dns")

    with caplog.at_level(logging.DEBUG):
        run_trigger("unlock", trigger)  # must not raise

    [record] = [r for r in caplog.records if "unlock" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None


def test_unexpected_error_is_logged_with_traceback_and_swallowed(caplog):
    def trigger():
        raise RuntimeError("bug")

    with caplog.at_level(logging.DEBUG):
        run_trigger("unlock", trigger)  # must not raise

    [record] = [r for r in caplog.records if "unlock" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_successful_trigger_logs_nothing_above_debug(caplog):
    with caplog.at_level(logging.INFO):
        run_trigger("unlock", lambda: None)
    assert caplog.records == []
