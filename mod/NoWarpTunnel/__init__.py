from __future__ import annotations

import os
from pathlib import Path
import tempfile

import unrealsdk
from mods_base import SETTINGS_DIR, Mod, build_mod, hook
from unrealsdk import logging
from unrealsdk.hooks import Type

TARGET_PATH = "Loader.TheWorld:PersistentLevel.HoldingAreaDestination_1"
TARGET_VALUE = -99

LOAD_EVENT = "WillowGame.WillowPlayerController:WillowClientDisableLoadingMovie"
ACTOR_SPAWN_EVENT = "Engine.Actor:PostBeginPlay"
ACTOR_HOOK_ID = "NoWarpTunnel:actor-created"
_actor_hook_owned = False
_actor_hook_enabled = False
# has_hook() cannot reveal callback identity. Registration that raises after
# changing SDK state stays inactive until our callback actually runs or the
# ambiguous ID is removed by its owner.
_actor_hook_uncertain = False
# False can mean a successful SDK 3.2.0 append or a foreign-ID race.
# Presence alone never proves which callback owns that ID.
_actor_hook_provisional = False


def _repair_target(target, reason: str) -> bool:
    """Set one resolved Loader transition counter and verify the write."""
    if target is None:
        return False

    try:
        current = int(target.ExitPointsCounter)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False

    if current == TARGET_VALUE:
        return True

    try:
        target.ExitPointsCounter = TARGET_VALUE
        if int(target.ExitPointsCounter) != TARGET_VALUE:
            raise ValueError("write did not persist")
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        logging.warning(f"No Warp Tunnel: failed to set ExitPointsCounter: {exc}")
        return False

    logging.info(
        "No Warp Tunnel: reset current Loader counter "
        f"({current} -> {TARGET_VALUE}, {reason})"
    )
    return True


def _repair(reason: str) -> bool:
    """Resolve and repair the current local Loader transition counter."""
    try:
        target = unrealsdk.find_object("HoldingAreaDestination", TARGET_PATH)
    except (RuntimeError, ValueError):
        return False
    return _repair_target(target, reason)



def _on_enable() -> None:
    # If the Loader destination already exists (for example after a hot reload),
    # repair it immediately. Otherwise PostBeginPlay will catch its creation.
    _set_actor_hook(True)
    _repair("enable")


def _actor_post_begin_play(obj, args, ret, func) -> None:
    """Repair the Loader destination as soon as it is created during map load.

    This is intentionally event-driven rather than per-frame polling.
    The global Actor hook is only busy while actors are being initialized; the
    fast class check exits immediately for unrelated actors.
    """
    global _actor_hook_owned, _actor_hook_uncertain, _actor_hook_provisional
    if _actor_hook_uncertain or _actor_hook_provisional:
        # Execution of *our* callback is positive evidence that an ambiguous
        # post-add exception installed it. ID presence alone is not.
        _actor_hook_owned = True
        _actor_hook_uncertain = False
        _actor_hook_provisional = False
    if not _actor_hook_enabled:
        return
    try:
        if str(obj.Class.Name) != "HoldingAreaDestination":
            return
    except (AttributeError, RuntimeError):
        return

    # Only the canonical Loader destination controls the tunnel. A matching
    # class alone is insufficient; validate the callback's exact path.
    try:
        if obj._path_name() != TARGET_PATH:
            return
    except (AttributeError, RuntimeError, ValueError):
        return
    _repair_target(obj, "PostBeginPlay")


@hook(LOAD_EVENT, Type.POST)
def _loaded(obj, args, ret, func) -> None:
    # Entirely local/offline: no SHiFT, hotfix, network or matchmaking dependency.
    _repair("loading complete")


def _on_disable() -> None:
    _set_actor_hook(False)


