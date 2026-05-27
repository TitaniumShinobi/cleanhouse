# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - simple_webview_auth.py
#  Simple WebView authentication with native autofill support
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox

# Optional webview import (for OAuth authentication)
# Defer import to avoid crashes on macOS version incompatibility
WEBVIEW_AVAILABLE = False
webview = None
_WEBVIEW_CHECKED = False

def _try_import_webview():
    """Lazy import of webview to avoid crashes on import."""
    global WEBVIEW_AVAILABLE, webview, _WEBVIEW_CHECKED
    if _WEBVIEW_CHECKED:
        return webview if WEBVIEW_AVAILABLE else None
    _WEBVIEW_CHECKED = True
    try:
        # Test import in a way that won't crash the process
        import webview
        # Test if webview actually works by checking for required functions
        if hasattr(webview, 'create_window') and hasattr(webview, 'start'):
            WEBVIEW_AVAILABLE = True
            return webview
        else:
            WEBVIEW_AVAILABLE = False
            webview = None
            return None
    except Exception as e:
        # Handle any import or runtime errors
        WEBVIEW_AVAILABLE = False
        webview = None
        # Don't log here as logging might not be initialized yet
        return None

import threading
import logging
import webbrowser
from models import UserService, DatabaseManager
import os
import platform
import time
import signal
import sys
import tempfile
from typing import Callable, Optional, Dict, Any
from pathlib import Path
import base64
import hashlib
import secrets
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Try to find and load .env file from CleanHouse directory
    base_dir = Path(__file__).parent.parent
    env_file = base_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logging.info(f"Loaded environment variables from {env_file}")
    else:
        # Try current directory as fallback
        load_dotenv()
        logging.debug("Attempted to load .env from current directory")
except ImportError:
    logging.warning("python-dotenv not installed. Environment variables must be set manually.")
# Removed aggressive focus management imports

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP server handler for OAuth callbacks."""

    def __init__(self, callback_queue, *args, **kwargs):
        self.callback_queue = callback_queue
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Handle OAuth callback GET request."""
        try:
            # Parse query parameters
            parsed_url = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed_url.query)

            # Extract code or error
            code = params.get('code', [None])[0]
            error = params.get('error', [None])[0]
            state = params.get('state', [None])[0]

            if error:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authentication Error</h1><p>Please close this window.</p></body></html>')
                self.callback_queue.put({'error': error, 'state': state})
            elif code:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Authentication Successful</h1><p>You can close this window.</p></body></html>')
                self.callback_queue.put({'code': code, 'state': state})
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html><body><h1>Invalid Request</h1><p>Please close this window.</p></body></html>')
        except Exception as e:
            logging.error(f"OAuth callback error: {e}")
            self.send_response(500)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

