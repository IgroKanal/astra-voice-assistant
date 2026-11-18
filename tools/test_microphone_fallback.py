import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.audio_io import VoiceIO
from src.audio_device_discovery import AudioInputDevice


class MicrophoneFallbackTests(unittest.TestCase):
    def make_voice(self, index, identity=""):
        voice = VoiceIO.__new__(VoiceIO)
        voice.settings = SimpleNamespace(stt_device_index=index, stt_device_identity=identity, ambient_noise_duration_seconds=0.1)
        voice.logger = logging.getLogger('test.microphone')
        voice.recognizer = Mock()
        return voice

    @patch('src.audio_io.emit_event')
    @patch('src.audio_io.sr.Microphone')
    def test_missing_selected_device_uses_and_reports_default(self, microphone, emit):
        device = MagicMock()
        microphone.side_effect = [OSError('device gone'), device]
        voice = self.make_voice(8)
        voice._init_microphone()
        self.assertIs(voice.microphone, device)
        self.assertEqual([call.kwargs['device_index'] for call in microphone.call_args_list], [8, None])
        emit.assert_called_once()

    @patch('src.audio_io.sr.Microphone', side_effect=OSError('unavailable'))
    def test_default_unavailable_is_not_retried(self, microphone):
        voice = self.make_voice(None)
        voice._init_microphone()
        self.assertIsNone(voice.microphone)
        self.assertEqual(microphone.call_count, 1)

    @patch('src.audio_io.emit_event')
    @patch('src.audio_io.discover_audio_inputs')
    @patch('src.audio_io.sr.Microphone')
    def test_stable_identity_finds_selected_device_after_index_reordering(self, microphone, discover, emit):
        identity = 'a' * 64
        device = MagicMock()
        microphone.return_value = device
        discover.return_value = (AudioInputDevice(3, identity),)
        voice = self.make_voice(8, identity)
        voice._init_microphone()
        self.assertIs(voice.microphone, device)
        self.assertEqual([call.kwargs['device_index'] for call in microphone.call_args_list], [3])
        emit.assert_not_called()

    @patch('src.audio_io.emit_event')
    @patch('src.audio_io.discover_audio_inputs', return_value=())
    @patch('src.audio_io.sr.Microphone')
    def test_unmatched_identity_uses_default_without_trying_stale_index(self, microphone, discover, emit):
        identity = 'b' * 64
        device = MagicMock()
        microphone.return_value = device
        voice = self.make_voice(8, identity)
        voice._init_microphone()
        self.assertIs(voice.microphone, device)
        self.assertEqual([call.kwargs['device_index'] for call in microphone.call_args_list], [None])
        emit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
