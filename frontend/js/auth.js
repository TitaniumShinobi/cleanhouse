// Debug: Log script loading
                console.log('[CLEANHOUSE] Script loaded');
                console.log('[CLEANHOUSE] window.pywebview:', typeof window.pywebview !== 'undefined' ? 'exists' : 'undefined');
                console.log('[CLEANHOUSE] window.pywebview.api:', typeof window.pywebview?.api !== 'undefined' ? 'exists' : 'undefined');

                // Global logging helpers - check for pywebview API availability
                function hasAPI() {
                    const has = typeof window !== 'undefined' &&
                           window.pywebview &&
                           window.pywebview.api;
                    return has;
                }

                // Function to attach click listeners (called when API is ready)
                function attachClickListeners() {
                    console.log('[CLEANHOUSE] Attaching click listeners...');

                    // Log ALL clicks on the page
                    document.addEventListener('click', function(e) {
                        if (!hasAPI()) {
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
                            window.pywebview.api.log_click(elementType, details);
                            console.log('[CLEANHOUSE] Click logged successfully:', elementType, details);
                        } catch (err) {
                            console.error('[CLEANHOUSE] Error logging click:', err);
                            // Fallback to generic log if specific method not available
                            try {
                                if (window.pywebview.api.log) {
                                    window.pywebview.api.log(`[CLICK] ${elementType}: ${details}`);
                                }
                            } catch (err2) {
                                console.error('[CLEANHOUSE] Fallback log also failed:', err2);
                            }
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
                            console.debug('[CLEANHOUSE] pywebview bridge not present; browser auth path remains active.');
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
                            window.pywebview.api.log_input(fieldName, fieldType, charCount);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[INPUT] ${fieldType} field "${fieldName}" changed (${charCount} chars)`);
                            }
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
                            window.pywebview.api.log_focus(fieldName);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[FOCUS] Field "${fieldName}" focused`);
                            }
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
                            window.pywebview.api.log_blur(fieldName);
                        } catch (err) {
                            // Fallback to generic log
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log(`[BLUR] Field "${fieldName}" blurred`);
                            }
                        }
                    }
                }, true);

		                const AUTH_BASE_PATH = '/api/auth';
		                const AUTH_UNAVAILABLE_MESSAGE = 'Authentication backend unavailable. Enable auth routes and retry.';
		                const TURNSTILE_SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
		                const DEFAULT_AUTH_CONFIG = {
		                    docs: [
		                        { key: 'cleanhouse:terms', label: 'CleanHouse Terms of Service', url: '/legal/terms', required: true },
		                        { key: 'cleanhouse:privacy', label: 'CleanHouse Privacy Notice', url: '/legal/privacy', required: true },
		                        { key: 'cleanhouse:eeccd', label: 'European Electronic Communications Code Disclosure', url: '/legal/eeccd', required: true },
		                    ],
		                    turnstile: { required: true, enabled: false, siteKey: null },
		                };
		                let authConfig = DEFAULT_AUTH_CONFIG;
		                let turnstileToken = '';
		                let turnstileWidgetId = null;
		                let turnstileScriptLoading = false;

		                async function postAuth(path, payload) {
	                    const response = await fetch(`${AUTH_BASE_PATH}${path}`, {
	                        method: 'POST',
	                        headers: {
	                            'Content-Type': 'application/json',
	                            'Accept': 'application/json',
	                        },
	                        credentials: 'include',
	                        body: JSON.stringify(payload),
	                    });
	                    const data = await response.json().catch(() => ({
	                        success: false,
	                        message: 'Authentication response was not valid JSON.',
	                    }));
	                    if (response.status === 404) {
	                        data.message = AUTH_UNAVAILABLE_MESSAGE;
	                    }
	                    if (!response.ok && data.success !== true) {
	                        data.success = false;
	                    }
		                    return data;
		                }

		                async function loadAuthConfig() {
		                    try {
		                        const response = await fetch(`${AUTH_BASE_PATH}/config`, {
		                            method: 'GET',
		                            headers: { 'Accept': 'application/json' },
		                            credentials: 'include',
		                        });
		                        const payload = await response.json().catch(() => ({}));
		                        const data = payload.data || payload;
		                        authConfig = {
		                            ...DEFAULT_AUTH_CONFIG,
		                            ...data,
		                            docs: Array.isArray(data.docs) && data.docs.length ? data.docs : DEFAULT_AUTH_CONFIG.docs,
		                            turnstile: {
		                                ...DEFAULT_AUTH_CONFIG.turnstile,
		                                ...(data.turnstile || {}),
		                            },
		                        };
		                    } catch (error) {
		                        authConfig = DEFAULT_AUTH_CONFIG;
		                    }
		                    renderProviderControls();
		                    renderTurnstile();
		                    return authConfig;
		                }

		                function providerAvailable(provider) {
		                    return (authConfig.providers || []).some((item) => (
		                        item.provider === provider && item.enabled === true && item.available === true
		                    ));
		                }

		                function renderProviderControls() {
		                    document.querySelectorAll('.oauth-btn[data-provider]').forEach((button) => {
		                        const available = providerAvailable(button.dataset.provider);
		                        button.hidden = !available;
		                        if (!available) {
		                            button.disabled = true;
		                            button.setAttribute('aria-disabled', 'true');
		                        }
		                    });
		                }

		                function requiredAuthDocs() {
		                    return (authConfig.docs || DEFAULT_AUTH_CONFIG.docs).filter((doc) => doc.required !== false);
		                }

		                function consentPayload() {
		                    const accepted = document.getElementById('terms')?.checked === true;
		                    return Object.fromEntries(requiredAuthDocs().map((doc) => [doc.key, accepted]));
		                }

		                function isTurnstileRequired() {
		                    return authConfig.turnstile?.required === true;
		                }

		                function setTurnstileHelper(message) {
		                    const helper = document.getElementById('turnstile-helper');
		                    if (!helper) return;
		                    helper.textContent = message || '';
		                    helper.style.display = message ? 'block' : 'none';
		                }

		                function renderTurnstile() {
		                    const host = document.getElementById('turnstile-widget');
		                    if (!host) return;
		                    if (!isTurnstileRequired()) {
		                        host.style.display = 'none';
		                        setTurnstileHelper('');
		                        return;
		                    }
		                    host.style.display = 'flex';
		                    const siteKey = (authConfig.turnstile?.siteKey || '').trim();
		                    if (!siteKey) {
		                        setTurnstileHelper('Human verification is required, but it is not configured for this environment.');
		                        return;
		                    }
		                    if (window.turnstile && !turnstileWidgetId) {
		                        host.innerHTML = '';
		                        turnstileWidgetId = window.turnstile.render('#turnstile-widget', {
		                            sitekey: siteKey,
		                            callback: (token) => {
		                                turnstileToken = token;
		                                setTurnstileHelper('');
		                            },
		                            'error-callback': () => {
		                                turnstileToken = '';
		                                setTurnstileHelper('Human verification failed. Please try again.');
		                            },
		                            'expired-callback': () => {
		                                turnstileToken = '';
		                                setTurnstileHelper('Verification expired. Please verify again.');
		                            },
		                            theme: 'auto',
		                            size: 'normal',
		                        });
		                        return;
		                    }
		                    if (!window.turnstile && !turnstileScriptLoading && !document.querySelector(`script[src="${TURNSTILE_SCRIPT_SRC}"]`)) {
		                        turnstileScriptLoading = true;
		                        const script = document.createElement('script');
		                        script.src = TURNSTILE_SCRIPT_SRC;
		                        script.async = true;
		                        script.defer = true;
		                        script.onload = () => {
		                            turnstileScriptLoading = false;
		                            renderTurnstile();
		                        };
		                        script.onerror = () => {
		                            turnstileScriptLoading = false;
		                            setTurnstileHelper('Human verification failed to load. Please refresh and try again.');
		                        };
		                        document.head.appendChild(script);
		                    }
		                }

		                function resetTurnstile() {
		                    turnstileToken = '';
		                    if (turnstileWidgetId && window.turnstile) {
		                        window.turnstile.reset(turnstileWidgetId);
		                    }
		                }

		                function validateSignupRequirements() {
		                    if (document.getElementById('terms')?.checked !== true) {
		                        showError('Please confirm you agree to CleanHouse Terms of Service.');
		                        return false;
		                    }
		                    if (isTurnstileRequired()) {
		                        if (!authConfig.turnstile?.enabled || !authConfig.turnstile?.siteKey) {
		                            showError('Human verification is required, but it is not configured for this environment.');
		                            return false;
		                        }
		                        if (!turnstileToken) {
		                            showError('Please complete human verification.');
		                            return false;
		                        }
		                    }
		                    return true;
		                }

		                function updateSignupOauthState() {
		                    const accepted = document.getElementById('terms')?.checked === true;
		                    document.querySelectorAll('#oauth-section .oauth-btn').forEach((button) => {
		                        const available = providerAvailable(button.dataset.provider);
		                        button.disabled = !accepted || !available;
		                        button.setAttribute('aria-disabled', String(!accepted || !available));
		                    });
		                }

	                function dashboardRedirectWithLoginReport(data) {
	                    const reportId = data.login_report?.id || data.login_report?.report_id;
	                    if (reportId) {
	                        return `/overview?login_report_id=${encodeURIComponent(reportId)}`;
	                    }
	                    return '/overview';
	                }

                let desktopHandoff = null;
                let oauthInProgress = false;
                async function waitForDesktopOAuth(handoff) {
                    try {
                        for (let attempt = 0; attempt < 150 && desktopHandoff === handoff; attempt += 1) {
                            await new Promise(resolve => setTimeout(resolve, 2000));
                            const response = await fetch(`${AUTH_BASE_PATH}/desktop/redeem`, {
                                method: 'POST', credentials: 'include',
                                headers: {'Content-Type': 'application/json'}, body: JSON.stringify(handoff),
                            });
                            if (response.status === 202) continue;
                            const result = await response.json();
                            if (!response.ok || !result.success) throw new Error(result.code || 'Sign-in could not complete.');
                            desktopHandoff = null;
                            try { await window.pywebview.api.activateExistingWindow(); }
                            catch (_) { /* Session is valid even if the OS refuses foreground activation. */ }
                            completeAuth(result);
                            return;
                        }
                        throw new Error('Sign-in timed out. Please retry.');
                    } catch (error) {
                        showError(error.message);
                    } finally {
                        if (desktopHandoff === handoff) {
                            desktopHandoff = null;
                            await fetch(`${AUTH_BASE_PATH}/desktop/cancel`, {method:'POST', credentials:'include'}).catch(() => {});
                        }
                        showOAuthLoading(false);
                    }
                }

	                function completeAuth(result) {
	                    if (window.authState && result.user) window.authState.setUser(result.user, null);
	                    showSuccess(result.message || 'Signed in.');
	                    setTimeout(() => {
	                        window.location.href = dashboardRedirectWithLoginReport(result);
	                    }, 350);
	                }

	                async function completeOAuthRedirectIfPresent() {
	                    const params = new URLSearchParams(window.location.search);
	                    if (params.get('oauth_success') !== '1') {
	                        return false;
	                    }
	                    showOAuthLoading(true);
	                    try {
	                        const response = await fetch(`${AUTH_BASE_PATH}/oauth/user`, {
	                            method: 'GET',
	                            headers: { 'Accept': 'application/json' },
	                            credentials: 'include',
	                        });
	                        const result = await response.json().catch(() => ({
	                            success: false,
	                            message: 'OAuth response was not valid JSON.',
	                        }));
	                        if (response.ok && result.success) {
	                            completeAuth(result);
	                            return true;
	                        }
	                        showError(result.message || 'OAuth sign-in could not be completed.');
	                    } catch (error) {
	                        showError(`OAuth sign-in failed: ${error.message}`);
	                    } finally {
	                        showOAuthLoading(false);
	                    }
	                    return false;
	                }

                async function openOAuthProvider(provider) {
                    if (oauthInProgress) return;
                    oauthInProgress = true;
                    showOAuthLoading(true);
                    try {
                        const signup = !!document.getElementById('signupForm');
                        if (signup && !validateSignupRequirements()) return;
                        const payload = {provider, intent: signup ? 'signup' : 'signin'};
                        if (signup) Object.assign(payload, {
                            consent: consentPayload(), turnstileToken,
                            consentVersions: Object.fromEntries(requiredAuthDocs().map(doc => [doc.key, doc.version])),
                        });
                        if (window.pywebview && window.pywebview.api) {
                            const response = await fetch(`${AUTH_BASE_PATH}/desktop/prepare`, {
                                method:'POST', credentials:'include', headers:{'Content-Type':'application/json'},
                                body:JSON.stringify(payload),
                            });
                            const result = await response.json();
                            if (!response.ok || !result.success) throw new Error(result.message || result.code || 'Sign-in unavailable.');
                            desktopHandoff = {transactionId:result.transactionId, verifier:result.verifier};
                            const opened = await window.pywebview.api.openOAuthUrl(result.transactionId, provider);
                            if (!opened || !opened.success) throw new Error('System browser could not be opened.');
                            showSuccess('Complete sign-in in your system browser.');
                            await waitForDesktopOAuth(desktopHandoff);
                            return;
                        }
                        if (signup) {
                            const response = await fetch(`${AUTH_BASE_PATH}/oauth/${encodeURIComponent(provider)}`, {
                                method:'POST', credentials:'include', headers:{'Content-Type':'application/json','Accept':'application/json'},
                                body:JSON.stringify(payload),
                            });
                            const result = await response.json();
                            if (!response.ok || !result.authorizationUrl) throw new Error(result.message || 'Signup could not start.');
                            window.location.href = result.authorizationUrl;
                        } else window.location.href = `${AUTH_BASE_PATH}/oauth/${encodeURIComponent(provider)}`;
                    } catch(error) {
                        showError(error.message);
                        if (desktopHandoff) {
                            desktopHandoff = null;
                            await fetch(`${AUTH_BASE_PATH}/desktop/cancel`, {method:'POST', credentials:'include'}).catch(() => {});
                        }
                    } finally { oauthInProgress = false; showOAuthLoading(false); }
                }

	                // Password toggle functionality
                function togglePassword() {
                    if (hasAPI()) {
                        try {
                            window.pywebview.api.log_click('button', '"Password toggle"');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Password toggle button clicked');
                            }
                        }
                    }
                    const passwordInput = document.getElementById('password');
                    const toggle = document.querySelector('.password-toggle');

                    if (passwordInput.type === 'password') {
                        passwordInput.type = 'text';
                        toggle.textContent = '🙈';
                        if (hasAPI() && window.pywebview.api.log) {
                            window.pywebview.api.log('[ACTION] Password visibility: SHOWN');
                        }
                    } else {
                        passwordInput.type = 'password';
                        toggle.textContent = '👁️';
                        if (hasAPI() && window.pywebview.api.log) {
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
                            window.pywebview.api.log_click('button', '"Sign In" (form submit)');
                        } catch (err) {
                            if (window.pywebview.api.log) {
                                window.pywebview.api.log('[CLICK] Login form submit button clicked');
                            }
                        }
                    }

                    const email = document.getElementById('email').value;
                    const password = document.getElementById('password').value;

                    if (!email || !password) {
                        showError('Please fill in all fields.');
                        return;
                    }

	                    showLoading(true);

	                    try {
	                        const result = await postAuth('/login', { email, password });
	                        if (result && result.success) {
	                            completeAuth(result);
	                        } else {
	                            showError(result?.message || 'Sign in failed.');
	                        }
	                    } catch (error) {
	                        showError(`Authentication request failed: ${error.message}`);
	                    } finally {
	                        showLoading(false);
	                    }
		                });
		                }

		                const signupForm = document.getElementById('signupForm');
		                if (signupForm) {
		                    updateSignupOauthState();
		                    document.getElementById('terms')?.addEventListener('change', updateSignupOauthState);
		                    signupForm.addEventListener('submit', async function(e) {
		                        e.preventDefault();
		                        const fullName = document.getElementById('fullName')?.value.trim() || '';
		                        const email = document.getElementById('email')?.value.trim() || '';
		                        const password = document.getElementById('password')?.value || '';
		                        const confirmPassword = document.getElementById('confirmPassword')?.value || '';

		                        if (!fullName || !email || !password || !confirmPassword) {
		                            showError('Name, email, password, and password confirmation are required.');
		                            return;
		                        }
		                        if (password !== confirmPassword) {
		                            showError('Passwords do not match.');
		                            return;
		                        }
		                        if (password.length < 8) {
		                            showError('Password must be at least 8 characters.');
		                            return;
		                        }
		                        if (!validateSignupRequirements()) {
		                            return;
		                        }

		                        showLoading(true);
		                        try {
		                            const result = await postAuth('/createAccount', {
		                                fullName,
		                                email,
		                                password,
		                                confirmPassword,
		                                role: 'user',
		                                consent: consentPayload(),
		                                turnstileToken,
		                            });
		                            if (result && result.success) {
		                                completeAuth(result);
		                            } else {
		                                showError(result?.message || 'Account creation failed.');
		                                resetTurnstile();
		                            }
		                        } catch (error) {
		                            showError(`Account creation request failed: ${error.message}`);
		                            resetTurnstile();
		                        } finally {
		                            showLoading(false);
		                        }
		                    });
		                }

                // Every desktop provider uses the same initiator-bound completion path.
                function signInWithGoogle() { return openOAuthProvider('google'); }
                function signInWithApple() { return openOAuthProvider('apple'); }
                function signInWithGithub() { return openOAuthProvider('github'); }
                function signInWithMicrosoft() { return openOAuthProvider('microsoft'); }

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
	                    if (window.pywebview && window.pywebview.api) {
	                        console.log('Calling window.pywebview.api.showSignup()');
	                        window.pywebview.api.showSignup();
	                    } else {
	                        window.location.href = '/signup';
	                    }
                    // Don't close window immediately - let the API handle it
	                    return false;
	                }

		                function showLogin(event) {
		                    if (event) {
		                        event.preventDefault();
		                    }
		                    window.location.href = '/login';
		                    return false;
		                }

	                // UI helper functions
	                function showError(message) {
	                    const errorDiv = document.getElementById('error-message') || document.getElementById('errorMessage');
	                    if (!errorDiv) return;
	                    errorDiv.textContent = message;
	                    errorDiv.style.display = 'block';
	                    const successDiv = document.getElementById('success-message') || document.getElementById('successMessage');
	                    if (successDiv) successDiv.style.display = 'none';
	                }

	                function showSuccess(message) {
	                    const successDiv = document.getElementById('success-message') || document.getElementById('successMessage');
	                    if (!successDiv) return;
	                    successDiv.textContent = message;
	                    successDiv.style.display = 'block';
	                    const errorDiv = document.getElementById('error-message') || document.getElementById('errorMessage');
	                    if (errorDiv) errorDiv.style.display = 'none';
	                }

	                function showLoading(show) {
	                    const loadingDiv = document.getElementById('loading');
	                    const actionBtn = document.getElementById('login-btn') || document.getElementById('signupButton');
	                    const defaultText = document.getElementById('signupButton') ? 'Create Account' : 'Sign In';
	                    const loadingText = document.getElementById('signupButton') ? 'Creating account...' : 'Signing in...';

	                    if (show) {
	                        if (loadingDiv) loadingDiv.style.display = 'block';
	                        if (actionBtn) {
	                            actionBtn.disabled = true;
	                            actionBtn.textContent = loadingText;
	                        }
	                    } else {
	                        if (loadingDiv) loadingDiv.style.display = 'none';
	                        if (actionBtn) {
	                            actionBtn.disabled = false;
	                            actionBtn.textContent = defaultText;
	                        }
	                    }
	                }

	                function showOAuthLoading(show) {
	                    const overlay = document.getElementById('loading-overlay');
	                    if (!overlay) return;
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

		                const query = new URLSearchParams(window.location.search);
		                if (query.get('error') === 'provider_unavailable') {
		                    showError('Google sign-in is not configured for this CleanHouse runtime.');
		                }
		                completeOAuthRedirectIfPresent();

		                // Focus first input
		                loadAuthConfig();
		                const emailField = document.getElementById('email');
		                if (emailField) {
		                    emailField.focus();
	                }
