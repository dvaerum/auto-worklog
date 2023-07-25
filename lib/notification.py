import threading
from time import sleep

import unittest
from typing import Callable, Dict, Set, Optional, Union

import dbus
import pendulum
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

_LOCK_SCREEN_NOTIFIER = None

# Does not work, if configured in the unittest class, I keep getting the error message.
# Error message:
#   RuntimeError: To make asynchronous calls, receive signals or export objects,
#   D-Bus connections must be attached to a main loop by passing mainloop=... to the constructor or
#   calling dbus.set_default_main_loop(...)
DBusGMainLoop(set_as_default=True)

TypeNotificationCallback = Callable[[int, int], None]


class _Notifications:
    _delay_between_notifications: Optional[int]
    _waiting_for_the_ip: Dict[
        int,
        TypeNotificationCallback,
    ]
    _grouped_msg_ids: Dict[str, Set[int]]
    _dismissed_msg_ids: Set[int]

    _glib_loop: GLib.MainLoop
    _session_bus: dbus.SessionBus
    _thread: threading.Thread

    bus_service = "org.freedesktop.Notifications"
    bus_path = "/org/freedesktop/Notifications"
    bus_interface = "org.freedesktop.Notifications"

    def __init__(self) -> None:
        self._delay_between_notifications = None
        self._waiting_for_the_ip = {}
        self._grouped_msg_ids = {}
        self._dismissed_msg_ids = set()

        self._glib_loop = GLib.MainLoop()
        self._session_bus = dbus.SessionBus()

        self._session_bus.add_signal_receiver(
            handler_function=self._signal_handler,
            bus_name=self.bus_service,
            path=self.bus_path,
            dbus_interface=self.bus_interface,
            signal_name='NotificationClosed'
        )

        self._thread = threading.Thread(name=__name__, target=self._glib_loop.run)
        self._thread.start()

        self.dbus_obj = dbus.SessionBus().get_object(
            bus_name=self.bus_service,
            object_path=self.bus_path,
        )

        self.dbus_interface_obj = dbus.Interface(
            object=self.dbus_obj,
            dbus_interface=self.bus_interface,
        )

    def send_notification(
            self, title: str, message: str, icon_path: str = None, actions=None,
            action_callback_function: TypeNotificationCallback = None, timeout_sec: int = 5,
            group_name: str = None,
    ):
        """

        :param title: The title of the notification.
        :param message: The message of the notification.
        :param icon_path: The icon data or path to an icon file to display.
        :param actions: This is how you create buttons on the notification.
                        Make a list of strings for each button you want to add. E.g. ["Button X", "Button 1"]
                        "Button X" will be the X button which will close you notification, callback value 2.
                        "Button 1" will be the 1st extra button and will have the name "Button 1, callback value 3.
                        "Button 2" will be the 2nd extra button and will have the name "Button 2, callback value 4.
                        And so on.
                        If you don't press any button and the notification times out, callback value 1.
        :param action_callback_function: This function will be called when the notification is closed or
                                         one of the buttons are pressed. It takes two parameters ...
                                         - 1st parameter: message ID (msg_id)
                                         - 2nd parameter: action ID (action_id)
        :param timeout_sec: The timeout in milliseconds at which to expire the notification.
        :param blocking: Is this function allowed to block the main thread?
        :param group_name: The notifications grouped?
                           Meaning that if you answer one notification, all the others disappear?
        :return: Set of Message IDs - The ID assigned to the notification by the DBus service.
        """
        notify_app_name = ""
        notify_replace_id = 0
        notify_app_icon = icon_path if icon_path else ""
        notify_summary = title
        notify_body = message
        notify_actions = ["X"]
        notify_hints = {
            "urgency": 1,
        }
        notify_timeout = timeout_sec * 1000

        print(f"{pendulum.today().to_datetime_string()} [=] Notification - send_notification - "
              f"notify_app_name: {notify_app_name} - "
              f"notify_replace_id: {notify_replace_id} - "
              f"notify_app_icon: {notify_app_icon} - "
              f"notify_summary: {notify_summary} - "
              f"notify_body: {notify_body} - "
              f"actions: {actions} - "
              f"notify_hints: {notify_hints} - "
              f"notify_timeout: {notify_timeout}")

        collect_all_msg_ids = set()

        if actions is None:
            msg_id = self.dbus_interface_obj.Notify(
                notify_app_name,
                notify_replace_id,
                notify_app_icon,
                notify_summary,
                notify_body,
                notify_actions,
                notify_hints,
                notify_timeout,
            )
            msg_id = int(msg_id)
            collect_all_msg_ids.add(msg_id)

        else:
            for index, action in enumerate(actions):
                msg_id = self.dbus_interface_obj.Notify(
                    notify_app_name + f" ({index + 1}/{actions.__len__()})" if actions.__len__() > 1 else "",
                    notify_replace_id,
                    notify_app_icon,
                    notify_summary,
                    notify_body,
                    notify_actions + [action],
                    notify_hints,
                    notify_timeout,
                )
                msg_id = int(msg_id)
                collect_all_msg_ids.add(msg_id)

                if group_name is not None:
                    self._grouped_msg_ids.setdefault(group_name, set())
                    self._grouped_msg_ids[group_name].add(msg_id)

                if action_callback_function is not None:
                    self._waiting_for_the_ip[msg_id] = action_callback_function

                if self._delay_between_notifications is not None:
                    sleep(self._delay_between_notifications)

        if action_callback_function is not None:
            if self._glib_loop.is_running() is False:
                print("{} [=] Notification - _thread: Starter".format(pendulum.now().to_datetime_string()))
                self._thread.start()
                print("{} [=] Notification - _thread: Finished".format(pendulum.now().to_datetime_string()))

            else:
                print("{} [=] Notification - _thread: Running".format(pendulum.now().to_datetime_string()))

        return collect_all_msg_ids

    def _signal_handler(self, *args):
        if args.__len__() == 2:
            msg_id = int(args[0])
            action_id = int(args[1])

            if msg_id in self._waiting_for_the_ip:
                print("{} [=] signal_handler (was expected) - msg_id: {}, action_id: {}".format(
                    pendulum.now().to_datetime_string(),
                    msg_id, action_id,
                ))
                callback_function = self._waiting_for_the_ip[msg_id]
                if msg_id in self._dismissed_msg_ids:
                    self._dismissed_msg_ids.remove(msg_id)
                else:
                    callback_function(msg_id, action_id)
                self._waiting_for_the_ip.pop(msg_id)

                for group_name in list(self._grouped_msg_ids.keys()):
                    if msg_id in self._grouped_msg_ids[group_name]:
                        dismissed_msg_ids = self._grouped_msg_ids.pop(group_name)
                        self._dismissed_msg_ids.update(dismissed_msg_ids)
                        for dismissed_msg_id in dismissed_msg_ids:
                            self.dbus_interface_obj.CloseNotification(dismissed_msg_id)
                        break

            else:
                print("{} [=] signal_handler (was not expected) - msg_id: {}, action_id: {}".format(
                    pendulum.now().to_datetime_string(),
                    msg_id, action_id,
                ))
        else:
            print("{} [=] signal_handler (unknown) - args: {}".format(
                pendulum.now().to_datetime_string(),
                args,
            ))

    def join(self) -> None:
        self._thread.join()

    def quit(self) -> None:
        if self._glib_loop.is_running():
            self._glib_loop.quit()

    def wait_for_message_ids(self, message_ids: Union[Set[int], int]) -> None:
        if isinstance(message_ids, int):
            message_ids = {message_ids}

        if self._glib_loop.is_running():
            while message_ids & set(self._waiting_for_the_ip.keys()):
                sleep(0.1)
        else:
            print("{} [=] Notification - wait_for_message_ids - _glib_loop is not running".format(
                pendulum.now().to_datetime_string(),
            ))


