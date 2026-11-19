from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from main import _listen_pending_voice_follow_up, handle_action, process_turn
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class ActionConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.responses, _ai, self.apps, *_ = make_context()

    def request_close(self):
        handle_action(
            AssistantAction(ActionType.CLOSE_APP, target="telegram", source="local"),
            self.ctx,
        )

    def test_close_app_waits_for_exact_one_time_confirmation(self):
        self.request_close()
        self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
        self.assertEqual(self.apps.closed, [])
        self.assertIn("telegram", self.responses[-1])
        process_turn("да", self.ctx)
        self.assertEqual(self.apps.closed, ["telegram"])
        self.assertEqual(self.ctx.state.pending_kind, "")

    def test_audit_records_confirmation_request_before_dispatch(self):
        audit = Mock()
        self.ctx = replace(self.ctx, audit=audit)
        self.request_close()
        audit.assert_called_once_with("close_app", "confirmation_requested")
        self.assertEqual(self.apps.closed, [])

    def test_refusal_and_expiry_never_close_app(self):
        self.request_close()
        process_turn("нет", self.ctx)
        self.assertEqual(self.apps.closed, [])

        self.request_close()
        self.ctx.state.pending_created_at -= 21
        process_turn("да", self.ctx)
        self.assertEqual(self.apps.closed, [])
        self.assertIn("истекло", self.responses[-1])

    def test_new_command_replaces_pending_close_without_executing_it(self):
        self.request_close()
        process_turn("Астра, открой телеграм", self.ctx)
        self.assertEqual(self.apps.closed, [])
        self.assertEqual(self.apps.opened, ["telegram"])
        self.assertEqual(self.ctx.state.pending_kind, "")

    def test_permissions_are_rechecked_when_confirmation_is_consumed(self):
        self.request_close()
        self.ctx = replace(
            self.ctx,
            settings=replace(self.ctx.settings, action_permissions=()),
        )
        process_turn("да", self.ctx)
        self.assertEqual(self.apps.closed, [])
        self.assertIn("отключён", self.responses[-1])

    def test_model_close_proposal_cannot_execute_without_user_confirmation(self):
        handle_action(
            AssistantAction(
                ActionType.CLOSE_APP,
                target="telegram",
                source="llm_router",
                confidence=1.0,
            ),
            self.ctx,
        )
        self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
        self.assertEqual(self.apps.closed, [])
        process_turn("да", self.ctx)
        self.assertEqual(self.apps.closed, ["telegram"])

    def test_vpn_changes_wait_but_status_is_read_only(self):
        vpn = Mock()
        vpn.disconnect.return_value = SimpleNamespace(ok=True, message="VPN отключён.")
        vpn.status.return_value = SimpleNamespace(ok=True, message="VPN выключен.")
        self.ctx = replace(self.ctx, vpn=vpn)

        handle_action(
            AssistantAction(ActionType.VPN_CONTROL, target="disconnect", source="local"),
            self.ctx,
        )
        vpn.disconnect.assert_not_called()
        self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
        process_turn("да", self.ctx)
        vpn.disconnect.assert_called_once_with()

        handle_action(
            AssistantAction(ActionType.VPN_CONTROL, target="status", source="local"),
            self.ctx,
        )
        vpn.status.assert_called_once_with()
        self.assertEqual(self.ctx.state.pending_kind, "")

    def test_closing_yandex_music_waits_before_stopping_or_closing(self):
        media = Mock()
        media.execute.return_value = SimpleNamespace(ok=True, message="Музыка остановлена.")
        self.ctx = replace(self.ctx, media=media)
        handle_action(
            AssistantAction(
                ActionType.MEDIA_CONTROL,
                target="shutdown_yandex_music",
                source="local",
            ),
            self.ctx,
        )
        media.execute.assert_not_called()
        process_turn("да", self.ctx)
        media.execute.assert_called_once_with("shutdown_yandex_music")

    def test_clearing_dialogue_waits_and_preserves_saved_memory_and_reminders(self):
        clear_dialogue = Mock()
        self.ctx.ai_client.clear_dialogue = clear_dialogue
        action = AssistantAction(ActionType.CLEAR_DIALOGUE, source="local")

        handle_action(action, self.ctx)
        clear_dialogue.assert_not_called()
        self.assertEqual(self.ctx.state.pending_kind, "action_confirmation")
        self.assertIn("Сохранённые заметки и напоминания не изменятся", self.responses[-1])

        process_turn("нет", self.ctx)
        clear_dialogue.assert_not_called()
        self.assertEqual(self.ctx.state.pending_kind, "")

        handle_action(action, self.ctx)
        process_turn("да", self.ctx)
        clear_dialogue.assert_called_once_with()
        self.assertEqual(self.ctx.state.pending_kind, "")

    def test_unrecognized_empty_confirmation_cancels_pending_action(self):
        self.request_close()
        process_turn("", self.ctx)
        self.assertEqual(self.ctx.state.pending_kind, "")
        self.assertEqual(self.apps.closed, [])
        self.assertIn("не распознано", self.responses[-1])

    def test_voice_followup_timeout_cancels_pending_action(self):
        self.request_close()
        voice = Mock()
        voice.listen_once.return_value = SimpleNamespace(ok=False, error="timeout")
        _listen_pending_voice_follow_up(
            voice,
            self.ctx,
            self.ctx.settings,
            self.ctx.logger,
        )
        self.assertEqual(self.ctx.state.pending_kind, "")
        self.assertEqual(self.apps.closed, [])
        self.assertIn("Действие отменено", self.responses[-1])

    def test_voice_followup_confirmation_executes_the_pending_action(self):
        self.request_close()
        voice = Mock()
        voice.listen_once.return_value = SimpleNamespace(ok=True, text="да")
        _listen_pending_voice_follow_up(
            voice,
            self.ctx,
            self.ctx.settings,
            self.ctx.logger,
        )
        self.assertEqual(self.apps.closed, ["telegram"])
        self.assertEqual(self.ctx.state.pending_kind, "")


if __name__ == "__main__":
    unittest.main()
