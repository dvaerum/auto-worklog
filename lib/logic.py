from enum import IntFlag
from typing import NamedTuple, Optional, Any, List

import pendulum

from .tracker import Tracker, ScreenState
from .notification import Notifications
from .toggl_handler import TogglHandler

_LOOP_RETRY = 5

_TIMEOUT_INFO_MSG_SEC = 10
_TIMEOUT_REPLY_MSG_SEC = 20


class AutoAnswer(IntFlag):
    disabled = 0
    forgot_to_stop_yesterday = 1
    first_unlock_today = 2
    unlock = 4
    lunch_break = 8


# _AUTO_ANSWER = AutoAnswer.disabled
_AUTO_ANSWER = AutoAnswer.disabled


def set_auto_answer(auto_answer: AutoAnswer) -> None:
    global _AUTO_ANSWER
    _AUTO_ANSWER = auto_answer


def _if_yes_then_stop_toggl(msg_id: int, action_id: int) -> None:
    if action_id == 3:
        tracker = Tracker()
        entry = tracker.from_yesterday_and_backwards().last_entry(ScreenState.LOCKED)
        if entry is None:
            raise Exception("No entry found, cannot stop Toggle, implement handler for this case!!!")

        toggl_handler = TogglHandler()
        toggl_handler.stop_current_entry(entry.datetime)


def _if_yes_then_start_toggl(msg_id: int, action_id: int) -> None:
    if action_id == 3:
        tracker = Tracker()
        entry = tracker.from_today_only().last_entry(ScreenState.UNLOCKED)
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
        entry = tracker.from_today_only().first_entry(ScreenState.UNLOCKED)
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

    unlock_entries = tracker.from_today_only().filter(state=ScreenState.UNLOCKED)
    if unlock_entries.__len__() != 1:
        return

    unlock_entry = tracker.from_today_only().first_entry(ScreenState.UNLOCKED)
    if unlock_entry is None:
        return

    tracker_entry = tracker.from_yesterday_and_backwards().last_entry(ScreenState.LOCKED)

    current_entry = toggl_handler.get_current_entry()
    if current_entry is not None:
        if current_entry.start.date() == pendulum.today().date():
            time_entries = toggl_handler.get_entries_stopped_today()

            # Find the time entry which started the latest
            earliest_stopped_time_entry = None
            for time_entry in time_entries:
                if earliest_stopped_time_entry is None:
                    earliest_stopped_time_entry = time_entry
                elif time_entry.stop < earliest_stopped_time_entry.stop:
                    earliest_stopped_time_entry = time_entry

            if earliest_stopped_time_entry is None:
                return

            if earliest_stopped_time_entry.start.date() == pendulum.today().date():
                return

            def _if_cancel_button_is_clicked_do_nothing(msg_id: int, action_id: int) -> None:
                if action_id == 3:
                    pass

                else:
                    earliest_stopped_time_entry.stop = tracker_entry.datetime
                    earliest_stopped_time_entry.save()

            notifications.send_notification(
                title='Manually stopped Toggl which was forgotten yesterday',
                message='It looks like you forgot to stop Toggl {week_day} ({days_passed}), '
                        'and then stopped it this morning. '
                        'So, I will adjust the Toggle started on the {start_date} and stopped today at {stop_time}. '
                        'If you don\'t want me to do this, click the "Cancel" button.'.format(
                            week_day=tracker_entry.datetime.format("dddd"),
                            days_passed=tracker_entry.datetime.diff_for_humans(),
                            start_date=earliest_stopped_time_entry.start.to_date_string(),
                            stop_time=tracker_entry.datetime.to_time_string(),
                        ),
                actions=["Cancel"],
                action_callback_function=_if_cancel_button_is_clicked_do_nothing,
                timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
            )

        elif current_entry.start.date() != pendulum.now().date():
            if AutoAnswer.forgot_to_stop_yesterday in _AUTO_ANSWER:
                _if_yes_then_stop_toggl(0, 3)
                notifications.send_notification(
                    title='Forgot to stop Toggl (Updated)',
                    message='You forgot to stop Toggl {week_day} ({days_passed}), so I stopped it for you 😉'.format(
                        week_day=tracker_entry.datetime.format("dddd"),
                        days_passed=tracker_entry.datetime.diff_for_humans(),
                    ),
                    timeout_sec=_TIMEOUT_INFO_MSG_SEC,
                )

            else:
                message_ids = notifications.send_notification(
                    title='First unlock of the day',
                    message=f'You forgot to stop Toggl yesterday, do you want to stop it now?',
                    actions=["Yes"],
                    action_callback_function=_if_yes_then_stop_toggl,
                    timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
                )
                notifications.wait_for_message_ids(message_ids)

            current_entry = toggl_handler.get_current_entry()

    if current_entry is None:
        if AutoAnswer.first_unlock_today in _AUTO_ANSWER:
            _if_yes_then_start_toggl_for_the_1st_time_today(0, 3)
            notifications.send_notification(
                title='First unlock of the day (Updated)',
                message=f'It is the first time you unlock your computer today, so I started Toggl for you 😉',
                timeout_sec=_TIMEOUT_INFO_MSG_SEC,
            )

        else:
            notifications.send_notification(
                title='First unlock of the day',
                message=f'Do you want to start Toggl',
                actions=["Yes"],
                action_callback_function=_if_yes_then_start_toggl_for_the_1st_time_today,
                timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
            )


