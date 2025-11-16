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

