"""Install and inspect the user-owned CleanHouse LaunchAgent.

The LaunchAgent owns the long-lived supervisor process.  The launcher may exit
without taking the local service down, and launchd can restart the supervisor
if it terminates unexpectedly.  This module never requests administrator
privileges; it only manages the current user's LaunchAgents domain.
"""

from __future__ import annotations

import ast
import argparse
import hashlib
import ipaddress
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from backend import auth_runtime_config


LABEL = "org.cleanhouse.runtime"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3333
STAGED_RUNTIME_NAME = "launchagent-runtime"
RUNTIME_DIRECTORIES = ("backend", "corefiles", "frontend", "models", "access_control", "assets")
RUNTIME_FILES: tuple[str, ...] = ()
RUNTIME_INDEX_PREFIXES = (*RUNTIME_DIRECTORIES, "config/auth-runtime.json", "docs/legal", "bundled/wazuh/darwin-arm64", "bundled/wireshark/darwin-arm64")
WIRESHARK_RUNTIME_ROOT = Path("bundled/wireshark/darwin-arm64")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entry_record(app_root: Path, relative: str) -> dict[str, Any]:
    path = app_root / relative
    if path.is_symlink():
        target = os.readlink(path)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(app_root.resolve(strict=True))
        except ValueError as exc:
            raise ValueError(f"runtime payload symlink escapes app root: {relative}") from exc
        marker = hashlib.sha256()
        marker.update(b"symlink\0" + target.encode("utf-8") + b"\0")
        if resolved.is_file():
            marker.update(bytes.fromhex(_sha256(resolved)))
            kind = "symlink"
        elif resolved.is_dir():
            marker.update(bytes.fromhex(_bounded_tree_sha256(resolved)))
            kind = "symlink-directory"
        else:
            raise ValueError(f"runtime payload symlink target is unsupported: {relative}")
        return {"kind": kind, "target": target, "sha256": marker.hexdigest()}
    if not path.is_file():
        raise ValueError(f"runtime payload entry is not a regular file: {relative}")
    return {"kind": "file", "sha256": _sha256(path)}


