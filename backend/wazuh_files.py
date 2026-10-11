"""Authenticated Wazuh FIM ingestion for the CleanHouse Files event spine."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from backend import events, file_integrity, vvault_sync, wazuh_runtime


SOURCE = "wazuh_fim"
COLLECTOR = "wazuh_fim_vvault"
EXCLUDED_SCOPE_PARTS = frozenset({
    ".git",
    ".venv",
    "venv",
    "cleanhouse_env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "runtime",
    "generated_evidence",
    "bundled",
})
EXCLUDED_FILE_SUFFIXES = (".pyc", ".pyo", ".swp", ".db-wal", ".db-shm", ".db-journal")
_STOP = threading.Event()
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STATE: dict[str, Any] = {
    "authenticated": False,
    "authenticated_event_count": 0,
    "last_event_at": "",
    "last_poll_at": "",
    "last_success_at": "",
    "last_error": "",
    "last_error_at": "",
    "ingestion_latency_ms": None,
    "agent_id": "",
    "manager": "",
    "manager_version": "",
    "stream_identity": "",
    "stream_generation": "",
    "gap_state": "unknown",
    "monitored_scope": "",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _secure_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _path_within_scope(path: str, scope: str) -> bool:
    try:
        candidate = Path(path).expanduser().resolve(strict=False)
        boundary = Path(scope).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return False
    return candidate == boundary or boundary in candidate.parents


def _path_excluded_from_scope(path: str, scope: str) -> bool:
    try:
        candidate = Path(path).expanduser().resolve(strict=False)
        boundary = Path(scope).expanduser().resolve(strict=False)
        relative = candidate.relative_to(boundary)
    except (OSError, RuntimeError, ValueError):
        return True
    return (
        any(part in EXCLUDED_SCOPE_PARTS for part in relative.parts)
        or candidate.name == ".DS_Store"
        or candidate.name.endswith(EXCLUDED_FILE_SUFFIXES)
    )


def _config() -> dict[str, Any]:
    vvault_url = vvault_sync.remote_base_url()
    headers = vvault_sync.authenticated_headers()
    return {
        "events_url": (
            os.getenv("CLEANHOUSE_WAZUH_EVENTS_URL")
            or (f"{vvault_url}/api/cleanhouse/files/wazuh/events" if vvault_url else "")
        ).strip(),
        "inventory_url": (
            os.getenv("CLEANHOUSE_WAZUH_INVENTORY_URL")
            or (f"{vvault_url}/api/cleanhouse/files/wazuh/inventory" if vvault_url else "")
        ).strip(),
        "status_url": (
            os.getenv("CLEANHOUSE_WAZUH_STATUS_URL")
            or (f"{vvault_url}/api/cleanhouse/files/wazuh/status" if vvault_url else "")
        ).strip(),
        "enroll_url": (
            os.getenv("CLEANHOUSE_WAZUH_ENROLL_URL")
            or (f"{vvault_url}/api/cleanhouse/files/wazuh/enroll" if vvault_url else "")
        ).strip(),
        "service_token": (
            os.getenv("CLEANHOUSE_VVAULT_SERVICE_TOKEN")
            or os.getenv("VVAULT_SERVICE_TOKEN")
            or ""
        ).strip(),
        "owner_email": (
            os.getenv("CLEANHOUSE_VVAULT_USER_EMAIL")
            or os.getenv("VVAULT_USER_EMAIL")
            or ""
        ).strip().lower(),
        "owner_user_id": os.getenv("CLEANHOUSE_VVAULT_USER_ID", "").strip(),
        "instance_id": os.getenv("CLEANHOUSE_VVAULT_INSTANCE_ID", "zen-001").strip().lower(),
        "scope": os.getenv("CLEANHOUSE_WATCH_DIR", str(events.DEFAULT_WATCH_DIR)).strip(),
        "agent_id": os.getenv("CLEANHOUSE_WAZUH_AGENT_ID", "").strip(),
        "auth_headers": headers,
    }


def _authorization_headers(config: dict[str, Any]) -> dict[str, str]:
    paired = config.get("auth_headers")
    if isinstance(paired, dict) and paired:
        return {str(key): str(value) for key, value in paired.items() if str(value)}
    if not config["service_token"] or not config["owner_email"]:
        return {}
    headers = {
        "X-Chatty-Key": config["service_token"],
        "X-Chatty-User": config["owner_email"],
        "X-CleanHouse-Instance": config["instance_id"],
    }
    if config["owner_user_id"]:
        headers["X-Chatty-User-Id"] = config["owner_user_id"]
    return headers


def enroll_agent(
    *,
    manager: str,
    agent_name: str,
    monitored_scope: str,
    transport: Callable[[urllib.request.Request], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Request an owner-scoped, idempotent agent key from authenticated VVAULT.

    The returned client key is deliberately transient: callers must move it to
    Keychain immediately and must never persist it in logs, events, or receipts.
    """
    config = _config()
    headers = _authorization_headers(config)
    if not config["enroll_url"] or not headers:
        raise RuntimeError("Authenticated VVAULT enrollment is not configured")
    payload = _request_json(
        config["enroll_url"],
        headers=headers,
        body={
            "instance_id": config["instance_id"],
            "agent_name": agent_name,
            "manager": manager,
            "monitored_scope": monitored_scope,
        },
        transport=transport,
    )
    if (
        payload.get("schema") != "vvault.cleanhouse.wazuh_enrollment.v1"
        or payload.get("provider") != "wazuh_manager"
        or payload.get("evidence_authenticated") is not True
    ):
        raise RuntimeError("VVAULT returned an unauthenticated or incompatible enrollment response")
    agent_id = str(payload.get("agent_id") or "").strip()
    client_key = str(payload.get("client_key") or "").strip()
    key_fingerprint = str(payload.get("key_fingerprint") or "").strip().lower()
    if not agent_id or not client_key or len(key_fingerprint) != 64:
        raise RuntimeError("VVAULT returned an incomplete Wazuh enrollment response")
    if hashlib.sha256(client_key.encode("utf-8")).hexdigest() != key_fingerprint:
        raise RuntimeError("VVAULT enrollment key fingerprint did not match the returned client key")
    return {
        "status": "ok",
        "agent_id": agent_id,
        "agent_name": str(payload.get("agent_name") or agent_name),
        "manager": str(payload.get("manager") or manager),
        "monitored_scope": str(payload.get("monitored_scope") or monitored_scope),
        "key_fingerprint": key_fingerprint,
        "receipt_id": str(payload.get("receipt_id") or ""),
        "client_key": client_key,
    }


