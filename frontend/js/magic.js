(function () {
  'use strict';
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get('token') || '';
  const intent = params.get('intent') || '';
  history.replaceState(history.state, '', '/magic');
  const button = document.getElementById('magic-confirm');
  const status = document.getElementById('magic-status');
  if (!token || !['signin', 'signup'].includes(intent)) {
    button.disabled = true;
    status.textContent = 'This confirmation link is malformed.';
    return;
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    status.textContent = 'Confirming…';
    try {
      const csrfResponse = await fetch('/api/auth/csrf', { credentials: 'include', headers: { Accept: 'application/json' } });
      const csrfPayload = await csrfResponse.json();
      const response = await fetch('/api/auth/magic/verify', {
        method: 'POST',
        credentials: 'include',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfPayload.csrfToken || '',
        },
        body: JSON.stringify({ token, intent }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.message || 'Confirmation failed.');
      window.location.replace('/overview');
    } catch (error) {
      status.textContent = error.message || 'Confirmation failed.';
      button.disabled = false;
    }
  });
})();
