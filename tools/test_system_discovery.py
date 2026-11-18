import tempfile
import unittest
from pathlib import Path

from src.capability_overrides import CapabilityOverrides, CapabilityOverrideStore
from src.config_loader import AppConfig
from src.system_discovery import BrowserDiscovery, _parse_registered_executable, discover_registered_applications, discover_windows_browsers, merge_discovered_browsers, resolve_browser_preference


class FakeRegistry:
    HKEY_CURRENT_USER = 'user'
    HKEY_LOCAL_MACHINE = 'machine'
    HKEY_CLASSES_ROOT = 'classes'

    def __init__(self, values, children):
        self.values, self.children = values, children

    def OpenKey(self, root, path):
        key = (root, path)
        if key not in self.children and not any(item[:2] == key for item in self.values):
            raise OSError('missing')
        return key

    def QueryValueEx(self, key, name):
        try:
            return self.values[(*key, name)], 1
        except KeyError:
            raise OSError('missing')

    def EnumKey(self, key, index):
        try:
            return self.children.get(key, [])[index]
        except IndexError:
            raise OSError('end')

    def CloseKey(self, key):
        pass


class DiscoveryTests(unittest.TestCase):
    def test_commands_are_not_executed_as_shell(self):
        self.assertIsNone(_parse_registered_executable('cmd.exe /c evil.exe'))
        self.assertIsNone(_parse_registered_executable('"C:\\Browser\\app.exe"suffix'))
        self.assertEqual(_parse_registered_executable('"C:\\Browser\\app.exe" --single-argument'), 'C:\\Browser\\app.exe')
        self.assertEqual(_parse_registered_executable('C:\\Program Files\\Browser\\chrome.exe', app_path=True), 'C:\\Program Files\\Browser\\chrome.exe')
        self.assertIsNone(_parse_registered_executable('C:\\Program Files\\Browser\\chrome.exe'))

    def test_registry_discovery_and_default_browser(self):
        app_paths = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
        choice = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        exe = r'C:\Program Files\Browser\chrome.exe'
        values = {
            ('user', app_paths + r'\chrome.exe', ''): exe,
            ('user', choice, 'ProgId'): 'ChromeHTML',
            ('classes', r'ChromeHTML\shell\open\command', ''): '"' + exe + '" -- "%1"',
        }
        registry = FakeRegistry(values, {('user', app_paths): ['chrome.exe']})
        result = discover_windows_browsers(registry=registry, file_exists=lambda path: path == exe)
        self.assertEqual(result.default_browser, 'chrome')
        self.assertEqual(result.apps['chrome'].open_command, [exe])
        self.assertIn('браузер', result.apps['chrome'].aliases)
        missing = discover_windows_browsers(registry=registry, file_exists=lambda path: False)
        self.assertEqual(missing.apps, {})
        self.assertEqual(missing.default_browser, '')

    def test_application_inventory_is_bounded_and_prefers_user_registration(self):
        base = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
        user_path = r'C:\Users\Example\Programs\Editor\editor.exe'
        machine_path = r'C:\Program Files\Editor\editor.exe'
        values = {('user', base + r'\editor.exe', ''): user_path,
                  ('machine', base + r'\editor.exe', ''): machine_path,
                  ('user', base + r'\missing.exe', ''): r'C:\missing.exe'}
        children = {('user', base): ['editor.exe', 'missing.exe'],
                    ('machine', base): ['editor.exe']}
        registry = FakeRegistry(values, children)
        apps = discover_registered_applications(registry=registry, file_exists=lambda p: p != r'C:\missing.exe')
        self.assertEqual([(item.name, item.executable) for item in apps], [('editor', user_path)])
        self.assertEqual(len(discover_registered_applications(registry=registry, file_exists=lambda p: True, limit=1)), 1)
        with self.assertRaises(ValueError):
            discover_registered_applications(registry=registry, limit=0)

    def test_interpreters_are_never_promoted_to_applications(self):
        base = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
        values = {('user', base + r'\editor.exe', ''): r'C:\Windows\System32\cmd.exe',
                  ('user', base + r'\powershell.exe', ''): r'C:\Windows\System32\powershell.exe'}
        children = {('user', base): ['editor.exe', 'powershell.exe']}
        registry = FakeRegistry(values, children)
        self.assertEqual(discover_registered_applications(registry=registry, file_exists=lambda p: True), ())

    def test_preference_and_merge(self):
        app = AppConfig('chrome', ['chrome'], ['C:\\Chrome\\chrome.exe'], 'chrome.exe')
        detected = BrowserDiscovery({'chrome': app}, 'chrome')
        self.assertEqual(resolve_browser_preference('', 'missing', detected), 'chrome')
        self.assertIs(merge_discovered_browsers({}, detected)['chrome'], app)
        old = AppConfig('chrome', ['custom alias'], ['old.exe'], 'old.exe')
        merged = merge_discovered_browsers({'chrome': old}, detected)['chrome']
        self.assertIn('custom alias', merged.aliases)
        self.assertEqual(merged.open_command, app.open_command)

    def test_overrides_round_trip_and_reject_paths(self):
        with tempfile.TemporaryDirectory() as root:
            store = CapabilityOverrideStore(Path(root) / 'preferences.json')
            store.save(CapabilityOverrides('Chrome'))
            self.assertEqual(store.load().browser_preferred, 'chrome')
            with self.assertRaises(ValueError):
                store.save(CapabilityOverrides('C:\\evil.exe'))
            store.save(CapabilityOverrides('chrome', ('browser',)))
            self.assertEqual(store.load().disabled_auto_scopes, ('browser',))
            with self.assertRaises(ValueError):
                store.save(CapabilityOverrides(disabled_auto_scopes=({},)))


if __name__ == '__main__':
    unittest.main()