def _write_release_manifest(
    release_root: Path,
    indexed_payload: tuple[str, ...],
    index_records: dict[str, dict[str, Any]] | None,
    *,
    origin: str,
    write: bool = True,
) -> dict[str, Any]:
    app_root = release_root / "app"
    actual_paths = _bounded_payload_paths(app_root)
    if set(actual_paths) != set(indexed_payload):
        missing = sorted(set(indexed_payload) - set(actual_paths))[:5]
        extra = sorted(set(actual_paths) - set(indexed_payload))[:5]
        raise ValueError(f"release payload path mismatch; missing={missing!r} extra={extra!r}")
    indexed = {path: _entry_record(app_root, path) for path in indexed_payload}
    if set(indexed) != set(indexed_payload):
        raise ValueError("release manifest does not exactly cover indexed runtime payload")
    derived = {"backend/keychain-helper": _entry_record(app_root, "backend/keychain-helper")}
    manifest = {
        "schema": "cleanhouse.launchagent-release.v1",
        "origin": origin,
        "indexed_payload": indexed,
        "index_records": index_records,
        "derived_payload": derived,
        "plist_sha256": None,
    }
    if write:
        (release_root / "release-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return manifest


def _bounded_payload_paths(app_root: Path, *, max_entries: int = 20000) -> tuple[str, ...]:
    paths: list[str] = []
    for directory, names, filenames in os.walk(app_root, followlinks=False):
        names.sort()
        filenames.sort()
        base = Path(directory)
        for name in tuple(names):
            path = base / name
            if path.is_symlink():
                paths.append(path.relative_to(app_root).as_posix())
        for name in filenames:
            path = base / name
            relative = path.relative_to(app_root).as_posix()
            if relative != "backend/keychain-helper":
                paths.append(relative)
        if len(paths) > max_entries:
            raise ValueError(f"legacy runtime payload exceeds {max_entries} entries")
    if not paths:
        raise ValueError("legacy runtime payload is empty")
    return tuple(paths)


def _snapshot_prior_release(current: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    manifest_path = current / "release-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        indexed = manifest.get("indexed_payload")
        if not isinstance(indexed, dict) or not indexed:
            raise ValueError("prior release manifest has no indexed payload")
        paths = tuple(indexed)
        if set(paths) != set(indexed):
            raise ValueError("prior release manifest paths are inconsistent")
        return manifest, paths
    paths = _bounded_payload_paths(current / "app")
    manifest = _write_release_manifest(
        current, paths, None, origin="retained-prior-legacy-snapshot", write=False
    )
    return manifest, paths


def _launch_contract_from_plist(payload: bytes) -> dict[str, Any]:
    definition = plistlib.loads(payload)
    arguments = definition.get("ProgramArguments")
    if not isinstance(arguments, list) or len(arguments) != 8 or arguments[1:4] != [
        "-m", "backend.runtime_supervisor", "supervise",
    ] or arguments[4] != "--host" or arguments[6] != "--port":
        raise ValueError("LaunchAgent ProgramArguments do not match the canonical supervisor contract")
    interpreter = Path(str(arguments[0]))
    working_directory = Path(str(definition.get("WorkingDirectory") or ""))
    host = str(arguments[5])
    try:
        port = int(arguments[7])
        loopback = ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        loopback = False
        port = 0
    if (
        not interpreter.is_absolute()
        or not working_directory.is_absolute()
        or not loopback
        or not 1 <= port <= 65535
    ):
        raise ValueError("LaunchAgent runtime identity must use absolute paths and a loopback endpoint")
    return {
        "interpreter": str(interpreter),
        "host": host,
        "port": port,
        "working_directory": str(working_directory),
        "arguments": [str(value) for value in arguments],
    }


def _bind_release_plists(staged: dict[str, Any], payload: bytes, prior_payload: bytes | None) -> None:
    for key, release, plist_bytes in (
        ("release_manifest_sha256", Path(staged["root"]), payload),
        ("prior_release_manifest_sha256", Path(staged["previous"]), prior_payload)
        if staged.get("previous") else ("prior_release_manifest_sha256", None, None),
    ):
        if release is None or plist_bytes is None:
            continue
        manifest_path = release / "release-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["plist_sha256"] = hashlib.sha256(plist_bytes).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staged[key] = _sha256(manifest_path)
        contract_key = "release_launch_contract" if key == "release_manifest_sha256" else "prior_launch_contract"
        staged[contract_key] = _launch_contract_from_plist(plist_bytes)


def _verify_release_manifest(
    release_root: Path,
    expected_paths: tuple[str, ...],
    plist_bytes: bytes,
    expected_manifest_sha256: str,
) -> bool:
    try:
        manifest_path = release_root / "release-manifest.json"
        if _sha256(manifest_path) != expected_manifest_sha256:
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        indexed = manifest.get("indexed_payload")
        index_records = manifest.get("index_records")
        derived = manifest.get("derived_payload")
        if (
            manifest.get("schema") != "cleanhouse.launchagent-release.v1"
            or not isinstance(indexed, dict)
            or set(indexed) != set(expected_paths)
            or (
                manifest.get("origin") == "git-index"
                and (not isinstance(index_records, dict) or set(index_records) != set(expected_paths))
            )
            or (
                isinstance(manifest.get("origin"), str)
                and manifest["origin"].startswith("retained-prior")
                and index_records is not None
            )
            or not isinstance(derived, dict)
            or set(derived) != {"backend/keychain-helper"}
            or manifest.get("plist_sha256") != hashlib.sha256(plist_bytes).hexdigest()
        ):
            return False
        app_root = release_root / "app"
        if set(_bounded_payload_paths(app_root)) != set(expected_paths):
            return False
        return all(_entry_record(app_root, path) == record for path, record in indexed.items()) and all(
            _entry_record(app_root, path) == record for path, record in derived.items()
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _launchd_process_observation() -> dict[str, Any]:
    result = _run_launchctl(["print", f"{gui_domain()}/{LABEL}"])
    if result.returncode != 0:
        return {"loaded": False}
    output = result.stdout
    pid_match = re.search(r"(?m)^\s*pid = (\d+)\s*$", output)
    program_match = re.search(r"(?m)^\s*program = (.+?)\s*$", output)
    cwd_match = re.search(r"(?m)^\s*working directory = (.+?)\s*$", output)
    arguments_match = re.search(r"(?ms)^\s*arguments = \{\s*(.*?)^\s*\}\s*$", output)
    arguments = []
    if arguments_match:
        arguments = [line.strip() for line in arguments_match.group(1).splitlines() if line.strip()]
    return {
        "loaded": True,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "program": program_match.group(1) if program_match else "",
        "working_directory": cwd_match.group(1) if cwd_match else "",
        "arguments": arguments,
    }


def _process_observation(pid: Any) -> dict[str, Any]:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return {}
    process = subprocess.run(
        ["ps", "-p", str(value), "-o", "ppid=,command="],
        text=True, capture_output=True, check=False, timeout=5,
    )
    cwd = subprocess.run(
        ["lsof", "-a", "-p", str(value), "-d", "cwd", "-Fn"],
        text=True, capture_output=True, check=False, timeout=5,
    )
    line = process.stdout.strip()
    match = re.match(r"\s*(\d+)\s+(.+)", line)
    cwd_line = next((item[1:] for item in cwd.stdout.splitlines() if item.startswith("n")), "")
    return {
        "pid": value,
        "ppid": int(match.group(1)) if match else None,
        "command": match.group(2) if match else "",
        "working_directory": cwd_line,
    }


def _canonical_readiness_matches(payload: dict[str, Any], state: dict[str, Any]) -> bool:
    required_checks = {
        "runtime_healthy", "startup_warm", "backend_alive", "supervisor_alive",
        "heartbeat_fresh", "readiness_probe_ok", "single_owned_listener",
        "listener_matches_backend", "no_foreign_listener", "no_self_deviation_block",
        "no_resource_guard_block",
    }
    contract = payload.get("readiness_contract")
    checks = contract.get("checks") if isinstance(contract, dict) else None
    backend = payload.get("backend") if isinstance(payload.get("backend"), dict) else {}
    supervisor = payload.get("supervisor") if isinstance(payload.get("supervisor"), dict) else {}
    listener = payload.get("listener") if isinstance(payload.get("listener"), dict) else {}
    return bool(
        payload.get("ready") is True
        and payload.get("bootstrap_ready") is True
        and payload.get("runtime_state") == "healthy"
        and isinstance(contract, dict)
        and contract.get("schema") == "cleanhouse.runtime_operator_readiness.v1"
        and contract.get("satisfied") is True
        and contract.get("required_runtime_state") == "healthy"
        and contract.get("required_startup_phases") == ["warm"]
        and isinstance(checks, dict)
        and set(checks) == required_checks
        and all(checks.get(name) is True for name in required_checks)
        and contract.get("failed_checks") == []
        and backend.get("pid") == state.get("backend_pid")
        and backend.get("boot_id") == state.get("backend_boot_id")
        and supervisor.get("pid") == state.get("supervisor_pid")
        and supervisor.get("boot_id") == state.get("boot_id")
        and listener.get("owned_pids") == state.get("owned_listener_pids")
        and listener.get("foreign_pids") == state.get("foreign_listener_pids")
    )


def _processes_match_release(
    staged: dict[str, Any], state: dict[str, Any], contract: dict[str, Any]
) -> bool:
    repo_root = str(Path(staged["repo_root"]).resolve())
    launchd = _launchd_process_observation()
    supervisor = _process_observation(state.get("supervisor_pid"))
    backend = _process_observation(state.get("backend_pid"))
    expected_interpreter = str(Path(str(contract["interpreter"])).resolve())
    expected_arguments = contract["arguments"]
    return bool(
        launchd.get("loaded") is True
        and launchd.get("pid") == state.get("supervisor_pid")
        and Path(str(launchd.get("program") or "")).resolve() == Path(expected_interpreter)
        and str(Path(str(launchd.get("working_directory") or "")).resolve()) == repo_root
        and launchd.get("arguments") == expected_arguments
        and supervisor.get("working_directory") == repo_root
        and "backend.runtime_supervisor" in str(supervisor.get("command") or "")
        and backend.get("ppid") == state.get("supervisor_pid")
        and backend.get("working_directory") == repo_root
        and str(Path(repo_root) / "backend" / "server.py") in str(backend.get("command") or "")
    )


def _readiness_payload(host: str, port: int) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(f"http://{host}:{port}/cleanhouse/status?ready=1", timeout=2) as response:
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("readiness response exceeded 65536 bytes")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("readiness response must be an object")
        return response.status, payload


def _bounded_tree_sha256(root: Path, *, max_files: int = 4096, max_bytes: int = 2 * 1024**3) -> str:
    """Hash one declared vendor subtree with explicit traversal bounds."""
    digest = hashlib.sha256()
    files = 0
    total_bytes = 0
    for directory, names, filenames in os.walk(root, followlinks=False):
        names.sort()
        filenames.sort()
        base = Path(directory)
        for name in tuple(names):
            path = base / name
            if not path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix().encode("utf-8")
            files += 1
            if files > max_files:
                raise ValueError(f"vendor subtree exceeds {max_files} files")
            target = os.readlink(path).encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big") + relative)
            digest.update(b"L" + len(target).to_bytes(4, "big") + target)
        for name in filenames:
            path = base / name
            relative = path.relative_to(root).as_posix().encode("utf-8")
            files += 1
            if files > max_files:
                raise ValueError(f"vendor subtree exceeds {max_files} files")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            if path.is_symlink():
                target = os.readlink(path).encode("utf-8")
                digest.update(b"L" + len(target).to_bytes(4, "big") + target)
                continue
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > max_bytes:
                raise ValueError(f"vendor subtree exceeds {max_bytes} bytes")
            digest.update(b"F" + size.to_bytes(8, "big"))
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def _validate_wireshark_runtime(app_root: Path) -> None:
    root = app_root / WIRESHARK_RUNTIME_ROOT
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    closure = manifest.get("runtime_closure")
    if not isinstance(closure, dict) or not closure:
        raise ValueError("Wireshark manifest is missing runtime_closure")
    for relative, expected in closure.items():
        if not isinstance(relative, str) or not isinstance(expected, dict):
            raise ValueError("invalid Wireshark runtime closure entry")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Wireshark runtime closure path escapes its root")
        expected_hash = expected.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError("invalid Wireshark runtime closure hash")
        path = root / relative
        if path.is_dir():
            actual = _bounded_tree_sha256(path)
        elif path.is_file():
            actual = _sha256(path)
        else:
            raise FileNotFoundError(path)
        if actual != expected_hash:
            raise ValueError(f"Wireshark runtime closure hash mismatch: {relative}")


def _wireshark_git_closure(app_root: Path) -> tuple[str, ...]:
    _validate_wireshark_runtime(app_root)
    root = app_root / WIRESHARK_RUNTIME_ROOT
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    paths = [str(WIRESHARK_RUNTIME_ROOT / "manifest.json")]
    for relative in manifest["runtime_closure"]:
        path = root / relative
        if path.is_dir():
            paths.extend(
                str(WIRESHARK_RUNTIME_ROOT / relative / nested)
                for nested in _bounded_payload_paths(path)
            )
        else:
            paths.append(str(WIRESHARK_RUNTIME_ROOT / relative))
    if len(paths) != len(set(paths)):
        raise ValueError("Wireshark runtime closure contains duplicate Git paths")
    return tuple(sorted(paths))


def _installed_keychain_helper() -> Path:
    return auth_runtime_config.INSTALLED_KEYCHAIN_HELPER


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return launch_agents_dir() / f"{LABEL}.plist"


def gui_domain() -> str:
    return f"gui/{os.getuid()}"


def _runtime_dir() -> Path:
    configured = os.getenv("CLEANHOUSE_RUNTIME_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cleanhouse" / "runtime"


def staged_runtime_root() -> Path:
    return _runtime_dir() / STAGED_RUNTIME_NAME


def _copy_runtime_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _materialize_index_runtime(source_repo: Path, destination: Path) -> tuple[str, ...]:
    """Export only declared runtime payload from the Git index."""
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=source_repo, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    if Path(root).resolve() != source_repo:
        raise ValueError("runtime source must be the exact Git worktree root")
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *RUNTIME_INDEX_PREFIXES, *RUNTIME_FILES],
        cwd=source_repo, capture_output=True, check=True,
    ).stdout
    paths = tuple(item.decode("utf-8") for item in listed.split(b"\0") if item)
    if not paths:
        raise ValueError("Git index contains no declared runtime payload")
    prefix = os.fspath(destination) + os.sep
    subprocess.run(
        ["git", "checkout-index", "--prefix", prefix, "--stdin", "-z"],
        cwd=source_repo, input=listed, check=True,
    )
    return paths


def _validate_staged_runtime_contract(app_root: Path) -> None:
    """Reject a staged server/supervisor pair with a known incompatible seam."""
    server_path = app_root / "backend" / "server.py"
    supervisor_path = app_root / "backend" / "runtime_supervisor.py"
    if not server_path.is_file() or not supervisor_path.is_file():
        return
    server_tree = ast.parse(server_path.read_text(encoding="utf-8"), filename=str(server_path))
    supervisor_tree = ast.parse(supervisor_path.read_text(encoding="utf-8"), filename=str(supervisor_path))
    required = {
        node.attr
        for node in ast.walk(server_tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "runtime_supervisor"
        and node.attr == "_start_isolated_runtime"
    }
    provided = {
        node.name
        for node in supervisor_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(required - provided)
    if missing:
        raise ValueError(f"staged runtime contract mismatch: missing {', '.join(missing)}")


def stage_runtime(interpreter: str, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Create an atomic launchd-readable runtime outside protected folders."""
    source_repo = repo_root.expanduser().resolve(strict=True)
    expanded_interpreter = Path(interpreter).expanduser()
    source_interpreter = Path(os.path.abspath(os.fspath(expanded_interpreter)))
    if not source_interpreter.exists():
        raise FileNotFoundError(source_interpreter)

    root = staged_runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".release-", dir=str(root)))
    app_root = temporary / "app"
    app_root.mkdir(parents=True)
    try:
        indexed_payload = _materialize_index_runtime(source_repo, app_root)
        index_records = {path: _entry_record(app_root, path) for path in indexed_payload}
        _validate_staged_runtime_contract(app_root)
        _validate_wireshark_runtime(app_root)
        for name in ("backend", "corefiles", "frontend", "models", "access_control"):
            if not (app_root / name).is_dir():
                raise FileNotFoundError(app_root / name)

        public_auth = auth_runtime_config.staged_public_contract(app_root)
        auth_config_path = app_root / "config" / "auth-runtime.json"
        auth_config_path.parent.mkdir(parents=True, exist_ok=True)
        auth_config_path.write_text(
            json.dumps(public_auth, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(auth_config_path, 0o600)

        helper_source = _installed_keychain_helper().expanduser().resolve(strict=True)
        source_mode = helper_source.stat().st_mode & 0o777
        if not helper_source.is_file() or not os.access(helper_source, os.X_OK) or source_mode & 0o077:
            raise PermissionError("installed Keychain helper must be an owner-only executable")
        staged_helper = app_root / "backend" / "keychain-helper"
        shutil.copy2(helper_source, staged_helper)
        os.chmod(staged_helper, 0o700)
        if _sha256(helper_source) != _sha256(staged_helper):
            raise OSError("staged Keychain helper verification failed")

        _write_release_manifest(temporary, indexed_payload, index_records, origin="git-index")

        environment_root = source_interpreter.parent.parent
        environment_config = environment_root / "pyvenv.cfg"
        try:
            environment_root.resolve(strict=True).relative_to(source_repo)
            environment_is_source_hosted = True
        except ValueError:
            environment_is_source_hosted = False
        if environment_config.is_file() and environment_is_source_hosted:
            _copy_runtime_tree(environment_root, temporary / "python")
            staged_interpreter_relative = source_interpreter.relative_to(environment_root)
            staged_interpreter = temporary / "python" / staged_interpreter_relative
        else:
            staged_interpreter = source_interpreter

        if not staged_interpreter.exists():
            raise FileNotFoundError(staged_interpreter)

        current = root / "current"
        previous = root / "previous"
        prior_root_identity = None
        prior_manifest: dict[str, Any] | None = None
        prior_indexed_payload: tuple[str, ...] = ()
        if current.is_dir():
            current_stat = current.stat()
            prior_root_identity = [current_stat.st_dev, current_stat.st_ino]
            prior_manifest, prior_indexed_payload = _snapshot_prior_release(current)
        if previous.exists():
            shutil.rmtree(previous)
        if current.exists():
            current.rename(previous)
            (previous / "release-manifest.json").write_text(
                json.dumps(prior_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        temporary.rename(current)
        return {
            "root": str(current),
            "repo_root": str(current / "app"),
            "interpreter": str(
                current / staged_interpreter.relative_to(temporary)
                if temporary in staged_interpreter.parents
                else staged_interpreter
            ),
            "source_repo_root": str(source_repo),
            "previous": str(previous) if previous.exists() else "",
            "indexed_payload": indexed_payload,
            "prior_indexed_payload": prior_indexed_payload,
            "prior_root_identity": prior_root_identity,
            "release_manifest": str(current / "release-manifest.json"),
            "prior_release_manifest": str(previous / "release-manifest.json") if prior_manifest else "",
        }
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def _rollback_staged_runtime(staged: dict[str, Any]) -> None:
    root = Path(str(staged.get("root") or ""))
    previous_raw = str(staged.get("previous") or "")
    previous = Path(previous_raw) if previous_raw else None
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    if previous is not None and previous.is_dir():
        previous.rename(root)


def _finalize_staged_runtime(staged: dict[str, Any]) -> None:
    previous_raw = str(staged.get("previous") or "")
    if previous_raw:
        shutil.rmtree(Path(previous_raw), ignore_errors=True)


def _verify_activation(staged: dict[str, Any], prior_state: dict[str, Any], host: str, port: int, timeout_seconds: float = 180.0) -> bool:
    from backend import runtime_supervisor

    deadline = time.monotonic() + timeout_seconds
    url = f"http://{host}:{port}/cleanhouse/status?ready=1"
    while time.monotonic() < deadline:
        try:
            response_status, payload = _readiness_payload(host, port)
            state = runtime_supervisor.read_state()
            launch_contract = staged.get("release_launch_contract")
            paths = staged.get("indexed_payload")
            manifest_matches = isinstance(paths, tuple) and bool(paths) and _verify_release_manifest(
                Path(staged["root"]), paths, plist_path().read_bytes(),
                str(staged.get("release_manifest_sha256") or ""),
            )
            identity_matches = (
                state.get("supervisor_pid") and state.get("supervisor_pid") != prior_state.get("supervisor_pid")
                and state.get("boot_id") and state.get("boot_id") != prior_state.get("boot_id")
                and state.get("backend_pid") and state.get("backend_pid") != prior_state.get("backend_pid")
                and state.get("backend_boot_id") and state.get("backend_boot_id") != prior_state.get("backend_boot_id")
                and state.get("owned_listener_pids") == [state.get("backend_pid")]
                and state.get("foreign_listener_pids") == []
                and state.get("supervisor_alive") is True
                and state.get("backend_alive") is True
                and isinstance(launch_contract, dict)
                and launch_contract.get("host") == host
                and launch_contract.get("port") == int(port)
                and launch_contract.get("working_directory") == staged.get("repo_root")
                and _processes_match_release(staged, state, launch_contract)
            )
            if response_status == 200 and _canonical_readiness_matches(payload, state) and manifest_matches and identity_matches:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _verify_rollback(
    staged: dict[str, Any],
    failed_state: dict[str, Any],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_seconds: float = 30.0,
) -> bool:
    from backend import runtime_supervisor
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            current = runtime_supervisor.read_state()
            launch_contract = staged.get("prior_launch_contract")
            if not isinstance(launch_contract, dict):
                raise ValueError("prior launch contract is unavailable")
            rollback_host = str(launch_contract["host"])
            rollback_port = int(launch_contract["port"])
            response_status, payload = _readiness_payload(rollback_host, rollback_port)
            root = Path(str(staged["root"]))
            expected_identity = staged.get("prior_root_identity")
            root_identity = None
            if root.is_dir():
                root_stat = root.stat()
                root_identity = [root_stat.st_dev, root_stat.st_ino]
            paths = staged.get("prior_indexed_payload")
            manifest_matches = isinstance(paths, tuple) and bool(paths) and _verify_release_manifest(
                root, paths, plist_path().read_bytes(),
                str(staged.get("prior_release_manifest_sha256") or ""),
            )
            if (
                current.get("supervisor_pid") and current.get("supervisor_pid") != failed_state.get("supervisor_pid")
                and current.get("boot_id") and current.get("boot_id") != failed_state.get("boot_id")
                and current.get("backend_pid") and current.get("backend_pid") != failed_state.get("backend_pid")
                and current.get("backend_boot_id") and current.get("backend_boot_id") != failed_state.get("backend_boot_id")
                and current.get("owned_listener_pids") == [current.get("backend_pid")]
                and current.get("foreign_listener_pids") == []
                and current.get("supervisor_alive") is True
                and current.get("backend_alive") is True
                and current.get("heartbeat_fresh") is True
                and current.get("runtime_state") == "healthy"
                and expected_identity is not None
                and root_identity == expected_identity
                and manifest_matches
                and launch_contract.get("working_directory") == staged.get("repo_root")
                and _processes_match_release(staged, current, launch_contract)
                and response_status == 200
                and _canonical_readiness_matches(payload, current)
            ):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _rollback_active_release(
    staged: dict[str, Any],
    domain: str,
    prior_state: dict[str, Any],
    *,
    path: Path | None = None,
    prior_payload: bytes | None = None,
    definition_changed: bool = False,
    prior_loaded: bool = True,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> bool:
    from backend import runtime_supervisor

    failed_state = runtime_supervisor.read_state()
    if definition_changed and path is not None:
        _run_launchctl(["bootout", domain, str(path)])
    _rollback_staged_runtime(staged)
    if not prior_loaded:
        if path is not None:
            if prior_payload is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(prior_payload)
                os.chmod(path, 0o600)
        return not status().get("loaded") and (
            (prior_payload is None and (path is None or not path.exists()))
            or (path is not None and path.is_file() and path.read_bytes() == prior_payload)
        )
    if definition_changed and path is not None:
        if prior_payload is None:
            path.unlink(missing_ok=True)
            return False
        path.write_bytes(prior_payload)
        os.chmod(path, 0o600)
        bootstrapped = _run_launchctl(["bootstrap", domain, str(path)])
        if bootstrapped.returncode != 0:
            return False
    kicked = _run_launchctl(["kickstart", "-k", f"{domain}/{LABEL}"])
    return kicked.returncode == 0 and _verify_rollback(staged, failed_state, host, port)


def build_payload(
    interpreter: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    repo_root: Path = REPO_ROOT,
    source_repo_root: Path | None = None,
    watch_root: Path | None = None,
) -> dict[str, Any]:
    # Preserve a virtual environment's executable path.  Resolving the
    # ``python3`` symlink to its framework binary discards the venv prefix, so
    # launchd starts a bare interpreter that cannot import CleanHouse.
    expanded_interpreter = Path(interpreter).expanduser()
    launch_interpreter = Path(os.path.abspath(os.fspath(expanded_interpreter)))
    if not launch_interpreter.exists():
        raise FileNotFoundError(launch_interpreter)
    resolved_repo = repo_root.expanduser().resolve(strict=True)
    resolved_source_repo = (source_repo_root or repo_root).expanduser().resolve(strict=True)
    resolved_watch_root = (watch_root or resolved_source_repo).expanduser().resolve(strict=True)
    runtime_dir = _runtime_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(launch_interpreter),
            "-m",
            "backend.runtime_supervisor",
            "supervise",
            "--host",
            str(host),
            "--port",
            str(int(port)),
        ],
        "WorkingDirectory": str(resolved_repo),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 5,
        "StandardOutPath": str(runtime_dir / "launchagent.stdout.log"),
        "StandardErrorPath": str(runtime_dir / "launchagent.stderr.log"),
        "EnvironmentVariables": {
            "CLEANHOUSE_HOST": str(host),
            "CLEANHOUSE_PORT": str(int(port)),
            "CLEANHOUSE_RUNTIME_DIR": str(runtime_dir),
            "CLEANHOUSE_LAUNCHD_OWNED": "1",
            "CLEANHOUSE_SOURCE_REPO_ROOT": str(resolved_source_repo),
            "CLEANHOUSE_WATCH_DIR": str(resolved_watch_root),
            "CLEANHOUSE_DATA_ROOT": str(runtime_dir / "data"),
            "CLEANHOUSE_AUTH_CONFIG_PATH": str(resolved_repo / "config" / "auth-runtime.json"),
            "CLEANHOUSE_KEYCHAIN_HELPER_PATH": str(resolved_repo / "backend" / "keychain-helper"),
            "PYTHONPATH": str(resolved_repo),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        },
    }


def render_plist(
    interpreter: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    repo_root: Path = REPO_ROOT,
    source_repo_root: Path | None = None,
    watch_root: Path | None = None,
) -> bytes:
    return plistlib.dumps(
        build_payload(
            interpreter,
            host=host,
            port=port,
            repo_root=repo_root,
            source_repo_root=source_repo_root,
            watch_root=watch_root,
        ),
        sort_keys=True,
    )


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def status() -> dict[str, Any]:
    path = plist_path()
    result = _run_launchctl(["print", f"{gui_domain()}/{LABEL}"])
    loaded = result.returncode == 0
    return {
        "label": LABEL,
        "plist_path": str(path),
        "installed": path.is_file(),
        "loaded": loaded,
        "state": "loaded" if loaded else ("installed" if path.is_file() else "unavailable"),
        "launchctl_error": "" if loaded else (result.stderr or result.stdout).strip()[:512],
    }


def install(
    interpreter: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    watch_root: Path | None = None,
    start: bool = True,
) -> dict[str, Any]:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _runtime_dir().mkdir(parents=True, exist_ok=True)
    domain = gui_domain()
    prior_status = status()
    from backend import runtime_supervisor
    prior_state = runtime_supervisor.read_state()
    prior_payload = path.read_bytes() if path.is_file() else None
    # Stage the replacement before touching the live service. A copy failure
    # must never take an otherwise healthy LaunchAgent offline.
    staged = stage_runtime(interpreter)
    payload = render_plist(
        str(staged["interpreter"]),
        host=host,
        port=port,
        repo_root=Path(str(staged["repo_root"])),
        source_repo_root=Path(str(staged["source_repo_root"])),
        watch_root=watch_root,
    )
    _bind_release_plists(staged, payload, prior_payload)

    # The managed runtime and interpreter paths are stable across releases.
    # When the loaded definition is unchanged, launchd does not need a
    # bootout/bootstrap cycle: atomically staged files plus kickstart provide
    # a bounded restart without the registration race seen during repeated
    # launcher invocations.
    if prior_status.get("loaded") and prior_payload == payload:
        if not start:
            _finalize_staged_runtime(staged)
            return {**status(), "status": "ok", "runtime_root": staged["root"]}
        kickstart = _run_launchctl(["kickstart", "-k", f"{domain}/{LABEL}"])
        if kickstart.returncode != 0:
            restored = _rollback_active_release(staged, domain, prior_state, host=host, port=port)
            return {
                **status(),
                "status": "error",
                "message": (
                    (kickstart.stderr or kickstart.stdout).strip()[:768]
                    + ("; previous release restored" if restored else "; rollback verification failed")
                ),
                "rollback_verified": restored,
            }
        if not _verify_activation(staged, prior_state, host, port):
            restored = _rollback_active_release(staged, domain, prior_state, host=host, port=port)
            message = "staged runtime readiness verification failed; previous release restored" if restored else "staged runtime readiness verification failed; rollback verification failed"
            return {**status(), "status": "error", "message": message, "rollback_verified": restored}
        _finalize_staged_runtime(staged)
        return {**status(), "status": "ok", "runtime_root": staged["root"]}

    if prior_status.get("loaded"):
        _run_launchctl(["bootout", domain, str(path)])
        for _ in range(20):
            if not status().get("loaded"):
                break
            time.sleep(0.1)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)

    bootstrap = _run_launchctl(["bootstrap", domain, str(path)])
    if bootstrap.returncode != 0:
        restored = _rollback_active_release(
            staged,
            domain,
            prior_state,
            path=path,
            prior_payload=prior_payload,
            definition_changed=bool(prior_status.get("loaded")),
            prior_loaded=bool(prior_status.get("loaded")),
            host=host,
            port=port,
        )
        return {
            **status(),
            "status": "error",
            "message": (
                (bootstrap.stderr or bootstrap.stdout).strip()[:768]
                + ("; previous release restored" if restored else "; rollback verification failed")
            ),
            "rollback_verified": restored,
        }
    # RunAtLoad starts a newly bootstrapped definition. An immediate kickstart
    # races launchd registration and can return "service not found" after a
    # successful bootstrap, causing the launcher to roll back a healthy job.
    # The loaded/unchanged branch above still uses kickstart when an actual
    # replacement of an already registered process is required.
    if start and not _verify_activation(staged, prior_state, host, port):
        restored = _rollback_active_release(
            staged,
            domain,
            prior_state,
            path=path,
            prior_payload=prior_payload,
            definition_changed=bool(prior_status.get("loaded")),
            prior_loaded=bool(prior_status.get("loaded")),
            host=host,
            port=port,
        )
        message = "staged runtime readiness verification failed; previous release restored" if restored else "staged runtime readiness verification failed; rollback verification failed"
        return {**status(), "status": "error", "message": message, "rollback_verified": restored}
    _finalize_staged_runtime(staged)
    return {**status(), "status": "ok", "runtime_root": staged["root"]}


def stop(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    """Stop launchd supervision and any verified owned runtime processes."""
    path = plist_path()
    result = _run_launchctl(["bootout", gui_domain(), str(path)])
    # A prior launchd failure can leave a verified CleanHouse backend orphaned
    # after the service itself is no longer registered.  Always follow the
    # bootout with the supervisor's ownership-aware stop path so a canonical
    # shutdown actually releases the configured listener without touching a
    # foreign process.
    from backend import runtime_supervisor

    runtime = runtime_supervisor.stop_runtime(host, port)
    current = status()
    if result.returncode not in {0, 3, 113} and current.get("loaded"):
        return {
            **current,
            "status": "error",
            "message": (result.stderr or result.stdout).strip()[:1024],
            "runtime": runtime,
        }
    return {**current, "status": "ok", "runtime": runtime}


def uninstall() -> dict[str, Any]:
    path = plist_path()
    stop()
    if path.exists():
        path.unlink()
    return {**status(), "status": "ok"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--interpreter", required=True)
    install_parser.add_argument("--host", default=os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST))
    install_parser.add_argument("--port", type=int, default=int(os.getenv("CLEANHOUSE_PORT", DEFAULT_PORT)))
    install_parser.add_argument("--watch-root", type=Path)
    install_parser.add_argument("--no-start", action="store_true")
    subparsers.add_parser("status")
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--host", default=os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST))
    stop_parser.add_argument("--port", type=int, default=int(os.getenv("CLEANHOUSE_PORT", DEFAULT_PORT)))
    subparsers.add_parser("uninstall")
    args = parser.parse_args(argv)
    if args.command == "install":
        result = install(
            args.interpreter,
            host=args.host,
            port=args.port,
            watch_root=args.watch_root,
            start=not args.no_start,
        )
    elif args.command == "stop":
        result = stop(host=args.host, port=args.port)
    elif args.command == "uninstall":
        result = uninstall()
    else:
        result = status()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
