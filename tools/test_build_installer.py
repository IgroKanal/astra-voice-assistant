import unittest

from tools.build_installer import installer_binary_version


class InstallerVersionTests(unittest.TestCase):
    def test_stable_product_version_maps_to_four_numeric_windows_parts(self):
        self.assertEqual(installer_binary_version("3.1.0"), "3.1.0.0")

    def test_beta_and_dev_builds_keep_their_numeric_prerelease_revision(self):
        self.assertEqual(installer_binary_version("3.0.0-beta.8"), "3.0.0.8")
        self.assertEqual(installer_binary_version("1.4.0-dev.31"), "1.4.0.31")

    def test_unknown_or_non_numeric_version_schemes_are_rejected(self):
        for version in ("", "3.1", "v3.1.0", "3.1.0-alpha.1", "3.1.0+build.1"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                installer_binary_version(version)


if __name__ == "__main__":
    unittest.main()
