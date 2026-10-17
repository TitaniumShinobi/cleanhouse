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
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any
import re
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import UserService, DatabaseManager
from backend.utils.jwt_utils import generate_jwt_token, verify_jwt_token, get_user_from_token
from backend.utils.csrf import generate_csrf_token, csrf_protect
from backend import auth_runtime_config
from backend.auth_recovery import issue_recovery, consume_recovery, deliver_recovery

bp = Blueprint('auth', __name__)

# Initialize database and user service
_db_manager = None
_user_service = None

_ALLOWED_OAUTH_PROVIDERS = {"google", "microsoft", "github", "apple"}
_OAUTH_STATE_TTL_SECONDS = 600
_MAX_PENDING_OAUTH_STATES = 4


def _bad_request(reason: str):
    return jsonify({
        'success': False,
        'message': reason,
    }), 400


def _public_error(code: str, message: str, status: int):
    return jsonify({'success': False, 'code': code, 'message': message}), status


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
    return os.getenv('CLEANHOUSE_PUBLIC_ORIGIN') or f"http://127.0.0.1:{os.getenv('CLEANHOUSE_PORT', '3333')}"


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
        return f"{canonical_origin}/api/auth/oauth/{urllib.parse.quote(provider)}"
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
                'signup_proof': payload.get('signup_proof') if _signup_proof_current(payload.get('signup_proof')) else None,
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
    return [
        {
            'product': 'cleanhouse',
            'docType': 'terms',
            'key': 'cleanhouse:terms',
            'version': os.getenv('LEGAL_VERSION_CLEANHOUSE_TERMS', '2025-11-09'),
            'label': 'CleanHouse Terms of Service',
            'url': f'{origin}/legal/terms',
            'required': True,
        },
        {
            'product': 'cleanhouse',
            'docType': 'privacy',
            'key': 'cleanhouse:privacy',
            'version': os.getenv('LEGAL_VERSION_CLEANHOUSE_PRIVACY', '2025-11-09'),
            'label': 'CleanHouse Privacy Notice',
            'url': f'{origin}/legal/privacy',
            'required': True,
        },
        {
            'product': 'cleanhouse',
            'docType': 'eeccd',
            'key': 'cleanhouse:eeccd',
            'version': os.getenv('LEGAL_VERSION_CLEANHOUSE_EECCD', '2025-11-09'),
            'label': 'European Electronic Communications Code Disclosure',
            'url': f'{origin}/legal/eeccd',
            'required': True,
        },
    ]


