from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.file_transactions import FileTransactions
from src.file_group_transactions import FileWorkspaceGroupTransactions
from src.file_workspace import FileWorkspace, FileWorkspaceGrant, FileWorkspaceGroup, WorkspaceDenied
from src.voice_file_confirmation import VoiceFileConfirmation
from tools.test_workspace_temp import workspace_tempdir


class VoiceFileConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = workspace_tempdir("astra-voice-file-", Path(__file__).resolve().parents[1])
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

    def test_create_folder_requires_write_grant_preview_confirmation_and_supports_undo(self):
        (self.root / "Проекты").mkdir()
        target = self.root / "Проекты" / "Новая папка"
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare("mkdir", source="", destination="Проекты/Новая папка")
        self.transactions.grant_write(True)

        prompt = self.confirmation.prepare("mkdir", source="", destination="Проекты/Новая папка")

        self.assertIn("Создать пустую папку", prompt)
        self.assertIn("подтверждаю", prompt)
        self.assertFalse(target.exists())
        result = self.confirmation.confirm("подтверждаю")
        self.assertTrue(target.is_dir())
        self.assertIn("Папка создана", result.message)
        self.assertTrue(result.operation_id)
        self.transactions.undo(result.operation_id)
        self.assertFalse(target.exists())

    def test_create_folder_uses_expiring_group_root_and_root_qualified_undo(self):
        documents = self.root / "Documents"
        documents.mkdir()
        group = FileWorkspaceGroup((
            FileWorkspaceGrant("Documents", FileWorkspace(documents), {"write"}, ttl_seconds=60),
        ))
        transactions = FileWorkspaceGroupTransactions(group)
        transactions.grant_write("Documents", True)
        confirmation = VoiceFileConfirmation(transactions, clock=lambda: self.time)

        confirmation.prepare("mkdir", source="", destination="Documents/Новая")
        result = confirmation.confirm("подтверждаю")

        self.assertTrue((documents / "Новая").is_dir())
        self.assertTrue(result.operation_id.startswith("Documents:"))
        transactions.undo(result.operation_id)
        self.assertFalse((documents / "Новая").exists())

    def test_nested_paths_are_bound_to_selected_workspace_and_folder_is_resolved(self):
        inbox = self.root / "Входящие"
        archive = self.root / "Архив"
        inbox.mkdir()
        archive.mkdir()
        (inbox / "отчёт.txt").write_text("содержимое", encoding="utf-8")
        self.transactions.grant_write(True)

        prompt = self.confirmation.prepare(
            "move",
            source="Входящие/отчёт.txt",
            destination="Архив",
            destination_is_folder=True,
        )
        self.assertIn("Архив/отчёт.txt", prompt)
        result = self.confirmation.confirm("подтверждаю")

        self.assertFalse((inbox / "отчёт.txt").exists())
        self.assertEqual((archive / "отчёт.txt").read_text(encoding="utf-8"), "содержимое")
        self.transactions.undo(result.operation_id)
        self.assertEqual((inbox / "отчёт.txt").read_text(encoding="utf-8"), "содержимое")

    def test_voice_copy_uses_existing_expiring_multi_root_grants(self):
        documents = self.root / "Documents"
        archive = self.root / "Archive"
        documents.mkdir()
        archive.mkdir()
        (documents / "report.txt").write_text("restricted source", encoding="utf-8")
        group = FileWorkspaceGroup((
            FileWorkspaceGrant("Documents", FileWorkspace(documents), {"read"}, ttl_seconds=60),
            FileWorkspaceGrant("Archive", FileWorkspace(archive), {"write"}, ttl_seconds=60),
        ))
        transactions = FileWorkspaceGroupTransactions(group)
        transactions.grant_write("Archive", True)
        confirmation = VoiceFileConfirmation(transactions, clock=lambda: self.time)

        prompt = confirmation.prepare(
            "copy",
            source="Documents/report.txt",
            destination="Archive",
            destination_is_folder=True,
        )
        self.assertIn("Archive/report.txt", prompt)
        self.assertFalse((archive / "report.txt").exists())
        result = confirmation.confirm("подтверждаю")

        self.assertEqual((archive / "report.txt").read_text(encoding="utf-8"), "restricted source")
        self.assertTrue(result.operation_id.startswith("Archive:"))
        transactions.undo(result.operation_id)
        self.assertFalse((archive / "report.txt").exists())
        self.assertEqual((documents / "report.txt").read_text(encoding="utf-8"), "restricted source")

    def test_group_grant_revocation_after_preview_prevents_voice_copy(self):
        documents = self.root / "Documents"
        archive = self.root / "Archive"
        documents.mkdir()
        archive.mkdir()
        (documents / "report.txt").write_text("restricted source", encoding="utf-8")
        group = FileWorkspaceGroup((
            FileWorkspaceGrant("Documents", FileWorkspace(documents), {"read"}, ttl_seconds=60),
            FileWorkspaceGrant("Archive", FileWorkspace(archive), {"write"}, ttl_seconds=60),
        ))
        transactions = FileWorkspaceGroupTransactions(group)
        transactions.grant_write("Archive", True)
        confirmation = VoiceFileConfirmation(transactions, clock=lambda: self.time)
        confirmation.prepare(
            "copy",
            source="Documents/report.txt",
            destination="Archive",
            destination_is_folder=True,
        )
        group.revoke("Archive")

        with self.assertRaises(WorkspaceDenied):
            confirmation.confirm("подтверждаю")
        self.assertFalse((archive / "report.txt").exists())
        self.assertEqual((documents / "report.txt").read_text(encoding="utf-8"), "restricted source")

    def test_path_traversal_from_source_and_folder_target_is_denied(self):
        self.transactions.grant_write(True)
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare("copy", source="../note.txt", destination="copy.txt")
        with self.assertRaises(WorkspaceDenied):
            self.confirmation.prepare(
                "copy", source="note.txt", destination="../outside", destination_is_folder=True
            )
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
