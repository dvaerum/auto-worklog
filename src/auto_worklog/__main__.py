import logging
import signal
import sys
from argparse import ArgumentParser
from os import environ
from pathlib import Path
import threading

from auto_worklog.logging_config import setup_logging, LOG_LEVELS
from auto_worklog.lock_screen_notifier import LockScreenNotifier
from auto_worklog.notification import Notifications
from auto_worklog.tracker import Tracker
from auto_worklog.toggl_handler import TogglHandler
from auto_worklog import logic as l

logger = logging.getLogger(__name__)

RUNNER_ALLOWED = True


def handler(signum, _frame):
    global RUNNER_ALLOWED

    sig_name = signal.Signals(signum).name
    logger.warning("Stop signal %s (%s) was received, quits...", sig_name, signum)

    RUNNER_ALLOWED = False

    Notifications().quit()
    LockScreenNotifier().quit()


def print_current_threads(signum, _frame):
    for thread in threading.enumerate():
        logger.debug("Thread: %s - running: %s", thread.name, thread.is_alive())


signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)
signal.signal(signal.SIGUSR2, print_current_threads)


def _resolve_token(args) -> str | None:
    """Resolve the Toggl token from --token, --token-file, or environment variables.

    Precedence (first wins):
      1. --token / AUTO_WORKLOG_TOGGL_TOKEN
      2. --token-file / AUTO_WORKLOG_TOGGL_TOKEN_FILE
    """
    if args.token:
        return args.token

    if args.token_file:
        path = Path(args.token_file)
        if not path.is_file():
            logger.error("Token file does not exist: %s", path)
            sys.exit(1)
        token = path.read_text().strip()
        if not token:
            logger.error("Token file is empty: %s", path)
            sys.exit(1)
        return token

    return None


def main():
    global RUNNER_ALLOWED

    arg_parser = ArgumentParser()

    arg_parser.add_argument('--log-level', type=str, required=False,
                            default=environ.get("AUTO_WORKLOG_LOG_LEVEL", "INFO"),
                            choices=LOG_LEVELS + ["OFF"],
                            help='Console (stderr) log level; OFF disables '
                                 '(or set AUTO_WORKLOG_LOG_LEVEL)')

    arg_parser.add_argument('--log-file', type=str, required=False,
                            default=environ.get("AUTO_WORKLOG_LOG_FILE", None),
                            help='Path to log file (or set AUTO_WORKLOG_LOG_FILE)')

    arg_parser.add_argument('--log-file-level', type=str, required=False,
                            default=environ.get("AUTO_WORKLOG_LOG_FILE_LEVEL", "DEBUG"),
                            choices=LOG_LEVELS,
                            help='File log level (or set AUTO_WORKLOG_LOG_FILE_LEVEL)')

    token_group = arg_parser.add_mutually_exclusive_group()
    token_group.add_argument('--token', type=str, required=False,
                             default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN", None),
                             help='Toggl API token (or set AUTO_WORKLOG_TOGGL_TOKEN)')
    token_group.add_argument('--token-file', type=str, required=False,
                             default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN_FILE", None),
                             help='Path to a file containing the Toggl API token '
                                  '(or set AUTO_WORKLOG_TOGGL_TOKEN_FILE)')

    arg_parser.add_argument('--auto-answer', type=str, required=False, nargs='+',
                            default=[
                                answer for answer in environ.get("AUTO_WORKLOG_AUTO_ANSWER", "").split(',')
                                if answer in l.AutoAnswer.__members__],
                            choices=list(l.AutoAnswer.__members__.keys()),
                            help='Auto answer to questions')
    args = arg_parser.parse_args()

    setup_logging(
        console_level=args.log_level,
        log_file=args.log_file,
        file_level=args.log_file_level,
    )

    logger.debug("Startup: console_level=%s, log_file=%s, file_level=%s",
                 args.log_level, args.log_file or "disabled", args.log_file_level)

    if args.auto_answer:
        auto_answer = l.AutoAnswer(sum([l.AutoAnswer[x] for x in args.auto_answer]))
        logger.info("Auto answer: %r", auto_answer)
        l.set_auto_answer(auto_answer)
    else:
        logger.info("Auto answer: %s", l.AutoAnswer.disabled)

    token = _resolve_token(args)
    if token:
        logger.debug("Startup: Toggl token provided, validating...")
        toggl = TogglHandler(token=token)
        if toggl.validate_token():
            logger.info("Toggl token validated")
        else:
            logger.error("Toggl token is invalid or API unreachable")
            Notifications().send_notification(
                title="Auto Worklog",
                message="Toggl token is invalid or API is unreachable. Time entries will not be synced.",
            )
    else:
        logger.debug("Startup: No Toggl token provided, running in offline mode")

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
        logger.info("Ready")
        lock_screen_notifier.join()
        Notifications().join()

    tracker.save()


if __name__ == "__main__":
    main()
