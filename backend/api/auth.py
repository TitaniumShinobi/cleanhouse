"""
Authentication API endpoints for CleanHouse.
"""

from flask import Blueprint, request, jsonify, redirect, session, url_for
from pathlib import Path
import sys
import os
import logging
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
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import UserService, DatabaseManager
from backend.utils.jwt_utils import generate_jwt_token, verify_jwt_token, get_user_from_token
from backend.utils.csrf import generate_csrf_token, csrf_protect

bp = Blueprint('auth', __name__)

# Initialize database and user service
_db_manager = None
_user_service = None

# OAuth state storage (in production, use Redis or database)
_oauth_states = {}  # {state: {provider, code_verifier, timestamp}}
_ALLOWED_OAUTH_PROVIDERS = {"google", "microsoft", "github", "apple"}


def _bad_request(reason: str):
    return jsonify({
        'success': False,
        'message': reason,
    }), 400


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

        return get_cleanhouse_monitoring_adapter().build_login_report(
            user_id=str(user_data.get('user_id') or user_data.get('id') or ''),
            email=str(user_data.get('email') or ''),
            previous_login_at=previous_login_at,
            current_login_at=current_login_at or datetime.now().isoformat(),
            trigger=trigger,
        )
    except Exception as exc:
        logging.warning("Login report generation failed: %s", exc, exc_info=True)
        return {
            'status': 'unavailable',
            'message': str(exc) or exc.__class__.__name__,
        }


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

@bp.route('/auth/createAccount', methods=['POST'])
def create_account():
    """Create a new user account"""
    try:
        data, error = _get_json_payload()
        if error:
            return error

        full_name, error = _require_string(data.get('fullName'), 'fullName', required=False)
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
            'message': f'Account creation failed: {str(e)}'
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
            'message': f'Login failed: {str(e)}'
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

        # Generate PKCE codes
        code_verifier, code_challenge = generate_pkce()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state and verifier (in production, use Redis or database)
        _oauth_states[state] = {
            'provider': provider,
            'code_verifier': code_verifier,
            'timestamp': threading.current_thread().ident
        }

        # Get client ID from environment
        client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
        if not client_id:
            logging.error(f"{provider.upper()}_CLIENT_ID not found in environment")
            logging.debug(f"Available env vars with CLIENT_ID: {[k for k in os.environ.keys() if 'CLIENT_ID' in k]}")
            # Try to load from .env file if not already loaded
            try:
                from dotenv import load_dotenv
                env_path = Path(__file__).parent.parent.parent / '.env'
                if env_path.exists():
                    load_dotenv(env_path, override=False)
                    client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
                    logging.info(f"Reloaded .env file, {provider.upper()}_CLIENT_ID: {'found' if client_id else 'not found'}")
            except ImportError:
                pass

            if not client_id:
                return jsonify({
                    'success': False,
                    'message': f'{provider.capitalize()} OAuth not configured. Please set {provider.upper()}_CLIENT_ID in environment.'
                }), 400

        # Build redirect URI (points back to our callback endpoint)
        redirect_uri = f'{_cleanhouse_public_origin()}/api/auth/oauth/callback'

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
        logging.info(f"[OAUTH] Client ID: {client_id[:20]}...")
        logging.info(f"[OAUTH] Redirect URI: {redirect_uri}")
        logging.info(f"[OAUTH] OAuth URL: {oauth_url[:150]}...")

        # Redirect to OAuth provider
        return redirect(oauth_url)

    except Exception as e:
        logging.error(f"OAuth error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'OAuth error: {str(e)}'
        }), 500

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
        if state not in _oauth_states:
            logging.error(f"OAuth state mismatch: {state}")
            return redirect('/login?error=invalid_state')

        oauth_data = _oauth_states.pop(state)
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
            # Create new user
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

        # Generate JWT token
        token = generate_jwt_token(user_data)

        # Store user data in session
        session['oauth_user'] = {
            'id': user_data['user_id'],
            'user_id': user_data['user_id'],
            'email': user_data['email'],
            'full_name': user_data['full_name'],
            'name': user_data['full_name'],
            'role': user_data['role']
        }
        session['oauth_token'] = token
        session['oauth_success'] = True
        session['oauth_login_report'] = login_report

        # Save token to file for desktop app to pick up
        from pathlib import Path
        cleanhouse_root = Path.home() / '.cleanhouse'
        cleanhouse_root.mkdir(parents=True, exist_ok=True)

        # Save token to .auth_token file
        auth_token_file = cleanhouse_root / '.auth_token'
        auth_token_file.write_text(token, encoding='utf-8')

        # Save user data to .auth_user.json
        auth_user_file = cleanhouse_root / '.auth_user.json'
        import json as json_lib
        auth_user_file.write_text(json_lib.dumps(session['oauth_user'], indent=2), encoding='utf-8')

        logging.info(f"Saved authentication token for desktop app: {user_data['email']}")

        # Redirect to login page with success indicator
        return redirect('/login?oauth_success=1')

    except Exception as e:
        logging.error(f"OAuth callback error: {e}", exc_info=True)
        return redirect('/login?error=' + urllib.parse.quote(str(e)))

