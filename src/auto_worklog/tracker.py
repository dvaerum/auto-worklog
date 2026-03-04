from __future__ import annotations
import logging
import os
from json import load as json_load, dump as json_dump
from pathlib import Path
from typing import Optional, Union, NamedTuple, List
import unittest
from socket import gethostname

import pendulum
from sortedcontainers import SortedDict, SortedKeysView, SortedValuesView, SortedItemsView

from .misc import ScreenState

logger = logging.getLogger(__name__)

_TRACKER = None
_LOAD_DAYS_BACK: int = 35


def pendulum_now() -> pendulum.DateTime:
    return pendulum.now()


class Entry(NamedTuple):
    datetime: pendulum.DateTime
    state: ScreenState


class Day:
    _entries: SortedDict[pendulum.DateTime, ScreenState]

    def __init__(self, raw_data=None) -> None:
        self._entries = SortedDict()
        if raw_data is not None:
            for date_time, microsecond, timezone, state in raw_data:
                dt = pendulum.parse(date_time, tz=timezone).replace(microsecond=microsecond)
                self._entries[dt] = ScreenState[state]

    def __getitem__(self, index_or_date_time: Union[int, pendulum.DateTime]) -> Optional[ScreenState]:
        if isinstance(index_or_date_time, int):
            return self._entries.values()[index_or_date_time]

        if not isinstance(index_or_date_time, pendulum.DateTime):
            raise TypeError(
                f'The parameter `data` should be a pendulum.DateTime object, '
                f'but got {type(index_or_date_time)}'
            )

        try:
            return self._entries[index_or_date_time]
        except KeyError:
            return None
        
    def __setitem__(self, date_time: pendulum.DateTime, screen_state: ScreenState) -> None:
        if not isinstance(date_time, pendulum.DateTime):
            raise TypeError(
                f'The parameter `data` should be a pendulum.DateTime object, '
                f'but got {type(date_time)}'
            )
        
        if not isinstance(screen_state, ScreenState):
            raise TypeError(
                f'The parameter `screen_state` should be a ScreenState object, '
                f'but got {type(screen_state)}'
            )

        self._entries[date_time] = screen_state

    def count_entries(self) -> int:
        return len(self._entries)

    def first_entry(self, state: ScreenState = None) -> Optional[Entry]:
        if len(self._entries) == 0:
            return None

        if state is None:
            key = self._entries.keys()[0]
            return Entry(key, self._entries[key])

        for _date_time, _state in self._entries.items():
            if state == _state:
                return Entry(_date_time, state)

        return None

    def last_entry(self, state: ScreenState = None) -> Optional[Entry]:
        if len(self._entries) == 0:
            return None

        if state is None:
            key = self._entries.keys()[-1]
            return Entry(key, self._entries[key])

        for _date_time, _state in reversed(self._entries.items()):
            if state == _state:
                return Entry(_date_time, state)

        return None

    def filter(
        self,
        state: ScreenState = None,
        start: pendulum.DateTime = None,
        end: pendulum.DateTime = None,
    ) -> SortedDict[pendulum.DateTime, ScreenState]:
        result = SortedDict()

        for _date_time, _state in self._entries.items():
            if state is not None and state != _state:
                continue

            if   start is not None and end is not None and not start <= _date_time <= end:
                continue

            elif start is not None and end is     None and not start <= _date_time:
                continue

            elif start is     None and end is not None and not          _date_time <= end:
                continue

            result[_date_time] = _state

        return result

    def dump(self):
        result = [
            [key.to_datetime_string(), key.microsecond, key.timezone_name, value.name]
            for key, value in self._entries.items()
        ]

        return result

    def __repr__(self):
        return f'{self.__class__.__name__} - entries counted: {self._entries.__len__()}'

    def keys(self):
        return self._entries.keys()

    def merge(self, day: Day):
        self._entries.update(day._entries)


class _ManyDays(Day):
    def __init__(self, entries: SortedDict[pendulum.DateTime, ScreenState]) -> None:
        super().__init__()
        self._entries = entries


