"""
Authentication API endpoints for CleanHouse.
"""

from flask import Blueprint, request, jsonify, redirect, session, url_for
from pathlib import Path
import sys
import os
import logging
import json
import sqlite3
import secrets
import base64
import hashlib
import urllib.parse
import requests
import threading
import queue
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any
import re
from datetime import datetime, timedelta, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import UserService, DatabaseManager
from backend import auth_runtime_config
from backend.auth_recovery import issue_recovery, consume_recovery, deliver_recovery
from backend.auth_email import deliver_auth_email
from backend import auth_context
from backend.auth_context import (
    DEVICE_COOKIE,
    REAUTH_HEADER,
    apply_session_cookie,
    clear_session_cookie,
    cookie_mutation_allowed,
    csrf_token,
    get_store,
    resolve_identity,
)

bp = Blueprint('auth', __name__)

# Initialize database and user service
_db_manager = None
_user_service = None

_ALLOWED_OAUTH_PROVIDERS = {"google", "microsoft", "github", "apple"}
_OAUTH_STATE_TTL_SECONDS = 600
_MAX_PENDING_OAUTH_STATES = 4
_MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
_MAGIC_RATE_WINDOW_SECONDS = 15 * 60
_magic_rate_lock = threading.Lock()
_magic_rate_events: Dict[str, list[int]] = {}
_login_rate_lock = threading.Lock()
_login_rate_events: Dict[str, list[int]] = {}


def _oauth_avatar_url(provider: str, value: Any) -> str:
    """Keep only bounded HTTPS image URLs from the expected provider host."""
    if not isinstance(value, str):
        return ''
    url = value.strip()
    if not url or len(url) > 2048:
        return ''
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return ''
    host = (parsed.hostname or '').lower()
    allowed = (provider == 'google' and host.endswith('.googleusercontent.com')) or (
        provider == 'github' and host == 'avatars.githubusercontent.com'
    )
    if parsed.scheme != 'https' or not allowed or parsed.username or parsed.password or parsed.fragment:
        return ''
    return url


@bp.after_request
def _auth_no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return response


def _bad_request(reason: str):
    return jsonify({
        'success': False,
        'message': reason,
    }), 400


def _public_error(code: str, message: str, status: int):
    return jsonify({'success': False, 'code': code, 'message': message}), status


def _bounded_response_json(response: Any) -> Optional[Dict[str, Any] | list[Any]]:
    if callable(getattr(response, 'iter_content', None)):
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > _MAX_PROVIDER_RESPONSE_BYTES:
                    return None
                chunks.append(chunk)
            content = b''.join(chunks)
        finally:
            close = getattr(response, 'close', None)
            if callable(close):
                close()
    else:
        content = getattr(response, 'content', b'') or b''
        if len(content) > _MAX_PROVIDER_RESPONSE_BYTES:
            return None
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return None
        return payload if isinstance(payload, (dict, list)) else None
    try:
        payload = json.loads(content.decode('utf-8'))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, (dict, list)) else None


def _get_json_payload():
    payload = request.get_json(silent=True)
    if payload is None:
        return None, _bad_request("Request body must be valid JSON")
    if not isinstance(payload, dict):
        return None, _bad_request("Request body must be a JSON object")
    return payload, None


