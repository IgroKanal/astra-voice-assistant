from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.file_group_transactions import FileWorkspaceGroupTransactions
from src.file_transactions import FileTransactions
from src.file_workspace import FileWorkspace, FileWorkspaceGrant, FileWorkspaceGroup, WorkspaceDenied
from src.skill_executor import ActionPlan, PlanDenied, SkillCall, SkillExecutor


class FileWorkspaceGroupTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-group-transactions-", dir=ROOT)
        self.root = Path(self.temp.name)
        self.documents = self.root / "Documents"
        self.backups = self.root / "Backups"
        self.documents.mkdir()
        self.backups.mkdir()
        self.grants = [
            FileWorkspaceGrant("Documents", FileWorkspace(self.documents), {"search", "read", "write"}),
            FileWorkspaceGrant("Backups", FileWorkspace(self.backups), {"search", "read", "write"}),
        ]
        self.group = FileWorkspaceGroup(self.grants)
        self.transactions = FileWorkspaceGroupTransactions(self.group)
        self.executor = SkillExecutor(self.group, self.transactions)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_is_scoped_per_root_and_uses_virtual_preview(self):
        (self.documents / "source.txt").write_text("safe payload", encoding="utf-8")
        self.transactions.grant_write("Documents", True)
        plan = ActionPlan((SkillCall("files.copy", {
            "source": "Documents/source.txt",
            "destination": "Documents/copy.txt",
        }),))
        preview = self.transactions.preview(
            "copy", source="Documents/source.txt", destination="Documents/copy.txt"
        )
        self.assertEqual(preview.source, "Documents/source.txt")
        self.assertEqual(preview.destination, "Documents/copy.txt")
        result = self.executor.execute(plan, transaction_previews={0: preview.token})
        self.assertTrue(result[0].ok)
        self.assertEqual((self.documents / "copy.txt").read_text(encoding="utf-8"), "safe payload")
        self.assertEqual(result[0].value.split(":", 1)[0], "Documents")
        self.assertTrue(self.transactions.writable)

        with self.assertRaises(WorkspaceDenied):
            self.transactions.preview("create", destination="Backups/forbidden.txt", text="denied")
        with self.assertRaises(WorkspaceDenied):
            self.transactions.grant_write("Missing", True)

    def test_read_only_root_cannot_be_enabled_for_writes(self):
        read_only = FileWorkspaceGrant(
            "ReadOnly", FileWorkspace(self.backups), {"search", "read"}
        )
        group = FileWorkspaceGroup([read_only])
        transactions = FileWorkspaceGroupTransactions(group)
        with self.assertRaisesRegex(WorkspaceDenied, "write"):
            transactions.grant_write("ReadOnly", True)

    def test_group_operation_ids_keep_root_scope_for_history_and_undo(self):
        (self.documents / "source.txt").write_text("keep original", encoding="utf-8")
        self.transactions.grant_write("Documents", True)
        plan = ActionPlan((SkillCall("files.copy", {
            "source": "Documents/source.txt",
            "destination": "Documents/copy.txt",
        }),))
        preview = self.transactions.preview(
            "copy", source="Documents/source.txt", destination="Documents/copy.txt"
        )
        operation_id = self.executor.execute(plan, transaction_previews={0: preview.token})[0].value
        self.assertTrue(operation_id.startswith("Documents:"))
        history = self.transactions.history("Documents")
        self.assertEqual(history[-1]["root_alias"], "Documents")
        self.assertEqual(history[-1]["id"], operation_id.split(":", 1)[1])
        self.transactions.undo(operation_id)
        self.assertFalse((self.documents / "copy.txt").exists())
        self.assertEqual((self.documents / "source.txt").read_text(encoding="utf-8"), "keep original")
        with self.assertRaises(WorkspaceDenied):
            self.transactions.undo(operation_id)

    def test_recycle_bin_requires_its_own_root_scope_and_session_switch(self):
        grants = [
            FileWorkspaceGrant("Documents", FileWorkspace(self.documents), {"trash"}),
        ]
        group = FileWorkspaceGroup(grants)
        transactions = FileWorkspaceGroupTransactions(group)
        executor = SkillExecutor(group, transactions)
        target = self.documents / "remove-this.txt"
        target.write_text("recycle bin only", encoding="utf-8")
        with self.assertRaises(WorkspaceDenied):
            transactions.preview("trash", source="Documents/remove-this.txt")
        transactions.grant_trash("Documents", True)
        preview = transactions.preview("trash", source="Documents/remove-this.txt")
        plan = ActionPlan((SkillCall("files.trash", {"path": "Documents/remove-this.txt"}),))
        with patch("src.file_transactions.send2trash", side_effect=lambda path: Path(path).unlink()) as send:
            results = executor.execute(plan, transaction_previews={0: preview.token})
        send.assert_called_once_with(str(target))
        self.assertTrue(results[0].ok)
        result = results[0].value
        self.assertFalse(target.exists())
        self.assertIn("Корзину Windows", result)
        self.assertFalse(transactions.writable)

    def test_cross_root_copy_needs_read_and_write_scopes_and_preserves_binary_data(self):
        source_data = bytes(range(256)) * 256
        (self.documents / "source.bin").write_bytes(source_data)
        grants = [
            FileWorkspaceGrant("Documents", FileWorkspace(self.documents), {"read", "search"}),
            FileWorkspaceGrant("Backups", FileWorkspace(self.backups), {"write"}),
        ]
        group = FileWorkspaceGroup(grants)
        transactions = FileWorkspaceGroupTransactions(group)
        executor = SkillExecutor(group, transactions)
        transactions.grant_write("Backups", True)
        plan = ActionPlan((SkillCall("files.copy", {
            "source": "Documents/source.bin",
            "destination": "Backups/source-copy.bin",
        }),))
        preview = transactions.preview(
            "copy", source="Documents/source.bin", destination="Backups/source-copy.bin"
        )
        self.assertEqual(preview.source, "Documents/source.bin")
        self.assertEqual(preview.destination, "Backups/source-copy.bin")
        result = executor.execute(plan, transaction_previews={0: preview.token})
        self.assertTrue(result[0].ok)
        self.assertEqual((self.backups / "source-copy.bin").read_bytes(), source_data)
        self.assertEqual((self.documents / "source.bin").read_bytes(), source_data)
        transactions.undo(result[0].value)
        self.assertFalse((self.backups / "source-copy.bin").exists())
        self.assertEqual((self.documents / "source.bin").read_bytes(), source_data)

    def test_cross_root_copy_rejects_a_stale_source_before_creating_destination(self):
        source = self.documents / "source.txt"
        source.write_text("reviewed", encoding="utf-8")
        grants = [
            FileWorkspaceGrant("Documents", FileWorkspace(self.documents), {"read"}),
            FileWorkspaceGrant("Backups", FileWorkspace(self.backups), {"write"}),
        ]
        group = FileWorkspaceGroup(grants)
        transactions = FileWorkspaceGroupTransactions(group)
        executor = SkillExecutor(group, transactions)
        transactions.grant_write("Backups", True)
        plan = ActionPlan((SkillCall("files.copy", {
            "source": "Documents/source.txt",
            "destination": "Backups/source-copy.txt",
        }),))
        preview = transactions.preview(
            "copy", source="Documents/source.txt", destination="Backups/source-copy.txt"
        )
        source.write_text("changed after preview", encoding="utf-8")
        with self.assertRaises(PlanDenied):
            executor.execute(plan, transaction_previews={0: preview.token})
        self.assertFalse((self.backups / "source-copy.txt").exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "changed after preview")

    def test_cross_root_move_remains_denied(self):
        (self.documents / "source.txt").write_text("preserve", encoding="utf-8")
        self.transactions.grant_write("Documents", True)
        self.transactions.grant_write("Backups", True)
        with self.assertRaisesRegex(WorkspaceDenied, "Перемещение между"):
            self.transactions.preview(
                "move", source="Documents/source.txt", destination="Backups/source.txt"
            )
        self.assertEqual((self.documents / "source.txt").read_text(encoding="utf-8"), "preserve")
        self.assertFalse((self.backups / "source.txt").exists())

    def test_revoking_root_grant_invalidates_preview_before_execution(self):
        (self.documents / "source.txt").write_text("safe", encoding="utf-8")
        self.transactions.grant_write("Documents", True)
        plan = ActionPlan((SkillCall("files.copy", {
            "source": "Documents/source.txt",
            "destination": "Documents/copy.txt",
        }),))
        preview = self.transactions.preview(
            "copy", source="Documents/source.txt", destination="Documents/copy.txt"
        )
        self.group.revoke("Documents")
        with self.assertRaises(PlanDenied):
            self.executor.execute(plan, transaction_previews={0: preview.token})
        self.assertFalse((self.documents / "copy.txt").exists())

    def test_preview_token_must_match_typed_plan_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="astra-preview-binding-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.txt").write_text("safe", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            executor = SkillExecutor(workspace, transactions)
            token = transactions.preview("copy", source="source.txt", destination="copy.txt").token
            different_plan = ActionPlan((SkillCall("files.copy", {
                "source": "source.txt", "destination": "other.txt",
            }),))
            with self.assertRaisesRegex(PlanDenied, "не совпадает"):
                executor.execute(different_plan, transaction_previews={0: token})
            self.assertFalse((root / "copy.txt").exists())
            self.assertFalse((root / "other.txt").exists())

    def test_every_write_preview_is_validated_before_the_first_step(self):
        with tempfile.TemporaryDirectory(prefix="astra-preview-all-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.txt").write_text("safe", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((
                SkillCall("files.copy", {"source": "source.txt", "destination": "copy.txt"}),
                SkillCall("files.move", {"source": "source.txt", "destination": "moved.txt"}),
            ))
            first = transactions.preview("copy", source="source.txt", destination="copy.txt")
            wrong_second = transactions.preview("move", source="source.txt", destination="different.txt")
            with self.assertRaisesRegex(PlanDenied, "не совпадает"):
                executor.execute(plan, transaction_previews={0: first.token, 1: wrong_second.token})
            self.assertFalse((root / "copy.txt").exists())
            self.assertTrue((root / "source.txt").exists())

    def test_duplicate_preview_token_cannot_authorize_two_plan_steps(self):
        with tempfile.TemporaryDirectory(prefix="astra-preview-duplicate-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.txt").write_text("safe", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((
                SkillCall("files.copy", {"source": "source.txt", "destination": "copy.txt"}),
                SkillCall("files.copy", {"source": "source.txt", "destination": "copy.txt"}),
            ))
            preview = transactions.preview("copy", source="source.txt", destination="copy.txt")
            with self.assertRaisesRegex(PlanDenied, "отдельный токен"):
                executor.execute(plan, transaction_previews={0: preview.token, 1: preview.token})
            self.assertFalse((root / "copy.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