def unlock() -> None:
    tracker = Tracker()
    toggl_handler = TogglHandler()
    notifications = Notifications()

    if tracker.from_today_only().filter(state=ScreenState.UNLOCKED).__len__() > 1 \
            and toggl_handler.get_entries_started_today_count() > 0:
        current_entry = toggl_handler.get_current_entry()
        if current_entry is None:
            if AutoAnswer.unlock in _AUTO_ANSWER:
                _if_yes_then_start_toggl(0, 3)
                notifications.send_notification(
                    title='Not logging time (Updated)',
                    message=f'You are not currently logging time, so I started Toggl for you 😉',
                    timeout_sec=_TIMEOUT_INFO_MSG_SEC,
                )

            else:
                notifications.send_notification(
                    title='Not logging time',
                    message=f'You are not currently logging time, do you want to?',
                    actions=["Yes"],
                    action_callback_function=_if_yes_then_start_toggl,
                    timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
                )


class Break(NamedTuple):
    start: pendulum.DateTime
    end: pendulum.DateTime
    period: pendulum.Interval
    toggl_entry: Optional[Any] = None

    def to_str(self) -> str:
        return "{period} min ({start} - {end})".format(
            period=self.period.in_minutes(),
            start=self.start.format('HH:mm'),
            end=self.end.format('HH:mm'),
        )


LUNCH_BREAK_MIN_DURATION = pendulum.duration(hours=0, minutes=15, seconds=0, microseconds=0)
LUNCH_BREAK_REGISTERED: Optional[Break] = None
LUNCH_BREAK_CANCELED: List[Break] = []