def _missing_required_consent(consent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for doc in _cleanhouse_auth_docs():
        if consent.get(doc['key']) is not True:
            return doc
    return None



def _validate_signup_intent(data):
    """Authorize signup only after current policy is accepted and verified."""
    if not isinstance(data, dict) or data.get('intent') != 'signup':
        return None, _public_error('SIGNUP_INTENT_REQUIRED', 'Explicit signup is required.', 400)
    consent = data.get('consent')
    versions = data.get('consentVersions')
    if not isinstance(consent, dict) or not isinstance(versions, dict):
        return None, _public_error('CONSENT_REQUIRED', 'Accept current signup documents.', 400)
    if _missing_required_consent(consent) or versions != {doc['key']: doc['version'] for doc in _cleanhouse_auth_docs() if doc['required']}:
        return None, _public_error('CONSENT_REQUIRED', 'Accept current signup documents.', 400)
    turnstile = _turnstile_config()
    verified = False
    if turnstile['required']:
        if not turnstile['enabled']:
            return None, _public_error('VERIFICATION_UNAVAILABLE', 'Signup verification is unavailable.', 503)
        token = data.get('turnstileToken')
        if not isinstance(token, str) or not token.strip() or not _verify_turnstile_token(token, _client_ip()):
            return None, _public_error('VERIFICATION_REQUIRED', 'Complete signup verification.', 400)
        verified = True
    return {'intent': 'signup', 'consent_versions': versions, 'turnstile_verified': verified}, None


def _signup_proof_current(proof):
    if not isinstance(proof, dict) or proof.get('intent') != 'signup':
        return False
    versions = {doc['key']: doc['version'] for doc in _cleanhouse_auth_docs() if doc['required']}
    return (proof.get('consent_versions') == versions
            and (not _turnstile_config()['required'] or proof.get('turnstile_verified') is True))


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
        logging.warning("Turnstile verification failed: %s", exc)
        return False


def _client_ip() -> str:
    forwarded = getattr(request, 'headers', {}).get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return getattr(request, 'remote_addr', '') or ''


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
        logging.warning("Login report generation failed: %s", exc, exc_info=True)
        return {
            'status': 'unavailable',
            'message': str(exc) or exc.__class__.__name__,
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
        logging.warning("Failed to write account deletion marker: %s", exc)
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
            'docs': _cleanhouse_auth_docs(),
            'turnstile': _turnstile_config(),
            'providers': public_auth['providers'],
        },
    })


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

        user_service = get_user_service()

        # Create user
        user = user_service.create_user(
            full_name=full_name,
            email=email,
            password=password,
            role=role
        )

        # Prepare user data for JWT
        user_data = {
            'user_id': _model_user_id(user),
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role
        }
        login_report = _build_login_report_payload(
            user_data,
            previous_login_at=None,
            trigger='auth/createAccount',
        )

        # Generate JWT token
        token = generate_jwt_token(user_data)

        # Store in session for OAuth compatibility
        session['user_id'] = user_data['user_id']
        session['email'] = user_data['email']

        return jsonify({
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
            'token': token,
            'login_report': login_report
        })
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 400
    except Exception as e:
        logging.error(f"Account creation error: {e}", exc_info=True)
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

        user_service = get_user_service()
        user = user_service.authenticate_user(email, password)

        if user:
            previous_login_at = _last_login_iso(user)
            # Prepare user data for JWT
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

            # Generate JWT token
            token = generate_jwt_token(user_data)

            # Store in session for OAuth compatibility
            session['user_id'] = user_data['user_id']
            session['email'] = user_data['email']

            return jsonify({
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
                'token': token,
                'login_report': login_report
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid email or password'
            }), 401
    except Exception as e:
        logging.error(f"Login error: {e}", exc_info=True)
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

        canonical_start = _canonical_oauth_start(provider)
        if canonical_start:
            if request.method == 'POST':
                return _public_error('CANONICAL_ORIGIN_REQUIRED', 'Open signup on the configured callback origin.', 409)
            return redirect(canonical_start)

        provider_runtime = auth_runtime_config.provider_config(provider)
        if not provider_runtime.get('enabled') or not provider_runtime.get('available'):
            return redirect(
                '/login?error=provider_unavailable&provider=' + urllib.parse.quote(provider)
            )

        signup_proof = None
        if request.method == 'POST':
            if request.headers.get('Origin') != request.host_url.rstrip('/'):
                return _public_error('REQUEST_ORIGIN_REJECTED', 'Same-origin signup is required.', 403)
            signup_proof, signup_error = _validate_signup_intent(request.get_json(silent=True))
            if signup_error:
                return signup_error

        # Generate PKCE codes
        code_verifier, code_challenge = generate_pkce()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        oauth_states = _bounded_oauth_states(session.get('oauth_states'))
        oauth_states[state] = {
            'provider': provider,
            'code_verifier': code_verifier,
            'created_at': int(datetime.now(timezone.utc).timestamp()),
            'signup_proof': signup_proof,
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
                'access_type': 'offline'
            }
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
            scope = 'user:email'
            auth_url = 'https://github.com/login/oauth/authorize'
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'scope': scope,
                'state': state
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

        # Signup POST is fetched; browser navigation follows the returned provider URL.
        if request.method == 'POST':
            return jsonify({'success': True, 'authorizationUrl': oauth_url})
        return redirect(oauth_url)

    except Exception as e:
        logging.error(f"OAuth error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'code': 'OAUTH_START_FAILED', 'message': 'OAuth sign in could not be started.'
        }), 500

