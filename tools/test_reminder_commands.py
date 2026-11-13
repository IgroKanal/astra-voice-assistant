from dataclasses import replace
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.command_parser import CommandType, parse_command_text
from src.action_policy import ActionPolicy
from src.task_router import ActionType, AssistantAction


class ReminderCommandTests(unittest.TestCase):
    def test_numeric_and_spoken_durations(self):
        for phrase, delay in [("напомни через пять минут сделать перерыв", 300), ("напомни мне через 2 часа позвонить", 7200), ("напомни через одну минуту выпить воды", 60)]:
            parsed = parse_command_text(phrase)
            self.assertEqual(parsed.type, CommandType.REMINDER)
            self.assertEqual(json.loads(parsed.target)["delay"], delay)

    def test_local_calendar_time_reminders(self):
        for phrase, upper_bound in (
            ("напомни завтра в 9 позвонить", 48 * 3600),
            ("напомни мне завтра в 9 30 позвонить", 48 * 3600),
            ("напомни послезавтра в 23 59 проверить файл", 72 * 3600),
        ):
            with self.subTest(phrase=phrase):
                parsed = parse_command_text(phrase)
                self.assertEqual(parsed.type, CommandType.REMINDER)
                payload = json.loads(parsed.target)
                self.assertEqual(set(payload), {"delay", "text"})
                self.assertGreater(payload["delay"], 0)
                self.assertLessEqual(payload["delay"], upper_bound)

    def test_calendar_time_reminders_reject_past_today_and_invalid_clock(self):
        for phrase in (
            "напомни сегодня в 0 позвонить",
            "напомни сегодня в 24 00 позвонить",
            "напомни сегодня в 9 60 позвонить",
            "напомни завтра в 24 позвонить",
            "напомни завтра в 9 99 позвонить",
            "напомни завтра в 9",
        ):
            with self.subTest(phrase=phrase):
                parsed = parse_command_text(phrase)
                self.assertEqual(parsed.type, CommandType.REMINDER)
                self.assertEqual(parsed.target, "")

    def test_invalid_duration_stays_local(self):
        for phrase in ("напомни завтра", "напомни через 0 минут x", "напомни через 99999 часов x"):
            parsed = parse_command_text(phrase)
            self.assertEqual(parsed.type, CommandType.REMINDER)
            self.assertEqual(parsed.target, "")

    def test_only_explicit_nearest_or_next_phrase_selects_one_reminder(self):
        from src.command_parser import CANCEL_NEXT_REMINDER_TARGET, CANCEL_REMINDER_UI_TARGET
        for phrase in ("отмени ближайшее напоминание", "отмени следующее напоминание"):
            parsed = parse_command_text(phrase)
            self.assertEqual(parsed.type, CommandType.REMINDER)
            self.assertEqual(parsed.target, CANCEL_NEXT_REMINDER_TARGET)
        self.assertEqual(
            parse_command_text("отмени напоминание").target,
            CANCEL_REMINDER_UI_TARGET,
        )
        self.assertEqual(
            parse_command_text("отмени напоминание о встрече").target,
            CANCEL_REMINDER_UI_TARGET,
        )

    def test_explicit_list_phrases_are_local_reminder_queries(self):
        from src.command_parser import LIST_UPCOMING_REMINDERS_TARGET, is_command_like_text
        phrases = (
            "покажи напоминания",
            "покажи мои напоминания",
            "какие у меня напоминания",
            "какие у меня есть напоминания",
            "какие у меня ближайшие напоминания",
            "какие ближайшие напоминания",
            "назови ближайшие напоминания",
            "что у меня с напоминаниями",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                parsed = parse_command_text(phrase)
                self.assertEqual(parsed.type, CommandType.REMINDER)
                self.assertEqual(parsed.target, LIST_UPCOMING_REMINDERS_TARGET)
                self.assertTrue(is_command_like_text(phrase))

    def test_voice_list_requires_wake_and_reminder_permission(self):
        from src.reminders import Reminder
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import process_turn
        ctx, responses, ai, *_ = make_context()
        ctx = replace(ctx, allow_conversation_without_wake=True)
        sample = Reminder("id", "проверить письмо", 1_800_000_000, "pending")
        with patch("src.reminders.ReminderStore") as store:
            store.return_value.list_upcoming.return_value = [sample]
            process_turn("какие у меня ближайшие напоминания", ctx)
            store.assert_not_called()
            self.assertEqual(ai.ask_calls, 0)
            self.assertEqual(ai.route_calls, 0)

            process_turn("Астра, какие у меня ближайшие напоминания", ctx)
            store.return_value.list_upcoming.assert_called_once_with(limit=4)
            self.assertIn("проверить письмо", responses[-1])

            ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=()))
            store.reset_mock()
            process_turn("Астра, покажи напоминания", ctx)
            store.assert_not_called()

    def test_voice_list_formats_only_bounded_items_and_local_times(self):
        from datetime import datetime
        from src.reminders import Reminder
        from main import _format_upcoming_reminders
        local_timezone = datetime.now().astimezone().tzinfo
        now = datetime(2026, 11, 14, 12, 0, tzinfo=local_timezone)
        items = [
            Reminder(str(index), f"задача {index}" + ("x" * 150), now.timestamp() + 60, "pending")
            for index in range(4)
        ]
        response = _format_upcoming_reminders(items, now=now)
        self.assertIn("Ближайшие напоминания", response)
        self.assertIn("сегодня в 12:01", response)
        self.assertIn("задача 0", response)
        self.assertIn("Полный список есть", response)
        self.assertLessEqual(response.count("задача "), 3)
        self.assertTrue(_format_upcoming_reminders([]).startswith("Активных напоминаний нет"))

    def test_wake_and_permission_required_before_storage(self):
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import process_turn
        ctx, responses, ai, *_ = make_context()
        with patch("src.reminders.ReminderStore") as store:
            process_turn("напомни через пять минут сделать перерыв", ctx)
            store.assert_not_called()
            process_turn("Астра, напомни через пять минут сделать перерыв", ctx)
            store.return_value.add.assert_called_once()
            self.assertEqual(ai.ask_calls, 0)
            ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=()))
            store.reset_mock()
            process_turn("Астра, напомни через пять минут сделать перерыв", ctx)
            store.assert_not_called()

    def test_voice_cancel_requires_wake_and_reminder_permission(self):
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import process_turn
        ctx, _, ai, *_ = make_context()
        with patch("src.reminders.ReminderStore") as store:
            process_turn("отмени ближайшее напоминание", ctx)
            store.assert_not_called()
            process_turn("Астра, отмени ближайшее напоминание", ctx)
            store.return_value.cancel_next.assert_called_once_with()
            self.assertEqual(ai.ask_calls, 0)
            ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=()))
            store.reset_mock()
            process_turn("Астра, отмени следующее напоминание", ctx)
            store.assert_not_called()

    def test_model_cannot_schedule_reminder(self):
        self.assertFalse(ActionPolicy().check(AssistantAction(ActionType.REMINDER, source="llm_router")).allowed)

    def test_no_wake_reminder_is_not_sent_to_text_conversation(self):
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import process_turn
        ctx, _, ai, *_ = make_context()
        ctx = replace(ctx, allow_conversation_without_wake=True)
        process_turn("напомни через пять минут попить воды", ctx)
        self.assertEqual(ai.ask_calls, 0)
        self.assertEqual(ai.route_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
