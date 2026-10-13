# CleanHouse Authentication Setup Guide

> **Superseded historical reference.** Do not implement this document. The canonical server-session architecture is [AUTHENTICATION_SYSTEM.md](AUTHENTICATION_SYSTEM.md).

**Date**: November 13, 2025  
**Status**: Complete Implementation Guide  
**Architecture**: Flask Backend + Vanilla JS Frontend + pywebview Desktop Wrapper

---

## Table of Contents

1. [Overview](#overview)
2. [Session Management](#session-management)
3. [OAuth Flow Completion](#oauth-flow-completion)
4. [Login/Signup Form Submission](#loginsignup-form-submission)
5. [Protected Routes/Pages](#protected-routespages)
6. [State Management](#state-management)
7. [Security Best Practices](#security-best-practices)
8. [Complete Code Examples](#complete-code-examples)
9. [Testing Checklist](#testing-checklist)

---

## Overview

This guide provides a complete authentication system for CleanHouse using:

- **Backend**: Flask with server-side sessions + JWT tokens for API authentication
- **Frontend**: Vanilla JavaScript with localStorage for client-side state
- **Desktop**: pywebview wrapper with secure session handling
- **User Storage**: Sharded file-based registry (VVAULT-style)

### Architecture Decision: Hybrid Session + JWT Approach

**Why Hybrid?**
- **Flask Sessions**: For server-side state (OAuth callbacks, CSRF protection)
- **JWT Tokens**: For stateless API authentication (mobile/desktop clients)
- **localStorage**: For client-side user state persistence

This provides:
- ✅ Secure server-side session management
- ✅ Stateless API authentication (scalable)
- ✅ Client-side state persistence (survives page reloads)
- ✅ Works with both browser and pywebview desktop app

---

## Session Management

### 1.1 Flask Session Configuration

**File**: `backend/__init__.py` or `backend/app.py`

```python
from flask import Flask
from flask_session import Session
import secrets
from pathlib import Path

def create_app():
    app = Flask(__name__)
    
    # Generate secret key for sessions
    secret_key = os.getenv('FLASK_SECRET_KEY')
    if not secret_key:
        # Generate and store secret key (first run)
        secret_key_file = Path.home() / '.cleanhouse' / '.flask_secret_key'
        if secret_key_file.exists():
            secret_key = secret_key_file.read_text().strip()
        else:
            secret_key = secrets.token_hex(32)
            secret_key_file.parent.mkdir(parents=True, exist_ok=True)
            secret_key_file.write_text(secret_key)
    
    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_TYPE'] = 'filesystem'  # Store sessions on disk
    app.config['SESSION_FILE_DIR'] = str(Path.home() / '.cleanhouse' / 'sessions')
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_NAME'] = 'cleanhouse_session'
    
    # Initialize Flask-Session
    Session(app)
    
    return app
```

### 1.2 JWT Token Generation

**File**: `backend/utils/jwt_utils.py` (new file)

```python
import jwt
import secrets
from datetime import datetime, timedelta
from pathlib import Path
import os

# JWT configuration
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY') or secrets.token_hex(32)
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

def generate_jwt_token(user_data: dict) -> str:
    """
    Generate JWT token for authenticated user.
    
    Args:
        user_data: Dictionary containing user information (user_id, email, etc.)
        
    Returns:
        str: JWT token
    """
    payload = {
        'user_id': user_data.get('user_id'),
        'email': user_data.get('email'),
        'full_name': user_data.get('full_name'),
        'role': user_data.get('role', 'user'),
        'iat': datetime.utcnow(),  # Issued at
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)  # Expiration
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token

def verify_jwt_token(token: str) -> dict:
    """
    Verify and decode JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded payload if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Invalid token

def get_user_from_token(token: str) -> dict:
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
            'user_id': payload.get('user_id'),
            'email': payload.get('email'),
            'full_name': payload.get('full_name'),
            'role': payload.get('role', 'user')
        }
    return None
```

### 1.3 Updated Auth Endpoints with JWT

**File**: `backend/api/auth.py` (updated)

```python
from flask import Blueprint, request, jsonify, redirect, session, url_for
from backend.utils.jwt_utils import generate_jwt_token, verify_jwt_token, get_user_from_token
import logging

bp = Blueprint('auth', __name__)

@bp.route('/auth/login', methods=['POST'])
def login():
    """Authenticate user and return JWT token"""
    try:
        data = request.get_json()
        email = data.get('email', '')
        password = data.get('password', '')
        
        user_service = get_user_service()
        user = user_service.authenticate_user(email, password)
        
        if user:
            # Create user data dictionary
            user_data = {
                'user_id': user.user_id or str(user.id),
                'email': user.email,
                'full_name': user.full_name,
                'role': getattr(user, 'role', 'user')
            }
            
            # Generate JWT token
            jwt_token = generate_jwt_token(user_data)
            
            # Store user in Flask session (for server-side state)
            session['user_id'] = user_data['user_id']
            session['email'] = user_data['email']
            session['authenticated'] = True
            
            return jsonify({
                'success': True,
                'message': 'Login successful!',
                'token': jwt_token,  # JWT token for API calls
                'user': user_data
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

@bp.route('/auth/createAccount', methods=['POST'])
def create_account():
    """Create new user account and return JWT token"""
    try:
        data = request.get_json()
        
        full_name = data.get('fullName', '')
        email = data.get('email', '')
        password = data.get('password', '')
        role = data.get('role', 'user')
        
        user_service = get_user_service()
        
        # Create user
        user = user_service.create_user(
            full_name=full_name,
            email=email,
            password=password,
            role=role
        )
        
        # Create user data dictionary
        user_data = {
            'user_id': user.user_id or str(user.id),
            'email': user.email,
            'full_name': user.full_name,
            'role': getattr(user, 'role', 'user')
        }
        
        # Generate JWT token
        jwt_token = generate_jwt_token(user_data)
        
        # Store user in Flask session
        session['user_id'] = user_data['user_id']
        session['email'] = user_data['email']
        session['authenticated'] = True
        
        return jsonify({
            'success': True,
            'message': 'Account created successfully!',
            'token': jwt_token,  # JWT token for API calls
            'user': user_data
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

@bp.route('/auth/me', methods=['GET'])
def get_current_user():
    """Get current authenticated user"""
    # Try JWT token first (from Authorization header)
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        user_data = get_user_from_token(token)
        if user_data:
            return jsonify({
                'success': True,
                'user': user_data
            })
    
    # Fallback to Flask session
    if session.get('authenticated'):
        return jsonify({
            'success': True,
            'user': {
                'user_id': session.get('user_id'),
                'email': session.get('email'),
                'full_name': session.get('full_name', ''),
                'role': session.get('role', 'user')
            }
        })
    
    return jsonify({
        'success': False,
        'message': 'Not authenticated'
    }), 401

@bp.route('/auth/logout', methods=['POST'])
def logout():
    """Logout user and clear session"""
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    })

@bp.route('/auth/oauth/callback', methods=['GET', 'POST'])
def oauth_callback():
    """Handle OAuth callback - updated to return JWT token"""
    try:
        # ... existing OAuth callback code ...
        
        # After successful OAuth authentication:
        user_data = {
            'user_id': existing_user.user_id or str(existing_user.id),
            'email': existing_user.email,
            'full_name': existing_user.full_name,
            'role': getattr(existing_user, 'role', 'user')
        }
        
        # Generate JWT token
        jwt_token = generate_jwt_token(user_data)
        
        # Store in Flask session
        session['user_id'] = user_data['user_id']
        session['email'] = user_data['email']
        session['authenticated'] = True
        session['oauth_success'] = True
        session['oauth_token'] = jwt_token  # Store token in session for frontend retrieval
        
        # Redirect to login page with success indicator
        return redirect('/login?oauth_success=1')
        
    except Exception as e:
        logging.error(f"OAuth callback error: {e}", exc_info=True)
        return redirect('/login?error=' + urllib.parse.quote(str(e)))

@bp.route('/auth/oauth/user', methods=['GET'])
def oauth_user():
    """Get OAuth user data from session and return JWT token"""
    if session.get('oauth_success') and session.get('oauth_token'):
        token = session.pop('oauth_token')
        session.pop('oauth_success', None)
        
        # Get user data from token
        user_data = get_user_from_token(token)
        
        return jsonify({
            'success': True,
            'token': token,  # Return JWT token
            'user': user_data
        })
    else:
        return jsonify({
            'success': False,
            'message': 'No OAuth user data found'
        }), 404
```

---

## OAuth Flow Completion

### 2.1 Updated OAuth Callback Handler

The OAuth callback now:
1. Authenticates user via OAuth provider
2. Creates/updates user in database
3. Generates JWT token
4. Stores token in Flask session
5. Redirects to frontend with success indicator

### 2.2 Frontend OAuth Callback Handling

**File**: `frontend/js/auth.js` (updated)

```javascript
// Handle OAuth callback (check URL params)
async function handleOAuthCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const oauthSuccess = urlParams.get('oauth_success');
    const error = urlParams.get('error');
    
    if (oauthSuccess === '1') {
        console.log('[OAUTH] OAuth success detected in URL');
        
        try {
            // Fetch user data and JWT token from session
            const response = await fetch('/api/auth/oauth/user');
            const data = await response.json();
            
            if (data.success && data.user && data.token) {
                console.log('[OAUTH] User authenticated:', data.user.email);
                
                // Store JWT token and user data in localStorage
                localStorage.setItem('auth_token', data.token);
                localStorage.setItem('user', JSON.stringify(data.user));
                
                // Update auth state
                updateAuthState(data.user);
                
                showSuccess('Successfully authenticated! Welcome, ' + data.user.full_name);
                
                // Clear URL params
                window.history.replaceState({}, document.title, window.location.pathname);
                
                // Redirect to main app after short delay
                setTimeout(() => {
                    redirectToApp();
                }, 1500);
            } else {
                showError('OAuth authentication completed but failed to load user data.');
            }
        } catch (err) {
            console.error('[OAUTH] Error fetching user data:', err);
            showError('OAuth authentication completed but failed to load user data.');
        }
    } else if (error) {
        console.error('[OAUTH] OAuth error:', error);
        showError('OAuth authentication failed: ' + decodeURIComponent(error));
        window.history.replaceState({}, document.title, window.location.pathname);
    }
}

// Run OAuth callback handler when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', handleOAuthCallback);
} else {
    handleOAuthCallback();
}
```

---

## Login/Signup Form Submission

### 3.1 Updated Login Form Handler

**File**: `frontend/js/auth.js` (updated)

```javascript
// Form submission
const loginForm = document.getElementById('login-form');
if (loginForm) {
    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        
        if (!email || !password) {
            showError('Please fill in all fields.');
            return;
        }
        
        showLoading(true);
        
        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ email, password })
            });
            
            const data = await response.json();
            
            if (data.success && data.user && data.token) {
                // Store JWT token and user data
                localStorage.setItem('auth_token', data.token);
                localStorage.setItem('user', JSON.stringify(data.user));
                
                // Update auth state
                updateAuthState(data.user);
                
                showSuccess('Login successful! Welcome, ' + data.user.full_name);
                
                // Redirect to main app after short delay
                setTimeout(() => {
                    redirectToApp();
                }, 1500);
            } else {
                showError(data.message || 'Invalid email or password.');
                showLoading(false);
            }
        } catch (error) {
            console.error('[LOGIN] API error:', error);
            showError('Login failed. Please try again.');
            showLoading(false);
        }
    });
}
```

### 3.2 Signup Form Handler

**File**: `frontend/js/auth.js` (add to existing file)

```javascript
// Signup form submission
const signupForm = document.getElementById('signupForm');
if (signupForm) {
    signupForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const fullName = document.getElementById('fullName').value;
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        const confirmPassword = document.getElementById('confirmPassword').value;
        
        // Validation
        if (!fullName || !email || !password || !confirmPassword) {
            showError('Please fill in all fields.');
            return;
        }
        
        if (password !== confirmPassword) {
            showError('Passwords do not match.');
            return;
        }
        
        if (password.length < 8) {
            showError('Password must be at least 8 characters long.');
            return;
        }
        
        // Check terms checkbox
        const termsCheckbox = document.getElementById('terms');
        if (termsCheckbox && !termsCheckbox.checked) {
            showError('Please accept the terms and conditions.');
            return;
        }
        
        showLoading(true);
        
        try {
            const response = await fetch('/api/auth/createAccount', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    fullName: fullName,
                    email: email,
                    password: password,
                    role: 'user'
                })
            });
            
            const data = await response.json();
            
            if (data.success && data.user && data.token) {
                // Store JWT token and user data
                localStorage.setItem('auth_token', data.token);
                localStorage.setItem('user', JSON.stringify(data.user));
                
                // Update auth state
                updateAuthState(data.user);
                
                showSuccess('Account created successfully! Welcome, ' + data.user.full_name);
                
                // Redirect to main app after short delay
                setTimeout(() => {
                    redirectToApp();
                }, 1500);
            } else {
                showError(data.message || 'Account creation failed.');
                showLoading(false);
            }
        } catch (error) {
            console.error('[SIGNUP] API error:', error);
            showError('Account creation failed. Please try again.');
            showLoading(false);
        }
    });
}
```

---

## Protected Routes/Pages

### 4.1 Auth State Management Module

**File**: `frontend/js/auth-state.js` (new file)

```javascript
/**
 * Authentication State Management
 * Handles user authentication state, token management, and protected route access
 */

class AuthState {
    constructor() {
        this.user = null;
        this.token = null;
        this.initialized = false;
    }
    
    /**
     * Initialize auth state from localStorage
     */
    init() {
        if (this.initialized) return;
        
        // Load token and user from localStorage
        this.token = localStorage.getItem('auth_token');
        const userStr = localStorage.getItem('user');
        
        if (userStr) {
            try {
                this.user = JSON.parse(userStr);
            } catch (e) {
                console.error('[AUTH] Failed to parse user data:', e);
                this.clear();
            }
        }
        
        // Verify token is still valid
        if (this.token) {
            this.verifyToken();
        }
        
        this.initialized = true;
    }
    
    /**
     * Verify JWT token is still valid
     */
    async verifyToken() {
        if (!this.token) {
            this.clear();
            return false;
        }
        
        try {
            const response = await fetch('/api/auth/me', {
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success && data.user) {
                    this.user = data.user;
                    localStorage.setItem('user', JSON.stringify(data.user));
                    return true;
                }
            }
        } catch (error) {
            console.error('[AUTH] Token verification failed:', error);
        }
        
        // Token invalid or expired
        this.clear();
        return false;
    }
    
    /**
     * Check if user is authenticated
     */
    isAuthenticated() {
        return this.user !== null && this.token !== null;
    }
    
    /**
     * Get current user
     */
    getUser() {
        return this.user;
    }
    
    /**
     * Get auth token
     */
    getToken() {
        return this.token;
    }
    
    /**
     * Set authenticated user
     */
    setUser(user, token) {
        this.user = user;
        this.token = token;
        localStorage.setItem('auth_token', token);
        localStorage.setItem('user', JSON.stringify(user));
    }
    
    /**
     * Clear authentication state
     */
    clear() {
        this.user = null;
        this.token = null;
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user');
    }
    
    /**
     * Logout user
     */
    async logout() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`
                }
            });
        } catch (error) {
            console.error('[AUTH] Logout error:', error);
        }
        
        this.clear();
    }
}

// Global auth state instance
const authState = new AuthState();

// Initialize on load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => authState.init());
} else {
    authState.init();
}

// Export for use in other scripts
window.authState = authState;
```

### 4.2 Protected Route Middleware

**File**: `frontend/js/protected-routes.js` (new file)

```javascript
/**
 * Protected Routes Handler
 * Redirects unauthenticated users to login page
 */

// List of protected routes (paths that require authentication)
const PROTECTED_ROUTES = [
    '/dashboard',
    '/settings',
    '/scan',
    '/results',
    '/logs'
];

// List of public routes (paths that don't require authentication)
const PUBLIC_ROUTES = [
    '/login',
    '/signup',
    '/'
];

/**
 * Check if current route requires authentication
 */
function isProtectedRoute(path) {
    return PROTECTED_ROUTES.some(route => path.startsWith(route));
}

/**
 * Check if current route is public
 */
function isPublicRoute(path) {
    return PUBLIC_ROUTES.some(route => path === route || path.startsWith(route));
}

/**
 * Protect route - redirect to login if not authenticated
 */
function protectRoute() {
    const currentPath = window.location.pathname;
    
    // Skip protection for public routes
    if (isPublicRoute(currentPath)) {
        return;
    }
    
    // Check if route is protected
    if (isProtectedRoute(currentPath)) {
        // Verify authentication
        if (!authState.isAuthenticated()) {
            console.log('[AUTH] Protected route accessed without authentication, redirecting to login');
            window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
            return false;
        }
        
        // Verify token is still valid
        authState.verifyToken().then(isValid => {
            if (!isValid) {
                console.log('[AUTH] Token expired, redirecting to login');
                window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
            }
        });
    }
    
    return true;
}

/**
 * Redirect authenticated users away from login/signup pages
 */
function redirectIfAuthenticated() {
    const currentPath = window.location.pathname;
    
    if (isPublicRoute(currentPath) && authState.isAuthenticated()) {
        // Check for redirect parameter
        const urlParams = new URLSearchParams(window.location.search);
        const redirect = urlParams.get('redirect');
        
        if (redirect) {
            window.location.href = redirect;
        } else {
            window.location.href = '/dashboard';
        }
    }
}

// Run protection on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        protectRoute();
        redirectIfAuthenticated();
    });
} else {
    protectRoute();
    redirectIfAuthenticated();
}

