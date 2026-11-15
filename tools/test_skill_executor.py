from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.file_workspace import FileWorkspace
from src.file_workspace import WorkspaceDenied
from src.file_transactions import FileTransactions
from src.skill_executor import ActionPlan, PlanDenied, SkillCall, SkillExecutor
from src.web_answer import WebAnswer, WebCitation
from src.web_research import WebPage, WebSearchHit


class SkillExecutorTests(unittest.TestCase):
    def test_grant_required_and_arbitrary_action_denied(self):
        for call in (SkillCall("shell", {"command": "whoami"}), SkillCall("files.read_text", {"path": "a.txt"})):
            with self.assertRaises(PlanDenied):
                SkillExecutor().execute(ActionPlan((call,)))

    def test_workspace_and_transaction_capability_must_be_the_same_object(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-binding-", dir=ROOT) as temp:
            root = Path(temp)
            workspace = FileWorkspace(root)
            other_workspace = FileWorkspace(root)
            with self.assertRaisesRegex(PlanDenied, "один workspace"):
                SkillExecutor(workspace, FileTransactions(other_workspace))

    def test_stale_later_preview_prevents_an_earlier_write(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-stale-plan-", dir=ROOT) as temp:
            root = Path(temp)
            first_source = root / "first.txt"
            second_source = root / "second.txt"
            first_source.write_text("first", encoding="utf-8")
            second_source.write_text("before", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((
                SkillCall("files.copy", {"source": "first.txt", "destination": "first-copy.txt"}),
                SkillCall("files.copy", {"source": "second.txt", "destination": "second-copy.txt"}),
            ))
            first = transactions.preview("copy", "first.txt", "first-copy.txt")
            second = transactions.preview("copy", "second.txt", "second-copy.txt")
            second_source.write_text("changed", encoding="utf-8")
            with self.assertRaises(PlanDenied):
                executor.execute(plan, transaction_previews={0: first.token, 1: second.token})
            self.assertFalse((root / "first-copy.txt").exists())
            self.assertEqual(first_source.read_text(encoding="utf-8"), "first")

    def test_overlapping_mutating_steps_are_rejected_before_the_first_write(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-overlap-plan-", dir=ROOT) as temp:
            root = Path(temp)
            (root / "source.txt").write_text("preserve", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            transactions.grant_write(True)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((
                SkillCall("files.move", {"source": "source.txt", "destination": "moved.txt"}),
                SkillCall("files.copy", {"source": "source.txt", "destination": "copy.txt"}),
            ))
            move = transactions.preview("move", "source.txt", "moved.txt")
            copy = transactions.preview("copy", "source.txt", "copy.txt")
            with self.assertRaisesRegex(PlanDenied, "пересекаются"):
                executor.execute(plan, transaction_previews={0: move.token, 1: copy.token})
            self.assertEqual((root / "source.txt").read_text(encoding="utf-8"), "preserve")
            self.assertFalse((root / "moved.txt").exists())
            self.assertFalse((root / "copy.txt").exists())

    def test_trash_skill_requires_separate_scope_and_preview_without_write_access(self):
        with tempfile.TemporaryDirectory(prefix="astra-skill-trash-", dir=ROOT) as temp:
            root = Path(temp)
            target = root / "remove.txt"
            target.write_text("move only to recycle bin", encoding="utf-8")
            workspace = FileWorkspace(root)
            transactions = FileTransactions(workspace)
            executor = SkillExecutor(workspace, transactions)
            plan = ActionPlan((SkillCall("files.trash", {"path": "remove.txt"}),))
            preview_info = executor.simulate(plan)
            self.assertIn("trash scope", preview_info.steps[0].required_capability)
            self.assertFalse(preview_info.execution_enabled)
            with self.assertRaises(PlanDenied):
                executor.execute(plan, transaction_previews={})

            transactions.grant_trash(True)
            preview = transactions.preview("trash", source="remove.txt")
            with patch("src.file_transactions.send2trash", side_effect=lambda path: Path(path).unlink()) as send:
                results = executor.execute(plan, transaction_previews={0: preview.token})
            send.assert_called_once_with(str(target))
            self.assertTrue(results[0].ok)
            self.assertFalse(target.exists())
            self.assertFalse(transactions.writable)

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

    def test_running_search_receives_cancellation_and_shared_plan_deadline(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="astra-skill-cancel-", dir=ROOT) as temp:
            workspace = FileWorkspace(Path(temp))
            executor = SkillExecutor(workspace)
            cancel = threading.Event()
            observed = {}

            def stop_during_search(_query, *, is_cancelled, deadline):
                observed["deadline"] = deadline
                cancel.set()
                if is_cancelled():
                    raise WorkspaceDenied("Поиск отменён пользователем")
                raise AssertionError("cancellation callback did not reflect the event")

            plan = ActionPlan((SkillCall("files.search", {"query": "report"}),))
            with patch.object(workspace, "search", side_effect=stop_during_search):
                results = executor.execute(plan, cancel=cancel, budget_seconds=2)

            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].ok)
            self.assertEqual(results[0].error, "План отменён или истёк лимит времени")
            self.assertGreater(observed["deadline"], time.monotonic())

    def test_running_document_read_receives_cancellation_and_shared_deadline(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="astra-skill-read-cancel-", dir=ROOT) as temp:
            workspace = FileWorkspace(Path(temp))
            executor = SkillExecutor(workspace)
            cancel = threading.Event()
            observed = {}

            def stop_during_read(_path, *, is_cancelled, deadline):
                observed["deadline"] = deadline
                cancel.set()
                if is_cancelled():
                    raise WorkspaceDenied("Чтение отменено пользователем")
                raise AssertionError("cancellation callback did not reflect the event")

            plan = ActionPlan((SkillCall("files.read_text", {"path": "report.pdf"}),))
            with patch.object(workspace, "read_text", side_effect=stop_during_read):
                results = executor.execute(plan, cancel=cancel, budget_seconds=2)

            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].ok)
            self.assertEqual(results[0].error, "План отменён или истёк лимит времени")
            self.assertGreater(observed["deadline"], time.monotonic())

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
            with self.assertRaises(PlanDenied):
                executor.execute(plan, transaction_previews={0: token})
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

    def test_web_skills_require_injected_read_only_capability_and_use_typed_calls(self):
        search_plan = ActionPlan((SkillCall("web.search", {"query": "Astra documentation"}),))
        read_plan = ActionPlan((SkillCall("web.read", {"url": "https://docs.example/page"}),))
        answer_plan = ActionPlan((SkillCall("web.answer", {"query": "Astra documentation"}),))
        with self.assertRaisesRegex(PlanDenied, "отдельное разрешение"):
            SkillExecutor().execute(search_plan)
        with self.assertRaisesRegex(PlanDenied, "веб-разрешение"):
            SkillExecutor().execute(answer_plan)

        web_research = Mock()
        hit = WebSearchHit("Docs", "https://docs.example/page", "Official documentation")
        page = WebPage("Docs", hit.url, "Public page text")
        web_research.search.return_value = (hit,)
        web_research.fetch_page.return_value = page
        executor = SkillExecutor(web_research=web_research)

        preview = executor.simulate(search_plan)
        self.assertEqual(preview.steps[0].required_capability, "истекающее разрешение на интернет-поиск")
        search_results = executor.execute(search_plan)
        page_results = executor.execute(read_plan)

        self.assertTrue(search_results[0].ok)
        self.assertEqual(search_results[0].value, (hit,))
        self.assertTrue(page_results[0].ok)
        self.assertEqual(page_results[0].value, page)
        self.assertEqual(web_research.search.call_args.args[0], "Astra documentation")
        self.assertEqual(web_research.fetch_page.call_args.args, ("https://docs.example/page",))

        web_answer = Mock()
        answer = WebAnswer(
            "Astra documentation",
            "Проверенный ответ [1].",
            (WebCitation(1, "Docs", hit.url),),
        )
        web_answer.answer.return_value = answer
        answer_executor = SkillExecutor(web_answer=web_answer)
        answer_preview = answer_executor.simulate(answer_plan)
        self.assertIn("локальн", answer_preview.steps[0].required_capability)
        answer_result = answer_executor.execute(answer_plan, budget_seconds=2)

        self.assertTrue(answer_result[0].ok)
        self.assertEqual(answer_result[0].value, answer)
        self.assertEqual(web_answer.answer.call_args.args, ("Astra documentation",))
        self.assertLessEqual(web_answer.answer.call_args.kwargs["timeout_seconds"], 2)
        self.assertGreater(web_answer.answer.call_args.kwargs["timeout_seconds"], 1)
        self.assertGreater(web_answer.answer.call_args.kwargs["deadline"], time.monotonic())

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
