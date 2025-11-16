"""
Flask server for CleanHouse frontend.
Serves static files and provides API endpoints.
"""

from flask import Flask, send_from_directory, jsonify, request, session
from flask_cors import CORS
from pathlib import Path
import sys
import os
import secrets
import logging

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

from backend.api import auth

app = Flask(__name__, static_folder=None)
app.secret_key = secrets.token_hex(32)  # Required for sessions

# Configure Flask sessions
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'cleanhouse:'
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

CORS(app)  # Enable CORS for all routes

# Get paths
BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Register API routes
app.register_blueprint(auth.bp, url_prefix='/api')

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
    return send_from_directory(str(FRONTEND_DIR / 'assets'), filename)

if __name__ == '__main__':
    # Run on localhost for desktop wrapper
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)

