from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.microphone_recovery import recover_microphone
from src.audio_io import ListenResult, VoiceIO


class MicrophoneRecoveryTests(unittest.TestCase):
    def test_transient_failure_recovers_on_second_attempt(self):
        reset = Mock(side_effect=[False, True])
        wait, notify = Mock(), Mock()
        self.assertTrue(recover_microphone(reset, wait, notify))
        self.assertEqual(wait.call_args_list, [call(0.5), call(1.0)])
        self.assertEqual(notify.call_args_list, [call(1), call(2)])

    def test_persistent_exception_stops_after_two_attempts(self):
        reset = Mock(side_effect=OSError("device absent"))
        wait, notify = Mock(), Mock()
        self.assertFalse(recover_microphone(reset, wait, notify))
        self.assertEqual(reset.call_count, 2)

    def test_success_does_not_retry(self):
        reset = Mock(return_value=True)
        wait, notify = Mock(), Mock()
        self.assertTrue(recover_microphone(reset, wait, notify))
        reset.assert_called_once()

    def test_voice_retries_the_same_selected_device_and_returns_real_result(self):
        voice = object.__new__(VoiceIO)
        voice._enable_microphone_recovery = True
        voice.microphone = None
        voice.logger = Mock()
        voice._listen_once = Mock(side_effect=[ListenResult(False, failure_kind="microphone"), ListenResult(True, text="Астра")])
        def initialize():
            voice.microphone = object()
        voice._init_microphone = Mock(side_effect=initialize)
        with patch("src.audio_io.time.sleep"), patch("src.audio_io.emit_event"):
            result = voice.listen_once(timeout_seconds=4, prompt="")
        self.assertEqual(result.text, "Астра")
        self.assertEqual(voice._listen_once.call_count, 2)
        voice._init_microphone.assert_called_once()

    def test_voice_stops_retrying_broken_device(self):
        voice = object.__new__(VoiceIO)
        voice._enable_microphone_recovery = True
        voice.microphone = None
        voice.logger = Mock()
        voice._listen_once = Mock(return_value=ListenResult(False, failure_kind="microphone"))
        voice._init_microphone = Mock()
        with patch("src.audio_io.time.sleep"), patch("src.audio_io.emit_event"):
            result = voice.listen_once(prompt="")
        self.assertEqual(result.failure_kind, "microphone")
        self.assertEqual(voice._init_microphone.call_count, 2)

    def test_normal_timeout_never_reinitializes_device(self):
        voice = object.__new__(VoiceIO)
        voice._enable_microphone_recovery = True
        voice._listen_once = Mock(return_value=ListenResult(False, error="Речь не распознана."))
        voice._init_microphone = Mock()
        with patch("src.audio_io.time.sleep") as sleep:
            result = voice.listen_once(prompt="")
        self.assertFalse(result.ok)
        voice._init_microphone.assert_not_called()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
