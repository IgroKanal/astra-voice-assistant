from pathlib import Path
from dataclasses import replace
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.audio_io import VoiceIO
from src.config_loader import Settings
from src.runtime_events import PREFIX, emit_activity, emit_assistant_profile, emit_event, parse_event_record
from src.ai_client import LLMResult
from main import handle_action
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class RuntimeActivityTests(unittest.TestCase):
    def test_active_character_profile_is_typed_and_opt_in(self):
        settings = Settings(
            assistant_name="Кайто",
            assistant_gender="male",
            assistant_avatar_id="male_kai",
        )
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "0"}), patch("builtins.print") as output:
            self.assertFalse(emit_assistant_profile(settings))
            output.assert_not_called()
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "1"}), patch("builtins.print") as output:
            self.assertTrue(emit_assistant_profile(settings))
            event = parse_event_record(output.call_args.args[0])
        self.assertEqual((event.kind, event.text), ("profile", ""))
        self.assertEqual(event.data, {
            "kind": "assistant_profile",
            "avatar_id": "male_kai",
            "name": "Кайто",
            "gender": "male",
        })

    def test_profile_event_rejects_unsafe_or_unknown_values(self):
        from src.runtime_events import emit_event

        invalid = (
            {"kind": "assistant_profile", "avatar_id": "../avatar", "name": "Кай", "gender": "male"},
            {"kind": "assistant_profile", "avatar_id": "male_kai", "name": "Кай\nто", "gender": "male"},
            {"kind": "assistant_profile", "avatar_id": "male_kai", "name": "Кай", "gender": "unknown"},
            {"kind": "assistant_profile", "avatar_id": "male_kai", "name": "Кай", "gender": "male", "voice_id": "private-id"},
        )
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                emit_event("profile", "", data=data)

    def test_activity_is_opt_in_and_has_bounded_payload(self):
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "1", "ASTRA_ACTIVITY_EVENTS": "0"}), patch("builtins.print") as output:
            self.assertFalse(emit_activity("thinking", True))
            output.assert_not_called()
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "1", "ASTRA_ACTIVITY_EVENTS": "1"}), patch("builtins.print") as output:
            self.assertTrue(emit_activity("thinking", True))
            event = parse_event_record(output.call_args.args[0])
            self.assertEqual((event.kind, event.text), ("activity", "thinking:start"))
        self.assertIsNone(parse_event_record(PREFIX + json.dumps({"version": 1, "type": "activity", "text": "delete:all"})))
        with self.assertRaises(ValueError):
            emit_activity("delete", True)

    def test_control_event_is_typed_and_rejects_unknown_values(self):
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "1"}), patch("builtins.print") as output:
            self.assertTrue(emit_event("control", "cancel_ready"))
            event = parse_event_record(output.call_args.args[0])
        self.assertEqual((event.kind, event.text), ("control", "cancel_ready"))
        invalid = PREFIX + json.dumps({"version": 1, "type": "control", "text": "run:command"})
        self.assertIsNone(parse_event_record(invalid))
        with self.assertRaises(ValueError):
            emit_event("control", "run:command")

    def test_runtime_passes_cancel_signal_to_ai_and_resets_it_afterward(self):
        class Signal:
            def __init__(self):
                self.active = True
                self.reset_count = 0

            def is_set(self):
                return self.active

            def reset(self):
                self.reset_count += 1
                self.active = False

        class CancellableAI:
            def __init__(self):
                self.cancelled_at_call = None

            def ask(self, _question, *, cancelled=None):
                self.cancelled_at_call = cancelled()
                return LLMResult(False, "Запрос отменён.")

        ctx, responses, *_ = make_context()
        signal = Signal()
        ai = CancellableAI()
        ctx = replace(ctx, ai_client=ai, cancellation_signal=signal)
        action = AssistantAction(ActionType.ASK_LLM, query="тест", source="local_parser")
        with patch("main.emit_activity"), patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "0"}):
            self.assertTrue(handle_action(action, ctx))

        self.assertTrue(ai.cancelled_at_call)
        self.assertEqual(signal.reset_count, 1)
        self.assertFalse(signal.is_set())
        self.assertEqual(responses, ["Запрос отменён."])

    def test_tts_signals_stop_even_if_playback_fails(self):
        voice = object.__new__(VoiceIO)
        voice.settings = Settings(tts_enabled=True, tts_engine="edge")
        voice._speak_edge = Mock(side_effect=RuntimeError("playback failure"))
        with patch("src.audio_io.emit_activity") as activity:
            with self.assertRaises(RuntimeError):
                voice.speak_audio_only("Привет", manage_state=False)
        self.assertEqual(activity.call_args_list, [call("speaking", True), call("speaking", False)])

    def test_thinking_activity_closes_even_if_model_fails(self):
        ctx, responses, *_ = make_context()
        with patch("main.emit_activity") as activity:
            handle_action(AssistantAction(ActionType.ASK_LLM, query="тест", source="local_parser"), ctx)
        self.assertEqual(activity.call_args_list, [call("thinking", True), call("thinking", False)])
        self.assertTrue(responses)

    def test_listening_and_recognition_are_separate_activities(self):
        voice = object.__new__(VoiceIO)
        voice.settings = Settings()
        voice.microphone = MagicMock()
        voice.recognizer = Mock()
        voice.logger = Mock()
        voice._recognize_google_alternatives = Mock(return_value=["привет"])
        voice._select_best_stt_alternative = Mock(return_value="привет")
        voice._log_stt_timing = Mock()
        with patch("src.audio_io.emit_activity") as activity, patch("src.audio_io.emit_event"):
            result = voice.listen_once(prompt="")
        self.assertTrue(result.ok)
        self.assertEqual(activity.call_args_list, [call("listening", True), call("listening", False), call("recognizing", True), call("recognizing", False)])

    def test_failed_microphone_open_does_not_emit_unmatched_stop(self):
        voice = object.__new__(VoiceIO)
        voice.settings = Settings()
        voice.microphone = MagicMock()
        voice.microphone.__enter__.side_effect = OSError("microphone unavailable")
        voice.logger = Mock()
        voice._log_stt_timing = Mock()
        with patch("src.audio_io.emit_activity") as activity:
            result = voice.listen_once(prompt="")
        self.assertFalse(result.ok)
        activity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
