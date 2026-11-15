from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.action_policy import ALL_SCOPES, CAPABILITY_CATALOG, DEFAULT_SCOPES, ActionPolicy, capability_catalog
from src.task_router import ActionType, AssistantAction


class ActionPolicyTests(unittest.TestCase):
    def test_capability_catalog_is_complete_and_matches_existing_defaults(self):
        catalog = capability_catalog()
        self.assertEqual(catalog, CAPABILITY_CATALOG)
        self.assertEqual(tuple(item.key for item in catalog), ALL_SCOPES)
        self.assertEqual(
            tuple(item.key for item in catalog if item.enabled_by_default),
            DEFAULT_SCOPES,
        )
        self.assertTrue(all(item.title and item.description for item in catalog))

    def test_invalid_permission_sets_and_malformed_actions_fail_closed(self):
        for scopes in ("apps", None, ("unknown",), (None,), ([],)):
            with self.subTest(scopes=scopes), self.assertRaises(ValueError):
                ActionPolicy(scopes)

        policy = ActionPolicy()
        for action in (
            AssistantAction(ActionType.OPEN_APP, target="editor", source=[]),
            AssistantAction(ActionType.OPEN_APP, target="editor", source="x" * 65),
            AssistantAction(ActionType.OPEN_APP, target="editor", reason=None),
            AssistantAction(ActionType.OPEN_APP, target="editor", confidence=True),
        ):
            with self.subTest(action=action):
                self.assertFalse(policy.check(action).allowed)

    def test_web_research_is_opt_in_and_never_model_routed(self):
        action = AssistantAction(ActionType.WEB_ANSWER, query="погода", source="local_parser")
        self.assertFalse(ActionPolicy().check(action).allowed)
        scopes = DEFAULT_SCOPES + ("web_research",)
        self.assertTrue(ActionPolicy(scopes).check(action).allowed)
        routed = AssistantAction(
            ActionType.WEB_ANSWER,
            query="погода",
            source="llm_router",
            confidence=1.0,
        )
        self.assertFalse(ActionPolicy(scopes).check(routed).allowed)

    def test_revoked_capabilities_block_every_mapped_action(self):
        policy = ActionPolicy(())
        for action_type in (ActionType.OPEN_APP, ActionType.CLOSE_APP, ActionType.OPEN_URL, ActionType.OPEN_FOLDER, ActionType.TYPE_TEXT, ActionType.WINDOW_CONTROL, ActionType.VPN_CONTROL, ActionType.MEDIA_CONTROL, ActionType.ROUTINE, ActionType.MEMORY_NOTE, ActionType.FILE_SEARCH, ActionType.FILE_OPEN, ActionType.FILE_READ, ActionType.FILE_QUESTION):
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

    def test_untrusted_sources_cannot_issue_scope_free_actions(self):
        for action_type in (
            ActionType.EXIT,
            ActionType.CLEAR_DIALOGUE,
            ActionType.BACKGROUND_CANCEL,
            ActionType.UNKNOWN,
        ):
            for source in ("document", "memory", "webpage", "plugin"):
                with self.subTest(action=action_type, source=source):
                    action = AssistantAction(action_type, source=source)
                    self.assertFalse(ActionPolicy().check(action).allowed)

    def test_open_file_requires_its_separate_user_grant_and_cannot_come_from_router(self):
        action = AssistantAction(ActionType.FILE_OPEN, query="report.pdf", source="local_parser")
        self.assertFalse(ActionPolicy(("files",)).check(action).allowed)
        self.assertTrue(ActionPolicy(("open_files",)).check(action).allowed)
        routed = AssistantAction(ActionType.FILE_OPEN, query="report.pdf", source="llm_router", confidence=1.0)
        self.assertFalse(ActionPolicy(("open_files",)).check(routed).allowed)

    def test_read_file_requires_its_separate_user_grant_and_cannot_come_from_router(self):
        action = AssistantAction(ActionType.FILE_READ, query="memo.txt", source="local_parser")
        self.assertFalse(ActionPolicy(("files", "open_files")).check(action).allowed)
        self.assertTrue(ActionPolicy(("read_files",)).check(action).allowed)
        routed = AssistantAction(ActionType.FILE_READ, query="memo.txt", source="llm_router", confidence=1.0)
        self.assertFalse(ActionPolicy(("read_files",)).check(routed).allowed)

    def test_file_question_requires_its_separate_user_grant_and_cannot_come_from_router(self):
        action = AssistantAction(ActionType.FILE_QUESTION, target="report.pdf", query="какие сроки")
        self.assertFalse(ActionPolicy(("read_files",)).check(action).allowed)
        self.assertTrue(ActionPolicy(("ask_files",)).check(action).allowed)
        routed = AssistantAction(ActionType.FILE_QUESTION, target="report.pdf", query="какие сроки", source="llm_router")
        self.assertFalse(ActionPolicy(("ask_files",)).check(routed).allowed)

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
