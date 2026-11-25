"""Mapping Toggl entries to project labels and merging them into one total per project and day."""

import pendulum
import pytest

from auto_worklog.worklog import MappingConfig, Rule, WorkEntry, summarize_day

TZ = "Europe/Copenhagen"
DAY = pendulum.date(2026, 11, 25)
NOW = pendulum.datetime(2026, 11, 26, 8, 0, tz=TZ)  # the morning after: DAY is complete


def at(hour, minute=0, day=25):
    return pendulum.datetime(2026, 11, day, hour, minute, tz=TZ)


def entry(start, stop, description="", project=None, tags=()):
    return WorkEntry(start=start, stop=stop, description=description, project=project, tags=tuple(tags))


MAPPING = MappingConfig(
    rules=(
        Rule(project="10", toggl_project="Alpha"),
        Rule(project="30", description=r"^support\b"),
        Rule(project="30", tag="internal"),
    ),
)


def kinds(summary):
    return {e.project: (e.minutes, e.comment) for e in summary.entries}


def test_one_project_all_day_is_one_total_entry_with_the_distinct_descriptions():
    summary = summarize_day(
        DAY,
        [
            entry(at(8), at(10), "planning", "Alpha"),
            entry(at(10, 30), at(12), "review", "Alpha"),
            entry(at(13), at(15), "planning", "Alpha"),
        ],
        MAPPING,
        NOW,
    )
    assert kinds(summary) == {"10": (330, "planning; review")}
    assert summary.date == DAY and summary.complete is True


def test_task_switching_across_projects_gives_one_entry_per_project():
    summary = summarize_day(
        DAY,
        [
            entry(at(8), at(9), "a", "Alpha"),
            entry(at(9), at(10), "support ticket 12"),
            entry(at(10), at(11), "b", "Alpha"),
            entry(at(11), at(11, 30), "retro", tags=["internal"]),
        ],
        MAPPING,
        NOW,
    )
    assert kinds(summary) == {"10": (120, "a; b"), "30": (90, "support ticket 12; retro")}
    assert [e.project for e in summary.entries] == ["10", "30"]  # order of first appearance


def test_the_first_matching_rule_wins_and_all_conditions_of_a_rule_must_hold():
    mapping = MappingConfig(
        rules=(
            Rule(project="1", toggl_project="Alpha", description="urgent"),
            Rule(project="2", toggl_project="Alpha"),
        )
    )
    summary = summarize_day(
        DAY,
        [entry(at(8), at(9), "urgent fix", "Alpha"), entry(at(9), at(10), "routine", "Alpha")],
        mapping,
        NOW,
    )
    assert kinds(summary) == {"1": (60, "urgent fix"), "2": (60, "routine")}


def test_project_names_match_ignoring_case_and_surrounding_space():
    mapping = MappingConfig(rules=(Rule(project="10", toggl_project="alpha"),))
    assert kinds(summarize_day(DAY, [entry(at(8), at(9), "", " ALPHA ")], mapping, NOW)) == {"10": (60, "")}


def test_unmatched_entries_go_to_the_default_project_when_there_is_one():
    mapping = MappingConfig(rules=MAPPING.rules, default_project="99")
    summary = summarize_day(DAY, [entry(at(8), at(9), "x", "Unknown")], mapping, NOW)
    assert kinds(summary) == {"99": (60, "x")} and summary.unmapped == []


def test_unmatched_entries_without_a_default_are_listed_not_sent():
    summary = summarize_day(
        DAY, [entry(at(8), at(9), "x", "Unknown"), entry(at(9), at(10), "y", "Alpha")], MAPPING, NOW
    )
    assert kinds(summary) == {"10": (60, "y")}
    [orphan] = summary.unmapped
    assert (orphan.description, orphan.project, orphan.minutes) == ("x", "Unknown", 60)


