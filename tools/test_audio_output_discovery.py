import unittest

from src.audio_device_discovery import (
    audio_input_identity,
    audio_output_identity,
    discover_audio_outputs,
)


class FakeAudio:
    def __init__(self):
        self.terminated = False
        self.devices = (
            {"index": 0, "name": "USB Headset", "hostApi": 0, "maxInputChannels": 1},
            {"index": 1, "name": "Speakers", "hostApi": 0, "maxOutputChannels": 2},
            {"index": 2, "name": "HDMI", "hostApi": 0, "maxOutputChannels": 8},
            {"index": 3, "name": "Broken", "hostApi": 0, "maxOutputChannels": "bad"},
        )

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def get_host_api_info_by_index(self, index):
        return {"name": "Windows WASAPI"}

    def terminate(self):
        self.terminated = True


class FakePyAudio:
    def __init__(self):
        self.audio = FakeAudio()

    def PyAudio(self):
        return self.audio


class BrokenPyAudio:
    def PyAudio(self):
        raise OSError("audio backend unavailable")


class AudioOutputDiscoveryTests(unittest.TestCase):
    def test_only_output_capable_endpoints_are_returned_and_metadata_is_closed(self):
        provider = FakePyAudio()

        devices = discover_audio_outputs(provider)

        self.assertEqual([device.index for device in devices], [1, 2])
        self.assertTrue(all(len(device.identity) == 64 for device in devices))
        self.assertNotIn("Speakers", repr(devices))
        self.assertTrue(provider.audio.terminated)

    def test_input_and_output_identity_domains_are_separate(self):
        self.assertNotEqual(
            audio_input_identity("Speakers", "WASAPI"),
            audio_output_identity("Speakers", "WASAPI"),
        )
        self.assertEqual(
            audio_output_identity("  SPEAKERS  ", "WASAPI"),
            audio_output_identity("speakers", "wasapi"),
        )

    def test_provider_failure_can_be_reported_separately_from_no_devices(self):
        self.assertEqual(discover_audio_outputs(BrokenPyAudio()), ())
        with self.assertRaisesRegex(OSError, "audio backend unavailable"):
            discover_audio_outputs(BrokenPyAudio(), strict=True)


if __name__ == "__main__":
    unittest.main()
