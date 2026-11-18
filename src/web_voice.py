"""Bounded, local-only public web research for an explicit voice request."""
from __future__ import annotations

import time

from src.desktop_settings import AIProfile
from src.web_answer import WebAnswer, WebAnswerDenied, WebQuestionSession
from src.web_research import WebResearchClient, WebResearchGrant


class VoiceWebResearch:
    """Run one expiring search/read/answer operation under the user's scope."""

    TTL_SECONDS = 90
    MAX_REQUESTS = 4  # one search and at most three public pages
    DEADLINE_SECONDS = 75
    MODEL_TIMEOUT_SECONDS = 45
    MAX_PAGES = 3

    def __init__(self, settings, *, client_factory=WebResearchClient,
                 session_factory=WebQuestionSession, grant_factory=WebResearchGrant):
        self.settings = settings
        self.client_factory = client_factory
        self.session_factory = session_factory
        self.grant_factory = grant_factory

    def answer(self, query: str) -> WebAnswer:
        if "web_research" not in self.settings.action_permissions:
            raise WebAnswerDenied("Веб-исследование выключено в разрешениях Astra")
        if not self.settings.llm_enabled or self.settings.llm_provider != "ollama":
            raise WebAnswerDenied(
                "Для ответа по сайтам выбери локальную Ollama и включи разрешение «Веб-исследование"
                "». Запрос поиска отправляется Bing, содержимое страниц остаётся у локальной модели."
            )

        profile = AIProfile(
            provider="ollama",
            model=self.settings.llm_model,
            base_url=self.settings.llm_base_url,
        ).validate()
        grant = self.grant_factory(
            {"search", "read"},
            ttl_seconds=self.TTL_SECONDS,
            max_requests=self.MAX_REQUESTS,
        )
        try:
            client = self.client_factory(grant)
            session = self.session_factory(client, profile)
            deadline = time.monotonic() + self.DEADLINE_SECONDS
            return session.answer(
                query,
                max_pages=self.MAX_PAGES,
                timeout_seconds=self.MODEL_TIMEOUT_SECONDS,
                deadline=deadline,
            )
        finally:
            grant.revoke()
