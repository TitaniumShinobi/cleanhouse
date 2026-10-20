document.getElementById('cleanhouse-logout')?.addEventListener('click', async () => {
  const button = document.getElementById('cleanhouse-logout');
  button.disabled = true;
  try {
    if (!window.authState) throw new Error('Authentication state unavailable');
    await window.authState.logout();
    window.location.assign('/login');
  } catch (error) {
    button.textContent = 'Sign out failed. Try again.';
    button.disabled = false;
  }
});