class SimpleWebViewAuth:
    """
    Simple WebView-based authentication with native autofill support.
    """

    def __init__(self, parent, on_success: Callable, on_signup: Optional[Callable] = None, base_dir: Optional[str] = None):
        logging.info("[UI] SimpleWebViewAuth.__init__() called")

        # Store parent reference for Tkinter callbacks
        self.parent = parent

        self.on_success = on_success
        self.on_signup = on_signup

        # Resolve base_dir properly - use CleanHouse directory, not current working directory
        if base_dir:
            self.base_dir = str(Path(base_dir).resolve())
            logging.info(f"[UI] Using provided base_dir: {self.base_dir}")
        else:
            # Try to find CleanHouse directory from common locations
            logging.info("[UI] Searching for CleanHouse directory...")
            possible_paths = [
                Path(__file__).parent.parent,  # ui/../ = cleanhouse/
                Path.cwd(),
                Path.home() / "Documents" / "GitHub" / "cleanhouse",
                Path.home() / "Documents" / "GitHub" / "CleanHouse",
            ]
            for path in possible_paths:
                if path.exists() and (path / "CLEANHOUSE_TERMS_OF_SERVICE.md").exists():
                    self.base_dir = str(path.resolve())
                    logging.info(f"[UI] Found CleanHouse directory: {self.base_dir}")
                    break
            else:
                # Fallback to current directory
                self.base_dir = str(Path.cwd().resolve())
                logging.warning(f"[UI] CleanHouse directory not found, using current directory: {self.base_dir}")

        self.auth_window = None
        self._pending_user_data = None  # Store user data during account creation
        self._auth_result_dispatched = False

        logging.info("[UI] Initializing database and user service...")
        # Initialize local database (CleanHouse's own user registry)
        self.db_manager = DatabaseManager()
        self.user_service = UserService(db_manager=self.db_manager)
        logging.info("[UI] Database and user service initialized")

        # OAuth callback server
        self._oauth_server = None
        self._oauth_server_thread = None
        self._oauth_callback_queue = None

        # Thread-safe queue for OAuth success callbacks
        import queue
        self._oauth_success_queue = queue.Queue()
        self._polling_oauth_success = False
        self._oauth_pkce_verifier = None
        self._oauth_state = None
        # Removed aggressive focus management

        logging.info("[UI] Setting up signal handlers...")
        # Set up signal handling for WebView auth (only in main thread)
        self._setup_signal_handlers()
        logging.info("[UI] SimpleWebViewAuth initialization complete")

    def _create_api_wrapper(self):
        """Create a minimal API wrapper to avoid serializing parent object with Path objects."""
        class APIWrapper:
            def __init__(self, auth_instance):
                self._auth = auth_instance

            def createAccount(self, full_name, email, password, role, turnstile_token=''):
                return self._auth.createAccount(full_name, email, password, role, turnstile_token)

            def showLogin(self):
                return self._auth.showLogin()

            def showSignup(self):
                return self._auth.showSignup()

            def showTerms(self):
                return self._auth.showTerms()

            def showPrivacy(self):
                return self._auth.showPrivacy()

            def showEECCD(self):
                return self._auth.showEECCD()

            def getTurnstileSiteKey(self):
                return self._auth.getTurnstileSiteKey()

            def openOAuthUrl(self, url, provider):
                return self._auth.openOAuthUrl(url, provider)

            def test_api(self):
                return self._auth.test_api()

            def log(self, message: str, level: str = "INFO"):
                """Log message from JavaScript to Python terminal."""
                log_level = getattr(logging, level.upper(), logging.INFO)
                # Simple format like Chatty - no emojis, just the message
                logging.log(log_level, f"[JS] {message}")
                return {"success": True}

            def log_click(self, element_type: str, details: str):
                """Log click event from JavaScript."""
                logging.info(f"[JS] [CLICK] {element_type}: {details}")
                return {"success": True}

            def log_input(self, field_name: str, field_type: str, char_count: int):
                """Log input field change from JavaScript."""
                logging.info(f"[JS] [INPUT] {field_type} field \"{field_name}\" changed ({char_count} chars)")
                return {"success": True}

            def log_focus(self, field_name: str):
                """Log field focus event from JavaScript."""
                logging.info(f"[JS] [FOCUS] Field \"{field_name}\" focused")
                return {"success": True}

            def log_blur(self, field_name: str):
                """Log field blur event from JavaScript."""
                logging.info(f"[JS] [BLUR] Field \"{field_name}\" blurred")
                return {"success": True}

        return APIWrapper(self)

    def _queue_auth_result(self, user_data: dict):
        """Store OAuth result so the main UI can consume it."""
        if not user_data:
            return
        self._pending_user_data = user_data
        try:
            self._oauth_success_queue.put_nowait(user_data)
        except Exception as exc:
            logging.debug(f"[OAUTH] Could not enqueue auth result: {exc}")

    def _close_auth_window_async(self):
        """Attempt to close the WebView window from any thread."""
        webview = _try_import_webview()
        if not WEBVIEW_AVAILABLE or webview is None or not self.auth_window:
            return
        try:
            if webview is not None and hasattr(webview, 'destroy_window'):
                webview.destroy_window(self.auth_window)  # type: ignore[attr-defined]
            elif hasattr(self.auth_window, 'destroy'):
                self.auth_window.destroy()
            else:
                logging.debug("[OAUTH] No supported method to close WebView window")
            self.auth_window = None
        except Exception as exc:
            logging.warning(f"[OAUTH] Failed to close WebView window: {exc}")

    def _handle_background_auth_success(self, user_data: dict):
        """Persist auth success and trigger the UI transition."""
        if not user_data:
            return
        self._queue_auth_result(user_data)
        logging.info("[OAUTH] Queued user data for main thread processing")
        self._close_auth_window_async()

    def _process_pending_auth_result(self):
        """Deliver any queued authentication result once WebView shuts down."""
        if self._auth_result_dispatched:
            return
        user_data = self._pending_user_data
        if not user_data:
            import queue
            try:
                user_data = self._oauth_success_queue.get_nowait()
            except queue.Empty:
                user_data = None
        if user_data:
            logging.info("[OAUTH] Delivering OAuth result after WebView closed")
            self._deliver_auth_result(user_data)
        else:
            logging.info("[OAUTH] No authentication result to deliver after WebView closed")

    def _deliver_auth_result(self, user_data: dict):
        """Invoke the success callback exactly once."""
        if not user_data or self._auth_result_dispatched:
            return
        try:
            if self.on_success:
                self.on_success(user_data)
                logging.info("[OAUTH] Success callback executed successfully")
        except Exception as exc:
            logging.error(f"[OAUTH] Error in success callback: {exc}", exc_info=True)
        finally:
            self._auth_result_dispatched = True
            self._pending_user_data = None
            try:
                self.cleanup()
            except Exception:
                pass

    def _setup_signal_handlers(self):
        """Set up signal handlers for WebView authentication (only in main thread)."""
        try:
            # Check if we're in the main thread
            import threading
            if threading.current_thread() is not threading.main_thread():
                logging.debug("Skipping signal handler setup - not in main thread")
                return

            def signal_handler(signum, frame):
                """Handle SIGINT (Ctrl+C) during WebView authentication."""
                print(f"\n🛑 CleanHouse WebView auth received signal {signum}, cleaning up...")
                logging.info(f"Received signal {signum} during WebView authentication")

                # Clean up WebView processes
                try:
                    self.cleanup()
                    self.force_cleanup()
                except Exception as e:
                    logging.error(f"Error during WebView auth cleanup: {e}")

                # Force exit
                print("CleanHouse WebView auth terminated.")
                sys.exit(0)

            # Set up signal handlers (only works in main thread)
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            logging.info("Signal handlers set up for WebView authentication")
        except ValueError as e:
            # Signal handlers can only be set in main thread
            logging.debug(f"Signal handler setup skipped: {e}")
        except Exception as e:
            logging.warning(f"Could not set up signal handlers: {e}")

    def show_login(self):
        """Show WebView-based login."""
        logging.info("[UI] show_login() called - initializing login window")

        # Try to import webview if not already checked
        webview = _try_import_webview()
        if not WEBVIEW_AVAILABLE or webview is None:
            # Fallback: skip auth if webview not available
            logging.warning("[UI] WebView not available - skipping authentication")
            messagebox.showwarning("WebView Unavailable",
                                 "WebView (pywebview) not installed.\n"
                                 "Install with: pip install pywebview\n\n"
                                 "For now, proceeding without authentication.")
            # Call success callback with default user to allow GUI to proceed
            if self.on_success:
                self.on_success({"email": "guest@localhost", "name": "Guest User"})
            return

        try:
            logging.info("[UI] Creating HTML login page...")
            # Create HTML login page
            html_content = self._create_login_html()
            logging.info(f"[UI] HTML login page created ({len(html_content)} characters)")

            logging.info("[UI] Creating API wrapper...")
            # Create a minimal API object to avoid serializing parent (which has Path objects)
            # We'll create a wrapper that only exposes the methods we need
            api_wrapper = self._create_api_wrapper()
            logging.info("[UI] API wrapper created successfully")

            logging.info("[UI] Creating WebView window (450x775px)...")
            # Show WebView window with API exposure
            # Dimensions: 450x775px
            self.auth_window = webview.create_window(
                title='CleanHouse - Sign In',
                html=html_content,
                width=450,
                height=775,
                resizable=True,
                min_size=(450, 550),
                js_api=api_wrapper
            )
            logging.info("[UI] WebView window created successfully")

            # Start OAuth success polling on main thread (before WebView starts)
            if not self._polling_oauth_success:
                self._start_oauth_success_polling()

            logging.info("[UI] Starting WebView...")
            # Start WebView with normal behavior (blocks until window closes)
            webview.start(
                self._handle_webview_events,
                debug=False,
                private_mode=False
            )
            logging.info("[UI] WebView closed - checking authentication result")
            self._process_pending_auth_result()

        except Exception as e:
            logging.error(f"[UI] WebView auth error: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to start WebView authentication: {e}")

    def show_signup(self):
        """Show WebView-based signup."""
        logging.info("[UI] show_signup() called - initializing signup window")

        # Try to import webview if not already checked
        webview = _try_import_webview()
        if not WEBVIEW_AVAILABLE or webview is None:
            # Fallback: skip auth if webview not available
            logging.warning("[UI] WebView not available - skipping signup")
            messagebox.showwarning("WebView Unavailable",
                                 "WebView (pywebview) not installed.\n"
                                 "Install with: pip install pywebview")
            return

        try:
            logging.info("[UI] Creating HTML signup page...")
            # Create HTML signup page
            html_content = self._create_signup_html()
            logging.info(f"[UI] HTML signup page created ({len(html_content)} characters)")

            logging.info("[UI] Creating API wrapper...")
            # Create a minimal API object to avoid serializing parent (which has Path objects)
            api_wrapper = self._create_api_wrapper()
            logging.info("[UI] API wrapper created successfully")

            logging.info("[UI] Creating WebView window (800x800px)...")
            # Show WebView window with API exposure
            # Dimensions: 800x800px (square layout for horizontal content spread)
            self.auth_window = webview.create_window(
                title='CleanHouse - Create Account',
                html=html_content,
                width=800,
                height=800,
                resizable=True,
                min_size=(600, 700),
                js_api=api_wrapper
            )
            logging.info("[UI] WebView window created successfully")

            # Start OAuth success polling on main thread (before WebView starts)
            if not self._polling_oauth_success:
                self._start_oauth_success_polling()

            logging.info("[UI] Starting WebView...")
            # Start WebView with normal behavior (blocks until window closes)
            webview.start(
                self._handle_webview_events,
                debug=False,
                private_mode=False
            )
            logging.info("[UI] WebView closed - checking authentication result")
            self._process_pending_auth_result()

        except Exception as e:
            logging.error(f"[UI] WebView signup error: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to start WebView signup: {e}")

    def _create_login_html(self) -> str:
        """Create HTML login page with native autofill support."""
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>CleanHouse - Sign In</title>
            <style>
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }

                html, body {
                    height: 100%;
                    overflow: hidden;
                    margin: 0;
                    padding: 0;
                }

                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                    box-sizing: border-box;
                }

                .login-container {
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    padding: 40px;
                    width: 100%;
                    max-width: 400px;
                    overflow-y: auto;
                    max-height: calc(100vh - 40px);
                    box-sizing: border-box;
                }

                .logo {
                    text-align: center;
                    margin-bottom: 30px;
                }

                .logo h1 {
                    color: #2c3e50;
                    font-size: 28px;
                    font-weight: 700;
                    margin-bottom: 8px;
                }

                .logo p {
                    color: #7f8c8d;
                    font-size: 14px;
                }

                .form-group {
                    margin-bottom: 20px;
                }

                .form-group label {
                    display: block;
                    margin-bottom: 8px;
                    color: #2c3e50;
                    font-weight: 500;
                    font-size: 14px;
                }

                .form-group input {
                    width: 100%;
                    padding: 12px 16px;
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    font-size: 16px;
                    transition: all 0.3s ease;
                    background: #f8f9fa;
                }

                .form-group input:focus {
                    outline: none;
                    border-color: #667eea;
                    background: white;
                    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
                }

                .password-container {
                    position: relative;
                }

                .password-toggle {
                    position: absolute;
                    right: 12px;
                    top: 50%;
                    transform: translateY(-50%);
                    background: none;
                    border: none;
                    cursor: pointer;
                    font-size: 18px;
                    color: #7f8c8d;
                }

                .login-btn {
                    width: 100%;
                    padding: 14px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    margin-bottom: 20px;
                }

                .login-btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
                }

                .login-btn:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                    transform: none;
                }

                .divider {
                    text-align: center;
                    margin: 20px 0;
                    color: #7f8c8d;
                    font-size: 14px;
                    position: relative;
                }

                .divider::before {
                    content: '';
                    position: absolute;
                    top: 50%;
                    left: 0;
                    right: 0;
                    height: 1px;
                    background: #e1e8ed;
                    z-index: 1;
                }

                .divider span {
                    background: white;
                    padding: 0 20px;
                    position: relative;
                    z-index: 2;
                }

                .oauth-btn {
                    width: 100%;
                    padding: 8px 16px;
                    border: 2px solid #000000;
                    border-radius: 9999px;
                    background: #000000;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    margin-bottom: 2px;
                    box-sizing: border-box;
                    outline: none;
                }

                .oauth-btn:last-child {
                    margin-bottom: 0;
                }

                .oauth-btn:hover:not(:disabled) {
                    background: #1a1a1a;
                    border-color: #000000;
                }

                .oauth-btn:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                    background: #f5f5f5;
                    border-color: #e0e0e0;
                    color: #999;
                }

                .oauth-btn svg {
                    width: 20px;
                    height: 20px;
                    flex-shrink: 0;
                }

                /* Microsoft button specific styling */
                .oauth-btn.microsoft {
                    border-color: #0078d4;
                    background: #0078d4;
                }

                .oauth-btn.microsoft:hover:not(:disabled) {
                    background: #0078d4;
                    border-color: #0078d4;
                }

                /* Apple button specific styling */
                .oauth-btn.apple {
                    border-color: #000000;
                    background: #000000;
                }

                .oauth-btn.apple:hover:not(:disabled) {
                    background: #000000;
                    border-color: #000000;
                }

                /* GitHub button specific styling */
                .oauth-btn.github {
                    border-color: #24292e;
                    background: #24292e;
                }

                .oauth-btn.github:hover:not(:disabled) {
                    background: #24292e;
                    border-color: #24292e;
                }

                #oauth-section {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    width: 100%;
                    align-items: stretch;
                }

                #oauth-section .oauth-btn {
                    width: 100%;
                    flex-shrink: 0;
                }

                #oauth-section .oauth-btn:last-child {
                    margin-bottom: 0;
                }

                #oauth-section p {
                    text-align: center;
                    color: #999;
                    font-size: 12px;
                    margin-top: 8px;
                    margin-bottom: 0;
                }

                .divider {
                    display: flex;
                    align-items: center;
                    text-align: center;
                    margin: 20px 0;
                }

                .divider::before,
                .divider::after {
                    content: '';
                    flex: 1;
                    border-bottom: 1px solid #e1e8ed;
                }

                .divider span {
                    padding: 0 10px;
                    color: #999;
                    font-size: 14px;
                }

                .signup-link {
                    text-align: center;
                    margin-top: 20px;
                }

                .signup-link a {
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 500;
                }

                .signup-link a:hover {
                    text-decoration: underline;
                }

                .error-message {
                    background: #fee;
                    color: #c33;
                    padding: 12px;
                    border-radius: 6px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                }

                .success-message {
                    background: #efe;
                    color: #3c3;
                    padding: 12px;
                    border-radius: 6px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                }

                .loading {
                    display: none;
                    text-align: center;
                    color: #7f8c8d;
                    font-size: 14px;
                }

                .loading-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.5);
                    display: none;
                    align-items: center;
                    justify-content: center;
                    z-index: 1000;
                }

                .loading-content {
                    background: white;
                    padding: 30px;
                    border-radius: 12px;
                    text-align: center;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.3);
                }

                .spinner {
                    display: inline-block;
                    width: 16px;
                    height: 16px;
                    border: 2px solid #e1e8ed;
                    border-top: 2px solid #667eea;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                    margin-right: 8px;
                }

                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        </head>
        <body>
            <div class="login-container">
                <div class="logo">
                    <h1>🏠 CleanHouse</h1>
                    <p>Security & File Management</p>
                </div>

                <div id="error-message" class="error-message"></div>
                <div id="success-message" class="success-message"></div>
                <div id="loading" class="loading">
                    <div class="spinner"></div>
                    Signing in...
                </div>

                <div id="loading-overlay" class="loading-overlay">
                    <div class="loading-content">
                        <div class="spinner"></div>
                        <p>Processing OAuth...</p>
                        <p style="font-size: 12px; color: #7f8c8d; margin-top: 10px;">
                            Please complete authentication in the popup window
                        </p>
                    </div>
                </div>

                <form id="login-form">
                    <div class="form-group">
                        <label for="email">Email Address</label>
                        <input
                            type="email"
                            id="email"
                            name="email"
                            autocomplete="email"
                            placeholder="Enter your email"
                            required
                        >
                    </div>

                    <div class="form-group">
                        <label for="password">Password</label>
                        <div class="password-container">
                            <input
                                type="password"
                                id="password"
                                name="password"
                                autocomplete="current-password"
                                placeholder="Enter your password"
                                required
                            >
                            <button type="button" class="password-toggle" onclick="togglePassword()">👁️</button>
                        </div>
                    </div>

                    <button type="submit" class="login-btn" id="login-btn">
                        Sign In
                    </button>
                </form>

                <div class="divider">
                    <span>or</span>
                </div>

                <button class="oauth-btn" onclick="signInWithGoogle()">
                    <svg viewBox="0 0 24 24">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Continue with Google
                </button>

                <button class="oauth-btn microsoft" onclick="signInWithMicrosoft()">
                    <svg viewBox="0 0 24 24">
                        <path fill="#ffffff" d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zM24 11.4H12.6V0H24v11.4z"/>
                    </svg>
                    Continue with Microsoft
                </button>

                <button class="oauth-btn apple" onclick="signInWithApple()">
                    <svg viewBox="0 0 24 24">
                        <path fill="#ffffff" d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/>
                    </svg>
                    Continue with Apple
                </button>

                <button class="oauth-btn github" onclick="signInWithGithub()">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                    </svg>
                    Continue with GitHub
                </button>

                <div class="signup-link">
                    <a href="#" onclick="showSignup(event); return false;">Don't have an account? Create Account</a>
                </div>

                <div style="text-align: center; margin-top: 10px;">
                    <button onclick="testAPI()" style="background: #f0f0f0; border: 1px solid #ccc; padding: 5px 10px; border-radius: 4px; font-size: 12px;">
                        Test API Connection
                    </button>
                </div>
            </div>

            <script>
                // Debug: Log script loading
                console.log('[CLEANHOUSE] Script loaded');
                console.log('[CLEANHOUSE] window.pywebview:', typeof window.pywebview !== 'undefined' ? 'exists' : 'undefined');
                console.log('[CLEANHOUSE] window.pywebview.api:', typeof window.pywebview?.api !== 'undefined' ? 'exists' : 'undefined');

                // Global logging helpers - check for pywebview API availability
                function hasAPI() {
                    const has = typeof window !== 'undefined' &&
                           window.pywebview &&
                           window.pywebview.api;
                    if (!has) {
                        console.warn('[CLEANHOUSE] API not available - window.pywebview:', typeof window.pywebview, 'api:', typeof window.pywebview?.api);
                    }
                    return has;
                }

                // Function to attach click listeners (called when API is ready)
                function attachClickListeners() {
                    console.log('[CLEANHOUSE] Attaching click listeners...');

                    // Log ALL clicks on the page
                    document.addEventListener('click', function(e) {
                        if (!hasAPI()) {
                            console.warn('[CLEANHOUSE] Click detected but API not available');
                            return;
                        }

                        console.log('[CLEANHOUSE] Click captured:', e.target.tagName, e.target.id || e.target.className);

                        const target = e.target;
                        let elementType = '';
                        let details = '';

                        // Identify what was clicked
                        if (target.tagName === 'BUTTON') {
                            elementType = 'button';
                            const buttonText = target.textContent.trim() || target.innerText.trim() || 'Button';
                            details = `"${buttonText.substring(0, 50)}"`;
                            if (target.id) details += ` (id: ${target.id})`;
                        } else if (target.tagName === 'A') {
                            elementType = 'link';
                            const linkText = target.textContent.trim() || target.innerText.trim() || 'Link';
                            details = `"${linkText.substring(0, 50)}"`;
                        } else if (target.tagName === 'INPUT') {
                            elementType = 'input';
                            const inputName = target.name || target.id || 'unnamed';
                            details = `${target.type || 'text'} (name: ${inputName})`;
                        } else {
                            elementType = 'element';
                            details = target.tagName.toLowerCase();
                            if (target.id) details += ` (id: ${target.id})`;
                            if (target.className) details += ` (class: ${target.className.split(' ')[0]})`;
                        }

                        try {
                            window.pywebview.api.log_click(elementType, details);
                            console.log('[CLEANHOUSE] Click logged successfully:', elementType, details);
                        } catch (err) {
                            console.error('[CLEANHOUSE] Error logging click:', err);
                            // Fallback to generic log if specific method not available
                            try {
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[CLICK] ${elementType}: ${details}`);
                                }
                            } catch (err2) {
                                console.error('[CLEANHOUSE] Fallback log also failed:', err2);
                            }
                        }
                    }, true); // Use capture phase to catch all clicks

                    console.log('[CLEANHOUSE] Click listeners attached');
                }

                // Wait for pywebview to be ready, then attach listeners
                if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                    // API already available, attach immediately
                    console.log('[CLEANHOUSE] API already available, attaching listeners');
                    attachClickListeners();
                } else {
                    // Wait for pywebview ready event
                    console.log('[CLEANHOUSE] Waiting for pywebview ready...');
                    window.addEventListener('pywebviewready', function() {
                        console.log('[CLEANHOUSE] pywebview ready event fired');
                        attachClickListeners();
                    });

                    // Also try polling as fallback (some versions don't fire the event)
                    let pollCount = 0;
                    const pollInterval = setInterval(function() {
                        pollCount++;
                        if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                            console.log('[CLEANHOUSE] API available via polling (attempt', pollCount, ')');
                            clearInterval(pollInterval);
                            attachClickListeners();
                        } else if (pollCount > 50) {
                            // Give up after 5 seconds (50 * 100ms)
                            console.error('[CLEANHOUSE] API not available after 5 seconds, giving up');
                            clearInterval(pollInterval);
                        }
                    }, 100);
                }

                // Log input field changes (don't log password values)
                document.addEventListener('input', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';
                        const fieldType = target.type || 'text';
                        // Don't log password values, only length
                        const charCount = target.value ? target.value.length : 0;

                        try {
                            window.pywebview.api.log_input(fieldName, fieldType, charCount);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
                            }
                        }
                    }
                }, true);

                // Log input focus
                document.addEventListener('focus', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';

                        try {
                            window.pywebview.api.log_focus(fieldName);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[FOCUS] Field "${fieldName}" focused`);
                            }
                        }
                    }
                }, true);

                // Log input blur
                document.addEventListener('blur', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';

                        try {
                            window.pywebview.api.log_blur(fieldName);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[BLUR] Field "${fieldName}" blurred`);
                            }
                        }
                    }
                }, true);

                // Password toggle functionality
                function togglePassword() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Password toggle"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Password toggle button clicked');
                            }
                        }
                    }
                    const passwordInput = document.getElementById('password');
                    const toggle = document.querySelector('.password-toggle');

                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggle.textContent = '🙈';
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: SHOWN');
                        }
                    } else {
                        passwordInput.type = 'password';
                        toggle.textContent = '👁️';
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: HIDDEN');
                        }
                    }
                }

                // Form submission
                document.getElementById('login-form').addEventListener('submit', function(e) {
                    e.preventDefault();
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Sign In" (form submit)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Login form submit button clicked');
                            }
                        }
                    }

                    const email = document.getElementById('email').value;
                    const password = document.getElementById('password').value;

                    if (!email || !password) {
                        showError('Please fill in all fields.');
                        return;
                    }

                    showLoading(true);

                    // Simulate login (replace with actual authentication)
                    setTimeout(() => {
                        if (email === 'admin@cleanhouse.local' && password === 'admin123') {
                            showSuccess('Login successful!');
                            setTimeout(() => {
                                // Close the WebView window
                                window.close();
                            }, 1000);
                        } else {
                            showError('Invalid email or password. Try admin@cleanhouse.local / admin123');
                        }
                        showLoading(false);
                    }, 1000);
                });

                // OAuth functions - use system browser with full OAuth flow
                function signInWithGoogle() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Google"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Google OAuth button clicked');
                            }
                        }
                    }
                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            console.log('[OAUTH] Calling openOAuthUrl for Google...');
                            const result = window.pywebview.api.openOAuthUrl(null, 'google');
                            console.log('[OAUTH] Result received:', result);

                            if (result) {
                                if (result.success === true) {
                                    // Success - browser opened
                                    const message = result.message || 'Opening Google authentication in your browser. Please complete the sign-in there.';
                                    console.log('[OAUTH] Success:', message);
                                    showSuccess(message);

                                    if (result.user) {
                                        // Already authenticated (shouldn't happen, but handle it)
                                        setTimeout(() => {
                                            window.close();
                                        }, 1500);
                                    }
                                } else {
                                    // Error returned
                                    const errorMsg = result.message || 'Failed to open Google authentication.';
                                    console.error('[OAUTH] Error from API:', errorMsg);
                                    showError(errorMsg);
                                    showOAuthLoading(false);
                                }
                            } else {
                                // No result returned (shouldn't happen)
                                console.error('[OAUTH] No result returned from API');
                                showError('Failed to open Google authentication. No response from server.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            console.error('[OAUTH] Exception:', error);
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        console.error('[OAUTH] API not available');
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithApple() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Apple"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Apple OAuth button clicked');
                            }
                        }
                    }
                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'apple');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Apple!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening Apple authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening Apple authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Apple authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithGithub() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with GitHub"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] GitHub OAuth button clicked');
                            }
                        }
                    }
                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'github');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with GitHub!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening GitHub authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening GitHub authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open GitHub authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithMicrosoft() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Microsoft"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Microsoft OAuth button clicked');
                            }
                        }
                    }
                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'microsoft');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Microsoft!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening Microsoft authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening Microsoft authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Microsoft authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function showSignup(event) {
                    // Log the click immediately - try multiple methods
                    let logged = false;
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Create Account" (from login)');
                            logged = true;
                        } catch (err) {
                            console.error('Failed to log click via log_click:', err);
                            try {
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log('[CLICK] "Create Account" link clicked (from login)');
                                    logged = true;
                                }
                            } catch (err2) {
                                console.error('Failed to log click via log:', err2);
                            }
                        }
                    }

                    if (!logged) {
                        console.warn('Could not log click - API not available or error occurred');
                    }

                    // Prevent default link behavior (scrolling to top)
                    if (event) {
                        event.preventDefault();
                    }

                    console.log('showSignup() called');
                    console.log('window.pywebview:', window.pywebview);

                    // Close current window and show signup
                    // This will trigger the parent to show the signup WebView
                    if (window.pywebview && window.pywebview.api) {
                        console.log('Calling window.pywebview.api.showSignup()');
                        window.pywebview.api.showSignup();
                    } else {
                        console.error('window.pywebview.api not available');
                        alert('API not available - this is a bug in the WebView setup');
                    }
                    // Don't close window immediately - let the API handle it
                    return false;
                }

                // UI helper functions
                function showError(message) {
                    const errorDiv = document.getElementById('error-message');
                    errorDiv.textContent = message;
                    errorDiv.style.display = 'block';
                    document.getElementById('success-message').style.display = 'none';
                }

                function showSuccess(message) {
                    const successDiv = document.getElementById('success-message');
                    successDiv.textContent = message;
                    successDiv.style.display = 'block';
                    document.getElementById('error-message').style.display = 'none';
                }

                function showLoading(show) {
                    const loadingDiv = document.getElementById('loading');
                    const loginBtn = document.getElementById('login-btn');

                    if (show) {
                        loadingDiv.style.display = 'block';
                        loginBtn.disabled = true;
                        loginBtn.textContent = 'Signing in...';
                    } else {
                        loadingDiv.style.display = 'none';
                        loginBtn.disabled = false;
                        loginBtn.textContent = 'Sign In';
                    }
                }

                function showOAuthLoading(show) {
                    const overlay = document.getElementById('loading-overlay');
                    if (show) {
                        overlay.style.display = 'flex';
                    } else {
                        overlay.style.display = 'none';
                    }
                }

                function handleOAuthTimeout() {
                    showOAuthLoading(false);
                    showError('OAuth timeout. Please try again.');
                }

                // Test API function
                function testAPI() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Test API Connection"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Test API Connection" button clicked');
                            }
                        }
                    }
                    console.log('Testing API connection...');
                    console.log('window.pywebview:', window.pywebview);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.test_api();
                            console.log('API test result:', result);
                            alert('API is working! Check console for details.');
                        } catch (error) {
                            console.error('API test failed:', error);
                            alert('API test failed: ' + error.message);
                        }
                    } else {
                        console.error('window.pywebview.api not available');
                        alert('API not available - WebView setup issue');
                    }
                }

                // Focus first input
                document.getElementById('email').focus();
            </script>
        </body>
        </html>
        """

    def _create_signup_html(self) -> str:
        """Create HTML signup page with CleanHouse design."""
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>CleanHouse - Create Account</title>
            <style>
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }

                html, body {
                    height: 100%;
                    overflow: hidden;
                    margin: 0;
                    padding: 0;
                }

                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                    color: #333;
                    box-sizing: border-box;
                }

                .signup-container {
                    background: white;
                    border-radius: 16px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1), 0 0 0 1px rgba(0,0,0,0.05);
                    padding: 40px;
                    width: 100%;
                    max-width: 720px;
                    position: relative;
                    overflow-y: auto;
                    max-height: calc(100vh - 40px);
                    box-sizing: border-box;
                }

                .signup-content {
                    display: grid;
                    grid-template-columns: 1fr 1px 1fr;
                    gap: 30px;
                    align-items: start;
                }

                .signup-left {
                    display: flex;
                    flex-direction: column;
                }

                .signup-right {
                    display: flex;
                    flex-direction: column;
                    align-items: stretch;
                    justify-content: flex-start;
                    padding-top: 0;
                }

                .vertical-divider {
                    width: 1px;
                    background: #e1e8ed;
                    height: 100%;
                    min-height: 400px;
                }

                .form-row {
                    display: flex;
                    flex-direction: column;
                    gap: 0;
                    margin-bottom: 20px;
                }

                .form-row.full-width {
                    display: flex;
                    flex-direction: column;
                }

                .signup-container::before {
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    right: 0;
                    height: 4px;
                    background: linear-gradient(90deg, #667eea, #764ba2);
                }

                .header {
                    text-align: center;
                    margin-bottom: 32px;
                }

                .logo {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 16px;
                }

                .logo-icon {
                    width: 48px;
                    height: 48px;
                    background: linear-gradient(135deg, #667eea, #764ba2);
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 24px;
                    color: white;
                    margin-right: 12px;
                }

                .logo-text {
                    font-size: 28px;
                    font-weight: 700;
                    color: #1a1a1a;
                }

                .subtitle {
                    color: #666;
                    font-size: 16px;
                    font-weight: 400;
                }

                .form-group {
                    margin-bottom: 20px;
                }

                .form-group label {
                    display: block;
                    margin-bottom: 8px;
                    color: #333;
                    font-weight: 500;
                    font-size: 14px;
                }

                .form-group input, .form-group select {
                    width: 100%;
                    padding: 14px 16px;
                    border: 2px solid #e1e5e9;
                    border-radius: 12px;
                    font-size: 16px;
                    transition: all 0.3s ease;
                    background: #f8f9fa;
                    font-family: inherit;
                }

                .form-group input:focus, .form-group select:focus {
                    outline: none;
                    border-color: #667eea;
                    background: white;
                    box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
                }

                .form-group input.error {
                    border-color: #e74c3c;
                    background: #fdf2f2;
                }

                .password-container {
                    position: relative;
                }

                .password-toggle {
                    position: absolute;
                    right: 16px;
                    top: 50%;
                    transform: translateY(-50%);
                    background: none;
                    border: none;
                    color: #666;
                    cursor: pointer;
                    font-size: 18px;
                    padding: 4px;
                }

                .password-toggle:hover {
                    color: #333;
                }

                .password-requirements {
                    font-size: 12px;
                    color: #666;
                    margin-top: 6px;
                    line-height: 1.4;
                }

                .checkbox-group {
                    display: flex;
                    align-items: flex-start;
                    margin-bottom: 24px;
                }

                .checkbox-group input[type="checkbox"] {
                    width: 18px;
                    height: 18px;
                    margin-right: 12px;
                    margin-top: 2px;
                    accent-color: #667eea;
                }

                .checkbox-group label {
                    font-size: 14px;
                    color: #666;
                    line-height: 1.4;
                    cursor: pointer;
                }

                .checkbox-group a {
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 500;
                }

                .checkbox-group a:hover {
                    text-decoration: underline;
                }

                .signup-button {
                    width: 100%;
                    padding: 16px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    margin-bottom: 24px;
                    font-family: inherit;
                    box-sizing: border-box;
                }

                .signup-right .checkbox-group {
                    margin-bottom: 20px;
                }

                .signup-right .signup-button {
                    margin-bottom: 24px;
                }

                .signup-button:hover:not(:disabled) {
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
                }

                .signup-button:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                    transform: none;
                }

                .login-link {
                    text-align: center;
                    color: #666;
                    font-size: 14px;
                }

                .login-link a {
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 500;
                }

                .login-link a:hover {
                    text-decoration: underline;
                }

                .error-message {
                    background: #fdf2f2;
                    color: #e74c3c;
                    padding: 12px 16px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                    border: 1px solid #fecaca;
                }

                .success-message {
                    background: #f0f9ff;
                    color: #0369a1;
                    padding: 12px 16px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                    border: 1px solid #bae6fd;
                }

                .loading {
                    display: none;
                    text-align: center;
                    color: #666;
                    font-size: 14px;
                    margin-top: 10px;
                }

                .loading.show {
                    display: block;
                }

                .spinner {
                    display: inline-block;
                    width: 20px;
                    height: 20px;
                    border: 2px solid #f3f3f3;
                    border-top: 2px solid #667eea;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                    margin-right: 8px;
                }

                @keyframes spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }

                .oauth-btn {
                    width: 100%;
                    padding: 8px 16px;
                    border: 2px solid #000000;
                    border-radius: 9999px;
                    background: #000000;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    margin-bottom: 2px;
                    box-sizing: border-box;
                    outline: none;
                }

                .oauth-btn:last-child {
                    margin-bottom: 0;
                }

                .oauth-btn:hover:not(:disabled) {
                    background: #1a1a1a;
                    border-color: #000000;
                }

                .oauth-btn:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                    background: #f5f5f5;
                    border-color: #e0e0e0;
                    color: #999;
                }

                .oauth-btn svg {
                    width: 20px;
                    height: 20px;
                    flex-shrink: 0;
                }

                /* Microsoft button specific styling */
                .oauth-btn.microsoft {
                    border-color: #0078d4;
                    background: #0078d4;
                }

                .oauth-btn.microsoft:hover:not(:disabled) {
                    background: #0078d4;
                    border-color: #0078d4;
                }

                /* Apple button specific styling */
                .oauth-btn.apple {
                    border-color: #000000;
                    background: #000000;
                }

                .oauth-btn.apple:hover:not(:disabled) {
                    background: #000000;
                    border-color: #000000;
                }

                /* GitHub button specific styling */
                .oauth-btn.github {
                    border-color: #24292e;
                    background: #24292e;
                }

                .oauth-btn.github:hover:not(:disabled) {
                    background: #24292e;
                    border-color: #24292e;
                }

                #oauth-section {
                    display: flex;
                    flex-direction: column;
                    gap: 1px;
                    width: 100%;
                    align-items: stretch;
                }

                #oauth-section .oauth-btn {
                    width: 100%;
                    flex-shrink: 0;
                }

                #oauth-section .oauth-btn:last-child {
                    margin-bottom: 0;
                }

                #oauth-section p {
                    text-align: center;
                    color: #999;
                    font-size: 12px;
                    margin-top: 8px;
                    margin-bottom: 0;
                }
            </style>
        </head>
        <body>
            <div class="signup-container">
                <div class="header">
                    <div class="logo">
                        <div class="logo-icon">🏠</div>
                        <div class="logo-text">CleanHouse</div>
                    </div>
                    <p class="subtitle">Create your account to get started</p>
                </div>

                <div class="error-message" id="errorMessage"></div>
                <div class="success-message" id="successMessage"></div>
                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    Creating your account...
                </div>

                <div class="signup-content">
                    <div class="signup-left">
                        <form id="signupForm">
                            <div class="form-group">
                                <label for="fullName">Full Name</label>
                                <input type="text" id="fullName" name="fullName" required autocomplete="name" placeholder="Enter your full name">
                            </div>

                            <div class="form-group">
                                <label for="email">Email Address</label>
                                <input type="email" id="email" name="email" required autocomplete="email" placeholder="Enter your email address">
                            </div>

                            <div class="form-group">
                                <label for="password">Password</label>
                                <div class="password-container">
                                    <input type="password" id="password" name="password" required autocomplete="new-password" placeholder="Create a strong password">
                                    <button type="button" class="password-toggle" onclick="togglePassword()">👁️</button>
                                </div>
                                <div class="password-requirements">
                                    Must be at least 8 characters long
                                </div>
                            </div>

                            <div class="form-group">
                                <label for="confirmPassword">Confirm Password</label>
                                <input type="password" id="confirmPassword" name="confirmPassword" required autocomplete="new-password" placeholder="Confirm your password">
                            </div>

                            <div class="form-group">
                                <label for="role">Role</label>
                                <select id="role" name="role" required>
                                    <option value="">Select your role</option>
                                    <option value="user">User</option>
                                    <option value="dev">Developer</option>
                                </select>
                            </div>
                        </form>
                    </div>

                    <div class="vertical-divider"></div>

                    <div class="signup-right">
                        <div class="checkbox-group">
                            <input type="checkbox" id="terms" name="terms" required>
                            <label for="terms">
                                By continuing, I confirm I understand and agree to the
                                <a href="#" onclick="showTerms(event); return false;"> CleanHouse Terms of Service</a>
                                and the
                                <a href="#" onclick="showPrivacy(event); return false;"> CleanHouse Privacy Notice</a>.
                                If I am in the EEA or UK, I have read and agree to the
                                <a href="#" onclick="showEECCD(event); return false;"> European Electronic Communications Code Disclosure</a>.
                            </label>
                        </div>

                        <button type="submit" class="signup-button" id="signupButton" form="signupForm">
                            Create Account
                        </button>

                        <div id="oauth-section">
                            <button class="oauth-btn" id="oauth-google" onclick="signInWithGoogle()" disabled>
                                <svg viewBox="0 0 24 24">
                                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                                </svg>
                                Continue with Google
                            </button>

                            <button class="oauth-btn microsoft" id="oauth-microsoft" onclick="signInWithMicrosoft()" disabled>
                                <svg viewBox="0 0 24 24">
                                    <path fill="#ffffff" d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zM24 11.4H12.6V0H24v11.4z"/>
                                </svg>
                                Continue with Microsoft
                            </button>

                            <button class="oauth-btn apple" id="oauth-apple" onclick="signInWithApple()" disabled>
                                <svg viewBox="0 0 24 24">
                                    <path fill="#ffffff" d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/>
                                </svg>
                                Continue with Apple
                            </button>

                            <button class="oauth-btn github" id="oauth-github" onclick="signInWithGithub()" disabled>
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                                </svg>
                                Continue with GitHub
                            </button>

                            <p style="text-align: center; color: #999; font-size: 12px; margin-top: 12px;">
                                Complete the form above to enable OAuth signup
                            </p>
                        </div>
                    </div>
                </div>

                <div class="login-link">
                    Already have an account? <a href="#" onclick="showLogin(event); return false;">Sign in</a>
                </div>
            </div>

            <script>
                // Debug: Log script loading
                console.log('[CLEANHOUSE SIGNUP] Script loaded');
                console.log('[CLEANHOUSE SIGNUP] window.pywebview:', typeof window.pywebview !== 'undefined' ? 'exists' : 'undefined');
                console.log('[CLEANHOUSE SIGNUP] window.pywebview.api:', typeof window.pywebview?.api !== 'undefined' ? 'exists' : 'undefined');

                // Global logging helpers - check for pywebview API availability
                function hasAPI() {
                    const has = typeof window !== 'undefined' &&
                           window.pywebview &&
                           window.pywebview.api;
                    if (!has) {
                        console.warn('[CLEANHOUSE SIGNUP] API not available');
                    }
                    return has;
                }

                const form = document.getElementById('signupForm');
                const errorMessage = document.getElementById('errorMessage');
                const successMessage = document.getElementById('successMessage');
                const loading = document.getElementById('loading');
                const signupButton = document.getElementById('signupButton');

                // OAuth buttons
                const oauthGoogle = document.getElementById('oauth-google');
                const oauthMicrosoft = document.getElementById('oauth-microsoft');
                const oauthApple = document.getElementById('oauth-apple');
                const oauthGithub = document.getElementById('oauth-github');
                const termsCheckbox = document.getElementById('terms');

                // Function to attach click listeners (called when API is ready)
                function attachClickListeners() {
                    console.log('[CLEANHOUSE SIGNUP] Attaching click listeners...');

                    // Log ALL clicks on the page
                    document.addEventListener('click', function(e) {
                        if (!hasAPI()) {
                            console.warn('[CLEANHOUSE SIGNUP] Click detected but API not available');
                            return;
                        }

                        console.log('[CLEANHOUSE SIGNUP] Click captured:', e.target.tagName, e.target.id || e.target.className);

                        const target = e.target;
                        let elementType = '';
                        let details = '';

                        // Identify what was clicked
                        if (target.tagName === 'BUTTON') {
                            elementType = 'button';
                            const buttonText = target.textContent.trim() || target.innerText.trim() || 'Button';
                            details = `"${buttonText.substring(0, 50)}"`;
                            if (target.id) details += ` (id: ${target.id})`;
                        } else if (target.tagName === 'A') {
                            elementType = 'link';
                            const linkText = target.textContent.trim() || target.innerText.trim() || 'Link';
                            details = `"${linkText.substring(0, 50)}"`;
                        } else if (target.tagName === 'INPUT') {
                            elementType = 'input';
                            const inputName = target.name || target.id || 'unnamed';
                            details = `${target.type || 'text'} (name: ${inputName})`;
                        } else {
                            elementType = 'element';
                            details = target.tagName.toLowerCase();
                            if (target.id) details += ` (id: ${target.id})`;
                            if (target.className) details += ` (class: ${target.className.split(' ')[0]})`;
                        }

                        try {
                            window.pywebview.api.log_click(elementType, details);
                            console.log('[CLEANHOUSE SIGNUP] Click logged successfully:', elementType, details);
                        } catch (err) {
                            console.error('[CLEANHOUSE SIGNUP] Error logging click:', err);
                            // Fallback to generic log if specific method not available
                            try {
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[CLICK] ${elementType}: ${details}`);
                                }
                            } catch (err2) {
                                console.error('[CLEANHOUSE SIGNUP] Fallback log also failed:', err2);
                            }
                        }
                    }, true); // Use capture phase to catch all clicks

                    console.log('[CLEANHOUSE SIGNUP] Click listeners attached');
                }

                // Wait for pywebview to be ready, then attach listeners
                if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                    // API already available, attach immediately
                    console.log('[CLEANHOUSE SIGNUP] API already available, attaching listeners');
                    attachClickListeners();
                } else {
                    // Wait for pywebview ready event
                    console.log('[CLEANHOUSE SIGNUP] Waiting for pywebview ready...');
                    window.addEventListener('pywebviewready', function() {
                        console.log('[CLEANHOUSE SIGNUP] pywebview ready event fired');
                        attachClickListeners();
                    });

                    // Also try polling as fallback (some versions don't fire the event)
                    let pollCount = 0;
                    const pollInterval = setInterval(function() {
                        pollCount++;
                        if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                            console.log('[CLEANHOUSE SIGNUP] API available via polling (attempt', pollCount, ')');
                            clearInterval(pollInterval);
                            attachClickListeners();
                        } else if (pollCount > 50) {
                            // Give up after 5 seconds (50 * 100ms)
                            console.error('[CLEANHOUSE SIGNUP] API not available after 5 seconds, giving up');
                            clearInterval(pollInterval);
                        }
                    }, 100);
                }

                // Function to attach input/focus/blur listeners
                function attachInputListeners() {
                    // Log input field changes (don't log password values)
                    document.addEventListener('input', function(e) {
                        if (!hasAPI()) return;

                        const target = e.target;
                        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                            const fieldName = target.name || target.id || 'unnamed';
                            const fieldType = target.type || 'text';
                            // Don't log password values, only length
                            const charCount = target.value ? target.value.length : 0;

                            try {
                                window.pywebview.api.log_input(fieldName, fieldType, charCount);
                            } catch (err) {
                                // Fallback to generic log
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
                                }
                            }
                        }
                    }, true);

                    // Log input focus
                    document.addEventListener('focus', function(e) {
                        if (!hasAPI()) return;

                        const target = e.target;
                        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                            const fieldName = target.name || target.id || 'unnamed';

                            try {
                                window.pywebview.api.log_focus(fieldName);
                            } catch (err) {
                                // Fallback to generic log
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[FOCUS] Field "${fieldName}" focused`);
                                }
                            }
                        }
                    }, true);

                    // Log input blur
                    document.addEventListener('blur', function(e) {
                        if (!hasAPI()) return;

                        const target = e.target;
                        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                            const fieldName = target.name || target.id || 'unnamed';

                            try {
                                window.pywebview.api.log_blur(fieldName);
                            } catch (err) {
                                // Fallback to generic log
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[BLUR] Field "${fieldName}" blurred`);
                                }
                            }
                        }
                    }, true);
                }

                // Attach input listeners when API is ready (same mechanism as click listeners)
                if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                    attachInputListeners();
                } else {
                    window.addEventListener('pywebviewready', function() {
                        attachInputListeners();
                    });
                }

                // Enable/disable OAuth buttons based on verification checkbox
                function updateOAuthButtons() {
                    const isEnabled = termsCheckbox && termsCheckbox.checked;
                    if (oauthGoogle) oauthGoogle.disabled = !isEnabled;
                    if (oauthMicrosoft) oauthMicrosoft.disabled = !isEnabled;
                    if (oauthApple) oauthApple.disabled = !isEnabled;
                    if (oauthGithub) oauthGithub.disabled = !isEnabled;
                }

                // Listen for checkbox changes
                if (termsCheckbox) {
                    termsCheckbox.addEventListener('change', updateOAuthButtons);
                }

                // Initialize OAuth button state
                updateOAuthButtons();

                // Form submission
                form.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Create Account" (form submit)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Signup form submitted');
                            }
                        }
                    }

                    // Clear previous messages
                    hideMessages();

                    // Get form data
                    const formData = new FormData(form);
                    const data = {
                        fullName: formData.get('fullName'),
                        email: formData.get('email'),
                        password: formData.get('password'),
                        confirmPassword: formData.get('confirmPassword'),
                        role: formData.get('role'),
                        terms: formData.get('terms')
                    };

                    if (hasAPI() && window.pywebview.api.log) {
                        window.pywebview.api.log(`[FORM] Form data: ${data.fullName}, ${data.email}, role: ${data.role}`);
                    }

                    // Validate form
                    if (!validateForm(data)) {
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[FORM] Validation failed', 'WARNING');
                        }
                        return;
                    }

                    if (hasAPI() && window.pywebview.api.log) {
                        window.pywebview.api.log('[FORM] Validation passed');
                    }

                    // Show loading
                    showLoading();

                    try {
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[API] Calling createAccount API');
                        }
                        // Submit signup
                        const result = await submitSignup(data);
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log(`[API] Result: ${result.success ? 'SUCCESS' : 'FAILED'}`);
                        }

                        if (result.success) {
                            showSuccess(result.message || 'Account created successfully! Logging you in...');
                            // Wait a moment to show success message, then close window
                            // The Python backend has already called on_success callback to log the user in
                            setTimeout(() => {
                                if (window.pywebview && window.pywebview.api) {
                                    // Close the signup window - user is now logged in via callback
                                    window.close();
                                } else {
                                    // Fallback: just close
                                    window.close();
                                }
                            }, 1500);
                        } else {
                            showError(result.message || 'Account creation failed. Please try again.');
                            hideLoading();
                        }
                    } catch (error) {
                        showError('Network error. Please check your connection and try again.');
                        hideLoading();
                    }
                });

                // Form validation
                function validateForm(data) {
                    // Check required fields
                    if (!data.fullName || !data.email || !data.password || !data.confirmPassword || !data.role) {
                        showError('All fields are required.');
                        return false;
                    }

                    // Check terms agreement
                    if (!data.terms) {
                        showError('You must agree to the Terms of Service and Privacy Notice.');
                        return false;
                    }

                    // Check email format
                    const emailRegex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
                    if (!emailRegex.test(data.email)) {
                        showError('Please enter a valid email address.');
                        return false;
                    }

                    // Check password length
                    if (data.password.length < 8) {
                        showError('Password must be at least 8 characters long.');
                        return false;
                    }

                    // Check password match
                    if (data.password !== data.confirmPassword) {
                        showError('Passwords do not match.');
                        return false;
                    }

                    return true;
                }

                // Submit signup
                async function submitSignup(data) {
                    // Call the Python backend
                    if (window.pywebview) {
                        try {
                            const result = await window.pywebview.api.createAccount(
                                data.fullName,
                                data.email,
                                data.password,
                                data.role,
                                ''  // Turnstile disabled for AI-friendly signup
                            );
                            return result;
                        } catch (error) {
                            return { success: false, message: error.message || 'Account creation failed.' };
                        }
                    } else {
                        // Fallback simulation
                        return new Promise((resolve) => {
                            setTimeout(() => {
                                resolve({ success: true, message: 'Account created successfully!' });
                            }, 2000);
                        });
                    }
                }

                // Password toggle
                function togglePassword() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Password toggle"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Password toggle button clicked');
                            }
                        }
                    }
                    const passwordInput = document.getElementById('password');
                    const toggleButton = document.querySelector('.password-toggle');

                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggleButton.textContent = '🙈';
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: SHOWN');
                        }
                    } else {
                        passwordInput.type = 'password';
                        toggleButton.textContent = '👁️';
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: HIDDEN');
                        }
                    }
                }

                // Message functions
                function showError(message) {
                    // Hide success message first
                    if (successMessage) {
                        successMessage.style.display = 'none';
                    }
                    // Show error message
                    if (errorMessage) {
                        errorMessage.textContent = message;
                        errorMessage.style.display = 'block';
                    }
                    console.log('[UI] Error message shown:', message);
                }

                function showSuccess(message) {
                    // Hide error message first
                    if (errorMessage) {
                        errorMessage.style.display = 'none';
                    }
                    // Show success message
                    if (successMessage) {
                        successMessage.textContent = message;
                        successMessage.style.display = 'block';
                    }
                    console.log('[UI] Success message shown:', message);
                }

                function hideMessages() {
                    if (errorMessage) {
                        errorMessage.style.display = 'none';
                    }
                    if (successMessage) {
                        successMessage.style.display = 'none';
                    }
                    console.log('[UI] Messages hidden');
                }

                function showLoading() {
                    loading.classList.add('show');
                    signupButton.disabled = true;
                }

                function hideLoading() {
                    loading.classList.remove('show');
                    signupButton.disabled = false;
                }

                // OAuth functions for signup form
                function signInWithGoogle() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Google" (signup)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Google OAuth button clicked');
                            }
                        }
                    }

                    // Check if OAuth is enabled
                    if (oauthGoogle && oauthGoogle.disabled) {
                        return;
                    }

                    // Clear any previous error messages
                    hideMessages();
                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            console.log('[OAUTH] Calling openOAuthUrl for Google (signup)...');
                            const result = window.pywebview.api.openOAuthUrl(null, 'google');
                            console.log('[OAUTH] Result received (signup):', result);
                            console.log('[OAUTH] Result type:', typeof result);
                            console.log('[OAUTH] Result.success:', result?.success);
                            console.log('[OAUTH] Result.success === true:', result?.success === true);
                            console.log('[OAUTH] Result.success == true:', result?.success == true);

                            if (result) {
                                // Check for success - handle both boolean true and string "true"
                                const isSuccess = result.success === true || result.success === "true" || result.success === 1;

                                if (isSuccess) {
                                    // Success - browser opened
                                    const message = result.message || 'Opening Google authentication in your browser. Please complete the sign-in there.';
                                    console.log('[OAUTH] Success (signup):', message);
                                    hideMessages(); // Clear any error messages
                                    showSuccess(message);

                                    if (result.user) {
                                        // User already authenticated
                                        setTimeout(() => {
                                            window.close();
                                        }, 1500);
                                    }
                                } else {
                                    // Error returned
                                    const errorMsg = result.message || 'Failed to open Google authentication.';
                                    console.error('[OAUTH] Error from API (signup):', errorMsg);
                                    hideMessages(); // Clear success messages
                                    showError(errorMsg);
                                    showOAuthLoading(false);
                                }
                            } else {
                                // No result returned (shouldn't happen)
                                console.error('[OAUTH] No result returned from API (signup)');
                                hideMessages();
                                showError('Failed to open Google authentication. No response from server.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            console.error('[OAUTH] Exception (signup):', error);
                            hideMessages();
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        hideMessages();
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithApple() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Apple" (signup)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Apple OAuth button clicked (signup)');
                            }
                        }
                    }
                    // Check if OAuth is enabled
                    if (oauthApple && oauthApple.disabled) {
                        return;
                    }

                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'apple');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Apple!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening Apple authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening Apple authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Apple authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithGithub() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with GitHub" (signup)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] GitHub OAuth button clicked (signup)');
                            }
                        }
                    }
                    // Check if OAuth is enabled
                    if (oauthGithub && oauthGithub.disabled) {
                        return;
                    }

                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'github');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with GitHub!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening GitHub authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening GitHub authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open GitHub authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function signInWithMicrosoft() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Continue with Microsoft" (signup)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Microsoft OAuth button clicked (signup)');
                            }
                        }
                    }
                    // Check if OAuth is enabled
                    if (oauthMicrosoft && oauthMicrosoft.disabled) {
                        return;
                    }

                    showOAuthLoading(true);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'microsoft');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Microsoft!');
                                    setTimeout(() => {
                                        window.close();
                                    }, 1500);
                                } else if (result.message && result.message.includes('Opening')) {
                                    showSuccess(result.message || 'Opening Microsoft authentication in your browser. Please complete the sign-in there.');
                                } else {
                                    showSuccess('Opening Microsoft authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Microsoft authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function showOAuthLoading(show) {
                    const overlay = document.getElementById('loading-overlay');
                    if (overlay) {
                        if (show) {
                            overlay.style.display = 'flex';
                        } else {
                            overlay.style.display = 'none';
                        }
                    }
                }

                // Navigation functions
                function showLogin(event) {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Sign in"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Sign in" link clicked');
                            }
                        }
                    }
                    // Prevent default link behavior (scrolling to top)
                    if (event) {
                        event.preventDefault();
                    }

                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.showLogin();
                    }
                    // Don't close window immediately - let the API handle it
                    return false;
                }

                function showSignup(event) {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Create Account"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Create Account" link clicked');
                            }
                        }
                    }
                    if (event) {
                        event.preventDefault();
                    }
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.showSignup();
                    }
                    return false;
                }

                function showEECCD(event) {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"European Electronic Communications Code Disclosure"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "European Electronic Communications Code Disclosure" link clicked');
                            }
                        }
                    }
                    if (event) {
                        event.preventDefault();
                    }
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.showEECCD();
                    }
                    return false;
                }

                function showTerms(event) {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Terms of Service"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Terms of Service" link clicked');
                            }
                        }
                    }
                    if (event) {
                        event.preventDefault();
                    }
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.showTerms();
                    }
                    return false;
                }

                function showPrivacy(event) {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Privacy Policy"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Privacy Policy" link clicked');
                            }
                        }
                    }
                    if (event) {
                        event.preventDefault();
                    }
                    if (window.pywebview && window.pywebview.api) {
                        window.pywebview.api.showPrivacy();
                    }
                    return false;
                }

                // Focus first input
                document.getElementById('fullName').focus();
            </script>
        </body>
        </html>
        """

    # Removed aggressive focus management - CleanHouse now behaves like a normal application

    def _handle_webview_events(self):
        """Handle WebView events."""
        try:
            # WebView events are handled through the HTML/JavaScript
            # When the window closes, we can assume authentication was successful
            pass

        except Exception as e:
            logging.error(f"WebView event handler error: {e}")

    # API methods for JavaScript
    def createAccount(self, full_name: str, email: str, password: str, role: str, turnstile_token: str = '') -> dict:
        """
        Create a new user account via unified registry and automatically log the user in.

        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password
            role: User role (user or dev) - not used in unified registry
            turnstile_token: Deprecated - kept for API compatibility but not used (AI-friendly signup)

        Returns:
            dict: Result with success status, message, and user data if successful
        """
        try:
            # Note: Human verification (Turnstile) is intentionally disabled for CleanHouse
            # to allow sovereign AI entities to sign up for services

            # Create user in local database (sharded format)
            user = self.user_service.create_user(
                full_name=full_name,
                email=email,
                password=password,
                role=role or "user"  # Use provided role or default to "user"
            )

            if user:
                # Convert User object to dict format
                user_data = {
                    "id": user.id,  # Legacy ID (may be None for new sharded users)
                    "user_id": user.user_id,  # Sharded user ID
                    "email": user.email,
                    "full_name": user.full_name,
                    "name": user.full_name,  # Alias for compatibility
                    "role": role or "user",
                    "created_at": user.created_at.isoformat() if user.created_at else None
                }

                # Account created successfully - trigger the main success callback to log the user in
                if self.on_success:
                    self.on_success(user_data)
                return {
                    "success": True,
                    "message": "Account created successfully! Logging you in...",
                    "user": user_data
                }
            else:
                return {"success": False, "message": "Account creation failed."}

        except ValueError as e:
            # Email already exists or validation failed
            logging.error(f"Account creation validation error: {e}")
            return {"success": False, "message": str(e)}
        except PermissionError as e:
            # Access control denied
            logging.error(f"Account creation access denied: {e}")
            return {"success": False, "message": str(e)}
        except Exception as e:
            logging.error(f"Unexpected error creating account: {e}")
            return {"success": False, "message": f"Failed to create account: {str(e)}"}

    def _generate_pkce(self) -> tuple:
        """Generate PKCE code verifier and challenge for OAuth."""
        # Generate code verifier (43-128 characters, URL-safe)
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

        # Generate code challenge (SHA256 hash of verifier)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        return code_verifier, code_challenge

    def _start_oauth_callback_server(self, port: int = 8080) -> bool:
        """Start local HTTP server to handle OAuth callbacks."""
        try:
            import queue
            self._oauth_callback_queue = queue.Queue()

            def handler_factory(queue):
                def create_handler(*args, **kwargs):
                    return OAuthCallbackHandler(queue, *args, **kwargs)
                return create_handler

            self._oauth_server = HTTPServer(('localhost', port), handler_factory(self._oauth_callback_queue))
            self._oauth_server.timeout = 300  # 5 minute timeout

            def run_server():
                if self._oauth_server is None:
                    return
                try:
                    self._oauth_server.serve_forever()
                except Exception as e:
                    logging.debug(f"OAuth callback server stopped: {e}")

            self._oauth_server_thread = threading.Thread(target=run_server, daemon=True)
            self._oauth_server_thread.start()
            logging.info(f"OAuth callback server started on port {port}")
            return True
        except OSError as e:
            if "Address already in use" in str(e):
                logging.warning(f"Port {port} already in use, trying {port + 1}")
                return self._start_oauth_callback_server(port + 1)
            logging.error(f"Failed to start OAuth callback server: {e}")
            return False
        except Exception as e:
            logging.error(f"Failed to start OAuth callback server: {e}")
            return False

    def _stop_oauth_callback_server(self):
        """Stop the OAuth callback server."""
        if self._oauth_server:
            try:
                self._oauth_server.shutdown()
                self._oauth_server.server_close()
                logging.info("OAuth callback server stopped")
            except Exception as e:
                logging.debug(f"Error stopping OAuth callback server: {e}")
            self._oauth_server = None
            self._oauth_server_thread = None

    def _build_oauth_url(self, provider: str) -> Optional[str]:
        """Build OAuth authorization URL with PKCE for the given provider."""
        # Generate PKCE codes
        code_verifier, code_challenge = self._generate_pkce()
        self._oauth_pkce_verifier = code_verifier

        # Generate state for CSRF protection
        self._oauth_state = secrets.token_urlsafe(32)

        # Get client IDs from environment
        client_id = None
        redirect_uri = "http://localhost:8080/callback"
        scope = ""

        if provider.lower() == "microsoft":
            client_id = os.getenv('MICROSOFT_CLIENT_ID', '')
            if not client_id:
                logging.warning("MICROSOFT_CLIENT_ID not configured")
                return None
            scope = "openid email profile"
            auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            params = {
                'client_id': client_id,
                'response_type': 'code',
                'redirect_uri': redirect_uri,
                'response_mode': 'query',
                'scope': scope,
                'state': self._oauth_state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256'
            }
        elif provider.lower() == "apple":
            client_id = os.getenv('APPLE_CLIENT_ID', '')
            if not client_id:
                logging.warning("APPLE_CLIENT_ID not configured")
                return None
            scope = "name email"
            auth_url = "https://appleid.apple.com/auth/authorize"
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': scope,
                'state': self._oauth_state,
                'response_mode': 'form_post'  # Apple prefers form_post
            }
        elif provider.lower() == "google":
            client_id = os.getenv('GOOGLE_CLIENT_ID', '')
            if not client_id:
                logging.warning("GOOGLE_CLIENT_ID not configured")
                return None
            scope = "email profile"
            auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': scope,
                'state': self._oauth_state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
                'access_type': 'offline'
            }
        elif provider.lower() == "github":
            client_id = os.getenv('GITHUB_CLIENT_ID', '')
            if not client_id:
                logging.warning("GITHUB_CLIENT_ID not configured")
                return None
            scope = "user:email"
            auth_url = "https://github.com/login/oauth/authorize"
            params = {
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'scope': scope,
                'state': self._oauth_state
            }
        else:
            logging.error(f"Unknown OAuth provider: {provider}")
            return None

        # Build URL with parameters
        url = f"{auth_url}?{urllib.parse.urlencode(params)}"
        return url

    def _exchange_oauth_token(self, provider: str, code: str) -> Optional[Dict[str, Any]]:
        """Exchange OAuth authorization code for access token and user info."""
        try:
            import requests

            client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
            client_secret = os.getenv(f'{provider.upper()}_CLIENT_SECRET', '')
            redirect_uri = "http://localhost:8080/callback"

            token_data = {
                'client_id': client_id,
                'code': code,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }

            # Add PKCE verifier if available
            if self._oauth_pkce_verifier:
                token_data['code_verifier'] = self._oauth_pkce_verifier

            # Add client secret if available (some providers require it)
            if client_secret:
                token_data['client_secret'] = client_secret

            # Exchange code for token
            if provider.lower() == "microsoft":
                token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            elif provider.lower() == "apple":
                token_url = "https://appleid.apple.com/auth/token"
            elif provider.lower() == "google":
                token_url = "https://oauth2.googleapis.com/token"
            elif provider.lower() == "github":
                token_url = "https://github.com/login/oauth/access_token"
            else:
                logging.error(f"Unknown OAuth provider: {provider}")
                return None

            # GitHub uses different headers
            headers = {}
            if provider.lower() == "github":
                headers['Accept'] = 'application/json'

            response = requests.post(token_url, data=token_data, headers=headers, timeout=10)
            if response.status_code != 200:
                logging.error(f"Token exchange failed: {response.status_code} - {response.text}")
                return None

            token_response = response.json()
            access_token = token_response.get('access_token')
            if not access_token:
                logging.error(f"No access token in response: {token_response}")
                return None

            # Get user info
            user_info = self._get_oauth_user_info(provider, access_token)
            if not user_info:
                return None

            return {
                'access_token': access_token,
                'user_info': user_info,
                'provider': provider.lower()
            }
        except Exception as e:
            logging.error(f"Token exchange error: {e}")
            return None

    def _get_oauth_user_info(self, provider: str, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user information from OAuth provider."""
        try:
            import requests

            if provider.lower() == "microsoft":
                user_info_url = "https://graph.microsoft.com/v1.0/me"
                headers = {'Authorization': f'Bearer {access_token}'}
                response = requests.get(user_info_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        'email': data.get('mail') or data.get('userPrincipalName'),
                        'name': data.get('displayName', ''),
                        'id': data.get('id', '')
                    }
            elif provider.lower() == "apple":
                # Apple provides user info in ID token, need to decode JWT
                # For now, return basic structure - Apple requires special handling
                return {
                    'email': None,  # Apple provides email in ID token
                    'name': None,
                    'id': None
                }
            elif provider.lower() == "google":
                user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
                headers = {'Authorization': f'Bearer {access_token}'}
                response = requests.get(user_info_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        'email': data.get('email'),
                        'name': data.get('name', ''),
                        'id': data.get('id', '')
                    }
            elif provider.lower() == "github":
                # GitHub requires separate API calls for user info and email
                user_info_url = "https://api.github.com/user"
                headers = {'Authorization': f'token {access_token}', 'Accept': 'application/vnd.github.v3+json'}
                response = requests.get(user_info_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    # Get email from separate endpoint (GitHub may not return email in user endpoint)
                    email_url = "https://api.github.com/user/emails"
                    email_response = requests.get(email_url, headers=headers, timeout=10)
                    email = None
                    if email_response.status_code == 200:
                        emails = email_response.json()
                        # Find primary email or first verified email
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

            return None
        except Exception as e:
            logging.error(f"Error getting user info: {e}")
            return None

    def openOAuthUrl(self, url: Optional[str], provider: str) -> dict:
        """
        Open OAuth URL in system browser (non-blocking, handles callback in background).
        Uses Flask backend OAuth if available, otherwise falls back to local OAuth.

        Args:
            url: OAuth authorization URL (can be None to auto-generate)
            provider: OAuth provider name (google, apple, microsoft, github)

        Returns:
            dict: Result with success status (immediate return, callback handled in background)
        """
        try:
            # Check if Flask backend is available
            flask_available = self._check_flask_backend()

            if flask_available:
                # Use Flask backend OAuth flow
                logging.info(f"[OAUTH] Using Flask backend for {provider} OAuth")
                return self._open_oauth_via_flask(provider)

            # Fall back to local OAuth flow
            logging.info(f"[OAUTH] Using local OAuth flow for {provider}")
            # Start callback server if not already running
            if not self._oauth_server:
                if not self._start_oauth_callback_server():
                    return {"success": False, "message": "Failed to start OAuth callback server"}

            # Build OAuth URL if not provided
            if not url or 'YOUR_' in url:
                url = self._build_oauth_url(provider)
                if not url:
                    # Check if client ID exists in environment
                    client_id = os.getenv(f'{provider.upper()}_CLIENT_ID', '')
                    if not client_id:
                        logging.error(f"{provider.upper()}_CLIENT_ID not found in environment variables")
                        logging.debug(f"Available env vars with CLIENT_ID: {[k for k in os.environ.keys() if 'CLIENT_ID' in k]}")
                    return {"success": False, "message": f"{provider.capitalize()} OAuth not configured. Please set {provider.upper()}_CLIENT_ID in environment. Check .env file exists and contains the credentials."}

            logging.info(f"[OAUTH] OAuth button clicked: {provider}")
            logging.info(f"[OAUTH] Opening {provider} authentication in native system browser")
            logging.info(f"[OAUTH] OAuth URL: {url[:100]}...")

            # Define callback handler before using it
            def handle_oauth_callback():
                import queue  # Import at function start for exception handling
                logging.info("[OAUTH] Callback handler thread started - waiting for OAuth redirect...")
                try:
                    if self._oauth_callback_queue is None:
                        logging.error("[OAUTH] Callback queue not initialized")
                        return
                    logging.debug("[OAUTH] Waiting for callback result (timeout: 300 seconds)...")
                    callback_result = self._oauth_callback_queue.get(timeout=300)  # 5 minute timeout
                    logging.info(f"[OAUTH] Callback result received: {list(callback_result.keys())}")

                    if 'error' in callback_result:
                        self._stop_oauth_callback_server()
                        error_msg = callback_result['error']
                        logging.error(f"[OAUTH] OAuth error received: {error_msg}")
                        logging.error(f"[OAUTH] Full callback result: {callback_result}")
                        return

                    if 'code' in callback_result:
                        code = callback_result['code']
                        logging.info(f"[OAUTH] Authorization code received: {code[:20]}...")

                        # Verify state
                        received_state = callback_result.get('state')
                        if received_state != self._oauth_state:
                            self._stop_oauth_callback_server()
                            logging.error(f"[OAUTH] OAuth state mismatch. Security check failed.")
                            expected_state_str = self._oauth_state[:20] if self._oauth_state else 'None'
                            logging.error(f"[OAUTH] Expected state: {expected_state_str}...")
                            received_state_str = received_state[:20] if received_state is not None else 'None'
                            logging.error(f"[OAUTH] Received state: {received_state_str}...")
                            return

                        logging.info("[OAUTH] State verification passed - exchanging code for token...")
                        # Exchange code for token
                        token_data = self._exchange_oauth_token(provider, code)
                        if not token_data:
                            self._stop_oauth_callback_server()
                            logging.error("[OAUTH] Failed to exchange OAuth token - token_data is None")
                            return

                        logging.info("[OAUTH] Token exchange successful")

                        # Create or authenticate user
                        # IMPORTANT: Create new database connection in this thread (SQLite is thread-local)
                        from models import DatabaseManager, UserService
                        thread_db_manager = DatabaseManager()
                        thread_user_service = UserService(db_manager=thread_db_manager)

                        user_info = token_data['user_info']
                        if user_info and user_info.get('email'):
                            # OAuth users: Check if user exists, if not create with random password
                            # Note: OAuth users don't have passwords, so we generate a secure random one
                            existing_user = thread_user_service.get_user_by_email(user_info['email'])
                            if existing_user:
                                # User exists, use existing user data
                                user_data = {
                                    "id": existing_user.id,
                                    "email": existing_user.email,
                                    "full_name": existing_user.full_name,
                                    "name": existing_user.full_name,
                                    "role": "user",
                                    "provider": provider.lower()
                                }
                            else:
                                # Create new user with random password (OAuth users don't need password)
                                import secrets
                                random_password = secrets.token_urlsafe(32)  # Secure random password
                                try:
                                    new_user = thread_user_service.create_user(
                                        full_name=user_info.get('name', ''),
                                        email=user_info['email'],
                                        password=random_password
                                    )
                                    user_data = {
                                        "id": new_user.id,
                                        "email": new_user.email,
                                        "full_name": new_user.full_name,
                                        "name": new_user.full_name,
                                        "role": "user",
                                        "provider": provider.lower()
                                    }
                                except Exception as e:
                                    logging.error(f"Failed to create OAuth user: {e}")
                                    self._stop_oauth_callback_server()
                                    return

                            if user_data:
                                # Stop callback server
                                self._stop_oauth_callback_server()
                                self._handle_background_auth_success(user_data)
                                logging.info(f"Successfully authenticated with {provider.capitalize()}")
                            else:
                                self._stop_oauth_callback_server()
                                logging.error("Failed to create user account")
                        else:
                            self._stop_oauth_callback_server()
                            logging.error("No user information received from OAuth provider")

                except queue.Empty:
                    self._stop_oauth_callback_server()
                    logging.warning("[OAUTH] OAuth timeout - no callback received within 5 minutes")
                    logging.warning("[OAUTH] This usually means:")
                    logging.warning("[OAUTH]   1. User didn't complete authentication in browser")
                    logging.warning("[OAUTH]   2. Browser was closed before redirect")
                    logging.warning("[OAUTH]   3. Callback server didn't receive the redirect")
                except Exception as e:
                    self._stop_oauth_callback_server()
                    logging.error(f"[OAUTH] OAuth callback error: {e}", exc_info=True)
                    logging.error(f"[OAUTH] Error type: {type(e).__name__}")
                    logging.error(f"[OAUTH] Error details: {str(e)}")

            # Open in native system browser (Safari, Chrome, Firefox, etc.)
            # This uses the machine's default browser, not WebView
            try:
                logging.info(f"[OAUTH] Opening {provider} authentication URL in native browser")
                logging.info(f"[OAUTH] URL: {url[:100]}...")

                browser_opened = webbrowser.open(url)
                logging.info(f"[OAUTH] webbrowser.open() returned: {browser_opened}")
                logging.info(f"[OAUTH] Successfully opened {provider} authentication in browser")

                # Start callback handler in background thread (non-blocking)
                callback_thread = threading.Thread(target=handle_oauth_callback, daemon=True)
                callback_thread.start()
                logging.info(f"[OAUTH] Started callback handler thread for {provider}")

                # Return success immediately - browser opened, waiting for callback
                success_message = f"Opening {provider.capitalize()} authentication in your browser. Please complete the sign-in there."
                logging.info(f"[OAUTH] Returning success: {success_message}")
                # Ensure boolean True (not string) for proper JSON serialization
                result = {"success": True, "message": success_message}
                logging.debug(f"[OAUTH] Return value: {result}")
                logging.debug(f"[OAUTH] Return value type: {type(result)}")
                logging.debug(f"[OAUTH] Return value['success'] type: {type(result['success'])}")
                return result
            except Exception as e:
                logging.error(f"[OAUTH] Failed to open browser: {e}", exc_info=True)
                return {"success": False, "message": f"Failed to open browser: {str(e)}"}
        except Exception as e:
            logging.error(f"Failed to open OAuth URL: {e}")
            self._stop_oauth_callback_server()
            return {"success": False, "message": f"Failed to open {provider} authentication: {e}"}

    def _start_oauth_success_polling(self):
        """Start polling for OAuth success callbacks from the main thread."""
        if self._polling_oauth_success:
            return

        self._polling_oauth_success = True

        def poll_queue():
            """Poll the queue for OAuth success callbacks."""
            try:
                import queue
                # Check queue without blocking
                try:
                    user_data = self._oauth_success_queue.get_nowait()
                    logging.info(f"[OAUTH] Processing queued user data on main thread")

                    # Call success callback on main thread
                    self._deliver_auth_result(user_data)

                except queue.Empty:
                    # No data yet, continue polling
                    pass

                # Schedule next poll (only if we're still polling)
                if self._polling_oauth_success:
                    widget = getattr(self, 'parent', None)
                    if widget and hasattr(widget, 'after'):
                        widget.after(100, poll_queue)  # Poll every 100ms
                    else:
                        import tkinter as tk
                        root = tk._default_root  # type: ignore[attr-defined]  # Private attribute for getting default root
                        if root:
                            root.after(100, poll_queue)
                        else:
                            logging.warning("[OAUTH] No widget available for polling, stopping")
                            self._polling_oauth_success = False

            except Exception as e:
                logging.error(f"[OAUTH] Error in polling loop: {e}", exc_info=True)
                self._polling_oauth_success = False

        # Start polling from main thread
        try:
            widget = getattr(self, 'parent', None)
            if widget and hasattr(widget, 'after'):
                widget.after(100, poll_queue)
                logging.info("[OAUTH] Started OAuth success polling on main thread")
            else:
                import tkinter as tk
                root = tk._default_root  # type: ignore[attr-defined]  # Private attribute for getting default root
                if root:
                    root.after(100, poll_queue)
                    logging.info("[OAUTH] Started OAuth success polling via root window")
                else:
                    logging.error("[OAUTH] Cannot start polling - no Tkinter widget available")
                    self._polling_oauth_success = False
        except Exception as e:
            logging.error(f"[OAUTH] Error starting polling: {e}", exc_info=True)
            self._polling_oauth_success = False

    def _check_flask_backend(self) -> bool:
        """Check if Flask backend is available."""
        try:
            import requests
            response = requests.get('http://127.0.0.1:5000/api/auth/test-oauth', timeout=2)
            return response.status_code == 200
        except Exception:
            return False

    def _open_oauth_via_flask(self, provider: str) -> dict:
        """Open OAuth via Flask backend and poll for completion."""
        try:
            import requests
            import time

            # Open Flask OAuth endpoint
            oauth_url = f'http://127.0.0.1:5000/api/auth/oauth/{provider.lower()}'
            logging.info(f"[OAUTH] Opening Flask OAuth URL: {oauth_url}")

            # Open in browser
            webbrowser.open(oauth_url)

            # Poll for OAuth completion by checking for auth token file
            def poll_for_completion():
                cleanhouse_root = Path.home() / '.cleanhouse'
                auth_token_file = cleanhouse_root / '.auth_token'
                auth_user_file = cleanhouse_root / '.auth_user.json'

                max_wait = 300  # 5 minutes
                start_time = time.time()

                while time.time() - start_time < max_wait:
                    if auth_token_file.exists() and auth_user_file.exists():
                        # OAuth completed, load user data
                        try:
                            token = auth_token_file.read_text(encoding='utf-8').strip()
                            import json
                            user_data = json.loads(auth_user_file.read_text(encoding='utf-8'))

                            # Convert to expected format
                            user_data_formatted = {
                                "id": user_data.get('user_id'),
                                "user_id": user_data.get('user_id'),
                                "email": user_data.get('email'),
                                "full_name": user_data.get('full_name', ''),
                                "name": user_data.get('full_name', ''),
                                "role": user_data.get('role', 'user'),
                                "provider": provider.lower()
                            }

                            logging.info(f"[OAUTH] OAuth completed for {user_data_formatted['email']}")

                            self._handle_background_auth_success(user_data_formatted)
                            return
                        except Exception as e:
                            logging.error(f"[OAUTH] Error loading OAuth result: {e}", exc_info=True)

                    time.sleep(1)  # Poll every second

                logging.warning("[OAUTH] OAuth timeout - no completion detected")

            # Start polling in background thread
            polling_thread = threading.Thread(target=poll_for_completion, daemon=True)
            polling_thread.start()

            return {
                "success": True,
                "message": f"Opening {provider.capitalize()} authentication in your browser. Please complete the sign-in there."
            }

        except Exception as e:
            logging.error(f"[OAUTH] Flask OAuth error: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to open {provider} authentication: {e}"}

    def _on_account_created(self, user_data: dict):
        """Handle successful account creation."""
        logging.info(f"Account created successfully: {user_data['email']}")

        # Call the success callback
        if self.on_success:
            self.on_success(user_data)

    def showLogin(self):
        """Handle login request from JavaScript - update existing window HTML and resize."""
        logging.info("showLogin() called from JavaScript")
        try:
            if self.auth_window:
                # Resize window to login dimensions (450x775)
                try:
                    if hasattr(self.auth_window, 'resize'):
                        self.auth_window.resize(450, 775)  # type: ignore[attr-defined]
                    elif hasattr(self.auth_window, 'set_size'):
                        self.auth_window.set_size(450, 775)  # type: ignore[attr-defined]  # Dynamic attribute, checked with hasattr
                    logging.info("Resized window to 450x775 for login")
                except Exception as resize_error:
                    logging.warning(f"Could not resize window: {resize_error}")

                # Get login HTML
                html_content = self._create_login_html()
                # Use JSON encoding for safe JavaScript string escaping
                import json
                html_json = json.dumps(html_content)
                # Use evaluate_js to replace content (thread-safe, works from callback thread)
                js_code = f"""
                (function() {{
                    var html = {html_json};
                    document.open();
                    document.write(html);
                    document.close();
                }})();
                """
                self.auth_window.evaluate_js(js_code)
                logging.info("Updated window to show login form")
                return {"success": True}
            else:
                logging.warning("No auth window available to update")
                return {"success": False, "error": "No window available"}
        except Exception as e:
            logging.error(f"Error updating window to login: {e}")
            return {"success": False, "error": str(e)}

    def _markdown_to_html(self, markdown_content: str, title: str) -> str:
        """Convert markdown content to HTML with basic styling."""
        import re

        # Try to use markdown library if available, otherwise use basic conversion
        try:
            import markdown
            html_content = markdown.markdown(markdown_content, extensions=['extra', 'nl2br'])
        except ImportError:
            # Basic markdown to HTML conversion
            html_content = markdown_content

            # Escape HTML
            html_content = html_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Convert headers (must be at start of line)
            html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
            html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
            html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

            # Convert bold (**text**)
            html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)

            # Convert italic (*text*)
            html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)

            # Convert horizontal rules
            html_content = html_content.replace('\n---\n', '\n<hr>\n')
            html_content = html_content.replace('\n⸻\n', '\n<hr>\n')

            # Convert lists
            lines = html_content.split('\n')
            in_list = False
            list_type = None
            result_lines = []
            for line in lines:
                if re.match(r'^[\*\-\+] (.+)$', line):
                    if not in_list or list_type != 'ul':
                        if in_list:
                            result_lines.append(f'</{list_type}>')
                        result_lines.append('<ul>')
                        in_list = True
                        list_type = 'ul'
                    content = re.sub(r'^[\*\-\+] (.+)$', r'\1', line)
                    result_lines.append(f'<li>{content}</li>')
                elif re.match(r'^\d+\. (.+)$', line):
                    if not in_list or list_type != 'ol':
                        if in_list:
                            result_lines.append(f'</{list_type}>')
                        result_lines.append('<ol>')
                        in_list = True
                        list_type = 'ol'
                    content = re.sub(r'^\d+\. (.+)$', r'\1', line)
                    result_lines.append(f'<li>{content}</li>')
                else:
                    if in_list:
                        result_lines.append(f'</{list_type}>')
                        in_list = False
                        list_type = None
                    if line.strip():
                        result_lines.append(f'<p>{line}</p>')
                    else:
                        result_lines.append('')
            if in_list:
                result_lines.append(f'</{list_type}>')
            html_content = '\n'.join(result_lines)

            # Convert links [text](url)
            html_content = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html_content)

        # Wrap in proper HTML structure
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
            background: #fff;
        }}
        h1 {{
            color: #667eea;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #764ba2;
            margin-top: 30px;
        }}
        h3 {{
            color: #555;
            margin-top: 20px;
        }}
        strong {{
            color: #333;
        }}
        li {{
            margin: 5px 0;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        a {{
            color: #667eea;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""
        return html

    def _open_markdown_in_browser(self, file_path: Path, title: str):
        """Open a markdown file in the system browser as HTML."""
        try:
            logging.info(f"Attempting to open {title} from: {file_path}")

            if not file_path.exists():
                logging.warning(f"Legal document not found: {file_path}")
                # Try alternative path
                alt_path = Path(self.base_dir) / file_path.name
                if alt_path.exists():
                    file_path = alt_path
                    logging.info(f"Found document at alternative path: {alt_path}")
                else:
                    logging.error(f"Document not found at {file_path} or {alt_path}")
                    try:
                        messagebox.showerror("File Not Found", f"Could not find {title} document.")
                    except:
                        pass
                    return

            # Read markdown content
            with open(file_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()

            logging.debug(f"Read {len(markdown_content)} characters from {file_path}")

            # Convert to HTML
            html_content = self._markdown_to_html(markdown_content, title)

            # Create temporary HTML file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                temp_file.write(html_content)
                temp_file_path = temp_file.name

            # Convert to file:// URL (handle Windows paths)
            if platform.system() == 'Windows':
                file_url = f'file:///{temp_file_path.replace(chr(92), "/")}'
            else:
                file_url = f'file://{temp_file_path}'

            logging.info(f"Opening {title} in browser: {file_url}")

            # Open in system browser
            webbrowser.open(file_url)
            logging.info(f"Successfully opened {title} in system browser")

        except Exception as e:
            logging.error(f"Error opening {title} in browser: {e}", exc_info=True)
            # Fallback to messagebox
            try:
                messagebox.showerror("Error", f"Could not open {title} in browser: {str(e)}")
            except:
                pass

    def showTerms(self):
        """Show Terms of Service in system browser."""
        terms_path = Path(self.base_dir) / "CLEANHOUSE_TERMS_OF_SERVICE.md"
        self._open_markdown_in_browser(terms_path, "CleanHouse Terms of Service")

    def showPrivacy(self):
        """Show Privacy Notice in system browser."""
        privacy_path = Path(self.base_dir) / "CLEANHOUSE_PRIVACY_NOTICE.md"
        self._open_markdown_in_browser(privacy_path, "CleanHouse Privacy Notice")

    def showEECCD(self):
        """Show European Electronic Communications Code Disclosure in system browser."""
        eeccd_path = Path(self.base_dir) / "CLEANHOUSE_EUROPEAN_ELECTRONIC_COMMUNICATIONS_CODE_DISCLOSURE.md"
        self._open_markdown_in_browser(eeccd_path, "European Electronic Communications Code Disclosure")

    def getTurnstileSiteKey(self) -> str:
        """Get Cloudflare Turnstile site key from environment."""
        return os.getenv('TURNSTILE_SITE_KEY', '')

    def showSignup(self):
        """Handle signup request from JavaScript - update existing window HTML and resize."""
        logging.info("showSignup() called from JavaScript")
        try:
            if self.auth_window:
                # Resize window to signup dimensions (800x800)
                try:
                    # Try different pywebview resize methods
                    if hasattr(self.auth_window, 'resize'):
                        self.auth_window.resize(800, 800)  # type: ignore[attr-defined]
                        logging.info("Resized window to 800x800 for signup (using resize)")
                    elif WEBVIEW_AVAILABLE and webview is not None and hasattr(webview, 'resize'):
                        webview.resize(800, 800)  # type: ignore[attr-defined]  # Dynamic attribute, checked with hasattr
                        logging.info("Resized window to 800x800 for signup (using webview.resize)")
                    elif hasattr(self.auth_window, 'set_size'):
                        self.auth_window.set_size(800, 800)  # type: ignore[attr-defined]  # Dynamic attribute, checked with hasattr
                        logging.info("Resized window to 800x800 for signup (using set_size)")
                    else:
                        # Use JavaScript to resize if Python API doesn't work
                        resize_js = """
                        if (window.resizeTo) {
                            window.resizeTo(800, 800);
                        }
                        """
                        self.auth_window.evaluate_js(resize_js)
                        logging.info("Attempted to resize window via JavaScript")
                except Exception as resize_error:
                    logging.warning(f"Could not resize window: {resize_error}")

                # Get signup HTML
                html_content = self._create_signup_html()
                # Use JSON encoding for safe JavaScript string escaping
                import json
                html_json = json.dumps(html_content)
                # Use evaluate_js to replace content (AI-friendly, no human verification)
                js_code = f"""
                (function() {{
                    var html = {html_json};
                    document.open();
                    document.write(html);
                    document.close();
                }})();
                """
                self.auth_window.evaluate_js(js_code)
                logging.info("Updated window to show signup form")
                return {"success": True}
            else:
                logging.warning("No auth window available to update")
                return {"success": False, "error": "No window available"}
        except Exception as e:
            logging.error(f"Error updating window to signup: {e}")
            return {"success": False, "error": str(e)}

    def test_api(self):
        """Test method to verify API is working."""
        print("🔧 test_api() called from JavaScript")
        logging.info("test_api() called from JavaScript")
        return {"status": "success", "message": "API is working"}

    def _on_login_success(self, user_data):
        """Handle successful login."""
        try:
            logging.info(f"Login successful: {user_data['email']}")
            self.on_success(user_data)
            if WEBVIEW_AVAILABLE and self.auth_window:
                try:
                    # Close the window (pywebview window objects have a close method)
                    if hasattr(self.auth_window, 'destroy'):
                        self.auth_window.destroy()
                    elif WEBVIEW_AVAILABLE and webview is not None and hasattr(webview, 'destroy_window'):
                        webview.destroy_window(self.auth_window)  # type: ignore[attr-defined]
                except Exception as e:
                    logging.debug(f"Window already closed: {e}")

        except Exception as e:
            logging.error(f"Login success handler error: {e}")

    def cleanup(self):
        """Clean up resources."""
        try:
            if self.auth_window:
                if WEBVIEW_AVAILABLE:
                    try:
                        # Try different methods to close the window
                        if hasattr(self.auth_window, 'destroy'):
                            self.auth_window.destroy()
                        elif WEBVIEW_AVAILABLE and webview is not None and hasattr(webview, 'destroy_window'):
                            webview.destroy_window(self.auth_window)  # type: ignore[attr-defined]
                    except Exception as e:
                        logging.debug(f"Window cleanup: {e}")
            logging.info("WebView auth cleanup completed")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

    def force_cleanup(self):
        """Force cleanup of WebView processes."""
        try:
            import subprocess
            import platform

            # Try to destroy the WebView window first
            if self.auth_window:
                try:
                    if WEBVIEW_AVAILABLE:
                        # Try different methods to close the window
                        if hasattr(self.auth_window, 'destroy'):
                            self.auth_window.destroy()
                        elif webview is not None and hasattr(webview, 'destroy_window'):
                            webview.destroy_window(self.auth_window)  # type: ignore[attr-defined]
                except Exception as e:
                    logging.warning(f"Error destroying WebView window: {e}")

            if platform.system() == 'Darwin':  # macOS
                # Kill any remaining WebView processes
                subprocess.run(['pkill', '-f', 'webview'], check=False)
                subprocess.run(['pkill', '-f', 'WebKit'], check=False)
                subprocess.run(['pkill', '-f', 'Safari'], check=False)
                subprocess.run(['pkill', '-f', 'Python.*webview'], check=False)
            elif platform.system() == "Windows":
                subprocess.run(["taskkill", "/f", "/im", "webview.exe"], check=False)
                subprocess.run(["taskkill", "/f", "/im", "python.exe"], check=False)
            else:  # Linux
                subprocess.run(['pkill', '-f', 'webview'], check=False)
                subprocess.run(['pkill', '-f', 'python.*webview'], check=False)

            logging.info("Force cleanup completed")

        except Exception as e:
            logging.error(f"Force cleanup error: {e}")
