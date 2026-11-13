import tempfile
from pathlib import Path
import socket
import unittest
import time
from unittest.mock import Mock

from src.avatar_preview import AvatarPreviewUnavailable, launch_avatar_preview, resolve_preview_files


class FakeProcess:
    def poll(self):
        return None


class AvatarPreviewTests(unittest.TestCase):
    def _package_root(self, root: Path):
        godot = root / "third_party" / "godot" / "Godot_v4.7.2-stable_win64.exe"
        project = root / "assets" / "3d_avatar"
        godot.parent.mkdir(parents=True)
        project.mkdir(parents=True)
        godot.write_bytes(b"test stub; never executed")
        (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        return godot, project

    def test_launch_uses_packaged_runtime_and_fixed_argument_list_without_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            godot, project = self._package_root(root)
            popen = Mock(return_value=FakeProcess())
            session = launch_avatar_preview("male_ren", "Рэн-2", initial_state="listening", resource_root=root, popen=popen)
            try:
                args, kwargs = popen.call_args
                self.assertEqual(args[0][:6], [str(godot), "--path", str(project), "--", "--avatar=male_ren", "--name=Рэн-2"])
                self.assertTrue(args[0][6].startswith("--port="))
                self.assertRegex(args[0][7], r"^--token=[0-9a-f]{64}$")
                self.assertEqual(kwargs["cwd"], str(project))
                self.assertFalse(kwargs["shell"])
            finally:
                session.close()

    def test_authenticated_loopback_stream_updates_only_bounded_avatar_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._package_root(root)
            popen = Mock(return_value=FakeProcess())
            session = launch_avatar_preview("female_miku", "Мику", resource_root=root, popen=popen)
            client = None
            try:
                command = popen.call_args.args[0]
                port = int(command[6].split("=", 1)[1])
                token = command[7].split("=", 1)[1]
                client = socket.create_connection(("127.0.0.1", port), timeout=2)
                client.settimeout(2)
                client.sendall((token + "\n").encode("ascii"))
                received = client.recv(256).decode("ascii")
                self.assertIn("STATE:idle\n", received)
                session.set_state("speaking")
                deadline = time.monotonic() + 2
                while "STATE:speaking\n" not in received and time.monotonic() < deadline:
                    received += client.recv(256).decode("ascii")
                self.assertIn("STATE:speaking\n", received)
                with self.assertRaises(ValueError):
                    session.set_state("open_file")
                session.close()
                deadline = time.monotonic() + 2
                while "CLOSE\n" not in received and time.monotonic() < deadline:
                    try:
                        received += client.recv(256).decode("ascii")
                    except OSError:
                        break
                self.assertIn("CLOSE\n", received)
            finally:
                session.close()
                if client is not None:
                    client.close()

    def test_missing_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AvatarPreviewUnavailable):
                resolve_preview_files(Path(temp))

    def test_unknown_profile_and_control_characters_are_rejected_before_launch(self):
        popen = Mock()
        with self.assertRaises(ValueError):
            launch_avatar_preview("../../other", "Астра", popen=popen)
        with self.assertRaises(ValueError):
            launch_avatar_preview("female_miku", "Астра\n--state=error", popen=popen)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
