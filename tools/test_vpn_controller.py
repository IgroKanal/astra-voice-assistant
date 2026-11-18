import unittest
from dataclasses import replace

from src.config_loader import Settings
from src.vpn_controller import VpnController
from src.windows_service_control import WindowsServiceError


class FakeServiceControl:
    def __init__(self, status="stopped", failure=None):
        self.status = status
        self.failure = failure
        self.queries = []
        self.transitions = []

    def query_status(self, service_name):
        self.queries.append(service_name)
        if self.failure:
            raise self.failure
        return self.status

    def set_state(self, service_name, desired, timeout_seconds):
        self.transitions.append((service_name, desired, timeout_seconds))
        if self.failure:
            raise self.failure
        self.status = desired
        return self.status


class VpnControllerServiceApiTests(unittest.TestCase):
    def make_controller(self, service_api):
        settings = replace(
            Settings(),
            vpn_enabled=True,
            vpn_tunnel_service_name="WireGuardTunnel$home",
            vpn_command_timeout_seconds=10,
        )
        return VpnController(settings, service_control=service_api)

    def test_status_reads_exact_selected_service(self):
        service_api = FakeServiceControl("running")
        result = self.make_controller(service_api).status()
        self.assertEqual(result.status, "running")
        self.assertTrue(result.ok)
        self.assertEqual(service_api.queries, ["WireGuardTunnel$home"])

    def test_connect_and_disconnect_use_typed_service_targets(self):
        service_api = FakeServiceControl("stopped")
        controller = self.make_controller(service_api)

        connected = controller.connect()
        disconnected = controller.disconnect()

        self.assertEqual(connected.status, "running")
        self.assertEqual(disconnected.status, "stopped")
        self.assertEqual(
            [(name, target) for name, target, _timeout in service_api.transitions],
            [
                ("WireGuardTunnel$home", "running"),
                ("WireGuardTunnel$home", "stopped"),
            ],
        )
        self.assertEqual([timeout for _name, _target, timeout in service_api.transitions], [10, 10])

    def test_configured_transition_timeout_has_a_sixty_second_ceiling(self):
        service_api = FakeServiceControl("stopped")
        settings = replace(
            Settings(),
            vpn_enabled=True,
            vpn_tunnel_service_name="WireGuardTunnel$home",
            vpn_command_timeout_seconds=500,
        )
        controller = VpnController(settings, service_control=service_api)

        controller.connect()

        self.assertEqual(service_api.transitions[0][2], 60)

    def test_access_denied_and_missing_service_are_reported_without_shell_fallback(self):
        denied = self.make_controller(FakeServiceControl("stopped", WindowsServiceError(5)))
        self.assertEqual(denied.connect().status, "access_denied")

        missing = self.make_controller(FakeServiceControl("stopped", WindowsServiceError(1060)))
        self.assertEqual(missing.status().status, "not_found")

    def test_disabled_vpn_never_queries_service_controller(self):
        service_api = FakeServiceControl("running")
        controller = self.make_controller(service_api)
        controller.settings = replace(controller.settings, vpn_enabled=False)

        self.assertEqual(controller.status().status, "disabled")
        self.assertEqual(service_api.queries, [])


if __name__ == "__main__":
    unittest.main()
