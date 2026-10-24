"""Canonical security assessments derived from retained Network evidence.

The assessment contract is intentionally independent from collector health.
Capture lifecycle states are operational evidence; they never become a
security strength, vulnerability, or threat.  This module is deterministic so
every Network projection can reuse the same identities without reclassifying
evidence in the browser.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable


ASSESSMENT_SCHEMA = "cleanhouse.security_assessment.v1"
ASSESSMENT_SUMMARY_SCHEMA = "cleanhouse.security_assessment_summary.v1"
RULE_REGISTRY_VERSION = "network-assessment-rules.v1"
ASSESSMENT_TRANSITION_EVENT_TYPE = "security_assessment_transition"
MAX_EVIDENCE_REFS = 32
MAX_TEXT_LENGTH = 1024

_CATEGORIES = {"strength", "vulnerability", "threat"}
_LIFECYCLES = {"observed", "active", "contained", "resolved", "dismissed", "superseded"}
_INACTIVE_LIFECYCLES = {"resolved", "dismissed", "superseded"}
SUPPORTED_TREND_METRICS = {"connections", "strengths", "vulnerabilities", "threats"}
_OPERATIONAL_REASONS = {
    "capture_engine_unavailable",
    "engine_unavailable",
    "permission_blocked",
    "capture_failed",
    "capture_start_timeout",
    "collector_not_started",
    "continuity_gap",
    "warming",
    "retrying",
    "offline",
    "degraded",
}


def _text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    return str(value or "").strip()[:limit]


def _timestamp(value: Any) -> str | None:
    text = _text(value, limit=128)
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return None


def _stable_id(prefix: str, *parts: Any) -> str:
    body = "|".join(_text(part, limit=512) for part in parts)
    return f"{prefix}:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _event_id(event: dict[str, Any]) -> str:
    return _text(
        event.get("event_id")
        or event.get("source_event_key")
        or event.get("collector_cursor")
        or event.get("cursor")
        or _stable_id(
            "network-evidence",
            event.get("timestamp"),
            event.get("process") or event.get("app"),
            event.get("src_ip"),
            event.get("src_port"),
            event.get("dst_ip"),
            event.get("dst_port"),
            event.get("protocol"),
        )
    )


def _evidence_refs(event: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    raw = event.get("evidence_refs")
    if isinstance(raw, list):
        refs.extend(_text(item, limit=512) for item in raw)
    for value in (event.get("raw_evidence_ref"), event.get("evidence_ref")):
        if value:
            refs.append(_text(value, limit=512))
    event_id = _event_id(event)
    if event_id:
        refs.append(f"local://cleanhouse/network/{event_id}")
    bounded: list[str] = []
    for ref in refs:
        if ref and ref not in bounded:
            bounded.append(ref)
        if len(bounded) >= MAX_EVIDENCE_REFS:
            break
    return bounded


def _is_local_destination(value: Any) -> bool:
    host = _text(value, limit=512).strip("[]").lower()
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local")
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _application(event: dict[str, Any]) -> str:
    value = _text(event.get("process") or event.get("app") or event.get("application"), limit=256)
    if not value or value.lower() in {"unknown", "unknown app", "unattributed"}:
        return "Unknown app"
    return value


def _destination(event: dict[str, Any]) -> str:
    return _text(
        event.get("destination_display")
        or event.get("dns_query")
        or event.get("http_host")
        or event.get("tls_sni")
        or event.get("dst_ip"),
        limit=512,
    )


def _subject(event: dict[str, Any]) -> dict[str, str]:
    app = _application(event)
    destination = _destination(event) or "missing-destination"
    protocol = _text(event.get("protocol"), limit=32).upper() or "UNKNOWN"
    port = _text(event.get("dst_port"), limit=16)
    identity = _stable_id("network-subject", app.lower(), destination.lower(), protocol, port)
    return {
        "type": "network_connection",
        "id": identity,
        "label": f"{app} to {destination}",
    }


def _confidence(score: float) -> dict[str, Any]:
    bounded = max(0.0, min(float(score), 1.0))
    label = "high" if bounded >= 0.8 else "medium" if bounded >= 0.5 else "low"
    return {"score": round(bounded, 3), "label": label}


def _assessment(
    event: dict[str, Any],
    *,
    rule_id: str,
    category: str,
    severity: str,
    confidence: float,
    rationale: str,
    subject: dict[str, str] | None = None,
    lifecycle: str | None = None,
) -> dict[str, Any]:
    if category not in _CATEGORIES:
        raise ValueError("invalid security assessment category")
    resolved_subject = subject or _subject(event)
    key = f"{rule_id}:{resolved_subject['type']}:{resolved_subject['id']}"
    assessment_id = _stable_id("security-assessment", RULE_REGISTRY_VERSION, key)
    observed_at = _timestamp(event.get("timestamp"))
    if observed_at is None:
        raise ValueError("network assessment requires a valid event timestamp")
    resolved_lifecycle = _text(lifecycle or event.get("assessment_lifecycle"), limit=32).lower() or "active"
    if resolved_lifecycle not in _LIFECYCLES:
        resolved_lifecycle = "active"
    return {
        "schema": ASSESSMENT_SCHEMA,
        "assessment_id": assessment_id,
        "assessment_key": key,
        "category": category,
        "severity": _text(severity, limit=32).lower() or "low",
        "confidence": _confidence(confidence),
        "lifecycle": resolved_lifecycle,
        "disposition": _text(event.get("assessment_disposition"), limit=64) or "unreviewed",
        "assessment_state": resolved_lifecycle,
        "owner_disposition": _text(event.get("assessment_disposition"), limit=64) or "unreviewed",
        "subject": resolved_subject,
        "subject_type": resolved_subject["type"],
        "subject_id": resolved_subject["id"],
        "rule": {"id": rule_id, "version": RULE_REGISTRY_VERSION},
        "rule_id": rule_id,
        "rule_version": RULE_REGISTRY_VERSION,
        "rationale": _text(rationale),
        "first_seen": observed_at,
        "last_seen": observed_at,
        "evidence_refs": _evidence_refs(event),
        "continuity": _text(event.get("continuity"), limit=32) or "unknown",
        "generation": event.get("generation"),
        "cursor": _text(event.get("collector_cursor") or event.get("cursor"), limit=256) or None,
        "source_cursor": _text(event.get("collector_cursor") or event.get("cursor"), limit=256) or None,
    }


def _truthy(event: dict[str, Any], *keys: str) -> bool:
    return any(event.get(key) is True for key in keys)


def assess_network_event(event: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return canonical assessments and neutral indicators for one event."""
    if not isinstance(event, dict):
        return [], []
    if _timestamp(event.get("timestamp")) is None:
        return [], []
    reason = _text(event.get("reason") or event.get("reason_code"), limit=128).lower()
    if reason in _OPERATIONAL_REASONS or _text(event.get("event_type"), limit=64) in {
        "collector.gap",
        "collector.failure",
        "network_collector_receipt",
        "network_timeline_gap",
    }:
        return [], []

    assessments: list[dict[str, Any]] = []
    indicators: list[dict[str, Any]] = []
    app = _application(event)
    destination = _destination(event)
    external = bool(
        event.get("external_activity") is True
        or event.get("is_external") is True
        or _text(event.get("direction"), limit=32).lower() in {"outbound_external", "inbound_external"}
        or (destination and not _is_local_destination(event.get("dst_ip") or destination))
    )

    if app == "Unknown app" and external:
        assessments.append(_assessment(
            event,
            rule_id="network.unknown_external_application",
            category="vulnerability",
            severity="medium",
            confidence=0.82,
            rationale="External network activity is present without verified application attribution.",
        ))
    named_destination = _text(
        event.get("destination_identity")
        or event.get("dns_query")
        or event.get("http_host")
        or event.get("tls_sni"),
        limit=512,
    )
    if _truthy(event, "destination_name_missing", "destination_identity_missing") or not named_destination:
        assessments.append(_assessment(
            event,
            rule_id="network.destination_identity_missing",
            category="vulnerability",
            severity="medium",
            confidence=0.9,
            rationale="The retained connection evidence does not identify its destination.",
        ))

    neutral_rules = (
        ("unusual_port", "An unusual port was observed without corroborating harmful evidence."),
        ("new_destination", "A newly observed destination requires context before security classification."),
        ("traffic_volume", "Traffic volume is an observation until corroborated by reviewed evidence."),
        ("repeated_attempts", "Repeated attempts are an indicator until corroborated by reviewed evidence."),
    )
    for signal, explanation in neutral_rules:
        if _truthy(event, signal):
            indicators.append({
                "indicator_id": _stable_id("network-indicator", signal, _subject(event)["id"]),
                "kind": signal,
                "classification": "neutral",
                "rationale": explanation,
                "evidence_refs": _evidence_refs(event),
            })

    if _truthy(event, "encryption_verified", "tls_verified"):
        assessments.append(_assessment(
            event,
            rule_id="network.encryption_verified",
            category="strength",
            severity="informational",
            confidence=0.95,
            rationale="The retained evidence explicitly verifies encrypted transport.",
        ))
    if _truthy(event, "attribution_verified"):
        assessments.append(_assessment(
            event,
            rule_id="network.application_attribution_verified",
            category="strength",
            severity="informational",
            confidence=0.95,
            rationale="The network activity is bound to a verified application identity.",
        ))
    if _truthy(event, "authorized_destination"):
        assessments.append(_assessment(
            event,
            rule_id="network.destination_authorized",
            category="strength",
            severity="informational",
            confidence=0.95,
            rationale="The destination is explicitly authorized by retained owner evidence.",
        ))
    if _truthy(event, "containment_verified", "effectively_contained"):
        assessments.append(_assessment(
            event,
            rule_id="network.containment_verified",
            category="strength",
            severity="informational",
            confidence=0.95,
            rationale="A retained control receipt verifies effective containment.",
            lifecycle="contained",
        ))

    threat_rules: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...] = (
        ("network.verified_malicious_endpoint", ("known_malicious_verified", "malicious_endpoint_verified"), ("known_malicious", "malicious_endpoint"), "A retained provider verdict verifies a malicious endpoint."),
        ("network.malware_activity_verified", ("malware_activity_verified",), ("malware", "malware_activity"), "Retained evidence verifies malware-related network activity."),
        ("network.exfiltration_verified", ("exfiltration_verified",), ("exfiltration",), "Retained evidence verifies active data exfiltration."),
        ("network.unauthorized_inbound_verified", ("unauthorized_inbound_verified",), ("unauthorized_inbound",), "Retained evidence verifies unauthorized inbound access."),
        ("network.exploit_verified", ("exploit_verified",), ("exploit", "active_exploit"), "Retained evidence verifies active exploitation."),
        ("network.quarantine_bypass_verified", ("quarantine_bypass_verified",), ("quarantine_bypass",), "Retained evidence verifies a quarantine bypass."),
    )
    for rule_id, flags, verified_verdicts, rationale in threat_rules:
        verified_verdict = bool(
            event.get("provider_verdict_verified") is True
            and _text(event.get("verified_verdict"), limit=128).lower() in verified_verdicts
        )
        if _truthy(event, *flags) or verified_verdict:
            assessments.append(_assessment(
                event,
                rule_id=rule_id,
                category="threat",
                severity="critical",
                confidence=0.98,
                rationale=rationale,
            ))

    by_id: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        by_id.setdefault(assessment["assessment_id"], assessment)
    return list(by_id.values()), indicators


