from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.latency_report import collect_metrics, format_report, percentile, read_metrics


class LatencyReportTests(unittest.TestCase):
    def test_extracts_component_timings_without_preserving_log_text(self):
        lines = [
            "STT timing: capture=0.42s recognition=1.70s total=2.12s [ok] transcript=PRIVATE_COMMAND",
            "LLM timing: provider=ollama task=answer result=ok thinking=false elapsed=0.80s PRIVATE_QUESTION",
            "LLM first-token timing: provider=ollama task=answer elapsed=0.21s PRIVATE_QUESTION",
            "LLM timing: provider=gemini task=answer model=x result=ok elapsed=1.20s PRIVATE_QUESTION",
            "TTS timing: 0.65s [direct] PRIVATE_QUESTION",
            "unrelated private contents PRIVATE_COMMAND",
        ]

        metrics = collect_metrics(lines)
        report = format_report(metrics)

        self.assertEqual(metrics["stt_total"], [2.12])
        self.assertEqual(metrics["llm_answer"], [0.8, 1.2])
        self.assertEqual(metrics["llm_first_token"], [0.21])
        self.assertEqual(metrics["tts"], [0.65])
        self.assertNotIn("PRIVATE_COMMAND", report)
        self.assertNotIn("PRIVATE_QUESTION", report)
        self.assertIn("Wake -> первый слышимый звук", report)
        self.assertIn("LLM - первый токен: n=1, p50=0.21, p95=0.21", report)

    def test_percentile_uses_nearest_rank_and_handles_empty_input(self):
        self.assertEqual(percentile([4, 1, 3, 2], 0.50), 2)
        self.assertEqual(percentile([4, 1, 3, 2], 0.95), 4)
        self.assertIsNone(percentile([], 0.95))

    def test_rejects_reparse_link_without_reading_target(self):
        with tempfile.TemporaryDirectory(prefix="astra-latency-report-") as temp:
            path = Path(temp) / "log.txt"
            path.write_text("STT timing: capture=1s recognition=2s total=3s [ok]", encoding="utf-8")
            link = Path(temp) / "link.txt"
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable in this environment")
            with self.assertRaises(ValueError):
                read_metrics(link)


if __name__ == "__main__":
    unittest.main(verbosity=2)
