"""
In-memory CleanHouse monitoring adapter for API endpoints.

This adapter keeps the request handlers thin:
- no UI imports
- no monitor loops
- no result file writes
- native notifications are emitted only from persisted operator notifications
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set
from urllib.parse import urlencode
from backend import events as cleanhouse_events

from corefiles import config
try:
    from corefiles.notifications import NotificationManager
except Exception:
    NotificationManager = None

VALID_EVIDENCE_LEVELS = frozenset({"observed", "inferred", "unknown"})
KNOWN_TOOL_IDENTITIES = frozenset({"cursor", "opencode", "codex", "copilot"})
ISSUE_SOURCES = {"processes", "network", "ai-activity", "anomalies", "integrity", "command", "cloud-usage", "tool-event", "runtime"}
ISSUE_SEVERITIES = {"safe", "warning", "critical"}
OPERATOR_SESSION_STATES = frozenset({"active", "stopped", "finalized"})
OPERATOR_NOTIFICATION_TYPES = frozenset({
    "session_started",
    "scope_drift_detected",
    "approval_required",
    "receipt_finalized",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
})
OPERATOR_NATIVE_NOTIFICATION_TYPES = frozenset({
    "scope_drift_detected",
    "approval_required",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
})
ROLLBACK_STATES = frozenset({
    "not_requested",
    "requested_no_route",
    "requested_route_available",
    "executed_verified",
    "executed_verification_failed",
})
OPERATOR_NOTIFICATION_SEVERITIES = frozenset({"info", "warning", "critical"})
CONTINUITY_CLASSIFICATIONS = frozenset({"evidence_backed", "inferred", "degraded", "unknown"})
CONTINUITY_DECISIONS = frozenset({"accept", "ignore"})
SEVERITY_RANK = {"safe": 0, "warning": 1, "critical": 2}
CONFIDENCE_BY_SEVERITY = {"safe": 0.65, "warning": 0.72, "critical": 0.84}
MAX_ISSUES_PER_RESPONSE = 50
SEVERITY_FROM_DETECTION = {
    "critical": "critical",
    "high": "warning",
    "medium": "warning",
    "low": "safe",
}
EVIDENCE_KEY_MANAGEMENT_MODE = "local_unmanaged_ed25519_file"
EVIDENCE_KEY_MANAGEMENT_LIMITATIONS = (
    "private_key_is_local_unencrypted_file_storage",
    "bundled_public_key_requires_out_of_band_fingerprint_trust",
    "no_rotation_revocation_ca_or_hardware_backing_in_gate_a",
)
ADAPTER_SCHEMA_VERSIONS = {
    "intent": 1,
    "prompt": 1,
    "rollback": 1,
}
ADAPTER_ARTIFACT_SUBDIRS = {
    "intent": "intents",
    "prompt": "prompts",
    "rollback": "rollbacks",
}


def _evidence_key_management_profile() -> Dict[str, Any]:
    return {
        "mode": EVIDENCE_KEY_MANAGEMENT_MODE,
        "private_key_storage": "cleanhouse_data_dir_keys_file",
        "trust_model": "self_contained_bundle_signature_with_out_of_band_fingerprint_check",
        "limitations": list(EVIDENCE_KEY_MANAGEMENT_LIMITATIONS),
    }

_RUNTIME_EVENT_WRITE_FAILURES: deque[Dict[str, Any]] = deque(maxlen=50)
_RUNTIME_EVENT_WRITE_FAILURE_LOCK = threading.Lock()
_RUNTIME_EVENT_WRITE_FAILURE_TOTAL = 0


def _normalize_evidence_level(value: str) -> str:
    return value if value in VALID_EVIDENCE_LEVELS else "observed"


def _coerce_confidence(raw: Any, fallback: float) -> float:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, fallback))
    return max(0.0, min(1.0, val))


def _coerce_uncertainty(raw: Any, confidence: float) -> float:
    if raw is None:
        return round(1.0 - confidence, 3)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return round(1.0 - confidence, 3)
    return max(0.0, min(1.0, round(val, 3)))


def _stable_json_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _canonical_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("ascii")


def _canonical_json_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _json_default(value: Any) -> str:
    return str(value)


def _artifact_schema_version(artifact_type: str) -> int:
    return config.SCHEMA_VERSIONS.get(
        artifact_type,
        ADAPTER_SCHEMA_VERSIONS.get(artifact_type, 1),
    )


def _artifact_subdir(artifact_type: str) -> Optional[str]:
    return config.ARTIFACT_SUBDIRS.get(
        artifact_type,
        ADAPTER_ARTIFACT_SUBDIRS.get(artifact_type),
    )


def _safe_json_loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    if not isinstance(value, str) or not value:
        return copy.deepcopy(fallback)
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(fallback)


def _insert_runtime_event(
    *,
    event_type: str,
    path: str,
    summary: str,
    session_id: Optional[str],
    objective_id: Optional[str] = None,
    source_surface: str = "",
    actor_type: str = "",
    evidence_level: str = "observed",
    observed_vs_expected: Optional[Dict[str, Any]] = None,
    collector_status: str = "ok",
    scope_relation: str = "unknown",
    evidence_refs: Optional[Sequence[str]] = None,
    raw_evidence_ref: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a runtime event while remaining compatible with older event stores."""
    global _RUNTIME_EVENT_WRITE_FAILURE_TOTAL
    failure_context = {
        "event_type": event_type,
        "path": path,
        "summary": summary,
        "session_id": session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session"),
        "objective_id": objective_id,
        "source_surface": source_surface,
        "timestamp": _now_iso(),
    }
    try:
        cleanhouse_events.insert_event_async(
            event_type=event_type,
            path=path,
            summary=summary,
            session_id=session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session"),
            objective_id=objective_id,
            source_surface=source_surface,
            actor_type=actor_type,
            evidence_level=_normalize_evidence_level(evidence_level),
            observed_vs_expected=observed_vs_expected or {"status": "observed"},
            collector_status=collector_status,
            scope_relation=scope_relation,
            evidence_refs=list(evidence_refs or ()),
            raw_evidence_ref=raw_evidence_ref,
            data=data or {},
        )
        return
    except TypeError:
        try:
            cleanhouse_events.insert_event_async(
                event_type=event_type,
                path=path,
                summary=summary,
                session_id=session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session"),
            )
            return
        except Exception as exc:
            failure_context["legacy_fallback"] = True
            failure_context["error_type"] = exc.__class__.__name__
            failure_context["error_detail"] = str(exc) or exc.__class__.__name__
    except Exception as exc:
        failure_context["legacy_fallback"] = False
        failure_context["error_type"] = exc.__class__.__name__
        failure_context["error_detail"] = str(exc) or exc.__class__.__name__

    with _RUNTIME_EVENT_WRITE_FAILURE_LOCK:
        _RUNTIME_EVENT_WRITE_FAILURE_TOTAL += 1
        failure_context["failure_total"] = _RUNTIME_EVENT_WRITE_FAILURE_TOTAL
        _RUNTIME_EVENT_WRITE_FAILURES.append(copy.deepcopy(failure_context))


def _runtime_event_write_health() -> Dict[str, Any]:
    with _RUNTIME_EVENT_WRITE_FAILURE_LOCK:
        recent = list(_RUNTIME_EVENT_WRITE_FAILURES)
        total = _RUNTIME_EVENT_WRITE_FAILURE_TOTAL
    latest = recent[-1] if recent else None
    return {
        "status": "failure" if total else "ok",
        "collector_status": "failure" if total else "ok",
        "failure_total": total,
        "recent_failure_count": len(recent),
        "latest_failure": latest,
        "recent_failures": recent[-10:],
    }


def _reset_runtime_event_write_failures_for_tests() -> None:
    global _RUNTIME_EVENT_WRITE_FAILURE_TOTAL
    with _RUNTIME_EVENT_WRITE_FAILURE_LOCK:
        _RUNTIME_EVENT_WRITE_FAILURES.clear()
        _RUNTIME_EVENT_WRITE_FAILURE_TOTAL = 0


@dataclass(frozen=True)
class EvidenceRef:
    """Single evidence reference with source and level."""
    uri: str
    evidence_level: str = "observed"
    description: str = ""

    def __post_init__(self):
        if self.evidence_level not in VALID_EVIDENCE_LEVELS:
            object.__setattr__(self, "evidence_level", "observed")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "evidence_level": self.evidence_level,
            "description": self.description,
        }


@dataclass(frozen=True)
class CleanHouseEvent:
    """Immutable event emitted by a collector. Fields are fixed at construction."""
    event_id: str
    timestamp: str
    source: str
    severity: str
    confidence: float
    uncertainty: float
    evidence_refs: tuple[EvidenceRef, ...]
    observed_vs_expected: Dict[str, str]
    message: str
    rationale: str
    evidence_level: str
    evidence: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.event_id,
            "event_id": self.event_id,
            "source": self.source,
            "severity": self.severity,
            "message": self.message,
            "detectedAt": self.timestamp,
            "timestamp": {"start": self.timestamp, "end": self.timestamp},
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "evidence_level": self.evidence_level,
            "rationale": self.rationale,
            "observed_vs_expected": self.observed_vs_expected,
        }
        if self.evidence is not None:
            d["evidence"] = self.evidence
        return d


@dataclass(frozen=True)
class SessionEnvelope:
    """Immutable response envelope wrapping a set of events."""
    status: str
    session: Dict[str, Any]
    rationale: str
    events: tuple[CleanHouseEvent, ...]
    generated_at: str
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": self.status,
            "session": self.session,
            "rationale": self.rationale,
            "issues": [e.to_dict() for e in self.events],
            "generatedAt": self.generated_at,
        }
        if self.data is not None:
            d["data"] = self.data
        return d


@dataclass(frozen=True)
class IntentRecord:
    """Immutable record of a user-submitted intent declaration."""
    id: str
    text: str
    scope: str
    repo_path: Optional[str]
    tool_identity: str
    timestamp: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "scope": self.scope,
            "repo_path": self.repo_path,
            "tool_identity": self.tool_identity,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass(frozen=True)
class PromptContextRecord:
    """Immutable record of prompt text plus local execution context."""
    id: str
    text: str
    context: str
    scope: str
    repo_path: Optional[str]
    tool_identity: str
    session_id: str
    objective_id: Optional[str]
    prompt_type: str
    parent_intervention_id: Optional[str]
    evidence_refs: tuple[str, ...]
    metadata: Dict[str, Any]
    timestamp: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "context": self.context,
            "scope": self.scope,
            "repo_path": self.repo_path,
            "tool_identity": self.tool_identity,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "prompt_type": self.prompt_type,
            "parent_intervention_id": self.parent_intervention_id,
            "evidence_refs": list(self.evidence_refs),
            "metadata": copy.deepcopy(self.metadata),
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass(frozen=True)
class ApprovalHistoryEntry:
    """Append-only operator review event for an approval queue item."""
    id: str
    approval_id: str
    session_id: str
    receipt_id: Optional[str]
    timestamp: str
    action: str
    status: str
    previous_status: Optional[str]
    reviewer: str
    note: str
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "approval_id": self.approval_id,
            "session_id": self.session_id,
            "receipt_id": self.receipt_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "status": self.status,
            "previous_status": self.previous_status,
            "reviewer": self.reviewer,
            "note": self.note,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ApprovalQueueItem:
    """Metadata-only approval queue record. It never pauses or mutates work."""
    id: str
    session_id: str
    status: str
    requested_action: str
    reason: str
    evidence_refs: tuple[str, ...]
    prompt_id: Optional[str]
    objective_id: Optional[str]
    created_at: str
    resolved_at: Optional[str]
    resolution_note: str
    reviewer_note: str
    reviewer: str
    history: tuple[ApprovalHistoryEntry, ...]
    source: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "requested_action": self.requested_action,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "prompt_id": self.prompt_id,
            "objective_id": self.objective_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_note": self.resolution_note,
            "reviewer_note": self.reviewer_note,
            "reviewer": self.reviewer,
            "history": [entry.to_dict() for entry in self.history],
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class OperatorSessionRecord:
    """Persistent local workstation session state."""
    id: str
    session_id: str
    objective_id: Optional[str]
    status: str
    started_at: str
    stopped_at: Optional[str]
    finalized_at: Optional[str]
    summary: str
    evidence_refs: tuple[str, ...]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "status": self.status,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "finalized_at": self.finalized_at,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class OperatorNotificationRecord:
    """Persisted evidence-scoped operator notification."""
    id: str
    notification_type: str
    session_id: str
    objective_id: Optional[str]
    severity: str
    summary: str
    evidence_refs: tuple[str, ...]
    created_at: str
    acknowledged: bool
    acknowledged_at: Optional[str]
    source: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "notification_type": self.notification_type,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "severity": self.severity,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class FileEntry:
    """Single file in a snapshot."""
    path: str
    hash: str


@dataclass(frozen=True)
class FileChange:
    """Single change detected between two snapshots."""
    path: str
    change_type: str
    before_hash: Optional[str]
    after_hash: Optional[str]


@dataclass(frozen=True)
class SnapshotRecord:
    """Immutable snapshot of a directory at a point in time."""
    id: str
    repo_path: str
    label: str
    timestamp: str
    file_count: int
    files: tuple[FileEntry, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "label": self.label,
            "timestamp": self.timestamp,
            "file_count": self.file_count,
        }


@dataclass(frozen=True)
class DiffRecord:
    """Immutable diff between two snapshots."""
    id: str
    before_id: str
    after_id: str
    timestamp: str
    session_id: Optional[str]
    changes: tuple[FileChange, ...]
    created_count: int
    modified_count: int
    deleted_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "before_id": self.before_id,
            "after_id": self.after_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "created_count": self.created_count,
            "modified_count": self.modified_count,
            "deleted_count": self.deleted_count,
            "changes": [{
                "path": c.path,
                "change_type": c.change_type,
                "before_hash": c.before_hash,
                "after_hash": c.after_hash,
            } for c in self.changes],
        }


@dataclass(frozen=True)
class CorrelationEdge:
    """Single directed edge between two observables in a correlation graph."""
    source_id: str
    target_id: str
    source_type: str
    target_type: str
    relationship: str
    confidence: float
    uncertainty: float
    time_delta_seconds: Optional[float]
    observed_vs_expected: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "relationship": self.relationship,
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "time_delta_seconds": self.time_delta_seconds,
            "observed_vs_expected": self.observed_vs_expected,
        }


@dataclass(frozen=True)
class CorrelationPass:
    """Result of a correlation pass for a given session."""
    id: str
    session_id: str
    timestamp: str
    edges: tuple[CorrelationEdge, ...]
    edge_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "edge_count": self.edge_count,
            "edges": [e.to_dict() for e in self.edges],
        }


@dataclass(frozen=True)
class TimelineEntry:
    """Single entry in an immutable per-session timeline."""
    event_id: str
    timestamp: str
    event_type: str
    previous_event_id: Optional[str]
    status: str
    label: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "previous_event_id": self.previous_event_id,
            "status": self.status,
            "label": self.label,
            "data": self.data,
        }
        payload["session_id"] = self.data.get("session_id", "")
        payload["objective_id"] = self.data.get("objective_id")
        payload["source_surface"] = self.data.get("source_surface", self.event_type)
        payload["actor_type"] = self.data.get("actor_type", "unknown")
        payload["evidence_level"] = self.data.get("evidence_level", self.status)
        payload["observed_vs_expected"] = self.data.get(
            "observed_vs_expected",
            {"status": self.status, "details": self.label},
        )
        payload["collector_status"] = self.data.get("collector_status", "ok")
        payload["scope_relation"] = self.data.get("scope_relation", "unknown")
        payload["evidence_refs"] = self.data.get(
            "evidence_refs",
            [f"local://cleanhouse/timeline/{self.event_id}"],
        )
        payload["raw_evidence_ref"] = self.data.get("raw_evidence_ref", "")
        return payload


@dataclass(frozen=True)
class TimelineRecord:
    """Immutable chronological timeline for one session."""
    id: str
    session_id: str
    timestamp: str
    origin: str
    entry_count: int
    entries: tuple[TimelineEntry, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "origin": self.origin,
            "entry_count": self.entry_count,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(frozen=True)
class ClassifiedSignal:
    """Single classified signal derived from correlation + timeline analysis.

    signal_class is one of ``drift``, ``deviation``, or ``risk``.
    """
    id: str
    session_id: str
    timestamp: str
    signal_class: str
    source: str
    source_id: str
    description: str
    confidence: float
    uncertainty: float
    evidence_refs: tuple[str, ...]
    observed_vs_expected: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "signal_class": self.signal_class,
            "source": self.source,
            "source_id": self.source_id,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "evidence_refs": list(self.evidence_refs),
            "observed_vs_expected": self.observed_vs_expected,
        }


@dataclass(frozen=True)
class SignalAlert:
    """First-level alert derived from classified signals.

    alert_type is one of:
        prompt_action_mismatch — command vs intent discrepancy
        scope_expansion      — file changes outside declared scope
        endpoint_drift       — gap in observable correlation chain
    severity is one of low | medium | high.
    """
    id: str
    session_id: str
    timestamp: str
    alert_type: str
    severity: str
    source: str
    source_ids: tuple[str, ...]
    description: str
    confidence: float
    uncertainty: float
    evidence_refs: tuple[str, ...]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "source": self.source,
            "source_ids": list(self.source_ids),
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class SessionReceipt:
    """Deterministic receipt artifact for one session.

    Aggregates metadata, events, alerts, gaps, evidence index,
    and integrity chain into a single stable JSON object.
    """
    id: str
    session_id: str
    timestamp: str
    metadata: Dict[str, Any]
    summary: Dict[str, Any]
    events: tuple[Dict[str, Any], ...]
    alerts: tuple[Dict[str, Any], ...]
    gaps: tuple[Dict[str, Any], ...]
    evidence_index: tuple[Dict[str, Any], ...]
    scope_analysis: Dict[str, Any]
    integrity: Dict[str, Any]
    collector_manifest: Dict[str, Any] = field(default_factory=dict)
    runtime_gaps: tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    lineage_graph: Dict[str, Any] = field(default_factory=dict)
    drift_reasons: tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    rollback_state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "summary": self.summary,
            "events": list(self.events),
            "alerts": list(self.alerts),
            "gaps": list(self.gaps),
            "evidence_index": list(self.evidence_index),
            "scope_analysis": self.scope_analysis,
            "integrity": self.integrity,
            "collector_manifest": self.collector_manifest,
            "runtime_gaps": list(self.runtime_gaps),
            "lineage_graph": self.lineage_graph,
            "drift_reasons": list(self.drift_reasons),
            "rollback_state": self.rollback_state,
        }


@dataclass(frozen=True)
class SessionReport:
    """Immutable report wrapping a receipt with contact/target filing metadata."""
    id: str
    session_id: str
    timestamp: str
    report_type: str
    contact: str
    target: str
    context: str
    receipt: Dict[str, Any]
    evidence_links: tuple[str, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "report_type": self.report_type,
            "contact": self.contact,
            "target": self.target,
            "context": self.context,
            "receipt": self.receipt,
            "evidence_links": list(self.evidence_links),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PluginMetadata:
    """Immutable metadata for a registered source adapter plugin.

    Registration is metadata-only — no code is imported or executed.
    Must be explicitly enabled before use.
    """
    id: str
    name: str
    version: str
    description: str
    enabled: bool = True
    scope: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class ToolEvent:
    """Immutable record of a tool CLI command boundary event."""
    tool_identity: str
    command: str
    args: tuple[str, ...]
    exit_code: int
    cwd: str | None
    timestamp: str
    session_id: str | None
    duration: float | None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_identity": self.tool_identity,
            "command": self.command,
            "args": list(self.args),
            "exit_code": self.exit_code,
            "cwd": self.cwd,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "duration": self.duration,
        }


@dataclass(frozen=True)
class RollbackRecord:
    """Evidence-scoped rollback request or result."""
    id: str
    session_id: str
    objective_id: Optional[str]
    receipt_id: Optional[str]
    status: str
    requested_path: str
    snapshot_id: Optional[str]
    requested_at: str
    executed_at: Optional[str]
    evidence_refs: tuple[str, ...]
    before_hash: Optional[str]
    target_hash: Optional[str]
    after_hash: Optional[str]
    verification: Dict[str, Any]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "receipt_id": self.receipt_id,
            "status": self.status,
            "requested_path": self.requested_path,
            "snapshot_id": self.snapshot_id,
            "requested_at": self.requested_at,
            "executed_at": self.executed_at,
            "evidence_refs": list(self.evidence_refs),
            "before_hash": self.before_hash,
            "target_hash": self.target_hash,
            "after_hash": self.after_hash,
            "verification": self.verification,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class RetentionEvent:
    """Immutable record of a single retention cleanup action."""
    id: str
    timestamp: str
    artifact_type: str
    max_count: int
    before_count: int
    after_count: int
    deleted_count: int
    deleted_files: tuple[str, ...]
    operator: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "artifact_type": self.artifact_type,
            "max_count": self.max_count,
            "before_count": self.before_count,
            "after_count": self.after_count,
            "deleted_count": self.deleted_count,
            "deleted_files": list(self.deleted_files),
            "operator": self.operator,
        }


