from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import process_turn, run_voice_mode
from main import _listen_pending_voice_follow_up, set_pending
from src.audio_io import ListenResult
from src.command_parser import CommandType, parse_command_text
from src.file_transactions import FileTransactions
from src.file_workspace import FileWorkspace
from src.task_router import ActionType, AssistantAction
from src.action_policy import ActionPolicy, ALL_SCOPES
from src.voice_file_confirmation import VoiceFileConfirmation
from tools.smoke_test_v11_daily_workflow import make_context
from tools.test_workspace_temp import workspace_tempdir

ROOT = Path(__file__).resolve().parents[1]


class VoiceFileRoutingTests(unittest.TestCase):
    def test_file_changes_require_internal_scope_and_never_model_authority(self):
        self.assertNotIn("modify_files", ALL_SCOPES)
        action = AssistantAction(ActionType.FILE_MUTATION, source="local")
        self.assertFalse(ActionPolicy().check(action).allowed)
        self.assertTrue(ActionPolicy(("modify_files",)).check(action).allowed)
        self.assertFalse(ActionPolicy(("modify_files",)).check(
            replace(action, source="llm_router", confidence=1)
        ).allowed)

    def test_typed_command_does_not_allow_model_routing(self):
        self.assertEqual(parse_command_text("удали файл report.txt").type, CommandType.FILE_MUTATION)
        self.assertFalse(ActionPolicy(("modify_files",)).check(AssistantAction(ActionType.FILE_MUTATION, source="llm_router", confidence=1)).allowed)

    def test_voice_undo_phrases_are_exact_typed_file_actions(self):
        for phrase in (
            "отмени последнее файловое действие",
            "отмени последнюю файловую операцию",
            "откати последнее файловое действие",
        ):
            with self.subTest(phrase=phrase):
                parsed = parse_command_text(phrase)
                self.assertEqual(parsed.type, CommandType.FILE_MUTATION)
                self.assertEqual(parsed.target, "undo")

    def test_explicit_wake_grants_and_confirmation_before_trash(self):
        with workspace_tempdir("astra-voice-route-", ROOT) as temp:
            path = Path(temp) / "report.txt"
            path.write_text("sample", encoding="utf-8")
            transactions = FileTransactions(FileWorkspace(Path(temp)))
            transactions.grant_trash(True)
            adapter = VoiceFileConfirmation(transactions)
            ctx, responses, ai, *_ = make_context()
            ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=(*ctx.settings.action_permissions, "modify_files")), file_mutation=adapter)
            with patch("src.file_transactions.send2trash", side_effect=lambda value: Path(value).unlink()) as trash:
                process_turn("Астра, удали файл report.txt", ctx)
                self.assertTrue(path.exists())
                self.assertIn("подтверждаю", responses[-1])
                trash.assert_not_called()
                process_turn("подтверждаю", ctx)
                trash.assert_called_once()
            self.assertFalse(path.exists())
            self.assertEqual(ai.ask_calls, 0)
            self.assertEqual(ai.route_calls, 0)

    def test_no_scope_or_no_wake_cannot_change_files(self):
        ctx, responses, ai, *_ = make_context()
        with patch("src.file_transactions.send2trash") as trash:
            process_turn("Астра, удали файл report.txt", ctx)
            self.assertIn("отключён", responses[-1])
            process_turn("удали файл report.txt", ctx)
            process_turn("Астра, отмени последнее файловое действие", ctx)
            trash.assert_not_called()
        self.assertEqual(ai.ask_calls, 0)

    def test_wake_is_required_even_when_other_commands_allow_no_wake(self):
        ctx, responses, ai, *_ = make_context()
        adapter = Mock()
        settings = replace(ctx.settings, allow_commands_without_wake=True, action_permissions=(*ctx.settings.action_permissions, "modify_files"))
        ctx = replace(ctx, settings=settings, file_mutation=adapter)
        process_turn("удали файл report.txt", ctx)
        adapter.prepare.assert_not_called()
        adapter.confirm.assert_not_called()
        process_turn("отмени последнее файловое действие", ctx)
        adapter.undo_last.assert_not_called()
        self.assertEqual(ai.ask_calls, 0)

    def test_invalid_or_ambiguous_path_fails_closed(self):
        for text in (
            "удали файл ../secret",
            "удали файл C:\\Windows\\win.ini",
            "создай папку ../secret",
            "перемести файл a.txt в b.txt в c.txt",
            "скопируй файл",
        ):
            with self.subTest(text=text):
                parsed = parse_command_text(text)
                self.assertEqual(parsed.type, CommandType.FILE_MUTATION)
                self.assertEqual(parsed.target, "__file_mutation_help__")

    def test_parser_accepts_nested_workspace_paths_and_folder_destinations(self):
        parsed = parse_command_text("скопируй файл входящие\\отчет.pdf в папку архив\\2026")
        self.assertEqual(parsed.type, CommandType.FILE_MUTATION)
        self.assertEqual(parsed.target, "copy")
        self.assertEqual(
            json.loads(parsed.query),
            {"source": "входящие/отчет.pdf", "destination": "архив/2026", "destination_is_folder": True},
        )
        folder = parse_command_text("создай пустую папку Проекты\\Новый")
        self.assertEqual(folder.type, CommandType.FILE_MUTATION)
        self.assertEqual(folder.target, "mkdir")
        self.assertEqual(
            json.loads(folder.query),
            {"source": "", "destination": "Проекты/Новый", "destination_is_folder": False},
        )

    def test_voice_folder_creation_requires_scope_preview_and_confirmation(self):
        with workspace_tempdir("astra-voice-route-", ROOT) as temp:
            root = Path(temp)
            (root / "Projects").mkdir()
            target = root / "Projects" / "New"
            transactions = FileTransactions(FileWorkspace(root))
            transactions.grant_write(True)
            ctx, responses, ai, *_ = make_context()
            ctx = replace(
                ctx,
                settings=replace(
                    ctx.settings,
                    action_permissions=(*ctx.settings.action_permissions, "modify_files"),
                ),
                file_mutation=VoiceFileConfirmation(transactions),
            )

            process_turn("Астра, создай пустую папку Projects/New", ctx)
            self.assertFalse(target.exists())
            self.assertIn("подтверждаю", responses[-1])
            process_turn("подтверждаю", ctx)

            self.assertTrue(target.is_dir())
            self.assertIn("Папка создана", responses[-1])
            process_turn("Астра, отмени последнее файловое действие", ctx)
            self.assertFalse(target.exists())
            self.assertIn("отменено", responses[-1])
            self.assertEqual(ai.ask_calls, 0)
            self.assertEqual(ai.route_calls, 0)

    def test_voice_undo_without_prior_operation_fails_closed_without_llm(self):
        with workspace_tempdir("astra-voice-route-", ROOT) as temp:
            transactions = FileTransactions(FileWorkspace(Path(temp)))
            adapter = VoiceFileConfirmation(transactions)
            ctx, responses, ai, *_ = make_context()
            ctx = replace(
                ctx,
                settings=replace(
                    ctx.settings,
                    action_permissions=(*ctx.settings.action_permissions, "modify_files"),
                ),
                file_mutation=adapter,
            )

            process_turn("Астра, отмени последнее файловое действие", ctx)

            self.assertIn("Нет доступного", responses[-1])
            self.assertEqual(ai.ask_calls, 0)
            self.assertEqual(ai.route_calls, 0)

    def test_revoking_scope_before_confirmation_cancels_preview(self):
        with workspace_tempdir("astra-voice-route-", ROOT) as temp:
            path = Path(temp) / "report.txt"
            path.write_text("sample", encoding="utf-8")
            transactions = FileTransactions(FileWorkspace(Path(temp)))
            transactions.grant_trash(True)
            ctx, responses, *_ = make_context()
            enabled = replace(ctx, settings=replace(ctx.settings, action_permissions=(*ctx.settings.action_permissions, "modify_files")), file_mutation=VoiceFileConfirmation(transactions))
            process_turn("Астра, удали файл report.txt", enabled)
            disabled = replace(enabled, settings=ctx.settings)
            with patch("src.file_transactions.send2trash") as trash:
                process_turn("подтверждаю", disabled)
                trash.assert_not_called()
            self.assertTrue(path.exists())
            self.assertIn("отключён", responses[-1])

    def test_voice_copy_is_confirmed_before_execution(self):
        with workspace_tempdir("astra-voice-route-", ROOT) as temp:
            root = Path(temp)
            (root / "Inbox").mkdir()
            (root / "Archive").mkdir()
            (root / "Inbox" / "a.txt").write_text("hello", encoding="utf-8")
            transactions = FileTransactions(FileWorkspace(root))
            transactions.grant_write(True)
            ctx, responses, *_ = make_context()
            ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=(*ctx.settings.action_permissions, "modify_files")), file_mutation=VoiceFileConfirmation(transactions))
            process_turn("Астра, скопируй файл Inbox/a.txt в папку Archive", ctx)
            self.assertFalse((root / "Archive" / "a.txt").exists())
            process_turn("подтверждаю", ctx)
            self.assertEqual((root / "Archive" / "a.txt").read_text(encoding="utf-8"), "hello")
            self.assertIn("скопирован", responses[-1])
            process_turn("Астра, отмени последнее файловое действие", ctx)
            self.assertFalse((root / "Archive" / "a.txt").exists())
            self.assertEqual((root / "Inbox" / "a.txt").read_text(encoding="utf-8"), "hello")
            self.assertIn("отменено", responses[-1])

    def test_unrecognized_confirmation_cancels_preview(self):
        ctx, responses, *_ = make_context()
        adapter = Mock()
        ctx = replace(ctx, file_mutation=adapter)
        set_pending(ctx.state, "file_mutation_confirmation")

        class NoSpeech:
            def listen_once(self, **_kwargs):
                return ListenResult(False, error="Речь не распознана.")

        self.assertTrue(_listen_pending_voice_follow_up(NoSpeech(), ctx, ctx.settings, ctx.logger))
        adapter.cancel.assert_called_once_with()
        adapter.confirm.assert_not_called()
        self.assertEqual(ctx.state.pending_kind, "")
        self.assertIn("отменено", responses[-1])

    def test_microphone_failure_cancels_preview_before_stopping_voice(self):
        ctx, _responses, *_ = make_context()
        adapter = Mock()
        ctx = replace(ctx, file_mutation=adapter)
        set_pending(ctx.state, "file_mutation_confirmation")

        class MissingMicrophone:
            def listen_once(self, **_kwargs):
                return ListenResult(False, error="Микрофон недоступен.", failure_kind="microphone")

        with patch("main.emit_event") as emit_event:
            self.assertFalse(_listen_pending_voice_follow_up(MissingMicrophone(), ctx, ctx.settings, ctx.logger))
        adapter.cancel.assert_called_once_with()
        adapter.confirm.assert_not_called()
        self.assertEqual(ctx.state.pending_kind, "")
        emit_event.assert_called_once()

    def test_voice_runtime_injects_adapter_and_cleans_it_up_on_exit(self):
        with workspace_tempdir("astra-voice-runtime-", ROOT) as temp:
            root = Path(temp)
            (root / "a.txt").write_text("hello", encoding="utf-8")
            transactions = FileTransactions(FileWorkspace(root))
            transactions.grant_write(True)
            adapter = VoiceFileConfirmation(transactions)
            adapter.cancel = Mock(wraps=adapter.cancel)
            ctx, _responses, *_ = make_context()
            settings = replace(
                ctx.settings,
                action_permissions=(*ctx.settings.action_permissions, "modify_files"),
            )
            with patch("src.desktop_file_search.DesktopFileSearchChannel"), patch("main.VoiceIO") as voice_type:
                voice = voice_type.return_value
                voice.microphone = object()
                voice.listen_once.side_effect = [
                    ListenResult(True, text="Астра, скопируй файл a.txt в b.txt"),
                    ListenResult(True, text="подтверждаю"),
                    ListenResult(False, error="Микрофон недоступен.", failure_kind="microphone"),
                ]
                run_voice_mode(
                    settings, ctx.apps, ctx.app_manager, ctx.keyboard, ctx.folders,
                    ctx.system, ctx.vpn, ctx.windows, ctx.ai_client, ctx.logger,
                    routines=ctx.routines, file_mutation=adapter,
                )
            self.assertEqual((root / "b.txt").read_text(encoding="utf-8"), "hello")
            self.assertEqual(adapter.cancel.call_count, 2)  # preview replacement plus runtime shutdown


if __name__ == "__main__":
    unittest.main()