@bp.route('/auth/google/callback', methods=['GET', 'POST'])
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

        if error:
            logging.error(f"OAuth error from provider: {error}")
            return redirect('/login?error=' + urllib.parse.quote(error))

        if not code or not state:
            logging.error("OAuth callback missing code or state")
            return redirect('/login?error=invalid_callback')

        if not isinstance(code, str) or not isinstance(state, str):
            logging.error("OAuth callback has non-string code/state")
            return redirect('/login?error=invalid_callback')

        code = code.strip()
        state = state.strip()
        if not code or not state:
            logging.error("OAuth callback has malformed code/state")
            return redirect('/login?error=invalid_callback')

        # Verify state
        raw_oauth_states = session.get('oauth_states')
        raw_oauth_states = dict(raw_oauth_states) if isinstance(raw_oauth_states, dict) else {}
        oauth_data = raw_oauth_states.pop(state, None)
        oauth_states = _bounded_oauth_states(raw_oauth_states)
        session['oauth_states'] = oauth_states
        session.modified = True
        if not oauth_data:
            logging.error(f"OAuth state mismatch: {state}")
            return redirect('/login?error=invalid_state')
        created_at = int(oauth_data.get('created_at') or 0)
        if int(datetime.now(timezone.utc).timestamp()) - created_at > _OAUTH_STATE_TTL_SECONDS:
            return redirect('/login?error=expired_state')
        provider = oauth_data['provider']
        code_verifier = oauth_data['code_verifier']
        if not isinstance(code_verifier, str) or not code_verifier.strip():
            logging.error("OAuth callback missing code verifier")
            return redirect('/login?error=invalid_state')

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

        # Create or authenticate user
        user_service = get_user_service()
        existing_user = user_service.get_user_by_email(user_info['email'])
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
        else:
            if not _signup_proof_current(oauth_data.get('signup_proof')):
                return redirect('/signup?error=signup_required')
            # Create new user only for the verified signup transaction.
            import secrets
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
        login_report = _build_login_report_payload(
            user_data,
            previous_login_at=previous_login_at,
            current_login_at=current_login_at,
            trigger=f'auth/oauth/{provider}',
        )

        # Store user data in session
        session['oauth_user'] = {
            'id': user_data['user_id'],
            'user_id': user_data['user_id'],
            'email': user_data['email'],
            'full_name': user_data['full_name'],
            'name': user_data['full_name'],
            'role': user_data['role']
        }
        session['oauth_success'] = True
        login_report_reference = _login_report_reference(login_report)
        if login_report_reference:
            session['oauth_login_report'] = login_report_reference
        else:
            session.pop('oauth_login_report', None)

        # Redirect to login page with success indicator
        return redirect('/login?oauth_success=1')

    except Exception as e:
        logging.error(f"OAuth callback error: {e}", exc_info=True)
        return redirect('/login?error=oauth_callback_failed')

@bp.route('/auth/oauth/user', methods=['GET'])
def oauth_user():
    """Get OAuth user data from session"""
    from flask import session
    if session.get('oauth_success') and session.get('oauth_user'):
        user_data = session.pop('oauth_user')
        login_report = session.pop('oauth_login_report', None)
        session.pop('oauth_success', None)
        session['user_id'] = user_data['user_id']
        session['email'] = user_data['email']
        return jsonify({
            'success': True,
            'user': user_data,
            'login_report': login_report
        })

    return jsonify({
        'success': False,
        'message': 'No OAuth user data found'
    }), 404

