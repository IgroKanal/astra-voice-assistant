from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.file_workspace import FileWorkspace
from src.file_transactions import FileTransactions
from src.skill_executor import ActionPlan, PlanDenied, SkillCall, SkillExecutor


class SkillExecutorTests(unittest.TestCase):
    def test_grant_required_and_arbitrary_action_denied(self):
        for call in (SkillCall("shell", {"command": "whoami"}), SkillCall("files.read_text", {"path": "a.txt"})):
            with self.assertRaises(PlanDenied):
                SkillExecutor().execute(ActionPlan((call,)))

    def test_schema_and_step_limits(self):
        executor = SkillExecutor()
        for plan in (ActionPlan(()), ActionPlan((SkillCall("files.search", {"query": ""}),) * 9), ActionPlan((SkillCall("files.search", {"query": "", "grant": "all"}),))):
            with self.assertRaises(PlanDenied):
                executor.execute(plan)

    def test_read_plan_and_cancel(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-test-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "hello.txt").write_text("hello", encoding="utf-8")
            executor = SkillExecutor(FileWorkspace(root))
            plan = ActionPlan((SkillCall("files.search", {"query": "hello"}), SkillCall("files.read_text", {"path": "hello.txt"})))
            results = executor.execute(plan)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[1].value, "hello")
            cancel = threading.Event()
            cancel.set()
            self.assertFalse(executor.execute(plan, cancel=cancel)[0].ok)

    def test_simulation_is_bounded_and_does_not_need_or_use_workspace(self):
        executor = SkillExecutor()
        plan = ActionPlan((
            SkillCall("files.search", {"query": "report"}),
            SkillCall("files.read_text", {"path": "docs/report.txt"}),
        ))

        preview = executor.simulate(plan, budget_seconds=0.5)

        self.assertFalse(preview.execution_enabled)
        self.assertEqual(preview.max_runtime_seconds, 0.5)
        self.assertEqual([step.name for step in preview.steps], ["files.search", "files.read_text"])
        self.assertTrue(all(step.required_capability == "разрешённая папка пользователя" for step in preview.steps))
        # Simulation validates shape, but actual execution still requires a selected workspace.
        with self.assertRaises(PlanDenied):
            executor.execute(plan)

    def test_copy_and_move_require_a_live_write_grant_and_single_use_transaction_preview(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-copy-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.bin").write_bytes(b"\x00\xffpayload")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((SkillCall("files.copy", {"source": "source.bin", "destination": "copy.bin"}),))
            with self.assertRaises(PlanDenied):
                executor.execute(plan, transaction_previews={})
            transactions.grant_write(True)
            with self.assertRaises(PlanDenied):
                executor.execute(plan)
            token = transactions.preview("copy", "source.bin", "copy.bin").token
            result = executor.execute(plan, transaction_previews={0: token})
            self.assertTrue(result[0].ok)
            self.assertEqual((root / "copy.bin").read_bytes(), b"\x00\xffpayload")
            self.assertFalse(executor.execute(plan, transaction_previews={0: token})[0].ok)
            transactions.grant_write(False)
            move_plan = ActionPlan((SkillCall("files.move", {"source": "copy.bin", "destination": "moved.bin"}),))
            with self.assertRaises(PlanDenied):
                executor.simulate(ActionPlan((SkillCall("files.move", {"source": "../outside", "destination": "inside"}),)))
            transactions.grant_write(True)
            move_token = transactions.preview("move", "copy.bin", "moved.bin").token
            moved = executor.execute(move_plan, transaction_previews={0: move_token})
            self.assertTrue(moved[0].ok)
            self.assertFalse((root / "copy.bin").exists())
            self.assertEqual((root / "moved.bin").read_bytes(), b"\x00\xffpayload")

    def test_rename_and_folder_creation_require_grant_preview_and_reject_unsafe_rename(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-rename-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "old.txt").write_text("safe", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((
                SkillCall("files.create_folder", {"path": "archive"}),
                SkillCall("files.rename", {"source": "old.txt", "destination": "new.txt"}),
            ))
            with self.assertRaises(PlanDenied):
                executor.execute(plan, transaction_previews={})
            for bad in (
                SkillCall("files.rename", {"source": "old.txt", "destination": "archive/new.txt"}),
                SkillCall("files.create_folder", {"path": "../outside"}),
            ):
                with self.subTest(bad=bad), self.assertRaises(PlanDenied):
                    executor.simulate(ActionPlan((bad,)))
            transactions.grant_write(True)
            folder = transactions.preview("mkdir", destination="archive")
            rename = transactions.preview("move", source="old.txt", destination="new.txt")
            results = executor.execute(plan, transaction_previews={0: folder.token, 1: rename.token})
            self.assertTrue(all(result.ok for result in results))
            self.assertTrue((root / "archive").is_dir())
            self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "safe")
            self.assertFalse((root / "old.txt").exists())

    def test_simulation_rejects_unknown_skills_and_invalid_budget(self):
        executor = SkillExecutor()
        with self.assertRaises(PlanDenied):
            executor.simulate(ActionPlan((SkillCall("shell", {"command": "dir"}),)))
        with self.assertRaises(PlanDenied):
            executor.simulate(ActionPlan((SkillCall("files.search", {"query": "x"}),)), budget_seconds=0)

    def test_simulation_rejects_escaping_paths_and_hidden_direction_controls(self):
        executor = SkillExecutor()
        for path in ("../outside.txt", "C:\\outside.txt", "folder/../../secret.txt", "folder/\u202ereport.txt"):
            with self.subTest(path=path), self.assertRaises(PlanDenied):
                executor.simulate(ActionPlan((SkillCall("files.read_text", {"path": path}),)))

    def test_failed_step_stops_plan(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-test-", dir=ROOT) as temp:
            executor = SkillExecutor(FileWorkspace(Path(temp)))
            plan = ActionPlan((SkillCall("files.read_text", {"path": "missing.txt"}), SkillCall("files.search", {"query": ""})))
            results = executor.execute(plan)
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
