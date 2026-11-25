"""Command hooks: run configured commands when something happens, with JSON on stdin.

This is how auto-worklog talks to other tools without knowing about them. A hook is just an
argument list (no shell) configured per event; auto-worklog pipes a JSON document to it and
logs what it prints. For example ``["bit", "sync"]`` on ``day_summary`` registers the day's
time in BIT, and neither program has any code for the other.

Hooks never block auto-worklog: events are queued and run one after another on a worker
thread, a hook that fails or hangs is logged and skipped, and a burst of events with the same
key (for instance the same day's summary requested on every screen lock) collapses into the
latest one.

The document on stdin::

    {"version": 1, "event": "day_summary", "time": "<ISO 8601>", "host": "<hostname>", ...data}

and the environment carries ``AUTO_WORKLOG_EVENT`` and ``AUTO_WORKLOG_HOST``.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import socket
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Union

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
EVENTS = ("screen_locked", "screen_unlocked", "day_summary")

# Event data, or a function producing it. The function runs on the worker thread, so it may
# do slow work (a network call) without holding up the caller; returning None skips the event.
Payload = Union[dict[str, Any], Callable[[], Union[dict[str, Any], None]]]


@dataclass(frozen=True)
class HookConfig:
    commands: dict[str, list[list[str]]] = field(default_factory=dict)
    timeout: float = 60.0


class HookRunner:
    def __init__(self, config: HookConfig, *, host: str | None = None, start_thread: bool = True) -> None:
        self._config = config
        self._host = host or socket.gethostname()
        self._start_thread = start_thread
        self._cond = threading.Condition()
        self._pending: OrderedDict[str, tuple[str, Payload]] = OrderedDict()
        self._numbers = itertools.count()
        self._busy = False
        self._closed = False
        self._thread: threading.Thread | None = None

    def wants(self, event: str) -> bool:
        return bool(self._config.commands.get(event))

    def emit(self, event: str, data: Payload, *, key: str | None = None) -> None:
        """Queue an event. A later event with the same ``key`` replaces a pending one."""
        if not self.wants(event):
            return
        with self._cond:
            if self._closed:
                return
            self._pending[key if key is not None else f"#{next(self._numbers)}"] = (event, data)
            self._cond.notify_all()
            if self._start_thread and self._thread is None:
                self._thread = threading.Thread(target=self._work, name="auto-worklog-hooks", daemon=True)
                self._thread.start()

    # -- running ---------------------------------------------------------------------------
    def run_pending(self) -> None:
        """Run everything queued, on the calling thread (for tests and shutdown)."""
        while self._run_next():
            pass

    def _run_next(self) -> bool:
        with self._cond:
            if not self._pending:
                return False
            _, (event, data) = self._pending.popitem(last=False)
            self._busy = True
        try:
            self._run(event, data)
        finally:
            with self._cond:
                self._busy = False
                self._cond.notify_all()
        return True

    def _work(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._closed:
                    self._cond.wait()
                if self._closed and not self._pending:
                    return
            self._run_next()

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until nothing is queued or running; False if ``timeout`` ran out first."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._pending and not self._busy, timeout)

    def close(self, wait: float = 10.0) -> None:
        self.flush(wait)
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def _run(self, event: str, data: Payload) -> None:
        try:
            payload = data() if callable(data) else data
        except Exception as err:  # noqa: BLE001 - a producer failing (Toggl unreachable, ...) must
            # not kill the worker: the event is dropped and the next one gets a fresh try.
            logger.warning("the data for the %s hook could not be produced: %s", event, err)
            return
        if payload is None:
            logger.debug("the %s hook has nothing to send", event)
            return

        envelope = {
            "version": SCHEMA_VERSION,
            "event": event,
            "time": datetime.now().astimezone().isoformat(),
            "host": self._host,
            **payload,
        }
        body = json.dumps(envelope)
        env = {**os.environ, "AUTO_WORKLOG_EVENT": event, "AUTO_WORKLOG_HOST": self._host}
        for argv in self._config.commands.get(event, []):
            self._run_command(event, argv, body, env)

    def _run_command(self, event: str, argv: list[str], body: str, env: dict[str, str]) -> None:
        name = argv[0]
        try:
            done = subprocess.run(argv, input=body, capture_output=True, text=True, timeout=self._config.timeout, env=env, check=False)
        except subprocess.TimeoutExpired:
            logger.warning("hook command %s for %s timed out after %gs", name, event, self._config.timeout)
            return
        except OSError as err:
            logger.warning("could not run hook command %s for %s: %s", name, event, err)
            return
        if done.returncode != 0:
            logger.warning(
                "hook command %s for %s failed with exit code %d: %s",
                name, event, done.returncode, (done.stderr or done.stdout).strip()[:500],
            )
            return
        for line in done.stdout.splitlines():
            logger.info("hook %s (%s): %s", event, name, line)
        logger.debug("hook command %s for %s succeeded", name, event)
