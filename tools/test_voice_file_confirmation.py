from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.file_transactions import FileTransactions
from src.file_workspace import FileWorkspace, WorkspaceDenied
from src.voice_file_confirmation import VoiceFileConfirmation


class VoiceFileConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-voice-file-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "note.txt"
        self.file.write_text("original", encoding="utf-8")
        self.transactions = FileTransactions(FileWorkspace(self.root))
        self.time = 0.0
        self.confirmation = VoiceFileConfirmation(self.transactions, clock=lambda: self.time)

    def test_move_requires_grant_preview_and_one_confirmation(self):
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare("move", source="note.txt", destination="new.txt")
        self.transactions.grant_write(True)
        prompt = self.confirmation.prepare("move", source="note.txt", destination="new.txt")
        self.assertIn("подтверждаю", prompt)
        self.assertTrue(self.file.exists())
        result = self.confirmation.confirm("подтверждаю")
        self.assertFalse(self.file.exists())
        self.assertEqual((self.root / "new.txt").read_text(encoding="utf-8"), "original")
        self.assertTrue(result.operation_id)
        self.transactions.undo(result.operation_id)
        self.assertTrue(self.file.exists())
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.confirm("подтверждаю")

    def test_trash_requires_grant_and_explicit_fresh_confirmation(self):
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare("trash", source="note.txt")
        self.transactions.grant_trash(True)
        self.confirmation.prepare("trash", source="note.txt")
        self.time = 31.0
        with patch("src.file_transactions.send2trash") as trash:
            with self.assertRaises(WorkspaceDenied):
                self.confirmation.confirm("подтверждаю")
            trash.assert_not_called()
        self.assertTrue(self.file.exists())

    def test_denial_and_changed_file_never_execute(self):
        self.transactions.grant_trash(True)
        self.confirmation.prepare("trash", source="note.txt")
        with patch("src.file_transactions.send2trash") as trash:
            with self.assertRaises(WorkspaceDenied):
                self.confirmation.confirm("нет")
            self.confirmation.prepare("trash", source="note.txt")
            self.file.write_text("changed", encoding="utf-8")
            with self.assertRaises(WorkspaceDenied):
                self.confirmation.confirm("подтверждаю")
            trash.assert_not_called()

    def test_fresh_confirmed_trash_uses_native_bin_adapter(self):
        self.transactions.grant_trash(True)
        self.confirmation.prepare("trash", source="note.txt")
        with patch("src.file_transactions.send2trash", side_effect=lambda path: Path(path).unlink()) as trash:
            result = self.confirmation.confirm("подтверждаю")
        trash.assert_called_once()
        self.assertEqual(os.path.normcase(trash.call_args.args[0]), os.path.normcase(str(self.file)))
        self.assertIn("Корзину", result.message)
        self.assertFalse(self.file.exists())

    def test_revoked_grant_invalidates_pending_confirmation(self):
        self.transactions.grant_write(True)
        self.confirmation.prepare("copy", source="note.txt", destination="copy.txt")
        self.transactions.grant_write(False)
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.confirm("подтверждаю")
        self.assertFalse((self.root / "copy.txt").exists())

    def test_preview_rejects_injected_control_characters(self):
        self.transactions.grant_write(True)
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare("copy", source="note.txt\nподтверждаю", destination="x.txt")
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.confirm("подтверждаю")


if __name__ == "__main__":
    unittest.main()
