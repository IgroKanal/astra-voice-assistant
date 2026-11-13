from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.action_audit import ActionAudit
from src.skill_executor import ActionPlan, SkillCall, SkillExecutor
from src.file_workspace import FileWorkspace
from src.file_transactions import FileTransactions


class AuditTests(unittest.TestCase):
    def test_direct_file_actions_and_undo_are_audited_without_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audit = ActionAudit(root / "audit.sqlite")
            transactions = FileTransactions(FileWorkspace(root), audit=audit.record)
            transactions.grant_write(True)
            preview = transactions.preview("create", destination="private.txt", text="sensitive note")
            identity = transactions.execute(preview.token)
            transactions.undo(identity)
            self.assertEqual([(row[1], row[2]) for row in audit.recent()], [("files.undo", "succeeded"), ("files.create", "succeeded")])
            self.assertNotIn(b"sensitive note", audit.path.read_bytes())
            self.assertNotIn(b"private.txt", audit.path.read_bytes())
            with self.assertRaises(ValueError):
                transactions.execute(preview.token)
            self.assertEqual(audit.recent()[0][2], "failed")

    def test_audit_failure_does_not_turn_committed_file_action_into_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def unavailable(*args):
                raise OSError("unavailable")
            transactions = FileTransactions(FileWorkspace(root), audit=unavailable)
            transactions.grant_write(True)
            preview = transactions.preview("create", destination="test.txt", text="data")
            self.assertTrue(transactions.execute(preview.token))
            self.assertEqual((root / "test.txt").read_text(), "data")

    def test_reopen_retention_and_no_arbitrary_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.sqlite"
            audit = ActionAudit(path)
            audit.MAX_ROWS = 2
            for outcome in ("blocked", "failed", "succeeded"):
                audit.record("files.copy", outcome)
            rows = ActionAudit(path).recent()
            self.assertEqual([row[2] for row in rows], ["succeeded", "failed"])
            with self.assertRaises(ValueError):
                audit.record("api_key=secret-value", "succeeded")
            self.assertNotIn(b"secret-value", path.read_bytes())

    def test_future_schema_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "future.sqlite"
            with closing(sqlite3.connect(path)) as db:
                db.execute("PRAGMA user_version=99")
            with self.assertRaises(ValueError):
                ActionAudit(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 99)

    def test_plan_results_share_correlation_without_paths_or_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private.txt").write_text("private document secret", encoding="utf-8")
            audit = ActionAudit(root / "audit.sqlite")
            executor = SkillExecutor(FileWorkspace(root), audit=audit.record)
            results = executor.execute(ActionPlan((SkillCall("files.read_text", {"path": "private.txt"}), SkillCall("files.read_text", {"path": "missing.txt"}))))
            self.assertEqual([item.ok for item in results], [True, False])
            rows = audit.recent()
            self.assertEqual(len({item[3] for item in rows}), 1)
            self.assertEqual([item[2] for item in rows], ["failed", "succeeded"])
            raw = audit.path.read_bytes()
            self.assertNotIn(b"private.txt", raw)
            self.assertNotIn(b"private document secret", raw)


if __name__ == "__main__":
    unittest.main()