def assessment_summary(
    assessments: Iterable[dict[str, Any]],
    indicators: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    unique = {
        _text(item.get("assessment_id"), limit=128): item
        for item in assessments
        if isinstance(item, dict) and _text(item.get("assessment_id"), limit=128)
    }
    counts = {"strengths": 0, "vulnerabilities": 0, "threats": 0}
    active_ids: list[str] = []
    for assessment_id, item in unique.items():
        if _text(item.get("lifecycle"), limit=32).lower() in _INACTIVE_LIFECYCLES:
            continue
        category = _text(item.get("category"), limit=32).lower()
        plural = {"strength": "strengths", "vulnerability": "vulnerabilities", "threat": "threats"}.get(category)
        if plural:
            counts[plural] += 1
            active_ids.append(assessment_id)
    indicator_list = [dict(item) for item in indicators if isinstance(item, dict)][:MAX_EVIDENCE_REFS]
    return {
        "schema": ASSESSMENT_SUMMARY_SCHEMA,
        "total": sum(counts.values()),
        "counts": counts,
        "active_assessment_refs": sorted(active_ids),
        "indicators": indicator_list,
        "rule_registry_version": RULE_REGISTRY_VERSION,
    }


def assess_network_events(events_payload: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assessments_by_id: dict[str, dict[str, Any]] = {}
    indicators_by_id: dict[str, dict[str, Any]] = {}
    for event in events_payload:
        retained_assessments = event.get("assessments") if isinstance(event, dict) else None
        if isinstance(retained_assessments, list):
            event_assessments = [
                normalized
                for item in retained_assessments
                if isinstance(item, dict)
                for normalized in [_assessment_from_transition(item)]
                if normalized is not None
            ]
            _derived, event_indicators = assess_network_event(event)
        else:
            event_assessments, event_indicators = assess_network_event(event)
        for assessment in event_assessments:
            existing = assessments_by_id.get(assessment["assessment_id"])
            if existing:
                incoming_is_latest = assessment["last_seen"] >= existing["last_seen"]
                existing["first_seen"] = min(existing["first_seen"], assessment["first_seen"])
                existing["last_seen"] = max(existing["last_seen"], assessment["last_seen"])
                existing["evidence_refs"] = sorted(set([
                    *existing.get("evidence_refs", []),
                    *assessment.get("evidence_refs", []),
                ]))[:MAX_EVIDENCE_REFS]
                if incoming_is_latest:
                    existing["lifecycle"] = assessment["lifecycle"]
                    existing["assessment_state"] = assessment["assessment_state"]
                    existing["disposition"] = assessment["disposition"]
                    existing["owner_disposition"] = assessment["owner_disposition"]
                    existing["cursor"] = assessment.get("cursor") or existing.get("cursor")
                    existing["source_cursor"] = assessment.get("source_cursor") or existing.get("source_cursor")
                    existing["generation"] = assessment.get("generation", existing.get("generation"))
            else:
                assessments_by_id[assessment["assessment_id"]] = assessment
        for indicator in event_indicators:
            indicators_by_id.setdefault(indicator["indicator_id"], indicator)
    return (
        [assessments_by_id[key] for key in sorted(assessments_by_id)],
        [indicators_by_id[key] for key in sorted(indicators_by_id)],
    )


def _assessment_from_transition(value: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a retained assessment or append-only transition envelope."""
    if not isinstance(value, dict):
        return None
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    candidate = (
        value.get("security_assessment")
        if isinstance(value.get("security_assessment"), dict)
        else data.get("security_assessment")
        if isinstance(data.get("security_assessment"), dict)
        else value
    )
    if not isinstance(candidate, dict):
        return None
    assessment_id = _text(candidate.get("assessment_id"), limit=128)
    category = _text(candidate.get("category"), limit=32).lower()
    observed_at = _timestamp(candidate.get("last_seen") or candidate.get("timestamp") or value.get("timestamp"))
    if not assessment_id or category not in _CATEGORIES or observed_at is None:
        return None
    normalized = dict(candidate)
    normalized["assessment_id"] = assessment_id
    normalized["category"] = category
    normalized["last_seen"] = observed_at
    state = _text(
        candidate.get("assessment_state") or candidate.get("lifecycle"),
        limit=32,
    ).lower() or "active"
    normalized["assessment_state"] = state
    normalized["lifecycle"] = state
    return normalized


def active_assessment_series(
    buckets: Iterable[dict[str, Any]],
    transitions: Iterable[dict[str, Any]],
    *,
    metric: str,
) -> list[dict[str, Any]]:
    """Apply ordered assessment transitions at each covered bucket boundary.

    Transitions before the first bucket seed active posture. Covered quiet
    buckets produce a truthful zero; uncovered buckets remain explicit gaps
    with ``value=None``. The caller retains authority for bucket geometry and
    coverage (for CleanHouse this is the existing retained Trend tick stream).
    """
    selected_metric = _text(metric, limit=32).lower()
    if selected_metric not in SUPPORTED_TREND_METRICS:
        raise ValueError("unsupported Network Trend metric")
    ordered_buckets: list[tuple[datetime, dict[str, Any]]] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        end_text = _timestamp(bucket.get("bucket_end") or bucket.get("timestamp"))
        if end_text is None:
            continue
        ordered_buckets.append((datetime.fromisoformat(end_text.replace("Z", "+00:00")), dict(bucket)))
    ordered_buckets.sort(key=lambda item: item[0])

    ordered_transitions: list[tuple[datetime, str, dict[str, Any]]] = []
    seen_transition_keys: set[tuple[str, str, str, str]] = set()
    for raw in transitions:
        normalized = _assessment_from_transition(raw)
        if normalized is None:
            continue
        at = datetime.fromisoformat(str(normalized["last_seen"]).replace("Z", "+00:00"))
        key = (
            normalized["assessment_id"],
            normalized["assessment_state"],
            normalized["last_seen"],
            _text(normalized.get("source_cursor") or normalized.get("cursor"), limit=256),
        )
        if key in seen_transition_keys:
            continue
        seen_transition_keys.add(key)
        ordered_transitions.append((at, normalized["assessment_id"], normalized))
    ordered_transitions.sort(key=lambda item: (item[0], item[1]))

    active: dict[str, dict[str, Any]] = {}
    transition_index = 0
    category = {
        "strengths": "strength",
        "vulnerabilities": "vulnerability",
        "threats": "threat",
    }.get(selected_metric)
    result: list[dict[str, Any]] = []
    for bucket_end, bucket in ordered_buckets:
        while transition_index < len(ordered_transitions) and ordered_transitions[transition_index][0] < bucket_end:
            _at, assessment_id, transition = ordered_transitions[transition_index]
            active[assessment_id] = transition
            transition_index += 1
        output = dict(bucket)
        coverage = _text(bucket.get("coverage_state"), limit=32).lower()
        is_gap = bool(bucket.get("gap")) or coverage in {"gap", "unknown", "missing", "unavailable"}
        if is_gap:
            output.update({
                "metric": selected_metric,
                "value": None,
                "gap": True,
                "assessment_refs": [],
                "assessment_counts": None,
            })
            result.append(output)
            continue
        counts = {"strengths": 0, "vulnerabilities": 0, "threats": 0}
        active_refs: list[str] = []
        for assessment_id, assessment in active.items():
            if assessment.get("assessment_state") in _INACTIVE_LIFECYCLES:
                continue
            plural = {
                "strength": "strengths",
                "vulnerability": "vulnerabilities",
                "threat": "threats",
            }.get(str(assessment.get("category") or ""))
            if plural:
                counts[plural] += 1
                if category is None or assessment.get("category") == category:
                    active_refs.append(assessment_id)
        value = int(bucket.get("connectionCount") or 0) if selected_metric == "connections" else counts[selected_metric]
        output.update({
            "metric": selected_metric,
            "value": value,
            "gap": False,
            "assessment_refs": sorted(active_refs),
            "assessment_counts": counts,
        })
        result.append(output)
    return result


def add_assessment_contract(
    payload: dict[str, Any],
    events_payload: Iterable[dict[str, Any]],
    *,
    metric: str = "connections",
    category: str = "all",
) -> dict[str, Any]:
    result = dict(payload)
    retained_events = [dict(item) for item in events_payload if isinstance(item, dict)]
    assessments, indicators = assess_network_events(retained_events)
    gap_events = [
        item
        for item in retained_events
        if item.get("gap") is True
        or _text(item.get("coverage_state"), limit=32).lower()
        in {"gap", "unknown", "missing", "unavailable"}
        or _text(item.get("event_type"), limit=64) == "network_timeline_gap"
    ]
    assessed_event_count = 0
    for item in retained_events:
        attached = item.get("assessments")
        if isinstance(attached, list) and any(isinstance(value, dict) for value in attached):
            assessed_event_count += 1
            continue
        derived, _neutral = assess_network_event(item)
        if derived:
            assessed_event_count += 1
    if not retained_events:
        coverage_state = "no_data"
    elif len(gap_events) == len(retained_events):
        coverage_state = "gap"
    elif gap_events:
        coverage_state = "partial"
    else:
        coverage_state = "observed"
    gap_refs = []
    for item in gap_events:
        reference = _event_id(item)
        if reference and reference not in gap_refs:
            gap_refs.append(reference)
        if len(gap_refs) >= MAX_EVIDENCE_REFS:
            break
    result["assessments"] = assessments
    result["assessment_refs"] = sorted(item["assessment_id"] for item in assessments)
    result["assessment_summary"] = assessment_summary(assessments, indicators)
    result["assessment_filter"] = {"category": category, "metric": metric}
    result["assessment_rule_version"] = RULE_REGISTRY_VERSION
    result["assessment_coverage"] = {
        "state": coverage_state,
        "retained_event_count": len(retained_events),
        "assessed_event_count": assessed_event_count,
        "gap_count": len(gap_events),
    }
    result["assessment_gap"] = {
        "present": bool(gap_events),
        "count": len(gap_events),
        "evidence_refs": gap_refs,
    }
    return result


def persist_network_assessment_transitions(
    event: dict[str, Any],
    *,
    insert_event: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Append derived transition records after the raw Network event exists."""
    # Collector fan-out intentionally carries the canonical assessments that
    # were derived before the public event was reduced to its bounded wire
    # shape.  Re-deriving here would silently lose assessments whenever the
    # public allowlist omits a classifier input (for example a verified
    # provider verdict).  The aggregate helper prefers retained assessments
    # and only derives them when the event has none.
    assessments, _indicators = assess_network_events([event])
    if not assessments:
        return []
    if insert_event is None:
        from backend import events as event_store

        insert_event = event_store.insert_event
    source_id = _event_id(event)
    for assessment in assessments:
        transition_key = _stable_id(
            "network-assessment-transition",
            assessment["assessment_id"],
            assessment["lifecycle"],
            source_id,
        )
        insert_event(
            event_type=ASSESSMENT_TRANSITION_EVENT_TYPE,
            path=f"/network/assessments/{assessment['assessment_id']}",
            summary=assessment["rationale"],
            timestamp=assessment["last_seen"],
            source_surface="network",
            actor_type="cleanhouse",
            evidence_level="derived",
            collector_status="ok",
            scope_relation="network_assessment",
            evidence_refs=assessment["evidence_refs"],
            source_event_key=transition_key,
            provider="cleanhouse",
            data={"security_assessment": assessment},
        )
    return assessments


def canonical_json_digest(value: Any) -> str:
    """Stable digest helper used by tests and append-only assessment identity."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

