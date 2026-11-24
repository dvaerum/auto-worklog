import functools
import logging
import unittest
from enum import Enum
from time import sleep
from typing import Optional, List

import pendulum
import requests

# noinspection PyUnresolvedReferences
from toggl import api, utils, exceptions

from .notification import Notifications

logger = logging.getLogger(__name__)

_TOGGL_HANDLER = None

_NETWORK_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)


class TogglUnavailableError(Exception):
    """Toggl could not be reached (no network, DNS failure, timeout).

    Raised instead of exiting: a dead process is restarted by systemd and
    fails the same way again, over and over, for as long as the network is down.
    """


class TokenStatus(Enum):
    VALID = "valid"
    INVALID = "invalid"  # Toggl answered 401/403: the user has to act
    UNREACHABLE = "unreachable"  # no answer or a server error: retrying later may work
    MISSING = "missing"


def _unavailable_when_offline(method):
    """Turn network failures of a Toggl API call into TogglUnavailableError."""

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except _NETWORK_ERRORS as err:
            raise TogglUnavailableError(f"{method.__name__}: {err}") from err

    return wrapper


class _TogglHandler:
    _offline_id: int

    _config: utils.Config

    _current_entry: Optional[api.TimeEntry]
    _entries: List[api.TimeEntry]

    def __init__(self, token: str = None) -> None:
        self._offline_id = 0

        self._config = utils.Config.factory()

        if token is None:
            self._config.api_token = None
        else:
            self._config.api_token = token

        self._current_entry = None
        self._entries = []

    def check_token(self) -> TokenStatus:
        """Check the Toggl API token with a lightweight API call."""
        token = self.get_token()
        if token is None:
            return TokenStatus.MISSING

        try:
            response = requests.get(
                "https://api.track.toggl.com/api/v9/me",
                auth=(token, "api_token"),
                timeout=10,
            )
        except requests.exceptions.RequestException as err:
            logger.debug("check_token: %s", err)
            return TokenStatus.UNREACHABLE

        if response.status_code == 200:
            return TokenStatus.VALID
        if response.status_code in (401, 403):
            return TokenStatus.INVALID
        return TokenStatus.UNREACHABLE

    def validate_token(self) -> bool:
        return self.check_token() is TokenStatus.VALID

    def set_token(self, token: str) -> None:
        self._config.api_token = token

    def get_token(self) -> str:
        return self._config.api_token

    @_unavailable_when_offline
    def get_current_entry(self) -> Optional[api.TimeEntry]:
        if self.get_token() is None:
            logger.debug("get_current_entry: offline mode, returning cached entry")
            return self._current_entry

        self._current_entry = api.TimeEntry.objects.current()
        logger.debug("get_current_entry: fetched from API, entry=%s", 
                     self._current_entry.id if self._current_entry else None)

        if self._current_entry not in self._entries:
            self._entries.append(self._current_entry)

        return self._current_entry

    @_unavailable_when_offline
    def _get_entries_started(self, date: pendulum.DateTime) -> List[api.TimeEntry]:
        _date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.get_token() is None:
            entries = [
                entry for entry in self._entries
                if entry.start.date() == date
            ]
            return entries

        self._entries = api.TimeEntry.objects.filter(start=_date, stop=_date.now())

        return self._entries

    def get_entries_started_today(self) -> List[api.TimeEntry]:
        today = pendulum.now()
        entries = self._get_entries_started(date=today)
        return entries

    def get_entries_started_today_count(self) -> int:
        return len(self.get_entries_started_today())

    @_unavailable_when_offline
    def _get_entries_stopped(self, date: pendulum.datetime) -> List[api.TimeEntry]:
        _date: pendulum.DateTime = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        if self.get_token() is None:
            entries = [
                entry for entry in self._entries
                if hasattr(entry, "stop") and entry.stop and entry.stop.date() == date
            ]
            return entries

        _entries = api.TimeEntry.objects.filter(
            start=pendulum.now().subtract(days=9),
            stop=date
        )
        entries = [
            entry for entry in _entries
            if hasattr(entry, "stop") and entry.stop and entry.stop.date() == _date.date()
        ]
        self._entries = entries
        return self._entries

    def get_entries_stopped_today(self) -> List[api.TimeEntry]:
        today = pendulum.now()
        entries = self._get_entries_stopped(date=today)
        return entries

    def get_entries_stopped_today_count(self) -> int:
        return len(self.get_entries_stopped_today())

    def _get_id(self) -> int:
        self._offline_id -= 1
        return self._offline_id

    @_unavailable_when_offline
    def start_entry(self, description: str, start_time: pendulum.duration = None) -> api.TimeEntry:
        current_entry = None

        if start_time is None:
            start = pendulum.now()
        else:
            start = start_time

        logger.debug("start_entry: description='%s', start=%s, offline=%s", 
                     description, start.to_datetime_string(), self.get_token() is None)

        if self.get_token() is None:
            stop = pendulum.from_timestamp(0)
        else:
            stop = None

        if self.get_token() is None:
            current_entry = _current_entry = api.TimeEntry(
                description=description,
                start=start,
                # duration=pendulum.duration(seconds=-int(pendulum.now().timestamp())),
                stop=stop,
            )
            current_entry.id = self._get_id()
            logger.debug("start_entry: created offline entry with id=%s", current_entry.id)
        else:
            _run = True
            while _run:
                try:
                    current_entry = api.TimeEntry.start_and_save(
                        description=description,
                        start=start,
                    )
                    logger.debug("start_entry: created API entry with id=%s", current_entry.id)
                    _run = False
                except exceptions.TogglServerException as err:
                    logger.error("Toggl (start_entry) - error: %s", err)
                    sleep(5)

        self._current_entry = current_entry
        if self._current_entry not in self._entries:
            self._entries.append(current_entry)

        return current_entry

    @_unavailable_when_offline
    def stop_current_entry(self, stop_time: pendulum.datetime) -> api.TimeEntry:
        if stop_time is None:
            stop_time = pendulum.now()

        current_entry = self.get_current_entry()
        logger.debug("stop_current_entry: entry=%s, stop=%s, offline=%s",
                     current_entry.id if current_entry else None,
                     stop_time.to_datetime_string(), self.get_token() is None)

        if self.get_token() is None:
            current_entry.stop = stop_time
            self._current_entry = None
            logger.debug("stop_current_entry: stopped offline entry")
        else:
            # Check for offline id and remove it if it exists
            if current_entry.id < 0:
                self._current_entry.id = None

            _run = True
            while _run:
                try:
                    if current_entry.start > stop_time:
                        Notifications().send_notification(
                            title="Error: Stop time < Start time",
                            message="The stop time cannot be less then the start time, "
                                    "something went wrong and your need to manually set the stop time "
                                    "of the current Toggl entry"
                        )
                    else:
                        current_entry.stop_and_save(stop_time)
                        logger.info("Stopped time entry (%s), at %s",
                                    current_entry.id,
                                    current_entry.stop.to_datetime_string())
                    _run = False
                except exceptions.TogglServerException as err:
                    logger.error("Toggl (stop_current_entry) - error: %s", err)
                    sleep(5)

        return current_entry


