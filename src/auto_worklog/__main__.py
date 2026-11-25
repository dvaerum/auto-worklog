import json
import logging
import signal
import sys
from argparse import ArgumentParser
from os import environ
from pathlib import Path
import threading

import pendulum

from auto_worklog import __version__
from auto_worklog.config import AppConfig, ConfigError, load_config
from auto_worklog.integrations import TrackerAdapter, build_integrations, parse_day
from auto_worklog.logging_config import setup_logging, LOG_LEVELS
from auto_worklog.worklog import MappingConfig, summarize_day
from auto_worklog.lock_screen_notifier import LockScreenNotifier
from auto_worklog.notification import Notifications
from auto_worklog.tracker import Tracker
from auto_worklog.toggl_handler import TogglHandler, TogglUnavailableError, TokenStatus
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


def run_trigger(name: str, trigger) -> None:
    """Run a trigger so that a failure is logged and never reaches the D-Bus handler."""
    try:
        trigger()
    except TogglUnavailableError as err:
        # Expected while offline (laptop on the move, DNS not up yet): no traceback.
        logger.warning("Trigger %s skipped, Toggl is unreachable: %s", name, err)
    except Exception as err:
        logger.exception("Error in %s trigger: %s", name, err)


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


def _print_day_summary(day_text: str, token: str | None, config: AppConfig | None) -> int:
    """``--print-day-summary``: the document a ``day_summary`` hook would receive."""
    if not token:
        logger.error("--print-day-summary needs a Toggl token (--token or --token-file)")
        return 2
    try:
        day = parse_day(day_text, pendulum.today().date())
    except ValueError as err:
        logger.error("%s", err)
        return 2
    try:
        entries = TogglHandler(token=token).get_work_entries(day)
    except TogglUnavailableError as err:
        logger.error("Toggl is unreachable: %s", err)
        return 1
    mapping = config.mapping if config else MappingConfig()
    summary = summarize_day(day, entries or [], mapping, pendulum.now())
    print(json.dumps({"days": [summary.to_dict()]}, indent=2))
    return 0