class Days:
    _days: SortedDict[pendulum.Date, Day]

    def __init__(self, raw_data=None, load_days_back: int = _LOAD_DAYS_BACK) -> None:
        self._days = SortedDict()

        load_days_back_date = pendulum_now().subtract(days=load_days_back).date()
        if raw_data is not None:
            for date, day in raw_data.items():
                date_obj = pendulum.parse(date).date()
                if date_obj < load_days_back_date:
                    continue

                self._days[date_obj] = Day(day)

    def __getitem__(self, index_or_date: Union[int, pendulum.Date]) -> Optional[Day]:
        if type(index_or_date) == int:
            return self._days.values()[index_or_date]

        if not type(index_or_date) == pendulum.Date:
            raise TypeError(
                f'The parameter `data` should be a pendulum.Date object, '
                f'but got {type(index_or_date)}'
            )

        try:
            return self._days[index_or_date]
        except KeyError:
            day = Day()
            self._days[index_or_date] = day
            return day

    def __setitem__(self, date: pendulum.date, day: Day) -> None:
        if not type(date) == pendulum.Date:
            raise TypeError(
                f'The parameter `data` should be a pendulum.Date object, '
                f'but got {type(date)}'
            )
        
        if not type(day) == Day:
            raise TypeError(
                f'The parameter `day` should be a Day object, '
                f'but got {type(day)}'
            )

        self._days[date] = day

    def add_adds(self, days: Days):
        for date, day in days.items():
            if date in self._days:
                self._days[date].merge(day)
            else:
                self._days[date] = day

    def count_days(self) -> int:
        return len(self._days)

    def today(self) -> Day:
        return self[pendulum_now().date()]

    def yesterday(self) -> Day:
        return self[pendulum_now().subtract(days=1).date()]

    def dump(self):
        result = {
            key.to_date_string(): value.dump() for key, value in self._days.items()
        }

        return result

    def __repr__(self):
        return f'{self.__class__.__name__} - days counted: {self._days.__len__()}'

    def __iter__(self):
        return iter(self._days)

    def merge(self, days: Days) -> None:
        for date, day in days.items():
            if date in self._days:
                self._days[date].merge(day)
            else:
                self._days[date] = day

    def keys(self) -> SortedKeysView[pendulum.Date]:
        # noinspection PyTypeChecker
        return self._days.keys()

    def values(self) -> SortedValuesView[Day]:
        # noinspection PyTypeChecker
        return self._days.values()

    def items(self) -> SortedItemsView[pendulum.Date, Day]:
        # noinspection PyTypeChecker
        return self._days.items()


class _Tracker:
    _store_tracking: bool
    file_name: str
    folder_path: Path
    file_path: Path

    _days: Days
    _only_local_days: Days

    def __init__(self, store_tracking: bool = True, cache_file: Path = None) -> None:
        self._days = Days()
        self._only_local_days = Days()

        if cache_file is None:
            self.file_name = f'{gethostname()}.json'
            self.folder_path = Path.home().joinpath('.cache').joinpath('auto-worklog')
            self.file_path = self.folder_path.joinpath(self.file_name)
        else:
            self.file_name = cache_file.name
            self.folder_path = cache_file.parent
            self.file_path = cache_file

        self._store_tracking = store_tracking
        if self._store_tracking:
            self._days = self._load()
            self._only_local_days = self._load(only_local=True)

    def trigger_screen_locked(self) -> None:
        self._trigger_screen_state(ScreenState.LOCKED)

    def trigger_screen_unlocked(self) -> None:
        self._trigger_screen_state(ScreenState.UNLOCKED)

    def _trigger_screen_state(self, screen_state: ScreenState) -> None:
        logger.info("Screen %s", screen_state.name)
        self._only_local_days.today()[pendulum_now()] = screen_state

        self.save()

    def _load(self, only_local: bool = False) -> Days:
        if self._store_tracking:
            if not self.folder_path.exists():
                logger.debug("_load: cache folder does not exist, returning empty Days")
                return Days()

            days = Days()
            if self.file_path.exists():
                with open(self.file_path, 'r') as file_obj:
                    raw_data = json_load(file_obj)
                    days = Days(raw_data)
                    logger.debug("_load: loaded %d days from %s", days.count_days(), self.file_path.name)

            if only_local:
                return days

            # Merge data from other hosts
            other_hosts = [p for p in self.folder_path.glob('*.json') if p.name != self.file_name]
            logger.debug("_load: merging data from %d other host(s)", len(other_hosts))
            
            for tracker_from_another_host in other_hosts:
                days_from_another_host = None
                try:
                    with open(tracker_from_another_host, 'r') as file:
                        raw_data = json_load(file)
                        days_from_another_host = Days(raw_data)
                        logger.debug("_load: merged %d days from %s", 
                                     days_from_another_host.count_days(), tracker_from_another_host.name)
                except Exception as e:
                    logger.warning("Error loading file %s: %s", tracker_from_another_host, e)
                    continue
                days.add_adds(days_from_another_host)

            return days

        return Days()

    def save(self) -> None:
        if self._store_tracking:
            if not self.folder_path.exists():
                logger.debug("save: creating cache folder %s", self.folder_path)
                self.folder_path.mkdir(parents=True)

            logger.debug("save: writing %d days to %s", self._only_local_days.count_days(), self.file_path.name)
            with open(self.file_path, 'w') as file:
                json_dump(self._only_local_days.dump(), file, indent=4, default=_json_dump_default)

            days = self._load()
            self._days = days

    def from_today_only(self) -> Day:
        return self._days.today()

    def from_yesterday_only(self) -> Day:
        return self._days.yesterday()

    def from_yesterday_and_backwards(self):
        entries = SortedDict()
        for date, value in self._days.items():
            if date == pendulum_now().date():
                continue

            entries.update(value)

        many_days = _ManyDays(entries)
        return many_days

    def get_day(self, day) -> Day:
        return self._days[day]

    def get_days(self) -> List[Day]:
        return list(self._days.keys())

    def __repr__(self):
        return f'<{self.__class__.__name__}: {self.file_path}>'