@bp.route('/auth/oauth/user', methods=['GET'])
def oauth_user():
    """Get OAuth user data from session"""
    from flask import session
    if session.get('oauth_success') and session.get('oauth_user'):
        user_data = session.pop('oauth_user')
        token = session.pop('oauth_token', None)
        login_report = session.pop('oauth_login_report', None)
        session.pop('oauth_success', None)
        return jsonify({
            'success': True,
            'user': user_data,
            'token': token,
            'login_report': login_report
        })
    else:
        return jsonify({
            'success': False,
            'message': 'No OAuth user data found'
        }), 404

@bp.route('/auth/launch-desktop', methods=['POST'])
def launch_desktop():
    """Save JWT token and launch desktop app"""
    try:
        data, error = _get_json_payload()
        if error:
            return error
        token, error = _require_string(data.get('token'), 'token')
        if error:
            return error
        user_data, error = _require_dict(data.get('user'), 'user')
        if error:
            return error
        if not token:
            return jsonify({
                'success': False,
                'message': 'Token required'
            }), 400

        # Save token to file that desktop app can read
        from pathlib import Path
        cleanhouse_root = Path.home() / '.cleanhouse'
        cleanhouse_root.mkdir(parents=True, exist_ok=True)

        # Save token to .auth_token file
        auth_token_file = cleanhouse_root / '.auth_token'
        auth_token_file.write_text(token, encoding='utf-8')

        # Save user data to .auth_user.json
        auth_user_file = cleanhouse_root / '.auth_user.json'
        import json as json_lib
        auth_user_file.write_text(json_lib.dumps(user_data, indent=2), encoding='utf-8')

        logging.info(f"Saved authentication token for user: {user_data.get('email', 'unknown')}")

        # Launch desktop app
        import subprocess
        import sys
        from pathlib import Path as PathLib

        # Get the project root directory
        project_root = PathLib(__file__).parent.parent.parent
        brain_py = project_root / 'corefiles' / 'brain.py'

        if not brain_py.exists():
            logging.error(f"Desktop app not found at: {brain_py}")
            return jsonify({
                'success': False,
                'message': 'Desktop app not found'
            }), 500

        # Launch desktop app in background
        # Use sys.executable to use the same Python interpreter
        subprocess.Popen(
            [sys.executable, str(brain_py)],
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True  # Detach from parent process
        )

        logging.info("Desktop app launched successfully")

        return jsonify({
            'success': True,
            'message': 'Desktop app launched'
        })

    except Exception as e:
        logging.error(f"Launch desktop error: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Failed to launch desktop app: {str(e)}'
        }), 500

@bp.route('/auth/me', methods=['GET'])
def get_current_user():
    """Get current authenticated user from JWT token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        token, error = _extract_bearer_token(auth_header)
        if error:
            return jsonify({
                'success': False,
                'message': error[0]['message'] if isinstance(error[0], dict) else 'Authorization header missing or invalid'
            }), 401

        user_data = get_user_from_token(token)

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
        return jsonify({
            'success': False,
            'message': f'Error getting user: {str(e)}'
        }), 500

@bp.route('/auth/test-oauth', methods=['GET'])
def test_oauth():
    """Test endpoint to check OAuth configuration"""
    providers = ['google', 'microsoft', 'apple', 'github']
    config = {}

    for provider in providers:
        client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
        client_secret = os.getenv(f'{provider.upper()}_CLIENT_SECRET', '')
        config[provider] = {
            'client_id_set': bool(client_id),
            'client_secret_set': bool(client_secret),
            'client_id_preview': client_id[:20] + '...' if client_id else None
        }

    return jsonify({
        'success': True,
        'oauth_config': config,
        'env_file_exists': (Path(__file__).parent.parent.parent / '.env').exists()
    })

@bp.route('/auth/logout', methods=['POST'])
def logout():
    """Logout user and clear session"""
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
            'message': f'Logout failed: {str(e)}'
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

        client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
        client_secret = os.getenv(f'{provider.upper()}_CLIENT_SECRET', '')
        redirect_uri = f'{_cleanhouse_public_origin()}/api/auth/oauth/callback'

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
