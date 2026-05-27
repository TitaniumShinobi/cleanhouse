// Debug: Log script loading
                console.log('[CLEANHOUSE] Script loaded');
                console.log('[CLEANHOUSE] window.pywebview:', typeof window.pywebview !== 'undefined' ? 'exists' : 'undefined');
                console.log('[CLEANHOUSE] window.pywebview.api:', typeof window.pywebview?.api !== 'undefined' ? 'exists' : 'undefined');

                // Detect environment
                const IS_PYWEBVIEW = typeof window !== 'undefined' &&
                                     window.pywebview &&
                                     window.pywebview.api;
                const IS_BROWSER = !IS_PYWEBVIEW;
                const CLEANHOUSE_HTTP_ORIGIN = 'http://127.0.0.1:3333';
                const API_BASE_URL = IS_BROWSER ? `${CLEANHOUSE_HTTP_ORIGIN}/api` : null;

                console.log('[CLEANHOUSE] Environment:', IS_PYWEBVIEW ? 'pywebview (desktop)' : 'browser (web)');

                // UI helper functions (define early so OAuth callback can use them)
                // Handle both login page (error-message) and signup page (errorMessage) IDs
                function showError(message) {
                    const errorDiv = document.getElementById('error-message') || document.getElementById('errorMessage');
                    if (errorDiv) {
                        errorDiv.textContent = message;
                        errorDiv.style.display = 'block';
                        const successDiv = document.getElementById('success-message') || document.getElementById('successMessage');
                        if (successDiv) successDiv.style.display = 'none';
                    }
                    console.log('[UI] Error:', message);
                }

                function showSuccess(message) {
                    const successDiv = document.getElementById('success-message') || document.getElementById('successMessage');
                    if (successDiv) {
                        successDiv.textContent = message;
                        successDiv.style.display = 'block';
                        const errorDiv = document.getElementById('error-message') || document.getElementById('errorMessage');
                        if (errorDiv) errorDiv.style.display = 'none';
                    }
                    console.log('[UI] Success:', message);
                }

                function dashboardRedirectWithLoginReport(redirect, loginReport) {
                    const reportId = loginReport && loginReport.status === 'ok' ? loginReport.id : '';
                    if (!reportId) {
                        return redirect || '/dashboard';
                    }
                    try {
                        const url = new URL(redirect || '/dashboard', window.location.origin);
                        url.searchParams.set('login_report_id', reportId);
                        return url.pathname + url.search + url.hash;
                    } catch (err) {
                        const separator = (redirect || '/dashboard').includes('?') ? '&' : '?';
                        return (redirect || '/dashboard') + separator + 'login_report_id=' + encodeURIComponent(reportId);
                    }
                }

                // Handle OAuth callback (check URL params) - run after DOM is ready
                function handleOAuthCallback() {
                    const urlParams = new URLSearchParams(window.location.search);
                    const oauthSuccess = urlParams.get('oauth_success');
                    const error = urlParams.get('error');

                    if (oauthSuccess === '1') {
                        console.log('[OAUTH] OAuth success detected in URL');
                        // Fetch user data from session via API
                        fetch('/api/auth/oauth/user')
                            .then(res => res.json())
                            .then(data => {
                                if (data.success && data.user && data.token) {
                                    console.log('[OAUTH] User authenticated:', data.user.email);

                                    // Store authentication state
                                    if (window.authState) {
                                        window.authState.setUser(data.user, data.token);
                                    }

                                    showSuccess('Successfully authenticated! Launching desktop app...');

                                    // Clear URL params
                                    window.history.replaceState({}, document.title, window.location.pathname);

                                    // Launch desktop app
                                    fetch('/api/auth/launch-desktop', {
                                        method: 'POST',
                                        headers: {
                                            'Content-Type': 'application/json'
                                        },
                                        body: JSON.stringify({
                                            token: data.token,
                                            user: data.user
                                        })
                                    })
                                    .then(res => res.json())
                                    .then(launchData => {
                                        if (launchData.success) {
                                            console.log('[OAUTH] Desktop app launched successfully');
                                            showSuccess('Desktop app is launching! You can close this window.');
                                            // Close window after a delay (if in pywebview, this will close the desktop window)
                                            setTimeout(() => {
                                                if (IS_PYWEBVIEW && window.pywebview) {
                                                    // In desktop mode, we're already in the desktop app
                                                    // Just show success message
                                                } else {
                                                    // In browser mode, show message that they can close the tab
                                                    showSuccess('Desktop app launched! You can close this browser tab.');
                                                }
                                            }, 2000);
                                        } else {
                                            console.error('[OAUTH] Failed to launch desktop app:', launchData.message);
                                            showError('Authentication successful, but failed to launch desktop app: ' + launchData.message);
                                        }
                                    })
                                    .catch(err => {
                                        console.error('[OAUTH] Error launching desktop app:', err);
                                        showError('Authentication successful, but failed to launch desktop app.');
                                    });
                                } else {
                                    showError('OAuth authentication completed but failed to load user data.');
                                }
                            })
                            .catch(err => {
                                console.error('[OAUTH] Error fetching user data:', err);
                                showError('OAuth authentication completed but failed to load user data.');
                            });
                    } else if (error) {
                        console.error('[OAUTH] OAuth error:', error);
                        showError('OAuth authentication failed: ' + decodeURIComponent(error));
                        // Clear URL params
                        window.history.replaceState({}, document.title, window.location.pathname);
                    }
                }

                // Run OAuth callback handler when DOM is ready
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', handleOAuthCallback);
                } else {
                    handleOAuthCallback();
                }

                // Global logging helpers - check for pywebview API availability
                function hasAPI() {
                    // In browser mode, we always have API (via HTTP)
                    if (IS_BROWSER) {
                        return true;
                    }
                    // In pywebview mode, check for pywebview API
                    const has = typeof window !== 'undefined' &&
                           window.pywebview &&
                           window.pywebview.api;
                    if (!has) {
                        console.warn('[CLEANHOUSE] pywebview API not available');
                    }
                    return has;
                }

                // Function to attach click listeners (called when API is ready)
                function attachClickListeners() {
                    console.log('[CLEANHOUSE] Attaching click listeners...');

                    // Log ALL clicks on the page
                    document.addEventListener('click', function(e) {
                        if (!hasAPI()) {
                            console.warn('[CLEANHOUSE] Click detected but API not available');
                            return;
                        }

                        console.log('[CLEANHOUSE] Click captured:', e.target.tagName, e.target.id || e.target.className);

                        const target = e.target;
                        let elementType = '';
                        let details = '';

                        // Identify what was clicked
                        if (target.tagName === 'BUTTON') {
                            elementType = 'button';
                            const buttonText = target.textContent.trim() || target.innerText.trim() || 'Button';
                            details = `"${buttonText.substring(0, 50)}"`;
                            if (target.id) details += ` (id: ${target.id})`;
                        } else if (target.tagName === 'A') {
                            elementType = 'link';
                            const linkText = target.textContent.trim() || target.innerText.trim() || 'Link';
                            details = `"${linkText.substring(0, 50)}"`;
                        } else if (target.tagName === 'INPUT') {
                            elementType = 'input';
                            const inputName = target.name || target.id || 'unnamed';
                            details = `${target.type || 'text'} (name: ${inputName})`;
                        } else {
                            elementType = 'element';
                            details = target.tagName.toLowerCase();
                            if (target.id) details += ` (id: ${target.id})`;
                            if (target.className) details += ` (class: ${target.className.split(' ')[0]})`;
                        }

                        try {
                            if (IS_PYWEBVIEW && window.pywebview?.api?.log_click) {
                                window.pywebview.api.log_click(elementType, details);
                                console.log('[CLEANHOUSE] Click logged successfully:', elementType, details);
                            } else {
                                console.log(`[CLICK] ${elementType}: ${details}`);
                            }
                        } catch (err) {
                            console.error('[CLEANHOUSE] Error logging click:', err);
                            console.log(`[CLICK] ${elementType}: ${details}`);
                        }
                    }, true); // Use capture phase to catch all clicks

                    console.log('[CLEANHOUSE] Click listeners attached');
                }

                // Wait for pywebview to be ready, then attach listeners
                if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                    // API already available, attach immediately
                    console.log('[CLEANHOUSE] API already available, attaching listeners');
                    attachClickListeners();
                } else {
                    // Wait for pywebview ready event
                    console.log('[CLEANHOUSE] Waiting for pywebview ready...');
                    window.addEventListener('pywebviewready', function() {
                        console.log('[CLEANHOUSE] pywebview ready event fired');
                        attachClickListeners();
                    });

                    // Also try polling as fallback (some versions don't fire the event)
                    let pollCount = 0;
                    const pollInterval = setInterval(function() {
                        pollCount++;
                        if (typeof window.pywebview !== 'undefined' && window.pywebview.api) {
                            console.log('[CLEANHOUSE] API available via polling (attempt', pollCount, ')');
                            clearInterval(pollInterval);
                            attachClickListeners();
                        } else if (pollCount > 50) {
                            // Give up after 5 seconds (50 * 100ms)
                            console.error('[CLEANHOUSE] API not available after 5 seconds, giving up');
                            clearInterval(pollInterval);
                        }
                    }, 100);
                }

                // Log input field changes (don't log password values)
                document.addEventListener('input', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';
                        const fieldType = target.type || 'text';
                        // Don't log password values, only length
                        const charCount = target.value ? target.value.length : 0;

                        try {
                            if (IS_PYWEBVIEW && window.pywebview?.api?.log_input) {
                                window.pywebview.api.log_input(fieldName, fieldType, charCount);
                            } else {
                                console.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
                            }
                        } catch (err) {
                            console.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
                        }
                    }
                }, true);

                // Log input focus
                document.addEventListener('focus', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';

                        try {
                            if (IS_PYWEBVIEW && window.pywebview?.api?.log_focus) {
                                window.pywebview.api.log_focus(fieldName);
                            } else {
                                console.log(`[FOCUS] Field "${fieldName}" focused`);
                            }
                        } catch (err) {
                            console.log(`[FOCUS] Field "${fieldName}" focused`);
                        }
                    }
                }, true);

                // Log input blur
                document.addEventListener('blur', function(e) {
                    if (!hasAPI()) return;

                    const target = e.target;
                    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
                        const fieldName = target.name || target.id || 'unnamed';

                        try {
                            if (IS_PYWEBVIEW && window.pywebview?.api?.log_blur) {
                                window.pywebview.api.log_blur(fieldName);
                            } else {
                                console.log(`[BLUR] Field "${fieldName}" blurred`);
                            }
                        } catch (err) {
                            console.log(`[BLUR] Field "${fieldName}" blurred`);
                        }
                    }
                }, true);

                // Password toggle functionality
                function togglePassword() {
                    if (IS_PYWEBVIEW && window.pywebview?.api?.log_click) {
                        try {
                            window.pywebview.api.log_click('button', '"Password toggle"');
                        } catch (err) {
                            console.log('[CLICK] Password toggle button clicked');
                        }
                    } else {
                        console.log('[CLICK] Password toggle button clicked');
                    }
                    const passwordInput = document.getElementById('password');
                    const toggle = document.querySelector('.password-toggle');

                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggle.textContent = '🙈';
                        if (IS_PYWEBVIEW && window.pywebview?.api?.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: SHOWN');
                        }
                    } else {
                        passwordInput.type = 'password';
                        toggle.textContent = '👁️';
                        if (IS_PYWEBVIEW && window.pywebview?.api?.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: HIDDEN');
                        }
                    }
                }

                // Form submission
                const loginForm = document.getElementById('login-form');
                if (loginForm) {
                    loginForm.addEventListener('submit', async function(e) {
                        e.preventDefault();
                        if (hasAPI()) {
                            try {
                                if (IS_PYWEBVIEW) {
                                    window.pywebview.api.log_click('button', '"Sign In" (form submit)');
                                } else {
                                    console.log('[CLICK] Login form submit button clicked');
                                }
                            } catch (err) {
                                console.error('[LOGIN] Log error:', err);
                            }
                        }

                        const email = document.getElementById('email').value;
                        const password = document.getElementById('password').value;

                        if (!email || !password) {
                            showError('Please fill in all fields.');
                            return;
                        }

                        showLoading(true);

                        if (IS_BROWSER) {
                            // Browser mode - use HTTP API
                            try {
                                const response = await fetch('/api/auth/login', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ email, password })
                                });
                                const data = await response.json();

                                if (data.success && data.user && data.token) {
                                    // Store authentication state
                                    if (window.authState) {
                                        window.authState.setUser(data.user, data.token);
                                    }

                                    showSuccess('Login successful! Welcome, ' + data.user.full_name);

                                    // Redirect to dashboard or redirect URL
                                    setTimeout(() => {
                                        const urlParams = new URLSearchParams(window.location.search);
                                        const redirect = urlParams.get('redirect') || '/dashboard';
                                        window.location.href = dashboardRedirectWithLoginReport(redirect, data.login_report);
                                    }, 1500);
                                } else {
                                    showError(data.message || 'Invalid email or password.');
                                }
                            } catch (error) {
                                console.error('[LOGIN] API error:', error);
                                showError('Login failed. Please try again.');
                            }
                            showLoading(false);
                        } else if (IS_PYWEBVIEW) {
                            // Desktop mode - use pywebview API (if available)
                            // For now, fallback to simple check
                            setTimeout(() => {
                                if (email === 'admin@cleanhouse.local' && password === 'admin123') {
                                    showSuccess('Login successful!');
                                    setTimeout(() => window.close(), 1000);
                                } else {
                                    showError('Invalid email or password.');
                                }
                                showLoading(false);
                            }, 1000);
                        } else {
                            showError('API not available. Please refresh the page.');
                            showLoading(false);
                        }
                    });
                }

                // OAuth functions - use system browser with full OAuth flow
                async function signInWithGoogle() {
                    console.log('[OAUTH] signInWithGoogle() called');
                    console.log('[OAUTH] IS_BROWSER:', IS_BROWSER);
                    console.log('[OAUTH] IS_PYWEBVIEW:', IS_PYWEBVIEW);
                    console.log('[OAUTH] Button disabled?', document.getElementById('oauth-google')?.disabled);

                    if (hasAPI()) {
                        try {
                            if (IS_PYWEBVIEW) {
                                window.pywebview.api.log_click('button', '"Continue with Google"');
                            } else {
                                console.log('[CLICK] Google OAuth button clicked');
                            }
                        } catch (err) {
                            console.error('[OAUTH] Log error:', err);
                        }
                    }

                    // Check if button is disabled
                    const googleBtn = document.getElementById('oauth-google');
                    if (googleBtn && googleBtn.disabled) {
                        console.error('[OAUTH] Google button is disabled - terms checkbox must be checked');
                        showError('Please check the terms checkbox to enable OAuth signup.');
                        return;
                    }

                    // Show loading (handle gracefully if element doesn't exist)
                    try {
                        showOAuthLoading(true);
                    } catch (err) {
                        console.warn('[OAUTH] Could not show loading overlay:', err);
                    }

                    if (IS_PYWEBVIEW && window.pywebview && window.pywebview.api) {
                        // Desktop mode - use pywebview API
                        try {
                            console.log('[OAUTH] Calling openOAuthUrl for Google (desktop)...');
                            const result = window.pywebview.api.openOAuthUrl(null, 'google');
                            console.log('[OAUTH] Result received:', result);

                            if (result) {
                                if (result.success === true) {
                                    // Success - browser opened
                                    const message = result.message || 'Opening Google authentication in your browser. Please complete the sign-in there.';
                                    console.log('[OAUTH] Success:', message);
                                    showSuccess(message);

                                    if (result.user) {
                                        // Already authenticated (shouldn't happen, but handle it)
                                        setTimeout(() => {
                                            window.close();
                                        }, 1500);
                                    }
                                } else {
                                    // Error returned
                                    const errorMsg = result.message || 'Failed to open Google authentication.';
                                    console.error('[OAUTH] Error from API:', errorMsg);
                                    showError(errorMsg);
                                    showOAuthLoading(false);
                                }
                            } else {
                                // No result returned (shouldn't happen)
                                console.error('[OAUTH] No result returned from API');
                                showError('Failed to open Google authentication. No response from server.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            console.error('[OAUTH] Exception:', error);
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else if (IS_BROWSER) {
                        // Browser mode - redirect to OAuth endpoint
                        console.log('[OAUTH] Redirecting to Google OAuth (browser mode)...');
                        console.log('[OAUTH] Current URL:', window.location.href);
                        console.log('[OAUTH] Target URL:', `${window.location.origin}/api/auth/oauth/google`);

                        // Use full URL to ensure proper redirect
                        // Use setTimeout to ensure any pending operations complete
                        setTimeout(() => {
                            try {
                                window.location.href = `${window.location.origin}/api/auth/oauth/google`;
                            } catch (error) {
                                console.error('[OAUTH] Redirect error:', error);
                                showError('OAuth error: ' + error.message);
                                try {
                                    showOAuthLoading(false);
                                } catch (e) {
                                    // Ignore if showOAuthLoading fails
                                }
                            }
                        }, 100);
                    } else {
                        console.error('[OAUTH] API not available');
                        showError('OAuth configuration required. Please contact support.');
                        try {
                            showOAuthLoading(false);
                        } catch (e) {
                            // Ignore if showOAuthLoading fails
                        }
                    }
                }

                async function signInWithApple() {
                    if (hasAPI()) {
                        try {
                            if (IS_PYWEBVIEW) {
                                window.pywebview.api.log_click('button', '"Continue with Apple"');
                            } else {
                                console.log('[CLICK] Apple OAuth button clicked');
                            }
                        } catch (err) {
                            console.error('[OAUTH] Log error:', err);
                        }
                    }
                    showOAuthLoading(true);

                    if (IS_PYWEBVIEW && window.pywebview && window.pywebview.api) {
                        // Desktop mode
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'apple');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Apple!');
                                    setTimeout(() => window.close(), 1500);
                                } else {
                                    showSuccess(result.message || 'Opening Apple authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Apple authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else if (IS_BROWSER) {
                        // Browser mode
                        window.location.href = `/api/auth/oauth/apple`;
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                async function signInWithGithub() {
                    if (hasAPI()) {
                        try {
                            if (IS_PYWEBVIEW) {
                                window.pywebview.api.log_click('button', '"Continue with GitHub"');
                            } else {
                                console.log('[CLICK] GitHub OAuth button clicked');
                            }
                        } catch (err) {
                            console.error('[OAUTH] Log error:', err);
                        }
                    }
                    showOAuthLoading(true);

                    if (IS_PYWEBVIEW && window.pywebview && window.pywebview.api) {
                        // Desktop mode
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'github');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with GitHub!');
                                    setTimeout(() => window.close(), 1500);
                                } else {
                                    showSuccess(result.message || 'Opening GitHub authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open GitHub authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else if (IS_BROWSER) {
                        // Browser mode
                        window.location.href = `/api/auth/oauth/github`;
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                async function signInWithMicrosoft() {
                    if (hasAPI()) {
                        try {
                            if (IS_PYWEBVIEW) {
                                window.pywebview.api.log_click('button', '"Continue with Microsoft"');
                            } else {
                                console.log('[CLICK] Microsoft OAuth button clicked');
                            }
                        } catch (err) {
                            console.error('[OAUTH] Log error:', err);
                        }
                    }
                    showOAuthLoading(true);

                    if (IS_PYWEBVIEW && window.pywebview && window.pywebview.api) {
                        // Desktop mode
                        try {
                            const result = window.pywebview.api.openOAuthUrl(null, 'microsoft');
                            if (result && result.success) {
                                if (result.user) {
                                    showSuccess(result.message || 'Successfully authenticated with Microsoft!');
                                    setTimeout(() => window.close(), 1500);
                                } else {
                                    showSuccess(result.message || 'Opening Microsoft authentication in your browser. Please complete the sign-in there.');
                                }
                            } else {
                                showError(result?.message || 'Failed to open Microsoft authentication.');
                                showOAuthLoading(false);
                            }
                        } catch (error) {
                            showError('OAuth error: ' + error.message);
                            showOAuthLoading(false);
                        }
                    } else if (IS_BROWSER) {
                        // Browser mode
                        window.location.href = `/api/auth/oauth/microsoft`;
                    } else {
                        showError('OAuth configuration required. Please contact support.');
                        showOAuthLoading(false);
                    }
                }

                function showSignup(event) {
                    // Log the click immediately - try multiple methods
                    let logged = false;
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('link', '"Create Account" (from login)');
                            logged = true;
                        } catch (err) {
                            console.error('Failed to log click via log_click:', err);
                            try {
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log('[CLICK] "Create Account" link clicked (from login)');
                                    logged = true;
                                }
                            } catch (err2) {
                                console.error('Failed to log click via log:', err2);
                            }
                        }
                    }

                    if (!logged) {
                        console.warn('Could not log click - API not available or error occurred');
                    }

                    // Prevent default link behavior (scrolling to top)
                    if (event) {
                        event.preventDefault();
                    }

                    console.log('showSignup() called');
                    console.log('window.pywebview:', window.pywebview);

                    // Close current window and show signup
                    // This will trigger the parent to show the signup WebView
                    if (IS_PYWEBVIEW && window.pywebview && window.pywebview.api) {
                        console.log('Calling window.pywebview.api.showSignup()');
                        window.pywebview.api.showSignup();
                    } else if (IS_BROWSER) {
                        // Browser mode - navigate to signup page
                        window.location.href = '/signup';
                    } else {
                        console.error('API not available');
                        showError('API not available. Please refresh the page.');
                    }
                    // Don't close window immediately - let the API handle it
                    return false;
                }

                // UI helper functions (already defined above, but keep for compatibility)
                // Note: showError and showSuccess are defined at the top of the file

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

                function showOAuthLoading(show) {
                    const overlay = document.getElementById('loading-overlay');
                    if (!overlay) {
                        // Element doesn't exist (e.g., on signup page), just log
                        console.log(`[OAUTH] Loading overlay ${show ? 'shown' : 'hidden'} (element not found)`);
                        return;
                    }
                    if (show) {
                        overlay.style.display = 'flex';
                    } else {
                        overlay.style.display = 'none';
                    }
                }

                function handleOAuthTimeout() {
                    showOAuthLoading(false);
                    showError('OAuth timeout. Please try again.');
                }

                // Test API function
                function testAPI() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Test API Connection"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] "Test API Connection" button clicked');
                            }
                        }
                    }
                    console.log('Testing API connection...');
                    console.log('window.pywebview:', window.pywebview);

                    if (window.pywebview && window.pywebview.api) {
                        try {
                            const result = window.pywebview.api.test_api();
                            console.log('API test result:', result);
                            alert('API is working! Check console for details.');
                        } catch (error) {
                            console.error('API test failed:', error);
                            alert('API test failed: ' + error.message);
                        }
                    } else {
                        console.error('window.pywebview.api not available');
                        alert('API not available - WebView setup issue');
                    }
                }

                // Focus first input (only if login form exists)
                const emailInput = document.getElementById('email');
                if (emailInput) {
                    emailInput.focus();
                }

                // Signup page: Enable OAuth buttons when terms checkbox is checked
                function setupSignupOAuthToggle() {
                    const termsCheckbox = document.getElementById('terms');
                    const oauthSection = document.getElementById('oauth-section');

                    if (!termsCheckbox || !oauthSection) {
                        // Not on signup page
                        return;
                    }

                    // Get all OAuth buttons
                    const oauthButtons = [
                        document.getElementById('oauth-google'),
                        document.getElementById('oauth-microsoft'),
                        document.getElementById('oauth-apple'),
                        document.getElementById('oauth-github')
                    ].filter(btn => btn !== null);

                    // Get the helper text paragraph
                    const helperText = document.getElementById('oauth-helper-text') || oauthSection.querySelector('p');

                    // Function to toggle OAuth buttons
                    function toggleOAuthButtons(enabled) {
                        oauthButtons.forEach(btn => {
                            btn.disabled = !enabled;
                        });

                        // Update helper text
                        if (helperText) {
                            if (enabled) {
                                helperText.textContent = 'Or sign up with one of the providers below';
                                helperText.style.color = '#666';
                            } else {
                                helperText.textContent = 'Complete the form above to enable OAuth signup';
                                helperText.style.color = '#999';
                            }
                        }
                    }

                    // Initial state: buttons disabled
                    toggleOAuthButtons(false);

                    // Listen for checkbox changes
                    termsCheckbox.addEventListener('change', function(e) {
                        toggleOAuthButtons(e.target.checked);

                        // Log the change
                        if (hasAPI()) {
                            try {
                                if (IS_PYWEBVIEW) {
                                    window.pywebview.api.log_input('terms', 'checkbox', e.target.checked ? 'checked' : 'unchecked');
                                } else {
                                    console.log('[INPUT] Terms checkbox:', e.target.checked ? 'checked' : 'unchecked');
                                }
                            } catch (err) {
                                console.error('[SIGNUP] Log error:', err);
                            }
                        }
                    });

                    console.log('[SIGNUP] OAuth toggle setup complete');
                }

                // Setup signup OAuth toggle when DOM is ready
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', setupSignupOAuthToggle);
                } else {
                    setupSignupOAuthToggle();
                }

                // Signup form submission handler
                const signupForm = document.getElementById('signupForm');
                if (signupForm) {
                    signupForm.addEventListener('submit', async function(e) {
                        e.preventDefault();

                        // Clear previous messages
                        showError('');
                        showSuccess('');

                        // Get form data
                        const formData = new FormData(signupForm);
                        const data = {
                            fullName: formData.get('fullName'),
                            email: formData.get('email'),
                            password: formData.get('password'),
                            confirmPassword: formData.get('confirmPassword'),
                            role: formData.get('role'),
                            terms: formData.get('terms')
                        };

                        // Validate form
                        if (!data.fullName || !data.email || !data.password || !data.confirmPassword || !data.role) {
                            showError('All fields are required.');
                            return;
                        }

                        if (data.password !== data.confirmPassword) {
                            showError('Passwords do not match.');
                            return;
                        }

                        if (data.password.length < 8) {
                            showError('Password must be at least 8 characters long.');
                            return;
                        }

                        if (!data.terms) {
                            showError('You must agree to the Terms of Service and Privacy Notice.');
                            return;
                        }

                        // Show loading
                        const loadingDiv = document.getElementById('loading');
                        const signupButton = document.getElementById('signupButton');
                        if (loadingDiv) loadingDiv.style.display = 'block';
                        if (signupButton) signupButton.disabled = true;

                        try {
                            const response = await fetch('/api/auth/createAccount', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    fullName: data.fullName,
                                    email: data.email,
                                    password: data.password,
                                    role: data.role
                                })
                            });

                            const result = await response.json();

                            if (result.success && result.user && result.token) {
                                // Store authentication state
                                if (window.authState) {
                                    window.authState.setUser(result.user, result.token);
                                }

                                showSuccess('Account created successfully! Welcome, ' + result.user.full_name);

                                // Redirect to dashboard
                                setTimeout(() => {
                                    window.location.href = '/dashboard';
                                }, 1500);
                            } else {
                                showError(result.message || 'Account creation failed. Please try again.');
                            }
                        } catch (error) {
                            console.error('[SIGNUP] API error:', error);
                            showError('Network error. Please check your connection and try again.');
                        } finally {
                            if (loadingDiv) loadingDiv.style.display = 'none';
                            if (signupButton) signupButton.disabled = false;
                        }
                    });
                }
