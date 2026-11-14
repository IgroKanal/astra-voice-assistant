import json
import queue
import sys
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import process_turn
from src.action_policy import DEFAULT_SCOPES, ActionPolicy
from src.command_parser import CommandType, FILE_SEARCH_HELP_TARGET, is_command_like_text, parse_command_text
from src.config_loader import Settings
from src.desktop_settings import AIProfile
from src.desktop_file_search import (
    CONTROL_PREFIX,
    DesktopFileSearchChannel,
    encode_search_result,
    make_search_request,
    make_search_result,
    parse_control_line,
    parse_search_request,
    validate_query,
)
from src.file_workspace import FileWorkspace
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class _QueueLineStream:
    def __init__(self):
        self.lines = queue.Queue()

    def readline(self, _limit=-1):
        return self.lines.get(timeout=3)

    def feed(self, line):
        self.lines.put(line)


class VoiceFileSearchTests(unittest.TestCase):
    def test_filename_phrases_are_typed_and_command_like(self):
        parsed = parse_command_text("найди файл Отчёт 2026.pdf")
        self.assertEqual(parsed.type, CommandType.FILE_SEARCH)
        self.assertEqual(parsed.target, "Отчёт 2026.pdf")
        self.assertEqual(parse_command_text("поищи документ").target, FILE_SEARCH_HELP_TARGET)
        self.assertTrue(is_command_like_text("найди файл отчёт"))

    def test_query_is_only_a_bounded_filename_fragment(self):
        self.assertEqual(validate_query("  отчёт  2026.pdf  "), "отчёт 2026.pdf")
        for value in ("x", "a" * 121, "C:\\private.txt", "../private.txt", "name\u202efile.txt"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_query(value)

    def test_ipc_schemas_reject_unknown_fields_and_path_traversal(self):
        request = make_search_request("a" * 32, "report")
        self.assertEqual(parse_search_request(json.dumps(request))["query"], "report")
        request["extra"] = "ignored?"
        with self.assertRaises(ValueError):
            parse_search_request(json.dumps(request))
        with self.assertRaises(ValueError):
            make_search_result("a" * 32, "ok", 1, ["..\\secret.txt"])
        valid = make_search_result("a" * 32, "ok", 1, ["reports\\report.txt"])
        self.assertEqual(parse_control_line(encode_search_result(valid).rstrip()), valid)
        self.assertIsNone(parse_control_line(CONTROL_PREFIX + '{"version":1,"type":"file_search_result"}'))

    def test_runtime_channel_pairs_one_bounded_request_with_reply(self):
        stream = _QueueLineStream()
        emitted = []

        def emit(kind, text):
            emitted.append((kind, text))
            request = parse_search_request(text)
            reply = make_search_result(request["request_id"], "ok", 2, ["one.txt", "folder\\two.txt"])
            stream.feed(encode_search_result(reply))
            return True

        channel = DesktopFileSearchChannel(emit=emit)
        with patch.dict("os.environ", {"ASTRA_DESKTOP_EVENTS": "1"}):
            self.assertTrue(channel.start_control_reader(stream))
            result = channel.search("report")
        stream.feed("")
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "file_search_request")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["files"], ["one.txt", "folder\\two.txt"])

    def test_voice_search_requires_wake_scope_and_never_uses_llm(self):
        ctx, responses, ai, *_ = make_context()
        search = Mock(return_value={
            "status": "ok", "count": 1, "files": ["Reports\\contract.pdf"],
        })
        settings = replace(
            ctx.settings,
            action_permissions=("files",),
            allow_commands_without_wake=True,
        )
        ctx = replace(ctx, settings=settings, file_search=search)
        process_turn("Астра, найди файл contract.pdf", ctx)
        self.assertIn("1 совпадение", responses[-1])
        self.assertIn("Reports\\contract.pdf", responses[-1])
        search.assert_called_once_with("contract.pdf")
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

        process_turn("найди файл contract.pdf", ctx)
        self.assertIn("Назови меня", responses[-1])
        self.assertEqual(search.call_count, 1)

    def test_revoked_files_scope_blocks_before_desktop_request(self):
        ctx, responses, _ai, *_ = make_context()
        search = Mock(side_effect=AssertionError("file search must not be requested"))
        ctx = replace(ctx, file_search=search)
        process_turn("Астра, найди файл contract.pdf", ctx)
        self.assertIn("навык отключён", responses[-1])
        search.assert_not_called()

    def test_separate_files_scope_blocks_search_and_router_cannot_create_it(self):
        action = AssistantAction(ActionType.FILE_SEARCH, query="report", source="local_parser")
        self.assertFalse(ActionPolicy(()).check(action).allowed)
        self.assertTrue(ActionPolicy(("files",)).check(action).allowed)
        routed = AssistantAction(ActionType.FILE_SEARCH, query="report", source="llm_router", confidence=1.0)
        self.assertFalse(ActionPolicy(("files",)).check(routed).allowed)

    def test_new_file_search_scope_is_opt_in_for_fresh_profiles(self):
        self.assertNotIn("files", DEFAULT_SCOPES)
        self.assertNotIn("files", Settings().action_permissions)
        self.assertNotIn("files", AIProfile().allowed_scopes)
        action = AssistantAction(ActionType.FILE_SEARCH, query="report", source="local_parser")
        self.assertFalse(ActionPolicy().check(action).allowed)

    def test_ui_search_uses_only_live_selected_workspace_and_revokes_on_close(self):
        import runpy
        import tempfile
        root_path = Path(__file__).resolve().parents[1]
        AstraDesktop = runpy.run_path(str(root_path / "astra_desktop.pyw"))["AstraDesktop"]

        class Panel:
            def winfo_exists(self):
                return True

        with tempfile.TemporaryDirectory(prefix="astra-voice-search-", dir=root_path) as temp:
            root = Path(temp)
            (root / "contract.pdf").write_bytes(b"file metadata only")
            (root / ".env").write_text("secret", encoding="utf-8")
            panel = Panel()
            app = AstraDesktop.__new__(AstraDesktop)
            app.active_file_workspace = FileWorkspace(root)
            app.active_file_panel = panel
            app._file_search_lock = threading.RLock()
            app._file_search_generation = 1
            app._file_search_jobs = {}
            app.bridge = Mock()
            replied = threading.Event()
            app.bridge.reply_file_search.side_effect = lambda _result, **_kwargs: replied.set() or True

            request = make_search_request("b" * 32, "contract")
            app._handle_file_search_request(json.dumps(request))
            self.assertTrue(replied.wait(3))
            result = app.bridge.reply_file_search.call_args.args[0]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["files"], ["contract.pdf"])
            self.assertNotIn("secret", json.dumps(result))

            app._revoke_file_workspace(panel)
            self.assertIsNone(app.active_file_workspace)
            replied.clear()
            request = make_search_request("c" * 32, "contract")
            app._handle_file_search_request(json.dumps(request))
            self.assertTrue(replied.wait(1))
            self.assertEqual(app.bridge.reply_file_search.call_args.args[0]["status"], "no_workspace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
