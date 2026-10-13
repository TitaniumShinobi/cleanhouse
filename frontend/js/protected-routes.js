/**
 * Protected Routes Handler
 * Redirects unauthenticated users to login page
 */

// List of protected routes (paths that require authentication)
const PROTECTED_ROUTES = [
    '/overview',
    '/advanced',
    '/zaelith',
    '/zaelith/connect',
    '/identity',
    '/reports',
    '/help',
    '/settings',
    '/scan',
    '/results',
    '/logs'
];

// List of public routes (paths that don't require authentication)
const PUBLIC_ROUTES = [
    '/login',
    '/signup',
    '/account-recovery',
    '/password-reset',
    '/'
];

/**
 * Match an exact route or one of its child paths without treating `/` as a
 * prefix for every page in the application.
 */
function matchesRoute(path, route) {
    if (route === '/') {
        return path === '/';
    }
    return path === route || path.startsWith(route + '/');
}

/**
 * Check if current route requires authentication
 */
function isProtectedRoute(path) {
    return PROTECTED_ROUTES.some(route => matchesRoute(path, route));
}

/**
 * Check if current route is public
 */
function isPublicRoute(path) {
    return PUBLIC_ROUTES.some(route => matchesRoute(path, route));
}

/**
 * Protect route - redirect to login if not authenticated
 */
async function protectRoute() {
    const currentPath = window.location.pathname;
    
    // Skip protection for public routes
    if (isPublicRoute(currentPath)) {
        return;
    }
    
    // Check if route is protected
    if (isProtectedRoute(currentPath)) {
        if (window.authState) await window.authState.init();
        if (!window.authState || !window.authState.isAuthenticated()) {
            console.log('[AUTH] Protected route accessed without authentication, redirecting to login');
            window.location.href = '/login?redirect=' + encodeURIComponent(currentPath);
            return false;
        }
        
    }
    
    return true;
}

/**
 * Redirect authenticated users away from login/signup pages
 */
async function redirectIfAuthenticated() {
    const currentPath = window.location.pathname;
    
    if (window.authState) await window.authState.init();
    if (isPublicRoute(currentPath) && window.authState && window.authState.isAuthenticated()) {
        // Check for redirect parameter
        const urlParams = new URLSearchParams(window.location.search);
        const redirect = urlParams.get('redirect');
        
        if (redirect) {
            window.location.href = redirect;
        } else {
            window.location.href = '/overview';
        }
    }
}

// Run protection on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        protectRoute().then(() => redirectIfAuthenticated());
    });
} else {
    protectRoute().then(() => redirectIfAuthenticated());
}

// Export functions
window.protectRoute = protectRoute;
window.redirectIfAuthenticated = redirectIfAuthenticated;
