"""Every host's *.json in the cache folder is read; only this host's own file is written."""

import json

import pendulum
import pytest

from auto_worklog import tracker as tracker_module
from auto_worklog.tracker import _Tracker


def _entry_count(path) -> int:
    """Number of lock/unlock entries stored in one cache file."""
    return sum(len(day) for day in json.loads(path.read_text()).values())


@pytest.fixture
def clock(monkeypatch):
    """Deterministic, strictly increasing 'now' so every entry has its own key."""
    state = {"now": pendulum.now().start_of("day").add(hours=8)}

    def fake_now():
        state["now"] = state["now"].add(minutes=5)
        return state["now"]

    monkeypatch.setattr(tracker_module, "pendulum_now", fake_now)


def test_reads_other_hosts_but_saves_only_its_own(tmp_path, clock):
    laptop = _Tracker(cache_file=tmp_path / "laptop.json")
    laptop.trigger_screen_locked()
    laptop.trigger_screen_unlocked()
    laptop_json_before = (tmp_path / "laptop.json").read_text()

    desktop = _Tracker(cache_file=tmp_path / "desktop.json")
    assert desktop.from_today_only().count_entries() == 2  # the laptop's, read

    desktop.trigger_screen_locked()

    # evaluates over both hosts ...
    assert desktop.from_today_only().count_entries() == 3
    # ... but writes only its own entry, and never touches the other file
    assert _entry_count(tmp_path / "desktop.json") == 1
    assert (tmp_path / "laptop.json").read_text() == laptop_json_before


def test_every_json_in_the_folder_is_read_whatever_its_name(tmp_path, clock):
    for name in ("old-hostname.json", "laptop.json"):
        other = _Tracker(cache_file=tmp_path / name)
        other.trigger_screen_unlocked()

    mine = _Tracker(cache_file=tmp_path / "desktop.json")

    assert mine.from_today_only().count_entries() == 2
    assert not (tmp_path / "desktop.json").exists()  # reading alone creates nothing


def test_unreadable_file_from_another_host_is_skipped(tmp_path, clock):
    (tmp_path / "broken.json").write_text("{not json")
    good = _Tracker(cache_file=tmp_path / "laptop.json")
    good.trigger_screen_unlocked()

    mine = _Tracker(cache_file=tmp_path / "desktop.json")

    assert mine.from_today_only().count_entries() == 1
