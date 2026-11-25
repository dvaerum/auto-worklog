"""Command hooks: run configured commands on events with a JSON payload on stdin."""

import json
import logging
import sys
import threading
import time

import pytest

from auto_worklog.hooks import HookConfig, HookRunner


def writer(path):
    """A command that stores its stdin and the event env var, one JSON object per run."""
    code = (
        "import json,os,sys;"
        "open(sys.argv[1],'a').write(json.dumps({'stdin':json.load(sys.stdin),'env_event':os.environ.get('AUTO_WORKLOG_EVENT')})+'\\n')"
    )
    return [sys.executable, "-c", code, str(path)]


def runs(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def runner(commands, timeout=10.0, **kwargs):
    return HookRunner(HookConfig(commands=commands, timeout=timeout), host="test-host", **kwargs)


def test_an_event_runs_its_commands_with_the_envelope_on_stdin(tmp_path):
    out = tmp_path / "out"
    hooks = runner({"day_summary": [writer(out)]})

    hooks.emit("day_summary", {"days": [{"date": "2026-11-25", "entries": []}]})
    assert hooks.flush(5)

    [run] = runs(out)
    payload = run["stdin"]
    assert payload["version"] == 1 and payload["event"] == "day_summary" and payload["host"] == "test-host"
    assert payload["days"] == [{"date": "2026-11-25", "entries": []}]
    assert "time" in payload
    assert run["env_event"] == "day_summary"


def test_only_configured_events_are_wanted(tmp_path):
    hooks = runner({"day_summary": [writer(tmp_path / "out")]})
    assert hooks.wants("day_summary") and not hooks.wants("screen_locked")


def test_an_unconfigured_event_does_not_even_compute_its_payload():
    calls = []
    hooks = runner({})
    hooks.emit("day_summary", lambda: calls.append(1) or {"days": []})
    assert hooks.flush(5) and calls == []


def test_commands_run_in_order_and_a_failure_does_not_stop_the_next(tmp_path, caplog):
    out = tmp_path / "out"
    failing = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    hooks = runner({"screen_locked": [failing, writer(out)]})

    with caplog.at_level(logging.WARNING):
        hooks.emit("screen_locked", {"state": "locked"})
        assert hooks.flush(5)

    assert len(runs(out)) == 1
    assert any("exit code 3" in r.getMessage() and "boom" in r.getMessage() for r in caplog.records)


def test_a_command_that_hangs_is_killed_after_the_timeout(tmp_path, caplog):
    out = tmp_path / "out"
    hanging = [sys.executable, "-c", "import time; time.sleep(30)"]
    hooks = runner({"screen_locked": [hanging, writer(out)]}, timeout=0.3)

    with caplog.at_level(logging.WARNING):
        started = time.monotonic()
        hooks.emit("screen_locked", {})
        assert hooks.flush(10)

    assert time.monotonic() - started < 8
    assert len(runs(out)) == 1
    assert any("timed out" in r.getMessage() for r in caplog.records)


def test_a_missing_executable_is_logged_not_raised(tmp_path, caplog):
    out = tmp_path / "out"
    hooks = runner({"screen_locked": [["/nonexistent/definitely-not-here"], writer(out)]})
    with caplog.at_level(logging.WARNING):
        hooks.emit("screen_locked", {})
        assert hooks.flush(5)
    assert len(runs(out)) == 1
    assert any("could not run" in r.getMessage() for r in caplog.records)


def test_emit_returns_immediately_while_the_command_runs_in_the_background(tmp_path):
    slow = [sys.executable, "-c", "import time; time.sleep(1)"]
    hooks = runner({"screen_locked": [slow]})
    started = time.monotonic()
    hooks.emit("screen_locked", {})
    assert time.monotonic() - started < 0.5  # did not wait for the command
    assert hooks.flush(10)


def test_a_payload_producer_runs_off_the_calling_thread(tmp_path):
    out = tmp_path / "out"
    seen = []
    hooks = runner({"day_summary": [writer(out)]})
    hooks.emit("day_summary", lambda: seen.append(threading.current_thread().name) or {"days": []})
    assert hooks.flush(5)
    assert seen and seen[0] != threading.current_thread().name


def test_a_producer_returning_none_skips_the_commands(tmp_path):
    out = tmp_path / "out"
    hooks = runner({"day_summary": [writer(out)]})
    hooks.emit("day_summary", lambda: None)
    assert hooks.flush(5) and runs(out) == []


def test_a_producer_that_raises_is_logged_and_later_events_still_run(tmp_path, caplog):
    out = tmp_path / "out"
    hooks = runner({"day_summary": [writer(out)]})

    def broken():
        raise RuntimeError("toggl is down")

    with caplog.at_level(logging.WARNING):
        hooks.emit("day_summary", broken)
        hooks.emit("day_summary", {"days": []})
        assert hooks.flush(5)

    assert len(runs(out)) == 1
    assert any("toggl is down" in r.getMessage() for r in caplog.records)


def test_pending_events_with_the_same_key_collapse_into_the_latest(tmp_path):
    out = tmp_path / "out"
    hooks = runner({"day_summary": [writer(out)]}, start_thread=False)

    for n in (1, 2, 3):
        hooks.emit("day_summary", {"n": n}, key="day_summary:2026-11-25")
    hooks.emit("day_summary", {"n": 99}, key="day_summary:2026-11-24")
    hooks.run_pending()

    assert [r["stdin"]["n"] for r in runs(out)] == [3, 99]  # latest per key, original order


def test_events_without_a_key_all_run(tmp_path):
    out = tmp_path / "out"
    hooks = runner({"screen_locked": [writer(out)]}, start_thread=False)
    hooks.emit("screen_locked", {"n": 1})
    hooks.emit("screen_locked", {"n": 2})
    hooks.run_pending()
    assert [r["stdin"]["n"] for r in runs(out)] == [1, 2]


def test_close_drains_what_is_pending(tmp_path):
    out = tmp_path / "out"
    hooks = runner({"screen_locked": [writer(out)]})
    hooks.emit("screen_locked", {})
    hooks.close(wait=5)
    assert len(runs(out)) == 1


def test_a_hooks_output_is_logged_so_it_ends_up_in_the_journal(tmp_path, caplog):
    echo = [sys.executable, "-c", "print('1 changed, 0 unchanged')"]
    hooks = runner({"screen_locked": [echo]})
    with caplog.at_level(logging.INFO):
        hooks.emit("screen_locked", {})
        assert hooks.flush(5)
    assert any("1 changed, 0 unchanged" in r.getMessage() for r in caplog.records)
