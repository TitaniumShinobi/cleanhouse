"""Apple Intelligence service boundary for evidence-backed Insight guidance."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


APPLE_INTELLIGENCE_PROVIDER = "apple_foundation_models"
HELPER_PATH = Path(__file__).with_name("apple_intelligence_helper.swift")
HELPER_TIMEOUT_SECONDS = 60
MAX_SUMMARY_CHARS = 1200
MAX_FIELD_CHARS = 512
MAX_REFS = 12
MAX_RECOMMENDATIONS = 5
MAX_LIMITATIONS = 8
NETWORK_AGGREGATE_LIMITATIONS = {
    "distribution": "Distribution owner grouping is aggregate evidence and does not prove app or process ownership.",
    "pie": "Distribution owner grouping is aggregate evidence and does not prove app or process ownership.",
}
MUTATING_RECOMMENDATION_TERMS = (
    "allow",
    "approve",
    "block",
    "change",
    "contact",
    "delete",
    "disable",
    "encrypt",
    "implement",
    "kill",
    "modify",
    "notify",
    "purge",
    "quarantine",
    "reject",
    "remove",
    "reset",
    "resolve",
    "restart",
    "revoke",
    "stop",
    "suppress",
    "terminate",
    "uninstall",
)
UNSUPPORTED_GENERATED_TERMS = (
    "account",
    "browser history",
    "credential",
    "identity",
    "malicious",
    "malware",
    "multi-factor",
    "phishing",
    "sensitive",
    "security risk",
    "suspicious",
    "transaction",
    "unauthorized",
)


def _clean_string(value: Any, *, max_len: int = MAX_FIELD_CHARS) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:max_len]


def _clean_string_list(value: Any, *, max_items: int = MAX_REFS, max_len: int = MAX_FIELD_CHARS) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_string(item, max_len=max_len)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _context_get(context: Any, field: str, default: Any = None) -> Any:
    if isinstance(context, dict):
        return context.get(field, default)
    return getattr(context, field, default)


def _bounded_network_tags(context: Any) -> dict[str, Any]:
    raw = _context_get(context, "network_tags", {})
    if not isinstance(raw, dict):
        return {}
    tags: dict[str, Any] = {}
    for field in ("status", "state", "explanation"):
        value = _clean_string(raw.get(field), max_len=160)
        if value:
            tags[field] = value
    reasons = _clean_string_list(raw.get("reasons"), max_items=8, max_len=160)
    if reasons:
        tags["reasons"] = reasons
    return tags


def bounded_evidence_context_payload(context: Any) -> dict[str, Any]:
    """Return the only evidence fields Apple Intelligence is allowed to receive."""

    payload = {
        "evidence_key": _clean_string(_context_get(context, "evidence_key"), max_len=512),
        "source_surface": _clean_string(_context_get(context, "source_surface"), max_len=64),
        "source_view": _clean_string(_context_get(context, "source_view"), max_len=64),
        "source_entity_id": _clean_string(_context_get(context, "source_entity_id"), max_len=512),
        "summary": _clean_string(_context_get(context, "summary"), max_len=MAX_SUMMARY_CHARS),
        "severity": _clean_string(_context_get(context, "severity"), max_len=64),
        "validation_state": _clean_string(_context_get(context, "validation_state"), max_len=64),
        "evidence_refs": _clean_string_list(_context_get(context, "evidence_refs"), max_items=MAX_REFS, max_len=1024),
        "timeline_event_id": _clean_string(_context_get(context, "timeline_event_id"), max_len=512),
        "open_back_route": _clean_string(_context_get(context, "open_back_route"), max_len=512),
    }
    network_tags = _bounded_network_tags(context)
    if network_tags:
        payload["network_tags"] = network_tags
    network_reasons = _clean_string_list(_context_get(context, "network_reasons"), max_items=8, max_len=240)
    if network_reasons:
        payload["network_reasons"] = network_reasons
    return payload


def _missing_refs_limitation(payload: dict[str, Any]) -> str:
    return (
        "Evidence references are missing from the resolved EvidenceContext; "
        "treat this guidance as limited until refs are attached."
    )


def _normalize_confidence(value: Any) -> str:
    text = _clean_string(value, max_len=32).lower()
    if text in {"high", "medium", "low", "unavailable"}:
        return text
    if text in {"0", "0.0"}:
        return "low"
    return "medium" if text else "low"


def _is_mutating_recommendation(value: str) -> bool:
    text = f" {value.lower()} "
    return any(f" {term} " in text or text.strip().startswith(f"{term} ") for term in MUTATING_RECOMMENDATION_TERMS)


def _payload_claim_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True).lower()


def _has_unsupported_generated_claim(value: str, payload_text: str) -> bool:
    text = value.lower()
    return any(term in text and term not in payload_text for term in UNSUPPORTED_GENERATED_TERMS)


def _read_only_recommendations(raw: Any, payload: dict[str, Any]) -> tuple[list[str], bool, bool]:
    recommendations = _clean_string_list(
        raw,
        max_items=MAX_RECOMMENDATIONS * 2,
        max_len=360,
    )
    safe: list[str] = []
    removed_mutating = False
    removed_unsupported = False
    payload_text = _payload_claim_text(payload)
    for item in recommendations:
        if _is_mutating_recommendation(item):
            removed_mutating = True
            continue
        if _has_unsupported_generated_claim(item, payload_text):
            removed_unsupported = True
            continue
        safe.append(item)
        if len(safe) >= MAX_RECOMMENDATIONS:
            break
    return safe, removed_mutating, removed_unsupported


def _safe_generated_text(value: Any, payload: dict[str, Any], *, max_len: int) -> tuple[str, bool]:
    text = _clean_string(value, max_len=max_len)
    if not text:
        return "", False
    if _has_unsupported_generated_claim(text, _payload_claim_text(payload)):
        return "", True
    return text, False


def _disabled_result(payload: dict[str, Any], reason: str, *, limitations: list[str] | None = None) -> dict[str, Any]:
    limitation_values = _clean_string_list(limitations or [], max_items=MAX_LIMITATIONS, max_len=512)
    if reason:
        limitation_values.insert(0, _clean_string(reason, max_len=512))
    aggregate_limitation = NETWORK_AGGREGATE_LIMITATIONS.get(str(payload.get("source_view") or "").lower())
    if aggregate_limitation and aggregate_limitation not in limitation_values:
        limitation_values.append(aggregate_limitation)
    if not payload.get("evidence_refs"):
        missing = _missing_refs_limitation(payload)
        if missing not in limitation_values:
            limitation_values.append(missing)
    return {
        "status": "ok",
        "insight_status": "unavailable",
        "provider": APPLE_INTELLIGENCE_PROVIDER,
        "apple_intelligence": {
            "available": False,
            "provider": APPLE_INTELLIGENCE_PROVIDER,
            "reason": _clean_string(reason, max_len=512) or "Apple Intelligence is unavailable on this runtime.",
        },
        "insight": {
            "plain_language_summary": "",
            "why_it_matters": "",
            "recommended_next_steps": [],
            "confidence": "unavailable",
            "limitations": limitation_values[:MAX_LIMITATIONS],
        },
    }


def _normalize_insight(raw: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _disabled_result(payload, "Apple Intelligence returned an invalid response shape.")
    if raw.get("status") == "unavailable":
        return _disabled_result(payload, raw.get("reason") or "Apple Intelligence is unavailable.", limitations=raw.get("limitations"))
    insight = raw.get("insight") if isinstance(raw.get("insight"), dict) else raw
    limitations = _clean_string_list(insight.get("limitations"), max_items=MAX_LIMITATIONS, max_len=512)
    if payload.get("evidence_refs"):
        limitations = [
            item for item in limitations
            if not ("evidence" in item.lower() and "ref" in item.lower() and "missing" in item.lower())
        ]
    aggregate_limitation = NETWORK_AGGREGATE_LIMITATIONS.get(str(payload.get("source_view") or "").lower())
    if aggregate_limitation and aggregate_limitation not in limitations:
        limitations.append(aggregate_limitation)
    if not payload.get("evidence_refs"):
        missing = _missing_refs_limitation(payload)
        if missing not in limitations:
            limitations.append(missing)
    next_steps, removed_mutating, removed_unsupported_steps = _read_only_recommendations(insight.get("recommended_next_steps"), payload)
    if removed_mutating:
        limitations.append("One or more mutating recommendations were removed; Insight guidance is read-only.")
    if removed_unsupported_steps:
        limitations.append("One or more recommendations were removed because they introduced unsupported claims outside the EvidenceContext.")
    plain_language_summary, removed_summary_claim = _safe_generated_text(
        insight.get("plain_language_summary"),
        payload,
        max_len=900,
    )
    why_it_matters, removed_why_claim = _safe_generated_text(
        insight.get("why_it_matters"),
        payload,
        max_len=900,
    )
    if removed_summary_claim or removed_why_claim:
        limitations.append("Some generated explanation was removed because it introduced unsupported claims outside the EvidenceContext.")
    normalized = {
        "plain_language_summary": plain_language_summary,
        "why_it_matters": why_it_matters,
        "recommended_next_steps": next_steps,
        "confidence": _normalize_confidence(insight.get("confidence")),
        "limitations": limitations[:MAX_LIMITATIONS],
    }
    if not normalized["plain_language_summary"] and not normalized["why_it_matters"] and not normalized["recommended_next_steps"]:
        return _disabled_result(payload, "Apple Intelligence returned no actionable guidance.", limitations=limitations)
    return {
        "status": "ok",
        "insight_status": "available",
        "provider": APPLE_INTELLIGENCE_PROVIDER,
        "apple_intelligence": {
            "available": True,
            "provider": APPLE_INTELLIGENCE_PROVIDER,
            "reason": "",
        },
        "insight": normalized,
    }


class AppleInsightRunner(Protocol):
    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class AppleFoundationModelsRunner:
    helper_path: Path = HELPER_PATH
    timeout_seconds: int = HELPER_TIMEOUT_SECONDS

    def _swift_command(self) -> list[str] | None:
        if platform.system() != "Darwin":
            return None
        xcrun = shutil.which("xcrun")
        if xcrun:
            return [xcrun, "swift", str(self.helper_path)]
        swift = shutil.which("swift")
        if swift:
            return [swift, str(self.helper_path)]
        return None

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        if os.getenv("CLEANHOUSE_APPLE_INTELLIGENCE_DISABLED", "").lower() in {"1", "true", "yes", "on"}:
            return {"status": "unavailable", "reason": "Apple Intelligence is disabled by CLEANHOUSE_APPLE_INTELLIGENCE_DISABLED."}
        if os.getenv("CODEX_SANDBOX") == "seatbelt":
            return {
                "status": "unavailable",
                "reason": (
                    "Apple FoundationModels cannot run from the Codex seatbelt sandbox because macOS blocks "
                    "mach lookup for com.apple.modelmanager. Launch CleanHouse from a normal Terminal/app "
                    "session to allow real Apple Intelligence generation."
                ),
            }
        if not self.helper_path.exists():
            return {"status": "unavailable", "reason": "Apple Intelligence helper is missing."}
        command = self._swift_command()
        if command is None:
            return {"status": "unavailable", "reason": "Apple Foundation Models require macOS with Swift tooling available."}
        env = os.environ.copy()
        cache_dir = Path(os.getenv("CLEANHOUSE_SWIFT_MODULE_CACHE", "/tmp/cleanhouse_swift_module_cache"))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            env.setdefault("CLANG_MODULE_CACHE_PATH", str(cache_dir))
            env.setdefault("SWIFT_MODULE_CACHE_PATH", str(cache_dir))
        except OSError:
            pass
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload, ensure_ascii=True),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"status": "unavailable", "reason": "Apple Intelligence request timed out before guidance was returned."}
        except OSError as exc:
            return {"status": "unavailable", "reason": f"Apple Intelligence helper could not start: {exc.__class__.__name__}."}
        stdout = completed.stdout.strip()
        if completed.returncode != 0:
            detail = _clean_string(completed.stderr or stdout, max_len=300)
            return {"status": "unavailable", "reason": f"Apple Foundation Models helper failed or is unsupported. {detail}".strip()}
        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError:
            return {"status": "unavailable", "reason": "Apple Intelligence helper returned unreadable output."}
        return decoded if isinstance(decoded, dict) else {"status": "unavailable", "reason": "Apple Intelligence helper returned an unsupported payload."}


class AppleIntelligenceInsightService:
    def __init__(self, runner: AppleInsightRunner | None = None):
        self.runner = runner or AppleFoundationModelsRunner()

    def generate(self, context: Any) -> dict[str, Any]:
        payload = bounded_evidence_context_payload(context)
        if not payload.get("evidence_key"):
            return _disabled_result(payload, "evidence_key is required before Apple Intelligence can run.")
        raw = self.runner.invoke(payload)
        result = _normalize_insight(raw, payload)
        result["evidence_context"] = payload
        return result

    def audit_summary(self, result: dict[str, Any]) -> dict[str, Any]:
        insight = result.get("insight") if isinstance(result.get("insight"), dict) else {}
        apple = result.get("apple_intelligence") if isinstance(result.get("apple_intelligence"), dict) else {}
        return {
            "provider": APPLE_INTELLIGENCE_PROVIDER,
            "available": bool(apple.get("available")),
            "insight_status": _clean_string(result.get("insight_status"), max_len=64),
            "plain_language_summary": _clean_string(insight.get("plain_language_summary"), max_len=300),
            "recommendation_count": len(insight.get("recommended_next_steps") or []),
            "confidence": _clean_string(insight.get("confidence"), max_len=32),
            "limitations": _clean_string_list(insight.get("limitations"), max_items=MAX_LIMITATIONS, max_len=240),
        }