def TogglHandler(token: str = None) -> _TogglHandler:
    global _TOGGL_HANDLER

    if _TOGGL_HANDLER is None:
        if token is None:
            _TOGGL_HANDLER = _TogglHandler()
        else:
            _TOGGL_HANDLER = _TogglHandler(token=token)

    else:
        if token is not None:
            _TOGGL_HANDLER.set_token(token)

    return _TOGGL_HANDLER


class TestTogglHandler(unittest.TestCase):
    def test_get_current_entry(self) -> None:
        toggl_handler = _TogglHandler()
        active_entry = toggl_handler.get_current_entry()

        self.assertIsNone(active_entry)

    def test_get_active_started_today(self) -> None:
        toggl_handler = _TogglHandler()
        active_entries = toggl_handler.get_entries_started_today()

        self.assertEqual([], active_entries)

        entry = toggl_handler.start_entry('test')
        toggl_handler.stop_current_entry()
        self.assertEqual([entry], toggl_handler.get_entries_started_today())

    def test_get_active_started_today_count(self) -> None:
        toggl_handler = _TogglHandler()
        active_entries_count = toggl_handler.get_entries_started_today_count()

        self.assertEqual(0, active_entries_count)

    def test_start_entry(self) -> None:
        toggl_handler = _TogglHandler()
        entry = toggl_handler.start_entry('test')

        self.assertEqual(toggl_handler._current_entry, entry)

        self.assertIn(entry, toggl_handler._entries)

    def test_stop_current_entry(self) -> None:
        toggl_handler = _TogglHandler()
        entry = toggl_handler.start_entry('test')
        stopped_entry = toggl_handler.stop_current_entry()

        self.assertEqual(entry, stopped_entry)
        self.assertIsNone(toggl_handler._current_entry)

        self.assertIn(stopped_entry, toggl_handler.get_entries_started_today())