def check_for_lunch_break_when_unlocking() -> None:
    global _AUTO_ANSWER, LUNCH_BREAK_CANCELED

    lunch_break_start_dt = pendulum.now().replace(hour=11, minute=00, second=0, microsecond=0)
    lunch_break_end_dt = pendulum.now().replace(hour=13, minute=45, second=0, microsecond=0)

    toggl_handler = TogglHandler()
    notifications = Notifications()

    # Check if there is a change that I have come back from lunch break
    if pendulum.now() < pendulum.now().replace(hour=11, minute=40, second=0, microsecond=0):
        return

    current_entry = toggl_handler.get_current_entry()
    if current_entry is None:
        return

    tracker = Tracker()
    entries = tracker.from_today_only().filter(
        start=lunch_break_start_dt,
        end=lunch_break_end_dt,
    )

    breaks = []
    start = None
    for datetime, state in entries.items():
        if state == ScreenState.LOCKED:
            start = datetime
            continue

        if state == ScreenState.UNLOCKED and start is not None:
            _break_period = datetime - start
            if _break_period < LUNCH_BREAK_MIN_DURATION:
                continue

            break_ = Break(
                start=start,
                end=datetime,
                period=_break_period,
            )
            breaks.append(break_)
            start = None
            continue

    tmp_lunch_breaks: List[Break] = []
    for break_ in sorted(breaks, key=lambda x: x.period, reverse=True):
        if break_.start < current_entry.start:
            continue

        tmp_lunch_breaks.append(break_)

    only_handle_stop_time_for_toggl_entries = False
    if tmp_lunch_breaks.__len__() == 0:
        _toggl_entries = toggl_handler.get_entries_started_today()
        toggl_entries = [
            toggl_entry for toggl_entry in _toggl_entries
            if toggl_entry.stop and lunch_break_start_dt < toggl_entry.stop < lunch_break_end_dt
        ]

        for toggl_entry in toggl_entries:
            for _break in breaks:
                if toggl_entry.stop in _break.period:
                    _new_break = Break(
                        start=_break.start,
                        end=_break.end,
                        period=_break.period,
                        toggl_entry=toggl_entry,
                    )
                    tmp_lunch_breaks.append(_new_break)
                    only_handle_stop_time_for_toggl_entries = True

    if tmp_lunch_breaks.__len__() >= 1:
        lunch_breaks = {}

        def lunch_break(msg_id, action_id):
            if action_id == 3:
                _toggl_handler = TogglHandler()
                _lunch_break = lunch_breaks[msg_id]

                if only_handle_stop_time_for_toggl_entries:
                    _lunch_break.toggl_entry.stop = _lunch_break.start
                    _lunch_break.toggl_entry.save()
                    print("{} [=] Logic - Updated stopped time entry ({}), at {}".format(
                        pendulum.now().to_datetime_string(),
                        _lunch_break.toggl_entry.id,
                        _lunch_break.toggl_entry.start.to_datetime_string(),
                    ))

                else:
                    time_entry_stop = _toggl_handler.stop_current_entry(_lunch_break.start)
                    print("{} [=] Logic - Stopped time entry ({}), at {}".format(
                        pendulum.now().to_datetime_string(),
                        time_entry_stop.id,
                        time_entry_stop.start.to_datetime_string(),
                    ))

                    time_entry_start = _toggl_handler.start_entry(
                        description="Working",
                        start_time=_lunch_break.end,
                    )
                    print("{} [=] Logic - Started time entry ({}), at {}".format(
                        pendulum.now().to_datetime_string(),
                        time_entry_start.id,
                        time_entry_start.start.to_datetime_string(),
                    ))

        if tmp_lunch_breaks.__len__() == 1 and AutoAnswer.lunch_break in _AUTO_ANSWER:
            lunch_breaks[-1] = tmp_lunch_breaks[0]

            if lunch_breaks[-1] in LUNCH_BREAK_CANCELED:
                return

            if LUNCH_BREAK_REGISTERED and LUNCH_BREAK_REGISTERED.start.date() == pendulum.now().date():
                return

            current_entry = toggl_handler.get_current_entry()
            if (pendulum.now() - current_entry.start).in_seconds() < 60:
                return

            def launch_break_cancel(_msg_id, action_id):
                global LUNCH_BREAK_CANCELED

                if action_id == 3:
                    LUNCH_BREAK_CANCELED.append(lunch_breaks[-1])

                else:
                    lunch_break(-1, 3)

            notifications.send_notification(
                title='Lunch break (Updated)',
                message="You have had lunch break which you did not register, but I have done it for you 😉 "
                        "The lunch break was {} min, start at {}".format(
                            tmp_lunch_breaks[0].period.in_minutes(),
                            tmp_lunch_breaks[0].start.format('HH:mm'),
                        ),
                actions=["Cancel"],
                action_callback_function=launch_break_cancel,
                timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
            )

        else:
            _buttons = [break_.to_str() for break_ in tmp_lunch_breaks]
            message_ids = notifications.send_notification(
                title='Lunch break',
                message=f'It looks like you have had lunch break, do you want to register the break?',
                actions=_buttons,
                action_callback_function=lunch_break,
                timeout_sec=_TIMEOUT_REPLY_MSG_SEC,
                group_name="lunch_break",
            )

            for index, _msg_id in enumerate(sorted(message_ids)):
                lunch_breaks[_msg_id] = tmp_lunch_breaks[index]
