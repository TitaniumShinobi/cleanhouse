/**
 * Authentication State Management
 * Handles user authentication state, token management, and protected route access
 */

class AuthState {
    constructor() {
        this.user = null;
        this.token = null;
        this.initialized = false;
        this.ready = null;
    }
    
    /**
     * Initialize auth state from the HttpOnly server session.
     */
    init() {
        if (this.ready) return this.ready;
        this.ready = this.verifyToken();
        this.initialized = true;
        return this.ready;
    }
    
    /**
     * Verify JWT token is still valid
     */
    async verifyToken() {
        try {
            const response = await fetch('/api/auth/me', {
                credentials: 'include',
                headers: { 'Accept': 'application/json' }
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success && data.user) {
                    this.user = data.user;
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
        return this.user !== null;
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
        this.token = null;
    }
    
    /**
     * Clear authentication state
     */
    clear() {
        this.user = null;
        this.token = null;
    }
    
    /**
     * Logout user
     */
    async logout() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'include'
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
