import pytest

from auto_worklog import toggl_handler


@pytest.fixture(autouse=True)
def fresh_toggl_singleton():
    """TogglHandler() is a process-wide singleton; give every test its own."""
    toggl_handler._TOGGL_HANDLER = None
    yield
    toggl_handler._TOGGL_HANDLER = None