// Export functions
window.protectRoute = protectRoute;
window.redirectIfAuthenticated = redirectIfAuthenticated;
```

### 4.3 Update HTML Files to Include Scripts

**File**: `frontend/login.html` (add before closing `</body>`)

```html
<!-- Auth state management -->
<script src="js/auth-state.js"></script>
<!-- Protected routes -->
<script src="js/protected-routes.js"></script>
<!-- Auth handlers -->
<script src="js/auth.js"></script>
```

**File**: `frontend/signup.html` (add before closing `</body>`)

```html
<!-- Auth state management -->
<script src="js/auth-state.js"></script>
<!-- Protected routes -->
<script src="js/protected-routes.js"></script>
<!-- Auth handlers -->
<script src="js/auth.js"></script>
```

---

## State Management

### 5.1 Update Auth State Functions

**File**: `frontend/js/auth.js` (add these helper functions)

```javascript
/**
 * Update authentication state after login/signup
 */
function updateAuthState(user) {
    if (window.authState) {
        window.authState.setUser(user, localStorage.getItem('auth_token'));
    }
}

/**
 * Redirect to main app after successful authentication
 */
function redirectToApp() {
    // Check for redirect parameter
    const urlParams = new URLSearchParams(window.location.search);
    const redirect = urlParams.get('redirect');
    
    if (redirect) {
        window.location.href = redirect;
    } else {
        // Default redirect to dashboard
        window.location.href = '/dashboard';
    }
}

