from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.action_policy import DEFAULT_SCOPES
from src.command_parser import CommandType, parse_command_text
from src.config_loader import Settings
from src.task_router import ActionType, AssistantAction
from src.web_answer import WebAnswer, WebAnswerDenied, WebCitation
from src.web_voice import VoiceWebResearch
from tools.smoke_test_v11_daily_workflow import make_context
from main import _publish_web_sources, handle_action, process_turn


class VoiceWebResearchTests(unittest.TestCase):
    def enabled_settings(self, **kwargs):
        return Settings(
            llm_provider="ollama",
            llm_enabled=True,
            llm_model="test-local",
            llm_base_url="http://127.0.0.1:11434",
            action_permissions=DEFAULT_SCOPES + ("web_research",),
            **kwargs,
        )

    def test_web_command_is_distinct_and_requires_the_wake_phrase(self):
        parsed = parse_command_text("найди ответ в интернете Кто создал Python?")
        self.assertEqual(parsed.type, CommandType.WEB_ANSWER)
        self.assertEqual(parsed.target, "Кто создал Python?")
        self.assertEqual(
            parse_command_text("поищи в интернете Python").type,
            CommandType.WEB_SEARCH,
        )

        ctx, responses, _ai, _apps, _keyboard, _folders, _windows = make_context()
        ctx = replace(
            ctx,
            settings=self.enabled_settings(),
            web_answer=Mock(),
        )
        process_turn("найди ответ в интернете кто создал python", ctx)
        self.assertEqual(responses, ["Назови меня перед этой командой."])
        ctx.web_answer.assert_not_called()

    def test_action_policy_and_voice_flow_require_the_separate_scope(self):
        ctx, responses, _ai, _apps, _keyboard, _folders, _windows = make_context()
        answer = Mock()
        ctx = replace(ctx, web_answer=answer)
        action = AssistantAction(
            ActionType.WEB_ANSWER,
            query="контрольный вопрос",
            source="local_parser",
        )

        handle_action(action, ctx)

        self.assertIn("отключён", responses[-1])
        answer.assert_not_called()

    def test_cloud_provider_is_rejected_before_web_handler(self):
        ctx, responses, _ai, _apps, _keyboard, _folders, _windows = make_context()
        answer = Mock()
        ctx = replace(
            ctx,
            settings=replace(
                self.enabled_settings(),
                llm_provider="gemini",
            ),
            web_answer=answer,
        )
        handle_action(
            AssistantAction(
                ActionType.WEB_ANSWER,
                query="контрольный вопрос",
                source="local_parser",
            ),
            ctx,
        )
        self.assertIn("только выбранную локальную Ollama", responses[-1])
        answer.assert_not_called()

    def test_voice_answer_is_local_and_publishes_only_cited_sources(self):
        ctx, responses, _ai, _apps, _keyboard, _folders, _windows = make_context()
        result = WebAnswer(
            "Вопрос",
            "Краткий ответ [1].",
            (WebCitation(1, "Документация", "https://docs.example/page"),),
        )
        answer = Mock(return_value=result)
        sources = Mock()
        ctx = replace(
            ctx,
            settings=self.enabled_settings(),
            web_answer=answer,
            web_sources=sources,
        )
        process_turn("Астра, найди ответ в интернете контрольный вопрос", ctx)
        answer.assert_called_once_with("контрольный вопрос")
        sources.assert_called_once_with(result.citations)
        self.assertEqual(responses[-1], result.text)

    def test_main_publishes_cited_sources_as_typed_runtime_data(self):
        citation = WebCitation(1, "Документация", "https://docs.example/page")
        with patch.dict(os.environ, {"ASTRA_DESKTOP_EVENTS": "1"}):
            with patch("builtins.print") as output:
                _publish_web_sources((citation,))
        from src.runtime_events import parse_event_record
        event = parse_event_record(output.call_args.args[0])
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "assistant")
        self.assertEqual(event.data, {
            "kind": "web_sources",
            "sources": [{"index": 1, "title": "Документация", "url": "https://docs.example/page"}],
        })

    def test_voice_service_uses_short_lived_search_and_revokes_after_success_or_error(self):
        settings = self.enabled_settings()
        citation = WebCitation(1, "Документация", "https://docs.example/page")
        result = WebAnswer("Вопрос", "Ответ [1].", (citation,))
        grant = Mock()
        session = Mock()
        session.answer.return_value = result
        client_factory = Mock(return_value=object())
        session_factory = Mock(return_value=session)
        grant_factory = Mock(return_value=grant)
        service = VoiceWebResearch(
            settings,
            client_factory=client_factory,
            session_factory=session_factory,
            grant_factory=grant_factory,
        )

        actual = service.answer("Вопрос")

        self.assertIs(actual, result)
        grant_factory.assert_called_once_with(
            {"search", "read"},
            ttl_seconds=VoiceWebResearch.TTL_SECONDS,
            max_requests=VoiceWebResearch.MAX_REQUESTS,
        )
        client_factory.assert_called_once_with(grant)
        kwargs = session.answer.call_args.kwargs
        self.assertEqual(kwargs["max_pages"], VoiceWebResearch.MAX_PAGES)
        self.assertLessEqual(kwargs["timeout_seconds"], 45)
        self.assertGreater(kwargs["deadline"], 0)
        grant.revoke.assert_called_once()

        grant = Mock()
        session = Mock()
        session.answer.side_effect = WebAnswerDenied("разрешение отозвано")
        service = VoiceWebResearch(
            settings,
            client_factory=Mock(return_value=object()),
            session_factory=Mock(return_value=session),
            grant_factory=Mock(return_value=grant),
        )
        with self.assertRaises(WebAnswerDenied):
            service.answer("Вопрос")
        grant.revoke.assert_called_once()

    def test_voice_service_refuses_network_without_user_scope_or_local_model(self):
        client_factory = Mock()
        settings = replace(self.enabled_settings(), action_permissions=DEFAULT_SCOPES)
        service = VoiceWebResearch(settings, client_factory=client_factory)
        with self.assertRaisesRegex(WebAnswerDenied, "выключено"):
            service.answer("Вопрос")
        client_factory.assert_not_called()

        settings = replace(self.enabled_settings(), llm_provider="gemini")
        service = VoiceWebResearch(settings, client_factory=client_factory)
        with self.assertRaisesRegex(WebAnswerDenied, "локальную Ollama"):
            service.answer("Вопрос")
        client_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
