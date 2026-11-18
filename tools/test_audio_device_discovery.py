import ctypes
import unittest
from types import SimpleNamespace

from src.audio_device_discovery import (
    AudioInputDevice,
    audio_input_identity,
    audio_input_endpoint_identity,
    audio_input_identity_for_index,
    audio_input_endpoint_identity_for_index,
    audio_input_identities_for_index,
    discover_audio_inputs,
    resolve_audio_input_index,
)
from src.windows_audio_endpoint import (
    WindowsAudioEndpoint,
    _PropVariant,
    discover_windows_capture_endpoints,
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

    def test_endpoint_identity_survives_index_reordering_and_keeps_legacy_fallback(self):
        endpoint = WindowsAudioEndpoint("opaque-endpoint-id", "USB Microphone")
        audio = FakeAudio(
            [{"index": 7, "name": "USB Microphone", "maxInputChannels": 1, "hostApi": 0}],
            {0: {"name": "Windows WASAPI"}},
        )
        devices = discover_audio_inputs(
            self.module_for(audio), endpoint_discovery=lambda: (endpoint,)
        )

        stable = audio_input_endpoint_identity(endpoint.endpoint_id, "Windows WASAPI")
        legacy = audio_input_identity("USB Microphone", "Windows WASAPI")
        self.assertEqual(devices, (AudioInputDevice(7, legacy, stable),))
        self.assertEqual(resolve_audio_input_index(legacy, devices, endpoint_identity=stable), 7)
        self.assertEqual(resolve_audio_input_index(legacy, devices), 7)
        self.assertNotIn(endpoint.endpoint_id, stable)

    def test_endpoint_change_can_fall_back_to_unique_legacy_identity(self):
        legacy = audio_input_identity("USB Microphone", "Windows WASAPI")
        saved_endpoint = audio_input_endpoint_identity("old-device-instance")
        current = AudioInputDevice(
            11,
            legacy,
            audio_input_endpoint_identity("new-device-instance", "Windows WASAPI"),
        )
        self.assertEqual(
            resolve_audio_input_index(
                legacy, (current,), endpoint_identity=saved_endpoint
            ),
            11,
        )

    def test_identical_endpoint_names_remain_ambiguous(self):
        audio = FakeAudio(
            [
                {"index": 2, "name": "USB Microphone", "maxInputChannels": 1, "hostApi": 0},
                {"index": 5, "name": "USB Microphone", "maxInputChannels": 1, "hostApi": 0},
            ],
            {0: {"name": "Windows WASAPI"}},
        )
        endpoints = (
            WindowsAudioEndpoint("endpoint-one", "USB Microphone"),
            WindowsAudioEndpoint("endpoint-two", "USB Microphone"),
        )
        devices = discover_audio_inputs(
            self.module_for(audio), endpoint_discovery=lambda: endpoints
        )
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(device.endpoint_identity == "" for device in devices))
        self.assertIsNone(resolve_audio_input_index(devices[0].identity, devices))

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
        self.assertEqual(audio_input_endpoint_identity_for_index(4, module), "")
        self.assertEqual(audio_input_identities_for_index(4, module), (identity, ""))
        self.assertEqual(audio_input_identity_for_index(3, module), "")

    def test_unavailable_audio_backend_returns_empty_inventory(self):
        def fail_to_initialize():
            raise OSError("no audio backend")

        self.assertEqual(discover_audio_inputs(SimpleNamespace(PyAudio=fail_to_initialize)), ())

    def test_core_audio_endpoint_source_is_bounded_and_failures_are_unknown(self):
        endpoint = WindowsAudioEndpoint("id", "Microphone")
        self.assertEqual(
            discover_windows_capture_endpoints(native_reader=lambda: (endpoint,)),
            (endpoint,),
        )
        self.assertIsNone(
            discover_windows_capture_endpoints(native_reader=lambda: (object(),))
        )
        self.assertIsNone(
            discover_windows_capture_endpoints(
                native_reader=lambda: tuple(endpoint for _ in range(513))
            )
        )
        self.assertIsNone(
            discover_windows_capture_endpoints(
                native_reader=lambda: (_ for _ in ()).throw(OSError("unavailable"))
            )
        )

    def test_core_audio_metadata_does_not_expose_raw_ids_in_repr_and_uses_native_variant_size(self):
        endpoint = WindowsAudioEndpoint("private-device-id", "Private microphone name")
        self.assertNotIn("private-device-id", repr(endpoint))
        self.assertNotIn("Private microphone name", repr(endpoint))
        self.assertEqual(audio_input_endpoint_identity("device" + chr(0xD800)), "")
        expected_size = 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16
        self.assertEqual(ctypes.sizeof(_PropVariant), expected_size)


if __name__ == "__main__":
    unittest.main()