/**
 * Check authentication status on page load
 */
function checkAuthStatus() {
    if (window.authState && window.authState.isAuthenticated()) {
        // User is authenticated, update UI
        const user = window.authState.getUser();
        console.log('[AUTH] User authenticated:', user.email);
        
        // Update UI elements (e.g., show user name, logout button)
        updateUserUI(user);
    } else {
        // User not authenticated
        console.log('[AUTH] User not authenticated');
    }
}

/**
 * Update UI with user information
 */
function updateUserUI(user) {
    // Update user name display
    const userNameElements = document.querySelectorAll('.user-name');
    userNameElements.forEach(el => {
        el.textContent = user.full_name || user.email;
    });
    
    // Update user email display
    const userEmailElements = document.querySelectorAll('.user-email');
    userEmailElements.forEach(el => {
        el.textContent = user.email;
    });
    
    // Show/hide authenticated elements
    const authElements = document.querySelectorAll('.auth-required');
    authElements.forEach(el => {
        el.style.display = '';
    });
    
    const unauthElements = document.querySelectorAll('.auth-not-required');
    unauthElements.forEach(el => {
        el.style.display = 'none';
    });
}

// Check auth status on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkAuthStatus);
} else {
    checkAuthStatus();
}
```

### 5.2 API Client with Auth Headers

**File**: `frontend/js/api-client.js` (update existing file)

```javascript
/**
 * API Client with automatic authentication headers
 */

