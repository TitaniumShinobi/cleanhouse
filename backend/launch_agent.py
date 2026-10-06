"""Install and inspect the user-owned CleanHouse LaunchAgent.

The LaunchAgent owns the long-lived supervisor process.  The launcher may exit
without taking the local service down, and launchd can restart the supervisor
if it terminates unexpectedly.  This module never requests administrator
privileges; it only manages the current user's LaunchAgents domain.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


LABEL = "org.cleanhouse.runtime"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3333
STAGED_RUNTIME_NAME = "launchagent-runtime"
RUNTIME_DIRECTORIES = ("backend", "corefiles", "frontend", "models", "assets")
RUNTIME_FILES: tuple[str, ...] = ()


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
        for name in RUNTIME_DIRECTORIES:
            source = source_repo / name
            if name in {"backend", "corefiles", "frontend", "models"} and not source.is_dir():
                raise FileNotFoundError(source)
            if source.is_dir():
                _copy_runtime_tree(source, app_root / name)

        for name in RUNTIME_FILES:
            source = source_repo / name
            if not source.is_file():
                raise FileNotFoundError(source)
            shutil.copy2(source, app_root / name)

        legal_source = source_repo / "docs" / "legal"
        if legal_source.is_dir():
            (app_root / "docs").mkdir(exist_ok=True)
            _copy_runtime_tree(legal_source, app_root / "docs" / "legal")

        wazuh_source = source_repo / "bundled" / "wazuh" / "darwin-arm64"
        if wazuh_source.is_dir():
            wazuh_destination = app_root / "bundled" / "wazuh" / "darwin-arm64"
            wazuh_destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_runtime_tree(wazuh_source, wazuh_destination)

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
        if previous.exists():
            shutil.rmtree(previous)
        if current.exists():
            current.rename(previous)
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


def build_payload(
    interpreter: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    repo_root: Path = REPO_ROOT,
    source_repo_root: Path | None = None,
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
            "CLEANHOUSE_WATCH_DIR": str(resolved_source_repo),
            "CLEANHOUSE_DATA_ROOT": str(runtime_dir / "data"),
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
) -> bytes:
    return plistlib.dumps(
        build_payload(
            interpreter,
            host=host,
            port=port,
            repo_root=repo_root,
            source_repo_root=source_repo_root,
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
    start: bool = True,
) -> dict[str, Any]:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _runtime_dir().mkdir(parents=True, exist_ok=True)
    domain = gui_domain()
    _run_launchctl(["bootout", domain, str(path)])
    staged = stage_runtime(interpreter)
    payload = render_plist(
        str(staged["interpreter"]),
        host=host,
        port=port,
        repo_root=Path(str(staged["repo_root"])),
        source_repo_root=Path(str(staged["source_repo_root"])),
    )
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
        _rollback_staged_runtime(staged)
        return {
            **status(),
            "status": "error",
            "message": (bootstrap.stderr or bootstrap.stdout).strip()[:1024],
        }
    if start:
        kickstart = _run_launchctl(["kickstart", "-k", f"{domain}/{LABEL}"])
        if kickstart.returncode != 0:
            _rollback_staged_runtime(staged)
            return {
                **status(),
                "status": "error",
                "message": (kickstart.stderr or kickstart.stdout).strip()[:1024],
            }
    _finalize_staged_runtime(staged)
    return {**status(), "status": "ok", "runtime_root": staged["root"]}


def stop() -> dict[str, Any]:
    """Stop the user service without deleting its installed definition."""
    path = plist_path()
    result = _run_launchctl(["bootout", gui_domain(), str(path)])
    current = status()
    if result.returncode not in {0, 3, 113} and current.get("loaded"):
        return {
            **current,
            "status": "error",
            "message": (result.stderr or result.stdout).strip()[:1024],
        }
    return {**current, "status": "ok"}


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
    install_parser.add_argument("--no-start", action="store_true")
    subparsers.add_parser("status")
    subparsers.add_parser("stop")
    subparsers.add_parser("uninstall")
    args = parser.parse_args(argv)
    if args.command == "install":
        result = install(
            args.interpreter,
            host=args.host,
            port=args.port,
            start=not args.no_start,
        )
    elif args.command == "stop":
        result = stop()
    elif args.command == "uninstall":
        result = uninstall()
    else:
        result = status()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
