(function () {
    function setStatus(message) {
        const status = document.getElementById('zaelith-connect-status');
        if (status) status.textContent = message;
    }

    document.addEventListener('click', event => {
        const button = event.target.closest('[data-connect-provider]');
        if (!button) return;
        const provider = button.dataset.connectProvider;
        const method = button.dataset.connectMethod;
        setStatus('Starting...');
        window.CleanHouseAPI.startAccountConnect(provider, method)
            .then(result => {
                if (result.status === 'ok' && result.connect_url) {
                    window.location.href = result.connect_url;
                    return;
                }
                setStatus(result.message || 'Connector prepared');
            })
            .catch(error => setStatus(error.message || 'Connection failed.'));
    });
})();
