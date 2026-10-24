(function () {
    const providerNames = {
        chatgpt: 'OpenAI / ChatGPT',
        anthropic: 'Anthropic / Claude',
        google: 'Google / Gemini',
        xai: 'xAI / Grok',
        microsoft: 'Microsoft Copilot',
        meta: 'Meta AI',
        mistral: 'Mistral',
        perplexity: 'Perplexity',
        cohere: 'Cohere',
        huggingface: 'Hugging Face',
        openrouter: 'OpenRouter',
    };

    let selectedFile = null;
    let notifications = [];
    let dictation = null;
    let dictationActive = false;

    function $(id) {
        return document.getElementById(id);
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
        })[char]);
    }

    function preview(value, max = 180) {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        if (!text) return '';
        return text.length > max ? `${text.slice(0, max - 1)}...` : text;
    }

    function setStatus(message) {
        const status = $('audit-status');
        if (status) status.textContent = message;
    }

    function setTag(text, mode) {
        const tag = $('zaelith-thread-tag');
        if (!tag) return;
        tag.textContent = text;
        tag.className = `one-word-tag ${mode}`;
    }

    function setWorking(active) {
        $('zaelith-notification-btn')?.classList.toggle('is-working', active);
        $('zaelith-send-btn')?.classList.toggle('sending', active);
    }

    function updateSendState() {
        const text = $('zaelith-text');
        const button = $('zaelith-send-btn');
        if (!button || !text) return;
        const hasContent = text.value.trim().length > 0;
        button.classList.toggle('soft', !hasContent);
        button.disabled = !hasContent;
    }

    function updatePillHeight() {
        const text = $('zaelith-text');
        const pill = $('zaelith-message-pill');
        if (!text || !pill) return;
        text.style.height = 'auto';
        const nextHeight = Math.min(Math.max(text.scrollHeight, 24), 120);
        text.style.height = `${nextHeight}px`;
        const expanded = text.value.includes('\n') || nextHeight > 25 || Boolean(selectedFile);
        pill.classList.toggle('expanded', expanded);
    }

    function renderFileChip() {
        const chips = $('zaelith-file-chips');
        if (!chips) return;
        if (!selectedFile) {
            chips.hidden = true;
            chips.innerHTML = '';
            return;
        }
        chips.hidden = false;
        chips.innerHTML = `<span class="zaelith-file-chip">
            <span>${escapeHtml(selectedFile.name)}</span>
            <button id="zaelith-remove-file" type="button" aria-label="Remove upload">x</button>
        </span>`;
        $('zaelith-remove-file')?.addEventListener('click', () => {
            selectedFile = null;
            const input = $('zaelith-file');
            if (input) input.value = '';
            renderFileChip();
            updatePillHeight();
            updateSendState();
        });
    }

    function playChime() {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        try {
            const ctx = new AudioContext();
            const gain = ctx.createGain();
            const osc = ctx.createOscillator();
            osc.type = 'sine';
            osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.0001, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.06, ctx.currentTime + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.22);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.24);
        } catch (error) {
            // Chime is best-effort only.
        }
    }

    function renderNotifications() {
        const menu = $('zaelith-notification-menu');
        const badge = $('zaelith-notification-badge');
        if (!menu || !badge) return;
        badge.hidden = notifications.length === 0;
        badge.textContent = notifications.length ? String(notifications.length) : '0';
        if (notifications.length === 0) {
            menu.innerHTML = '<div class="notification-empty">No Zaelith notifications yet.</div>';
            return;
        }
        menu.innerHTML = notifications.map(item => `<button class="zaelith-notification-item" type="button" data-report-id="${escapeHtml(item.reportId)}">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.detail)}</span>
        </button>`).join('');
        menu.querySelectorAll('[data-report-id]').forEach(button => {
            button.addEventListener('click', () => {
                const reportId = button.getAttribute('data-report-id') || '';
                if (!reportId) return;
                window.location.replace(`/reports?source=zaelith&open=${encodeURIComponent(reportId)}`);
            });
        });
    }

    function addAuditNotification(payload) {
        const report = payload.report || {};
        const analysis = payload.analysis || {};
        const summary = analysis.summary || {};
        if (!report.id) return;
        notifications = [{
            reportId: report.id,
            title: 'Zaelith audit ready',
            detail: `${analysis.risk_level || 'unknown'} risk, ${summary.triggered_indicators ?? 0} indicator(s), ${summary.analysis_confidence || 'unknown'} confidence.`,
        }, ...notifications].slice(0, 5);
        renderNotifications();
        playChime();
    }

    function updateMonitorAfterAudit(payload, submittedText) {
        const analysis = payload.analysis || {};
        const summary = analysis.summary || {};
        const messagePair = document.querySelector('.zaelith-message-pair');
        const costRow = document.querySelector('.zaelith-cost-row');
        if (messagePair) messagePair.hidden = false;
        if (costRow) costRow.hidden = false;
        $('zaelith-provider-label').textContent = 'Manual Zaelith audit';
        $('zaelith-thread-title').textContent = 'Latest submitted text';
        $('zaelith-latest-prompt').textContent = preview(submittedText, 220) || 'Manual audit submitted.';
        $('zaelith-latest-response').textContent = `${analysis.risk_level || 'unknown'} risk, ${summary.triggered_indicators ?? 0} indicator(s), ${summary.analysis_confidence || 'unknown'} confidence.`;
        $('zaelith-model-label').textContent = `Grade ${summary.grade || 'unknown'}`;
        $('zaelith-cost-label').textContent = 'Local audit cost not metered yet';
        $('zaelith-trace-label').textContent = payload.report?.id ? 'Report ready' : 'Report pending';
        const risk = String(analysis.risk_level || '').toLowerCase();
        if (risk === 'high' || risk === 'medium') {
            setTag('Attention', risk === 'high' ? 'alert' : 'attention');
        } else {
            setTag('Green', 'green');
        }
    }

    async function loadAccounts() {
        try {
            const payload = await window.CleanHouseAPI.listConnectedAccounts();
            const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
            const first = accounts[0];
            const addConnection = $('zaelith-add-connection');
            if (first) {
                const provider = String(first.provider || '').toLowerCase();
                $('zaelith-provider-label').textContent = providerNames[provider] || first.provider || 'Connected provider';
                if (addConnection) addConnection.hidden = false;
                setTag('Green', 'green');
            } else {
                $('zaelith-provider-label').textContent = 'No provider connected';
                if (addConnection) addConnection.hidden = true;
                setTag('Attention', 'attention');
            }
        } catch (error) {
            $('zaelith-provider-label').textContent = 'Provider status unavailable';
            const addConnection = $('zaelith-add-connection');
            if (addConnection) addConnection.hidden = true;
            setTag('Attention', 'attention');
        }
    }

    function setupDictation() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const button = $('zaelith-dictate-btn');
        if (!button || !SpeechRecognition) {
            button?.addEventListener('click', () => setStatus('Dictation is not available in this browser.'));
            return;
        }
        dictation = new SpeechRecognition();
        dictation.continuous = false;
        dictation.interimResults = false;
        dictation.onstart = () => {
            dictationActive = true;
            button.classList.add('active');
            setStatus('Listening...');
        };
        dictation.onend = () => {
            dictationActive = false;
            button.classList.remove('active');
            setStatus('Ready');
        };
        dictation.onerror = () => setStatus('Dictation failed.');
        dictation.onresult = event => {
            const text = $('zaelith-text');
            const transcript = Array.from(event.results || [])
                .map(result => result[0]?.transcript || '')
                .join(' ')
                .trim();
            if (text && transcript) {
                text.value = text.value ? `${text.value} ${transcript}` : transcript;
                updatePillHeight();
                updateSendState();
            }
        };
        button.addEventListener('click', () => {
            if (dictationActive) {
                dictation.stop();
                return;
            }
            dictation.start();
        });
    }

    function bindEvents() {
        const form = $('zaelith-form');
        const text = $('zaelith-text');
        const file = $('zaelith-file');
        const pill = $('zaelith-message-pill');

        $('zaelith-notification-btn')?.addEventListener('click', () => {
            const menu = $('zaelith-notification-menu');
            const button = $('zaelith-notification-btn');
            if (!menu || !button) return;
            menu.hidden = !menu.hidden;
            button.setAttribute('aria-expanded', String(!menu.hidden));
        });

        document.querySelectorAll('[data-monitor-tab]').forEach(button => {
            button.addEventListener('click', () => {
                document.querySelectorAll('[data-monitor-tab]').forEach(tab => tab.classList.remove('active'));
                button.classList.add('active');
            });
        });

        $('zaelith-upload-btn')?.addEventListener('click', () => file?.click());
        file?.addEventListener('change', () => {
            const selected = file.files && file.files[0];
            if (!selected) return;
            selectedFile = selected;
            renderFileChip();
            if (selected.type && selected.type.startsWith('image/')) {
                setStatus('Screenshot attached. OCR hook is next; paste text if needed.');
                updatePillHeight();
                updateSendState();
                return;
            }
            const reader = new FileReader();
            reader.onload = () => {
                if (text) text.value = String(reader.result || '');
                setStatus(`${selected.name} loaded`);
                updatePillHeight();
                updateSendState();
            };
            reader.readAsText(selected);
        });

        text?.addEventListener('focus', () => pill?.classList.add('focused'));
        text?.addEventListener('blur', () => pill?.classList.remove('focused'));
        text?.addEventListener('input', () => {
            updatePillHeight();
            updateSendState();
        });
        text?.addEventListener('keydown', event => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                form?.requestSubmit();
            }
        });

        form?.addEventListener('submit', event => {
            event.preventDefault();
            const submittedText = text?.value || '';
            if (!submittedText.trim()) {
                setStatus('Add text to audit.');
                updateSendState();
                return;
            }
            setWorking(true);
            setStatus('Auditing...');
            window.CleanHouseAPI.analyzeZaelithText(submittedText, $('zaelith-prompt')?.value || '', 'zaelith-page')
                .then(payload => {
                    if (payload.status !== 'ok') {
                        setStatus(payload.message || payload.analysis?.error || 'Audit failed.');
                        return;
                    }
                    addAuditNotification(payload);
                    updateMonitorAfterAudit(payload, submittedText);
                    if (text) text.value = '';
                    selectedFile = null;
                    if (file) file.value = '';
                    renderFileChip();
                    updatePillHeight();
                    updateSendState();
                    setStatus('Audit complete');
                })
                .catch(error => {
                    setStatus(error.message || 'Audit failed.');
                })
                .finally(() => {
                    setWorking(false);
                });
        });

        setupDictation();
        renderNotifications();
        renderFileChip();
        updatePillHeight();
        updateSendState();
    }

    document.addEventListener('DOMContentLoaded', () => {
        bindEvents();
        loadAccounts();
    });
})();
