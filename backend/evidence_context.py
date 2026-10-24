"""Evidence-context resolver and action catalog for the CleanHouse command center."""

from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Iterable

from backend import events


SUPPORTED_SURFACES = {"network"}
NETWORK_TIME_SURFACE_PREFIXES = {
    "local://cleanhouse/network/",
    "/cleanhouse/network/",
    "cleanhouse/network/",
}
NETWORK_TIMELINE_TYPES = {"network_timeline_notable", "network_timeline_gap"}
NETWORK_AGGREGATE_LIMITATION = "Aggregate grouping does not prove app or process ownership."
NETWORK_SEVERITY_RANK = {"critical": 4, "high": 3, "warning": 2, "medium": 2, "low": 1, "info": 0}


def _normalize_surface(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_view(value: Any) -> str:
    value = str(value or "").strip().lower()
    return value or "network"


def _normalize_string(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:max_len]


def _normalize_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values = []
    for item in raw:
        text = _normalize_string(item, max_len=2048)
        if text:
            values.append(text)
    return values


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_owner_label(value: Any) -> str:
    return _normalize_string(value, max_len=256).casefold()


def network_distribution_owner_id(value: Any) -> str:
    label = _normalize_string(value, max_len=256) or "Unknown app"
    digest = hashlib.sha256(label.lower().encode("utf-8")).hexdigest()[:24]
    return f"network-owner:{digest}"


def _trace_id(*parts: Any) -> str:
    payload = json.dumps([_normalize_string(part) for part in parts], sort_keys=True, ensure_ascii=True)
    return f"trace:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _row_event_id(row: dict[str, Any]) -> str:
    return _normalize_string(row.get("event_id") or row.get("id"), max_len=512)


def _row_timestamp(row: dict[str, Any]) -> str:
    return _normalize_string(row.get("timestamp"), max_len=64)


def _row_summary(row: dict[str, Any]) -> str:
    summary = _normalize_string(row.get("summary"), max_len=600)
    if summary:
        return summary
    data = row.get("data")
    if isinstance(data, dict):
        nested = _normalize_string(data.get("summary") or data.get("meaning"), max_len=600)
        if nested:
            return nested
    payload = _network_payload(row)
    payload_summary = _normalize_string(payload.get("summary") or payload.get("meaning") or payload.get("reason"), max_len=600)
    if payload_summary:
        return payload_summary
    if payload.get("tick_id") or payload.get("bucket_key"):
        count = _normalize_string(payload.get("connectionCount"), max_len=32) or "one or more"
        start = _normalize_string(payload.get("bucket_start") or payload.get("timestamp"), max_len=96)
        end = _normalize_string(payload.get("bucket_end"), max_len=96)
        window = f" from {start} to {end}" if start and end else (f" at {start}" if start else "")
        return f"Network Trend candle observed {count} connection(s){window}."
    if payload.get("event_type") in NETWORK_TIMELINE_TYPES or payload.get("gap_start") or payload.get("gap_end"):
        return "Network Timeline marker from persisted evidence."
    return "Network evidence context"


def _row_severity(row: dict[str, Any]) -> str:
    data = row.get("data")
    if isinstance(data, dict):
        severity = _normalize_string(data.get("severity") or data.get("criticality"), max_len=64)
        if severity:
            return severity
    payload = _network_payload(row)
    severity = _normalize_string(payload.get("severity") or payload.get("criticality"), max_len=64)
    if severity:
        return severity
    return _normalize_string(row.get("severity"), max_len=64)


def _row_validation_state(row: dict[str, Any]) -> str:
    for candidate in (row.get("validation_state"), row.get("validationStatus"), row.get("validation")):
        normalized = _normalize_string(candidate, max_len=64)
        if normalized:
            return normalized.lower()
    data = row.get("data")
    if isinstance(data, dict):
        for candidate in (data.get("validation_state"), data.get("validationStatus"), data.get("validation")):
            normalized = _normalize_string(candidate, max_len=64)
            if normalized:
                return normalized.lower()
    payload = _network_payload(row)
    for candidate in (payload.get("validation_state"), payload.get("validationStatus"), payload.get("validation")):
        normalized = _normalize_string(candidate, max_len=64)
        if normalized:
            return normalized.lower()
    return ""


def _row_evidence_refs(row: dict[str, Any]) -> list[str]:
    refs = _normalize_string_list(row.get("evidence_refs"))
    raw_ref = _normalize_string(row.get("raw_evidence_ref"), max_len=2048)
    if raw_ref:
        refs.append(raw_ref)
    data = row.get("data")
    if isinstance(data, dict):
        nested_refs = _normalize_string_list(data.get("evidence_refs"))
        if nested_refs:
            refs.extend(nested_refs)
        nested_raw_ref = _normalize_string(data.get("raw_evidence_ref") or data.get("raw_ref"), max_len=2048)
        if nested_raw_ref:
            refs.append(nested_raw_ref)
    payload = _network_payload(row)
    refs.extend(_normalize_string_list(payload.get("evidence_refs")))
    payload_raw_ref = _normalize_string(payload.get("raw_evidence_ref") or payload.get("raw_ref"), max_len=2048)
    if payload_raw_ref:
        refs.append(payload_raw_ref)
    return _dedupe_strings(refs)


def _row_assessment_refs(row: dict[str, Any]) -> list[str]:
    refs = _normalize_string_list(row.get("assessment_refs"))
    data = row.get("data")
    if isinstance(data, dict):
        refs.extend(_normalize_string_list(data.get("assessment_refs")))
    payload = _network_payload(row)
    refs.extend(_normalize_string_list(payload.get("assessment_refs")))
    return _dedupe_strings(refs)


def _network_payload(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("data")
    if isinstance(data, dict) and isinstance(data.get("network"), dict):
        return data["network"]
    if isinstance(data, dict):
        for key in ("network_timeline_notable", "network_gap", "network_tick"):
            nested = data.get(key)
            if isinstance(nested, dict):
                return nested
    return {}


def _normalize_network_tags(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    tags: dict[str, Any] = {}
    for key in ("status", "state", "explanation"):
        value = _normalize_string(raw.get(key), max_len=160)
        if value:
            tags[key] = value
    reasons = _dedupe_strings(_normalize_string_list(raw.get("reasons")))[:8]
    if reasons:
        tags["reasons"] = reasons
    return tags or None


def _row_network_tags(row: dict[str, Any]) -> dict[str, Any] | None:
    tags = _normalize_network_tags(row.get("tags"))
    if tags:
        return tags
    data = row.get("data")
    if isinstance(data, dict):
        tags = _normalize_network_tags(data.get("tags"))
        if tags:
            return tags
    payload = _network_payload(row)
    return _normalize_network_tags(payload.get("tags"))


def _row_network_reasons(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    tags = _row_network_tags(row)
    if isinstance(tags, dict):
        values.extend(_normalize_string_list(tags.get("reasons")))
        values.append(_normalize_string(tags.get("explanation"), max_len=160))
    payload = _network_payload(row)
    values.extend(_normalize_string_list([
        row.get("reason"),
        payload.get("reason"),
        payload.get("meaning"),
        payload.get("category"),
    ]))
    return _dedupe_strings(values)[:8]


def _row_owner_labels(row: dict[str, Any]) -> list[str]:
    payload = _network_payload(row)
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    values = [
        row.get("process"),
        row.get("app"),
        row.get("application"),
        payload.get("process"),
        payload.get("app"),
        payload.get("application"),
        data.get("process") if isinstance(data, dict) else "",
        data.get("app") if isinstance(data, dict) else "",
        data.get("application") if isinstance(data, dict) else "",
    ]
    return _dedupe_strings(_normalize_string_list(values))


def _row_matches_distribution_owner(row: dict[str, Any], owner: str) -> bool:
    target = _normalize_owner_label(owner)
    if not target:
        return False
    return any(_normalize_owner_label(label) == target for label in _row_owner_labels(row))


def _highest_severity(rows: list[dict[str, Any]]) -> str | None:
    highest = ""
    highest_rank = -1
    for row in rows:
        severity = _row_severity(row).lower()
        rank = NETWORK_SEVERITY_RANK.get(severity, -1)
        if rank > highest_rank:
            highest = severity
            highest_rank = rank
    return highest or None


def _matches_network_entity(row: dict[str, Any], entity_id: str) -> bool:
    if not entity_id:
        return False
    candidates = {_normalize_string(row.get("id"), max_len=512), _row_event_id(row)}
    raw_ref = _normalize_string(row.get("raw_evidence_ref"), max_len=2048)
    if raw_ref:
        candidates.add(raw_ref)
        candidates.add(raw_ref.rsplit("/", 1)[-1])
    path = _normalize_string(row.get("path"), max_len=1024)
    if path:
        candidates.add(path)
        candidates.add(PurePosixPath(path).name)
    for ref in _normalize_string_list(row.get("evidence_refs")):
        candidates.add(ref)
        candidates.add(ref.rsplit("/", 1)[-1])
    for candidate in _normalize_string_list([_normalize_string(row.get("related_event_id"), max_len=512)]):
        candidates.add(candidate)
        candidates.add(candidate.rsplit("/", 1)[-1])
    data = row.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("network"), dict):
            network = data["network"]
            if isinstance(network, dict):
                candidates.update(_normalize_string_list([network.get("event_id"), network.get("id")]))
                candidates.update(_normalize_string_list([network.get("raw_evidence_ref")]))
        else:
            candidates.update(_normalize_string_list([data.get("event_id"), data.get("id")]))
    payload = _network_payload(row)
    if payload:
        candidates.update(_normalize_string_list([
            payload.get("event_id"),
            payload.get("id"),
            payload.get("tick_id"),
            payload.get("bucket_key"),
            payload.get("source_event_id"),
            payload.get("raw_evidence_ref"),
        ]))
        for ref in _normalize_string_list(payload.get("evidence_refs")):
            candidates.add(ref)
            candidates.add(ref.rsplit("/", 1)[-1])
        for related in _normalize_string_list(payload.get("related_event_ids")):
            candidates.add(related)
            candidates.add(related.rsplit("/", 1)[-1])
    for candidate in candidates:
        if candidate == entity_id:
            return True
    return False


def _is_network_ref(ref: str) -> tuple[str, str] | None:
    for prefix in NETWORK_TIME_SURFACE_PREFIXES:
        if ref.startswith(prefix):
            entity_id = _normalize_string(ref[len(prefix):], max_len=512)
            return "network", entity_id
    if not ref.startswith("local://"):
        return None
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class EvidenceContext:
    evidence_key: str
    source_surface: str
    source_view: str
    source_entity_id: str
    evidence_refs: list[str]
    summary: str
    severity: str | None
    validation_state: str | None
    open_back_route: str
    timeline_event_id: str | None
    network_tags: dict[str, Any] | None
    network_reasons: list[str]
    origin: str
    trace_id: str
    assessment_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_key": self.evidence_key,
            "source_surface": self.source_surface,
            "source_view": self.source_view,
            "source_entity_id": self.source_entity_id,
            "evidence_refs": list(self.evidence_refs),
            "assessment_refs": list(self.assessment_refs),
            "summary": self.summary,
            "severity": self.severity,
            "validation_state": self.validation_state,
            "open_back_route": self.open_back_route,
            "timeline_event_id": self.timeline_event_id,
            "network_tags": dict(self.network_tags or {}),
            "network_reasons": list(self.network_reasons),
            "origin": self.origin,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class EvidenceAction:
    id: str
    label: str
    intent: str
    enabled: bool
    disabled_reason: str
    required_role: str
    voice_role: str | None
    backend_roles: list[str]
    capability_source: str
    source_navigation: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "intent": self.intent,
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "required_role": self.required_role,
            "voice_role": self.voice_role,
            "backend_roles": list(self.backend_roles),
            "capability_source": self.capability_source,
            "source_navigation": self.source_navigation,
        }


@dataclass(frozen=True)
class ActionAuditEntry:
    trace_id: str
    evidence_key: str
    action_id: str
    invoker: str
    role: str
    source_surface: str
    source_view: str
    source_entity_id: str
    action_origin: str = ""
    action_subject: dict[str, Any] | None = None
    action_context: dict[str, Any] | None = None
    selected_evidence_receipt: dict[str, Any] | None = None
    report_intent: str = ""

    def to_dict(self) -> dict[str, Any]:
        now = _now_iso()
        return {
            "id": f"evidence_action:{hashlib.sha256((self.trace_id + self.action_id + self.invoker + now).encode('utf-8')).hexdigest()[:24]}",
            "trace_id": self.trace_id,
            "evidence_key": self.evidence_key,
            "action_id": self.action_id,
            "invoker": self.invoker,
            "role": self.role,
            "source_surface": self.source_surface,
            "source_view": self.source_view,
            "source_entity_id": self.source_entity_id,
            "action_origin": self.action_origin,
            "action_subject": copy.deepcopy(self.action_subject or {}),
            "action_context": copy.deepcopy(self.action_context or {}),
            "selected_evidence_receipt": copy.deepcopy(self.selected_evidence_receipt or {}),
            "report_intent": self.report_intent,
            "timestamp": now,
        }


class EvidenceActionResolver:
    """Resolve evidence context and available actions."""

    def __init__(self, *, network_event_limit: int = 5000):
        self.network_event_limit = max(1, min(network_event_limit, 20000))

    def _network_events(self) -> list[dict[str, Any]]:
        try:
            return events.list_events(limit=self.network_event_limit, source_surface="network")
        except TypeError:
            return events.list_events(limit=self.network_event_limit)

    def _network_row(self, entity_id: str) -> dict[str, Any] | None:
        target = _normalize_string(entity_id, max_len=512)
        if not target:
            return None
        for row in self._network_events():
            if _matches_network_entity(row, target):
                return row
        return None

    def _network_timeline_event_id(self, entity_id: str) -> str | None:
        target = _normalize_string(entity_id, max_len=512)
        if not target:
            return None
        rows = self._network_events()
        for row in rows:
            if row.get("event_type") not in NETWORK_TIMELINE_TYPES:
                continue
            data = row.get("data")
            related = _normalize_string_list(data.get("related_event_ids") if isinstance(data, dict) else []) if isinstance(data, dict) else []
            if target in related:
                return _normalize_string(row.get("id") or row.get("event_id"), max_len=512)
            path = _normalize_string(row.get("path"), max_len=1024)
            if target in path:
                return _normalize_string(row.get("id") or row.get("event_id"), max_len=512)
        return None

    def _network_open_back_route(self, source_view: str, source_entity_id: str) -> str:
        view = _normalize_view(source_view)
        if view == "findings":
            route_view = "findings"
        elif view in {"distribution", "pie"}:
            route_view = "pie"
        elif view == "timeline":
            route_view = "timeline"
        elif view in {"trend", "bar"}:
            route_view = "bar"
        else:
            route_view = "table"
        return f"/network?network_view={route_view}&event_id={_normalize_string(source_entity_id, max_len=512)}"

    def _resolve_network_distribution_context(self, entity_id: str) -> EvidenceContext:
        normalized_entity = _normalize_string(entity_id, max_len=512)
        all_rows = self._network_events()
        owner = ""
        if normalized_entity.startswith("network-owner:"):
            for row in all_rows:
                for label in _row_owner_labels(row):
                    if network_distribution_owner_id(label) == normalized_entity:
                        owner = label
                        break
                if owner:
                    break
            owner_id = normalized_entity
        else:
            owner = _normalize_string(
                normalized_entity.split(":", 1)[1] if normalized_entity.startswith("distribution:") else normalized_entity,
                max_len=256,
            )
            owner_id = network_distribution_owner_id(owner)
        rows = [row for row in all_rows if _row_matches_distribution_owner(row, owner)]
        refs = _dedupe_strings(ref for row in rows for ref in _row_evidence_refs(row))[:32]
        assessment_refs = _dedupe_strings(ref for row in rows for ref in _row_assessment_refs(row))[:32]
        reasons = [NETWORK_AGGREGATE_LIMITATION]
        if not refs:
            reasons.append("No retained Network evidence references were resolved for this Distribution owner selection.")
        else:
            reasons.append(f"{len(refs)} retained evidence reference(s) resolved for this Distribution owner selection.")
        summary = (
            f"Distribution owner '{owner or 'Unknown app'}' appears in {len(rows)} retained Network evidence item(s). "
            f"{NETWORK_AGGREGATE_LIMITATION}"
        )
        return EvidenceContext(
            evidence_key=f"network:{owner_id}",
            source_surface="network",
            source_view="distribution",
            source_entity_id=owner_id,
            evidence_refs=refs,
            summary=summary,
            severity=_highest_severity(rows),
            validation_state="aggregate_observed" if rows else "aggregate_unresolved",
            open_back_route=self._network_open_back_route("distribution", owner_id),
            timeline_event_id=None,
            network_tags=None,
            network_reasons=_dedupe_strings(reasons)[:8],
            origin=f"local://cleanhouse/network/distribution/{owner_id}",
            trace_id=_trace_id("network", "distribution", owner_id, "|".join(refs), len(rows)),
            assessment_refs=assessment_refs,
        )

    def _fallback_network_context(self, source_view: str, source_entity_id: str) -> EvidenceContext:
        source_view = _normalize_view(source_view)
        refs = [f"local://cleanhouse/network/{_normalize_string(source_entity_id, max_len=512)}"] if source_entity_id else []
        evidence_key = f"network:{_normalize_string(source_entity_id, max_len=512)}"
        return EvidenceContext(
            evidence_key=evidence_key,
            source_surface="network",
            source_view=source_view,
            source_entity_id=_normalize_string(source_entity_id, max_len=512),
            evidence_refs=_dedupe_strings(refs),
            summary="Network evidence context unavailable.",
            severity=None,
            validation_state=None,
            open_back_route=self._network_open_back_route(source_view, source_entity_id),
            timeline_event_id=None,
            network_tags=None,
            network_reasons=[],
            origin=f"local://cleanhouse/network/{_normalize_string(source_entity_id, max_len=512)}" if source_entity_id else "local://cleanhouse/network",
            trace_id=_trace_id("network", source_entity_id, source_view, "fallback"),
        )

    def resolve(self, surface: str, entity_id: str, source_view: str | None = None) -> EvidenceContext:
        normalized_surface = _normalize_surface(surface)
        if normalized_surface != "network":
            return EvidenceContext(
                evidence_key=f"{normalized_surface}:{_normalize_string(entity_id, max_len=512)}",
                source_surface=normalized_surface or "unknown",
                source_view=_normalize_view(source_view),
                source_entity_id=_normalize_string(entity_id, max_len=512),
                evidence_refs=[],
                summary=f"No resolver available for source surface '{normalized_surface}'.",
                severity=None,
                validation_state=None,
                open_back_route=f"/{normalized_surface}" if normalized_surface else "/network",
                timeline_event_id=None,
                network_tags=None,
                network_reasons=[],
                origin=f"cleanhouse://{normalized_surface}/{_normalize_string(entity_id, max_len=512)}",
                trace_id=_trace_id(normalized_surface, entity_id, _normalize_view(source_view), "unsupported"),
            )
        return self._resolve_network(entity_id, _normalize_view(source_view))

    def resolve_from_evidence_key(self, evidence_key: str, source_view: str | None = None) -> EvidenceContext:
        normalized = _normalize_string(evidence_key, max_len=512)
        if not normalized:
            return self._fallback_network_context(_normalize_view(source_view), "")
        surface, _, entity_id = normalized.partition(":")
        if surface != "network" or not entity_id:
            return self.resolve(surface or "unknown", entity_id, source_view=source_view)
        return self._resolve_network(entity_id, _normalize_view(source_view))

    def resolve_from_ref(self, ref: str, source_view: str | None = None) -> EvidenceContext:
        parsed = _is_network_ref(_normalize_string(ref, max_len=1024))
        if parsed is None:
            return self._fallback_network_context(_normalize_view(source_view), _normalize_string(ref, max_len=512))
        surface, entity_id = parsed
        if surface != "network":
            return self.resolve(surface, entity_id, source_view=source_view)
        return self._resolve_network(entity_id, _normalize_view(source_view))

    def _resolve_network(self, entity_id: str, source_view: str) -> EvidenceContext:
        if _normalize_view(source_view) in {"distribution", "pie"}:
            return self._resolve_network_distribution_context(entity_id)
        row = self._network_row(entity_id)
        if row is None:
            return self._fallback_network_context(source_view, entity_id)
        refs = _row_evidence_refs(row)
        if not refs and entity_id:
            refs = [f"local://cleanhouse/network/{entity_id}"]
        summary = _row_summary(row)
        row_data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if not summary and isinstance(row_data, dict):
            summary = _normalize_string(row_data.get("summary") or row_data.get("meaning"), max_len=600)
        timeline_event_id = _normalize_string(row.get("timeline_event_id"), max_len=512) or self._network_timeline_event_id(entity_id)
        if not timeline_event_id and row.get("event_type") in NETWORK_TIMELINE_TYPES:
            timeline_event_id = _normalize_string(row.get("id") or row.get("event_id"), max_len=512)
        evidence_id = _row_event_id(row) or _normalize_string(entity_id, max_len=512)
        raw_ref = _normalize_string(row.get("raw_evidence_ref"), max_len=2048)
        origin = raw_ref or (f"local://cleanhouse/network/{evidence_id}" if evidence_id else f"local://cleanhouse/network/{_normalize_string(entity_id, max_len=512)}")
        return EvidenceContext(
            evidence_key=f"network:{evidence_id}",
            source_surface="network",
            source_view=source_view,
            source_entity_id=evidence_id,
            evidence_refs=_dedupe_strings(refs),
            summary=summary,
            severity=_row_severity(row) or None,
            validation_state=_row_validation_state(row) or None,
            open_back_route=self._network_open_back_route(source_view, evidence_id),
            timeline_event_id=timeline_event_id,
            network_tags=_row_network_tags(row),
            network_reasons=_row_network_reasons(row),
            origin=origin,
            trace_id=_trace_id("network", evidence_id, source_view, _normalize_string(_row_timestamp(row), max_len=64), "|".join(_dedupe_strings(refs))),
            assessment_refs=_row_assessment_refs(row)[:32],
        )

    def _action(self, context: EvidenceContext, action: dict[str, Any], enabled: bool, disabled_reason: str, required_role: str) -> EvidenceAction:
        return EvidenceAction(
            id=str(action["id"]),
            label=str(action["label"]),
            intent=str(action["intent"]),
            enabled=bool(enabled),
            disabled_reason=disabled_reason,
            required_role=required_role,
            voice_role=action.get("voice_role"),
            backend_roles=_dedupe_strings(_normalize_string_list(action.get("backend_roles"))),
            capability_source=_normalize_string(action.get("capability_source"), max_len=128) or "evidence_command_center",
            source_navigation=action.get("source_navigation"),
        )

    def _navigation(self, route: str) -> dict[str, Any]:
        return {"type": "route", "route": route}

    def actions(self, context: EvidenceContext) -> list[dict[str, Any]]:
        has_timeline = bool(context.timeline_event_id)
        has_ref = bool(context.evidence_refs)
        validation = _normalize_string(context.validation_state, max_len=64).lower()
        actions = [
            self._action(
                context,
                {
                    "id": "view_on_timeline",
                    "label": "View on Timeline",
                    "intent": "route",
                    "backend_roles": ["CLICK", "Day-Day", "Clean"],
                    "capability_source": "network_evidence_navigation",
                    "source_navigation": self._navigation(f"/network?network_view=timeline&event_id={context.source_entity_id}") if has_timeline else {"type": "none", "route": None},
                },
                enabled=has_timeline,
                disabled_reason="No linked timeline anchor in current evidence lineage." if not has_timeline else "",
                required_role="viewer",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "view_related_finding",
                    "label": "View related Finding",
                    "intent": "route",
                    "backend_roles": ["Day-Day", "Valorie", "Clean"],
                    "capability_source": "network_semantic_review",
                    "source_navigation": self._navigation("/network?network_view=findings") if has_ref else {"type": "none", "route": None},
                },
                enabled=has_ref,
                disabled_reason="No related finding evidence was resolved yet." if not has_ref else "",
                required_role="viewer",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "view_trend_candle",
                    "label": "View Trend candle",
                    "intent": "route",
                    "backend_roles": ["CLICK", "Day-Day", "Clean"],
                    "capability_source": "network_trend_history",
                    "source_navigation": self._navigation("/network?network_view=trend") if has_ref else {"type": "none", "route": None},
                },
                enabled=has_ref,
                disabled_reason="Trend view requires event-derived evidence refs." if not has_ref else "",
                required_role="viewer",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "view_app_process",
                    "label": "View app/process",
                    "intent": "route",
                    "backend_roles": ["Scout", "Clean"],
                    "capability_source": "application_process_evidence",
                    "source_navigation": self._navigation("/applications"),
                },
                enabled=True,
                disabled_reason="",
                required_role="viewer",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "generate_report",
                    "label": "Generate report",
                    "intent": "generate_report",
                    "voice_role": "Aurora",
                    "backend_roles": ["Auditor", "Quality Control", "Valorie", "Clean"],
                    "capability_source": "report_clerk",
                    "source_navigation": {"type": "postback", "route": "/cleanhouse/evidence/actions"},
                },
                enabled=validation == "validated",
                disabled_reason="Evidence must be validated before report generation." if validation != "validated" else "",
                required_role="Aurora",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "create_letter_of_concern",
                    "label": "Create letter of concern",
                    "intent": "generate_letter",
                    "voice_role": "Aurora",
                    "backend_roles": ["Auditor", "Quality Control", "Valorie", "Clean"],
                    "capability_source": "report_clerk",
                    "source_navigation": {"type": "postback", "route": "/cleanhouse/evidence/actions"},
                },
                enabled=validation == "validated",
                disabled_reason="Evidence must be validated before concern letters are generated." if validation != "validated" else "",
                required_role="Aurora",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "ask_insight",
                    "label": "Ask Insight",
                    "intent": "analysis",
                    "voice_role": "Insight",
                    "backend_roles": ["Insight", "Clean"],
                    "capability_source": "apple_intelligence_foundation_models",
                    "source_navigation": {"type": "none", "route": None},
                },
                enabled=True,
                disabled_reason="",
                required_role="Insight",
            ).to_dict(),
            self._action(
                context,
                {
                    "id": "validate_with_val",
                    "label": "Validate with Val",
                    "intent": "validation",
                    "voice_role": "Valorie",
                    "backend_roles": ["Auditor", "Quality Control", "Clean"],
                    "capability_source": "evidence_validation",
                    "source_navigation": {"type": "none", "route": None},
                },
                enabled=validation not in {"validated", "proven"},
                disabled_reason="Evidence already validated." if validation in {"validated", "proven"} else "",
                required_role="Valorie",
            ).to_dict(),
        ]
        # Core control actions are capability-backed by the evidence action
        # endpoint. Destructive controls remain unavailable until a guarded
        # local provider can prove it can act on this exact target.
        core_actions = [
            ("mark_read", "Mark as Read", "review", True, ""),
            ("mark_unread", "Mark as Unread", "review", True, ""),
            ("copy", "Copy", "copy", bool(context.evidence_key), "Evidence identity is unavailable."),
            ("export", "Export Evidence", "export", bool(context.evidence_refs), "No evidence references are available to export."),
            ("observe", "Observe", "monitor", bool(context.evidence_key), "Evidence identity is unavailable."),
        ]
        actions.extend(self._action(
            context,
            {
                "id": action_id,
                "label": label,
                "intent": intent,
                "backend_roles": ["Clean", "Valorie"],
                "capability_source": "evidence_action_executor",
                "source_navigation": {"type": "postback", "route": "/cleanhouse/evidence/actions"},
            },
            enabled=enabled,
            disabled_reason="" if enabled else disabled_reason,
            required_role="operator",
        ).to_dict() for action_id, label, intent, enabled, disabled_reason in core_actions)
        for action_id, label in (("restrict", "Restrict"), ("block", "Block"), ("quarantine", "Quarantine"), ("terminate", "Terminate")):
            actions.append(self._action(
                context,
                {
                    "id": action_id,
                    "label": label,
                    "intent": "enforcement",
                    "backend_roles": ["K.A.T.A.N.A.", "Clean"],
                    "capability_source": "guarded_local_enforcement",
                    "source_navigation": {"type": "postback", "route": "/cleanhouse/evidence/actions"},
                },
                enabled=False,
                disabled_reason="No guarded local enforcement provider is available for this target.",
                required_role="operator",
            ).to_dict())
        return actions

    def audit_entry(
        self,
        context: EvidenceContext,
        *,
        action_id: str,
        invoker: str,
        role: str,
        action_origin: str | None = None,
        action_subject: dict[str, Any] | None = None,
        action_context: dict[str, Any] | None = None,
        selected_evidence_receipt: dict[str, Any] | None = None,
        report_intent: str | None = None,
    ) -> dict[str, Any]:
        entry = ActionAuditEntry(
            trace_id=context.trace_id,
            evidence_key=context.evidence_key,
            action_id=action_id,
            invoker=invoker,
            role=role,
            source_surface=context.source_surface,
            source_view=context.source_view,
            source_entity_id=context.source_entity_id,
            action_origin=(action_origin or "").strip(),
            action_subject=copy.deepcopy(action_subject) if action_subject else None,
            action_context=copy.deepcopy(action_context) if action_context else None,
            selected_evidence_receipt=copy.deepcopy(selected_evidence_receipt) if selected_evidence_receipt else None,
            report_intent=(report_intent or "").strip(),
        ).to_dict()
        return entry
