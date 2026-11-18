"""Keep local packaging output and temporary files in the configured build area."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.build_paths import cleanup_build_work, configure_temp_directory, resolve_build_paths, using_temp_directory


class BuildPathTests(unittest.TestCase):
    def test_local_windows_defaults_to_d_drive(self) -> None:
        paths = resolve_build_paths(
            Path("C:/work/astra"), {}, is_windows=True, d_drive_available=True
        )
        self.assertEqual(paths.output_root, Path("D:/AstraBuild").resolve())
        self.assertEqual(paths.temp_root, paths.output_root / "_tmp")

    def test_local_windows_does_not_silently_fall_back_to_system_drive(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "D: is unavailable"):
            resolve_build_paths(
                Path("C:/work/astra"), {}, is_windows=True, d_drive_available=False
            )

    def test_ci_defaults_to_runner_checkout_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "checkout" / "astra"
            project.mkdir(parents=True)
            paths = resolve_build_paths(
                project, {"GITHUB_ACTIONS": "true"}, is_windows=True
            )
            self.assertEqual(paths.output_root, project.parent.resolve())
            self.assertEqual(paths.temp_root, project.parent.resolve() / "_tmp")

    def test_explicit_output_and_temp_roots_are_respected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "artifact"
            scratch = Path(temp) / "scratch"
            paths = resolve_build_paths(
                Path(temp) / "repo",
                {
                    "ASTRA_BUILD_OUTPUT_ROOT": str(output),
                    "ASTRA_BUILD_TEMP_ROOT": str(scratch),
                },
                is_windows=True,
                d_drive_available=True,
            )
            self.assertEqual(paths.output_root, output.resolve())
            self.assertEqual(paths.temp_root, scratch.resolve())

    def test_temp_environment_is_restored_after_context(self) -> None:
        names = ("TEMP", "TMP", "TMPDIR")
        old_values = {name: os.environ.get(name) for name in names}
        old_tempdir = tempfile.tempdir
        try:
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / "redirected"
                with using_temp_directory(target):
                    self.assertTrue(target.is_dir())
                    self.assertEqual(tempfile.gettempdir(), str(target.resolve()))
                    for name in names:
                        self.assertEqual(os.environ[name], str(target.resolve()))
            for name, value in old_values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            tempfile.tempdir = old_tempdir
            with patch.dict(os.environ, {"TEMP": str(Path.cwd())}):
                self.assertEqual(configure_temp_directory(Path.cwd()), Path.cwd().resolve())
        finally:
            for name, value in old_values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            tempfile.tempdir = old_tempdir

    def test_cleanup_removes_only_a_named_build_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            work = root / "astra-desktop-build-test"
            work.mkdir()
            (work / "scratch.bin").write_bytes(b"temporary")
            cleanup_build_work(work, temp_root=root)
            self.assertFalse(work.exists())

            outside = root / "outside"
            outside.mkdir()
            with self.assertRaises(ValueError):
                cleanup_build_work(outside, temp_root=root)
            self.assertTrue(outside.is_dir())


if __name__ == "__main__":
    unittest.main()