class APIClient {
    constructor() {
        this.baseURL = '/api';
    }
    
    /**
     * Get authentication headers
     */
    getAuthHeaders() {
        const headers = {
            'Content-Type': 'application/json'
        };
        
        // Add JWT token if available
        if (window.authState && window.authState.getToken()) {
            headers['Authorization'] = `Bearer ${window.authState.getToken()}`;
        }
        
        return headers;
    }
    
    /**
     * Make authenticated API request
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        
        const config = {
            ...options,
            headers: {
                ...this.getAuthHeaders(),
                ...(options.headers || {})
            }
        };
        
        try {
            const response = await fetch(url, config);
            
            // Handle 401 Unauthorized (token expired)
            if (response.status === 401) {
                console.log('[API] Unauthorized, clearing auth state');
                if (window.authState) {
                    window.authState.clear();
                }
                window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                return null;
            }
            
            const data = await response.json();
            return data;
        } catch (error) {
            console.error('[API] Request failed:', error);
            throw error;
        }
    }
    
    /**
     * GET request
     */
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    }
    
    /**
     * POST request
     */
    async post(endpoint, body) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(body)
        });
    }
    
    /**
     * PUT request
     */
    async put(endpoint, body) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(body)
        });
    }
    
    /**
     * DELETE request
     */
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
}

