from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from main import process_turn
from src.command_parser import CommandType, parse_command_text
from tools.smoke_test_v11_daily_workflow import make_context


class LocalCalendarTests(unittest.TestCase):
    def test_weekday_questions_use_local_date_without_model(self):
        for phrase in ("какой сегодня день", "какой сегодня день недели", "какой день недели", "сегодня какой день недели"):
            with self.subTest(phrase=phrase):
                self.assertEqual(parse_command_text(phrase).type, CommandType.GET_DATE)
                ctx, responses, ai, *_ = make_context()
                with patch("main.datetime") as clock:
                    clock.now.return_value = datetime(2026, 11, 16, 12, 0)
                    process_turn("Астра, " + phrase, ctx)
                self.assertEqual(responses[-1], "Сегодня понедельник, 16.11.2026.")
                self.assertEqual(ai.ask_calls, 0)
                self.assertEqual(ai.route_calls, 0)

    def test_longer_questions_are_not_misclassified_as_local_date(self):
        self.assertNotEqual(parse_command_text("какой сегодня день в Японии").type, CommandType.GET_DATE)

    def test_all_weekdays_have_russian_names(self):
        for day, expected in enumerate(("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"), 16):
            ctx, responses, *_ = make_context()
            with self.subTest(day=day), patch("main.datetime") as clock:
                clock.now.return_value = datetime(2026, 11, day, 12, 0)
                process_turn("Астра, какая сегодня дата", ctx)
            self.assertIn(expected, responses[-1])


if __name__ == "__main__":
    unittest.main()
