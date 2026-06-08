"""Local active-work context sources for CleanHouse.

This module intentionally reads only operator-approved local sources:
frontmost app/window identity, clipboard text after follow mode is enabled,
explicit pickup/export files, and local Codex transcript artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


MAX_PROMPT_CHARS = 16000
MAX_CONTEXT_CHARS = 32000
MAX_PICKUP_BYTES = 512_000
MAX_SESSION_INDEX_TAIL_BYTES = 1_000_000

TRUTH_OBSERVED = "observed_context"
TRUTH_INFERRED = "inferred_context"
TRUTH_MISSING = "missing_context"
TRUTH_DEGRADED = "degraded_continuity"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_fingerprint(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _preview(text: str, limit: int = 500) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit]


@dataclass(frozen=True)
class FrontmostApp:
    app_name: str = ""
    window_title: str = ""
    status: str = "unknown"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_name": self.app_name,
            "window_title": self.window_title,
            "status": self.status,
            "error": self.error,
        }

    @property
    def is_chatgpt_or_codex(self) -> bool:
        haystack = f"{self.app_name} {self.window_title}".lower()
        return any(token in haystack for token in ("chatgpt", "codex"))

    @property
    def tool_identity(self) -> str:
        haystack = f"{self.app_name} {self.window_title}".lower()
        if "codex" in haystack:
            return "codex"
        if "chatgpt" in haystack:
            return "chatgpt"
        return "unknown"


class ActiveContextCollector:
    """Collect active-work context without browser automation or scraping."""

    def __init__(
        self,
        *,
        frontmost_reader: Callable[[], FrontmostApp | dict[str, Any] | None] | None = None,
        clipboard_reader: Callable[[], str] | None = None,
        codex_root: Path | None = None,
        pickup_paths_reader: Callable[[], Sequence[Path]] | None = None,
    ):
        self.frontmost_reader = frontmost_reader or read_frontmost_app
        self.clipboard_reader = clipboard_reader or read_clipboard_text
        self.codex_root = codex_root or Path.home() / ".codex"
        self.pickup_paths_reader = pickup_paths_reader or configured_pickup_paths

    def collect(
        self,
        *,
        follow_enabled: bool,
        ignored_keys: Sequence[str] = (),
        explicit_pickup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        frontmost = self._frontmost()
        ignored = {str(key) for key in ignored_keys}
        candidates: list[dict[str, Any]] = []

        if explicit_pickup:
            candidates.append(self._context_from_explicit_pickup(explicit_pickup, frontmost))

        if follow_enabled:
            clipboard_context = self._context_from_clipboard(frontmost)
            if clipboard_context:
                candidates.append(clipboard_context)
            file_context = self._context_from_pickup_files(frontmost)
            if file_context:
                candidates.append(file_context)

        allow_codex_artifact = follow_enabled
        if os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_CODEX_FOLLOW_OFF", "").strip().lower() in {"1", "true", "yes", "on"}:
            allow_codex_artifact = True
        if allow_codex_artifact:
            codex_context = self._context_from_codex_artifact(frontmost)
            if codex_context:
                candidates.append(codex_context)

        for candidate in candidates:
            if candidate.get("dedupe_key") in ignored:
                continue
            return candidate

        return self._missing_context(frontmost, follow_enabled)

    def _frontmost(self) -> FrontmostApp:
        try:
            raw = self.frontmost_reader()
        except Exception as exc:
            return FrontmostApp(status="degraded", error=str(exc) or exc.__class__.__name__)
        if isinstance(raw, FrontmostApp):
            return raw
        if isinstance(raw, dict):
            return FrontmostApp(
                app_name=str(raw.get("app_name") or raw.get("app") or ""),
                window_title=str(raw.get("window_title") or raw.get("title") or ""),
                status=str(raw.get("status") or "observed"),
                error=str(raw.get("error") or ""),
            )
        return FrontmostApp(status="missing")

    def _base_context(self, source_type: str, frontmost: FrontmostApp) -> dict[str, Any]:
        return {
            "source_type": source_type,
            "source_labels": [],
            "truth_classification": TRUTH_OBSERVED,
            "frontmost_app": frontmost.to_dict(),
            "app_name": frontmost.app_name,
            "window_title": frontmost.window_title,
            "current_repo": "",
            "current_objective": "",
            "active_prompt": "",
            "active_prompt_preview": "",
            "last_agent_action": "",
            "session_id": "",
            "objective_id": "",
            "tool_identity": frontmost.tool_identity if frontmost.tool_identity != "unknown" else "CleanHouse",
            "context": "",
            "evidence_refs": [],
            "metadata": {},
            "source_ref": "",
            "updated_at": now_iso(),
        }

    def _context_from_clipboard(self, frontmost: FrontmostApp) -> dict[str, Any] | None:
        if not frontmost.is_chatgpt_or_codex:
            return None
        try:
            text = (self.clipboard_reader() or "").strip()
        except Exception as exc:
            ctx = self._base_context("clipboard", frontmost)
            ctx.update({
                "truth_classification": TRUTH_DEGRADED,
                "source_labels": ["active_window_observed", "clipboard_unavailable"],
                "continuity_status": "degraded",
                "degraded_reason": str(exc) or exc.__class__.__name__,
            })
            return self._finalize_context(ctx)
        if not text:
            return None
        ctx = self._base_context("clipboard", frontmost)
        tool = frontmost.tool_identity if frontmost.tool_identity != "unknown" else "chatgpt"
        prompt_text = text[:MAX_PROMPT_CHARS]
        prompt_hash = stable_fingerprint("clipboard", frontmost.app_name, frontmost.window_title, prompt_text)
        ctx.update({
            "source_labels": ["active_window_observed", "clipboard_observed"],
            "tool_identity": tool,
            "active_prompt": prompt_text,
            "active_prompt_preview": _preview(prompt_text),
            "current_objective": _preview(prompt_text, 180),
            "session_id": f"{tool}:active:{stable_fingerprint(frontmost.app_name, frontmost.window_title)[:10]}",
            "objective_id": f"objective:{prompt_hash}",
            "context": f"Clipboard-gated active context from {frontmost.app_name or 'unknown app'} / {frontmost.window_title or 'unknown window'}",
            "metadata": {
                "active_context_source": "clipboard",
                "clipboard_hash": prompt_hash,
            },
        })
        return self._finalize_context(ctx)

    def _context_from_explicit_pickup(self, pickup: dict[str, Any], frontmost: FrontmostApp) -> dict[str, Any]:
        ctx = self._base_context("operator_pickup", frontmost)
        text = str(pickup.get("text") or pickup.get("prompt") or "").strip()
        context = str(pickup.get("context") or "").strip()
        repo_path = str(pickup.get("repo_path") or pickup.get("current_repo") or "").strip()
        tool = str(pickup.get("tool_identity") or frontmost.tool_identity or "CleanHouse").strip() or "CleanHouse"
        session_id = str(pickup.get("session_id") or "").strip()
        objective_id = str(pickup.get("objective_id") or "").strip()
        source_ref = str(pickup.get("source_ref") or "").strip()
        pickup_hash = stable_fingerprint("operator_pickup", text, context, repo_path, source_ref)
        if not session_id:
            session_id = f"pickup:{pickup_hash}"
        if not objective_id and text:
            objective_id = f"objective:{stable_fingerprint(text)}"
        ctx.update({
            "source_labels": ["operator_pickup_observed"],
            "tool_identity": tool,
            "active_prompt": text[:MAX_PROMPT_CHARS],
            "active_prompt_preview": _preview(text),
            "current_objective": _preview(str(pickup.get("objective") or text), 180),
            "current_repo": repo_path,
            "session_id": session_id,
            "objective_id": objective_id,
            "context": context[:MAX_CONTEXT_CHARS],
            "source_ref": source_ref,
            "metadata": {
                "active_context_source": "operator_pickup",
                "pickup_refs": [source_ref] if source_ref.startswith("local://cleanhouse/") else [],
            },
        })
        return self._finalize_context(ctx)

    def _context_from_pickup_files(self, frontmost: FrontmostApp) -> dict[str, Any] | None:
        paths = [path for path in self.pickup_paths_reader() if path.exists()]
        files: list[Path] = []
        for path in paths:
            if path.is_file():
                files.append(path)
            elif path.is_dir():
                files.extend(
                    candidate
                    for candidate in path.iterdir()
                    if candidate.is_file() and candidate.suffix.lower() in {".json", ".txt", ".md"}
                )
        if not files:
            return None
        latest = max(files, key=lambda p: p.stat().st_mtime)
        try:
            raw = latest.read_text(encoding="utf-8")[:MAX_PICKUP_BYTES]
            if latest.suffix.lower() == ".json":
                payload = json.loads(raw)
                pickup = payload if isinstance(payload, dict) else {"text": raw}
            else:
                pickup = {"text": raw, "source_ref": f"local://cleanhouse/active-context-export/{stable_fingerprint(str(latest.resolve()))}"}
            pickup.setdefault("source_ref", f"local://cleanhouse/active-context-export/{stable_fingerprint(str(latest.resolve()))}")
            ctx = self._context_from_explicit_pickup(pickup, frontmost)
            ctx["source_type"] = "export_file"
            ctx["source_labels"] = ["operator_export_observed"]
            ctx["metadata"]["export_file"] = str(latest.resolve())
            return self._finalize_context(ctx)
        except Exception as exc:
            ctx = self._base_context("export_file", frontmost)
            ctx.update({
                "truth_classification": TRUTH_DEGRADED,
                "source_labels": ["operator_export_degraded"],
                "degraded_reason": str(exc) or exc.__class__.__name__,
            })
            return self._finalize_context(ctx)

    def _context_from_codex_artifact(self, frontmost: FrontmostApp) -> dict[str, Any] | None:
        if os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_CODEX", "1").strip().lower() in {"0", "false", "no", "off"}:
            return None
        index_path = self.codex_root / "session_index.jsonl"
        if not index_path.is_file():
            return None
        entry = latest_jsonl_object(index_path)
        thread_id = str(entry.get("id") or "").strip()
        if not thread_id:
            return None
        rollout_path = find_codex_rollout(self.codex_root, thread_id)
        session_meta, last_user_prompt, last_agent_action = parse_codex_rollout(rollout_path) if rollout_path else ({}, "", "")
        cwd = str(session_meta.get("cwd") or "").strip()
        prompt_text = last_user_prompt.strip()
        context_text = f"Codex local transcript artifact: {thread_id}"
        if rollout_path:
            context_text += f" ({rollout_path})"
        ctx = self._base_context("codex_artifact", frontmost)
        source_ref = f"local://cleanhouse/codex-session/{thread_id}"
        ctx.update({
            "source_labels": ["codex_session_index_observed"] + (["codex_rollout_observed"] if rollout_path else ["codex_rollout_missing"]),
            "truth_classification": TRUTH_OBSERVED if prompt_text else TRUTH_INFERRED,
            "tool_identity": "codex",
            "active_prompt": prompt_text[:MAX_PROMPT_CHARS],
            "active_prompt_preview": _preview(prompt_text),
            "current_objective": str(entry.get("thread_name") or _preview(prompt_text, 180) or "Codex local session").strip(),
            "current_repo": cwd,
            "last_agent_action": _preview(last_agent_action, 240),
            "session_id": thread_id,
            "objective_id": f"objective:{stable_fingerprint(thread_id, entry.get('thread_name') or prompt_text)}",
            "context": context_text[:MAX_CONTEXT_CHARS],
            "source_ref": source_ref,
            "evidence_refs": [source_ref],
            "metadata": {
                "active_context_source": "codex_artifact",
                "codex_thread_id": thread_id,
                "codex_thread_name": entry.get("thread_name", ""),
                "codex_updated_at": entry.get("updated_at", ""),
                "codex_rollout_path": str(rollout_path) if rollout_path else "",
                "transcript_refs": [source_ref],
            },
        })
        return self._finalize_context(ctx)

    def _missing_context(self, frontmost: FrontmostApp, follow_enabled: bool) -> dict[str, Any]:
        ctx = self._base_context("none", frontmost)
        labels = []
        if frontmost.status == "observed":
            labels.append("active_window_observed")
        if not follow_enabled:
            labels.append("follow_disabled")
        if frontmost.status == "degraded":
            labels.append("active_window_degraded")
        ctx.update({
            "truth_classification": TRUTH_DEGRADED if frontmost.status == "degraded" else TRUTH_MISSING,
            "source_labels": labels or ["active_context_missing"],
            "continuity_status": "missing" if frontmost.status != "degraded" else "degraded",
            "degraded_reason": frontmost.error,
        })
        return self._finalize_context(ctx)

    def _finalize_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        prompt = str(ctx.get("active_prompt") or "")
        dedupe_key = stable_fingerprint(
            ctx.get("source_type", ""),
            ctx.get("session_id", ""),
            ctx.get("current_repo", ""),
            prompt,
            ctx.get("source_ref", ""),
        )
        context_id = f"active_context:{dedupe_key}"
        evidence_refs = [
            ref for ref in ctx.get("evidence_refs", [])
            if isinstance(ref, str) and ref.startswith("local://cleanhouse/")
        ]
        evidence_ref = f"local://cleanhouse/active-context/{context_id}"
        if evidence_ref not in evidence_refs:
            evidence_refs.insert(0, evidence_ref)
        ctx["id"] = context_id
        ctx["dedupe_key"] = dedupe_key
        ctx["evidence_refs"] = evidence_refs
        ctx["attachable"] = bool(prompt and ctx.get("session_id") and ctx.get("truth_classification") in {TRUTH_OBSERVED, TRUTH_INFERRED})
        ctx.setdefault("continuity_status", "ok" if ctx["attachable"] else "missing")
        return ctx


def read_frontmost_app() -> FrontmostApp:
    if os.name != "posix":
        return FrontmostApp(status="unsupported", error="frontmost app detection is only implemented for local macOS/posix")
    script = (
        'tell application "System Events"\n'
        '  set frontApp to first application process whose frontmost is true\n'
        '  set appName to name of frontApp\n'
        '  set windowTitle to ""\n'
        '  try\n'
        '    set windowTitle to name of front window of frontApp\n'
        '  end try\n'
        '  return appName & "\\n" & windowTitle\n'
        'end tell'
    )
    completed = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
        timeout=2.0,
        check=False,
    )
    if completed.returncode != 0:
        return FrontmostApp(status="degraded", error=(completed.stderr or completed.stdout or "osascript failed").strip()[:300])
    lines = completed.stdout.splitlines()
    return FrontmostApp(
        app_name=(lines[0] if lines else "").strip(),
        window_title=(lines[1] if len(lines) > 1 else "").strip(),
        status="observed",
    )


def read_clipboard_text() -> str:
    completed = subprocess.run(
        ["pbpaste"],
        text=True,
        capture_output=True,
        timeout=1.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "pbpaste failed").strip())
    return completed.stdout or ""


def configured_pickup_paths() -> list[Path]:
    raw = os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_PICKUP_PATHS", "").strip()
    if not raw:
        return []
    return [Path(item.strip()).expanduser() for item in raw.split(",") if item.strip()]


def latest_jsonl_object(path: Path) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    try:
        size = path.stat().st_size
        if size > MAX_SESSION_INDEX_TAIL_BYTES:
            with path.open("rb") as handle:
                handle.seek(max(0, size - MAX_SESSION_INDEX_TAIL_BYTES))
                tail = handle.read().decode("utf-8", errors="ignore")
            lines = tail.splitlines()
        else:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                latest = payload
    except OSError:
        return {}
    return latest


def find_codex_rollout(codex_root: Path, thread_id: str) -> Path | None:
    roots = [
        codex_root / "sessions",
        codex_root / "archived_sessions",
    ]
    # Fast path: resolve canonical filenames without recursive scans.
    for root in roots:
        if not root.exists():
            continue
        for candidate in (
            root / f"{thread_id}.jsonl",
            root / f"{thread_id}.md.jsonl",
        ):
            if candidate.is_file():
                return candidate

    deep_scan_enabled = os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_DEEP_ROLLOUT_SCAN", "").strip().lower() in {"1", "true", "yes", "on"}
    if not deep_scan_enabled:
        return None

    for root in roots:
        if not root.exists():
            continue
        try:
            matches = sorted(root.rglob(f"*{thread_id}*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        if matches:
            return matches[0]
    return None


def parse_codex_rollout(path: Path | None) -> tuple[dict[str, Any], str, str]:
    if path is None or not path.is_file():
        return {}, "", ""
    session_meta: dict[str, Any] = {}
    last_user_prompt = ""
    last_agent_action = ""
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") == "session_meta" and isinstance(item.get("payload"), dict):
                    session_meta = item["payload"]
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                if item.get("type") == "response_item":
                    if payload.get("type") == "message":
                        role = payload.get("role")
                        text = _message_text(payload.get("content"))
                        if role == "user" and text.strip():
                            last_user_prompt = text.strip()
                        elif role == "assistant" and text.strip():
                            last_agent_action = text.strip()
                    elif payload.get("type") in {"function_call", "tool_call"}:
                        name = payload.get("name") or payload.get("call_id") or payload.get("type")
                        last_agent_action = f"{payload.get('type')}: {name}"
                elif item.get("type") == "event_msg":
                    message = str(payload.get("message") or "")
                    if message and "user_message" not in str(payload.get("type") or ""):
                        last_agent_action = message
    except OSError:
        return session_meta, last_user_prompt, last_agent_action
    return session_meta, last_user_prompt, last_agent_action


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)
