import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from main import _controller_message, handle_action, process_turn
from src.ai_client import AIClient
from src.config_loader import Settings
from src.desktop_settings import AIProfile, DesktopSettings
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class CharacterGrammarTests(unittest.TestCase):
    def test_profile_drives_name_and_grammar_for_all_four_characters(self):
        for avatar, gender in [('female_miku', 'female'), ('female_saya', 'female'),
                               ('male_ren', 'male'), ('male_kai', 'male')]:
            with self.subTest(avatar=avatar), patch.object(DesktopSettings, 'load', return_value=AIProfile(avatar_id=avatar, assistant_name='Кира')):
                settings = DesktopSettings().apply(Settings())
                self.assertEqual((settings.assistant_name, settings.assistant_gender), ('Кира', gender))
                prompt = AIClient(settings)._build_answer_system_prompt()
                self.assertIn('Кира', prompt)
                self.assertIn('мужского' if gender == 'male' else 'женского', prompt)

    def test_dialogue_reset_uses_selected_gender(self):
        ctx, responses, *_ = make_context()
        for gender, expected in [('female', 'Начала'), ('male', 'Начал')]:
            selected = replace(ctx, settings=replace(ctx.settings, assistant_gender=gender), ai_client=Mock())
            action = AssistantAction(ActionType.CLEAR_DIALOGUE)
            handle_action(action, selected)
            self.assertEqual(selected.state.pending_kind, "action_confirmation")
            process_turn("да", selected)
            self.assertTrue(responses[-1].startswith(expected + ' '))

    def test_known_controller_responses_follow_character_gender(self):
        ctx, responses, *_ = make_context()
        for gender, expected in [('female', 'Не нашла'), ('male', 'Не нашёл')]:
            selected = replace(ctx, settings=replace(ctx.settings, assistant_gender=gender))
            handle_action(AssistantAction(ActionType.OPEN_APP, target='missing_app'), selected)
            self.assertTrue(responses[-1].startswith(expected))
            self.assertEqual(_controller_message(selected, 'Не нашёл подходящее окно.'), expected + ' подходящее окно.')
            self.assertEqual(_controller_message(selected, 'Она не нашёл письмо.'), 'Она не нашёл письмо.')

    def test_empty_input_follows_character_gender(self):
        ctx, responses, *_ = make_context()
        for gender, expected in [('female', 'Не расслышала'), ('male', 'Не расслышал')]:
            process_turn('', replace(ctx, settings=replace(ctx.settings, assistant_gender=gender)))
            self.assertTrue(responses[-1].startswith(expected))


if __name__ == '__main__':
    unittest.main()
