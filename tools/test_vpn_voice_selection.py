import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from main import _vpn_choice_index, handle_action, process_turn
from src.capability_overrides import CapabilityOverrideStore
from src.config_loader import Settings
from src.task_router import ActionType, AssistantAction
from src.vpn_controller import VpnActionResult, VpnController
from tools.smoke_test_v11_daily_workflow import make_context


class VpnVoiceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctx, self.responses, *_ = make_context()
        settings = replace(self.ctx.settings, vpn_tunnel_service_name="", vpn_enabled=True)
        self.store = CapabilityOverrideStore(self.root / "preferences.json")
        self.vpn = VpnController(settings, override_store=self.store)
        self.ctx = replace(self.ctx, settings=settings, vpn=self.vpn)
        self.action = AssistantAction(ActionType.VPN_CONTROL, target="connect", source="local")

    def test_voice_choice_is_revalidated_remembered_then_separately_confirmed(self):
        candidates = ("WireGuardTunnel$home", "AmneziaWGTunnel$work")
        audit = Mock()
        self.ctx = replace(self.ctx, audit=audit)
        with patch("src.vpn_controller.discover_vpn_tunnel_services", return_value=candidates), \
             patch.object(
                 self.vpn,
                 "connect",
                 return_value=VpnActionResult(True, "VPN включён.", "running"),
             ) as connect:
            handle_action(self.action, self.ctx)
            self.assertEqual(self.ctx.state.pending_kind, "vpn_service_selection")
            self.assertIn("1. WireGuard home", self.responses[-1])
            self.assertIn("2. AmneziaWG work", self.responses[-1])
            self.assertEqual(self.vpn.tunnel_service, "")
            connect.assert_not_called()
            audit.assert_called_once_with("vpn_control", "choice_requested")

            process_turn("второй", self.ctx)
            self.assertEqual(self.vpn.tunnel_service, "AmneziaWGTunnel$work")
            self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
            self.assertIn("Подтверди подключение VPN", self.responses[-1])
            self.assertEqual(self.store.load().vpn_service_preferred, "AmneziaWGTunnel$work")
            connect.assert_not_called()

            process_turn("да", self.ctx)
            connect.assert_called_once_with()
            self.assertEqual(self.ctx.state.pending_kind, "")

    def test_unique_candidate_is_auto_selected_but_still_needs_confirmation(self):
        with patch(
            "src.vpn_controller.discover_vpn_tunnel_services",
            return_value=("WireGuardTunnel$home",),
        ), patch.object(
            self.vpn,
            "connect",
            return_value=VpnActionResult(True, "VPN включён.", "running"),
        ) as connect:
            handle_action(self.action, self.ctx)
            self.assertEqual(self.vpn.tunnel_service, "WireGuardTunnel$home")
            self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
            self.assertEqual(self.store.load().vpn_service_preferred, "")
            connect.assert_not_called()

    def test_changed_inventory_invalidates_confirmation_before_connect(self):
        candidates = ("WireGuardTunnel$home", "AmneziaWGTunnel$work")
        with patch(
            "src.vpn_controller.discover_vpn_tunnel_services",
            side_effect=[candidates, candidates, candidates, candidates, (candidates[0],)],
        ), patch.object(
            self.vpn,
            "connect",
            return_value=VpnActionResult(True, "VPN включён.", "running"),
        ) as connect:
            handle_action(self.action, self.ctx)
            process_turn("2", self.ctx)
            self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
            process_turn("да", self.ctx)
            connect.assert_not_called()
            self.assertIn("изменилось", self.responses[-1])

    def test_cancel_expiry_and_new_command_never_connect(self):
        candidates = ("WireGuardTunnel$home", "AmneziaWGTunnel$work")
        with patch("src.vpn_controller.discover_vpn_tunnel_services", return_value=candidates), \
             patch.object(self.vpn, "connect") as connect:
            handle_action(self.action, self.ctx)
            process_turn("отмена", self.ctx)
            self.assertEqual(self.ctx.state.pending_kind, "")

            handle_action(self.action, self.ctx)
            self.ctx.state.pending_created_at -= 21
            process_turn("1", self.ctx)
            self.assertIn("истекло", self.responses[-1])

            handle_action(self.action, self.ctx)
            process_turn("Астра, открой телеграм", self.ctx)
            self.assertNotEqual(self.ctx.state.pending_kind, "vpn_service_selection")
            connect.assert_not_called()

    def test_missing_inventory_does_not_prompt_or_confirm_unavailable_vpn(self):
        with patch("src.vpn_controller.discover_vpn_tunnel_services", return_value=()), \
             patch.object(self.vpn, "connect") as connect:
            handle_action(self.action, self.ctx)
        self.assertEqual(self.ctx.state.pending_kind, "")
        self.assertIn("не найдены", self.responses[-1])
        connect.assert_not_called()

    def test_disabled_vpn_and_unbounded_choice_list_are_not_presented_as_available(self):
        self.vpn.settings = replace(self.vpn.settings, vpn_enabled=False)
        with patch("src.vpn_controller.discover_vpn_tunnel_services") as discover, \
             patch.object(self.vpn, "connect") as connect:
            handle_action(self.action, self.ctx)
            discover.assert_not_called()
            connect.assert_not_called()
        self.assertEqual(self.ctx.state.pending_kind, "")
        self.assertIn("отключены", self.responses[-1])

        self.vpn.settings = replace(self.vpn.settings, vpn_enabled=True)
        too_many = tuple(f"WireGuardTunnel$profile-{index}" for index in range(10))
        with patch("src.vpn_controller.discover_vpn_tunnel_services", return_value=too_many), \
             patch.object(self.vpn, "connect") as connect:
            handle_action(self.action, self.ctx)
            connect.assert_not_called()
        self.assertEqual(self.ctx.state.pending_kind, "")
        self.assertIn("слишком много", self.responses[-1])

    def test_voice_choice_accepts_only_exact_bounded_ordinals(self):
        self.assertEqual(_vpn_choice_index("2", 2), 1)
        self.assertEqual(_vpn_choice_index("второй", 2), 1)
        self.assertEqual(_vpn_choice_index("второе", 2), 1)
        self.assertEqual(_vpn_choice_index("четвёртая", 4), 3)
        self.assertIsNone(_vpn_choice_index("второй vpn", 2))
        self.assertIsNone(_vpn_choice_index("9", 2))
        self.assertIsNone(_vpn_choice_index("1", 10))


if __name__ == "__main__":
    unittest.main()
