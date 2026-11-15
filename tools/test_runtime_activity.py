from pathlib import Path
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.audio_io import VoiceIO
from src.config_loader import Settings
from src.runtime_events import PREFIX, emit_activity, parse_event_record
from main import handle_action
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class RuntimeActivityTests(unittest.TestCase):
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
