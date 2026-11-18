import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from main import handle_action, process_turn, _listen_pending_voice_follow_up
from src.system_discovery import RegisteredApplication
from src.task_router import ActionType, AssistantAction
from tools.smoke_test_v11_daily_workflow import make_context


class DiscoveredLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=r'D:\Astra-Work\Temp')
        self.path = Path(self.temp.name) / 'example.exe'
        self.path.write_bytes(b'first')
        self.app = RegisteredApplication('example', str(self.path))
        self.ctx, self.responses, _, self.apps, *_ = make_context()
        self.apps.registered_apps = (self.app,)

    def tearDown(self):
        self.temp.cleanup()

    def request(self):
        handle_action(AssistantAction(ActionType.OPEN_APP, target='example', source='local'), self.ctx)

    @patch('main.subprocess.Popen')
    @patch('main.discover_registered_applications')
    def test_confirmation_runs_exact_detected_executable_once(self, discover, popen):
        discover.return_value = (self.app,)
        self.request()
        popen.assert_not_called()
        process_turn('да', self.ctx)
        self.assertEqual(popen.call_args.args[0], [str(self.path)])
        self.assertEqual(self.ctx.state.pending_kind, '')
        self.assertEqual(popen.call_count, 1)

    @patch('main.subprocess.Popen')
    @patch('main.discover_registered_applications')
    def test_refusal_and_changed_executable_are_not_run(self, discover, popen):
        discover.return_value = (self.app,)
        self.request()
        process_turn('нет', self.ctx)
        self.request()
        self.path.write_bytes(b'changed')
        process_turn('да', self.ctx)
        popen.assert_not_called()

    @patch('main.subprocess.Popen')
    def test_expired_confirmation_is_not_run(self, popen):
        self.request()
        self.ctx.state.pending_created_at -= 30
        process_turn('да', self.ctx)
        popen.assert_not_called()

    @patch('main.subprocess.Popen')
    def test_new_wake_command_cancels_old_proposal_and_is_handled(self, popen):
        self.request()
        process_turn('астра открой телеграм', self.ctx)
        self.assertEqual(self.apps.opened, ['telegram'])
        self.assertEqual(self.ctx.state.pending_kind, '')
        popen.assert_not_called()

    @patch('main.subprocess.Popen')
    @patch('main.discover_registered_applications')
    def test_revoked_permission_and_changed_registration_prevent_launch(self, discover, popen):
        discover.return_value = ()
        self.request()
        process_turn('да', self.ctx)
        self.assertIn('изменилось', self.responses[-1])
        self.request()
        self.ctx = replace(self.ctx, settings=replace(self.ctx.settings, action_permissions=()))
        process_turn('да', self.ctx)
        self.assertIn('недоступен', self.responses[-1])
        popen.assert_not_called()

    @patch('main.subprocess.Popen')
    def test_model_router_cannot_propose_discovered_launch(self, popen):
        handle_action(AssistantAction(ActionType.OPEN_APP, target='example', source='llm_router'), self.ctx)
        self.assertEqual(self.ctx.state.pending_kind, '')
        popen.assert_not_called()

    @patch('main.discover_registered_applications')
    def test_new_registration_is_found_without_restart(self, discover):
        self.apps.registered_apps = ()
        discover.return_value = (self.app,)
        self.request()
        self.assertEqual(self.ctx.state.pending_kind, 'confirm_discovered_app')
        discover.assert_called_once()

    @patch('main.subprocess.Popen')
    @patch('main.discover_registered_applications')
    def test_start_menu_alias_uses_the_existing_one_time_confirmation(self, discover, popen):
        self.apps.registered_apps = (RegisteredApplication('Friendly Editor', str(self.path), ('editor',)),)
        discover.return_value = self.apps.registered_apps
        handle_action(AssistantAction(ActionType.OPEN_APP, target='editor', source='local'), self.ctx)
        self.assertEqual(self.ctx.state.pending_kind, 'confirm_discovered_app')
        popen.assert_not_called()
        process_turn('да', self.ctx)
        self.assertEqual(popen.call_args.args[0], [str(self.path)])

    @patch('main.subprocess.Popen')
    def test_ambiguous_start_menu_alias_never_launches_either_candidate(self, popen):
        second_path = Path(self.temp.name) / 'other.exe'
        second_path.write_bytes(b'other')
        self.apps.registered_apps = (
            RegisteredApplication('Editor A', str(self.path), ('editor',)),
            RegisteredApplication('Editor B', str(second_path), ('editor',)),
        )
        handle_action(AssistantAction(ActionType.OPEN_APP, target='editor', source='local'), self.ctx)
        self.assertEqual(self.ctx.state.pending_kind, '')
        popen.assert_not_called()

    @patch('main.subprocess.Popen')
    @patch('main.discover_registered_applications')
    def test_voice_followup_handles_open_then_confirmation(self, discover, popen):
        discover.return_value = (self.app,)
        process_turn('астра открой', self.ctx)
        voice = Mock()
        voice.listen_once.side_effect = [SimpleNamespace(ok=True, text='example'),
                                         SimpleNamespace(ok=True, text='да')]
        result = _listen_pending_voice_follow_up(voice, self.ctx, self.ctx.settings, self.ctx.logger)
        self.assertTrue(result)
        self.assertEqual(voice.listen_once.call_count, 2)
        self.assertEqual(popen.call_args.args[0], [str(self.path)])
        self.assertEqual(self.ctx.state.pending_kind, '')

    @patch('main.subprocess.Popen')
    def test_voice_timeout_cancels_confirmation(self, popen):
        self.request()
        voice = Mock()
        voice.listen_once.return_value = SimpleNamespace(ok=False, error='timeout')
        self.assertTrue(_listen_pending_voice_follow_up(voice, self.ctx, self.ctx.settings, self.ctx.logger))
        self.assertEqual(self.ctx.state.pending_kind, '')
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
