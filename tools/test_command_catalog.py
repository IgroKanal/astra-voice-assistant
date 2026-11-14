from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.command_catalog import COMMAND_GROUPS, search_command_examples
from src.command_parser import CommandType, parse_command_text


class CommandCatalogTests(unittest.TestCase):
    def test_catalog_contains_only_parser_supported_examples(self):
        keys = []
        for group in COMMAND_GROUPS:
            self.assertTrue(group.examples)
            for example in group.examples:
                keys.append(example.key)
                if example.phrase:
                    parsed = parse_command_text(example.phrase)
                    self.assertNotIn(parsed.type, {CommandType.EMPTY, CommandType.ASK_LLM, CommandType.NO_WAKE}, example)
        self.assertEqual(len(keys), len(set(keys)))

    def test_search_is_case_and_yo_insensitive_and_intersects_tokens(self):
        self.assertEqual(
            {example.key for _group, example in search_command_examples("НОВЫЙ ДИАЛОГ")},
            {"new_dialogue"},
        )
        self.assertEqual(
            {example.key for _group, example in search_command_examples("YouTube")},
            {"open_youtube", "youtube_search"},
        )
        self.assertEqual(search_command_examples("несуществующая команда"), ())
        self.assertGreater(len(search_command_examples("")), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
