import threading
from typing import Callable, List, Union

import dbus
import pendulum
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop
from .misc import ScreenState


_LOCK_SCREEN_NOTIFIER = None


# Does not work, if configured in the unittest class, I keep getting the error message.
# Error message:
#   RuntimeError: To make asynchronous calls, receive signals or export objects,
#   D-Bus connections must be attached to a main loop by passing mainloop=... to the constructor or
#   calling dbus.set_default_main_loop(...)
DBusGMainLoop(set_as_default=True)


class _LockScreenNotifier:
    _glib_loop: GLib.MainLoop
    _session_bus: dbus.SessionBus
    _thread: threading.Thread

    _lock_subscription: List[Callable[[], None]]
    _unlock_subscription: List[Callable[[], None]]

    def __init__(self) -> None:
        self._lock_subscription = []
        self._unlock_subscription = []
        self._glib_loop = GLib.MainLoop()
        self._session_bus = dbus.SessionBus()

        self._session_bus.add_signal_receiver(
            handler_function=self.signal_handler,
            bus_name='org.freedesktop.ScreenSaver',
            path='/ScreenSaver',
            dbus_interface='org.freedesktop.ScreenSaver',
            signal_name='ActiveChanged'
        )

        self._thread = threading.Thread(target=self._glib_loop.run)
        self._thread.start()

    def subscribe_to_lock_notification(self, func_: Callable[[], None]) -> None:
        self._lock_subscription.append(func_)

    def subscribe_to_unlock_notification(self, func_: Callable[[], None]) -> None:
        self._unlock_subscription.append(func_)

    def signal_handler(self, screen_locked: Union[int, ScreenState]):
        screen_state = ScreenState(screen_locked)
        print('{} [=] Lock Screen Notifier - {}'.format(pendulum.now().to_datetime_string(), screen_state.name))

        if screen_state == ScreenState.UNLOCKED:
            for func_ in self._unlock_subscription:
                print('{} [=] Lock Screen Notifier - {} - Run: {}'.format(
                    pendulum.now().to_datetime_string(),
                    screen_state.name,
                    func_,
                ))
                func_()

        elif screen_state == ScreenState.LOCKED:
            for func_ in self._lock_subscription:
                print('{} [=] Lock Screen Notifier - {} - Run: {}'.format(
                    pendulum.now().to_datetime_string(),
                    screen_state.name,
                    func_,
                ))
                func_()

        else:
            raise NotImplementedError(
                f'Screen unlocked event is not implemented '
                f'for the value ({type(screen_locked)}): {screen_locked}'
            )

    def join(self) -> None:
        self._thread.join()

    def quit(self) -> None:
        print("{} [=] LockScreenNotifier - Told to quit".format(pendulum.now().to_datetime_string()))
        if self._glib_loop.is_running():
            print("{} [=] LockScreenNotifier - Quit command send".format(pendulum.now().to_datetime_string()))
            self._glib_loop.quit()


def LockScreenNotifier() -> _LockScreenNotifier:
    global _LOCK_SCREEN_NOTIFIER

    if _LOCK_SCREEN_NOTIFIER is None:
        _LOCK_SCREEN_NOTIFIER = _LockScreenNotifier()

    return _LOCK_SCREEN_NOTIFIER



