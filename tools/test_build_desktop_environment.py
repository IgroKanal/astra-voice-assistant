from pathlib import Path
import os
import sys
import unittest

from tools.build_desktop_environment import isolated_pyinstaller_environment


class DesktopBuildEnvironmentTests(unittest.TestCase):
    def test_excludes_unrelated_native_library_directories(self) -> None:
        env = isolated_pyinstaller_environment(
            {
                "SystemRoot": os.environ["SystemRoot"],
                "PATH": r"C:\Users\user\codex\poppler;C:\Other\bin",
                "KEEP_ME": "present",
            },
            executable=Path(sys.executable),
            python_base=Path(sys.base_prefix),
        )

        self.assertNotIn("codex", env["PATH"].casefold())
        self.assertNotIn("poppler", env["PATH"].casefold())
        self.assertNotIn("Other", env["PATH"])
        self.assertIn(str(Path(os.environ["SystemRoot"]) / "System32"), env["PATH"])
        self.assertIn(str(Path(sys.executable).parent), env["PATH"])
        self.assertIn(str(Path(sys.base_prefix)), env["PATH"])
        self.assertEqual(env["KEEP_ME"], "present")

    def test_deduplicates_paths_without_rewriting_other_environment_values(self) -> None:
        env = isolated_pyinstaller_environment(
            {
                "SystemRoot": os.environ["SystemRoot"],
                "WINDIR": os.environ["SystemRoot"],
                "PATH": "untrusted",
                "TOKEN_PLACEHOLDER": "unchanged",
            },
            executable=Path(sys.executable),
            python_base=Path(sys.base_prefix),
        )

        entries = [entry.casefold() for entry in env["PATH"].split(";")]
        self.assertEqual(len(entries), len(set(entries)))
        self.assertEqual(env["TOKEN_PLACEHOLDER"], "unchanged")


if __name__ == "__main__":
    unittest.main()
