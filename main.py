import signal
from argparse import ArgumentParser
from os import environ

import pendulum

from lib.lock_screen_notifier import LockScreenNotifier
from lib.notification import Notifications
from lib.tracker import Tracker
from lib.toggl_handler import TogglHandler
from lib.logic import first_unlock_today, check_for_lunch_break_when_unlocking, AutoAnswer, set_auto_answer

RUNNER_ALLOWED = True


def handler(signum, _frame):
    global RUNNER_ALLOWED

    sig_name = signal.Signals(signum).name
    print(f'Stop signal {sig_name} ({signum}) was received, quits...')

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

    arg_parser = ArgumentParser()
    arg_parser.add_argument('--token', type=str, required=False,
                            default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN", None),
                            help='Toggl API token')
    arg_parser.add_argument('--auto-answer', type=str, required=False, nargs='+',
                            default=[
                                answer for answer in environ.get("AUTO_WORKLOG_AUTO_ANSWER", "").split(',')
                                if answer in AutoAnswer.__members__],
                            choices=list(AutoAnswer.__members__.keys()),
                            help='Auto answer to questions')
    args = arg_parser.parse_args()

    if args.auto_answer:
        auto_answer = AutoAnswer(sum([AutoAnswer[x] for x in args.auto_answer]))
        print('{} [=] Main - Auto answer: {}'.format(pendulum.now().to_datetime_string(), auto_answer.__repr__()))
        set_auto_answer(auto_answer)
    else:
        print('{} [=] Main - Auto answer: {}'.format(pendulum.now().to_datetime_string(), AutoAnswer.disabled))

    if args.token:
        print('{} [=] Main - Toggl token received'.format(pendulum.now().to_datetime_string()))
        TogglHandler(token=args.token)

    tracker = Tracker()

    lock_screen_notifier = LockScreenNotifier()
    lock_screen_notifier.subscribe_to_lock_notification(tracker.trigger_screen_locked)
    lock_screen_notifier.subscribe_to_lock_notification(screen_locked)

    lock_screen_notifier.subscribe_to_unlock_notification(tracker.trigger_screen_unlocked)
    lock_screen_notifier.subscribe_to_unlock_notification(first_unlock_today)
    lock_screen_notifier.subscribe_to_unlock_notification(check_for_lunch_break_when_unlocking)
    lock_screen_notifier.subscribe_to_unlock_notification(screen_unlocked)

    first_unlock_today()
    check_for_lunch_break_when_unlocking()

    if RUNNER_ALLOWED:
        print('{} [=] Main - Ready 😁'.format(pendulum.now().to_datetime_string()))
        lock_screen_notifier.join()
        Notifications().join()

    tracker.save()


if __name__ == "__main__":
    main()
