import unittest
from unittest.mock import patch

from src.config_loader import Settings
from src.system_discovery import discover_vpn_tunnel_services
from src.vpn_controller import VpnController
from tools.test_system_discovery import FakeRegistry


class VpnDiscoveryTests(unittest.TestCase):
    def test_inventory_selects_only_supported_tunnel_services(self):
        base = r'SYSTEM\CurrentControlSet\Services'
        registry = FakeRegistry({}, {('machine', base): [
            'AmneziaWGTunnel$work', 'WireGuardTunnel$home', 'WireGuardManager', 'random']})
        self.assertEqual(discover_vpn_tunnel_services(registry=registry),
                         ('AmneziaWGTunnel$work', 'WireGuardTunnel$home'))

    @patch('src.vpn_controller.discover_vpn_tunnel_services')
    def test_status_uses_unique_discovery_only_when_configured_service_missing(self, discover):
        controller = VpnController(Settings())
        discover.return_value = ('WireGuardTunnel$home',)
        with patch.object(controller, '_get_service_status', side_effect=['not_found', 'running']) as query:
            result = controller.status()
        self.assertEqual(result.status, 'running')
        self.assertEqual(query.call_args_list[1].args[0], 'WireGuardTunnel$home')
        with patch.object(controller, '_get_service_status', return_value='stopped'):
            self.assertEqual(controller.status().status, 'stopped')
        self.assertEqual(discover.call_count, 1)

    @patch('src.vpn_controller.discover_vpn_tunnel_services')
    def test_multiple_tunnels_do_not_select_one(self, discover):
        discover.return_value = ('WireGuardTunnel$one', 'WireGuardTunnel$two')
        controller = VpnController(Settings())
        with patch.object(controller, '_get_service_status', return_value='not_found') as query:
            self.assertEqual(controller.status().status, 'ambiguous')
            query.assert_called_once()

    @patch('src.vpn_controller.discover_vpn_tunnel_services')
    def test_discovery_never_changes_tunnel(self, discover):
        controller = VpnController(Settings())
        with patch.object(controller, '_get_service_status', return_value='not_found'), \
             patch.object(controller, '_set_service_state') as mutate:
            controller.connect()
            controller.disconnect()
        discover.assert_not_called()
        mutate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
