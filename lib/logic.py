from typing import NamedTuple

import pendulum

from .tracker import Tracker, ScreenState
from .notification import Notifications
from .toggl_handler import TogglHandler


def _if_yes_then_stop_toggl(msg_id: int, action_id: int) -> None:
    if action_id == 3:
        tracker = Tracker()
        entry = tracker.yesterday().last_entry(ScreenState.LOCKED)
        if entry is None:
            raise Exception("No entry found, cannot stop Toggle, implement handler for this case!!!")

        toggl_handler = TogglHandler()
        time_entry = toggl_handler.stop_current_entry(entry.datetime)
        print("{} [=] Logic - Stopped time entry ({}), at {}".format(
            pendulum.now().to_datetime_string(),
            time_entry.id,
            time_entry.stop.to_datetime_string(),
        ))


def _if_yes_then_start_toggl(msg_id: int, action_id: int) -> None:
    if action_id == 3:
        tracker = Tracker()
        entry = tracker.today().last_entry(ScreenState.UNLOCKED)
        if entry is None:
            raise Exception("No entry found, cannot start Toggle, implement handler for this case!!!")

        toggl_handler = TogglHandler()
        time_entry = toggl_handler.start_entry(
            description="Working",
            start_time=entry.datetime,
        )
        print("{} [=] Logic - Started time entry ({}), at {}".format(
            pendulum.now().to_datetime_string(),
            time_entry.id,
            time_entry.start.to_datetime_string(),
        ))


def _if_yes_then_start_toggl_for_the_1st_time_today(msg_id: int, action_id: int) -> None:
    if action_id == 3:
        tracker = Tracker()
        entry = tracker.today().first_entry(ScreenState.UNLOCKED)
        if entry is None:
            raise Exception("No entry found, cannot start Toggle, implement handler for this case!!!")

        toggl_handler = TogglHandler()
        time_entry = toggl_handler.start_entry(
            description="Working",
            start_time=entry.datetime.subtract(minutes=5),
        )
        print("{} [=] Logic - Started time entry ({}), at {}".format(
            pendulum.now().to_datetime_string(),
            time_entry.id,
            time_entry.start.to_datetime_string(),
        ))


def first_unlock_today() -> None:
    tracker = Tracker()
    toggl_handler = TogglHandler()
    notifications = Notifications()

    if tracker.today().filter(state=ScreenState.UNLOCKED).__len__() > 1 \
            and toggl_handler.get_entries_started_today_count() > 0:
        current_entry = toggl_handler.get_current_entry()
        if current_entry is None:
            notifications.send_notification(
                title='Not logging time',
                message=f'You are not currently logging time, do you want to?',
                actions=["Yes"],
                action_callback_function=_if_yes_then_start_toggl,
                timeout=60 * 1000,
            )

    entry = tracker.today().first_entry(ScreenState.UNLOCKED)
    if entry is not None:

        current_entry = toggl_handler.get_current_entry()
        if current_entry is not None and current_entry.start.date() == pendulum.yesterday().date():
            message_ids = notifications.send_notification(
                title='First unlock of the day',
                message=f'You forgot to stop Toggl yesterday, do you want to stop it now?',
                icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
                actions=["Yes"],
                action_callback_function=_if_yes_then_stop_toggl,
                timeout=60 * 1000,
            )
            notifications.wait_for_message_ids(message_ids)
            current_entry = toggl_handler.get_current_entry()

        if current_entry is None:
            notifications.send_notification(
                title='First unlock of the day',
                message=f'Do you want to start Toggl',
                actions=["Yes"],
                action_callback_function=_if_yes_then_start_toggl_for_the_1st_time_today,
                timeout=60 * 1000,
            )


class Break(NamedTuple):
    start: pendulum.datetime
    end: pendulum.datetime
    duration: pendulum.duration


def check_for_lunch_break_when_unlocking() -> None:
    # Check if there is a change that I have come back from lunch break
    if pendulum.now() < pendulum.now().replace(hour=11, minute=50):
        return

    toggl_handler = TogglHandler()
    current_entry = toggl_handler.get_current_entry()
    if toggl_handler.get_current_entry() is None:
        return

    tracker = Tracker()
    entries = tracker.today().filter(
        start=pendulum.now().replace(hour=11, minute=15, second=0, microsecond=0),
        end=pendulum.now().replace(hour=13, minute=45, second=0, microsecond=0),
    )

    breaks = []
    start = None
    for datetime, state in entries.items():
        if state == ScreenState.LOCKED:
            start = datetime
            continue

        if state == ScreenState.UNLOCKED and start is not None:
            break_ = Break(
                start=start,
                end=datetime,
                duration=datetime - start,
            )
            breaks.append(break_)
            start = None
            continue

    lunch_breaks = []
    buttons = []
    for break_ in sorted(breaks, key=lambda x: x.duration, reverse=True):
        if break_.duration.in_minutes() < 15:
            continue

        if break_.start < current_entry.start:
            continue

        lunch_breaks.append(break_)
        buttons.append(
            f"{break_.duration.in_minutes()} min "
            f"({break_.start.format('HH:mm')} - {break_.end.format('HH:mm')})"
        )

    if buttons.__len__() >= 1:
        def lunch_break(msg_id, action_id):
            accept_id_and_above = 3
            if action_id >= accept_id_and_above:
                _toggl_handler = TogglHandler()
                time_entry_stop = _toggl_handler.stop_current_entry(lunch_breaks[action_id - accept_id_and_above].start)
                print("{} [=] Logic - Stopped time entry ({}), at {}".format(
                    pendulum.now().to_datetime_string(),
                    time_entry_stop.id,
                    time_entry_stop.start.to_datetime_string(),
                ))

                time_entry_start = _toggl_handler.start_entry(
                    description="Working",
                    start_time=lunch_breaks[action_id - accept_id_and_above].end,
                )
                print("{} [=] Logic - Started time entry ({}), at {}".format(
                    pendulum.now().to_datetime_string(),
                    time_entry_start.id,
                    time_entry_start.start.to_datetime_string(),
                ))

        Notifications().send_notification(
            title='Lunch break',
            message=f'It looks like you have had lunch break, do you want to register the break?',
            actions=buttons,
            action_callback_function=lunch_break,
            timeout=60 * 1000,
            group_name="lunch_break",
        )
