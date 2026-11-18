import logging
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.audio_io import VoiceIO


class MicrophoneFallbackTests(unittest.TestCase):
    def make_voice(self, index):
        voice = VoiceIO.__new__(VoiceIO)
        voice.settings = SimpleNamespace(stt_device_index=index, ambient_noise_duration_seconds=0.1)
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


if __name__ == '__main__':
    unittest.main()
