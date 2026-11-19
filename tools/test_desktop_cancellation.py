from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.desktop_cancellation import DesktopCancellationEvent, ENVIRONMENT_VARIABLE
from src.desktop_bridge import DesktopBridge


class DesktopCancellationTests(unittest.TestCase):
    def test_named_event_shares_and_resets_only_the_cancel_state(self):
        if os.name != "nt":
            self.skipTest("Windows named events are required")
        owner = DesktopCancellationEvent.create()
        runtime = None
        try:
            runtime = DesktopCancellationEvent.open(owner.name)
            self.assertFalse(runtime.is_set())
            owner.set()
            self.assertTrue(runtime.is_set())
            runtime.reset()
            self.assertFalse(owner.is_set())
        finally:
            if runtime is not None:
                runtime.close()
            owner.close()

    def test_bridge_launches_runtime_with_typed_activity_and_cancel_channel(self):
        if os.name != "nt":
            self.skipTest("The desktop runtime launcher is Windows-only")
        with tempfile.TemporaryDirectory() as root, \
                patch("src.desktop_bridge.subprocess.Popen") as popen, \
                patch("src.desktop_bridge.threading.Thread"):
            process = Mock()
            process.poll.return_value = None
            popen.return_value = process
            bridge = DesktopBridge(Path(root))
            bridge.start("text")
            try:
                env = popen.call_args.kwargs["env"]
                self.assertEqual(env["ASTRA_DESKTOP_EVENTS"], "1")
                self.assertEqual(env["ASTRA_ACTIVITY_EVENTS"], "1")
                self.assertRegex(env[ENVIRONMENT_VARIABLE], r"Local\\AstraCancel-[0-9a-f]{32}")
            finally:
                bridge.prevent_restart()
                bridge.stop()

    def test_event_name_validation_rejects_arbitrary_windows_objects(self):
        for name in ("Global\\Other", "Local\\AstraCancel-abc", "Local\\AstraCancel-" + "A" * 32):
            with self.subTest(name=name), self.assertRaises(ValueError):
                DesktopCancellationEvent.open(name)

    def test_bridge_only_signals_a_ready_live_runtime(self):
        bridge = DesktopBridge(Path.cwd())
        signal = Mock()
        bridge._cancel_signal = signal
        process = Mock()
        process.poll.return_value = None
        bridge.process = process
        bridge.mode = "text"

        self.assertFalse(bridge.cancel_response())
        bridge._cancel_ready.set()
        self.assertTrue(bridge.cancel_response())
        signal.set.assert_called_once_with()

    def test_missing_event_environment_does_not_create_runtime_signal(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {ENVIRONMENT_VARIABLE: ""}):
            self.assertIsNone(DesktopCancellationEvent.open_from_environment())


if __name__ == "__main__":
    unittest.main()
