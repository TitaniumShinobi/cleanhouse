"""JWT token utilities for CleanHouse authentication.

Primary path uses PyJWT when available. A deterministic local HS256 fallback is
provided so local runtime/tests are not blocked when the optional dependency is
missing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import jwt as pyjwt  # type: ignore[import-not-found]
except Exception:
    pyjwt = None


class _ExpiredSignatureError(Exception):
    """Fallback compatibility error for expired tokens."""


class _InvalidTokenError(Exception):
    """Fallback compatibility error for malformed/invalid tokens."""

# JWT configuration
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

# Generate and store secret key if not set
if not JWT_SECRET_KEY:
    secret_key_file = Path.home() / '.cleanhouse' / '.jwt_secret_key'
    if secret_key_file.exists():
        JWT_SECRET_KEY = secret_key_file.read_text().strip()
    else:
        JWT_SECRET_KEY = secrets.token_hex(32)
        secret_key_file.parent.mkdir(parents=True, exist_ok=True)
        secret_key_file.write_text(JWT_SECRET_KEY)
        logging.info("Generated new JWT secret key")

def generate_jwt_token(user_data: Dict[str, Any]) -> str:
    """
    Generate JWT token for authenticated user.
    
    Args:
        user_data: Dictionary containing user information (user_id, email, full_name, role)
        
    Returns:
        str: JWT token
    """
    payload = {
        'credential_generation': user_data.get('credential_generation', '0'),
        'user_id': user_data.get('user_id'),
        'email': user_data.get('email'),
        'full_name': user_data.get('full_name', ''),
        'role': user_data.get('role', 'user'),
        'iat': datetime.now(timezone.utc),  # Issued at
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)  # Expiration
    }
    if pyjwt is not None:
        token = pyjwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return str(token)
    return _fallback_encode(payload, JWT_SECRET_KEY)


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _fallback_encode(payload: Dict[str, Any], secret: str) -> str:
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    payload_copy = dict(payload)
    for key in ("iat", "exp"):
        value = payload_copy.get(key)
        if isinstance(value, datetime):
            payload_copy[key] = int(value.timestamp())

    signing_input = ".".join(
        (
            _urlsafe_b64encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
            _urlsafe_b64encode(json.dumps(payload_copy, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        )
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_urlsafe_b64encode(signature)}"


def _fallback_decode(token: str, secret: str) -> Dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise _InvalidTokenError("wrong JWT segment count")
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        actual = _urlsafe_b64decode(sig_b64)
        if not hmac.compare_digest(actual, expected):
            raise _InvalidTokenError("signature mismatch")

        payload = json.loads(_urlsafe_b64decode(payload_b64).decode("utf-8"))
        if not isinstance(payload, dict):
            raise _InvalidTokenError("payload is not an object")
        exp = payload.get("exp")
        if isinstance(exp, (int, float)) and datetime.now(timezone.utc).timestamp() > float(exp):
            raise _ExpiredSignatureError("token expired")
        return payload
    except (_ExpiredSignatureError, _InvalidTokenError):
        raise
    except Exception as exc:
        raise _InvalidTokenError(str(exc)) from exc

def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded payload if valid, None if invalid
    """
    try:
        if pyjwt is not None:
            payload = pyjwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        else:
            payload = _fallback_decode(token, JWT_SECRET_KEY)
        from backend.api.auth import get_user_service
        user = get_user_service().get_user_by_id(user_id=payload.get('user_id'))
        if not credential_generation_matches(user, payload):
            return None
        return payload
    except Exception as exc:
        expired_type = getattr(pyjwt, "ExpiredSignatureError", _ExpiredSignatureError)
        invalid_type = getattr(pyjwt, "InvalidTokenError", _InvalidTokenError)
        if isinstance(exc, expired_type):
            logging.warning("JWT token expired")
            return None
        if isinstance(exc, invalid_type):
            logging.warning("Invalid JWT token: %s", exc)
            return None
        logging.warning("JWT token verification error: %s", exc)
        return None

def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Get user data from JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: User data if token is valid, None otherwise
    """
    payload = verify_jwt_token(token)
    if payload:
        return {
            'credential_generation': payload.get('credential_generation', '0'),
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'full_name': payload.get('full_name', ''),
            'role': payload.get('role', 'user')
        }
    return None

def refresh_jwt_token(token: str) -> Optional[str]:
    """
    Refresh JWT token if it's close to expiring.
    
    Args:
        token: Current JWT token
        
    Returns:
        str: New JWT token if refresh successful, None otherwise
    """
    payload = verify_jwt_token(token)
    if not payload:
        return None
    
    # Check if token expires within 24 hours
    exp_time = datetime.fromtimestamp(float(payload.get('exp', 0)), tz=timezone.utc)
    time_until_expiry = exp_time - datetime.now(timezone.utc)
    
    if time_until_expiry.total_seconds() < 24 * 3600:  # Less than 24 hours
        # Generate new token with same user data
        user_data = {
            'credential_generation': payload.get('credential_generation', '0'),
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'full_name': payload.get('full_name', ''),
            'role': payload.get('role', 'user')
        }
        return generate_jwt_token(user_data)
    
    return token  # Token still valid, return original


def credential_generation_matches(user, credential):
    """Legacy credentials belong only to accounts which have never been reset."""
    if user is None:
        return False
    current = getattr(user, 'credential_generation', '0')
    supplied = credential.get('credential_generation', '0')
    return isinstance(current, str) and bool(current) and isinstance(supplied, str) and hmac.compare_digest(current, supplied)