// Global API client instance
const apiClient = new APIClient();
window.apiClient = apiClient;
```

---

## Security Best Practices

### 6.1 CSRF Protection

**File**: `backend/utils/csrf.py` (new file)

```python
import secrets
from flask import session, request, abort

def generate_csrf_token():
    """Generate CSRF token and store in session"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

def validate_csrf_token(token):
    """Validate CSRF token"""
    if 'csrf_token' not in session:
        return False
    return secrets.compare_digest(session['csrf_token'], token)

def csrf_protect():
    """Decorator to protect routes with CSRF validation"""
    def decorator(f):
        def wrapper(*args, **kwargs):
            if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
                token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
                if not token or not validate_csrf_token(token):
                    abort(403, description='CSRF token validation failed')
            return f(*args, **kwargs)
        return wrapper
    return decorator
```

**File**: `backend/api/auth.py` (add CSRF protection)

```python
from backend.utils.csrf import csrf_protect, generate_csrf_token

@bp.route('/auth/csrf-token', methods=['GET'])
def get_csrf_token():
    """Get CSRF token for forms"""
    return jsonify({
        'csrf_token': generate_csrf_token()
    })

@bp.route('/auth/createAccount', methods=['POST'])
@csrf_protect()
def create_account():
    # ... existing code ...
```

### 6.2 Password Security

**Already implemented**:
- ✅ bcrypt password hashing (in `UserService`)
- ✅ Password length validation (minimum 8 characters)
- ✅ Password never sent in error messages

**Additional recommendations**:
- Rate limiting on login attempts
- Account lockout after failed attempts
- Password strength requirements

### 6.3 Token Security

**JWT Token Security**:
- ✅ Tokens expire after 7 days
- ✅ Tokens stored in localStorage (not cookies) for desktop app compatibility
- ✅ Tokens verified on each API request
- ✅ Tokens cleared on logout

**Additional recommendations**:
- Implement token refresh mechanism
- Store tokens in httpOnly cookies for web version (optional)
- Use secure random secret keys

### 6.4 Session Security

**Flask Session Security**:
- ✅ Secret key stored securely
- ✅ HttpOnly cookies
- ✅ SameSite cookie protection
- ✅ Session expiration

---

## Complete Code Examples

### 7.1 Updated Login Flow

**Complete flow**:
1. User submits login form
2. Frontend sends credentials to `/api/auth/login`
3. Backend validates credentials
4. Backend generates JWT token
5. Backend stores user in Flask session
6. Backend returns JWT token and user data
7. Frontend stores token and user in localStorage
8. Frontend updates auth state
9. Frontend redirects to dashboard

### 7.2 Updated OAuth Flow

**Complete flow**:
1. User clicks OAuth button
2. Frontend redirects to `/api/auth/oauth/<provider>`
3. Backend redirects to OAuth provider
4. User authenticates with provider
5. Provider redirects to `/api/auth/oauth/callback`
6. Backend exchanges code for token
7. Backend gets user info from provider
8. Backend creates/updates user
9. Backend generates JWT token
10. Backend stores token in Flask session
11. Backend redirects to `/login?oauth_success=1`
12. Frontend detects success parameter
13. Frontend fetches token from `/api/auth/oauth/user`
14. Frontend stores token and user in localStorage
15. Frontend updates auth state
16. Frontend redirects to dashboard

---

## Testing Checklist

### 8.1 Authentication Tests

- [ ] Login with valid credentials
- [ ] Login with invalid credentials
- [ ] Signup with valid data
- [ ] Signup with duplicate email
- [ ] Signup with weak password
- [ ] OAuth login (Google, Microsoft, GitHub, Apple)
- [ ] OAuth callback handling
- [ ] Token expiration handling
- [ ] Logout functionality
- [ ] Session persistence across page reloads

### 8.2 Protected Routes Tests

- [ ] Access protected route without authentication → redirect to login
- [ ] Access protected route with valid token → allow access
- [ ] Access protected route with expired token → redirect to login
- [ ] Access login page while authenticated → redirect to dashboard
- [ ] Redirect parameter handling

### 8.3 Security Tests

- [ ] CSRF token validation
- [ ] JWT token verification
- [ ] Password hashing verification
- [ ] Session expiration
- [ ] Token storage security

---

## Summary

This guide provides a complete authentication system for CleanHouse with:

1. **Session Management**: Flask sessions + JWT tokens
2. **OAuth Flow**: Complete OAuth integration with JWT tokens
3. **Form Handling**: Secure login/signup form submission
4. **Protected Routes**: Automatic route protection and redirection
5. **State Management**: Client-side auth state with localStorage
6. **Security**: CSRF protection, secure password hashing, token management

**Next Steps**:
1. Implement the code changes in your codebase
2. Test all authentication flows
3. Add rate limiting for production
4. Configure HTTPS for production deployment
5. Add monitoring and logging for security events

---

**End of Guide**