class PersistenceBackend:
    """Versioned artifact persistence to ``DATA_DIR``.

    Each artifact type (event, timeline, receipt, ...) is written as a
    versioned JSON file under ``<DATA_DIR>/<subdir>/v<N>/<id>.json``.

    Files without a ``schema_version`` field are read as v0 (old format)
    — no silent data loss.
    """

    @staticmethod
    def _ensure_dir(*parts: str) -> Path:
        path = config.DATA_DIR.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def persist(artifact_type: str, artifact_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        subdir = _artifact_subdir(artifact_type)
        if subdir is None:
            return {"status": "error", "message": f"Unknown artifact type: {artifact_type}"}
        version = _artifact_schema_version(artifact_type)
        version_dir = PersistenceBackend._ensure_dir(subdir, f"v{version}")
        payload = {
            "schema_version": version,
            "artifact_type": artifact_type,
            "created_at": _now_iso(),
            "data": data,
        }
        filename = f"{artifact_id}.json"
        tmp_path = version_dir / f".{filename}.tmp"
        final_path = version_dir / filename
        try:
            tmp_path.write_text(
                json.dumps(payload, indent=2, default=str, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.rename(final_path)
            return {"status": "ok", "path": str(final_path), "schema_version": version}
        except OSError as exc:
            return {"status": "error", "message": f"Write failed: {exc}"}

    @staticmethod
    def read(artifact_type: str, artifact_id: str) -> Dict[str, Any] | None:
        subdir = _artifact_subdir(artifact_type)
        if subdir is None:
            return None
        # Try current version first, then descend to older versions
        versions = sorted({_artifact_schema_version(artifact_type), 1}, reverse=True)
        for version in versions:
            candidate = config.DATA_DIR / subdir / f"v{version}" / f"{artifact_id}.json"
            if candidate.is_file():
                return PersistenceBackend._load_file(candidate, artifact_type)
        # Try v0 (old format, no schema_version)
        v0_candidate = config.DATA_DIR / subdir / "v0" / f"{artifact_id}.json"
        if v0_candidate.is_file():
            raw = PersistenceBackend._load_file(v0_candidate, artifact_type)
            if raw and "schema_version" not in raw:
                raw["schema_version"] = 0
                raw["v0_compat"] = True
            return raw
        return None

    @staticmethod
    def _load_file(path: Path, artifact_type: str) -> Dict[str, Any] | None:
        try:
            raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            if "schema_version" not in raw:
                raw["schema_version"] = 0
                raw["v0_compat"] = True
            if "artifact_type" not in raw:
                raw["artifact_type"] = artifact_type
            return raw
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def list_artifacts(artifact_type: str) -> list[Dict[str, Any]]:
        subdir = _artifact_subdir(artifact_type)
        if subdir is None:
            return []
        base = config.DATA_DIR / subdir
        if not base.is_dir():
            return []
        results: list[Dict[str, Any]] = []
        for vdir in sorted(base.iterdir()):
            if not vdir.is_dir() or not vdir.name.startswith("v"):
                continue
            for f in sorted(vdir.iterdir()):
                if f.suffix == ".json":
                    entry = PersistenceBackend._load_file(f, artifact_type)
                    if entry is not None:
                        results.append(entry)
        return results

    @staticmethod
    def prune(artifact_type: str, max_count: int) -> Dict[str, Any]:
        if max_count < 1:
            return {"status": "skipped", "deleted_count": 0, "before_count": 0, "after_count": 0, "max_count": max_count, "deleted_files": []}
        subdir = _artifact_subdir(artifact_type)
        if subdir is None:
            return {"status": "skipped", "deleted_count": 0, "before_count": 0, "after_count": 0, "max_count": max_count, "deleted_files": []}
        base = config.DATA_DIR / subdir
        if not base.is_dir():
            return {"status": "skipped", "deleted_count": 0, "before_count": 0, "after_count": 0, "max_count": max_count, "deleted_files": []}
        all_files: list[Path] = []
        for vdir in sorted(base.iterdir()):
            if not vdir.is_dir() or not vdir.name.startswith("v"):
                continue
            all_files.extend(sorted(vdir.iterdir(), key=lambda p: p.stat().st_mtime))
        before_count = len(all_files)
        to_delete = before_count - max_count
        if to_delete <= 0:
            return {"status": "ok", "deleted_count": 0, "before_count": before_count, "after_count": before_count, "max_count": max_count, "deleted_files": []}
        deleted_files: list[str] = []
        for f in sorted(all_files, key=lambda p: p.stat().st_mtime)[:to_delete]:
            try:
                f.unlink()
                deleted_files.append(f.name)
            except OSError:
                pass
        after_count = before_count - len(deleted_files)
        return {
            "status": "ok",
            "deleted_count": len(deleted_files),
            "before_count": before_count,
            "after_count": after_count,
            "max_count": max_count,
            "deleted_files": sorted(deleted_files),
        }


ProcessMonitor = None
DataFlowTracer = None
AgentMovementMonitor = None
SurveillanceDetector = None
IntegrityModule = None


def _get_process_monitor_class():
    global ProcessMonitor
    if ProcessMonitor is None:
        from corefiles.collectors.process_monitor import ProcessMonitor as imported_process_monitor

        ProcessMonitor = imported_process_monitor
    return ProcessMonitor


def _get_data_flow_tracer_class():
    global DataFlowTracer
    if DataFlowTracer is None:
        from corefiles.collectors.data_flow_tracer import DataFlowTracer as imported_data_flow_tracer

        DataFlowTracer = imported_data_flow_tracer
    return DataFlowTracer


def _get_agent_movement_monitor_class():
    global AgentMovementMonitor
    if AgentMovementMonitor is None:
        from corefiles.collectors.agent_movement_monitor import AgentMovementMonitor as imported_agent_movement_monitor

        AgentMovementMonitor = imported_agent_movement_monitor
    return AgentMovementMonitor


def _get_surveillance_detector_class():
    global SurveillanceDetector
    if SurveillanceDetector is None:
        from corefiles.collectors.surveillance_detector import SurveillanceDetector as imported_surveillance_detector

        SurveillanceDetector = imported_surveillance_detector
    return SurveillanceDetector


def _get_integrity_module():
    global IntegrityModule
    if IntegrityModule is None:
        from corefiles.integrity import scan_integrity as _scan_integrity
        IntegrityModule = _scan_integrity
    return IntegrityModule


from corefiles.collectors.command_observer import CommandResult, get_observer as _get_command_observer


def _now_iso() -> str:
    return datetime.now().isoformat()


def _timestamp_seconds(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        return value.timestamp()
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except (TypeError, ValueError, OSError):
        return None


def _timestamp_in_window(
    value: Any,
    window_start: Optional[str],
    window_end: Optional[str],
) -> bool:
    seconds = _timestamp_seconds(value)
    if seconds is None:
        return False
    start_seconds = _timestamp_seconds(window_start)
    end_seconds = _timestamp_seconds(window_end)
    if start_seconds is not None and seconds <= start_seconds:
        return False
    if end_seconds is not None and seconds > end_seconds:
        return False
    return True


def _coerce_issue(
    *,
    category: str,
    severity: str,
    title: str,
    details: str,
    source: str,
    confidence: Optional[float] = None,
    uncertainty: Optional[float] = None,
    evidence_refs: Optional[Sequence[str]] = None,
    rationale: Optional[str] = None,
    evidence_level: str = "observed",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_source = source if source in ISSUE_SOURCES else "anomalies"
    normalized_severity = severity if severity in ISSUE_SEVERITIES else "warning"
    message = title if not details else f"{title}: {details}"
    normalized_level = _normalize_evidence_level(evidence_level)
    fallback_confidence = CONFIDENCE_BY_SEVERITY.get(normalized_severity, 0.5)
    resolved_confidence = _coerce_confidence(confidence, fallback_confidence)
    resolved_uncertainty = _coerce_uncertainty(uncertainty, resolved_confidence)
    detected_at = _now_iso()
    fingerprint_payload = {
        "category": category,
        "source": normalized_source,
        "severity": normalized_severity,
        "message": message,
        "evidence": evidence or {},
        "confidence": resolved_confidence,
        "evidence_level": normalized_level,
        "evidence_refs": list(evidence_refs or []),
    }
    fingerprint = hashlib.sha1(
        json.dumps(fingerprint_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    event_id = f"{normalized_source}:{fingerprint}"
    raw_refs: list[str] = list(evidence_refs or [])
    raw_refs.append(f"local://cleanhouse/evidence/{event_id}.json")
    resolved_refs = tuple(
        EvidenceRef(uri=ref, evidence_level=normalized_level)
        for ref in raw_refs
    )
    event = CleanHouseEvent(
        event_id=event_id,
        timestamp=detected_at,
        source=normalized_source,
        severity=normalized_severity,
        confidence=resolved_confidence,
        uncertainty=resolved_uncertainty,
        evidence_refs=resolved_refs,
        observed_vs_expected={
            "status": normalized_level,
            "details": rationale or details or "Observed and normalized to policy schema",
        },
        message=message,
        rationale=rationale or details or title,
        evidence_level=normalized_level,
        evidence=evidence,
    )
    return event.to_dict()


def _envelope(issue_dicts: Sequence[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    status = "safe"
    for d in issue_dicts:
        status = max(status, d.get("severity", "warning"), key=lambda value: SEVERITY_RANK.get(value, 1))

    ordered = sorted(
        issue_dicts,
        key=lambda d: SEVERITY_RANK.get(d.get("severity", "warning"), 1),
        reverse=True,
    )
    returned = ordered[:MAX_ISSUES_PER_RESPONSE]
    data = dict(extra)
    if len(issue_dicts) > len(returned):
        data["issue_counts"] = {
            "total": len(issue_dicts),
            "returned": len(returned),
        }

    events = tuple(
        CleanHouseEvent(
            event_id=d.get("event_id") or d.get("id", "unknown"),
            timestamp=d.get("detectedAt", _now_iso()),
            source=d.get("source", "anomalies"),
            severity=d.get("severity", "warning"),
            confidence=d.get("confidence", 0.5),
            uncertainty=d.get("uncertainty", 0.5),
            evidence_refs=tuple(
                EvidenceRef(
                    uri=r if isinstance(r, str) else r.get("uri", str(r)),
                    evidence_level=_normalize_evidence_level(d.get("evidence_level", "observed")),
                )
                for r in d.get("evidence_refs", [])
            ),
            observed_vs_expected=d.get("observed_vs_expected", {"status": "observed", "details": ""}),
            message=d.get("message", ""),
            rationale=d.get("rationale") or d.get("message", ""),
            evidence_level=_normalize_evidence_level(d.get("evidence_level", "observed")),
            evidence=d.get("evidence"),
        )
        for d in returned
    )

    envelope = SessionEnvelope(
        status=status,
        session={
            "scope": "local",
            "mode": "observer",
            "event_count": len(issue_dicts),
        },
        rationale="aggregate rollup from normalized events",
        events=events,
        generated_at=_now_iso(),
        data=data or None,
    )
    return envelope.to_dict()


def _trim(items: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    return copy.deepcopy(items[:limit])


def _source_for_cache_key(key: str) -> str:
    if key == "ai_activity":
        return "ai-activity"
    if key == "cloud_usage":
        return "cloud-usage"
    if key == "tool_events":
        return "tool-event"
    if key in {"processes", "network", "anomalies", "integrity", "command"}:
        return key
    return "anomalies"


def _fingerprint(*values: str) -> str:
    return hashlib.sha1(":".join(values).encode("utf-8")).hexdigest()[:16]


def _destructive_command_reason(args: Sequence[str]) -> str:
    tokens = [str(arg).strip() for arg in args if str(arg).strip()]
    if not tokens:
        return ""
    command = Path(tokens[0]).name.lower()
    lowered = [token.lower() for token in tokens]
    flags = [token for token in lowered[1:] if token.startswith("-")]
    joined = " ".join(lowered)

    if command == "rm" and len(tokens) > 1:
        return "rm command removes filesystem paths"
    if command in {"unlink", "rmdir", "shred", "truncate"} and len(tokens) > 1:
        return f"{command} command mutates or removes filesystem paths"
    if command == "dd" and any(token.startswith("of=") for token in lowered[1:]):
        return "dd command writes directly to an output target"
    if command in {"mkfs", "newfs"} or command.startswith("mkfs."):
        return "filesystem format command attempted"
    if command == "diskutil" and any(token.startswith("erase") for token in lowered[1:]):
        return "disk erase command attempted"
    if command == "git" and len(lowered) > 2:
        if lowered[1] == "reset" and "--hard" in lowered[2:]:
            return "git reset --hard attempted"
        if lowered[1] == "clean" and any("f" in flag for flag in flags):
            return "git clean force attempted"
    if command in {"chmod", "chown", "chgrp"} and any("r" in flag for flag in flags):
        return f"recursive {command} attempted"
    if "rm -rf" in joined or "rm -fr" in joined:
        return "recursive forced remove attempted"
    return ""


def _normalize_endpoint_family(reason: str) -> str:
    if ":" in reason:
        return reason.split(":", 1)[0]
    return reason


def _hash_file_for_snapshot(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def _snapshot_directory(repo_path: str) -> tuple[FileEntry, ...]:
    root = Path(repo_path).resolve()
    entries: list[FileEntry] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        file_hash = _hash_file_for_snapshot(file_path)
        if file_hash is None:
            continue
        entries.append(FileEntry(
            path=str(file_path.relative_to(root)),
            hash=file_hash,
        ))
    return tuple(entries)


def _snapshot_file_contents(repo_path: str, *, max_bytes: int = 1024 * 1024) -> Dict[str, str]:
    root = Path(repo_path).resolve()
    contents: Dict[str, str] = {}
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        try:
            raw = file_path.read_bytes()
        except Exception:
            continue
        if len(raw) > max_bytes:
            continue
        contents[str(file_path.relative_to(root))] = base64.b64encode(raw).decode("ascii")
    return contents


def _compute_file_changes(
    before_files: tuple[FileEntry, ...],
    after_files: tuple[FileEntry, ...],
) -> tuple[FileChange, ...]:
    before_map = {e.path: e for e in before_files}
    after_map = {e.path: e for e in after_files}
    all_paths = sorted(set(before_map.keys()) | set(after_map.keys()))
    changes: list[FileChange] = []
    for p in all_paths:
        b = before_map.get(p)
        a = after_map.get(p)
        if b and not a:
            changes.append(FileChange(path=p, change_type="deleted", before_hash=b.hash, after_hash=None))
        elif not b and a:
            changes.append(FileChange(path=p, change_type="created", before_hash=None, after_hash=a.hash))
        elif b and a and b.hash != a.hash:
            changes.append(FileChange(path=p, change_type="modified", before_hash=b.hash, after_hash=a.hash))
    return tuple(changes)


def _cluster_key_for_path(path: str, scope_prefix: str) -> str:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    scope_parts = [part for part in scope_prefix.strip("/").split("/") if part]
    depth = max(1, len(scope_parts)) if scope_parts else 1
    return "/".join(parts[: min(depth, len(parts))])


def _build_scope_analysis(scope: str, diffs: Sequence[DiffRecord]) -> Dict[str, Any]:
    scope_prefix = scope.strip("/")
    normalized_scope = f"{scope_prefix}/" if scope_prefix else ""
    changes = [change for diff in diffs for change in diff.changes]
    clusters: dict[str, dict[str, Any]] = {}
    in_scope_count = 0
    out_of_scope_count = 0

    for change in changes:
        in_scope = bool(normalized_scope) and change.path.startswith(normalized_scope)
        if in_scope:
            in_scope_count += 1
        else:
            out_of_scope_count += 1
        cluster_key = _cluster_key_for_path(change.path, normalized_scope)
        cluster = clusters.setdefault(cluster_key, {
            "cluster": cluster_key,
            "changed_paths": [],
            "change_count": 0,
            "in_scope_count": 0,
            "out_of_scope_count": 0,
            "scope_weight": 0.0,
            "relation": "unknown",
            "explanation": "",
        })
        cluster["changed_paths"].append(change.path)
        cluster["change_count"] += 1
        if in_scope:
            cluster["in_scope_count"] += 1
        else:
            cluster["out_of_scope_count"] += 1

    total = len(changes)
    overall_weight = round(out_of_scope_count / total, 3) if total else 0.0
    cluster_list: list[dict[str, Any]] = []
    for cluster in clusters.values():
        count = cluster["change_count"]
        out_count = cluster["out_of_scope_count"]
        in_count = cluster["in_scope_count"]
        cluster["changed_paths"] = sorted(cluster["changed_paths"])
        cluster["scope_weight"] = round(out_count / count, 3) if count else 0.0
        if not normalized_scope:
            cluster["relation"] = "unknown_scope"
            cluster["explanation"] = "No declared scope prefix was recorded for this session."
        elif out_count and in_count:
            cluster["relation"] = "mixed_scope"
            cluster["explanation"] = (
                f"{out_count} of {count} change(s) in {cluster['cluster']} were outside "
                f"declared scope prefix {normalized_scope}."
            )
        elif out_count:
            cluster["relation"] = "outside_declared_scope"
            cluster["explanation"] = (
                f"{count} change(s) in {cluster['cluster']} did not match declared "
                f"scope prefix {normalized_scope}."
            )
        else:
            cluster["relation"] = "within_declared_scope"
            cluster["explanation"] = (
                f"{count} change(s) in {cluster['cluster']} matched declared "
                f"scope prefix {normalized_scope}."
            )
        cluster_list.append(cluster)

    cluster_list.sort(key=lambda item: (-item["scope_weight"], item["cluster"]))
    if not normalized_scope:
        classification = "unknown"
    elif out_of_scope_count and in_scope_count:
        classification = "mixed_scope"
    elif out_of_scope_count:
        classification = "outside_declared_scope"
    else:
        classification = "within_declared_scope"

    return {
        "declared_scope": normalized_scope,
        "classification": classification,
        "changed_paths": sorted(change.path for change in changes),
        "change_count": total,
        "in_scope_count": in_scope_count,
        "out_of_scope_count": out_of_scope_count,
        "scope_weight": overall_weight,
        "path_clusters": cluster_list,
    }


_COLLECTOR_DESCRIPTIONS = {
    "processes": "scan running processes and classify platforms",
    "network": "scan active network connections and DNS queries",
    "ai_activity": "scan for agent platform process, file, and network activity",
    "anomalies": "scan for surveillance indicators across 12 detection categories",
    "integrity": "scan file integrity against baseline",
    "command": "observe internal command execution",
    "cloud_usage": "observe cloud service usage indicators via env/config/process/network",
    "tool_events": "capture tool CLI command boundary events from Cursor/OpenCode/Codex/Copilot",
}


def _collector_failure_event(
    *,
    key: str,
    exc: Exception,
) -> Dict[str, Any]:
    source = _source_for_cache_key(key)
    reason = str(exc) or exc.__class__.__name__
    expected = _COLLECTOR_DESCRIPTIONS.get(key, "collect monitoring data")
    return _coerce_issue(
        category="collector",
        severity="critical",
        title=f"unable to execute {key}",
        details=reason,
        source=source,
        confidence=0.95,
        uncertainty=0.05,
        rationale=f"Collector '{key}' raised {exc.__class__.__name__}. Expected to {expected} but could not execute.",
        evidence_level="observed",
        evidence={
            "collector": key,
            "error_type": exc.__class__.__name__,
            "error_detail": reason,
            "expected_context": expected,
            "status": "unable to execute",
        },
    )


class CleanHouseMonitoringAdapter:
    """Collect monitoring snapshots with a small in-memory cache."""

    def __init__(self, cache_ttl_seconds: float = 10.0):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._command_buffer: deque[CommandResult] = deque(maxlen=200)
        self._intents: deque[IntentRecord] = deque(maxlen=100)
        self._prompts: deque[PromptContextRecord] = deque(maxlen=200)
        self._approval_queue: Dict[str, ApprovalQueueItem] = {}
        self._operator_sessions: Dict[str, OperatorSessionRecord] = {}
        self._operator_notifications: Dict[str, OperatorNotificationRecord] = {}
        self._snapshots: Dict[str, SnapshotRecord] = {}
        self._snapshot_contents: Dict[str, Dict[str, str]] = {}
        self._diffs: Dict[str, DiffRecord] = {}
        self._correlations: Dict[str, CorrelationPass] = {}
        self._timelines: Dict[str, TimelineRecord] = {}
        self._signals: Dict[str, ClassifiedSignal] = {}
        self._alerts: Dict[str, SignalAlert] = {}
        self._receipts: Dict[str, SessionReceipt] = {}
        self._rollback_records: Dict[str, RollbackRecord] = {}
        self._reports: Dict[str, SessionReport] = {}
        self._settings: Dict[str, Any] = copy.deepcopy(config.SETTINGS_DEFAULTS)
        self._settings_updated: str = _now_iso()
        self._settings_lock = threading.Lock()
        self._valid_collectors: Set[str] = set(config.SETTINGS_DEFAULTS["collectors"].keys())
        self._plugins: Dict[str, PluginMetadata] = {}
        self._plugins_lock = threading.Lock()
        for entry in config.PLUGIN_DEFAULTS:
            p = PluginMetadata(
                id=entry["id"],
                name=entry["name"],
                version=entry["version"],
                description=entry["description"],
                enabled=entry.get("enabled", False),
                scope=entry.get("scope", ""),
            )
            self._plugins[p.id] = p
        self._tool_events: deque[ToolEvent] = deque(maxlen=200)
        self._retention_events: deque[RetentionEvent] = deque(maxlen=config.RETENTION_EVENT_MAX)
        self.persistence_enabled: bool = True
        self._native_notification_manager: Any = None
        _get_command_observer().on_completed = self._on_command_completed

    def _on_command_completed(self, result: CommandResult) -> None:
        self._command_buffer.append(result)
        summary = f"{result.command} (rc={result.returncode})"
        command_path = result.command or " ".join(result.args)
        session_id = result.session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session")
        objective_id = result.objective_id or os.getenv("CLEANHOUSE_OBJECTIVE_ID")
        evidence_ref = f"local://cleanhouse/command/{_fingerprint(result.command, *result.args)}"
        data = {
            "command": result.command,
            "args": list(result.args),
            "cwd": result.cwd,
            "user": result.user,
            "returncode": result.returncode,
            "duration": result.duration,
            "child_pid": getattr(result, "child_pid", None),
        }
        _insert_runtime_event(
            event_type="shell_event",
            path=command_path,
            summary=f"shell_event: {summary}",
            session_id=session_id,
            objective_id=objective_id,
            source_surface="command_observer",
            actor_type="shell",
            evidence_level="observed",
            observed_vs_expected={
                "status": "matched" if result.returncode == 0 else "unexpected",
                "details": f"owned command exited {result.returncode}",
            },
            collector_status="ok",
            evidence_refs=[evidence_ref],
            raw_evidence_ref=evidence_ref,
            data=data,
        )
        _insert_runtime_event(
            event_type="process_event",
            path=command_path,
            summary=f"process_event: {summary}",
            session_id=session_id,
            objective_id=objective_id,
            source_surface="command_observer",
            actor_type="process",
            evidence_level="observed" if getattr(result, "child_pid", None) is not None else "unknown",
            observed_vs_expected={
                "status": "matched" if getattr(result, "child_pid", None) is not None else "unknown",
                "details": "child process id captured" if getattr(result, "child_pid", None) is not None else "child process id unavailable",
            },
            collector_status="ok",
            evidence_refs=[evidence_ref],
            raw_evidence_ref=evidence_ref,
            data=data,
        )
        destructive_reason = _destructive_command_reason(result.args or (result.command,))
        if destructive_reason:
            self._ensure_operator_notification(
                notification_type="destructive_command_attempt",
                session_id=session_id,
                objective_id=objective_id,
                severity="critical",
                summary=f"destructive command attempt: {summary}",
                evidence_refs=[evidence_ref],
                source="command_observer",
                metadata={
                    "command": result.command,
                    "args": list(result.args),
                    "cwd": result.cwd,
                    "returncode": result.returncode,
                    "reason": destructive_reason,
                },
            )

    def _cached(self, key: str, collector, refresh: bool = False) -> Dict[str, Any]:
        with self._lock:
            cached = self._cache.get(key)
            if not refresh and cached and (time.monotonic() - cached["cached_at"]) < self.cache_ttl_seconds:
                return copy.deepcopy(cached["value"])

        try:
            value = collector()
        except Exception as exc:
            value = _envelope(
                [_collector_failure_event(key=key, exc=exc)],
                collector_failure={
                    "source": key,
                    "error_type": exc.__class__.__name__,
                    "error_detail": str(exc) or exc.__class__.__name__,
                    "status": "unable to execute",
                },
            )
        with self._lock:
            self._cache[key] = {"cached_at": time.monotonic(), "value": copy.deepcopy(value)}
        return value

    def get_processes(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("processes", self._collect_processes, refresh=refresh)

    def get_network(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("network", self._collect_network, refresh=refresh)

    def get_ai_activity(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("ai_activity", self._collect_ai_activity, refresh=refresh)

    def get_anomalies(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("anomalies", self._collect_anomalies, refresh=refresh)

    def get_integrity(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("integrity", self._collect_integrity, refresh=refresh)

    def get_commands(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("command", self._collect_commands, refresh=refresh)

    def get_cloud_usage(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("cloud_usage", self._collect_cloud_usage, refresh=refresh)

    def get_tool_events(self, refresh: bool = False) -> Dict[str, Any]:
        return self._cached("tool_events", self._collect_tool_events, refresh=refresh)

    def submit_tool_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raw_identity = (data.get("tool_identity") or "").strip().lower()
        if not raw_identity:
            return {"status": "error", "message": "tool_identity is required"}
        tool_identity = raw_identity if raw_identity in KNOWN_TOOL_IDENTITIES else "tool_unknown"
        command = (data.get("command") or "").strip()
        if not command:
            return {"status": "error", "message": "command is required"}
        raw_args = data.get("args")
        args: tuple[str, ...] = tuple(raw_args) if isinstance(raw_args, list) else (command,)
        exit_code = int(data.get("exit_code", 0))
        cwd = (data.get("cwd") or "").strip() or None
        session_id = (data.get("session_id") or "").strip() or None
        duration = data.get("duration")
        if duration is not None:
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                duration = None

        event = ToolEvent(
            tool_identity=tool_identity,
            command=command,
            args=args,
            exit_code=exit_code,
            cwd=cwd,
            timestamp=_now_iso(),
            session_id=session_id,
            duration=duration,
        )
        self._tool_events.append(event)
        event_id = f"tool:{_fingerprint(tool_identity, command, event.timestamp)}"
        _insert_runtime_event(
            event_type="tool_event",
            path=f"/tool-events/{event_id}",
            summary=f"tool_event: {tool_identity} {command} (exit {exit_code})",
            session_id=session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session"),
            objective_id=(data.get("objective_id") or os.getenv("CLEANHOUSE_OBJECTIVE_ID") or None),
            source_surface="tool_event",
            actor_type="tool",
            evidence_level="observed",
            observed_vs_expected={
                "status": "matched" if exit_code == 0 else "unexpected",
                "details": f"tool boundary returned {exit_code}",
            },
            collector_status="ok",
            evidence_refs=[f"local://cleanhouse/tool-event/{event_id}"],
            raw_evidence_ref=f"local://cleanhouse/tool-event/{event_id}",
            data=event.to_dict(),
        )
        return {"status": "ok", "tool_identity": tool_identity, "id": event_id}

    def _collect_tool_events(self) -> Dict[str, Any]:
        events = list(self._tool_events)
        issues: List[Dict[str, Any]] = []

        for event in events:
            ref = f"local://cleanhouse/tool-event/{event.tool_identity}/{_fingerprint(event.command, event.timestamp)}"
            issues.append(
                _coerce_issue(
                    category="tool_event",
                    severity="safe",
                    title=f"tool context captured: {event.tool_identity} {event.command}",
                    details=f"Exit code {event.exit_code}",
                    source="tool-event",
                    confidence=0.95,
                    uncertainty=0.05,
                    rationale=f"Tool '{event.tool_identity}' executed '{event.command}' (exit {event.exit_code}).",
                    evidence_level="observed",
                    evidence_refs=[ref],
                    evidence=event.to_dict(),
                )
            )

        return _envelope(issues, tool_events=[e.to_dict() for e in events])

    def _event_runtime_status(self) -> Dict[str, Any]:
        runtime_event_writer = _runtime_event_write_health()
        if hasattr(cleanhouse_events, "get_runtime_status"):
            try:
                status = cleanhouse_events.get_runtime_status()
                if isinstance(status, dict):
                    status["runtime_event_writer"] = runtime_event_writer
                    return status
                return {"runtime_event_writer": runtime_event_writer}
            except Exception as exc:
                return {
                    "watcher": {"status": "unknown", "collector_status": "error", "error": str(exc)},
                    "writer": {"status": "unknown", "collector_status": "error", "error": str(exc)},
                    "runtime_event_writer": runtime_event_writer,
                }
        watcher_available = (
            getattr(cleanhouse_events, "FileSystemEventHandler", None) is not None
            and getattr(cleanhouse_events, "Observer", None) is not None
        )
        try:
            writer_metrics = cleanhouse_events.get_writer_metrics()
        except Exception:
            writer_metrics = {}
        return {
            "watcher": {
                "status": "unavailable" if not watcher_available else "unknown",
                "collector_status": "dependency_missing" if not watcher_available else "unknown",
                "dependency_available": watcher_available,
            },
            "writer": {
                "status": "unknown",
                "collector_status": "unknown",
                "metrics": writer_metrics,
            },
            "runtime_event_writer": runtime_event_writer,
        }

    @staticmethod
    def _surface_degradation_reasons(name: str, surface: Dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        status = str(surface.get("status", "unknown") or "unknown")
        collector_status = str(surface.get("collector_status", "unknown") or "unknown")
        support_status = str(surface.get("support_status", "") or "")
        degradation = surface.get("degradation")
        if isinstance(degradation, dict):
            for reason in degradation.get("reasons", []):
                if isinstance(reason, str) and reason:
                    reasons.append(reason)
                elif isinstance(reason, dict):
                    detail = reason.get("collector_status") or reason.get("surface")
                    if detail:
                        reasons.append(str(detail))
        if collector_status not in {"ok"}:
            reasons.append(collector_status)
        if status in {"unknown", "unsupported", "unavailable"}:
            reasons.append(status)
        if support_status == "unsupported":
            reasons.append("unsupported")
        return sorted({reason for reason in reasons if reason})

    def _collector_health_from_surfaces(self, surfaces: Dict[str, Any]) -> Dict[str, Any]:
        degraded_surfaces: list[Dict[str, Any]] = []
        unknown_surfaces: list[str] = []
        unsupported_surfaces: list[str] = []
        for name, surface in surfaces.items():
            if not isinstance(surface, dict):
                unknown_surfaces.append(name)
                continue
            status = str(surface.get("status", "unknown") or "unknown")
            collector_status = str(surface.get("collector_status", "unknown") or "unknown")
            support_status = str(surface.get("support_status", "") or "")
            if status == "unknown" or collector_status == "unknown":
                unknown_surfaces.append(name)
            if status == "unsupported" or support_status == "unsupported" or collector_status == "dependency_missing":
                unsupported_surfaces.append(name)
            reasons = self._surface_degradation_reasons(name, surface)
            if reasons:
                degraded_surfaces.append({
                    "surface": name,
                    "status": status,
                    "collector_status": collector_status,
                    "reasons": reasons,
                })
        return {
            "status": "degraded" if degraded_surfaces else "ok",
            "surface_count": len(surfaces),
            "healthy_count": max(0, len(surfaces) - len(degraded_surfaces)),
            "degraded_count": len(degraded_surfaces),
            "unknown": unknown_surfaces,
            "unsupported": unsupported_surfaces,
            "degraded_surfaces": degraded_surfaces,
        }

    def _collector_degradation_from_surfaces(self, surfaces: Dict[str, Any]) -> Dict[str, Any]:
        health = self._collector_health_from_surfaces(surfaces)
        degraded_surfaces = health["degraded_surfaces"]
        return {
            "status": "degraded" if degraded_surfaces else "ok",
            "degraded": bool(degraded_surfaces),
            "reasons": degraded_surfaces,
        }

    def _refresh_status_runtime_payload(self, result: Dict[str, Any]) -> None:
        data = result.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            result["data"] = data
        manifest = data.get("collector_manifest")
        if not isinstance(manifest, dict):
            manifest = {
                "schema": "cleanhouse.collector_manifest.v1",
                "generated_at": _now_iso(),
                "surfaces": {},
            }
        runtime_manifest = self._build_collector_manifest()
        runtime_surfaces = runtime_manifest.get("surfaces", {})
        surfaces = manifest.setdefault("surfaces", {})
        for name in ("filesystem_watcher", "event_writer", "runtime_event_writer"):
            if isinstance(runtime_surfaces.get(name), dict):
                surfaces[name] = runtime_surfaces[name]
        manifest["runtime"] = runtime_manifest.get("runtime", {})
        manifest["collector_health"] = self._collector_health_from_surfaces(surfaces)
        manifest["degradation"] = self._collector_degradation_from_surfaces(surfaces)
        data["collector_manifest"] = manifest
        data["runtime"] = manifest["runtime"]
        data["collector_health"] = manifest["collector_health"]
        data["degradation"] = manifest["degradation"]

    def _build_collector_manifest(
        self,
        sections: Optional[Dict[str, Any]] = None,
        section_summaries: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime_status = self._event_runtime_status()
        manifest: Dict[str, Any] = {
            "schema": "cleanhouse.collector_manifest.v1",
            "generated_at": _now_iso(),
            "surfaces": {},
            "runtime": runtime_status,
        }
        sections = sections or {}
        section_summaries = section_summaries or {}
        for name in (
            "processes",
            "network",
            "ai_activity",
            "anomalies",
            "integrity",
            "command",
            "cloud_usage",
            "tool_events",
        ):
            summary = section_summaries.get(name, {}) if isinstance(section_summaries, dict) else {}
            section = sections.get(name, {}) if isinstance(sections, dict) else {}
            issues = section.get("issues", []) if isinstance(section, dict) else []
            failure_count = 0
            if isinstance(summary, dict):
                failure_count = int(summary.get("event_counts", {}).get("collector_failures", 0) or 0)
            status = summary.get("status") if isinstance(summary, dict) else section.get("status") if isinstance(section, dict) else "unknown"
            collector_status = "ok" if (summary or section) else "unknown"
            if failure_count:
                collector_status = "failure"
            elif name == "integrity":
                integrity_scan = section.get("data", {}).get("integrity_scan", {}) if isinstance(section.get("data"), dict) else {}
                if integrity_scan.get("status") == "no_baseline":
                    collector_status = "no_baseline"
            manifest["surfaces"][name] = {
                "status": status or "unknown",
                "collector_status": collector_status,
                "issue_count": len(issues) if isinstance(issues, list) else 0,
                "collector_failures": failure_count,
            }
        watcher = runtime_status.get("watcher", {}) if isinstance(runtime_status, dict) else {}
        writer = runtime_status.get("writer", {}) if isinstance(runtime_status, dict) else {}
        manifest["surfaces"]["filesystem_watcher"] = {
            "status": watcher.get("status", "unknown"),
            "state": watcher.get("state", watcher.get("status", "unknown")),
            "collector_status": watcher.get("collector_status", "unknown"),
            "dependency_available": watcher.get("dependency_available"),
            "support_status": watcher.get("support_status", "unknown"),
            "unsupported_reason": watcher.get("unsupported_reason"),
            "watch_dir": watcher.get("watch_dir"),
            "last_error": watcher.get("last_error"),
            "degradation": watcher.get("degradation", {"degraded": False, "reasons": []}),
        }
        manifest["surfaces"]["event_writer"] = {
            "status": writer.get("status", "unknown"),
            "state": writer.get("state", writer.get("status", "unknown")),
            "collector_status": writer.get("collector_status", "unknown"),
            "support_status": writer.get("support_status", "unknown"),
            "unsupported_reason": writer.get("unsupported_reason"),
            "queue_depth": writer.get("queue_depth"),
            "queue_maxsize": writer.get("queue_maxsize"),
            "queue": writer.get("queue", {}),
            "stop_requested": writer.get("stop_requested"),
            "metrics": writer.get("metrics", {}),
            "last_error": writer.get("last_error"),
            "degradation": writer.get("degradation", {"degraded": False, "reasons": []}),
        }
        runtime_event_writer = runtime_status.get("runtime_event_writer", {}) if isinstance(runtime_status, dict) else {}
        manifest["surfaces"]["runtime_event_writer"] = {
            "status": runtime_event_writer.get("status", "unknown"),
            "collector_status": runtime_event_writer.get("collector_status", "unknown"),
            "support_status": "supported",
            "unsupported_reason": None,
            "failure_total": runtime_event_writer.get("failure_total", 0),
            "recent_failure_count": runtime_event_writer.get("recent_failure_count", 0),
            "latest_failure": runtime_event_writer.get("latest_failure"),
            "degradation": {
                "degraded": bool(runtime_event_writer.get("failure_total", 0)),
                "reasons": ["write_failures"] if runtime_event_writer.get("failure_total", 0) else [],
            },
        }
        manifest["collector_health"] = self._collector_health_from_surfaces(manifest["surfaces"])
        manifest["degradation"] = self._collector_degradation_from_surfaces(manifest["surfaces"])
        return manifest

    def get_status(self, refresh: bool = False) -> Dict[str, Any]:
        def collector() -> Dict[str, Any]:
            sections = {
                "processes": self.get_processes(refresh=refresh),
                "network": self.get_network(refresh=refresh),
                "ai_activity": self.get_ai_activity(refresh=refresh),
                "anomalies": self.get_anomalies(refresh=refresh),
                "integrity": self.get_integrity(refresh=refresh),
                "command": self.get_commands(refresh=refresh),
                "cloud_usage": self.get_cloud_usage(refresh=refresh),
                "tool_events": self.get_tool_events(refresh=refresh),
            }
            issues: List[Dict[str, Any]] = []
            for name, section in sections.items():
                for issue in section["issues"]:
                    issues.append(copy.deepcopy(issue))
            section_summaries = {}
            for name, section in sections.items():
                section_data = section.get("data", {})
                section_issue_counts = section_data.get("issue_counts", {}) if isinstance(section_data, dict) else {}
                collector_failure = section_data.get("collector_failure") if isinstance(section_data, dict) else None
                normal_issues = [
                    copy.deepcopy(issue)
                    for issue in section["issues"]
                    if issue.get("evidence", {}).get("status") != "unable to execute"
                ]
                failure_issues = [
                    copy.deepcopy(issue)
                    for issue in section["issues"]
                    if issue.get("evidence", {}).get("status") == "unable to execute"
                ]
                section_summary = {
                    "status": section["status"],
                    "issue_count": section_issue_counts.get("total", len(section["issues"])),
                    "returned_issue_count": len(section["issues"]),
                    "event_counts": {
                        "total": len(section["issues"]),
                        "collector_failures": len(failure_issues),
                        "observations": len(normal_issues),
                    },
                }
                if isinstance(collector_failure, dict):
                    section_summary["collector_failure"] = collector_failure
                section_summaries[name] = section_summary
            collector_manifest = self._build_collector_manifest(sections, section_summaries)
            runtime_status = collector_manifest.get("runtime", {}) if isinstance(collector_manifest, dict) else {}
            runtime_event_writer = runtime_status.get("runtime_event_writer", {}) if isinstance(runtime_status, dict) else {}
            if runtime_event_writer.get("failure_total", 0):
                latest_failure = runtime_event_writer.get("latest_failure") or {}
                issues.append(
                    _coerce_issue(
                        category="runtime_event_writer",
                        severity="critical",
                        title="runtime event persistence failure",
                        details=str(latest_failure.get("error_detail") or "runtime event write failed"),
                        source="runtime",
                        confidence=0.99,
                        uncertainty=0.01,
                        rationale="Runtime event write failure was caught and surfaced instead of being hidden.",
                        evidence_level="observed",
                        evidence_refs=[f"local://cleanhouse/runtime-event-writer/failure/{runtime_event_writer.get('failure_total')}"],
                        evidence={
                            "status": "unable to persist",
                            "failure_total": runtime_event_writer.get("failure_total", 0),
                            "recent_failure_count": runtime_event_writer.get("recent_failure_count", 0),
                            "latest_failure": latest_failure,
                        },
                    )
                )
            return _envelope(
                issues,
                sections=section_summaries,
                collector_manifest=collector_manifest,
                runtime=runtime_status,
                collector_health=collector_manifest.get("collector_health", {}),
                degradation=collector_manifest.get("degradation", {}),
            )

        result = self._cached("status", collector, refresh=refresh)
        self._refresh_status_runtime_payload(result)
        with self._settings_lock:
            result["settings"] = {
                name: self._settings["collectors"].get(name, True)
                for name in self._valid_collectors
            }
        with self._plugins_lock:
            plugins_list = [p.to_dict() for p in self._plugins.values()]
            result["plugins"] = {
                "count": len(plugins_list),
                "enabled_count": sum(1 for p in plugins_list if p["enabled"]),
                "entries": plugins_list,
            }
        return result

    def _persist_intent_record(self, record: IntentRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "intent",
            record.id,
            {"status": "ok", "intent": record.to_dict()},
        )

    def _intent_record_from_dict(self, intent: Dict[str, Any]) -> IntentRecord:
        return IntentRecord(
            id=str(intent.get("id", "")),
            text=str(intent.get("text", "")),
            scope=str(intent.get("scope", "")),
            repo_path=intent.get("repo_path") if intent.get("repo_path") is not None else None,
            tool_identity=str(intent.get("tool_identity", "CleanHouse")),
            timestamp=str(intent.get("timestamp", "")),
            source=str(intent.get("source", "ui")),
        )

    def _intent_records(self) -> list[IntentRecord]:
        with self._lock:
            records = {record.id: record for record in self._intents}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("intent"):
                payload = artifact.get("data", {})
                intent = payload.get("intent", payload) if isinstance(payload, dict) else None
                if not isinstance(intent, dict):
                    continue
                record = self._intent_record_from_dict(intent)
                if record.id:
                    records.setdefault(record.id, record)
        return sorted(records.values(), key=lambda record: record.timestamp)

    def _intent_record_by_id(self, record_id: str) -> Optional[IntentRecord]:
        for record in self._intent_records():
            if record.id == record_id:
                return record
        return None

    def _persist_prompt_record(self, record: PromptContextRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "prompt",
            record.id,
            {"status": "ok", "prompt": record.to_dict()},
        )

    def _prompt_record_from_dict(self, prompt: Dict[str, Any]) -> PromptContextRecord:
        prompt_type = str(prompt.get("prompt_type", "objective") or "objective")
        if prompt_type not in {"objective", "stabilization"}:
            prompt_type = "objective"
        return PromptContextRecord(
            id=str(prompt.get("id", "")),
            text=str(prompt.get("text", "")),
            context=str(prompt.get("context", "")),
            scope=str(prompt.get("scope", "")),
            repo_path=prompt.get("repo_path") if prompt.get("repo_path") is not None else None,
            tool_identity=str(prompt.get("tool_identity", "CleanHouse")),
            session_id=str(prompt.get("session_id", "")),
            objective_id=prompt.get("objective_id"),
            prompt_type=prompt_type,
            parent_intervention_id=prompt.get("parent_intervention_id"),
            evidence_refs=self._local_evidence_refs(prompt.get("evidence_refs", [])),
            metadata=copy.deepcopy(prompt.get("metadata", {})) if isinstance(prompt.get("metadata"), dict) else {},
            timestamp=str(prompt.get("timestamp", "")),
            source=str(prompt.get("source", "ui")),
        )

    def _prompt_records(self) -> list[PromptContextRecord]:
        with self._lock:
            records = {record.id: record for record in self._prompts}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("prompt"):
                payload = artifact.get("data", {})
                prompt = payload.get("prompt", payload) if isinstance(payload, dict) else None
                if not isinstance(prompt, dict):
                    continue
                record = self._prompt_record_from_dict(prompt)
                if record.id:
                    records.setdefault(record.id, record)
        return sorted(records.values(), key=lambda record: record.timestamp)

    def _prompt_records_for_session(self, session_id: str) -> list[PromptContextRecord]:
        return [record for record in self._prompt_records() if record.session_id == session_id]

    def _latest_prompt_context(self, session_id: str) -> Optional[PromptContextRecord]:
        prompts = self._prompt_records_for_session(session_id)
        return prompts[-1] if prompts else None

    def submit_intent(
        self,
        text: str,
        scope: str = "",
        repo_path: Optional[str] = None,
        tool_identity: str = "CleanHouse",
    ) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"status": "unknown", "id": None, "message": "No prompt text provided"}
        scope = scope.strip()
        now = _now_iso()
        record = IntentRecord(
            id=f"intent:{_fingerprint(text, scope, now)}",
            text=text,
            scope=scope,
            repo_path=repo_path,
            tool_identity=tool_identity,
            timestamp=now,
            source="ui",
        )
        with self._lock:
            self._intents.append(record)
        self._persist_intent_record(record)
        return {"status": "ok", "id": record.id}

    def get_intents(self) -> Dict[str, Any]:
        records = [r.to_dict() for r in reversed(self._intent_records())]
        return {"intents": records, "count": len(records)}

    def submit_prompt(
        self,
        text: str,
        context: str = "",
        scope: str = "",
        repo_path: Optional[str] = None,
        tool_identity: str = "CleanHouse",
        session_id: Optional[str] = None,
        objective_id: Optional[str] = None,
        prompt_type: str = "objective",
        parent_intervention_id: Optional[str] = None,
        evidence_refs: Optional[Sequence[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"status": "unknown", "id": None, "message": "No prompt text provided"}
        context = context.strip()
        scope = scope.strip()
        tool_identity = (tool_identity or "CleanHouse").strip() or "CleanHouse"
        prompt_type = (prompt_type or "objective").strip()
        if prompt_type not in {"objective", "stabilization"}:
            prompt_type = "objective"
        parent_intervention_id = (
            parent_intervention_id.strip()
            if isinstance(parent_intervention_id, str) and parent_intervention_id.strip()
            else None
        )
        local_evidence_refs = self._local_evidence_refs(evidence_refs or [])
        metadata = copy.deepcopy(metadata or {}) if isinstance(metadata, dict) else {}
        now = _now_iso()
        prompt_id = f"prompt:{_fingerprint(text, context, scope, now)}"
        resolved_session_id = (session_id or prompt_id).strip()
        objective = objective_id.strip() if isinstance(objective_id, str) and objective_id.strip() else None
        record = PromptContextRecord(
            id=prompt_id,
            text=text,
            context=context,
            scope=scope,
            repo_path=repo_path,
            tool_identity=tool_identity,
            session_id=resolved_session_id,
            objective_id=objective,
            prompt_type=prompt_type,
            parent_intervention_id=parent_intervention_id,
            evidence_refs=local_evidence_refs,
            metadata=metadata,
            timestamp=now,
            source="ui",
        )
        intent_record = IntentRecord(
            id=resolved_session_id,
            text=text,
            scope=scope,
            repo_path=repo_path,
            tool_identity=tool_identity,
            timestamp=now,
            source="prompt",
        )
        should_persist_intent = False
        with self._lock:
            self._prompts.append(record)
            if not any(existing.id == resolved_session_id for existing in self._intents):
                self._intents.append(intent_record)
                should_persist_intent = True
        self._persist_prompt_record(record)
        if should_persist_intent or self._intent_record_by_id(resolved_session_id) is None:
            self._persist_intent_record(intent_record)
        _insert_runtime_event(
            event_type="prompt_event",
            path=f"/prompts/{prompt_id}",
            summary=f"prompt_event: {text[:160]}",
            session_id=resolved_session_id,
            objective_id=objective,
            source_surface="prompt_context",
            actor_type="human",
            evidence_level="observed",
            observed_vs_expected={"status": "matched", "details": "prompt/context captured"},
            collector_status="ok",
            scope_relation="objective_root" if objective else "unknown",
            evidence_refs=[f"local://cleanhouse/prompt/{prompt_id}", *local_evidence_refs],
            raw_evidence_ref=f"local://cleanhouse/prompt/{prompt_id}",
            data=record.to_dict(),
        )
        return {"status": "ok", "id": prompt_id, "session_id": resolved_session_id}

    def get_prompts(
        self,
        session_id: Optional[str] = None,
        objective_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        records = self._prompt_records()
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        if objective_id:
            records = [r for r in records if r.objective_id == objective_id]
        return {
            "prompts": [r.to_dict() for r in records],
            "count": len(records),
        }

    def start_operator_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        objective_id = data.get("objective_id")
        objective_id = objective_id.strip() if isinstance(objective_id, str) and objective_id.strip() else self._objective_id_for_session(session_id)
        summary = str(data.get("summary", "")).strip() or f"session started: {session_id}"
        metadata = copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {}
        now = _now_iso()
        existing = self._operator_session_record(session_id)
        started_at = existing.started_at if existing else now
        evidence_refs = (f"local://cleanhouse/session/{session_id}",)
        record = OperatorSessionRecord(
            id=f"operator_session:{_fingerprint(session_id)}",
            session_id=session_id,
            objective_id=objective_id,
            status="active",
            started_at=started_at,
            stopped_at=None,
            finalized_at=None,
            summary=summary,
            evidence_refs=evidence_refs,
            metadata=metadata,
        )
        with self._lock:
            self._operator_sessions[session_id] = record
        self._persist_operator_session(record)
        notification = self._ensure_operator_notification(
            notification_type="session_started",
            session_id=session_id,
            objective_id=objective_id,
            severity="info",
            summary=summary,
            evidence_refs=evidence_refs,
            source="session_api",
            metadata={"session_status": "active"},
        )
        result = {"status": "ok", "session": record.to_dict()}
        if notification is not None:
            result["notification"] = notification.to_dict()
        return result

    def stop_operator_session(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        finalize = bool(data.get("finalize", False))
        existing = self._operator_session_record(session_id)
        if existing is None:
            return {"status": "not_found", "message": f"operator session not found: {session_id}"}
        now = _now_iso()
        summary = str(data.get("summary", "")).strip() or (
            f"session finalized: {session_id}" if finalize else f"session stopped: {session_id}"
        )
        metadata = copy.deepcopy(existing.metadata)
        if isinstance(data.get("metadata"), dict):
            metadata.update(copy.deepcopy(data["metadata"]))
        record = OperatorSessionRecord(
            id=existing.id,
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            status="finalized" if finalize else "stopped",
            started_at=existing.started_at,
            stopped_at=now,
            finalized_at=now if finalize else existing.finalized_at,
            summary=summary,
            evidence_refs=existing.evidence_refs,
            metadata=metadata,
        )
        with self._lock:
            self._operator_sessions[session_id] = record
        self._persist_operator_session(record)
        notifications: list[Dict[str, Any]] = []
        if finalize:
            receipt = self._latest_receipt_dict(session_id)
            if receipt is not None:
                refs = self._receipt_local_evidence_refs(receipt)
                notification = self._ensure_operator_notification(
                    notification_type="receipt_finalized",
                    session_id=session_id,
                    objective_id=existing.objective_id,
                    severity="info",
                    summary=f"receipt finalized: {receipt.get('id', '')}",
                    evidence_refs=refs,
                    source="session_api",
                    metadata={"receipt_id": receipt.get("id", "")},
                )
                if notification is not None:
                    notifications.append(notification.to_dict())
        return {"status": "ok", "session": record.to_dict(), "notifications": notifications}

    def ack_operator_notification(self, notification_id: str) -> Dict[str, Any]:
        notification_id = notification_id.strip() if isinstance(notification_id, str) else ""
        if not notification_id:
            return {"status": "error", "message": "notification_id required"}
        existing = self._operator_notification_record(notification_id)
        if existing is None:
            return {"status": "not_found", "message": f"notification not found: {notification_id}"}
        now = _now_iso()
        updated = OperatorNotificationRecord(
            id=existing.id,
            notification_type=existing.notification_type,
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            severity=existing.severity,
            summary=existing.summary,
            evidence_refs=existing.evidence_refs,
            created_at=existing.created_at,
            acknowledged=True,
            acknowledged_at=existing.acknowledged_at or now,
            source=existing.source,
            metadata=copy.deepcopy(existing.metadata),
        )
        with self._lock:
            self._operator_notifications[updated.id] = updated
        self._persist_operator_notification(updated)
        return {"status": "ok", "notification": updated.to_dict()}

    def get_operator_notifications(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        records = self._operator_notification_dicts()
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return {"notifications": records, "count": len(records)}

    def get_continuity_provenance(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        resolved_session_id = (session_id or "").strip() or self._latest_workstation_session_id()
        pins = self._continuity_artifacts("continuity_pin", resolved_session_id, "pin")
        decisions = self._continuity_artifacts("continuity_decision", resolved_session_id, "decision")
        searches = self._continuity_artifacts("continuity_search", resolved_session_id, "search")
        ignored_claim_ids = {
            str(item.get("claim_id", ""))
            for item in decisions
            if item.get("decision") == "ignore"
        }
        accepted_claim_ids = [
            str(item.get("claim_id", ""))
            for item in decisions
            if item.get("decision") == "accept"
        ]

        claims: list[Dict[str, Any]] = []
        claims.extend(self._continuity_claims_from_pins(pins, ignored_claim_ids))
        claims.extend(self._continuity_claims_from_searches(searches, ignored_claim_ids))
        claims.extend(self._continuity_claims_from_prompts(resolved_session_id, ignored_claim_ids))
        claims.extend(self._continuity_claims_from_session(resolved_session_id, ignored_claim_ids))
        claims.extend(self._continuity_metadata_claims(resolved_session_id, ignored_claim_ids))
        failed_pickups = self._continuity_failed_pickups(resolved_session_id)
        claims.extend(self._continuity_claims_from_failures(failed_pickups, ignored_claim_ids))

        if not claims:
            unknown_claim = self._continuity_claim(
                session_id=resolved_session_id,
                source_type="unknown",
                classification="unknown",
                summary="No usable continuity source recovered.",
                snippet="",
                source_ref="",
                evidence_refs=[],
                freshness_at=None,
                confidence_basis="No prompt, pin, transcript search result, memory ref, or pickup source was available.",
            )
            claims.append(unknown_claim)

        active_source = self._select_active_continuity_source(claims, accepted_claim_ids, ignored_claim_ids)
        status = self._continuity_status(claims, failed_pickups, active_source)
        return {
            "status": status,
            "session_id": resolved_session_id,
            "generated_at": _now_iso(),
            "active_source": active_source,
            "freshness": self._continuity_freshness(active_source),
            "confidence_basis": active_source.get("confidence_basis", "unavailable") if active_source else "unavailable",
            "claims": claims,
            "failed_pickups": failed_pickups,
            "manual_pins": pins,
            "decisions": decisions,
            "search_results": searches,
            "actions_available": ["accept", "ignore", "search_deeper", "pin_canonical_context"],
        }

    def pin_continuity_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        text = str(data.get("text", "")).strip()
        if not text:
            return {"status": "error", "message": "text is required"}
        operator = str(data.get("operator", "dashboard")).strip() or "dashboard"
        source_ref = str(data.get("source_ref", "")).strip()
        evidence_refs = self._local_evidence_refs(data.get("evidence_refs", []))
        now = _now_iso()
        pin_id = f"continuity_pin:{_fingerprint(session_id, text, now)}"
        claim_id = f"continuity_claim:{_fingerprint(session_id, 'manual_pin', pin_id)}"
        pin = {
            "id": pin_id,
            "claim_id": claim_id,
            "session_id": session_id,
            "objective_id": data.get("objective_id"),
            "text": text,
            "snippet": text[:500],
            "source_ref": source_ref,
            "source_type": "manual_pin",
            "classification": "evidence_backed",
            "confidence_basis": "Operator pinned this continuity context as canonical.",
            "freshness_at": now,
            "operator": operator,
            "evidence_refs": list(evidence_refs),
            "metadata": copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {},
            "created_at": now,
        }
        result = {"status": "ok", "pin": pin}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("continuity_pin", pin_id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def record_continuity_decision(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        claim_id = str(data.get("claim_id", "")).strip()
        if not claim_id:
            return {"status": "error", "message": "claim_id is required"}
        decision = str(data.get("decision", "")).strip().lower()
        if decision not in CONTINUITY_DECISIONS:
            return {"status": "error", "message": "decision must be accept or ignore"}
        operator = str(data.get("operator", "dashboard")).strip() or "dashboard"
        note = str(data.get("note", "")).strip()
        now = _now_iso()
        decision_id = f"continuity_decision:{_fingerprint(session_id, claim_id, decision, now)}"
        record = {
            "id": decision_id,
            "session_id": session_id,
            "claim_id": claim_id,
            "decision": decision,
            "operator": operator,
            "note": note,
            "created_at": now,
            "evidence_refs": list(self._local_evidence_refs(data.get("evidence_refs", []))),
            "metadata": copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {},
        }
        result = {"status": "ok", "decision": record}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("continuity_decision", decision_id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def search_continuity(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        query = str(data.get("query", "")).strip() or self._continuity_default_query(session_id)
        if not query:
            return {"status": "error", "message": "query is required"}
        max_results = max(1, min(int(data.get("max_results", 8) or 8), 20))
        max_files = max(1, min(int(data.get("max_files", 12) or 12), 40))
        max_bytes = max(1024, min(int(data.get("max_bytes", 1000000) or 1000000), 2500000))
        now = _now_iso()
        search_id = f"continuity_search:{_fingerprint(session_id, query, now)}"
        sources = self._continuity_search_sources(max_files=max_files)
        results = self._run_bounded_continuity_search(
            query=query,
            sources=sources,
            max_results=max_results,
            max_bytes=max_bytes,
            search_id=search_id,
        )
        status = "ok" if results else "no_results"
        record = {
            "id": search_id,
            "session_id": session_id,
            "query": query,
            "status": status,
            "classification": "evidence_backed" if results else "degraded",
            "searched_sources": [str(source) for source in sources],
            "result_count": len(results),
            "results": results,
            "created_at": now,
            "freshness_at": now,
            "operator": str(data.get("operator", "dashboard")).strip() or "dashboard",
            "metadata": {
                "max_results": max_results,
                "max_files": max_files,
                "max_bytes": max_bytes,
            },
        }
        persisted = {"status": status, "search": record}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("continuity_search", search_id, persisted)
            if pr["status"] != "ok":
                persisted["persistence_warning"] = pr["message"]
        return persisted

    def _continuity_artifacts(self, artifact_type: str, session_id: str, payload_key: str) -> list[Dict[str, Any]]:
        records: list[Dict[str, Any]] = []
        if not self.persistence_enabled:
            return records
        for artifact in PersistenceBackend.list_artifacts(artifact_type):
            payload = artifact.get("data", {})
            record = payload.get(payload_key, payload) if isinstance(payload, dict) else None
            if not isinstance(record, dict):
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            records.append(copy.deepcopy(record))
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records

    def _continuity_claims_from_pins(
        self,
        pins: Sequence[Dict[str, Any]],
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for pin in pins:
            claim_id = str(pin.get("claim_id") or f"continuity_claim:{_fingerprint(str(pin.get('id', '')))}")
            if claim_id in ignored_claim_ids:
                continue
            claims.append(self._continuity_claim(
                session_id=str(pin.get("session_id", "")),
                source_type="manual_pin",
                classification="evidence_backed",
                summary="Operator-pinned canonical context.",
                snippet=str(pin.get("snippet") or pin.get("text") or ""),
                source_ref=str(pin.get("source_ref", "")),
                evidence_refs=pin.get("evidence_refs", []),
                freshness_at=str(pin.get("freshness_at") or pin.get("created_at") or ""),
                confidence_basis=str(pin.get("confidence_basis") or "Operator pinned this context as canonical."),
                claim_id=claim_id,
                metadata={"pin_id": pin.get("id", ""), "operator": pin.get("operator", "")},
            ))
        return claims

    def _continuity_claims_from_searches(
        self,
        searches: Sequence[Dict[str, Any]],
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for search in searches:
            search_id = str(search.get("id", ""))
            results = search.get("results", []) if isinstance(search.get("results"), list) else []
            if results:
                for idx, result in enumerate(results[:8]):
                    claim_id = str(result.get("claim_id") or f"continuity_claim:{_fingerprint(search_id, str(idx), str(result.get('source_ref', '')))}")
                    if claim_id in ignored_claim_ids:
                        continue
                    claims.append(self._continuity_claim(
                        session_id=str(search.get("session_id", "")),
                        source_type="transcript_hit",
                        classification="evidence_backed",
                        summary=str(result.get("summary") or "Bounded continuity search recovered an exact hit."),
                        snippet=str(result.get("snippet", "")),
                        source_ref=str(result.get("source_ref", "")),
                        evidence_refs=result.get("evidence_refs", []),
                        freshness_at=str(search.get("freshness_at") or search.get("created_at") or ""),
                        confidence_basis="Exact snippet recovered by an operator-triggered bounded search.",
                        claim_id=claim_id,
                        metadata={"search_id": search_id},
                    ))
            else:
                claim_id = f"continuity_claim:{_fingerprint(search_id, 'no-results')}"
                if claim_id in ignored_claim_ids:
                    continue
                claims.append(self._continuity_claim(
                    session_id=str(search.get("session_id", "")),
                    source_type="transcript_search",
                    classification="degraded",
                    summary="No additional continuity recovered by bounded search.",
                    snippet="",
                    source_ref=search_id,
                    evidence_refs=[f"local://cleanhouse/continuity-search/{search_id}"],
                    freshness_at=str(search.get("created_at", "")),
                    confidence_basis="Operator-triggered bounded search completed with no exact continuity hit.",
                    claim_id=claim_id,
                    metadata={"search_id": search_id, "searched_sources": search.get("searched_sources", [])},
                ))
        return claims

    def _continuity_claims_from_prompts(
        self,
        session_id: str,
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for prompt in reversed(self._prompt_records_for_session(session_id)[-5:]):
            claim_id = f"continuity_claim:{_fingerprint(session_id, 'prompt', prompt.id)}"
            if claim_id in ignored_claim_ids:
                continue
            claims.append(self._continuity_claim(
                session_id=session_id,
                source_type="current_thread_context",
                classification="evidence_backed",
                summary="Current session prompt/context is available.",
                snippet=prompt.text[:500],
                source_ref=f"local://cleanhouse/prompt/{prompt.id}",
                evidence_refs=[f"local://cleanhouse/prompt/{prompt.id}", *prompt.evidence_refs],
                freshness_at=prompt.timestamp,
                confidence_basis="Prompt/context record is persisted in this CleanHouse session.",
                claim_id=claim_id,
                metadata={"prompt_id": prompt.id, "prompt_type": prompt.prompt_type, "objective_id": prompt.objective_id},
            ))
        return claims

    def _continuity_claims_from_session(
        self,
        session_id: str,
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        session = self._operator_session_record(session_id) if session_id else None
        if session is None:
            return []
        claim_id = f"continuity_claim:{_fingerprint(session_id, 'operator_session', session.id)}"
        if claim_id in ignored_claim_ids:
            return []
        return [self._continuity_claim(
            session_id=session_id,
            source_type="session_summary",
            classification="inferred",
            summary="Operator session state is available, but it is not a transcript replay.",
            snippet=session.summary,
            source_ref=f"local://cleanhouse/session/{session_id}",
            evidence_refs=session.evidence_refs,
            freshness_at=session.started_at,
            confidence_basis="Session summary can orient continuity but does not prove conversation content.",
            claim_id=claim_id,
            metadata={"session_status": session.status, "objective_id": session.objective_id},
        )]

    def _continuity_metadata_claims(
        self,
        session_id: str,
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for prompt in self._prompt_records_for_session(session_id):
            metadata = prompt.metadata if isinstance(prompt.metadata, dict) else {}
            for source_type, key in (("memory_injection", "memory_refs"), ("transcript_hit", "transcript_refs"), ("pickup", "pickup_refs")):
                refs = metadata.get(key, [])
                if isinstance(refs, str):
                    refs = [refs]
                if not isinstance(refs, list):
                    continue
                for raw_ref in refs[:8]:
                    ref = str(raw_ref).strip()
                    if not ref:
                        continue
                    claim_id = f"continuity_claim:{_fingerprint(session_id, source_type, ref)}"
                    if claim_id in ignored_claim_ids:
                        continue
                    claims.append(self._continuity_claim(
                        session_id=session_id,
                        source_type=source_type,
                        classification="evidence_backed",
                        summary=f"{source_type} reference was carried in prompt metadata.",
                        snippet=ref[:500],
                        source_ref=ref,
                        evidence_refs=[f"local://cleanhouse/prompt/{prompt.id}"],
                        freshness_at=prompt.timestamp,
                        confidence_basis="Continuity source ref was explicitly present in prompt metadata.",
                        claim_id=claim_id,
                        metadata={"prompt_id": prompt.id, "metadata_key": key},
                    ))
        return claims

    def _continuity_failed_pickups(self, session_id: str) -> list[Dict[str, Any]]:
        failures: list[Dict[str, Any]] = []
        now = _now_iso()
        configured = {
            "vvault_pickup": os.getenv("CLEANHOUSE_VVAULT_PICKUP_URL") or os.getenv("VVAULT_PICKUP_URL"),
            "chatty_pickup": os.getenv("CLEANHOUSE_CHATTY_PICKUP_URL") or os.getenv("CHATTY_PICKUP_URL"),
        }
        token = os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN") or os.getenv("VVAULT_SERVICE_TOKEN")
        for source, url in configured.items():
            if not url:
                failure_id = f"continuity_failure:{_fingerprint(session_id, source, 'not_configured')}"
                failures.append({
                    "id": failure_id,
                    "session_id": session_id,
                    "source_type": source,
                    "classification": "degraded",
                    "reason": "not_configured",
                    "detail": f"{source} endpoint is not configured for this CleanHouse runtime.",
                    "freshness_at": now,
                    "evidence_refs": [f"local://cleanhouse/continuity/{failure_id}"],
                })
            elif source == "vvault_pickup" and not token:
                failure_id = f"continuity_failure:{_fingerprint(session_id, source, 'missing_service_token')}"
                failures.append({
                    "id": failure_id,
                    "session_id": session_id,
                    "source_type": source,
                    "classification": "degraded",
                    "reason": "missing_vvault_service_token",
                    "detail": "VVAULT pickup endpoint is configured, but the service token is missing.",
                    "freshness_at": now,
                    "evidence_refs": [f"local://cleanhouse/continuity/{failure_id}"],
                })
        env_failure = os.getenv("CLEANHOUSE_CONTINUITY_PICKUP_FAILURE", "").strip()
        if env_failure:
            failure_id = f"continuity_failure:{_fingerprint(session_id, 'env_failure', env_failure)}"
            failures.append({
                "id": failure_id,
                "session_id": session_id,
                "source_type": "explicit_failure",
                "classification": "degraded",
                "reason": env_failure,
                "detail": env_failure,
                "freshness_at": now,
                "evidence_refs": [f"local://cleanhouse/continuity/{failure_id}"],
            })
        return failures

    def _continuity_claims_from_failures(
        self,
        failures: Sequence[Dict[str, Any]],
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        for failure in failures:
            claim_id = f"continuity_claim:{_fingerprint(str(failure.get('id', '')))}"
            if claim_id in ignored_claim_ids:
                continue
            claims.append(self._continuity_claim(
                session_id=str(failure.get("session_id", "")),
                source_type=str(failure.get("source_type", "pickup_failure")),
                classification="degraded",
                summary=str(failure.get("detail") or failure.get("reason") or "Continuity pickup failed."),
                snippet="",
                source_ref=str(failure.get("reason", "")),
                evidence_refs=failure.get("evidence_refs", []),
                freshness_at=str(failure.get("freshness_at", "")),
                confidence_basis="Continuity source was unavailable or failed before recovered context could be trusted.",
                claim_id=claim_id,
                metadata={"failure_id": failure.get("id", "")},
            ))
        return claims

    def _continuity_claim(
        self,
        *,
        session_id: str,
        source_type: str,
        classification: str,
        summary: str,
        snippet: str,
        source_ref: str,
        evidence_refs: Sequence[Any],
        freshness_at: Optional[str],
        confidence_basis: str,
        claim_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        classification = classification if classification in CONTINUITY_CLASSIFICATIONS else "unknown"
        claim_id = claim_id or f"continuity_claim:{_fingerprint(session_id, source_type, source_ref, summary)}"
        return {
            "id": claim_id,
            "session_id": session_id,
            "source_type": source_type,
            "classification": classification,
            "summary": summary,
            "snippet": snippet,
            "source_ref": source_ref,
            "freshness_at": freshness_at,
            "freshness": self._continuity_freshness({"freshness_at": freshness_at}),
            "confidence_basis": confidence_basis,
            "evidence_refs": list(self._local_evidence_refs(evidence_refs)),
            "metadata": copy.deepcopy(metadata or {}),
        }

    def _select_active_continuity_source(
        self,
        claims: Sequence[Dict[str, Any]],
        accepted_claim_ids: Sequence[str],
        ignored_claim_ids: Set[str],
    ) -> Dict[str, Any]:
        by_id = {str(claim.get("id", "")): claim for claim in claims}
        for claim_id in accepted_claim_ids:
            claim = by_id.get(claim_id)
            if claim is not None and claim_id not in ignored_claim_ids:
                return copy.deepcopy(claim)
        priority = {
            ("manual_pin", "evidence_backed"): 0,
            ("transcript_hit", "evidence_backed"): 1,
            ("pickup", "evidence_backed"): 2,
            ("current_thread_context", "evidence_backed"): 3,
            ("memory_injection", "evidence_backed"): 4,
            ("session_summary", "inferred"): 5,
            ("transcript_search", "degraded"): 6,
            ("vvault_pickup", "degraded"): 7,
            ("chatty_pickup", "degraded"): 8,
            ("unknown", "unknown"): 99,
        }
        candidates = [claim for claim in claims if claim.get("id") not in ignored_claim_ids]
        candidates.sort(key=lambda claim: (
            priority.get((claim.get("source_type"), claim.get("classification")), 50),
            str(claim.get("freshness_at", "")),
        ))
        return copy.deepcopy(candidates[0]) if candidates else {}

    @staticmethod
    def _continuity_status(
        claims: Sequence[Dict[str, Any]],
        failures: Sequence[Dict[str, Any]],
        active_source: Dict[str, Any],
    ) -> str:
        if not active_source or active_source.get("classification") == "unknown":
            return "unknown"
        if active_source.get("classification") == "degraded" or failures:
            return "degraded"
        if any(claim.get("classification") == "evidence_backed" for claim in claims):
            return "ok"
        return "inferred"

    @staticmethod
    def _continuity_freshness(source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        value = (source or {}).get("freshness_at") or (source or {}).get("created_at")
        if not value:
            return {"state": "unknown", "timestamp": None, "age_seconds": None}
        try:
            timestamp = datetime.fromisoformat(str(value))
            age_seconds = max(0, int((datetime.now() - timestamp).total_seconds()))
        except ValueError:
            return {"state": "unknown", "timestamp": str(value), "age_seconds": None}
        if age_seconds <= 3600:
            state = "fresh"
        elif age_seconds <= 86400:
            state = "stale"
        else:
            state = "old"
        return {"state": state, "timestamp": str(value), "age_seconds": age_seconds}

    def _continuity_default_query(self, session_id: str) -> str:
        prompt = self._latest_prompt_context(session_id)
        if prompt is not None and prompt.text:
            return prompt.text[:200]
        session = self._operator_session_record(session_id)
        if session is not None and session.summary:
            return session.summary[:200]
        return session_id

    def _continuity_search_sources(self, *, max_files: int) -> list[Path]:
        raw = os.getenv("CLEANHOUSE_CONTINUITY_SEARCH_PATHS", "").strip()
        seeds: list[Path] = []
        if raw:
            seeds.extend(Path(item.strip()).expanduser() for item in raw.split(",") if item.strip())
        else:
            seeds.extend([
                Path.home() / ".codex" / "memories" / "MEMORY.md",
                Path.home() / ".codex" / "session_index.jsonl",
            ])
        sources: list[Path] = []
        for seed in seeds:
            if len(sources) >= max_files:
                break
            try:
                resolved = seed.resolve()
            except (OSError, RuntimeError):
                continue
            if resolved.is_file():
                sources.append(resolved)
            elif resolved.is_dir():
                for candidate in sorted(resolved.rglob("*")):
                    if len(sources) >= max_files:
                        break
                    if candidate.is_file() and candidate.suffix.lower() in {".jsonl", ".md", ".txt"}:
                        sources.append(candidate)
        return sources[:max_files]

    def _run_bounded_continuity_search(
        self,
        *,
        query: str,
        sources: Sequence[Path],
        max_results: int,
        max_bytes: int,
        search_id: str,
    ) -> list[Dict[str, Any]]:
        terms = [term.lower() for term in query.split() if len(term) >= 3][:8]
        if not terms:
            terms = [query.lower()]
        results: list[Dict[str, Any]] = []
        for source in sources:
            if len(results) >= max_results:
                break
            try:
                if source.stat().st_size > max_bytes:
                    text = source.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
                else:
                    text = source.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if len(results) >= max_results:
                    break
                lowered = line.lower()
                if not any(term in lowered for term in terms):
                    continue
                result_index = len(results)
                local_ref = f"local://cleanhouse/continuity-search/{search_id}/result/{result_index}"
                results.append({
                    "id": f"{search_id}:result:{result_index}",
                    "claim_id": f"continuity_claim:{_fingerprint(search_id, str(result_index), str(source), str(lineno))}",
                    "summary": "Exact continuity search hit.",
                    "snippet": line.strip()[:500],
                    "source_ref": f"{source}:{lineno}",
                    "evidence_refs": [local_ref],
                    "classification": "evidence_backed",
                })
        return results

    def get_workstation(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        resolved_session_id = (session_id or "").strip() or self._latest_workstation_session_id()
        session_record = self._operator_session_record(resolved_session_id) if resolved_session_id else None
        session_payload = session_record.to_dict() if session_record else {
            "id": "",
            "session_id": resolved_session_id,
            "objective_id": self._objective_id_for_session(resolved_session_id) if resolved_session_id else None,
            "status": "stopped" if resolved_session_id else "unknown",
            "started_at": None,
            "stopped_at": None,
            "finalized_at": None,
            "summary": "",
            "evidence_refs": [],
            "metadata": {},
        }

        timeline_result: Dict[str, Any] = {"status": "unknown", "entries": [], "entry_count": 0}
        signals_result: Dict[str, Any] = {"status": "unknown", "signals": [], "signal_count": 0}
        alerts_result: Dict[str, Any] = {"status": "unknown", "alerts": [], "alert_count": 0}
        receipts_result: Dict[str, Any] = {"receipts": [], "count": 0}
        approvals_result: Dict[str, Any] = {"approval_queue": [], "count": 0}
        receipt_replays: Dict[str, Any] = {}
        live_events: list[Dict[str, Any]] = []

        if resolved_session_id:
            timeline_result = self.build_timeline(resolved_session_id)
            self.correlate(resolved_session_id)
            signals_result = self.classify(resolved_session_id)
            alerts_result = self.generate_alerts(resolved_session_id)
            receipts_result = self.get_receipts(session_id=resolved_session_id)
            approvals_result = self.get_approval_queue(session_id=resolved_session_id)
            for receipt in receipts_result.get("receipts", []):
                receipt_id = receipt.get("id")
                if receipt_id:
                    replay = self.replay_receipt_state(str(receipt_id))
                    if replay.get("status") == "ok":
                        receipt_replays[str(receipt_id)] = replay
            try:
                live_events = cleanhouse_events.list_events(limit=80, session_id=resolved_session_id)
            except Exception:
                live_events = []

        receipts = receipts_result.get("receipts", [])
        approvals = approvals_result.get("approval_queue", [])
        alerts = alerts_result.get("alerts", [])
        evidence_summaries = self._build_workstation_evidence_summaries(
            session_id=resolved_session_id,
            receipts=receipts,
            alerts=alerts,
            approvals=approvals,
        )
        continuity_provenance = self.get_continuity_provenance(session_id=resolved_session_id) if resolved_session_id else {
            "status": "unknown",
            "session_id": resolved_session_id,
            "failed_pickups": [],
            "claims": [],
        }
        if resolved_session_id:
            self._derive_workstation_notifications(
                session_id=resolved_session_id,
                objective_id=session_payload.get("objective_id"),
                receipts=receipts,
                alerts=alerts,
                approvals=approvals,
                evidence_summaries=evidence_summaries,
            )
            self._ensure_continuity_degraded_notification(
                session_id=resolved_session_id,
                objective_id=session_payload.get("objective_id"),
                provenance=continuity_provenance,
            )

        notifications = self.get_operator_notifications(session_id=resolved_session_id).get("notifications", [])
        objectives = self._workstation_objectives(resolved_session_id)
        mutations = self._workstation_mutations(resolved_session_id, timeline_result, live_events)
        operational_presence = self._build_operational_presence(
            session=session_payload,
            objectives=objectives,
            mutations=mutations,
            approvals=approvals,
            notifications=notifications,
            evidence_summaries=evidence_summaries,
            timeline=timeline_result,
            live_events=live_events,
        )
        return {
            "status": "ok",
            "session": session_payload,
            "operational_presence": operational_presence,
            "continuity_provenance": continuity_provenance,
            "objectives": objectives,
            "live_events": live_events,
            "mutations": mutations,
            "deviation_signals": {
                "signals": signals_result.get("signals", []),
                "alerts": alerts,
                "signal_count": signals_result.get("signal_count", len(signals_result.get("signals", []))),
                "alert_count": alerts_result.get("alert_count", len(alerts)),
            },
            "receipts": receipts,
            "approvals": approvals,
            "notifications": notifications,
            "evidence_summaries": evidence_summaries,
            "receipt_replays": receipt_replays,
            "timeline": timeline_result,
        }

    def _build_operational_presence(
        self,
        *,
        session: Dict[str, Any],
        objectives: Sequence[Dict[str, Any]],
        mutations: Sequence[Dict[str, Any]],
        approvals: Sequence[Dict[str, Any]],
        notifications: Sequence[Dict[str, Any]],
        evidence_summaries: Sequence[Dict[str, Any]],
        timeline: Dict[str, Any],
        live_events: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        session_id = str(session.get("session_id") or "")
        session_status = str(session.get("status") or "unknown")
        pending_approvals = [
            item for item in approvals
            if item.get("status") in {"pending", "needs_review"}
        ]
        unacked_notifications = [
            item for item in notifications
            if not item.get("acknowledged")
        ]
        drift_summaries = [
            item for item in evidence_summaries
            if item.get("summary_type") == "scope_drift"
        ]
        critical_notifications = [
            item for item in unacked_notifications
            if item.get("severity") == "critical"
        ]
        other_notifications = [
            item for item in unacked_notifications
            if item not in critical_notifications
        ]
        latest_objective = objectives[0] if objectives else None
        timeline_entries = timeline.get("entries", []) if isinstance(timeline, dict) else []
        counts = {
            "objectives": len(objectives),
            "recent_mutations": len(mutations),
            "timeline_entries": len(timeline_entries),
            "pending_approvals": len(pending_approvals),
            "unacknowledged_notifications": len(unacked_notifications),
            "scope_drift_summaries": len(drift_summaries),
            "live_events": len(live_events),
        }

        focus: Dict[str, Any] = {}
        evidence_refs: tuple[str, ...] = ()
        interrupt = False
        priority = "info"

        if not session_id:
            state = "idle"
            summary = "No operator session is selected."
            next_action = "Start a session and declare the objective before leaving CleanHouse running."
        elif session_status == "active" and latest_objective is None:
            state = "waiting_for_objective"
            summary = "Session is active, but no objective is attached."
            next_action = "Declare the objective and allowed scope so CleanHouse can watch the work in context."
            priority = "warning"
        elif pending_approvals:
            first = pending_approvals[0]
            state = "attention_required"
            summary = f"{len(pending_approvals)} approval record(s) need operator review."
            next_action = str(first.get("requested_action") or "Review the pending approval.")
            focus = {
                "type": "approval",
                "id": first.get("id", ""),
                "status": first.get("status", ""),
                "reason": first.get("reason", ""),
            }
            evidence_refs = self._local_evidence_refs(first.get("evidence_refs", []))
            interrupt = True
            priority = "warning"
        elif drift_summaries:
            first = drift_summaries[0]
            state = "attention_required"
            summary = str(first.get("summary") or "Scope drift evidence needs review.")
            next_action = "Inspect why CleanHouse flagged the drift before accepting the work."
            focus = {
                "type": "scope_drift",
                "id": first.get("id", ""),
                "receipt_id": first.get("receipt_id", ""),
                "scope_weight": first.get("scope_weight"),
            }
            evidence_refs = self._local_evidence_refs(first.get("evidence_refs", []))
            interrupt = True
            priority = "warning"
        elif critical_notifications:
            first = critical_notifications[0]
            state = "attention_required"
            summary = str(first.get("summary") or "Critical notification needs review.")
            next_action = "Open the notification evidence and acknowledge it when understood."
            focus = {
                "type": "notification",
                "id": first.get("id", ""),
                "notification_type": first.get("notification_type", ""),
                "severity": first.get("severity", ""),
            }
            evidence_refs = self._local_evidence_refs(first.get("evidence_refs", []))
            interrupt = True
            priority = "critical"
        elif session_status == "active":
            state = "watching_changes" if mutations else "watching"
            if mutations:
                summary = f"Watching the active objective with {len(mutations)} recent mutation(s) in view."
            else:
                summary = "Watching the active objective; no operator action is pending."
            next_action = "No operator action needed unless CleanHouse raises a notification or approval."
            focus = {
                "type": "objective",
                "id": latest_objective.get("id", "") if latest_objective else "",
                "scope": latest_objective.get("scope", "") if latest_objective else "",
            }
            priority = "clear"
        else:
            state = "idle"
            summary = f"Session is {session_status}."
            next_action = "Start or resume a session before relying on live operational guidance."

        if not evidence_refs:
            refs: list[str] = []
            for item in [focus, *(unacked_notifications[:2]), *(drift_summaries[:2]), *(pending_approvals[:2])]:
                if isinstance(item, dict):
                    refs.extend(item.get("evidence_refs", []) or [])
            evidence_refs = self._local_evidence_refs(refs)
        primary_intervention = self._build_primary_intervention(
            session_id=session_id,
            objective=latest_objective,
            pending_approvals=pending_approvals,
            drift_summaries=drift_summaries,
            critical_notifications=critical_notifications,
            other_notifications=other_notifications,
            notifications=notifications,
        )

        return {
            "state": state,
            "priority": priority,
            "interrupt": interrupt,
            "quiet": not interrupt,
            "summary": summary,
            "next_action": next_action,
            "session_id": session_id,
            "session_status": session_status,
            "objective": {
                "id": latest_objective.get("id", ""),
                "text": latest_objective.get("text", ""),
                "scope": latest_objective.get("scope", ""),
                "tool_identity": latest_objective.get("tool_identity", ""),
            } if latest_objective else None,
            "focus": focus,
            "primary_intervention": primary_intervention,
            "open_counts": counts,
            "last_activity_at": self._presence_latest_timestamp(
                mutations,
                live_events,
                timeline_entries,
                notifications,
                [session],
            ),
            "evidence_refs": list(evidence_refs[:8]),
        }

    def _build_primary_intervention(
        self,
        *,
        session_id: str,
        objective: Optional[Dict[str, Any]],
        pending_approvals: Sequence[Dict[str, Any]],
        drift_summaries: Sequence[Dict[str, Any]],
        critical_notifications: Sequence[Dict[str, Any]],
        other_notifications: Sequence[Dict[str, Any]],
        notifications: Sequence[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        if pending_approvals:
            approval = pending_approvals[0]
            refs = self._local_evidence_refs(approval.get("evidence_refs", []))
            notification = self._matching_notification(
                notifications,
                metadata_key="approval_id",
                metadata_value=approval.get("id", ""),
                evidence_refs=refs,
            )
            return self._primary_intervention_payload(
                intervention_type="approval",
                session_id=session_id,
                objective=objective,
                approval_id=str(approval.get("id", "")),
                notification_id=str((notification or {}).get("id", "")),
                receipt_id=str(approval.get("metadata", {}).get("receipt_id", "")) if isinstance(approval.get("metadata"), dict) else "",
                summary=str(approval.get("requested_action") or "approval requires operator review"),
                reason=str(approval.get("reason") or "pending approval requires stabilization"),
                evidence_refs=refs,
            )
        if drift_summaries:
            drift = drift_summaries[0]
            refs = self._local_evidence_refs(drift.get("evidence_refs", []))
            receipt_id = str(drift.get("receipt_id", ""))
            notification = self._matching_notification(
                notifications,
                metadata_key="receipt_id",
                metadata_value=receipt_id,
                notification_type="scope_drift_detected",
                evidence_refs=refs,
            )
            return self._primary_intervention_payload(
                intervention_type="scope_drift",
                session_id=session_id,
                objective=objective,
                approval_id="",
                notification_id=str((notification or {}).get("id", "")),
                receipt_id=receipt_id,
                summary=str(drift.get("summary") or "scope drift needs operator review"),
                reason=str(drift.get("rationale") or drift.get("classification") or "scope drift evidence lowered operator confidence"),
                evidence_refs=refs,
            )
        for notification in [*critical_notifications, *other_notifications]:
            refs = self._local_evidence_refs(notification.get("evidence_refs", []))
            metadata = notification.get("metadata", {}) if isinstance(notification.get("metadata"), dict) else {}
            return self._primary_intervention_payload(
                intervention_type="notification",
                session_id=session_id,
                objective=objective,
                approval_id=str(metadata.get("approval_id", "")),
                notification_id=str(notification.get("id", "")),
                receipt_id=str(metadata.get("receipt_id", "")),
                summary=str(notification.get("summary") or "notification needs operator review"),
                reason=str(notification.get("notification_type") or "unacknowledged notification"),
                evidence_refs=refs,
            )
        return None

    def _matching_notification(
        self,
        notifications: Sequence[Dict[str, Any]],
        *,
        metadata_key: str,
        metadata_value: Any,
        evidence_refs: Sequence[str],
        notification_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if metadata_value:
            for notification in notifications:
                metadata = notification.get("metadata", {}) if isinstance(notification.get("metadata"), dict) else {}
                if notification_type and notification.get("notification_type") != notification_type:
                    continue
                if metadata.get(metadata_key) == metadata_value:
                    return notification
        ref_set = set(evidence_refs)
        if not ref_set:
            return None
        for notification in notifications:
            if notification_type and notification.get("notification_type") != notification_type:
                continue
            if ref_set.intersection(self._local_evidence_refs(notification.get("evidence_refs", []))):
                return notification
        return None

    def _primary_intervention_payload(
        self,
        *,
        intervention_type: str,
        session_id: str,
        objective: Optional[Dict[str, Any]],
        approval_id: str,
        notification_id: str,
        receipt_id: str,
        summary: str,
        reason: str,
        evidence_refs: Sequence[str],
    ) -> Dict[str, Any]:
        refs = self._local_evidence_refs(evidence_refs)
        return {
            "type": intervention_type,
            "approval_id": approval_id,
            "notification_id": notification_id,
            "receipt_id": receipt_id,
            "summary": summary,
            "reason": reason,
            "evidence_refs": list(refs),
            "draft_correction_prompt": self._draft_correction_prompt(
                session_id=session_id,
                objective=objective,
                intervention_type=intervention_type,
                summary=summary,
                reason=reason,
                evidence_refs=refs,
            ),
        }

    @staticmethod
    def _draft_correction_prompt(
        *,
        session_id: str,
        objective: Optional[Dict[str, Any]],
        intervention_type: str,
        summary: str,
        reason: str,
        evidence_refs: Sequence[str],
    ) -> str:
        objective_text = str((objective or {}).get("text") or "current objective")
        scope = str((objective or {}).get("scope") or "declared scope unavailable")
        refs = ", ".join(evidence_refs[:6]) if evidence_refs else "local evidence refs unavailable"
        return (
            f"Stabilize CleanHouse session {session_id}. "
            f"Continue the objective only inside declared scope: {scope}. "
            f"Objective: {objective_text}. "
            f"Operator intervention: {intervention_type} - {summary}. "
            f"Reason: {reason}. "
            f"Use these evidence refs before continuing: {refs}. "
            "Pause any scope expansion until the operator approves it."
        )

    @staticmethod
    def _presence_latest_timestamp(*groups: Sequence[Dict[str, Any]]) -> Optional[str]:
        timestamps: list[str] = []
        for group in groups:
            for item in group or []:
                if not isinstance(item, dict):
                    continue
                for key in ("timestamp", "created_at", "started_at", "stopped_at", "finalized_at"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        timestamps.append(value)
                        break
        if not timestamps:
            return None
        return sorted(timestamps)[-1]

    def _operator_session_record(self, session_id: str) -> Optional[OperatorSessionRecord]:
        if not session_id:
            return None
        with self._lock:
            existing = self._operator_sessions.get(session_id)
        if existing is not None:
            return existing
        if not self.persistence_enabled:
            return None
        artifact = PersistenceBackend.read("operator_session", f"operator_session:{_fingerprint(session_id)}")
        if not artifact:
            return None
        payload = artifact.get("data", {})
        session = payload.get("session", payload) if isinstance(payload, dict) else None
        if not isinstance(session, dict):
            return None
        record = self._operator_session_from_dict(session)
        with self._lock:
            self._operator_sessions[record.session_id] = record
        return record

    def _operator_session_from_dict(self, session: Dict[str, Any]) -> OperatorSessionRecord:
        status = str(session.get("status", "stopped"))
        if status not in OPERATOR_SESSION_STATES:
            status = "stopped"
        return OperatorSessionRecord(
            id=str(session.get("id", f"operator_session:{_fingerprint(session.get('session_id', ''))}")),
            session_id=str(session.get("session_id", "")),
            objective_id=session.get("objective_id"),
            status=status,
            started_at=str(session.get("started_at", "")),
            stopped_at=session.get("stopped_at"),
            finalized_at=session.get("finalized_at"),
            summary=str(session.get("summary", "")),
            evidence_refs=tuple(str(ref) for ref in session.get("evidence_refs", [])),
            metadata=copy.deepcopy(session.get("metadata", {})) if isinstance(session.get("metadata"), dict) else {},
        )

    def _persist_operator_session(self, record: OperatorSessionRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "operator_session",
            record.id,
            {"status": "ok", "session": record.to_dict()},
        )

    def _operator_notification_record(self, notification_id: str) -> Optional[OperatorNotificationRecord]:
        with self._lock:
            existing = self._operator_notifications.get(notification_id)
        if existing is not None:
            return existing
        if not self.persistence_enabled:
            return None
        artifact = PersistenceBackend.read("operator_notification", notification_id)
        if not artifact:
            return None
        payload = artifact.get("data", {})
        notification = payload.get("notification", payload) if isinstance(payload, dict) else None
        if not isinstance(notification, dict):
            return None
        record = self._operator_notification_from_dict(notification)
        with self._lock:
            self._operator_notifications[record.id] = record
        return record

    def _operator_notification_from_dict(self, notification: Dict[str, Any]) -> OperatorNotificationRecord:
        ntype = str(notification.get("notification_type", "")) or "unknown"
        severity = str(notification.get("severity", "info"))
        if severity not in OPERATOR_NOTIFICATION_SEVERITIES:
            severity = "info"
        return OperatorNotificationRecord(
            id=str(notification.get("id", "")),
            notification_type=ntype,
            session_id=str(notification.get("session_id", "")),
            objective_id=notification.get("objective_id"),
            severity=severity,
            summary=str(notification.get("summary", "")),
            evidence_refs=tuple(str(ref) for ref in notification.get("evidence_refs", [])),
            created_at=str(notification.get("created_at", "")),
            acknowledged=bool(notification.get("acknowledged", False)),
            acknowledged_at=notification.get("acknowledged_at"),
            source=str(notification.get("source", "workstation")),
            metadata=copy.deepcopy(notification.get("metadata", {})) if isinstance(notification.get("metadata"), dict) else {},
        )

    def _operator_notification_dicts(self) -> list[Dict[str, Any]]:
        with self._lock:
            records = {record.id: record.to_dict() for record in self._operator_notifications.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("operator_notification"):
                payload = artifact.get("data", {})
                notification = payload.get("notification", payload) if isinstance(payload, dict) else None
                if isinstance(notification, dict):
                    records.setdefault(str(notification.get("id", "")), notification)
        return [record for record in records.values() if record.get("id")]

    def _operator_notification_by_evidence_refs(
        self,
        notification_type: str,
        session_id: str,
        local_refs: Sequence[str],
    ) -> Optional[OperatorNotificationRecord]:
        evidence_key = tuple(sorted(str(ref) for ref in local_refs))
        for notification in self._operator_notification_dicts():
            if (
                str(notification.get("notification_type", "")) == notification_type
                and str(notification.get("session_id", "")) == session_id
                and tuple(sorted(str(ref) for ref in notification.get("evidence_refs", []))) == evidence_key
            ):
                return self._operator_notification_from_dict(notification)
        return None

    def _persist_operator_notification(self, record: OperatorNotificationRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "operator_notification",
            record.id,
            {"status": "ok", "notification": record.to_dict()},
        )

    def _local_evidence_refs(self, evidence_refs: Sequence[Any]) -> tuple[str, ...]:
        refs: list[str] = []
        seen: set[str] = set()
        for raw in evidence_refs:
            ref = str(raw).strip()
            if not ref or not ref.startswith("local://cleanhouse/") or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return tuple(refs)

    def _ensure_operator_notification(
        self,
        *,
        notification_type: str,
        session_id: str,
        objective_id: Optional[str],
        severity: str,
        summary: str,
        evidence_refs: Sequence[Any],
        source: str = "workstation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[OperatorNotificationRecord]:
        if notification_type not in OPERATOR_NOTIFICATION_TYPES:
            return None
        local_refs = self._local_evidence_refs(evidence_refs)
        if not session_id or not local_refs:
            return None
        if severity not in OPERATOR_NOTIFICATION_SEVERITIES:
            severity = "info"
        existing_by_evidence = self._operator_notification_by_evidence_refs(
            notification_type,
            session_id,
            local_refs,
        )
        if existing_by_evidence is not None:
            return existing_by_evidence
        stable_id = f"notification:{_fingerprint(notification_type, session_id, *sorted(local_refs))}"
        existing = self._operator_notification_record(stable_id)
        if existing is not None:
            return existing
        now = _now_iso()
        record_metadata = copy.deepcopy(metadata or {})
        record_metadata.setdefault("click_url", self._operator_notification_click_url(session_id, stable_id))
        record = OperatorNotificationRecord(
            id=stable_id,
            notification_type=notification_type,
            session_id=session_id,
            objective_id=objective_id,
            severity=severity,
            summary=summary,
            evidence_refs=local_refs,
            created_at=now,
            acknowledged=False,
            acknowledged_at=None,
            source=source,
            metadata=record_metadata,
        )
        with self._lock:
            self._operator_notifications[record.id] = record
        self._persist_operator_notification(record)
        self._dispatch_native_operator_notification(record)
        try:
            cleanhouse_events.insert_event_async(
                event_type=notification_type,
                path=f"/notifications/{record.id}",
                summary=f"{notification_type}: {summary[:160]}",
                session_id=session_id,
            )
        except Exception:
            pass
        return record

    def _operator_notification_click_url(self, session_id: str, notification_id: str) -> str:
        base = os.getenv("CLEANHOUSE_DASHBOARD_URL", "http://localhost:3333/dashboard").strip()
        if not base:
            base = "http://localhost:3333/dashboard"
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}{urlencode({'session_id': session_id, 'notification_id': notification_id})}"

    def _dispatch_native_operator_notification(self, record: OperatorNotificationRecord) -> None:
        if record.notification_type not in OPERATOR_NATIVE_NOTIFICATION_TYPES:
            return
        if NotificationManager is None:
            return
        if os.getenv("CLEANHOUSE_NATIVE_NOTIFICATIONS", "1").strip().lower() in {"0", "false", "no", "off"}:
            return
        try:
            if self._native_notification_manager is None:
                self._native_notification_manager = NotificationManager()
            click_url = str(record.metadata.get("click_url") or self._operator_notification_click_url(record.session_id, record.id))
            self._native_notification_manager.send_notification(
                f"CleanHouse: {record.notification_type}",
                record.summary,
                level=record.severity,
                metadata={
                    "notification_id": record.id,
                    "notification_type": record.notification_type,
                    "session_id": record.session_id,
                    "objective_id": record.objective_id,
                    "evidence_refs": list(record.evidence_refs),
                },
                click_url=click_url,
            )
        except Exception:
            pass

    def _objective_id_for_session(self, session_id: str) -> Optional[str]:
        if not session_id:
            return None
        prompts = [
            prompt for prompt in self._prompt_records()
            if prompt.session_id == session_id and prompt.objective_id
        ]
        approvals = [
            self._approval_item_from_dict(approval)
            for approval in self.get_approval_queue(session_id=session_id).get("approval_queue", [])
            if isinstance(approval, dict) and approval.get("objective_id")
        ]
        receipts = [
            receipt for receipt in self.get_receipts(session_id=session_id).get("receipts", [])
            if isinstance(receipt.get("metadata"), dict) and receipt["metadata"].get("objective_id")
        ]
        if prompts:
            return prompts[-1].objective_id
        if approvals:
            approvals.sort(key=lambda item: item.created_at)
            return approvals[-1].objective_id
        if receipts:
            receipts.sort(key=lambda item: item.get("timestamp", ""))
            return str(receipts[-1]["metadata"].get("objective_id"))
        return None

    def _latest_workstation_session_id(self) -> str:
        sessions: list[Dict[str, Any]] = []
        with self._lock:
            sessions.extend(record.to_dict() for record in self._operator_sessions.values())
        prompts = self._prompt_records()
        intents = self._intent_records()
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("operator_session"):
                payload = artifact.get("data", {})
                session = payload.get("session", payload) if isinstance(payload, dict) else None
                if isinstance(session, dict):
                    sessions.append(session)
        if sessions:
            sessions.sort(key=lambda item: item.get("started_at", ""), reverse=True)
            return str(sessions[0].get("session_id", ""))
        if prompts:
            prompts.sort(key=lambda item: item.timestamp, reverse=True)
            return prompts[0].session_id
        if intents:
            intents.sort(key=lambda item: item.timestamp, reverse=True)
            return intents[0].id
        return ""

    def _latest_receipt_dict(self, session_id: str) -> Optional[Dict[str, Any]]:
        receipts = self.get_receipts(session_id=session_id).get("receipts", [])
        return receipts[0] if receipts else None

    def _receipt_local_evidence_refs(self, receipt: Dict[str, Any]) -> tuple[str, ...]:
        refs: list[str] = []
        receipt_id = receipt.get("id", "")
        if receipt_id:
            refs.append(f"local://cleanhouse/receipt/{receipt_id}")
        for entry in receipt.get("evidence_index", []):
            if isinstance(entry, dict):
                refs.append(str(entry.get("ref") or entry.get("uri") or ""))
        for alert in receipt.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            refs.extend(str(ref) for ref in alert.get("evidence_refs", []))
        return self._local_evidence_refs(refs)

    def _derive_workstation_notifications(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        receipts: Sequence[Dict[str, Any]],
        alerts: Sequence[Dict[str, Any]],
        approvals: Sequence[Dict[str, Any]],
        evidence_summaries: Sequence[Dict[str, Any]],
    ) -> None:
        for summary in evidence_summaries:
            if summary.get("summary_type") != "scope_drift":
                continue
            self._ensure_operator_notification(
                notification_type="scope_drift_detected",
                session_id=session_id,
                objective_id=objective_id,
                severity="warning",
                summary=str(summary.get("summary", "")),
                evidence_refs=summary.get("evidence_refs", []),
                source="workstation",
                metadata={"receipt_id": summary.get("receipt_id", ""), "scope_weight": summary.get("scope_weight")},
            )
        for alert in alerts:
            if alert.get("alert_type") != "scope_expansion":
                continue
            self._ensure_operator_notification(
                notification_type="scope_drift_detected",
                session_id=session_id,
                objective_id=objective_id,
                severity="warning" if alert.get("severity") != "high" else "critical",
                summary=str(alert.get("description", "scope drift detected")),
                evidence_refs=alert.get("evidence_refs", []),
                source="alert",
                metadata={"alert_id": alert.get("id", ""), "alert_type": alert.get("alert_type", "")},
            )
        for approval in approvals:
            if approval.get("status") not in {"pending", "needs_review"}:
                continue
            self._ensure_operator_notification(
                notification_type="approval_required",
                session_id=session_id,
                objective_id=approval.get("objective_id") or objective_id,
                severity="warning",
                summary=str(approval.get("reason") or approval.get("requested_action") or "approval required"),
                evidence_refs=approval.get("evidence_refs", []),
                source="approval_queue",
                metadata={"approval_id": approval.get("id", "")},
            )
        for receipt in receipts:
            receipt_id = receipt.get("id", "")
            if not receipt_id:
                continue
            self._ensure_operator_notification(
                notification_type="receipt_finalized",
                session_id=session_id,
                objective_id=receipt.get("metadata", {}).get("objective_id") or objective_id,
                severity="info",
                summary=f"receipt finalized: {receipt_id}",
                evidence_refs=self._receipt_local_evidence_refs(receipt),
                source="receipt",
                metadata={"receipt_id": receipt_id},
            )

    def _ensure_continuity_degraded_notification(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        provenance: Dict[str, Any],
    ) -> None:
        if provenance.get("status") != "degraded":
            return
        refs: list[str] = []
        failed_pickups = provenance.get("failed_pickups", [])
        if not isinstance(failed_pickups, list):
            failed_pickups = []
        claims = provenance.get("claims", [])
        if not isinstance(claims, list):
            claims = []
        for failure in failed_pickups:
            if isinstance(failure, dict):
                refs.extend(failure.get("evidence_refs", []) or [])
        for claim in claims:
            if isinstance(claim, dict) and claim.get("classification") == "degraded":
                refs.extend(claim.get("evidence_refs", []) or [])
        refs.append(f"local://cleanhouse/continuity/{session_id}")
        reason = str(provenance.get("confidence_basis") or "Continuity provenance degraded.")
        self._ensure_operator_notification(
            notification_type="continuity_degraded",
            session_id=session_id,
            objective_id=objective_id,
            severity="warning",
            summary=f"continuity degraded: {reason[:140]}",
            evidence_refs=refs,
            source="continuity_provenance",
            metadata={
                "continuity_status": provenance.get("status", ""),
                "failed_pickup_count": len(failed_pickups),
            },
        )

    def _build_workstation_evidence_summaries(
        self,
        *,
        session_id: str,
        receipts: Sequence[Dict[str, Any]],
        alerts: Sequence[Dict[str, Any]],
        approvals: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        summaries: list[Dict[str, Any]] = []
        for receipt in receipts:
            analysis = receipt.get("scope_analysis", {}) if isinstance(receipt.get("scope_analysis"), dict) else {}
            receipt_id = str(receipt.get("id", ""))
            classification = str(analysis.get("classification", "unknown"))
            scope_weight = analysis.get("scope_weight")
            out_count = int(analysis.get("out_of_scope_count", 0) or 0)
            change_count = int(analysis.get("change_count", len(analysis.get("changed_paths", []))) or 0)
            declared_scope = str(analysis.get("declared_scope") or receipt.get("metadata", {}).get("scope") or "")
            refs = self._receipt_local_evidence_refs(receipt)
            if classification == "outside_declared_scope" or out_count > 0:
                summary_type = "scope_drift"
                summary = (
                    f"Receipt {receipt_id} flagged {out_count} of {change_count} changed path(s) "
                    f"outside declared scope '{declared_scope}' with scope_weight={scope_weight}."
                )
                severity = "warning"
            else:
                summary_type = "receipt_scope"
                summary = (
                    f"Receipt {receipt_id} kept {change_count} changed path(s) within declared scope "
                    f"'{declared_scope}' with scope_weight={scope_weight}."
                )
                severity = "info"
            summaries.append({
                "id": f"summary:{_fingerprint(receipt_id, classification, str(scope_weight))}",
                "summary_type": summary_type,
                "session_id": session_id,
                "receipt_id": receipt_id,
                "severity": severity,
                "summary": summary,
                "classification": classification,
                "scope_weight": scope_weight,
                "declared_scope": declared_scope,
                "path_clusters": analysis.get("path_clusters", []),
                "evidence_refs": list(refs),
            })
        for alert in alerts:
            refs = self._local_evidence_refs(alert.get("evidence_refs", []))
            if not refs:
                continue
            summaries.append({
                "id": f"summary:{_fingerprint(alert.get('id', ''), alert.get('alert_type', ''))}",
                "summary_type": "alert",
                "session_id": session_id,
                "alert_id": alert.get("id", ""),
                "severity": alert.get("severity", "low"),
                "summary": f"{alert.get('alert_type', 'alert')}: {alert.get('description', '')}",
                "rationale": alert.get("rationale", ""),
                "evidence_refs": list(refs),
            })
        for approval in approvals:
            refs = self._local_evidence_refs(approval.get("evidence_refs", []))
            if not refs:
                continue
            summaries.append({
                "id": f"summary:{_fingerprint(approval.get('id', ''), approval.get('status', ''))}",
                "summary_type": "approval",
                "session_id": session_id,
                "approval_id": approval.get("id", ""),
                "severity": "warning" if approval.get("status") in {"pending", "needs_review"} else "info",
                "summary": f"Approval {approval.get('status', 'unknown')}: {approval.get('requested_action', '')}",
                "evidence_refs": list(refs),
            })
        return summaries

    def _workstation_objectives(self, session_id: str) -> list[Dict[str, Any]]:
        if not session_id:
            return []
        objectives: list[Dict[str, Any]] = []
        for prompt in self._prompt_records():
            if prompt.session_id == session_id:
                objectives.append({
                    "id": prompt.objective_id or prompt.id,
                    "session_id": session_id,
                    "prompt_id": prompt.id,
                    "text": prompt.text,
                    "scope": prompt.scope,
                    "context": prompt.context,
                    "tool_identity": prompt.tool_identity,
                    "timestamp": prompt.timestamp,
                })
        for intent in self._intent_records():
            if intent.id == session_id and not any(item.get("id") == intent.id for item in objectives):
                objectives.append({
                    "id": intent.id,
                    "session_id": session_id,
                    "prompt_id": None,
                    "text": intent.text,
                    "scope": intent.scope,
                    "context": "",
                    "tool_identity": intent.tool_identity,
                    "timestamp": intent.timestamp,
                })
        objectives.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return objectives

    def _workstation_mutations(
        self,
        session_id: str,
        timeline_result: Dict[str, Any],
        live_events: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        mutations: list[Dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            diffs = [diff.to_dict() for diff in self._diffs.values() if diff.session_id == session_id]
        for diff in diffs:
            key = f"diff:{diff.get('id', '')}"
            seen.add(key)
            mutations.append({
                "id": diff.get("id", ""),
                "source": "diff",
                "timestamp": diff.get("timestamp", ""),
                "summary": f"{diff.get('created_count', 0)} created, {diff.get('modified_count', 0)} modified, {diff.get('deleted_count', 0)} deleted",
                "changes": diff.get("changes", []),
                "evidence_refs": [f"local://cleanhouse/diff/{diff.get('id', '')}"],
            })
        for entry in timeline_result.get("entries", []):
            if entry.get("event_type") != "diff":
                continue
            key = f"timeline:{entry.get('event_id', '')}"
            if key in seen:
                continue
            seen.add(key)
            mutations.append({
                "id": entry.get("event_id", ""),
                "source": "timeline",
                "timestamp": entry.get("timestamp", ""),
                "summary": entry.get("label", ""),
                "changes": entry.get("data", {}).get("changes", []),
                "evidence_refs": [f"local://cleanhouse/timeline/{entry.get('event_id', '')}"],
            })
        for event in live_events:
            if event.get("event_type") not in {"created", "modified", "deleted"}:
                continue
            key = f"event:{event.get('id', '')}"
            if key in seen:
                continue
            seen.add(key)
            mutations.append({
                "id": str(event.get("id", "")),
                "source": "event",
                "timestamp": event.get("timestamp", ""),
                "summary": event.get("summary", ""),
                "path": event.get("path", ""),
                "event_type": event.get("event_type", ""),
                "evidence_refs": [f"local://cleanhouse/events/{event.get('id', '')}"],
            })
        mutations.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return mutations

    def create_approval_queue_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raw_session_id = data.get("session_id")
        session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        raw_requested_action = data.get("requested_action") or data.get("action")
        requested_action = raw_requested_action.strip() if isinstance(raw_requested_action, str) else ""
        if not requested_action:
            return {"status": "error", "message": "requested_action is required"}
        raw_reason = data.get("reason")
        reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
        raw_refs = data.get("evidence_refs") or []
        if not isinstance(raw_refs, list):
            return {"status": "error", "message": "evidence_refs must be a list"}
        evidence_refs = tuple(str(ref).strip() for ref in raw_refs if str(ref).strip())
        prompt_id = data.get("prompt_id")
        prompt_id = prompt_id.strip() if isinstance(prompt_id, str) and prompt_id.strip() else None
        objective_id = data.get("objective_id")
        objective_id = objective_id.strip() if isinstance(objective_id, str) and objective_id.strip() else None
        raw_source = data.get("source")
        source = raw_source.strip() if isinstance(raw_source, str) and raw_source.strip() else "api"
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        raw_reviewer_note = data.get("reviewer_note")
        reviewer_note = raw_reviewer_note.strip() if isinstance(raw_reviewer_note, str) else ""
        raw_reviewer = data.get("reviewer")
        reviewer = raw_reviewer.strip() if isinstance(raw_reviewer, str) and raw_reviewer.strip() else source
        now = _now_iso()
        approval_id = f"approval:{_fingerprint(session_id, requested_action, now)}"
        history_entry = ApprovalHistoryEntry(
            id=f"approval-history:{_fingerprint(approval_id, 'created', now)}",
            approval_id=approval_id,
            session_id=session_id,
            receipt_id=str(metadata.get("receipt_id")) if metadata.get("receipt_id") else None,
            timestamp=now,
            action="created",
            status="pending",
            previous_status=None,
            reviewer=reviewer,
            note=reviewer_note,
            evidence_refs=evidence_refs,
        )
        item = ApprovalQueueItem(
            id=approval_id,
            session_id=session_id,
            status="pending",
            requested_action=requested_action,
            reason=reason,
            evidence_refs=evidence_refs,
            prompt_id=prompt_id,
            objective_id=objective_id,
            created_at=now,
            resolved_at=None,
            resolution_note="",
            reviewer_note=reviewer_note,
            reviewer=reviewer,
            history=(history_entry,),
            source=source,
            metadata=copy.deepcopy(metadata),
        )
        with self._lock:
            self._approval_queue[item.id] = item
        _insert_runtime_event(
            event_type="approval_requested",
            path=f"/approval-queue/{approval_id}",
            summary=f"approval_requested: {requested_action}",
            session_id=session_id,
            objective_id=objective_id,
            source_surface="approval_queue",
            actor_type="operator",
            evidence_level="observed",
            observed_vs_expected={"status": "matched", "details": "approval review state created"},
            collector_status="ok",
            evidence_refs=evidence_refs,
            raw_evidence_ref=f"local://cleanhouse/approval-queue/{approval_id}",
            data=item.to_dict(),
        )
        result = {"status": "ok", "approval": item.to_dict()}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("approval", item.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        notification = self._ensure_operator_notification(
            notification_type="approval_required",
            session_id=session_id,
            objective_id=objective_id,
            severity="warning",
            summary=reason or requested_action,
            evidence_refs=evidence_refs,
            source="approval_queue",
            metadata={"approval_id": item.id},
        )
        if notification is not None:
            result["notification"] = notification.to_dict()
        return result

    def get_approval_queue(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            records = [r.to_dict() for r in self._approval_queue.values()]
        seen = {r["id"] for r in records}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("approval"):
                payload = artifact.get("data", {})
                approval = payload.get("approval", payload)
                if not isinstance(approval, dict):
                    continue
                approval_id = approval.get("id")
                if approval_id and approval_id not in seen:
                    seen.add(approval_id)
                    records.append(approval)
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        if session_id:
            records = [r for r in records if r.get("session_id") == session_id]
        if status:
            records = [r for r in records if r.get("status") == status]
        return {
            "approval_queue": records,
            "count": len(records),
        }

    def resolve_approval_queue_item(
        self,
        approval_id: str,
        status: str,
        note: str = "",
        reviewer: str = "api",
    ) -> Dict[str, Any]:
        normalized_status = status.strip().lower().replace(" ", "_").replace("-", "_") if isinstance(status, str) else ""
        if normalized_status not in {"approved", "rejected", "needs_review", "pending"}:
            return {"status": "error", "message": "status must be approved, rejected, needs_review, or pending"}
        with self._lock:
            existing = self._approval_queue.get(approval_id)
        if existing is None:
            loaded = self._load_approval_from_persistence(approval_id)
            if loaded is None:
                return {"status": "not_found", "message": f"approval not found: {approval_id}"}
            existing = loaded
        now = _now_iso()
        reviewer_name = reviewer.strip() if isinstance(reviewer, str) and reviewer.strip() else existing.reviewer
        reviewer_note = note.strip()
        resolved_at = now if normalized_status in {"approved", "rejected"} else None
        history_entry = ApprovalHistoryEntry(
            id=f"approval-history:{_fingerprint(approval_id, normalized_status, now, reviewer_note)}",
            approval_id=approval_id,
            session_id=existing.session_id,
            receipt_id=str(existing.metadata.get("receipt_id")) if existing.metadata.get("receipt_id") else None,
            timestamp=now,
            action=normalized_status,
            status=normalized_status,
            previous_status=existing.status,
            reviewer=reviewer_name,
            note=reviewer_note,
            evidence_refs=existing.evidence_refs,
        )
        updated = ApprovalQueueItem(
            id=existing.id,
            session_id=existing.session_id,
            status=normalized_status,
            requested_action=existing.requested_action,
            reason=existing.reason,
            evidence_refs=existing.evidence_refs,
            prompt_id=existing.prompt_id,
            objective_id=existing.objective_id,
            created_at=existing.created_at,
            resolved_at=resolved_at,
            resolution_note=reviewer_note if normalized_status in {"approved", "rejected"} else existing.resolution_note,
            reviewer_note=reviewer_note,
            reviewer=reviewer_name,
            history=existing.history + (history_entry,),
            source=existing.source,
            metadata=existing.metadata,
        )
        with self._lock:
            self._approval_queue[approval_id] = updated
        _insert_runtime_event(
            event_type="approval_resolved",
            path=f"/approval-queue/{approval_id}",
            summary=f"approval_resolved: {normalized_status}",
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            source_surface="approval_queue",
            actor_type="operator",
            evidence_level="observed",
            observed_vs_expected={"status": normalized_status, "details": reviewer_note},
            collector_status="ok",
            evidence_refs=existing.evidence_refs,
            raw_evidence_ref=f"local://cleanhouse/approval-queue/{approval_id}",
            data=updated.to_dict(),
        )
        result = {"status": "ok", "approval": updated.to_dict()}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("approval", updated.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def _load_approval_from_persistence(self, approval_id: str) -> Optional[ApprovalQueueItem]:
        artifact = PersistenceBackend.read("approval", approval_id)
        if not artifact:
            return None
        payload = artifact.get("data", {})
        approval = payload.get("approval", payload)
        if not isinstance(approval, dict):
            return None
        return self._approval_item_from_dict(approval)

    def _approval_item_from_dict(self, approval: Dict[str, Any]) -> ApprovalQueueItem:
        history = tuple(
            ApprovalHistoryEntry(
                id=str(entry.get("id", "")),
                approval_id=str(entry.get("approval_id", approval.get("id", ""))),
                session_id=str(entry.get("session_id", approval.get("session_id", ""))),
                receipt_id=entry.get("receipt_id"),
                timestamp=str(entry.get("timestamp", "")),
                action=str(entry.get("action", entry.get("status", ""))),
                status=str(entry.get("status", "")),
                previous_status=entry.get("previous_status"),
                reviewer=str(entry.get("reviewer", approval.get("reviewer", ""))),
                note=str(entry.get("note", "")),
                evidence_refs=tuple(str(ref) for ref in entry.get("evidence_refs", [])),
            )
            for entry in approval.get("history", [])
            if isinstance(entry, dict)
        )
        return ApprovalQueueItem(
            id=str(approval.get("id", "")),
            session_id=str(approval.get("session_id", "")),
            status=str(approval.get("status", "pending")),
            requested_action=str(approval.get("requested_action", "")),
            reason=str(approval.get("reason", "")),
            evidence_refs=tuple(str(ref) for ref in approval.get("evidence_refs", [])),
            prompt_id=approval.get("prompt_id"),
            objective_id=approval.get("objective_id"),
            created_at=str(approval.get("created_at", "")),
            resolved_at=approval.get("resolved_at"),
            resolution_note=str(approval.get("resolution_note", "")),
            reviewer_note=str(approval.get("reviewer_note", approval.get("resolution_note", ""))),
            reviewer=str(approval.get("reviewer", approval.get("source", "api"))),
            history=history,
            source=str(approval.get("source", "api")),
            metadata=copy.deepcopy(approval.get("metadata", {})) if isinstance(approval.get("metadata"), dict) else {},
        )

    def find_nearest_intent(self, timestamp: str) -> Optional[IntentRecord]:
        with self._lock:
            for record in reversed(self._intents):
                if record.timestamp <= timestamp:
                    return record
        return None

    def create_snapshot(
        self,
        repo_path: str,
        label: str = "",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        files = _snapshot_directory(repo_path)
        file_contents = _snapshot_file_contents(repo_path)
        ts = _now_iso()
        snap = SnapshotRecord(
            id=f"snap:{_fingerprint(repo_path, label, ts)}",
            repo_path=repo_path,
            label=label,
            timestamp=ts,
            file_count=len(files),
            files=files,
        )
        with self._lock:
            if len(self._snapshots) >= 200:
                oldest = min(self._snapshots.keys(), key=lambda k: self._snapshots[k].timestamp)
                del self._snapshots[oldest]
                self._snapshot_contents.pop(oldest, None)
            self._snapshots[snap.id] = snap
            self._snapshot_contents[snap.id] = file_contents
        result = {"status": "ok", "id": snap.id, "file_count": snap.file_count}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("snapshot", snap.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def compute_diff(
        self,
        before_id: str,
        after_id: str,
        session_id: Optional[str] = None,
        max_time_window_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        with self._lock:
            before = self._snapshots.get(before_id)
            after = self._snapshots.get(after_id)
        if not before:
            return {"status": "error", "message": f"snapshot not found: {before_id}"}
        if not after:
            return {"status": "error", "message": f"snapshot not found: {after_id}"}
        changes = _compute_file_changes(before.files, after.files)
        created = sum(1 for c in changes if c.change_type == "created")
        modified = sum(1 for c in changes if c.change_type == "modified")
        deleted = sum(1 for c in changes if c.change_type == "deleted")
        ts = _now_iso()
        diff = DiffRecord(
            id=f"diff:{_fingerprint(before_id, after_id, ts)}",
            before_id=before_id,
            after_id=after_id,
            timestamp=ts,
            session_id=session_id,
            changes=changes,
            created_count=created,
            modified_count=modified,
            deleted_count=deleted,
        )
        with self._lock:
            if len(self._diffs) >= 500:
                oldest = min(self._diffs.keys(), key=lambda k: self._diffs[k].timestamp)
                del self._diffs[oldest]
            self._diffs[diff.id] = diff
        result = {
            "status": "ok",
            "id": diff.id,
            "changes": [c.path for c in changes],
            "created_count": created,
            "modified_count": modified,
            "deleted_count": deleted,
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("diff", diff.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def get_diffs(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            records = list(self._diffs.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        return {
            "diffs": [r.to_dict() for r in records],
            "count": len(records),
        }

    def correlate(
        self,
        session_id: str,
        max_time_window_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        intent = self._intent_record_by_id(session_id)

        if not intent:
            return {
                "status": "unknown",
                "message": f"No intent found for session_id {session_id}",
                "edge_count": 0,
                "edges": [],
            }

        edges: list[CorrelationEdge] = []
        intent_dt = datetime.fromisoformat(intent.timestamp)

        command_count = 0
        with self._lock:
            commands = list(self._command_buffer)
        for cmd_result in commands:
            cmd_dt = datetime.fromisoformat(cmd_result.timestamp)
            delta = (cmd_dt - intent_dt).total_seconds()
            if delta < 0 or delta > max_time_window_seconds:
                continue
            confidence = max(0.0, 1.0 - delta / max_time_window_seconds)
            command_count += 1
            target_id = f"command:{_fingerprint(cmd_result.command, *cmd_result.args)}"
            edges.append(CorrelationEdge(
                source_id=intent.id,
                target_id=target_id,
                source_type="intent",
                target_type="command",
                relationship="temporal_proximity",
                confidence=confidence,
                uncertainty=round(1.0 - confidence, 3),
                time_delta_seconds=round(delta, 3),
                observed_vs_expected={
                    "status": "matched",
                    "details": f"command '{cmd_result.command}' observed {delta:.2f}s after intent",
                },
            ))

        diff_count = 0
        with self._lock:
            session_diffs = [r for r in self._diffs.values() if r.session_id == session_id]
        for diff in session_diffs:
            diff_dt = datetime.fromisoformat(diff.timestamp)
            time_delta = (diff_dt - intent_dt).total_seconds()
            diff_count += 1
            edges.append(CorrelationEdge(
                source_id=intent.id,
                target_id=diff.id,
                source_type="intent",
                target_type="diff",
                relationship="session_link",
                confidence=0.95,
                uncertainty=0.05,
                time_delta_seconds=round(time_delta, 3) if time_delta >= 0 else None,
                observed_vs_expected={
                    "status": "matched",
                    "details": f"diff {diff.id} explicitly linked via session_id",
                },
            ))

        action_count = 0
        with self._lock:
            session_actions = [r for r in self._tool_events if r.session_id == session_id]
        for action in session_actions:
            action_dt = datetime.fromisoformat(action.timestamp)
            time_delta = (action_dt - intent_dt).total_seconds()
            action_count += 1
            target_id = f"action:{_fingerprint(action.tool_identity, action.command, action.timestamp)}"
            edges.append(CorrelationEdge(
                source_id=intent.id,
                target_id=target_id,
                source_type="intent",
                target_type="action",
                relationship="session_link",
                confidence=0.95,
                uncertainty=0.05,
                time_delta_seconds=round(time_delta, 3) if time_delta >= 0 else None,
                observed_vs_expected={
                    "status": "matched",
                    "details": f"tool action '{action.command}' explicitly linked via session_id",
                },
            ))

        if command_count == 0 and diff_count == 0 and action_count == 0:
            edges.append(CorrelationEdge(
                source_id=intent.id,
                target_id="",
                source_type="intent",
                target_type="unknown",
                relationship="temporal_proximity",
                confidence=0.0,
                uncertainty=1.0,
                time_delta_seconds=None,
                observed_vs_expected={
                    "status": "unknown",
                    "details": "No command or diff observed within time window for this intent",
                },
            ))

        ts = _now_iso()
        pass_obj = CorrelationPass(
            id=f"corr:{_fingerprint(session_id, ts)}",
            session_id=session_id,
            timestamp=ts,
            edges=tuple(edges),
            edge_count=len(edges),
        )
        with self._lock:
            if len(self._correlations) >= 200:
                oldest = min(self._correlations.keys(), key=lambda k: self._correlations[k].timestamp)
                del self._correlations[oldest]
            self._correlations[pass_obj.id] = pass_obj

        return {
            "status": "ok",
            "id": pass_obj.id,
            "session_id": session_id,
            "edge_count": pass_obj.edge_count,
            "edges": [e.to_dict() for e in edges],
        }

    def get_correlations(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            records = list(self._correlations.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        return {
            "correlations": [r.to_dict() for r in records],
            "count": len(records),
        }

    def _list_persisted_events(self, session_id: str, limit: int = 500) -> list[Dict[str, Any]]:
        try:
            return cleanhouse_events.list_events(limit=limit, session_id=session_id)
        except TypeError:
            try:
                return [
                    event for event in cleanhouse_events.list_events(limit=limit)
                    if event.get("session_id") == session_id
                ]
            except Exception:
                return []
        except Exception:
            return []

    def _scope_relation_for_path(self, path: str, scope: str) -> str:
        clean_path = str(path or "").strip()
        clean_scope = str(scope or "").strip().strip("/")
        if not clean_path or not clean_scope:
            return "unknown"
        normalized_path = clean_path.replace("\\", "/").strip("/")
        normalized_scope = clean_scope.replace("\\", "/").strip("/")
        if normalized_path.startswith(normalized_scope + "/") or normalized_path == normalized_scope:
            return "in_scope"
        if f"/{normalized_scope}/" in f"/{normalized_path}/":
            return "in_scope"
        return "out_of_scope"

    def _canonical_data(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        source_surface: str,
        actor_type: str,
        evidence_level: str,
        observed_vs_expected: Optional[Dict[str, Any]],
        collector_status: str,
        scope_relation: str,
        evidence_refs: Sequence[str],
        raw_evidence_ref: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = copy.deepcopy(data or {})
        payload.update({
            "session_id": session_id,
            "objective_id": objective_id,
            "source_surface": source_surface,
            "actor_type": actor_type,
            "evidence_level": _normalize_evidence_level(evidence_level),
            "observed_vs_expected": observed_vs_expected or {"status": evidence_level},
            "collector_status": collector_status,
            "scope_relation": scope_relation,
            "evidence_refs": list(evidence_refs),
            "raw_evidence_ref": raw_evidence_ref,
        })
        return payload

    def _persisted_timeline_entries(
        self,
        session_id: str,
        raw_entries: Sequence[tuple[str, str, str, Dict[str, Any]]],
    ) -> list[tuple[str, str, str, Dict[str, Any]]]:
        persisted = self._list_persisted_events(session_id)
        if not persisted:
            return []

        command_keys = {
            str(entry[3].get("command", ""))
            for entry in raw_entries
            if entry[1] == "command" and entry[3].get("command")
        }
        prompt_keys = {
            str(entry[3].get("prompt_id", ""))
            for entry in raw_entries
            if entry[1] == "prompt" and entry[3].get("prompt_id")
        }
        approval_keys = {
            str(entry[3].get("approval_id", ""))
            for entry in raw_entries
            if entry[1] == "approval_queue" and entry[3].get("approval_id")
        }
        objective_id = self._objective_id_for_session(session_id)
        prompts = self.get_prompts(session_id=session_id).get("prompts", [])
        scope = str(prompts[0].get("scope", "")) if prompts else ""
        rows: list[tuple[str, str, str, Dict[str, Any]]] = []
        seen: set[str] = set()

        for event in persisted:
            event_type = str(event.get("event_type", ""))
            if event_type in OPERATOR_NOTIFICATION_TYPES:
                continue
            path = str(event.get("path", ""))
            summary = str(event.get("summary", ""))
            event_id = str(event.get("id", ""))
            timestamp = str(event.get("timestamp") or _now_iso())
            event_objective_id = event.get("objective_id") or objective_id
            evidence_refs = event.get("evidence_refs")
            if not isinstance(evidence_refs, list) or not evidence_refs:
                evidence_refs = [f"local://cleanhouse/events/{event_id}"]
            data = _safe_json_loads(event.get("data"), {})
            observed_vs_expected = _safe_json_loads(
                event.get("observed_vs_expected"),
                {"status": event.get("evidence_level", "observed"), "details": summary},
            )
            collector_status = str(event.get("collector_status") or "ok")
            source_surface = str(event.get("source_surface") or event_type)
            actor_type = str(event.get("actor_type") or "unknown")
            evidence_level = _normalize_evidence_level(str(event.get("evidence_level") or "observed"))
            scope_relation = str(event.get("scope_relation") or self._scope_relation_for_path(path, scope))
            raw_ref = str(event.get("raw_evidence_ref") or f"local://cleanhouse/events/{event_id}")

            if event_type == "prompt_event" and any(key and key in path for key in prompt_keys):
                continue
            if event_type in {"shell_event", "process_event"} and any(key and key in path for key in command_keys):
                continue
            if event_type in {"approval_requested", "approval_resolved"} and any(key and key in path for key in approval_keys):
                continue

            mapped_type = {
                "prompt_event": "prompt",
                "shell_event": "command",
                "process_event": "process",
                "tool_event": "action",
                "created": "file_mutation",
                "modified": "file_mutation",
                "deleted": "file_mutation",
                "objective_start": "objective",
                "objective_end": "objective",
                "approval_requested": "approval_queue",
                "approval_resolved": "approval_queue",
            }.get(event_type, event_type or "event")
            key = f"{mapped_type}:{event_id}:{path}:{summary}"
            if key in seen:
                continue
            seen.add(key)

            payload = self._canonical_data(
                session_id=session_id,
                objective_id=str(event_objective_id) if event_objective_id else None,
                source_surface=source_surface,
                actor_type=actor_type,
                evidence_level=evidence_level,
                observed_vs_expected=observed_vs_expected,
                collector_status=collector_status,
                scope_relation=scope_relation,
                evidence_refs=[str(ref) for ref in evidence_refs],
                raw_evidence_ref=raw_ref,
                data={
                    "persisted_event_id": event_id,
                    "persisted_event_type": event_type,
                    "path": path,
                    "summary": summary,
                    **(data if isinstance(data, dict) else {}),
                },
            )
            rows.append((timestamp, mapped_type, summary[:80] or event_type, payload))
        return rows

    def build_timeline(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        raw_entries: list[tuple[str, str, str, Dict[str, Any]]] = []
        # (timestamp, event_type, label, data)

        with self._lock:
            for prompt in self._prompt_records():
                if prompt.session_id == session_id:
                    prompt_ref = f"local://cleanhouse/prompt/{prompt.id}"
                    raw_entries.append((
                        prompt.timestamp,
                        "prompt",
                        prompt.text[:80],
                        self._canonical_data(
                            session_id=session_id,
                            objective_id=prompt.objective_id,
                            source_surface="prompt_context",
                            actor_type="human",
                            evidence_level="observed",
                            observed_vs_expected={"status": "matched", "details": "prompt/context captured"},
                            collector_status="ok",
                            scope_relation="objective_root" if prompt.objective_id else "unknown",
                            evidence_refs=[prompt_ref],
                            raw_evidence_ref=prompt_ref,
                            data={
                            "context": prompt.context,
                            "scope": prompt.scope,
                            "tool_identity": prompt.tool_identity,
                            "repo_path": prompt.repo_path,
                            "prompt_id": prompt.id,
                            "objective_id": prompt.objective_id,
                            },
                        ),
                    ))

            for record in self._intent_records():
                if record.id == session_id:
                    intent_ref = f"local://cleanhouse/intent/{record.id}"
                    raw_entries.append((
                        record.timestamp,
                        "intent",
                        record.text[:80],
                        self._canonical_data(
                            session_id=session_id,
                            objective_id=self._objective_id_for_session(session_id),
                            source_surface="intent",
                            actor_type="human",
                            evidence_level="observed",
                            observed_vs_expected={"status": "matched", "details": "intent captured"},
                            collector_status="ok",
                            scope_relation="objective_root",
                            evidence_refs=[intent_ref],
                            raw_evidence_ref=intent_ref,
                            data={"scope": record.scope, "tool_identity": record.tool_identity, "repo_path": record.repo_path},
                        ),
                    ))

            for result in self._command_buffer:
                result_session = getattr(result, "session_id", None)
                if result_session and result_session != session_id:
                    continue
                command_ref = f"local://cleanhouse/command/{_fingerprint(result.command, *result.args)}"
                raw_entries.append((
                    result.timestamp,
                    "command",
                    result.command[:80],
                    self._canonical_data(
                        session_id=session_id,
                        objective_id=getattr(result, "objective_id", None) or self._objective_id_for_session(session_id),
                        source_surface="command_observer",
                        actor_type="shell",
                        evidence_level="observed",
                        observed_vs_expected={
                            "status": "matched" if result.returncode == 0 else "unexpected",
                            "details": f"owned command exited {result.returncode}",
                        },
                        collector_status="ok",
                        scope_relation="unknown",
                        evidence_refs=[command_ref],
                        raw_evidence_ref=command_ref,
                        data={
                            "command": result.command,
                            "returncode": result.returncode,
                            "duration": result.duration,
                            "args": list(result.args),
                            "cwd": result.cwd,
                            "user": result.user,
                            "child_pid": getattr(result, "child_pid", None),
                        },
                    ),
                ))

            for event in self._tool_events:
                if event.session_id == session_id:
                    action_ref = f"local://cleanhouse/tool-event/{event.tool_identity}/{_fingerprint(event.command, event.timestamp)}"
                    raw_entries.append((
                        event.timestamp,
                        "action",
                        f"{event.tool_identity} {event.command}"[:80],
                        self._canonical_data(
                            session_id=session_id,
                            objective_id=self._objective_id_for_session(session_id),
                            source_surface="tool_event",
                            actor_type="tool",
                            evidence_level="observed",
                            observed_vs_expected={
                                "status": "matched" if event.exit_code == 0 else "unexpected",
                                "details": f"tool boundary returned {event.exit_code}",
                            },
                            collector_status="ok",
                            scope_relation="unknown",
                            evidence_refs=[action_ref],
                            raw_evidence_ref=action_ref,
                            data={
                            "tool_identity": event.tool_identity,
                            "command": event.command,
                            "args": list(event.args),
                            "exit_code": event.exit_code,
                            "cwd": event.cwd,
                            "duration": event.duration,
                            },
                        ),
                    ))

            for diff in self._diffs.values():
                if diff.session_id == session_id:
                    diff_ref = f"local://cleanhouse/diff/{diff.id}"
                    raw_entries.append((
                        diff.timestamp,
                        "diff",
                        f"{diff.created_count + diff.modified_count + diff.deleted_count} change(s)",
                        self._canonical_data(
                            session_id=session_id,
                            objective_id=self._objective_id_for_session(session_id),
                            source_surface="snapshot_diff",
                            actor_type="filesystem",
                            evidence_level="observed",
                            observed_vs_expected={"status": "observed", "details": "snapshot diff captured"},
                            collector_status="ok",
                            scope_relation="mixed",
                            evidence_refs=[diff_ref],
                            raw_evidence_ref=diff_ref,
                            data={
                            "created": diff.created_count,
                            "modified": diff.modified_count,
                            "deleted": diff.deleted_count,
                            "changes": [c.path for c in diff.changes],
                            "file_changes": [c.__dict__ for c in diff.changes],
                            },
                        ),
                    ))

            for corr in self._correlations.values():
                if corr.session_id == session_id:
                    raw_entries.append((
                        corr.timestamp,
                        "correlation",
                        f"{corr.edge_count} edge(s)",
                        self._canonical_data(
                            session_id=session_id,
                            objective_id=self._objective_id_for_session(session_id),
                            source_surface="correlation",
                            actor_type="cleanhouse",
                            evidence_level="inferred",
                            observed_vs_expected={"status": "inferred", "details": "correlation graph generated"},
                            collector_status="ok",
                            scope_relation="unknown",
                            evidence_refs=[f"local://cleanhouse/correlation/{corr.id}"],
                            raw_evidence_ref=f"local://cleanhouse/correlation/{corr.id}",
                            data={"edge_count": corr.edge_count},
                        ),
                    ))

            for approval in (
                self._approval_item_from_dict(record)
                for record in self.get_approval_queue(session_id=session_id).get("approval_queue", [])
                if isinstance(record, dict)
            ):
                if approval.session_id == session_id:
                    if approval.history:
                        for history_entry in approval.history:
                            raw_entries.append((
                                history_entry.timestamp,
                                "approval_queue",
                                (
                                    approval.requested_action[:80]
                                    if history_entry.action == "created"
                                    else f"{history_entry.status}: {approval.requested_action[:70]}"
                                ),
                                self._canonical_data(
                                    session_id=session_id,
                                    objective_id=approval.objective_id,
                                    source_surface="approval_queue",
                                    actor_type="operator",
                                    evidence_level="observed",
                                    observed_vs_expected={"status": history_entry.status, "details": history_entry.note},
                                    collector_status="ok",
                                    scope_relation="review_state",
                                    evidence_refs=list(history_entry.evidence_refs) or [f"local://cleanhouse/approval-queue/{approval.id}"],
                                    raw_evidence_ref=f"local://cleanhouse/approval-queue/{approval.id}/history/{history_entry.id}",
                                    data={
                                    "approval_id": approval.id,
                                    "approval_history_id": history_entry.id,
                                    "approval_action": history_entry.action,
                                    "status": history_entry.status,
                                    "previous_status": history_entry.previous_status,
                                    "reason": approval.reason,
                                    "reviewer": history_entry.reviewer,
                                    "reviewer_note": history_entry.note,
                                    "prompt_id": approval.prompt_id,
                                    "objective_id": approval.objective_id,
                                    "evidence_refs": list(history_entry.evidence_refs),
                                    },
                                ),
                            ))
                    else:
                        raw_entries.append((
                            approval.created_at,
                            "approval_queue",
                            approval.requested_action[:80],
                            self._canonical_data(
                                session_id=session_id,
                                objective_id=approval.objective_id,
                                source_surface="approval_queue",
                                actor_type="operator",
                                evidence_level="observed",
                                observed_vs_expected={"status": approval.status, "details": approval.reason},
                                collector_status="ok",
                                scope_relation="review_state",
                                evidence_refs=list(approval.evidence_refs) or [f"local://cleanhouse/approval-queue/{approval.id}"],
                                raw_evidence_ref=f"local://cleanhouse/approval-queue/{approval.id}",
                                data={
                                "approval_id": approval.id,
                                "status": approval.status,
                                "reason": approval.reason,
                                "prompt_id": approval.prompt_id,
                                "objective_id": approval.objective_id,
                                "evidence_refs": list(approval.evidence_refs),
                                },
                            ),
                        ))

        raw_entries.extend(self._persisted_timeline_entries(session_id, raw_entries))
        raw_entries.sort(key=lambda e: e[0])

        entries: list[TimelineEntry] = []
        previous_id: Optional[str] = None
        for idx, (ts, etype, label, data) in enumerate(raw_entries):
            eid = f"tl:{session_id}:{idx}"
            entries.append(TimelineEntry(
                event_id=eid,
                timestamp=ts,
                event_type=etype,
                previous_event_id=previous_id,
                status="observed" if etype in ("intent", "command", "prompt", "approval_queue", "action") else "inferred",
                label=label,
                data=data,
            ))
            previous_id = eid

        if not entries:
            ts = _now_iso()
            eid = f"tl:{session_id}:0"
            entries.append(TimelineEntry(
                event_id=eid,
                timestamp=ts,
                event_type="unknown",
                previous_event_id=None,
                status="unknown",
                label="No events recorded for this session",
                data=self._canonical_data(
                    session_id=session_id,
                    objective_id=self._objective_id_for_session(session_id),
                    source_surface="timeline",
                    actor_type="cleanhouse",
                    evidence_level="unknown",
                    observed_vs_expected={"status": "unknown", "details": "no observable data"},
                    collector_status="no_events",
                    scope_relation="unknown",
                    evidence_refs=[f"local://cleanhouse/timeline/{eid}"],
                    raw_evidence_ref=f"local://cleanhouse/timeline/{eid}",
                    data={},
                ),
            ))
            record_ts = ts
            origin = ts
            status = "unknown"
        else:
            record_ts = _now_iso()
            origin = entries[0].timestamp
            status = "ok"

        record = TimelineRecord(
            id=f"timeline:{_fingerprint(session_id, record_ts)}",
            session_id=session_id,
            timestamp=record_ts,
            origin=origin,
            entry_count=len(entries),
            entries=tuple(entries),
        )
        with self._lock:
            self._timelines[record.id] = record
        result = {
            "status": status,
            "id": record.id,
            "session_id": session_id,
            "origin": origin,
            "entry_count": record.entry_count,
            "entries": [e.to_dict() for e in entries],
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("timeline", record.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def get_timelines(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            records = list(self._timelines.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        return {
            "timelines": [r.to_dict() for r in records],
            "count": len(records),
        }

    def classify(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        intent = self._intent_record_by_id(session_id)

        if not intent:
            return {"status": "unknown", "session_id": session_id, "signal_count": 0, "signals": []}

        scope_prefix = intent.scope.strip("/") + "/" if intent.scope else ""
        now = _now_iso()
        signals: list[ClassifiedSignal] = []

        timeline_entries: list[TimelineEntry] = []
        with self._lock:
            for tl in self._timelines.values():
                if tl.session_id == session_id:
                    timeline_entries.extend(tl.entries)

        corr_edges: list[CorrelationEdge] = []
        with self._lock:
            for corr in self._correlations.values():
                if corr.session_id == session_id:
                    corr_edges.extend(corr.edges)

        session_diffs: list[DiffRecord] = []
        with self._lock:
            for diff in self._diffs.values():
                if diff.session_id == session_id:
                    session_diffs.append(diff)
        scope_analysis = _build_scope_analysis(intent.scope, session_diffs)

        for entry in timeline_entries:
            if entry.event_type == "command":
                rc = entry.data.get("returncode", 0)
                cmd = entry.data.get("command", entry.label)
                if rc == 0:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id)}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="drift",
                        source="command",
                        source_id=entry.event_id,
                        description=f"Command '{cmd}' completed normally",
                        confidence=0.85, uncertainty=0.15,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={"status": "matched", "details": "exit 0"},
                    ))
                else:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id)}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="deviation",
                        source="command",
                        source_id=entry.event_id,
                        description=f"Command '{cmd}' returned exit {rc}",
                        confidence=0.65, uncertainty=0.35,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={"status": "unexpected", "details": f"exit {rc}"},
                    ))

            elif entry.event_type == "action":
                rc = entry.data.get("exit_code", 0)
                cmd = entry.data.get("command", entry.label)
                if rc == 0:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id)}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="drift",
                        source="action",
                        source_id=entry.event_id,
                        description=f"Tool action '{cmd}' completed normally",
                        confidence=0.85, uncertainty=0.15,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={"status": "matched", "details": "exit 0"},
                    ))
                else:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id)}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="deviation",
                        source="action",
                        source_id=entry.event_id,
                        description=f"Tool action '{cmd}' returned exit {rc}",
                        confidence=0.65, uncertainty=0.35,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={"status": "unexpected", "details": f"exit {rc}"},
                    ))

            elif entry.event_type == "diff":
                has_in_scope = False
                has_out_of_scope = False
                for diff in session_diffs:
                    for change in diff.changes:
                        if scope_prefix and not change.path.startswith(scope_prefix):
                            has_out_of_scope = True
                        else:
                            has_in_scope = True

                if has_in_scope:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id, 'drift')}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="drift",
                        source="diff",
                        source_id=entry.event_id,
                        description="File changes within scope",
                        confidence=0.80, uncertainty=0.20,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={"status": "matched", "details": "within scope"},
                    ))
                if has_out_of_scope:
                    signals.append(ClassifiedSignal(
                        id=f"sig:{_fingerprint(session_id, entry.event_id, 'deviation')}",
                        session_id=session_id,
                        timestamp=entry.timestamp,
                        signal_class="deviation",
                        source="diff",
                        source_id=entry.event_id,
                        description=(
                            "File changes outside declared scope "
                            f"(scope_weight={scope_analysis['scope_weight']})"
                        ),
                        confidence=0.72, uncertainty=0.28,
                        evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                        observed_vs_expected={
                            "status": "unexpected",
                            "details": (
                                f"{scope_analysis['out_of_scope_count']} of "
                                f"{scope_analysis['change_count']} change(s) outside declared scope"
                            ),
                            "scope_weight": str(scope_analysis["scope_weight"]),
                        },
                    ))

            elif entry.event_type == "unknown":
                signals.append(ClassifiedSignal(
                    id=f"sig:{_fingerprint(session_id, entry.event_id)}",
                    session_id=session_id,
                    timestamp=entry.timestamp,
                    signal_class="risk",
                    source="timeline",
                    source_id=entry.event_id,
                    description="No events recorded for session",
                    confidence=0.0, uncertainty=1.0,
                    evidence_refs=(f"local://cleanhouse/timeline/{entry.event_id}",),
                    observed_vs_expected={"status": "unknown", "details": "no observable data"},
                ))

        for edge in corr_edges:
            if edge.target_type == "unknown":
                eid = f"sig:{_fingerprint(session_id, 'corr', edge.source_id, edge.target_id)}"
                signals.append(ClassifiedSignal(
                    id=eid,
                    session_id=session_id,
                    timestamp=now,
                    signal_class="risk",
                    source="correlation",
                    source_id=f"{edge.source_id}->{edge.target_id}",
                    description=f"Unmatched {edge.source_type}, no observable found",
                    confidence=0.0, uncertainty=1.0,
                    evidence_refs=(),
                    observed_vs_expected={"status": "unknown", "details": "gap in observable chain"},
                ))

        with self._lock:
            for sig in signals:
                self._signals[sig.id] = sig

        return {
            "status": "ok",
            "session_id": session_id,
            "signal_count": len(signals),
            "signals": [s.to_dict() for s in signals],
        }

    def get_signals(
        self,
        session_id: Optional[str] = None,
        signal_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            records = list(self._signals.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        if signal_class:
            records = [r for r in records if r.signal_class == signal_class]
        return {
            "signals": [r.to_dict() for r in records],
            "count": len(records),
        }

    def generate_alerts(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        signals_result = self.get_signals(session_id=session_id)
        all_signals = signals_result["signals"]
        now = _now_iso()

        def _classify_severity(count: int, avg_conf: float) -> tuple[str, float, str]:
            if count >= 4 or avg_conf <= 0.05:
                return ("high", 0.0, "{alert} confirmed through consistent signal pattern")
            if count >= 2:
                return ("medium", round(avg_conf * 0.85, 3), "{alert} detected with partial evidence")
            return ("low", max(avg_conf, 0.45), "Possible {alert} observed")

        alert_builders: list[tuple[str, str, str, list[dict]]] = []
        # (alert_type, source, description_template, matching_signals)

        dev_commands = [s for s in all_signals if s["source"] == "command" and s["signal_class"] == "deviation"]
        dev_actions = [s for s in all_signals if s["source"] == "action" and s["signal_class"] == "deviation"]
        if dev_commands or dev_actions:
            mismatch_signals = dev_commands + dev_actions
            alert_builders.append((
                "prompt_action_mismatch", "command",
                f"{len(mismatch_signals)} command/action signal(s) with unexpected exit status",
                mismatch_signals,
            ))

        dev_diffs = [s for s in all_signals if s["source"] == "diff" and s["signal_class"] == "deviation"]
        if dev_diffs:
            alert_builders.append((
                "scope_expansion", "diff",
                f"{len(dev_diffs)} diff signal(s) with out-of-scope file changes",
                dev_diffs,
            ))

        risk_corr = [s for s in all_signals if s["source"] == "correlation" and s["signal_class"] == "risk"]
        risk_timeline = [s for s in all_signals if s["source"] == "timeline" and s["signal_class"] == "risk"]
        endpoint_signals = risk_corr + risk_timeline
        if endpoint_signals:
            alert_builders.append((
                "endpoint_drift", "correlation",
                f"{len(endpoint_signals)} signal(s) with unmatched correlation or unknown timeline",
                endpoint_signals,
            ))

        alerts: list[SignalAlert] = []
        for alert_type, src, desc, sigs in alert_builders:
            sig_count = len(sigs)
            avg_conf = sum(s["confidence"] for s in sigs) / sig_count if sig_count else 0.0
            severity, alert_conf, rationale_tpl = _classify_severity(sig_count, avg_conf)

            source_ids = tuple(s["source_id"] for s in sigs)
            evidence_refs = tuple(
                ref for s in sigs for ref in s.get("evidence_refs", [])
            )
            rationale = rationale_tpl.format(alert=alert_type.replace("_", " ").title())

            alerts.append(SignalAlert(
                id=f"alert:{_fingerprint(session_id, alert_type, now)}",
                session_id=session_id,
                timestamp=now,
                alert_type=alert_type,
                severity=severity,
                source=src,
                source_ids=source_ids,
                description=desc,
                confidence=alert_conf,
                uncertainty=round(1.0 - alert_conf, 3) if alert_conf > 0 else 1.0,
                evidence_refs=evidence_refs,
                rationale=rationale,
            ))

        if not alerts:
            ts = _now_iso()
            alerts.append(SignalAlert(
                id=f"alert:{_fingerprint(session_id, 'none', ts)}",
                session_id=session_id,
                timestamp=ts,
                alert_type="endpoint_drift",
                severity="high",
                source="correlation",
                source_ids=(),
                description="No classified signals available for alert generation",
                confidence=0.0,
                uncertainty=1.0,
                evidence_refs=(),
                rationale="No signal data to derive alerts from — entire session is unknown",
            ))

        with self._lock:
            for a in alerts:
                self._alerts[a.id] = a

        for alert in alerts:
            if alert.alert_type != "scope_expansion":
                continue
            self._ensure_operator_notification(
                notification_type="scope_drift_detected",
                session_id=session_id,
                objective_id=self._objective_id_for_session(session_id),
                severity="warning" if alert.severity != "high" else "critical",
                summary=alert.description,
                evidence_refs=alert.evidence_refs,
                source="alert",
                metadata={"alert_id": alert.id, "alert_type": alert.alert_type},
            )

        return {
            "status": "ok",
            "session_id": session_id,
            "alert_count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }

    def get_alerts(
        self,
        session_id: Optional[str] = None,
        alert_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            records = list(self._alerts.values())
        records.sort(key=lambda r: r.timestamp, reverse=True)
        if session_id:
            records = [r for r in records if r.session_id == session_id]
        if alert_type:
            records = [r for r in records if r.alert_type == alert_type]
        return {
            "alerts": [r.to_dict() for r in records],
            "count": len(records),
        }

    def _runtime_gaps_from_manifest(self, collector_manifest: Dict[str, Any]) -> list[Dict[str, Any]]:
        gaps: list[Dict[str, Any]] = []
        surfaces = collector_manifest.get("surfaces", {}) if isinstance(collector_manifest, dict) else {}
        for name, surface in surfaces.items():
            if not isinstance(surface, dict):
                continue
            collector_status = surface.get("collector_status")
            if collector_status in {None, "", "ok"}:
                continue
            gaps.append({
                "source": name,
                "event_id": f"collector:{name}",
                "label": "unknown" if collector_status in {"dependency_missing", "no_baseline", "inactive"} else "collector_gap",
                "description": f"{name} collector status: {collector_status}",
                "collector_status": collector_status,
                "evidence_refs": [f"local://cleanhouse/collector/{name}"],
            })
        return gaps

    def _stable_collector_manifest_for_hash(self, collector_manifest: Dict[str, Any]) -> Dict[str, Any]:
        stable = copy.deepcopy(collector_manifest or {})
        stable.pop("generated_at", None)
        dynamic_runtime_fields = {
            "status",
            "state",
            "queue",
            "queue_depth",
            "queue_maxsize",
            "stop_requested",
            "metrics",
            "last_error",
        }
        runtime = stable.get("runtime")
        if isinstance(runtime, dict):
            runtime.pop("queue", None)
            writer = runtime.get("writer")
            if isinstance(writer, dict):
                for key in dynamic_runtime_fields:
                    writer.pop(key, None)
            watcher = runtime.get("watcher")
            if isinstance(watcher, dict):
                for key in ("status", "state", "last_error", "watch_dir"):
                    watcher.pop(key, None)
            runtime_event_writer = runtime.get("runtime_event_writer")
            if isinstance(runtime_event_writer, dict):
                runtime_event_writer.pop("recent_failures", None)
                runtime_event_writer.pop("latest_failure", None)
        surfaces = stable.get("surfaces")
        if isinstance(surfaces, dict):
            for name in ("event_writer", "filesystem_watcher", "runtime_event_writer"):
                surface = surfaces.get(name)
                if not isinstance(surface, dict):
                    continue
                for key in dynamic_runtime_fields:
                    surface.pop(key, None)
                if name == "filesystem_watcher":
                    surface.pop("watch_dir", None)
                if name == "runtime_event_writer":
                    surface.pop("latest_failure", None)
        return stable

    def _build_lineage_graph(
        self,
        session_id: str,
        t_entries: Sequence[Dict[str, Any]],
        receipt_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        objective_id = self._objective_id_for_session(session_id)
        nodes: list[Dict[str, Any]] = [{
            "id": objective_id or f"objective:unknown:{session_id}",
            "type": "objective",
            "label": objective_id or "unknown objective",
            "evidence_level": "observed" if objective_id else "unknown",
            "evidence_refs": [f"local://cleanhouse/session/{session_id}"],
        }]
        edges: list[Dict[str, Any]] = []
        previous_node = nodes[0]["id"]
        for entry in t_entries:
            node_id = entry.get("event_id") or f"event:{_fingerprint(session_id, entry.get('timestamp', ''), entry.get('event_type', ''))}"
            node_type = entry.get("event_type", "event")
            evidence_refs = entry.get("evidence_refs") or [f"local://cleanhouse/timeline/{node_id}"]
            nodes.append({
                "id": node_id,
                "type": node_type,
                "label": entry.get("label", node_type),
                "timestamp": entry.get("timestamp", ""),
                "evidence_level": entry.get("evidence_level", entry.get("status", "unknown")),
                "evidence_refs": evidence_refs,
                "scope_relation": entry.get("scope_relation", "unknown"),
            })
            edges.append({
                "source_id": previous_node,
                "target_id": node_id,
                "relationship": "objective_lineage" if previous_node == nodes[0]["id"] else "temporal_sequence",
                "evidence_level": entry.get("evidence_level", entry.get("status", "unknown")),
                "evidence_refs": evidence_refs,
            })
            previous_node = node_id
        if receipt_id:
            nodes.append({
                "id": receipt_id,
                "type": "receipt",
                "label": receipt_id,
                "evidence_level": "observed",
                "evidence_refs": [f"local://cleanhouse/receipt/{receipt_id}"],
            })
            edges.append({
                "source_id": previous_node,
                "target_id": receipt_id,
                "relationship": "captured_in_receipt",
                "evidence_level": "observed",
                "evidence_refs": [f"local://cleanhouse/receipt/{receipt_id}"],
            })
        return {
            "schema": "cleanhouse.lineage_graph.v1",
            "session_id": session_id,
            "objective_id": objective_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    def _build_drift_reasons(
        self,
        scope_analysis: Dict[str, Any],
        alerts: Sequence[Dict[str, Any]],
        gaps: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        reasons: list[Dict[str, Any]] = []
        for cluster in scope_analysis.get("path_clusters", []) if isinstance(scope_analysis, dict) else []:
            if not isinstance(cluster, dict):
                continue
            reasons.append({
                "reason_id": f"drift:{_fingerprint(cluster.get('cluster', ''), cluster.get('relation', ''))}",
                "category": "scope",
                "relation": cluster.get("relation", "unknown"),
                "summary": cluster.get("explanation", ""),
                "evidence_level": "observed",
                "evidence_refs": [f"local://cleanhouse/scope/{_fingerprint(cluster.get('cluster', ''))}"],
                "data": cluster,
            })
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            alert_source_ids = alert.get("source_ids", [])
            if not isinstance(alert_source_ids, list):
                alert_source_ids = []
            reasons.append({
                "reason_id": f"drift:{_fingerprint(alert.get('alert_type', ''), alert.get('description', ''), alert.get('source', ''), alert.get('severity', ''), *[str(item) for item in alert_source_ids])}",
                "category": alert.get("alert_type", "alert"),
                "relation": alert.get("observed_vs_expected", {}).get("status", "inferred") if isinstance(alert.get("observed_vs_expected"), dict) else "inferred",
                "summary": alert.get("description", ""),
                "evidence_level": "inferred",
                "evidence_refs": list(alert.get("evidence_refs", [])),
                "data": {"source": alert.get("source", ""), "severity": alert.get("severity", "")},
            })
        for gap in gaps:
            reasons.append({
                "reason_id": f"drift:{_fingerprint(gap.get('event_id', ''), gap.get('source', ''))}",
                "category": "runtime_gap",
                "relation": "unknown",
                "summary": gap.get("description", ""),
                "evidence_level": "unknown",
                "evidence_refs": list(gap.get("evidence_refs", [])),
                "data": gap,
            })
        return reasons

    def _latest_rollback_state(self, session_id: str) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._rollback_records_for_session(session_id)]
        if not records:
            return {"status": "not_requested", "records": [], "count": 0}
        records.sort(key=lambda item: item.get("executed_at") or item.get("requested_at") or "", reverse=True)
        return {
            "status": records[0].get("status", "not_requested"),
            "records": records,
            "count": len(records),
            "latest": records[0],
        }

    def _persist_rollback_record(self, record: RollbackRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "rollback",
            record.id,
            {"status": "ok", "rollback": record.to_dict()},
        )

    def _rollback_record_from_dict(self, rollback: Dict[str, Any]) -> RollbackRecord:
        status = str(rollback.get("status", "not_requested"))
        if status not in ROLLBACK_STATES:
            status = "not_requested"
        return RollbackRecord(
            id=str(rollback.get("id", "")),
            session_id=str(rollback.get("session_id", "")),
            objective_id=rollback.get("objective_id"),
            receipt_id=rollback.get("receipt_id"),
            status=status,
            requested_path=str(rollback.get("requested_path", "")),
            snapshot_id=rollback.get("snapshot_id"),
            requested_at=str(rollback.get("requested_at", "")),
            executed_at=rollback.get("executed_at"),
            evidence_refs=tuple(str(ref) for ref in rollback.get("evidence_refs", [])),
            before_hash=rollback.get("before_hash"),
            target_hash=rollback.get("target_hash"),
            after_hash=rollback.get("after_hash"),
            verification=copy.deepcopy(rollback.get("verification", {})) if isinstance(rollback.get("verification"), dict) else {},
            metadata=copy.deepcopy(rollback.get("metadata", {})) if isinstance(rollback.get("metadata"), dict) else {},
        )

    def _all_rollback_records(self) -> list[RollbackRecord]:
        with self._lock:
            records = {record.id: record for record in self._rollback_records.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("rollback"):
                payload = artifact.get("data", {})
                rollback = payload.get("rollback", payload) if isinstance(payload, dict) else None
                if not isinstance(rollback, dict):
                    continue
                record = self._rollback_record_from_dict(rollback)
                if record.id:
                    records.setdefault(record.id, record)
        return list(records.values())

    def _rollback_records_for_session(self, session_id: str) -> list[RollbackRecord]:
        return [record for record in self._all_rollback_records() if record.session_id == session_id]

    def _rollback_record_by_id(self, rollback_id: str) -> Optional[RollbackRecord]:
        for record in self._all_rollback_records():
            if record.id == rollback_id:
                return record
        return None

    def request_rollback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        requested_path = str(data.get("path") or data.get("requested_path") or "").strip()
        if not requested_path:
            return {"status": "error", "message": "path is required"}
        snapshot_id = str(data.get("snapshot_id") or "").strip() or None
        objective_id = str(data.get("objective_id") or "").strip() or self._objective_id_for_session(session_id)
        receipt_id = str(data.get("receipt_id") or "").strip() or None
        evidence_refs = tuple(str(ref).strip() for ref in data.get("evidence_refs", []) if str(ref).strip()) if isinstance(data.get("evidence_refs"), list) else ()
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if data.get("repo_path") and "repo_path" not in metadata:
            metadata = {**metadata, "repo_path": str(data.get("repo_path"))}

        target_hash = None
        route_available = False
        if snapshot_id:
            with self._lock:
                snapshot = self._snapshots.get(snapshot_id)
                content_map = self._snapshot_contents.get(snapshot_id, {})
            if snapshot and requested_path in content_map:
                route_available = True
                for entry in snapshot.files:
                    if entry.path == requested_path:
                        target_hash = entry.hash
                        break

        now = _now_iso()
        rollback_id = f"rollback:{_fingerprint(session_id, requested_path, now)}"
        rollback = RollbackRecord(
            id=rollback_id,
            session_id=session_id,
            objective_id=objective_id or None,
            receipt_id=receipt_id,
            status="requested_route_available" if route_available else "requested_no_route",
            requested_path=requested_path,
            snapshot_id=snapshot_id,
            requested_at=now,
            executed_at=None,
            evidence_refs=evidence_refs or (f"local://cleanhouse/rollback/{rollback_id}",),
            before_hash=None,
            target_hash=target_hash,
            after_hash=None,
            verification={
                "route_available": route_available,
                "reason": "snapshot content available" if route_available else "no snapshot content for requested path",
            },
            metadata=metadata,
        )
        with self._lock:
            self._rollback_records[rollback.id] = rollback
        self._persist_rollback_record(rollback)
        _insert_runtime_event(
            event_type="rollback_requested",
            path=f"/rollback/{rollback_id}",
            summary=f"rollback_requested: {requested_path}",
            session_id=session_id,
            objective_id=objective_id or None,
            source_surface="rollback",
            actor_type="operator",
            evidence_level="observed",
            observed_vs_expected={"status": rollback.status, "details": rollback.verification["reason"]},
            collector_status="ok",
            scope_relation="recovery_state",
            evidence_refs=rollback.evidence_refs,
            raw_evidence_ref=f"local://cleanhouse/rollback/{rollback_id}",
            data=rollback.to_dict(),
        )
        return {"status": "ok", "rollback": rollback.to_dict()}

    def execute_rollback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        rollback_id = str(data.get("rollback_id") or "").strip()
        if not rollback_id:
            return {"status": "error", "message": "rollback_id is required"}
        repo_path = str(data.get("repo_path") or "").strip()
        with self._lock:
            existing = self._rollback_records.get(rollback_id)
        if existing is None:
            existing = self._rollback_record_by_id(rollback_id)
        if existing is None:
            return {"status": "not_found", "message": f"rollback not found: {rollback_id}"}
        if not repo_path:
            repo_path = str(existing.metadata.get("repo_path", "")).strip()
        if existing.status != "requested_route_available" or not existing.snapshot_id:
            updated_status = "requested_no_route"
            verification = {
                **existing.verification,
                "executed": False,
                "reason": "rollback route unavailable",
            }
            after_hash = None
        else:
            with self._lock:
                content_map = self._snapshot_contents.get(existing.snapshot_id, {})
            encoded = content_map.get(existing.requested_path)
            target_root = Path(repo_path).resolve() if repo_path else None
            target_path = target_root / existing.requested_path if target_root else None
            try:
                if encoded is None or target_path is None:
                    raise ValueError("snapshot content or repo_path missing")
                resolved_target = target_path.resolve()
                if not str(resolved_target).startswith(str(target_root)):
                    raise ValueError("rollback path escapes repo_path")
                resolved_target.parent.mkdir(parents=True, exist_ok=True)
                before_hash = _hash_file_for_snapshot(resolved_target) if resolved_target.exists() else None
                resolved_target.write_bytes(base64.b64decode(encoded.encode("ascii")))
                after_hash = _hash_file_for_snapshot(resolved_target)
                verified = after_hash == existing.target_hash
                updated_status = "executed_verified" if verified else "executed_verification_failed"
                verification = {
                    "executed": True,
                    "route_available": True,
                    "verified": verified,
                    "repo_path": str(target_root),
                    "reason": "post-rollback hash matched snapshot" if verified else "post-rollback hash mismatch",
                }
            except Exception as exc:
                before_hash = None
                after_hash = None
                updated_status = "executed_verification_failed"
                verification = {
                    "executed": False,
                    "route_available": True,
                    "verified": False,
                    "reason": str(exc),
                }

        if "before_hash" not in locals():
            before_hash = existing.before_hash
        executed_at = _now_iso()
        updated = RollbackRecord(
            id=existing.id,
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            receipt_id=existing.receipt_id,
            status=updated_status,
            requested_path=existing.requested_path,
            snapshot_id=existing.snapshot_id,
            requested_at=existing.requested_at,
            executed_at=executed_at,
            evidence_refs=existing.evidence_refs,
            before_hash=before_hash,
            target_hash=existing.target_hash,
            after_hash=after_hash,
            verification=verification,
            metadata=existing.metadata,
        )
        with self._lock:
            self._rollback_records[updated.id] = updated
        self._persist_rollback_record(updated)
        _insert_runtime_event(
            event_type="rollback_executed",
            path=f"/rollback/{updated.id}",
            summary=f"rollback_executed: {updated.status} {updated.requested_path}",
            session_id=updated.session_id,
            objective_id=updated.objective_id,
            source_surface="rollback",
            actor_type="operator",
            evidence_level="observed" if updated.status == "executed_verified" else "unknown",
            observed_vs_expected={"status": updated.status, "details": verification.get("reason", "")},
            collector_status="ok",
            scope_relation="recovery_state",
            evidence_refs=updated.evidence_refs,
            raw_evidence_ref=f"local://cleanhouse/rollback/{updated.id}",
            data=updated.to_dict(),
        )
        if updated.status == "executed_verification_failed":
            self._ensure_operator_notification(
                notification_type="runtime_recovery_failure",
                session_id=updated.session_id,
                objective_id=updated.objective_id,
                severity="critical",
                summary=f"runtime recovery failure: {verification.get('reason', updated.requested_path)}",
                evidence_refs=[*updated.evidence_refs, f"local://cleanhouse/rollback/{updated.id}"],
                source="rollback",
                metadata={
                    "rollback_id": updated.id,
                    "receipt_id": updated.receipt_id,
                    "requested_path": updated.requested_path,
                    "verification": copy.deepcopy(verification),
                },
            )
        return {"status": "ok", "rollback": updated.to_dict()}

    def get_rollbacks(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._all_rollback_records()]
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        records.sort(key=lambda item: item.get("executed_at") or item.get("requested_at") or "", reverse=True)
        return {"status": "ok", "rollbacks": records, "count": len(records)}

    def _ensure_scope_approval(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        receipt_id: str,
        scope_analysis: Dict[str, Any],
        evidence_refs: Sequence[str],
    ) -> Optional[Dict[str, Any]]:
        if int(scope_analysis.get("out_of_scope_count", 0) or 0) <= 0:
            return None
        policy_id = "scope_out_of_scope_v1"
        with self._lock:
            for approval in self._approval_queue.values():
                if approval.session_id == session_id and approval.metadata.get("policy_id") == policy_id:
                    return approval.to_dict()
        result = self.create_approval_queue_item({
            "session_id": session_id,
            "requested_action": "review out-of-scope mutation",
            "reason": "receipt contains file mutation outside declared objective scope",
            "objective_id": objective_id,
            "evidence_refs": list(evidence_refs),
            "source": "approval_policy",
            "metadata": {
                "receipt_id": receipt_id,
                "policy_id": policy_id,
                "route_ownership": "review_state_only",
                "scope_weight": scope_analysis.get("scope_weight"),
            },
        })
        return result.get("approval") if result.get("status") == "ok" else None

    def build_receipt(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        intent = self._intent_record_by_id(session_id)
        prompt_context = self._latest_prompt_context(session_id)

        declared_scope = intent.scope if intent else (prompt_context.scope if prompt_context else "")
        objective_id = prompt_context.objective_id if prompt_context else ""
        now = _now_iso()
        receipt_id = f"receipt:{_fingerprint(session_id, now)}"
        with self._lock:
            corr_edges: list[CorrelationEdge] = [
                edge
                for corr in self._correlations.values()
                if corr.session_id == session_id
                for edge in corr.edges
            ]
            session_diffs = [
                diff for diff in self._diffs.values()
                if diff.session_id == session_id
            ]

        scope_analysis = _build_scope_analysis(declared_scope, session_diffs)
        approval_seed_refs = [f"local://cleanhouse/receipt/{receipt_id}"]
        approval_seed_refs.extend(f"local://cleanhouse/diff/{diff.id}" for diff in session_diffs)
        policy_approval = self._ensure_scope_approval(
            session_id=session_id,
            objective_id=objective_id or None,
            receipt_id=receipt_id,
            scope_analysis=scope_analysis,
            evidence_refs=approval_seed_refs,
        )

        timeline_result = self.build_timeline(session_id=session_id)
        alerts_result = self.generate_alerts(session_id=session_id)

        timeline = self.get_timelines(session_id=session_id)
        timeline_records = timeline.get("timelines", [])
        t_entries: list[dict] = []
        if timeline_records:
            t_entries = timeline_records[0].get("entries", [])

        alert_records = alerts_result.get("alerts", [])
        with self._lock:
            cached_status = copy.deepcopy(self._cache.get("status", {}).get("value", {}))
        cached_status_data = cached_status.get("data", {}) if isinstance(cached_status, dict) else {}
        collector_manifest = (
            cached_status_data.get("collector_manifest", {})
            if isinstance(cached_status_data, dict) and cached_status_data.get("collector_manifest")
            else self._build_collector_manifest()
        )

        gaps: list[dict] = []
        evidence_index: list[dict] = []
        timestamps: list[str] = []

        for entry in t_entries:
            ts = entry.get("timestamp", "")
            if ts:
                timestamps.append(ts)
            etype = entry.get("event_type", "")
            label = entry.get("status", "unknown")
            event_id = entry.get("event_id", "")

            if etype == "unknown" or label == "unknown":
                gaps.append({
                    "source": "timeline",
                    "event_id": event_id,
                    "label": "unknown",
                    "description": entry.get("label", "No observable data"),
                })

            evidence_index.append({
                "ref": f"local://cleanhouse/timeline/{event_id}",
                "source": etype,
                "label": label,
            })

        for edge in corr_edges:
            if edge.target_type == "unknown":
                gaps.append({
                    "source": "correlation",
                    "event_id": f"{edge.source_id}->{edge.target_id}",
                    "label": "unknown",
                    "description": f"Unmatched {edge.source_type}, no observable found",
                })

        runtime_gaps = self._runtime_gaps_from_manifest(collector_manifest)
        for runtime_gap in runtime_gaps:
            if not any(
                gap.get("event_id") == runtime_gap.get("event_id")
                and gap.get("source") == runtime_gap.get("source")
                for gap in gaps
            ):
                gaps.append(runtime_gap)

        timestamps.sort()
        origin = timestamps[0] if timestamps else ""
        duration: Optional[float] = None
        if len(timestamps) >= 2:
            try:
                dt_first = datetime.fromisoformat(timestamps[0])
                dt_last = datetime.fromisoformat(timestamps[-1])
                duration = round((dt_last - dt_first).total_seconds(), 3)
            except Exception:
                pass

        has_unknown = any(g["label"] == "unknown" for g in gaps)
        has_inferred = any(e.get("status") == "inferred" for e in t_entries)
        if has_unknown:
            verdict = "unknown"
        elif has_inferred:
            verdict = "inferred"
        else:
            verdict = "observed"

        event_count = len(t_entries)
        alert_count = len(alert_records)
        gap_count = len(gaps)

        scope = declared_scope
        tool = intent.tool_identity if intent else (prompt_context.tool_identity if prompt_context else "")
        repo = intent.repo_path if intent else (prompt_context.repo_path if prompt_context else "")
        intent_text = intent.text if intent else (prompt_context.text if prompt_context else "")
        prompt_id = prompt_context.id if prompt_context else ""
        context_text = prompt_context.context if prompt_context else ""
        rollback_state = self._latest_rollback_state(session_id)
        lineage_graph = self._build_lineage_graph(session_id, t_entries, receipt_id=receipt_id)
        drift_reasons = self._build_drift_reasons(scope_analysis, alert_records, gaps)

        event_hash_chain: list[str] = []
        prev = ""
        for event in t_entries:
            canonical = json.dumps(event, sort_keys=True, default=str)
            prev = hashlib.sha256((prev + canonical).encode()).hexdigest()
            event_hash_chain.append(prev)

        summary_text = (
            f"Session for '{intent_text}' completed with "
            f"{event_count} event(s), {alert_count} alert(s), "
            f"{gap_count} unresolved gap(s). "
            f"Verdict: {verdict}."
        )

        def _strip_mutable(r: dict) -> dict:
            return {k: v for k, v in r.items() if k not in ("id", "timestamp")}

        core_alerts = [_strip_mutable(a) for a in alert_records]
        core_gaps = [_strip_mutable(g) for g in gaps]
        stable_collector_manifest = self._stable_collector_manifest_for_hash(collector_manifest)
        stable_lineage_graph = self._build_lineage_graph(session_id, t_entries, receipt_id=None)

        receipt_core = {
            "metadata": {
                "session_id": session_id,
                "origin": origin,
                "duration_seconds": duration,
                "tool_identity": tool,
                "scope": scope,
                "repo_path": repo,
                "prompt_id": prompt_id,
                "objective_id": objective_id,
                "context": context_text,
                "event_count": event_count,
                "alert_count": alert_count,
                "gap_count": gap_count,
            },
            "summary": {"verdict": verdict, "text": summary_text},
            "events": t_entries,
            "alerts": core_alerts,
            "gaps": core_gaps,
            "evidence_index": evidence_index,
            "scope_analysis": scope_analysis,
            "collector_manifest": stable_collector_manifest,
            "runtime_gaps": runtime_gaps,
            "lineage_graph": stable_lineage_graph,
            "drift_reasons": drift_reasons,
            "rollback_state": rollback_state,
        }
        root_hash = hashlib.sha256(
            json.dumps(receipt_core, sort_keys=True, default=str).encode()
        ).hexdigest()

        integrity = {
            "algorithm": "sha-256",
            "root_hash": root_hash,
            "event_hash_chain": event_hash_chain,
            "event_count": len(event_hash_chain),
            "purpose": "receipt integrity verification",
        }

        receipt = SessionReceipt(
            id=receipt_id,
            session_id=session_id,
            timestamp=now,
            metadata={
                "session_id": session_id,
                "origin": origin,
                "duration_seconds": duration,
                "tool_identity": tool,
                "scope": scope,
                "repo_path": repo,
                "prompt_id": prompt_id,
                "objective_id": objective_id,
                "context": context_text,
                "event_count": event_count,
                "alert_count": alert_count,
                "gap_count": gap_count,
            },
            summary={
                "verdict": verdict,
                "text": summary_text,
            },
            events=tuple(t_entries),
            alerts=tuple(alert_records),
            gaps=tuple(gaps),
            evidence_index=tuple(evidence_index),
            scope_analysis=scope_analysis,
            integrity=integrity,
            collector_manifest=collector_manifest,
            runtime_gaps=tuple(runtime_gaps),
            lineage_graph=lineage_graph,
            drift_reasons=tuple(drift_reasons),
            rollback_state=rollback_state,
        )

        with self._lock:
            self._receipts[receipt.id] = receipt

        result = {
            "status": "ok",
            "id": receipt.id,
            "session_id": session_id,
            "metadata": receipt.metadata,
            "summary": receipt.summary,
            "events": t_entries,
            "alerts": alert_records,
            "gaps": gaps,
            "evidence_index": evidence_index,
            "scope_analysis": scope_analysis,
            "integrity": integrity,
            "collector_manifest": collector_manifest,
            "runtime_gaps": runtime_gaps,
            "lineage_graph": lineage_graph,
            "drift_reasons": drift_reasons,
            "rollback_state": rollback_state,
        }
        if policy_approval is not None:
            result["approval_policy"] = {
                "policy_id": "scope_out_of_scope_v1",
                "approval_id": policy_approval.get("id", ""),
                "status": policy_approval.get("status", ""),
                "route_ownership": "review_state_only",
            }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("receipt", receipt.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        notification = self._ensure_operator_notification(
            notification_type="receipt_finalized",
            session_id=session_id,
            objective_id=objective_id or None,
            severity="info",
            summary=f"receipt finalized: {receipt.id}",
            evidence_refs=self._receipt_local_evidence_refs(result),
            source="receipt",
            metadata={"receipt_id": receipt.id},
        )
        if notification is not None:
            result["notification"] = notification.to_dict()
        return result

    def get_receipts(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            records = [r.to_dict() for r in self._receipts.values()]
        seen = {r["id"] for r in records}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("receipt"):
                payload = artifact.get("data", {})
                if not isinstance(payload, dict):
                    continue
                receipt_id = payload.get("id")
                if receipt_id and receipt_id not in seen:
                    seen.add(receipt_id)
                    records.append(payload)
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        if session_id:
            records = [r for r in records if r.get("session_id") == session_id]
        return {
            "receipts": records,
            "count": len(records),
        }

    def replay_receipt_state(self, receipt_id: str) -> Dict[str, Any]:
        receipt_id = receipt_id.strip() if isinstance(receipt_id, str) else ""
        if not receipt_id:
            return {"status": "error", "message": "receipt_id required"}
        receipt = self._receipt_dict_by_id(receipt_id)
        if receipt is None:
            return {"status": "not_found", "message": f"receipt not found: {receipt_id}"}

        session_id = receipt.get("session_id", "")
        approval = self._approval_dict_for_receipt(receipt_id, session_id)
        approval_history = approval.get("history", []) if approval else []
        approval_state = {
            "approval_id": approval.get("id", "") if approval else "",
            "status": approval.get("status", "unreviewed") if approval else "unreviewed",
            "reviewer": approval.get("reviewer", "") if approval else "",
            "reviewer_note": approval.get("reviewer_note", "") if approval else "",
            "resolved_at": approval.get("resolved_at") if approval else None,
            "resolution_note": approval.get("resolution_note", "") if approval else "",
        }

        evidence_chain = self._receipt_replay_evidence_chain(receipt, approval)
        replay_core = {
            "receipt_id": receipt_id,
            "session_id": session_id,
            "receipt_root_hash": receipt.get("integrity", {}).get("root_hash", ""),
            "scope_analysis": receipt.get("scope_analysis", {}),
            "collector_manifest": receipt.get("collector_manifest", {}),
            "runtime_gaps": receipt.get("runtime_gaps", []),
            "lineage_graph": receipt.get("lineage_graph", {}),
            "drift_reasons": receipt.get("drift_reasons", []),
            "rollback_state": receipt.get("rollback_state", {}),
            "approval_state": approval_state,
            "approval_history": approval_history,
            "evidence_chain": evidence_chain,
        }
        replay_hash = _stable_json_hash(replay_core)
        replay_id = f"receipt_replay:{_fingerprint(receipt_id, replay_hash)}"
        result = {
            "status": "ok",
            "id": replay_id,
            "receipt_id": receipt_id,
            "session_id": session_id,
            "generated_at": _now_iso(),
            "state": approval_state,
            "approval_history": approval_history,
            "evidence_chain": evidence_chain,
            "replay": replay_core,
            "integrity": {
                "algorithm": "sha-256",
                "replay_hash": replay_hash,
                "receipt_root_hash": receipt.get("integrity", {}).get("root_hash", ""),
                "evidence_ref_count": len(evidence_chain),
                "approval_history_count": len(approval_history),
                "purpose": "receipt state replay verification",
            },
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("receipt_replay", replay_id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def export_receipt_timeline_bundle(self, receipt_id: str) -> Dict[str, Any]:
        receipt_id = receipt_id.strip() if isinstance(receipt_id, str) else ""
        if not receipt_id:
            return {"status": "error", "message": "receipt_id required"}
        receipt = self._receipt_dict_by_id(receipt_id)
        if receipt is None:
            return {"status": "not_found", "message": f"receipt not found: {receipt_id}"}
        replay_result = self.replay_receipt_state(receipt_id)
        if replay_result.get("status") != "ok":
            return replay_result

        session_id = receipt.get("session_id", "")
        approval = self._approval_dict_for_receipt(receipt_id, session_id)
        timeline = self._receipt_timeline_bundle_timeline(receipt)
        bundle: Dict[str, Any] = {
            "schema": "cleanhouse.receipt_timeline_bundle.v1",
            "schema_version": 1,
            "artifact_type": "receipt_timeline_bundle",
            "receipt_id": receipt_id,
            "session_id": session_id,
            "receipt": receipt,
            "timeline": timeline,
            "approval": approval,
            "replay": replay_result.get("replay", {}),
            "evidence_chain": replay_result.get("evidence_chain", []),
        }
        bundle_hash = self._receipt_bundle_hash(bundle)
        timeline_hash = _stable_json_hash(timeline)
        receipt_root_hash = self._compute_receipt_root_hash(receipt)
        replay_hash = _stable_json_hash(bundle["replay"])
        bundle_id = f"receipt_bundle:{_fingerprint(receipt_id, bundle_hash)}"
        bundle["bundle_id"] = bundle_id
        bundle["integrity"] = {
            "algorithm": "sha-256",
            "bundle_hash": bundle_hash,
            "timeline_hash": timeline_hash,
            "receipt_root_hash": receipt_root_hash,
            "replay_hash": replay_hash,
            "evidence_ref_count": len(bundle["evidence_chain"]),
            "timeline_event_count": timeline.get("entry_count", 0),
            "approval_history_count": len((approval or {}).get("history", [])) if isinstance(approval, dict) else 0,
            "purpose": "receipt timeline bundle verification",
        }
        manifest, signature = self._sign_receipt_bundle_manifest(bundle)
        bundle["manifest"] = manifest
        bundle["manifest_signature"] = signature
        bundle["integrity"]["manifest_hash"] = signature.get("manifest_hash", "")
        verification = self.verify_receipt_timeline_bundle(bundle)
        result = {
            "status": "ok",
            "bundle": bundle,
            "verification": verification["verification"],
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("receipt_bundle", bundle_id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def import_receipt_timeline_bundle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        bundle = payload.get("bundle") if isinstance(payload, dict) and isinstance(payload.get("bundle"), dict) else payload
        if not isinstance(bundle, dict):
            return {"status": "error", "message": "bundle must be an object"}
        verification = self.verify_receipt_timeline_bundle(bundle)
        if verification["status"] != "ok":
            return verification
        bundle_id = bundle.get("bundle_id") or f"receipt_bundle:{_fingerprint(bundle.get('receipt_id', ''), verification['verification']['computed_bundle_hash'])}"
        result = {
            "status": "ok",
            "bundle_id": bundle_id,
            "receipt_id": bundle.get("receipt_id", ""),
            "session_id": bundle.get("session_id", ""),
            "integrity": {
                "algorithm": "sha-256",
                "bundle_hash": verification["verification"]["computed_bundle_hash"],
                "replay_hash": verification["verification"]["computed_replay_hash"],
                "receipt_root_hash": verification["verification"]["computed_receipt_root_hash"],
                "timeline_hash": verification["verification"]["computed_timeline_hash"],
                "manifest_hash": verification["verification"].get("manifest_hash", ""),
                "purpose": "imported receipt timeline bundle verification",
            },
            "verification": verification["verification"],
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("receipt_bundle", bundle_id, {"status": "ok", "bundle": bundle, "import": result})
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def verify_receipt_timeline_bundle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        bundle = payload.get("bundle") if isinstance(payload, dict) and isinstance(payload.get("bundle"), dict) else payload
        if not isinstance(bundle, dict):
            return {"status": "error", "message": "bundle must be an object"}
        integrity = bundle.get("integrity", {})
        if not isinstance(integrity, dict):
            integrity = {}
        receipt = bundle.get("receipt", {})
        timeline = bundle.get("timeline", {})
        replay_core = bundle.get("replay", {})
        if not isinstance(receipt, dict) or not isinstance(timeline, dict) or not isinstance(replay_core, dict):
            return {"status": "error", "message": "bundle receipt, timeline, and replay must be objects"}

        computed_bundle_hash = self._receipt_bundle_hash(bundle)
        computed_timeline_hash = _stable_json_hash(timeline)
        computed_receipt_root_hash = self._compute_receipt_root_hash(receipt)
        computed_replay_hash = _stable_json_hash(replay_core)
        expected_bundle_id = f"receipt_bundle:{_fingerprint(bundle.get('receipt_id', ''), computed_bundle_hash)}"
        signature_verification = self._verify_receipt_bundle_manifest(
            bundle=bundle,
            computed_bundle_hash=computed_bundle_hash,
            computed_timeline_hash=computed_timeline_hash,
            computed_receipt_root_hash=computed_receipt_root_hash,
            computed_replay_hash=computed_replay_hash,
        )
        verification = {
            "bundle_hash_match": integrity.get("bundle_hash") == computed_bundle_hash,
            "timeline_hash_match": integrity.get("timeline_hash") == computed_timeline_hash,
            "receipt_root_hash_match": receipt.get("integrity", {}).get("root_hash") == computed_receipt_root_hash == integrity.get("receipt_root_hash"),
            "replay_hash_match": integrity.get("replay_hash") == computed_replay_hash,
            "bundle_id_match": bundle.get("bundle_id") in (None, "", expected_bundle_id),
            "expected_bundle_hash": integrity.get("bundle_hash", ""),
            "computed_bundle_hash": computed_bundle_hash,
            "expected_timeline_hash": integrity.get("timeline_hash", ""),
            "computed_timeline_hash": computed_timeline_hash,
            "expected_receipt_root_hash": integrity.get("receipt_root_hash", ""),
            "computed_receipt_root_hash": computed_receipt_root_hash,
            "expected_replay_hash": integrity.get("replay_hash", ""),
            "computed_replay_hash": computed_replay_hash,
            "expected_bundle_id": expected_bundle_id,
            **signature_verification,
        }
        signature_required = verification["signature_status"] != "unavailable"
        passed = all(
            verification[key]
            for key in (
                "bundle_hash_match",
                "timeline_hash_match",
                "receipt_root_hash_match",
                "replay_hash_match",
                "bundle_id_match",
            )
        ) and (
            not signature_required
            or (
                bool(verification["signature_verified"])
                and bool(verification["manifest_hash_match"])
                and bool(verification["manifest_contents_match"])
            )
        )
        if not passed:
            self._ensure_replay_or_signature_failure_notification(bundle, verification)
        return {
            "status": "ok" if passed else "failed",
            "receipt_id": bundle.get("receipt_id", ""),
            "session_id": bundle.get("session_id", ""),
            "verification": verification,
        }

    def _ensure_replay_or_signature_failure_notification(
        self,
        bundle: Dict[str, Any],
        verification: Dict[str, Any],
    ) -> None:
        session_id = str(bundle.get("session_id") or "")
        if not session_id:
            receipt = bundle.get("receipt", {}) if isinstance(bundle.get("receipt"), dict) else {}
            session_id = str(receipt.get("session_id") or "")
        if not session_id:
            return
        receipt_id = str(bundle.get("receipt_id") or "")
        bundle_id = str(bundle.get("bundle_id") or "")
        receipt = bundle.get("receipt", {}) if isinstance(bundle.get("receipt"), dict) else {}
        objective_id = None
        metadata = receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}
        if metadata.get("objective_id"):
            objective_id = str(metadata.get("objective_id"))
        refs = []
        if receipt_id:
            refs.append(f"local://cleanhouse/receipt/{receipt_id}")
        if bundle_id:
            refs.append(f"local://cleanhouse/receipt-bundle/{bundle_id}")
        refs.append(f"local://cleanhouse/replay-signature/{_fingerprint(session_id, receipt_id, bundle_id or verification.get('computed_bundle_hash', ''))}")
        failed_checks = [
            key for key, value in verification.items()
            if key.endswith("_match") and value is False
        ]
        if verification.get("signature_status") not in {"verified", "unavailable"} or verification.get("signature_verified") is False:
            failed_checks.append("signature_verified")
        self._ensure_operator_notification(
            notification_type="replay_or_signature_failure",
            session_id=session_id,
            objective_id=objective_id,
            severity="critical",
            summary=f"replay/signature verification failed: {receipt_id or bundle_id or 'bundle'}",
            evidence_refs=refs,
            source="receipt_bundle",
            metadata={
                "receipt_id": receipt_id,
                "bundle_id": bundle_id,
                "failed_checks": sorted(set(failed_checks)),
                "verification": copy.deepcopy(verification),
            },
        )

    def _load_or_create_evidence_signing_key(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except Exception as exc:
            raise RuntimeError("cryptography is required for Ed25519 evidence manifests") from exc

        key_dir = config.DATA_DIR / "keys"
        key_dir.mkdir(parents=True, exist_ok=True)
        key_path = key_dir / "evidence_ed25519_private.json"
        if key_path.exists():
            payload = json.loads(key_path.read_text(encoding="utf-8"))
            raw_private = base64.b64decode(str(payload.get("private_key_b64", "")))
            private_key = Ed25519PrivateKey.from_private_bytes(raw_private)
        else:
            private_key = Ed25519PrivateKey.generate()
            raw_private = private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            key_path.write_text(
                json.dumps({
                    "schema": "cleanhouse.evidence_signing_key.v1",
                    "algorithm": "ed25519",
                    "private_key_b64": base64.b64encode(raw_private).decode("ascii"),
                }, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        return private_key, self._public_key_metadata(private_key)

    def _public_key_metadata(self, private_key) -> Dict[str, str]:
        from cryptography.hazmat.primitives import serialization

        raw_public = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        fingerprint = hashlib.sha256(raw_public).hexdigest()
        return {
            "algorithm": "ed25519",
            "key_id": f"ed25519:{fingerprint[:16]}",
            "public_key_fingerprint": fingerprint,
            "public_key_b64": base64.b64encode(raw_public).decode("ascii"),
            "public_key_encoding": "raw-base64",
        }

    def _receipt_bundle_evidence_refs(self, bundle: Dict[str, Any]) -> list[str]:
        refs: set[str] = set()
        for entry in bundle.get("evidence_chain", []):
            if not isinstance(entry, dict):
                continue
            ref = str(entry.get("ref", "")).strip()
            if ref.startswith("local://cleanhouse/"):
                refs.add(ref)
        return sorted(refs)

    def _receipt_bundle_manifest(self, bundle: Dict[str, Any], signer: Dict[str, str]) -> Dict[str, Any]:
        integrity = bundle.get("integrity", {}) if isinstance(bundle.get("integrity"), dict) else {}
        return {
            "schema": "cleanhouse.evidence_manifest.v1",
            "schema_version": 1,
            "artifact_type": "signed_evidence_manifest",
            "bundle_id": bundle.get("bundle_id", ""),
            "receipt_id": bundle.get("receipt_id", ""),
            "session_id": bundle.get("session_id", ""),
            "bundle_hash": integrity.get("bundle_hash", ""),
            "timeline_hash": integrity.get("timeline_hash", ""),
            "receipt_root_hash": integrity.get("receipt_root_hash", ""),
            "replay_hash": integrity.get("replay_hash", ""),
            "evidence_ref_count": integrity.get("evidence_ref_count", 0),
            "approval_history_count": integrity.get("approval_history_count", 0),
            "evidence_refs": self._receipt_bundle_evidence_refs(bundle),
            "signer": copy.deepcopy(signer),
            "key_management": _evidence_key_management_profile(),
        }

    def _sign_receipt_bundle_manifest(self, bundle: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        private_key, signer = self._load_or_create_evidence_signing_key()
        manifest = self._receipt_bundle_manifest(bundle, signer)
        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        signature = private_key.sign(manifest_bytes)
        return manifest, {
            "algorithm": "ed25519",
            "signature_encoding": "base64",
            "signature_b64": base64.b64encode(signature).decode("ascii"),
            "manifest_hash": manifest_hash,
            "key_id": signer["key_id"],
            "public_key_fingerprint": signer["public_key_fingerprint"],
        }

    def _verify_receipt_bundle_manifest(
        self,
        *,
        bundle: Dict[str, Any],
        computed_bundle_hash: str,
        computed_timeline_hash: str,
        computed_receipt_root_hash: str,
        computed_replay_hash: str,
    ) -> Dict[str, Any]:
        manifest = bundle.get("manifest")
        signature = bundle.get("manifest_signature")
        integrity = bundle.get("integrity", {}) if isinstance(bundle.get("integrity"), dict) else {}
        base = {
            "manifest_hash": "",
            "manifest_hash_match": False,
            "manifest_contents_match": False,
            "signature_status": "unavailable",
            "signature_verified": False,
            "signer_key_id": "",
            "public_key_fingerprint": "",
            "signature_error": "",
            "key_management_status": "unavailable",
            "key_management_label_present": False,
            "key_management_label_match": False,
            "key_management_limitations": list(EVIDENCE_KEY_MANAGEMENT_LIMITATIONS),
        }
        if not isinstance(manifest, dict) and not isinstance(signature, dict):
            if integrity.get("manifest_hash"):
                base["signature_status"] = "failed"
                base["signature_error"] = "integrity.manifest_hash present but manifest and manifest_signature are missing"
            return base
        if not isinstance(manifest, dict) or not isinstance(signature, dict):
            base["signature_status"] = "failed"
            base["signature_error"] = "manifest and manifest_signature must both be objects"
            return base

        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        signer = manifest.get("signer", {}) if isinstance(manifest.get("signer"), dict) else {}
        signer_key_id = str(signer.get("key_id", ""))
        public_key_fingerprint = str(signer.get("public_key_fingerprint", ""))
        expected_hashes = [
            str(value)
            for value in (
                integrity.get("manifest_hash"),
                signature.get("manifest_hash"),
            )
            if value
        ]
        manifest_hash_match = bool(expected_hashes) and all(value == manifest_hash for value in expected_hashes)
        expected_refs = self._receipt_bundle_evidence_refs(bundle)
        expected_key_management = _evidence_key_management_profile()
        manifest_key_management = manifest.get("key_management")
        key_management_label_present = isinstance(manifest_key_management, dict)
        key_management_label_match = (
            not key_management_label_present
            or manifest_key_management == expected_key_management
        )
        key_management_status = (
            str(manifest_key_management.get("mode", "unlabeled"))
            if key_management_label_present
            else "unlabeled"
        )
        manifest_contents_match = all((
            manifest.get("bundle_id", "") == bundle.get("bundle_id", ""),
            manifest.get("receipt_id", "") == bundle.get("receipt_id", ""),
            manifest.get("session_id", "") == bundle.get("session_id", ""),
            manifest.get("bundle_hash", "") == computed_bundle_hash,
            manifest.get("timeline_hash", "") == computed_timeline_hash,
            manifest.get("receipt_root_hash", "") == computed_receipt_root_hash,
            manifest.get("replay_hash", "") == computed_replay_hash,
            manifest.get("evidence_ref_count", 0) == len(expected_refs),
            manifest.get("evidence_refs", []) == expected_refs,
            signature.get("key_id", "") == signer_key_id,
            signature.get("public_key_fingerprint", "") == public_key_fingerprint,
            key_management_label_match,
        ))
        result = {
            **base,
            "manifest_hash": manifest_hash,
            "manifest_hash_match": manifest_hash_match,
            "manifest_contents_match": manifest_contents_match,
            "signature_status": "failed",
            "signer_key_id": signer_key_id,
            "public_key_fingerprint": public_key_fingerprint,
            "key_management_status": key_management_status,
            "key_management_label_present": key_management_label_present,
            "key_management_label_match": key_management_label_match,
        }
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            raw_public = base64.b64decode(str(signer.get("public_key_b64", "")))
            derived_fingerprint = hashlib.sha256(raw_public).hexdigest()
            derived_key_id = f"ed25519:{derived_fingerprint[:16]}"
            if derived_fingerprint != public_key_fingerprint or derived_key_id != signer_key_id:
                raise ValueError("public key fingerprint or key id mismatch")
            raw_signature = base64.b64decode(str(signature.get("signature_b64", "")))
            public_key = Ed25519PublicKey.from_public_bytes(raw_public)
            public_key.verify(raw_signature, manifest_bytes)
            result["signature_status"] = "verified"
            result["signature_verified"] = True
        except InvalidSignature:
            result["signature_error"] = "invalid Ed25519 signature"
        except Exception as exc:
            result["signature_error"] = str(exc)
        return result

    def _receipt_bundle_hash(self, bundle: Dict[str, Any]) -> str:
        core = {
            key: value
            for key, value in bundle.items()
            if key not in {"integrity", "bundle_id", "manifest", "manifest_signature"}
        }
        return _stable_json_hash(core)

    def _receipt_timeline_bundle_timeline(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        entries = receipt.get("events", [])
        if not isinstance(entries, list):
            entries = []
        return {
            "session_id": receipt.get("session_id", ""),
            "receipt_id": receipt.get("id", ""),
            "source": "receipt.events",
            "entry_count": len(entries),
            "entries": entries,
        }

    def _compute_receipt_root_hash(self, receipt: Dict[str, Any]) -> str:
        def strip_mutable(record: Dict[str, Any]) -> Dict[str, Any]:
            return {
                key: value
                for key, value in record.items()
                if key not in ("id", "timestamp")
            }

        def stable_lineage_graph(graph: Any) -> Dict[str, Any]:
            if not isinstance(graph, dict):
                return {}
            lineage = copy.deepcopy(graph)
            nodes = lineage.get("nodes", [])
            edges = lineage.get("edges", [])
            removed_node_ids: set[str] = set()
            stable_nodes: list[dict] = []
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    if node.get("type") == "receipt":
                        node_id = str(node.get("id", ""))
                        if node_id:
                            removed_node_ids.add(node_id)
                        continue
                    stable_nodes.append(node)
            stable_edges: list[dict] = []
            if isinstance(edges, list):
                for edge in edges:
                    if not isinstance(edge, dict):
                        continue
                    if edge.get("relationship") == "captured_in_receipt":
                        continue
                    if str(edge.get("source_id", "")) in removed_node_ids:
                        continue
                    if str(edge.get("target_id", "")) in removed_node_ids:
                        continue
                    stable_edges.append(edge)
            lineage["nodes"] = stable_nodes
            lineage["edges"] = stable_edges
            lineage["node_count"] = len(stable_nodes)
            lineage["edge_count"] = len(stable_edges)
            return lineage

        alerts = [
            strip_mutable(alert)
            for alert in receipt.get("alerts", [])
            if isinstance(alert, dict)
        ]
        gaps = [
            strip_mutable(gap)
            for gap in receipt.get("gaps", [])
            if isinstance(gap, dict)
        ]
        receipt_core = {
            "metadata": receipt.get("metadata", {}),
            "summary": receipt.get("summary", {}),
            "events": receipt.get("events", []),
            "alerts": alerts,
            "gaps": gaps,
            "evidence_index": receipt.get("evidence_index", []),
            "scope_analysis": receipt.get("scope_analysis", {}),
            "collector_manifest": self._stable_collector_manifest_for_hash(
                receipt.get("collector_manifest", {}) or {}
            ),
            "runtime_gaps": receipt.get("runtime_gaps", []),
            "lineage_graph": stable_lineage_graph(receipt.get("lineage_graph", {})),
            "drift_reasons": receipt.get("drift_reasons", []),
            "rollback_state": receipt.get("rollback_state", {}),
        }
        return _stable_json_hash(receipt_core)

    def _receipt_dict_by_id(self, receipt_id: str) -> Optional[Dict[str, Any]]:
        if self.persistence_enabled:
            artifact = PersistenceBackend.read("receipt", receipt_id)
            if artifact:
                payload = artifact.get("data", {})
                if isinstance(payload, dict):
                    return payload
        with self._lock:
            receipt = self._receipts.get(receipt_id)
        if receipt is not None:
            return receipt.to_dict()
        return None

    def _approval_dict_for_receipt(self, receipt_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        approvals = self.get_approval_queue(session_id=session_id).get("approval_queue", [])
        matches = [
            approval for approval in approvals
            if isinstance(approval, dict)
            and isinstance(approval.get("metadata"), dict)
            and approval["metadata"].get("receipt_id") == receipt_id
        ]
        if not matches:
            return None
        matches.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return matches[0]

    def _receipt_replay_evidence_chain(
        self,
        receipt: Dict[str, Any],
        approval: Optional[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        seen: set[str] = set()

        def add(ref: str, source: str, label: str = "") -> None:
            if not ref or ref in seen:
                return
            seen.add(ref)
            rows.append({"ref": ref, "source": source, "label": label})

        add(f"local://cleanhouse/receipt/{receipt.get('id', '')}", "receipt", "receipt artifact")
        for entry in receipt.get("evidence_index", []):
            if isinstance(entry, dict):
                add(str(entry.get("ref") or entry.get("uri") or ""), str(entry.get("source", "timeline")), str(entry.get("label", "")))
        for alert in receipt.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            for ref in alert.get("evidence_refs", []):
                add(str(ref), str(alert.get("alert_type", "alert")), str(alert.get("severity", "")))
        if approval:
            add(f"local://cleanhouse/approval-queue/{approval.get('id', '')}", "approval_queue", str(approval.get("status", "")))
            for ref in approval.get("evidence_refs", []):
                add(str(ref), "approval_queue", "approval evidence")
            for entry in approval.get("history", []):
                if not isinstance(entry, dict):
                    continue
                add(
                    f"local://cleanhouse/approval-queue/{approval.get('id', '')}/history/{entry.get('id', '')}",
                    "approval_history",
                    str(entry.get("status", "")),
                )
                for ref in entry.get("evidence_refs", []):
                    add(str(ref), "approval_history", str(entry.get("status", "")))
        return rows

    def _report_dicts(self) -> list[Dict[str, Any]]:
        with self._lock:
            records = {report.id: report.to_dict() for report in self._reports.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("report"):
                payload = artifact.get("data", {})
                if not isinstance(payload, dict):
                    continue
                report_id = str(payload.get("id", ""))
                if report_id:
                    records.setdefault(report_id, payload)
        return sorted(records.values(), key=lambda r: r.get("timestamp", ""), reverse=True)

    def _login_report_event_window(
        self,
        *,
        previous_login_at: Optional[str],
        current_login_at: str,
        max_events: int = 500,
    ) -> tuple[list[Dict[str, Any]], Optional[str]]:
        try:
            events = cleanhouse_events.list_events(limit=max_events)
        except Exception as exc:
            return [], str(exc) or exc.__class__.__name__
        windowed = [
            event for event in events
            if _timestamp_in_window(event.get("timestamp"), previous_login_at, current_login_at)
        ]
        windowed.sort(key=lambda event: event.get("timestamp", ""))
        return windowed, None

    @staticmethod
    def _event_evidence_refs(event: Dict[str, Any]) -> list[str]:
        refs: list[str] = []
        event_id = event.get("id")
        if event_id is not None:
            refs.append(f"local://cleanhouse/event/{event_id}")
        for ref in event.get("evidence_refs", []) or []:
            if isinstance(ref, str):
                refs.append(ref)
            elif isinstance(ref, dict):
                value = ref.get("uri") or ref.get("ref")
                if value:
                    refs.append(str(value))
        raw_ref = event.get("raw_evidence_ref")
        if raw_ref:
            refs.append(str(raw_ref))
        return refs

    def _windowed_artifacts(self, artifact_type: str, previous_login_at: Optional[str], current_login_at: str) -> list[Dict[str, Any]]:
        if artifact_type == "receipt":
            records = self.get_receipts().get("receipts", [])
        elif artifact_type == "report":
            records = self._report_dicts()
        else:
            records = []
        return [
            record for record in records
            if _timestamp_in_window(record.get("timestamp"), previous_login_at, current_login_at)
        ]

    def build_login_report(
        self,
        *,
        user_id: str = "",
        email: str = "",
        previous_login_at: Optional[str] = None,
        current_login_at: Optional[str] = None,
        trigger: str = "auth/login",
    ) -> Dict[str, Any]:
        user_id = str(user_id or "").strip()
        email = str(email or "").strip()
        if not user_id and not email:
            return {"status": "error", "message": "user_id or email required"}

        now = current_login_at or _now_iso()
        report_session_id = f"login:{_fingerprint(user_id or email)}"
        events, event_error = self._login_report_event_window(
            previous_login_at=previous_login_at,
            current_login_at=now,
        )
        receipts = self._windowed_artifacts("receipt", previous_login_at, now)
        reports = [
            report for report in self._windowed_artifacts("report", previous_login_at, now)
            if report.get("report_type") != "login_summary"
        ]
        latest_session_id = self._latest_workstation_session_id()
        latest_session = self._operator_session_record(latest_session_id).to_dict() if latest_session_id and self._operator_session_record(latest_session_id) else None

        event_type_counts = dict(Counter(str(event.get("event_type", "unknown")) for event in events))
        session_counts = dict(Counter(str(event.get("session_id", "unknown")) for event in events))

        evidence_refs: list[str] = []
        evidence_index: list[Dict[str, Any]] = []
        for event in events:
            refs = self._local_evidence_refs(self._event_evidence_refs(event))
            if not refs:
                continue
            evidence_refs.extend(refs)
            evidence_index.append({
                "ref": refs[0],
                "source": str(event.get("event_type", "event")),
                "label": str(event.get("summary", ""))[:160],
            })
        for receipt in receipts:
            receipt_id = str(receipt.get("id", ""))
            if receipt_id:
                ref = f"local://cleanhouse/receipt/{receipt_id}"
                evidence_refs.append(ref)
                evidence_index.append({"ref": ref, "source": "receipt", "label": receipt_id})
        evidence_links = tuple(dict.fromkeys(self._local_evidence_refs(evidence_refs)))

        gaps: list[Dict[str, Any]] = []
        if not previous_login_at:
            gaps.append({
                "source": "auth",
                "label": "first_login_or_unknown_previous_login",
                "description": "No previous login timestamp was available; report covers available local evidence only.",
            })
        if event_error:
            gaps.append({
                "source": "events",
                "label": "event_window_unavailable",
                "description": event_error,
            })

        summary_text = (
            f"Since previous login: {len(events)} runtime event(s), "
            f"{len(receipts)} receipt(s), {len(reports)} report artifact(s)."
        )
        receipt_core = {
            "metadata": {
                "user_id": user_id,
                "email": email,
                "window_start": previous_login_at,
                "window_end": now,
                "trigger": trigger,
                "latest_session_id": latest_session_id,
                "event_count": len(events),
                "receipt_count": len(receipts),
                "report_count": len(reports),
            },
            "summary": {
                "verdict": "observed" if not event_error else "unknown",
                "text": summary_text,
                "event_count": len(events),
                "receipt_count": len(receipts),
                "report_count": len(reports),
                "event_type_counts": event_type_counts,
                "session_counts": session_counts,
            },
            "events": events,
            "receipts": receipts,
            "reports": reports,
            "gaps": gaps,
            "evidence_index": evidence_index,
            "latest_session": latest_session,
        }
        root_hash = hashlib.sha256(
            json.dumps(receipt_core, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        synthetic_receipt = {
            "id": f"login_receipt:{_fingerprint(user_id or email, previous_login_at or '', now)}",
            "session_id": report_session_id,
            "timestamp": now,
            "metadata": receipt_core["metadata"],
            "summary": receipt_core["summary"],
            "events": events,
            "receipts": receipts,
            "reports": reports,
            "alerts": [],
            "gaps": gaps,
            "evidence_index": evidence_index,
            "integrity": {
                "algorithm": "sha-256",
                "root_hash": root_hash,
                "event_count": len(events),
                "purpose": "login report integrity verification",
            },
        }

        report = SessionReport(
            id=f"report:{_fingerprint('login_summary', user_id or email, previous_login_at or '', now)}",
            session_id=report_session_id,
            timestamp=now,
            report_type="login_summary",
            contact="",
            target=email or user_id,
            context="CleanHouse activity since previous login.",
            receipt=synthetic_receipt,
            evidence_links=evidence_links,
            metadata={
                "user_id": user_id,
                "email": email,
                "previous_login_at": previous_login_at,
                "current_login_at": now,
                "trigger": trigger,
                "latest_session_id": latest_session_id,
            },
        )
        result = {
            "status": "ok",
            **report.to_dict(),
            "integrity": synthetic_receipt["integrity"],
        }
        with self._lock:
            self._reports[report.id] = report
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("report", report.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        try:
            cleanhouse_events.insert_event_async(
                event_type="login_report_generated",
                path=f"/reports/{report.id}",
                summary=summary_text,
                session_id=report_session_id,
                source_surface="auth",
                actor_type="user",
                evidence_level="observed",
                evidence_refs=[f"local://cleanhouse/report/{report.id}"],
                raw_evidence_ref=f"local://cleanhouse/report/{report.id}",
                data={
                    "user_id": user_id,
                    "email": email,
                    "window_start": previous_login_at,
                    "window_end": now,
                    "event_count": len(events),
                    "receipt_count": len(receipts),
                    "report_count": len(reports),
                },
            )
        except Exception:
            pass
        return result

    def build_report(
        self,
        session_id: str,
        report_type: str = "incident",
        contact: str = "",
        target: str = "",
        context: str = "",
    ) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        if self._intent_record_by_id(session_id) is None:
            return {"status": "not_found", "message": "no session data for session_id"}

        receipt_result = self.build_receipt(session_id=session_id)

        evidence_links = tuple(
            ref.get("ref", "") for ref in receipt_result.get("evidence_index", [])
        )
        now = _now_iso()
        report = SessionReport(
            id=f"report:{_fingerprint(session_id, report_type, contact, target, now)}",
            session_id=session_id,
            timestamp=now,
            report_type=report_type,
            contact=contact,
            target=target,
            context=context,
            receipt=receipt_result,
            evidence_links=evidence_links,
        )

        with self._lock:
            self._reports[report.id] = report

        result = {
            "status": "ok",
            "id": report.id,
            "session_id": session_id,
            "timestamp": now,
            "report_type": report_type,
            "contact": contact,
            "target": target,
            "context": context,
            "receipt": receipt_result,
            "evidence_links": list(evidence_links),
            "integrity": receipt_result.get("integrity", {}),
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("report", report.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result

    def get_reports(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        records = self._report_dicts()
        if session_id:
            records = [r for r in records if r.get("session_id") == session_id]
        return {
            "reports": records,
            "count": len(records),
        }

    def prune_all_artifacts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.persistence_enabled:
            return {"status": "ok", "pruned": 0, "message": "persistence disabled"}
        if config.PRUNE_REQUIRES_CONFIRM and not data.get("confirm"):
            return {"status": "error", "message": "confirm required (set confirm=true)"}
        artifact_types = data.get("artifact_types")
        if artifact_types is None:
            artifact_types = sorted(config.RETAINED_ARTIFACT_TYPES)
        retention = self._settings.get("retention", {})
        key_map = {
            "snapshot": "snapshot_max_count",
            "diff": "diff_max_count",
            "timeline": "timeline_max",
            "receipt": "receipt_max",
            "report": "report_max",
        }
        now = _now_iso()
        retention_events: list[RetentionEvent] = []
        total_deleted = 0
        for atype in artifact_types:
            if atype not in config.ARTIFACT_SUBDIRS:
                continue
            max_count = data.get("max_count")
            if max_count is None:
                retention_key = key_map.get(atype)
                max_count = retention.get(retention_key) if retention_key else 100
            result = PersistenceBackend.prune(atype, int(max_count))
            if result["deleted_count"] > 0:
                event = RetentionEvent(
                    id=f"retention.{atype}.{int(time.time() * 1000000)}",
                    timestamp=now,
                    artifact_type=atype,
                    max_count=int(max_count),
                    before_count=result["before_count"],
                    after_count=result["after_count"],
                    deleted_count=result["deleted_count"],
                    deleted_files=tuple(result["deleted_files"]),
                    operator=data.get("operator", "api"),
                )
                retention_events.append(event)
            total_deleted += result["deleted_count"]
        with self._lock:
            for ev in retention_events:
                self._retention_events.append(ev)
        return {
            "status": "ok",
            "pruned": total_deleted,
            "retention_events_count": len(retention_events),
        }

    def get_retention_events(self) -> Dict[str, Any]:
        with self._lock:
            records = list(self._retention_events)
        return {
            "retention_events": [r.to_dict() for r in records],
            "count": len(records),
        }

    def run_zaelith_inference(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        intent_text = ""
        intent = self._intent_record_by_id(session_id)
        if intent is not None:
            intent_text = intent.text

        command_outputs: list[str] = []
        with self._lock:
            for r in self._command_buffer:
                if r.stdout_preview:
                    command_outputs.append(r.stdout_preview)

        diff_summaries: list[str] = []
        with self._lock:
            for d in self._diffs.values():
                if d.session_id == session_id:
                    diff_summaries.append(
                        f"{d.created_count} created, {d.modified_count} modified, "
                        f"{d.deleted_count} deleted"
                    )

        try:
            from corefiles.zaelith_service import get_zaelith_service
            service = get_zaelith_service()
        except Exception:
            return {
                "status": "ok",
                "inference": {
                    "status": "unavailable",
                    "zaelith_available": False,
                    "timestamp": _now_iso(),
                    "source": "zaelith",
                    "inference_label": "inferred",
                    "confidence": 0.0,
                    "confidence_level": "unknown",
                    "unknown_fields": ["zaelith service import failed"],
                    "summary_grade": "unknown",
                    "risk_level": "unknown",
                    "recommendations": [],
                    "key_findings": [],
                    "summary": None,
                },
            }

        inference = service.infer_from_evidence(
            intent_text=intent_text,
            command_outputs=command_outputs,
            diff_summaries=diff_summaries,
        )
        return {"status": "ok", "inference": inference}

    def run_scope_alignment(self, session_id: str) -> Dict[str, Any]:
        session_id = session_id.strip()
        if not session_id:
            return {"status": "error", "message": "session_id required"}

        scope = ""
        intent_text = ""
        intent = self._intent_record_by_id(session_id)
        if intent is not None:
            scope = intent.scope
            intent_text = intent.text

        command_args: list[tuple[str, list[str]]] = []
        with self._lock:
            for r in self._command_buffer:
                command_args.append((r.command, list(r.args)))

        file_changes: list[dict] = []
        with self._lock:
            for d in self._diffs.values():
                if d.session_id == session_id:
                    file_changes.extend(
                        {"path": c.path, "change_type": c.change_type}
                        for c in d.changes
                    )

        from corefiles.zaelith_service import assess_scope_alignment
        assessment = assess_scope_alignment(
            scope=scope,
            intent_text=intent_text,
            command_args=command_args,
            file_changes=file_changes,
        )
        return {"status": "ok", "session_id": session_id, **assessment}

    def get_settings(self) -> Dict[str, Any]:
        with self._settings_lock:
            return {
                "status": "ok",
                "settings": copy.deepcopy(self._settings),
                "updated": self._settings_updated,
            }

    def update_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        _VALID_TOP_KEYS = frozenset({"collectors", "risk_thresholds", "retention", "evidence_depth"})
        _VALID_COLLECTORS = frozenset(
            {"process_monitor", "network", "ai_activity", "anomalies", "integrity", "command_observer"}
        )
        _THRESHOLD_SIGNAL_KEYS = frozenset({"high", "medium"})
        _RETENTION_KEYS = frozenset(
            {"snapshot_max_count", "diff_max_count", "timeline_max", "receipt_max", "report_max", "command_buffer_max"}
        )
        _DEPTH_KEYS = frozenset(
            {"cache_ttl_seconds", "scan_interval_seconds", "scan_batch_size", "max_retries", "retry_delay_seconds"}
        )

        for key in data:
            if key not in _VALID_TOP_KEYS:
                return {"status": "error", "message": f"Unknown setting group: {key}"}

        merged = copy.deepcopy(self._settings)

        if "collectors" in data:
            for name, val in data["collectors"].items():
                if name not in _VALID_COLLECTORS:
                    return {"status": "error", "message": f"Unknown collector: {name}"}
                if not isinstance(val, bool):
                    return {"status": "error", "message": f"Collector '{name}' must be boolean"}
            merged["collectors"].update(data["collectors"])

        if "risk_thresholds" in data:
            rt = data["risk_thresholds"]
            if "alert_signal_count" in rt:
                asc = rt["alert_signal_count"]
                for k, v in asc.items():
                    if k not in _THRESHOLD_SIGNAL_KEYS:
                        return {"status": "error", "message": f"Unknown signal count key: {k}"}
                    if not isinstance(v, int) or v < 0:
                        return {"status": "error", "message": f"alert_signal_count.{k} must be non-negative integer"}
                merged["risk_thresholds"]["alert_signal_count"].update(asc)
            if "alert_confidence_min" in rt:
                v = rt["alert_confidence_min"]
                if not isinstance(v, (int, float)) or v < 0 or v > 1:
                    return {"status": "error", "message": "alert_confidence_min must be a number between 0 and 1"}
                merged["risk_thresholds"]["alert_confidence_min"] = float(v)

        if "retention" in data:
            for k, v in data["retention"].items():
                if k not in _RETENTION_KEYS:
                    return {"status": "error", "message": f"Unknown retention key: {k}"}
                if not isinstance(v, int) or v < 1:
                    return {"status": "error", "message": f"retention.{k} must be a positive integer"}
            merged["retention"].update(data["retention"])

        if "evidence_depth" in data:
            for k, v in data["evidence_depth"].items():
                if k not in _DEPTH_KEYS:
                    return {"status": "error", "message": f"Unknown evidence_depth key: {k}"}
                if not isinstance(v, (int, float)) or v <= 0:
                    return {"status": "error", "message": f"evidence_depth.{k} must be a positive number"}
            merged["evidence_depth"].update(data["evidence_depth"])

        now = _now_iso()
        with self._settings_lock:
            self._settings = merged
            self._settings_updated = now

        return {
            "status": "ok",
            "settings": copy.deepcopy(merged),
            "updated": now,
        }

    def get_plugins(self) -> Dict[str, Any]:
        with self._plugins_lock:
            return {
                "status": "ok",
                "plugins": [p.to_dict() for p in self._plugins.values()],
                "count": len(self._plugins),
            }

    def register_plugin(self, data: Dict[str, Any]) -> Dict[str, Any]:
        plugin_id = (data.get("id") or "").strip()
        if not plugin_id:
            return {"status": "error", "message": "plugin id is required"}
        name = (data.get("name") or "").strip()
        if not name:
            return {"status": "error", "message": "plugin name is required"}
        version = (data.get("version") or "").strip()
        if not version:
            return {"status": "error", "message": "plugin version is required"}
        description = (data.get("description") or "").strip()
        if not description:
            return {"status": "error", "message": "plugin description is required"}

        with self._plugins_lock:
            if plugin_id in self._plugins:
                return {"status": "error", "message": f"Plugin already registered: {plugin_id}"}

            plugin = PluginMetadata(
                id=plugin_id,
                name=name,
                version=version,
                description=description,
                enabled=data.get("enabled", False),
                scope=data.get("scope", ""),
            )
            self._plugins[plugin_id] = plugin

        return {"status": "ok", "plugin": plugin.to_dict()}

    def update_plugin(self, plugin_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self._plugins_lock:
            existing = self._plugins.get(plugin_id)
            if existing is None:
                return {"status": "error", "message": f"Unknown plugin: {plugin_id}"}

            enabled = data.get("enabled", existing.enabled)
            if not isinstance(enabled, bool):
                return {"status": "error", "message": "enabled must be boolean"}
            scope = data.get("scope", existing.scope)
            if not isinstance(scope, str):
                return {"status": "error", "message": "scope must be string"}

            updated = PluginMetadata(
                id=existing.id,
                name=existing.name,
                version=existing.version,
                description=existing.description,
                enabled=enabled,
                scope=scope,
            )
            self._plugins[plugin_id] = updated

        return {"status": "ok", "plugin": updated.to_dict()}

    def _collect_processes(self) -> Dict[str, Any]:
        monitor_class = _get_process_monitor_class()
        monitor = monitor_class(show_all=True)
        processes = monitor.get_processes()
        normalized: List[Dict[str, Any]] = []
        issues: List[Dict[str, Any]] = []

        for proc in sorted(processes, key=lambda item: item.get("cpu", 0.0), reverse=True)[:100]:
            command = proc.get("command", "")
            platform_detail = monitor.identify_platform_detail(command)
            is_agent, agent_pattern = monitor.is_agent_process_detail(command)
            is_system = monitor.is_system_process(command, proc.get("user", ""))

            platform_name = platform_detail[0] if platform_detail else None
            platform_match = platform_detail[2] if platform_detail else None

            normalized.append(
                {
                    "pid": proc.get("pid"),
                    "user": proc.get("user"),
                    "cpu": proc.get("cpu"),
                    "mem": proc.get("mem"),
                    "command": command,
                    "platform": platform_name,
                    "agent": is_agent,
                    "system": is_system,
                }
            )

            if platform_detail or is_agent:
                refs = [f"local://cleanhouse/process/{proc.get('pid')}"]
                if platform_match:
                    refs.append(f"local://cleanhouse/pattern/platform/{platform_match}")
                if agent_pattern:
                    refs.append(f"local://cleanhouse/pattern/agent/{agent_pattern}")

                parts = []
                if platform_detail:
                    parts.append(f"platform pattern '{platform_match}' for {platform_name}")
                if is_agent:
                    parts.append(f"agent pattern '{agent_pattern}'")
                title = "process command matched " + " and ".join(parts)

                issues.append(
                    _coerce_issue(
                        category="process",
                        severity="warning",
                        title=title,
                        details=command or "Process command matched a platform or agent pattern",
                        source="processes",
                        confidence=0.83,
                        rationale=f"Process command contained substring matching {', '.join(parts)}.",
                        evidence_level="observed",
                        evidence_refs=refs,
                        evidence={
                            "pid": proc.get("pid"),
                            "user": proc.get("user"),
                            "cpu": proc.get("cpu"),
                            "mem": proc.get("mem"),
                            "command": command,
                            "platform": platform_name,
                            "platform_matched_pattern": platform_match,
                            "agent": is_agent,
                            "agent_matched_pattern": agent_pattern,
                            "system": is_system,
                        },
                    )
                )

        return _envelope(
            issues,
            processes=normalized,
            counts={
                "total_processes": len(processes),
                "returned_processes": len(normalized),
            },
        )

    def _collect_network(self) -> Dict[str, Any]:
        tracer_class = _get_data_flow_tracer_class()
        tracer = tracer_class(monitor_duration=1)
        tracer.scan_network_connections()
        tracer.scan_dns_queries()

        connections = tracer.trace_data.get("network_connections", [])
        suspicious = tracer.trace_data.get("suspicious_connections", [])
        unusual = tracer.trace_data.get("unusual_patterns", [])
        dns_queries = tracer.trace_data.get("dns_queries", [])

        issues: List[Dict[str, Any]] = []
        for conn in suspicious:
            reason = conn.get("suspicious_reason", "suspicious connection")
            endpoint_family = _normalize_endpoint_family(reason)
            matched_pattern = reason.split(":", 1)[1] if ":" in reason else reason
            severity = "critical" if reason.startswith(("government:", "suspicious_tld:")) else "warning"
            host = conn.get("host", "unknown")
            pid = conn.get("pid", "unknown")
            domain = conn.get("domain") or host
            process = conn.get("process", "unknown")
            ref = f"local://cleanhouse/network/{_fingerprint(pid, host)}"
            issues.append(
                _coerce_issue(
                    category="network",
                    severity=severity,
                    title=f"network connection matched endpoint pattern '{endpoint_family}'",
                    details=f"{process} -> {domain} ({reason})",
                    source="network",
                    confidence=0.81,
                    rationale=f"Destination '{domain}' matched pattern '{matched_pattern}' in endpoint category '{endpoint_family}'.",
                    evidence_level="observed",
                    evidence_refs=[ref],
                    evidence={
                        "process": process,
                        "pid": pid,
                        "host": host,
                        "port": conn.get("port"),
                        "domain": conn.get("domain"),
                        "address": conn.get("address"),
                        "connection_type": conn.get("connection_type"),
                        "endpoint_family": endpoint_family,
                        "matched_pattern": matched_pattern,
                        "reason": reason,
                        "process_info": conn.get("process_info"),
                    },
                )
            )

        for entry in unusual:
            ptype = entry.get("type", "unknown")
            pdesc = entry.get("description", "Unusual network pattern")
            ref = f"local://cleanhouse/network/pattern/{_fingerprint(ptype)}"
            issues.append(
                _coerce_issue(
                    category="network",
                    severity="warning",
                    title=f"data transfer pattern '{ptype}' observed",
                    details=pdesc,
                    source="network",
                    confidence=0.68,
                    rationale=f"Data transfer pattern '{ptype}' exceeded anomaly heuristic thresholds.",
                    evidence_level="inferred",
                    evidence_refs=[ref],
                    evidence={
                        "type": ptype,
                        "description": pdesc,
                        "connections": entry.get("connections"),
                        "unique_domains": entry.get("unique_domains"),
                        "cloud_domains": entry.get("cloud_domains"),
                        "process": entry.get("process"),
                    },
                )
            )

        for dns_entry in dns_queries:
            if dns_entry.get("suspicious"):
                host = dns_entry.get("dns_server", "unknown")
                ref = f"local://cleanhouse/network/dns/{_fingerprint(host)}"
                issues.append(
                    _coerce_issue(
                        category="network",
                        severity="warning",
                        title="DNS server matched non-standard pattern",
                        details=dns_entry.get("reason", "Suspicious DNS activity"),
                        source="network",
                        confidence=0.64,
                        rationale=f"DNS server '{host}' is not a standard resolver and matched suspicious classification.",
                        evidence_level="observed",
                        evidence_refs=[ref],
                        evidence={
                            "dns_server": host,
                            "reason": dns_entry.get("reason"),
                        },
                    )
                )

        normalized_connections = [
            {
                "process": conn.get("process"),
                "pid": conn.get("pid"),
                "host": conn.get("host"),
                "port": conn.get("port"),
                "domain": conn.get("domain"),
                "address": conn.get("address"),
                "suspicious": bool(conn.get("suspicious")),
                "reason": conn.get("suspicious_reason"),
            }
            for conn in _trim(connections, 100)
        ]

        return _envelope(
            issues,
            connections=normalized_connections,
            dns_queries=_trim(dns_queries, 20),
            counts={
                "connections": len(connections),
                "suspicious_connections": len(suspicious),
                "unusual_patterns": len(unusual),
            },
        )

    def _collect_ai_activity(self) -> Dict[str, Any]:
        monitor_class = _get_agent_movement_monitor_class()
        monitor = monitor_class(verbose=False)
        process_hits = monitor.scan_processes()
        file_hits = monitor.scan_file_access()
        network_hits = monitor.scan_network_connections()

        issues: List[Dict[str, Any]] = []

        for platform_name, hits in process_hits.items():
            if hits:
                issues.append(
                    _coerce_issue(
                        category="ai_activity",
                        severity="warning",
                        title=f"Agent activity seen on {platform_name}",
                        details=f"{len(hits)} process match(es) for {platform_name}",
                        source="ai-activity",
                        confidence=0.77,
                        rationale="Agent process matches were observed from platform scan.",
                        evidence_level="observed",
                        evidence_refs=[f"local://cleanhouse/agent/{platform_name}/processes"],
                        evidence={
                            "platform": platform_name,
                            "count": len(hits),
                            "sample": _trim(hits, 3),
                        },
                    )
                )

        for platform_name, hits in file_hits.items():
            if hits:
                issues.append(
                    _coerce_issue(
                        category="ai_activity",
                        severity="warning",
                        title=f"Recent file activity seen on {platform_name}",
                        details=f"{len(hits)} file event(s) for {platform_name}",
                        source="ai-activity",
                        confidence=0.75,
                        rationale="File access traces were observed during the platform activity scan.",
                        evidence_level="observed",
                        evidence_refs=[f"local://cleanhouse/agent/{platform_name}/files"],
                        evidence={
                            "platform": platform_name,
                            "count": len(hits),
                            "sample": _trim(hits, 3),
                        },
                    )
                )

        for platform_name, hits in network_hits.items():
            if hits:
                issues.append(
                    _coerce_issue(
                        category="ai_activity",
                        severity="warning",
                        title=f"Network activity seen on {platform_name}",
                        details=f"{len(hits)} network event(s) for {platform_name}",
                        source="ai-activity",
                        confidence=0.71,
                        rationale="Network activity was observed for the platform scan scope.",
                        evidence_level="observed",
                        evidence_refs=[f"local://cleanhouse/agent/{platform_name}/network"],
                        evidence={
                            "platform": platform_name,
                            "count": len(hits),
                            "sample": _trim(hits, 3),
                        },
                    )
                )

        platform_activity = {}
        for platform_name, activity in monitor.activity_log["platform_activity"].items():
            platform_activity[platform_name] = {
                "process_detections": len(activity["process_detections"]),
                "file_access": len(activity["file_access"]),
                "network_connections": len(activity["network_connections"]),
                "active_periods": len(activity["active_periods"]),
                "switches": len(activity["switches"]),
            }

        return _envelope(
            issues,
            platform_processes={name: _trim(items, 10) for name, items in process_hits.items()},
            file_access={name: _trim(items, 10) for name, items in file_hits.items()},
            network_connections={name: _trim(items, 10) for name, items in network_hits.items()},
            platform_activity=platform_activity,
        )

    def _collect_anomalies(self) -> Dict[str, Any]:
        detector_class = _get_surveillance_detector_class()
        detector = detector_class(verbose=False)
        scan_steps = [
            detector._scan_filesystem,
            detector._scan_processes,
            detector._scan_network_connections,
            detector._scan_launch_agents,
            detector._scan_browser_extensions,
            detector._scan_system_modifications,
            detector._scan_hidden_files,
            detector._scan_audio_access,
            detector._scan_bluetooth_connections,
            detector._scan_wifi_security,
            detector._scan_screen_sharing,
            detector._scan_cloud_surveillance,
            detector._scan_data_exfiltration,
        ]

        for step in scan_steps:
            step()

        detector._calculate_summary()

        issues: List[Dict[str, Any]] = []
        for category, findings in detector.findings.items():
            if category == "summary" or not isinstance(findings, list):
                continue
            for finding in findings:
                severity = SEVERITY_FROM_DETECTION.get(finding.get("severity", "medium"), "warning")
                if severity == "safe":
                    continue
                evidence = copy.deepcopy(finding)
                issues.append(
                    _coerce_issue(
                        category=category,
                        severity=severity,
                        title=f"{category.replace('_', ' ').title()} finding",
                        details=finding.get("description") or finding.get("signature") or finding.get("file") or finding.get("process") or "Surveillance indicator detected",
                        source="anomalies",
                        confidence=0.66,
                        uncertainty=0.34,
                        rationale="Derived from local detector classification and scan output.",
                        evidence_level="inferred",
                        evidence=evidence,
                    )
                )

        return _envelope(
            issues,
            summary=copy.deepcopy(detector.findings.get("summary", {})),
        )

    def _collect_integrity(self) -> Dict[str, Any]:
        scan_fn = _get_integrity_module()
        result = scan_fn()
        issues: List[Dict[str, Any]] = []

        if result["status"] == "no_baseline":
            issues.append(
                _coerce_issue(
                    category="integrity",
                    severity="warning",
                    title="integrity baseline not found",
                    details=f"No baseline at {result['baseline_path']}",
                    source="integrity",
                    confidence=0.95,
                    uncertainty=0.05,
                    rationale="Integrity baseline file does not exist. Run generate_baseline to create one.",
                    evidence_level="observed",
                    evidence={
                        "baseline_path": result["baseline_path"],
                        "change_type": "no_baseline",
                    },
                )
            )
        elif result["status"] == "error":
            issues.append(
                _coerce_issue(
                    category="integrity",
                    severity="critical",
                    title="integrity scan error",
                    details=result.get("error", "unknown error"),
                    source="integrity",
                    confidence=0.95,
                    uncertainty=0.05,
                    rationale="Integrity scan failed to load baseline.",
                    evidence_level="observed",
                    evidence={
                        "baseline_path": result["baseline_path"],
                        "error": result.get("error"),
                        "change_type": "scan_error",
                    },
                )
            )
        elif result["status"] == "ok":
            for change in result["changes"]:
                change_type = change["change_type"]
                severity = "critical" if change_type == "modified" else "warning"
                rel_path = change["rel_path"]
                ref = f"local://cleanhouse/integrity/{_fingerprint(rel_path)}"

                evidence: Dict[str, Any] = {
                    "file": rel_path,
                    "change_type": change_type,
                }
                if change["baseline_hash"] is not None:
                    evidence["baseline_hash"] = change["baseline_hash"]
                if change["current_hash"] is not None:
                    evidence["current_hash"] = change["current_hash"]

                issues.append(
                    _coerce_issue(
                        category="integrity",
                        severity=severity,
                        title=f"file integrity mismatch: {change_type} {rel_path}",
                        details=f"File content hash differs from baseline record",
                        source="integrity",
                        confidence=0.95,
                        uncertainty=0.05,
                        rationale="File content hash differs from baseline record.",
                        evidence_level="observed",
                        evidence_refs=[ref],
                        evidence=evidence,
                    )
                )

            if result["changes"]:
                modified_count = sum(1 for c in result["changes"] if c["change_type"] == "modified")
                new_count = sum(1 for c in result["changes"] if c["change_type"] == "new")
                missing_count = sum(1 for c in result["changes"] if c["change_type"] == "missing")
                issues.append(
                    _coerce_issue(
                        category="integrity",
                        severity="warning",
                        title=f"integrity scan summary: {len(result['changes'])} change(s)",
                        details=f"{modified_count} modified, {new_count} new, {missing_count} missing",
                        source="integrity",
                        confidence=0.95,
                        uncertainty=0.05,
                        rationale="Aggregate summary of integrity changes detected.",
                        evidence_level="observed",
                        evidence={
                            "change_type": "summary",
                            "files_scanned": result["files_scanned"],
                            "baseline_count": result["baseline_count"],
                            "modified_count": modified_count,
                            "new_count": new_count,
                            "missing_count": missing_count,
                        },
                    )
                )

        return _envelope(
            issues,
            integrity_scan=result,
        )

    def _collect_commands(self) -> Dict[str, Any]:
        results = list(self._command_buffer)
        issues: List[Dict[str, Any]] = []

        for result in results:
            severity = "safe" if result.returncode == 0 else "warning"
            ref = f"local://cleanhouse/command/{_fingerprint(result.command, *result.args)}"
            evidence: Dict[str, Any] = {
                "command": result.command,
                "args": list(result.args),
                "cwd": result.cwd,
                "user": result.user,
                "returncode": result.returncode,
                "duration": result.duration,
                "stdout_preview": result.stdout_preview,
                "stderr_preview": result.stderr_preview,
            }
            issues.append(
                _coerce_issue(
                    category="command",
                    severity=severity,
                    title=f"command executed: {result.command}",
                    details=f"Exit status {result.returncode}",
                    source="command",
                    confidence=0.99,
                    uncertainty=0.01,
                    rationale=f"Command '{result.command}' completed with exit status {result.returncode} in {result.duration:.3f}s.",
                    evidence_level="observed",
                    evidence_refs=[ref],
                    evidence=evidence,
                )
            )

        return _envelope(issues)

    def _collect_cloud_usage(self) -> Dict[str, Any]:
        from corefiles.cloud_usage import get_cloud_usage_observer
        observer = get_cloud_usage_observer()
        data = observer.observe_all()
        adapters = data.get("cloud_usage_adapters", [])
        issues: List[Dict[str, Any]] = []

        for adapter in adapters:
            provider = adapter.get("provider", "unknown")
            status = adapter.get("status", "unsupported")
            limitation = adapter.get("limitation", "")
            indicators = adapter.get("observed_indicators", [])

            if status == "supported":
                for ind in indicators:
                    ind_type = ind.get("type", "indicator")
                    ind_detail = ind.get("detail", "")
                    issues.append(
                        _coerce_issue(
                            category="cloud_usage",
                            severity="safe",
                            title=f"observed request target: {provider} {ind_type}",
                            details=ind_detail,
                            source="cloud-usage",
                            confidence=0.85,
                            uncertainty=0.15,
                            rationale=f"Observed {provider} {ind_type}: {ind_detail[:120]}",
                            evidence_level="observed",
                            evidence_refs=[f"local://cleanhouse/cloud/{provider}/{ind_type}"],
                            evidence={
                                "provider": provider,
                                "indicator_type": ind_type,
                                "detail": ind_detail,
                            },
                        )
                    )
            else:
                issues.append(
                    _coerce_issue(
                        category="cloud_usage",
                        severity="safe",
                        title=f"cloud usage adapter: {provider} unsupported",
                        details=limitation,
                        source="cloud-usage",
                        confidence=0.99,
                        uncertainty=0.01,
                        rationale=limitation,
                        evidence_level="observed",
                        evidence_refs=[f"local://cleanhouse/cloud/{provider}/unsupported"],
                        evidence={
                            "provider": provider,
                            "status": "unsupported",
                            "limitation": limitation,
                        },
                    )
                )

        return _envelope(issues, cloud_usage_adapters=adapters)
