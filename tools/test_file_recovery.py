from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.file_transactions import FileTransactions
from src.file_workspace import FileWorkspace, WorkspaceDenied


class SimulatedCrash(RuntimeError):
    pass


class FileRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra-recovery-", dir=ROOT)
        self.root = Path(self.temp.name)
        self.files = FileTransactions(FileWorkspace(self.root))
        self.files.grant_write(True)

    def tearDown(self):
        self.temp.cleanup()

    def interrupt(self, terminal_status):
        original = self.files._save_record
        def save(path, record):
            if record["status"] == terminal_status:
                raise SimulatedCrash()
            original(path, record)
        return patch.object(self.files, "_save_record", side_effect=save)

    def test_crash_after_commit_can_be_reconciled_and_undone(self):
        for kind in ("create", "copy", "move", "replace"):
            with self.subTest(kind=kind):
                source = kind + "-source.txt"
                destination = kind + "-target.txt"
                (self.root / source).write_text("before")
                if kind == "replace":
                    (self.root / destination).write_text("old")
                preview = self.files.preview(kind, source=source if kind in {"copy", "move"} else "", destination=destination, text="after" if kind in {"create", "replace"} else "")
                with self.interrupt("done"), self.assertRaises(SimulatedCrash):
                    self.files.execute(preview.token)
                identity = next(item["id"] for item in self.files.history() if item["destination"] == destination)
                reopened = FileTransactions(FileWorkspace(self.root))
                reopened.grant_write(True)
                self.assertEqual(reopened.recover(identity), "done")
                reopened.undo(identity)
                if kind == "replace":
                    self.assertEqual((self.root / destination).read_text(), "old")
                else:
                    self.assertFalse((self.root / destination).exists())

    def test_crash_after_folder_creation_can_be_reconciled_and_undone(self):
        preview = self.files.preview("mkdir", destination="created-folder")
        with self.interrupt("done"), self.assertRaises(SimulatedCrash):
            self.files.execute(preview.token)
        identity = self.files.history()[0]["id"]
        reopened = FileTransactions(FileWorkspace(self.root))
        reopened.grant_write(True)
        self.assertEqual(reopened.recover(identity), "done")
        reopened.undo(identity)
        self.assertTrue((self.root / ".astra-history" / (identity + ".undone-dir")).is_dir())

    def test_crash_while_undoing_folder_can_be_reconciled(self):
        identity = self.files.execute(self.files.preview("mkdir", destination="created-folder").token)
        with self.interrupt("undone"), self.assertRaises(SimulatedCrash):
            self.files.undo(identity)
        self.assertEqual(self.files.recover(identity), "undone")
        self.assertFalse((self.root / "created-folder").exists())

    def test_crash_during_undo_does_not_repeat_data_mutation(self):
        for kind in ("create", "copy", "move", "replace"):
            with self.subTest(kind=kind):
                source = kind + "-src.txt"
                destination = kind + "-dst.txt"
                (self.root / source).write_text("before")
                if kind == "replace":
                    (self.root / destination).write_text("old")
                identity = self.files.execute(self.files.preview(kind, source=source if kind in {"copy", "move"} else "", destination=destination, text="after" if kind in {"create", "replace"} else "").token)
                with self.interrupt("undone"), self.assertRaises(SimulatedCrash):
                    self.files.undo(identity)
                self.assertEqual(self.files.recover(identity), "undone")
                with self.assertRaises(WorkspaceDenied):
                    self.files.undo(identity)

    def test_recovery_refuses_later_user_changes(self):
        preview = self.files.preview("create", destination="x.txt", text="generated")
        with self.interrupt("done"), self.assertRaises(SimulatedCrash):
            self.files.execute(preview.token)
        identity = self.files.history()[0]["id"]
        (self.root / "x.txt").write_text("user edit")
        with self.assertRaises(WorkspaceDenied):
            self.files.recover(identity)
        self.assertEqual((self.root / "x.txt").read_text(), "user edit")

    def test_prepared_without_data_mutation_is_cancelled(self):
        preview = self.files.preview("create", destination="x.txt", text="new")
        with patch("src.file_transactions.os.link", side_effect=SimulatedCrash), self.assertRaises(SimulatedCrash):
            self.files.execute(preview.token)
        identity = self.files.history()[0]["id"]
        self.assertEqual(self.files.recover(identity), "cancelled")
        self.assertFalse((self.root / "x.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
