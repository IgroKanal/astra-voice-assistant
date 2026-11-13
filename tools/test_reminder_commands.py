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

    def test_invalid_duration_stays_local(self):
        for phrase in ("напомни завтра", "напомни через 0 минут x", "напомни через 99999 часов x"):
            parsed = parse_command_text(phrase)
            self.assertEqual(parsed.type, CommandType.REMINDER)
            self.assertEqual(parsed.target, "")

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
