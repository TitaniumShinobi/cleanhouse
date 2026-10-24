(() => {
  const error = document.getElementById('error-message');
  const success = document.getElementById('success-message');
  const show = (node, message) => { node.textContent = message; node.style.display = message ? 'block' : 'none'; };
  let csrfToken = '';
  const csrf = async () => {
    if (csrfToken) return csrfToken;
    const response = await fetch('/api/auth/csrf', { credentials: 'include', headers: { Accept: 'application/json' } });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.csrfToken) throw new Error(payload.message || 'Unable to initialize a protected request.');
    csrfToken = payload.csrfToken;
    return csrfToken;
  };
  const post = async (path, body) => {
    const token = await csrf();
    const response = await fetch(path, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRF-Token': token }, body: JSON.stringify(body) });
    const payload = await response.json().catch(() => ({ success: false, message: 'Authentication response was not valid JSON.' }));
    if (!response.ok) throw new Error(payload.message || 'Request failed.');
    return payload;
  };
  document.getElementById('recovery-form')?.addEventListener('submit', async event => {
    event.preventDefault(); show(error, '');
    try { const result = await post('/api/auth/recovery/request', { email: document.getElementById('email').value.trim() }); show(success, result.message); }
    catch (reason) { show(error, reason.message); }
  });
  document.getElementById('reset-form')?.addEventListener('submit', async event => {
    event.preventDefault(); show(error, '');
    const password = document.getElementById('password').value;
    if (password !== document.getElementById('confirm-password').value) return show(error, 'Passwords do not match.');
    try {
      const token = new URLSearchParams(location.search).get('token') || '';
      const result = await post('/api/auth/recovery/reset', { token, password });
      show(success, result.message); setTimeout(() => { location.href = '/login'; }, 800);
    } catch (reason) { show(error, reason.message); }
  });
})();
