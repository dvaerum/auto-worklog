"""When auto-worklog tells other tools about things."""

import json
import logging
import sys

import pendulum
import pytest

from auto_worklog.hooks import HookConfig, HookRunner
from auto_worklog.integrations import Integrations
from auto_worklog.worklog import MappingConfig, Rule, WorkEntry

TZ = "Europe/Copenhagen"
NOW = pendulum.datetime(2026, 11, 25, 16, 0, tz=TZ)
TODAY = NOW.date()
YESTERDAY = pendulum.date(2026, 11, 24)

MAPPING = MappingConfig(rules=(Rule(project="10", toggl_project="Alpha"),))


def writer(path):
    code = "import sys; open(sys.argv[1],'a').write(sys.stdin.read().replace('\\n',' ')+'\\n')"
    return [sys.executable, "-c", code, str(path)]


def runs(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class FakeTracker:
    def __init__(self, unlocks_today=1, last_lock_day=YESTERDAY):
        self.unlocks, self.last_lock_day = unlocks_today, last_lock_day

    def unlocks_today(self):
        return self.unlocks

    def last_lock_before_today(self):
        return self.last_lock_day


def make(tmp_path, events=("screen_locked", "screen_unlocked", "day_summary"), tracker=None, entries=None):
    out = tmp_path / "out"
    runner = HookRunner(HookConfig(commands={e: [writer(out)] for e in events}), host="h", start_thread=False)
    asked = []

    def entries_for(day):
        asked.append(day)
        if callable(entries):
            return entries(day)
        return entries if entries is not None else [WorkEntry(pendulum.datetime(day.year, day.month, day.day, 8, tz=TZ), pendulum.datetime(day.year, day.month, day.day, 12, tz=TZ), "work", "Alpha")]

    integrations = Integrations(runner, MAPPING, entries_for, tracker or FakeTracker(), now=lambda: NOW)
    return integrations, runner, out, asked


def test_a_screen_lock_emits_the_lock_and_the_summaries_of_the_last_working_day_and_today(tmp_path):
    integrations, runner, out, _ = make(tmp_path)

    integrations.on_screen_locked()
    runner.run_pending()

    lock, previous, today = runs(out)
    assert lock["event"] == "screen_locked" and lock["state"] == "locked" and lock["at"] == NOW.isoformat()
    assert previous["event"] == "day_summary" and today["event"] == "day_summary"
    # re-sent on every lock so a correction made later (a forgotten timer fixed) still reaches the consumer
    assert previous["days"][0]["date"] == "2026-11-24" and previous["days"][0]["complete"] is True
    [day] = today["days"]
    assert day["date"] == "2026-11-25" and day["complete"] is False
    assert day["entries"] == [{"project": "10", "minutes": 240, "comment": "work"}]


def test_the_last_working_day_is_not_sent_twice_when_it_is_today(tmp_path):
    integrations, runner, out, _ = make(tmp_path, tracker=FakeTracker(last_lock_day=TODAY))
    integrations.on_screen_locked()
    runner.run_pending()
    assert [r["event"] for r in runs(out)] == ["screen_locked", "day_summary"]


def test_a_timer_still_running_from_before_today_blocks_the_summaries_with_a_warning(tmp_path, caplog):
    forgotten = [WorkEntry(pendulum.datetime(2026, 11, 24, 8, tz=TZ), None, "left on", "Alpha")]
    integrations, runner, out, _ = make(tmp_path, entries=forgotten)
    with caplog.at_level(logging.WARNING):
        integrations.on_screen_locked()
        runner.run_pending()
    assert [r["event"] for r in runs(out)] == ["screen_locked"]  # no wrong totals are sent
    assert any("still running" in r.getMessage() and "2026-11-24" in r.getMessage() for r in caplog.records)


def test_repeated_locks_collapse_into_one_summary_run(tmp_path):
    integrations, runner, out, asked = make(tmp_path, events=("day_summary",), tracker=FakeTracker(last_lock_day=TODAY))
    for _ in range(4):
        integrations.on_screen_locked()
    runner.run_pending()
    assert len(runs(out)) == 1 and len(asked) == 1  # one Toggl lookup, not four


def test_the_first_unlock_of_the_day_sends_the_last_working_days_final_summary(tmp_path):
    integrations, runner, out, asked = make(tmp_path, tracker=FakeTracker(unlocks_today=1, last_lock_day=pendulum.date(2026, 11, 20)))

    integrations.on_screen_unlocked()
    runner.run_pending()

    unlock, summary = runs(out)
    assert unlock["event"] == "screen_unlocked" and unlock["state"] == "unlocked"
    assert summary["days"][0]["date"] == "2026-11-20"  # last working day, not just "yesterday"
    assert summary["days"][0]["complete"] is True
    assert asked == [pendulum.date(2026, 11, 20)]


def test_later_unlocks_only_report_the_unlock(tmp_path):
    integrations, runner, out, asked = make(tmp_path, tracker=FakeTracker(unlocks_today=3))
    integrations.on_screen_unlocked()
    runner.run_pending()
    assert [r["event"] for r in runs(out)] == ["screen_unlocked"] and asked == []


def test_a_first_unlock_with_no_history_sends_no_summary(tmp_path):
    integrations, runner, out, asked = make(tmp_path, tracker=FakeTracker(unlocks_today=1, last_lock_day=None))
    integrations.on_screen_unlocked()
    runner.run_pending()
    assert [r["event"] for r in runs(out)] == ["screen_unlocked"] and asked == []


def test_nothing_is_looked_up_when_no_summary_hook_is_configured(tmp_path):
    integrations, runner, out, asked = make(tmp_path, events=("screen_locked",))
    integrations.on_screen_locked()
    runner.run_pending()
    assert [r["event"] for r in runs(out)] == ["screen_locked"] and asked == []


def test_offline_mode_sends_no_summary(tmp_path):
    integrations, runner, out, _ = make(tmp_path, events=("day_summary",), entries=lambda day: None)
    integrations.on_screen_locked()
    runner.run_pending()
    assert runs(out) == []


def test_toggl_failing_is_logged_and_does_not_break_the_other_events(tmp_path, caplog):
    def broken(day):
        raise RuntimeError("toggl unreachable")

    integrations, runner, out, _ = make(tmp_path, entries=broken)
    with caplog.at_level(logging.WARNING):
        integrations.on_screen_locked()
        runner.run_pending()

    assert [r["event"] for r in runs(out)] == ["screen_locked"]
    assert any("toggl unreachable" in r.getMessage() for r in caplog.records)


def test_a_day_with_only_unmapped_work_still_sends_the_document_with_the_orphans(tmp_path):
    other = [WorkEntry(pendulum.datetime(2026, 11, 25, 8, tz=TZ), pendulum.datetime(2026, 11, 25, 9, tz=TZ), "x", "Other")]
    integrations, runner, out, _ = make(tmp_path, events=("day_summary",), entries=other, tracker=FakeTracker(last_lock_day=TODAY))
    integrations.on_screen_locked()
    runner.run_pending()
    [summary] = runs(out)
    assert summary["days"][0]["entries"] == []
    assert summary["days"][0]["unmapped"] == [{"description": "x", "project": "Other", "minutes": 60}]


def test_summary_payload_for_explicit_days_is_the_document_bit_sync_reads(tmp_path):
    integrations, _, _, _ = make(tmp_path)
    payload = integrations.summary_payload([YESTERDAY, TODAY])
    assert [d["date"] for d in payload["days"]] == ["2026-11-24", "2026-11-25"]
    assert integrations.summary_payload([TODAY], entries_for=lambda d: None) is None


# -- building it from a config --------------------------------------------------------------------
def test_parse_day_accepts_words_and_iso_dates():
    from auto_worklog.integrations import parse_day

    assert parse_day("today", TODAY) == TODAY
    assert parse_day("yesterday", TODAY) == YESTERDAY
    assert parse_day("2026-11-20", TODAY) == pendulum.date(2026, 11, 20)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_day("25/11/2026", TODAY)


def test_build_integrations_uses_the_config_and_the_toggl_factory(tmp_path):
    from auto_worklog.config import parse_config
    from auto_worklog.integrations import build_integrations

    out = tmp_path / "out"
    config = parse_config(
        {"hooks": {"day_summary": [writer(out)]}, "summary": {"rules": [{"toggl_project": "Alpha", "project": "10"}]}}
    )

    class FakeToggl:
        def get_work_entries(self, day):
            return [WorkEntry(pendulum.datetime(day.year, day.month, day.day, 8, tz=TZ), pendulum.datetime(day.year, day.month, day.day, 9, tz=TZ), "x", "Alpha")]

    integrations = build_integrations(config, tracker=FakeTracker(last_lock_day=TODAY), toggl_factory=FakeToggl, now=lambda: NOW)
    assert integrations.summary_payload([TODAY])["days"][0]["entries"] == [{"project": "10", "minutes": 60, "comment": "x"}]
    integrations.close(1)
