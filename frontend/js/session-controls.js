document.getElementById('cleanhouse-logout')?.addEventListener('click', async () => {
  const button = document.getElementById('cleanhouse-logout');
  button.disabled = true;
  try {
    if (window.authState) await window.authState.logout();
  } finally {
    window.location.assign('/login');
  }
});