def _json_dump_default(*args, **kwargs):
    raise TypeError(
        f'Support for object of type {args} or {kwargs} is not implemented, yet!'
    )


def Tracker(store_tracking: bool = None) -> _Tracker:
    global _TRACKER

    if _TRACKER is None:
        if store_tracking is None:
            _TRACKER = _Tracker()
        else:
            _TRACKER = _Tracker(store_tracking=store_tracking)

    return _TRACKER


class TestTracker(unittest.TestCase):
    def test_trigger_screen_locked(self) -> None:
        tracker = _Tracker(store_tracking=False)
        tracker.trigger_screen_locked()
        tracker.trigger_screen_unlocked()

        self.assertEqual(
            1,
            tracker._days.count_days(),
        )
        self.assertEqual(
            2,
            tracker.from_today_only().count_entries(),
        )
        self.assertEqual(
            ScreenState.LOCKED,
            tracker.from_today_only()[0],
        )
        self.assertEqual(
            ScreenState.UNLOCKED,
            tracker.from_today_only()[1],
        )

    def test_first_last_entry(self) -> None:
        tracker = _Tracker(store_tracking=False)
        now = pendulum_now()
        minute_later_10 = now.add(minutes=10)
        minute_earlier_10 = now.subtract(minutes=10)
        hour_earlier_1 = now.subtract(hours=1)

        self.assertIsNone(tracker.from_today_only().first_entry())
        self.assertIsNone(tracker.from_today_only().first_entry(state=ScreenState.LOCKED))
        self.assertIsNone(tracker.from_today_only().first_entry(state=ScreenState.UNLOCKED))
        self.assertIsNone(tracker.from_today_only().last_entry())
        self.assertIsNone(tracker.from_today_only().last_entry(state=ScreenState.LOCKED))
        self.assertIsNone(tracker.from_today_only().last_entry(state=ScreenState.UNLOCKED))

        tracker.from_today_only()._entries[hour_earlier_1] = ScreenState.LOCKED
        tracker.from_today_only()._entries[minute_earlier_10] = ScreenState.UNLOCKED
        tracker.from_today_only()._entries[now] = ScreenState.LOCKED
        tracker.from_today_only()._entries[minute_later_10] = ScreenState.UNLOCKED
        self.assertEqual(
            Entry(hour_earlier_1, ScreenState.LOCKED),
            tracker.from_today_only().first_entry(),
        )
        self.assertEqual(
            Entry(hour_earlier_1, ScreenState.LOCKED),
            tracker.from_today_only().first_entry(state=ScreenState.LOCKED),
        )
        self.assertEqual(
            Entry(minute_earlier_10, ScreenState.UNLOCKED),
            tracker.from_today_only().first_entry(state=ScreenState.UNLOCKED),
        )

        self.assertEqual(
            Entry(minute_later_10, ScreenState.UNLOCKED),
            tracker.from_today_only().last_entry(),
        )
        self.assertEqual(
            Entry(now, ScreenState.LOCKED),
            tracker.from_today_only().last_entry(state=ScreenState.LOCKED),
        )
        self.assertEqual(
            Entry(minute_later_10, ScreenState.UNLOCKED),
            tracker.from_today_only().last_entry(state=ScreenState.UNLOCKED),
        )

    def test_filter(self) -> None:
        tracker = _Tracker(store_tracking=False)

        now = pendulum_now()
        minute_later_10 = now.add(minutes=10)
        minute_earlier_10 = now.subtract(minutes=10)
        hour_later_1 = now.add(hours=1)
        hour_earlier_1 = now.subtract(hours=1)
        tracker.from_today_only()._entries[hour_earlier_1] = ScreenState.LOCKED
        tracker.from_today_only()._entries[minute_earlier_10] = ScreenState.UNLOCKED
        tracker.from_today_only()._entries[now] = ScreenState.LOCKED
        tracker.from_today_only()._entries[minute_later_10] = ScreenState.UNLOCKED
        tracker.from_today_only()._entries[hour_later_1] = ScreenState.LOCKED

        filter_10 = tracker.from_today_only().filter(
            state=ScreenState.LOCKED,
        )
        self.assertEqual({
            hour_earlier_1: ScreenState.LOCKED,
            now: ScreenState.LOCKED,
            hour_later_1: ScreenState.LOCKED,
        }, dict(filter_10))

        filter_20 = tracker.from_today_only().filter(
            start=now,
        )
        self.assertEqual({
            now: ScreenState.LOCKED,
            minute_later_10: ScreenState.UNLOCKED,
            hour_later_1: ScreenState.LOCKED,
        }, dict(filter_20))

        filter_21 = tracker.from_today_only().filter(
            start=now.add(minutes=1),
        )
        self.assertEqual({
            minute_later_10: ScreenState.UNLOCKED,
            hour_later_1: ScreenState.LOCKED,
        }, dict(filter_21))

        filter_30 = tracker.from_today_only().filter(
            end=now,
        )
        self.assertEqual({
            hour_earlier_1: ScreenState.LOCKED,
            minute_earlier_10: ScreenState.UNLOCKED,
            now: ScreenState.LOCKED,
        }, dict(filter_30))

        filter_31 = tracker.from_today_only().filter(
            end=now.subtract(minutes=1),
        )
        self.assertEqual({
            hour_earlier_1: ScreenState.LOCKED,
            minute_earlier_10: ScreenState.UNLOCKED,
        }, dict(filter_31))

    def test_filter_cache_file(self) -> None:
        cache_file = Path('/tmp/test_cache.json')
        if cache_file.exists():
            os.remove(cache_file)
        tracker1 = _Tracker(store_tracking=True, cache_file=cache_file)

        now = pendulum_now()
        minute_later_10 = now.add(minutes=10)
        minute_earlier_10 = now.subtract(minutes=10)
        hour_later_1 = now.add(hours=1)
        hour_earlier_1 = now.subtract(hours=1)
        tracker1.from_today_only()._entries[hour_earlier_1] = ScreenState.LOCKED
        tracker1.from_today_only()._entries[minute_earlier_10] = ScreenState.UNLOCKED
        tracker1.from_today_only()._entries[now] = ScreenState.LOCKED
        tracker1.from_today_only()._entries[minute_later_10] = ScreenState.UNLOCKED
        tracker1.from_today_only()._entries[hour_later_1] = ScreenState.LOCKED
        tracker1.save()

        tracker2 = _Tracker(store_tracking=True, cache_file=cache_file)

        _t1_days = tracker1.get_days()
        _t2_days = tracker2.get_days()
        self.assertEqual(_t1_days, _t2_days)

        for index in range(_t1_days.__len__()):
            day = _t1_days[index]
            _t1_day = tracker1.get_day(day)
            _t2_day = tracker2.get_day(day)
            self.assertEqual(_t1_day._entries.__len__(), _t2_day._entries.__len__())
            for i in range(_t1_day._entries.__len__()):
                _t1_day_entry = _t1_day[i]
                _t2_day_entry = _t2_day[i]
                self.assertEqual(_t1_day[i], _t2_day[i])
