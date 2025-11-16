# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - webview_auth.py
#  WebView-based authentication with native autofill support
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox
import webview
import threading
import json
import logging
import webbrowser
import signal
import sys
from typing import Callable, Optional, Dict, Any
from pathlib import Path
import http.server
import socketserver
import urllib.parse
import time
import platform
# Removed aggressive focus management imports

class WebViewAuth:
    """
    WebView-based authentication with native autofill support.
    """
    
    def __init__(self, parent, on_success: Callable, base_dir: str = None):
        self.parent = parent
        self.on_success = on_success
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.auth_window = None
        self.local_server = None
        self.server_thread = None
        self.port = 8080
        # Removed aggressive focus management
        
        # Set up signal handling for WebView auth
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Set up signal handlers for WebView authentication."""
        def signal_handler(signum, frame):
            """Handle SIGINT (Ctrl+C) during WebView authentication."""
            print(f"\n🛑 CleanHouse WebView auth received signal {signum}, cleaning up...")
            logging.info(f"Received signal {signum} during WebView authentication")
            
            # Clean up WebView processes and local server
            try:
                self.cleanup()
            except Exception as e:
                logging.error(f"Error during WebView auth cleanup: {e}")
            
            # Force exit
            print("✅ CleanHouse WebView auth terminated.")
            sys.exit(0)
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logging.info("Signal handlers set up for WebView authentication")
        
    def show_login(self):
        """Show WebView-based login."""
        try:
            # Start local server for OAuth callback
            self._start_local_server()
            
            # Create HTML login page
            html_content = self._create_login_html()
            
            # Show WebView window with normal window behavior
            self.auth_window = webview.create_window(
                title='CleanHouse - Sign In',
                html=html_content,
                width=500,
                height=600,
                resizable=False
            )
            
            # Start WebView
            webview.start(
                self._handle_webview_events,
                debug=False,
                private_mode=False
            )
            
        except Exception as e:
            logging.error(f"WebView auth error: {e}")
            messagebox.showerror("Error", f"Failed to start WebView authentication: {e}")
    
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
                
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }
                
                .login-container {
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                    padding: 40px;
                    width: 100%;
                    max-width: 400px;
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
                    padding: 12px;
                    border: 2px solid #e1e8ed;
                    border-radius: 8px;
                    background: white;
                    color: #2c3e50;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.3s ease;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    margin-bottom: 10px;
                }
                
                .oauth-btn:hover {
                    border-color: #667eea;
                    background: #f8f9fa;
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
                    <span>🔐</span>
                    Sign in with Google
                </button>
                
                <button class="oauth-btn" onclick="signInWithApple()">
                    <span>🍎</span>
                    Sign in with Apple
                </button>
                
                <div class="signup-link">
                    <a href="#" onclick="showSignup()">Don't have an account? Sign up</a>
                </div>
            </div>
            
            <script>
                // Password toggle functionality
                function togglePassword() {
                    const passwordInput = document.getElementById('password');
                    const toggle = document.querySelector('.password-toggle');
                    
                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggle.textContent = '🙈';
                    } else {
                        passwordInput.type = 'password';
                        toggle.textContent = '👁️';
                    }
                }
                
                // Form submission
                document.getElementById('login-form').addEventListener('submit', function(e) {
                    e.preventDefault();
                    
                    const email = document.getElementById('email').value;
                    const password = document.getElementById('password').value;
                    
                    if (!email || !password) {
                        showError('Please fill in all fields.');
                        return;
                    }
                    
                    showLoading(true);
                    
                    // Send login request
                    fetch('/api/login', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ email, password })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            showSuccess('Login successful!');
                            setTimeout(() => {
                                // Close the WebView window
                                window.close();
                            }, 1000);
                        } else {
                            showError(data.error || 'Login failed. Please try again.');
                        }
                    })
                    .catch(error => {
                        showError('Network error. Please try again.');
                        console.error('Login error:', error);
                    })
                    .finally(() => {
                        showLoading(false);
                    });
                });
                
                // OAuth functions
                function signInWithGoogle() {
                    showLoading(true);
                    window.location.href = '/auth/google';
                }
                
                function signInWithApple() {
                    showLoading(true);
                    window.location.href = '/auth/apple';
                }
                
                function showSignup() {
                    // Switch to signup form
                    window.location.href = '/signup';
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
                
                // Focus first input
                document.getElementById('email').focus();
            </script>
        </body>
        </html>
        """
    
    def _start_local_server(self):
        """Start local HTTP server for OAuth callbacks."""
        try:
            handler = self._create_request_handler()
            self.local_server = socketserver.TCPServer(("localhost", self.port), handler)
            
            self.server_thread = threading.Thread(
                target=self.local_server.serve_forever,
                daemon=True
            )
            self.server_thread.start()
            
            logging.info(f"Local server started on port {self.port}")
            
        except Exception as e:
            logging.error(f"Failed to start local server: {e}")
            raise
    
    def _create_request_handler(self):
        """Create HTTP request handler for OAuth callbacks."""
        auth_instance = self
        
        class AuthRequestHandler(http.server.SimpleHTTPRequestHandler):
            def do_POST(self):
                if self.path == '/api/login':
                    self._handle_login()
                else:
                    self._send_error(404)
            
            def do_GET(self):
                if self.path == '/auth/google':
                    self._handle_google_oauth()
                elif self.path == '/auth/apple':
                    self._handle_apple_oauth()
                elif self.path.startswith('/callback'):
                    self._handle_oauth_callback()
                else:
                    self._send_error(404)
            
            def _handle_login(self):
                """Handle login request."""
                try:
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    # Here you would validate credentials
                    # For now, we'll simulate a successful login
                    response = {
                        'success': True,
                        'user': {
                            'email': data['email'],
                            'name': data['email'].split('@')[0],
                            'role': 'user'
                        }
                    }
                    
                    self._send_json_response(response)
                    
                except Exception as e:
                    logging.error(f"Login error: {e}")
                    self._send_json_response({'success': False, 'error': 'Login failed'})
            
            def _handle_google_oauth(self):
                """Handle Google OAuth."""
                # Redirect to Google OAuth
                google_oauth_url = (
                    "https://accounts.google.com/oauth/authorize?"
                    "client_id=YOUR_GOOGLE_CLIENT_ID&"
                    "redirect_uri=http://localhost:8080/callback/google&"
                    "scope=email profile&"
                    "response_type=code"
                )
                self._send_redirect(google_oauth_url)
            
            def _handle_apple_oauth(self):
                """Handle Apple OAuth."""
                # Redirect to Apple OAuth
                apple_oauth_url = (
                    "https://appleid.apple.com/auth/authorize?"
                    "client_id=YOUR_APPLE_CLIENT_ID&"
                    "redirect_uri=http://localhost:8080/callback/apple&"
                    "scope=name email&"
                    "response_type=code"
                )
                self._send_redirect(apple_oauth_url)
            
            def _handle_oauth_callback(self):
                """Handle OAuth callback."""
                # Parse callback and extract user info
                # This is where you'd exchange the code for tokens
                response = {
                    'success': True,
                    'user': {
                        'email': 'user@example.com',
                        'name': 'User Name',
                        'role': 'user'
                    }
                }
                
                # Send success page
                success_html = """
                <!DOCTYPE html>
                <html>
                <head><title>Login Successful</title></head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>✅ Login Successful!</h1>
                    <p>You can close this window and return to CleanHouse.</p>
                </body>
                </html>
                """
                
                self._send_html_response(success_html)
                
                # Notify the main app
                auth_instance._on_oauth_success(response['user'])
            
            def _send_json_response(self, data):
                """Send JSON response."""
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            
            def _send_html_response(self, html):
                """Send HTML response."""
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(html.encode())
            
            def _send_redirect(self, url):
                """Send redirect response."""
                self.send_response(302)
                self.send_header('Location', url)
                self.end_headers()
            
            def _send_error(self, code):
                """Send error response."""
                self.send_response(code)
                self.end_headers()
        
        return AuthRequestHandler
    
    # Removed aggressive focus management - CleanHouse now behaves like a normal application
    
    def _handle_webview_events(self):
        """Handle WebView events."""
        try:
            # WebView events are handled through the local server
            # No need for direct API setup
            pass
            
        except Exception as e:
            logging.error(f"WebView event handler error: {e}")
    
    def _on_login_success(self, user_data):
        """Handle successful login."""
        try:
            logging.info(f"Login successful: {user_data['email']}")
            self.on_success(user_data)
            webview.destroy_window(self.auth_window)
            
        except Exception as e:
            logging.error(f"Login success handler error: {e}")
    
    def _on_oauth_success(self, user_data):
        """Handle successful OAuth."""
        try:
            logging.info(f"OAuth successful: {user_data['email']}")
            self.on_success(user_data)
            webview.destroy_window(self.auth_window)
            
        except Exception as e:
            logging.error(f"OAuth success handler error: {e}")
    
    def cleanup(self):
        """Clean up resources."""
        try:
            if self.local_server:
                self.local_server.shutdown()
                self.local_server.server_close()
            logging.info("WebView auth cleanup completed")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")