@bp.route('/auth/me', methods=['GET'])
def get_current_user():
    """Get the current browser session, with bearer support for native clients."""
    try:
        auth_header = request.headers.get('Authorization', '')
        user_data = None
        if auth_header:
            token, error = _extract_bearer_token(auth_header)
            if error:
                return _public_error('INVALID_AUTHORIZATION', 'Authorization header must be in the format: Bearer <token>', 401)
            user_data = get_user_from_token(token)
        elif session.get('user_id'):
            user = get_user_service().get_user_by_id(user_id=str(session['user_id']))
            if user:
                user_data = {'user_id': _model_user_id(user), 'email': user.email, 'full_name': user.full_name, 'role': user.role}

        if user_data:
            return jsonify({
                'success': True,
                'user': {
                    'id': user_data['user_id'],
                    'user_id': user_data['user_id'],
                    'email': user_data['email'],
                    'full_name': user_data['full_name'],
                    'name': user_data['full_name'],
                    'role': user_data['role']
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired token'
            }), 401
    except Exception as e:
        logging.error(f"Get current user error: {e}", exc_info=True)
        return _public_error('AUTH_SESSION_FAILED', 'Unable to validate the current session.', 500)


@bp.route('/auth/account', methods=['DELETE'])
@bp.route('/auth/deleteAccount', methods=['POST'])
def delete_account():
    """Delete the authenticated CleanHouse account and clear local VVAULT user rows."""
    try:
        auth_header = request.headers.get('Authorization', '')
        user_data = None
        if auth_header:
            token, error = _extract_bearer_token(auth_header)
            if error:
                return _public_error('INVALID_AUTHORIZATION', 'Authorization header must be in the format: Bearer <token>', 401)
            user_data = get_user_from_token(token)
        elif session.get('user_id'):
            user = get_user_service().get_user_by_id(user_id=str(session['user_id']))
            if user:
                user_data = {'user_id': _model_user_id(user), 'email': user.email, 'full_name': user.full_name, 'role': user.role}
        if not user_data:
            return jsonify({
                'success': False,
                'message': 'Invalid or expired token',
            }), 401

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
        logging.error(f"Account deletion error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'code': 'ACCOUNT_DELETION_FAILED', 'message': 'Account deletion failed.',
        }), 500


@bp.route('/auth/recovery/request', methods=['POST'])
def request_recovery():
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
    session.clear()
    return jsonify({'success': True, 'message': 'Password updated. Please sign in.'})

@bp.route('/auth/logout', methods=['POST'])
def logout():
    """Clear only the requesting browser session; preserve other clients."""
    try:
        # Clear session
        session.clear()

        return jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
    except Exception as e:
        logging.error(f"Logout error: {e}", exc_info=True)
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
        response = requests.post(token_url, data=token_data, headers=headers, timeout=10)

        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Token exchange failed: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logging.error(f"Token exchange error: {e}", exc_info=True)
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
            response = requests.get(user_info_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'email': data.get('email'),
                    'name': data.get('name', ''),
                    'id': data.get('id', '')
                }
        elif provider.lower() == 'microsoft':
            user_info_url = 'https://graph.microsoft.com/v1.0/me'
            headers = {'Authorization': f'Bearer {access_token}'}
            response = requests.get(user_info_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    'email': data.get('mail') or data.get('userPrincipalName'),
                    'name': data.get('displayName', ''),
                    'id': data.get('id', '')
                }
        elif provider.lower() == 'github':
            user_info_url = 'https://api.github.com/user'
            headers = {'Authorization': f'token {access_token}', 'Accept': 'application/vnd.github.v3+json'}
            response = requests.get(user_info_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Get email from separate endpoint
                email_url = 'https://api.github.com/user/emails'
                email_response = requests.get(email_url, headers=headers, timeout=10)
                email = None
                if email_response.status_code == 200:
                    emails = email_response.json()
                    for em in emails:
                        if em.get('primary') or em.get('verified'):
                            email = em.get('email')
                            break
                    if not email and emails:
                        email = emails[0].get('email')
                return {
                    'email': email or data.get('email'),
                    'name': data.get('name') or data.get('login', ''),
                    'id': str(data.get('id', ''))
                }
        # Apple requires different handling (JWT token)
        elif provider.lower() == 'apple':
            # Apple returns user info in the initial callback, not via API
            # This would need to be handled differently
            return None

        return None
    except Exception as e:
        logging.error(f"Error getting user info: {e}", exc_info=True)
        return None
