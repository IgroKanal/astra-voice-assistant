import unittest
from types import SimpleNamespace

from src.audio_device_discovery import (
    AudioInputDevice,
    audio_input_identity,
    audio_input_identity_for_index,
    discover_audio_inputs,
    resolve_audio_input_index,
)


class FakeAudio:
    def __init__(self, devices, host_apis=None):
        self.devices = devices
        self.host_apis = host_apis or {}
        self.terminated = False

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def get_host_api_info_by_index(self, index):
        return self.host_apis[index]

    def terminate(self):
        self.terminated = True


class AudioDeviceDiscoveryTests(unittest.TestCase):
    def module_for(self, audio):
        return SimpleNamespace(PyAudio=lambda: audio)

    def test_discovery_keeps_only_input_devices_and_closes_enumerator(self):
        audio = FakeAudio(
            [
                {"index": 0, "name": "USB Microphone", "maxInputChannels": 1, "hostApi": 0},
                {"index": 1, "name": "HDMI Output", "maxInputChannels": 0, "hostApi": 0},
            ],
            {0: {"name": "Windows WASAPI"}},
        )
        devices = discover_audio_inputs(self.module_for(audio))
        self.assertEqual(devices, (AudioInputDevice(0, audio_input_identity("usb microphone", "windows wasapi")),))
        self.assertTrue(audio.terminated)

    def test_identity_survives_portaudio_index_reordering(self):
        identity_before = audio_input_identity("USB Microphone", "Windows WASAPI")
        identity_after = audio_input_identity("  usb   microphone ", "windows wasapi")
        self.assertEqual(identity_before, identity_after)
        self.assertEqual(resolve_audio_input_index(identity_before, (AudioInputDevice(7, identity_after),)), 7)

    def test_duplicate_devices_are_not_guessed(self):
        identity = audio_input_identity("USB Microphone", "Windows WASAPI")
        devices = (AudioInputDevice(2, identity), AudioInputDevice(5, identity))
        self.assertIsNone(resolve_audio_input_index(identity, devices))

    def test_selected_index_identity_is_captured_only_for_a_current_input(self):
        identity = audio_input_identity("USB Microphone", "Windows WASAPI")
        audio = FakeAudio(
            [{"index": 4, "name": "USB Microphone", "maxInputChannels": 1, "hostApi": 0}],
            {0: {"name": "Windows WASAPI"}},
        )
        module = self.module_for(audio)
        self.assertEqual(audio_input_identity_for_index(4, module), identity)
        self.assertEqual(audio_input_identity_for_index(3, module), "")

    def test_unavailable_audio_backend_returns_empty_inventory(self):
        def fail_to_initialize():
            raise OSError("no audio backend")

        self.assertEqual(discover_audio_inputs(SimpleNamespace(PyAudio=fail_to_initialize)), ())


if __name__ == "__main__":
    unittest.main()
