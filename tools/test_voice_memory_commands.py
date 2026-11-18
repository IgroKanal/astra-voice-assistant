from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import process_turn
from src.action_policy import ALL_SCOPES, ActionPolicy
from src.command_parser import (
    CommandType,
    MEMORY_FORGET_PREFIX,
    MEMORY_HELP_TARGET,
    MEMORY_LIST_TARGET,
    MEMORY_SAVE_TARGET,
    MEMORY_SEARCH_PREFIX,
    is_command_like_text,
    parse_command_text,
)
from src.personal_memory import MemoryNote
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class VoiceMemoryParserTests(unittest.TestCase):
    def test_save_preserves_spoken_note_and_stays_a_local_command(self):
        parsed = parse_command_text("запомни, что Я предпочитаю ответы по-русски!")
        self.assertEqual(parsed.type, CommandType.MEMORY_NOTE)
        self.assertEqual(parsed.target, MEMORY_SAVE_TARGET)
        self.assertEqual(parsed.text, "Я предпочитаю ответы по-русски!")
        self.assertTrue(is_command_like_text("запомни, что Я предпочитаю ответы по-русски"))

    def test_list_search_and_forget_phrases_are_typed(self):
        self.assertEqual(parse_command_text("покажи сохранённые заметки").target, MEMORY_LIST_TARGET)
        self.assertEqual(
            parse_command_text("найди заметку про ЯЗЫК ответов").target,
            MEMORY_SEARCH_PREFIX + "ЯЗЫК ответов",
        )
        self.assertEqual(
            parse_command_text("забудь заметку про язык ответов").target,
            MEMORY_FORGET_PREFIX + "язык ответов",
        )
        self.assertEqual(parse_command_text("запомни").target, MEMORY_HELP_TARGET)

    def test_forget_command_without_wake_is_rejected_even_in_open_command_mode(self):
        from main import parse_without_wake_if_allowed

        parsed = parse_without_wake_if_allowed(
            "удали из памяти заметку про домашний адрес",
            allow_without_wake=True,
        )
        self.assertEqual(parsed.type.value, "no_wake")
        self.assertEqual(parsed.target, "__requires_wake__")

    def test_oversize_or_too_short_note_stays_local_and_is_not_saved(self):
        for phrase in ("запомни, что ок", "запомни, что " + "x" * 3001):
            with self.subTest(length=len(phrase)):
                parsed = parse_command_text(phrase)
                self.assertEqual(parsed.type, CommandType.MEMORY_NOTE)
                self.assertEqual(parsed.target, MEMORY_HELP_TARGET)


class VoiceMemoryRuntimeTests(unittest.TestCase):
    def _context(self, *, enabled=True, scopes=ALL_SCOPES, provider="ollama", path=""):
        ctx, responses, ai, *_ = make_context()
        settings = replace(
            ctx.settings,
            llm_provider=provider,
            personal_memory_enabled=enabled,
            personal_memory_path=path,
            action_permissions=tuple(scopes),
        )
        return replace(ctx, settings=settings), responses, ai

    def test_memory_commands_require_wake_and_never_reach_any_llm(self):
        ctx, _responses, ai = self._context(enabled=True)
        ctx = replace(ctx, allow_conversation_without_wake=True)

        with patch("src.personal_memory.PersonalMemory") as store:
            process_turn("запомни, что я люблю короткие ответы", ctx)
            store.assert_not_called()

        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

    def test_memory_permission_is_checked_before_opening_store(self):
        scopes = tuple(scope for scope in ALL_SCOPES if scope != "memory")
        ctx, responses, ai = self._context(enabled=True, scopes=scopes)

        with patch("src.personal_memory.PersonalMemory") as store:
            process_turn("Астра, покажи сохранённые заметки", ctx)
            store.assert_not_called()

        self.assertIn("отключён", responses[-1])
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

    def test_disabled_memory_and_nonlocal_provider_do_not_open_store(self):
        for enabled, provider in ((False, "ollama"), (True, "compatible")):
            with self.subTest(enabled=enabled, provider=provider):
                ctx, responses, ai = self._context(enabled=enabled, provider=provider)
                with patch("src.personal_memory.PersonalMemory") as store:
                    process_turn("Астра, покажи сохранённые заметки", ctx)
                    store.assert_not_called()
                self.assertIn("Личная память выключена", responses[-1])
                self.assertEqual(ai.ask_calls, 0)
                self.assertEqual(ai.route_calls, 0)

    def test_save_is_local_encrypted_store_operation_with_separate_consent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "memory.sqlite")
            ctx, responses, ai = self._context(enabled=True, path=path)
            with patch("src.personal_memory.PersonalMemory") as store:
                process_turn("Астра, запомни, что Я люблю короткие ответы.", ctx)
                store.assert_called_once_with(Path(path))
                store.return_value.add.assert_called_once_with(
                    "Я люблю короткие ответы.", "Я люблю короткие ответы."
                )
            self.assertIn("сохранена локально", responses[-1])
            self.assertEqual(ai.ask_calls, 0)
            self.assertEqual(ai.route_calls, 0)

    def test_list_reads_only_titles_and_limits_spoken_summary(self):
        ctx, responses, ai = self._context(enabled=True)
        notes = [
            MemoryNote(str(index), f"Тема {index}", f"секретный текст {index}")
            for index in range(5)
        ]
        with patch("src.personal_memory.PersonalMemory") as store:
            store.return_value.search.return_value = notes
            process_turn("Астра, покажи сохранённые заметки", ctx)

        self.assertIn("Тема 0", responses[-1])
        self.assertIn("найти голосом по фрагменту", responses[-1])
        self.assertNotIn("разделе «Память»", responses[-1])
        self.assertNotIn("секретный текст", responses[-1])
        self.assertLessEqual(responses[-1].count("Тема "), 3)
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

    def test_search_reads_one_match_and_asks_when_ambiguous(self):
        ctx, responses, ai = self._context(enabled=True)
        note = MemoryNote("one", "Язык", "Предпочитаю русский язык интерфейса")
        with patch("src.personal_memory.PersonalMemory") as store:
            store.return_value.search.side_effect = [[note], [note, MemoryNote("two", "Язык 2", "другая заметка")]]
            process_turn("Астра, найди заметку про язык интерфейса", ctx)
            self.assertIn("Предпочитаю русский язык", responses[-1])
            process_turn("Астра, найди заметку про язык интерфейса", ctx)
            self.assertIn("несколько заметок", responses[-1])

        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

    def test_forget_deletes_only_a_unique_match(self):
        ctx, responses, ai = self._context(enabled=True)
        first = MemoryNote("one", "Язык", "Предпочитаю русский язык интерфейса")
        second = MemoryNote("two", "Язык 2", "Другой язык интерфейса")
        with patch("src.personal_memory.PersonalMemory") as store:
            store.return_value.search.side_effect = [[first], [first, second]]
            store.return_value.forget.return_value = True
            process_turn("Астра, забудь заметку про русский язык интерфейса", ctx)
            store.return_value.forget.assert_called_once_with("one")
            self.assertIn("забыта", responses[-1])
            process_turn("Астра, забудь заметку про русский язык интерфейса", ctx)
            self.assertIn("ничего не удалено", responses[-1])
            self.assertEqual(store.return_value.forget.call_count, 1)

        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)

    def test_llm_router_cannot_call_memory_action(self):
        action = AssistantAction(ActionType.MEMORY_NOTE, source="llm_router", confidence=1.0)
        decision = ActionPolicy(ALL_SCOPES).check(action)
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
