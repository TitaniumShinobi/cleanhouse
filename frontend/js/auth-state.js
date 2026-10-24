/**
 * Authentication State Management
 * Handles opaque device-session state and protected route access.
 */

class AuthState {
    constructor() {
        this.user = null;
        this.initialized = false;
        this.ready = null;
    }
    
    /**
     * Initialize auth state from the HttpOnly server session.
     */
    init() {
        if (this.ready) return this.ready;
        this.ready = this.verifySession();
        this.initialized = true;
        return this.ready;
    }
    
    /**
     * Verify the HttpOnly device session through the canonical identity route.
     */
    async verifySession() {
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
            console.error('[AUTH] Session verification failed:', error);
        }
        
        // Session invalid or expired.
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
     * Update the in-memory user projection after a server-authenticated flow.
     */
    setUser(user) {
        this.user = user;
    }
    
    /**
     * Clear authentication state
     */
    clear() {
        this.user = null;
    }
    
    /**
     * Logout user
     */
    async logout() {
        const csrfResponse = await fetch('/api/auth/csrf', {
            credentials: 'include', headers: { 'Accept': 'application/json' }
        });
        if (!csrfResponse.ok) throw new Error('Sign out failed. Try again.');
        const csrfPayload = await csrfResponse.json();
        const response = await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include',
            headers: { 'X-CSRF-Token': csrfPayload.csrfToken || '' }
        });
        if (!response.ok) throw new Error('Sign out failed. Try again.');
        const result = await response.json();
        if (result.success !== true) throw new Error('Sign out failed. Try again.');
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
