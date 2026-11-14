import json
import os
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
from src.command_parser import CommandType, FILE_OPEN_HELP_TARGET, FILE_READ_HELP_TARGET, FILE_SEARCH_HELP_TARGET, is_command_like_text, parse_command_text
from src.config_loader import Settings
from src.desktop_settings import AIProfile
from src.desktop_file_search import (
    CONTROL_PREFIX,
    DesktopFileSearchChannel,
    encode_search_result,
    encode_file_result,
    make_file_open_request,
    make_file_open_result,
    make_file_read_request,
    make_file_read_result,
    make_search_request,
    make_search_result,
    parse_control_line,
    parse_file_open_request,
    parse_file_read_request,
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
        opened = parse_command_text("открой файл Отчёт 2026.pdf")
        self.assertEqual(opened.type, CommandType.FILE_OPEN)
        self.assertEqual(opened.target, "Отчёт 2026.pdf")
        self.assertEqual(parse_command_text("открой документ").target, FILE_OPEN_HELP_TARGET)
        read = parse_command_text("прочитай документ Отчёт 2026.pdf")
        self.assertEqual(read.type, CommandType.FILE_READ)
        self.assertEqual(read.target, "Отчёт 2026.pdf")
        self.assertEqual(parse_command_text("зачитай файл").target, FILE_READ_HELP_TARGET)
        self.assertEqual(parse_command_text("поищи документ").target, FILE_SEARCH_HELP_TARGET)
        self.assertTrue(is_command_like_text("найди файл отчёт"))
        self.assertTrue(is_command_like_text("прочитай файл отчёт.txt"))

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
        open_request = make_file_open_request("c" * 32, "report.pdf")
        self.assertEqual(parse_file_open_request(json.dumps(open_request))["type"], "file_open_request")
        open_request["unexpected"] = True
        with self.assertRaises(ValueError):
            parse_file_open_request(json.dumps(open_request))
        read_request = make_file_read_request("d" * 32, "report.txt")
        self.assertEqual(parse_file_read_request(json.dumps(read_request))["type"], "file_read_request")
        read_request["unexpected"] = True
        with self.assertRaises(ValueError):
            parse_file_read_request(json.dumps(read_request))
        with self.assertRaises(ValueError):
            make_search_result("a" * 32, "ok", 1, ["..\\secret.txt"])
        valid = make_search_result("a" * 32, "ok", 1, ["reports\\report.txt"])
        self.assertEqual(parse_control_line(encode_search_result(valid).rstrip()), valid)
        opened = make_file_open_result("d" * 32, "ok", "Reports\\report.pdf")
        self.assertEqual(parse_control_line(encode_file_result(opened).rstrip()), opened)
        read = make_file_read_result("f" * 32, "ok", "report.txt", "  Привет,\n мир!  ")
        self.assertEqual(read["text"], "Привет, мир!")
        self.assertEqual(parse_control_line(encode_file_result(read).rstrip()), read)
        with self.assertRaises(ValueError):
            make_file_read_result("f" * 32, "ok", "..\\secret.txt", "secret")
        with self.assertRaises(ValueError):
            make_file_read_result("f" * 32, "ok", "report.txt", "x" * 1601)
        self.assertIsNone(parse_control_line(encode_file_result(make_file_read_result("e" * 32, "read_failed")).rstrip().replace('"text":""', '"text":"unexpected"')))
        self.assertIsNone(parse_control_line(encode_file_result(make_file_open_result("e" * 32, "ambiguous")).rstrip().replace('"count":0', '"count":1')))
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

    def test_runtime_channel_pairs_exact_open_request_with_only_open_reply(self):
        stream = _QueueLineStream()
        emitted = []

        def emit(kind, text):
            emitted.append((kind, text))
            request = parse_file_open_request(text)
            stream.feed(encode_file_result(make_file_open_result(request["request_id"], "ok", "report.pdf")))
            return True

        channel = DesktopFileSearchChannel(emit=emit)
        with patch.dict("os.environ", {"ASTRA_DESKTOP_EVENTS": "1"}):
            self.assertTrue(channel.start_control_reader(stream))
            result = channel.open_exact("report.pdf")
        stream.feed("")
        self.assertEqual(emitted[0][0], "file_open_request")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["files"], ["report.pdf"])

    def test_runtime_channel_rejects_search_reply_for_open_request(self):
        stream = _QueueLineStream()

        def emit(_kind, text):
            request = parse_file_open_request(text)
            wrong_reply = make_search_result(request["request_id"], "ok", 1, ["report.pdf"])
            stream.feed(encode_search_result(wrong_reply))
            return True

        channel = DesktopFileSearchChannel(emit=emit)
        with patch.dict("os.environ", {"ASTRA_DESKTOP_EVENTS": "1"}):
            self.assertTrue(channel.start_control_reader(stream))
            result = channel.open_exact("report.pdf", timeout_seconds=0.1)
        stream.feed("")
        self.assertEqual(result["type"], "file_open_result")
        self.assertEqual(result["status"], "open_failed")

    def test_runtime_channel_pairs_bounded_read_with_strict_read_reply(self):
        stream = _QueueLineStream()
        emitted = []

        def emit(kind, text):
            emitted.append((kind, text))
            request = parse_file_read_request(text)
            stream.feed(encode_file_result(make_file_read_result(request["request_id"], "ok", "memo.txt", "Private excerpt")))
            return True

        channel = DesktopFileSearchChannel(emit=emit)
        with patch.dict("os.environ", {"ASTRA_DESKTOP_EVENTS": "1"}):
            self.assertTrue(channel.start_control_reader(stream))
            result = channel.read_exact("memo.txt")
        stream.feed("")
        self.assertEqual(emitted[0][0], "file_read_request")
        self.assertEqual(result["text"], "Private excerpt")

    def test_runtime_channel_rejects_open_reply_for_read_request(self):
        stream = _QueueLineStream()

        def emit(_kind, text):
            request = parse_file_read_request(text)
            stream.feed(encode_file_result(make_file_open_result(request["request_id"], "ok", "memo.txt")))
            return True

        channel = DesktopFileSearchChannel(emit=emit)
        with patch.dict("os.environ", {"ASTRA_DESKTOP_EVENTS": "1"}):
            self.assertTrue(channel.start_control_reader(stream))
            result = channel.read_exact("memo.txt", timeout_seconds=0.1)
        stream.feed("")
        self.assertEqual(result["type"], "file_read_result")
        self.assertEqual(result["status"], "read_failed")

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
        self.assertNotIn("open_files", DEFAULT_SCOPES)
        self.assertNotIn("open_files", Settings().action_permissions)
        self.assertNotIn("open_files", AIProfile().allowed_scopes)
        self.assertNotIn("read_files", DEFAULT_SCOPES)
        self.assertNotIn("read_files", Settings().action_permissions)
        self.assertNotIn("read_files", AIProfile().allowed_scopes)
        action = AssistantAction(ActionType.FILE_SEARCH, query="report", source="local_parser")
        self.assertFalse(ActionPolicy().check(action).allowed)

    def test_voice_open_requires_wake_separate_scope_and_never_uses_llm(self):
        ctx, responses, ai, *_ = make_context()
        open_file = Mock(return_value={"status": "ok", "count": 1, "files": ["Reports\\contract.pdf"]})
        settings = replace(ctx.settings, action_permissions=("open_files",), allow_commands_without_wake=True)
        ctx = replace(ctx, settings=settings, file_open=open_file)
        process_turn("Астра, открой файл contract.pdf", ctx)
        self.assertIn("Открываю файл contract.pdf", responses[-1])
        open_file.assert_called_once_with("contract.pdf")
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

        process_turn("открой файл contract.pdf", ctx)
        self.assertIn("Назови меня", responses[-1])
        self.assertEqual(open_file.call_count, 1)

    def test_voice_open_is_blocked_without_open_files_permission(self):
        ctx, responses, _ai, *_ = make_context()
        open_file = Mock(side_effect=AssertionError("must not reach desktop"))
        ctx = replace(ctx, file_open=open_file)
        process_turn("Астра, открой файл contract.pdf", ctx)
        self.assertIn("навык отключён", responses[-1])
        open_file.assert_not_called()

    def test_voice_document_read_requires_wake_and_separate_scope_and_never_uses_llm(self):
        from src.desktop_file_search import make_file_read_result

        ctx, responses, ai, *_ = make_context()
        secret_text = "Содержимое документа не должно появиться в чате"
        read_file = Mock(return_value=make_file_read_result("a" * 32, "ok", "memo.txt", secret_text))
        speak_private = Mock(return_value=True)
        settings = replace(
            ctx.settings,
            action_permissions=("read_files",),
            allow_commands_without_wake=True,
            tts_enabled=True,
            tts_engine="sapi",
        )
        ctx = replace(ctx, settings=settings, file_read=read_file, speak_private_local=speak_private)

        process_turn("Астра, прочитай файл memo.txt", ctx)
        self.assertIn("локальным голосом", responses[-1])
        self.assertNotIn(secret_text, " ".join(responses))
        read_file.assert_called_once_with("memo.txt")
        speak_private.assert_called_once_with(secret_text)
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

        process_turn("прочитай файл memo.txt", ctx)
        self.assertIn("Назови меня", responses[-1])
        self.assertEqual(read_file.call_count, 1)

    def test_voice_document_read_refuses_without_grant_or_local_sapi_before_fetch(self):
        ctx, responses, _ai, *_ = make_context()
        read_file = Mock(side_effect=AssertionError("document content must not be fetched"))
        speak_private = Mock(return_value=True)
        ctx = replace(ctx, file_read=read_file, speak_private_local=speak_private)
        process_turn("Астра, прочитай файл memo.txt", ctx)
        self.assertIn("навык отключён", responses[-1])
        read_file.assert_not_called()

        local_settings = replace(ctx.settings, action_permissions=("read_files",), tts_enabled=True, tts_engine="edge")
        ctx = replace(ctx, settings=local_settings)
        process_turn("Астра, прочитай файл memo.txt", ctx)
        self.assertIn("Windows SAPI", responses[-1])
        read_file.assert_not_called()
        speak_private.assert_not_called()

    def test_private_sapi_reader_does_not_emit_document_text_or_log_it(self):
        from src.audio_io import VoiceIO

        voice = VoiceIO.__new__(VoiceIO)
        voice.settings = replace(Settings(), tts_enabled=True, tts_engine="sapi")
        voice.tts_engine = Mock()
        voice.tts_has_russian_voice = True
        voice.logger = Mock()
        voice._log_tts_timing = Mock()
        events = []
        with patch("src.audio_io.emit_event", side_effect=lambda kind, text: events.append((kind, text)) or True):
            self.assertTrue(voice.speak_private_local("секретный текст документа"))
        self.assertEqual(voice.tts_engine.say.call_args.args[0], "секретный текст документа")
        self.assertTrue(events)
        self.assertTrue(all(kind == "state" for kind, _text in events))
        self.assertNotIn("секретный текст документа", json.dumps(events, ensure_ascii=False))
        self.assertNotIn("секретный текст документа", str(voice.logger.mock_calls))
        self.assertEqual(voice._log_tts_timing.call_args.args[1], "sapi_private")

        voice.settings = replace(voice.settings, tts_engine="edge")
        voice.tts_engine.reset_mock()
        self.assertFalse(voice.speak_private_local("не отправлять в облако"))
        voice.tts_engine.say.assert_not_called()

    def test_ui_voice_read_only_returns_unique_supported_excerpt_from_selected_workspace(self):
        import runpy
        import tempfile
        root_path = Path(__file__).resolve().parents[1]
        AstraDesktop = runpy.run_path(str(root_path / "astra_desktop.pyw"))["AstraDesktop"]

        class Panel:
            def winfo_exists(self):
                return True

        with tempfile.TemporaryDirectory(prefix="astra-voice-read-", dir=root_path) as temp:
            root = Path(temp)
            expected = "Локальный текст документа. " * 120
            (root / "memo.txt").write_text(expected, encoding="utf-8")
            (root / "script.exe").write_bytes(b"MZ")
            panel = Panel()
            app = AstraDesktop.__new__(AstraDesktop)
            app.active_file_workspace = FileWorkspace(root)
            app.active_file_panel = panel
            app._file_search_lock = threading.RLock()
            app._file_search_generation = 1
            app._file_search_jobs = {}
            app.bridge = Mock()
            replied = threading.Event()
            app.bridge.reply_file_request.side_effect = lambda _result, **_kwargs: replied.set() or True

            app._handle_file_read_request(json.dumps(make_file_read_request("9" * 32, "memo.txt")))
            self.assertTrue(replied.wait(3))
            result = app.bridge.reply_file_request.call_args.args[0]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["filename"], "memo.txt")
            self.assertLessEqual(len(result["text"]), 1600)
            self.assertNotIn(str(root), json.dumps(result, ensure_ascii=False))
            self.assertNotIn("script.exe", json.dumps(result, ensure_ascii=False))

            replied.clear()
            app._handle_file_read_request(json.dumps(make_file_read_request("8" * 32, "script.exe")))
            self.assertTrue(replied.wait(3))
            self.assertEqual(app.bridge.reply_file_request.call_args.args[0]["status"], "unsafe_file")

    def test_ui_revokes_read_and_discards_text_when_selected_folder_closes(self):
        import runpy
        import tempfile
        from src.file_workspace import WorkspaceDenied

        root_path = Path(__file__).resolve().parents[1]
        AstraDesktop = runpy.run_path(str(root_path / "astra_desktop.pyw"))["AstraDesktop"]

        class Panel:
            def winfo_exists(self):
                return True

        with tempfile.TemporaryDirectory(prefix="astra-voice-read-revoke-", dir=root_path) as temp:
            root = Path(temp)
            (root / "memo.txt").write_text("contents", encoding="utf-8")
            panel = Panel()
            app = AstraDesktop.__new__(AstraDesktop)
            app.active_file_workspace = FileWorkspace(root)
            app.active_file_panel = panel
            app._file_search_lock = threading.RLock()
            app._file_search_generation = 1
            app._file_search_jobs = {}
            app.bridge = Mock()
            started = threading.Event()
            release = threading.Event()
            replied = threading.Event()
            app.bridge.reply_file_request.side_effect = lambda _result, **_kwargs: replied.set() or True

            def delayed_read(_relative, *, is_cancelled=None, **_kwargs):
                started.set()
                release.wait(3)
                if is_cancelled and is_cancelled():
                    raise WorkspaceDenied("cancelled")
                return "private contents"

            with patch.object(FileWorkspace, "read_text", side_effect=delayed_read):
                app._handle_file_read_request(json.dumps(make_file_read_request("7" * 32, "memo.txt")))
                self.assertTrue(started.wait(2))
                app._revoke_file_workspace(panel)
                release.set()
                self.assertTrue(replied.wait(3))
            result = app.bridge.reply_file_request.call_args.args[0]
            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(result["text"], "")

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
            app.bridge.reply_file_request.side_effect = lambda _result, **_kwargs: replied.set() or True

            request = make_search_request("b" * 32, "contract")
            app._handle_file_search_request(json.dumps(request))
            self.assertTrue(replied.wait(3))
            result = app.bridge.reply_file_request.call_args.args[0]
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
            self.assertEqual(app.bridge.reply_file_request.call_args.args[0]["status"], "no_workspace")

    def test_ui_voice_open_requires_one_exact_safe_match_in_live_workspace(self):
        import runpy
        import tempfile
        root_path = Path(__file__).resolve().parents[1]
        AstraDesktop = runpy.run_path(str(root_path / "astra_desktop.pyw"))["AstraDesktop"]

        class Panel:
            def winfo_exists(self):
                return True

        with tempfile.TemporaryDirectory(prefix="astra-voice-open-", dir=root_path) as temp:
            root = Path(temp)
            (root / "report.pdf").write_bytes(b"pdf placeholder")
            (root / "script.ps1").write_text("not executable here", encoding="utf-8")
            panel = Panel()
            app = AstraDesktop.__new__(AstraDesktop)
            app.active_file_workspace = FileWorkspace(root)
            app.active_file_panel = panel
            app._file_search_lock = threading.RLock()
            app._file_search_generation = 1
            app._file_search_jobs = {}
            app.bridge = Mock()
            replied = threading.Event()
            app.bridge.reply_file_request.side_effect = lambda _result, **_kwargs: replied.set() or True

            with patch("os.startfile", create=True) as start_file:
                app._handle_file_open_request(json.dumps(make_file_open_request("f" * 32, "report.pdf")))
                self.assertTrue(replied.wait(3))
                result = app.bridge.reply_file_request.call_args.args[0]
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["files"], ["report.pdf"])
                start_file.assert_called_once_with(str((root / "report.pdf").resolve()))

                replied.clear()
                app._handle_file_open_request(json.dumps(make_file_open_request("1" * 32, "script.ps1")))
                self.assertTrue(replied.wait(3))
                self.assertEqual(app.bridge.reply_file_request.call_args.args[0]["status"], "unsafe_file")
                start_file.assert_called_once()

                duplicate = root / "archive"
                duplicate.mkdir()
                (duplicate / "report.pdf").write_bytes(b"another placeholder")
                replied.clear()
                app._handle_file_open_request(json.dumps(make_file_open_request("2" * 32, "report.pdf")))
                self.assertTrue(replied.wait(3))
                self.assertEqual(app.bridge.reply_file_request.call_args.args[0]["status"], "ambiguous")
                start_file.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