def _set_actor_hook(enabled: bool) -> None:
    """Only remove a proven-owned callback; fail closed on uncertain SDK state."""
    global _actor_hook_owned, _actor_hook_enabled, _actor_hook_uncertain, _actor_hook_provisional
    spec = (ACTOR_SPAWN_EVENT, Type.POST, ACTOR_HOOK_ID)
    if not enabled:
        # Disable callbacks before attempting any potentially failing cleanup.
        _actor_hook_enabled = False

    current = bool(unrealsdk.hooks.has_hook(*spec))
    if not current:
        # The old callback is absent, so both prior ownership and any uncertain
        # registration are retired. The next enable may safely try a new add.
        _actor_hook_owned = False
        _actor_hook_uncertain = False
        _actor_hook_provisional = False
    if enabled:
        if _actor_hook_uncertain:
            raise RuntimeError(
                "No Warp Tunnel: actor hook registration uncertain; "
                "wait for a hook callback or restart the game"
            )
        if not _actor_hook_owned:
            if current:
                if not _actor_hook_provisional:
                    raise RuntimeError(
                        "No Warp Tunnel: actor hook ID already in use by another callback"
                    )
                # A prior add(False) may have registered our callback. Reuse its
                # inert/identity-unproven registration until it is invoked.
                _actor_hook_enabled = True
                return
            try:
                added = unrealsdk.hooks.add_hook(*spec, _actor_post_begin_play)
            except Exception as exc:
                # The SDK may have registered our callback and then raised.
                # ID presence cannot distinguish our callback from a foreign
                # replacement, so leave it inert rather than removing it.
                try:
                    _actor_hook_uncertain = bool(unrealsdk.hooks.has_hook(*spec))
                except Exception:
                    _actor_hook_uncertain = True
                raise RuntimeError("No Warp Tunnel: actor hook addition failed") from exc
            if added is not True:
                # Native UnrealSDK 3.2.0 can append to an existing hook list
                # and incorrectly return False. Presence proves existence,
                # not identity: don't remove it until our callback runs.
                try:
                    present = bool(unrealsdk.hooks.has_hook(*spec))
                except Exception:
                    _actor_hook_uncertain = True
                    raise
                if not present:
                    raise RuntimeError("No Warp Tunnel: actor hook addition was rejected")
                _actor_hook_provisional = True
                _actor_hook_enabled = True
                return
            # SDK confirmed a successful add, so retain ownership even if a
            # subsequent presence check raises and startup must be rolled back.
            _actor_hook_owned = True
            if not unrealsdk.hooks.has_hook(*spec):
                _actor_hook_owned = False
                raise RuntimeError("No Warp Tunnel: actor hook disappeared after addition")
        _actor_hook_enabled = True
        return

    if not _actor_hook_owned:
        return  # Foreign, provisional and post-add uncertain IDs are never removed.
    if not current:
        _actor_hook_owned = False
        return
    try:
        removed = unrealsdk.hooks.remove_hook(*spec)
    except Exception:
        # Keep confirmed ownership for a later cleanup attempt. Do not turn
        # callback handling back on while removal is unresolved.
        if not unrealsdk.hooks.has_hook(*spec):
            _actor_hook_owned = False
        raise
    still_present = bool(unrealsdk.hooks.has_hook(*spec))
    if still_present:
        if removed is True:
            # Our callback was removed and another writer took the ID.
            _actor_hook_owned = False
            raise RuntimeError("No Warp Tunnel: hook ID replaced during removal")
        # A failed removal could leave our callback installed. Retain its
        # ledger and try again during a later explicit disable/reload.
        raise RuntimeError("No Warp Tunnel: actor hook removal failed")
    _actor_hook_owned = False



# Preserve the historic settings filename without overwriting current preferences.
def migrate_settings(settings_dir):
    folder = Path(settings_dir)
    old = folder / "4NoWarpTunnel.json"
    new = folder / "NoWarpTunnel.json"
    if new.exists() or not old.is_file():
        return
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".NoWarpTunnel.", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(old.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        if not new.exists():
            os.replace(temp, new)
            temp = None
    except OSError:
        # A missing/unwritable settings directory must not prevent the mod from loading.
        pass
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

migrate_settings(SETTINGS_DIR)


class NoWarpTunnelMod(Mod):
    def enable(self) -> None:
        """Keep mods_base Enabled aligned with the active actor-hook lifecycle."""
        try:
            super().enable()
        except Exception as exc:
            logging.warning(f"No Warp Tunnel: enable failed: {type(exc).__name__}: {exc}")
            if self.is_enabled:
                try:
                    # SDK sets Enabled before invoking on_enable. Preserve the
                    # saved auto-enable preference when rolling back a failure.
                    self.disable(dont_update_setting=True)
                except Exception as cleanup_exc:
                    logging.warning(
                        f"No Warp Tunnel: activation cleanup failed: "
                        f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                    )


mod = build_mod(cls=NoWarpTunnelMod, settings_file=SETTINGS_DIR / "NoWarpTunnel.json",
                on_enable=_on_enable, on_disable=_on_disable)
