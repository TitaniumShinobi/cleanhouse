#!/usr/bin/env python3
"""Fail-closed product entrypoint for a START-owned disposable runtime.

This module validates isolation inputs and then replaces itself with the real
CleanHouse runtime supervisor.  START remains the sole owner of process-group,
listener, recovery, cleanup, and final verification evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import pwd
import re
import socket
import sys
from pathlib import Path
from datetime import datetime, timezone


REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = REPO_ROOT / "start.isolated-launcher.json"
CANONICAL_PORT = 3333
SOURCE_FILES = (
    "backend/api/cleanhouse.py",
    "backend/runtime_env.py",
    "backend/runtime_supervisor.py",
    "backend/server.py",
    "scripts/start_isolated_runtime.py",
    "tests/test_start_isolated_runtime.py",
)
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
VERIFICATION_LANES = (
    "build", "regression", "behavioral", "security_penetration",
    "recovery", "integration", "acceptance",
)


class IsolationError(RuntimeError):
    pass


def source_content_digest(root: Path = REPO_ROOT) -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise IsolationError(f"unsafe source: {relative}")
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_verification_declaration(value: object) -> None:
    if not isinstance(value, dict) or value.get("contract") != "life-start-final-verification/v2":
        raise IsolationError("invalid verification contract")
    lanes = value.get("lanes")
    if not isinstance(lanes, list) or tuple(item.get("id") for item in lanes if isinstance(item, dict)) != VERIFICATION_LANES:
        raise IsolationError("invalid verification lanes")
    for lane in lanes:
        if not isinstance(lane, dict) or lane.get("status") != "DECLARED_NOT_VERIFIED":
            raise IsolationError("verification lane may not self-assert completion")
        if not all(
            isinstance(lane.get(key), str) and lane.get(key)
            for key in ("proposed_adapter_id", "predicate_version", "operation_id")
        ):
            raise IsolationError("verification lane adapter contract missing")
        if not isinstance(lane.get("expected"), dict):
            raise IsolationError("verification lane expected outcome missing")
        if "command" in lane:
            command = lane.get("command")
            timeout = lane.get("timeout_seconds")
            output_limit = lane.get("max_output_bytes")
            if (
                not isinstance(command, list) or not command
                or not all(isinstance(part, str) and part for part in command)
                or not isinstance(timeout, int) or timeout < 1 or timeout > 60
                or not isinstance(output_limit, int) or output_limit < 1024 or output_limit > 65536
            ):
                raise IsolationError("verification lane command is unbounded")
            if lane.get("id") == "build" and (
                lane.get("environment", {}).get("PYTHONPYCACHEPREFIX") != "START_BUILD_ROOT/pycache"
                or lane.get("fresh_artifact") != "START_BUILD_ROOT/pycache"
            ):
                raise IsolationError("build artifact is not task-owned and fresh")
        elif not isinstance(lane.get("predicate") or lane.get("adapter_predicate"), str):
            raise IsolationError("verification lane predicate missing")


def verify_bound_evidence(
    value: object,
    *,
    secret: str,
    nonce: str,
    generation: str,
    content_digest: str,
    now: datetime | None = None,
    max_age_seconds: float = 10.0,
) -> bool:
    if not isinstance(value, dict) or value.get("schema") != "cleanhouse.start_isolation_evidence.v1":
        return False
    binding = value.get("binding")
    if not isinstance(binding, dict) or binding.get("algorithm") != "hmac-sha256":
        return False
    core = {key: item for key, item in value.items() if key != "binding"}
    expected = hmac.new(
        secret.encode("utf-8"),
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    try:
        observed = datetime.fromisoformat(str(value.get("observed_at") or "").replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = abs(((now or datetime.now(timezone.utc)) - observed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return False
    return bool(
        hmac.compare_digest(str(binding.get("digest") or ""), expected)
        and value.get("invocation_nonce") == nonce
        and value.get("generation") == generation
        and value.get("source_content_digest") == content_digest
        and age <= max_age_seconds
    )


def ownership_checks(supervisor: object, backend: object) -> dict[str, bool]:
    supervisor = supervisor if isinstance(supervisor, dict) else {}
    backend = backend if isinstance(backend, dict) else {}
    return {
        "direct_child": backend.get("parent_pid") == supervisor.get("pid"),
        "same_process_group": backend.get("process_group_id") == supervisor.get("process_group_id"),
        "same_session": backend.get("session_id") == supervisor.get("session_id"),
        "generation_matches": bool(
            backend.get("run_id")
            and backend.get("run_id") == supervisor.get("run_id")
            and backend.get("invocation_nonce") == supervisor.get("invocation_nonce")
            and backend.get("source_content_digest") == supervisor.get("source_content_digest")
        ),
    }


def _path(name: str, env: dict[str, str]) -> Path:
    raw = env.get(name, "").strip()
    if not raw:
        raise IsolationError(f"missing {name}")
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        raise IsolationError(f"unsafe {name}")
    return path.resolve(strict=False)


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _canonical_home() -> Path:
    """Resolve the account home independently of a task-scoped HOME value."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)


