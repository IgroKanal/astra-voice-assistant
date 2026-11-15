"""Character grammar shared by the runtime and its AI prompt."""
from __future__ import annotations


def character_phrase(settings, *, female: str, male: str) -> str:
    """Select an explicitly authored phrase, without rewriting user content."""
    return male if getattr(settings, "assistant_gender", "female") == "male" else female


def character_instruction(settings) -> str:
    """Describe only the assistant's own grammatical gender to the model."""
    return character_phrase(
        settings,
        female=("Твой активный персонаж женского рода. Говоря о себе по-русски, "
                "используй женский род: «я поняла», «я нашла»."),
        male=("Твой активный персонаж мужского рода. Говоря о себе по-русски, "
              "используй мужской род: «я понял», «я нашёл»."),
    ) + " Род пользователя и цитаты не изменяй."
