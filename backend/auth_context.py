"""Request authentication for the device-local CleanHouse antivirus.

The Flask session is retained only for short-lived OAuth/CSRF transactions.
Authorization comes from an opaque, revocable device session or a personal API
token whose digest is held by :mod:`backend.auth_store`.
"""

from __future__ import annotations

import os
import secrets
import types
from dataclasses import dataclass
from typing import Any, Callable

import flask

g = getattr(flask, "g", types.SimpleNamespace())
request = getattr(flask, "request", types.SimpleNamespace(headers={}, cookies={}))
session = getattr(flask, "session", {})

from backend import auth_runtime_config
from backend.auth_store import AuthStore


DEVICE_COOKIE = "cleanhouse_device_session"
CSRF_HEADER = "X-CSRF-Token"
REAUTH_HEADER = "X-CleanHouse-Reauth"


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    kind: str
    credential_id: str
    user: dict[str, Any]
    consent_current: bool
    credential_metadata: dict[str, Any] | None = None


_store: AuthStore | None = None
_store_path: str | None = None


def get_store() -> AuthStore:
    global _store, _store_path
    configured = os.getenv("CLEANHOUSE_AUTH_DB", "").strip()
    if _store is None or configured != (_store_path or ""):
        _store = AuthStore(configured or None)
        _store_path = configured
    return _store


def reset_store_cache() -> None:
    """Test hook; production callers should not replace the authority."""
    global _store, _store_path
    _store = None
    _store_path = None


def _user_dict(user: Any) -> dict[str, Any] | None:
    if user is None or getattr(user, "is_active", True) is not True:
        return None
    user_id = str(getattr(user, "user_id", None) or getattr(user, "id", None) or "").strip()
    if not user_id:
        return None
    return {
        "user_id": user_id,
        "email": str(getattr(user, "email", "") or ""),
        "full_name": str(getattr(user, "full_name", "") or ""),
        "role": str(getattr(user, "role", "user") or "user"),
    }


def _bearer() -> str | None:
    value = str(request.headers.get("Authorization", "") or "").strip()
    if not value:
        return None
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1]


def resolve_identity(
    user_loader: Callable[[str], Any],
    consent_checker: Callable[[str], bool],
    *,
    allow_legacy_migration: bool = True,
) -> RequestIdentity | None:
    """Resolve the request once and fail closed on invalid credentials."""
    cached = getattr(g, "cleanhouse_identity_resolved", False)
    if cached:
        return getattr(g, "cleanhouse_identity", None)
    g.cleanhouse_identity_resolved = True

    bearer = _bearer()
    if bearer is not None:
        if not bearer.startswith("chpat_"):
            return None
        store = get_store()
        result = store.validate_api_token(bearer)
        if result.status != "valid" or not result.record:
            return None
        user_id = str(result.record["user_id"])
        user = _user_dict(user_loader(user_id))
        if not user:
            return None
        identity = RequestIdentity(user_id, "api_token", str(result.record["token_id"]), user, consent_checker(user_id))
        g.cleanhouse_identity = identity
        return identity

    raw = str(getattr(request, "cookies", {}).get(DEVICE_COOKIE, "") or "")
    if raw:
        store = get_store()
        result = store.validate_session(raw)
        if result.status not in {"valid", "rotated"} or not result.record:
            return None
        if result.replacement:
            g.cleanhouse_session_replacement = result.replacement
            previous = str(result.record.get("previous_session_id") or "")
            if previous:
                from backend.auth_mfa import CleanHouseMFA
                CleanHouseMFA(store.path).rebind_rotated_session(user_id=str(result.record["user_id"]), old_session_id=previous, new_session_id=result.replacement.id)
        user_id = str(result.record["user_id"])
        user = _user_dict(user_loader(user_id))
        if not user:
            return None
        metadata = result.record.get("metadata") if isinstance(result.record.get("metadata"), dict) else {}
        identity = RequestIdentity(user_id, "session", str(result.record["id"]), user, consent_checker(user_id), metadata)
        g.cleanhouse_identity = identity
        return identity

    legacy_user_id = str(session.get("user_id") or "").strip()
    if allow_legacy_migration and legacy_user_id:
        store = get_store()
        user = _user_dict(user_loader(legacy_user_id))
        if not user:
            return None
        issued = store.issue_session(
            legacy_user_id,
            auth_method="legacy_signed_session",
            legacy_migrated=True,
            metadata={"role": user["role"]},
        )
        g.cleanhouse_session_replacement = issued
        g.cleanhouse_clear_legacy_identity = True
        identity = RequestIdentity(legacy_user_id, "session", issued.id, user, consent_checker(legacy_user_id))
        g.cleanhouse_identity = identity
        return identity
    return None


def csrf_token() -> str:
    token = str(session.get("csrf_token") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def exact_local_origin() -> bool:
    origin = str(request.headers.get("Origin") or "").rstrip("/")
    if not origin:
        referer = str(request.headers.get("Referer") or "")
        origin = referer.split("/", 3)[:3]
        origin = "/".join(origin).rstrip("/") if len(origin) == 3 else ""
    allowed = set(auth_runtime_config.runtime_config().get("allowed_origins", []))
    return bool(origin and origin in allowed)


def cookie_mutation_allowed() -> bool:
    supplied = str(request.headers.get(CSRF_HEADER) or "")
    expected = str(session.get("csrf_token") or "")
    return exact_local_origin() and bool(supplied and expected and secrets.compare_digest(supplied, expected))


def apply_session_cookie(response: Any, raw: str) -> Any:
    if not hasattr(response, "set_cookie"):
        return response
    response.set_cookie(
        DEVICE_COOKIE,
        raw,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("CLEANHOUSE_SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"},
        samesite="Lax",
        path="/",
    )
    return response

def clear_session_cookie(response: Any) -> Any:
    if hasattr(response, "delete_cookie"):
        response.delete_cookie(DEVICE_COOKIE, path="/", samesite="Lax")
    return response


def finalize_response(response: Any) -> Any:
    replacement = getattr(g, "cleanhouse_session_replacement", None)
    if replacement is not None:
        apply_session_cookie(response, replacement.secret)
    if getattr(g, "cleanhouse_clear_legacy_identity", False):
        session.pop("user_id", None)
        session.pop("email", None)
    return response
