from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.file_workspace import FileWorkspace, WorkspaceDenied
from src.file_transactions import FileTransactions


class FileTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-transactions-", dir=ROOT)
        self.root = Path(self.temp.name)
        self.files = FileTransactions(FileWorkspace(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def test_write_requires_grant_preview_and_fresh_token(self):
        self.assertEqual(self.files.history(), [])
        self.assertFalse((self.root / ".astra-history").exists())
        with self.assertRaises(WorkspaceDenied):
            self.files.preview("create", destination="note.txt", text="hi")
        self.files.grant_write(True)
        preview = self.files.preview("create", destination="note.txt", text="hi")
        self.assertFalse((self.root / "note.txt").exists())
        self.files.execute(preview.token)
        self.assertEqual((self.root / "note.txt").read_text(), "hi")
        with self.assertRaises(WorkspaceDenied):
            self.files.execute(preview.token)

    def test_trash_requires_separate_grant_review_and_uses_native_bin(self):
        target = self.root / "large-user-file.bin"
        with target.open("wb") as stream:
            stream.truncate(20_000_000)
        with self.assertRaises(WorkspaceDenied):
            self.files.preview("trash", source=target.name)
        self.files.grant_trash(True)
        preview = self.files.preview("trash", source=target.name)
        self.assertEqual(preview.size, 20_000_000)
        self.assertTrue(target.exists(), "Preview must not move the file")
        self.files.grant_trash(False)
        with patch("src.file_transactions.send2trash") as send:
            with self.assertRaises(WorkspaceDenied):
                self.files.execute_trash(preview.token)
            send.assert_not_called()

        self.files.grant_trash(True)
        preview = self.files.preview("trash", source=target.name)
        with patch("src.file_transactions.send2trash", side_effect=lambda path: Path(path).unlink()) as send:
            result = self.files.execute_trash(preview.token)
            send.assert_called_once_with(str(target))
        self.assertFalse(target.exists())
        self.assertIn("Корзину Windows", result)

    def test_trash_stops_if_file_changes_after_preview(self):
        self.files.grant_trash(True)
        target = self.root / "note.txt"
        target.write_text("before", encoding="utf-8")
        preview = self.files.preview("trash", source=target.name)
        target.write_text("changed while waiting", encoding="utf-8")
        with patch("src.file_transactions.send2trash") as send:
            with self.assertRaises(WorkspaceDenied):
                self.files.execute_trash(preview.token)
            send.assert_not_called()

    def test_all_operations_and_undo(self):
        self.files.grant_write(True)
        (self.root / "source.txt").write_text("original")
        copied = self.files.execute(self.files.preview("copy", source="source.txt", destination="copy.txt").token)
        moved = self.files.execute(self.files.preview("move", source="copy.txt", destination="moved.txt").token)
        self.assertFalse((self.root / "copy.txt").exists())
        self.files.undo(moved)
        replaced = self.files.execute(self.files.preview("replace", destination="copy.txt", text="new").token)
        self.files.undo(replaced)
        self.assertEqual((self.root / "copy.txt").read_text(), "original")
        self.files.undo(copied)
        self.assertFalse((self.root / "copy.txt").exists())
        self.assertEqual((self.root / "source.txt").read_text(), "original")

    def test_create_folder_preview_execute_and_recoverable_undo(self):
        self.files.grant_write(True)
        preview = self.files.preview("mkdir", destination="notes")
        self.assertFalse((self.root / "notes").exists(), "Preview must not create a folder")
        identity = self.files.execute(preview.token)
        created = self.root / "notes"
        self.assertTrue(created.is_dir())
        self.files.undo(identity)
        self.assertFalse(created.exists())
        preserved = self.root / ".astra-history" / (identity + ".undone-dir")
        self.assertTrue(preserved.is_dir(), "Undo preserves the empty folder in recovery history")
        self.assertEqual(self.files.history()[0]["status"], "undone")

    def test_copy_and_move_keep_arbitrary_binary_bytes(self):
        import hashlib
        self.files.grant_write(True)
        payload = bytes(range(256)) * 4096
        (self.root / "sample.bin").write_bytes(payload)
        copied = self.files.execute(self.files.preview("copy", source="sample.bin", destination="copy.bin").token)
        moved = self.files.execute(self.files.preview("move", source="copy.bin", destination="moved.bin").token)
        self.assertEqual(hashlib.sha256((self.root / "moved.bin").read_bytes()).digest(), hashlib.sha256(payload).digest())
        self.files.undo(moved)
        self.assertFalse((self.root / "moved.bin").exists())
        self.files.undo(copied)
        self.assertFalse((self.root / "copy.bin").exists())
        self.assertEqual((self.root / "sample.bin").read_bytes(), payload)

    def test_folder_undo_stops_if_user_added_content(self):
        self.files.grant_write(True)
        identity = self.files.execute(self.files.preview("mkdir", destination="notes").token)
        content = self.root / "notes" / "keep.txt"
        content.write_text("user data", encoding="utf-8")
        with self.assertRaises(WorkspaceDenied):
            self.files.undo(identity)
        self.assertEqual(content.read_text(encoding="utf-8"), "user data")

    def test_preview_detects_changed_files_and_revocation(self):
        self.files.grant_write(True)
        source = self.root / "a.txt"
        source.write_text("one")
        preview = self.files.preview("copy", source="a.txt", destination="b.txt")
        source.write_text("two")
        with self.assertRaises(WorkspaceDenied):
            self.files.execute(preview.token)
        preview = self.files.preview("create", destination="b.txt", text="x")
        self.files.grant_write(False)
        with self.assertRaises(WorkspaceDenied):
            self.files.execute(preview.token)

    def test_another_process_cannot_overwrite_a_concurrently_created_destination(self):
        import os
        import subprocess

        self.files.grant_write(True)
        target = self.root / "contended.txt"
        preview = self.files.preview("create", destination=target.name, text="Astra must not replace this")
        native_link = os.link
        peer_program = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('created by another process', encoding='utf-8')"

        def create_target_before_atomic_link(_temporary, destination):
            peer = subprocess.run(
                [sys.executable, "-c", peer_program, str(destination)],
                check=False, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(peer.returncode, 0, peer.stderr)
            return native_link(_temporary, destination)

        with patch("src.file_transactions.os.link", side_effect=create_target_before_atomic_link):
            with self.assertRaisesRegex(WorkspaceDenied, "появился во время операции"):
                self.files.execute(preview.token)

        self.assertEqual(target.read_text(encoding="utf-8"), "created by another process")
        self.assertEqual(self.files.history()[0]["status"], "cancelled")
        self.assertEqual(list(self.root.glob(".astra-*.tmp")), [])

    def test_undo_never_overwrites_user_edits(self):
        self.files.grant_write(True)
        identity = self.files.execute(self.files.preview("create", destination="x.txt", text="initial").token)
        (self.root / "x.txt").write_text("edited by user")
        with self.assertRaises(WorkspaceDenied):
            self.files.undo(identity)
        self.assertEqual((self.root / "x.txt").read_text(), "edited by user")

    def test_unsafe_targets_and_existing_destination(self):
        self.files.grant_write(True)
        for name in ("../escape.txt", ".env", "CON.txt", "trailing. ", "x:ads", ".astra-history/x.txt"):
            with self.subTest(name=name), self.assertRaises((WorkspaceDenied, FileNotFoundError)):
                self.files.preview("create", destination=name, text="x")
        (self.root / "exists.txt").write_text("preserve")
        with self.assertRaises(WorkspaceDenied):
            self.files.preview("create", destination="exists.txt", text="x")

    def test_backup_corruption_stops_restore(self):
        self.files.grant_write(True)
        (self.root / "note.txt").write_text("before")
        identity = self.files.execute(self.files.preview("replace", destination="note.txt", text="after").token)
        (self.root / ".astra-history" / (identity + ".backup")).write_text("corrupt")
        with self.assertRaises(WorkspaceDenied):
            self.files.undo(identity)
        self.assertEqual((self.root / "note.txt").read_text(), "after")

    def test_history_refuses_linked_records(self):
        history = self.root / ".astra-history"
        history.mkdir()
        target = self.root / "untrusted.json"
        target.write_text('{}', encoding="utf-8")
        try:
            (history / ("a" * 32 + ".json")).symlink_to(target)
        except OSError:
            self.skipTest("Symlink privilege unavailable")
        with self.assertRaises(WorkspaceDenied):
            self.files.history()


if __name__ == "__main__":
    unittest.main(verbosity=2)