def Notifications() -> _Notifications:
    global _LOCK_SCREEN_NOTIFIER

    if _LOCK_SCREEN_NOTIFIER is None:
        _LOCK_SCREEN_NOTIFIER = _Notifications()

    return _LOCK_SCREEN_NOTIFIER


class TestNotification(unittest.TestCase):
    def test_send_notification(self) -> None:
        _notifications = Notifications()
        replace_id = _notifications.send_notification(
            "test_send_notification",
            "message",
            timeout_sec=100,
        )
        self.assertTrue(replace_id)

    def test_send_notification_with_icon(self) -> None:
        _notifications = Notifications()
        replace_id = _notifications.send_notification(
            "test_send_notification_with_icon",
            "message3",
            icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
            timeout_sec=100,
        )
        self.assertTrue(replace_id)

    def test_send_notification_with_button(self) -> None:
        _notifications = Notifications()

        received_arguments = []

        def quit_loop(msg_id: int, action_id: int) -> None:
            received_arguments.append(msg_id)
            received_arguments.append(action_id)

        replace_id = _notifications.send_notification(
            title="test_send_notification_with_button",
            message="click the button",
            icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
            actions=["Start"],
            action_callback_function=quit_loop,
            timeout_sec=100,
        )

        self.assertTrue(replace_id)
        self.assertEqual(2, received_arguments.__len__())
        self.assertEqual(replace_id, {received_arguments[0]})
        self.assertEqual(1, received_arguments[1])

    def test_send_notification_with_multiple_button(self) -> None:
        _notifications = Notifications()

        received_arguments = []

        def quit_loop(msg_id: int, action_id: int) -> None:
            received_arguments.append((msg_id, action_id))

        replace_id = _notifications.send_notification(
            title="test_send_notification_with_multiple_button",
            message="click the button 2",
            icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
            actions=["1", "2", "3"],
            action_callback_function=quit_loop,
            timeout_sec=100,
        )

        self.assertTrue(replace_id)
        self.assertEqual(3, received_arguments.__len__())
        self.assertEqual(replace_id, set([msg_id for msg_id, action_id in received_arguments]))
        self.assertEqual(1, received_arguments[0][1])
        self.assertEqual(1, received_arguments[1][1])
        self.assertEqual(1, received_arguments[2][1])

    def test_send_notification_with_multiple_button_and_group(self) -> None:
        _notifications = Notifications()
        _notifications._delay_between_notifications = 1

        received_arguments = []

        def quit_loop(msg_id: int, action_id: int) -> None:
            received_arguments.append((msg_id, action_id))

        replace_id = _notifications.send_notification(
            title="test_send_notification_with_multiple_button_and_group",
            message="click the button 2",
            icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
            actions=["1", "2", "3"],
            action_callback_function=quit_loop,
            timeout_sec=3000,
            group_name="test_send_notification_with_multiple_button_and_group",
        )

        self.assertTrue(replace_id)
        self.assertEqual(1, received_arguments.__len__())
        self.assertNotEqual(replace_id, set([msg_id for msg_id, action_id in received_arguments]))
        self.assertIn(received_arguments[0][0], replace_id)
        self.assertEqual(1, received_arguments[0][1])

        received_arguments.clear()

        replace_id = _notifications.send_notification(
            title="test_send_notification_with_multiple_button_and_group (again)",
            message="click the button 2",
            icon_path="/usr/share/icons/breeze/apps/48/ktimetracker.svg",
            actions=["1 (again)", "2 (again)", "3 (again)"],
            action_callback_function=quit_loop,
            timeout_sec=3000,
            group_name="test_send_notification_with_multiple_button_and_group",
        )

        self.assertTrue(replace_id)
        self.assertEqual(1, received_arguments.__len__())
        self.assertNotEqual(replace_id, set([msg_id for msg_id, action_id in received_arguments]))
        self.assertIn(received_arguments[0][0], replace_id)
        self.assertEqual(1, received_arguments[0][1])
