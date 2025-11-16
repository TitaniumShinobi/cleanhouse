/**
 * CleanHouse API Client
 * Supports both pywebview (desktop) and HTTP fetch (browser) modes
 */

// Detect environment
const IS_PYWEBVIEW = typeof window !== 'undefined' && 
                     window.pywebview && 
                     window.pywebview.api;

const API_BASE_URL = IS_PYWEBVIEW ? null : 'http://127.0.0.1:5000/api';

console.log('[API] Environment detected:', IS_PYWEBVIEW ? 'pywebview (desktop)' : 'browser (web)');

/**
 * API Client - routes calls to pywebview or HTTP fetch
 */
const API = {
    /**
     * Create account
     */
    async createAccount(fullName, email, password, role, turnstileToken = '') {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.createAccount(fullName, email, password, role, turnstileToken);
        } else {
            const response = await fetch(`${API_BASE_URL}/auth/createAccount`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fullName, email, password, role, turnstileToken })
            });
            return await response.json();
        }
    },

    /**
     * Login
     */
    async login(email, password) {
        if (IS_PYWEBVIEW) {
            // For desktop, we'd need to add a login method to the API wrapper
            // For now, return error
            return { success: false, message: 'Login via pywebview not yet implemented' };
        } else {
            const response = await fetch(`${API_BASE_URL}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            return await response.json();
        }
    },

    /**
     * Open OAuth URL
     */
    openOAuthUrl(url, provider) {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.openOAuthUrl(url, provider);
        } else {
            // For web, we need to implement OAuth differently
            // For now, open in same window
            const oauthUrl = `/api/auth/oauth/${provider}`;
            window.location.href = oauthUrl;
            return { success: true, message: `Opening ${provider} authentication...` };
        }
    },

    /**
     * Show login page
     */
    showLogin() {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.showLogin();
        } else {
            window.location.href = '/login';
            return { success: true };
        }
    },

    /**
     * Show signup page
     */
    showSignup() {
        if (IS_PYWEBVIEW) {
            return window.pywebview.api.showSignup();
        } else {
            window.location.href = '/signup';
            return { success: true };
        }
    },

    /**
     * Logging functions (optional, for debugging)
     */
    log(message, level = 'INFO') {
        if (IS_PYWEBVIEW && window.pywebview.api.log) {
            return window.pywebview.api.log(message, level);
        } else {
            console.log(`[${level}] ${message}`);
            return { success: true };
        }
    },

    logClick(elementType, details) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_click) {
            return window.pywebview.api.log_click(elementType, details);
        } else {
            console.log(`[CLICK] ${elementType}: ${details}`);
            return { success: true };
        }
    },

    logInput(fieldName, fieldType, charCount) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_input) {
            return window.pywebview.api.log_input(fieldName, fieldType, charCount);
        } else {
            console.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
            return { success: true };
        }
    },

    logFocus(fieldName) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_focus) {
            return window.pywebview.api.log_focus(fieldName);
        } else {
            console.log(`[FOCUS] Field "${fieldName}" focused`);
            return { success: true };
        }
    },

    logBlur(fieldName) {
        if (IS_PYWEBVIEW && window.pywebview.api.log_blur) {
            return window.pywebview.api.log_blur(fieldName);
        } else {
            console.log(`[BLUR] Field "${fieldName}" blurred`);
            return { success: true };
        }
    }
};

// Export for use in other scripts
if (typeof window !== 'undefined') {
    window.CleanHouseAPI = API;
}

