"""Character grammar shared by the runtime and its AI prompt."""
from __future__ import annotations


def character_phrase(settings, *, female: str, male: str) -> str:
    """Select an explicitly authored phrase, without rewriting user content."""
    return male if getattr(settings, "assistant_gender", "female") == "male" else female


def character_instruction(settings) -> str:
    """Describe only the assistant's own grammatical gender to the model."""
    return character_phrase(
        settings,
        female=("Твой активный персонаж женского рода. Говоря о себе от первого лица, "
                "согласуй прошедшее время и краткие прилагательные с женским родом: "
                "«я поняла», «я нашла», «я готова». Не используй мужской род о себе."),
        male=("Твой активный персонаж мужского рода. Говоря о себе от первого лица, "
              "согласуй прошедшее время и краткие прилагательные с мужским родом: "
              "«я понял», «я нашёл», «я готов». Не используй женский род о себе."),
    ) + " Род пользователя и цитаты не изменяй."
