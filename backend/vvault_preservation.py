"""
Mirror selected CleanHouse artifacts into the user-scoped VVAULT tree.

This module is intentionally boring: it never replaces the local runtime DB or
local JSON artifact store, and preservation failures are returned as status
payloads instead of breaking the live runtime path.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corefiles import config

SCHEMA_VERSION = 1
MANIFEST_SCHEMA = "cleanhouse.vvault_manifest.v1"
ARTIFACT_SCHEMA = "cleanhouse.vvault_artifact.v1"
_WRITE_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_part(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9._:-]+", "_", text)
    text = text.strip("._")
    return text[:160] or fallback


def cleanhouse_root() -> Path | None:
    return config.cleanhouse_vvault_root()


def preservation_available() -> bool:
    return cleanhouse_root() is not None


def _disabled(reason: str = "missing_user_id") -> dict[str, Any]:
    return {"status": "disabled", "reason": reason}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return default.copy()
    return default.copy()


def _manifest_path(root: Path) -> Path:
    return root / "indexes" / "manifest.json"


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _index_entry(envelope: dict[str, Any], artifact_path: Path, root: Path) -> dict[str, Any]:
    return {
        "id": envelope["id"],
        "type": envelope["type"],
        "timestamp": envelope["timestamp"],
        "path": _relative(artifact_path, root),
        "source": envelope.get("source", ""),
        "app": envelope.get("app", ""),
        "severity": envelope.get("severity", ""),
        "report_type": envelope.get("report_type", ""),
    }


def _update_index_map(path: Path, key: str, entry: dict[str, Any]) -> None:
    payload = _read_json(path, {"schema": "cleanhouse.vvault_index.v1", "entries": {}})
    entries = payload.setdefault("entries", {})
    if isinstance(entries, dict):
        entries[key] = entry
    payload["updated_at"] = _now_iso()
    _atomic_write_json(path, payload)


def _update_manifest(root: Path, envelope: dict[str, Any], artifact_path: Path, *, new_artifact: bool) -> None:
    path = _manifest_path(root)
    user_id = config.vvault_user_id()
    default = {
        "schema": MANIFEST_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "user_id": user_id,
        "artifact_counts": {},
        "index_versions": {
            "by_time": 1,
            "by_app": 1,
            "by_severity": 1,
            "by_report": 1,
        },
    }
    payload = _read_json(path, default)
    payload["schema"] = MANIFEST_SCHEMA
    payload["schema_version"] = SCHEMA_VERSION
    payload["root"] = str(root)
    payload["user_id"] = user_id
    payload["updated_at"] = _now_iso()
    counts = payload.setdefault("artifact_counts", {})
    artifact_type = str(envelope.get("type") or "unknown")
    if isinstance(counts, dict) and new_artifact:
        counts[artifact_type] = int(counts.get(artifact_type) or 0) + 1
    latest = payload.setdefault("latest", {})
    if isinstance(latest, dict):
        latest[artifact_type] = {
            "id": envelope["id"],
            "timestamp": envelope["timestamp"],
            "path": _relative(artifact_path, root),
        }
    _atomic_write_json(path, payload)


def _update_indexes(root: Path, envelope: dict[str, Any], artifact_path: Path) -> None:
    entry = _index_entry(envelope, artifact_path, root)
    timestamp = str(envelope.get("timestamp") or _now_iso())
    day = _safe_part(timestamp[:10], "unknown-date")
    artifact_id = _safe_part(envelope.get("id"))
    _update_index_map(root / "indexes" / "by_time" / f"{day}.json", artifact_id, entry)
    if envelope.get("app"):
        _update_index_map(root / "indexes" / "by_app" / f"{_safe_part(envelope['app'])}.json", artifact_id, entry)
    if envelope.get("severity"):
        _update_index_map(root / "indexes" / "by_severity" / f"{_safe_part(envelope['severity'])}.json", artifact_id, entry)
    if envelope.get("report_type"):
        _update_index_map(root / "indexes" / "by_report" / f"{_safe_part(envelope['report_type'])}.json", artifact_id, entry)


def preserve_json(
    *,
    relative_dir: str,
    artifact_id: str,
    artifact_type: str,
    data: dict[str, Any],
    source: str,
    timestamp: str | None = None,
    local_ref: str = "",
    evidence_refs: list[Any] | None = None,
    app: str = "",
    severity: str = "",
    report_type: str = "",
) -> dict[str, Any]:
    root = cleanhouse_root()
    if root is None:
        _LOG.debug(
            "cleanhouse_vvault_save status=disabled type=%s id=%s reason=missing_user_id",
            artifact_type,
            artifact_id,
        )
        return _disabled()
    safe_dir = Path(relative_dir)
    if safe_dir.is_absolute() or ".." in safe_dir.parts:
        _LOG.warning(
            "cleanhouse_vvault_save status=error type=%s id=%s reason=invalid_relative_dir",
            artifact_type,
            artifact_id,
        )
        return {"status": "error", "message": "invalid relative_dir"}
    created_at = timestamp or str(data.get("timestamp") or data.get("created_at") or _now_iso())
    envelope = {
        "schema": ARTIFACT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "id": str(artifact_id),
        "type": str(artifact_type),
        "timestamp": created_at,
        "source": source,
        "local_ref": local_ref,
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [],
        "data": data,
    }
    if app:
        envelope["app"] = app
    if severity:
        envelope["severity"] = severity
    if report_type:
        envelope["report_type"] = report_type
    filename = f"{_safe_part(artifact_id)}.json"
    artifact_path = root / safe_dir / filename
    try:
        with _WRITE_LOCK:
            new_artifact = not artifact_path.exists()
            _atomic_write_json(artifact_path, envelope)
            _update_manifest(root, envelope, artifact_path, new_artifact=new_artifact)
            _update_indexes(root, envelope, artifact_path)
    except OSError as exc:
        _LOG.warning(
            "cleanhouse_vvault_save status=error type=%s id=%s error=%s",
            artifact_type,
            artifact_id,
            exc,
        )
        return {"status": "error", "message": f"vvault preservation failed: {exc}"}
    _LOG.debug(
        "cleanhouse_vvault_save status=ok type=%s id=%s timestamp=%s path=%s",
        artifact_type,
        artifact_id,
        created_at,
        _relative(artifact_path, root),
    )
    return {
        "status": "ok",
        "path": str(artifact_path),
        "root": str(root),
        "schema_version": SCHEMA_VERSION,
    }


def _parse_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _artifact_data(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data")
    return data if isinstance(data, dict) else {}


def load_artifacts(
    relative_dir: str,
    *,
    artifact_type: str = "",
    limit: int = 1000,
) -> list[dict[str, Any]]:
    root = cleanhouse_root()
    if root is None:
        _LOG.debug(
            "cleanhouse_vvault_load status=disabled directory=%s type=%s reason=missing_user_id",
            relative_dir,
            artifact_type or "any",
        )
        return []
    safe_dir = Path(relative_dir)
    if safe_dir.is_absolute() or ".." in safe_dir.parts:
        _LOG.warning(
            "cleanhouse_vvault_load status=error directory=%s type=%s reason=invalid_relative_dir",
            relative_dir,
            artifact_type or "any",
        )
        return []
    base = root / safe_dir
    if not base.exists():
        _LOG.info(
            "cleanhouse_vvault_load status=empty directory=%s type=%s count=0",
            relative_dir,
            artifact_type or "any",
        )
        return []
    envelopes = []
    for path in base.glob("*.json"):
        envelope = _read_json(path, {})
        if not envelope:
            continue
        if artifact_type and envelope.get("type") != artifact_type:
            continue
        envelopes.append(envelope)
    envelopes.sort(key=lambda item: (_parse_timestamp(item.get("timestamp")), str(item.get("id") or "")))
    selected = envelopes[-max(1, int(limit)):]
    _LOG.info(
        "cleanhouse_vvault_load status=ok directory=%s type=%s count=%s",
        relative_dir,
        artifact_type or "any",
        len(selected),
    )
    return selected


def _in_window(payload: dict[str, Any], start: datetime | None, end: datetime | None, timestamp_key: str = "timestamp") -> bool:
    timestamp = _parse_timestamp(payload.get(timestamp_key))
    if start and timestamp < start:
        return False
    if end and timestamp > end:
        return False
    return True


def _overlaps_window(
    payload: dict[str, Any],
    start: datetime | None,
    end: datetime | None,
    *,
    start_key: str,
    end_key: str,
) -> bool:
    interval_start = _parse_timestamp(payload.get(start_key) or payload.get("timestamp"))
    interval_end = _parse_timestamp(payload.get(end_key) or payload.get(start_key) or payload.get("timestamp"))
    if start and interval_end < start:
        return False
    if end and interval_start > end:
        return False
    return True


def load_network_trend_buckets(
    *,
    range_key: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    buckets = []
    for envelope in load_artifacts("network/trend/buckets", artifact_type="network_trend_bucket", limit=limit):
        bucket = _artifact_data(envelope)
        if range_key and bucket.get("bucket_range") and bucket.get("bucket_range") != range_key:
            continue
        if range_key and not bucket.get("bucket_range") and not str(bucket.get("bucket_key") or "").startswith(f"{range_key}:"):
            continue
        if not _overlaps_window(bucket, start, end, start_key="bucket_start", end_key="bucket_end"):
            continue
        buckets.append(bucket)
    return buckets


def load_network_trend_samples(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    samples = []
    for envelope in load_artifacts("network/trend/samples", artifact_type="network_trend_sample", limit=limit):
        sample = _artifact_data(envelope)
        if not _in_window(sample, start, end):
            continue
        samples.append(sample)
    return samples


def load_network_trend_ticks(
    *,
    range_key: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    ticks = []
    for envelope in load_artifacts("network/trend/ticks", artifact_type="network_trend_tick", limit=limit):
        tick = _artifact_data(envelope)
        if range_key and tick.get("bucket_range") != range_key:
            continue
        if not _in_window(tick, start, end):
            continue
        ticks.append(tick)
    return ticks


def load_network_timeline_notables(
    *,
    range_key: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    notables = []
    for envelope in load_artifacts("network/timeline/notable_events", artifact_type="network_timeline_notable", limit=limit):
        data = _artifact_data(envelope)
        if range_key and data.get("range") not in {"", range_key, "history"}:
            continue
        event = data.get("event") if isinstance(data.get("event"), dict) else data
        if not _in_window(event, start, end):
            continue
        notables.append(event)
    return notables


def load_network_timeline_gaps(
    *,
    range_key: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    gaps = []
    for envelope in load_artifacts("network/timeline/gaps", artifact_type="network_timeline_gap", limit=limit):
        data = _artifact_data(envelope)
        if range_key and data.get("range") not in {"", range_key, "history"}:
            continue
        gap = data.get("gap") if isinstance(data.get("gap"), dict) else data
        if not _in_window(gap, start, end):
            continue
        gaps.append(gap)
    return gaps


def _report_dir(report_type: str, data: dict[str, Any]) -> str:
    value = str(report_type or "").lower()
    if "network" in value:
        return "reports/network_reports"
    if "scan" in value:
        return "reports/scan_reports"
    if "letter" in value or data.get("concern_letter"):
        return "reports/letters_of_concern"
    return "reports/security_reports"


def preserve_local_artifact(artifact_type: str, artifact_id: str, payload: dict[str, Any], local_ref: str = "") -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if artifact_type == "report":
        report_type = str(data.get("report_type") or data.get("type") or "security")
        return preserve_json(
            relative_dir=_report_dir(report_type, data),
            artifact_id=artifact_id,
            artifact_type="report",
            data=payload,
            source="cleanhouse.local_artifact",
            timestamp=str(data.get("timestamp") or payload.get("created_at") or ""),
            local_ref=local_ref,
            evidence_refs=list(data.get("evidence_links") or data.get("evidence_refs") or []),
            severity=str(data.get("severity") or ""),
            report_type=report_type,
        )
    if artifact_type == "receipt":
        return preserve_json(
            relative_dir="receipts/investigations",
            artifact_id=artifact_id,
            artifact_type="receipt",
            data=payload,
            source="cleanhouse.local_artifact",
            timestamp=str(data.get("timestamp") or payload.get("created_at") or ""),
            local_ref=local_ref,
            evidence_refs=list(data.get("evidence_refs") or data.get("evidence_index") or []),
            severity=str(data.get("severity") or ""),
        )
    return _disabled("artifact_type_not_selected")


def preserve_network_trend_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(bucket.get("event_id") or bucket.get("bucket_key") or "")
    return preserve_json(
        relative_dir="network/trend/buckets",
        artifact_id=artifact_id,
        artifact_type="network_trend_bucket",
        data=bucket,
        source="cleanhouse.network",
        timestamp=str(bucket.get("timestamp") or bucket.get("bucket_start") or ""),
        local_ref=f"local://cleanhouse/network/trend/{bucket.get('bucket_key', artifact_id)}",
        evidence_refs=[bucket.get("source_event_id")] if bucket.get("source_event_id") else [],
    )


def preserve_network_trend_sample(sample: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(sample.get("sample_id") or sample.get("event_id") or sample.get("source_event_id") or "")
    return preserve_json(
        relative_dir="network/trend/samples",
        artifact_id=artifact_id,
        artifact_type="network_trend_sample",
        data=sample,
        source="cleanhouse.network",
        timestamp=str(sample.get("timestamp") or ""),
        local_ref=f"local://cleanhouse/network/{sample.get('source_event_id') or sample.get('event_id') or artifact_id}",
        evidence_refs=list(sample.get("evidence_refs") or []),
        app=str(sample.get("app") or sample.get("process") or ""),
        severity=str(sample.get("severity") or ""),
    )


def preserve_network_trend_tick(tick: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(tick.get("tick_id") or tick.get("event_id") or "")
    root = cleanhouse_root()
    if root is None:
        return _disabled()
    if not artifact_id:
        return {"status": "error", "message": "tick_id required"}
    artifact_path = root / "network" / "trend" / "ticks" / f"{_safe_part(artifact_id)}.json"
    if artifact_path.exists():
        return {
            "status": "ok",
            "path": str(artifact_path),
            "root": str(root),
            "schema_version": SCHEMA_VERSION,
            "immutable": True,
            "existing": True,
        }
    sealed = tick.copy()
    sealed.setdefault("tick_id", artifact_id)
    sealed.setdefault("event_id", artifact_id)
    sealed.setdefault("immutable", True)
    sealed.setdefault("sealed_at", sealed.get("timestamp") or _now_iso())
    return preserve_json(
        relative_dir="network/trend/ticks",
        artifact_id=artifact_id,
        artifact_type="network_trend_tick",
        data=sealed,
        source="cleanhouse.network",
        timestamp=str(sealed.get("timestamp") or sealed.get("sealed_at") or ""),
        local_ref=f"local://cleanhouse/network/trend/tick/{artifact_id}",
        evidence_refs=list(sealed.get("evidence_refs") or []),
        app=str(sealed.get("app") or sealed.get("process") or ""),
        severity=str(sealed.get("severity") or ""),
    )


def preserve_network_trend_tick_revision(revision: dict[str, Any]) -> dict[str, Any]:
    revision_of = str(revision.get("revision_of") or revision.get("supersedes") or "")
    seed = json.dumps(revision, sort_keys=True, default=str)
    revision_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    artifact_id = str(revision.get("revision_id") or f"network_trend_tick_revision:{_safe_part(revision_of)}:{revision_hash}")
    payload = revision.copy()
    payload.setdefault("revision_id", artifact_id)
    payload.setdefault("immutable", True)
    payload.setdefault("sealed_at", payload.get("timestamp") or _now_iso())
    return preserve_json(
        relative_dir="network/trend/revisions",
        artifact_id=artifact_id,
        artifact_type="network_trend_tick_revision",
        data=payload,
        source="cleanhouse.network",
        timestamp=str(payload.get("timestamp") or payload.get("sealed_at") or ""),
        local_ref=f"local://cleanhouse/network/trend/revision/{artifact_id}",
        evidence_refs=list(payload.get("evidence_refs") or []),
        app=str(payload.get("app") or payload.get("process") or ""),
        severity=str(payload.get("severity") or ""),
    )


def preserve_network_timeline_notable(event: dict[str, Any], range_key: str) -> dict[str, Any]:
    artifact_id = f"network_timeline:{event.get('event_id', '')}"
    return preserve_json(
        relative_dir="network/timeline/notable_events",
        artifact_id=artifact_id,
        artifact_type="network_timeline_notable",
        data={"range": range_key, "event": event},
        source="cleanhouse.network",
        timestamp=str(event.get("timestamp") or ""),
        local_ref=f"local://cleanhouse/network/{event.get('event_id', '')}",
        evidence_refs=list(event.get("evidence_refs") or event.get("related_event_ids") or []),
        app=str(event.get("app") or event.get("process") or ""),
        severity=str(event.get("severity") or ""),
    )


def preserve_network_timeline_gap(range_key: str, reason: str, window: dict[str, Any]) -> dict[str, Any]:
    day_key = str(window.get("gap_end") or window.get("end") or window.get("gap_start") or window.get("start") or _now_iso())[:10] or "unknown"
    artifact_id = str(window.get("event_id") or f"network_timeline_gap:{range_key}:{_safe_part(day_key)}:{_safe_part(reason)}")
    gap = window.copy()
    gap.setdefault("timestamp", gap.get("gap_end") or gap.get("end") or _now_iso())
    gap.setdefault("reason", reason)
    return preserve_json(
        relative_dir="network/timeline/gaps",
        artifact_id=artifact_id,
        artifact_type="network_timeline_gap",
        data={"range": range_key, "reason": reason, "gap": gap},
        source="cleanhouse.network",
        timestamp=str(gap.get("timestamp") or _now_iso()),
        local_ref="",
        evidence_refs=[],
    )