def _request_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    transport: Callable[[urllib.request.Request], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not _secure_url(url):
        raise RuntimeError("Wazuh endpoint must use HTTPS, except for localhost development")
    request = urllib.request.Request(
        url,
        data=(json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None),
        headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
        method="POST" if body is not None else "GET",
    )
    if transport is not None:
        result = transport(request)
        if not isinstance(result, dict):
            raise RuntimeError("Wazuh transport returned an invalid payload")
        return result
    with urllib.request.urlopen(request, timeout=10, context=ssl.create_default_context()) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Wazuh endpoint returned a non-object payload")
    return payload


def _canonical_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def normalize_hit(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source") if isinstance(hit.get("_source"), dict) else hit
    data = source.get("data") if isinstance(source.get("data"), dict) else {}
    syscheck = (
        data.get("syscheck")
        if isinstance(data.get("syscheck"), dict)
        else (source.get("syscheck") if isinstance(source.get("syscheck"), dict) else {})
    )
    agent = source.get("agent") if isinstance(source.get("agent"), dict) else {}
    manager = source.get("manager") if isinstance(source.get("manager"), dict) else {}
    cluster = source.get("cluster") if isinstance(source.get("cluster"), dict) else {}
    rule = source.get("rule") if isinstance(source.get("rule"), dict) else {}
    path = str(syscheck.get("path") or syscheck.get("file") or "").strip()
    if not path:
        raise ValueError("Wazuh FIM alert is missing data.syscheck.path")
    raw_event = str(syscheck.get("event") or syscheck.get("action") or "modified").lower()
    operation_map = {
        "added": "created",
        "created": "created",
        "modified": "modified",
        "changed": "modified",
        "deleted": "deleted",
        "removed": "deleted",
        "moved": "moved",
        "renamed": "moved",
    }
    operation = operation_map.get(raw_event, "metadata" if "attribute" in raw_event else "modified")
    raw_changed = syscheck.get("changed_attributes") or syscheck.get("changed_fields") or []
    if isinstance(raw_changed, str):
        changed_attributes = [item.strip().lower() for item in raw_changed.split(",") if item.strip()]
    elif isinstance(raw_changed, list):
        changed_attributes = [str(item).strip().lower() for item in raw_changed if str(item).strip()]
    else:
        changed_attributes = []
    ownership_fields = {"uid", "gid", "uname", "gname", "owner", "group"}
    permission_fields = {"perm", "permission", "permissions", "mode"}
    hash_fields = {"md5", "sha1", "sha256", "hash"}
    change_kinds = ["content"] if any(item in hash_fields for item in changed_attributes) else []
    if any(item in ownership_fields for item in changed_attributes):
        change_kinds.append("ownership")
    if any(item in permission_fields for item in changed_attributes):
        change_kinds.append("permission")
    if changed_attributes and not change_kinds:
        change_kinds.append("metadata")
    if operation == "modified" and "content" not in change_kinds:
        if "permission" in change_kinds:
            operation = "permission"
        elif "ownership" in change_kinds:
            operation = "ownership"
        elif "metadata" in change_kinds:
            operation = "metadata"
    old_path = str(syscheck.get("old_path") or syscheck.get("previous_path") or "").strip()
    index = str(hit.get("_index") or "")
    document_id = str(hit.get("_id") or source.get("id") or _canonical_hash(source))
    timestamp = str(source.get("timestamp") or syscheck.get("mtime_after") or _now())
    hashes = {
        key: str(syscheck.get(f"{key}_after") or syscheck.get(key) or "")
        for key in ("sha256", "sha1", "md5")
        if str(syscheck.get(f"{key}_after") or syscheck.get(key) or "")
    }
    metadata = {
        "size": syscheck.get("size_after", syscheck.get("size")),
        "mode": syscheck.get("perm_after", syscheck.get("perm")),
        "uid": syscheck.get("uid_after", syscheck.get("uid")),
        "gid": syscheck.get("gid_after", syscheck.get("gid")),
        "owner": syscheck.get("uname_after", syscheck.get("uname")),
        "group": syscheck.get("gname_after", syscheck.get("gname")),
        "mtime": syscheck.get("mtime_after", syscheck.get("mtime")),
        "inode": syscheck.get("inode_after", syscheck.get("inode")),
        "file_type": syscheck.get("type"),
    }
    metadata = {key: value for key, value in metadata.items() if value is not None and str(value) != ""}
    evidence_refs = [
        (
            f"wazuh-manager-alert://{document_id}"
            if index == "wazuh-manager-alerts"
            else (f"wazuh-index://{index}/{document_id}" if index else f"wazuh-alert://{document_id}")
        ),
    ]
    if agent.get("id"):
        evidence_refs.append(f"wazuh-agent://{agent['id']}")
    if rule.get("id"):
        evidence_refs.append(f"wazuh-rule://{rule['id']}")
    manager_generation = str(manager.get("generation") or cluster.get("node") or manager.get("id") or "")
    if manager.get("name"):
        evidence_refs.append(
            f"wazuh-manager://{manager['name']}" + (f"/{manager_generation}" if manager_generation else "")
        )
    return {
        "source_event_key": f"wazuh:{index}:{document_id}",
        "cursor": str(
            hit.get("_vvault_cursor")
            or json.dumps(hit.get("sort") or [timestamp, document_id], separators=(",", ":"))
        ),
        "operation": operation,
        "change_kinds": change_kinds or [operation],
        "changed_attributes": changed_attributes,
        "event_type": operation,
        "path": path,
        "old_path": old_path,
        "timestamp": timestamp,
        "original_timestamp": timestamp,
        "provider": "wazuh",
        "alert_id": document_id,
        "index": index,
        "agent_id": str(agent.get("id") or ""),
        "agent_name": str(agent.get("name") or ""),
        "manager": str(manager.get("name") or ""),
        "manager_generation": manager_generation,
        "rule_id": str(rule.get("id") or ""),
        "rule_description": str(rule.get("description") or ""),
        "hashes": hashes,
        "metadata": metadata,
        "evidence_refs": evidence_refs,
        "raw_evidence_ref": evidence_refs[0],
        "raw_payload_hash": str(hit.get("_vvault_raw_sha256") or _canonical_hash(source)),
    }


def ingest_hits(hits: Iterable[dict[str, Any]]) -> dict[str, Any]:
    inserted = 0
    duplicates = 0
    errors: list[str] = []
    for hit in hits:
        try:
            normalized = normalize_hit(hit)
            operation = normalized["operation"]
            path = normalized["path"]
            observed = _parse_time(normalized["timestamp"])
            latency = None
            if observed is not None:
                latency = max(0, int((datetime.now(timezone.utc) - observed).total_seconds() * 1000))
            normalized["ingestion_latency_ms"] = latency
            # Stage idempotent projections first. If either durable store is
            # unavailable, the provider cursor is not advanced and this alert
            # is retried. A later retry reuses the same observation/outbox IDs.
            generation = file_integrity.observe(normalized)
            preservation_payload = {
                **normalized,
                "baseline_generation": generation["generation"],
            }
            # Ingestion latency is a live transport metric, not provider
            # evidence. Preserving it would make the same immutable alert
            # collide on replay merely because wall-clock time advanced.
            preservation_payload.pop("ingestion_latency_ms", None)
            vvault_sync.enqueue(
                normalized["source_event_key"],
                preservation_payload,
            )
            result = events.insert_event_with_cursor(
                collector=COLLECTOR,
                cursor=normalized["cursor"],
                source_event_key=normalized["source_event_key"],
                event_type=operation,
                path=path,
                summary=f"Wazuh observed {operation}: {path}",
                timestamp=normalized["timestamp"],
                source_surface=SOURCE,
                provider="wazuh",
                actor_type="unattributed",
                evidence_level="authenticated",
                collector_status="ok",
                scope_relation="observed",
                evidence_refs=normalized["evidence_refs"],
                raw_evidence_ref=normalized["raw_evidence_ref"],
                data={"wazuh": normalized, **normalized},
                cursor_metadata={"agent_id": normalized["agent_id"], "manager": normalized["manager"]},
            )
            if result["inserted"]:
                inserted += 1
            else:
                duplicates += 1
            with _LOCK:
                _STATE.update(
                    {
                        "authenticated": True,
                        "authenticated_event_count": int(_STATE["authenticated_event_count"]) + (1 if result["inserted"] else 0),
                        "last_event_at": normalized["timestamp"],
                        "last_success_at": _now(),
                        "last_error": "",
                        "last_error_at": "",
                        "ingestion_latency_ms": latency,
                        "agent_id": normalized["agent_id"],
                        "manager": normalized["manager"],
                    }
                )
        except Exception as exc:
            errors.append(str(exc)[:512])
    return {"status": "ok" if not errors else "degraded", "inserted": inserted, "duplicates": duplicates, "errors": errors}


def poll_once(*, transport: Callable[[urllib.request.Request], dict[str, Any]] | None = None) -> dict[str, Any]:
    config = _config()
    if not config["events_url"] or not _authorization_headers(config):
        return {"status": "unavailable", "reason": "authenticated_vvault_feed_missing"}
    cursor = str(events.get_collector_cursor(COLLECTOR).get("cursor") or "")
    parsed = urllib.parse.urlparse(config["events_url"])
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"after": cursor, "limit": "100"})
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    try:
        payload = _request_json(
            url,
            headers=_authorization_headers(config),
            transport=transport,
        )
        if (
            payload.get("schema") != "vvault.cleanhouse.wazuh_feed.v1"
            or payload.get("provider") != "wazuh_manager"
            or payload.get("evidence_authenticated") is not True
        ):
            raise RuntimeError("VVAULT returned an unauthenticated or incompatible Wazuh feed")
        hits = payload.get("items") if isinstance(payload.get("items"), list) else []
        feed_agent_id = str(payload.get("agent_id") or "").strip()
        expected_agent_id = str(config.get("agent_id") or _STATE.get("agent_id") or "").strip()
        if expected_agent_id and feed_agent_id and feed_agent_id != expected_agent_id:
            raise RuntimeError("VVAULT Wazuh feed agent does not match the enrolled CleanHouse agent")
        monitored_scope = str(payload.get("monitored_scope") or config["scope"]).strip()
        if not monitored_scope:
            raise RuntimeError("VVAULT Wazuh feed omitted the monitored scope")
        accepted_hits = []
        for hit in hits:
            normalized = normalize_hit(hit)
            if feed_agent_id and normalized["agent_id"] != feed_agent_id:
                raise RuntimeError("VVAULT Wazuh feed contained evidence for another agent")
            if not _path_within_scope(normalized["path"], monitored_scope):
                raise RuntimeError("VVAULT Wazuh feed contained evidence outside the monitored scope")
            if _path_excluded_from_scope(normalized["path"], monitored_scope):
                continue
            accepted_hits.append(hit)
        result = ingest_hits(accepted_hits)
        page_cursor = str(payload.get("cursor") or "").strip()
        if page_cursor and not result.get("errors"):
            events.advance_collector_cursor(
                collector=COLLECTOR,
                cursor=page_cursor,
                metadata={
                    "agent_id": feed_agent_id,
                    "manager": str(payload.get("manager") or ""),
                    "stream_identity": str(payload.get("stream_identity") or ""),
                    "stream_generation": str(payload.get("stream_generation") or ""),
                    "gap_state": str(payload.get("gap_state") or "none_observed"),
                },
            )
        with _LOCK:
            _STATE.update({
                "authenticated": True,
                "last_poll_at": _now(),
                "last_success_at": _now(),
                "last_error": "",
                "last_error_at": "",
                "agent_id": feed_agent_id or _STATE.get("agent_id", ""),
                "manager": str(payload.get("manager") or _STATE.get("manager") or ""),
                "manager_version": str(payload.get("manager_version") or ""),
                "stream_identity": str(payload.get("stream_identity") or ""),
                "stream_generation": str(payload.get("stream_generation") or ""),
                "gap_state": str(payload.get("gap_state") or "none_observed"),
                "monitored_scope": monitored_scope,
            })
        return {
            **result,
            "authenticated": True,
            "received": len(accepted_hits),
            "filtered": len(hits) - len(accepted_hits),
        }
    except Exception as exc:
        message = str(exc)[:1024]
        with _LOCK:
            _STATE.update(
                {
                    "authenticated": False,
                    "last_poll_at": _now(),
                    "last_error": message,
                    "last_error_at": _now(),
                }
            )
        return {"status": "degraded", "authenticated": False, "reason": "wazuh_poll_failed", "error": message}


