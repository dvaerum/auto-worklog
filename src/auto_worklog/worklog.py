"""Turn a day's time entries into one total per project, ready to hand to other tools.

Auto-worklog knows entries (what you worked on, from Toggl); other tools want totals per
project and day. This module maps each entry to a *project label* using configured rules and
merges the entries of the same label: one project all day gives one entry, task switching
across projects gives one entry per project. The label is an opaque string; whatever consumes
the summary decides what it means (for ``bit sync`` it is a BIT project code).
"""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Sequence

import pendulum

# Entries auto-worklog creates itself carry this description; it says nothing about the work.
DEFAULT_IGNORED_DESCRIPTIONS = ("Working",)


@dataclass(frozen=True)
class WorkEntry:
    """One time entry, independent of where it came from."""

    start: pendulum.DateTime
    stop: pendulum.DateTime | None  # None: still running
    description: str = ""
    project: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    """Maps entries to ``project``; every condition given must hold (project names and tags
    compare ignoring case, ``description`` is a regular expression searched in the text)."""

    project: str
    toggl_project: str | None = None
    description: str | None = None
    tag: str | None = None
    _pattern: re.Pattern | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.project.strip():
            raise ValueError("a rule needs a target project")
        if self.toggl_project is None and self.description is None and self.tag is None:
            raise ValueError(
                f"the rule for {self.project!r} has no condition; give toggl_project, description or tag "
                "(use default_project for 'everything else')"
            )
        if self.description is not None:
            try:
                object.__setattr__(self, "_pattern", re.compile(self.description))
            except re.error as err:
                raise ValueError(f"the rule for {self.project!r} has an invalid description pattern: {err}") from err

    def matches(self, entry: WorkEntry) -> bool:
        if self.toggl_project is not None and (entry.project or "").strip().lower() != self.toggl_project.strip().lower():
            return False
        if self._pattern is not None and not self._pattern.search(entry.description or ""):
            return False
        if self.tag is not None and self.tag.strip().lower() not in {t.strip().lower() for t in entry.tags}:
            return False
        return True


@dataclass(frozen=True)
class MappingConfig:
    rules: tuple[Rule, ...] = ()
    default_project: str | None = None
    comments: str = "descriptions"  # or "none"
    ignore_descriptions: tuple[str, ...] = DEFAULT_IGNORED_DESCRIPTIONS

    def __post_init__(self) -> None:
        if self.comments not in ("descriptions", "none"):
            raise ValueError(f"comments must be 'descriptions' or 'none', not {self.comments!r}")

    def project_for(self, entry: WorkEntry) -> str | None:
        for rule in self.rules:
            if rule.matches(entry):
                return rule.project
        return self.default_project


@dataclass(frozen=True)
class SummaryEntry:
    project: str
    minutes: int
    comment: str = ""


@dataclass(frozen=True)
class Unmapped:
    description: str
    project: str | None
    minutes: int


@dataclass(frozen=True)
class DaySummary:
    date: date
    complete: bool  # False while the day is still going: later entries may change it
    entries: list[SummaryEntry] = field(default_factory=list)
    unmapped: list[Unmapped] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "complete": self.complete,
            "entries": [{"project": e.project, "minutes": e.minutes, "comment": e.comment} for e in self.entries],
            "unmapped": [{"description": u.description, "project": u.project, "minutes": u.minutes} for u in self.unmapped],
        }


def _minutes(seconds: float) -> int:
    return math.floor(seconds / 60 + 0.5)  # half up, once per total


def summarize_day(day: date, entries: Sequence[WorkEntry], mapping: MappingConfig, now: pendulum.DateTime) -> DaySummary:
    """One total per mapped project for ``day`` (entries are clipped to that day, and an entry
    that is still running counts up to ``now``)."""
    day_start = pendulum.datetime(day.year, day.month, day.day, tz=now.timezone)
    day_end = day_start.add(days=1)
    ignored = {text.strip().lower() for text in mapping.ignore_descriptions}

    totals: OrderedDict[str, list] = OrderedDict()  # project -> [seconds, descriptions]
    orphans: OrderedDict[tuple[str, str | None], float] = OrderedDict()
    for entry in entries:
        start = max(entry.start, day_start)
        end = min(entry.stop or now, day_end)
        seconds = (end - start).total_seconds()
        if seconds <= 0:
            continue
        description = " ".join((entry.description or "").split())
        target = mapping.project_for(entry)
        if target is None:
            key = (description, entry.project)
            orphans[key] = orphans.get(key, 0) + seconds
            continue
        slot = totals.setdefault(target, [0.0, []])
        slot[0] += seconds
        if description and description.lower() not in ignored and description not in slot[1]:
            slot[1].append(description)

    summary_entries = []
    for project, (seconds, descriptions) in totals.items():
        minutes = _minutes(seconds)
        if minutes:
            comment = "; ".join(descriptions) if mapping.comments == "descriptions" else ""
            summary_entries.append(SummaryEntry(project, minutes, comment))
    unmapped = [Unmapped(description, project, _minutes(seconds)) for (description, project), seconds in orphans.items() if _minutes(seconds)]
    return DaySummary(date=day, complete=day < now.date(), entries=summary_entries, unmapped=unmapped)
