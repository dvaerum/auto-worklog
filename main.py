import sys
import signal
# from pathlib import Path

import pendulum

from lib.lock_screen_notifier import LockScreenNotifier
from lib.notification import Notifications
from lib.tracker import Tracker
from lib.toggl_handler import TogglHandler
from lib.logic import first_unlock_today, check_for_lunch_break_when_unlocking


RUNNER_ALLOWED = True


def handler(signum, frame):
    global RUNNER_ALLOWED

    signame = signal.Signals(signum).name
    print(f'Stop signal {signame} ({signum}) was received, quits...')

    RUNNER_ALLOWED = False

    Notifications().quit()
    LockScreenNotifier().quit()


signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)


def screen_locked():
    print('{} [=] Screen locked'.format(pendulum.now().to_datetime_string()))


def screen_unlocked():
    print('{} [=] Screen unlocked'.format(pendulum.now().to_datetime_string()))


def main():
    global RUNNER_ALLOWED

    TogglHandler(token='e4d92673be6dc4f8483e52081c2ae946')

    tracker = Tracker()

    lock_screen_notifier = LockScreenNotifier()
    lock_screen_notifier.subscribe_to_lock_notification(tracker.trigger_screen_locked)
    lock_screen_notifier.subscribe_to_lock_notification(screen_locked)

    lock_screen_notifier.subscribe_to_unlock_notification(tracker.trigger_screen_unlocked)
    lock_screen_notifier.subscribe_to_unlock_notification(screen_unlocked)
    lock_screen_notifier.subscribe_to_unlock_notification(first_unlock_today)
    lock_screen_notifier.subscribe_to_unlock_notification(check_for_lunch_break_when_unlocking)

    first_unlock_today()
    check_for_lunch_break_when_unlocking()

    if RUNNER_ALLOWED:
        print('{} [=] Main - Ready 😁'.format(pendulum.now().to_datetime_string()))
        lock_screen_notifier.run()

    tracker.save()


if __name__ == "__main__":
    main()
