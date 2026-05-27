"""
Observable wrapper around subprocess.run for CleanHouse internal command execution.

Usage:
    from corefiles.collectors.command_observer import get_observer
    result = get_observer().run(["ps", "aux"], capture_output=True, text=True)
    # result is a standard subprocess.CompletedProcess — transparent wrapper.

The adapter in cleanhouse_monitoring.py hooks into the singleton to emit events.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class CommandResult:
    """Immutable record of a single command execution."""
    command: str
    args: tuple[str, ...]
    cwd: str | None
    user: str | None
    returncode: int
    duration: float
    timestamp: str
    stdout_preview: str | None
    stderr_preview: str | None
    session_id: str | None = None
    objective_id: str | None = None
    child_pid: int | None = None


class CommandObserver:
    """Transparent wrapper around subprocess.run with metadata capture.

    Returns the same subprocess.CompletedProcess as subprocess.run, while
    capturing execution metadata and (optionally) notifying a callback.
    """

    def __init__(self, max_results: int = 200):
        self._results: deque[CommandResult] = deque(maxlen=max_results)
        self.on_completed: Callable[[CommandResult], None] | None = None

    def run(
        self,
        cmd_args: list[str],
        *,
        capture_output: bool = True,
        timeout: float | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        objective_id: str | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess:
        start = time.monotonic()
        try:
            user: str | None = getpass.getuser()
        except Exception:
            user = None

        stdout_preview: str | None = None
        stderr_preview: str | None = None
        child_pid: int | None = None
        env = kwargs.get("env")
        metadata_env = env if isinstance(env, dict) else os.environ
        resolved_session_id = session_id or metadata_env.get("CLEANHOUSE_SESSION_ID")
        resolved_objective_id = objective_id or metadata_env.get("CLEANHOUSE_OBJECTIVE_ID")

        try:
            proc = _run_with_child_pid(
                cmd_args,
                capture_output=capture_output,
                timeout=timeout,
                cwd=cwd,
                **kwargs,
            )
            child_pid = getattr(proc, "child_pid", None)
            duration = time.monotonic() - start
            if capture_output:
                if proc.stdout is not None:
                    stdout_preview = _preview(proc.stdout)
                if proc.stderr is not None:
                    stderr_preview = _preview(proc.stderr)
            returncode = proc.returncode
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - start
            returncode = -1
            stderr_preview = str(e)[:500]
            raise
        except Exception as e:
            duration = time.monotonic() - start
            returncode = -1
            stderr_preview = str(e)[:500]
            raise

        result = CommandResult(
            command=cmd_args[0] if cmd_args else "",
            args=tuple(cmd_args),
            cwd=str(cwd) if cwd is not None else None,
            user=user,
            returncode=returncode,
            duration=round(duration, 3),
            timestamp=datetime.now().isoformat(),
            stdout_preview=stdout_preview,
            stderr_preview=stderr_preview,
            session_id=resolved_session_id,
            objective_id=resolved_objective_id,
            child_pid=child_pid,
        )
        self._results.append(result)
        if self.on_completed is not None:
            self.on_completed(result)
        return proc

    def drain(self) -> list[CommandResult]:
        """Atomically clear and return all buffered results."""
        items = list(self._results)
        self._results.clear()
        return items


_observer: CommandObserver | None = None


def _preview(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:500]
    return str(value)[:500]


def _run_with_child_pid(*popenargs: Any, input: Any = None, capture_output: bool = False, timeout: float | None = None, check: bool = False, **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run-compatible helper that preserves the spawned PID."""
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE

    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    with subprocess.Popen(*popenargs, **kwargs) as process:
        child_pid = process.pid
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            exc.output = stdout
            exc.stdout = stdout
            exc.stderr = stderr
            raise
        except Exception:
            process.kill()
            raise
        retcode = process.poll()

    completed = subprocess.CompletedProcess(popenargs[0], retcode, stdout, stderr)
    completed.child_pid = child_pid
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, popenargs[0], output=stdout, stderr=stderr)
    return completed


def get_observer() -> CommandObserver:
    """Return the module-level CommandObserver singleton."""
    global _observer
    if _observer is None:
        _observer = CommandObserver()
    return _observer
