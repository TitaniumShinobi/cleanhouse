# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - ui/signup_webview.py
#  WebView-based user signup with email/password
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import webview
import logging
import signal
import sys
from typing import Callable, Optional, Dict, Any
from pathlib import Path
from tkinter import messagebox

# Import our new user management system
from models import User, UserService, DatabaseManager

class SignupWebView:
    """
    WebView-based user signup with email/password registration.
    Provides a clean, modern signup interface matching industry standards.
    """
    
    def __init__(self, parent, on_success: Callable, base_dir: str = None):
        self.parent = parent
        self.on_success = on_success
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.auth_window = None
        
        # Initialize user service
        self.db_manager = DatabaseManager()
        self.user_service = UserService(db_manager=self.db_manager)
        
        # Set up signal handling for WebView auth
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Set up signal handlers for WebView authentication."""
        def signal_handler(signum, frame):
            """Handle SIGINT (Ctrl+C) during WebView authentication."""
            print(f"\n🛑 CleanHouse signup received signal {signum}, cleaning up...")
            logging.info(f"Received signal {signum} during signup authentication")
            
            # Clean up WebView processes
            try:
                self.cleanup()
            except Exception as e:
                logging.error(f"Error during signup cleanup: {e}")
            
            # Force exit
            print("✅ CleanHouse signup terminated.")
            sys.exit(0)
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logging.info("Signal handlers set up for signup authentication")
    
    def show_signup(self):
        """Show WebView-based signup form."""
        try:
            # Create HTML signup page
            html_content = self._create_signup_html()
            
            # Show WebView window with normal window behavior
            self.auth_window = webview.create_window(
                title='CleanHouse - Create Account',
                html=html_content,
                width=500,
                height=700,
                resizable=False
            )
            
            # Start WebView with normal behavior
            webview.start(
                self._handle_webview_events,
                debug=False,
                private_mode=False
            )
            
        except Exception as e:
            logging.error(f"WebView signup error: {e}")
            messagebox.showerror("Error", f"Failed to start signup: {e}")
    
    def _create_signup_html(self) -> str:
        """Create HTML signup page with modern styling."""
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
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 20px;
                }
                
                .signup-container {
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
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
                
                .logo {
                    text-align: center;
                    margin-bottom: 30px;
                }
                
                .logo h1 {
                    color: #333;
                    font-size: 28px;
                    font-weight: 700;
                    margin-bottom: 8px;
                }
                
                .logo p {
                    color: #666;
                    font-size: 14px;
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
                
                .form-group input {
                    width: 100%;
                    padding: 12px 16px;
                    border: 2px solid #e1e5e9;
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
                
                .form-group input.error {
                    border-color: #e74c3c;
                    background: #fdf2f2;
                }
                
                .password-requirements {
                    font-size: 12px;
                    color: #666;
                    margin-top: 4px;
                }
                
                .signup-button {
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
                    margin-top: 10px;
                }
                
                .signup-button:hover {
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
                    margin-top: 20px;
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
                    padding: 12px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                }
                
                .success-message {
                    background: #f0f9ff;
                    color: #0369a1;
                    padding: 12px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    font-size: 14px;
                    display: none;
                }
                
                .loading {
                    display: none;
                    text-align: center;
                    color: #666;
                    font-size: 14px;
                }
                
                .loading.show {
                    display: block;
                }
                
                .terms-privacy {
                    margin-top: 20px;
                    font-size: 12px;
                    color: #666;
                    text-align: center;
                    line-height: 1.4;
                }
                
                .terms-privacy a {
                    color: #667eea;
                    text-decoration: none;
                }
                
                .terms-privacy a:hover {
                    text-decoration: underline;
                }
            </style>
        </head>
        <body>
            <div class="signup-container">
                <div class="logo">
                    <h1>🏠 CleanHouse</h1>
                    <p>Create your account to get started</p>
                </div>
                
                <div class="error-message" id="errorMessage"></div>
                <div class="success-message" id="successMessage"></div>
                <div class="loading" id="loading">Creating your account...</div>
                
                <form id="signupForm">
                    <div class="form-group">
                        <label for="fullName">Full Name</label>
                        <input type="text" id="fullName" name="fullName" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="email">Email Address</label>
                        <input type="email" id="email" name="email" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" name="password" required>
                        <div class="password-requirements">
                            Must be at least 8 characters long
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="confirmPassword">Confirm Password</label>
                        <input type="password" id="confirmPassword" name="confirmPassword" required>
                    </div>
                    
                    <button type="submit" class="signup-button" id="signupButton">
                        Create Account
                    </button>
                </form>
                
                <div class="login-link">
                    Already have an account? <a href="#" onclick="showLogin()">Sign in</a>
                </div>
                
                <div class="terms-privacy">
                    By creating an account, you agree to our 
                    <a href="#" onclick="showTerms()">Terms of Use</a> and 
                    <a href="#" onclick="showPrivacy()">Privacy Policy</a>
                </div>
            </div>
            
            <script>
                const form = document.getElementById('signupForm');
                const errorMessage = document.getElementById('errorMessage');
                const successMessage = document.getElementById('successMessage');
                const loading = document.getElementById('loading');
                const signupButton = document.getElementById('signupButton');
                
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
                        confirmPassword: formData.get('confirmPassword')
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
                            showError(result.message || 'Signup failed. Please try again.');
                        }
                    } catch (error) {
                        showError('Network error. Please check your connection and try again.');
                    } finally {
                        hideLoading();
                    }
                });
                
                function validateForm(data) {
                    // Check required fields
                    if (!data.fullName || !data.email || !data.password || !data.confirmPassword) {
                        showError('All fields are required.');
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
                
                async function submitSignup(data) {
                    // Simulate API call - in real implementation, this would call your backend
                    return new Promise((resolve) => {
                        setTimeout(() => {
                            // For now, just simulate success
                            // In real implementation, you'd call your user service here
                            resolve({ success: true, message: 'Account created successfully!' });
                        }, 1000);
                    });
                }
                
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
                
                function showLogin() {
                    // Close signup and show login
                    window.close();
                }
                
                function showTerms() {
                    alert('Terms of Use will be displayed here.');
                }
                
                function showPrivacy() {
                    alert('Privacy Policy will be displayed here.');
                }
            </script>
        </body>
        </html>
        """
    
    def _handle_webview_events(self):
        """Handle WebView events."""
        try:
            # WebView events are handled through the HTML/JavaScript
            # The signup form will call back to this class when successful
            pass
        except Exception as e:
            logging.error(f"WebView event handling error: {e}")
    
    def cleanup(self):
        """Clean up resources."""
        try:
            if self.auth_window:
                webview.destroy_window(self.auth_window)
            logging.info("WebView signup cleanup completed")
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