def interpreter_provenance(executable: str | None = None) -> dict[str, object]:
    expected = (REPO_ROOT / "cleanhouse_env" / "bin" / "python3").absolute()
    observed = Path(executable or sys.executable).absolute()
    dependencies = {
        name: importlib.util.find_spec(name) is not None
        for name in ("flask", "flask_cors", "cryptography")
    }
    return {
        "expected": str(expected),
        "observed": str(observed),
        "exact_invocation_path": observed == expected,
        "dependencies": dependencies,
        "dependencies_available": all(dependencies.values()),
    }


def _load_json_file(path: Path, name: str, *, private: bool = True) -> dict:
    try:
        stat = path.stat()
        if not path.is_file() or path.is_symlink() or (private and stat.st_mode & 0o077):
            raise IsolationError(f"unsafe {name}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IsolationError(f"invalid {name}") from exc
    if not isinstance(value, dict):
        raise IsolationError(f"invalid {name}")
    return value


def validate_isolation(env: dict[str, str] | None = None) -> dict:
    source = dict(os.environ if env is None else env)
    task_root = _path("START_TASK_ROOT", source)
    bootstrap_home = _path("HOME", source)
    state_root = _path("START_STATE_ROOT", source)
    data_root = _path("START_DATA_ROOT", source)
    auth_config = _path("START_AUTH_CONFIG", source)
    credentials_path = _path("START_EPHEMERAL_CREDENTIALS", source)
    nonce = source.get("START_INVOCATION_NONCE", "").strip()
    if not NONCE_RE.fullmatch(nonce):
        raise IsolationError("invalid START_INVOCATION_NONCE")
    try:
        port = int(source.get("START_PORT", ""))
    except ValueError as exc:
        raise IsolationError("invalid START_PORT") from exc
    if port < 1024 or port > 65535 or port == CANONICAL_PORT:
        raise IsolationError("START_PORT must be noncanonical and unprivileged")
    if source.get("START_HOST") != "127.0.0.1":
        raise IsolationError("START_HOST must be 127.0.0.1")

    canonical_home = _canonical_home()
    canonical_roots = (
        REPO_ROOT,
        canonical_home / ".cleanhouse",
        canonical_home / "Documents" / "CleanHouse",
    )
    if any(_within(task_root, item) or _within(item, task_root) for item in canonical_roots):
        raise IsolationError("START_TASK_ROOT overlaps canonical storage")
    for name, path in (
        ("HOME", bootstrap_home),
        ("START_STATE_ROOT", state_root),
        ("START_DATA_ROOT", data_root),
        ("START_AUTH_CONFIG", auth_config),
        ("START_EPHEMERAL_CREDENTIALS", credentials_path),
    ):
        if not _within(path, task_root):
            raise IsolationError(f"{name} escapes START_TASK_ROOT")

    provenance = interpreter_provenance()
    if not provenance["exact_invocation_path"] or not provenance["dependencies_available"]:
        raise IsolationError("isolated interpreter provenance or dependencies unavailable")

    declaration = _load_json_file(DECLARATION, "isolated launcher declaration", private=False)
    validate_verification_declaration(declaration.get("verification"))
    expected_digest = declaration.get("source", {}).get("content_digest")
    if expected_digest != source_content_digest():
        raise IsolationError("isolated launcher source digest mismatch")
    auth = _load_json_file(auth_config, "START_AUTH_CONFIG")
    if auth.get("providers") not in ({}, None):
        raise IsolationError("isolated auth config must not declare providers")
    credentials = _load_json_file(credentials_path, "START_EPHEMERAL_CREDENTIALS")
    if credentials.get("invocation_nonce") != nonce:
        raise IsolationError("ephemeral credentials nonce mismatch")
    secret = str(credentials.get("flask_secret_key") or "")
    if len(secret) < 32:
        raise IsolationError("ephemeral signing secret is too short")

    task_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in (state_root, data_root, bootstrap_home, task_root / "tmp"):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise IsolationError("START_PORT is already occupied") from exc
    return {
        "task_root": task_root,
        "bootstrap_home": bootstrap_home,
        "state_root": state_root,
        "data_root": data_root,
        "auth_config": auth_config,
        "nonce": nonce,
        "port": port,
        "secret": secret,
    }


def isolated_environment(validated: dict) -> dict[str, str]:
    task_root = validated["task_root"]
    # Preserve the exact venv invocation path. Resolving this symlink changes
    # Python's prefix discovery and silently drops CleanHouse dependencies.
    python = str(Path(sys.executable).absolute())
    content_digest = source_content_digest()
    generation = hashlib.sha256(
        f"{validated['nonce']}:{content_digest}".encode("utf-8")
    ).hexdigest()
    declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(validated["bootstrap_home"]),
        "TMPDIR": str(task_root / "tmp"),
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "CLEANHOUSE_PYTHON": python,
        "CLEANHOUSE_START_ISOLATED": "1",
        "CLEANHOUSE_HOST": "127.0.0.1",
        "CLEANHOUSE_PORT": str(validated["port"]),
        "CLEANHOUSE_RUNTIME_DIR": str(validated["state_root"]),
        "CLEANHOUSE_DATA_ROOT": str(validated["data_root"]),
        "CLEANHOUSE_EVENTS_DB": str(validated["data_root"] / "events" / "events.db"),
        "CLEANHOUSE_AUTH_DB": str(validated["data_root"] / "auth" / "auth.db"),
        "CLEANHOUSE_AUTH_RECOVERY_DB": str(validated["data_root"] / "auth" / "recovery.db"),
        "CLEANHOUSE_AUTH_CONFIG_PATH": str(validated["auth_config"]),
        "CLEANHOUSE_AUTH_PUBLIC_CONFIG_PATH": str(validated["auth_config"]),
        "CLEANHOUSE_ENABLE_AUTH": "1",
        "CLEANHOUSE_REQUIRE_LOGIN": "1",
        "CLEANHOUSE_ALLOWED_DOMAINS": "start.invalid",
        "CLEANHOUSE_TURNSTILE_REQUIRED": "0",
        "CLEANHOUSE_PUBLIC_ORIGIN": f"http://127.0.0.1:{validated['port']}",
        "CLEANHOUSE_NATIVE_NOTIFICATIONS": "0",
        "CLEANHOUSE_NETWORK_COLLECTOR_AUTOSTART": "0",
        "CLEANHOUSE_NETWORK_HISTORY_ENABLED": "0",
        "FLASK_SECRET_KEY": validated["secret"],
        "START_INVOCATION_NONCE": validated["nonce"],
        "START_RUNTIME_GENERATION": generation,
        "START_SOURCE_CONTENT_DIGEST": content_digest,
        "START_SOURCE_REVISION": str(declaration["source"]["revision"]),
    }


def main() -> int:
    try:
        validated = validate_isolation()
        environment = isolated_environment(validated)
    except IsolationError as exc:
        print(f"cleanhouse START isolation refused: {exc}", file=sys.stderr)
        return 78
    python = environment["CLEANHOUSE_PYTHON"]
    argv = [
        python, "-m", "backend.runtime_supervisor", "supervise",
        "--host", "127.0.0.1", "--port", str(validated["port"]),
    ]
    os.chdir(REPO_ROOT)
    os.execve(python, argv, environment)
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
