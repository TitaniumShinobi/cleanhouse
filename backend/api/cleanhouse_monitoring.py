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
import hmac
import json
import os
import queue
import secrets
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set
from urllib.parse import urlencode
from backend import events as cleanhouse_events
from backend.active_context import (
    ActiveContextCollector,
    TRUTH_DEGRADED,
    TRUTH_INFERRED,
    TRUTH_MISSING,
    TRUTH_OBSERVED,
)

from corefiles import config
try:
    from corefiles.notifications import NotificationManager
except Exception:
    NotificationManager = None

VALID_EVIDENCE_LEVELS = frozenset({"observed", "inferred", "imported", "manual", "unknown"})
CONNECTED_ACCOUNT_STATUSES = frozenset({"pending", "connected", "degraded", "disconnected", "disabled"})
CONNECTED_ACCOUNT_PROVIDERS = frozenset({"github", "chatgpt"})
CONNECTED_ACCOUNT_METHODS = frozenset({"oauth", "browser_connector"})
KNOWN_TOOL_IDENTITIES = frozenset({"cursor", "opencode", "codex", "copilot"})
ISSUE_SOURCES = {"processes", "network", "ai-activity", "anomalies", "integrity", "command", "cloud-usage", "tool-event", "runtime"}
ISSUE_SEVERITIES = {"safe", "warning", "critical"}
OPERATOR_SESSION_STATES = frozenset({"active", "stopped", "finalized"})
OPERATOR_NOTIFICATION_TYPES = frozenset({
    "session_started",
    "session_ended",
    "scope_drift_detected",
    "approval_required",
    "receipt_finalized",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
    "runtime_state_transition",
    "runtime_connection_lost",
    "runtime_connection_restored",
    "excessive_traversal",
    "collector_failure",
    "critical_filesystem_mutation",
    "rollback_needed",
    "qpb_transition",
    "incident_action_required",
    "unexpected_deletion_detected",
    "integrity_mismatch_detected",
    "watcher_offline",
    "port_reopened_unknown_process",
    "avatar_substitution_chain_break",
    "codex_prompt_sent",
    "codex_response_observed",
})
OPERATOR_NATIVE_NOTIFICATION_TYPES = frozenset({
    "codex_prompt_sent",
    "session_started",
    "session_ended",
    "incident_action_required",
    "scope_drift_detected",
    "approval_required",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
    "runtime_state_transition",
    "runtime_connection_lost",
    "runtime_connection_restored",
    "excessive_traversal",
    "collector_failure",
    "critical_filesystem_mutation",
    "rollback_needed",
    "unexpected_deletion_detected",
})
NATIVE_DESKTOP_DELIVERY_TYPES = frozenset({
    "session_started",
    "session_ended",
    "scope_drift_detected",
    "approval_required",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
    "runtime_state_transition",
    "runtime_connection_lost",
    "runtime_connection_restored",
    "excessive_traversal",
    "collector_failure",
    "critical_filesystem_mutation",
    "rollback_needed",
    "incident_action_required",
    "unexpected_deletion_detected",
    "integrity_mismatch_detected",
    "watcher_offline",
    "port_reopened_unknown_process",
})
PRODUCTION_OPERATOR_NOTIFICATION_TYPES = frozenset({
    "session_started",
    "session_ended",
    "scope_drift_detected",
})
ESSENTIAL_OPERATOR_NOTIFICATION_TYPES = PRODUCTION_OPERATOR_NOTIFICATION_TYPES
ROLLBACK_STATES = frozenset({
    "not_requested",
    "requested_no_route",
    "requested_route_available",
    "executed_verified",
    "executed_verification_failed",
})
OPERATOR_NOTIFICATION_SEVERITIES = frozenset({"info", "warning", "critical"})
NOTIFICATION_VISIBILITY_STATES = frozenset({
    "dispatch_attempted",
    "backend_accepted",
    "operator_acknowledged",
    "visibility_confirmed",
    "visibility_risk",
    "snoozed",
})
DEFAULT_HARD_INTERRUPT_TYPES = (
    "session_started",
    "session_ended",
    "scope_drift_detected",
    "approval_required",
    "destructive_command_attempt",
    "replay_or_signature_failure",
    "continuity_degraded",
    "runtime_recovery_failure",
    "runtime_state_transition",
    "runtime_connection_lost",
    "runtime_connection_restored",
    "excessive_traversal",
    "collector_failure",
    "critical_filesystem_mutation",
    "rollback_needed",
    "incident_action_required",
    "unexpected_deletion_detected",
    "integrity_mismatch_detected",
    "watcher_offline",
    "port_reopened_unknown_process",
)
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
    "runtime_recovery": 1,
    "runtime_presence": 1,
    "active_context": 1,
    "native_notification_cooldown": 1,
    "qpb_case": 1,
    "operation_proposal": 1,
    "domain_event": 1,
    "incident_case": 1,
    "notification_delivery": 1,
    "policy_decision": 1,
    "action_outcome": 1,
    "connected_account": 1,
    "provider_sync_cursor": 1,
    "provider_import_job": 1,
    "approval_mediation_proof": 1,
}
ADAPTER_ARTIFACT_SUBDIRS = {
    "intent": "intents",
    "prompt": "prompts",
    "rollback": "rollbacks",
    "runtime_recovery": "runtime_recoveries",
    "runtime_presence": "runtime_presence",
    "active_context": "active_contexts",
    "native_notification_cooldown": "native_notification_cooldowns",
    "qpb_case": "qpb_cases",
    "operation_proposal": "operation_proposals",
    "domain_event": "domain_events",
    "incident_case": "incident_cases",
    "notification_delivery": "notification_deliveries",
    "policy_decision": "policy_decisions",
    "action_outcome": "action_outcomes",
    "connected_account": "connected_accounts",
    "provider_sync_cursor": "provider_sync_cursors",
    "provider_import_job": "provider_import_jobs",
    "approval_mediation_proof": "approval_mediation_proofs",
}
LOGIN_REPORT_QUEUE_SIZE = 2
LOGIN_REPORT_WAIT_SECONDS = 2.0
LOGIN_REPORT_JOB_TIMEOUT_SECONDS = 30.0
RUNTIME_GLOBAL_SESSION_ID = "runtime-global"
RUNTIME_PRESENCE_ARTIFACT_ID = "runtime_presence:global"
ACTIVE_CONTEXT_LATEST_ARTIFACT_ID = "active_context:latest"
NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID = "native_notification_cooldown:global"
NATIVE_NOTIFICATION_COOLDOWN_SECONDS = 600.0
NATIVE_NOTIFICATION_BURST_WINDOW_SECONDS = 30
NATIVE_NOTIFICATION_BURST_CAP = 3
ACTIVE_CONTEXT_TRUTH_LABELS = frozenset({
    TRUTH_OBSERVED,
    TRUTH_INFERRED,
    TRUTH_MISSING,
    TRUTH_DEGRADED,
})
QPB_CASE_STATES = frozenset({
    "detected",
    "quarantined",
    "purge_pending",
    "purged",
    "blessed",
    "rejected",
})
PROPOSAL_STATES = frozenset({"pending", "approved", "rejected", "applied", "undone", "failed"})
INCIDENT_CASE_STATES = frozenset({"open", "acknowledged", "in_review", "resolved", "suppressed"})
DOMAIN_HEALTH_STATES = frozenset({"supported", "degraded", "offline", "permission_blocked", "unknown"})
PROCESS_MEMORY_BUDGET_BYTES = 10 * 1024 * 1024 * 1024


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


def _parse_process_rss_bytes(raw: Any) -> int:
    # `ps` RSS is kilobytes on macOS; collectors may surface it as string or number.
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return int(value * 1024)


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
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
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
            "incident_key": str(metadata.get("incident_key", "")),
            "visibility_proof": str(metadata.get("visibility_proof", "transport_only") or "transport_only"),
            "metadata": metadata,
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
    scope_enforcement: Dict[str, Any] = field(default_factory=dict)
    intervention_workflows: tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    chain_of_custody: Dict[str, Any] = field(default_factory=dict)
    actor_attribution: Dict[str, Any] = field(default_factory=dict)
    channel_attribution: Dict[str, Any] = field(default_factory=dict)
    trust_attribution: Dict[str, Any] = field(default_factory=dict)

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
            "scope_enforcement": self.scope_enforcement,
            "intervention_workflows": list(self.intervention_workflows),
            "chain_of_custody": self.chain_of_custody,
            "actor_attribution": self.actor_attribution,
            "channel_attribution": self.channel_attribution,
            "trust_attribution": self.trust_attribution,
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
    concern_letter: Dict[str, Any] = field(default_factory=dict)
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
            "concern_letter": self.concern_letter,
            "metadata": self.metadata,
        }


class LoginReportCoordinator:
    """Single-worker queue for login report generation."""

    def __init__(
        self,
        report_builder: Callable[..., Dict[str, Any]],
        *,
        max_queue_size: int = LOGIN_REPORT_QUEUE_SIZE,
        max_jobs: int = 100,
        job_timeout_seconds: float = LOGIN_REPORT_JOB_TIMEOUT_SECONDS,
    ):
        self._report_builder = report_builder
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._job_order: deque[str] = deque()
        self._worker: Optional[threading.Thread] = None
        self._max_jobs = max_jobs
        self._job_timeout_seconds = max(0.001, float(job_timeout_seconds or LOGIN_REPORT_JOB_TIMEOUT_SECONDS))

    def submit(
        self,
        *,
        user_id: str = "",
        email: str = "",
        previous_login_at: Optional[str] = None,
        current_login_at: Optional[str] = None,
        trigger: str = "auth/login",
        wait_timeout_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        submitted_at = _now_iso()
        payload = {
            "user_id": str(user_id or "").strip(),
            "email": str(email or "").strip(),
            "previous_login_at": previous_login_at,
            "current_login_at": current_login_at,
            "trigger": str(trigger or "auth/login").strip() or "auth/login",
        }
        job_id = f"login_report_job:{_fingerprint(payload['user_id'] or payload['email'], submitted_at, payload['trigger'])}"
        done = threading.Event()
        job = {
            "job_id": job_id,
            "state": "queued",
            "submitted_at": submitted_at,
            "started_at": None,
            "completed_at": None,
            "timeout_seconds": self._job_timeout_seconds,
            "blocking_phase": "queue",
            "payload": payload,
            "result": None,
            "error": None,
            "_done": done,
            "_deadline_monotonic": time.monotonic() + self._job_timeout_seconds,
        }
        with self._lock:
            self._prune_jobs_locked()
            self._jobs[job_id] = job
            self._job_order.append(job_id)

        self._ensure_worker()
        try:
            self._queue.put_nowait(job_id)
        except queue.Full:
            with self._lock:
                job["state"] = "rejected"
                job["completed_at"] = _now_iso()
                job["error"] = "login report queue is full"
                done.set()
            return self.response_for_job(job_id)

        timeout = max(0.0, float(wait_timeout_seconds or 0.0))
        if timeout:
            done.wait(timeout=timeout)
        return self.response_for_job(job_id)

    def poll(self, job_id: str) -> Dict[str, Any]:
        return self.response_for_job(job_id)

    def state(self) -> Dict[str, Any]:
        with self._lock:
            self._mark_timed_out_jobs_locked()
            jobs = [self._public_job(job) for job in self._jobs.values()]
            running = [job for job in jobs if job.get("state") == "running"]
            queued = [job for job in jobs if job.get("state") == "queued"]
            completed = [job for job in jobs if job.get("completed_at")]
            failed = [job for job in jobs if job.get("state") in {"failed", "rejected"}]
        completed.sort(key=lambda item: str(item.get("completed_at") or ""), reverse=True)
        failed.sort(key=lambda item: str(item.get("completed_at") or item.get("submitted_at") or ""), reverse=True)
        return {
            "status": "degraded" if failed else "ok",
            "queue_depth": self._queue.qsize(),
            "queue_maxsize": self._queue.maxsize,
            "running_job_id": running[0].get("job_id") if running else None,
            "queued_count": len(queued),
            "job_count": len(jobs),
            "last_completed_at": completed[0].get("completed_at") if completed else None,
            "last_error": failed[0].get("error") if failed else None,
        }

    def response_for_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            self._mark_timed_out_jobs_locked()
        job = self._job_snapshot(job_id)
        if not job:
            return {
                "status": "not_found",
                "message": "login report job not found",
                "job_id": job_id,
            }

        state = job.get("state")
        public_job = self._public_job(job)
        if state == "succeeded" and isinstance(job.get("result"), dict):
            result = copy.deepcopy(job["result"])
            result["job_id"] = job_id
            result["job"] = public_job
            return result
        if state == "failed":
            return {
                "status": "error",
                "message": job.get("error") or "login report job failed",
                "job_id": job_id,
                "job": public_job,
            }
        if state == "rejected":
            return {
                "status": "rate_limited",
                "message": job.get("error") or "login report queue is full",
                "job_id": job_id,
                "job": public_job,
            }
        return {
            "status": "accepted",
            "message": "login report generation queued",
            "job_id": job_id,
            "job": public_job,
        }

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="cleanhouse-login-report-worker",
                daemon=True,
            )
            self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                with self._lock:
                    job = self._jobs.get(job_id)
                    if not job or job.get("state") != "queued":
                        continue
                    job["state"] = "running"
                    job["started_at"] = _now_iso()
                    job["blocking_phase"] = "report_builder"
                    payload = copy.deepcopy(job["payload"])
                    done = job["_done"]
                try:
                    result = self._report_builder(**payload)
                    with self._lock:
                        job = self._jobs.get(job_id)
                        if job and job.get("state") == "running":
                            job["result"] = copy.deepcopy(result)
                            if isinstance(result, dict) and result.get("status") == "error":
                                job["state"] = "failed"
                                job["error"] = str(result.get("message") or "login report job failed")
                            else:
                                job["state"] = "succeeded"
                            job["completed_at"] = _now_iso()
                            job["blocking_phase"] = ""
                            done = job["_done"]
                except Exception as exc:
                    with self._lock:
                        job = self._jobs.get(job_id)
                        if job and job.get("state") == "running":
                            job["state"] = "failed"
                            job["completed_at"] = _now_iso()
                            job["error"] = str(exc) or exc.__class__.__name__
                            job["blocking_phase"] = "report_builder"
                            done = job["_done"]
                done.set()
            finally:
                self._queue.task_done()

    def _job_snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._mark_timed_out_jobs_locked()
            job = self._jobs.get(job_id)
            if not job:
                return None
            return {
                key: copy.deepcopy(value)
                for key, value in job.items()
                if not key.startswith("_")
            }

    @staticmethod
    def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": job.get("job_id"),
            "state": job.get("state"),
            "submitted_at": job.get("submitted_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "timeout_seconds": job.get("timeout_seconds"),
            "blocking_phase": job.get("blocking_phase"),
            "payload": copy.deepcopy(job.get("payload", {})),
            "error": job.get("error"),
        }

    def _mark_timed_out_jobs_locked(self) -> None:
        now = time.monotonic()
        for job in self._jobs.values():
            if job.get("state") not in {"queued", "running"}:
                continue
            deadline = job.get("_deadline_monotonic")
            if not isinstance(deadline, (int, float)) or now < float(deadline):
                continue
            phase = str(job.get("blocking_phase") or ("report_builder" if job.get("state") == "running" else "queue"))
            job["state"] = "failed"
            job["completed_at"] = _now_iso()
            job["blocking_phase"] = phase
            job["error"] = f"login report timed out after {self._job_timeout_seconds:g}s during {phase}"
            done = job.get("_done")
            if isinstance(done, threading.Event):
                done.set()

    def _prune_jobs_locked(self) -> None:
        while len(self._job_order) >= self._max_jobs:
            oldest = self._job_order.popleft()
            job = self._jobs.get(oldest)
            if job and job.get("state") in {"queued", "running"}:
                self._job_order.append(oldest)
                break
            self._jobs.pop(oldest, None)


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
class QPBCaseRecord:
    """Evidence-scoped QPB case lifecycle record."""
    id: str
    session_id: str
    objective_id: Optional[str]
    status: str
    target_scope: Dict[str, Any]
    created_at: str
    updated_at: str
    evidence_refs: tuple[str, ...]
    metadata: Dict[str, Any]
    history: tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "status": self.status,
            "target_scope": self.target_scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "evidence_refs": list(self.evidence_refs),
            "metadata": self.metadata,
            "history": list(self.history),
        }


@dataclass(frozen=True)
class OperationProposalRecord:
    """Mediated operation proposal with explicit confirm/reject and undo support."""
    id: str
    proposal_type: str
    session_id: str
    objective_id: Optional[str]
    status: str
    reason: str
    target_scope: Dict[str, Any]
    operations: tuple[Dict[str, Any], ...]
    created_at: str
    updated_at: str
    applied_at: Optional[str]
    undone_at: Optional[str]
    evidence_refs: tuple[str, ...]
    rollback_id: Optional[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "proposal_type": self.proposal_type,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "status": self.status,
            "reason": self.reason,
            "target_scope": self.target_scope,
            "operations": list(self.operations),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "applied_at": self.applied_at,
            "undone_at": self.undone_at,
            "evidence_refs": list(self.evidence_refs),
            "rollback_id": self.rollback_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class DomainEventRecord:
    """Canonical normalized domain observer event."""
    id: str
    domain: str
    surface: str
    event_type: str
    severity: str
    observed_at: str
    session_id: str
    objective_id: Optional[str]
    actor: Dict[str, Any]
    resource: Dict[str, Any]
    observed_vs_expected: Dict[str, Any]
    confidence: float
    unknown_fields: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "surface": self.surface,
            "event_type": self.event_type,
            "severity": self.severity,
            "observed_at": self.observed_at,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "actor": self.actor,
            "resource": self.resource,
            "observed_vs_expected": self.observed_vs_expected,
            "confidence": round(self.confidence, 3),
            "unknown_fields": list(self.unknown_fields),
            "evidence_refs": list(self.evidence_refs),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class IncidentCaseRecord:
    """Actionable incident linked to domain events and operator decisions."""
    id: str
    status: str
    severity: str
    title: str
    summary: str
    session_id: str
    objective_id: Optional[str]
    source_event_id: str
    notification_type: str
    created_at: str
    updated_at: str
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    next_action: str
    evidence_refs: tuple[str, ...]
    metadata: Dict[str, Any]
    history: tuple[Dict[str, Any], ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "session_id": self.session_id,
            "objective_id": self.objective_id,
            "source_event_id": self.source_event_id,
            "notification_type": self.notification_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "acknowledged_at": self.acknowledged_at,
            "resolved_at": self.resolved_at,
            "next_action": self.next_action,
            "evidence_refs": list(self.evidence_refs),
            "metadata": self.metadata,
            "history": list(self.history),
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


def _iso_from_timestamp(seconds: float) -> str:
    try:
        return datetime.fromtimestamp(float(seconds)).isoformat()
    except (TypeError, ValueError, OSError):
        return _now_iso()


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
        self._live_notifications_started_seconds = time.time()
        self._live_notifications_started_at = _iso_from_timestamp(self._live_notifications_started_seconds)
        self._notification_boot_id = str(os.getenv("CLEANHOUSE_BACKEND_BOOT_ID", "") or _fingerprint(self._live_notifications_started_at))
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._command_buffer: deque[CommandResult] = deque(maxlen=200)
        self._intents: deque[IntentRecord] = deque(maxlen=100)
        self._prompts: deque[PromptContextRecord] = deque(maxlen=200)
        self._approval_queue: Dict[str, ApprovalQueueItem] = {}
        self._operator_sessions: Dict[str, OperatorSessionRecord] = {}
        self._operator_notifications: Dict[str, OperatorNotificationRecord] = {}
        self._open_codex_prompts_by_session: Dict[str, deque[str]] = {}
        self._active_context_collector = ActiveContextCollector()
        self._snapshots: Dict[str, SnapshotRecord] = {}
        self._snapshot_contents: Dict[str, Dict[str, str]] = {}
        self._diffs: Dict[str, DiffRecord] = {}
        self._correlations: Dict[str, CorrelationPass] = {}
        self._timelines: Dict[str, TimelineRecord] = {}
        self._signals: Dict[str, ClassifiedSignal] = {}
        self._alerts: Dict[str, SignalAlert] = {}
        self._receipts: Dict[str, SessionReceipt] = {}
        self._rollback_records: Dict[str, RollbackRecord] = {}
        self._qpb_cases: Dict[str, QPBCaseRecord] = {}
        self._operation_proposals: Dict[str, OperationProposalRecord] = {}
        self._domain_events: Dict[str, DomainEventRecord] = {}
        self._incident_cases: Dict[str, IncidentCaseRecord] = {}
        self._presence_loop_started = False
        self._presence_loop_lock = threading.Lock()
        self._presence_loop_stop = threading.Event()
        self._presence_last_health: Dict[str, str] = {}
        self._presence_last_signal: Dict[str, str] = {}
        self._reports: Dict[str, SessionReport] = {}
        self._login_report_coordinator = LoginReportCoordinator(
            lambda **payload: self.build_login_report(**payload)
        )
        self._settings: Dict[str, Any] = copy.deepcopy(config.SETTINGS_DEFAULTS)
        self._settings_updated: str = _now_iso()
        self._settings_lock = threading.Lock()
        self._valid_collectors: Set[str] = set(config.SETTINGS_DEFAULTS["collectors"].keys())
        self._plugins: Dict[str, PluginMetadata] = {}
        self._plugins_lock = threading.Lock()
        self._connect_sessions: Dict[str, Dict[str, Any]] = {}
        self._connect_sessions_lock = threading.Lock()
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
        self._native_notification_cooldown_cache: Dict[str, Any] = {"updated_at": "", "entries": {}, "bursts": {}}
        _get_command_observer().on_completed = self._on_command_completed
        self._ensure_presence_loop()

    def _provider_token_cipher(self):
        try:
            from cryptography.fernet import Fernet
        except Exception:
            return None
        key_raw = str(os.getenv("CLEANHOUSE_PROVIDER_TOKEN_KEY", "")).strip()
        if key_raw:
            key_material = key_raw.encode("utf-8")
        else:
            key_file = Path.home() / ".cleanhouse" / "provider_tokens.key"
            key_file.parent.mkdir(parents=True, exist_ok=True)
            if key_file.exists():
                key_material = key_file.read_bytes().strip()
            else:
                key_material = Fernet.generate_key()
                key_file.write_bytes(key_material)
        try:
            return Fernet(key_material)
        except Exception:
            return None

    def _encrypt_provider_secret(self, value: str) -> str:
        text = str(value or "")
        if not text:
            return ""
        cipher = self._provider_token_cipher()
        if cipher is None:
            return ""
        try:
            return cipher.encrypt(text.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def _decrypt_provider_secret(self, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return ""
        cipher = self._provider_token_cipher()
        if cipher is None:
            return ""
        try:
            return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def _connected_account_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row = copy.deepcopy(payload if isinstance(payload, dict) else {})
        row["account_id"] = str(row.get("account_id", "")).strip()
        row["cleanhouse_user_id"] = str(row.get("cleanhouse_user_id", "")).strip()
        row["provider"] = str(row.get("provider", "")).strip().lower()
        row["connection_method"] = str(row.get("connection_method", "")).strip().lower()
        status = str(row.get("status", "connected") or "connected").strip().lower()
        row["status"] = status if status in CONNECTED_ACCOUNT_STATUSES else "connected"
        scopes = row.get("scopes", [])
        if isinstance(scopes, str):
            scopes = [item.strip() for item in scopes.split(",") if item.strip()]
        if not isinstance(scopes, list):
            scopes = []
        row["scopes"] = [str(item).strip() for item in scopes if str(item).strip()]
        row["connected_at"] = str(row.get("connected_at", "") or "")
        row["last_sync_at"] = str(row.get("last_sync_at", "") or "")
        row["last_error"] = str(row.get("last_error", "") or "")
        row["consent_version"] = str(row.get("consent_version", "v1") or "v1")
        row["provider_account_id"] = str(row.get("provider_account_id", "") or "")
        row["ingestion_enabled"] = bool(row.get("ingestion_enabled", True))
        row["secrets"] = copy.deepcopy(row.get("secrets", {})) if isinstance(row.get("secrets"), dict) else {}
        row["metadata"] = copy.deepcopy(row.get("metadata", {})) if isinstance(row.get("metadata"), dict) else {}
        return row

    def _connected_account_public_view(self, row: Dict[str, Any]) -> Dict[str, Any]:
        record = self._connected_account_from_payload(row)
        sync_status = "ok"
        degraded_reason = ""
        if record["status"] in {"degraded", "disabled"}:
            sync_status = "degraded"
            degraded_reason = record["last_error"] or record["status"]
        elif record["status"] == "disconnected":
            sync_status = "disabled"
            degraded_reason = "disconnected"
        elif not record.get("last_sync_at"):
            sync_status = "pending"
        return {
            "account_id": record["account_id"],
            "cleanhouse_user_id": record["cleanhouse_user_id"],
            "provider": record["provider"],
            "provider_account_id": record.get("provider_account_id", ""),
            "connection_method": record["connection_method"],
            "status": record["status"],
            "scopes": list(record["scopes"]),
            "connected_at": record["connected_at"],
            "last_sync_at": record["last_sync_at"],
            "last_error": record["last_error"],
            "consent_version": record["consent_version"],
            "ingestion_enabled": bool(record.get("ingestion_enabled", True)),
            "sync_status": sync_status,
            "last_successful_sync": record["last_sync_at"] or "",
            "degraded_reason": degraded_reason,
            "source_type": "provider_import",
        }

    def _connected_accounts_for_user(self, cleanhouse_user_id: str) -> list[Dict[str, Any]]:
        user_id = str(cleanhouse_user_id or "").strip()
        if not user_id:
            return []
        rows: list[Dict[str, Any]] = []
        for artifact in PersistenceBackend.list_artifacts("connected_account"):
            payload = artifact.get("data", {})
            account = payload.get("account", payload) if isinstance(payload, dict) else {}
            if not isinstance(account, dict):
                continue
            normalized = self._connected_account_from_payload(account)
            if normalized.get("cleanhouse_user_id") != user_id:
                continue
            rows.append(normalized)
        rows.sort(key=lambda row: str(row.get("connected_at", "")), reverse=True)
        return rows

    def _connected_account_by_id(self, cleanhouse_user_id: str, account_id: str) -> Dict[str, Any] | None:
        account_id = str(account_id or "").strip()
        if not account_id:
            return None
        artifact = PersistenceBackend.read("connected_account", account_id)
        payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
        account = payload.get("account", payload) if isinstance(payload, dict) else {}
        if not isinstance(account, dict):
            return None
        normalized = self._connected_account_from_payload(account)
        if normalized.get("cleanhouse_user_id") != str(cleanhouse_user_id or "").strip():
            return None
        return normalized

    def _runtime_presence_state(self) -> Dict[str, Any]:
        artifact = PersistenceBackend.read("runtime_presence", RUNTIME_PRESENCE_ARTIFACT_ID) if self.persistence_enabled else None
        payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
        state = payload.get("runtime_presence", payload) if isinstance(payload, dict) else {}
        if not isinstance(state, dict):
            state = {}
        return {
            "id": RUNTIME_PRESENCE_ARTIFACT_ID,
            "runtime_state": str(state.get("runtime_state", "unknown") or "unknown"),
            "connection_state": str(state.get("connection_state", "unknown") or "unknown"),
            "reason_codes": list(state.get("reason_codes", [])) if isinstance(state.get("reason_codes"), list) else [],
            "notification_type": str(state.get("notification_type", "") or ""),
            "notification_id": str(state.get("notification_id", "") or ""),
            "runtime_evidence_ref": str(state.get("runtime_evidence_ref", "") or ""),
            "runtime_transition_ref": str(state.get("runtime_transition_ref", "") or ""),
            "recovery_receipt_id": str(state.get("recovery_receipt_id", "") or ""),
            "updated_at": str(state.get("updated_at", "") or ""),
        }

    def _persist_runtime_presence_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "status": "ok",
            "runtime_presence": {
                "id": RUNTIME_PRESENCE_ARTIFACT_ID,
                "runtime_state": str(state.get("runtime_state", "unknown") or "unknown"),
                "connection_state": str(state.get("connection_state", "unknown") or "unknown"),
                "reason_codes": list(state.get("reason_codes", [])) if isinstance(state.get("reason_codes"), list) else [],
                "notification_type": str(state.get("notification_type", "") or ""),
                "notification_id": str(state.get("notification_id", "") or ""),
                "runtime_evidence_ref": str(state.get("runtime_evidence_ref", "") or ""),
                "runtime_transition_ref": str(state.get("runtime_transition_ref", "") or ""),
                "recovery_receipt_id": str(state.get("recovery_receipt_id", "") or ""),
                "updated_at": str(state.get("updated_at", _now_iso()) or _now_iso()),
            },
        }
        if self.persistence_enabled:
            PersistenceBackend.persist("runtime_presence", RUNTIME_PRESENCE_ARTIFACT_ID, payload)
        return payload["runtime_presence"]

    def _connected_account_health(self, cleanhouse_user_id: Optional[str] = None) -> Dict[str, Any]:
        rows: list[Dict[str, Any]] = []
        if cleanhouse_user_id:
            rows = self._connected_accounts_for_user(cleanhouse_user_id)
        else:
            for artifact in PersistenceBackend.list_artifacts("connected_account"):
                payload = artifact.get("data", {})
                account = payload.get("account", payload) if isinstance(payload, dict) else {}
                if isinstance(account, dict):
                    rows.append(self._connected_account_from_payload(account))
        public_rows = [self._connected_account_public_view(row) for row in rows]
        degraded = [row for row in public_rows if row.get("sync_status") == "degraded"]
        enabled = [row for row in public_rows if bool(row.get("ingestion_enabled", True))]
        latest_success = ""
        for row in public_rows:
            candidate = str(row.get("last_successful_sync", "") or "")
            if candidate and candidate > latest_success:
                latest_success = candidate
        return {
            "count": len(public_rows),
            "enabled_count": len(enabled),
            "degraded_count": len(degraded),
            "sync_status": "degraded" if degraded else ("ok" if public_rows else "pending"),
            "last_successful_sync": latest_success,
            "degraded_reason": str((degraded[0].get("degraded_reason", "") if degraded else "") or ""),
            "accounts": public_rows,
        }

    def _active_context_state(self) -> Dict[str, Any]:
        artifact = PersistenceBackend.read("active_context", ACTIVE_CONTEXT_LATEST_ARTIFACT_ID) if self.persistence_enabled else None
        payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        context = payload.get("active_context")
        if not isinstance(context, dict):
            context = None
        ignored = payload.get("ignored_keys", [])
        if not isinstance(ignored, list):
            ignored = []
        follow_env_enabled = os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_FOLLOW", "1").strip().lower() in {"1", "true", "yes", "on"}
        payload_follow = payload.get("follow_enabled")
        follow_enabled = bool(payload_follow) if isinstance(payload_follow, bool) else bool(follow_env_enabled)
        if follow_env_enabled:
            follow_enabled = True
        return {
            "status": str(payload.get("status", "unknown") or "unknown"),
            "follow_enabled": follow_enabled,
            "ignored_keys": [str(key) for key in ignored if str(key)],
            "active_context": copy.deepcopy(context),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }

    def _persist_active_context_state(
        self,
        *,
        context: Optional[Dict[str, Any]],
        follow_enabled: bool,
        ignored_keys: Sequence[str],
        status: str = "ok",
    ) -> Dict[str, Any]:
        payload = {
            "status": status,
            "follow_enabled": bool(follow_enabled),
            "ignored_keys": list(dict.fromkeys(str(key) for key in ignored_keys if str(key)))[-50:],
            "active_context": copy.deepcopy(context) if isinstance(context, dict) else None,
            "updated_at": _now_iso(),
        }
        if self.persistence_enabled:
            PersistenceBackend.persist("active_context", ACTIVE_CONTEXT_LATEST_ARTIFACT_ID, payload)
            if isinstance(context, dict) and context.get("id"):
                PersistenceBackend.persist("active_context", str(context["id"]), payload)
        return payload

    def _active_context_prompt_source(self, source_type: str) -> str:
        if source_type == "codex_artifact":
            return "codex_artifact"
        if source_type in {"operator_pickup", "export_file"}:
            return "operator_pickup"
        if source_type == "clipboard":
            return "active_context"
        return "active_context"

    def _attach_active_context(
        self,
        context: Dict[str, Any],
        previous_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        context = copy.deepcopy(context)
        if (
            isinstance(previous_context, dict)
            and previous_context.get("dedupe_key") == context.get("dedupe_key")
            and previous_context.get("prompt_id")
        ):
            for key in ("prompt_id", "session_id", "objective_id", "attached_at", "session_status"):
                if previous_context.get(key) and not context.get(key):
                    context[key] = previous_context[key]
            if previous_context.get("prompt_id"):
                context["prompt_id"] = previous_context["prompt_id"]
                context["attached"] = True
                previous_action = str(previous_context.get("last_agent_action", "") or "").strip()
                current_action = str(context.get("last_agent_action", "") or "").strip()
                if current_action and current_action != previous_action:
                    self._emit_codex_active_context_response_notification(
                        context=context,
                        session_id=str(context.get("session_id") or ""),
                        objective_id=str(context.get("objective_id") or "") or None,
                        prompt_id=str(context.get("prompt_id") or ""),
                    )
                return context
        if not context.get("attachable"):
            return context
        text = str(context.get("active_prompt", "")).strip()
        session_id = str(context.get("session_id", "")).strip()
        if not text or not session_id:
            return context
        objective_id = str(context.get("objective_id", "")).strip() or None
        repo_path = str(context.get("current_repo", "")).strip() or None
        evidence_refs = self._local_evidence_refs(context.get("evidence_refs", []))
        metadata = copy.deepcopy(context.get("metadata", {})) if isinstance(context.get("metadata"), dict) else {}
        metadata.update({
            "active_context_id": context.get("id", ""),
            "active_context_source": context.get("source_type", ""),
            "truth_classification": context.get("truth_classification", TRUTH_MISSING),
            "source_labels": list(context.get("source_labels", [])) if isinstance(context.get("source_labels"), list) else [],
            "frontmost_app": copy.deepcopy(context.get("frontmost_app", {})) if isinstance(context.get("frontmost_app"), dict) else {},
            "current_repo": repo_path or "",
        })
        prompt_result = self.submit_prompt(
            text=text,
            context=str(context.get("context", "")),
            scope=str(context.get("declared_scope", "") or ""),
            repo_path=repo_path,
            tool_identity=str(context.get("tool_identity", "CleanHouse") or "CleanHouse"),
            session_id=session_id,
            objective_id=objective_id,
            prompt_type="objective",
            evidence_refs=evidence_refs,
            metadata=metadata,
            source=self._active_context_prompt_source(str(context.get("source_type", ""))),
        )
        if prompt_result.get("status") != "ok":
            context["attach_error"] = prompt_result.get("message", "prompt attachment failed")
            return context
        context["prompt_id"] = prompt_result.get("id", "")
        context["session_id"] = prompt_result.get("session_id", session_id)
        context["attached"] = True
        context["attached_at"] = _now_iso()
        session_result = self.start_operator_session({
            "session_id": context["session_id"],
            "objective_id": objective_id,
            "summary": "active context attached: " + (str(context.get("current_objective") or text)[:160]),
            "metadata": {
                "source": "active_context",
                "active_context_id": context.get("id", ""),
                "prompt_id": context.get("prompt_id", ""),
                "truth_classification": context.get("truth_classification", TRUTH_MISSING),
                "current_repo": repo_path or "",
            },
        })
        context["session_status"] = session_result.get("session", {}).get("status", "unknown") if isinstance(session_result, dict) else "unknown"
        self._emit_codex_active_context_response_notification(
            context=context,
            session_id=context["session_id"],
            objective_id=objective_id,
            prompt_id=str(context.get("prompt_id") or ""),
        )
        return context

    def _emit_codex_active_context_response_notification(
        self,
        *,
        context: Dict[str, Any],
        session_id: str,
        objective_id: Optional[str],
        prompt_id: str,
    ) -> None:
        if os.getenv("CLEANHOUSE_ACTIVE_CONTEXT_RESPONSE_NOTIFICATIONS", "1").strip().lower() not in {"1", "true", "yes", "on"}:
            return
        if not isinstance(context, dict):
            return
        source_type = str(context.get("source_type", "") or "").strip().lower()
        tool_identity = str(context.get("tool_identity", "") or "").strip().lower()
        if source_type != "codex_artifact" and tool_identity != "codex":
            return
        last_action = str(context.get("last_agent_action", "") or "").strip()
        if not last_action:
            return
        if not session_id:
            return
        response_ref = f"local://cleanhouse/codex-response/{_fingerprint(session_id, prompt_id, last_action)}"
        evidence_refs = [response_ref]
        if prompt_id:
            evidence_refs.append(f"local://cleanhouse/prompt/{prompt_id}")
        evidence_refs.extend(self._local_evidence_refs(context.get("evidence_refs", [])))
        self._ensure_operator_notification(
            notification_type="codex_response_observed",
            session_id=session_id,
            objective_id=objective_id,
            severity="info",
            summary=f"codex responded: {last_action[:180]}",
            evidence_refs=evidence_refs,
            source="active_context",
            metadata={
                "tool_identity": "codex",
                "active_context_source": source_type or "active_context",
                "prompt_id": prompt_id,
                "active_context_id": str(context.get("id", "") or ""),
            },
        )

    def get_active_context(self, *, refresh: bool = False, attach: bool = False) -> Dict[str, Any]:
        state = self._active_context_state()
        context = state.get("active_context")
        if refresh:
            collected = self._active_context_collector.collect(
                follow_enabled=state["follow_enabled"],
                ignored_keys=state["ignored_keys"],
            )
            if attach:
                context = self._attach_active_context(collected, context)
            else:
                previous = context if isinstance(context, dict) else None
                context = copy.deepcopy(collected) if isinstance(collected, dict) else copy.deepcopy(previous)
                if isinstance(previous, dict) and isinstance(context, dict):
                    if previous.get("dedupe_key") == context.get("dedupe_key"):
                        for key in ("prompt_id", "session_id", "objective_id", "attached", "attached_at", "session_status"):
                            if previous.get(key) and not context.get(key):
                                context[key] = previous[key]
            state = self._persist_active_context_state(
                context=context,
                follow_enabled=state["follow_enabled"],
                ignored_keys=state["ignored_keys"],
            )
        return {
            "status": "ok",
            "follow_enabled": bool(state.get("follow_enabled", False)),
            "ignored_count": len(state.get("ignored_keys", [])),
            "active_context": copy.deepcopy(context) if isinstance(context, dict) else None,
            "updated_at": state.get("updated_at", ""),
        }

    def set_active_context_follow(self, enabled: bool, *, refresh: bool = True) -> Dict[str, Any]:
        state = self._active_context_state()
        state = self._persist_active_context_state(
            context=state.get("active_context"),
            follow_enabled=bool(enabled),
            ignored_keys=state["ignored_keys"],
        )
        if refresh:
            return self.get_active_context(refresh=True)
        return {
            "status": "ok",
            "follow_enabled": bool(state.get("follow_enabled", False)),
            "active_context": copy.deepcopy(state.get("active_context")) if isinstance(state.get("active_context"), dict) else None,
            "updated_at": state.get("updated_at", ""),
        }

    def pickup_active_context(self, data: Dict[str, Any]) -> Dict[str, Any]:
        state = self._active_context_state()
        collected = self._active_context_collector.collect(
            follow_enabled=True,
            ignored_keys=state["ignored_keys"],
            explicit_pickup=copy.deepcopy(data),
        )
        context = self._attach_active_context(collected, state.get("active_context"))
        state = self._persist_active_context_state(
            context=context,
            follow_enabled=state["follow_enabled"],
            ignored_keys=state["ignored_keys"],
        )
        return {
            "status": "ok",
            "follow_enabled": bool(state.get("follow_enabled", False)),
            "active_context": context,
            "updated_at": state.get("updated_at", ""),
        }

    def ignore_active_context(self, dedupe_key: Optional[str] = None) -> Dict[str, Any]:
        state = self._active_context_state()
        context = state.get("active_context")
        key = (dedupe_key or "").strip()
        if not key and isinstance(context, dict):
            key = str(context.get("dedupe_key", "") or "")
        ignored = list(state["ignored_keys"])
        if key and key not in ignored:
            ignored.append(key)
        if isinstance(context, dict) and key and context.get("dedupe_key") == key:
            context = {
                **context,
                "ignored": True,
                "truth_classification": TRUTH_MISSING,
                "continuity_status": "missing",
            }
        state = self._persist_active_context_state(
            context=context if isinstance(context, dict) else None,
            follow_enabled=state["follow_enabled"],
            ignored_keys=ignored,
        )
        return {
            "status": "ok",
            "ignored_key": key,
            "ignored_count": len(state["ignored_keys"]),
            "active_context": state.get("active_context"),
        }

    def _active_context_for_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        state = self._active_context_state()
        context = state.get("active_context")
        if isinstance(context, dict) and str(context.get("session_id", "")) == session_id:
            return copy.deepcopy(context)
        for artifact in PersistenceBackend.list_artifacts("active_context") if self.persistence_enabled else []:
            payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
            ctx = payload.get("active_context") if isinstance(payload, dict) else None
            if isinstance(ctx, dict) and str(ctx.get("session_id", "")) == session_id:
                return copy.deepcopy(ctx)
        return None

    def _latest_active_context_dict(self) -> Optional[Dict[str, Any]]:
        state = self._active_context_state()
        context = state.get("active_context")
        return copy.deepcopy(context) if isinstance(context, dict) else None

    def _active_context_notification_metadata(self, session_id: str) -> Dict[str, Any]:
        context = self._latest_active_context_dict()
        if session_id != RUNTIME_GLOBAL_SESSION_ID and (
            not isinstance(context, dict)
            or str(context.get("session_id", "")) != session_id
        ):
            context = None
        if not isinstance(context, dict):
            return {}
        metadata = {
            "active_context_id": context.get("id", ""),
            "prompt_id": context.get("prompt_id", ""),
            "objective_id": context.get("objective_id", ""),
            "active_context_source": context.get("source_type", ""),
            "truth_classification": context.get("truth_classification", ""),
            "active_context_evidence_ref": f"local://cleanhouse/active-context/{context.get('id', '')}" if context.get("id") else "",
        }
        runtime = self._runtime_presence_state()
        if runtime.get("runtime_evidence_ref"):
            metadata["runtime_evidence_ref"] = runtime["runtime_evidence_ref"]
        return {key: value for key, value in metadata.items() if value}

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
        command_tokens = [str(token or "").lower() for token in (result.args or ()) if str(token or "").strip()]
        command_name = str(result.command or "").lower()
        if "codex" in command_name or any("codex" in token for token in command_tokens):
            self._ensure_operator_notification(
                notification_type="codex_response_observed",
                session_id=session_id,
                objective_id=objective_id,
                severity="info" if result.returncode == 0 else "warning",
                summary=f"codex responded: {summary}",
                evidence_refs=[evidence_ref],
                source="command_observer",
                metadata={
                    "tool_identity": "codex",
                    "command": result.command,
                    "args": list(result.args),
                    "cwd": result.cwd,
                    "returncode": result.returncode,
                    "duration": result.duration,
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
        if tool_identity == "codex":
            severity = "info" if exit_code == 0 else "warning"
            self._ensure_operator_notification(
                notification_type="codex_response_observed",
                session_id=session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session"),
                objective_id=(data.get("objective_id") or os.getenv("CLEANHOUSE_OBJECTIVE_ID") or None),
                severity=severity,
                summary=f"codex responded: {command} (exit {exit_code})",
                evidence_refs=[f"local://cleanhouse/tool-event/{event_id}"],
                source="tool_event",
                metadata={
                    "tool_identity": tool_identity,
                    "command": command,
                    "args": list(args),
                    "exit_code": exit_code,
                    "cwd": cwd,
                    "duration": duration,
                },
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
        runtime = self.get_runtime()
        data = result.setdefault("data", {})
        if isinstance(data, dict):
            runtime_data = data.setdefault("runtime", {})
            if not isinstance(runtime_data, dict):
                runtime_data = {}
                data["runtime"] = runtime_data
            runtime_data["supervisor"] = runtime.get("supervisor", {})
            runtime_data["runtime_state"] = runtime.get("runtime_state")
            runtime_data["reason_codes"] = runtime.get("reason_codes", [])
            runtime_data["report_executor"] = runtime.get("report_executor", {})
            runtime_data["notifications"] = runtime.get("notifications", {})
            runtime_data["recovery_receipts"] = runtime.get("recovery_receipts", [])
            runtime_data["active_context"] = runtime.get("active_context", {})
            collector_manifest = data.get("collector_manifest", {})
            if isinstance(collector_manifest, dict):
                self._ensure_collector_failure_notifications(collector_manifest)
        return result

    def _runtime_recovery_dicts(self) -> list[Dict[str, Any]]:
        if not self.persistence_enabled:
            return []
        records: list[Dict[str, Any]] = []
        for artifact in PersistenceBackend.list_artifacts("runtime_recovery"):
            payload = artifact.get("data", {})
            if isinstance(payload, dict):
                records.append(payload)
        records.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
        return records

    def record_runtime_recovery(
        self,
        *,
        action: str,
        previous_state: Optional[Dict[str, Any]] = None,
        final_state: Optional[Dict[str, Any]] = None,
        reason_codes: Sequence[str] = (),
        evidence: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            from backend import runtime_supervisor

            return runtime_supervisor.persist_runtime_recovery(
                action=action,
                previous_state=previous_state,
                final_state=final_state,
                reason_codes=reason_codes,
                evidence=evidence,
            )
        except Exception as exc:
            return {"status": "error", "message": str(exc) or exc.__class__.__name__}

    def _notification_delivery_state(self) -> Dict[str, Any]:
        records = self._operator_notification_dicts()
        delivery_records = []
        failures = 0
        visibility_risk_count = 0
        for record in records:
            metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
            delivery = metadata.get("native_delivery")
            if not isinstance(delivery, dict):
                continue
            if metadata.get("visibility_state") == "visibility_risk":
                visibility_risk_count += 1
            delivery_records.append({
                "notification_id": record.get("id"),
                "notification_type": record.get("notification_type"),
                "status": delivery.get("status", "unknown"),
                "channel": delivery.get("channel"),
                "attempt_count": delivery.get("attempt_count", 0),
                "updated_at": delivery.get("updated_at"),
                "visibility_state": metadata.get("visibility_state", "dispatch_attempted"),
            })
            if delivery.get("status") not in {"dispatch_attempted", "delivered", "queued", "skipped"}:
                failures += 1
        delivery_records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {
            "status": "degraded" if failures else "ok",
            "delivery_count": len(delivery_records),
            "failure_count": failures,
            "visibility_risk_count": visibility_risk_count,
            "recent": delivery_records[:10],
        }

    def _runtime_evidence_refs(self, runtime: Dict[str, Any]) -> tuple[str, ...]:
        refs: list[str] = []
        runtime_state = str(runtime.get("runtime_state", "unknown") or "unknown")
        reasons = ",".join(sorted(str(reason) for reason in runtime.get("reason_codes", []) if reason))
        refs.append(f"local://cleanhouse/runtime/current/{_fingerprint(runtime_state, reasons or 'none')}")
        blocked = runtime.get("blocked_recovery", {}) if isinstance(runtime.get("blocked_recovery"), dict) else {}
        if blocked.get("receipt_id"):
            refs.append(f"local://cleanhouse/runtime_recovery/{blocked['receipt_id']}")
        for item in runtime.get("recovery_receipts", [])[:3]:
            if isinstance(item, dict) and item.get("id"):
                refs.append(f"local://cleanhouse/runtime_recovery/{item['id']}")
        return self._local_evidence_refs(refs)

    def _runtime_transition_kind(
        self,
        previous: Dict[str, Any],
        current: Dict[str, Any],
    ) -> str:
        if not str(previous.get("updated_at") or "").strip():
            return ""
        previous_state = str(previous.get("runtime_state", "unknown") or "unknown")
        current_state = str(current.get("runtime_state", "unknown") or "unknown")
        previous_conn = str(previous.get("connection_state", "unknown") or "unknown")
        current_conn = str(current.get("connection_state", "unknown") or "unknown")
        if previous_conn == "reachable" and current_conn != "reachable":
            return "runtime_connection_lost"
        if previous_conn != "reachable" and current_conn == "reachable" and current_state == "healthy":
            return "runtime_connection_restored"
        if previous_state != current_state:
            if previous_state in {"degraded", "recovering", "unhealthy", "unknown"} and current_state == "healthy":
                return "runtime_connection_restored"
            if current_state == "unhealthy":
                return "runtime_connection_lost"
            return "runtime_state_transition"
        return ""

    def _runtime_transition_summary(
        self,
        notification_type: str,
        previous: Dict[str, Any],
        current: Dict[str, Any],
    ) -> str:
        current_state = str(current.get("runtime_state", "unknown") or "unknown")
        previous_state = str(previous.get("runtime_state", "unknown") or "unknown")
        reasons = ", ".join(str(reason) for reason in current.get("reason_codes", []) if reason) or "no explicit reason codes"
        if notification_type == "runtime_connection_lost":
            return f"runtime connection lost: state={current_state} ({reasons})"
        if notification_type == "runtime_connection_restored":
            return f"runtime restored: {previous_state} -> {current_state}"
        return f"runtime transitioned: {previous_state} -> {current_state} ({reasons})"

    def _emit_runtime_transition_notification(self, runtime: Dict[str, Any], previous: Dict[str, Any]) -> None:
        notification_type = self._runtime_transition_kind(previous, runtime)
        connection_state = str(runtime.get("connection_state", "unknown") or "unknown")
        if not notification_type:
            state = {
                "runtime_state": str(runtime.get("runtime_state", "unknown") or "unknown"),
                "connection_state": connection_state,
                "reason_codes": list(runtime.get("reason_codes", [])),
                "notification_type": "",
                "notification_id": "",
                "runtime_evidence_ref": "",
                "runtime_transition_ref": "",
                "recovery_receipt_id": "",
                "updated_at": _now_iso(),
            }
            self._persist_runtime_presence_state(state)
            return
        refs = list(self._runtime_evidence_refs(runtime))
        transition_ref = f"local://cleanhouse/runtime-transition/{_fingerprint(previous.get('runtime_state', 'unknown'), runtime.get('runtime_state', 'unknown'), notification_type, ','.join(str(reason) for reason in runtime.get('reason_codes', []) if reason))}"
        refs.append(transition_ref)
        recovery_receipt_id = ""
        blocked = runtime.get("blocked_recovery", {}) if isinstance(runtime.get("blocked_recovery"), dict) else {}
        if blocked.get("receipt_id"):
            recovery_receipt_id = str(blocked.get("receipt_id"))
        created = self._ensure_operator_notification(
            notification_type=notification_type,
            session_id=RUNTIME_GLOBAL_SESSION_ID,
            objective_id=None,
            severity="critical" if runtime.get("runtime_state") == "unhealthy" or notification_type == "runtime_connection_lost" else "warning",
            summary=self._runtime_transition_summary(notification_type, previous, runtime),
            evidence_refs=refs,
            source="runtime",
            metadata={
                "runtime_state_before": str(previous.get("runtime_state", "unknown") or "unknown"),
                "runtime_state_after": str(runtime.get("runtime_state", "unknown") or "unknown"),
                "reason_codes": list(runtime.get("reason_codes", [])),
                "connection_state": connection_state,
                "recovery_receipt_id": recovery_receipt_id,
                "runtime_evidence_ref": refs[0] if refs else "",
                "runtime_transition_ref": transition_ref,
                "dashboard_target": "runtime",
            },
        )
        state = {
            "runtime_state": str(runtime.get("runtime_state", "unknown") or "unknown"),
            "connection_state": connection_state,
            "reason_codes": list(runtime.get("reason_codes", [])),
            "notification_type": notification_type,
            "notification_id": created.id if created else "",
            "runtime_evidence_ref": refs[0] if refs else "",
            "runtime_transition_ref": transition_ref,
            "recovery_receipt_id": recovery_receipt_id,
            "updated_at": _now_iso(),
        }
        self._persist_runtime_presence_state(state)

    def get_runtime(self, *, refresh_active_context: bool = False) -> Dict[str, Any]:
        previous_runtime_state = self._runtime_presence_state()
        try:
            from backend import runtime_supervisor

            runtime = runtime_supervisor.current_runtime_payload()
            runtime["connection_state"] = "reachable"
        except Exception as exc:
            runtime = {
                "status": "unhealthy",
                "runtime_state": "unhealthy",
                "reason_codes": ["runtime_supervisor_unavailable"],
                "error": str(exc) or exc.__class__.__name__,
                "connection_state": "lost",
                "blocked_recovery": {
                    "status": "blocked",
                    "type": "runtime_supervisor_unavailable",
                    "reason": str(exc) or exc.__class__.__name__,
                },
            }
        runtime["report_executor"] = self.login_report_executor_state()
        runtime["notifications"] = self._notification_delivery_state()
        runtime["recovery_receipts"] = [
            {
                "id": item.get("id"),
                "timestamp": item.get("timestamp"),
                "action": item.get("action"),
                "final_state": item.get("final_state", {}),
                "integrity": item.get("integrity", {}),
            }
            for item in self._runtime_recovery_dicts()[:10]
        ]
        if runtime.get("runtime_state") == "healthy":
            if runtime["report_executor"].get("status") == "degraded" or runtime["notifications"].get("status") == "degraded":
                runtime["runtime_state"] = "degraded"
                runtime["status"] = "degraded"
                runtime["reason_codes"] = sorted(set(runtime.get("reason_codes", []) + ["runtime_subsystem_degraded"]))
        runtime["operator_ready"] = bool(
            runtime.get("runtime_state") == "healthy"
            and runtime["report_executor"].get("status") != "degraded"
            and runtime["notifications"].get("status") != "degraded"
        )
        runtime["active_context"] = self.get_active_context(refresh=refresh_active_context)
        runtime["presence_mode"] = {
            "enabled": bool(self._settings.get("automation", {}).get("presence_mode_enabled", True)),
            "loop_started": self._presence_loop_started,
            "last_domain_health_count": len(self._presence_last_health),
        }
        runtime["domain_observer_matrix"] = self._domain_health_matrix(self._build_collector_manifest())
        runtime["connected_accounts"] = self._connected_account_health()
        self._emit_runtime_transition_notification(runtime, previous_runtime_state)
        runtime["runtime_notifications"] = self._runtime_notification_center_feed(limit=200)
        transport_only = 0
        operator_confirmed = 0
        unknown_visibility = 0
        for item in runtime["runtime_notifications"]:
            proof = str(item.get("visibility_proof", "") or (item.get("metadata", {}) or {}).get("visibility_proof", "transport_only"))
            if proof == "operator_confirmed":
                operator_confirmed += 1
            elif proof == "transport_only":
                transport_only += 1
            else:
                unknown_visibility += 1
        runtime["visibility_proof_summary"] = {
            "transport_only": transport_only,
            "operator_confirmed": operator_confirmed,
            "unknown": unknown_visibility,
        }
        runtime["visibility_state"] = {
            "risk_notifications": len([
                item for item in runtime["runtime_notifications"]
                if isinstance(item.get("metadata"), dict) and item.get("metadata", {}).get("visibility_state") == "visibility_risk"
            ]),
            "unacknowledged": len([item for item in runtime["runtime_notifications"] if not item.get("acknowledged")]),
        }
        return runtime

    def _domain_observer_registry(self) -> Dict[str, Dict[str, Any]]:
        return {
            "coding_agents": {
                "description": "Agentic coding systems and delegated execution surfaces",
                "surfaces": ["ai_activity", "tool_events", "command", "processes"],
                "adapters": ["cursor", "copilot", "codex", "opencode", "vscode", "replit", "ollama"],
            },
            "local_runtime": {
                "description": "Shell runtimes, localhost services, repositories, and filesystem activity",
                "surfaces": ["command", "network", "integrity", "processes", "filesystem_watcher"],
                "adapters": ["shell", "localhost", "git", "filesystem", "background_tools"],
            },
            "future_domains": {
                "description": "Planned expansion domains for all operator-visible runtime activity",
                "surfaces": ["browser", "cloud_drive", "messaging", "package_manager", "cicd", "daemon", "remote_api"],
                "adapters": [],
            },
        }

    def _domain_state_from_surface(self, surface: Dict[str, Any]) -> str:
        collector_status = str(surface.get("collector_status", "unknown") or "unknown")
        status = str(surface.get("status", "unknown") or "unknown")
        if collector_status in {"dependency_missing", "permission_denied"}:
            return "permission_blocked"
        if collector_status in {"failure", "error"} or status in {"unhealthy", "unavailable"}:
            return "offline"
        if collector_status in {"no_baseline", "unknown"} or status in {"degraded", "unknown", "unsupported"}:
            return "degraded"
        if collector_status == "ok" and status in {"safe", "warning", "critical", "ok", "supported"}:
            return "supported"
        return "unknown"

    def _domain_health_matrix(self, collector_manifest: Dict[str, Any]) -> Dict[str, Any]:
        registry = self._domain_observer_registry()
        surfaces = collector_manifest.get("surfaces", {}) if isinstance(collector_manifest, dict) else {}
        matrix: Dict[str, Any] = {"generated_at": _now_iso(), "domains": {}}
        for domain, spec in registry.items():
            entries: list[Dict[str, Any]] = []
            for surface_name in spec.get("surfaces", []):
                if surface_name in surfaces and isinstance(surfaces.get(surface_name), dict):
                    surface = surfaces[surface_name]
                    state = self._domain_state_from_surface(surface)
                    entries.append({
                        "surface": surface_name,
                        "state": state,
                        "status": surface.get("status", "unknown"),
                        "collector_status": surface.get("collector_status", "unknown"),
                        "support_status": surface.get("support_status", "unknown"),
                        "issue_count": int(surface.get("issue_count", 0) or 0),
                    })
                else:
                    entries.append({
                        "surface": surface_name,
                        "state": "unknown",
                        "status": "unknown",
                        "collector_status": "unknown",
                        "support_status": "unknown",
                        "issue_count": 0,
                    })
            states = [entry["state"] for entry in entries]
            aggregate = "supported"
            if any(state in {"offline", "permission_blocked"} for state in states):
                aggregate = "offline"
            elif any(state in {"degraded", "unknown"} for state in states):
                aggregate = "degraded"
            matrix["domains"][domain] = {
                "description": spec.get("description", ""),
                "adapters": list(spec.get("adapters", [])),
                "state": aggregate,
                "surfaces": entries,
            }
        return matrix

    def _domain_event_from_dict(self, payload: Dict[str, Any]) -> Optional[DomainEventRecord]:
        event_id = str(payload.get("id", "")).strip()
        domain = str(payload.get("domain", "")).strip()
        surface = str(payload.get("surface", "")).strip()
        if not event_id or not domain or not surface:
            return None
        severity = str(payload.get("severity", "warning") or "warning")
        if severity not in ISSUE_SEVERITIES:
            severity = "warning"
        return DomainEventRecord(
            id=event_id,
            domain=domain,
            surface=surface,
            event_type=str(payload.get("event_type", "domain_event") or "domain_event"),
            severity=severity,
            observed_at=str(payload.get("observed_at", _now_iso())),
            session_id=str(payload.get("session_id", RUNTIME_GLOBAL_SESSION_ID) or RUNTIME_GLOBAL_SESSION_ID),
            objective_id=str(payload.get("objective_id", "")).strip() or None,
            actor=copy.deepcopy(payload.get("actor", {})) if isinstance(payload.get("actor"), dict) else {},
            resource=copy.deepcopy(payload.get("resource", {})) if isinstance(payload.get("resource"), dict) else {},
            observed_vs_expected=copy.deepcopy(payload.get("observed_vs_expected", {})) if isinstance(payload.get("observed_vs_expected"), dict) else {},
            confidence=_coerce_confidence(payload.get("confidence", 0.7), 0.7),
            unknown_fields=tuple(str(item) for item in payload.get("unknown_fields", []) if str(item)) if isinstance(payload.get("unknown_fields"), list) else tuple(),
            evidence_refs=self._local_evidence_refs(payload.get("evidence_refs", [])),
            metadata=copy.deepcopy(payload.get("metadata", {})) if isinstance(payload.get("metadata"), dict) else {},
        )

    def _persist_domain_event(self, record: DomainEventRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist("domain_event", record.id, {"status": "ok", "event": record.to_dict()})

    def _all_domain_events(self) -> list[DomainEventRecord]:
        with self._lock:
            records = {record.id: record for record in self._domain_events.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("domain_event"):
                payload = artifact.get("data", {})
                raw = payload.get("event", payload) if isinstance(payload, dict) else None
                if not isinstance(raw, dict):
                    continue
                record = self._domain_event_from_dict(raw)
                if record and record.id not in records:
                    records[record.id] = record
        return list(records.values())

    def get_domain_events(
        self,
        *,
        domain: Optional[str] = None,
        surface: Optional[str] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._all_domain_events()]
        if domain:
            records = [record for record in records if record.get("domain") == domain]
        if surface:
            records = [record for record in records if record.get("surface") == surface]
        if severity:
            records = [record for record in records if record.get("severity") == severity]
        if status:
            records = [
                record for record in records
                if str((record.get("observed_vs_expected", {}) or {}).get("status", "")) == status
            ]
        records.sort(key=lambda item: item.get("observed_at", ""), reverse=True)
        records = records[: max(1, min(limit, 1000))]
        return {"status": "ok", "events": records, "count": len(records)}

    def _persist_policy_decision(self, payload: Dict[str, Any]) -> None:
        if not self.persistence_enabled:
            return
        decision_id = str(payload.get("id", "")).strip() or f"policy_decision:{_fingerprint(json.dumps(payload, sort_keys=True, default=str))}"
        PersistenceBackend.persist("policy_decision", decision_id, {"status": "ok", "decision": payload})

    def _persist_action_outcome(self, payload: Dict[str, Any]) -> None:
        if not self.persistence_enabled:
            return
        outcome_id = str(payload.get("id", "")).strip() or f"action_outcome:{_fingerprint(json.dumps(payload, sort_keys=True, default=str))}"
        PersistenceBackend.persist("action_outcome", outcome_id, {"status": "ok", "outcome": payload})

    def _notification_policy_decision(self, event: DomainEventRecord) -> Dict[str, Any]:
        notification_settings = self._settings.get("notification_policy", {}) if isinstance(self._settings, dict) else {}
        event_type = event.event_type
        notification_type = "incident_action_required"
        severity = "warning"
        next_action = "inspect lineage"
        if event_type == "scope_drift_detected":
            notification_type = "scope_drift_detected"
            severity = "critical"
            next_action = "review drift"
        elif event_type == "unexpected_deletion":
            notification_type = "unexpected_deletion_detected"
            severity = "critical"
            next_action = "open rollback"
        elif event_type == "port_reopened_unknown_process":
            notification_type = "port_reopened_unknown_process"
            severity = "critical"
            next_action = "inspect process lineage"
        elif event_type == "avatar_substitution_chain_break":
            notification_type = "avatar_substitution_chain_break"
            severity = "critical"
            next_action = "approve/reject mutation chain"
        elif event_type == "integrity_mismatch":
            notification_type = "integrity_mismatch_detected"
            severity = "critical"
            next_action = "open integrity chain"
        elif event_type == "watcher_offline":
            notification_type = "watcher_offline"
            severity = "warning"
            next_action = "ack watcher outage"
        elif event_type == "runtime_resumed":
            if bool(notification_settings.get("runtime_resumed_enabled", True)):
                notification_type = "runtime_connection_restored"
                severity = "info"
                next_action = "inspect recovery evidence"
            else:
                notification_type = "incident_action_required"
                severity = "warning"
                next_action = "inspect lineage"
        decision = {
            "id": f"policy_decision:{_fingerprint(event.id, notification_type)}",
            "event_id": event.id,
            "notification_type": notification_type,
            "severity": severity,
            "next_action": next_action,
            "timestamp": _now_iso(),
            "explainability": {
                "evidence_refs": list(event.evidence_refs),
                "reason": f"policy matched event_type={event_type}",
            },
        }
        self._persist_policy_decision(decision)
        return decision

    def _incident_case_from_dict(self, payload: Dict[str, Any]) -> Optional[IncidentCaseRecord]:
        incident_id = str(payload.get("id", "")).strip()
        state = str(payload.get("status", "")).strip()
        if not incident_id or state not in INCIDENT_CASE_STATES:
            return None
        return IncidentCaseRecord(
            id=incident_id,
            status=state,
            severity=str(payload.get("severity", "warning") or "warning"),
            title=str(payload.get("title", "") or ""),
            summary=str(payload.get("summary", "") or ""),
            session_id=str(payload.get("session_id", RUNTIME_GLOBAL_SESSION_ID) or RUNTIME_GLOBAL_SESSION_ID),
            objective_id=str(payload.get("objective_id", "")).strip() or None,
            source_event_id=str(payload.get("source_event_id", "") or ""),
            notification_type=str(payload.get("notification_type", "incident_action_required") or "incident_action_required"),
            created_at=str(payload.get("created_at", _now_iso())),
            updated_at=str(payload.get("updated_at", _now_iso())),
            acknowledged_at=payload.get("acknowledged_at"),
            resolved_at=payload.get("resolved_at"),
            next_action=str(payload.get("next_action", "") or ""),
            evidence_refs=self._local_evidence_refs(payload.get("evidence_refs", [])),
            metadata=copy.deepcopy(payload.get("metadata", {})) if isinstance(payload.get("metadata"), dict) else {},
            history=tuple(copy.deepcopy(payload.get("history", []))) if isinstance(payload.get("history"), list) else tuple(),
        )

    def _persist_incident_case(self, record: IncidentCaseRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist("incident_case", record.id, {"status": "ok", "incident": record.to_dict()})

    def _all_incident_cases(self) -> list[IncidentCaseRecord]:
        with self._lock:
            records = {record.id: record for record in self._incident_cases.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("incident_case"):
                payload = artifact.get("data", {})
                raw = payload.get("incident", payload) if isinstance(payload, dict) else None
                if not isinstance(raw, dict):
                    continue
                record = self._incident_case_from_dict(raw)
                if record and record.id not in records:
                    records[record.id] = record
        return list(records.values())

    def get_incident_cases(
        self,
        *,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._all_incident_cases()]
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        if status:
            records = [record for record in records if record.get("status") == status]
        if severity:
            records = [record for record in records if record.get("severity") == severity]
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        records = records[: max(1, min(limit, 1000))]
        return {"status": "ok", "incidents": records, "count": len(records)}

    def _incident_history_entry(
        self,
        *,
        incident_id: str,
        action: str,
        actor: str,
        state: str,
        note: str,
        evidence_refs: Sequence[str],
    ) -> Dict[str, Any]:
        payload = {
            "incident_id": incident_id,
            "action": action,
            "actor": actor,
            "state": state,
            "note": note,
            "timestamp": _now_iso(),
            "evidence_refs": list(self._local_evidence_refs(evidence_refs)),
        }
        payload["integrity"] = {"root_hash": _canonical_json_hash(payload)}
        return payload

    def _incident_case_by_event(self, event_id: str) -> Optional[IncidentCaseRecord]:
        for incident in self._all_incident_cases():
            if incident.source_event_id == event_id and incident.status in {"open", "acknowledged", "in_review"}:
                return incident
        return None

    def _ensure_incident_case_for_event(self, event: DomainEventRecord, decision: Dict[str, Any]) -> IncidentCaseRecord:
        notification_type = str(decision.get("notification_type", "incident_action_required") or "incident_action_required")
        incident_id = f"incident:{_fingerprint(event.id, notification_type)}"
        with self._lock:
            existing = self._incident_cases.get(incident_id)
        if existing is not None:
            return existing
        artifact = PersistenceBackend.read("incident_case", incident_id)
        if artifact is not None:
            payload = artifact.get("data", {})
            raw = payload.get("incident", payload) if isinstance(payload, dict) else None
            if isinstance(raw, dict):
                existing = self._incident_case_from_dict(raw)
                if existing is not None:
                    with self._lock:
                        self._incident_cases[existing.id] = existing
                    return existing
        now = _now_iso()
        history = (
            self._incident_history_entry(
                incident_id=incident_id,
                action="created",
                actor="policy_engine",
                state="open",
                note="incident created from domain event",
                evidence_refs=event.evidence_refs,
            ),
        )
        incident = IncidentCaseRecord(
            id=incident_id,
            status="open",
            severity=str(decision.get("severity", "warning") or "warning"),
            title=str(event.event_type or "incident"),
            summary=f"{event.domain}/{event.surface}: {event.event_type}",
            session_id=event.session_id,
            objective_id=event.objective_id,
            source_event_id=event.id,
            notification_type=notification_type,
            created_at=now,
            updated_at=now,
            acknowledged_at=None,
            resolved_at=None,
            next_action=str(decision.get("next_action", "inspect lineage")),
            evidence_refs=event.evidence_refs,
            metadata={
                "domain": event.domain,
                "surface": event.surface,
                "policy_decision_id": decision.get("id", ""),
            },
            history=history,
        )
        with self._lock:
            self._incident_cases[incident.id] = incident
        self._persist_incident_case(incident)
        return incident

    def emit_domain_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        domain = str(payload.get("domain", "")).strip()
        surface = str(payload.get("surface", "")).strip()
        event_type = str(payload.get("event_type", "")).strip()
        if not domain or not surface or not event_type:
            return {"status": "error", "message": "domain, surface, and event_type are required"}
        observed_at = str(payload.get("observed_at", _now_iso()) or _now_iso())
        session_id = str(payload.get("session_id", RUNTIME_GLOBAL_SESSION_ID) or RUNTIME_GLOBAL_SESSION_ID)
        severity = str(payload.get("severity", "warning") or "warning")
        if severity not in ISSUE_SEVERITIES:
            severity = "warning"
        evidence_refs = self._local_evidence_refs(payload.get("evidence_refs", []))
        if not evidence_refs:
            evidence_refs = (f"local://cleanhouse/domain-event/{_fingerprint(domain, surface, event_type, observed_at)}",)
        record = DomainEventRecord(
            id=f"domain_event:{_fingerprint(domain, surface, event_type, observed_at, session_id)}",
            domain=domain,
            surface=surface,
            event_type=event_type,
            severity=severity,
            observed_at=observed_at,
            session_id=session_id,
            objective_id=str(payload.get("objective_id", "")).strip() or None,
            actor=copy.deepcopy(payload.get("actor", {})) if isinstance(payload.get("actor"), dict) else {},
            resource=copy.deepcopy(payload.get("resource", {})) if isinstance(payload.get("resource"), dict) else {},
            observed_vs_expected=copy.deepcopy(payload.get("observed_vs_expected", {})) if isinstance(payload.get("observed_vs_expected"), dict) else {"status": "observed", "details": event_type},
            confidence=_coerce_confidence(payload.get("confidence", 0.7), 0.7),
            unknown_fields=tuple(str(item) for item in payload.get("unknown_fields", []) if str(item)) if isinstance(payload.get("unknown_fields"), list) else tuple(),
            evidence_refs=evidence_refs,
            metadata=copy.deepcopy(payload.get("metadata", {})) if isinstance(payload.get("metadata"), dict) else {},
        )
        with self._lock:
            self._domain_events[record.id] = record
        self._persist_domain_event(record)
        _insert_runtime_event(
            event_type="domain_event",
            path=f"/domain-events/{record.id}",
            summary=f"{record.domain}:{record.surface}:{record.event_type}",
            session_id=record.session_id,
            objective_id=record.objective_id,
            source_surface="domain_observer",
            actor_type=str(record.actor.get("type", "runtime") or "runtime"),
            evidence_level="observed",
            observed_vs_expected=record.observed_vs_expected,
            collector_status="ok",
            scope_relation="unknown",
            evidence_refs=record.evidence_refs,
            raw_evidence_ref=record.evidence_refs[0],
            data=record.to_dict(),
        )
        decision = self._notification_policy_decision(record)
        incident = self._ensure_incident_case_for_event(record, decision)
        self._ensure_operator_notification(
            notification_type=str(decision.get("notification_type", "incident_action_required")),
            session_id=record.session_id or RUNTIME_GLOBAL_SESSION_ID,
            objective_id=record.objective_id,
            severity=str(decision.get("severity", "warning")),
            summary=incident.summary,
            evidence_refs=record.evidence_refs,
            source="policy_engine",
            metadata={
                "incident_id": incident.id,
                "domain_event_id": record.id,
                "next_action": incident.next_action,
                "policy_decision_id": decision.get("id", ""),
            },
        )
        if incident.severity == "critical":
            self.create_approval_queue_item({
                "session_id": incident.session_id,
                "requested_action": incident.next_action,
                "reason": incident.summary,
                "objective_id": incident.objective_id,
                "evidence_refs": list(incident.evidence_refs),
                "source": "incident_case",
                "metadata": {"incident_id": incident.id, "domain_event_id": record.id},
            })
        return {
            "status": "ok",
            "event": record.to_dict(),
            "incident": incident.to_dict(),
            "policy_decision": decision,
        }

    def update_incident_case(self, incident_id: str, action: str, note: str = "", actor: str = "operator") -> Dict[str, Any]:
        incident_id = str(incident_id or "").strip()
        action = str(action or "").strip().lower()
        if action not in {"ack", "review", "resolve", "suppress"}:
            return {"status": "error", "message": "action must be ack, review, resolve, or suppress"}
        incident = next((item for item in self._all_incident_cases() if item.id == incident_id), None)
        if incident is None:
            return {"status": "not_found", "message": f"incident not found: {incident_id}"}
        now = _now_iso()
        state_map = {"ack": "acknowledged", "review": "in_review", "resolve": "resolved", "suppress": "suppressed"}
        next_state = state_map[action]
        history_entry = self._incident_history_entry(
            incident_id=incident.id,
            action=action,
            actor=actor,
            state=next_state,
            note=note,
            evidence_refs=incident.evidence_refs,
        )
        updated = IncidentCaseRecord(
            id=incident.id,
            status=next_state,
            severity=incident.severity,
            title=incident.title,
            summary=incident.summary,
            session_id=incident.session_id,
            objective_id=incident.objective_id,
            source_event_id=incident.source_event_id,
            notification_type=incident.notification_type,
            created_at=incident.created_at,
            updated_at=now,
            acknowledged_at=now if next_state in {"acknowledged", "in_review", "resolved"} and not incident.acknowledged_at else incident.acknowledged_at,
            resolved_at=now if next_state in {"resolved", "suppressed"} else incident.resolved_at,
            next_action=incident.next_action,
            evidence_refs=incident.evidence_refs,
            metadata=incident.metadata,
            history=incident.history + (history_entry,),
        )
        with self._lock:
            self._incident_cases[updated.id] = updated
        self._persist_incident_case(updated)
        self._persist_action_outcome({
            "id": f"action_outcome:{_fingerprint(updated.id, action, now)}",
            "incident_id": updated.id,
            "action": action,
            "actor": actor,
            "state": next_state,
            "note": note,
            "timestamp": now,
            "evidence_refs": list(updated.evidence_refs),
        })
        return {"status": "ok", "incident": updated.to_dict()}

    def notification_delivery_audit(self, limit: int = 200) -> Dict[str, Any]:
        records: list[Dict[str, Any]] = []
        for artifact in PersistenceBackend.list_artifacts("notification_delivery"):
            payload = artifact.get("data", {})
            row = payload.get("delivery", payload) if isinstance(payload, dict) else None
            if isinstance(row, dict):
                records.append(copy.deepcopy(row))
        records.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
        records = records[: max(1, min(limit, 1000))]
        return {"status": "ok", "deliveries": records, "count": len(records)}

    def notification_policy_audit(self, limit: int = 200) -> Dict[str, Any]:
        records: list[Dict[str, Any]] = []
        for artifact in PersistenceBackend.list_artifacts("policy_decision"):
            payload = artifact.get("data", {})
            row = payload.get("decision", payload) if isinstance(payload, dict) else None
            if isinstance(row, dict):
                records.append(copy.deepcopy(row))
        records.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
        records = records[: max(1, min(limit, 1000))]
        return {"status": "ok", "decisions": records, "count": len(records)}

    def action_outcome_audit(self, limit: int = 200) -> Dict[str, Any]:
        records: list[Dict[str, Any]] = []
        for artifact in PersistenceBackend.list_artifacts("action_outcome"):
            payload = artifact.get("data", {})
            row = payload.get("outcome", payload) if isinstance(payload, dict) else None
            if isinstance(row, dict):
                records.append(copy.deepcopy(row))
        records.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
        records = records[: max(1, min(limit, 1000))]
        return {"status": "ok", "outcomes": records, "count": len(records)}

    def notification_policy_config(self) -> Dict[str, Any]:
        settings = self.get_settings()
        policy = settings.get("settings", {}).get("notification_policy", {})
        return {
            "status": "ok",
            "notification_policy": copy.deepcopy(policy),
            "updated": settings.get("updated"),
        }

    def get_domain_observer_catalog(self) -> Dict[str, Any]:
        manifest = self._build_collector_manifest()
        return {
            "status": "ok",
            "registry": self._domain_observer_registry(),
            "matrix": self._domain_health_matrix(manifest),
        }

    def _workstation_unresolved_gaps(
        self,
        *,
        incidents: Sequence[Dict[str, Any]],
        runtime_health: Dict[str, Any],
        evidence_summaries: Sequence[Dict[str, Any]],
        domain_observer_matrix: Dict[str, Any],
        notifications: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        unresolved_incidents = [
            item for item in incidents
            if item.get("status") in {"open", "acknowledged", "in_review"}
        ]
        unresolved_drift = [
            item for item in evidence_summaries
            if item.get("summary_type") == "scope_drift"
        ]
        unresolved_integrity = [
            item for item in unresolved_incidents
            if item.get("notification_type") in {"integrity_mismatch_detected", "unexpected_deletion_detected"}
        ]
        unresolved_runtime = [
            item for item in unresolved_incidents
            if item.get("notification_type") in {"watcher_offline", "port_reopened_unknown_process"}
        ]
        offline_surfaces: list[Dict[str, Any]] = []
        domains = domain_observer_matrix.get("domains", {}) if isinstance(domain_observer_matrix, dict) else {}
        for domain_name, domain_payload in domains.items():
            surfaces = domain_payload.get("surfaces", []) if isinstance(domain_payload, dict) else []
            for surface in surfaces:
                if not isinstance(surface, dict):
                    continue
                if surface.get("state") not in {"offline", "permission_blocked"}:
                    continue
                offline_surfaces.append({
                    "domain": domain_name,
                    "surface": surface.get("surface", "unknown"),
                    "state": surface.get("state", "unknown"),
                    "collector_status": surface.get("collector_status", "unknown"),
                })
        runtime_state = str(runtime_health.get("runtime_state", "unknown") or "unknown")
        visibility_risk_count = len([
            item for item in notifications
            if isinstance(item.get("metadata"), dict)
            and item.get("metadata", {}).get("visibility_state") == "visibility_risk"
            and not item.get("acknowledged")
        ])
        return {
            "scope_drift": {
                "count": len(unresolved_drift),
                "status": "open" if unresolved_drift else "clear",
            },
            "integrity": {
                "count": len(unresolved_integrity),
                "status": "open" if unresolved_integrity else "clear",
            },
            "runtime": {
                "runtime_state": runtime_state,
                "state": "degraded" if runtime_state in {"unknown", "degraded", "unhealthy", "recovering"} else "clear",
                "incident_count": len(unresolved_runtime),
            },
            "observer_coverage": {
                "offline_surface_count": len(offline_surfaces),
                "offline_surfaces": offline_surfaces,
            },
            "notification_visibility": {
                "visibility_risk_count": visibility_risk_count,
                "status": "open" if visibility_risk_count else "clear",
            },
            "incident_count": len(unresolved_incidents),
        }

    def _ensure_presence_loop(self) -> None:
        if os.getenv("CLEANHOUSE_PRESENCE_MODE", "1").strip().lower() in {"0", "false", "no", "off"}:
            return
        if not bool(self._settings.get("automation", {}).get("presence_mode_enabled", True)):
            return
        with self._presence_loop_lock:
            if self._presence_loop_started:
                return
            thread = threading.Thread(target=self._presence_loop_worker, name="cleanhouse-presence-loop", daemon=True)
            thread.start()
            self._presence_loop_started = True

    def _presence_loop_worker(self) -> None:
        while not self._presence_loop_stop.is_set():
            try:
                self._run_presence_cycle()
            except Exception:
                pass
            time.sleep(max(2.0, float(self._settings.get("evidence_depth", {}).get("cache_ttl_seconds", 5.0))))

    def _emit_domain_health_event(self, domain: str, surface: Dict[str, Any], state: str) -> None:
        surface_name = str(surface.get("surface", "unknown") or "unknown")
        key = f"{domain}:{surface_name}"
        previous = self._presence_last_health.get(key)
        if previous == state:
            return
        self._presence_last_health[key] = state
        if state == "supported":
            event_type = "runtime_resumed"
            severity = "safe"
        elif state == "offline":
            event_type = "watcher_offline"
            severity = "critical"
        elif state == "permission_blocked":
            event_type = "watcher_offline"
            severity = "warning"
        else:
            event_type = "observer_degraded"
            severity = "warning"
        refs = [
            f"local://cleanhouse/domain-health/{_fingerprint(domain, surface_name, state)}",
            f"local://cleanhouse/collector/{surface_name}",
        ]
        self.emit_domain_event({
            "domain": domain,
            "surface": surface_name,
            "event_type": event_type,
            "severity": severity,
            "session_id": RUNTIME_GLOBAL_SESSION_ID,
            "actor": {"type": "runtime", "name": "presence_loop"},
            "resource": {"surface": surface_name, "collector_status": surface.get("collector_status")},
            "observed_vs_expected": {
                "status": state,
                "details": f"{surface_name} transitioned to {state}",
            },
            "confidence": 0.82,
            "unknown_fields": [],
            "evidence_refs": refs,
            "metadata": {"domain_state": state},
        })

    def _run_presence_cycle(self) -> None:
        try:
            self.get_active_context(refresh=True)
        except Exception:
            pass
        self._emit_process_file_integrity_suspicion_from_collectors()
        manifest = self._build_collector_manifest()
        matrix = self._domain_health_matrix(manifest)
        domains = matrix.get("domains", {}) if isinstance(matrix.get("domains"), dict) else {}
        for domain_name, domain_payload in domains.items():
            for surface in domain_payload.get("surfaces", []):
                if not isinstance(surface, dict):
                    continue
                state = str(surface.get("state", "unknown") or "unknown")
                if state not in DOMAIN_HEALTH_STATES:
                    state = "unknown"
                self._emit_domain_health_event(str(domain_name), surface, state)
        self._run_notification_visibility_cycle()

    def _issue_evidence_uris(self, issue: Dict[str, Any]) -> tuple[str, ...]:
        refs: list[str] = []
        seen: set[str] = set()
        for raw in issue.get("evidence_refs", []):
            if isinstance(raw, dict):
                value = raw.get("uri")
            else:
                value = raw
            ref = str(value or "").strip()
            if not ref or not ref.startswith("local://cleanhouse/") or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
        return tuple(refs)

    def _collector_process_issue_with_pid(self, issues: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            evidence = issue.get("evidence", {}) if isinstance(issue.get("evidence"), dict) else {}
            try:
                pid = int(evidence.get("pid", 0))
            except (TypeError, ValueError):
                pid = 0
            if pid > 0:
                return issue
        return None

    def _collector_integrity_issue_with_path(self, issues: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            evidence = issue.get("evidence", {}) if isinstance(issue.get("evidence"), dict) else {}
            path = str(evidence.get("file", "") or "").strip()
            change_type = str(evidence.get("change_type", "") or "").strip()
            if path and change_type in {"modified", "new", "missing"}:
                return issue
        return None

    def _emit_process_file_integrity_suspicion_from_collectors(self) -> None:
        process_payload = self.get_processes(refresh=True)
        integrity_payload = self.get_integrity(refresh=True)
        process_issues = process_payload.get("issues", []) if isinstance(process_payload.get("issues"), list) else []
        integrity_issues = integrity_payload.get("issues", []) if isinstance(integrity_payload.get("issues"), list) else []
        process_issue = self._collector_process_issue_with_pid(process_issues)
        integrity_issue = self._collector_integrity_issue_with_path(integrity_issues)
        if process_issue is None or integrity_issue is None:
            return

        process_evidence = process_issue.get("evidence", {}) if isinstance(process_issue.get("evidence"), dict) else {}
        integrity_evidence = integrity_issue.get("evidence", {}) if isinstance(integrity_issue.get("evidence"), dict) else {}
        try:
            pid = int(process_evidence.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        path = str(integrity_evidence.get("file", "") or "").strip()
        change_type = str(integrity_evidence.get("change_type", "") or "").strip()
        if pid <= 0 or not path:
            return

        signature = _fingerprint(
            str(pid),
            path,
            change_type,
            str(integrity_evidence.get("baseline_hash", "")),
            str(integrity_evidence.get("current_hash", "")),
        )
        key = "process_file_integrity_suspicion"
        if self._presence_last_signal.get(key) == signature:
            return
        self._presence_last_signal[key] = signature

        process_refs = self._issue_evidence_uris(process_issue)
        integrity_refs = self._issue_evidence_uris(integrity_issue)
        confidence = min(
            _coerce_confidence(process_issue.get("confidence"), 0.83),
            _coerce_confidence(integrity_issue.get("confidence"), 0.95),
        )
        command = str(process_evidence.get("command", "") or "").strip() or "unknown"
        details = f"process {pid} ({command}) correlated with integrity {change_type} on {path}"
        evidence_refs = self._local_evidence_refs([
            *process_refs,
            *integrity_refs,
            f"local://cleanhouse/correlation/process-integrity/{signature}",
        ])
        severity = "critical" if change_type == "modified" else "warning"
        self.emit_domain_event({
            "domain": "agent_firewall",
            "surface": "process_integrity_collector",
            "event_type": "process_file_integrity_suspicion",
            "severity": severity,
            "session_id": RUNTIME_GLOBAL_SESSION_ID,
            "actor": {
                "type": "process",
                "pid": pid,
                "process": command,
                "user": str(process_evidence.get("user", "") or ""),
            },
            "resource": {
                "path": path,
                "process_pid": pid,
                "change_type": change_type,
            },
            "observed_vs_expected": {
                "status": "deviation",
                "details": details,
            },
            "confidence": confidence,
            "unknown_fields": [],
            "evidence_refs": evidence_refs,
            "metadata": {
                "process_issue_id": str(process_issue.get("id", "") or process_issue.get("event_id", "")),
                "integrity_issue_id": str(integrity_issue.get("id", "") or integrity_issue.get("event_id", "")),
                "correlation_signature": signature,
                "workflow": "collector_correlation",
            },
        })

    def _notification_requires_visibility_watch(self, record: OperatorNotificationRecord) -> bool:
        return record.notification_type in OPERATOR_NATIVE_NOTIFICATION_TYPES

    def _run_notification_visibility_cycle(self) -> None:
        now_seconds = time.time()
        now_iso = _now_iso()
        policy = self._notification_policy_settings()
        max_reminders = int(policy["max_native_reminders_per_notification"])
        native_reminders_enabled = os.getenv("CLEANHOUSE_NATIVE_REMINDERS", "0").strip().lower() in {"1", "true", "yes", "on"}
        live_only = os.getenv("CLEANHOUSE_NATIVE_LIVE_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
        for row in self._operator_notification_dicts():
            record = self._operator_notification_from_dict(row)
            if not self._notification_requires_visibility_watch(record):
                continue
            metadata = copy.deepcopy(record.metadata)
            metadata = self._apply_visibility_metadata(record=record, metadata=metadata, delivery_result=None)
            visibility = metadata.get("visibility", {}) if isinstance(metadata.get("visibility"), dict) else {}
            visibility_state = metadata.get("visibility_state", "dispatch_attempted")
            next_reminder_at = _timestamp_seconds(visibility.get("next_reminder_at"))
            snoozed_until = _timestamp_seconds(visibility.get("snoozed_until"))
            should_remind = (
                not record.acknowledged
                and self._is_hard_interrupt_notification(record)
                and (snoozed_until is None or snoozed_until <= now_seconds)
                and (next_reminder_at is None or now_seconds >= next_reminder_at)
            )
            if live_only and should_remind:
                visibility["reminder_suppressed"] = True
                visibility["suppressed_reason"] = "live_only_no_replay"
                metadata["visibility"] = visibility
                should_remind = False
            if (not native_reminders_enabled) and should_remind:
                visibility["reminder_suppressed"] = True
                visibility["suppressed_reason"] = "native_reminders_disabled"
                metadata["visibility"] = visibility
                should_remind = False
            if visibility_state == "visibility_risk":
                visibility["persistent_marker"] = True
                metadata["visibility"] = visibility
            if not should_remind:
                updated = OperatorNotificationRecord(
                    id=record.id,
                    notification_type=record.notification_type,
                    session_id=record.session_id,
                    objective_id=record.objective_id,
                    severity=record.severity,
                    summary=record.summary,
                    evidence_refs=record.evidence_refs,
                    created_at=record.created_at,
                    acknowledged=record.acknowledged,
                    acknowledged_at=record.acknowledged_at,
                    source=record.source,
                    metadata=metadata,
                )
                with self._lock:
                    self._operator_notifications[updated.id] = updated
                self._persist_operator_notification(updated)
                continue
            current_reminder_count = int(visibility.get("reminder_count", 0) or 0)
            if current_reminder_count >= max_reminders:
                visibility["reminder_suppressed"] = True
                visibility["suppressed_reason"] = "max_native_reminders_reached"
                metadata["visibility"] = visibility
                updated = OperatorNotificationRecord(
                    id=record.id,
                    notification_type=record.notification_type,
                    session_id=record.session_id,
                    objective_id=record.objective_id,
                    severity=record.severity,
                    summary=record.summary,
                    evidence_refs=record.evidence_refs,
                    created_at=record.created_at,
                    acknowledged=record.acknowledged,
                    acknowledged_at=record.acknowledged_at,
                    source=record.source,
                    metadata=metadata,
                )
                with self._lock:
                    self._operator_notifications[updated.id] = updated
                self._persist_operator_notification(updated)
                continue
            reminder_seconds = self._notification_reminder_interval_seconds(record)
            reminder_count = current_reminder_count + 1
            visibility["last_reminder_at"] = now_iso
            visibility["next_reminder_at"] = _iso_from_timestamp(now_seconds + reminder_seconds)
            visibility["reminder_count"] = reminder_count
            visibility["reminder_suppressed"] = False
            visibility.pop("suppressed_reason", None)
            visibility["state"] = "backend_accepted"
            metadata["visibility"] = visibility
            metadata["visibility_state"] = "backend_accepted"
            reminder_record = OperatorNotificationRecord(
                id=record.id,
                notification_type=record.notification_type,
                session_id=record.session_id,
                objective_id=record.objective_id,
                severity=record.severity,
                summary=record.summary,
                evidence_refs=record.evidence_refs,
                created_at=record.created_at,
                acknowledged=record.acknowledged,
                acknowledged_at=record.acknowledged_at,
                source=record.source,
                metadata=metadata,
            )
            with self._lock:
                self._operator_notifications[reminder_record.id] = reminder_record
            self._persist_operator_notification(reminder_record)
            self._dispatch_native_operator_notification(reminder_record)

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
        stable_record_id = str(record_id or "").strip()
        if not stable_record_id:
            return None
        with self._lock:
            for record in self._intents:
                if record.id == stable_record_id:
                    return record
        if self.persistence_enabled:
            payload = PersistenceBackend.read("intent", stable_record_id)
            intent = payload.get("intent", payload) if isinstance(payload, dict) else None
            if isinstance(intent, dict):
                record = self._intent_record_from_dict(intent)
                if record.id == stable_record_id:
                    return record
        for record in self._intent_records():
            if record.id == stable_record_id:
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
        source: str = "ui",
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
        source = (source or "ui").strip() or "ui"
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
            source=source,
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
        if tool_identity.strip().lower() == "codex":
            prompt_ref = f"local://cleanhouse/prompt/{prompt_id}"
            self._ensure_operator_notification(
                notification_type="codex_prompt_sent",
                session_id=resolved_session_id,
                objective_id=objective,
                severity="info",
                summary=f"prompt sent to codex: {text[:120]}",
                evidence_refs=[prompt_ref, *local_evidence_refs],
                source="prompt",
                metadata={
                    "tool_identity": "codex",
                    "prompt_id": prompt_id,
                    "prompt_type": prompt_type,
                    "source": source,
                },
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
        notification = self._ensure_operator_notification(
            notification_type="session_ended",
            session_id=session_id,
            objective_id=existing.objective_id,
            severity="info",
            summary=summary,
            evidence_refs=existing.evidence_refs,
            source="session_api",
            metadata={"session_status": "finalized" if finalize else "stopped"},
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
        return self.set_operator_notification_acknowledged(notification_id, acknowledged=True)

    def set_operator_notification_acknowledged(self, notification_id: str, *, acknowledged: bool) -> Dict[str, Any]:
        notification_id = notification_id.strip() if isinstance(notification_id, str) else ""
        if not notification_id:
            return {"status": "error", "message": "notification_id required"}
        existing = self._operator_notification_record(notification_id)
        if existing is None:
            return {"status": "not_found", "message": f"notification not found: {notification_id}"}
        now = _now_iso()
        metadata = copy.deepcopy(existing.metadata)
        if acknowledged:
            metadata["visibility_proof"] = "operator_confirmed"
        else:
            metadata.setdefault("visibility_proof", "transport_only")
        updated = OperatorNotificationRecord(
            id=existing.id,
            notification_type=existing.notification_type,
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            severity=existing.severity,
            summary=existing.summary,
            evidence_refs=existing.evidence_refs,
            created_at=existing.created_at,
            acknowledged=bool(acknowledged),
            acknowledged_at=(existing.acknowledged_at or now) if acknowledged else None,
            source=existing.source,
            metadata=metadata,
        )
        metadata = self._apply_visibility_metadata(record=updated, metadata=metadata, delivery_result=None)
        updated = OperatorNotificationRecord(
            id=updated.id,
            notification_type=updated.notification_type,
            session_id=updated.session_id,
            objective_id=updated.objective_id,
            severity=updated.severity,
            summary=updated.summary,
            evidence_refs=updated.evidence_refs,
            created_at=updated.created_at,
            acknowledged=updated.acknowledged,
            acknowledged_at=updated.acknowledged_at,
            source=updated.source,
            metadata=metadata,
        )
        with self._lock:
            self._operator_notifications[updated.id] = updated
        self._persist_operator_notification(updated)
        return {"status": "ok", "notification": updated.to_dict()}

    def snooze_operator_notification(self, notification_id: str, *, minutes: int = 10) -> Dict[str, Any]:
        notification_id = notification_id.strip() if isinstance(notification_id, str) else ""
        if not notification_id:
            return {"status": "error", "message": "notification_id required"}
        existing = self._operator_notification_record(notification_id)
        if existing is None:
            return {"status": "not_found", "message": f"notification not found: {notification_id}"}
        minutes = max(1, min(int(minutes or 10), 1440))
        metadata = copy.deepcopy(existing.metadata)
        visibility = metadata.get("visibility", {}) if isinstance(metadata.get("visibility"), dict) else {}
        snoozed_until = _iso_from_timestamp(time.time() + (minutes * 60))
        visibility["snoozed_until"] = snoozed_until
        visibility["state"] = "snoozed"
        visibility["last_snoozed_at"] = _now_iso()
        visibility["next_reminder_at"] = snoozed_until
        metadata["visibility"] = visibility
        metadata["visibility_state"] = "snoozed"
        updated = OperatorNotificationRecord(
            id=existing.id,
            notification_type=existing.notification_type,
            session_id=existing.session_id,
            objective_id=existing.objective_id,
            severity=existing.severity,
            summary=existing.summary,
            evidence_refs=existing.evidence_refs,
            created_at=existing.created_at,
            acknowledged=existing.acknowledged,
            acknowledged_at=existing.acknowledged_at,
            source=existing.source,
            metadata=metadata,
        )
        with self._lock:
            self._operator_notifications[updated.id] = updated
        self._persist_operator_notification(updated)
        return {"status": "ok", "notification": updated.to_dict()}

    def notification_visibility_timeline(self, notification_id: str) -> Dict[str, Any]:
        notification_id = notification_id.strip() if isinstance(notification_id, str) else ""
        if not notification_id:
            return {"status": "error", "message": "notification_id required"}
        notification = self._operator_notification_record(notification_id)
        if notification is None:
            return {"status": "not_found", "message": f"notification not found: {notification_id}"}
        deliveries = []
        for artifact in PersistenceBackend.list_artifacts("notification_delivery"):
            payload = artifact.get("data", {})
            row = payload.get("delivery", payload) if isinstance(payload, dict) else None
            if not isinstance(row, dict):
                continue
            if row.get("notification_id") == notification_id:
                deliveries.append(copy.deepcopy(row))
        deliveries.sort(key=lambda row: str(row.get("timestamp", "")))
        metadata = notification.metadata if isinstance(notification.metadata, dict) else {}
        return {
            "status": "ok",
            "notification": notification.to_dict(),
            "phases": copy.deepcopy(metadata.get("delivery_phases", {})),
            "visibility_state": metadata.get("visibility_state", "dispatch_attempted"),
            "visibility": copy.deepcopy(metadata.get("visibility", {})),
            "deliveries": deliveries,
            "delivery_count": len(deliveries),
        }

    def send_test_operator_notification(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        notification_type: str = "codex_prompt_sent",
        severity: str = "info",
        summary: str = "CleanHouse test notification",
    ) -> Dict[str, Any]:
        session_id = str(session_id or "").strip() or RUNTIME_GLOBAL_SESSION_ID
        if notification_type not in OPERATOR_NOTIFICATION_TYPES:
            return {"status": "error", "message": f"unsupported notification_type: {notification_type}"}
        evidence_ref = f"local://cleanhouse/notification-probe/{_fingerprint(session_id, notification_type, summary, _now_iso())}"
        created = self._ensure_operator_notification(
            notification_type=notification_type,
            session_id=session_id,
            objective_id=objective_id,
            severity=severity,
            summary=summary,
            evidence_refs=[evidence_ref],
            source="notification_probe",
            metadata={"probe": True},
        )
        if created is None:
            return {"status": "error", "message": "notification not created"}
        return {"status": "ok", "notification": created.to_dict()}

    def get_operator_notifications(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        records = self._operator_notification_dicts()
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return {"notifications": records, "count": len(records)}

    def _runtime_notification_center_feed(self, limit: int = 200) -> list[Dict[str, Any]]:
        records = self._operator_notification_dicts()
        live_feed: list[Dict[str, Any]] = []
        for record in records:
            notification_type = str(record.get("notification_type", "") or "")
            if notification_type not in ESSENTIAL_OPERATOR_NOTIFICATION_TYPES:
                continue
            created_seconds = _timestamp_seconds(str(record.get("created_at", "") or ""))
            if created_seconds is None or created_seconds < self._live_notifications_started_seconds:
                continue
            metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
            if not bool(metadata.get("live_delivery_eligible", False)):
                continue
            if str(metadata.get("notification_boot_id", "") or "") != str(self._notification_boot_id):
                continue
            native_delivery = metadata.get("native_delivery", {}) if isinstance(metadata.get("native_delivery"), dict) else {}
            if str(native_delivery.get("status", "unknown") or "").strip().lower() != "delivered":
                continue
            live_feed.append(record)
        live_feed.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return live_feed[: max(1, int(limit or 200))]

    def start_connected_account_connect(
        self,
        *,
        cleanhouse_user_id: str,
        provider: str,
        connection_method: str,
        consent_version: str = "v1",
    ) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        provider = str(provider or "").strip().lower()
        method = str(connection_method or "").strip().lower()
        if not user_id:
            return {"status": "error", "message": "cleanhouse_user_id is required"}
        if provider not in CONNECTED_ACCOUNT_PROVIDERS:
            return {"status": "error", "message": f"unsupported provider: {provider}"}
        if method not in CONNECTED_ACCOUNT_METHODS:
            return {"status": "error", "message": f"unsupported connection_method: {method}"}
        provider_method = {"github": "oauth", "chatgpt": "browser_connector"}[provider]
        if method != provider_method:
            return {
                "status": "error",
                "message": f"{provider} requires connection_method={provider_method}",
            }
        connect_session_token = secrets.token_urlsafe(24)
        now = _now_iso()
        with self._connect_sessions_lock:
            self._connect_sessions[connect_session_token] = {
                "cleanhouse_user_id": user_id,
                "provider": provider,
                "connection_method": method,
                "consent_version": str(consent_version or "v1"),
                "created_at": now,
            }
        public_origin = os.getenv("CLEANHOUSE_PUBLIC_ORIGIN") or f"http://127.0.0.1:{os.getenv('CLEANHOUSE_PORT', '3333')}"
        if provider == "github":
            connect_url = f"{public_origin}/api/auth/oauth/github"
        else:
            connect_url = f"{public_origin}/api/cleanhouse/provider-events/import"
        return {
            "status": "ok",
            "provider": provider,
            "connection_method": method,
            "connect_session_token": connect_session_token,
            "connect_url": connect_url,
            "consent_version": str(consent_version or "v1"),
            "expires_in_seconds": 900,
        }

    def complete_connected_account_connect(
        self,
        *,
        cleanhouse_user_id: str,
        provider: str,
        connection_method: str,
        connect_session_token: str = "",
        provider_account_id: str = "",
        scopes: Optional[Sequence[str]] = None,
        consent_version: str = "v1",
        access_token: str = "",
        refresh_token: str = "",
        connector_signing_secret: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        provider = str(provider or "").strip().lower()
        method = str(connection_method or "").strip().lower()
        if not user_id:
            return {"status": "error", "message": "cleanhouse_user_id is required"}
        if provider not in CONNECTED_ACCOUNT_PROVIDERS:
            return {"status": "error", "message": f"unsupported provider: {provider}"}
        if method not in CONNECTED_ACCOUNT_METHODS:
            return {"status": "error", "message": f"unsupported connection_method: {method}"}
        token = str(connect_session_token or "").strip()
        if token:
            with self._connect_sessions_lock:
                pending = copy.deepcopy(self._connect_sessions.get(token, {}))
                self._connect_sessions.pop(token, None)
            if not pending:
                return {"status": "error", "message": "connect_session_token is invalid or expired"}
            if pending.get("cleanhouse_user_id") != user_id:
                return {"status": "forbidden", "message": "connect_session_token user mismatch"}
            if pending.get("provider") != provider:
                return {"status": "error", "message": "connect_session_token provider mismatch"}
            if pending.get("connection_method") != method:
                return {"status": "error", "message": "connect_session_token connection_method mismatch"}
        now = _now_iso()
        provider_account_id = str(provider_account_id or "").strip() or f"{provider}-account"
        account_id = f"connected_account:{_fingerprint(user_id, provider, provider_account_id)}"
        previous = self._connected_account_by_id(user_id, account_id)
        existing_connected_at = str((previous or {}).get("connected_at", "") or "")
        account = self._connected_account_from_payload({
            "account_id": account_id,
            "cleanhouse_user_id": user_id,
            "provider": provider,
            "provider_account_id": provider_account_id,
            "connection_method": method,
            "status": "connected",
            "scopes": [str(item).strip() for item in (scopes or []) if str(item).strip()],
            "connected_at": existing_connected_at or now,
            "last_sync_at": str((previous or {}).get("last_sync_at", "") or ""),
            "last_error": "",
            "consent_version": str(consent_version or "v1"),
            "ingestion_enabled": bool((previous or {}).get("ingestion_enabled", True)),
            "secrets": {
                "access_token_enc": self._encrypt_provider_secret(access_token),
                "refresh_token_enc": self._encrypt_provider_secret(refresh_token),
                "connector_signing_secret_enc": self._encrypt_provider_secret(connector_signing_secret),
            },
            "metadata": copy.deepcopy(metadata) if isinstance(metadata, dict) else {},
        })
        result = {"status": "ok", "account": account}
        if self.persistence_enabled:
            persisted = PersistenceBackend.persist("connected_account", account_id, result)
            if persisted.get("status") != "ok":
                result["status"] = "error"
                result["message"] = persisted.get("message", "persistence failed")
                return result
        return {"status": "ok", "account": self._connected_account_public_view(account)}

    def list_connected_accounts(self, *, cleanhouse_user_id: str) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        if not user_id:
            return {"status": "error", "message": "cleanhouse_user_id is required"}
        accounts = [self._connected_account_public_view(item) for item in self._connected_accounts_for_user(user_id)]
        return {"status": "ok", "accounts": accounts, "count": len(accounts)}

    def disconnect_connected_account(self, *, cleanhouse_user_id: str, account_id: str) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        account = self._connected_account_by_id(user_id, account_id)
        if account is None:
            return {"status": "not_found", "message": f"connected account not found: {account_id}"}
        account["status"] = "disconnected"
        account["ingestion_enabled"] = False
        account["last_error"] = ""
        account["secrets"] = {}
        payload = {"status": "ok", "account": account}
        if self.persistence_enabled:
            persisted = PersistenceBackend.persist("connected_account", account["account_id"], payload)
            if persisted.get("status") != "ok":
                return {"status": "error", "message": persisted.get("message", "persistence failed")}
        return {"status": "ok", "account": self._connected_account_public_view(account)}

    def _provider_import_signature_ok(
        self,
        *,
        account: Dict[str, Any],
        provider: str,
        account_id: str,
        events: Sequence[Dict[str, Any]],
        signature: str,
        nonce: str,
    ) -> bool:
        if provider != "chatgpt":
            return True
        encrypted_secret = str((account.get("secrets", {}) or {}).get("connector_signing_secret_enc", "") or "")
        shared_secret = self._decrypt_provider_secret(encrypted_secret)
        if not shared_secret:
            return False
        signature = str(signature or "").strip().lower()
        if signature.startswith("sha256="):
            signature = signature.split("=", 1)[1]
        body = {
            "provider": provider,
            "account_id": account_id,
            "nonce": nonce,
            "events": list(events),
        }
        digest = hmac.new(
            shared_secret.encode("utf-8"),
            _canonical_json_bytes(body),
            hashlib.sha256,
        ).hexdigest().lower()
        return bool(signature) and hmac.compare_digest(signature, digest)

    def _prompt_storage_for_import_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        prompt_text = ""
        for key in ("prompt", "prompt_text", "content", "text", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                prompt_text = value.strip()
                break
        if not prompt_text and isinstance(payload.get("prompt"), dict):
            prompt_text = str(payload.get("prompt", {}).get("text", "") or "").strip()
        if not prompt_text:
            return {}
        return {
            "encrypted_text": self._encrypt_provider_secret(prompt_text),
            "preview": prompt_text[:240],
            "content_hash": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        }

    def import_provider_events(
        self,
        *,
        cleanhouse_user_id: str,
        provider: str,
        account_id: str,
        events: Sequence[Dict[str, Any]],
        signature: str = "",
        nonce: str = "",
        imported_at: Optional[str] = None,
        capture_method: str = "",
        cursor: str = "",
    ) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        account_id = str(account_id or "").strip()
        provider = str(provider or "").strip().lower()
        if not user_id:
            return {"status": "error", "message": "cleanhouse_user_id is required"}
        if provider not in CONNECTED_ACCOUNT_PROVIDERS:
            return {"status": "error", "message": f"unsupported provider: {provider}"}
        if not account_id:
            return {"status": "error", "message": "account_id is required"}
        if not isinstance(events, list):
            return {"status": "error", "message": "events must be a list"}
        account = self._connected_account_by_id(user_id, account_id)
        if account is None:
            return {"status": "not_found", "message": f"connected account not found: {account_id}"}
        if account.get("provider") != provider:
            return {"status": "error", "message": "provider/account mismatch"}
        if not bool(account.get("ingestion_enabled", True)):
            return {"status": "error", "message": "ingestion is disabled for this account"}
        normalized_events = [item for item in events if isinstance(item, dict)]
        if not self._provider_import_signature_ok(
            account=account,
            provider=provider,
            account_id=account_id,
            events=normalized_events,
            signature=signature,
            nonce=nonce,
        ):
            return {"status": "forbidden", "message": "provider signature verification failed"}
        now = imported_at or _now_iso()
        accepted = 0
        deduped = 0
        rejected = 0
        rejected_reasons: list[str] = []
        provider_account_id = str(account.get("provider_account_id", "") or account_id)
        method = str(capture_method or account.get("connection_method") or "").strip() or "provider_import"
        session_id = self._latest_workstation_session_id() or RUNTIME_GLOBAL_SESSION_ID
        for idx, item in enumerate(normalized_events):
            provider_event_id = str(item.get("provider_event_id") or item.get("id") or "").strip()
            if not provider_event_id:
                rejected += 1
                rejected_reasons.append(f"event[{idx}] missing provider_event_id")
                continue
            dedupe_key = f"{provider}:{provider_event_id}"
            record_id = f"domain_event:{_fingerprint('provider_import', dedupe_key)}"
            if record_id in self._domain_events or PersistenceBackend.read("domain_event", record_id):
                deduped += 1
                continue
            observed_at = str(item.get("observed_at") or item.get("timestamp") or now)
            event_type = str(item.get("event_type") or item.get("type") or "activity")
            raw_ref = str(item.get("raw_ref") or f"local://cleanhouse/provider/{provider}/{provider_event_id}")
            prompt_storage = self._prompt_storage_for_import_event(item)
            metadata = copy.deepcopy(item.get("metadata", {})) if isinstance(item.get("metadata"), dict) else {}
            metadata.update({
                "source_type": "provider_import",
                "provider": provider,
                "provider_account_id": provider_account_id,
                "provider_event_id": provider_event_id,
                "imported_at": now,
                "capture_method": method,
                "raw_ref": raw_ref,
                "dedupe_key": dedupe_key,
            })
            if prompt_storage:
                metadata["prompt_storage"] = prompt_storage
            record = DomainEventRecord(
                id=record_id,
                domain="connected_account",
                surface=provider,
                event_type=event_type,
                severity="safe",
                observed_at=observed_at,
                session_id=str(item.get("session_id") or session_id),
                objective_id=str(item.get("objective_id") or "").strip() or None,
                actor=copy.deepcopy(item.get("actor", {})) if isinstance(item.get("actor"), dict) else {"type": "provider"},
                resource=copy.deepcopy(item.get("resource", {})) if isinstance(item.get("resource"), dict) else {},
                observed_vs_expected={"status": "imported", "details": f"imported from {provider}"},
                confidence=_coerce_confidence(item.get("confidence", 0.7), 0.7),
                unknown_fields=tuple(),
                evidence_refs=(raw_ref,),
                metadata=metadata,
            )
            with self._lock:
                self._domain_events[record.id] = record
            self._persist_domain_event(record)
            _insert_runtime_event(
                event_type="provider_import_event",
                path=f"/provider-events/{provider}/{provider_event_id}",
                summary=f"provider_import: {provider} {event_type}",
                session_id=record.session_id,
                objective_id=record.objective_id,
                source_surface="provider_import",
                actor_type="provider_connector",
                evidence_level="imported",
                observed_vs_expected=record.observed_vs_expected,
                collector_status="ok",
                scope_relation="unknown",
                evidence_refs=record.evidence_refs,
                raw_evidence_ref=raw_ref,
                data=record.to_dict(),
            )
            accepted += 1
        status = "ok" if rejected == 0 else "partial"
        if accepted == 0 and rejected > 0:
            status = "error"
        job_id = f"provider_import_job:{_fingerprint(user_id, account_id, provider, now, str(len(normalized_events)))}"
        job = {
            "id": job_id,
            "cleanhouse_user_id": user_id,
            "account_id": account_id,
            "provider": provider,
            "requested_count": len(normalized_events),
            "accepted_count": accepted,
            "dedupe_count": deduped,
            "rejected_count": rejected,
            "rejected_reasons": rejected_reasons[:20],
            "imported_at": now,
            "capture_method": method,
            "cursor": str(cursor or ""),
            "status": status,
        }
        if self.persistence_enabled:
            PersistenceBackend.persist("provider_import_job", job_id, {"status": "ok", "job": job})
            if cursor:
                cursor_id = f"provider_sync_cursor:{_fingerprint(account_id, provider)}"
                PersistenceBackend.persist("provider_sync_cursor", cursor_id, {
                    "status": "ok",
                    "cursor": {
                        "id": cursor_id,
                        "account_id": account_id,
                        "provider": provider,
                        "cursor": str(cursor),
                        "updated_at": now,
                    },
                })
        account["last_sync_at"] = now if accepted > 0 or deduped > 0 else str(account.get("last_sync_at", "") or "")
        account["last_error"] = "" if status == "ok" else "; ".join(rejected_reasons[:3])
        account["status"] = "connected" if status == "ok" else "degraded"
        if self.persistence_enabled:
            PersistenceBackend.persist("connected_account", account["account_id"], {"status": "ok", "account": account})
        return {
            "status": status,
            "account": self._connected_account_public_view(account),
            "job": job,
            "accepted_count": accepted,
            "dedupe_count": deduped,
            "rejected_count": rejected,
        }

    def sync_connected_account(
        self,
        *,
        cleanhouse_user_id: str,
        account_id: str,
        events: Optional[Sequence[Dict[str, Any]]] = None,
        cursor: str = "",
    ) -> Dict[str, Any]:
        user_id = str(cleanhouse_user_id or "").strip()
        account = self._connected_account_by_id(user_id, account_id)
        if account is None:
            return {"status": "not_found", "message": f"connected account not found: {account_id}"}
        if account.get("status") == "disconnected":
            return {"status": "error", "message": "account is disconnected"}
        normalized_events = [item for item in (events or []) if isinstance(item, dict)]
        if normalized_events:
            return self.import_provider_events(
                cleanhouse_user_id=user_id,
                provider=str(account.get("provider", "")),
                account_id=account["account_id"],
                events=normalized_events,
                cursor=cursor,
                capture_method=str(account.get("connection_method", "") or "provider_import"),
            )
        now = _now_iso()
        account["last_sync_at"] = now
        account["last_error"] = ""
        account["status"] = "connected"
        if self.persistence_enabled:
            PersistenceBackend.persist("connected_account", account["account_id"], {"status": "ok", "account": account})
            job_id = f"provider_import_job:{_fingerprint(user_id, account['account_id'], 'empty_sync', now)}"
            PersistenceBackend.persist("provider_import_job", job_id, {
                "status": "ok",
                "job": {
                    "id": job_id,
                    "cleanhouse_user_id": user_id,
                    "account_id": account["account_id"],
                    "provider": account.get("provider", ""),
                    "requested_count": 0,
                    "accepted_count": 0,
                    "dedupe_count": 0,
                    "rejected_count": 0,
                    "rejected_reasons": [],
                    "imported_at": now,
                    "capture_method": account.get("connection_method", ""),
                    "cursor": str(cursor or ""),
                    "status": "ok",
                },
            })
        return {"status": "ok", "account": self._connected_account_public_view(account)}

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
        claims.extend(self._continuity_claims_from_provider_imports(resolved_session_id, ignored_claim_ids))
        failed_pickups = self._continuity_failed_pickups(resolved_session_id)
        claims.extend(self._continuity_claims_from_failures(failed_pickups, ignored_claim_ids))
        active_context = self._active_context_for_session(resolved_session_id)
        continuity_truth = {
            "label": TRUTH_MISSING,
            "source_type": "active_context",
            "source_labels": [],
            "confidence_basis": "No active work context artifact is attached to this session.",
        }
        if isinstance(active_context, dict):
            truth_label = str(active_context.get("truth_classification") or TRUTH_MISSING)
            if truth_label not in ACTIVE_CONTEXT_TRUTH_LABELS:
                truth_label = TRUTH_MISSING
            source_labels = list(active_context.get("source_labels", [])) if isinstance(active_context.get("source_labels"), list) else []
            classification = {
                TRUTH_OBSERVED: "evidence_backed",
                TRUTH_INFERRED: "inferred",
                TRUTH_DEGRADED: "degraded",
                TRUTH_MISSING: "unknown",
            }.get(truth_label, "unknown")
            source_ref = str(active_context.get("source_ref") or "")
            evidence_refs = self._local_evidence_refs(active_context.get("evidence_refs", []))
            claim = self._continuity_claim(
                session_id=resolved_session_id,
                source_type="active_context",
                classification=classification,
                summary=f"Active work context attached with truth label {truth_label}.",
                snippet=str(active_context.get("active_prompt_preview") or active_context.get("current_objective") or "")[:500],
                source_ref=source_ref,
                evidence_refs=evidence_refs,
                freshness_at=str(active_context.get("updated_at") or ""),
                confidence_basis="Continuity is limited to observed/inferred local active-context fields; missing fields remain explicit.",
            )
            if claim["id"] not in ignored_claim_ids:
                claims.append(claim)
            continuity_truth = {
                "label": truth_label,
                "source_type": str(active_context.get("source_type") or "active_context"),
                "source_labels": source_labels,
                "confidence_basis": claim["confidence_basis"],
                "missing_fields": [
                    field for field in ("current_repo", "current_objective", "active_prompt", "last_agent_action")
                    if not str(active_context.get(field) or "").strip()
                ],
            }

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
        active_source_status = self._continuity_active_source_status(claims, active_source)
        pickup_channel_status = "degraded" if failed_pickups else "ok"
        status = self._continuity_status(active_source_status, pickup_channel_status)
        return {
            "status": status,
            "active_source_status": active_source_status,
            "pickup_channel_status": pickup_channel_status,
            "session_id": resolved_session_id,
            "generated_at": _now_iso(),
            "active_source": active_source,
            "freshness": self._continuity_freshness(active_source),
            "confidence_basis": active_source.get("confidence_basis", "unavailable") if active_source else "unavailable",
            "continuity_truth": continuity_truth,
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
            source_type = "manual" if str(prompt.source or "").strip().lower() in {"manual", "operator_pickup", "pickup", "clipboard"} else "current_thread_context"
            summary = "Manual prompt pickup is available." if source_type == "manual" else "Current session prompt/context is available."
            claims.append(self._continuity_claim(
                session_id=session_id,
                source_type=source_type,
                classification="evidence_backed",
                summary=summary,
                snippet=prompt.text[:500],
                source_ref=f"local://cleanhouse/prompt/{prompt.id}",
                evidence_refs=[f"local://cleanhouse/prompt/{prompt.id}", *prompt.evidence_refs],
                freshness_at=prompt.timestamp,
                confidence_basis="Prompt/context record is persisted in this CleanHouse session.",
                claim_id=claim_id,
                metadata={"prompt_id": prompt.id, "prompt_type": prompt.prompt_type, "objective_id": prompt.objective_id, "source": prompt.source},
            ))
        return claims

    def _continuity_claims_from_provider_imports(
        self,
        session_id: str,
        ignored_claim_ids: Set[str],
    ) -> list[Dict[str, Any]]:
        claims: list[Dict[str, Any]] = []
        records = [row for row in self.get_domain_events(limit=300).get("events", []) if isinstance(row, dict)]
        records.sort(key=lambda row: str(row.get("observed_at", "")), reverse=True)
        for event in records:
            if str(event.get("session_id", "")) != session_id:
                continue
            metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
            if str(metadata.get("source_type", "")).strip() != "provider_import":
                continue
            provider = str(metadata.get("provider", "")).strip() or str(event.get("surface", "")).strip()
            provider_event_id = str(metadata.get("provider_event_id", "")).strip()
            claim_id = f"continuity_claim:{_fingerprint(session_id, 'provider_import', provider, provider_event_id, str(event.get('id', '')))}"
            if claim_id in ignored_claim_ids:
                continue
            preview = str((metadata.get("prompt_storage", {}) or {}).get("preview", "")).strip()
            summary = f"Imported {provider} activity is available for continuity." if provider else "Imported provider activity is available for continuity."
            claims.append(self._continuity_claim(
                session_id=session_id,
                source_type="provider_import",
                classification="evidence_backed",
                summary=summary,
                snippet=preview[:500],
                source_ref=str(metadata.get("raw_ref", "") or f"local://cleanhouse/domain-event/{event.get('id', '')}"),
                evidence_refs=event.get("evidence_refs", []),
                freshness_at=str(metadata.get("imported_at", "") or event.get("observed_at", "")),
                confidence_basis="Provider-linked imported event is persisted with provenance metadata and stable dedupe key.",
                claim_id=claim_id,
                metadata={
                    "provider": provider,
                    "provider_account_id": str(metadata.get("provider_account_id", "") or ""),
                    "provider_event_id": provider_event_id,
                    "capture_method": str(metadata.get("capture_method", "") or ""),
                },
            ))
            if len(claims) >= 10:
                break
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
    def _continuity_active_source_status(
        claims: Sequence[Dict[str, Any]],
        active_source: Dict[str, Any],
    ) -> str:
        if not active_source or active_source.get("classification") == "unknown":
            return "unknown"
        if active_source.get("classification") == "degraded":
            return "degraded"
        if any(claim.get("classification") == "evidence_backed" for claim in claims):
            return "ok"
        return "inferred"

    @staticmethod
    def _continuity_status(active_source_status: str, pickup_channel_status: str) -> str:
        if active_source_status == "unknown":
            return "unknown"
        if active_source_status == "degraded":
            return "degraded"
        if active_source_status == "inferred":
            return "inferred"
        if pickup_channel_status == "degraded":
            return "ok_with_pickup_degraded"
        return "ok"

    @staticmethod
    def _continuity_freshness(source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        value = (source or {}).get("freshness_at") or (source or {}).get("created_at")
        if not value:
            return {"state": "unknown", "timestamp": None, "age_seconds": None}
        try:
            timestamp = datetime.fromisoformat(str(value))
            now = datetime.now(timestamp.tzinfo) if timestamp.tzinfo else datetime.now()
            age_seconds = max(0, int((now - timestamp).total_seconds()))
        except (TypeError, ValueError):
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
        active_context_payload = self.get_active_context(refresh=False)
        active_context = active_context_payload.get("active_context")
        if (
            not resolved_session_id
            and isinstance(active_context, dict)
            and str(active_context.get("session_id") or "").strip()
        ):
            resolved_session_id = str(active_context.get("session_id") or "").strip()
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
            timelines = self.get_timelines(session_id=resolved_session_id).get("timelines", [])
            timeline_result = timelines[0] if timelines else self.build_timeline(resolved_session_id)
            if timelines:
                timeline_result.setdefault("status", "ok")
                timeline_result.setdefault("session_id", resolved_session_id)

            # Keep workstation requests responsive: reuse cached signals/alerts when present.
            signal_rows = self.get_signals(session_id=resolved_session_id).get("signals", [])
            if signal_rows:
                signals_result = {
                    "status": "ok",
                    "session_id": resolved_session_id,
                    "signal_count": len(signal_rows),
                    "signals": signal_rows,
                }
            else:
                self.correlate(resolved_session_id)
                signals_result = self.classify(resolved_session_id)

            alert_rows = self.get_alerts(session_id=resolved_session_id).get("alerts", [])
            if alert_rows:
                alerts_result = {
                    "status": "ok",
                    "session_id": resolved_session_id,
                    "alert_count": len(alert_rows),
                    "alerts": alert_rows,
                }
            else:
                alerts_result = self.generate_alerts(resolved_session_id)

            receipts_result = self.get_receipts(session_id=resolved_session_id)
            approvals_result = self.get_approval_queue(session_id=resolved_session_id)
            for receipt in receipts_result.get("receipts", [])[:5]:
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

        objectives = self._workstation_objectives(resolved_session_id)
        mutations = self._workstation_mutations(resolved_session_id, timeline_result, live_events)
        file_lineage = self._file_lineage_rows(session_id=resolved_session_id, mutations=mutations) if resolved_session_id else []
        task_manager = self.get_task_manager_snapshot(refresh=False)
        port_monitor = self.get_port_monitor_snapshot(refresh=False)
        proposal_queue = self.get_operation_proposals(session_id=resolved_session_id).get("proposals", []) if resolved_session_id else []
        qpb_cases = self.get_qpb_cases(session_id=resolved_session_id).get("cases", []) if resolved_session_id else []
        qpb_action_queue = [
            case for case in qpb_cases
            if case.get("status") in {"detected", "quarantined", "purge_pending", "purged"}
        ]
        if resolved_session_id:
            declared_scope = str(objectives[0].get("scope", "")) if objectives else ""
            self._ensure_critical_filesystem_mutation_notifications(
                session_id=resolved_session_id,
                objective_id=session_payload.get("objective_id"),
                declared_scope=declared_scope,
                mutations=mutations,
            )
        domain_observer_matrix = self._domain_health_matrix(self._build_collector_manifest())
        incidents_payload = self.get_incident_cases(session_id=resolved_session_id or None, limit=200)
        incidents = incidents_payload.get("incidents", [])
        active_incident_queue = [
            item for item in incidents
            if item.get("status") in {"open", "acknowledged", "in_review"}
        ]
        action_history = self.action_outcome_audit(limit=200)
        notification_delivery = self.notification_delivery_audit(limit=200)
        notification_policy = self.notification_policy_audit(limit=200)
        notifications = self.get_operator_notifications(session_id=resolved_session_id).get("notifications", [])
        notification_visibility_queue = [
            item for item in notifications
            if isinstance(item.get("metadata"), dict)
            and item.get("metadata", {}).get("visibility_state") == "visibility_risk"
            and not item.get("acknowledged")
        ]
        notification_reminders = [
            {
                "notification_id": item.get("id", ""),
                "notification_type": item.get("notification_type", ""),
                "visibility_state": item.get("metadata", {}).get("visibility_state", "dispatch_attempted") if isinstance(item.get("metadata"), dict) else "dispatch_attempted",
                "reminder": copy.deepcopy(item.get("metadata", {}).get("visibility", {})) if isinstance(item.get("metadata"), dict) else {},
            }
            for item in notifications
            if isinstance(item.get("metadata"), dict) and isinstance(item.get("metadata", {}).get("visibility"), dict)
        ]
        runtime_health = self._runtime_presence_state()
        operational_presence = self._build_operational_presence(
            session=session_payload,
            objectives=objectives,
            mutations=mutations,
            approvals=approvals,
            notifications=notifications,
            evidence_summaries=evidence_summaries,
            timeline=timeline_result,
            live_events=live_events,
            active_context=active_context if isinstance(active_context, dict) else None,
            runtime_health=runtime_health,
        )
        unresolved_gaps = self._workstation_unresolved_gaps(
            incidents=incidents,
            runtime_health=runtime_health,
            evidence_summaries=evidence_summaries,
            domain_observer_matrix=domain_observer_matrix,
            notifications=notifications,
        )
        return {
            "status": "ok",
            "session": session_payload,
            "active_context": active_context_payload,
            "operational_presence": operational_presence,
            "continuity_provenance": continuity_provenance,
            "continuity": {
                "status": continuity_provenance.get("status", "unknown"),
                "active_source_status": continuity_provenance.get("active_source_status", "unknown"),
                "pickup_channel_status": continuity_provenance.get("pickup_channel_status", "unknown"),
                "active_source": continuity_provenance.get("active_source", {}),
            },
            "domain_observer_matrix": domain_observer_matrix,
            "active_incident_queue": active_incident_queue,
            "incidents": incidents,
            "notification_history": notification_delivery.get("deliveries", []),
            "action_history": action_history.get("outcomes", []),
            "notification_policy_history": notification_policy.get("decisions", []),
            "unresolved_gaps": unresolved_gaps,
            "objectives": objectives,
            "live_events": live_events,
            "mutations": mutations,
            "file_lineage": file_lineage,
            "task_manager": task_manager,
            "port_monitor": port_monitor,
            "qpb_cases": qpb_cases,
            "qpb_action_queue": qpb_action_queue,
            "mediator_queue": proposal_queue,
            "deviation_signals": {
                "signals": signals_result.get("signals", []),
                "alerts": alerts,
                "signal_count": signals_result.get("signal_count", len(signals_result.get("signals", []))),
                "alert_count": alerts_result.get("alert_count", len(alerts)),
            },
            "receipts": receipts,
            "approvals": approvals,
            "notifications": notifications,
            "notification_visibility_queue": notification_visibility_queue,
            "notification_reminders": notification_reminders,
            "evidence_summaries": evidence_summaries,
            "receipt_replays": receipt_replays,
            "timeline": timeline_result,
            "connected_accounts": self._connected_account_health(),
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
        active_context: Optional[Dict[str, Any]] = None,
        runtime_health: Optional[Dict[str, Any]] = None,
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
        runtime_health = runtime_health if isinstance(runtime_health, dict) else {}
        active_work_context = {
            "id": str((active_context or {}).get("id") or ""),
            "source_type": str((active_context or {}).get("source_type") or "none"),
            "source_labels": list((active_context or {}).get("source_labels", [])) if isinstance((active_context or {}).get("source_labels"), list) else [],
            "truth_classification": str((active_context or {}).get("truth_classification") or TRUTH_MISSING),
            "current_repo": str((active_context or {}).get("current_repo") or ""),
            "current_objective": str((active_context or {}).get("current_objective") or ""),
            "active_prompt_preview": str((active_context or {}).get("active_prompt_preview") or ""),
            "prompt_id": str((active_context or {}).get("prompt_id") or ""),
            "session_id": str((active_context or {}).get("session_id") or session_id),
            "objective_id": str((active_context or {}).get("objective_id") or ""),
            "last_agent_action": str((active_context or {}).get("last_agent_action") or ""),
            "pending_review_drift": {
                "pending_approvals": len(pending_approvals),
                "scope_drift_summaries": len(drift_summaries),
                "unacknowledged_notifications": len(unacked_notifications),
            },
            "runtime_health": {
                "runtime_state": str(runtime_health.get("runtime_state") or "unknown"),
                "connection_state": str(runtime_health.get("connection_state") or "unknown"),
                "reason_codes": list(runtime_health.get("reason_codes", [])) if isinstance(runtime_health.get("reason_codes"), list) else [],
                "notification_id": str(runtime_health.get("notification_id") or ""),
                "runtime_evidence_ref": str(runtime_health.get("runtime_evidence_ref") or ""),
            },
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
            "active_work_context": active_work_context,
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

    def _operator_notification_by_incident_key(
        self,
        *,
        notification_type: str,
        session_id: str,
        incident_key: str,
    ) -> Optional[OperatorNotificationRecord]:
        if not incident_key:
            return None
        stable_id = f"notification:{_fingerprint(incident_key, notification_type, session_id)}"
        existing = self._operator_notification_record(stable_id)
        if existing is not None:
            return existing
        with self._lock:
            notifications = list(self._operator_notifications.values())
        for record in notifications:
            notification = record.to_dict()
            metadata = notification.get("metadata", {}) if isinstance(notification.get("metadata"), dict) else {}
            if (
                str(notification.get("notification_type", "")) == notification_type
                and str(notification.get("session_id", "")) == session_id
                and str(metadata.get("incident_key", "")) == incident_key
            ):
                return self._operator_notification_from_dict(notification)
        return None

    def _track_open_codex_prompt(self, session_id: str, prompt_id: str) -> None:
        stable_session_id = str(session_id or "").strip()
        stable_prompt_id = str(prompt_id or "").strip()
        if not stable_session_id or not stable_prompt_id:
            return
        with self._lock:
            queue = self._open_codex_prompts_by_session.get(stable_session_id)
            if queue is None:
                queue = deque(maxlen=64)
                self._open_codex_prompts_by_session[stable_session_id] = queue
            if stable_prompt_id not in queue:
                queue.append(stable_prompt_id)

    def _resolve_open_codex_prompt_for_end(self, session_id: str, prompt_id: str) -> str:
        stable_session_id = str(session_id or "").strip()
        explicit_prompt_id = str(prompt_id or "").strip()
        if not stable_session_id:
            return explicit_prompt_id
        with self._lock:
            queue = self._open_codex_prompts_by_session.get(stable_session_id)
            if queue is None or not queue:
                return explicit_prompt_id
            if explicit_prompt_id:
                if explicit_prompt_id in queue:
                    queue.remove(explicit_prompt_id)
                if not queue:
                    self._open_codex_prompts_by_session.pop(stable_session_id, None)
                return explicit_prompt_id
            resolved = queue.popleft()
            if not queue:
                self._open_codex_prompts_by_session.pop(stable_session_id, None)
            return str(resolved or "")

    def _notification_incident_key(
        self,
        *,
        notification_type: str,
        session_id: str,
        evidence_refs: Sequence[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        md = metadata or {}
        if notification_type in {"scope_drift_detected", "excessive_traversal"}:
            if evidence_refs:
                stable_refs = sorted(str(ref) for ref in evidence_refs)
                return f"{notification_type}:{session_id}:evidence:{_fingerprint(*stable_refs[:8])}"
            for key in ("alert_id", "domain_event_id", "prompt_id", "objective_id", "active_context_id", "incident_id"):
                value = str(md.get(key) or "").strip()
                if value:
                    return f"{notification_type}:{session_id}:{key}:{value}"
            raw_ts = str(md.get("timestamp") or md.get("observed_at") or _now_iso())
            ts_value = _timestamp_seconds(raw_ts)
            if ts_value is None:
                ts_value = time.time()
            dedupe_window_seconds = int(self._notification_policy_settings().get("dedupe_window_seconds", 120))
            bucket = int(ts_value // max(1, dedupe_window_seconds))
            return f"{notification_type}:{session_id}:time_window:{bucket}"
        for key in (
            "runtime_transition_ref",
            "runtime_evidence_ref",
            "receipt_id",
            "active_context_id",
            "prompt_id",
            "alert_id",
            "incident_id",
            "domain_event_id",
            "mutation_event_id",
            "rollback_id",
        ):
            value = str(md.get(key) or "").strip()
            if value:
                return f"{notification_type}:{session_id}:{key}:{value}"
        if evidence_refs:
            stable_refs = sorted(str(ref) for ref in evidence_refs)
            return f"{notification_type}:{session_id}:evidence:{_fingerprint(*stable_refs[:8])}"
        raw_ts = str(md.get("timestamp") or md.get("observed_at") or _now_iso())
        ts_value = _timestamp_seconds(raw_ts)
        if ts_value is None:
            ts_value = time.time()
        dedupe_window_seconds = int(self._notification_policy_settings().get("dedupe_window_seconds", 120))
        bucket = int(ts_value // max(1, dedupe_window_seconds))
        return f"{notification_type}:{session_id}:time_window:{bucket}"

    def _persist_operator_notification(self, record: OperatorNotificationRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "operator_notification",
            record.id,
            {"status": "ok", "notification": record.to_dict()},
        )

    def _runtime_notification_click_url(
        self,
        notification_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        metadata = metadata or {}
        incident_id = str(metadata.get("incident_id", "") or "").strip()
        if incident_id:
            base = os.getenv("CLEANHOUSE_INCIDENT_RECEIPT_URL", "http://localhost:3333/incident-receipt").strip()
            if not base:
                base = "http://localhost:3333/incident-receipt"
            separator = "&" if "?" in base else "?"
            params = {"incident_id": incident_id, "notification_id": notification_id}
            for key in ("session_id", "domain_event_id", "receipt_id"):
                value = metadata.get(key)
                if value:
                    params[key] = str(value)
            return f"{base}{separator}{urlencode(params)}"
        base = os.getenv("CLEANHOUSE_DASHBOARD_URL", "http://localhost:3333/dashboard").strip()
        if not base:
            base = "http://localhost:3333/dashboard"
        separator = "&" if "?" in base else "?"
        params = {"notification_id": notification_id, "runtime_focus": "1"}
        for key in (
            "active_context_id",
            "prompt_id",
            "objective_id",
            "receipt_id",
            "runtime_evidence_ref",
            "runtime_transition_ref",
            "incident_id",
            "domain_event_id",
        ):
            value = (metadata or {}).get(key)
            if value:
                params[key] = str(value)
        return f"{base}{separator}{urlencode(params)}"

    def _env_truthy(self, name: str, default: str = "0") -> bool:
        return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

    def _allow_validation_dispatch(self) -> bool:
        return (
            self._env_truthy("CLEANHOUSE_NOTIFICATION_DEBUG_MODE")
            or self._env_truthy("CLEANHOUSE_NOTIFICATION_VALIDATION_MODE")
            or self._env_truthy("CLEANHOUSE_NOTIFICATION_PROVING_MODE")
        )

    def _is_validation_notification_source(self, record: OperatorNotificationRecord) -> bool:
        source = str(record.source or "").strip().lower()
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        return (
            source in {"probe", "notification_probe"}
            or bool(metadata.get("probe"))
        )

    def _coalesce_notification_event_id(
        self,
        *,
        notification_type: str,
        metadata: Dict[str, Any],
        session_id: str,
        source: str,
    ) -> str:
        for key in (
            "event_id",
            "domain_event_id",
            "alert_id",
            "prompt_id",
            "receipt_id",
            "approval_id",
            "rollback_id",
            "case_id",
            "runtime_transition_ref",
            "runtime_evidence_ref",
        ):
            value = str(metadata.get(key, "") or "").strip()
            if value:
                return value
        if notification_type in {"session_started", "session_ended"} and session_id:
            return f"session:{session_id}"
        if source == "runtime":
            return f"runtime:{notification_type}:{session_id or RUNTIME_GLOBAL_SESSION_ID}"
        return ""

    def _normalize_notification_metadata(
        self,
        *,
        notification_type: str,
        metadata: Dict[str, Any],
        session_id: str,
        source: str,
    ) -> Dict[str, Any]:
        normalized = copy.deepcopy(metadata)
        normalized_event_id = self._coalesce_notification_event_id(
            notification_type=notification_type,
            metadata=normalized,
            session_id=session_id,
            source=source,
        )
        if normalized_event_id and not str(normalized.get("event_id", "") or "").strip():
            normalized["event_id"] = normalized_event_id
        return normalized

    def _notification_dispatch_classification(self, record: OperatorNotificationRecord) -> str:
        if self._is_validation_notification_source(record) and not self._allow_validation_dispatch():
            return "validation_only"
        if record.notification_type not in PRODUCTION_OPERATOR_NOTIFICATION_TYPES:
            return "persist_only"
        return "production_operator"

    def _notification_backing_errors(self, record: OperatorNotificationRecord) -> list[str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        errors: list[str] = []
        if not str(metadata.get("event_id", "") or "").strip():
            errors.append("missing_event_id")
        if not str(metadata.get("click_url", "") or "").strip():
            errors.append("missing_click_url")
        if record.notification_type == "incident_action_required":
            if not str(metadata.get("incident_id", "") or "").strip():
                errors.append("missing_incident_id")
        return errors

    def _with_notification_dispatch_state(
        self,
        record: OperatorNotificationRecord,
        *,
        dispatch_class: str,
        suppressed_reason: str = "",
    ) -> OperatorNotificationRecord:
        metadata = copy.deepcopy(record.metadata if isinstance(record.metadata, dict) else {})
        metadata["dispatch_class"] = dispatch_class
        if suppressed_reason:
            metadata["dispatch_suppressed_reason"] = suppressed_reason
        else:
            metadata.pop("dispatch_suppressed_reason", None)
        return OperatorNotificationRecord(
            id=record.id,
            notification_type=record.notification_type,
            session_id=record.session_id,
            objective_id=record.objective_id,
            severity=record.severity,
            summary=record.summary,
            evidence_refs=record.evidence_refs,
            created_at=record.created_at,
            acknowledged=record.acknowledged,
            acknowledged_at=record.acknowledged_at,
            source=record.source,
            metadata=metadata,
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

    def _notification_policy_settings(self) -> Dict[str, Any]:
        policy = self._settings.get("notification_policy", {}) if isinstance(self._settings, dict) else {}
        def _int_default(raw: Any, default: int, minimum: int) -> int:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
            return max(minimum, value)
        hard_interrupt_types_raw = policy.get("hard_interrupt_types", DEFAULT_HARD_INTERRUPT_TYPES)
        hard_interrupt_types: list[str] = []
        if isinstance(hard_interrupt_types_raw, list):
            hard_interrupt_types = [str(item).strip() for item in hard_interrupt_types_raw if str(item).strip()]
        elif isinstance(hard_interrupt_types_raw, str) and hard_interrupt_types_raw.strip():
            hard_interrupt_types = [hard_interrupt_types_raw.strip()]
        if not hard_interrupt_types:
            hard_interrupt_types = list(DEFAULT_HARD_INTERRUPT_TYPES)
        cooldown_bypass_types_raw = policy.get("cooldown_bypass_types", [])
        cooldown_bypass_types: list[str] = []
        if isinstance(cooldown_bypass_types_raw, list):
            cooldown_bypass_types = [str(item).strip() for item in cooldown_bypass_types_raw if str(item).strip()]
        elif isinstance(cooldown_bypass_types_raw, str) and cooldown_bypass_types_raw.strip():
            cooldown_bypass_types = [cooldown_bypass_types_raw.strip()]
        raw_cooldowns = policy.get("cooldown_seconds_by_type", {})
        cooldown_by_type: Dict[str, int] = {}
        if isinstance(raw_cooldowns, dict):
            for key, value in raw_cooldowns.items():
                name = str(key).strip()
                if not name:
                    continue
                cooldown_by_type[name] = _int_default(value, int(NATIVE_NOTIFICATION_COOLDOWN_SECONDS), 1)
        return {
            "hard_interrupt_enabled": bool(policy.get("hard_interrupt_enabled", True)),
            "hard_interrupt_types": tuple(hard_interrupt_types),
            "hard_interrupt_reminder_seconds": _int_default(policy.get("hard_interrupt_reminder_seconds", 60), 60, 15),
            "visibility_risk_seconds": _int_default(policy.get("visibility_risk_seconds", 180), 180, 30),
            "critical_reminder_interval_seconds": _int_default(policy.get("critical_reminder_interval_seconds", 300), 300, 30),
            "dedupe_window_seconds": _int_default(policy.get("dedupe_window_seconds", 120), 120, 1),
            "fanout_all_backends": bool(policy.get("fanout_all_backends", True)),
            "backend_order": str(policy.get("backend_order", "osascript_first") or "osascript_first"),
            "codex_activity_native_enabled": bool(policy.get("codex_activity_native_enabled", False)),
            "cooldown_seconds_by_type": cooldown_by_type,
            "default_cooldown_seconds": _int_default(policy.get("default_cooldown_seconds", int(NATIVE_NOTIFICATION_COOLDOWN_SECONDS)), int(NATIVE_NOTIFICATION_COOLDOWN_SECONDS), 1),
            "burst_window_seconds": _int_default(policy.get("burst_window_seconds", NATIVE_NOTIFICATION_BURST_WINDOW_SECONDS), NATIVE_NOTIFICATION_BURST_WINDOW_SECONDS, 1),
            "burst_cap": _int_default(policy.get("burst_cap", NATIVE_NOTIFICATION_BURST_CAP), NATIVE_NOTIFICATION_BURST_CAP, 1),
            "max_native_reminders_per_notification": _int_default(policy.get("max_native_reminders_per_notification", 2), 2, 1),
            "cooldown_bypass_types": tuple(cooldown_bypass_types),
        }

    def _is_hard_interrupt_notification(self, record: OperatorNotificationRecord) -> bool:
        policy = self._notification_policy_settings()
        if not policy["hard_interrupt_enabled"]:
            return False
        if record.notification_type in set(policy["hard_interrupt_types"]):
            return True
        return record.severity == "critical"

    def _notification_reminder_interval_seconds(self, record: OperatorNotificationRecord) -> int:
        policy = self._notification_policy_settings()
        if self._is_hard_interrupt_notification(record):
            return int(policy["hard_interrupt_reminder_seconds"])
        return int(policy["critical_reminder_interval_seconds"])

    def _notification_visibility_state(
        self,
        *,
        record: OperatorNotificationRecord,
        metadata: Dict[str, Any],
    ) -> str:
        if record.acknowledged:
            return "visibility_confirmed"
        visibility = metadata.get("visibility", {}) if isinstance(metadata.get("visibility"), dict) else {}
        snoozed_until = str(visibility.get("snoozed_until", "") or "")
        snoozed_until_seconds = _timestamp_seconds(snoozed_until)
        if snoozed_until_seconds is not None and snoozed_until_seconds > time.time():
            return "snoozed"
        phases = metadata.get("delivery_phases", {}) if isinstance(metadata.get("delivery_phases"), dict) else {}
        backend_accepted_at = phases.get("backend_accepted")
        backend_accepted_seconds = _timestamp_seconds(backend_accepted_at)
        if backend_accepted_seconds is None:
            return "dispatch_attempted"
        policy = self._notification_policy_settings()
        visibility_risk_seconds = int(policy["visibility_risk_seconds"])
        if time.time() - backend_accepted_seconds >= visibility_risk_seconds:
            return "visibility_risk"
        return "backend_accepted"

    def _apply_visibility_metadata(
        self,
        *,
        record: OperatorNotificationRecord,
        metadata: Dict[str, Any],
        delivery_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        phases = metadata.get("delivery_phases", {}) if isinstance(metadata.get("delivery_phases"), dict) else {}
        if not phases.get("dispatch_attempted"):
            phases["dispatch_attempted"] = record.created_at or now
        if isinstance(delivery_result, dict):
            status = str(delivery_result.get("status", "") or "")
            if status in {"delivered", "queued"} and not phases.get("backend_accepted"):
                phases["backend_accepted"] = str(delivery_result.get("timestamp", now) or now)
        if record.acknowledged and not phases.get("operator_acknowledged"):
            phases["operator_acknowledged"] = record.acknowledged_at or now
        if record.acknowledged and not phases.get("visibility_confirmed"):
            phases["visibility_confirmed"] = record.acknowledged_at or now
        metadata["delivery_phases"] = {
            "dispatch_attempted": phases.get("dispatch_attempted"),
            "backend_accepted": phases.get("backend_accepted"),
            "operator_acknowledged": phases.get("operator_acknowledged"),
            "visibility_confirmed": phases.get("visibility_confirmed"),
        }
        visibility = metadata.get("visibility", {}) if isinstance(metadata.get("visibility"), dict) else {}
        reminder_seconds = self._notification_reminder_interval_seconds(record)
        visibility.setdefault("reminder_seconds", reminder_seconds)
        visibility.setdefault("risk_after_seconds", int(self._notification_policy_settings()["visibility_risk_seconds"]))
        visibility.setdefault("next_reminder_at", _iso_from_timestamp(time.time() + reminder_seconds))
        visibility_state = self._notification_visibility_state(record=record, metadata=metadata)
        if visibility_state not in NOTIFICATION_VISIBILITY_STATES:
            visibility_state = "dispatch_attempted"
        visibility["state"] = visibility_state
        metadata["visibility"] = visibility
        metadata["visibility_state"] = visibility_state
        return metadata

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
        runtime_presence: Optional[Dict[str, Any]] = None
        runtime_presence_ref = f"local://cleanhouse/runtime_presence/{RUNTIME_PRESENCE_ARTIFACT_ID}"
        local_refs = self._local_evidence_refs(evidence_refs)
        if notification_type in ESSENTIAL_OPERATOR_NOTIFICATION_TYPES:
            runtime_presence = self._runtime_presence_state()
            runtime_ref = str(runtime_presence.get("runtime_evidence_ref", "") or "").strip()
            if runtime_ref.startswith("local://cleanhouse/"):
                runtime_presence_ref = runtime_ref
            local_refs = self._local_evidence_refs([*local_refs, runtime_presence_ref])
        if not session_id or not local_refs:
            return None
        if severity not in OPERATOR_NOTIFICATION_SEVERITIES:
            severity = "info"
        record_metadata = copy.deepcopy(metadata or {})
        record_metadata.setdefault("session_id", session_id)
        record_metadata.setdefault("live_delivery_eligible", True)
        record_metadata.setdefault("live_delivery_started_at", self._live_notifications_started_at)
        record_metadata.setdefault("notification_boot_id", self._notification_boot_id)
        if notification_type in ESSENTIAL_OPERATOR_NOTIFICATION_TYPES:
            record_metadata.setdefault(
                "runtime_presence_ref",
                runtime_presence_ref,
            )
            record_metadata.setdefault(
                "runtime_state",
                str((runtime_presence or {}).get("runtime_state", "unknown") or "unknown"),
            )
            record_metadata.setdefault(
                "runtime_connection_state",
                str((runtime_presence or {}).get("connection_state", "unknown") or "unknown"),
            )
        incident_key = self._notification_incident_key(
            notification_type=notification_type,
            session_id=session_id,
            evidence_refs=local_refs,
            metadata=record_metadata,
        )
        existing_incident = self._operator_notification_by_incident_key(
            notification_type=notification_type,
            session_id=session_id,
            incident_key=incident_key,
        )
        if existing_incident is not None:
            return existing_incident
        stable_id = f"notification:{_fingerprint(incident_key, notification_type, session_id)}"
        existing = self._operator_notification_record(stable_id)
        if existing is not None:
            return existing
        now = _now_iso()
        record_metadata["incident_key"] = incident_key
        record_metadata.setdefault("visibility_proof", "transport_only")
        active_context_metadata = self._active_context_notification_metadata(session_id)
        for key, value in active_context_metadata.items():
            record_metadata.setdefault(key, value)
        if objective_id:
            record_metadata.setdefault("objective_id", objective_id)
        record_metadata = self._normalize_notification_metadata(
            notification_type=notification_type,
            metadata=record_metadata,
            session_id=session_id,
            source=source,
        )
        if session_id == RUNTIME_GLOBAL_SESSION_ID:
            record_metadata.setdefault("dashboard_target", "runtime")
            record_metadata.setdefault("click_url", self._runtime_notification_click_url(stable_id, record_metadata))
        else:
            record_metadata.setdefault("click_url", self._operator_notification_click_url(session_id, stable_id, record_metadata))
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
        record_metadata = self._apply_visibility_metadata(record=record, metadata=record_metadata, delivery_result=None)
        record = OperatorNotificationRecord(
            id=record.id,
            notification_type=record.notification_type,
            session_id=record.session_id,
            objective_id=record.objective_id,
            severity=record.severity,
            summary=record.summary,
            evidence_refs=record.evidence_refs,
            created_at=record.created_at,
            acknowledged=record.acknowledged,
            acknowledged_at=record.acknowledged_at,
            source=record.source,
            metadata=record_metadata,
        )
        with self._lock:
            self._operator_notifications[record.id] = record
        self._persist_operator_notification(record)
        record = self._dispatch_native_operator_notification(record)
        try:
            cleanhouse_events.insert_event_async(
                event_type=notification_type,
                path=f"/notifications/{record.id}",
                summary=f"{notification_type}: {summary[:160]}",
                session_id=session_id,
            )
        except Exception:
            pass
        if notification_type == "codex_response_observed":
            response_metadata = record.metadata if isinstance(record.metadata, dict) else {}
            response_source = str(record.source or "").strip().lower()
            response_prompt_id = self._resolve_open_codex_prompt_for_end(
                session_id=session_id,
                prompt_id=str(response_metadata.get("prompt_id") or "").strip(),
            )
            live_end_source = (
                response_source in {"tool_event", "command_observer"}
                or (response_source == "active_context" and bool(response_prompt_id))
            )
            if live_end_source:
                if not response_prompt_id:
                    return record
                response_ref = f"local://cleanhouse/operator_notification/{record.id}"
                end_refs = self._local_evidence_refs([*record.evidence_refs, response_ref])
                self._ensure_operator_notification(
                    notification_type="session_ended",
                    session_id=session_id,
                    objective_id=objective_id,
                    severity="info",
                    summary=f"agent turn completed: {summary[:140]}",
                    evidence_refs=end_refs,
                    source="codex_turn_end",
                    metadata={
                        "prompt_id": response_prompt_id,
                        "domain_event_id": record.id,
                        "session_status": "turn_completed",
                    },
                )
        if notification_type == "codex_prompt_sent":
            prompt_metadata = record.metadata if isinstance(record.metadata, dict) else {}
            prompt_source = str(prompt_metadata.get("source") or "").strip().lower()
            prompt_id = str(prompt_metadata.get("prompt_id") or "").strip()
            record_source = str(record.source or "").strip().lower()
            live_start_source = (
                record_source == "prompt"
                and prompt_source in {
                    "ui",
                    "command_observer",
                    "tool_event",
                    "session_api",
                    "api",
                    "workstation",
                    "active_context",
                    "codex_artifact",
                    "operator_pickup",
                }
                and bool(prompt_id)
            )
            if live_start_source:
                self._track_open_codex_prompt(session_id=session_id, prompt_id=prompt_id)
                prompt_ref = f"local://cleanhouse/operator_notification/{record.id}"
                start_refs = self._local_evidence_refs([*record.evidence_refs, prompt_ref])
                self._ensure_operator_notification(
                    notification_type="session_started",
                    session_id=session_id,
                    objective_id=objective_id,
                    severity="info",
                    summary=f"agent turn started: {summary[:140]}",
                    evidence_refs=start_refs,
                    source="codex_turn_start",
                    metadata={
                        "prompt_id": prompt_id,
                        "domain_event_id": record.id,
                        "session_status": "turn_started",
                    },
                )
        return record

    def _operator_notification_click_url(
        self,
        session_id: str,
        notification_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        metadata = metadata or {}
        incident_id = str(metadata.get("incident_id", "") or "").strip()
        if incident_id:
            base = os.getenv("CLEANHOUSE_INCIDENT_RECEIPT_URL", "http://localhost:3333/incident-receipt").strip()
            if not base:
                base = "http://localhost:3333/incident-receipt"
            separator = "&" if "?" in base else "?"
            params = {"session_id": session_id, "incident_id": incident_id, "notification_id": notification_id}
            for key in ("domain_event_id", "receipt_id"):
                value = metadata.get(key)
                if value:
                    params[key] = str(value)
            return f"{base}{separator}{urlencode(params)}"
        base = os.getenv("CLEANHOUSE_DASHBOARD_URL", "http://localhost:3333/dashboard").strip()
        if not base:
            base = "http://localhost:3333/dashboard"
        separator = "&" if "?" in base else "?"
        params = {"session_id": session_id, "notification_id": notification_id, "runtime_focus": "1"}
        for key in (
            "active_context_id",
            "prompt_id",
            "objective_id",
            "receipt_id",
            "runtime_evidence_ref",
            "runtime_transition_ref",
            "rollback_id",
            "incident_id",
            "domain_event_id",
        ):
            value = metadata.get(key)
            if value:
                params[key] = str(value)
        return f"{base}{separator}{urlencode(params)}"

    def _native_notification_cooldown_state(self) -> Dict[str, Any]:
        cooldowns: Dict[str, Any] = {}
        if isinstance(self._native_notification_cooldown_cache, dict):
            cached_entries = self._native_notification_cooldown_cache.get("entries")
            cached_bursts = self._native_notification_cooldown_cache.get("bursts")
            if isinstance(cached_entries, dict) or isinstance(cached_bursts, dict):
                cooldowns = self._native_notification_cooldown_cache
        if not cooldowns and self.persistence_enabled:
            artifact = PersistenceBackend.read("native_notification_cooldown", NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID)
            payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
            cooldowns = payload.get("cooldowns", payload) if isinstance(payload, dict) and payload else {}
        entries = cooldowns.get("entries", {}) if isinstance(cooldowns, dict) else {}
        if not isinstance(entries, dict):
            entries = {}
        bursts = cooldowns.get("bursts", {}) if isinstance(cooldowns, dict) else {}
        if not isinstance(bursts, dict):
            bursts = {}
        return {
            "id": NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID,
            "updated_at": str(cooldowns.get("updated_at", "") or ""),
            "entries": {str(key): value for key, value in entries.items() if isinstance(value, dict)},
            "bursts": {str(key): value for key, value in bursts.items() if isinstance(value, dict)},
        }

    def _persist_native_notification_cooldown_state(
        self,
        entries: Dict[str, Dict[str, Any]],
        bursts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._native_notification_cooldown_cache = {
            "id": NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID,
            "updated_at": _now_iso(),
            "entries": copy.deepcopy(entries),
            "bursts": copy.deepcopy(bursts or {}),
        }
        payload = {
            "status": "ok",
            "cooldowns": {
                "id": NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID,
                "updated_at": self._native_notification_cooldown_cache["updated_at"],
                "entries": self._native_notification_cooldown_cache["entries"],
                "bursts": self._native_notification_cooldown_cache["bursts"],
            },
        }
        if self.persistence_enabled:
            PersistenceBackend.persist("native_notification_cooldown", NATIVE_NOTIFICATION_COOLDOWN_ARTIFACT_ID, payload)

    def _native_notification_source_key(self, record: OperatorNotificationRecord) -> str:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        for key in (
            "runtime_transition_ref",
            "runtime_evidence_ref",
            "rollback_id",
            "receipt_id",
            "approval_id",
            "alert_id",
            "mutation_event_id",
            "mutation_path",
            "collector_name",
            "collector_status",
            "continuity_status",
            "source_ref",
        ):
            value = metadata.get(key)
            if value:
                return f"{key}:{value}"
        if record.evidence_refs:
            return "evidence:" + _fingerprint(*sorted(str(ref) for ref in record.evidence_refs)[:8])
        return "notification:" + _fingerprint(record.id)

    def _native_notification_cooldown_key(self, record: OperatorNotificationRecord) -> str:
        lane = "runtime-global" if record.session_id == RUNTIME_GLOBAL_SESSION_ID else f"session:{record.session_id}"
        source_key = self._native_notification_source_key(record)
        return f"{record.notification_type}:{lane}:{source_key}"

    def _should_bypass_native_cooldown(self, record: OperatorNotificationRecord) -> bool:
        policy = self._notification_policy_settings()
        return record.notification_type in set(policy.get("cooldown_bypass_types", ()))

    def _native_notification_in_cooldown(self, record: OperatorNotificationRecord) -> tuple[bool, str, str]:
        key = self._native_notification_cooldown_key(record)
        if self._should_bypass_native_cooldown(record):
            return False, key, ""
        state = self._native_notification_cooldown_state()
        entries = state.get("entries", {})
        if not isinstance(entries, dict):
            return False, key, ""
        entry = entries.get(key, {})
        if not isinstance(entry, dict):
            return False, key, ""
        expires_at = str(entry.get("expires_at", "") or "")
        expires_seconds = _timestamp_seconds(expires_at)
        if expires_seconds is None:
            return False, key, ""
        if time.time() >= expires_seconds:
            return False, key, ""
        return True, key, expires_at

    def _native_notification_burst_key(self, record: OperatorNotificationRecord) -> str:
        lane = "runtime-global" if record.session_id == RUNTIME_GLOBAL_SESSION_ID else f"session:{record.session_id}"
        return f"{record.notification_type}:{lane}"

    def _native_notification_in_burst_limit(self, record: OperatorNotificationRecord) -> tuple[bool, str, str]:
        if self._should_bypass_native_cooldown(record):
            return False, "", ""
        policy = self._notification_policy_settings()
        burst_window_seconds = int(policy["burst_window_seconds"])
        burst_cap = int(policy["burst_cap"])
        state = self._native_notification_cooldown_state()
        bursts = state.get("bursts", {})
        if not isinstance(bursts, dict):
            return False, "", ""
        key = self._native_notification_burst_key(record)
        entry = bursts.get(key, {})
        if not isinstance(entry, dict):
            return False, key, ""
        count = int(entry.get("count", 0) or 0)
        window_started = _timestamp_seconds(entry.get("window_started_at"))
        if window_started is None:
            return False, key, ""
        expires_seconds = window_started + burst_window_seconds
        if time.time() >= expires_seconds:
            return False, key, ""
        if count >= burst_cap:
            return True, key, _iso_from_timestamp(expires_seconds)
        return False, key, _iso_from_timestamp(expires_seconds)

    def _mark_native_notification_sent(self, record: OperatorNotificationRecord) -> None:
        state = self._native_notification_cooldown_state()
        entries = state.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        bursts = state.get("bursts", {})
        if not isinstance(bursts, dict):
            bursts = {}
        now = datetime.now()
        policy = self._notification_policy_settings()
        cooldown_seconds = int(policy["cooldown_seconds_by_type"].get(record.notification_type, policy["default_cooldown_seconds"]))
        burst_window_seconds = int(policy["burst_window_seconds"])
        expires_at = (now + timedelta(seconds=cooldown_seconds)).isoformat()
        key = self._native_notification_cooldown_key(record)
        entries[key] = {
            "notification_type": record.notification_type,
            "session_id": record.session_id,
            "source_key": self._native_notification_source_key(record),
            "last_sent_at": now.isoformat(),
            "expires_at": expires_at,
        }
        burst_key = self._native_notification_burst_key(record)
        burst_entry = bursts.get(burst_key, {}) if isinstance(bursts.get(burst_key), dict) else {}
        started_seconds = _timestamp_seconds(burst_entry.get("window_started_at"))
        if started_seconds is None or (time.time() - started_seconds) >= burst_window_seconds:
            bursts[burst_key] = {
                "window_started_at": now.isoformat(),
                "count": 1,
            }
        else:
            bursts[burst_key] = {
                "window_started_at": burst_entry.get("window_started_at"),
                "count": int(burst_entry.get("count", 0) or 0) + 1,
            }
        cutoff_seconds = time.time() - (NATIVE_NOTIFICATION_COOLDOWN_SECONDS * 24)
        pruned: Dict[str, Dict[str, Any]] = {}
        for raw_key, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            last_sent_at = _timestamp_seconds(entry.get("last_sent_at"))
            expires_seconds = _timestamp_seconds(entry.get("expires_at"))
            if expires_seconds is not None and expires_seconds < time.time() and (last_sent_at is None or last_sent_at < cutoff_seconds):
                continue
            pruned[str(raw_key)] = entry
        pruned_bursts: Dict[str, Dict[str, Any]] = {}
        for raw_key, entry in bursts.items():
            if not isinstance(entry, dict):
                continue
            started_seconds = _timestamp_seconds(entry.get("window_started_at"))
            if started_seconds is None:
                continue
            if (time.time() - started_seconds) > (burst_window_seconds * 4):
                continue
            pruned_bursts[str(raw_key)] = entry
        self._persist_native_notification_cooldown_state(pruned, pruned_bursts)

    def _dispatch_native_operator_notification(self, record: OperatorNotificationRecord) -> OperatorNotificationRecord:
        dispatch_class = self._notification_dispatch_classification(record)
        if dispatch_class != "production_operator":
            reason = (
                "validation_notification_dispatch_disabled"
                if dispatch_class == "validation_only"
                else "non_target_notification_persist_only"
            )
            gated_record = self._with_notification_dispatch_state(
                record,
                dispatch_class=dispatch_class,
                suppressed_reason=reason,
            )
            return self._persist_native_delivery_result(
                gated_record,
                self._native_delivery_result(
                    "skipped",
                    "notification_dispatch_gate",
                    reason=reason,
                ),
            )
        record = self._with_notification_dispatch_state(record, dispatch_class=dispatch_class)
        backing_errors = self._notification_backing_errors(record)
        if backing_errors:
            reason = "missing_runtime_backing:" + ",".join(backing_errors)
            gated_record = self._with_notification_dispatch_state(
                record,
                dispatch_class=dispatch_class,
                suppressed_reason=reason,
            )
            return self._persist_native_delivery_result(
                gated_record,
                self._native_delivery_result(
                    "skipped",
                    "notification_backing_gate",
                    reason=reason,
                ),
            )
        if record.notification_type not in OPERATOR_NATIVE_NOTIFICATION_TYPES:
            return record
        desktop_allowlist_only = os.getenv("CLEANHOUSE_NATIVE_DESKTOP_ALLOWLIST_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
        if desktop_allowlist_only and record.notification_type not in NATIVE_DESKTOP_DELIVERY_TYPES:
            return self._persist_native_delivery_result(
                record,
                self._native_delivery_result(
                    "skipped",
                    "native_noise_control_policy",
                    reason="native_notification_type_not_allowlisted",
                ),
            )
        existing_metadata = record.metadata if isinstance(record.metadata, dict) else {}
        existing_native_result = (
            existing_metadata.get("native_delivery_result", {})
            if isinstance(existing_metadata.get("native_delivery_result"), dict)
            else {}
        )
        live_only = os.getenv("CLEANHOUSE_NATIVE_LIVE_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
        if live_only:
            created_seconds = _timestamp_seconds(record.created_at)
            is_live_eligible = bool(existing_metadata.get("live_delivery_eligible", False))
            same_boot = str(existing_metadata.get("notification_boot_id", "") or "") == str(self._notification_boot_id)
            if (not is_live_eligible) or (not same_boot) or (created_seconds is None) or (created_seconds < self._live_notifications_started_seconds):
                if (
                    str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                    and str(existing_native_result.get("reason", "")).strip() == "live_only_not_current_runtime"
                ):
                    return record
                return self._persist_native_delivery_result(
                    record,
                    self._native_delivery_result(
                        "skipped",
                        "native_live_only",
                        reason="live_only_not_current_runtime",
                    ),
                )
            max_live_age_seconds_raw = os.getenv("CLEANHOUSE_NATIVE_LIVE_MAX_AGE_SECONDS", "10").strip()
            try:
                max_live_age_seconds = max(1, int(max_live_age_seconds_raw))
            except ValueError:
                max_live_age_seconds = 10
            if created_seconds is not None and (time.time() - created_seconds) > max_live_age_seconds:
                if (
                    str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                    and str(existing_native_result.get("reason", "")).strip() == "live_only_stale_event"
                ):
                    return record
                return self._persist_native_delivery_result(
                    record,
                    self._native_delivery_result(
                        "skipped",
                        "native_live_only",
                        reason="live_only_stale_event",
                    ),
                )
        if record.notification_type == "codex_prompt_sent":
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            prompt_id = str(metadata.get("prompt_id") or "").strip()
            if not prompt_id:
                if (
                    str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                    and str(existing_native_result.get("reason", "")).strip() == "codex_prompt_id_missing"
                ):
                    return record
                return self._persist_native_delivery_result(
                    record,
                    self._native_delivery_result(
                        "skipped",
                        "codex_prompt_validation",
                        reason="codex_prompt_id_missing",
                    ),
                )
        if record.notification_type in {"codex_prompt_sent", "codex_response_observed"}:
            policy = self._notification_policy_settings()
            env_raw = os.getenv("CLEANHOUSE_NATIVE_CODEX_ACTIVITY", "").strip().lower()
            if env_raw in {"1", "true", "yes", "on"}:
                codex_native_enabled = True
            elif env_raw in {"0", "false", "no", "off"}:
                codex_native_enabled = False
            else:
                codex_native_enabled = bool(policy.get("codex_activity_native_enabled", False))
            if not codex_native_enabled:
                if (
                    str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                    and str(existing_native_result.get("reason", "")).strip() == "codex_activity_native_disabled"
                ):
                    return record
                return self._persist_native_delivery_result(
                    record,
                    self._native_delivery_result(
                        "skipped",
                        "codex_activity_native_disabled",
                        reason="codex_activity_native_disabled",
                    ),
                )
        if record.notification_type in {"codex_prompt_sent", "codex_response_observed"}:
            metadata = record.metadata if isinstance(record.metadata, dict) else {}
            record_source = str(record.source or "").strip().lower()
            prompt_source = str(metadata.get("source") or "").strip().lower()
            active_context_source = str(metadata.get("active_context_source") or "").strip().lower()
            prompt_id = str(metadata.get("prompt_id") or "").strip()
            if record.notification_type == "codex_prompt_sent":
                if (prompt_source in {"active_context", "codex_artifact", "operator_pickup"} or record_source == "active_context") and not prompt_id:
                    if (
                        str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                        and str(existing_native_result.get("reason", "")).strip() == "codex_prompt_source_not_live"
                    ):
                        return record
                    return self._persist_native_delivery_result(
                        record,
                        self._native_delivery_result(
                            "skipped",
                            "codex_prompt_source_gate",
                            reason="codex_prompt_source_not_live",
                        ),
                    )
            if record.notification_type == "codex_response_observed":
                response_from_live_active_context = (record_source == "active_context")
                if record_source not in {"tool_event", "command_observer"} and not response_from_live_active_context:
                    if (
                        str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                        and str(existing_native_result.get("reason", "")).strip() == "codex_response_source_not_live"
                    ):
                        return record
                    return self._persist_native_delivery_result(
                        record,
                        self._native_delivery_result(
                            "skipped",
                            "codex_response_source_gate",
                            reason="codex_response_source_not_live",
                        ),
                    )
            if (
                record.notification_type == "codex_prompt_sent"
                and
                not prompt_id
                and (
                    record_source == "active_context"
                    or prompt_source in {"active_context", "codex_artifact", "operator_pickup"}
                    or bool(active_context_source)
                )
            ):
                if (
                    str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                    and str(existing_native_result.get("reason", "")).strip() == "passive_active_context_codex_signal"
                ):
                    return record
                return self._persist_native_delivery_result(
                    record,
                    self._native_delivery_result(
                        "skipped",
                        "active_context_passive_codex",
                        reason="passive_active_context_codex_signal",
                    ),
                )
        if os.getenv("CLEANHOUSE_NATIVE_NOTIFICATIONS", "0").strip().lower() in {"0", "false", "no", "off"}:
            if (
                str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                and str(existing_native_result.get("reason", "")).strip() == "CLEANHOUSE_NATIVE_NOTIFICATIONS disabled"
            ):
                return record
            return self._persist_native_delivery_result(
                record,
                self._native_delivery_result(
                    "skipped",
                    "native_notifications_disabled",
                    reason="CLEANHOUSE_NATIVE_NOTIFICATIONS disabled",
                ),
            )
        record = self._persist_native_delivery_result(
            record,
            {
                "status": "dispatch_attempted",
                "backend": "native_dispatch",
                "timestamp": _now_iso(),
                "phase": "dispatch_attempted",
            },
        )
        in_cooldown, cooldown_key, expires_at = self._native_notification_in_cooldown(record)
        if in_cooldown:
            if (
                str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                and str(existing_native_result.get("reason", "")).strip() == "cooldown_active"
                and str(existing_native_result.get("next_allowed_at", "")).strip() == str(expires_at).strip()
            ):
                return record
            return self._persist_native_delivery_result(
                record,
                {
                    "status": "skipped",
                    "backend": "native_notification_cooldown",
                    "reason": "cooldown_active",
                    "timestamp": _now_iso(),
                    "cooldown_key": cooldown_key,
                    "next_allowed_at": expires_at,
                },
            )
        in_burst_limit, burst_key, burst_expires_at = self._native_notification_in_burst_limit(record)
        if in_burst_limit:
            if (
                str(existing_native_result.get("status", "")).strip().lower() == "skipped"
                and str(existing_native_result.get("reason", "")).strip() == "burst_cap_active"
                and str(existing_native_result.get("next_allowed_at", "")).strip() == str(burst_expires_at).strip()
            ):
                return record
            return self._persist_native_delivery_result(
                record,
                {
                    "status": "skipped",
                    "backend": "native_notification_burst_cap",
                    "reason": "burst_cap_active",
                    "timestamp": _now_iso(),
                    "burst_key": burst_key,
                    "next_allowed_at": burst_expires_at,
                },
            )
        if NotificationManager is None:
            return self._persist_native_delivery_failure(
                record,
                self._native_delivery_result(
                    "failed",
                    "notification_manager",
                    reason="NotificationManager unavailable",
                ),
            )
        try:
            if self._native_notification_manager is None:
                self._native_notification_manager = NotificationManager()
            click_url = str(record.metadata.get("click_url") or self._operator_notification_click_url(record.session_id, record.id))
            title = f"CleanHouse: {record.notification_type}"
            policy = self._notification_policy_settings()
            backend_order = str(policy.get("backend_order", "terminal_notifier_first"))
            preferred_backend = "terminal-notifier" if click_url else ("osascript" if backend_order == "osascript_first" else "terminal-notifier")
            fanout_all_backends = bool(policy.get("fanout_all_backends", True)) and self._is_hard_interrupt_notification(record)
            metadata = {
                "notification_id": record.id,
                "notification_type": record.notification_type,
                "session_id": record.session_id,
                "objective_id": record.objective_id,
                "evidence_refs": list(record.evidence_refs),
            }
            try:
                delivery_result = self._native_notification_manager.send_notification(
                    title,
                    record.summary,
                    level=record.severity,
                    metadata=metadata,
                    click_url=click_url,
                    wait_for_delivery=True,
                    preferred_backend=preferred_backend,
                    fanout_all_backends=fanout_all_backends,
                )
            except TypeError as exc:
                if "wait_for_delivery" in str(exc):
                    delivery_result = self._native_notification_manager.send_notification(
                        title,
                        record.summary,
                        level=record.severity,
                        metadata=metadata,
                        click_url=click_url,
                    )
                else:
                    delivery_result = self._native_notification_manager.send_notification(
                        title,
                        record.summary,
                        level=record.severity,
                        metadata=metadata,
                        click_url=click_url,
                        wait_for_delivery=True,
                    )
            normalized = self._normalize_native_delivery_result(
                delivery_result,
                fallback_backend=self._native_notification_manager.__class__.__name__,
            )
            if normalized.get("status") == "failed":
                return self._persist_native_delivery_failure(record, normalized)
            if normalized.get("status") == "delivered":
                self._mark_native_notification_sent(record)
            return self._persist_native_delivery_result(record, normalized)
        except Exception as exc:
            return self._persist_native_delivery_failure(
                record,
                self._native_delivery_result(
                    "failed",
                    "notification_manager",
                    reason="dispatch_exception",
                    error=exc,
                ),
            )

    def _native_delivery_result(
        self,
        status: str,
        backend: str,
        *,
        reason: Optional[str] = None,
        error: Optional[BaseException] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": str(status),
            "backend": str(backend),
            "timestamp": _now_iso(),
        }
        if reason:
            result["reason"] = str(reason)[:200]
        if error is not None:
            result["error_type"] = error.__class__.__name__
            result["error_detail"] = str(error)[:300] or error.__class__.__name__
        return result

    def _normalize_native_delivery_result(self, raw: Any, *, fallback_backend: str) -> Dict[str, Any]:
        if isinstance(raw, dict):
            result = copy.deepcopy(raw)
        else:
            result = self._native_delivery_result(
                "queued",
                fallback_backend,
                reason="manager did not return delivery evidence",
            )
        status = str(result.get("status", "queued")).strip().lower() or "queued"
        if status not in {"dispatch_attempted", "delivered", "queued", "failed", "skipped", "unknown"}:
            status = "failed" if status in {"error", "exception"} else "queued"
        result["status"] = status
        result.setdefault("backend", fallback_backend)
        result.setdefault("timestamp", _now_iso())
        result.setdefault("attempts", [])
        result.setdefault("reason", "")
        return result

    def _persist_native_delivery_result(
        self,
        record: OperatorNotificationRecord,
        delivery_result: Dict[str, Any],
    ) -> OperatorNotificationRecord:
        metadata = copy.deepcopy(record.metadata)
        result = copy.deepcopy(delivery_result)
        if str(result.get("status", "")) in {"delivered", "queued"}:
            result.setdefault("phase", "backend_accepted")
        elif str(result.get("status", "")) == "dispatch_attempted":
            result.setdefault("phase", "dispatch_attempted")
        metadata["native_delivery_result"] = result
        metadata.setdefault("visibility_proof", "operator_confirmed" if record.acknowledged else "transport_only")
        metadata["native_delivery"] = {
            "status": result.get("status", "unknown"),
            "channel": result.get("backend"),
            "backend": result.get("backend"),
            "attempt_count": max(1, len(result.get("attempts", []) or [])),
            "updated_at": result.get("timestamp", _now_iso()),
            "reason": result.get("reason"),
            "runtime_recovery_artifact_id": result.get("runtime_recovery_artifact_id"),
            "runtime_recovery_evidence_ref": result.get("runtime_recovery_evidence_ref"),
        }
        history = metadata.get("native_delivery_results", [])
        if not isinstance(history, list):
            history = []
        history.append(result)
        metadata["native_delivery_results"] = history[-10:]
        escalation_history = metadata.get("escalation_history", [])
        if not isinstance(escalation_history, list):
            escalation_history = []
        escalation_history.append({
            "timestamp": result.get("timestamp", _now_iso()),
            "status": result.get("status", "unknown"),
            "backend": result.get("backend", ""),
            "phase": result.get("phase", ""),
            "reason": result.get("reason", ""),
            "attempts": copy.deepcopy(result.get("attempts", [])) if isinstance(result.get("attempts"), list) else [],
        })
        metadata["escalation_history"] = escalation_history[-20:]
        updated = OperatorNotificationRecord(
            id=record.id,
            notification_type=record.notification_type,
            session_id=record.session_id,
            objective_id=record.objective_id,
            severity=record.severity,
            summary=record.summary,
            evidence_refs=record.evidence_refs,
            created_at=record.created_at,
            acknowledged=record.acknowledged,
            acknowledged_at=record.acknowledged_at,
            source=record.source,
            metadata=metadata,
        )
        metadata = self._apply_visibility_metadata(record=updated, metadata=metadata, delivery_result=result)
        updated = OperatorNotificationRecord(
            id=updated.id,
            notification_type=updated.notification_type,
            session_id=updated.session_id,
            objective_id=updated.objective_id,
            severity=updated.severity,
            summary=updated.summary,
            evidence_refs=updated.evidence_refs,
            created_at=updated.created_at,
            acknowledged=updated.acknowledged,
            acknowledged_at=updated.acknowledged_at,
            source=updated.source,
            metadata=metadata,
        )
        with self._lock:
            self._operator_notifications[updated.id] = updated
        self._persist_operator_notification(updated)
        if self.persistence_enabled:
            delivery_id = f"notification_delivery:{_fingerprint(record.id, result.get('status', ''), result.get('timestamp', ''))}"
            PersistenceBackend.persist(
                "notification_delivery",
                delivery_id,
                {
                    "status": "ok",
                    "delivery": {
                        "id": delivery_id,
                        "notification_id": record.id,
                        "notification_type": record.notification_type,
                        "session_id": record.session_id,
                        "severity": record.severity,
                        "timestamp": result.get("timestamp", _now_iso()),
                        "phase": result.get("phase", ""),
                        "phases": copy.deepcopy(updated.metadata.get("delivery_phases", {})),
                        "visibility_state": updated.metadata.get("visibility_state", "dispatch_attempted"),
                        "delivery_result": result,
                        "delivery_attempts": copy.deepcopy(result.get("attempts", [])) if isinstance(result.get("attempts"), list) else [],
                        "escalation_history": copy.deepcopy(updated.metadata.get("escalation_history", [])),
                        "evidence_refs": list(updated.evidence_refs),
                    },
                },
            )
        return updated

    def _persist_native_delivery_failure(
        self,
        record: OperatorNotificationRecord,
        delivery_result: Dict[str, Any],
    ) -> OperatorNotificationRecord:
        result = copy.deepcopy(delivery_result)
        recovery = self._persist_runtime_recovery_artifact(record, result)
        if recovery.get("status") == "ok":
            result["runtime_recovery_artifact_id"] = recovery["artifact"]["id"]
            result["runtime_recovery_evidence_ref"] = recovery["artifact"]["evidence_ref"]
        else:
            result["runtime_recovery_persistence_warning"] = recovery.get("message", "runtime recovery artifact write failed")
        return self._persist_native_delivery_result(record, result)

    def _persist_runtime_recovery_artifact(
        self,
        record: OperatorNotificationRecord,
        delivery_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        recovery_id = f"runtime_recovery:{_fingerprint('native_notification_delivery', record.id)}"
        evidence_ref = f"local://cleanhouse/runtime_recovery/{recovery_id}"
        notification_ref = f"local://cleanhouse/operator_notification/{record.id}"
        evidence_refs = list(self._local_evidence_refs([*record.evidence_refs, notification_ref]))
        created_at = _now_iso()
        artifact = {
            "id": recovery_id,
            "status": "failed",
            "timestamp": created_at,
            "action": "native_notification_delivery",
            "failure_type": "native_notification_delivery",
            "created_at": created_at,
            "session_id": record.session_id,
            "objective_id": record.objective_id,
            "notification_id": record.id,
            "notification_type": record.notification_type,
            "severity": record.severity,
            "summary": record.summary,
            "delivery_result": copy.deepcopy(delivery_result),
            "evidence_ref": evidence_ref,
            "evidence_refs": evidence_refs,
            "reason_codes": ["native_notification_delivery_failed"],
            "final_state": {
                "status": "failed",
                "reason": delivery_result.get("reason", "native notification delivery failed"),
                "backend": delivery_result.get("backend"),
            },
            "integrity": {
                "algorithm": "sha-256",
                "evidence_ref": evidence_ref,
                "evidence_refs": [*evidence_refs, evidence_ref],
            },
            "metadata": {
                "source": "native_operator_notification",
                "click_url": record.metadata.get("click_url"),
            },
        }
        artifact["integrity"]["root_hash"] = _canonical_json_hash({
            key: value for key, value in artifact.items() if key != "integrity"
        })
        if not self.persistence_enabled:
            return {"status": "skipped", "message": "persistence disabled", "artifact": artifact}
        persisted = PersistenceBackend.persist("runtime_recovery", recovery_id, artifact)
        if persisted.get("status") != "ok":
            return {"status": "error", "message": persisted.get("message", "runtime recovery artifact write failed"), "artifact": artifact}
        _insert_runtime_event(
            event_type="runtime_recovery_failure",
            path=f"/runtime-recovery/{recovery_id}",
            summary=f"runtime_recovery_failure: native notification delivery failed for {record.id}",
            session_id=record.session_id,
            objective_id=record.objective_id,
            source_surface="native_operator_notification",
            actor_type="runtime",
            evidence_level="observed",
            observed_vs_expected={
                "status": "failed",
                "details": delivery_result.get("reason", "native notification delivery failed"),
            },
            collector_status="failure",
            scope_relation="recovery_state",
            evidence_refs=[*evidence_refs, evidence_ref],
            raw_evidence_ref=evidence_ref,
            data=artifact,
        )
        return {"status": "ok", "artifact": artifact, "path": persisted.get("path")}

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
        for workflow in receipt.get("intervention_workflows", []):
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("workflow_id", "") or "")
            if workflow_id:
                refs.append(f"local://cleanhouse/intervention-workflow/{workflow_id}")
            refs.extend(str(ref) for ref in workflow.get("evidence_refs", []))
        custody = receipt.get("chain_of_custody", {}) if isinstance(receipt.get("chain_of_custody"), dict) else {}
        custody_id = str(custody.get("custody_id", "") or "")
        if custody_id:
            refs.append(f"local://cleanhouse/chain-of-custody/{custody_id}")
        for hop in custody.get("hops", []):
            if not isinstance(hop, dict):
                continue
            ref = str(hop.get("ref", "") or "")
            if ref:
                refs.append(ref)
        scope_enforcement = (
            receipt.get("scope_enforcement", {})
            if isinstance(receipt.get("scope_enforcement"), dict)
            else {}
        )
        for mediation_event in scope_enforcement.get("mediation_events", []):
            if not isinstance(mediation_event, dict):
                continue
            refs.append(str(mediation_event.get("event_ref", "") or ""))
            refs.extend(str(ref) for ref in mediation_event.get("evidence_refs", []))
        for deviation in scope_enforcement.get("deviation_records", []):
            if not isinstance(deviation, dict):
                continue
            deviation_id = str(deviation.get("id", "") or "")
            if deviation_id:
                refs.append(f"local://cleanhouse/scope-deviation/{deviation_id}")
            refs.extend(str(ref) for ref in deviation.get("evidence_refs", []))
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
            if summary.get("classification") == "outside_declared_scope" and float(summary.get("scope_weight") or 0.0) >= 1.0:
                scope_analysis = summary.get("scope_analysis", {}) if isinstance(summary.get("scope_analysis"), dict) else {}
                path_clusters = scope_analysis.get("path_clusters", []) if isinstance(scope_analysis.get("path_clusters"), list) else []
                affected_paths = []
                for cluster in path_clusters[:6]:
                    if isinstance(cluster, dict) and cluster.get("cluster"):
                        affected_paths.append(str(cluster.get("cluster")))
                self._ensure_operator_notification(
                    notification_type="excessive_traversal",
                    session_id=session_id,
                    objective_id=objective_id,
                    severity="critical",
                    summary=str(summary.get("summary", "excessive traversal detected")),
                    evidence_refs=summary.get("evidence_refs", []),
                    source="workstation",
                    metadata={
                        "receipt_id": summary.get("receipt_id", ""),
                        "traversal_type": "out_of_scope_file_traversal",
                        "scope_relation": summary.get("classification", "outside_declared_scope"),
                        "affected_paths": affected_paths,
                        "scope_weight": summary.get("scope_weight"),
                    },
                )
        for alert in alerts:
            if alert.get("alert_type") != "scope_expansion":
                continue
            alert_description = str(alert.get("description", "scope drift detected"))
            self._ensure_operator_notification(
                notification_type="scope_drift_detected",
                session_id=session_id,
                objective_id=objective_id,
                severity="warning" if alert.get("severity") != "high" else "critical",
                summary=alert_description,
                evidence_refs=alert.get("evidence_refs", []),
                source="alert",
                metadata={"alert_id": alert.get("id", ""), "alert_type": alert.get("alert_type", "")},
            )
            if "out-of-scope file changes" in alert_description.lower() or alert.get("severity") == "high":
                self._ensure_operator_notification(
                    notification_type="excessive_traversal",
                    session_id=session_id,
                    objective_id=objective_id,
                    severity="critical",
                    summary=str(alert.get("description", "excessive traversal detected")),
                    evidence_refs=alert.get("evidence_refs", []),
                    source="alert",
                    metadata={
                        "alert_id": alert.get("id", ""),
                        "alert_type": alert.get("alert_type", ""),
                        "traversal_type": "scope_expansion",
                        "scope_relation": "outside_declared_scope",
                        "affected_paths": [],
                    },
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
        status = str(provenance.get("status") or "")
        pickup_status = str(provenance.get("pickup_channel_status") or "")
        if status != "degraded" and pickup_status != "degraded":
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
                "continuity_status": status,
                "pickup_channel_status": pickup_status,
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
            scope_enforcement = (
                receipt.get("scope_enforcement", {})
                if isinstance(receipt.get("scope_enforcement"), dict)
                else {}
            )
            deviation_records = (
                scope_enforcement.get("deviation_records", [])
                if isinstance(scope_enforcement.get("deviation_records"), list)
                else []
            )
            if deviation_records:
                summaries.append({
                    "id": f"summary:{_fingerprint(receipt_id, 'scope_enforcement', str(len(deviation_records)))}",
                    "summary_type": "scope_enforcement",
                    "session_id": session_id,
                    "receipt_id": receipt_id,
                    "severity": "critical",
                    "summary": (
                        f"Receipt {receipt_id} produced {len(deviation_records)} enforceable scope deviation record(s) "
                        "for mediated authorization review."
                    ),
                    "classification": "deviation",
                    "scope_weight": scope_enforcement.get("scope_weight", scope_weight),
                    "declared_scope": scope_enforcement.get("declared_scope", declared_scope),
                    "path_clusters": analysis.get("path_clusters", []),
                    "deviation_records": copy.deepcopy(deviation_records),
                    "evidence_refs": list(self._local_evidence_refs([
                        *refs,
                        *[
                            ref
                            for record in deviation_records
                            if isinstance(record, dict)
                            for ref in (record.get("evidence_refs", []) if isinstance(record.get("evidence_refs"), list) else [])
                        ],
                    ])),
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

    def _critical_mutation_changes(self, mutation: Dict[str, Any]) -> list[Dict[str, str]]:
        source = str(mutation.get("source", "") or "")
        if source in {"diff", "timeline"}:
            raw_changes = mutation.get("changes", [])
            if not isinstance(raw_changes, list):
                return []
            changes: list[Dict[str, str]] = []
            for entry in raw_changes:
                if not isinstance(entry, dict):
                    continue
                path = str(entry.get("path", "") or "")
                change_type = str(entry.get("change_type", "") or "")
                if path and change_type:
                    changes.append({"path": path, "change_type": change_type})
            return changes
        if source == "event":
            path = str(mutation.get("path", "") or "")
            change_type = str(mutation.get("event_type", "") or "")
            if path and change_type:
                return [{"path": path, "change_type": change_type}]
        return []

    def _ensure_critical_filesystem_mutation_notifications(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        declared_scope: str,
        mutations: Sequence[Dict[str, Any]],
    ) -> None:
        for mutation in mutations:
            mutation_id = str(mutation.get("id", "") or "")
            mutation_source = str(mutation.get("source", "") or "")
            base_refs = self._local_evidence_refs(mutation.get("evidence_refs", []))
            for change in self._critical_mutation_changes(mutation):
                path = str(change.get("path", "") or "")
                change_type = str(change.get("change_type", "") or "")
                if change_type != "deleted":
                    continue
                scope_relation = (
                    self._scope_relation_for_path(path, declared_scope)
                    if declared_scope
                    else "unknown"
                )
                if scope_relation not in {"out_of_scope", "unknown"}:
                    continue
                mutation_ref = (
                    "local://cleanhouse/mutation/"
                    + _fingerprint(session_id, mutation_source, mutation_id, path, change_type)
                )
                summary = f"critical filesystem mutation requires review: {change_type} {path}"
                self._ensure_operator_notification(
                    notification_type="critical_filesystem_mutation",
                    session_id=session_id,
                    objective_id=objective_id,
                    severity="critical",
                    summary=summary[:220],
                    evidence_refs=[*base_refs, mutation_ref],
                    source="workstation_mutation",
                    metadata={
                        "mutation_event_id": mutation_id,
                        "mutation_source": mutation_source,
                        "mutation_path": path,
                        "mutation_change_type": change_type,
                        "scope_relation": scope_relation,
                        "declared_scope": declared_scope,
                        "source_ref": mutation_ref,
                    },
                )

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
        metadata = copy.deepcopy(metadata)
        approval_channel = str(
            data.get("execution_channel")
            or metadata.get("approval_channel")
            or ("api" if source in {"api", "mediator", "approval_policy"} else "human")
        ).strip().lower()
        metadata["approval_channel"] = approval_channel
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
        proof = self._approval_mediation_proof(item)
        with self._lock:
            self._approval_queue[item.id] = item
        approval_ref = f"local://cleanhouse/approval-queue/{approval_id}"
        proof_ref = f"local://cleanhouse/approval-mediation-proof/{approval_id}"
        event_evidence_refs = sorted(set((*evidence_refs, approval_ref, proof_ref)))
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
            evidence_refs=event_evidence_refs,
            raw_evidence_ref=approval_ref,
            data={**item.to_dict(), "mediation_proof": proof},
        )
        result = {"status": "ok", "approval": {**item.to_dict(), "mediation_proof": proof}}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("approval", item.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        self._persist_approval_mediation_proof(item, proof)
        notification_metadata = {"approval_id": item.id}
        if item.prompt_id:
            notification_metadata["prompt_id"] = item.prompt_id
        if item.objective_id:
            notification_metadata["objective_id"] = item.objective_id
        if metadata.get("receipt_id"):
            notification_metadata["receipt_id"] = str(metadata.get("receipt_id"))
        notification = self._ensure_operator_notification(
            notification_type="approval_required",
            session_id=session_id,
            objective_id=objective_id,
            severity="warning",
            summary=reason or requested_action,
            evidence_refs=evidence_refs,
            source="approval_queue",
            metadata=notification_metadata,
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
            records = [self._approval_dict_with_mediation_proof(r.to_dict()) for r in self._approval_queue.values()]
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
                    records.append(self._approval_dict_with_mediation_proof(approval))
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
        metadata = copy.deepcopy(existing.metadata)
        metadata["decision_channel"] = "human"
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
            metadata=metadata,
        )
        proof = self._approval_mediation_proof(updated)
        with self._lock:
            self._approval_queue[approval_id] = updated
        approval_ref = f"local://cleanhouse/approval-queue/{approval_id}"
        proof_ref = f"local://cleanhouse/approval-mediation-proof/{approval_id}"
        event_evidence_refs = sorted(set((*existing.evidence_refs, approval_ref, proof_ref)))
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
            evidence_refs=event_evidence_refs,
            raw_evidence_ref=approval_ref,
            data={**updated.to_dict(), "mediation_proof": proof},
        )
        result = {"status": "ok", "approval": {**updated.to_dict(), "mediation_proof": proof}}
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("approval", updated.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        self._persist_approval_mediation_proof(updated, proof)
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

    def _approval_mediation_proof(self, approval: ApprovalQueueItem) -> Dict[str, Any]:
        history_records: list[Dict[str, Any]] = []
        for entry in approval.history:
            history_records.append({
                "id": entry.id,
                "action": entry.action,
                "status": entry.status,
                "previous_status": entry.previous_status,
                "reviewer": entry.reviewer,
                "note": entry.note,
                "receipt_id": entry.receipt_id,
                "timestamp": entry.timestamp,
                "evidence_refs": sorted(set(entry.evidence_refs)),
            })
        core = {
            "schema": "cleanhouse.approval_mediation_proof.v1",
            "approval_id": approval.id,
            "session_id": approval.session_id,
            "status": approval.status,
            "requested_action": approval.requested_action,
            "reason": approval.reason,
            "prompt_id": approval.prompt_id,
            "objective_id": approval.objective_id,
            "source": approval.source,
            "route_ownership": "review_state_only",
            "evidence_refs": sorted(set(approval.evidence_refs)),
            "history": history_records,
            "history_count": len(history_records),
        }
        proof_hash = _stable_json_hash(core)
        proof_id = f"approval_proof:{_fingerprint(approval.id, proof_hash)}"
        return {
            **core,
            "proof_id": proof_id,
            "proof_hash": proof_hash,
        }

    def _persist_approval_mediation_proof(
        self,
        approval: ApprovalQueueItem,
        proof: Dict[str, Any],
    ) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist(
            "approval_mediation_proof",
            approval.id,
            {
                "status": "ok",
                "approval_id": approval.id,
                "session_id": approval.session_id,
                "proof": copy.deepcopy(proof),
            },
        )

    def _approval_dict_with_mediation_proof(self, approval: Dict[str, Any]) -> Dict[str, Any]:
        item = self._approval_item_from_dict(approval)
        normalized = item.to_dict()
        normalized["mediation_proof"] = self._approval_mediation_proof(item)
        return normalized

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
        objective_id = self._objective_id_for_session(session_id or "") or os.getenv("CLEANHOUSE_OBJECTIVE_ID") or None
        event_session_id = session_id or os.getenv("CLEANHOUSE_SESSION_ID", "default-session")
        for change in changes:
            change_ref = f"local://cleanhouse/diff/{diff.id}/change/{_fingerprint(change.change_type, change.path)}"
            _insert_runtime_event(
                event_type=change.change_type,
                path=change.path,
                summary=f"file_mutation: {change.change_type} {change.path}",
                session_id=event_session_id,
                objective_id=objective_id,
                source_surface="snapshot_diff",
                actor_type="filesystem",
                evidence_level="observed",
                observed_vs_expected={
                    "status": "observed",
                    "details": f"snapshot diff recorded {change.change_type} change",
                },
                collector_status="ok",
                scope_relation="unknown",
                evidence_refs=[f"local://cleanhouse/diff/{diff.id}", change_ref],
                raw_evidence_ref=change_ref,
                data={
                    "diff_id": diff.id,
                    "change_type": change.change_type,
                    "path": change.path,
                    "before_hash": change.before_hash,
                    "after_hash": change.after_hash,
                },
            )
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
        resolved_actor_id = self._resolve_actor_id_from_payload(
            actor_type=actor_type,
            source_surface=source_surface,
            payload=payload,
        )
        actor_status = "observed"
        if not str(actor_type or "").strip():
            actor_status = "unknown"
        elif not resolved_actor_id:
            actor_status = "inferred"
        actor_attribution = self._actor_attribution_entry(
            actor_type=actor_type or "unknown",
            actor_id=resolved_actor_id,
            status=actor_status,
            basis="canonical_event_payload",
            evidence_refs=evidence_refs,
        )
        execution_channel = self._resolve_execution_channel(
            actor_type=actor_type,
            source_surface=source_surface,
            payload=payload,
        )
        channel_attribution = self._channel_attribution_entry(
            channel=execution_channel,
            status="observed" if execution_channel != "unknown" else "unknown",
            basis="canonical_event_payload",
            evidence_refs=evidence_refs,
        )
        trust_classification, trust_basis, trust_docs = self._resolve_trust_classification(
            evidence_level=evidence_level,
            collector_status=collector_status,
            observed_vs_expected=observed_vs_expected,
            evidence_refs=evidence_refs,
            payload=payload,
        )
        trust_attribution = self._trust_attribution_entry(
            trust_classification=trust_classification,
            basis=trust_basis,
            evidence_refs=evidence_refs,
            documentation=trust_docs,
        )
        payload.update({
            "session_id": session_id,
            "objective_id": objective_id,
            "source_surface": source_surface,
            "actor_type": actor_type,
            "actor_id": resolved_actor_id,
            "actor": actor_attribution,
            "actor_attribution_hash": actor_attribution.get("attribution_hash", ""),
            "execution_channel": execution_channel,
            "channel": channel_attribution,
            "channel_attribution_hash": channel_attribution.get("attribution_hash", ""),
            "trust_classification": trust_classification,
            "trust": trust_attribution,
            "trust_attribution_hash": trust_attribution.get("attribution_hash", ""),
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
                                    "mediation_proof": self._approval_mediation_proof(approval),
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
                                "mediation_proof": self._approval_mediation_proof(approval),
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

        classification_result = self.classify(session_id=session_id)
        if classification_result.get("status") == "error":
            return classification_result

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
            collector_status = str(surface.get("collector_status") or "").strip()
            if collector_status in {None, "", "ok"}:
                continue
            if collector_status == "dependency_missing":
                label = "unsupported"
            elif collector_status == "permission_denied":
                label = "permission_blocked"
            elif collector_status in {"inactive", "no_baseline"}:
                label = "partial"
            elif collector_status == "unknown":
                label = "unknown"
            else:
                label = "collector_gap"
            gaps.append({
                "source": name,
                "event_id": f"collector:{name}",
                "label": label,
                "description": f"{name} collector status: {collector_status}",
                "collector_status": collector_status,
                "evidence_refs": [f"local://cleanhouse/collector/{name}"],
            })
        return gaps

    @staticmethod
    def _timeline_command_signature(entry: Dict[str, Any]) -> str:
        data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
        args = data.get("args")
        if isinstance(args, list):
            normalized_args = [str(arg).strip() for arg in args if str(arg).strip()]
            if normalized_args:
                return " ".join(normalized_args)
        command = str(data.get("command", "")).strip()
        return command

    def _unsupported_shell_action_gaps(self, timeline_entries: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
        owned_signatures: set[str] = set()
        tool_action_entries: list[Dict[str, Any]] = []
        for entry in timeline_entries:
            if not isinstance(entry, dict):
                continue
            source_surface = str(entry.get("source_surface") or "")
            event_type = str(entry.get("event_type") or "")
            signature = self._timeline_command_signature(entry)
            if source_surface == "command_observer" and event_type == "command" and signature:
                owned_signatures.add(signature)
            if source_surface == "tool_event" and event_type == "action":
                tool_action_entries.append(entry)

        grouped: Dict[str, Dict[str, Any]] = {}
        for entry in tool_action_entries:
            signature = self._timeline_command_signature(entry)
            if signature and signature in owned_signatures:
                continue
            data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
            evidence_refs: list[str] = []
            for source_refs in (entry.get("evidence_refs"), data.get("evidence_refs")):
                if not isinstance(source_refs, list):
                    continue
                for ref in source_refs:
                    if isinstance(ref, str) and ref:
                        evidence_refs.append(ref)
            deduped_refs = sorted({ref for ref in evidence_refs})
            descriptor = signature or str(data.get("command", "")).strip() or str(entry.get("label", "")).strip() or "unknown action"
            key = descriptor
            if key not in grouped:
                grouped[key] = {
                    "session_id": str(entry.get("session_id") or ""),
                    "descriptor": descriptor,
                    "refs": set(deduped_refs),
                }
            else:
                grouped[key]["refs"].update(deduped_refs)

        gaps: list[Dict[str, Any]] = []
        for group in grouped.values():
            event_id = f"unsupported-shell:{_fingerprint(group['session_id'], group['descriptor'])}"
            gaps.append({
                "source": "command_observer",
                "event_id": event_id,
                "label": "unknown",
                "description": f"unsupported-shell action observed outside owned command observer: {group['descriptor']}",
                "collector_status": "unsupported_shell_action",
                "evidence_refs": sorted(group["refs"]),
            })
        return gaps

    def _collector_failure_severity(self, collector_status: str) -> str:
        normalized = str(collector_status or "").strip().lower()
        if normalized in {"failure", "error"}:
            return "critical"
        return "warning"

    def _ensure_collector_failure_notifications(self, collector_manifest: Dict[str, Any]) -> None:
        surfaces = collector_manifest.get("surfaces", {}) if isinstance(collector_manifest, dict) else {}
        if not isinstance(surfaces, dict):
            return
        for name, surface in surfaces.items():
            if not isinstance(surface, dict):
                continue
            collector_status = str(surface.get("collector_status", "") or "")
            if collector_status in {"", "ok"}:
                continue
            evidence_ref = f"local://cleanhouse/collector/{name}/{collector_status}"
            self._ensure_operator_notification(
                notification_type="collector_failure",
                session_id=RUNTIME_GLOBAL_SESSION_ID,
                objective_id=None,
                severity=self._collector_failure_severity(collector_status),
                summary=f"collector failure: {name} status={collector_status}",
                evidence_refs=[evidence_ref],
                source="collector_manifest",
                metadata={
                    "collector_name": name,
                    "collector_status": collector_status,
                    "dashboard_target": "runtime",
                    "runtime_evidence_ref": evidence_ref,
                },
            )

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

    def _build_scope_enforcement(
        self,
        *,
        session_id: str,
        objective_id: str,
        receipt_id: str,
        declared_scope: str,
        scope_analysis: Dict[str, Any],
        policy_approval: Optional[Dict[str, Any]],
        evidence_refs: Sequence[str],
    ) -> Dict[str, Any]:
        out_of_scope_count = int(scope_analysis.get("out_of_scope_count", 0) or 0)
        change_count = int(scope_analysis.get("change_count", 0) or 0)
        scope_weight = float(scope_analysis.get("scope_weight", 0.0) or 0.0)
        declared_scope_text = str(declared_scope or scope_analysis.get("declared_scope", "") or "").strip()
        approval_id = str((policy_approval or {}).get("id", "") or "")
        approval_status = str((policy_approval or {}).get("status", "") or "")
        approval_ref = f"local://cleanhouse/approval-queue/{approval_id}" if approval_id else ""
        approval_proof_ref = f"local://cleanhouse/approval-mediation-proof/{approval_id}" if approval_id else ""
        receipt_ref = f"local://cleanhouse/receipt/{receipt_id}" if receipt_id else ""
        base_refs = self._local_evidence_refs([*evidence_refs, receipt_ref, approval_ref, approval_proof_ref])
        cluster_paths: list[str] = []
        for cluster in scope_analysis.get("path_clusters", []):
            if not isinstance(cluster, dict):
                continue
            cluster_name = str(cluster.get("cluster", "") or "").strip()
            if cluster_name:
                cluster_paths.append(cluster_name)
        cluster_paths = sorted(set(cluster_paths))

        objective_evaluable = bool(objective_id or declared_scope_text)
        objective_exceeded = bool(out_of_scope_count > 0 and objective_evaluable)
        scope_evaluable = bool(declared_scope_text)
        approved_scope_exceeded = bool(out_of_scope_count > 0 and scope_evaluable)
        authorization_exceeded = bool(out_of_scope_count > 0 and approval_status != "approved")
        boundaries = [
            {
                "boundary": "declared_objective",
                "status": "exceeded" if objective_exceeded else ("within_boundary" if objective_evaluable else "unknown"),
                "exceeded": objective_exceeded,
                "rationale": "out-of-scope mutations crossed declared objective constraints"
                if objective_exceeded
                else ("objective boundary not exceeded" if objective_evaluable else "objective boundary unavailable"),
            },
            {
                "boundary": "approved_scope",
                "status": "exceeded" if approved_scope_exceeded else ("within_boundary" if scope_evaluable else "unknown"),
                "exceeded": approved_scope_exceeded,
                "rationale": f"mutations exceeded approved scope prefix '{declared_scope_text}'"
                if approved_scope_exceeded
                else ("approved scope boundary not exceeded" if scope_evaluable else "approved scope boundary unavailable"),
            },
            {
                "boundary": "authorization_boundary",
                "status": "exceeded" if authorization_exceeded else "within_boundary",
                "exceeded": authorization_exceeded,
                "rationale": (
                    "scope expansion remains outside authorization boundary until explicit approval is granted"
                    if authorization_exceeded
                    else "authorization boundary includes explicit approval for scope expansion"
                ),
                "approval_status": approval_status or "pending",
            },
        ]

        deviation_records: list[Dict[str, Any]] = []
        for boundary in boundaries:
            if not boundary.get("exceeded"):
                continue
            boundary_type = str(boundary.get("boundary", "") or "boundary")
            deviation_id = f"scope_deviation:{_fingerprint(session_id, receipt_id, boundary_type, approval_id, str(out_of_scope_count), str(scope_weight))}"
            deviation_ref = f"local://cleanhouse/scope-deviation/{deviation_id}"
            deviation_records.append({
                "id": deviation_id,
                "record_type": "scope_boundary_exceeded",
                "boundary": boundary_type,
                "status": "deviation",
                "enforceable": True,
                "enforcement_action": "operator_mediation_required",
                "objective_id": objective_id,
                "receipt_id": receipt_id,
                "approval_id": approval_id,
                "approval_status": approval_status or "pending",
                "declared_scope": declared_scope_text,
                "out_of_scope_count": out_of_scope_count,
                "change_count": change_count,
                "scope_weight": scope_weight,
                "affected_path_clusters": cluster_paths,
                "rationale": str(boundary.get("rationale", "")),
                "evidence_refs": self._local_evidence_refs([*base_refs, deviation_ref]),
            })

        return {
            "schema": "cleanhouse.scope_enforcement.v1",
            "policy_id": "scope_enforcement_v1",
            "session_id": session_id,
            "objective_id": objective_id,
            "receipt_id": receipt_id,
            "declared_scope": declared_scope_text,
            "change_count": change_count,
            "out_of_scope_count": out_of_scope_count,
            "scope_weight": scope_weight,
            "boundaries": boundaries,
            "deviation_records": deviation_records,
            "approval": {
                "approval_id": approval_id,
                "status": approval_status or "pending",
                "route_ownership": "review_state_only",
            },
            "enforcement_status": (
                "blocked_pending_approval"
                if authorization_exceeded
                else ("approved_override" if out_of_scope_count > 0 else "within_boundaries")
            ),
            "evidence_refs": list(base_refs),
        }

    def _emit_scope_enforcement_mediation_event(
        self,
        *,
        session_id: str,
        objective_id: str,
        receipt_id: str,
        scope_enforcement: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        deviation_records = (
            scope_enforcement.get("deviation_records", [])
            if isinstance(scope_enforcement.get("deviation_records"), list)
            else []
        )
        if not deviation_records:
            return []
        mediation_id = f"scope_enforcement:{_fingerprint(session_id, receipt_id, str(len(deviation_records)), scope_enforcement.get('enforcement_status', ''))}"
        mediation_ref = f"local://cleanhouse/scope-enforcement/{mediation_id}"
        refs = self._local_evidence_refs([
            *scope_enforcement.get("evidence_refs", []),
            *[
                ref
                for record in deviation_records
                if isinstance(record, dict)
                for ref in (record.get("evidence_refs", []) if isinstance(record.get("evidence_refs"), list) else [])
            ],
            mediation_ref,
        ])
        observed_status = "deviation" if deviation_records else "matched"
        _insert_runtime_event(
            event_type="scope_enforcement_mediation",
            path=f"/scope-enforcement/{mediation_id}",
            summary=(
                f"scope enforcement mediation required: {len(deviation_records)} deviation record(s), "
                f"status={scope_enforcement.get('enforcement_status', 'unknown')}"
            ),
            session_id=session_id,
            objective_id=objective_id or None,
            source_surface="approval_policy",
            actor_type="cleanhouse",
            evidence_level="observed",
            observed_vs_expected={
                "status": observed_status,
                "details": "out-of-scope actions require mediated authorization review",
            },
            collector_status="degraded" if observed_status == "deviation" else "ok",
            scope_relation="outside_declared_scope",
            evidence_refs=refs,
            raw_evidence_ref=mediation_ref,
            data={
                "mediation_id": mediation_id,
                "mediation_ref": mediation_ref,
                "scope_enforcement": copy.deepcopy(scope_enforcement),
            },
        )
        return [{
            "id": mediation_id,
            "event_type": "scope_enforcement_mediation",
            "event_ref": mediation_ref,
            "status": "enforceable",
            "summary": "out-of-scope actions routed to mediated authorization flow",
            "deviation_count": len(deviation_records),
            "evidence_refs": refs,
        }]

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

    def _ensure_rollback_needed_notification(
        self,
        *,
        session_id: str,
        objective_id: Optional[str],
        receipt_id: str,
        rollback_state: Dict[str, Any],
        policy_approval: Optional[Dict[str, Any]],
        evidence_refs: Sequence[str],
    ) -> None:
        if not policy_approval:
            return
        rollback_status = str(rollback_state.get("status", "not_requested") or "not_requested")
        if rollback_status == "executed_verified":
            return
        severity = "critical" if rollback_status == "executed_verification_failed" else "warning"
        approval_id = str(policy_approval.get("id", "") or "")
        summary = f"rollback needed: receipt {receipt_id} rollback_state={rollback_status}"
        rollback_ref = f"local://cleanhouse/rollback-state/{receipt_id or session_id}"
        self._ensure_operator_notification(
            notification_type="rollback_needed",
            session_id=session_id,
            objective_id=objective_id,
            severity=severity,
            summary=summary[:220],
            evidence_refs=[*evidence_refs, rollback_ref],
            source="receipt_policy",
            metadata={
                "receipt_id": receipt_id,
                "rollback_status": rollback_status,
                "approval_id": approval_id,
                "route_ownership": "review_state_only",
                "source_ref": rollback_ref,
            },
        )

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

    def _resolve_repo_root(self, repo_path: str) -> Path:
        path = Path(str(repo_path or "")).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = path.resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError("repo_path must be an existing directory")
        return resolved

    def _resolve_scoped_path(self, repo_root: Path, rel_path: str) -> Path:
        cleaned = str(rel_path or "").replace("\\", "/").lstrip("/")
        if not cleaned:
            raise ValueError("path is required")
        candidate = (repo_root / cleaned).resolve()
        if not str(candidate).startswith(str(repo_root)):
            raise ValueError("path escapes repo root")
        return candidate

    def _qpb_history_entry(
        self,
        *,
        case_id: str,
        action: str,
        actor: str,
        status: str,
        target_scope: Dict[str, Any],
        evidence_refs: Sequence[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        payload = {
            "case_id": case_id,
            "action": action,
            "actor": actor,
            "status": status,
            "timestamp": now,
            "target_scope": copy.deepcopy(target_scope),
            "evidence_refs": list(self._local_evidence_refs(evidence_refs)),
            "metadata": copy.deepcopy(metadata or {}),
        }
        payload["integrity"] = {
            "root_hash": _canonical_json_hash(payload),
        }
        return payload

    def _persist_qpb_case(self, record: QPBCaseRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist("qpb_case", record.id, {"status": "ok", "case": record.to_dict()})

    def _qpb_case_from_dict(self, raw: Dict[str, Any]) -> Optional[QPBCaseRecord]:
        case_id = str(raw.get("id", "")).strip()
        session_id = str(raw.get("session_id", "")).strip()
        status = str(raw.get("status", "")).strip()
        if not case_id or not session_id or status not in QPB_CASE_STATES:
            return None
        return QPBCaseRecord(
            id=case_id,
            session_id=session_id,
            objective_id=str(raw.get("objective_id", "")).strip() or None,
            status=status,
            target_scope=copy.deepcopy(raw.get("target_scope", {})) if isinstance(raw.get("target_scope"), dict) else {},
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            evidence_refs=tuple(self._local_evidence_refs(raw.get("evidence_refs", []))),
            metadata=copy.deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {},
            history=tuple(copy.deepcopy(raw.get("history", []))) if isinstance(raw.get("history"), list) else tuple(),
        )

    def _all_qpb_cases(self) -> list[QPBCaseRecord]:
        with self._lock:
            records = {record.id: record for record in self._qpb_cases.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("qpb_case"):
                payload = artifact.get("data", {})
                raw = payload.get("case", payload) if isinstance(payload, dict) else None
                if not isinstance(raw, dict):
                    continue
                record = self._qpb_case_from_dict(raw)
                if record and record.id not in records:
                    records[record.id] = record
        return list(records.values())

    def _qpb_case_by_id(self, case_id: str) -> Optional[QPBCaseRecord]:
        for case in self._all_qpb_cases():
            if case.id == case_id:
                return case
        return None

    def get_qpb_cases(self, session_id: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._all_qpb_cases()]
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        if status:
            records = [record for record in records if record.get("status") == status]
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return {"status": "ok", "cases": records, "count": len(records)}

    def create_qpb_case(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        target_scope = copy.deepcopy(data.get("target_scope", {})) if isinstance(data.get("target_scope"), dict) else {}
        actor = str(data.get("actor", "operator")).strip() or "operator"
        objective_id = str(data.get("objective_id", "")).strip() or self._objective_id_for_session(session_id)
        evidence_refs = self._local_evidence_refs(data.get("evidence_refs", []))
        now = _now_iso()
        case_id = f"qpb_case:{_fingerprint(session_id, json.dumps(target_scope, sort_keys=True, default=str), now)}"
        history = (
            self._qpb_history_entry(
                case_id=case_id,
                action="detected",
                actor=actor,
                status="detected",
                target_scope=target_scope,
                evidence_refs=evidence_refs,
                metadata={"source": str(data.get("source", "api") or "api")},
            ),
        )
        record = QPBCaseRecord(
            id=case_id,
            session_id=session_id,
            objective_id=objective_id,
            status="detected",
            target_scope=target_scope,
            created_at=now,
            updated_at=now,
            evidence_refs=tuple(evidence_refs),
            metadata=copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {},
            history=history,
        )
        with self._lock:
            self._qpb_cases[record.id] = record
        self._persist_qpb_case(record)
        _insert_runtime_event(
            event_type="qpb_case",
            path=f"/qpb/cases/{record.id}",
            summary="qpb detected",
            session_id=session_id,
            objective_id=objective_id,
            source_surface="qpb",
            actor_type="process",
            evidence_level="observed",
            observed_vs_expected={"status": "detected", "details": "qpb case created"},
            collector_status="ok",
            scope_relation="recovery_state",
            evidence_refs=[*evidence_refs, f"local://cleanhouse/qpb_case/{record.id}"],
            raw_evidence_ref=f"local://cleanhouse/qpb_case/{record.id}",
            data=record.to_dict(),
        )
        return {"status": "ok", "case": record.to_dict()}

    def _qpb_execute_purge(self, case: QPBCaseRecord, repo_path: Optional[str]) -> Dict[str, Any]:
        target_paths = case.target_scope.get("paths", [])
        process_pids = case.target_scope.get("process_pids", [])
        removed_paths: list[str] = []
        process_results: list[Dict[str, Any]] = []
        root = self._resolve_repo_root(repo_path) if repo_path else None
        undo_records: list[Dict[str, Any]] = []

        if isinstance(target_paths, list) and root is not None:
            for raw_path in target_paths:
                rel_path = str(raw_path or "").strip()
                if not rel_path:
                    continue
                target = self._resolve_scoped_path(root, rel_path)
                before_exists = target.exists()
                before_is_dir = target.is_dir()
                before_content = None
                if before_exists and target.is_file():
                    before_content = base64.b64encode(target.read_bytes()).decode("ascii")
                if before_exists and target.is_file():
                    target.unlink()
                    removed_paths.append(rel_path)
                elif before_exists and target.is_dir():
                    for nested in sorted(target.rglob("*"), reverse=True):
                        if nested.is_file():
                            nested.unlink()
                        elif nested.is_dir():
                            try:
                                nested.rmdir()
                            except OSError:
                                pass
                    try:
                        target.rmdir()
                    except OSError:
                        pass
                    removed_paths.append(rel_path)
                undo_records.append({
                    "path": rel_path,
                    "before_exists": before_exists,
                    "before_is_dir": before_is_dir,
                    "before_content_b64": before_content,
                })

        if isinstance(process_pids, list):
            for raw_pid in process_pids:
                try:
                    pid = int(raw_pid)
                except (TypeError, ValueError):
                    continue
                result = {"pid": pid, "killed": False, "error": ""}
                try:
                    os.kill(pid, 15)
                    result["killed"] = True
                except Exception as exc:
                    result["error"] = str(exc)
                process_results.append(result)

        return {
            "removed_paths": removed_paths,
            "process_results": process_results,
            "undo_records": undo_records,
        }

    def advance_qpb_case(self, case_id: str, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        case_id = str(case_id or "").strip()
        action = str(action or "").strip().lower()
        if action not in {"quarantine", "purge", "bless", "reject"}:
            return {"status": "error", "message": "action must be quarantine, purge, bless, or reject"}
        case = self._qpb_case_by_id(case_id)
        if case is None:
            return {"status": "not_found", "message": f"qpb case not found: {case_id}"}
        actor = str(data.get("actor", "operator")).strip() or "operator"
        metadata = copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {}
        evidence_refs = self._local_evidence_refs(data.get("evidence_refs", []))
        now = _now_iso()
        next_status = case.status
        step_meta: Dict[str, Any] = {}

        if action == "quarantine":
            if case.status not in {"detected", "quarantined"}:
                return {"status": "error", "message": "quarantine requires detected or quarantined state"}
            next_status = "quarantined"
        elif action == "purge":
            if case.status not in {"quarantined", "purge_pending"}:
                return {"status": "error", "message": "purge requires quarantined or purge_pending state"}
            purge_requires_confirmation = bool(self._settings.get("qpb_policy", {}).get("purge_requires_confirmation", True))
            confirm = bool(data.get("confirm", False))
            if purge_requires_confirmation and not confirm:
                next_status = "purge_pending"
                step_meta["confirmation_required"] = True
            else:
                purge_outcome = self._qpb_execute_purge(case, data.get("repo_path"))
                next_status = "purged"
                step_meta.update(purge_outcome)
        elif action == "bless":
            if case.status != "purged":
                return {"status": "error", "message": "bless requires purged state"}
            next_status = "blessed"
            step_meta["trust_reset"] = True
        elif action == "reject":
            next_status = "rejected"

        history_entry = self._qpb_history_entry(
            case_id=case.id,
            action=action,
            actor=actor,
            status=next_status,
            target_scope=case.target_scope,
            evidence_refs=[*case.evidence_refs, *evidence_refs],
            metadata={**metadata, **step_meta},
        )
        updated = QPBCaseRecord(
            id=case.id,
            session_id=case.session_id,
            objective_id=case.objective_id,
            status=next_status,
            target_scope=case.target_scope,
            created_at=case.created_at,
            updated_at=now,
            evidence_refs=tuple(self._local_evidence_refs([*case.evidence_refs, *evidence_refs])),
            metadata={**case.metadata, **metadata},
            history=case.history + (history_entry,),
        )
        with self._lock:
            self._qpb_cases[updated.id] = updated
        self._persist_qpb_case(updated)
        _insert_runtime_event(
            event_type="qpb_transition",
            path=f"/qpb/cases/{updated.id}",
            summary=f"qpb {action}: {next_status}",
            session_id=updated.session_id,
            objective_id=updated.objective_id,
            source_surface="qpb",
            actor_type="operator",
            evidence_level="observed",
            observed_vs_expected={"status": next_status, "details": action},
            collector_status="ok",
            scope_relation="recovery_state",
            evidence_refs=[*updated.evidence_refs, f"local://cleanhouse/qpb_case/{updated.id}"],
            raw_evidence_ref=f"local://cleanhouse/qpb_case/{updated.id}",
            data=updated.to_dict(),
        )
        self._ensure_operator_notification(
            notification_type="qpb_transition",
            session_id=updated.session_id,
            objective_id=updated.objective_id,
            severity="warning" if next_status in {"quarantined", "purge_pending"} else "info",
            summary=f"qpb {action}: {next_status}",
            evidence_refs=[*updated.evidence_refs, f"local://cleanhouse/qpb_case/{updated.id}"],
            source="qpb",
            metadata={"case_id": updated.id, "action": action, "status": next_status},
        )
        return {"status": "ok", "case": updated.to_dict()}

    def _standalone_incident_target_path(self, raw_path: str, session_id: str) -> str:
        cleaned = str(raw_path or "").strip().replace("\\", "/").lstrip("/")
        if cleaned:
            parts = [part for part in cleaned.split("/") if part]
            if parts and ".." not in parts:
                return "/".join(parts)
        token = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(session_id or "session"))[:80]
        token = token.strip("_") or "session"
        return f"data/incident_receipts/{token}.txt"

    def _find_standalone_incident_case(self, *, session_id: Optional[str] = None, case_id: Optional[str] = None) -> Optional[QPBCaseRecord]:
        candidates: list[QPBCaseRecord] = []
        for case in self._all_qpb_cases():
            metadata = case.metadata if isinstance(case.metadata, dict) else {}
            if str(metadata.get("workflow", "")) != "standalone_incident_receipt":
                continue
            if case_id and case.id != case_id:
                continue
            if session_id and case.session_id != session_id:
                continue
            candidates.append(case)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates[0]

    def _incident_by_id(self, incident_id: str) -> Optional[IncidentCaseRecord]:
        incident_id = str(incident_id or "").strip()
        if not incident_id:
            return None
        for incident in self._all_incident_cases():
            if incident.id == incident_id:
                return incident
        return None

    def _domain_event_by_id(self, event_id: str) -> Optional[DomainEventRecord]:
        event_id = str(event_id or "").strip()
        if not event_id:
            return None
        for event in self._all_domain_events():
            if event.id == event_id:
                return event
        return None

    def _latest_runtime_incident(self, session_id: str) -> Optional[IncidentCaseRecord]:
        candidates: list[IncidentCaseRecord] = []
        for incident in self._all_incident_cases():
            if incident.session_id != session_id:
                continue
            if incident.status not in {"open", "acknowledged", "in_review"}:
                continue
            metadata = incident.metadata if isinstance(incident.metadata, dict) else {}
            if str(metadata.get("workflow", "")) == "standalone_incident_receipt":
                continue
            if not incident.source_event_id:
                continue
            candidates.append(incident)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.updated_at, reverse=True)
        return candidates[0]

    def _operation_proposal_dict(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        proposal = self._operation_proposal_by_id(str(proposal_id or "").strip())
        if proposal is None:
            return None
        return proposal.to_dict()

    def _standalone_incident_outcome(self, case: QPBCaseRecord) -> Dict[str, Any]:
        history = list(case.history or [])
        if not history:
            return {"status": case.status}
        latest = history[-1] if isinstance(history[-1], dict) else {}
        metadata = latest.get("metadata", {}) if isinstance(latest.get("metadata"), dict) else {}
        return {
            "status": case.status,
            "action": str(latest.get("action", "") or ""),
            "actor": str(latest.get("actor", "") or ""),
            "timestamp": str(latest.get("timestamp", "") or ""),
            "note": str(latest.get("note", "") or ""),
            "details": copy.deepcopy(metadata),
            "integrity_root_hash": str((latest.get("integrity", {}) or {}).get("root_hash", "")),
        }

    def _standalone_incident_card(self, case: QPBCaseRecord) -> Dict[str, Any]:
        metadata = case.metadata if isinstance(case.metadata, dict) else {}
        incident = self._incident_by_id(str(metadata.get("incident_id", "")))
        proposal = self._operation_proposal_dict(str(metadata.get("proposal_id", "")))
        target_scope = case.target_scope if isinstance(case.target_scope, dict) else {}
        target_paths = target_scope.get("paths", []) if isinstance(target_scope.get("paths"), list) else []
        process_pids = target_scope.get("process_pids", []) if isinstance(target_scope.get("process_pids"), list) else []
        signal_reason = str(metadata.get("suspicion_reason", "") or "signal_reason_unavailable")

        evidence_refs: list[str] = list(self._local_evidence_refs(case.evidence_refs))
        if incident is not None:
            evidence_refs.extend(self._local_evidence_refs(incident.evidence_refs))
        if proposal and isinstance(proposal.get("evidence_refs"), list):
            evidence_refs.extend(self._local_evidence_refs(proposal.get("evidence_refs", [])))
        evidence_refs = self._local_evidence_refs(evidence_refs)

        decision_path = {
            "allowed_actions": ["quarantine", "purge", "bless"],
            "current_status": case.status,
            "next_action": (
                "quarantine"
                if case.status == "detected"
                else "purge"
                if case.status in {"quarantined", "purge_pending"}
                else "bless"
                if case.status == "purged"
                else "complete"
            ),
        }
        return {
            "card_id": f"incident_receipt:{case.id}",
            "workflow": "standalone_incident_receipt",
            "session_id": case.session_id,
            "objective_id": case.objective_id,
            "incident": incident.to_dict() if incident is not None else None,
            "qpb_case": case.to_dict(),
            "proposal": proposal,
            "suspicion": {
                "title": "Agent Firewall + File Integrity Suspicion",
                "reason": signal_reason,
                "signal_source": str(metadata.get("signal_source", "") or "unknown"),
                "signal_process": str(metadata.get("signal_process", "") or "unknown"),
                "signal_pid": metadata.get("signal_pid"),
                "target_path": target_paths[0] if target_paths else "",
                "target_paths": target_paths,
                "process_pids": process_pids,
            },
            "decision_path": decision_path,
            "evidence": {
                "refs": evidence_refs,
                "history": list(case.history or []),
            },
            "outcome": self._standalone_incident_outcome(case),
        }

    def get_standalone_incident_receipt(self, *, session_id: Optional[str] = None, case_id: Optional[str] = None) -> Dict[str, Any]:
        record = self._find_standalone_incident_case(session_id=session_id, case_id=case_id)
        if record is None:
            return {"status": "not_found", "message": "standalone incident receipt not found"}
        return {"status": "ok", "card": self._standalone_incident_card(record)}

    def create_standalone_incident_receipt(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}

        existing = self._find_standalone_incident_case(session_id=session_id)
        if existing is not None and str(data.get("force_new", "")).strip().lower() not in {"1", "true", "yes"}:
            return {"status": "ok", "card": self._standalone_incident_card(existing), "reused": True}

        repo_path = str(data.get("repo_path", "") or "").strip()
        requested_incident_id = str(data.get("incident_id", "") or "").strip()
        allow_synthetic = bool(data.get("allow_synthetic", False))

        incident_record = self._incident_by_id(requested_incident_id) if requested_incident_id else None
        if incident_record is None:
            incident_record = self._latest_runtime_incident(session_id)
        if incident_record is None and not allow_synthetic:
            return {
                "status": "error",
                "message": "no runtime incident available; pass incident_id or wait for runtime-generated incident",
            }

        signal_source = ""
        signal_process = ""
        signal_reason = ""
        signal_pid = 0
        target_path = ""
        observed_at = _now_iso()
        evidence_refs: list[str] = []
        incident_id = ""

        if incident_record is not None:
            incident_id = incident_record.id
            event = self._domain_event_by_id(incident_record.source_event_id)
            if event is None:
                return {"status": "error", "message": f"source domain event missing for incident {incident_id}"}
            resource = event.resource if isinstance(event.resource, dict) else {}
            actor = event.actor if isinstance(event.actor, dict) else {}
            details = event.observed_vs_expected if isinstance(event.observed_vs_expected, dict) else {}
            signal_source = str(event.surface or "").strip() or "unknown"
            signal_process = str(actor.get("process", "") or actor.get("command", "") or "").strip() or "unknown"
            signal_reason = str(details.get("details", "") or incident_record.summary or "").strip() or "runtime incident detected"
            observed_at = str(event.observed_at or observed_at)
            target_path = self._standalone_incident_target_path(str(resource.get("path", "") or ""), session_id)
            try:
                signal_pid = int(resource.get("process_pid", actor.get("pid", 0)))
            except (TypeError, ValueError):
                signal_pid = 0
            evidence_refs = [
                *self._local_evidence_refs(event.evidence_refs),
                *self._local_evidence_refs(incident_record.evidence_refs),
            ]
        else:
            signal_pid_raw = data.get("signal_pid")
            signal_source = str(data.get("signal_source", "") or "").strip() or "manual"
            signal_process = str(data.get("signal_process", "") or "").strip() or "unknown"
            signal_reason = str(data.get("suspicion_reason", "") or "").strip() or "synthetic incident path"
            target_path = self._standalone_incident_target_path(str(data.get("target_path", "") or ""), session_id)
            try:
                signal_pid = int(signal_pid_raw)
            except (TypeError, ValueError):
                signal_pid = 0
            incident_result = self.emit_domain_event({
                "domain": "agent_firewall",
                "surface": signal_source,
                "event_type": "process_file_integrity_suspicion",
                "session_id": session_id,
                "objective_id": self._objective_id_for_session(session_id),
                "observed_at": _now_iso(),
                "severity": "warning",
                "actor": {"type": "process", "pid": signal_pid, "process": signal_process},
                "resource": {"path": target_path, "process_pid": signal_pid},
                "observed_vs_expected": {"status": "observed", "details": signal_reason},
                "metadata": {"workflow": "standalone_incident_receipt", "repo_path": repo_path, "synthetic": True},
            })
            if incident_result.get("status") != "ok":
                return incident_result
            incident_payload = incident_result.get("incident", {}) if isinstance(incident_result.get("incident"), dict) else {}
            incident_id = str(incident_payload.get("id", "") or "")
            evidence_refs = self._local_evidence_refs(incident_payload.get("evidence_refs", []))

        if signal_pid <= 0:
            return {"status": "error", "message": "runtime incident is missing process pid evidence"}
        if not target_path:
            return {"status": "error", "message": "runtime incident is missing file path evidence"}
        if not evidence_refs:
            evidence_refs = [
                f"local://cleanhouse/incident/{_fingerprint(incident_id or session_id)}",
            ]

        proposal = self.create_operation_proposal({
            "session_id": session_id,
            "proposal_type": "incident_receipt_stage",
            "reason": "incident receipt file-integrity marker staged for mediation evidence",
            "operations": [{
                "op": "write_file",
                "path": target_path,
                "content": (
                    "standalone_incident_receipt=true\n"
                    f"session_id={session_id}\n"
                    f"signal_source={signal_source}\n"
                    f"signal_pid={signal_pid}\n"
                    f"signal_process={signal_process}\n"
                    f"suspicion_reason={signal_reason}\n"
                    f"created_at={observed_at}\n"
                ),
            }],
            "target_scope": {"paths": [target_path], "process_pids": [signal_pid]},
            "metadata": {
                "repo_path": repo_path,
                "workflow": "standalone_incident_receipt",
                "incident_id": incident_id,
                "synthetic": incident_record is None,
            },
            "evidence_refs": evidence_refs,
        })
        if proposal.get("status") != "ok":
            return proposal
        proposal_id = str((proposal.get("proposal") or {}).get("id", "") or "")
        if repo_path and proposal_id:
            applied = self.resolve_operation_proposal(
                proposal_id,
                "approve",
                {"confirm": True, "repo_path": repo_path},
            )
            if applied.get("status") != "ok":
                return applied

        qpb_case = self.create_qpb_case({
            "session_id": session_id,
            "objective_id": self._objective_id_for_session(session_id),
            "target_scope": {"paths": [target_path], "process_pids": [signal_pid]},
            "metadata": {
                "repo_path": repo_path,
                "workflow": "standalone_incident_receipt",
                "incident_id": incident_id,
                "proposal_id": proposal_id,
                "signal_source": signal_source,
                "signal_process": signal_process,
                "signal_pid": signal_pid,
                "suspicion_reason": signal_reason,
                "synthetic": incident_record is None,
            },
            "evidence_refs": evidence_refs,
            "source": "incident_receipt",
        })
        if qpb_case.get("status") != "ok":
            return qpb_case
        case_id = str((qpb_case.get("case") or {}).get("id", "") or "")
        return self.get_standalone_incident_receipt(case_id=case_id)

    def advance_standalone_incident_receipt(self, case_id: str, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        step = self.advance_qpb_case(case_id, action, data)
        if step.get("status") != "ok":
            return step
        updated_case = step.get("case", {}) if isinstance(step.get("case"), dict) else {}
        metadata = updated_case.get("metadata", {}) if isinstance(updated_case.get("metadata"), dict) else {}
        incident_id = str(metadata.get("incident_id", "") or "")
        if incident_id:
            if updated_case.get("status") == "blessed":
                self.update_incident_case(incident_id, "resolve", note="qpb bless completed", actor=str(data.get("actor", "operator") or "operator"))
            elif updated_case.get("status") in {"quarantined", "purge_pending", "purged"}:
                self.update_incident_case(incident_id, "review", note=f"qpb {action} -> {updated_case.get('status')}", actor=str(data.get("actor", "operator") or "operator"))
        return self.get_standalone_incident_receipt(case_id=case_id)

    def get_task_manager_snapshot(self, refresh: bool = False) -> Dict[str, Any]:
        processes = self.get_processes(refresh=refresh)
        data = processes.get("data", {}) if isinstance(processes.get("data"), dict) else {}
        rows = data.get("processes", []) if isinstance(data.get("processes"), list) else []
        rows = sorted(rows, key=lambda row: float(row.get("cpu", 0) or 0), reverse=True)
        return {
            "status": "ok",
            "tasks": rows[:100],
            "count": len(rows),
            "generated_at": _now_iso(),
        }

    def get_port_monitor_snapshot(self, refresh: bool = False) -> Dict[str, Any]:
        network = self.get_network(refresh=refresh)
        data = network.get("data", {}) if isinstance(network.get("data"), dict) else {}
        suspicious = data.get("suspicious_connections", []) if isinstance(data.get("suspicious_connections"), list) else []
        open_ports: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for conn in suspicious:
            port = conn.get("port")
            host = conn.get("host") or conn.get("domain") or "unknown"
            key = f"{host}:{port}"
            if key in seen:
                continue
            seen.add(key)
            open_ports.append({
                "host": host,
                "port": port,
                "process": conn.get("process"),
                "pid": conn.get("pid"),
                "reason": conn.get("suspicious_reason", ""),
            })
        return {
            "status": "ok",
            "ports": open_ports[:200],
            "count": len(open_ports),
            "generated_at": _now_iso(),
        }

    def _file_lineage_rows(
        self,
        *,
        session_id: str,
        mutations: Sequence[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        prompts = self.get_prompts(session_id=session_id).get("prompts", [])
        latest_prompt = prompts[0] if prompts else {}
        context_snippet = str(latest_prompt.get("text", "") or "")[:200]
        context_ref = f"local://cleanhouse/prompt/{latest_prompt.get('id', '')}" if latest_prompt.get("id") else ""
        rows: list[Dict[str, Any]] = []
        for mutation in mutations:
            timestamp = str(mutation.get("timestamp", "") or "")
            actor = str(mutation.get("source", "unknown") or "unknown")
            if mutation.get("source") in {"diff", "timeline"}:
                for change in mutation.get("changes", []):
                    if not isinstance(change, dict):
                        continue
                    path = str(change.get("path", "") or "")
                    if not path:
                        continue
                    rows.append({
                        "when": timestamp,
                        "who": actor,
                        "what": str(change.get("change_type", "unknown") or "unknown"),
                        "where": path,
                        "context": context_snippet,
                        "context_ref": context_ref,
                        "evidence_refs": self._local_evidence_refs([
                            *(mutation.get("evidence_refs", []) or []),
                            context_ref,
                        ]),
                    })
            else:
                path = str(mutation.get("path", "") or "")
                if not path:
                    continue
                rows.append({
                    "when": timestamp,
                    "who": actor,
                    "what": str(mutation.get("event_type", "unknown") or "unknown"),
                    "where": path,
                    "context": context_snippet,
                    "context_ref": context_ref,
                    "evidence_refs": self._local_evidence_refs([
                        *(mutation.get("evidence_refs", []) or []),
                        context_ref,
                    ]),
                })
        rows.sort(key=lambda row: row.get("when", ""), reverse=True)
        return rows[:200]

    def _persist_operation_proposal(self, record: OperationProposalRecord) -> None:
        if not self.persistence_enabled:
            return
        PersistenceBackend.persist("operation_proposal", record.id, {"status": "ok", "proposal": record.to_dict()})

    def _operation_proposal_from_dict(self, raw: Dict[str, Any]) -> Optional[OperationProposalRecord]:
        proposal_id = str(raw.get("id", "")).strip()
        session_id = str(raw.get("session_id", "")).strip()
        state = str(raw.get("status", "")).strip()
        if not proposal_id or not session_id or state not in PROPOSAL_STATES:
            return None
        operations = raw.get("operations", [])
        if not isinstance(operations, list):
            operations = []
        return OperationProposalRecord(
            id=proposal_id,
            proposal_type=str(raw.get("proposal_type", "")).strip() or "mediator",
            session_id=session_id,
            objective_id=str(raw.get("objective_id", "")).strip() or None,
            status=state,
            reason=str(raw.get("reason", "") or ""),
            target_scope=copy.deepcopy(raw.get("target_scope", {})) if isinstance(raw.get("target_scope"), dict) else {},
            operations=tuple(copy.deepcopy(operations)),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
            applied_at=raw.get("applied_at"),
            undone_at=raw.get("undone_at"),
            evidence_refs=tuple(self._local_evidence_refs(raw.get("evidence_refs", []))),
            rollback_id=str(raw.get("rollback_id", "")).strip() or None,
            metadata=copy.deepcopy(raw.get("metadata", {})) if isinstance(raw.get("metadata"), dict) else {},
        )

    def _all_operation_proposals(self) -> list[OperationProposalRecord]:
        with self._lock:
            records = {record.id: record for record in self._operation_proposals.values()}
        if self.persistence_enabled:
            for artifact in PersistenceBackend.list_artifacts("operation_proposal"):
                payload = artifact.get("data", {})
                raw = payload.get("proposal", payload) if isinstance(payload, dict) else None
                if not isinstance(raw, dict):
                    continue
                record = self._operation_proposal_from_dict(raw)
                if record and record.id not in records:
                    records[record.id] = record
        return list(records.values())

    def _operation_proposal_by_id(self, proposal_id: str) -> Optional[OperationProposalRecord]:
        for proposal in self._all_operation_proposals():
            if proposal.id == proposal_id:
                return proposal
        return None

    def get_operation_proposals(
        self,
        *,
        session_id: Optional[str] = None,
        proposal_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        records = [record.to_dict() for record in self._all_operation_proposals()]
        if session_id:
            records = [record for record in records if record.get("session_id") == session_id]
        if proposal_type:
            records = [record for record in records if record.get("proposal_type") == proposal_type]
        if status:
            records = [record for record in records if record.get("status") == status]
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return {"status": "ok", "proposals": records, "count": len(records)}

    def _approval_for_operation_proposal(self, proposal_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        proposal_id = str(proposal_id or "").strip()
        if not proposal_id or not session_id:
            return None
        approvals = self.get_approval_queue(session_id=session_id).get("approval_queue", [])
        matches: list[Dict[str, Any]] = []
        for approval in approvals:
            if not isinstance(approval, dict):
                continue
            metadata = approval.get("metadata", {}) if isinstance(approval.get("metadata"), dict) else {}
            if str(metadata.get("proposal_id", "")) == proposal_id:
                matches.append(approval)
        if not matches:
            return None
        matches.sort(key=lambda row: row.get("created_at", ""), reverse=True)
        return matches[0]

    @staticmethod
    def _actor_attribution_entry(
        *,
        actor_type: str,
        actor_id: str,
        status: str,
        basis: str,
        evidence_refs: Sequence[str],
    ) -> Dict[str, Any]:
        normalized_status = status if status in {"observed", "inferred", "unknown"} else "unknown"
        normalized_type = str(actor_type or "unknown").strip() or "unknown"
        normalized_id = str(actor_id or "").strip()
        attribution_core = {
            "actor_type": normalized_type,
            "actor_id": normalized_id,
        }
        attribution_id = f"actor:{_fingerprint(normalized_type, normalized_id or 'unknown')}"
        attribution_hash = _stable_json_hash(attribution_core)
        refs = [
            str(ref).strip()
            for ref in evidence_refs
            if isinstance(ref, str) and str(ref).strip().startswith("local://cleanhouse/")
        ]
        return {
            "actor_type": normalized_type,
            "actor_id": normalized_id,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
            "status": normalized_status,
            "basis": str(basis or "unknown"),
            "evidence_refs": refs,
        }

    def _resolve_actor_id_from_payload(
        self,
        *,
        actor_type: str,
        source_surface: str,
        payload: Dict[str, Any],
    ) -> str:
        actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        candidate_values = [
            actor.get("actor_id"),
            actor.get("id"),
            payload.get("actor_id"),
            payload.get("reviewer"),
            payload.get("tool_identity"),
            payload.get("command"),
            payload.get("source_command"),
            payload.get("persisted_event_id"),
        ]
        for candidate in candidate_values:
            value = str(candidate or "").strip()
            if value:
                return value
        normalized_type = str(actor_type or "unknown").strip() or "unknown"
        normalized_surface = str(source_surface or "unknown").strip() or "unknown"
        return f"{normalized_type}:{normalized_surface}"

    def _artifact_actor_attribution(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        chain_of_custody: Dict[str, Any],
    ) -> Dict[str, Any]:
        hops = chain_of_custody.get("hops", []) if isinstance(chain_of_custody, dict) else []
        preferred_order = ("decision", "enforcement", "intervention", "event", "prompt", "objective")
        by_hop: Dict[str, Dict[str, Any]] = {}
        provenance: list[Dict[str, Any]] = []
        for hop in hops:
            if not isinstance(hop, dict):
                continue
            hop_name = str(hop.get("hop", "") or "")
            actor = hop.get("actor") if isinstance(hop.get("actor"), dict) else {}
            record = {
                "hop": hop_name,
                "actor_type": str(actor.get("actor_type", "unknown") or "unknown"),
                "actor_id": str(actor.get("actor_id", "") or ""),
                "attribution_id": str(actor.get("attribution_id", "") or ""),
                "attribution_hash": str(actor.get("attribution_hash", "") or ""),
                "status": str(actor.get("status", "unknown") or "unknown"),
            }
            provenance.append(record)
            if hop_name and hop_name not in by_hop:
                by_hop[hop_name] = record

        origin_actor = {
            "hop": "unknown",
            "actor_type": "unknown",
            "actor_id": "",
            "attribution_id": "",
            "attribution_hash": "",
            "status": "unknown",
        }
        for hop_name in preferred_order:
            candidate = by_hop.get(hop_name)
            if candidate and candidate.get("actor_id"):
                origin_actor = candidate
                break

        core = {
            "artifact_type": str(artifact_type or "unknown"),
            "artifact_id": str(artifact_id or ""),
            "origin_actor": origin_actor,
            "provenance": provenance,
        }
        attribution_hash = _stable_json_hash(core)
        attribution_id = f"{artifact_type}_actor_attribution:{_fingerprint(artifact_type, artifact_id, origin_actor.get('attribution_id', ''), attribution_hash)}"
        return {
            **core,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
        }

    @staticmethod
    def _channel_attribution_entry(
        *,
        channel: str,
        status: str,
        basis: str,
        evidence_refs: Sequence[str],
    ) -> Dict[str, Any]:
        normalized_status = status if status in {"observed", "inferred", "unknown"} else "unknown"
        normalized_channel = str(channel or "unknown").strip().lower() or "unknown"
        attribution_core = {
            "execution_channel": normalized_channel,
        }
        attribution_id = f"channel:{_fingerprint(normalized_channel)}"
        attribution_hash = _stable_json_hash(attribution_core)
        refs = [
            str(ref).strip()
            for ref in evidence_refs
            if isinstance(ref, str) and str(ref).strip().startswith("local://cleanhouse/")
        ]
        return {
            "execution_channel": normalized_channel,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
            "status": normalized_status,
            "basis": str(basis or "unknown"),
            "evidence_refs": refs,
        }

    @staticmethod
    def _normalize_trust_classification(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"trusted", "untrusted", "unknown", "degraded"}:
            return normalized
        return "unknown"

    def _resolve_trust_classification(
        self,
        *,
        evidence_level: str,
        collector_status: str,
        observed_vs_expected: Optional[Dict[str, Any]],
        evidence_refs: Sequence[str],
        payload: Dict[str, Any],
    ) -> tuple[str, str, list[str]]:
        local_refs = self._local_evidence_refs(evidence_refs)
        explicit_sources: list[str] = []
        trust_payload = payload.get("trust") if isinstance(payload.get("trust"), dict) else {}
        trust_eval = payload.get("trust_evaluation") if isinstance(payload.get("trust_evaluation"), dict) else {}
        explicit_candidates = [
            payload.get("trust_classification"),
            payload.get("trust_status"),
            trust_payload.get("trust_classification"),
            trust_payload.get("classification"),
            trust_payload.get("status"),
            trust_eval.get("trust_classification"),
            trust_eval.get("classification"),
            trust_eval.get("status"),
        ]
        for candidate in explicit_candidates:
            normalized = self._normalize_trust_classification(str(candidate or ""))
            if normalized != "unknown":
                explicit_sources.append(normalized)
        if explicit_sources and local_refs:
            return (
                explicit_sources[0],
                "explicit trust classification with local runtime evidence references",
                ["explicit trust metadata", f"local evidence refs: {len(local_refs)}"],
            )

        if not local_refs:
            return ("unknown", "no documented local runtime evidence references", ["evidence_refs absent"])

        observed_status = str((observed_vs_expected or {}).get("status", "") or "").strip().lower()
        collector_label = str(collector_status or "").strip().lower()
        evidence_level_norm = _normalize_evidence_level(evidence_level)

        verification = payload.get("verification", {}) if isinstance(payload.get("verification"), dict) else {}
        failed_verification_keys = sorted(
            key for key, value in verification.items()
            if key.endswith("_match") and value is False
        )
        if failed_verification_keys:
            return (
                "untrusted",
                "bundle verification check failed with documented runtime evidence",
                [f"failed checks: {', '.join(failed_verification_keys[:3])}", f"local evidence refs: {len(local_refs)}"],
            )

        degraded_collectors = {
            "degraded",
            "partial",
            "collector_error",
            "unsupported",
            "unavailable",
            "no_baseline",
            "unknown",
            "error",
            "failed",
        }
        untrusted_observed_states = {"mismatch", "failed", "tampered", "blocked", "denied"}
        trusted_observed_states = {"matched", "observed", "ok", "pass"}

        if observed_status in untrusted_observed_states:
            return (
                "untrusted",
                "observed-vs-expected runtime evidence reports mismatch",
                [f"observed_vs_expected.status={observed_status}", f"local evidence refs: {len(local_refs)}"],
            )
        if collector_label in degraded_collectors:
            return (
                "degraded",
                "collector runtime evidence indicates degraded observability",
                [f"collector_status={collector_label}", f"local evidence refs: {len(local_refs)}"],
            )
        if evidence_level_norm != "observed":
            return (
                "degraded",
                "runtime evidence is present but not fully observed",
                [f"evidence_level={evidence_level_norm}", f"local evidence refs: {len(local_refs)}"],
            )
        if observed_status in trusted_observed_states or not observed_status:
            return (
                "trusted",
                "documented local runtime evidence with healthy collector state",
                [
                    f"collector_status={collector_label or 'supported'}",
                    f"observed_vs_expected.status={observed_status or 'observed'}",
                    f"local evidence refs: {len(local_refs)}",
                ],
            )
        return (
            "unknown",
            "runtime evidence present but trust conditions are inconclusive",
            [f"collector_status={collector_label or 'unknown'}", f"local evidence refs: {len(local_refs)}"],
        )

    def _trust_attribution_entry(
        self,
        *,
        trust_classification: str,
        basis: str,
        evidence_refs: Sequence[str],
        documentation: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        normalized_classification = self._normalize_trust_classification(trust_classification)
        refs = [
            str(ref).strip()
            for ref in evidence_refs
            if isinstance(ref, str) and str(ref).strip().startswith("local://cleanhouse/")
        ]
        docs = [str(item).strip() for item in (documentation or []) if str(item).strip()]
        core = {
            "trust_classification": normalized_classification,
            "evidence_refs": refs,
            "documentation": docs,
        }
        attribution_hash = _stable_json_hash(core)
        attribution_id = f"trust:{_fingerprint(normalized_classification, attribution_hash)}"
        return {
            **core,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
            "basis": str(basis or "unknown"),
        }

    def _resolve_execution_channel(
        self,
        *,
        actor_type: str,
        source_surface: str,
        payload: Dict[str, Any],
    ) -> str:
        explicit = str(payload.get("execution_channel", "") or "").strip().lower()
        if explicit:
            return explicit
        actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        actor_channel = str(actor.get("execution_channel", "") or "").strip().lower()
        if actor_channel:
            return actor_channel

        normalized_actor = str(actor_type or "").strip().lower()
        normalized_surface = str(source_surface or "").strip().lower()
        tool_identity = str(payload.get("tool_identity", "") or "").strip().lower()

        if normalized_actor == "human" or normalized_surface in {"prompt_context", "auth"}:
            return "human"
        if normalized_actor == "shell" or normalized_surface == "command_observer":
            return "cli"
        if normalized_actor == "process":
            return "process"
        if normalized_actor in {"tool", "agent"} or normalized_surface == "tool_event":
            if any(token in tool_identity for token in ("codex", "cursor", "opencode", "copilot", "agent")):
                return "agent"
            return "cli"
        if normalized_actor in {"provider_connector", "provider"} or normalized_surface in {"provider_import", "api", "domain_observer"}:
            return "api"
        if normalized_actor in {"runtime", "cleanhouse"} or normalized_surface in {
            "approval_queue",
            "rollback",
            "qpb",
            "native_operator_notification",
            "workstation_mutation",
            "snapshot_diff",
            "receipt",
        }:
            return "service"
        if normalized_actor == "operator":
            return "human"
        return "unknown"

    def _artifact_channel_attribution(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        chain_of_custody: Dict[str, Any],
    ) -> Dict[str, Any]:
        hops = chain_of_custody.get("hops", []) if isinstance(chain_of_custody, dict) else []
        preferred_order = ("decision", "enforcement", "intervention", "event", "prompt", "objective")
        by_hop: Dict[str, Dict[str, Any]] = {}
        provenance: list[Dict[str, Any]] = []
        for hop in hops:
            if not isinstance(hop, dict):
                continue
            hop_name = str(hop.get("hop", "") or "")
            channel = hop.get("channel") if isinstance(hop.get("channel"), dict) else {}
            record = {
                "hop": hop_name,
                "execution_channel": str(channel.get("execution_channel", "unknown") or "unknown"),
                "attribution_id": str(channel.get("attribution_id", "") or ""),
                "attribution_hash": str(channel.get("attribution_hash", "") or ""),
                "status": str(channel.get("status", "unknown") or "unknown"),
            }
            provenance.append(record)
            if hop_name and hop_name not in by_hop:
                by_hop[hop_name] = record

        origin_channel = {
            "hop": "unknown",
            "execution_channel": "unknown",
            "attribution_id": "",
            "attribution_hash": "",
            "status": "unknown",
        }
        for hop_name in preferred_order:
            candidate = by_hop.get(hop_name)
            if candidate and candidate.get("execution_channel") and candidate.get("execution_channel") != "unknown":
                origin_channel = candidate
                break

        core = {
            "artifact_type": str(artifact_type or "unknown"),
            "artifact_id": str(artifact_id or ""),
            "origin_channel": origin_channel,
            "provenance": provenance,
        }
        attribution_hash = _stable_json_hash(core)
        attribution_id = f"{artifact_type}_channel_attribution:{_fingerprint(artifact_type, artifact_id, origin_channel.get('attribution_id', ''), attribution_hash)}"
        return {
            **core,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
        }

    def _artifact_trust_attribution(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        chain_of_custody: Dict[str, Any],
    ) -> Dict[str, Any]:
        hops = chain_of_custody.get("hops", []) if isinstance(chain_of_custody, dict) else []
        preferred_order = ("decision", "enforcement", "intervention", "event", "prompt", "objective")
        by_hop: Dict[str, Dict[str, Any]] = {}
        provenance: list[Dict[str, Any]] = []
        for hop in hops:
            if not isinstance(hop, dict):
                continue
            hop_name = str(hop.get("hop", "") or "")
            trust = hop.get("trust") if isinstance(hop.get("trust"), dict) else {}
            record = {
                "hop": hop_name,
                "trust_classification": self._normalize_trust_classification(
                    str(trust.get("trust_classification", "unknown") or "unknown")
                ),
                "attribution_id": str(trust.get("attribution_id", "") or ""),
                "attribution_hash": str(trust.get("attribution_hash", "") or ""),
                "basis": str(trust.get("basis", "") or ""),
            }
            provenance.append(record)
            if hop_name and hop_name not in by_hop:
                by_hop[hop_name] = record

        origin_trust = {
            "hop": "unknown",
            "trust_classification": "unknown",
            "attribution_id": "",
            "attribution_hash": "",
            "basis": "",
        }
        for hop_name in preferred_order:
            candidate = by_hop.get(hop_name)
            if candidate and candidate.get("trust_classification") != "unknown":
                origin_trust = candidate
                break

        core = {
            "artifact_type": str(artifact_type or "unknown"),
            "artifact_id": str(artifact_id or ""),
            "origin_trust": origin_trust,
            "provenance": provenance,
        }
        attribution_hash = _stable_json_hash(core)
        attribution_id = f"{artifact_type}_trust_attribution:{_fingerprint(artifact_type, artifact_id, origin_trust.get('attribution_id', ''), attribution_hash)}"
        return {
            **core,
            "attribution_id": attribution_id,
            "attribution_hash": attribution_hash,
        }

    def _workflow_actor_attribution(
        self,
        proposal: OperationProposalRecord,
        approval: Optional[Dict[str, Any]],
        proposal_ref: str,
        approval_ref: str,
        decision_ref: str,
        outcome_ref: str,
    ) -> Dict[str, Dict[str, Any]]:
        proposal_actor = (
            proposal.metadata.get("proposal_actor")
            if isinstance(proposal.metadata, dict) and isinstance(proposal.metadata.get("proposal_actor"), dict)
            else {}
        )
        proposal_actor_type = str(proposal_actor.get("type", "cleanhouse_mediator") or "cleanhouse_mediator")
        proposal_actor_id = str(proposal_actor.get("id", "cleanhouse:mediator") or "cleanhouse:mediator")

        approval_history = approval.get("history", []) if isinstance(approval, dict) and isinstance(approval.get("history"), list) else []
        created_entry = next(
            (entry for entry in approval_history if isinstance(entry, dict) and str(entry.get("action", "")) == "created"),
            {},
        )
        created_reviewer = str(created_entry.get("reviewer", "") or (approval or {}).get("reviewer", "") or "operator")
        decision_entry = next(
            (
                entry for entry in reversed(approval_history)
                if isinstance(entry, dict) and str(entry.get("action", "")) in {"approved", "rejected", "needs_review", "pending"}
            ),
            {},
        )
        decision_reviewer = str(decision_entry.get("reviewer", "") or created_reviewer or "operator")

        enforcement_actor = (
            proposal.metadata.get("enforcement_actor")
            if isinstance(proposal.metadata, dict) and isinstance(proposal.metadata.get("enforcement_actor"), dict)
            else {}
        )
        enforcement_actor_type = str(enforcement_actor.get("type", "operator") or "operator")
        enforcement_actor_id = str(enforcement_actor.get("id", decision_reviewer or "operator") or decision_reviewer or "operator")

        return {
            "event_detected": self._actor_attribution_entry(
                actor_type=proposal_actor_type,
                actor_id=proposal_actor_id,
                status="observed" if proposal_actor else "inferred",
                basis="operation proposal creation metadata",
                evidence_refs=[proposal_ref],
            ),
            "intervention_requested": self._actor_attribution_entry(
                actor_type="operator",
                actor_id=created_reviewer,
                status="observed" if created_reviewer else "unknown",
                basis="approval queue created reviewer",
                evidence_refs=[approval_ref],
            ),
            "decision_recorded": self._actor_attribution_entry(
                actor_type="operator",
                actor_id=decision_reviewer,
                status="observed" if decision_reviewer else "unknown",
                basis="approval decision reviewer",
                evidence_refs=[decision_ref or approval_ref],
            ),
            "outcome_enforced": self._actor_attribution_entry(
                actor_type=enforcement_actor_type,
                actor_id=enforcement_actor_id,
                status="observed" if proposal.status in {"applied", "undone"} else "inferred",
                basis="operation proposal enforcement metadata",
                evidence_refs=[outcome_ref or proposal_ref],
            ),
        }

    def _workflow_channel_attribution(
        self,
        proposal: OperationProposalRecord,
        approval: Optional[Dict[str, Any]],
        proposal_ref: str,
        approval_ref: str,
        decision_ref: str,
        outcome_ref: str,
    ) -> Dict[str, Dict[str, Any]]:
        proposal_channel = (
            str(proposal.metadata.get("proposal_channel", "") or "")
            if isinstance(proposal.metadata, dict)
            else ""
        ) or "api"
        approval_channel = (
            str((approval or {}).get("metadata", {}).get("approval_channel", "") or "")
            if isinstance((approval or {}).get("metadata"), dict)
            else ""
        ) or "human"
        decision_channel = (
            str((approval or {}).get("metadata", {}).get("decision_channel", "") or "")
            if isinstance((approval or {}).get("metadata"), dict)
            else ""
        ) or approval_channel
        enforcement_channel = (
            str(proposal.metadata.get("enforcement_channel", "") or "")
            if isinstance(proposal.metadata, dict)
            else ""
        ) or decision_channel
        return {
            "event_detected": self._channel_attribution_entry(
                channel=proposal_channel,
                status="observed",
                basis="operation proposal metadata",
                evidence_refs=[proposal_ref],
            ),
            "intervention_requested": self._channel_attribution_entry(
                channel=approval_channel,
                status="observed" if approval_ref else "unknown",
                basis="approval queue metadata",
                evidence_refs=[approval_ref],
            ),
            "decision_recorded": self._channel_attribution_entry(
                channel=decision_channel,
                status="observed" if decision_ref else "inferred",
                basis="approval decision metadata",
                evidence_refs=[decision_ref or approval_ref],
            ),
            "outcome_enforced": self._channel_attribution_entry(
                channel=enforcement_channel,
                status="observed" if proposal.status in {"applied", "undone"} else "inferred",
                basis="operation proposal enforcement metadata",
                evidence_refs=[outcome_ref or proposal_ref],
            ),
        }

    def _workflow_trust_attribution(
        self,
        proposal: OperationProposalRecord,
        approval: Optional[Dict[str, Any]],
        proposal_ref: str,
        approval_ref: str,
        decision_ref: str,
        outcome_ref: str,
    ) -> Dict[str, Dict[str, Any]]:
        decision_value = str((approval or {}).get("status", "") or "").strip().lower()
        event_classification = "trusted" if proposal_ref else "unknown"
        intervention_classification = "trusted" if approval_ref else "unknown"
        if decision_ref:
            decision_classification = "trusted"
        elif decision_value in {"rejected", "needs_review"}:
            decision_classification = "degraded"
        else:
            decision_classification = "unknown"
        if proposal.status in {"applied", "undone"} and outcome_ref:
            outcome_classification = "trusted"
        elif proposal.status in {"approved", "rejected", "pending"}:
            outcome_classification = "degraded"
        else:
            outcome_classification = "unknown"

        return {
            "event_detected": self._trust_attribution_entry(
                trust_classification=event_classification,
                basis="operation proposal runtime record",
                evidence_refs=[proposal_ref],
                documentation=["proposal ref present" if proposal_ref else "proposal ref missing"],
            ),
            "intervention_requested": self._trust_attribution_entry(
                trust_classification=intervention_classification,
                basis="approval queue runtime record",
                evidence_refs=[approval_ref],
                documentation=["approval ref present" if approval_ref else "approval ref missing"],
            ),
            "decision_recorded": self._trust_attribution_entry(
                trust_classification=decision_classification,
                basis="approval decision runtime record",
                evidence_refs=[decision_ref or approval_ref],
                documentation=[
                    f"approval_status={decision_value or 'unknown'}",
                    "decision ref present" if decision_ref else "decision ref missing",
                ],
            ),
            "outcome_enforced": self._trust_attribution_entry(
                trust_classification=outcome_classification,
                basis="proposal outcome runtime record",
                evidence_refs=[outcome_ref or proposal_ref],
                documentation=[
                    f"proposal_status={proposal.status}",
                    "outcome ref present" if outcome_ref else "outcome ref missing",
                ],
            ),
        }

    def _intervention_workflow_from_proposal(
        self,
        proposal: OperationProposalRecord,
        *,
        approval: Optional[Dict[str, Any]] = None,
        receipt_id: Optional[str] = None,
        receipt_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval_id = str((approval or {}).get("id", "") or "")
        approval_status = str((approval or {}).get("status", "") or "")
        proposal_ref = f"local://cleanhouse/operation-proposal/{proposal.id}"
        approval_ref = f"local://cleanhouse/approval-queue/{approval_id}" if approval_id else ""
        decision_ref = (
            f"local://cleanhouse/approval-queue/{approval_id}/decision/{approval_status}"
            if approval_id and approval_status
            else ""
        )
        outcome_ref = f"local://cleanhouse/operation-proposal/{proposal.id}/outcome/{proposal.status}"

        decision_recorded_at = (
            str((approval or {}).get("resolved_at") or "")
            or (proposal.updated_at if proposal.status in {"approved", "rejected", "applied", "undone"} else "")
        )
        outcome_enforced_at = (
            str(proposal.applied_at or proposal.undone_at or "")
            if proposal.status in {"applied", "undone"}
            else ""
        )
        if proposal.status == "pending":
            workflow_status = "intervention_requested"
        elif proposal.status in {"approved", "rejected"}:
            workflow_status = "decision_recorded"
        elif proposal.status in {"applied", "undone"}:
            workflow_status = "outcome_enforced"
        else:
            workflow_status = proposal.status

        event_evidence_refs = self._local_evidence_refs(proposal.evidence_refs)
        approval_evidence_refs = self._local_evidence_refs((approval or {}).get("evidence_refs", []))
        stage_refs = [proposal_ref, approval_ref, decision_ref, outcome_ref]
        all_refs = self._local_evidence_refs([*event_evidence_refs, *approval_evidence_refs, *stage_refs])
        actor_attribution = self._workflow_actor_attribution(
            proposal,
            approval,
            proposal_ref,
            approval_ref,
            decision_ref,
            outcome_ref,
        )
        channel_attribution = self._workflow_channel_attribution(
            proposal,
            approval,
            proposal_ref,
            approval_ref,
            decision_ref,
            outcome_ref,
        )
        trust_attribution = self._workflow_trust_attribution(
            proposal,
            approval,
            proposal_ref,
            approval_ref,
            decision_ref,
            outcome_ref,
        )

        core = {
            "schema": "cleanhouse.intervention_workflow.v1",
            "session_id": proposal.session_id,
            "objective_id": proposal.objective_id,
            "proposal_id": proposal.id,
            "proposal_type": proposal.proposal_type,
            "approval_id": approval_id,
            "approval_status": approval_status,
            "decision": approval_status or ("approved" if proposal.status in {"approved", "applied", "undone"} else proposal.status),
            "status": workflow_status,
            "event_detected_at": proposal.created_at,
            "intervention_requested_at": str((approval or {}).get("created_at") or proposal.created_at),
            "decision_recorded_at": decision_recorded_at or None,
            "outcome_enforced_at": outcome_enforced_at or None,
            "receipt_id": str(receipt_id or ""),
            "receipt_generated_at": str(receipt_timestamp or ""),
            "stage_refs": {
                "event_detected": proposal_ref,
                "intervention_requested": approval_ref,
                "decision_recorded": decision_ref,
                "outcome_enforced": outcome_ref,
            },
            "outcome": {
                "status": proposal.status,
                "applied_at": proposal.applied_at,
                "undone_at": proposal.undone_at,
                "rollback_id": proposal.rollback_id,
            },
            "actor_attribution": actor_attribution,
            "channel_attribution": channel_attribution,
            "trust_attribution": trust_attribution,
            "evidence_refs": all_refs,
        }
        proof_hash = _stable_json_hash(core)
        workflow_id = f"intervention_workflow:{_fingerprint(proposal.id, approval_id, proof_hash)}"
        return {
            **core,
            "workflow_id": workflow_id,
            "proof_hash": proof_hash,
        }

    def get_intervention_workflows(
        self,
        *,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        workflows: list[Dict[str, Any]] = []
        for proposal in self._all_operation_proposals():
            if session_id and proposal.session_id != session_id:
                continue
            approval = self._approval_for_operation_proposal(proposal.id, proposal.session_id)
            workflows.append(self._intervention_workflow_from_proposal(proposal, approval=approval))
        if status:
            workflows = [row for row in workflows if row.get("status") == status]
        workflows.sort(key=lambda row: row.get("event_detected_at", ""), reverse=True)
        return {"status": "ok", "workflows": workflows, "count": len(workflows)}

    def _compose_chain_of_custody(
        self,
        *,
        session_id: str,
        objective_id: str,
        prompt_id: str,
        receipt_id: str,
        receipt_timestamp: str,
        events: Sequence[Dict[str, Any]],
        intervention_workflows: Sequence[Dict[str, Any]],
        replay_ref: str = "",
        replay_generated_at: str = "",
        bundle_ref: str = "",
        bundle_generated_at: str = "",
    ) -> Dict[str, Any]:
        objective_ref = f"local://cleanhouse/objective/{objective_id}" if objective_id else ""
        prompt_ref = f"local://cleanhouse/prompt/{prompt_id}" if prompt_id else ""
        receipt_ref = f"local://cleanhouse/receipt/{receipt_id}" if receipt_id else ""

        event_ref = ""
        event_timestamp = ""
        if isinstance(events, list):
            for entry in events:
                if not isinstance(entry, dict):
                    continue
                event_id = str(entry.get("event_id") or entry.get("id") or "").strip()
                if event_id:
                    event_ref = f"local://cleanhouse/timeline/{event_id}"
                    event_timestamp = str(entry.get("timestamp", "") or "")
                    break

        workflow = intervention_workflows[0] if intervention_workflows else {}
        stage_refs = workflow.get("stage_refs", {}) if isinstance(workflow, dict) else {}
        stage_actor_attribution = (
            workflow.get("actor_attribution", {})
            if isinstance(workflow, dict) and isinstance(workflow.get("actor_attribution"), dict)
            else {}
        )
        stage_channel_attribution = (
            workflow.get("channel_attribution", {})
            if isinstance(workflow, dict) and isinstance(workflow.get("channel_attribution"), dict)
            else {}
        )
        stage_trust_attribution = (
            workflow.get("trust_attribution", {})
            if isinstance(workflow, dict) and isinstance(workflow.get("trust_attribution"), dict)
            else {}
        )
        intervention_ref = str(stage_refs.get("intervention_requested", "") or "")
        decision_ref = str(stage_refs.get("decision_recorded", "") or "")
        enforcement_ref = str(stage_refs.get("outcome_enforced", "") or "")
        intervention_timestamp = str(workflow.get("intervention_requested_at", "") or "")
        decision_timestamp = str(workflow.get("decision_recorded_at", "") or "")
        enforcement_timestamp = str(workflow.get("outcome_enforced_at", "") or "")

        event_actor_type = "unknown"
        event_actor_id = ""
        event_actor_basis = "timeline event actor metadata"
        event_channel = "unknown"
        event_trust_attribution: Dict[str, Any] = {}
        if isinstance(events, list):
            for entry in events:
                if not isinstance(entry, dict):
                    continue
                data = entry.get("data", {}) if isinstance(entry.get("data"), dict) else {}
                actor = data.get("actor") if isinstance(data.get("actor"), dict) else {}
                actor_type = str(
                    actor.get("actor_type", "")
                    or data.get("actor_type", "")
                    or ""
                )
                actor_id = str(
                    actor.get("actor_id", "")
                    or data.get("actor_id", "")
                    or ""
                )
                if actor_type:
                    event_actor_type = actor_type
                    event_actor_id = actor_id
                    event_channel = str(
                        (data.get("channel", {}) if isinstance(data.get("channel"), dict) else {}).get("execution_channel", "")
                        or data.get("execution_channel", "")
                        or "unknown"
                    )
                    event_trust_attribution = (
                        copy.deepcopy(data.get("trust"))
                        if isinstance(data.get("trust"), dict)
                        else {}
                    )
                    break

        hops = [
            {
                "hop": "prompt",
                "timestamp": "",
                "ref": prompt_ref,
                "actor": self._actor_attribution_entry(
                    actor_type="human",
                    actor_id=prompt_id,
                    status="observed" if prompt_id else "unknown",
                    basis="prompt record identifier",
                    evidence_refs=[prompt_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel="human",
                    status="observed" if prompt_ref else "unknown",
                    basis="prompt source channel",
                    evidence_refs=[prompt_ref],
                ),
                "trust": self._trust_attribution_entry(
                    trust_classification="trusted" if prompt_ref else "unknown",
                    basis="prompt provenance runtime record",
                    evidence_refs=[prompt_ref],
                    documentation=["prompt ref present" if prompt_ref else "prompt ref missing"],
                ),
            },
            {
                "hop": "objective",
                "timestamp": "",
                "ref": objective_ref,
                "actor": self._actor_attribution_entry(
                    actor_type="human",
                    actor_id=objective_id,
                    status="observed" if objective_id else "unknown",
                    basis="objective identifier",
                    evidence_refs=[objective_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel="human",
                    status="observed" if objective_ref else "unknown",
                    basis="objective declaration channel",
                    evidence_refs=[objective_ref],
                ),
                "trust": self._trust_attribution_entry(
                    trust_classification="trusted" if objective_ref else "unknown",
                    basis="objective provenance runtime record",
                    evidence_refs=[objective_ref],
                    documentation=["objective ref present" if objective_ref else "objective ref missing"],
                ),
            },
            {
                "hop": "event",
                "timestamp": event_timestamp,
                "ref": event_ref,
                "actor": self._actor_attribution_entry(
                    actor_type=event_actor_type,
                    actor_id=event_actor_id,
                    status="observed" if (event_ref and event_actor_type) else "unknown",
                    basis=event_actor_basis,
                    evidence_refs=[event_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel=event_channel,
                    status="observed" if event_ref else "unknown",
                    basis="timeline event channel metadata",
                    evidence_refs=[event_ref],
                ),
                "trust": copy.deepcopy(event_trust_attribution)
                if event_trust_attribution
                else self._trust_attribution_entry(
                    trust_classification="unknown",
                    basis="timeline event trust metadata unavailable",
                    evidence_refs=[event_ref],
                    documentation=["event trust metadata missing"],
                ),
            },
            {
                "hop": "intervention",
                "timestamp": intervention_timestamp,
                "ref": intervention_ref,
                "actor": copy.deepcopy(stage_actor_attribution.get("intervention_requested", {}))
                if isinstance(stage_actor_attribution.get("intervention_requested"), dict)
                else self._actor_attribution_entry(
                    actor_type="operator",
                    actor_id="",
                    status="unknown",
                    basis="intervention attribution unavailable",
                    evidence_refs=[intervention_ref],
                ),
                "channel": copy.deepcopy(stage_channel_attribution.get("intervention_requested", {}))
                if isinstance(stage_channel_attribution.get("intervention_requested"), dict)
                else self._channel_attribution_entry(
                    channel="unknown",
                    status="unknown",
                    basis="intervention channel attribution unavailable",
                    evidence_refs=[intervention_ref],
                ),
                "trust": copy.deepcopy(stage_trust_attribution.get("intervention_requested", {}))
                if isinstance(stage_trust_attribution.get("intervention_requested"), dict)
                else self._trust_attribution_entry(
                    trust_classification="unknown",
                    basis="intervention trust attribution unavailable",
                    evidence_refs=[intervention_ref],
                    documentation=["intervention trust attribution missing"],
                ),
            },
            {
                "hop": "decision",
                "timestamp": decision_timestamp,
                "ref": decision_ref,
                "actor": copy.deepcopy(stage_actor_attribution.get("decision_recorded", {}))
                if isinstance(stage_actor_attribution.get("decision_recorded"), dict)
                else self._actor_attribution_entry(
                    actor_type="operator",
                    actor_id="",
                    status="unknown",
                    basis="decision attribution unavailable",
                    evidence_refs=[decision_ref],
                ),
                "channel": copy.deepcopy(stage_channel_attribution.get("decision_recorded", {}))
                if isinstance(stage_channel_attribution.get("decision_recorded"), dict)
                else self._channel_attribution_entry(
                    channel="unknown",
                    status="unknown",
                    basis="decision channel attribution unavailable",
                    evidence_refs=[decision_ref],
                ),
                "trust": copy.deepcopy(stage_trust_attribution.get("decision_recorded", {}))
                if isinstance(stage_trust_attribution.get("decision_recorded"), dict)
                else self._trust_attribution_entry(
                    trust_classification="unknown",
                    basis="decision trust attribution unavailable",
                    evidence_refs=[decision_ref],
                    documentation=["decision trust attribution missing"],
                ),
            },
            {
                "hop": "enforcement",
                "timestamp": enforcement_timestamp,
                "ref": enforcement_ref,
                "actor": copy.deepcopy(stage_actor_attribution.get("outcome_enforced", {}))
                if isinstance(stage_actor_attribution.get("outcome_enforced"), dict)
                else self._actor_attribution_entry(
                    actor_type="operator",
                    actor_id="",
                    status="unknown",
                    basis="enforcement attribution unavailable",
                    evidence_refs=[enforcement_ref],
                ),
                "channel": copy.deepcopy(stage_channel_attribution.get("outcome_enforced", {}))
                if isinstance(stage_channel_attribution.get("outcome_enforced"), dict)
                else self._channel_attribution_entry(
                    channel="unknown",
                    status="unknown",
                    basis="enforcement channel attribution unavailable",
                    evidence_refs=[enforcement_ref],
                ),
                "trust": copy.deepcopy(stage_trust_attribution.get("outcome_enforced", {}))
                if isinstance(stage_trust_attribution.get("outcome_enforced"), dict)
                else self._trust_attribution_entry(
                    trust_classification="unknown",
                    basis="enforcement trust attribution unavailable",
                    evidence_refs=[enforcement_ref],
                    documentation=["enforcement trust attribution missing"],
                ),
            },
            {
                "hop": "receipt",
                "timestamp": receipt_timestamp,
                "ref": receipt_ref,
                "actor": self._actor_attribution_entry(
                    actor_type="cleanhouse",
                    actor_id="cleanhouse:receipt",
                    status="observed" if receipt_ref else "unknown",
                    basis="receipt artifact generated by adapter",
                    evidence_refs=[receipt_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel="service",
                    status="observed" if receipt_ref else "unknown",
                    basis="receipt generated by adapter service",
                    evidence_refs=[receipt_ref],
                ),
                "trust": self._trust_attribution_entry(
                    trust_classification="trusted" if receipt_ref else "unknown",
                    basis="receipt artifact generated by monitored service runtime",
                    evidence_refs=[receipt_ref],
                    documentation=["receipt ref present" if receipt_ref else "receipt ref missing"],
                ),
            },
            {
                "hop": "replay",
                "timestamp": replay_generated_at,
                "ref": replay_ref,
                "actor": self._actor_attribution_entry(
                    actor_type="cleanhouse",
                    actor_id="cleanhouse:replay",
                    status="observed" if replay_ref else "unknown",
                    basis="replay artifact generated by adapter",
                    evidence_refs=[replay_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel="service",
                    status="observed" if replay_ref else "unknown",
                    basis="replay generated by adapter service",
                    evidence_refs=[replay_ref],
                ),
                "trust": self._trust_attribution_entry(
                    trust_classification="trusted" if replay_ref else "unknown",
                    basis="replay artifact generated by monitored service runtime",
                    evidence_refs=[replay_ref],
                    documentation=["replay ref present" if replay_ref else "replay ref missing"],
                ),
            },
            {
                "hop": "bundle",
                "timestamp": bundle_generated_at,
                "ref": bundle_ref,
                "actor": self._actor_attribution_entry(
                    actor_type="cleanhouse",
                    actor_id="cleanhouse:bundle",
                    status="observed" if bundle_ref else "unknown",
                    basis="bundle artifact generated by adapter",
                    evidence_refs=[bundle_ref],
                ),
                "channel": self._channel_attribution_entry(
                    channel="service",
                    status="observed" if bundle_ref else "unknown",
                    basis="bundle generated by adapter service",
                    evidence_refs=[bundle_ref],
                ),
                "trust": self._trust_attribution_entry(
                    trust_classification="trusted" if bundle_ref else "unknown",
                    basis="bundle artifact generated by monitored service runtime",
                    evidence_refs=[bundle_ref],
                    documentation=["bundle ref present" if bundle_ref else "bundle ref missing"],
                ),
            },
        ]
        for hop in hops:
            ref = str(hop.get("ref", "") or "")
            hop["traceable"] = ref.startswith("local://cleanhouse/")

        missing_hops = [str(hop.get("hop", "")) for hop in hops if not hop.get("traceable")]
        core = {
            "schema": "cleanhouse.chain_of_custody.v1",
            "session_id": session_id,
            "objective_id": objective_id,
            "receipt_id": receipt_id,
            "hop_order": [str(hop.get("hop", "")) for hop in hops],
            "hops": hops,
            "traceable_hop_count": sum(1 for hop in hops if hop.get("traceable")),
            "missing_hops": missing_hops,
            "fully_traceable": len(missing_hops) == 0,
        }
        proof_hash = _stable_json_hash(core)
        custody_id = f"custody:{_fingerprint(session_id, receipt_id, proof_hash)}"
        return {
            **core,
            "custody_id": custody_id,
            "proof_hash": proof_hash,
        }

    def create_operation_proposal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            return {"status": "error", "message": "session_id is required"}
        proposal_type = str(data.get("proposal_type", "mediator")).strip() or "mediator"
        operations = copy.deepcopy(data.get("operations", [])) if isinstance(data.get("operations"), list) else []
        if not operations:
            return {"status": "error", "message": "operations are required"}
        reason = str(data.get("reason", "") or "").strip()
        now = _now_iso()
        proposal_id = f"proposal:{_fingerprint(session_id, proposal_type, json.dumps(operations, sort_keys=True, default=str), now)}"
        objective_id = str(data.get("objective_id", "")).strip() or self._objective_id_for_session(session_id)
        evidence_refs = self._local_evidence_refs(data.get("evidence_refs", []))
        metadata = copy.deepcopy(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {}
        proposal_actor = data.get("actor")
        if isinstance(proposal_actor, dict):
            metadata["proposal_actor"] = {
                "type": str(proposal_actor.get("type", "operator") or "operator"),
                "id": str(proposal_actor.get("id", "operator") or "operator"),
            }
        else:
            metadata["proposal_actor"] = {
                "type": "operator",
                "id": str(proposal_actor or "operator"),
            }
        proposal_channel = str(
            data.get("execution_channel")
            or metadata.get("execution_channel")
            or ("api" if str(data.get("source", "") or "").strip() else "")
            or "api"
        ).strip().lower()
        metadata["proposal_channel"] = proposal_channel
        record = OperationProposalRecord(
            id=proposal_id,
            proposal_type=proposal_type,
            session_id=session_id,
            objective_id=objective_id,
            status="pending",
            reason=reason or f"{proposal_type} proposal pending confirmation",
            target_scope=copy.deepcopy(data.get("target_scope", {})) if isinstance(data.get("target_scope"), dict) else {},
            operations=tuple(operations),
            created_at=now,
            updated_at=now,
            applied_at=None,
            undone_at=None,
            evidence_refs=tuple(evidence_refs),
            rollback_id=None,
            metadata=metadata,
        )
        with self._lock:
            self._operation_proposals[record.id] = record
        self._persist_operation_proposal(record)
        approval_result = self.create_approval_queue_item({
            "session_id": session_id,
            "requested_action": f"keep changes? {proposal_type}",
            "reason": record.reason,
            "objective_id": objective_id,
            "evidence_refs": list(evidence_refs),
            "source": "mediator",
            "metadata": {
                "proposal_id": record.id,
                "proposal_type": proposal_type,
                "confirm_required": True,
            },
        })
        approval = approval_result.get("approval") if isinstance(approval_result, dict) else None
        intervention_workflow = self._intervention_workflow_from_proposal(record, approval=approval if isinstance(approval, dict) else None)
        return {
            "status": "ok",
            "proposal": record.to_dict(),
            "intervention_workflow": intervention_workflow,
        }

    def _apply_operation_proposal(self, proposal: OperationProposalRecord, repo_path: str) -> Dict[str, Any]:
        repo_root = self._resolve_repo_root(repo_path)
        undo_records: list[Dict[str, Any]] = []
        applied_ops: list[Dict[str, Any]] = []
        for operation in proposal.operations:
            if not isinstance(operation, dict):
                continue
            op = str(operation.get("op", "")).strip().lower()
            rel_path = str(operation.get("path", "")).strip()
            if op in {"write_file", "delete_file", "move_file"} and not rel_path:
                raise ValueError(f"{op} requires path")
            if op == "write_file":
                target = self._resolve_scoped_path(repo_root, rel_path)
                before_exists = target.exists()
                before_content_b64 = base64.b64encode(target.read_bytes()).decode("ascii") if before_exists and target.is_file() else None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(operation.get("content", "")), encoding="utf-8")
                undo_records.append({
                    "op": "write_file",
                    "path": rel_path,
                    "before_exists": before_exists,
                    "before_content_b64": before_content_b64,
                })
                applied_ops.append({"op": op, "path": rel_path})
            elif op == "delete_file":
                target = self._resolve_scoped_path(repo_root, rel_path)
                before_exists = target.exists()
                before_content_b64 = base64.b64encode(target.read_bytes()).decode("ascii") if before_exists and target.is_file() else None
                if before_exists and target.is_file():
                    target.unlink()
                undo_records.append({
                    "op": "delete_file",
                    "path": rel_path,
                    "before_exists": before_exists,
                    "before_content_b64": before_content_b64,
                })
                applied_ops.append({"op": op, "path": rel_path})
            elif op == "move_file":
                src = self._resolve_scoped_path(repo_root, rel_path)
                dst_rel = str(operation.get("dest_path", "")).strip()
                dst = self._resolve_scoped_path(repo_root, dst_rel)
                if not src.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
                undo_records.append({"op": "move_file", "path": dst_rel, "dest_path": rel_path})
                applied_ops.append({"op": op, "path": rel_path, "dest_path": dst_rel})
            elif op == "mkdir":
                target = self._resolve_scoped_path(repo_root, rel_path)
                existed = target.exists()
                target.mkdir(parents=True, exist_ok=True)
                undo_records.append({"op": "mkdir", "path": rel_path, "before_exists": existed})
                applied_ops.append({"op": op, "path": rel_path})
        return {"undo_records": undo_records, "applied_ops": applied_ops}

    def resolve_operation_proposal(self, proposal_id: str, decision: str, data: Dict[str, Any]) -> Dict[str, Any]:
        decision = str(decision or "").strip().lower()
        if decision not in {"approve", "reject"}:
            return {"status": "error", "message": "decision must be approve or reject"}
        proposal = self._operation_proposal_by_id(str(proposal_id or "").strip())
        if proposal is None:
            return {"status": "not_found", "message": f"proposal not found: {proposal_id}"}
        if proposal.status not in {"pending", "approved"}:
            return {"status": "error", "message": f"proposal state does not allow decision: {proposal.status}"}
        approval = self._approval_for_operation_proposal(proposal.id, proposal.session_id)
        if approval is None:
            return {"status": "error", "message": "proposal requires an approval queue item before decision"}
        approval_status = str(approval.get("status", "") or "")
        target_approval_status = "approved" if decision == "approve" else "rejected"
        if approval_status in {"approved", "rejected"} and approval_status != target_approval_status:
            return {
                "status": "error",
                "message": f"approval status conflict: approval is {approval_status}, proposal decision requested {target_approval_status}",
            }
        reviewer = str(data.get("actor", "operator")).strip() or "operator"
        approval_note = str(data.get("approval_note", data.get("note", "")) or "").strip()
        if approval_status != target_approval_status:
            approval_result = self.resolve_approval_queue_item(
                approval_id=str(approval.get("id", "")),
                status=target_approval_status,
                note=approval_note,
                reviewer=reviewer,
            )
            if approval_result.get("status") != "ok":
                return {
                    "status": "error",
                    "message": f"failed to resolve linked approval: {approval_result.get('message', 'unknown error')}",
                }
            approval = approval_result.get("approval", approval)
        now = _now_iso()
        updated_status = "rejected" if decision == "reject" else "approved"
        applied_at = proposal.applied_at
        rollback_id = proposal.rollback_id
        metadata = copy.deepcopy(proposal.metadata)
        metadata["decision_actor"] = {"type": "operator", "id": reviewer}
        decision_channel = str(data.get("execution_channel") or metadata.get("decision_channel") or "human").strip().lower()
        metadata["decision_channel"] = decision_channel
        if decision == "approve":
            if not bool(data.get("confirm", False)):
                return {"status": "error", "message": "confirm=true is required to apply proposal"}
            repo_path = str(data.get("repo_path") or metadata.get("repo_path") or "").strip()
            if not repo_path:
                return {"status": "error", "message": "repo_path is required"}
            apply_outcome = self._apply_operation_proposal(proposal, repo_path)
            updated_status = "applied"
            applied_at = now
            rollback_id = rollback_id or f"op_rollback:{_fingerprint(proposal.id, now)}"
            metadata["undo_records"] = apply_outcome["undo_records"]
            metadata["applied_ops"] = apply_outcome["applied_ops"]
            metadata["repo_path"] = repo_path
            metadata["enforcement_actor"] = {"type": "operator", "id": reviewer}
            metadata["enforcement_channel"] = decision_channel
        updated = OperationProposalRecord(
            id=proposal.id,
            proposal_type=proposal.proposal_type,
            session_id=proposal.session_id,
            objective_id=proposal.objective_id,
            status=updated_status,
            reason=proposal.reason,
            target_scope=proposal.target_scope,
            operations=proposal.operations,
            created_at=proposal.created_at,
            updated_at=now,
            applied_at=applied_at,
            undone_at=proposal.undone_at,
            evidence_refs=proposal.evidence_refs,
            rollback_id=rollback_id,
            metadata=metadata,
        )
        with self._lock:
            self._operation_proposals[updated.id] = updated
        self._persist_operation_proposal(updated)
        workflow = self._intervention_workflow_from_proposal(updated, approval=approval if isinstance(approval, dict) else None)
        return {"status": "ok", "proposal": updated.to_dict(), "intervention_workflow": workflow}

    def undo_operation_proposal(self, proposal_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        proposal = self._operation_proposal_by_id(str(proposal_id or "").strip())
        if proposal is None:
            return {"status": "not_found", "message": f"proposal not found: {proposal_id}"}
        if proposal.status != "applied":
            return {"status": "error", "message": "only applied proposals can be undone"}
        metadata = copy.deepcopy(proposal.metadata)
        repo_path = str(data.get("repo_path") or metadata.get("repo_path") or "").strip()
        if not repo_path:
            return {"status": "error", "message": "repo_path is required"}
        repo_root = self._resolve_repo_root(repo_path)
        undo_records = metadata.get("undo_records", [])
        if not isinstance(undo_records, list):
            undo_records = []
        for record in reversed(undo_records):
            if not isinstance(record, dict):
                continue
            op = str(record.get("op", "")).strip()
            rel_path = str(record.get("path", "")).strip()
            if op == "write_file":
                target = self._resolve_scoped_path(repo_root, rel_path)
                if record.get("before_exists"):
                    content = record.get("before_content_b64")
                    if content:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(base64.b64decode(content.encode("ascii")))
                elif target.exists():
                    target.unlink()
            elif op == "delete_file":
                target = self._resolve_scoped_path(repo_root, rel_path)
                if record.get("before_exists"):
                    content = record.get("before_content_b64")
                    if content:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(base64.b64decode(content.encode("ascii")))
            elif op == "move_file":
                src = self._resolve_scoped_path(repo_root, rel_path)
                dst = self._resolve_scoped_path(repo_root, str(record.get("dest_path", "")).strip())
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.rename(dst)
            elif op == "mkdir":
                target = self._resolve_scoped_path(repo_root, rel_path)
                if not record.get("before_exists") and target.exists():
                    try:
                        target.rmdir()
                    except OSError:
                        pass
        now = _now_iso()
        actor_value = str(data.get("actor", "operator") or "operator")
        metadata["enforcement_actor"] = {"type": "operator", "id": actor_value}
        updated = OperationProposalRecord(
            id=proposal.id,
            proposal_type=proposal.proposal_type,
            session_id=proposal.session_id,
            objective_id=proposal.objective_id,
            status="undone",
            reason=proposal.reason,
            target_scope=proposal.target_scope,
            operations=proposal.operations,
            created_at=proposal.created_at,
            updated_at=now,
            applied_at=proposal.applied_at,
            undone_at=now,
            evidence_refs=proposal.evidence_refs,
            rollback_id=proposal.rollback_id,
            metadata=metadata,
        )
        with self._lock:
            self._operation_proposals[updated.id] = updated
        self._persist_operation_proposal(updated)
        approval = self._approval_for_operation_proposal(updated.id, updated.session_id)
        workflow = self._intervention_workflow_from_proposal(updated, approval=approval if isinstance(approval, dict) else None)
        return {"status": "ok", "proposal": updated.to_dict(), "intervention_workflow": workflow}

    def create_auto_sort_proposal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        repo_path = str(data.get("repo_path", "")).strip()
        target_dir = str(data.get("target_dir", ".")).strip() or "."
        if not session_id or not repo_path:
            return {"status": "error", "message": "session_id and repo_path are required"}
        root = self._resolve_repo_root(repo_path)
        scan_root = self._resolve_scoped_path(root, target_dir)
        if not scan_root.exists() or not scan_root.is_dir():
            return {"status": "error", "message": "target_dir must be an existing directory"}
        operations: list[Dict[str, Any]] = []
        for entry in sorted(scan_root.iterdir()):
            if not entry.is_file():
                continue
            suffix = entry.suffix.lower().lstrip(".") or "misc"
            dst_dir = entry.parent / f"group_{suffix}"
            dst = dst_dir / entry.name
            rel_src = str(entry.relative_to(root))
            rel_dst = str(dst.relative_to(root))
            operations.append({"op": "mkdir", "path": str(dst_dir.relative_to(root))})
            operations.append({"op": "move_file", "path": rel_src, "dest_path": rel_dst})
        if not operations:
            return {"status": "ok", "proposal": None, "message": "no sortable files found"}
        return self.create_operation_proposal({
            "session_id": session_id,
            "objective_id": data.get("objective_id"),
            "proposal_type": "auto_sort",
            "reason": "auto-sort proposal grouped files by extension",
            "operations": operations,
            "target_scope": {"repo_path": str(root), "target_dir": target_dir},
            "metadata": {"repo_path": str(root)},
            "evidence_refs": [f"local://cleanhouse/auto-sort/{_fingerprint(str(root), target_dir)}"],
        })

    def create_cleaner_proposal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(data.get("session_id", "")).strip()
        repo_path = str(data.get("repo_path", "")).strip()
        target_dir = str(data.get("target_dir", ".")).strip() or "."
        if not session_id or not repo_path:
            return {"status": "error", "message": "session_id and repo_path are required"}
        root = self._resolve_repo_root(repo_path)
        scan_root = self._resolve_scoped_path(root, target_dir)
        if not scan_root.exists() or not scan_root.is_dir():
            return {"status": "error", "message": "target_dir must be an existing directory"}
        operations: list[Dict[str, Any]] = []
        for path in sorted(scan_root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith((".tmp", ".bak", ".swp")) or path.name == ".DS_Store":
                operations.append({"op": "delete_file", "path": str(path.relative_to(root))})
        if not operations:
            return {"status": "ok", "proposal": None, "message": "no cleaner candidates found"}
        return self.create_operation_proposal({
            "session_id": session_id,
            "objective_id": data.get("objective_id"),
            "proposal_type": "cleaner",
            "reason": "universal cleaner proposal for temporary artifacts",
            "operations": operations,
            "target_scope": {"repo_path": str(root), "target_dir": target_dir},
            "metadata": {"repo_path": str(root)},
            "evidence_refs": [f"local://cleanhouse/cleaner/{_fingerprint(str(root), target_dir)}"],
        })

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
                if (
                    approval.session_id == session_id
                    and approval.metadata.get("policy_id") == policy_id
                    and approval.metadata.get("receipt_id") == receipt_id
                ):
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
                "enforcement_required": True,
                "enforcement_action": "block_scope_expansion_until_review",
                "boundary_type": "scope_authorization",
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
        scope_enforcement = self._build_scope_enforcement(
            session_id=session_id,
            objective_id=str(objective_id or ""),
            receipt_id=receipt_id,
            declared_scope=declared_scope,
            scope_analysis=scope_analysis,
            policy_approval=policy_approval if isinstance(policy_approval, dict) else None,
            evidence_refs=approval_seed_refs,
        )
        scope_enforcement["mediation_events"] = self._emit_scope_enforcement_mediation_event(
            session_id=session_id,
            objective_id=str(objective_id or ""),
            receipt_id=receipt_id,
            scope_enforcement=scope_enforcement,
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
        for mediation_event in (
            scope_enforcement.get("mediation_events", [])
            if isinstance(scope_enforcement.get("mediation_events"), list)
            else []
        ):
            if not isinstance(mediation_event, dict):
                continue
            event_ref = str(mediation_event.get("event_ref", "") or "")
            if event_ref:
                evidence_index.append({
                    "ref": event_ref,
                    "source": "scope_enforcement_mediation",
                    "label": str(mediation_event.get("status", "enforceable") or "enforceable"),
                })
        for deviation in (
            scope_enforcement.get("deviation_records", [])
            if isinstance(scope_enforcement.get("deviation_records"), list)
            else []
        ):
            if not isinstance(deviation, dict):
                continue
            deviation_ref = f"local://cleanhouse/scope-deviation/{deviation.get('id', '')}"
            evidence_index.append({
                "ref": deviation_ref,
                "source": "scope_enforcement_deviation",
                "label": str(deviation.get("status", "deviation") or "deviation"),
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
        for action_gap in self._unsupported_shell_action_gaps(t_entries):
            if not any(
                gap.get("event_id") == action_gap.get("event_id")
                and gap.get("source") == action_gap.get("source")
                for gap in gaps
            ):
                gaps.append(action_gap)

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
        intervention_workflows = [
            self._intervention_workflow_from_proposal(
                proposal,
                approval=self._approval_for_operation_proposal(proposal.id, proposal.session_id),
                receipt_id=receipt_id,
                receipt_timestamp=now,
            )
            for proposal in self._all_operation_proposals()
            if proposal.session_id == session_id
        ]
        chain_of_custody = self._compose_chain_of_custody(
            session_id=session_id,
            objective_id=str(objective_id or ""),
            prompt_id=str(prompt_id or ""),
            receipt_id=receipt_id,
            receipt_timestamp=now,
            events=t_entries,
            intervention_workflows=intervention_workflows,
        )
        actor_attribution = self._artifact_actor_attribution(
            artifact_type="receipt",
            artifact_id=receipt_id,
            chain_of_custody=chain_of_custody,
        )
        channel_attribution = self._artifact_channel_attribution(
            artifact_type="receipt",
            artifact_id=receipt_id,
            chain_of_custody=chain_of_custody,
        )
        trust_attribution = self._artifact_trust_attribution(
            artifact_type="receipt",
            artifact_id=receipt_id,
            chain_of_custody=chain_of_custody,
        )

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
            "scope_enforcement": scope_enforcement,
            "intervention_workflows": intervention_workflows,
            "chain_of_custody": chain_of_custody,
            "actor_attribution": actor_attribution,
            "channel_attribution": channel_attribution,
            "trust_attribution": trust_attribution,
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
            scope_enforcement=scope_enforcement,
            intervention_workflows=tuple(intervention_workflows),
            chain_of_custody=chain_of_custody,
            actor_attribution=actor_attribution,
            channel_attribution=channel_attribution,
            trust_attribution=trust_attribution,
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
            "scope_enforcement": scope_enforcement,
            "intervention_workflows": intervention_workflows,
            "chain_of_custody": chain_of_custody,
            "actor_attribution": actor_attribution,
            "channel_attribution": channel_attribution,
            "trust_attribution": trust_attribution,
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
        receipt_refs = self._receipt_local_evidence_refs(result)
        self._ensure_rollback_needed_notification(
            session_id=session_id,
            objective_id=objective_id or None,
            receipt_id=receipt.id,
            rollback_state=rollback_state,
            policy_approval=policy_approval,
            evidence_refs=receipt_refs,
        )
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
        custody = self._compose_chain_of_custody(
            session_id=session_id,
            objective_id=str((receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}).get("objective_id", "") or ""),
            prompt_id=str((receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}).get("prompt_id", "") or ""),
            receipt_id=receipt_id,
            receipt_timestamp=str(receipt.get("timestamp", "") or ""),
            events=receipt.get("events", []) if isinstance(receipt.get("events"), list) else [],
            intervention_workflows=receipt.get("intervention_workflows", []) if isinstance(receipt.get("intervention_workflows"), list) else [],
            replay_ref=f"local://cleanhouse/receipt-replay/{receipt_id}",
            replay_generated_at=str(receipt.get("timestamp", "") or ""),
        )
        actor_attribution = self._artifact_actor_attribution(
            artifact_type="replay",
            artifact_id=receipt_id,
            chain_of_custody=custody,
        )
        channel_attribution = self._artifact_channel_attribution(
            artifact_type="replay",
            artifact_id=receipt_id,
            chain_of_custody=custody,
        )
        trust_attribution = self._artifact_trust_attribution(
            artifact_type="replay",
            artifact_id=receipt_id,
            chain_of_custody=custody,
        )
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
            "scope_enforcement": receipt.get("scope_enforcement", {}),
            "intervention_workflows": receipt.get("intervention_workflows", []),
            "chain_of_custody": custody,
            "approval_state": approval_state,
            "approval_history": approval_history,
            "evidence_chain": evidence_chain,
            "actor_attribution": actor_attribution,
            "channel_attribution": channel_attribution,
            "trust_attribution": trust_attribution,
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
            "scope_enforcement": receipt.get("scope_enforcement", {}),
            "chain_of_custody": custody,
            "actor_attribution": actor_attribution,
            "channel_attribution": channel_attribution,
            "trust_attribution": trust_attribution,
            "replay": replay_core,
            "integrity": {
                "algorithm": "sha-256",
                "replay_hash": replay_hash,
                "receipt_root_hash": receipt.get("integrity", {}).get("root_hash", ""),
                "evidence_ref_count": len(evidence_chain),
                "approval_history_count": len(approval_history),
                "actor_attribution_hash": actor_attribution.get("attribution_hash", ""),
                "channel_attribution_hash": channel_attribution.get("attribution_hash", ""),
                "trust_attribution_hash": trust_attribution.get("attribution_hash", ""),
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
        bundle["chain_of_custody"] = self._compose_chain_of_custody(
            session_id=session_id,
            objective_id=str((receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}).get("objective_id", "") or ""),
            prompt_id=str((receipt.get("metadata", {}) if isinstance(receipt.get("metadata"), dict) else {}).get("prompt_id", "") or ""),
            receipt_id=receipt_id,
            receipt_timestamp=str(receipt.get("timestamp", "") or ""),
            events=receipt.get("events", []) if isinstance(receipt.get("events"), list) else [],
            intervention_workflows=receipt.get("intervention_workflows", []) if isinstance(receipt.get("intervention_workflows"), list) else [],
            replay_ref=f"local://cleanhouse/receipt-replay/{receipt_id}",
            replay_generated_at=str(receipt.get("timestamp", "") or ""),
            bundle_ref=f"local://cleanhouse/receipt-bundle/{receipt_id}",
            bundle_generated_at=str(receipt.get("timestamp", "") or ""),
        )
        bundle["actor_attribution"] = self._artifact_actor_attribution(
            artifact_type="bundle",
            artifact_id=receipt_id,
            chain_of_custody=bundle["chain_of_custody"],
        )
        bundle["channel_attribution"] = self._artifact_channel_attribution(
            artifact_type="bundle",
            artifact_id=receipt_id,
            chain_of_custody=bundle["chain_of_custody"],
        )
        bundle["trust_attribution"] = self._artifact_trust_attribution(
            artifact_type="bundle",
            artifact_id=receipt_id,
            chain_of_custody=bundle["chain_of_custody"],
        )
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
            "actor_attribution_hash": bundle["actor_attribution"].get("attribution_hash", ""),
            "channel_attribution_hash": bundle["channel_attribution"].get("attribution_hash", ""),
            "trust_attribution_hash": bundle["trust_attribution"].get("attribution_hash", ""),
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
                "actor_attribution_hash": str(
                    (bundle.get("actor_attribution", {}) if isinstance(bundle.get("actor_attribution"), dict) else {}).get("attribution_hash", "")
                ),
                "channel_attribution_hash": str(
                    (bundle.get("channel_attribution", {}) if isinstance(bundle.get("channel_attribution"), dict) else {}).get("attribution_hash", "")
                ),
                "trust_attribution_hash": str(
                    (bundle.get("trust_attribution", {}) if isinstance(bundle.get("trust_attribution"), dict) else {}).get("attribution_hash", "")
                ),
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
        actor_attribution = (
            bundle.get("actor_attribution", {})
            if isinstance(bundle.get("actor_attribution"), dict)
            else {}
        )
        channel_attribution = (
            bundle.get("channel_attribution", {})
            if isinstance(bundle.get("channel_attribution"), dict)
            else {}
        )
        trust_attribution = (
            bundle.get("trust_attribution", {})
            if isinstance(bundle.get("trust_attribution"), dict)
            else {}
        )
        if not isinstance(receipt, dict) or not isinstance(timeline, dict) or not isinstance(replay_core, dict):
            return {"status": "error", "message": "bundle receipt, timeline, and replay must be objects"}

        computed_bundle_hash = self._receipt_bundle_hash(bundle)
        computed_timeline_hash = _stable_json_hash(timeline)
        computed_receipt_root_hash = self._compute_receipt_root_hash(receipt)
        computed_replay_hash = _stable_json_hash(replay_core)
        expected_bundle_id = f"receipt_bundle:{_fingerprint(bundle.get('receipt_id', ''), computed_bundle_hash)}"
        custody = bundle.get("chain_of_custody", {}) if isinstance(bundle.get("chain_of_custody"), dict) else {}
        custody_hops = custody.get("hops", []) if isinstance(custody.get("hops"), list) else []
        required_hops = {"prompt", "objective", "event", "intervention", "decision", "enforcement", "receipt", "replay", "bundle"}
        observed_hops = {
            str(hop.get("hop", ""))
            for hop in custody_hops
            if isinstance(hop, dict)
        }
        custody_all_hops_present = required_hops.issubset(observed_hops)
        custody_refs_traceable = all(
            str(hop.get("ref", "")).startswith("local://cleanhouse/")
            for hop in custody_hops
            if (
                isinstance(hop, dict)
                and str(hop.get("hop", "")) in required_hops
                and str(hop.get("ref", ""))
            )
        )
        custody_bundle_ref_match = any(
            isinstance(hop, dict)
            and str(hop.get("hop", "")) == "bundle"
            and str(hop.get("ref", "")) == f"local://cleanhouse/receipt-bundle/{bundle.get('receipt_id', '')}"
            for hop in custody_hops
        )
        custody_required = bool(custody)
        custody_enforced = bool(custody.get("fully_traceable")) if isinstance(custody, dict) else False
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
            "actor_attribution_hash_match": (
                integrity.get("actor_attribution_hash", "")
                == str(actor_attribution.get("attribution_hash", ""))
            ),
            "channel_attribution_hash_match": (
                integrity.get("channel_attribution_hash", "")
                == str(channel_attribution.get("attribution_hash", ""))
            ),
            "trust_attribution_hash_match": (
                integrity.get("trust_attribution_hash", "")
                == str(trust_attribution.get("attribution_hash", ""))
            ),
            "chain_of_custody_present": bool(custody),
            "chain_of_custody_hops_complete": custody_all_hops_present,
            "chain_of_custody_refs_traceable": custody_refs_traceable,
            "chain_of_custody_bundle_ref_match": custody_bundle_ref_match,
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
                "actor_attribution_hash_match",
                "channel_attribution_hash_match",
                "trust_attribution_hash_match",
            )
        ) and (
            not custody_required
            or (
                bool(verification["chain_of_custody_present"])
                and bool(verification["chain_of_custody_refs_traceable"])
                and (
                    not custody_enforced
                    or (
                        bool(verification["chain_of_custody_hops_complete"])
                        and bool(verification["chain_of_custody_bundle_ref_match"])
                    )
                )
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
        custody = bundle.get("chain_of_custody", {}) if isinstance(bundle.get("chain_of_custody"), dict) else {}
        actor_attribution = (
            bundle.get("actor_attribution", {})
            if isinstance(bundle.get("actor_attribution"), dict)
            else {}
        )
        channel_attribution = (
            bundle.get("channel_attribution", {})
            if isinstance(bundle.get("channel_attribution"), dict)
            else {}
        )
        trust_attribution = (
            bundle.get("trust_attribution", {})
            if isinstance(bundle.get("trust_attribution"), dict)
            else {}
        )
        custody_hops = custody.get("hops", []) if isinstance(custody.get("hops"), list) else []
        custody_hash = _stable_json_hash(custody) if custody else ""
        traceable_hop_count = 0
        for hop in custody_hops:
            if not isinstance(hop, dict):
                continue
            ref = str(hop.get("ref", "") or "")
            if ref.startswith("local://cleanhouse/"):
                traceable_hop_count += 1
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
            "actor_attribution_hash": actor_attribution.get("attribution_hash", ""),
            "actor_attribution_id": actor_attribution.get("attribution_id", ""),
            "channel_attribution_hash": channel_attribution.get("attribution_hash", ""),
            "channel_attribution_id": channel_attribution.get("attribution_id", ""),
            "trust_attribution_hash": trust_attribution.get("attribution_hash", ""),
            "trust_attribution_id": trust_attribution.get("attribution_id", ""),
            "evidence_ref_count": integrity.get("evidence_ref_count", 0),
            "approval_history_count": integrity.get("approval_history_count", 0),
            "evidence_refs": self._receipt_bundle_evidence_refs(bundle),
            "chain_of_custody_hash": custody_hash,
            "chain_of_custody_hop_count": len(custody_hops),
            "chain_of_custody_traceable_hop_count": traceable_hop_count,
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
        custody = bundle.get("chain_of_custody", {}) if isinstance(bundle.get("chain_of_custody"), dict) else {}
        actor_attribution = (
            bundle.get("actor_attribution", {})
            if isinstance(bundle.get("actor_attribution"), dict)
            else {}
        )
        channel_attribution = (
            bundle.get("channel_attribution", {})
            if isinstance(bundle.get("channel_attribution"), dict)
            else {}
        )
        trust_attribution = (
            bundle.get("trust_attribution", {})
            if isinstance(bundle.get("trust_attribution"), dict)
            else {}
        )
        custody_hops = custody.get("hops", []) if isinstance(custody.get("hops"), list) else []
        expected_custody_hash = _stable_json_hash(custody) if custody else ""
        expected_traceable_hops = 0
        for hop in custody_hops:
            if not isinstance(hop, dict):
                continue
            ref = str(hop.get("ref", "") or "")
            if ref.startswith("local://cleanhouse/"):
                expected_traceable_hops += 1
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
            manifest.get("actor_attribution_hash", "") == actor_attribution.get("attribution_hash", ""),
            manifest.get("actor_attribution_id", "") == actor_attribution.get("attribution_id", ""),
            manifest.get("channel_attribution_hash", "") == channel_attribution.get("attribution_hash", ""),
            manifest.get("channel_attribution_id", "") == channel_attribution.get("attribution_id", ""),
            manifest.get("trust_attribution_hash", "") == trust_attribution.get("attribution_hash", ""),
            manifest.get("trust_attribution_id", "") == trust_attribution.get("attribution_id", ""),
            manifest.get("evidence_ref_count", 0) == len(expected_refs),
            manifest.get("evidence_refs", []) == expected_refs,
            manifest.get("chain_of_custody_hash", "") == expected_custody_hash,
            manifest.get("chain_of_custody_hop_count", 0) == len(custody_hops),
            manifest.get("chain_of_custody_traceable_hop_count", 0) == expected_traceable_hops,
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
            "chain_of_custody_hash_match": manifest.get("chain_of_custody_hash", "") == expected_custody_hash,
            "chain_of_custody_hop_count_match": manifest.get("chain_of_custody_hop_count", 0) == len(custody_hops),
            "chain_of_custody_traceable_hop_count_match": (
                manifest.get("chain_of_custody_traceable_hop_count", 0) == expected_traceable_hops
            ),
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
            "scope_enforcement": receipt.get("scope_enforcement", {}),
            "intervention_workflows": receipt.get("intervention_workflows", []),
            "chain_of_custody": receipt.get("chain_of_custody", {}),
            "actor_attribution": receipt.get("actor_attribution", {}),
            "channel_attribution": receipt.get("channel_attribution", {}),
            "trust_attribution": receipt.get("trust_attribution", {}),
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
        custody = receipt.get("chain_of_custody", {}) if isinstance(receipt.get("chain_of_custody"), dict) else {}
        custody_id = str(custody.get("custody_id", "") or "")
        if custody_id:
            add(f"local://cleanhouse/chain-of-custody/{custody_id}", "chain_of_custody", "custody artifact")
        for hop in custody.get("hops", []):
            if not isinstance(hop, dict):
                continue
            hop_ref = str(hop.get("ref", "") or "")
            hop_name = str(hop.get("hop", "") or "hop")
            if hop_ref:
                add(hop_ref, "chain_of_custody", hop_name)
        for workflow in receipt.get("intervention_workflows", []):
            if not isinstance(workflow, dict):
                continue
            workflow_id = str(workflow.get("workflow_id", "") or "")
            if workflow_id:
                add(f"local://cleanhouse/intervention-workflow/{workflow_id}", "intervention_workflow", str(workflow.get("status", "")))
            for ref in workflow.get("evidence_refs", []):
                add(str(ref), "intervention_workflow", "workflow evidence")
            stage_refs = workflow.get("stage_refs", {}) if isinstance(workflow.get("stage_refs"), dict) else {}
            for ref in stage_refs.values():
                add(str(ref), "intervention_workflow", "workflow stage")
        if approval:
            add(f"local://cleanhouse/approval-queue/{approval.get('id', '')}", "approval_queue", str(approval.get("status", "")))
            add(f"local://cleanhouse/approval-mediation-proof/{approval.get('id', '')}", "approval_queue", "approval mediation proof")
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

    def submit_login_report(
        self,
        *,
        user_id: str = "",
        email: str = "",
        previous_login_at: Optional[str] = None,
        current_login_at: Optional[str] = None,
        trigger: str = "auth/login",
        wait_timeout_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        return self._login_report_coordinator.submit(
            user_id=user_id,
            email=email,
            previous_login_at=previous_login_at,
            current_login_at=current_login_at,
            trigger=trigger,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def poll_login_report(self, job_id: str) -> Dict[str, Any]:
        return self._login_report_coordinator.poll(job_id)

    def login_report_executor_state(self) -> Dict[str, Any]:
        return self._login_report_coordinator.state()

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

    @staticmethod
    def _summary_report_dict(report: Dict[str, Any]) -> Dict[str, Any]:
        record = copy.deepcopy(report)
        receipt = record.get("receipt")
        if isinstance(receipt, dict):
            summary_receipt = {
                key: copy.deepcopy(receipt[key])
                for key in ("id", "session_id", "timestamp", "metadata", "summary", "gaps", "integrity")
                if key in receipt
            }
            record["receipt"] = summary_receipt
        return record

    def get_reports(
        self,
        session_id: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        report_type: Optional[str] = None,
        summary_only: bool = False,
    ) -> Dict[str, Any]:
        records = self._report_dicts()
        if session_id:
            records = [r for r in records if r.get("session_id") == session_id]
        if report_type:
            records = [r for r in records if r.get("report_type") == report_type]
        if limit is not None:
            records = records[:max(0, int(limit))]
        if summary_only:
            records = [self._summary_report_dict(r) for r in records]
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
        _VALID_TOP_KEYS = frozenset({
            "collectors",
            "risk_thresholds",
            "retention",
            "evidence_depth",
            "automation",
            "qpb_policy",
            "mediator",
            "notification_policy",
        })
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
        _AUTOMATION_KEYS = frozenset({"qpb_enabled", "presence_mode_enabled", "auto_adjust_enabled", "auto_sort_enabled", "cleaner_enabled"})
        _QPB_BOOL_KEYS = frozenset({"purge_requires_confirmation", "auto_quarantine_high_risk", "auto_purge_high_risk"})
        _QPB_FLOAT_KEYS = frozenset({"quarantine_confidence_min", "purge_confidence_min"})
        _MEDIATOR_BOOL_KEYS = frozenset({"undo_enabled"})
        _MEDIATOR_INT_KEYS = frozenset({"approval_timeout_seconds"})
        _MEDIATOR_STR_KEYS = frozenset({"default_mode"})
        _NOTIFICATION_POLICY_BOOL_KEYS = frozenset({"runtime_resumed_enabled", "hard_interrupt_enabled", "fanout_all_backends", "codex_activity_native_enabled"})
        _NOTIFICATION_POLICY_INT_KEYS = frozenset(
            {
                "critical_reminder_interval_seconds",
                "dedupe_window_seconds",
                "hard_interrupt_reminder_seconds",
                "visibility_risk_seconds",
                "default_cooldown_seconds",
                "burst_window_seconds",
                "burst_cap",
                "max_native_reminders_per_notification",
            }
        )
        _NOTIFICATION_POLICY_STR_KEYS = frozenset({"backend_order"})
        _NOTIFICATION_POLICY_LIST_KEYS = frozenset({"hard_interrupt_types", "cooldown_bypass_types"})

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

        if "automation" in data:
            for k, v in data["automation"].items():
                if k not in _AUTOMATION_KEYS:
                    return {"status": "error", "message": f"Unknown automation key: {k}"}
                if not isinstance(v, bool):
                    return {"status": "error", "message": f"automation.{k} must be boolean"}
            merged["automation"].update(data["automation"])

        if "qpb_policy" in data:
            for k, v in data["qpb_policy"].items():
                if k in _QPB_BOOL_KEYS:
                    if not isinstance(v, bool):
                        return {"status": "error", "message": f"qpb_policy.{k} must be boolean"}
                elif k in _QPB_FLOAT_KEYS:
                    if not isinstance(v, (int, float)) or v < 0 or v > 1:
                        return {"status": "error", "message": f"qpb_policy.{k} must be a number between 0 and 1"}
                else:
                    return {"status": "error", "message": f"Unknown qpb_policy key: {k}"}
            merged["qpb_policy"].update(data["qpb_policy"])

        if "mediator" in data:
            for k, v in data["mediator"].items():
                if k in _MEDIATOR_BOOL_KEYS:
                    if not isinstance(v, bool):
                        return {"status": "error", "message": f"mediator.{k} must be boolean"}
                elif k in _MEDIATOR_INT_KEYS:
                    if not isinstance(v, int) or v < 1:
                        return {"status": "error", "message": f"mediator.{k} must be a positive integer"}
                elif k in _MEDIATOR_STR_KEYS:
                    if not isinstance(v, str) or not v.strip():
                        return {"status": "error", "message": f"mediator.{k} must be a non-empty string"}
                else:
                    return {"status": "error", "message": f"Unknown mediator key: {k}"}
            merged["mediator"].update(data["mediator"])

        if "notification_policy" in data:
            for k, v in data["notification_policy"].items():
                if k in _NOTIFICATION_POLICY_BOOL_KEYS:
                    if not isinstance(v, bool):
                        return {"status": "error", "message": f"notification_policy.{k} must be boolean"}
                elif k in _NOTIFICATION_POLICY_INT_KEYS:
                    if not isinstance(v, int) or v < 1:
                        return {"status": "error", "message": f"notification_policy.{k} must be a positive integer"}
                elif k in _NOTIFICATION_POLICY_STR_KEYS:
                    if not isinstance(v, str) or not v.strip():
                        return {"status": "error", "message": f"notification_policy.{k} must be a non-empty string"}
                elif k in _NOTIFICATION_POLICY_LIST_KEYS:
                    if not isinstance(v, list):
                        return {"status": "error", "message": f"notification_policy.{k} must be a list"}
                else:
                    return {"status": "error", "message": f"Unknown notification_policy key: {k}"}
            merged["notification_policy"].update(data["notification_policy"])

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
        total_rss_bytes = 0
        budget_bytes = PROCESS_MEMORY_BUDGET_BYTES

        for proc in processes:
            total_rss_bytes += _parse_process_rss_bytes(proc.get("rss"))

        sorted_processes = sorted(processes, key=lambda item: item.get("cpu", 0.0), reverse=True)
        selected_processes = sorted_processes[:100]
        selected_pids = {str(proc.get("pid")) for proc in selected_processes}
        supported_app_markers = ("terminal.app", "com.apple.terminal", "/utilities/terminal")
        for proc in sorted_processes[100:]:
            pid = str(proc.get("pid"))
            command = str(proc.get("command", "")).lower()
            if pid not in selected_pids and any(marker in command for marker in supported_app_markers):
                selected_processes.append(proc)
                selected_pids.add(pid)

        for proc in selected_processes:
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
                    "rss_bytes": _parse_process_rss_bytes(proc.get("rss")),
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

        memory_budget_exceeded = total_rss_bytes > budget_bytes
        if memory_budget_exceeded:
            over_budget_bytes = total_rss_bytes - budget_bytes
            budget_ref = f"local://cleanhouse/process-memory/{_fingerprint(str(total_rss_bytes), str(budget_bytes))}"
            details = (
                f"aggregate process rss {round(total_rss_bytes / (1024 * 1024), 2)} MB "
                f"exceeded 10 GB budget by {round(over_budget_bytes / (1024 * 1024), 2)} MB"
            )
            issues.append(
                _coerce_issue(
                    category="process",
                    severity="critical",
                    title="process memory budget exceeded",
                    details=details,
                    source="processes",
                    confidence=0.98,
                    rationale="Observed aggregate process RSS exceeded the hard 10 GB runtime budget.",
                    evidence_level="observed",
                    evidence_refs=[budget_ref],
                    evidence={
                        "memory_budget_bytes": budget_bytes,
                        "aggregate_rss_bytes": total_rss_bytes,
                        "over_budget_bytes": over_budget_bytes,
                    },
                )
            )

        return _envelope(
            issues,
            processes=normalized,
            counts={
                "total_processes": len(processes),
                "returned_processes": len(normalized),
                "aggregate_rss_bytes": total_rss_bytes,
                "aggregate_rss_mb": round(total_rss_bytes / (1024 * 1024), 2),
                "memory_budget_bytes": budget_bytes,
                "memory_budget_mb": round(budget_bytes / (1024 * 1024), 2),
                "memory_budget_exceeded": memory_budget_exceeded,
                "over_budget_bytes": max(0, total_rss_bytes - budget_bytes),
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


    def get_report(self, report_id: str) -> Dict[str, Any]:
        stable_report_id = str(report_id or "").strip()
        if not stable_report_id:
            return {"status": "error", "message": "report_id required"}
        if "/" in stable_report_id or "\\" in stable_report_id:
            return {"status": "error", "message": "report_id format is invalid"}
        with self._lock:
            report = self._reports.get(stable_report_id)
        if report is not None:
            return {"status": "ok", **report.to_dict()}
        if self.persistence_enabled:
            artifact = PersistenceBackend.read("report", stable_report_id)
            payload = artifact.get("data", {}) if isinstance(artifact, dict) else {}
            if isinstance(payload, dict) and payload.get("id") == stable_report_id:
                payload = copy.deepcopy(payload)
                payload.setdefault("status", "ok")
                return payload
        return {"status": "not_found", "message": f"report not found: {stable_report_id}"}

    def build_zaelith_report(
        self,
        *,
        analysis: Dict[str, Any],
        prompt: str = "",
        response: str = "",
        source: str = "zaelith-page",
    ) -> Dict[str, Any]:
        summary = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
        raw_report = analysis.get("zaelith_report") if isinstance(analysis.get("zaelith_report"), dict) else {}
        risk_level = str(analysis.get("risk_level") or "unknown")
        confidence = str(summary.get("analysis_confidence") or "unknown")
        grade = str(summary.get("grade") or "unknown")
        triggered = int(summary.get("triggered_indicators") or 0)
        total = int(summary.get("total_indicators") or 0)
        now = _now_iso()
        report_id = f"report:{_fingerprint('zaelith_audit', source, risk_level, confidence, grade, now)}"
        report_session_id = f"zaelith:{_fingerprint(report_id, source)}"
        triggered_names = [
            str(name)
            for name, details in raw_report.items()
            if isinstance(details, dict) and details.get("triggered")
        ]
        evidence_links = tuple(
            f"local://cleanhouse/zaelith/{report_id}/indicator/{_fingerprint(name)}"
            for name in triggered_names[:10]
        )
        summary_text = (
            f"Zaelith audit completed: {risk_level} risk, {triggered} of {total} indicator(s), "
            f"{confidence} confidence."
        )
        receipt_result = {
            "id": f"receipt:{_fingerprint(report_id, 'zaelith')}",
            "session_id": report_session_id,
            "timestamp": now,
            "summary": {
                "text": summary_text,
                "risk_level": risk_level,
                "confidence": confidence,
                "grade": grade,
                "triggered_indicators": triggered,
                "total_indicators": total,
            },
            "metadata": {
                "source": source,
                "report_family": "zaelith_audit",
                "prompt_preview": prompt[:240],
                "response_preview": response[:240],
                "full_text_retained": False,
            },
            "gaps": [],
            "integrity": {
                "receipt_hash": _fingerprint(report_id, risk_level, confidence, grade, str(triggered)),
            },
        }
        metadata = {
            "template": "zaelith_audit_report_v1",
            "synthesis_role": "conversation_audit",
            "evidence_boundary": "Full submitted text is analyzed in request scope but not retained in the report record.",
            "triggered_indicators": triggered_names[:20],
        }
        report = SessionReport(
            id=report_id,
            session_id=report_session_id,
            timestamp=now,
            report_type="zaelith_audit",
            contact="",
            target="Zaelith",
            context=summary_text,
            receipt=receipt_result,
            evidence_links=evidence_links,
            concern_letter={},
            metadata=metadata,
        )
        with self._lock:
            self._reports[report.id] = report
        result = {
            "status": "ok",
            **report.to_dict(),
            "integrity": receipt_result["integrity"],
        }
        if self.persistence_enabled:
            pr = PersistenceBackend.persist("report", report.id, result)
            if pr["status"] != "ok":
                result["persistence_warning"] = pr["message"]
        return result
