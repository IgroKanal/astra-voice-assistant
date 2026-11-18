import unittest
from unittest.mock import Mock
from unittest.mock import patch

from src.windows_service_control import WindowsServiceControl


class WindowsServiceControlTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.OpenSCManagerW.return_value = 101
        self.api.OpenServiceW.return_value = 202
        self.states = []

        def query(_handle, _info_level, status_ptr, _size, returned_ptr):
            state_name = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            state_value = {
                "stopped": 1,
                "startpending": 2,
                "stoppending": 3,
                "running": 4,
                "continuepending": 5,
                "pausepending": 6,
                "paused": 7,
            }[state_name]
            status_ptr._obj.dwCurrentState = state_value
            returned_ptr._obj.value = 36
            return 1

        self.api.QueryServiceStatusEx.side_effect = query
        self.control = WindowsServiceControl(self.api)

    def test_query_uses_exact_service_name_and_closes_handles(self):
        self.states[:] = ["running"]

        self.assertEqual(self.control.query_status("WireGuardTunnel$home"), "running")
        self.api.OpenServiceW.assert_called_once_with(
            101, "WireGuardTunnel$home", WindowsServiceControl.SERVICE_QUERY_STATUS
        )
        self.api.CloseServiceHandle.assert_any_call(202)
        self.api.CloseServiceHandle.assert_any_call(101)

    def test_start_changes_only_requested_service_and_reports_final_state(self):
        self.states[:] = ["stopped", "running"]
        self.api.StartServiceW.return_value = 1

        result = self.control.set_state("AmneziaWGTunnel$work", "running", 1)

        self.assertEqual(result, "running")
        self.api.OpenServiceW.assert_called_once_with(
            101,
            "AmneziaWGTunnel$work",
            WindowsServiceControl.SERVICE_QUERY_STATUS
            | WindowsServiceControl.SERVICE_START
            | WindowsServiceControl.SERVICE_PAUSE_CONTINUE,
        )
        self.api.StartServiceW.assert_called_once_with(202, 0, None)
        self.api.ControlService.assert_not_called()

    def test_stop_uses_only_query_and_stop_access(self):
        self.states[:] = ["running", "stopped"]
        self.api.ControlService.return_value = 1

        result = self.control.set_state("WireGuardTunnel$home", "stopped", 1)

        self.assertEqual(result, "stopped")
        self.api.OpenServiceW.assert_called_once_with(
            101,
            "WireGuardTunnel$home",
            WindowsServiceControl.SERVICE_QUERY_STATUS | WindowsServiceControl.SERVICE_STOP,
        )
        self.api.ControlService.assert_called_once()

    def test_pending_state_is_bounded_and_does_not_issue_a_second_command(self):
        self.states[:] = ["startpending", "startpending", "startpending"]
        with patch("src.windows_service_control.time.monotonic", side_effect=[100.0, 101.0]), \
             patch("src.windows_service_control.time.sleep") as sleep:
            result = self.control.set_state("WireGuardTunnel$home", "running", 1)

        self.assertEqual(result, "startpending")
        self.api.StartServiceW.assert_not_called()
        self.api.ControlService.assert_not_called()
        sleep.assert_not_called()

    def test_invalid_names_and_unbounded_timeouts_are_rejected_before_open(self):
        for name in ("", " bad\nname", "x" * 257):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.control.query_status(name)

        for timeout in (0, -1, float("inf"), 121):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.control.set_state("WireGuardTunnel$home", "running", timeout)

        self.api.OpenSCManagerW.assert_not_called()


if __name__ == "__main__":
    unittest.main()
