(function () {
    const userBox = document.getElementById('account-delete-user');
    const form = document.getElementById('account-delete-form');
    const input = document.getElementById('delete-confirmation');
    const button = document.getElementById('delete-account-button');
    const result = document.getElementById('account-delete-result');

    function readUser() {
        try {
            return JSON.parse(localStorage.getItem('user') || 'null');
        } catch (_error) {
            return null;
        }
    }

    function setResult(message, kind) {
        result.textContent = message;
        result.className = 'account-delete-result ' + (kind || '');
    }

    const token = localStorage.getItem('auth_token') || '';
    const user = readUser();

    if (!token || !user || !user.email) {
        userBox.textContent = 'No signed-in CleanHouse account was found in this browser.';
        form.style.display = 'none';
        setResult('Sign in before deleting an account.', 'error');
        return;
    }

    userBox.textContent = 'Signed in as ' + user.email;
    input.placeholder = user.email;

    form.addEventListener('submit', async function (event) {
        event.preventDefault();
        const confirmation = input.value.trim();
        if (confirmation.toLowerCase() !== String(user.email).toLowerCase()) {
            setResult('Type the account email exactly to confirm deletion.', 'error');
            return;
        }

        button.disabled = true;
        button.textContent = 'Deleting...';
        setResult('Deleting local account and clearing matching VVAULT records...', '');

        try {
            const response = await fetch('/api/auth/account', {
                method: 'DELETE',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ confirmation }),
            });
            const payload = await response.json();
            if (!response.ok || !payload.success) {
                throw new Error(payload.message || 'Account deletion failed');
            }

            localStorage.removeItem('auth_token');
            localStorage.removeItem('user');
            form.style.display = 'none';
            setResult(payload.message || 'Account deleted.', 'success');
        } catch (error) {
            button.disabled = false;
            button.textContent = 'Delete Account';
            setResult(error.message || 'Account deletion failed.', 'error');
        }
    });
})();