def inventory(*, transport: Callable[[urllib.request.Request], dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    config = _config()
    if not config["inventory_url"]:
        raise RuntimeError("VVAULT Wazuh FIM inventory endpoint is not configured")
    headers = _authorization_headers(config)
    if not headers:
        raise RuntimeError("Authenticated VVAULT owner credentials are not configured")
    page_size = 500
    try:
        configured_max = int(os.getenv("CLEANHOUSE_WAZUH_INVENTORY_MAX_ENTRIES", "10000"))
    except ValueError:
        configured_max = 10000
    max_entries = max(1, min(configured_max, 100000))
    rows: list[dict[str, Any]] = []
    inventory_agent_id = ""
    inventory_scope = ""
    offset = 0
    source_total = 0
    source_complete = False
    while len(rows) < max_entries:
        parsed = urllib.parse.urlparse(config["inventory_url"])
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        query.update({"offset": str(offset), "limit": str(min(page_size, max_entries - len(rows)))})
        page_url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
        payload = _request_json(page_url, headers=headers, transport=transport)
        if (
            payload.get("schema") != "vvault.cleanhouse.wazuh_inventory.v1"
            or payload.get("provider") != "wazuh_manager"
            or payload.get("evidence_authenticated") is not True
        ):
            raise RuntimeError("VVAULT returned an unauthenticated or incompatible Wazuh inventory")
        page_agent_id = str(payload.get("agent_id") or "").strip()
        page_scope = str(payload.get("monitored_scope") or config["scope"]).strip()
        expected_agent_id = str(config.get("agent_id") or _STATE.get("agent_id") or "").strip()
        if expected_agent_id and page_agent_id and page_agent_id != expected_agent_id:
            raise RuntimeError("VVAULT Wazuh inventory agent does not match the enrolled CleanHouse agent")
        if inventory_agent_id and page_agent_id and page_agent_id != inventory_agent_id:
            raise RuntimeError("VVAULT Wazuh inventory changed agents during pagination")
        if inventory_scope and page_scope and page_scope != inventory_scope:
            raise RuntimeError("VVAULT Wazuh inventory changed scope during pagination")
        inventory_agent_id = page_agent_id or inventory_agent_id
        inventory_scope = page_scope or inventory_scope
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        affected = data.get("affected_items") if isinstance(data, dict) else None
        page = affected if isinstance(affected, list) else (data.get("items", []) if isinstance(data, dict) else [])
        rows.extend(item for item in page if isinstance(item, dict))
        if isinstance(data, dict):
            source_page_count = int(data.get("source_page_count") or len(page))
            source_total = int(
                data.get("source_total_affected_items")
                or data.get("total_affected_items")
                or (offset + source_page_count)
            )
            next_offset = int(data.get("next_offset") or (offset + source_page_count))
            source_complete = bool(data.get("complete")) or next_offset >= source_total
        else:
            source_page_count = len(page)
            source_total = offset + source_page_count
            next_offset = source_total
            source_complete = True
        if source_complete or source_page_count <= 0 or next_offset <= offset:
            break
        offset = next_offset
    if not source_complete and len(rows) >= max_entries:
        raise RuntimeError(f"Wazuh inventory exceeded configured limit of {max_entries} entries")
    result = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        path = str(item.get("file") or item.get("path") or "").strip()
        if not path:
            continue
        if inventory_scope and not _path_within_scope(path, inventory_scope):
            raise RuntimeError("VVAULT Wazuh inventory contained an entry outside the monitored scope")
        if inventory_scope and _path_excluded_from_scope(path, inventory_scope):
            continue
        item_agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
        item_agent_id = str(item.get("agent_id") or item_agent.get("id") or "").strip()
        if inventory_agent_id and item_agent_id and item_agent_id != inventory_agent_id:
            raise RuntimeError("VVAULT Wazuh inventory contained an entry for another agent")
        result.append(
            {
                "path": path,
                "provider": "wazuh",
                "observed_at": str(item.get("date") or item.get("mtime") or _now()),
                "hashes": {key: item[key] for key in ("sha256", "sha1", "md5") if item.get(key)},
                "metadata": {
                    key: item[key]
                    for key in ("size", "mode", "uid", "gid", "owner", "group", "mtime", "inode", "file_type")
                    if item.get(key) is not None
                },
                "evidence_refs": [f"wazuh-inventory://{item.get('id') or hashlib.sha256(path.encode()).hexdigest()[:24]}"],
                "agent_id": inventory_agent_id or item_agent_id,
                "baseline_authority": "authenticated_wazuh",
            }
        )
    return result


def status() -> dict[str, Any]:
    config = _config()
    cursor = events.get_collector_cursor(COLLECTOR)
    with _LOCK:
        state = dict(_STATE)
    if int(state.get("authenticated_event_count") or 0) == 0:
        retained = events.list_events(limit=1000, source_surface=SOURCE)
        state["authenticated_event_count"] = sum(
            1 for row in retained if row.get("provider") == "wazuh" and row.get("evidence_level") == "authenticated"
        )
        if retained and not state.get("last_event_at"):
            state["last_event_at"] = str(retained[0].get("timestamp") or "")
        if retained and state.get("ingestion_latency_ms") is None:
            retained_data = retained[0].get("data") if isinstance(retained[0].get("data"), dict) else {}
            retained_wazuh = retained_data.get("wazuh") if isinstance(retained_data.get("wazuh"), dict) else retained_data
            state["ingestion_latency_ms"] = retained_wazuh.get("ingestion_latency_ms")
        if state["authenticated_event_count"]:
            with _LOCK:
                _STATE["authenticated_event_count"] = state["authenticated_event_count"]
                if state.get("last_event_at"):
                    _STATE["last_event_at"] = state["last_event_at"]
                if state.get("ingestion_latency_ms") is not None:
                    _STATE["ingestion_latency_ms"] = state["ingestion_latency_ms"]
    configured = bool(config["events_url"] and _authorization_headers(config))
    runtime = wazuh_runtime.lifecycle_status(ingestion=state)
    if state["authenticated"] and state["authenticated_event_count"]:
        health = "live"
    elif state["authenticated"]:
        health = "no_data"
    elif configured and state["last_error"]:
        health = "degraded"
    elif configured:
        health = "warming"
    else:
        health = "unavailable"
    return {
        **state,
        "configured": configured,
        "health": health,
        "cursor": cursor.get("cursor") or "",
        "cursor_updated_at": cursor.get("updated_at") or "",
        "monitored_scope": state.get("monitored_scope") or config["scope"],
        "transport_provider": "vvault",
        "evidence_endpoint": config["events_url"],
        "lifecycle": runtime["lifecycle"],
        "runtime": runtime,
        "historical_wazuh_proof": int(state["authenticated_event_count"] or 0) > 0,
        "powered_by_wazuh": int(state["authenticated_event_count"] or 0) > 0,
    }


def _worker() -> None:
    while not _STOP.is_set():
        result = poll_once()
        _STOP.wait(1 if result.get("status") == "ok" else 15)


def start_service() -> dict[str, Any]:
    global _THREAD
    if not _config()["events_url"]:
        return status()
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _STOP.clear()
            _THREAD = threading.Thread(target=_worker, name="cleanhouse-wazuh-files", daemon=True)
            _THREAD.start()
    return status()


def stop_service(timeout: float = 5) -> dict[str, Any]:
    global _THREAD
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=max(0, timeout))
    stopped = thread is None or not thread.is_alive()
    if stopped:
        _THREAD = None
    return {"state": "stopped" if stopped else "stopping"}
