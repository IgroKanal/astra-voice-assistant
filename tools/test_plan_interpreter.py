from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.desktop_settings import AIProfile
from src.plan_interpreter import PlanInterpreter
from src.skill_executor import PlanDenied, SkillExecutor


class PlanInterpreterTests(unittest.TestCase):
    def make_interpreter(self, response, profile=None):
        client = Mock()
        client.chat.return_value = response
        return PlanInterpreter(profile or AIProfile(provider="ollama"), client), client

    def test_local_request_becomes_bounded_typed_plan_without_file_context(self):
        response = '{"steps":[{"name":"files.search","arguments":{"query":"счёт"}},' \
                   '{"name":"files.read_text","arguments":{"path":"docs/март.docx"}}]}'
        interpreter, client = self.make_interpreter(response)

        plan = interpreter.interpret("Найди мартовский счёт и прочитай его")

        self.assertEqual([step.name for step in plan.steps], ["files.search", "files.read_text"])
        client.chat.assert_called_once()
        args = client.chat.call_args.args
        self.assertEqual(args[2], "Найди мартовский счёт и прочитай его")
        self.assertNotIn("memory_context", client.chat.call_args.kwargs)

    def test_local_request_can_propose_bounded_copy_and_move_without_granting_write(self):
        response = '{"steps":[{"name":"files.copy","arguments":{"source":"docs/a.pdf","destination":"backup/a.pdf"}},' \
                   '{"name":"files.move","arguments":{"source":"docs/old.txt","destination":"docs/archive/old.txt"}}]}'
        interpreter, _ = self.make_interpreter(response)
        plan = interpreter.interpret("Скопируй PDF в backup и перенеси старую заметку в архив")
        self.assertEqual([step.name for step in plan.steps], ["files.copy", "files.move"])
        preview = SkillExecutor().simulate(plan)
        self.assertTrue(all("временное разрешение записи" in step.required_capability for step in preview.steps))
        self.assertFalse(preview.execution_enabled)

    def test_local_request_can_propose_rename_and_empty_folder_creation(self):
        response = '{"steps":[{"name":"files.rename","arguments":{"source":"notes/old.txt","destination":"notes/new.txt"}},' \
                   '{"name":"files.create_folder","arguments":{"path":"archive/2026"}}]}'
        interpreter, _ = self.make_interpreter(response)
        plan = interpreter.interpret("Переименуй заметку и создай папку архива")
        preview = SkillExecutor().simulate(plan)
        self.assertEqual([step.name for step in plan.steps], ["files.rename", "files.create_folder"])
        self.assertTrue(all("временное разрешение записи" in step.required_capability for step in preview.steps))

    def test_rejects_cloud_provider_and_empty_requests(self):
        with self.assertRaises(PlanDenied):
            PlanInterpreter(AIProfile(provider="compatible", base_url="https://example.invalid"), Mock())
        interpreter, _ = self.make_interpreter('{"steps":[]}')
        with self.assertRaises(PlanDenied):
            interpreter.interpret("   ")
        with self.assertRaises(PlanDenied):
            interpreter.interpret("x" * 1501)

    def test_fails_closed_for_malformed_or_out_of_schema_model_output(self):
        for response in (
            "```json\n{\"steps\": []}\n```",
            '{"steps":[]}',
            '{"steps":[{"name":"shell","arguments":{"command":"dir"}}]}',
            '{"steps":[{"name":"files.read_text","arguments":{"path":"../secret.txt"}}]}',
            '{"steps":[{"name":"files.copy","arguments":{"source":"../secret.txt","destination":"safe.txt"}}]}',
            '{"steps":[{"name":"files.move","arguments":{"source":"safe.txt","destination":"C:\\\\outside.txt"}}]}',
            '{"steps":[{"name":"files.delete","arguments":{"path":"safe.txt"}}]}',
            '{"steps":[{"name":"files.search","arguments":{"query":"x","extra":"y"}}]}',
            '{"steps":[{"name":"files.search","name":"shell","arguments":{"query":"x"}}]}',
            '{"steps":[{"name":"files.search","arguments":{"query":"x"}}],"execute":true}',
        ):
            with self.subTest(response=response):
                interpreter, _ = self.make_interpreter(response)
                with self.assertRaises(PlanDenied):
                    interpreter.interpret("найди файл")


if __name__ == "__main__":
    unittest.main(verbosity=2)
