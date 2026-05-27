# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - ui/signup.py
#  Modern Create Account UI component with PyWebView
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import webview
import logging
import signal
import sys
import os
from typing import Callable, Optional, Dict, Any
from pathlib import Path
from tkinter import messagebox

# Import our account system
from models import User, UserService, DatabaseManager
from access_control.access_control import access_control

class SignupUI:
    """
    Modern Create Account UI component with industry-standard design.
    Matches Bitdefender, 1Password, and ChatGPT login page aesthetics.
    """

    def __init__(self, parent, on_success: Callable, on_login_request: Callable = None, base_dir: str = None):
        self.parent = parent
        self.on_success = on_success
        self.on_login_request = on_login_request
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.signup_window = None

        # Initialize user service
        self.db_manager = DatabaseManager()
        self.user_service = UserService(db_manager=self.db_manager)

        # Set up signal handling
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            """Handle SIGINT (Ctrl+C) during signup."""
            print(f"\n🛑 CleanHouse signup received signal {signum}, cleaning up...")
            logging.info(f"Received signal {signum} during signup")

            try:
                self.cleanup()
            except Exception as e:
                logging.error(f"Error during signup cleanup: {e}")

            print("✅ CleanHouse signup terminated.")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logging.info("Signal handlers set up for signup")

    def show_signup(self):
        """Show the Create Account form."""
        try:
            # Create HTML signup page
            html_content = self._create_signup_html()

            # Show WebView window with modern styling and focus management
            self.signup_window = webview.create_window(
                title='CleanHouse - Create Account',
                html=html_content,
                width=480,
                height=720,
                resizable=False,
                shadow=True,
                focus=True
            )

            # Apply focus management to ensure modal is visible
            self._apply_focus_management()

            # Start WebView with focus management
            webview.start(
                self._handle_webview_events,
                debug=False,
                private_mode=False
            )

        except Exception as e:
            logging.error(f"Signup UI error: {e}")
            messagebox.showerror("Error", f"Failed to start signup: {e}")

    def _create_signup_html(self) -> str:
        """Create modern HTML signup page with industry-standard design."""
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

                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                    color: #333;
                }

                .signup-container {
                    background: white;
                    border-radius: 16px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1), 0 0 0 1px rgba(0,0,0,0.05);
                    padding: 40px;
                    width: 100%;
                    max-width: 400px;
                    position: relative;
                    overflow: hidden;
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
                    margin-bottom: 24px;
                }

                .form-group label {
                    display: block;
                    margin-bottom: 8px;
                    color: #333;
                    font-weight: 500;
                    font-size: 14px;
                }

                .form-group input {
                    width: 100%;
                    padding: 14px 16px;
                    border: 2px solid #e1e5e9;
                    border-radius: 12px;
                    font-size: 16px;
                    transition: all 0.3s ease;
                    background: #f8f9fa;
                    font-family: inherit;
                }

                .form-group input:focus {
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
                    margin-bottom: 20px;
                    font-family: inherit;
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

                .divider {
                    text-align: center;
                    margin: 24px 0;
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
                    padding: 14px;
                    border: 2px solid #e1e8ed;
                    border-radius: 12px;
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
                    margin-bottom: 12px;
                    font-family: inherit;
                }

                .oauth-btn:hover {
                    border-color: #667eea;
                    background: #f8f9fa;
                }

                .oauth-btn:last-child {
                    margin-bottom: 0;
                }

                /* Dark mode support */
                @media (prefers-color-scheme: dark) {
                    body {
                        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    }

                    .signup-container {
                        background: #2d3748;
                        color: #e2e8f0;
                    }

                    .logo-text {
                        color: #e2e8f0;
                    }

                    .subtitle {
                        color: #a0aec0;
                    }

                    .form-group input {
                        background: #4a5568;
                        border-color: #4a5568;
                        color: #e2e8f0;
                    }

                    .form-group input:focus {
                        background: #2d3748;
                        border-color: #667eea;
                    }

                    .checkbox-group label {
                        color: #a0aec0;
                    }

                    .oauth-btn {
                        background: #4a5568;
                        border-color: #4a5568;
                        color: #e2e8f0;
                    }

                    .oauth-btn:hover {
                        background: #2d3748;
                        border-color: #667eea;
                    }
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

                <form id="signupForm">
                    <div class="form-group">
                        <label for="fullName">Full Name</label>
                        <input type="text" id="fullName" name="fullName" required autocomplete="name">
                    </div>

                    <div class="form-group">
                        <label for="email">Email Address</label>
                        <input type="email" id="email" name="email" required autocomplete="email">
                    </div>

                    <div class="form-group">
                        <label for="password">Password</label>
                        <div class="password-container">
                            <input type="password" id="password" name="password" required autocomplete="new-password">
                            <button type="button" class="password-toggle" onclick="togglePassword()">👁️</button>
                        </div>
                        <div class="password-requirements">
                            Must be at least 8 characters long
                        </div>
                    </div>

                    <div class="checkbox-group">
                        <input type="checkbox" id="terms" name="terms" required>
                        <label for="terms">
                            I agree to the <a href="#" onclick="showTerms()">Terms of Use</a> and
                            <a href="#" onclick="showPrivacy()">Privacy Policy</a>
                        </label>
                    </div>

                    <button type="submit" class="signup-button" id="signupButton">
                        Create Account
                    </button>
                </form>

                <div class="divider">
                    <span>or</span>
                </div>

                <button class="oauth-btn" onclick="signInWithGoogle()">
                    <span>🔐</span>
                    Sign up with Google
                </button>

                <button class="oauth-btn" onclick="signInWithApple()">
                    <span>🍎</span>
                    Sign up with Apple
                </button>

                <div class="login-link">
                    Already have an account? <a href="#" onclick="showLogin()">Sign in</a>
                </div>
            </div>

            <script>
                const form = document.getElementById('signupForm');
                const errorMessage = document.getElementById('errorMessage');
                const successMessage = document.getElementById('successMessage');
                const loading = document.getElementById('loading');
                const signupButton = document.getElementById('signupButton');

                // Form submission
                form.addEventListener('submit', async (e) => {
                    e.preventDefault();

                    // Clear previous messages
                    hideMessages();

                    // Get form data
                    const formData = new FormData(form);
                    const data = {
                        fullName: formData.get('fullName'),
                        email: formData.get('email'),
                        password: formData.get('password'),
                        terms: formData.get('terms')
                    };

                    // Validate form
                    if (!validateForm(data)) {
                        return;
                    }

                    // Show loading
                    showLoading();

                    try {
                        // Submit signup
                        const result = await submitSignup(data);

                        if (result.success) {
                            showSuccess('Account created successfully! Redirecting...');
                            setTimeout(() => {
                                window.close();
                            }, 1500);
                        } else {
                            showError(result.message || 'Account creation failed. Please try again.');
                        }
                    } catch (error) {
                        showError('Network error. Please check your connection and try again.');
                    } finally {
                        hideLoading();
                    }
                });

                // Form validation
                function validateForm(data) {
                    // Check required fields
                    if (!data.fullName || !data.email || !data.password) {
                        showError('All fields are required.');
                        return false;
                    }

                    // Check terms agreement
                    if (!data.terms) {
                        showError('You must agree to the Terms of Use and Privacy Policy.');
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
                                data.password
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
                    const passwordInput = document.getElementById('password');
                    const toggleButton = document.querySelector('.password-toggle');

                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggleButton.textContent = '🙈';
                    } else {
                        passwordInput.type = 'password';
                        toggleButton.textContent = '👁️';
                    }
                }

                // Message functions
                function showError(message) {
                    errorMessage.textContent = message;
                    errorMessage.style.display = 'block';
                }

                function showSuccess(message) {
                    successMessage.textContent = message;
                    successMessage.style.display = 'block';
                }

                function hideMessages() {
                    errorMessage.style.display = 'none';
                    successMessage.style.display = 'none';
                }

                function showLoading() {
                    loading.classList.add('show');
                    signupButton.disabled = true;
                }

                function hideLoading() {
                    loading.classList.remove('show');
                    signupButton.disabled = false;
                }

                // Navigation functions
                function showLogin() {
                    if (window.pywebview) {
                        window.pywebview.api.showLogin();
                    }
                    window.close();
                }

                function showTerms() {
                    if (window.pywebview) {
                        window.pywebview.api.showTerms();
                    }
                }

                function showPrivacy() {
                    if (window.pywebview) {
                        window.pywebview.api.showPrivacy();
                    }
                }

                function signInWithGoogle() {
                    if (window.pywebview) {
                        window.pywebview.api.signInWithGoogle();
                    }
                }

                function signInWithApple() {
                    if (window.pywebview) {
                        window.pywebview.api.signInWithApple();
                    }
                }
            </script>
        </body>
        </html>
        """

    def _apply_focus_management(self):
        """Apply focus management to ensure modal is visible."""
        try:
            import platform
            import time
            import subprocess

            if platform.system() == "Darwin":  # macOS
                # Use AppleScript to bring window to front
                script = '''
                tell application "System Events"
                    set frontmost of process "Python" to true
                    delay 0.2
                    set frontmost of process "Python" to true
                end tell
                '''

                # Run the script in the background
                subprocess.Popen(['osascript', '-e', script])
                logging.info("Applied macOS focus management for signup modal")

        except Exception as e:
            logging.warning(f"Could not apply focus management: {e}")

    def _handle_webview_events(self):
        """Handle WebView events and API calls."""
        try:
            # WebView events are handled through the HTML/JavaScript
            pass
        except Exception as e:
            logging.error(f"WebView event handling error: {e}")

    # API methods for JavaScript
    def showLogin(self):
        """Handle login request from JavaScript."""
        if self.on_login_request:
            self.on_login_request()

    def showTerms(self):
        """Show Terms of Use."""
        try:
            terms_path = self.base_dir / "docs" / "legal" / "CLEANHOUSE_TERMS_OF_SERVICE.md"
            if terms_path.exists():
                with open(terms_path, 'r') as f:
                    content = f.read()
                    # Show in a simple alert for now
                    # In production, you'd show this in a proper modal
                    messagebox.showinfo("Terms of Use", content[:500] + "...")
            else:
                messagebox.showinfo("Terms of Use", "Terms of Use will be displayed here.")
        except Exception as e:
            logging.error(f"Error showing terms: {e}")
            messagebox.showinfo("Terms of Use", "Terms of Use will be displayed here.")

    def showPrivacy(self):
        """Show Privacy Policy."""
        try:
            privacy_path = self.base_dir / "docs" / "legal" / "CLEANHOUSE_PRIVACY_NOTICE.md"
            if privacy_path.exists():
                with open(privacy_path, 'r') as f:
                    content = f.read()
                    # Show in a simple alert for now
                    # In production, you'd show this in a proper modal
                    messagebox.showinfo("Privacy Policy", content[:500] + "...")
            else:
                messagebox.showinfo("Privacy Policy", "Privacy Policy will be displayed here.")
        except Exception as e:
            logging.error(f"Error showing privacy policy: {e}")
            messagebox.showinfo("Privacy Policy", "Privacy Policy will be displayed here.")

    def signInWithGoogle(self):
        """Handle Google OAuth signup."""
        logging.info("Google OAuth signup requested")
        # Close signup and trigger OAuth flow
        if self.on_login_request:
            self.on_login_request()

    def signInWithApple(self):
        """Handle Apple OAuth signup."""
        logging.info("Apple OAuth signup requested")
        # Close signup and trigger OAuth flow
        if self.on_login_request:
            self.on_login_request()

    def createAccount(self, full_name: str, email: str, password: str) -> dict:
        """
        Create a new user account.

        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password

        Returns:
            dict: Result with success status and message
        """
        try:
            # Create user account using the auth system
            from .auth import AuthWindow

            # Create a temporary auth window for account creation
            auth_window = AuthWindow(None, self._on_account_created, str(self.base_dir))

            # Create the account
            success = auth_window.create_account(full_name, email, password)

            if success:
                return {"success": True, "message": "Account created successfully!"}
            else:
                return {"success": False, "message": "Account creation failed."}

        except Exception as e:
            logging.error(f"Account creation error: {e}")
            return {"success": False, "message": f"Account creation failed: {e}"}

    def _on_account_created(self, user_data: dict):
        """Handle successful account creation."""
        logging.info(f"Account created successfully: {user_data['email']}")

        # Call the success callback
        if self.on_success:
            self.on_success(user_data)

    def cleanup(self):
        """Clean up resources."""
        try:
            if self.signup_window:
                webview.destroy_window(self.signup_window)
            logging.info("Signup UI cleanup completed")
        except Exception as e:
            logging.error(f"Cleanup error: {e}")

    def force_cleanup(self):
        """Force cleanup of WebView processes."""
        try:
            import subprocess
            import platform

            if platform.system() == "Darwin":  # macOS
                subprocess.run(["pkill", "-f", "webview"], check=False)
            elif platform.system() == "Windows":
                subprocess.run(["taskkill", "/f", "/im", "webview.exe"], check=False)
            else:  # Linux
                subprocess.run(["pkill", "-f", "webview"], check=False)

        except Exception as e:
            logging.error(f"Force cleanup error: {e}")
