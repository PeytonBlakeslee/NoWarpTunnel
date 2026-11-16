# No Warp Tunnel: User Guide

[Back to the repository overview](../README.md)

**Contents:** [Install, upgrade or remove](#install-upgrade-or-remove) · [How it works](#how-it-works) · [Compatibility and limitations](#compatibility-and-limitations) · [Troubleshooting](#troubleshooting)

## Install, upgrade or remove

1. Confirm [PythonSDK and Willow2 Mod Manager](https://bl-sdk.github.io/willow2-mod-db/) load in Borderlands 2.
2. Exit the game. For an upgrade, back up `sdk_mods/NoWarpTunnel/` and your SDK settings, including `NoWarpTunnel.json` if present.
3. Remove any duplicate or older numbered installation. Keep a single `NoWarpTunnel/` folder.
4. Extract a verified **Player ZIP** so that `sdk_mods/NoWarpTunnel/__init__.py` is present. Do not use the GitHub-generated source archive.
5. Launch the game and enable **No Warp Tunnel** in the SDK Mods menu.

To **roll back**, exit the game and restore the backed-up mod folder and settings. To **uninstall**, disable the mod, close the game, and remove its folder. Do not replace saved settings with an empty file.

Existing `NoWarpTunnel.json` settings are preserved. The mod can migrate the legacy `4NoWarpTunnel.json` file when the newer file does not already exist.

## How it works

While enabled, the mod skips the local warp-tunnel presentation by adjusting the current Loader destination. It checks when that actor is created and again when loading finishes. It does not change destinations, saved characters, or game packages, and has no extra gameplay settings.

Disabling the mod does not necessarily undo a change to an already-loaded Loader actor; the engine may need to update or replace that actor.

## Compatibility and limitations

| Environment | Status |
| --- | --- |
| Windows Borderlands 2 | Intended Player release target |
| The Pre-Sequel | Experimental, not tested in-game |
| Co-op host/client travel | Not verified |
| Windows game through Proton/Wine | Not verified |
| Native Linux Borderlands 2 | Not supported by this Windows package |

An experimental code path is not evidence of compatibility. Do not rely on unverified co-op or TPS behavior.

## Troubleshooting

- **Mod not listed:** Check PythonSDK/Willow2 and confirm the folder is exactly `sdk_mods/NoWarpTunnel/`, not `sdk_mods/mod/NoWarpTunnel/` or a numbered duplicate.
- **Tunnel still appears or travel stalls:** Compare the same travel with the mod disabled. Record the maps, destination, and stage at which loading fails. The Loader counter can remain changed temporarily after disable.
- **Settings changed:** Exit the game and restore your settings backup. Check that only one mod installation is loaded.

[Report a problem](https://github.com/PeytonBlakeslee/NoWarpTunnel/issues) with the game, SDK and mod versions; solo/host/client role; exact reproduction steps; and a short relevant excerpt from `unrealsdk.log`. Remove personal paths, accounts, and unrelated information.
