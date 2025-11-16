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
        if (!window.authState || !window.authState.isAuthenticated()) {
            console.log('[AUTH] Protected route accessed without authentication, redirecting to login');
            window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
            return false;
        }
        
        // Verify token is still valid
        if (window.authState) {
            window.authState.verifyToken().then(isValid => {
                if (!isValid) {
                    console.log('[AUTH] Token expired, redirecting to login');
                    window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
                }
            });
        }
    }
    
    return true;
}

/**
 * Redirect authenticated users away from login/signup pages
 */
function redirectIfAuthenticated() {
    const currentPath = window.location.pathname;
    
    if (isPublicRoute(currentPath) && window.authState && window.authState.isAuthenticated()) {
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

