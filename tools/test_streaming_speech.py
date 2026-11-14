from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import handle_action
from src.ai_client import LLMResult
from src.streaming_speech import FirstSentenceBuffer
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class FirstSentenceBufferTests(unittest.TestCase):
    def test_releases_one_clean_sentence_only_after_boundary(self):
        stream = FirstSentenceBuffer()
        self.assertEqual(stream.feed("Привет, Егор."), "")
        self.assertEqual(stream.feed(" Следующая часть ответа."), "Привет, Егор.")
        self.assertEqual(stream.feed(" Больше текста."), "")

    def test_does_not_release_hidden_markup_or_draft_prefix(self):
        for text in (
            "<think>Скрытое рассуждение. финал",
            "Analysis: промежуточный текст.",
            "```python\nprint(1).\n```",
        ):
            with self.subTest(text=text):
                self.assertEqual(FirstSentenceBuffer().feed(text + " "), "")

    def test_cleaner_removes_leading_answer_label_before_speech(self):
        stream = FirstSentenceBuffer(lambda text: text.removeprefix("Ответ: ").strip())
        self.assertEqual(stream.feed("Ответ: готово."), "")
        self.assertEqual(stream.feed(" Продолжаю."), "готово.")

    def test_discards_overlong_first_sentence(self):
        stream = FirstSentenceBuffer()
        self.assertEqual(stream.feed("А" * 401 + ". "), "")
        self.assertEqual(stream.feed("Следующее предложение. "), "")


class VoiceAnswerStreamingTests(unittest.TestCase):
    def test_local_answer_speaks_first_sentence_once_and_publishes_complete_text(self):
        base_ctx, responses, *_ = make_context()
        spoken = []

        class FakeAI:
            def _clean_llm_answer(self, text):
                return text.strip()

            def ask(self, question, on_text_chunk=None):
                self.asserted_question = question
                on_text_chunk("Первая фраза.")
                on_text_chunk(" ")
                on_text_chunk("Вторая часть ответа.")
                return LLMResult(True, "Первая фраза. Вторая часть ответа.")

        fake = FakeAI()
        publish_streamed = Mock()
        ctx = replace(
            base_ctx,
            settings=replace(
                base_ctx.settings,
                llm_provider="ollama",
                ollama_thinking_enabled=False,
            ),
            ai_client=fake,
            speak_partial=lambda text: spoken.append(text) or True,
            respond_streamed=publish_streamed,
        )

        handle_action(
            AssistantAction(ActionType.ASK_LLM, query="тестовый вопрос"), ctx
        )

        self.assertEqual(fake.asserted_question, "тестовый вопрос")
        self.assertEqual(spoken, ["Первая фраза."])
        publish_streamed.assert_called_once_with(
            "Первая фраза. Вторая часть ответа.", "Первая фраза."
        )
        self.assertEqual(responses, [])

    def test_thinking_mode_does_not_speak_unfinished_model_output(self):
        base_ctx, responses, *_ = make_context()
        speak_partial = Mock(return_value=True)
        respond_streamed = Mock()

        class FakeAI:
            def ask(self, question):
                return LLMResult(True, "Полный проверенный ответ.")

        ctx = replace(
            base_ctx,
            settings=replace(
                base_ctx.settings,
                llm_provider="ollama",
                ollama_thinking_enabled=True,
            ),
            ai_client=FakeAI(),
            speak_partial=speak_partial,
            respond_streamed=respond_streamed,
        )
        handle_action(AssistantAction(ActionType.ASK_LLM, query="вопрос"), ctx)

        speak_partial.assert_not_called()
        respond_streamed.assert_not_called()
        self.assertEqual(responses, ["Полный проверенный ответ."])


if __name__ == "__main__":
    unittest.main(verbosity=2)
