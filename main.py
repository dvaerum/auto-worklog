import signal
from argparse import ArgumentParser
from os import environ
import threading
import pendulum

from lib.lock_screen_notifier import LockScreenNotifier
from lib.notification import Notifications
from lib.tracker import Tracker
from lib.toggl_handler import TogglHandler
from lib import logic as l


RUNNER_ALLOWED = True


def handler(signum, _frame):
    global RUNNER_ALLOWED

    sig_name = signal.Signals(signum).name
    print(f'Stop signal {sig_name} ({signum}) was received, quits...')

    RUNNER_ALLOWED = False

    Notifications().quit()
    LockScreenNotifier().quit()


def print_current_threads(signum, _frame):
    for thread in threading.enumerate():
        print(f"name: {thread.name} - running: {thread.is_alive()}")


signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGUSR2, print_current_threads)


def main():
    global RUNNER_ALLOWED

    arg_parser = ArgumentParser()
    arg_parser.add_argument('--token', type=str, required=False,
                            default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN", None),
                            help='Toggl API token')
    arg_parser.add_argument('--auto-answer', type=str, required=False, nargs='+',
                            default=[
                                answer for answer in environ.get("AUTO_WORKLOG_AUTO_ANSWER", "").split(',')
                                if answer in l.AutoAnswer.__members__],
                            choices=list(l.AutoAnswer.__members__.keys()),
                            help='Auto answer to questions')
    args = arg_parser.parse_args()

    if args.auto_answer:
        auto_answer = l.AutoAnswer(sum([l.AutoAnswer[x] for x in args.auto_answer]))
        print('{} [=] Main - Auto answer: {}'.format(pendulum.now().to_datetime_string(), auto_answer.__repr__()))
        l.set_auto_answer(auto_answer)
    else:
        print('{} [=] Main - Auto answer: {}'.format(pendulum.now().to_datetime_string(), l.AutoAnswer.disabled))

    if args.token:
        print('{} [=] Main - Toggl token received'.format(pendulum.now().to_datetime_string()))
        TogglHandler(token=args.token)

    tracker = Tracker()

    lock_screen_notifier = LockScreenNotifier()
    lock_screen_notifier.subscribe_to_lock_notification(tracker.trigger_screen_locked)

    lock_screen_notifier.subscribe_to_unlock_notification(tracker.trigger_screen_unlocked)
    lock_screen_notifier.subscribe_to_unlock_notification(l.first_unlock_today)
    lock_screen_notifier.subscribe_to_unlock_notification(l.unlock)
    lock_screen_notifier.subscribe_to_unlock_notification(l.check_for_lunch_break_when_unlocking)

    l.first_unlock_today()
    l.unlock()
    l.check_for_lunch_break_when_unlocking()

    if RUNNER_ALLOWED:
        print('{} [=] Main - Ready 😁'.format(pendulum.now().to_datetime_string()))
        lock_screen_notifier.join()
        Notifications().join()

    tracker.save()


if __name__ == "__main__":
    main()
