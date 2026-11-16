"""NoWarpTunnel BUG-08: negative hook-ownership and SDK Enabled regressions.

The stub follows the installed modern SDK's add_hook/has_hook/remove_hook
boolean contract and mods_base's enable-before-callback ordering.
"""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_settings_migration import load_player_module


class HookOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.m, self.registered = load_player_module(Path(self.temp.name))
        self.key = self.m.ACTOR_HOOK_ID
        self.hooks = self.m.unrealsdk.hooks

    def test_normal_enable_disable_reenable(self):
        self.m.mod.enable()
        self.assertTrue(self.m.mod.is_enabled)
        self.assertTrue(self.m._actor_hook_owned)
        self.assertTrue(self.m._actor_hook_enabled)
        self.assertIs(self.registered[self.key], self.m._actor_post_begin_play)
        self.m.mod.disable(dont_update_setting=True)
        self.assertFalse(self.m.mod.is_enabled)
        self.assertFalse(self.registered)
        self.assertFalse(self.m._actor_hook_owned)
        self.m.mod.enable()
        self.assertIn(self.key, self.registered)
        self.assertEqual(self.m.mod.saved, [True, True])

    def test_preexisting_foreign_hook_is_never_adopted_or_removed(self):
        foreign = lambda *args: None
        self.registered[self.key] = foreign
        self.m.mod.enable()
        self.assertFalse(self.m.mod.is_enabled)
        self.assertFalse(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_enabled)
        self.assertIs(self.registered[self.key], foreign)
        self.assertEqual(self.m.mod.saved, [])
        self.m._on_disable()
        self.assertIs(self.registered[self.key], foreign)

    def test_false_add_from_foreign_race_cannot_be_claimed(self):
        foreign = lambda *args: None
        def raced_add(_target, _stage, hook_id, _callback):
            self.registered[hook_id] = foreign
            return False
        self.hooks.add_hook = raced_add
        self.m.mod.enable()
        # The mod may remain enabled using the separate loading-complete hook,
        # but an unwitnessed actor hook is not owned and must not be removed.
        self.assertTrue(self.m.mod.is_enabled)
        self.assertIs(self.registered[self.key], foreign)
        self.assertFalse(self.m._actor_hook_owned)
        self.assertTrue(self.m._actor_hook_provisional)
        self.assertFalse(self.m._actor_hook_uncertain)
        self.m.mod.disable(dont_update_setting=True)
        self.assertIs(self.registered[self.key], foreign)
        self.assertTrue(self.m._actor_hook_provisional)

    def test_sdk_false_after_append_requires_callback_witness(self):
        def append_and_false(_target, _stage, hook_id, callback):
            self.registered[hook_id] = callback
            return False
        self.hooks.add_hook = append_and_false
        self.m.mod.enable()
        self.assertTrue(self.m.mod.is_enabled)
        self.assertFalse(self.m._actor_hook_owned)
        self.assertTrue(self.m._actor_hook_provisional)
        original_callback = self.registered[self.key]
        original_callback(SimpleNamespace(Class=SimpleNamespace(Name="Other")),
                          None, None, None)
        self.assertTrue(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_provisional)
        self.m.mod.disable(dont_update_setting=True)
        self.assertNotIn(self.key, self.registered)

    def test_provisional_registration_survives_toggle_until_witness(self):
        additions = []
        def append_and_false(_target, _stage, hook_id, callback):
            additions.append(hook_id)
            self.registered[hook_id] = callback
            return False
        self.hooks.add_hook = append_and_false
        self.m.mod.enable()
        self.m.mod.disable(dont_update_setting=True)
        self.assertIn(self.key, self.registered)
        self.m.mod.enable()
        self.assertEqual(additions, [self.key])
        self.registered[self.key](
            SimpleNamespace(Class=SimpleNamespace(Name="Other")),
            None, None, None)
        self.m.mod.disable(dont_update_setting=True)
        self.assertNotIn(self.key, self.registered)

    def test_add_then_throw_is_inactive_until_own_callback_is_observed(self):
        def add_then_throw(_target, _stage, hook_id, callback):
            self.registered[hook_id] = callback
            raise RuntimeError("exception after SDK inserted callback")
        self.hooks.add_hook = add_then_throw
        self.m.mod.enable()
        self.assertFalse(self.m.mod.is_enabled)
        self.assertTrue(self.m._actor_hook_uncertain)
        self.assertFalse(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_enabled)
        original_callback = self.registered[self.key]
        self.m.mod.enable()  # Presence alone must not establish ownership.
        self.assertFalse(self.m.mod.is_enabled)
        self.assertIs(self.registered[self.key], original_callback)
        self.assertEqual(self.m.mod.saved, [])
        # A real SDK invocation of our callback provides positive evidence.
        actor = SimpleNamespace(Class=SimpleNamespace(Name="Other"))
        original_callback(actor, None, None, None)
        self.assertTrue(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_uncertain)
        self.assertFalse(self.m._actor_hook_enabled)
        self.m.mod.enable()
        self.assertTrue(self.m.mod.is_enabled)
        self.assertIs(self.registered[self.key], original_callback)
        self.m.mod.disable(dont_update_setting=True)
        self.assertNotIn(self.key, self.registered)

    def test_ambiguous_callback_can_be_retried_after_external_cleanup(self):
        def add_then_throw(_target, _stage, hook_id, callback):
            self.registered[hook_id] = callback
            raise RuntimeError("post-install failure")
        self.hooks.add_hook = add_then_throw
        self.m.mod.enable()
        self.assertTrue(self.m._actor_hook_uncertain)
        self.registered.pop(self.key)
        self.hooks.add_hook = lambda path, kind, ident, cb: (
            False if ident in self.registered
            else self.registered.__setitem__(ident, cb) is None)
        self.m.mod.enable()
        self.assertTrue(self.m.mod.is_enabled)
        self.assertTrue(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_uncertain)
        self.m.mod.disable(dont_update_setting=True)
        self.assertFalse(self.registered)

    def test_remove_exception_retains_ownership_and_inhibits_actor_writes(self):
        self.m.mod.enable()
        real_remove = self.hooks.remove_hook
        def fail_remove(*args):
            raise RuntimeError("remove failed before change")
        self.hooks.remove_hook = fail_remove
        with self.assertRaisesRegex(RuntimeError, "remove failed"):
            self.m.mod.disable(dont_update_setting=True)
        self.assertFalse(self.m.mod.is_enabled)
        self.assertFalse(self.m._actor_hook_enabled)
        self.assertTrue(self.m._actor_hook_owned)
        self.assertIn(self.key, self.registered)
        self.hooks.remove_hook = real_remove
        self.m._on_disable()  # Retry cleanup without making the mod active.
        self.assertFalse(self.registered)
        self.assertFalse(self.m._actor_hook_owned)

    def test_remove_false_with_live_hook_preserves_retry_ledger(self):
        self.m.mod.enable()
        actual_remove = self.hooks.remove_hook
        self.hooks.remove_hook = lambda *args: False
        with self.assertRaisesRegex(RuntimeError, "removal failed"):
            self.m.mod.disable(dont_update_setting=True)
        self.assertFalse(self.m._actor_hook_enabled)
        self.assertTrue(self.m._actor_hook_owned)
        self.hooks.remove_hook = actual_remove
        self.m._on_disable()
        self.assertFalse(self.registered)

    def test_foreign_replacement_after_successful_remove_is_not_removed(self):
        self.m.mod.enable()
        foreign = lambda *args: None
        def replace_on_remove(_target, _stage, hook_id):
            self.registered.pop(hook_id)
            self.registered[hook_id] = foreign
            return True
        self.hooks.remove_hook = replace_on_remove
        with self.assertRaisesRegex(RuntimeError, "replaced during removal"):
            self.m.mod.disable(dont_update_setting=True)
        self.assertFalse(self.m._actor_hook_owned)
        self.assertFalse(self.m._actor_hook_enabled)
        self.assertIs(self.registered[self.key], foreign)
        self.m._on_disable()
        self.assertIs(self.registered[self.key], foreign)

    def test_callback_repairs_canonical_actor_only_while_enabled(self):
        self.m.mod.enable()
        dest = SimpleNamespace(Class=SimpleNamespace(Name="HoldingAreaDestination"),
                               ExitPointsCounter=0,
                               _path_name=lambda: self.m.TARGET_PATH)
        unrelated = SimpleNamespace(Class=SimpleNamespace(Name="Other"))
        handler = self.registered[self.key]
        handler(unrelated, None, None, None)
        self.assertEqual(dest.ExitPointsCounter, 0)
        handler(dest, None, None, None)
        self.assertEqual(dest.ExitPointsCounter, self.m.TARGET_VALUE)
        dest.ExitPointsCounter = 5
        self.m.mod.disable(dont_update_setting=True)
        handler(dest, None, None, None)
        self.assertEqual(dest.ExitPointsCounter, 5)


if __name__ == "__main__":
    unittest.main()