def _require_string(value: Any, field: str, *, max_len: int = 4096, required: bool = True):
    if value is None:
        if required:
            return None, _bad_request(f"{field} is required")
        return None, None
    if not isinstance(value, str):
        return None, _bad_request(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        return None, _bad_request(f"{field} is required")
    if len(value) > max_len:
        return None, _bad_request(f"{field} exceeds maximum length")
    return value, None


def _require_dict(value: Any, field: str, *, required: bool = True):
    if value is None:
        if required:
            return None, _bad_request(f"{field} is required")
        return None, None
    if not isinstance(value, dict):
        return None, _bad_request(f"{field} must be an object")
    return value, None


def _extract_bearer_token(auth_header: str):
    match = re.fullmatch(r"Bearer\s+(\S+)", (auth_header or "").strip())
    if not match:
        return None, _bad_request("Authorization header must be in the format: Bearer <token>")
    token = match.group(1).strip()
    if not token:
        return None, _bad_request("Authorization token must not be empty")
    return token, None

def _cleanhouse_public_origin() -> str:
    """Return the local browser origin used for CleanHouse OAuth callbacks."""
    configured = str(auth_runtime_config.runtime_config().get('public_origin') or '').strip()
    return configured or os.getenv('CLEANHOUSE_PUBLIC_ORIGIN') or f"http://127.0.0.1:{os.getenv('CLEANHOUSE_PORT', '3333')}"


def _oauth_redirect_uri(provider: str) -> str:
    """Return the callback URI registered with the OAuth provider."""
    configured = auth_runtime_config.provider_config(provider).get('callback_url')
    if configured:
        return str(configured)
    provider_key = str(provider or '').strip().upper()
    for name in (f'{provider_key}_CALLBACK_URL', f'{provider_key}_CALLBACK'):
        value = os.getenv(name, '').strip()
        if value:
            return value
    return f"{_cleanhouse_public_origin().rstrip('/')}/api/auth/oauth/callback"


def _canonical_oauth_start(provider: str) -> Optional[str]:
    """Keep the OAuth state cookie on the same host used by the callback.

    CleanHouse can be reached through both ``localhost`` and ``127.0.0.1``.
    Browser cookies are host-bound, so starting on one name and returning to
    the other loses the session-bound OAuth state and makes every valid
    callback fail closed as ``invalid_state``.
    """
    callback = urllib.parse.urlsplit(_oauth_redirect_uri(provider))
    canonical_origin = f"{callback.scheme}://{callback.netloc}" if callback.scheme and callback.netloc else ''
    request_origin = str(getattr(request, 'host_url', '') or '').rstrip('/')
    if canonical_origin and request_origin and request_origin != canonical_origin:
        query = urllib.parse.urlencode({key: value for key, value in request.args.items() if key == 'intent'})
        suffix = f"?{query}" if query else ''
        return f"{canonical_origin}/api/auth/oauth/{urllib.parse.quote(provider)}{suffix}"
    return None


def _bounded_oauth_states(value: Any, *, now: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """Return only fresh, well-formed OAuth transactions within the cookie budget."""
    current_time = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    candidates = []
    if isinstance(value, dict):
        for position, (state, payload) in enumerate(value.items()):
            if not isinstance(state, str) or not state or not isinstance(payload, dict):
                continue
            try:
                created_at = int(payload.get('created_at') or 0)
            except (TypeError, ValueError):
                continue
            if created_at <= 0 or current_time - created_at > _OAUTH_STATE_TTL_SECONDS:
                continue
            provider = payload.get('provider')
            code_verifier = payload.get('code_verifier')
            if provider not in _ALLOWED_OAUTH_PROVIDERS or not isinstance(code_verifier, str) or not code_verifier:
                continue
            candidates.append((created_at, position, state, {
                'provider': provider,
                'code_verifier': code_verifier,
                'created_at': created_at,
                **{key: payload[key] for key in ('intent', 'user_id', 'session_id', 'consent') if key in payload},
            }))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return {state: payload for _, _, state, payload in candidates[:_MAX_PENDING_OAUTH_STATES]}


def _login_report_reference(value: Any) -> Optional[Dict[str, str]]:
    """Keep only the durable report identifier in the browser session cookie."""
    if not isinstance(value, dict):
        return None
    for key in ('id', 'report_id', 'job_id'):
        report_id = value.get(key)
        if isinstance(report_id, str) and report_id.strip():
            return {'id': report_id.strip()}
    return None


def _env_flag(name: str, default: str = '1') -> bool:
    return os.getenv(name, default).strip().lower() not in {'0', 'false', 'no', 'off'}


def _turnstile_config() -> Dict[str, Any]:
    site_key = os.getenv('TURNSTILE_SITE_KEY', '').strip()
    secret_key = os.getenv('TURNSTILE_SECRET_KEY', '').strip()
    required = _env_flag('CLEANHOUSE_TURNSTILE_REQUIRED', '1')
    enabled = bool(site_key and secret_key)
    return {
        'required': required,
        'enabled': enabled,
        'siteKey': site_key if site_key else None,
    }


def _cleanhouse_auth_docs() -> list[Dict[str, Any]]:
    origin = _cleanhouse_public_origin().rstrip('/')
    documents = [
        {
            'product': 'cleanhouse',
            'docType': 'terms',
            'key': 'cleanhouse:terms',
            'path': Path(__file__).parent.parent.parent / 'docs' / 'legal' / 'CLEANHOUSE_TERMS_OF_SERVICE.md',
            'label': 'CleanHouse Terms of Service',
            'url': f'{origin}/legal/terms',
            'required': True,
        },
        {
            'product': 'cleanhouse',
            'docType': 'privacy',
            'key': 'cleanhouse:privacy',
            'path': Path(__file__).parent.parent.parent / 'docs' / 'legal' / 'CLEANHOUSE_PRIVACY_NOTICE.md',
            'label': 'CleanHouse Privacy Notice',
            'url': f'{origin}/legal/privacy',
            'required': True,
        },
        {
            'product': 'cleanhouse',
            'docType': 'eeccd',
            'key': 'cleanhouse:eeccd',
            'path': Path(__file__).parent.parent.parent / 'docs' / 'legal' / 'CLEANHOUSE_EUROPEAN_ELECTRONIC_COMMUNICATIONS_CODE_DISCLOSURE.md',
            'label': 'European Electronic Communications Code Disclosure',
            'url': f'{origin}/legal/eeccd',
            'required': True,
        },
    ]
    for document in documents:
        try:
            digest = hashlib.sha256(document.pop('path').read_bytes()).hexdigest()
        except OSError:
            digest = ''
            document.pop('path', None)
        document['digest'] = digest
        document['version'] = digest
    return documents


def _missing_required_consent(consent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for doc in _cleanhouse_auth_docs():
        if consent.get(doc['key']) is not True:
            return doc
    return None


def _required_consent_digests() -> Dict[str, str]:
    return {doc['key']: doc['digest'] for doc in _cleanhouse_auth_docs() if doc.get('required') and doc.get('digest')}


def user_has_current_consent(user_id: str) -> bool:
    return bool(user_id) and get_store().consent_status(str(user_id), _required_consent_digests())['current']


def _record_current_consent(user_id: str, consent: Dict[str, Any], method: str, transaction_id: str) -> None:
    missing = _missing_required_consent(consent)
    if missing:
        raise ValueError(f"Please confirm you agree to {missing['label']}")
    for document, digest in _required_consent_digests().items():
        get_store().record_consent(
            str(user_id), document, digest, method,
            transaction_id=transaction_id,
        )


def _current_identity(*, allow_api_token: bool = False):
    identity = resolve_identity(
        lambda user_id: get_user_service().get_user_by_id(user_id=str(user_id)),
        user_has_current_consent,
    )
    if identity is None or (identity.kind == 'api_token' and not allow_api_token):
        return None
    return identity


def _require_cookie_mutation():
    if not cookie_mutation_allowed():
        return _public_error('CSRF_FAILED', 'Exact local origin and CSRF verification are required.', 403)
    return None


def _issue_session_response(user_data: Dict[str, Any], payload: Dict[str, Any], *, auth_method: str):
    issued = get_store().issue_session(
        str(user_data['user_id']),
        auth_method=auth_method,
        metadata={'role': user_data.get('role', 'user')},
    )
    response = jsonify(payload)
    apply_session_cookie(response, issued.secret)
    session.pop('user_id', None)
    session.pop('email', None)
    return response


def _consent_payload_for(user_id: str) -> Dict[str, Any]:
    status = get_store().consent_status(str(user_id), _required_consent_digests())
    return {
        'current': bool(status['current']),
        'missing': status['missing'],
        'accepted': status['accepted'],
        'documents': _cleanhouse_auth_docs(),
    }


def _require_sensitive(identity, scope: str):
    raw = str(request.headers.get(REAUTH_HEADER) or '')
    if not raw or not get_store().consume_reauth_grant(
        raw,
        user_id=identity.user_id,
        session_id=identity.credential_id,
        scope=scope,
    ):
        return _public_error('REAUTHENTICATION_REQUIRED', 'Recent human reauthentication is required.', 403)
    return None


def _verify_turnstile_token(token: str, remote_ip: str = '') -> bool:
    secret_key = os.getenv('TURNSTILE_SECRET_KEY', '').strip()
    if not secret_key or not token:
        return False

    try:
        body = {
            'secret': secret_key,
            'response': token,
        }
        if remote_ip:
            body['remoteip'] = remote_ip
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=body,
            timeout=5,
        )
        if not getattr(response, 'ok', False):
            return False
        payload = response.json()
        return payload.get('success') is True
    except Exception as exc:
        logging.warning("Turnstile verification failed: %s", exc.__class__.__name__)
        return False


def _client_ip() -> str:
    forwarded = getattr(request, 'headers', {}).get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return getattr(request, 'remote_addr', '') or ''


def _magic_request_rate_allowed(email: str, intent: str, client_ip: str) -> bool:
    """Bound email abuse without retaining raw email addresses or IPs."""
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - _MAGIC_RATE_WINDOW_SECONDS
    email_key = 'email:' + hashlib.sha256(f'{intent}:{email}'.encode('utf-8')).hexdigest()
    ip_key = 'ip:' + hashlib.sha256(str(client_ip or 'unknown').encode('utf-8')).hexdigest()
    with _magic_rate_lock:
        for key in list(_magic_rate_events):
            retained = [stamp for stamp in _magic_rate_events[key] if stamp > cutoff]
            if retained:
                _magic_rate_events[key] = retained
            else:
                _magic_rate_events.pop(key, None)
        if len(_magic_rate_events) > 512:
            for key in sorted(_magic_rate_events, key=lambda item: _magic_rate_events[item][-1])[:len(_magic_rate_events) - 512]:
                _magic_rate_events.pop(key, None)
        email_events = _magic_rate_events.setdefault(email_key, [])
        ip_events = _magic_rate_events.setdefault(ip_key, [])
        allowed = len(email_events) < 5 and len(ip_events) < 20
        email_events.append(now_epoch)
        ip_events.append(now_epoch)
        return allowed


def _password_attempt_rate_allowed(email: str, client_ip: str) -> bool:
    """Bound password attempts while retaining only digests of identifiers."""
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - _MAGIC_RATE_WINDOW_SECONDS
    keys = (
        'email:' + hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest(),
        'ip:' + hashlib.sha256(str(client_ip or 'unknown').encode('utf-8')).hexdigest(),
    )
    with _login_rate_lock:
        for key in list(_login_rate_events):
            retained = [stamp for stamp in _login_rate_events[key] if stamp > cutoff]
            if retained:
                _login_rate_events[key] = retained
            else:
                _login_rate_events.pop(key, None)
        if len(_login_rate_events) > 512:
            oldest = sorted(_login_rate_events, key=lambda item: _login_rate_events[item][-1])
            for key in oldest[:len(_login_rate_events) - 512]:
                _login_rate_events.pop(key, None)
        email_events = _login_rate_events.setdefault(keys[0], [])
        ip_events = _login_rate_events.setdefault(keys[1], [])
        allowed = len(email_events) < 10 and len(ip_events) < 20
        email_events.append(now_epoch)
        ip_events.append(now_epoch)
        return allowed


def _clear_password_attempts(email: str, client_ip: str) -> None:
    """Forget bounded failure counters after a successful human sign-in."""
    keys = (
        'email:' + hashlib.sha256(email.strip().lower().encode('utf-8')).hexdigest(),
        'ip:' + hashlib.sha256(str(client_ip or 'unknown').encode('utf-8')).hexdigest(),
    )
    with _login_rate_lock:
        for key in keys:
            _login_rate_events.pop(key, None)


def _model_user_id(user: Any) -> Any:
    return getattr(user, 'user_id', None) or getattr(user, 'id', None)


def _last_login_iso(user: Any) -> Optional[str]:
    value = getattr(user, 'last_login', None)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_login_report_payload(
    user_data: Dict[str, Any],
    *,
    previous_login_at: Optional[str],
    current_login_at: Optional[str] = None,
    trigger: str,
) -> Dict[str, Any]:
    try:
        from backend.api.cleanhouse import get_cleanhouse_monitoring_adapter

        return get_cleanhouse_monitoring_adapter().submit_login_report(
            user_id=str(user_data.get('user_id') or user_data.get('id') or ''),
            email=str(user_data.get('email') or ''),
            previous_login_at=previous_login_at,
            current_login_at=current_login_at or datetime.now().isoformat(),
            trigger=trigger,
            wait_timeout_seconds=2.0,
        )
    except Exception as exc:
        logging.warning("Login report generation failed: %s", exc.__class__.__name__)
        return {
            'status': 'unavailable',
            'message': 'Login report unavailable.',
        }


def _vvault_root() -> Path:
    configured = os.getenv('CLEANHOUSE_VVAULT_ROOT') or os.getenv('VVAULT_ROOT')
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent.parent.parent.parent / "vvault"


def _clear_vvault_user_records(user_id: str, email: str) -> Dict[str, Any]:
    """Remove local VVAULT user rows for an account deletion request."""
    root = _vvault_root()
    cleanup = {
        'root': str(root),
        'available': root.exists(),
        'users_json_removed': 0,
        'sqlite_rows_removed': 0,
        'sqlite_tables': [],
        'status': 'not_configured' if not root.exists() else 'ok',
    }
    if not root.exists():
        return cleanup

    target_ids = {str(user_id or '').strip()}
    target_ids.discard('')
    target_email = str(email or '').strip().lower()

    users_path = root / "users.json"
    if users_path.exists():
        try:
            data = json.loads(users_path.read_text(encoding='utf-8'))
            users = data.get('users') if isinstance(data, dict) else None
            if isinstance(users, dict):
                removed = []
                for key, value in list(users.items()):
                    record = value if isinstance(value, dict) else {}
                    record_id = str(record.get('id') or key or '').strip()
                    record_email = str(record.get('email') or '').strip().lower()
                    if record_id == user_id or record_email == target_email or key == user_id:
                        if record_id:
                            target_ids.add(record_id)
                        removed.append(key)
                for key in removed:
                    users.pop(key, None)
                if removed:
                    temp_path = users_path.with_suffix('.json.tmp')
                    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                    temp_path.replace(users_path)
                    cleanup['users_json_removed'] = len(removed)
        except Exception as exc:
            cleanup['status'] = 'partial'
            cleanup['users_json_error'] = str(exc)

    for db_path in (root / "security.db", root / "vvault" / "data" / "audit.db"):
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(db_path)
            try:
                tables = [
                    row[0]
                    for row in conn.execute("select name from sqlite_master where type='table' order by name")
                ]
                for table in tables:
                    quoted_table = '"' + table.replace('"', '""') + '"'
                    columns = [row[1] for row in conn.execute(f"pragma table_info({quoted_table})")]
                    if 'user_id' not in columns:
                        continue
                    before = conn.total_changes
                    conn.executemany(
                        f"delete from {quoted_table} where user_id = ?",
                        [(target_id,) for target_id in sorted(target_ids)],
                    )
                    removed = conn.total_changes - before
                    if removed:
                        cleanup['sqlite_rows_removed'] += removed
                        cleanup['sqlite_tables'].append({
                            'database': str(db_path),
                            'table': table,
                            'rows_removed': removed,
                        })
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            cleanup['status'] = 'partial'
            cleanup.setdefault('sqlite_errors', []).append({
                'database': str(db_path),
                'error': str(exc),
            })

    if cleanup['status'] == 'ok' and not cleanup['users_json_removed'] and not cleanup['sqlite_rows_removed']:
        cleanup['status'] = 'no_local_vvault_records'
    return cleanup


def _write_account_deletion_marker(user_data: Dict[str, Any], vvault_cleanup: Dict[str, Any]) -> Optional[str]:
    try:
        root = Path.home() / ".cleanhouse" / "account_deletions"
        root.mkdir(parents=True, exist_ok=True)
        user_id = str(user_data.get('user_id') or user_data.get('id') or 'unknown')
        marker_id = hashlib.sha256(f"{user_id}:{datetime.now().isoformat()}".encode('utf-8')).hexdigest()[:16]
        path = root / f"{marker_id}.json"
        path.write_text(json.dumps({
            'id': marker_id,
            'deleted_at': datetime.now().isoformat(),
            'user_id': user_id,
            'email': user_data.get('email'),
            'company_archive_retention_years': 7,
            'local_vvault_cleanup': vvault_cleanup,
        }, indent=2), encoding='utf-8')
        return str(path)
    except Exception as exc:
        logging.warning("Failed to write account deletion marker: %s", exc.__class__.__name__)
        return None


def get_user_service():
    """Get or create user service instance"""
    global _user_service, _db_manager

    if _user_service is None:
        base_dir = Path(__file__).parent.parent.parent
        _db_manager = DatabaseManager()
        _user_service = UserService(db_manager=_db_manager)

    return _user_service

def generate_pkce():
    """Generate PKCE code verifier and challenge for OAuth."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge

@bp.route('/auth/config', methods=['GET'])
def auth_config():
    public_auth = auth_runtime_config.public_config_payload()
    return jsonify({
        'success': True,
        'ok': True,
        'data': {
            'credentials': {'enabled': True},
            'magicEmail': {
                'enabled': bool(os.getenv('FROM_EMAIL', '').strip() and (
                    os.getenv('RESEND_API_KEY', '').strip() or os.getenv('EMAIL_HOST', '').strip()
                )),
                'intents': ['signin', 'signup'],
            },
            'docs': _cleanhouse_auth_docs(),
            'turnstile': _turnstile_config(),
            'providers': public_auth['providers'],
        },
    })


@bp.route('/auth/csrf', methods=['GET'])
def get_csrf():
    response = jsonify({'success': True, 'csrfToken': csrf_token()})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/createAccount', methods=['POST'])
@bp.route('/auth/register', methods=['POST'])
def create_account():
    """Create a new user account"""
    try:
        data, error = _get_json_payload()
        if error:
            return error

        full_name, error = _require_string(data.get('fullName') or data.get('name'), 'fullName', required=False)
        if error:
            return error
        email, error = _require_string(data.get('email'), 'email')
        if error:
            return error
        password, error = _require_string(data.get('password'), 'password')
        if error:
            return error

        role, error = _require_string(data.get('role'), 'role', required=False)
        if error:
            return error
        turnstile_token, turnstile_error = _require_string(data.get('turnstileToken'), 'turnstileToken', required=False)
        if turnstile_error:
            return turnstile_error
        turnstile_token = turnstile_token or ''
        confirm_password, error = _require_string(data.get('confirmPassword'), 'confirmPassword', required=False)
        if error:
            return error
        if confirm_password and confirm_password != password:
            return _bad_request('Passwords do not match')

        consent, error = _require_dict(data.get('consent'), 'consent', required=False)
        if error:
            return error
        if consent is None and data.get('terms') is True:
            consent = {doc['key']: True for doc in _cleanhouse_auth_docs()}
        consent = consent or {}
        missing_consent = _missing_required_consent(consent)
        if missing_consent:
            return _bad_request(f"Please confirm you agree to {missing_consent['label']}")

        turnstile = _turnstile_config()
        if turnstile['required']:
            if not turnstile['enabled']:
                return jsonify({
                    'success': False,
                    'message': 'Turnstile is required but not configured',
                }), 503
            if not turnstile_token:
                return _bad_request('Turnstile verification is required')
            if not _verify_turnstile_token(turnstile_token, _client_ip()):
                return _bad_request('Turnstile verification failed')

        role = role or 'user'
        full_name = full_name or ''

        csrf_error = _require_cookie_mutation()
        if csrf_error:
            return csrf_error
        user_service = get_user_service()

        # Create user
        user = user_service.create_user(
            full_name=full_name,
            email=email,
            password=password,
            role=role
        )

        # Prepare the canonical identity payload for the durable device session.
        user_data = {
            'user_id': _model_user_id(user),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role
        }
        transaction_id = str(uuid.uuid4())
        try:
            _record_current_consent(str(user_data['user_id']), consent, 'password_signup', transaction_id)
        except Exception:
            user_service.delete_user(user_id=str(user_data['user_id']))
            raise
        login_report = _build_login_report_payload(
            user_data,
            previous_login_at=None,
            trigger='auth/createAccount',
        )

        return _issue_session_response(user_data, {
            'success': True,
            'message': 'Account created successfully!',
            'user': {
                'id': user_data['user_id'],
                'user_id': user_data['user_id'],
                'email': user_data['email'],
                'full_name': user_data['full_name'],
                'name': user_data['full_name'],
                'role': user_data['role']
            },
            'login_report': login_report
        }, auth_method='password')
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        logging.error("Account creation failed: %s", e.__class__.__name__)
        return jsonify({
            'success': False,
            'code': 'ACCOUNT_CREATION_FAILED', 'message': 'Account creation failed.'
        }), 500

@bp.route('/auth/login', methods=['POST'])
def login():
    """Authenticate user"""
    try:
        data, error = _get_json_payload()
        if error:
            return error
        email, error = _require_string(data.get('email'), 'email')
        if error:
            return error
        password, error = _require_string(data.get('password'), 'password')
        if error:
            return error
        if not _password_attempt_rate_allowed(email, _client_ip()):
            return _public_error('RATE_LIMITED', 'Sign in is temporarily rate limited. Try again later.', 429)

        csrf_error = _require_cookie_mutation()
        if csrf_error:
            return csrf_error
        user_service = get_user_service()
        user = user_service.authenticate_user(email, password)

        if user:
            _clear_password_attempts(email, _client_ip())
            previous_login_at = _last_login_iso(user)
            # Prepare the canonical identity payload for the durable device session.
            user_data = {
                'user_id': _model_user_id(user),
                'email': user.email,
                'full_name': user.full_name,
                'role': user.role
            }
            login_report = _build_login_report_payload(
                user_data,
                previous_login_at=previous_login_at,
                trigger='auth/login',
            )

            return _issue_session_response(user_data, {
                'success': True,
                'message': 'Login successful!',
                'user': {
                    'id': user_data['user_id'],
                    'user_id': user_data['user_id'],
                    'email': user_data['email'],
                    'full_name': user_data['full_name'],
                    'name': user_data['full_name'],
                    'role': user_data['role']
                },
                'login_report': login_report,
                'consent': _consent_payload_for(str(user_data['user_id'])),
            }, auth_method='password')
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid email or password'
            }), 401
    except Exception as e:
        logging.error("Login failed: %s", e.__class__.__name__)
        return jsonify({
            'success': False,
            'code': 'LOGIN_FAILED', 'message': 'Sign in failed.'
        }), 500

@bp.route('/auth/oauth/<provider>', methods=['GET', 'POST'])
def oauth(provider):
    """Handle OAuth authentication - redirects to OAuth provider"""
    try:
        provider = provider.lower()
        if provider not in _ALLOWED_OAUTH_PROVIDERS:
            return jsonify({
                'success': False,
                'message': f'Unknown OAuth provider: {provider}'
            }), 400

        intent = str(request.args.get('intent') or 'login').strip().lower()
        if intent not in {'login', 'signup', 'link', 'photo'}:
            return redirect('/login?error=invalid_oauth_intent')
        canonical_start = _canonical_oauth_start(provider)
        if canonical_start:
            if intent == 'photo':
                return _public_error('CANONICAL_ORIGIN_REQUIRED', 'Use the configured CleanHouse origin.', 400)
            return redirect(canonical_start)
        link_identity = None
        signup_consent = None
        if intent == 'link':
            link_identity = _current_identity()
            if link_identity is None or link_identity.kind != 'session':
                return redirect('/login?error=reauthentication_required')
            if request.method == 'GET':
                nonce = str(request.args.get('prepared') or '')
                prepared = dict(session.get('provider_link_prepared') or {})
                record = prepared.pop(nonce, None)
                session['provider_link_prepared'] = prepared
                now_epoch = int(datetime.now(timezone.utc).timestamp())
                if not record or record.get('provider') != provider or record.get('user_id') != link_identity.user_id or now_epoch - int(record.get('created_at') or 0) > 120:
                    return redirect('/settings?settings=providers&error=reauthentication_required')
            else:
                csrf_error = _require_cookie_mutation()
                if csrf_error:
                    return csrf_error
                grant = str(request.headers.get(REAUTH_HEADER) or '')
                if not grant or not get_store().consume_reauth_grant(
                    grant,
                    user_id=link_identity.user_id,
                    session_id=link_identity.credential_id,
                    scope='provider_link',
                ):
                    return _public_error('REAUTHENTICATION_REQUIRED', 'Recent human reauthentication is required.', 403)
        elif intent == 'photo':
            if request.method != 'POST':
                return _public_error('PHOTO_REFRESH_POST_REQUIRED', 'Start photo refresh from the connected provider settings.', 405)
            csrf_error = _require_cookie_mutation()
            if csrf_error:
                return csrf_error
            link_identity = _current_identity()
            if link_identity is None or link_identity.kind != 'session':
                return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
            if provider not in {'google', 'github'} or not any(
                item['provider'] == provider for item in get_store().list_external_identities(link_identity.user_id)
            ):
                return _public_error('PROVIDER_NOT_CONNECTED', 'This provider is not connected to the current account.', 409)
        elif intent == 'signup':
            if request.method != 'POST':
                return redirect('/signup?error=signup_admission_required')
            payload, payload_error = _get_json_payload()
            if payload_error:
                return payload_error
            signup_consent = payload.get('consent') if isinstance(payload.get('consent'), dict) else {}
            missing = _missing_required_consent(signup_consent)
            if missing:
                return _bad_request(f"Please confirm you agree to {missing['label']}")
            turnstile = _turnstile_config()
            token = str(payload.get('turnstileToken') or '')
            if turnstile['required'] and (not turnstile['enabled'] or not _verify_turnstile_token(token, _client_ip())):
                return _public_error('ADMISSION_REQUIRED', 'Signup admission verification failed.', 503)

        provider_runtime = auth_runtime_config.provider_config(provider)
        if not provider_runtime.get('enabled') or not provider_runtime.get('available'):
            return redirect(
                '/login?error=provider_unavailable&provider=' + urllib.parse.quote(provider)
            )

        # Generate PKCE codes
        code_verifier, code_challenge = generate_pkce()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        oauth_states = _bounded_oauth_states(session.get('oauth_states'))
        oauth_states[state] = {
            'provider': provider,
            'intent': intent,
            'user_id': link_identity.user_id if link_identity else None,
            'session_id': link_identity.credential_id if intent == 'photo' else None,
            'consent': signup_consent,
            'code_verifier': code_verifier,
            'created_at': int(datetime.now(timezone.utc).timestamp()),
        }
        oauth_states = _bounded_oauth_states(oauth_states)
        session['oauth_states'] = oauth_states
        session.modified = True

        # Get client ID from environment
        client_id = str(provider_runtime.get('client_id') or '')

        # Build redirect URI (points back to our callback endpoint)
        redirect_uri = _oauth_redirect_uri(provider)

        # Build OAuth URL based on provider
        if provider.lower() == 'google':
            scope = 'email profile'
            auth_url = 'https://accounts.google.com/o/oauth2/v2/auth'
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': scope,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
            }
            if intent != 'photo':
                params['access_type'] = 'offline'
        elif provider.lower() == 'microsoft':
            scope = 'openid email profile'
            auth_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'
            params = {
                'client_id': client_id,
                'response_type': 'code',
                'redirect_uri': redirect_uri,
                'response_mode': 'query',
                'scope': scope,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256'
            }
        elif provider.lower() == 'github':
            scope = 'read:user user:email'
            auth_url = 'https://github.com/login/oauth/authorize'
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'scope': scope,
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
            }
        elif provider.lower() == 'apple':
            scope = 'name email'
            auth_url = 'https://appleid.apple.com/auth/authorize'
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': scope,
                'state': state,
                'response_mode': 'form_post'
            }
        else:
            return jsonify({
                'success': False,
                'message': f'Unknown OAuth provider: {provider}'
            }), 400

        # Build full URL
        oauth_url = f"{auth_url}?{urllib.parse.urlencode(params)}"

        logging.info(f"[OAUTH] Redirecting to {provider} OAuth")
        logging.info(f"[OAUTH] Redirect URI: {redirect_uri}")

        if request.method == 'POST' and intent in {'link', 'signup', 'photo'}:
            response = jsonify({'success': True, 'authorization_url': oauth_url})
            response.headers['Cache-Control'] = 'no-store'
            return response
        return redirect(oauth_url)

    except Exception as exc:
        logging.error("OAuth start failed: %s", exc.__class__.__name__)
        return jsonify({
            'success': False,
            'code': 'OAUTH_START_FAILED', 'message': 'OAuth sign in could not be started.'
        }), 500

@bp.route('/auth/google/callback', methods=['GET', 'POST'])
@bp.route('/auth/github/callback', methods=['GET', 'POST'])
@bp.route('/auth/oauth/callback', methods=['GET', 'POST'])
def oauth_callback():
    """Handle OAuth callback from provider"""
    try:
        # Get code and state from callback
        if request.method == 'POST':
            # Apple uses form_post
            code = request.form.get('code')
            state = request.form.get('state')
            error = request.form.get('error')
        else:
            code = request.args.get('code')
            state = request.args.get('state')
            error = request.args.get('error')

        if not isinstance(state, str) or not state.strip():
            return redirect('/login?error=invalid_callback')
        state = state.strip()

        # Verify state
        raw_oauth_states = session.get('oauth_states')
        raw_oauth_states = dict(raw_oauth_states) if isinstance(raw_oauth_states, dict) else {}
        oauth_data = raw_oauth_states.pop(state, None)
        oauth_states = _bounded_oauth_states(raw_oauth_states)
        session['oauth_states'] = oauth_states
        session.modified = True
        if not oauth_data:
            logging.error("OAuth state mismatch")
            return redirect('/login?error=invalid_state')
        created_at = int(oauth_data.get('created_at') or 0)
        if int(datetime.now(timezone.utc).timestamp()) - created_at > _OAUTH_STATE_TTL_SECONDS:
            return redirect('/login?error=expired_state')
        provider = oauth_data['provider']
        intent = str(oauth_data.get('intent') or 'login')
        callback_provider = None
        callback_path = str(getattr(request, 'path', '') or '')
        if callback_path.endswith('/google/callback'):
            callback_provider = 'google'
        elif callback_path.endswith('/github/callback'):
            callback_provider = 'github'
        if callback_provider and provider != callback_provider:
            logging.error("OAuth callback provider mismatch")
            return redirect('/login?error=invalid_state')
        code_verifier = oauth_data['code_verifier']
        if not isinstance(code_verifier, str) or not code_verifier.strip():
            logging.error("OAuth callback missing code verifier")
            return redirect('/login?error=invalid_state')

        if error:
            if intent == 'photo':
                return redirect('/settings?settings=providers&error=' + (
                    'photo_denied' if str(error) == 'access_denied' else 'photo_provider_error'
                ))
            return redirect('/login?error=access_denied' if str(error) == 'access_denied' else '/login?error=provider_error')
        if not isinstance(code, str) or not code.strip():
            return redirect('/login?error=invalid_callback')
        code = code.strip()

        # Exchange code for token
        token_data = exchange_oauth_token(provider, code, code_verifier)
        if not token_data:
            logging.error("Failed to exchange OAuth token")
            return redirect('/login?error=token_exchange_failed')

        # Get user info
        user_info = get_oauth_user_info(provider, token_data.get('access_token'))
        if not user_info or not user_info.get('email'):
            logging.error("Failed to get user info from OAuth provider")
            return redirect('/login?error=user_info_failed')

        # Resolve by provider subject. GitHub email is never an account-linking
        # authority; explicit linking or signup is required.
        user_service = get_user_service()
        provider_subject = str(user_info.get('id') or '').strip()
        if not provider_subject:
            return redirect('/login?error=provider_identity_invalid')
        binding = get_store().external_identity(provider, provider_subject)
        existing_user = user_service.get_user_by_id(user_id=str(binding['user_id'])) if binding else None
        if intent == 'photo':
            identity = _current_identity()
            if (
                not identity or identity.kind != 'session'
                or identity.user_id != str(oauth_data.get('user_id') or '')
                or identity.credential_id != str(oauth_data.get('session_id') or '')
                or not binding or str(binding['user_id']) != identity.user_id
            ):
                return redirect('/settings?settings=providers&error=photo_identity_mismatch')
            avatar_url = _oauth_avatar_url(provider, user_info.get('avatar_url'))
            if not avatar_url:
                return redirect('/settings?settings=providers&error=photo_unavailable')
            get_store().refresh_provider_session_avatar(
                identity.user_id, provider, avatar_url, current_session_id=identity.credential_id,
            )
            return redirect('/settings?settings=providers&photo_refreshed=' + urllib.parse.quote(provider))
        if provider == 'google' and not existing_user and intent == 'login':
            # One-time compatibility for established Google users. GitHub is
            # deliberately excluded from email matching.
            existing_user = user_service.get_user_by_email(user_info['email'])
            if existing_user:
                get_store().bind_external_identity(
                    str(_model_user_id(existing_user)), provider, provider_subject,
                    verified_email=user_info['email'],
                )
        if intent == 'link':
            link_user_id = str(oauth_data.get('user_id') or '')
            link_user = user_service.get_user_by_id(user_id=link_user_id) if link_user_id else None
            if not link_user:
                return redirect('/settings?settings=providers&error=session_expired')
            try:
                get_store().bind_external_identity(
                    link_user_id, provider, provider_subject,
                    verified_email=user_info['email'],
                )
            except ValueError:
                return redirect('/settings?settings=providers&error=provider_link_conflict')
            return redirect('/settings?settings=providers&linked=' + urllib.parse.quote(provider))
        if intent == 'login' and not existing_user:
            return redirect('/login?error=provider_not_linked&provider=' + urllib.parse.quote(provider))
        previous_login_at = _last_login_iso(existing_user) if existing_user else None
        current_login_at = datetime.now().isoformat()

        if existing_user:
            user_data = {
                'user_id': _model_user_id(existing_user),
                'email': existing_user.email,
                'full_name': existing_user.full_name,
                'role': existing_user.role
            }
            if getattr(existing_user, 'user_id', None) and hasattr(user_service, '_update_last_login'):
                user_service._update_last_login(existing_user.user_id)
                if getattr(user_service, 'user_registry', None):
                    user_service.user_registry.update_last_seen(existing_user.user_id)
            elif getattr(existing_user, 'id', None) and hasattr(user_service, '_update_last_login_legacy'):
                user_service._update_last_login_legacy(existing_user.id)
        elif intent == 'signup':
            consent = oauth_data.get('consent') if isinstance(oauth_data.get('consent'), dict) else {}
            missing = _missing_required_consent(consent)
            if missing:
                return redirect('/signup?error=consent_required')
            random_password = secrets.token_urlsafe(32)
            new_user = user_service.create_user(
                full_name=user_info.get('name', ''),
                email=user_info['email'],
                password=random_password
            )
            user_data = {
                'user_id': _model_user_id(new_user),
                'email': new_user.email,
                'full_name': new_user.full_name,
                'role': new_user.role
            }
            try:
                transaction_id = str(uuid.uuid4())
                _record_current_consent(str(user_data['user_id']), consent, f'{provider}_signup', transaction_id)
                get_store().bind_external_identity(
                    str(user_data['user_id']), provider, provider_subject,
                    verified_email=user_info['email'],
                )
            except Exception:
                user_service.delete_user(user_id=str(user_data['user_id']))
                raise
        else:
            return redirect('/login?error=provider_not_linked')
        login_report = _build_login_report_payload(
            user_data,
            previous_login_at=previous_login_at,
            current_login_at=current_login_at,
            trigger=f'auth/oauth/{provider}',
        )

        response = redirect('/overview')
        issued = get_store().issue_session(
            str(user_data['user_id']), auth_method=f'oauth:{provider}',
            metadata={
                'role': user_data.get('role', 'user'),
                'avatar_url': _oauth_avatar_url(provider, user_info.get('avatar_url')),
            },
        )
        apply_session_cookie(response, issued.secret)
        return response

    except Exception as exc:
        logging.error("OAuth callback failed: %s", exc.__class__.__name__)
        return redirect('/login?error=oauth_callback_failed')

@bp.route('/auth/oauth/user', methods=['GET'])
def oauth_user():
    """Compatibility read backed by the canonical opaque device session."""
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    return jsonify({'success': True, 'user': identity.user})

@bp.route('/auth/me', methods=['GET'])
def get_current_user():
    """Return the canonical device-session or PAT identity."""
    try:
        identity = _current_identity(allow_api_token=True)
        if not identity:
            return _public_error('AUTHENTICATION_REQUIRED', 'Invalid or expired credential.', 401)
        response = jsonify({
            'success': True,
            'auth_kind': identity.kind,
            'consent_required': not identity.consent_current,
            'user': {
                'id': identity.user_id,
                'user_id': identity.user_id,
                'email': identity.user['email'],
                'full_name': identity.user['full_name'],
                'name': identity.user['full_name'],
                'role': identity.user['role'],
                'avatar_url': str((identity.credential_metadata or {}).get('avatar_url') or ''),
            },
        })
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        logging.error("Current session validation failed: %s", e.__class__.__name__)
        return _public_error('AUTH_SESSION_FAILED', 'Unable to validate the current session.', 500)


@bp.route('/auth/session/refresh', methods=['POST'])
def refresh_session():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    raw = str(request.cookies.get(DEVICE_COOKIE, '') or '')
    result = get_store().refresh_session(raw)
    if result.status != 'rotated' or not result.replacement:
        return _public_error('SESSION_REFRESH_FAILED', 'Session refresh was rejected.', 401)
    response = jsonify({'success': True, 'session': {'id': result.replacement.id, 'expires_at': result.replacement.expires_at}})
    apply_session_cookie(response, result.replacement.secret)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/sessions', methods=['GET'])
def list_sessions():
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    records = []
    for item in get_store().list_sessions(identity.user_id):
        records.append({
            'id': item['id'],
            'current': item['id'] == identity.credential_id,
            'label': 'This Mac browser' if item['id'] == identity.credential_id else 'Local browser session',
            'created_at': item['created_at'],
            'last_used_at': item['last_used_at'],
            'expires_at': item['absolute_expires_at'],
            'idle_expires_at': item['idle_expires_at'],
            'revoked_at': item['revoked_at'],
            'auth_method': item['auth_method'],
        })
    response = jsonify({'success': True, 'sessions': records})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/sessions/<session_id>', methods=['DELETE'])
def revoke_session(session_id):
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'session_manage')
    if sensitive_error:
        return sensitive_error
    if session_id == identity.credential_id:
        return _bad_request('Use logout to revoke the current session')
    changed = get_store().revoke_session(str(session_id), identity.user_id)
    return jsonify({'success': changed}), (200 if changed else 404)


@bp.route('/auth/sessions/revoke-others', methods=['POST'])
def revoke_other_sessions():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'session_manage')
    if sensitive_error:
        return sensitive_error
    count = get_store().revoke_other_sessions(identity.user_id, identity.credential_id)
    return jsonify({'success': True, 'revoked': count})


@bp.route('/auth/reauth', methods=['POST'])
def reauthenticate():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    payload, error = _get_json_payload()
    if error:
        return error
    scope = str(payload.get('scope') or 'auth_sensitive')
    if scope not in {'auth_sensitive', 'provider_link', 'token_manage', 'session_manage', 'account'}:
        return _bad_request('Unsupported reauthentication scope')
    method = str(payload.get('method') or 'password').strip().lower()
    if method == 'magic_email_request':
        return_path = str(payload.get('return_path') or '/settings')
        if return_path not in {'/settings', '/account/delete'}:
            return _bad_request('Unsupported reauthentication return path')
        issued = get_store().issue_magic_challenge(
            identity.user['email'],
            intent='signin',
            purpose=f'auth_reauth:{scope}',
            origin=_cleanhouse_public_origin().rstrip('/'),
            user_id=identity.user_id,
            metadata={'session_id': identity.credential_id, 'scope': scope},
        )
        target = (
            f"{_cleanhouse_public_origin().rstrip('/')}{return_path}"
            f"#reauth={urllib.parse.quote(issued.secret)}&scope={urllib.parse.quote(scope)}"
        )
        try:
            deliver_auth_email(
                identity.user['email'],
                subject='Confirm a sensitive CleanHouse action',
                text=f"Confirm this action in the CleanHouse antivirus on this Mac: {target}\nThis link expires in 15 minutes and can be used once.",
            )
        except Exception:
            get_store().revoke_magic_challenge(issued.id)
            return _public_error('REAUTHENTICATION_DELIVERY_FAILED', 'Email confirmation could not be delivered.', 503)
        response = jsonify({'success': True, 'pending': True, 'message': 'A single-use confirmation link was sent.'})
        response.headers['Cache-Control'] = 'no-store'
        return response
    if method == 'magic_email_verify':
        token, error = _require_string(payload.get('token'), 'token', max_len=512)
        if error:
            return error
        result = get_store().consume_magic_challenge(
            token,
            purpose=f'auth_reauth:{scope}',
            origin=_cleanhouse_public_origin().rstrip('/'),
        )
        record = result.record if result.status == 'consumed' else None
        metadata = record.get('metadata') if isinstance(record, dict) and isinstance(record.get('metadata'), dict) else {}
        if (
            not record
            or str(record.get('user_id') or '') != identity.user_id
            or str(metadata.get('session_id') or '') != identity.credential_id
            or str(metadata.get('scope') or '') != scope
        ):
            return _public_error('REAUTHENTICATION_FAILED', 'Human reauthentication failed.', 401)
    elif method == 'password':
        password, error = _require_string(payload.get('password'), 'password', max_len=4096)
        if error:
            return error
        verified = get_user_service().authenticate_user(identity.user['email'], password)
        if not verified or str(_model_user_id(verified)) != identity.user_id:
            return _public_error('REAUTHENTICATION_FAILED', 'Human reauthentication failed.', 401)
    else:
        return _bad_request('Unsupported reauthentication method')
    issued = get_store().issue_reauth_grant(identity.user_id, identity.credential_id, scope)
    response = jsonify({'success': True, 'reauthToken': issued.secret, 'expires_at': issued.expires_at, 'scope': scope})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/consent', methods=['GET'])
def consent_status():
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    payload = _consent_payload_for(identity.user_id)
    payload.update({'success': True, 'required': list(_required_consent_digests())})
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/consent', methods=['POST'])
def accept_consent():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    payload, error = _get_json_payload()
    if error:
        return error
    if payload.get('accept_current') is not True:
        return _bad_request('Explicit current-policy acceptance is required')
    consent = {key: True for key in _required_consent_digests()}
    _record_current_consent(identity.user_id, consent, 'settings_reconsent', str(uuid.uuid4()))
    return jsonify({'success': True, **_consent_payload_for(identity.user_id)})


@bp.route('/auth/magic/request', methods=['POST'])
def request_magic_email():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    payload, error = _get_json_payload()
    if error:
        return error
    email, error = _require_string(payload.get('email'), 'email', max_len=320)
    if error:
        return error
    intent = str(payload.get('intent') or '').strip().lower()
    if intent not in {'signin', 'signup'}:
        return _bad_request('intent must be signin or signup')
    normalized = email.strip().lower()
    user = get_user_service().get_user_by_email(normalized)
    metadata: Dict[str, Any] = {}
    eligible = (bool(user) if intent == 'signin' else not bool(user)) and _magic_request_rate_allowed(
        normalized, intent, _client_ip(),
    )
    if intent == 'signup':
        full_name, error = _require_string(payload.get('fullName') or payload.get('name'), 'fullName', max_len=200)
        if error:
            return error
        consent = payload.get('consent') if isinstance(payload.get('consent'), dict) else {}
        missing = _missing_required_consent(consent)
        if missing:
            return _bad_request(f"Please confirm you agree to {missing['label']}")
        turnstile = _turnstile_config()
        turnstile_token = str(payload.get('turnstileToken') or '')
        if turnstile['required']:
            if not turnstile['enabled']:
                return _public_error('ADMISSION_UNAVAILABLE', 'Signup admission is not configured.', 503)
            if not _verify_turnstile_token(turnstile_token, _client_ip()):
                return _public_error('ADMISSION_FAILED', 'Signup admission verification failed.', 400)
        metadata = {'full_name': full_name, 'consent': consent, 'admission_verified': True}

    if get_store().recent_magic_challenge_count(
        normalized, since=datetime.now(timezone.utc) - timedelta(minutes=15), intent=intent,
    ) >= 5:
        eligible = False

    issued = None
    if eligible:
        issued = get_store().issue_magic_challenge(
            normalized,
            intent=intent,
            purpose=f'auth_magic:{intent}',
            origin=_cleanhouse_public_origin().rstrip('/'),
            user_id=str(_model_user_id(user)) if user else None,
            metadata=metadata,
        )
        link = f"{_cleanhouse_public_origin().rstrip('/')}/magic#token={urllib.parse.quote(issued.secret)}&intent={intent}"
        try:
            deliver_auth_email(
                normalized,
                subject='Your CleanHouse sign-in link',
                text=f"Confirm access to the CleanHouse antivirus on this Mac: {link}\nThis link expires in 15 minutes and can be used once.",
            )
        except Exception:
            get_store().revoke_magic_challenge(issued.id)
            logging.warning('Magic-email delivery failed for a bounded challenge')
    response = jsonify({
        'success': True,
        'message': 'If this request is eligible, a CleanHouse confirmation link has been sent.',
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/magic/verify', methods=['POST'])
def verify_magic_email():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    payload, error = _get_json_payload()
    if error:
        return error
    token, error = _require_string(payload.get('token'), 'token', max_len=512)
    if error:
        return error
    intent = str(payload.get('intent') or '').strip().lower()
    if intent not in {'signin', 'signup'}:
        return _bad_request('intent must be signin or signup')
    result = get_store().consume_magic_challenge(
        token,
        purpose=f'auth_magic:{intent}',
        origin=_cleanhouse_public_origin().rstrip('/'),
    )
    if result.status != 'consumed' or not result.record:
        return _public_error('MAGIC_LINK_INVALID', 'Magic link is invalid, expired, or already used.', 400)
    record = result.record
    user_service = get_user_service()
    user = user_service.get_user_by_email(record['normalized_email'])
    if intent == 'signin':
        if not user or str(_model_user_id(user)) != str(record.get('user_id') or ''):
            return _public_error('MAGIC_LINK_INVALID', 'Magic link is invalid, expired, or already used.', 400)
    else:
        if user:
            return _public_error('MAGIC_SIGNUP_CONFLICT', 'This identity already exists. Use sign in.', 409)
        metadata = record.get('metadata') or {}
        if metadata.get('admission_verified') is not True:
            return _public_error('ADMISSION_REQUIRED', 'Verified signup admission is required.', 400)
        consent = metadata.get('consent') if isinstance(metadata.get('consent'), dict) else {}
        missing = _missing_required_consent(consent)
        if missing:
            return _public_error('CONSENT_REQUIRED', 'Current policy acceptance is required.', 428)
        user = user_service.create_user(
            full_name=str(metadata.get('full_name') or ''),
            email=record['normalized_email'],
            password=secrets.token_urlsafe(32),
        )
        try:
            _record_current_consent(str(_model_user_id(user)), consent, 'magic_email_signup', str(uuid.uuid4()))
        except Exception:
            user_service.delete_user(user_id=str(_model_user_id(user)))
            raise
    user_data = {
        'user_id': str(_model_user_id(user)),
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role,
    }
    response = _issue_session_response(user_data, {'success': True, 'user': user_data}, auth_method='magic_email')
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/providers', methods=['GET'])
def providers():
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    connected = {item['provider']: item for item in get_store().list_external_identities(identity.user_id)}
    public = auth_runtime_config.public_config_payload().get('providers', [])
    response = jsonify({'success': True, 'providers': [
        {**item, 'id': item['provider'], 'connected': item['provider'] in connected}
        for item in public if item.get('provider') in {'google', 'github'}
    ]})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/providers/<provider>/start', methods=['POST'])
def prepare_provider_link(provider):
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'provider_link')
    if sensitive_error:
        return sensitive_error
    provider = str(provider).lower()
    runtime = auth_runtime_config.provider_config(provider)
    if provider not in {'google', 'github'} or not runtime.get('available'):
        return _public_error('PROVIDER_UNAVAILABLE', 'Provider is not configured.', 503)
    nonce = secrets.token_urlsafe(24)
    prepared = dict(session.get('provider_link_prepared') or {})
    prepared[nonce] = {
        'provider': provider,
        'user_id': identity.user_id,
        'created_at': int(datetime.now(timezone.utc).timestamp()),
    }
    session['provider_link_prepared'] = prepared
    response = jsonify({
        'success': True,
        'authorization_url': f'/api/auth/oauth/{urllib.parse.quote(provider)}?intent=link&prepared={urllib.parse.quote(nonce)}',
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/providers/<provider>', methods=['DELETE'])
def unlink_provider(provider):
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'provider_link')
    if sensitive_error:
        return sensitive_error
    changed = get_store().unbind_external_identity(identity.user_id, str(provider).lower())
    return jsonify({'success': changed}), (200 if changed else 404)


@bp.route('/auth/tokens', methods=['GET'])
def list_api_tokens():
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    records = [{
        'id': item['token_id'], 'prefix': item['display_prefix'], 'name': item['label'],
        'created_at': item['created_at'], 'expires_at': item['expires_at'],
        'last_used_at': item['last_used_at'], 'revoked_at': item['revoked_at'],
    } for item in get_store().list_api_tokens(identity.user_id)]
    response = jsonify({'success': True, 'tokens': records})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/tokens', methods=['POST'])
def create_api_token():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity or not identity.consent_current:
        return _public_error('CONSENT_REQUIRED', 'Current consent and a device session are required.', 428)
    sensitive_error = _require_sensitive(identity, 'token_manage')
    if sensitive_error:
        return sensitive_error
    payload, error = _get_json_payload()
    if error:
        return error
    days = int(payload.get('expires_in_days') or 30)
    label = str(payload.get('label') or 'CleanHouse automation')[:120]
    try:
        issued = get_store().issue_api_token(identity.user_id, label=label, lifetime_days=days)
    except (TypeError, ValueError):
        return _bad_request('expires_in_days must be between 1 and 90')
    response = jsonify({'success': True, 'id': issued.id, 'token': issued.secret, 'prefix': issued.display_prefix, 'expires_at': issued.expires_at})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/tokens/<token_id>/rotate', methods=['POST'])
def rotate_api_token(token_id):
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'token_manage')
    if sensitive_error:
        return sensitive_error
    issued = get_store().rotate_api_token(str(token_id), identity.user_id)
    if not issued:
        return _public_error('TOKEN_NOT_FOUND', 'Token was not found.', 404)
    response = jsonify({'success': True, 'id': issued.id, 'token': issued.secret, 'prefix': issued.display_prefix, 'expires_at': issued.expires_at})
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.route('/auth/tokens/<token_id>', methods=['DELETE'])
def revoke_api_token(token_id):
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    identity = _current_identity()
    if not identity:
        return _public_error('AUTHENTICATION_REQUIRED', 'A device session is required.', 401)
    sensitive_error = _require_sensitive(identity, 'token_manage')
    if sensitive_error:
        return sensitive_error
    changed = get_store().revoke_api_token(str(token_id), identity.user_id)
    return jsonify({'success': changed}), (200 if changed else 404)


@bp.route('/auth/account', methods=['DELETE'])
@bp.route('/auth/deleteAccount', methods=['POST'])
def delete_account():
    """Delete the authenticated CleanHouse account and clear local VVAULT user rows."""
    try:
        csrf_error = _require_cookie_mutation()
        if csrf_error:
            return csrf_error
        identity = _current_identity()
        if not identity:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired token',
            }), 401
        sensitive_error = _require_sensitive(identity, 'account')
        if sensitive_error:
            return sensitive_error
        user_data = identity.user

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _bad_request("Request body must be a JSON object")

        email = str(user_data.get('email') or '').strip()
        user_id = str(user_data.get('user_id') or user_data.get('id') or '').strip()
        confirmation = str(payload.get('confirmation') or payload.get('email') or '').strip()
        if not email or not user_id:
            return jsonify({
                'success': False,
                'message': 'Authenticated user identity is incomplete',
            }), 400
        if confirmation.lower() != email.lower():
            return _bad_request('Confirm the account email before deletion')

        user_service = get_user_service()
        deleted = user_service.delete_user(user_id=user_id)
        get_store().revoke_all_sessions(user_id, reason='account_deleted')
        vvault_cleanup = _clear_vvault_user_records(user_id, email)
        marker_path = _write_account_deletion_marker(user_data, vvault_cleanup)
        session.clear()

        if not deleted:
            return jsonify({
                'success': False,
                'message': 'CleanHouse account was not found locally',
                'vvault_cleanup': vvault_cleanup,
                'archive_policy': {
                    'company_side_retention_years': 7,
                    'marker_path': marker_path,
                },
            }), 404

        return jsonify({
            'success': True,
            'message': 'Account deleted locally. Company-side archive retention remains 7 years.',
            'deleted_user_id': user_id,
            'email': email,
            'vvault_cleanup': vvault_cleanup,
            'archive_policy': {
                'company_side_retention_years': 7,
                'marker_path': marker_path,
            },
        })
    except Exception as e:
        logging.error("Account deletion failed: %s", e.__class__.__name__)
        return jsonify({
            'success': False,
            'code': 'ACCOUNT_DELETION_FAILED', 'message': 'Account deletion failed.',
        }), 500


@bp.route('/auth/recovery/request', methods=['POST'])
def request_recovery():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    data, error = _get_json_payload()
    if error:
        return error
    email, error = _require_string(data.get('email'), 'email', max_len=320)
    if error:
        return error
    user = get_user_service().get_user_by_email(email)
    if user:
        raw_token = issue_recovery(str(_model_user_id(user)), user.email)
        try:
            deliver_recovery(user.email, raw_token, _cleanhouse_public_origin())
        except Exception:
            logging.exception('Account recovery delivery failed')
    return jsonify({'success': True, 'message': 'If that account exists, recovery instructions have been sent.'})


@bp.route('/auth/recovery/reset', methods=['POST'])
def reset_password():
    csrf_error = _require_cookie_mutation()
    if csrf_error:
        return csrf_error
    data, error = _get_json_payload()
    if error:
        return error
    token, error = _require_string(data.get('token'), 'token', max_len=512)
    if error:
        return error
    password, error = _require_string(data.get('password'), 'password', max_len=4096)
    if error:
        return error
    if len(password) < 8:
        return _bad_request('Password must be at least 8 characters')
    recovery = consume_recovery(token)
    if not recovery:
        return _public_error('INVALID_RECOVERY_TOKEN', 'Recovery link is invalid or expired.', 400)
    if not get_user_service().set_password(recovery['user_id'], password):
        return _public_error('RECOVERY_FAILED', 'Password could not be updated.', 500)
    get_store().revoke_all_sessions(str(recovery['user_id']), reason='password_recovery')
    session.clear()
    response = jsonify({'success': True, 'message': 'Password updated. Please sign in.'})
    clear_session_cookie(response)
    return response

@bp.route('/auth/logout', methods=['POST'])
def logout():
    """Clear only the requesting browser session; preserve other clients."""
    try:
        csrf_error = _require_cookie_mutation()
        if csrf_error:
            return csrf_error
        identity = _current_identity()
        if identity and identity.kind == 'session':
            get_store().revoke_session(identity.credential_id, identity.user_id)
        session.clear()

        auth_context.g.cleanhouse_session_replacement = None
        response = jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
        clear_session_cookie(response)
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception as e:
        logging.error("Logout failed: %s", e.__class__.__name__)
        return jsonify({
            'success': False,
            'code': 'LOGOUT_FAILED', 'message': 'Logout failed.'
        }), 500

def exchange_oauth_token(provider: str, code: str, code_verifier: str) -> Optional[Dict[str, Any]]:
    """Exchange OAuth authorization code for access token."""
    try:
        if provider not in _ALLOWED_OAUTH_PROVIDERS:
            return None
        if not isinstance(code, str) or not code.strip():
            return None
        if not isinstance(code_verifier, str) or not code_verifier.strip():
            return None

        provider_runtime = auth_runtime_config.provider_config(provider)
        client_id = str(provider_runtime.get('client_id') or '')
        client_secret = str(provider_runtime.get('client_secret') or '')
        redirect_uri = _oauth_redirect_uri(provider)

        token_data = {
            'client_id': client_id,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        # Add PKCE verifier
        if code_verifier:
            token_data['code_verifier'] = code_verifier

        # Add client secret if available
        if client_secret:
            token_data['client_secret'] = client_secret

        # Determine token URL
        if provider.lower() == 'google':
            token_url = 'https://oauth2.googleapis.com/token'
        elif provider.lower() == 'microsoft':
            token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        elif provider.lower() == 'github':
            token_url = 'https://github.com/login/oauth/access_token'
            headers = {'Accept': 'application/json'}
        elif provider.lower() == 'apple':
            token_url = 'https://appleid.apple.com/auth/token'
        else:
            return None

        headers = headers if provider.lower() == 'github' else {}
        response = requests.post(token_url, data=token_data, headers=headers, timeout=(3, 10), stream=True)

        if response.status_code == 200:
            payload = _bounded_response_json(response)
            return payload if isinstance(payload, dict) else None
        else:
            logging.error("OAuth token exchange failed with HTTP %s", response.status_code)
            return None

    except Exception as e:
        logging.error("OAuth token exchange failed: %s", e.__class__.__name__)
        return None

def get_oauth_user_info(provider: str, access_token: str) -> Optional[Dict[str, Any]]:
    """Get user information from OAuth provider."""
    try:
        if provider not in _ALLOWED_OAUTH_PROVIDERS:
            return None
        if not isinstance(access_token, str) or not access_token.strip():
            return None

        if provider.lower() == 'google':
            user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get(user_info_url, headers=headers, timeout=(3, 10), stream=True)
            if response.status_code == 200:
                data = _bounded_response_json(response)
                if not isinstance(data, dict):
                    return None
                return {
                    'email': data.get('email'),
                    'name': data.get('name', ''),
                    'id': data.get('id', ''),
                    'avatar_url': data.get('picture', ''),
                }
        elif provider.lower() == 'microsoft':
            user_info_url = 'https://graph.microsoft.com/v1.0/me'
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get(user_info_url, headers=headers, timeout=(3, 10), stream=True)
            if response.status_code == 200:
                data = _bounded_response_json(response)
                if not isinstance(data, dict):
                    return None
                return {
                    'email': data.get('mail') or data.get('userPrincipalName'),
                    'name': data.get('displayName', ''),
                    'id': data.get('id', '')
                }
        elif provider.lower() == 'github':
            user_info_url = 'https://api.github.com/user'
            headers = {'Authorization': f'token {access_token}', 'Accept': 'application/vnd.github.v3+json'}
            response = requests.get(user_info_url, headers=headers, timeout=(3, 10), stream=True)
            if response.status_code == 200:
                data = _bounded_response_json(response)
                if not isinstance(data, dict):
                    return None
                # Get email from separate endpoint
                email_url = 'https://api.github.com/user/emails'
                email_response = requests.get(email_url, headers=headers, timeout=(3, 10), stream=True)
                email = None
                if email_response.status_code == 200:
                    emails = _bounded_response_json(email_response)
                    if not isinstance(emails, list):
                        return None
                    for em in emails:
                        if isinstance(em, dict) and em.get('primary') is True and em.get('verified') is True:
                            email = em.get('email')
                            break
                if not email:
                    return None
                return {
                    'email': email,
                    'name': data.get('name') or data.get('login', ''),
                    'id': str(data.get('id', '')),
                    'avatar_url': data.get('avatar_url', ''),
                }
        # Apple requires different handling (JWT token)
        elif provider.lower() == 'apple':
            # Apple returns user info in the initial callback, not via API
            # This would need to be handled differently
            return None

        return None
    except Exception as exc:
        logging.error("OAuth user-info resolution failed: %s", exc.__class__.__name__)
        return None
