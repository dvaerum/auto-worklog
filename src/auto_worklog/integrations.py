"""When auto-worklog tells other tools about things.

The decisions live here, the mechanics in :mod:`hooks` and the arithmetic in
:mod:`worklog`:

* every screen lock emits ``screen_locked`` and today's ``day_summary``;
* the first unlock of the day emits ``screen_unlocked`` and the *final* summary of the last
  working day (the day of the last lock before today, so weekends are covered);
* every other unlock only emits ``screen_unlocked``.

A summary is cheap to repeat because whatever consumes it is expected to be idempotent
(``bit sync`` is), so it is sent after each lock instead of trying to guess when the day
really ended; requests for the same day that are still queued collapse into one.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Optional, Protocol, Sequence

import pendulum

from .config import AppConfig
from .hooks import HookRunner
from .worklog import MappingConfig, WorkEntry, summarize_day

logger = logging.getLogger(__name__)


class TrackerView(Protocol):
    def unlocks_today(self) -> int: ...

    def last_lock_before_today(self) -> Optional[date]: ...


class Integrations:
    def __init__(
        self,
        runner: HookRunner,
        mapping: MappingConfig,
        entries_for: Callable[[date], Optional[Sequence[WorkEntry]]],
        tracker: TrackerView,
        now: Callable[[], pendulum.DateTime] = pendulum.now,
    ) -> None:
        self._runner = runner
        self._mapping = mapping
        self._entries_for = entries_for
        self._tracker = tracker
        self._now = now

    # -- screen events ---------------------------------------------------------------------
    def on_screen_locked(self) -> None:
        at = self._now()
        self._runner.emit("screen_locked", {"state": "locked", "at": at.isoformat()})
        # The last working day is re-sent too: if its timer was fixed after the first unlock,
        # this is what carries the corrected total to the consumer (which is idempotent).
        last = self._tracker.last_lock_before_today() if self._runner.wants("day_summary") else None
        if last is not None and last != at.date():
            self._request_summary(last)
        self._request_summary(at.date())

    def on_screen_unlocked(self) -> None:
        at = self._now()
        self._runner.emit("screen_unlocked", {"state": "unlocked", "at": at.isoformat()})
        if self._tracker.unlocks_today() != 1:
            return
        last = self._tracker.last_lock_before_today()
        if last is not None:
            self._request_summary(last)

    # -- summaries --------------------------------------------------------------------------
    def _request_summary(self, day: date) -> None:
        # The lookup is a network call: it runs on the hook worker, and only if a hook wants it.
        self._runner.emit("day_summary", lambda: self.summary_payload([day]), key=f"day_summary:{day.isoformat()}")

    def summary_payload(
        self,
        days: Sequence[date],
        entries_for: Optional[Callable[[date], Optional[Sequence[WorkEntry]]]] = None,
    ) -> Optional[dict[str, Any]]:
        """The ``{"days": [...]}`` document for ``days``; None if the entries are unavailable."""
        lookup = entries_for or self._entries_for
        now = self._now()
        summaries = []
        for day in days:
            entries = lookup(day)
            if entries is None:  # offline mode: no token, nothing to report
                logger.debug("no time entries available for %s, skipping the summary", day)
                return None
            forgotten = [e for e in entries if e.stop is None and e.start.date() < now.date()]
            if forgotten:
                # A timer left running since an earlier day would be counted until midnight and
                # sent as a wrong total. Wait: a later lock re-sends once it has been stopped.
                logger.warning(
                    "a time entry started on %s is still running; not sending the summary for %s until it is stopped",
                    forgotten[0].start.date().isoformat(), day.isoformat(),
                )
                return None
            summaries.append(summarize_day(day, entries, self._mapping, now).to_dict())
        return {"days": summaries}

    def close(self, wait: float = 10.0) -> None:
        self._runner.close(wait)


class TrackerAdapter:
    """Reads the answers :class:`Integrations` needs from the screen lock tracker."""

    def __init__(self, tracker_factory: Callable[[], Any]) -> None:
        self._tracker_factory = tracker_factory

    def unlocks_today(self) -> int:
        from .tracker import ScreenState

        return len(self._tracker_factory().from_today_only().filter(state=ScreenState.UNLOCKED))

    def last_lock_before_today(self) -> Optional[date]:
        from .tracker import ScreenState

        entry = self._tracker_factory().from_yesterday_and_backwards().last_entry(ScreenState.LOCKED)
        return entry.datetime.date() if entry is not None else None


def parse_day(text: str, today: date) -> date:
    """``today``, ``yesterday`` or ``YYYY-MM-DD``."""
    word = text.strip().lower()
    if word == "today":
        return today
    if word == "yesterday":
        return today - pendulum.duration(days=1)
    try:
        return date.fromisoformat(word)
    except ValueError:
        raise ValueError(f"not a day: {text!r} (use today, yesterday or YYYY-MM-DD)") from None


def build_integrations(
    config: AppConfig,
    *,
    tracker: TrackerView,
    toggl_factory: Callable[[], Any],
    now: Callable[[], pendulum.DateTime] = pendulum.now,
) -> Integrations:
    """Wire the hook runner, the mapping and the time entry source together."""
    return Integrations(
        HookRunner(config.hooks),
        config.mapping,
        lambda day: toggl_factory().get_work_entries(day),
        tracker,
        now,
    )
