"""Offline smoke tests for the No Warp Tunnel player runtime and legacy settings."""
from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'mod' / 'NoWarpTunnel' / '__init__.py'


class FakeMod:
    """Subset of mods_base's documented enable/disable ordering."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.is_enabled = False
        self.saved = []

    def enable(self):
        if self.is_enabled:
            return
        self.is_enabled = True
        self.on_enable()
        self.saved.append(True)

    def disable(self, dont_update_setting=False):
        if not self.is_enabled:
            return
        self.is_enabled = False
        self.on_disable()
        if not dont_update_setting:
            self.saved.append(False)


def load_player_module(settings_dir):
    owned_hooks = {}
    sdk = types.ModuleType('unrealsdk')
    sdk.logging = logging
    sdk.find_object = lambda *args: None
    sdk.hooks = types.SimpleNamespace(
        Type=types.SimpleNamespace(POST='POST'),
        has_hook=lambda _target, _type, hook_id: hook_id in owned_hooks,
        add_hook=lambda _target, _type, hook_id, callback: (
            False if hook_id in owned_hooks
            else owned_hooks.__setitem__(hook_id, callback) is None),
        remove_hook=lambda _target, _type, hook_id: (
            owned_hooks.pop(hook_id, None) is not None),
    )
    sdk_hooks = types.ModuleType('unrealsdk.hooks')
    sdk_hooks.Type = sdk.hooks.Type
    mods = types.ModuleType('mods_base')
    mods.SETTINGS_DIR = settings_dir
    mods.Mod = FakeMod
    mods.build_mod = lambda cls=FakeMod, **kwargs: cls(**kwargs)
    mods.hook = lambda *args, **kwargs: lambda callback: callback
    with patch.dict(sys.modules, {
        'unrealsdk': sdk, 'unrealsdk.hooks': sdk_hooks, 'mods_base': mods
    }):
        spec = importlib.util.spec_from_file_location('nwt_player_smoke', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, owned_hooks

class LegacySettingsTests(unittest.TestCase):
    def test_legacy_migration_preserves_old_and_copies_to_new(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            legacy = root / '4NoWarpTunnel.json'
            legacy.write_bytes(b'{"test":"legacy"}')
            runtime, hooks = load_player_module(root)
            self.assertEqual((root / 'NoWarpTunnel.json').read_bytes(), legacy.read_bytes())
            self.assertEqual(legacy.read_bytes(), b'{"test":"legacy"}')
            self.assertEqual(list(root.glob('*.tmp')), [])
            self.assertEqual(runtime.mod.settings_file, root / 'NoWarpTunnel.json')
            runtime._on_enable()
            self.assertEqual(len(hooks), 1)
            runtime._on_disable()
            self.assertFalse(hooks)

    def test_modern_settings_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '4NoWarpTunnel.json').write_text('legacy')
            (root / 'NoWarpTunnel.json').write_text('modern')
            load_player_module(root)
            self.assertEqual((root / 'NoWarpTunnel.json').read_text(), 'modern')
            self.assertEqual((root / '4NoWarpTunnel.json').read_text(), 'legacy')

    def test_missing_legacy_file_does_not_create_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            load_player_module(root)
            self.assertFalse((root / 'NoWarpTunnel.json').exists())


if __name__ == '__main__':
    unittest.main()
