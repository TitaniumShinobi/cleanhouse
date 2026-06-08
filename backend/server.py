"""
Flask server for CleanHouse frontend.
Serves static files and provides API endpoints.
"""

from pathlib import Path
import atexit
from flask import Flask, send_from_directory, jsonify, request, session
from flask_cors import CORS
import sys
import os
import secrets
import logging

def _read_secret_key() -> str:
    """Load or create a local secret key for Flask session signing."""
    env_secret = os.getenv("FLASK_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    secret_path = Path.home() / ".cleanhouse" / ".flask_secret_key"
    if secret_path.exists():
        try:
            file_secret = secret_path.read_text(encoding="utf-8").strip()
            if file_secret:
                return file_secret
        except Exception as exc:
            logging.warning("Failed to read secret key file at %s: %s", secret_path, exc)

    generated = secrets.token_hex(32)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(generated, encoding="utf-8")
    except Exception as exc:
        logging.warning("Unable to persist secret key to %s: %s", secret_path, exc)
    return generated


def _allowed_cors_origins():
    local_patterns = [
        r"^https?://localhost(:\d+)?$",
        r"^https?://127\.0\.0\.1(:\d+)?$",
        r"^https?://\[\:\:1\](:\d+)?$",
    ]

    for env_name in ("CLEANHOUSE_ALLOWED_ORIGINS", "CLEANHOUSE_ALLOW_REMOTE_ORIGINS"):
        extra = os.getenv(env_name, "").strip()
        if extra:
            local_patterns.extend(
                value.strip() for value in extra.split(",") if value.strip()
            )

    return local_patterns

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 3333

# Configure logging
logging.basicConfig(level=logging.INFO)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        logging.info(f"Loaded environment variables from {env_path}")
    else:
        logging.warning(f".env file not found at {env_path}")
except ImportError:
    logging.warning("python-dotenv not installed, environment variables must be set manually")

# Safe defaults: native notifications enabled with live-only delivery gates.
os.environ.setdefault("CLEANHOUSE_NATIVE_NOTIFICATIONS", "1")
os.environ.setdefault("CLEANHOUSE_NATIVE_CODEX_ACTIVITY", "1")
os.environ.setdefault("CLEANHOUSE_NATIVE_LIVE_ONLY", "1")
os.environ.setdefault("CLEANHOUSE_NATIVE_LIVE_MAX_AGE_SECONDS", "3")
os.environ.setdefault("CLEANHOUSE_NATIVE_REMINDERS", "0")
os.environ.setdefault("CLEANHOUSE_ACTIVE_CONTEXT_RESPONSE_NOTIFICATIONS", "1")
os.environ.setdefault("CLEANHOUSE_ACTIVE_CONTEXT_FOLLOW", "1")

from backend.api.cleanhouse import bp as cleanhouse_bp
from backend import events as cleanhouse_events
from backend import runtime_supervisor

app = Flask(__name__, static_folder=None)
app.secret_key = _read_secret_key()

# Configure Flask sessions
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'cleanhouse:'
app.config['SESSION_FILE_DIR'] = str(Path.home() / ".cleanhouse" / "sessions")
app.config['SESSION_COOKIE_NAME'] = "cleanhouse_session"
app.config['SESSION_COOKIE_SECURE'] = os.getenv("CLEANHOUSE_SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

CORS(
    app,
    resources={r"/*": {
        "origins": _allowed_cors_origins(),
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
    }},
)

# Get paths
BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Register API routes
app.register_blueprint(cleanhouse_bp)


def _cleanhouse_port():
    value = os.environ.get('CLEANHOUSE_PORT', str(DEFAULT_PORT))
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid CLEANHOUSE_PORT=%r; falling back to %s", value, DEFAULT_PORT)
        return DEFAULT_PORT


def _auth_enabled():
    return os.environ.get('CLEANHOUSE_ENABLE_AUTH', '1').lower() not in {'0', 'false', 'no', 'off'}


if _auth_enabled():
    try:
        from backend.api import auth
        app.register_blueprint(auth.bp, url_prefix='/api')
    except Exception as exc:
        logging.warning("Auth API disabled; CleanHouse monitoring endpoints remain available: %s", exc)
else:
    logging.info("Auth API disabled; set CLEANHOUSE_ENABLE_AUTH=1 or unset it to enable auth routes.")

@app.route('/')
def index():
    """Serve login page by default"""
    return send_from_directory(str(FRONTEND_DIR), 'login.html')

@app.route('/login')
def login():
    """Serve login page"""
    return send_from_directory(str(FRONTEND_DIR), 'login.html')

@app.route('/signup')
def signup():
    """Serve signup page"""
    return send_from_directory(str(FRONTEND_DIR), 'signup.html')

@app.route('/account/delete')
def account_delete():
    """Serve official account deletion page."""
    return send_from_directory(str(FRONTEND_DIR), 'account-delete.html')

@app.route('/legal/terms')
def legal_terms():
    """Serve CleanHouse Terms of Service."""
    path = BASE_DIR / "docs" / "legal" / "CLEANHOUSE_TERMS_OF_SERVICE.md"
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/markdown; charset=utf-8"}

@app.route('/legal/privacy')
def legal_privacy():
    """Serve CleanHouse Privacy Notice."""
    path = BASE_DIR / "docs" / "legal" / "CLEANHOUSE_PRIVACY_NOTICE.md"
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/markdown; charset=utf-8"}

@app.route('/legal/eeccd')
def legal_eeccd():
    """Serve CleanHouse European Electronic Communications Code Disclosure."""
    path = BASE_DIR / "docs" / "legal" / "CLEANHOUSE_EUROPEAN_ELECTRONIC_COMMUNICATIONS_CODE_DISCLOSURE.md"
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/markdown; charset=utf-8"}

@app.route('/dashboard')
def dashboard():
    """Serve monitoring dashboard"""
    return send_from_directory(str(FRONTEND_DIR), 'dashboard.html')

@app.route('/investigations')
def investigations():
    """Serve investigation-first operator surface"""
    return send_from_directory(str(FRONTEND_DIR), 'investigations.html')

@app.route('/applications')
@app.route('/applications/<path:_app_id>')
@app.route('/network')
@app.route('/files')
@app.route('/custom-scan')
def app_security_center(_app_id=None):
    """Serve app-first security center routes"""
    return send_from_directory(str(FRONTEND_DIR), 'investigations.html')

@app.route('/incident-receipt')
def incident_receipt():
    """Serve standalone incident receipt card"""
    return send_from_directory(str(FRONTEND_DIR), 'incident-receipt.html')

@app.route('/css/<path:filename>')
def css(filename):
    """Serve CSS files"""
    return send_from_directory(str(FRONTEND_DIR / 'css'), filename)

@app.route('/js/<path:filename>')
def js(filename):
    """Serve JavaScript files"""
    return send_from_directory(str(FRONTEND_DIR / 'js'), filename)

@app.route('/assets/<path:filename>')
def assets(filename):
    """Serve asset files"""
    frontend_asset = FRONTEND_DIR / 'assets' / filename
    if frontend_asset.exists():
        return send_from_directory(str(FRONTEND_DIR / 'assets'), filename)
    return send_from_directory(str(BASE_DIR / 'assets'), filename)


_EVENTS_SERVICES_STARTED = False
_RUNTIME_HEARTBEAT_STARTED = False


def _cleanhouse_host():
    return os.environ.get('CLEANHOUSE_HOST', DEFAULT_HOST) or DEFAULT_HOST


def _start_runtime_heartbeat() -> None:
    global _RUNTIME_HEARTBEAT_STARTED
    if _RUNTIME_HEARTBEAT_STARTED:
        return
    _RUNTIME_HEARTBEAT_STARTED = True
    try:
        runtime_supervisor.start_backend_heartbeat(_cleanhouse_host(), _cleanhouse_port())
    except Exception as exc:
        logging.warning("cleanhouse runtime heartbeat not started: %s", exc)


def _start_events_services():
    global _EVENTS_SERVICES_STARTED
    _start_runtime_heartbeat()
    if _EVENTS_SERVICES_STARTED:
        return
    _EVENTS_SERVICES_STARTED = True
    try:
        cleanhouse_events.init_db()
        cleanhouse_events.start_watcher()
    except Exception as exc:
        logging.warning("cleanhouse event services not started: %s", exc)


def _stop_events_services() -> None:
    try:
        cleanhouse_events.stop_events_services()
    except Exception as exc:  # pragma: no cover
        logging.warning("cleanhouse event services not stopped cleanly: %s", exc)
    try:
        runtime_supervisor.stop_backend_heartbeat(_cleanhouse_host(), _cleanhouse_port())
    except Exception as exc:  # pragma: no cover
        logging.warning("cleanhouse runtime heartbeat not stopped cleanly: %s", exc)


atexit.register(_stop_events_services)


if hasattr(app, "before_serving"):
    app.before_serving(_start_events_services)
elif hasattr(app, "before_first_request"):
    app.before_first_request(_start_events_services)
else:
    @app.before_request
    def _legacy_start_events_services_once() -> None:
        _start_events_services()

if __name__ == '__main__':
    cleanhouse_events.init_db()
    _start_runtime_heartbeat()

    # Run on localhost for desktop wrapper
    app.run(
        host=_cleanhouse_host(),
        port=_cleanhouse_port(),
        debug=False,
        threaded=True,
    )
