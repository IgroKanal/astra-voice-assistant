"""Print privacy-safe timing summaries from one explicitly selected log."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import stat
import sys
from typing import Iterable


MAX_LOG_BYTES = 25 * 1024 * 1024
_STT_RE = re.compile(
    r"STT timing: capture=(\d+(?:\.\d+)?)s "
    r"recognition=(\d+(?:\.\d+)?)s total=(\d+(?:\.\d+)?)s "
    r"\[[^\]\r\n]{1,32}\]"
)
_LLM_RE = re.compile(
    r"LLM timing: provider=[A-Za-z0-9_.-]+ task=answer\b.*?"
    r"\bresult=[A-Za-z0-9_-]+\b.*?\belapsed=(\d+(?:\.\d+)?)s"
)
_TTS_RE = re.compile(r"TTS timing: (\d+(?:\.\d+)?)s \[[^\]\r\n]{1,32}\]")


def percentile(values: Iterable[float], quantile: float) -> float | None:
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def collect_metrics(lines: Iterable[str]) -> dict[str, list[float]]:
    metrics: dict[str, list[float]] = {
        "stt_capture": [],
        "stt_recognition": [],
        "stt_total": [],
        "llm_answer": [],
        "tts": [],
    }
    for line in lines:
        stt_match = _STT_RE.search(line)
        if stt_match:
            metrics["stt_capture"].append(float(stt_match.group(1)))
            metrics["stt_recognition"].append(float(stt_match.group(2)))
            metrics["stt_total"].append(float(stt_match.group(3)))
        llm_match = _LLM_RE.search(line)
        if llm_match:
            metrics["llm_answer"].append(float(llm_match.group(1)))
        tts_match = _TTS_RE.search(line)
        if tts_match:
            metrics["tts"].append(float(tts_match.group(1)))
    return metrics


def read_metrics(log_path: str | Path) -> dict[str, list[float]]:
    path = Path(log_path).expanduser()
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError("Символические ссылки и reparse-файлы запрещены")
    if not path.is_file() or info.st_size > MAX_LOG_BYTES:
        raise ValueError("Выбранный лог отсутствует или превышает 25 МБ")
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        return collect_metrics(stream)


def format_report(metrics: dict[str, list[float]]) -> str:
    rows = (
        ("stt_capture", "STT - захват звука"),
        ("stt_recognition", "STT - распознавание"),
        ("stt_total", "STT - всего"),
        ("llm_answer", "LLM - ответ"),
        ("tts", "TTS - синтез и воспроизведение"),
    )
    report = ["Замеры по выбранному логу Astra (секунды):"]
    found = False
    for key, label in rows:
        values = metrics.get(key, [])
        if not values:
            continue
        found = True
        p50 = percentile(values, 0.50)
        p95 = percentile(values, 0.95)
        assert p50 is not None and p95 is not None
        report.append(f"{label}: n={len(values)}, p50={p50:.2f}, p95={p95:.2f}")
    if not found:
        report.append("В логе нет известных timing-записей.")
    report.append("Wake -> первый слышимый звук текущие логи не измеряют; эту проверку нужно делать отдельно.")
    report.append("Содержимое команд и документов отчёт не показывает.")
    return "\n".join(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_file", help="путь к одному явно выбранному локальному логу")
    args = parser.parse_args(argv)
    if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        metrics = read_metrics(args.log_file)
    except (OSError, ValueError):
        print("Не удалось безопасно прочитать выбранный файл лога.")
        return 2
    print(format_report(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
