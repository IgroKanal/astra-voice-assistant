from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.action_policy import ActionPolicy
from src.task_router import ActionType, AssistantAction


class ActionPolicyTests(unittest.TestCase):
    def test_revoked_capabilities_block_every_mapped_action(self):
        policy = ActionPolicy(())
        for action_type in (ActionType.OPEN_APP, ActionType.CLOSE_APP, ActionType.OPEN_URL, ActionType.OPEN_FOLDER, ActionType.TYPE_TEXT, ActionType.WINDOW_CONTROL, ActionType.VPN_CONTROL, ActionType.MEDIA_CONTROL, ActionType.ROUTINE, ActionType.MEMORY_NOTE, ActionType.FILE_SEARCH):
            with self.subTest(action=action_type):
                self.assertFalse(policy.check(AssistantAction(action_type)).allowed)
        self.assertTrue(policy.check(AssistantAction(ActionType.GET_TIME)).allowed)

    def test_llm_and_untrusted_sources_cannot_expand_capabilities(self):
        for source in ("llm_router", "document", "memory", "webpage"):
            action = AssistantAction(ActionType.TYPE_TEXT, target="x", source=source)
            self.assertFalse(ActionPolicy().check(action).allowed)
        action = AssistantAction(ActionType.OPEN_APP, target="editor", source="llm_router", confidence=0.4)
        self.assertFalse(ActionPolicy().check(action).allowed)
        reset = AssistantAction(ActionType.CLEAR_DIALOGUE, source="llm_router", confidence=1.0)
        self.assertFalse(ActionPolicy().check(reset).allowed)

    def test_shortcuts_respect_appropriate_scope(self):
        self.assertTrue(ActionPolicy(("media",)).check(AssistantAction(ActionType.KEYBOARD_SHORTCUT, target="media_next")).allowed)
        self.assertFalse(ActionPolicy(("media",)).check(AssistantAction(ActionType.KEYBOARD_SHORTCUT, target="enter")).allowed)

    def test_all_browser_shortcuts_are_blocked_when_browser_revoked(self):
        from src.keyboard_controller import _BROWSER_SHORTCUTS
        for shortcut in _BROWSER_SHORTCUTS:
            with self.subTest(shortcut=shortcut):
                self.assertFalse(ActionPolicy(("typing",)).check(AssistantAction(ActionType.KEYBOARD_SHORTCUT, target=shortcut)).allowed)
        self.assertFalse(ActionPolicy(("typing",)).check(AssistantAction(ActionType.KEYBOARD_SHORTCUT, target="show_desktop")).allowed)

    def test_media_cannot_bypass_app_permission(self):
        for target in ("open_play_local", "shutdown_yandex_music"):
            self.assertFalse(ActionPolicy(("media",)).check(AssistantAction(ActionType.MEDIA_CONTROL, target=target)).allowed)

    def test_routine_steps_respect_revoked_app_permission(self):
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import _execute_routine
        ctx, _, _, apps, *_ = make_context()
        ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=()))
        from src.routine_controller import RoutineDefinition, RoutineStep
        routine = RoutineDefinition(name="test", aliases=("test",), steps=(RoutineStep("open_app", "telegram"),), response="test")
        self.assertEqual(_execute_routine(routine, ctx)[0], 0)
        self.assertEqual(apps.opened, [])

    def test_runtime_denial_happens_before_controller(self):
        from tools.smoke_test_v11_daily_workflow import make_context
        from main import handle_action
        ctx, responses, ai, apps, *_ = make_context()
        ctx = replace(ctx, settings=replace(ctx.settings, action_permissions=()))
        handle_action(AssistantAction(ActionType.OPEN_APP, target="telegram"), ctx)
        self.assertEqual(apps.opened, [])
        self.assertIn("отключён", responses[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
