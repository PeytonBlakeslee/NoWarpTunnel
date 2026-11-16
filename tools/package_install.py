"""Build reproducible, private BL2 SDK installation ZIPs (no release publishing)."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MOD = "NoWarpTunnel"
SOURCE = ROOT / "mod" / MOD
IGNORED_PARTS = {"__pycache__", ".git", ".pytest_cache", "reports", "tests", "fixtures", "benchmarks"}
ALLOWED_SUFFIXES = {".py", ".toml", ".md", ".txt", ""}
DEV_MODULES = {"_fpstester_bridge.py", "profiler.py", "profiling.py", "native_capture.py", "_fpstester_native_upgrade.py"}
DATE = (2020, 1, 1, 0, 0, 0)
# Exact installable player files. Any new runtime module requires an explicit review.
PLAYER_FILES = frozenset({
    "__init__.py",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_version() -> str:
    project = SOURCE / "pyproject.toml"
    if project.is_file():
        version = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    else:
        tree = ast.parse((SOURCE / "__init__.py").read_text(encoding="utf-8"))
        assignments = [node for node in tree.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)]
        if len(assignments) != 1:
            raise ValueError("Expected one static __version__ in mod/__init__.py")
        version = ast.literal_eval(assignments[0].value)
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+-]*", version):
        raise ValueError("Unexpected mod version")
    if "profiler" in version.lower() or "debug" in version.lower():
        raise ValueError("Developer-only version suffix; resolve before install packaging")
    return version


def source_commit() -> str:
    commit = os.environ.get("GITHUB_SHA")
    if commit is None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
        raise ValueError("A 40-character source commit is required")
    return commit.lower()


def gather(flavor: str) -> dict[str, bytes]:
    if not SOURCE.is_dir():
        raise FileNotFoundError(SOURCE)
    files: dict[str, bytes] = {}
    for source in sorted(SOURCE.rglob("*")):
        if source.is_symlink():
            raise ValueError(f"Symlink not allowed: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(SOURCE)
        if any(part in IGNORED_PARTS for part in relative.parts) or source.suffix in {".pyc", ".pyo"}:
            continue
        if source.suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"Unexpected installer file: {relative}")
        if flavor == "player" and source.name in DEV_MODULES:
            raise ValueError(f"Player folder includes developer module: {relative}")
        if flavor == "player" and relative.as_posix() not in PLAYER_FILES:
            raise ValueError(f"Unreviewed player install file: {relative}")
        data = source.read_bytes()
        if source.suffix == ".py":
            compile(data, str(source), "exec")
        files[f"{MOD}/{relative.as_posix()}"] = data

    # Legal files are maintained at the repository root and installed by the packager.
    for legal_name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        legal_source = ROOT / legal_name
        if not legal_source.is_file():
            raise FileNotFoundError(legal_source)
        files[f"{MOD}/{legal_name}"] = legal_source.read_bytes()

    if flavor == "player":
        actual = {name.split("/", 1)[1] for name in files}
        if actual != PLAYER_FILES:
            raise ValueError(f"Player file catalog mismatch: missing={sorted(PLAYER_FILES - actual)}, extra={sorted(actual - PLAYER_FILES)}")
    for required in ("__init__.py", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        if f"{MOD}/{required}" not in files:
            raise ValueError(f"Missing required mod file: {required}")
    bridge = f"{MOD}/_fpstester_bridge.py"
    imports_bridge = b"_fpstester_bridge" in files[f"{MOD}/__init__.py"]
    if flavor == "player":
        if bridge in files or imports_bridge:
            raise ValueError("Player installation contains FPS Tester integration")
    elif bridge in files:
        # Developer profiling is optional. If present, require a working
        # import path and instructions; do not package a stranded bridge.
        if not imports_bridge:
            raise ValueError("Developer FPS Tester bridge is not wired into the mod")
        doc = ROOT / "docs" / "DEVELOPER_TESTING.md"
        if not doc.is_file():
            raise ValueError("Developer testing instructions missing")
        files[f"{MOD}/DEVELOPER_TESTING.md"] = doc.read_bytes()
    elif imports_bridge:
        raise ValueError("Developer runtime references a missing FPS Tester bridge")
    return files


def make_zip(output: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            segments = name.split("/")
            if (not name or name.startswith("/") or "\\" in name or ":" in name
                    or "\x00" in name or len(segments) < 2 or segments[0] != MOD
                    or any(part in ("", ".", "..") for part in segments)):
                raise ValueError(f"Unsafe ZIP entry: {name!r}")
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or len(set(archive.namelist())) != len(files):
            raise AssertionError("ZIP validation failed")
        if sorted(archive.namelist()) != sorted(files):
            raise AssertionError("ZIP entry mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flavor", choices=("player", "developer"), required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--private-candidate", action="store_true", help="Build the protected release-candidate Player package")
    args = parser.parse_args()
    expected = "main" if args.flavor == "player" else "testing"
    ref = os.environ.get("GITHUB_REF_NAME") or subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    if args.private_candidate:
        if args.flavor != "player" or ref != "release-candidate":
            raise ValueError("Private candidate is limited to the release-candidate Player branch")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
            raise ValueError("Private candidate requires a clean source checkout")
        expected = ref
    elif ref != expected:
        raise ValueError(f"{args.flavor} packages must come from {expected}, not {ref}")
    version = get_version()
    if args.flavor == "player":
        project = SOURCE / "pyproject.toml"
        if project.is_file():
            package = tomllib.loads(project.read_text(encoding="utf-8"))
            declared = [package.get("project", {}).get("version"),
                        package.get("tool", {}).get("sdkmod", {}).get("version")]
            if any(item is not None and item != version for item in declared):
                raise ValueError("Package metadata versions disagree")
        # The repository homepage is version-neutral; the installed guide stays versioned.
        player_readme = SOURCE / "README.md"
        if version not in player_readme.read_text(encoding="utf-8"):
            raise ValueError(f"Player documentation version does not match {version}: {player_readme}")
    commit = source_commit()
    files = gather(args.flavor)
    metadata = {
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "workflow_file": ".github/workflows/package-install.yml",
        "workflow_run": (
            f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            if os.environ.get("GITHUB_REPOSITORY") and os.environ.get("GITHUB_RUN_ID") else None),
        "mod": MOD, "version": version, "flavor": args.flavor,
        "source_branch": expected, "source_commit": commit,
        "supported_games": ["BL2", "TPS (experimental; not gameplay-certified)"],
        "coop_scope": "Local-only travel presentation; co-op transitions unverified",
        "dependencies": {"required": ["PythonSDK", "Willow2 Mod Manager"], "optional": []},
        "native_backend": "not required",
        "developer_tool_files": (
            sorted(name for name in files if name.endswith("/_fpstester_bridge.py")
                   or f"/_devtools/" in name)
            if args.flavor == "developer" else []
        ),
        "status": "UNVERIFIED: pending in-game acceptance; not a published release",
        "install_path": f"Borderlands 2/sdk_mods/{MOD}/",
    }
    # Release provenance belongs in the adjacent manifest, not sdk_mods/<Mod>/.
    args.output.mkdir(parents=True, exist_ok=True)
    basename = f"{MOD}-v{version}-{'Player' if args.flavor == 'player' else 'Developer'}"
    archive = args.output / f"{basename}.zip"
    if archive.exists():
        raise FileExistsError(f"Will not overwrite existing package: {archive}")
    make_zip(archive, files)
    manifest = {
        **metadata, "archive": archive.name, "archive_sha256": sha256(archive.read_bytes()),
        "entries": [{"path": name, "bytes": len(data), "sha256": sha256(data)}
                    for name, data in sorted(files.items())],
    }
    (args.output / f"{basename}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (args.output / f"{basename}.sha256").write_text(f"{manifest['archive_sha256']}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "archive": archive.name, "files": len(files),
                      "sha256": manifest["archive_sha256"], "source_commit": commit}, indent=2))


if __name__ == "__main__":
    main()
