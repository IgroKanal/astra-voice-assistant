"""Keep the user-facing portable package 2D-only until 3D art is approved."""
from __future__ import annotations

import unittest

from tools.validate_desktop_package import validate_deferred_3d_contract


class DeferredThreeDPackageTests(unittest.TestCase):
    def test_manifest_and_archive_can_explicitly_defer_three_dimensional_preview(self):
        validate_deferred_3d_contract(
            {"bundled_components": {"3d_avatar_preview": False}},
            {"Astra/Astra.exe", "Astra/assets/avatars/full_female.png"},
            "Astra",
        )

    def test_package_cannot_claim_to_bundle_the_unapproved_preview(self):
        for manifest in (
            {},
            {"bundled_components": {"3d_avatar_preview": True}},
        ):
            with self.subTest(manifest=manifest), self.assertRaisesRegex(
                ValueError, "must leave the unapproved 3D preview out"
            ):
                validate_deferred_3d_contract(manifest, {"Astra/Astra.exe"}, "Astra")

    def test_prototype_or_godot_binary_is_rejected_even_when_manifest_says_excluded(self):
        forbidden_entries = (
            "Astra/assets/3d_avatar/main.tscn",
            "Astra/third_party/godot/Godot_v4.7.2-stable_win64.exe",
            "Astra/GODOT_LICENSE.txt",
        )
        for entry in forbidden_entries:
            with self.subTest(entry=entry), self.assertRaisesRegex(
                ValueError, "contains the deferred 3D preview"
            ):
                validate_deferred_3d_contract(
                    {"bundled_components": {"3d_avatar_preview": False}},
                    {"Astra/Astra.exe", entry},
                    "Astra",
                )


if __name__ == "__main__":
    unittest.main()