def test_a_running_entry_counts_up_to_now_and_the_day_is_not_complete():
    now = at(14, 30)
    summary = summarize_day(DAY, [entry(at(8), None, "w", "Alpha")], MAPPING, now)
    assert kinds(summary) == {"10": (390, "w")}
    assert summary.complete is False  # today is still going


def test_a_past_day_is_complete_even_if_an_entry_is_still_running():
    summary = summarize_day(DAY, [entry(at(8), None, "w", "Alpha")], MAPPING, NOW)
    # 08:00 to the end of that day: the running entry is clipped at midnight
    assert kinds(summary) == {"10": (16 * 60, "w")}
    assert summary.complete is True


def test_entries_are_clipped_to_the_day_at_midnight():
    summary = summarize_day(DAY, [entry(at(23, 0, day=24), at(1, 0), "night", "Alpha")], MAPPING, NOW)
    assert kinds(summary) == {"10": (60, "night")}  # only 00:00-01:00 belongs to the 25th
    earlier = summarize_day(pendulum.date(2026, 11, 24), [entry(at(23, 0, day=24), at(1, 0), "night", "Alpha")], MAPPING, NOW)
    assert kinds(earlier) == {"10": (60, "night")}


def test_entries_outside_the_day_are_ignored():
    summary = summarize_day(DAY, [entry(at(8, day=24), at(9, day=24), "x", "Alpha")], MAPPING, NOW)
    assert summary.entries == []


def test_rounding_happens_once_per_project_total_not_per_entry():
    entries = [entry(at(8, 0), at(8, 0).add(seconds=20), "a", "Alpha") for _ in range(3)]  # 3 x 20 s = 60 s
    assert kinds(summarize_day(DAY, entries, MAPPING, NOW)) == {"10": (1, "a")}


def test_half_a_minute_rounds_up_and_less_is_dropped():
    half = summarize_day(DAY, [entry(at(8), at(8).add(seconds=30), "a", "Alpha")], MAPPING, NOW)
    less = summarize_day(DAY, [entry(at(8), at(8).add(seconds=29), "a", "Alpha")], MAPPING, NOW)
    assert kinds(half) == {"10": (1, "a")} and less.entries == []


def test_auto_worklogs_own_default_description_is_not_sent_as_a_comment():
    summary = summarize_day(DAY, [entry(at(8), at(9), "Working", "Alpha"), entry(at(9), at(10), "design", "Alpha")], MAPPING, NOW)
    assert kinds(summary) == {"10": (120, "design")}


def test_comments_can_be_switched_off_or_the_ignore_list_changed():
    entries = [entry(at(8), at(9), "design", "Alpha")]
    none = MappingConfig(rules=MAPPING.rules, comments="none")
    assert kinds(summarize_day(DAY, entries, none, NOW)) == {"10": (60, "")}
    custom = MappingConfig(rules=MAPPING.rules, ignore_descriptions=("design",))
    assert kinds(summarize_day(DAY, entries, custom, NOW)) == {"10": (60, "")}


def test_the_payload_has_the_shape_bit_sync_reads():
    summary = summarize_day(DAY, [entry(at(8), at(9), "x", "Alpha"), entry(at(9), at(9, 10), "y", "Nope")], MAPPING, NOW)
    assert summary.to_dict() == {
        "date": "2026-11-25",
        "complete": True,
        "entries": [{"project": "10", "minutes": 60, "comment": "x"}],
        "unmapped": [{"description": "y", "project": "Nope", "minutes": 10}],
    }


def test_an_empty_day_has_no_entries_and_stays_a_valid_document():
    summary = summarize_day(DAY, [], MAPPING, NOW)
    assert summary.to_dict()["entries"] == [] and summary.to_dict()["unmapped"] == []


@pytest.mark.parametrize("kwargs", [{}, {"description": "["}])
def test_a_rule_needs_a_condition_and_a_valid_pattern(kwargs):
    with pytest.raises(ValueError):
        Rule(project="1", **kwargs)
