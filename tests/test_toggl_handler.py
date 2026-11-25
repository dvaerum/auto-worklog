"""Toggl being unreachable must never take the whole process down.

Regression: on 2026-11-11/12 a ConnectionError inside _get_entries_started
called exit(1) without logging anything.  systemd restarted the service every
~20 s for 14 hours (2,334 restarts).
"""

import requests
import pytest
from toggl import api

from auto_worklog import toggl_handler
from auto_worklog.toggl_handler import TogglHandler, TogglUnavailableError, TokenStatus


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _patch_get(monkeypatch, result):
    def fake_get(*_args, **_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(toggl_handler.requests, "get", fake_get)


@pytest.mark.parametrize(
    "result, expected",
    [
        (_Response(200), TokenStatus.VALID),
        (_Response(401), TokenStatus.INVALID),
        (_Response(403), TokenStatus.INVALID),
        (_Response(500), TokenStatus.UNREACHABLE),
        (_Response(503), TokenStatus.UNREACHABLE),
        (requests.exceptions.ConnectionError("no dns"), TokenStatus.UNREACHABLE),
        (requests.exceptions.Timeout("slow"), TokenStatus.UNREACHABLE),
    ],
)
def test_check_token_tells_invalid_from_unreachable(monkeypatch, result, expected):
    _patch_get(monkeypatch, result)
    assert TogglHandler(token="t").check_token() is expected


def test_check_token_without_token_is_missing():
    assert TogglHandler().check_token() is TokenStatus.MISSING


def test_validate_token_stays_a_bool(monkeypatch):
    _patch_get(monkeypatch, _Response(200))
    assert TogglHandler(token="t").validate_token() is True
    _patch_get(monkeypatch, _Response(401))
    assert TogglHandler(token="t").validate_token() is False


def test_unreachable_entries_lookup_raises_instead_of_exiting(monkeypatch):
    def boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("no dns")

    monkeypatch.setattr(api.TimeEntry.objects, "filter", boom)

    with pytest.raises(TogglUnavailableError):  # not SystemExit
        TogglHandler(token="t").get_entries_started_today()


def test_unreachable_current_entry_raises_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("no dns")

    monkeypatch.setattr(api.TimeEntry.objects, "current", boom)

    with pytest.raises(TogglUnavailableError):
        TogglHandler(token="t").get_current_entry()


def test_unreachable_stopped_lookup_raises_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(api.TimeEntry.objects, "filter", boom)

    with pytest.raises(TogglUnavailableError):
        TogglHandler(token="t").get_entries_stopped_today()


def test_unreachable_start_entry_raises_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("no dns")

    monkeypatch.setattr(api.TimeEntry, "start_and_save", staticmethod(boom))

    with pytest.raises(TogglUnavailableError):
        TogglHandler(token="t").start_entry("work")


def test_retry_sleep_really_sleeps():
    """`from asyncio import sleep` returned an un-awaited coroutine, so the
    5 s pause between retries was a no-op and failures spun in a hot loop."""
    import inspect

    assert not inspect.iscoroutinefunction(toggl_handler.sleep)


# -- entries for the day summary -------------------------------------------------------------
class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_work_entries_are_plain_values_with_project_name_tags_and_description(monkeypatch):
    import pendulum
    from auto_worklog.worklog import WorkEntry

    start = pendulum.datetime(2026, 11, 25, 8, 0, tz="Europe/Copenhagen")
    fakes = [
        _Obj(start=start, stop=start.add(hours=2), description="planning", project=_Obj(name="Alpha"), tags={"b", "a"}),
        _Obj(start=start.add(hours=3), stop=None, description=None, project=None, tags=None),
    ]
    seen = {}

    def fake_filter(**conditions):
        seen.update(conditions)
        return fakes

    monkeypatch.setattr(api.TimeEntry.objects, "filter", fake_filter)

    entries = TogglHandler(token="t").get_work_entries(pendulum.date(2026, 11, 25))

    assert entries == [
        WorkEntry(start=start, stop=start.add(hours=2), description="planning", project="Alpha", tags=("a", "b")),
        WorkEntry(start=start.add(hours=3), stop=None, description="", project=None, tags=()),
    ]
    # the window starts a day early so an entry that began the evening before is seen too
    assert seen["start"] == pendulum.datetime(2026, 11, 24, tz=start.timezone)
    assert seen["stop"] == pendulum.datetime(2026, 11, 26, tz=start.timezone)


def test_work_entries_in_offline_mode_are_none_not_an_empty_day():
    import pendulum

    assert TogglHandler().get_work_entries(pendulum.date(2026, 11, 25)) is None


def test_work_entries_while_unreachable_raise_unavailable(monkeypatch):
    import pendulum

    def boom(**_):
        raise requests.exceptions.ConnectionError("no dns")

    monkeypatch.setattr(api.TimeEntry.objects, "filter", boom)
    with pytest.raises(TogglUnavailableError):
        TogglHandler(token="t").get_work_entries(pendulum.date(2026, 11, 25))
