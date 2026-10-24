(async function () {
    const userBox = document.getElementById('account-delete-user');
    const form = document.getElementById('account-delete-form');
    const input = document.getElementById('delete-confirmation');
    const button = document.getElementById('delete-account-button');
    const passwordInput = document.getElementById('delete-password');
    const emailReauthButton = document.getElementById('delete-email-reauth');
    const result = document.getElementById('account-delete-result');
    let reauthToken = '';
    const setResult = (message, kind) => { result.textContent = message; result.className = 'account-delete-result ' + (kind || ''); };

    if (window.authState) await window.authState.init();
    const user = window.authState?.getUser();
    if (!user?.email) {
        userBox.textContent = 'No signed-in CleanHouse account was found in this browser.';
        form.style.display = 'none';
        setResult('Sign in before deleting an account.', 'error');
        return;
    }
    userBox.textContent = 'Signed in as ' + user.email;
    input.placeholder = user.email;

    async function csrf() {
        const response = await fetch('/api/auth/csrf', { credentials: 'include', headers: { Accept: 'application/json' } });
        const payload = await response.json();
        if (!response.ok || !payload.csrfToken) throw new Error(payload.message || 'Unable to initialize a protected request.');
        return payload.csrfToken;
    }

    async function verifyEmailFragment() {
        const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''));
        const token = fragment.get('reauth');
        if (!token || fragment.get('scope') !== 'account') return;
        history.replaceState(history.state, '', window.location.pathname + window.location.search);
        const csrfToken = await csrf();
        const response = await fetch('/api/auth/reauth', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
            body: JSON.stringify({ method: 'magic_email_verify', token, scope: 'account' }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.reauthToken) throw new Error(payload.message || 'Email confirmation failed.');
        reauthToken = payload.reauthToken;
        setResult('Recent email reauthentication confirmed. You may delete the account.', 'success');
    }

    emailReauthButton.addEventListener('click', async () => {
        emailReauthButton.disabled = true;
        try {
            const csrfToken = await csrf();
            const response = await fetch('/api/auth/reauth', {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                body: JSON.stringify({ method: 'magic_email_request', scope: 'account', return_path: '/account/delete' }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.message || 'Email confirmation could not be sent.');
            setResult(payload.message || 'A single-use confirmation link was sent.', 'success');
        } catch (error) {
            setResult(error.message || 'Email confirmation could not be sent.', 'error');
        } finally {
            emailReauthButton.disabled = false;
        }
    });

    try { await verifyEmailFragment(); } catch (error) { setResult(error.message || 'Email confirmation failed.', 'error'); }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const confirmation = input.value.trim();
        if (confirmation.toLowerCase() !== String(user.email).toLowerCase()) return setResult('Type the account email exactly to confirm deletion.', 'error');
        button.disabled = true; button.textContent = 'Deleting...';
        try {
            const csrfToken = await csrf();
            if (!reauthToken) {
                if (!passwordInput.value) throw new Error('Enter the current password or confirm by email.');
                const reauthResponse = await fetch('/api/auth/reauth', {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                    body: JSON.stringify({ password: passwordInput.value, scope: 'account' }),
                });
                const reauth = await reauthResponse.json();
                passwordInput.value = '';
                if (!reauthResponse.ok || !reauth.reauthToken) throw new Error(reauth.message || 'Reauthentication failed');
                reauthToken = reauth.reauthToken;
            }
            const response = await fetch('/api/auth/account', { method: 'DELETE', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken, 'X-CleanHouse-Reauth': reauthToken }, body: JSON.stringify({ confirmation }) });
            reauthToken = '';
            const payload = await response.json();
            if (!response.ok || !payload.success) throw new Error(payload.message || 'Account deletion failed');
            window.authState?.clear(); form.style.display = 'none'; setResult(payload.message || 'Account deleted.', 'success');
        } catch (error) {
            button.disabled = false; button.textContent = 'Delete Account'; setResult(error.message || 'Account deletion failed.', 'error');
        }
    });
})();
