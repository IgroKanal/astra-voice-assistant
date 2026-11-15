from dataclasses import replace
from pathlib import Path
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import handle_action, run_voice_mode
from src.ai_client import LLMResult
from src.streaming_speech import EarlySpeechCoordinator, FirstSentenceBuffer
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

    def test_does_not_speak_observed_untagged_reasoning_prefixes(self):
        for text in (
            "Хорошо, пользователь спрашивает про сумму.",
            "Хорошо, давай подумаю над этим вопросом.",
            "The user asks for a number.",
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


class EarlySpeechCoordinatorTests(unittest.TestCase):
    def test_timeout_keeps_playback_tracked_and_later_turn_recovers(self):
        started = threading.Event()
        release = threading.Event()

        def speak(text):
            if text == "Первая фраза.":
                started.set()
                release.wait(2.0)
                return True
            return False

        output = EarlySpeechCoordinator(speak)
        try:
            self.assertTrue(output.start("Первая фраза."))
            self.assertTrue(started.wait(1.0))
            self.assertFalse(output.wait(0.01).finished)
            self.assertFalse(output.start("Новая фраза."))
            release.set()
            first = output.wait(1.0)
            self.assertTrue(first.finished)
            self.assertTrue(first.succeeded)
            self.assertEqual(first.text, "Первая фраза.")
            self.assertTrue(output.start("Новая фраза."))
            second = output.wait(1.0)
            self.assertTrue(second.finished)
            self.assertFalse(second.succeeded)
            self.assertEqual(second.text, "Новая фраза.")
        finally:
            release.set()

    def test_finished_old_task_cannot_be_confused_with_new_task(self):
        first_finished = threading.Event()

        def speak(text):
            if text == "Старая":
                first_finished.set()
                return True
            return False

        output = EarlySpeechCoordinator(speak)
        self.assertTrue(output.start("Старая"))
        self.assertTrue(first_finished.wait(1.0))
        self.assertTrue(output.wait(1.0).succeeded)
        self.assertTrue(output.start("Новая"))
        outcome = output.wait(1.0)
        self.assertEqual(outcome.text, "Новая")
        self.assertFalse(outcome.succeeded)

    def test_playback_exception_is_reported_without_leaking_text(self):
        on_error = Mock()

        def speak(_text):
            raise RuntimeError("private speech text")

        output = EarlySpeechCoordinator(speak, on_error=on_error)
        self.assertTrue(output.start("Личная фраза"))
        outcome = output.wait(1.0)
        self.assertTrue(outcome.finished)
        self.assertFalse(outcome.succeeded)
        on_error.assert_called_once_with()

    def test_failed_thread_start_does_not_leave_a_pending_task(self):
        output = EarlySpeechCoordinator(lambda _text: True)
        with patch("src.streaming_speech.threading.Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("thread unavailable")
            self.assertFalse(output.start("Тест"))
        self.assertTrue(output.wait(0).finished)
        self.assertTrue(output.start("Следующая"))
        self.assertTrue(output.wait(1.0).succeeded)


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

    def test_compatible_provider_speaks_first_complete_sentence_as_tokens_arrive(self):
        base_ctx, responses, *_ = make_context()
        spoken = []

        class FakeAI:
            def _clean_llm_answer(self, text):
                return text.strip()

            def ask(self, question, on_text_chunk=None):
                self.asserted_question = question
                on_text_chunk("Ответ от облачной модели.")
                on_text_chunk(" Продолжение ответа.")
                return LLMResult(True, "Ответ от облачной модели. Продолжение ответа.")

        fake = FakeAI()
        publish_streamed = Mock()
        ctx = replace(
            base_ctx,
            settings=replace(
                base_ctx.settings,
                llm_provider="compatible",
                ollama_thinking_enabled=True,
            ),
            ai_client=fake,
            speak_partial=lambda text: spoken.append(text) or True,
            respond_streamed=publish_streamed,
        )

        handle_action(
            AssistantAction(ActionType.ASK_LLM, query="вопрос"), ctx
        )

        self.assertEqual(fake.asserted_question, "вопрос")
        self.assertEqual(spoken, ["Ответ от облачной модели."])
        publish_streamed.assert_called_once_with(
            "Ответ от облачной модели. Продолжение ответа.", "Ответ от облачной модели."
        )
        self.assertEqual(responses, [])

    def test_partial_speech_is_finalized_before_reporting_stream_failure(self):
        base_ctx, responses, *_ = make_context()

        class FakeAI:
            def _clean_llm_answer(self, text):
                return text.strip()

            def ask(self, question, on_text_chunk=None):
                on_text_chunk("Начало ответа.")
                on_text_chunk(" ")
                return LLMResult(False, "Не удалось получить ответ.")

        publish_streamed = Mock()
        ctx = replace(
            base_ctx,
            settings=replace(base_ctx.settings, llm_provider="compatible"),
            ai_client=FakeAI(),
            speak_partial=Mock(return_value=True),
            respond_streamed=publish_streamed,
        )

        handle_action(AssistantAction(ActionType.ASK_LLM, query="вопрос"), ctx)

        publish_streamed.assert_called_once_with("Не удалось получить ответ.", "")
        self.assertEqual(responses, [])

    def test_unexpected_failure_after_partial_speech_is_finalized_without_leaking_exception(self):
        base_ctx, responses, *_ = make_context()
        logger = Mock()

        class FakeAI:
            def ask(self, question, on_text_chunk=None):
                on_text_chunk("Начало ответа. ")
                raise RuntimeError("private question and token")

        publish_streamed = Mock()
        ctx = replace(
            base_ctx,
            settings=replace(base_ctx.settings, llm_provider="compatible"),
            ai_client=FakeAI(),
            logger=logger,
            speak_partial=Mock(return_value=True),
            respond_streamed=publish_streamed,
        )

        handle_action(AssistantAction(ActionType.ASK_LLM, query="вопрос"), ctx)

        publish_streamed.assert_called_once_with(
            "Не удалось получить ответ от ИИ. Попробуй ещё раз.", ""
        )
        logger.warning.assert_called_once_with("AI answer failed unexpectedly (%s)", "RuntimeError")
        self.assertEqual(responses, [])

    def test_voice_runtime_serializes_error_after_early_speech_and_recovers_next_turn(self):
        base_ctx, *_ = make_context()
        audio_events = []
        published = []
        first_started = threading.Event()
        release_first = threading.Event()

        class FakeVoice:
            microphone = object()

            def __init__(self, **_kwargs):
                pass

            def set_alternative_selector(self, _selector):
                pass

            def speak(self, _text):
                pass  # Startup greeting is outside the two tested answers.

            def speak_audio_only(self, text, *, manage_state=True):
                audio_events.append(("start", text))
                if text == "Первое начало.":
                    first_started.set()
                    release_first.wait(2.0)
                audio_events.append(("end", text))
                return True

            def publish_response(self, text):
                published.append(text)

            def listen_once(self, **_kwargs):
                return SimpleNamespace(ok=True, text="тест", error="")

        class FakeAI:
            calls = 0

            def ask(self, question, on_text_chunk=None):
                self.calls += 1
                if self.calls == 1:
                    on_text_chunk("Первое начало. ")
                    if not first_started.wait(1.0):
                        raise RuntimeError("early playback did not start")
                    release_first.set()
                    return LLMResult(False, "Не удалось получить ответ.")
                on_text_chunk("Второе начало. Затем продолжение.")
                return LLMResult(True, "Второе начало. Затем продолжение.")

        ai = FakeAI()
        turns = []

        def dispatch(_text, ctx):
            turns.append(1)
            handle_action(AssistantAction(ActionType.ASK_LLM, query="вопрос"), ctx)
            return len(turns) < 2

        settings = replace(
            base_ctx.settings,
            voice_runtime_mode="legacy",
            wake_only_mode=False,
            tts_enabled=True,
            tts_engine="edge",
            llm_provider="compatible",
        )
        try:
            with patch("main.VoiceIO", FakeVoice), \
                 patch("src.desktop_file_search.DesktopFileSearchChannel"), \
                 patch("main.process_turn", side_effect=dispatch), \
                 patch("main.emit_event", return_value=True):
                run_voice_mode(
                    settings, base_ctx.apps, base_ctx.app_manager, base_ctx.keyboard,
                    base_ctx.folders, base_ctx.system, base_ctx.vpn, base_ctx.windows,
                    ai, base_ctx.logger,
                )
        finally:
            release_first.set()

        self.assertEqual(published, [
            "Не удалось получить ответ.",
            "Второе начало. Затем продолжение.",
        ])
        self.assertEqual(audio_events, [
            ("start", "Первое начало."), ("end", "Первое начало."),
            ("start", "Не удалось получить ответ."), ("end", "Не удалось получить ответ."),
            ("start", "Второе начало."), ("end", "Второе начало."),
            ("start", "Затем продолжение."), ("end", "Затем продолжение."),
        ])

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
