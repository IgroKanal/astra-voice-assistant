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

    def test_start_menu_shortcuts_add_display_names_without_launching_targets(self):
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            shortcut_root = Path(root) / 'Programs'
            shortcut_root.mkdir()
            shortcut = shortcut_root / 'Friendly Editor.lnk'
            shortcut.write_bytes(b'fixture')
            executable = r'C:\Program Files\Vendor\editor.exe'
            seen = []

            def read_shortcut(path):
                seen.append(path)
                return executable

            registry = FakeRegistry({}, {})
            apps = discover_registered_applications(
                registry=registry,
                file_exists=lambda path: path == executable,
                start_menu_roots=(str(shortcut_root),),
                shortcut_target=read_shortcut,
            )
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0].name, 'Friendly Editor')
            self.assertEqual(apps[0].executable, executable)
            self.assertEqual(apps[0].aliases, ('editor',))
            self.assertEqual(seen, [str(shortcut)])

    def test_start_menu_ignores_shell_hosts_and_missing_targets(self):
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            shortcut_root = Path(root) / 'Programs'
            shortcut_root.mkdir()
            (shortcut_root / 'Explorer.lnk').write_bytes(b'fixture')
            (shortcut_root / 'Missing.lnk').write_bytes(b'fixture')
            (shortcut_root / 'Network.lnk').write_bytes(b'fixture')
            (shortcut_root / 'Arguments.lnk').write_bytes(b'fixture')
            targets = {
                'Explorer.lnk': r'C:\Windows\explorer.exe',
                'Missing.lnk': r'C:\Program Files\gone.exe',
                'Network.lnk': r'\\server\share\remote.exe',
                'Arguments.lnk': r'C:\Program Files\app.exe --launch-extra',
            }
            apps = discover_registered_applications(
                registry=FakeRegistry({}, {}),
                file_exists=lambda path: path == r'C:\Windows\explorer.exe',
                start_menu_roots=(str(shortcut_root),),
                shortcut_target=lambda path: targets[Path(path).name],
            )
            self.assertEqual(apps, ())

    def test_start_menu_name_merges_as_alias_for_registered_executable(self):
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            shortcut_root = Path(root) / 'Programs'
            shortcut_root.mkdir()
            (shortcut_root / 'Friendly Editor.lnk').write_bytes(b'fixture')
            base = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
            executable = r'C:\Program Files\Vendor\editor.exe'
            registry = FakeRegistry(
                {('user', base + r'\editor.exe', ''): executable},
                {('user', base): ['editor.exe']},
            )
            apps = discover_registered_applications(
                registry=registry,
                file_exists=lambda path: path == executable,
                start_menu_roots=(str(shortcut_root),),
                shortcut_target=lambda _path: executable,
            )
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0].name, 'editor')
            self.assertEqual(apps[0].aliases, ('Friendly Editor',))

    def test_shortcut_scan_is_bounded(self):
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            shortcut_root = Path(root) / 'Programs'
            shortcut_root.mkdir()
            for name in ('One.lnk', 'Two.lnk'):
                (shortcut_root / name).write_bytes(b'fixture')
            seen = []
            discover_registered_applications(
                registry=FakeRegistry({}, {}),
                file_exists=lambda _path: True,
                start_menu_roots=(str(shortcut_root),),
                shortcut_target=lambda path: seen.append(path) or r'C:\Program Files\app.exe',
                max_shortcuts=1,
            )
            self.assertEqual(len(seen), 1)

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
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            store = CapabilityOverrideStore(Path(root) / 'preferences.json')
            store.save(CapabilityOverrides('Chrome', vpn_service_preferred='WireGuardTunnel$home'))
            self.assertEqual(store.load().browser_preferred, 'chrome')
            self.assertEqual(store.load().vpn_service_preferred, 'WireGuardTunnel$home')
            with self.assertRaises(ValueError):
                store.save(CapabilityOverrides('C:\\evil.exe'))
            store.save(CapabilityOverrides('chrome', ('browser',)))
            self.assertEqual(store.load().disabled_auto_scopes, ('browser',))
            with self.assertRaises(ValueError):
                store.save(CapabilityOverrides(disabled_auto_scopes=({},)))
            with self.assertRaises(ValueError):
                store.save(CapabilityOverrides(vpn_service_preferred='WireGuardTunnel$home*'))

    def test_legacy_override_file_loads_without_vpn_choice(self):
        with tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp') as root:
            path = Path(root) / 'preferences.json'
            path.write_text(
                '{"version":1,"browser_preferred":"chrome","disabled_auto_scopes":[]}',
                encoding='utf-8',
            )
            loaded = CapabilityOverrideStore(path).load()
            self.assertEqual(loaded.browser_preferred, 'chrome')
            self.assertEqual(loaded.vpn_service_preferred, '')


if __name__ == '__main__':
    unittest.main()