def main():
    global RUNNER_ALLOWED

    arg_parser = ArgumentParser()

    arg_parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    arg_parser.add_argument(
        "--log-level",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_LOG_LEVEL", "INFO"),
        choices=LOG_LEVELS + ["OFF"],
        help="Console (stderr) log level; OFF disables "
        "(or set AUTO_WORKLOG_LOG_LEVEL)",
    )

    arg_parser.add_argument(
        "--log-file",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_LOG_FILE", None),
        help="Path to log file (or set AUTO_WORKLOG_LOG_FILE)",
    )

    arg_parser.add_argument(
        "--log-file-level",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_LOG_FILE_LEVEL", "DEBUG"),
        choices=LOG_LEVELS,
        help="File log level (or set AUTO_WORKLOG_LOG_FILE_LEVEL)",
    )

    token_group = arg_parser.add_mutually_exclusive_group()
    token_group.add_argument(
        "--token",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN", None),
        help="Toggl API token (or set AUTO_WORKLOG_TOGGL_TOKEN)",
    )
    token_group.add_argument(
        "--token-file",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_TOGGL_TOKEN_FILE", None),
        help="Path to a file containing the Toggl API token "
        "(or set AUTO_WORKLOG_TOGGL_TOKEN_FILE)",
    )

    arg_parser.add_argument(
        "--auto-answer",
        type=str,
        required=False,
        nargs="+",
        default=[
            answer
            for answer in environ.get("AUTO_WORKLOG_AUTO_ANSWER", "").split(",")
            if answer in l.AutoAnswer.__members__
        ],
        choices=list(l.AutoAnswer.__members__.keys()),
        help="Auto answer to questions",
    )
    arg_parser.add_argument(
        "--config",
        type=str,
        required=False,
        default=environ.get("AUTO_WORKLOG_CONFIG", None),
        help="JSON file with hooks and the project mapping (or set AUTO_WORKLOG_CONFIG)",
    )
    arg_parser.add_argument(
        "--print-day-summary",
        metavar="DAY",
        required=False,
        help="print the day_summary JSON for DAY (today, yesterday or YYYY-MM-DD) and exit; "
        "pipe it into a consumer to try the mapping, e.g. `... | bit sync --dry-run`",
    )
    args = arg_parser.parse_args()

    setup_logging(
        console_level=args.log_level,
        log_file=args.log_file,
        file_level=args.log_file_level,
    )

    logger.debug(
        "Startup: console_level=%s, log_file=%s, file_level=%s",
        args.log_level,
        args.log_file or "disabled",
        args.log_file_level,
    )

    if args.auto_answer:
        auto_answer = l.AutoAnswer(sum([l.AutoAnswer[x] for x in args.auto_answer]))
        logger.info("Auto answer: %r", auto_answer)
        l.set_auto_answer(auto_answer)
    else:
        logger.info("Auto answer: %s", l.AutoAnswer.disabled)

    config: AppConfig | None = None
    if args.config:
        try:
            config = load_config(args.config)
        except ConfigError as err:
            logger.error("%s", err)
            sys.exit(2)

    token = _resolve_token(args)
    if args.print_day_summary:
        sys.exit(_print_day_summary(args.print_day_summary, token, config))

    if token:
        logger.debug("Startup: Toggl token provided, validating...")
        toggl = TogglHandler(token=token)
        status = toggl.check_token()
        if status is TokenStatus.VALID:
            logger.info("Toggl token validated")
        elif status is TokenStatus.INVALID:
            # Needs the user: the token was rejected.
            logger.error("Toggl token was rejected (invalid or revoked)")
            Notifications().send_notification(
                title="Auto Worklog",
                message="The Toggl token was rejected. Time entries will not be synced.",
            )
        else:
            # Transient: no network yet, or Toggl is down. Nothing to fix.
            logger.warning("Toggl API is unreachable, time entries may not be synced")
    else:
        logger.debug("Startup: No Toggl token provided, running in offline mode")

    tracker = Tracker()

    def safe_first_unlock_today():
        run_trigger("first_unlock_today", l.first_unlock_today)

    def safe_unlock():
        run_trigger("unlock", l.unlock)

    def safe_lunch_break():
        run_trigger("lunch_break", l.check_for_lunch_break_when_unlocking)

    lock_screen_notifier = LockScreenNotifier()
    lock_screen_notifier.subscribe_to_lock_notification(tracker.trigger_screen_locked)

    lock_screen_notifier.subscribe_to_unlock_notification(
        tracker.trigger_screen_unlocked
    )
    lock_screen_notifier.subscribe_to_unlock_notification(safe_first_unlock_today)
    lock_screen_notifier.subscribe_to_unlock_notification(safe_unlock)
    lock_screen_notifier.subscribe_to_unlock_notification(safe_lunch_break)

    # Registered last so the tracker has recorded the event, and the Toggl triggers above have
    # had their say (they may fix a forgotten timer), before anything is sent to hooks.
    integrations = None
    if config is not None and any(config.hooks.commands.values()):
        integrations = build_integrations(config, tracker=TrackerAdapter(Tracker), toggl_factory=TogglHandler)
        lock_screen_notifier.subscribe_to_lock_notification(
            lambda: run_trigger("hooks", integrations.on_screen_locked)
        )
        lock_screen_notifier.subscribe_to_unlock_notification(
            lambda: run_trigger("hooks", integrations.on_screen_unlocked)
        )
        logger.info("Hooks enabled for: %s", ", ".join(sorted(e for e, c in config.hooks.commands.items() if c)))

    safe_first_unlock_today()
    safe_unlock()
    safe_lunch_break()

    if RUNNER_ALLOWED:
        logger.info("Ready")
        lock_screen_notifier.join()
        Notifications().join()

    tracker.save()
    if integrations is not None:
        integrations.close()  # let queued hooks finish (bounded) before the process ends


if __name__ == "__main__":
    main()
