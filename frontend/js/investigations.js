let applications = [];
let applicationsLoaded = false;
let selectedApp = null;
let selectedFilter = '';
let runtimeNotifications = [];
let currentFileEvents = [];
let currentFileFindings = [];
let currentFileIntegrity = {};
let currentFileLocations = [];
let currentFileSuggestions = [];
let filesLoaded = false;
let selectedFilesView = 'changes';
let filesSearchQuery = '';
let filesLiveSource = null;
let filesSnapshotCursor = '';
let currentNetworkData = null;
let currentNetworkTableData = null;
let currentNetworkProjectionData = null;
let currentNetworkHeaderData = {
    state: 'NO_DATA',
    events: [],
    summary: {},
    assessments: [],
    assessmentRefs: [],
    assessmentSummary: null,
    assessmentFilter: null,
    osActiveConnectionCount: null,
    totalConnectionCount: 0,
    displayedConnectionCount: 0,
    displayedConnectionCountCapped: false,
    activeConnectionCount: 0,
    activeSocketCount: 0,
    packetCount: 0,
    captureAvailable: true,
    lastPacketAt: 0,
    lastSnapshotAt: 0,
    latestTags: null,
    evidenceBySource: {},
    latchedReason: '',
    latchedReasons: [],
    latchedState: '',
    latchedPriority: 0,
    latchedFirstSeenAt: 0,
    latchedLastSeenAt: 0,
    lastCleanSnapshotAt: 0,
};
let networkPagePhase = 'starting';
let networkPagePhaseReason = 'initial';
let networkServerLifecycle = 'unknown';
let networkHeaderSnapshotRequested = false;
let networkHeaderSnapshotInFlight = false;
let networkSnapshotActivePromise = null;
let networkSnapshotPendingDemand = null;
let networkSnapshotFailureCount = 0;
let networkSnapshotBackoffUntil = 0;
let currentNetworkTrendBaseData = null;
let networkTimelineLastGoodData = null;
let networkTimelineLastGoodMeta = { range: '', epoch: 0 };
let networkProjectionCache = {};
let networkProjectionRequestId = 0;
let networkSnapshotRequestId = 0;
let networkHydrationEpoch = 0;
let networkSnapshotAbortController = null;
let networkProjectionAbortController = null;
let networkDocumentHiddenAt = 0;
let networkSettledProjectionState = {
    findings: null,
    trend: null,
    distribution: null,
    timeline: null,
};
let networkViewMode = 'table';
let networkTimelineRangeMode = '5s';
let networkTrendMetric = 'connections';
let networkLiveSource = null;
let networkLiveStartTimer = null;
let networkLiveQuietTimer = null;
let networkLiveRenderTimer = null;
let networkHeaderRenderTimer = null;
let networkHeaderRenderPending = false;
let networkLiveLastEventAt = 0;
let networkLiveEvidenceEstablished = false;
let networkLiveLastQuietSnapshotAt = 0;
let networkSnapshotCursor = '';
let networkLastAppliedCursor = '';
let networkCursorEpoch = '';
let networkLiveEventOrdinal = 0;
let networkLiveReplayBuffer = [];
let networkLiveSeenDeliveryKeys = new Set();
let networkLiveSeenDeliveryOrder = [];
let networkTrendLiveDirty = false;
let networkTrendLiveTape = [];
let networkTableFlushTimer = null;
let networkTableUiBuffer = [];
let networkTableHiddenPacketCount = 0;
let networkRenderSuspended = false;
let networkWindowBackgrounded = false;
let networkVisibilityPendingHydration = false;
let networkForegroundRecoveryTimer = null;
let networkDeferredRenderFlags = {
    display: false,
    table: false,
    header: false,
    sidebar: false,
    timeline: false,
    trend: false,
};
let networkTableRenderState = {
    rowKeys: [],
    rowSignatures: [],
    lastReason: '',
    lastFilterReason: '',
};
let networkStreamTags = null;
let networkCtrlRouteTarget = null;
let networkTablePinnedEntityId = '';
let networkTablePinnedRowSnapshot = null;
let networkTableSort = { key: 'time', direction: 'desc' };
let currentNetworkTags = { status: 'NO_DATA', state: 'NO_DATA', reasons: [], explanation: '' };
let networkActionFilterReason = '';
let actionSidebarOpen = false;
let actionSidebarPage = 'network';
let evidenceCommandContext = null;
let evidenceCommandActions = [];
let evidenceCommandError = '';
let evidenceCommandStatus = '';
let evidenceCommandLoading = false;
let evidenceInsightResult = null;
let evidenceInsightLoading = false;
let evidenceInsightError = '';
let evidenceInsightRequestKey = '';
let evidenceInsightReceipt = '';
let filesMediationPanelOpen = false;
let filesMediationBoardOpen = false;
let filesMediationQueue = [];
let filesMediationSearchQuery = '';
let filesMediationDraft = '';
let filesMediationScope = 'all';
let filesMediationEvidenceNames = [];
let evidenceAutoInsightSelectionKey = '';
let evidenceCommandSelectionKey = '';
let evidenceCommandSnapshot = null;
let actionSidebarDeferredDetailsReady = false;
let actionSidebarDeferredRenderRequestId = 0;
let actionSidebarDeferredFrame = null;
let actionSidebarDeferredTimer = null;
let actionSidebarRenderFrame = null;
let actionSidebarRenderTimer = null;
let actionSidebarLastBodyHtml = '';
let controlKeyChordActive = false;
let actionSidebarRequestEpoch = 0;
let evidenceInsightRequestEpoch = 0;
let evidenceActionRequestEpoch = 0;
let networkCoordinatorState = null;
let networkStartupInstrumentation = { epoch: 0, headerCountAvailable: false, firstRowRendered: false };
const networkColumnWidths = {
    time: 82,
    app: 120,
    source: 168,
    destination: 180,
    protocol: 90,
    port: 70,
    translation: 430,
};
const APPLICATION_RENDER_LIMIT = 500;
const PROCESS_RENDER_LIMIT = 5;
const NETWORK_LIVE_QUIET_MS = 30000;
const NETWORK_OS_SUMMARY_REFRESH_MS = 30000;
const NETWORK_LIVE_START_DELAY_MS = 900;
const NETWORK_LIVE_EVENT_LIMIT = 300;
const NETWORK_LIVE_REPLAY_LIMIT = 600;
const NETWORK_LIVE_DELIVERY_KEY_LIMIT = 2400;
const NETWORK_TABLE_DOM_ROW_LIMIT = 120;
const NETWORK_TABLE_FLUSH_MS = 180;
const NETWORK_HEADER_FLUSH_MS = 500;
const NETWORK_SNAPSHOT_BACKOFF_BASE_MS = 1000;
const NETWORK_SNAPSHOT_BACKOFF_MAX_MS = 30000;
const NETWORK_TREND_LIVE_TICK_LIMIT = 2000;
const NETWORK_TREND_Y_AXIS_OPTIONS = [100, 250, 500, 1000];
let networkTrendYAxisMax = 250;
const NETWORK_VIEW_STORAGE_KEY = 'cleanhouse.network.view';
const NETWORK_TIMELINE_RANGE_STORAGE_KEY = 'cleanhouse.network.timeline.range';
const NETWORK_TREND_Y_AXIS_STORAGE_KEY = 'cleanhouse.network.trend.yAxisMax';
const NETWORK_TREND_METRIC_STORAGE_KEY = 'cleanhouse.network.trend.metric';
const NETWORK_SERVER_BOOT_STORAGE_KEY = 'cleanhouse.network.serverBootId';
const NETWORK_VIEW_MODES = new Set(['table', 'findings', 'bar', 'pie', 'timeline']);
const NETWORK_TREND_METRICS = new Set(['connections', 'strengths', 'vulnerabilities', 'threats']);
const NETWORK_CTRL_VIEW_ALIASES = {
    table: 'table',
    findings: 'findings',
    distribution: 'pie',
    timeline: 'timeline',
};
const CTRL_ACTION_LABELS = {
    mark_read: 'Mark as Read',
    mark_unread: 'Mark as Unread',
    observe: 'Observe',
    restrict: 'Restrict',
    block: 'Block',
    quarantine: 'Quarantine',
    terminate: 'Terminate',
    export: 'Export',
    copy: 'Copy',
    allow: 'Allow',
};
const CTRL_ACTION_GROUPS = [
    { key: 'monitoring', label: 'Monitoring', actions: ['observe', 'allow'] },
    { key: 'evidence', label: 'Evidence', actions: ['mark_read', 'mark_unread', 'copy', 'export'] },
    { key: 'enforcement', label: 'Enforcement', actions: ['restrict', 'block', 'quarantine', 'terminate'] },
];
const CTRL_REPORT_ACTION_IDS = new Set([
    'mark_read',
    'mark_unread',
    'observe',
    'restrict',
    'block',
    'quarantine',
    'terminate',
    'export',
    'copy',
    'allow',
]);
const CTRL_SUBJECT_TYPES = new Set(['event', 'finding', 'app_process', 'destination', 'port', 'time_bucket', 'aggregate_group']);
const CTRL_THREAT_REASONS = new Set([
    'known malicious endpoint',
    'blocked threat active',
    'data exfiltration suspected',
    'malware process active',
    'suspicious listener exposed',
    'repeated failed connections',
    'unexpected inbound access',
    'privilege process online',
    'malicious',
    'threat',
    'quarantine bypass suspected',
]);
function normalizeNetworkModeValue(value) {
    return String(value || '').trim().toLowerCase();
}
const NETWORK_TIMELINE_RANGES = {
    '5s': { label: '-5s', title: 'Last 5 seconds', durationMs: 5 * 1000, buckets: 5, maxMarkers: 18, minPriority: 1 },
    '1m': { label: '-1m', title: 'Last minute', durationMs: 60 * 1000, buckets: 18, maxMarkers: 24, minPriority: 1 },
    '30m': { label: '-30m', title: 'Last 30 minutes', durationMs: 30 * 60 * 1000, buckets: 24, maxMarkers: 28, minPriority: 2 },
    '1h': { label: '-1h', title: 'Last hour', durationMs: 60 * 60 * 1000, buckets: 24, maxMarkers: 28, minPriority: 2 },
    '24h': { label: '-24h', title: 'Last 24 hours', durationMs: 24 * 60 * 60 * 1000, buckets: 30, maxMarkers: 30, minPriority: 3 },
    '7d': { label: '-7d', title: 'Last 7 days', durationMs: 7 * 24 * 60 * 60 * 1000, buckets: 32, maxMarkers: 32, minPriority: 3 },
    '1mo': { label: '-1mo', title: 'Last month', durationMs: 30 * 24 * 60 * 60 * 1000, buckets: 36, maxMarkers: 36, minPriority: 3 },
    '3mo': { label: '-3mo', title: 'Last 3 months', durationMs: 90 * 24 * 60 * 60 * 1000, buckets: 36, maxMarkers: 36, minPriority: 3 },
    '12mo': { label: '-12mo', title: 'Last year', durationMs: 365 * 24 * 60 * 60 * 1000, buckets: 40, maxMarkers: 40, minPriority: 3 },
};
const NETWORK_TIMELINE_VISIBLE_RANGE_KEYS = ['1m', '30m', '1h', '24h', '7d', '1mo', '3mo', '12mo'];
const NETWORK_CONTRACT_STATES = new Set(['READY', 'CAPTURING', 'NO_DATA', 'WARMING', 'ERROR', 'CAPTURE_BLOCKED']);
const NETWORK_STATUS_TAGS = new Set(['OBSERVING', 'QUIET', 'LOCAL ONLY', 'OFFLINE']);
const NETWORK_STATE_TAGS = new Set(['HEALTHY', 'DEGRADED', 'CRITICAL', 'UNKNOWN']);
const NETWORK_REASON_TAGS = new Set([
    'Destination name missing',
    'Unknown app active',
    'New destination seen',
    'Many destinations contacted',
    'High connection volume',
    'Unusual port used',
    'Unencrypted web request',
    'Capture engine limited',
    'Permission blocks capture',
    'Fallback mode active',
    'Interface changed',
    'Connection attempts failed',
    'Local traffic only',
    'Known malicious endpoint',
    'Blocked threat active',
    'Data exfiltration suspected',
    'Malware process active',
    'Suspicious listener exposed',
    'Repeated failed connections',
    'Unsigned app communicating',
    'Unexpected inbound access',
    'Privilege process online',
    'Quarantine bypass suspected',
    'Capture failed',
]);
const NETWORK_REASON_PRIORITIES = {
    'Known malicious endpoint': 100,
    'Blocked threat active': 99,
    'Data exfiltration suspected': 98,
    'Malware process active': 97,
    'Suspicious listener exposed': 96,
    'Repeated failed connections': 95,
    'Unsigned app communicating': 94,
    'Unexpected inbound access': 93,
    'Privilege process online': 92,
    'Quarantine bypass suspected': 91,
    'Unknown app active': 50,
    'Unusual port used': 49,
    'Destination name missing': 48,
    'New destination seen': 47,
    'Many destinations contacted': 46,
    'High connection volume': 45,
    'Unencrypted web request': 44,
    'Capture engine limited': 43,
    'Permission blocks capture': 42,
    'Fallback mode active': 41,
    'Interface changed': 40,
    'Connection attempts failed': 39,
    'Local traffic only': 38,
    'Restarting': 37,
};
const NETWORK_CAPTURE_HEALTH_REASONS = new Set([
    'Capture engine limited',
    'Permission blocks capture',
    'Fallback mode active',
    'Interface changed',
    'Connection attempts failed',
    'Capture failed',
    'Restarting',
]);
const NETWORK_CRITICAL_REASONS = new Set([
    'Known malicious endpoint',
    'Blocked threat active',
    'Data exfiltration suspected',
    'Malware process active',
    'Suspicious listener exposed',
    'Repeated failed connections',
    'Unsigned app communicating',
    'Unexpected inbound access',
    'Privilege process online',
    'Quarantine bypass suspected',
]);
const NETWORK_REASON_LABELS = {
    ready: 'ready',
    no_data: 'no_data',
    snapshot: 'snapshot',
    events_observed: 'events_observed',
    waiting_for_capture: 'Restarting',
    permission_blocked: 'permission_blocked',
    capture_failed: 'Capture failed',
    capture_backlog: 'Capture engine limited',
    timeout: 'timeout',
    engine_unavailable: 'engine_unavailable',
};
const NETWORK_TABLE_COLUMNS = [
    { key: 'time', label: 'Time', className: 'network-col-time' },
    { key: 'app', label: 'App', className: 'network-col-app' },
    { key: 'source', label: 'Source', className: 'network-col-source' },
    { key: 'destination', label: 'Destination', className: 'network-col-destination' },
    { key: 'protocol', label: 'Protocol', className: 'network-col-protocol' },
    { key: 'port', label: 'Port', className: 'network-col-port' },
    { key: 'translation', label: 'Translation', className: 'network-col-translation' },
];

function byId(id) {
    return document.getElementById(id);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function setText(id, value) {
    const el = byId(id);
    if (el) el.textContent = value || 'Unknown';
}

function reportFrontendDegraded(error) {
    const message = String(error?.message || error || 'CleanHouse runtime is reconnecting.');
    setText('network-area-status', 'Runtime degraded');
    setText('apps-area-status', 'Runtime degraded');
    const networkMessage = byId('network-message');
    if (networkMessage && networkMessage.textContent.trim()) {
        const base = networkMessage.textContent.replace(/\s+·\s+Reconnecting$/, '').trim();
        networkMessage.textContent = base ? `${base} · Reconnecting` : 'Reconnecting';
    }
}

function validNetworkViewMode(value) {
    const mode = normalizeNetworkModeValue(value);
    return NETWORK_VIEW_MODES.has(mode) ? mode : '';
}

function validNetworkTimelineRange(value) {
    return Object.prototype.hasOwnProperty.call(NETWORK_TIMELINE_RANGES, value) ? value : '';
}

function validNetworkTrendYAxisMax(value) {
    const numeric = Number(value);
    return NETWORK_TREND_Y_AXIS_OPTIONS.includes(numeric) ? numeric : 0;
}

function validNetworkTrendMetric(value) {
    const metric = normalizeNetworkModeValue(value);
    return NETWORK_TREND_METRICS.has(metric) ? metric : '';
}

function networkViewFromUrl() {
    try {
        const params = new URLSearchParams(window.location.search);
        return validNetworkViewMode(params.get('network_view') || params.get('view'));
    } catch (error) {
        return '';
    }
}

function networkTimelineRangeFromUrl() {
    try {
        const params = new URLSearchParams(window.location.search);
        return validNetworkTimelineRange(normalizeNetworkModeValue(params.get('network_timeline') || params.get('timeline')));
    } catch (error) {
        return '';
    }
}

function networkTrendYAxisMaxFromUrl() {
    try {
        const params = new URLSearchParams(window.location.search);
        return validNetworkTrendYAxisMax(params.get('network_trend_y') || params.get('trend_y'));
    } catch (error) {
        return 0;
    }
}

function storedNetworkViewMode() {
    try {
        return validNetworkViewMode(window.localStorage?.getItem(NETWORK_VIEW_STORAGE_KEY));
    } catch (error) {
        return '';
    }
}

function storedNetworkTimelineRange() {
    try {
        return validNetworkTimelineRange(normalizeNetworkModeValue(window.localStorage?.getItem(NETWORK_TIMELINE_RANGE_STORAGE_KEY)));
    } catch (error) {
        return '';
    }
}

function storedNetworkTrendYAxisMax() {
    try {
        return validNetworkTrendYAxisMax(window.localStorage?.getItem(NETWORK_TREND_Y_AXIS_STORAGE_KEY));
    } catch (error) {
        return 0;
    }
}

function storedNetworkTrendMetric() {
    try {
        return validNetworkTrendMetric(window.localStorage?.getItem(NETWORK_TREND_METRIC_STORAGE_KEY));
    } catch (error) {
        return '';
    }
}

function restoreNetworkViewMode() {
    networkViewMode = networkViewFromUrl() || storedNetworkViewMode() || validNetworkViewMode(networkViewMode) || 'table';
    networkTimelineRangeMode = networkTimelineRangeFromUrl() || storedNetworkTimelineRange() || validNetworkTimelineRange(networkTimelineRangeMode) || '5s';
    networkTrendYAxisMax = networkTrendYAxisMaxFromUrl() || storedNetworkTrendYAxisMax() || validNetworkTrendYAxisMax(networkTrendYAxisMax) || 250;
    networkTrendMetric = storedNetworkTrendMetric() || validNetworkTrendMetric(networkTrendMetric) || 'connections';
    syncNetworkCoordinatorUiState();
}

function persistNetworkTrendMetric(value) {
    networkTrendMetric = validNetworkTrendMetric(value) || 'connections';
    networkProjectionCache = {};
    try {
        window.localStorage?.setItem(NETWORK_TREND_METRIC_STORAGE_KEY, networkTrendMetric);
    } catch (error) {
        // localStorage may be unavailable in restricted browser contexts.
    }
}

function persistNetworkViewMode(mode) {
    networkViewMode = validNetworkViewMode(mode) || 'table';
    syncNetworkCoordinatorUiState();
    try {
        window.localStorage?.setItem(NETWORK_VIEW_STORAGE_KEY, networkViewMode);
    } catch (error) {
        // localStorage may be unavailable in restricted browser contexts.
    }
    if (!window.location.pathname.startsWith('/network')) return;
    try {
        const url = new URL(window.location.href);
        url.searchParams.set('network_view', networkViewMode);
        window.history.replaceState({}, '', url);
    } catch (error) {
        // URL persistence is best-effort; localStorage keeps the tab choice.
    }
}

function persistNetworkTimelineRange(mode) {
    networkTimelineRangeMode = validNetworkTimelineRange(mode) || '5s';
    syncNetworkCoordinatorUiState();
    try {
        window.localStorage?.setItem(NETWORK_TIMELINE_RANGE_STORAGE_KEY, networkTimelineRangeMode);
    } catch (error) {
        // localStorage may be unavailable in restricted browser contexts.
    }
    if (!window.location.pathname.startsWith('/network')) return;
    try {
        const url = new URL(window.location.href);
        url.searchParams.set('network_timeline', networkTimelineRangeMode);
        window.history.replaceState({}, '', url);
    } catch (error) {
        // URL persistence is best-effort; localStorage keeps the range choice.
    }
}

function persistNetworkTrendYAxisMax(value) {
    networkTrendYAxisMax = validNetworkTrendYAxisMax(value) || 250;
    try {
        window.localStorage?.setItem(NETWORK_TREND_Y_AXIS_STORAGE_KEY, String(networkTrendYAxisMax));
    } catch (error) {
        // localStorage may be unavailable in restricted browser contexts.
    }
    if (!window.location.pathname.startsWith('/network')) return;
    try {
        const url = new URL(window.location.href);
        url.searchParams.set('network_trend_y', String(networkTrendYAxisMax));
        window.history.replaceState({}, '', url);
    } catch (error) {
        // URL persistence is best-effort; localStorage keeps the axis choice.
    }
}

function networkTimelineDisplayRangeMode(rangeKey = networkTimelineRangeMode) {
    const normalized = validNetworkTimelineRange(rangeKey);
    if (!normalized || normalized === '5s') return '1m';
    return normalized;
}

function networkTimelineSelectedRangeMode(rangeKey = networkTimelineRangeMode) {
    return validNetworkTimelineRange(rangeKey) || '5s';
}

function createNetworkCoordinatorState() {
    return {
        snapshot: {
            epoch: 0,
            version: 0,
            data: null,
        },
        ui: {
            activeView: networkViewMode,
            selectedRangeByView: {
                findings: networkTimelineSelectedRangeMode(networkTimelineRangeMode),
                trend: networkTimelineSelectedRangeMode(networkTimelineRangeMode),
                distribution: networkTimelineSelectedRangeMode(networkTimelineRangeMode),
                timeline: networkTimelineSelectedRangeMode(networkTimelineRangeMode),
            },
        },
        projections: {
            findings: {},
            trend: {},
            distribution: {},
            timeline: {},
        },
        live: {
            trendTape: networkTrendLiveTape,
        },
        requests: {
            hydrationEpoch: 0,
            snapshot: { requestId: 0, status: 'idle' },
            projection: {
                requestId: 0,
                view: '',
                selectedRange: '5s',
                effectiveFetchRange: '5s',
                status: 'idle',
            },
        },
        viewStates: {
            page: { phase: networkPagePhase, reason: networkPagePhaseReason },
            tabs: {
                table: { phase: 'starting', copy: 'Starting network view.' },
                findings: { phase: 'starting', copy: 'Grouped findings will load when Findings opens.' },
                trend: { phase: 'starting', copy: 'Saved and live trend will load when Trend opens.' },
                distribution: { phase: 'starting', copy: 'App distribution will load when Distribution opens.' },
                timeline: { phase: 'starting', copy: 'Event history will load when Timeline opens.' },
            },
        },
        render: {
            key: null,
            version: 0,
            model: null,
        },
    };
}

function ensureNetworkCoordinatorState() {
    if (!networkCoordinatorState) {
        networkCoordinatorState = createNetworkCoordinatorState();
    }
    return networkCoordinatorState;
}

function syncNetworkCoordinatorUiState() {
    const coordinator = ensureNetworkCoordinatorState();
    coordinator.ui.activeView = networkViewMode;
    const selectedRange = networkTimelineSelectedRangeMode(networkTimelineRangeMode);
    coordinator.ui.selectedRangeByView.findings = selectedRange;
    coordinator.ui.selectedRangeByView.trend = selectedRange;
    coordinator.ui.selectedRangeByView.distribution = selectedRange;
    coordinator.ui.selectedRangeByView.timeline = selectedRange;
    coordinator.live.trendTape = networkTrendLiveTape;
    coordinator.viewStates.page = { phase: networkPagePhase, reason: networkPagePhaseReason };
    return coordinator;
}

function setNetworkPagePhase(phase, reason = '') {
    networkPagePhase = String(phase || 'ready');
    networkPagePhaseReason = String(reason || '');
    syncNetworkCoordinatorUiState();
}

function logNetworkStartup(stage, details = {}) {
    console.info('[CleanHouse Network startup]', {
        stage,
        epoch: networkHydrationEpoch,
        timestamp: new Date().toISOString(),
        ...details,
    });
}

function observeNetworkServerBoot(response = {}, requestReason = '') {
    const bootId = String(response?.server_boot_id || '').trim();
    if (!bootId || normalizeNetworkContractState(response?.state || 'ERROR') === 'ERROR') return networkServerLifecycle;
    let previousBootId = '';
    try {
        previousBootId = String(window.localStorage?.getItem(NETWORK_SERVER_BOOT_STORAGE_KEY) || '').trim();
    } catch (error) {
        previousBootId = '';
    }
    networkServerLifecycle = requestReason === 'manual-refresh'
        ? 'manual-refresh'
        : (!previousBootId ? 'first-visit' : (previousBootId === bootId ? 'page-reload' : 'server-restarted'));
    try {
        window.localStorage?.setItem(NETWORK_SERVER_BOOT_STORAGE_KEY, bootId);
    } catch (error) {
        // Lifecycle classification remains valid for this page even when storage is unavailable.
    }
    return networkServerLifecycle;
}

function networkCoordinatorSelectedRange(view = networkProjectionViewForMode(networkViewMode) || networkViewMode) {
    const coordinator = ensureNetworkCoordinatorState();
    const key = String(view || '').trim();
    return coordinator.ui.selectedRangeByView[key] || networkTimelineSelectedRangeMode(networkTimelineRangeMode);
}

function networkCoordinatorEffectiveFetchRange(view, selectedRange = networkCoordinatorSelectedRange(view)) {
    return view === 'timeline'
        ? networkTimelineDisplayRangeMode(selectedRange)
        : networkTimelineSelectedRangeMode(selectedRange);
}

function networkProjectionRangeForView(view) {
    return networkCoordinatorEffectiveFetchRange(view);
}

function networkCoordinatorProjectionStore(view) {
    const coordinator = ensureNetworkCoordinatorState();
    const key = String(view || '').trim();
    if (!key) return null;
    if (!coordinator.projections[key]) coordinator.projections[key] = {};
    return coordinator.projections[key];
}

function networkCoordinatorProjectionRecord(view, selectedRange = networkCoordinatorSelectedRange(view)) {
    const store = networkCoordinatorProjectionStore(view);
    if (!store) return null;
    const key = view === 'trend' ? `${selectedRange}:${networkTrendMetric}` : selectedRange;
    return store[key] || null;
}

function networkCoordinatorRememberSnapshot(data, epoch = networkHydrationEpoch, requestId = networkSnapshotRequestId) {
    const coordinator = syncNetworkCoordinatorUiState();
    coordinator.snapshot = {
        epoch,
        version: Number(coordinator.snapshot?.version || 0) + 1,
        data: cloneNetworkProjectionData(data),
    };
    coordinator.requests.hydrationEpoch = epoch;
    coordinator.requests.snapshot = { requestId, status: 'settled' };
    coordinator.viewStates.tabs.table = networkTabSettledState('table', data || {});
}

function networkCoordinatorSetProjectionLoading(view, selectedRange, effectiveFetchRange, epoch, requestId) {
    const coordinator = syncNetworkCoordinatorUiState();
    coordinator.requests.hydrationEpoch = epoch;
    coordinator.requests.projection = {
        requestId,
        view,
        selectedRange,
        effectiveFetchRange,
        status: 'loading',
    };
    const tab = networkModeForProjectionView(view);
    if (tab) {
        coordinator.viewStates.tabs[tab] = {
            phase: networkPagePhase === 'refreshing' ? 'refreshing' : 'loading',
            copy: networkTabLoadingCopy(tab, networkPagePhase),
        };
    }
}

function networkCoordinatorRememberProjection(view, selectedRange, effectiveFetchRange, data, epoch = networkHydrationEpoch, requestId = networkProjectionRequestId) {
    if (!view) return;
    const coordinator = syncNetworkCoordinatorUiState();
    const payload = cloneNetworkProjectionData(data);
    if (view === 'trend') payload.summary = { range: selectedRange, metric: networkTrendMetric, ...payload.summary };
    const key = view === 'trend' ? `${selectedRange}:${networkTrendMetric}` : selectedRange;
    networkCoordinatorProjectionStore(view)[key] = {
        view,
        selectedRange,
        effectiveFetchRange,
        epoch,
        requestId,
        receivedAt: Date.now(),
        status: 'settled',
        data: payload,
    };
    coordinator.requests.hydrationEpoch = epoch;
    coordinator.requests.projection = {
        requestId,
        view,
        selectedRange,
        effectiveFetchRange,
        status: 'settled',
    };
    const tab = networkModeForProjectionView(view);
    if (tab) {
        coordinator.viewStates.tabs[tab] = networkTabSettledState(tab, payload);
    }
}

function firstPresent(source, paths) {
    for (const path of paths) {
        let value = source;
        for (const key of path) {
            if (value == null || typeof value !== 'object' || !(key in value)) {
                value = undefined;
                break;
            }
            value = value[key];
        }
        if (value !== undefined && value !== null && value !== '') return value;
    }
    return undefined;
}

function valueOrUnavailable(value) {
    if (Array.isArray(value)) return value.length ? String(value.length) : '0';
    return value === undefined || value === null || value === '' ? 'Unavailable' : String(value);
}

function overviewThreatLabel(threat) {
    if (typeof threat === 'string') return threat;
    if (!threat || typeof threat !== 'object') return String(threat ?? 'Unavailable');
    return threat.threat_name || threat.name || threat.label || threat.title || threat.summary || threat.id || 'Unavailable';
}

function overviewThreatField(threat, keys, fallback = 'Unavailable') {
    if (!threat || typeof threat !== 'object') return fallback;
    for (const key of keys) {
        const value = threat[key];
        if (value !== undefined && value !== null && String(value).trim()) return String(value);
    }
    return fallback;
}

function overviewThreatAllowPayload(threat) {
    return {
        threat_name: overviewThreatLabel(threat),
        severity: overviewThreatField(threat, ['severity', 'level', 'status']),
        target_type: overviewThreatField(threat, ['target_type', 'surface', 'type']),
        target_name: overviewThreatField(threat, ['target_name', 'app_name', 'process_name', 'name', 'command', 'host', 'domain']),
        target_path: overviewThreatField(threat, ['target_path', 'path', 'file_path', 'process_path']),
        source: overviewThreatField(threat, ['source'], 'overview'),
        reason: overviewThreatField(threat, ['reason', 'summary', 'message', 'description'], 'Allowed from Current Threats.'),
        evidence_refs: Array.isArray(threat?.evidence_refs) ? threat.evidence_refs : [],
        receipt_ref: overviewThreatField(threat, ['receipt_ref'], ''),
    };
}

function canAllowOverviewThreat(threat) {
    if (!threat || typeof threat !== 'object' || threat.allowable !== true) return false;
    const label = overviewThreatLabel(threat);
    const targetName = overviewThreatField(threat, ['target_name', 'app_name', 'process_name', 'name', 'command', 'host', 'domain'], '');
    const targetPath = overviewThreatField(threat, ['target_path', 'path', 'file_path', 'process_path'], '');
    return Boolean(label && label !== 'Unavailable' && (targetName || targetPath));
}

function renderOverviewThreatDetails(threat) {
    if (!threat || typeof threat !== 'object') return '';
    const details = {
        severity: overviewThreatField(threat, ['severity', 'level', 'status']),
        target_type: overviewThreatField(threat, ['target_type', 'surface', 'type']),
        target_name: overviewThreatField(threat, ['target_name', 'app_name', 'process_name', 'name', 'command', 'host', 'domain']),
        target_path: overviewThreatField(threat, ['target_path', 'path', 'file_path', 'process_path']),
        recommended_action: overviewThreatField(threat, ['recommended_action', 'next_action']),
        evidence_refs: Array.isArray(threat.evidence_refs) ? threat.evidence_refs : [],
        receipt_ref: overviewThreatField(threat, ['receipt_ref'], ''),
    };
    return '<details class="overview-threat-details"><summary>Inspect details</summary><pre>' + escapeHtml(JSON.stringify(details, null, 2)) + '</pre></details>';
}

function overviewThreatCard(threat, index) {
    const label = overviewThreatLabel(threat);
    const severity = threat && typeof threat === 'object' ? overviewThreatField(threat, ['severity', 'level', 'status'], '') : '';
    const target = threat && typeof threat === 'object'
        ? overviewThreatField(threat, ['target_name', 'app_name', 'process_name', 'name', 'command', 'host', 'domain', 'target_path', 'path'], '')
        : '';
    const allowable = canAllowOverviewThreat(threat);
    return (
        '<article class="overview-threat-item">' +
        '  <div class="overview-threat-main">' +
        '    <strong>' + escapeHtml(label) + '</strong>' +
        (target ? '    <span>' + escapeHtml(target) + '</span>' : '') +
        '  </div>' +
        (severity ? '<small>' + escapeHtml(severity) + '</small>' : '') +
        '  <div class="overview-threat-actions">' +
        '    <button class="overview-threat-action" type="button" disabled>Safe action unavailable</button>' +
        '    <button class="overview-threat-action overview-allow-action" type="button" data-threat-index="' + escapeHtml(index) + '"' + (allowable ? '' : ' disabled') + '>Allow on this device</button>' +
        '  </div>' +
        renderOverviewThreatDetails(threat) +
        '</article>'
    );
}

async function allowOverviewThreat(threat, button) {
    if (!canAllowOverviewThreat(threat) || !window.CleanHouseAPI?.createAllowedThreat) return;
    button.disabled = true;
    const result = await window.CleanHouseAPI.createAllowedThreat(overviewThreatAllowPayload(threat));
    if (result.status === 'ok') {
        button.textContent = 'Allowed';
        loadAllowedThreatCount();
    } else {
        button.disabled = false;
        button.textContent = 'Allow failed';
    }
}

function renderOverviewThreats(threats, findingCount, errorText = '') {
    const container = byId('overview-threats');
    if (!container) return;
    if (errorText) {
        container.textContent = errorText;
        return;
    }
    if (!Array.isArray(threats) || threats.length === 0) {
        container.textContent = Number(findingCount || 0) > 0 ? 'Unavailable' : 'No active threats detected';
        return;
    }
    container.innerHTML = '<div class="overview-threat-list">' + threats.map(overviewThreatCard).join('') + '</div>';
    container.querySelectorAll('.overview-allow-action').forEach(button => {
        button.addEventListener('click', () => allowOverviewThreat(threats[Number(button.dataset.threatIndex)], button));
    });
}

function renderOverviewScan(result = {}) {
    const findingCount = firstPresent(result, [['finding_count'], ['threat_count'], ['threats_found']]);
    const threats = firstPresent(result, [['threats'], ['findings'], ['issues'], ['data', 'threats'], ['data', 'findings']]);
    renderOverviewThreats(threats, findingCount);
    setText('overview-last-scan', valueOrUnavailable(firstPresent(result, [['timestamp'], ['scanned_at'], ['completed_at'], ['last_fullhouse_scan'], ['last_fullhouse_scan_timestamp']])));
    setText('overview-threat-count', findingCount === undefined ? '0' : String(findingCount));
    setText('overview-scan-time', valueOrUnavailable(firstPresent(result, [['scan_time'], ['duration'], ['duration_ms'], ['elapsed_time'], ['elapsed_ms']])));
    setText('overview-llms-scanned', valueOrUnavailable(firstPresent(result, [['llms_scanned'], ['llm_count'], ['areas', 'llms', 'count']])));
    setText('overview-files-scanned', valueOrUnavailable(firstPresent(result, [['files_scanned'], ['file_count'], ['areas', 'files', 'count']])));
    setText('overview-ports-scanned', valueOrUnavailable(firstPresent(result, [['ports_scanned'], ['port_count'], ['areas', 'network', 'ports_scanned'], ['areas', 'ports', 'count']])));
}

async function loadAllowedThreatCount() {
    const el = byId('overview-allowed-threats-count');
    if (!el || !window.CleanHouseAPI?.getAllowedThreats) return;
    try {
        const result = await window.CleanHouseAPI.getAllowedThreats();
        const count = Number(result.count ?? 0);
        el.textContent = Number.isFinite(count) ? `(${count})` : '';
    } catch (error) {
        el.textContent = '';
    }
}

function showView(view) {
    const target = view === 'app-dashboard' ? 'app-dashboard' : view;
    document.querySelectorAll('[data-view-panel]').forEach(panel => {
        panel.hidden = panel.dataset.viewPanel !== target;
    });
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.view === view);
    });
    document.querySelector('.sidebar-brand-link')?.classList.toggle('active', view === 'home');
    const preserveCurrentRoute = route => window.location.pathname === route ? route + window.location.search + window.location.hash : route;
    if (view === 'applications') history.replaceState(null, '', preserveCurrentRoute('/applications'));
    if (view === 'network') history.replaceState(null, '', preserveCurrentRoute('/network'));
    if (view === 'files') history.replaceState(null, '', preserveCurrentRoute('/files'));
    if (view === 'custom') history.replaceState(null, '', preserveCurrentRoute('/custom-scan'));
    if (view === 'home' && window.location.pathname !== '/settings') history.replaceState(null, '', '/investigations');
    syncFilesMediationView(view);
    if (view === 'network') {
        syncNetworkCoordinatorUiState();
        networkEnginePanel();
        if (!currentNetworkData && !currentNetworkTableData && !currentNetworkProjectionData) {
            currentNetworkTableData = networkCoordinatorSnapshotTableData();
        }
        renderNetworkDisplay();
        hydrateNetworkView({ refresh: false, reason: 'view-enter' }).catch(reportFrontendDegraded);
    } else {
        cancelNetworkSnapshotLifecycle();
        stopNetworkLiveUpdates();
    }
    if (view === 'files') {
        if (!filesLoaded) loadFilesSnapshot().catch(reportFrontendDegraded);
        startFilesLiveMonitoring();
    } else {
        stopFilesLiveMonitoring();
    }
    if (view !== 'network') {
        actionSidebarOpen = false;
        networkActionFilterReason = '';
        setCurrentEvidenceCommandSnapshot(null);
        evidenceCommandError = '';
        actionSidebarRequestEpoch += 1;
        evidenceInsightRequestEpoch += 1;
        evidenceActionRequestEpoch += 1;
    }
    renderActionSidebar();
}

function normalizedText(value) {
    return String(value ?? '').trim().toLowerCase();
}

function notificationText(notification) {
    try {
        return JSON.stringify(notification || {}).toLowerCase();
    } catch (error) {
        return String(notification || '').toLowerCase();
    }
}

function routeContext(id, message) {
    const el = byId(id);
    if (!el) return;
    el.textContent = message;
    el.hidden = !message;
}

function highlightElement(id) {
    const el = byId(id);
    if (!el) return;
    el.classList.remove('route-highlight');
    void el.offsetWidth;
    el.classList.add('route-highlight');
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function appBadge(app) {
    if (!app.badge) return '';
    return '<span class="app-badge" aria-label="New app">' + escapeHtml(app.badge_count || app.badge) + '</span>';
}

function appCard(app, selectable = false) {
    const checked = selectedFilter && customFilterMatch(app, selectedFilter) ? ' checked' : '';
    return (
        '<button class="app-card" type="button" data-app-id="' + escapeHtml(app.id) + '">' +
        '  <span class="app-icon-wrap">' + appBadge(app) + '<img class="app-icon" src="' + escapeHtml(app.icon_url) + '" alt="" loading="eager" fetchpriority="high" decoding="async"></span>' +
        '  <strong>' + escapeHtml(app.name) + '</strong>' +
        '  <small>' + escapeHtml(app.category || 'Installed') + '</small>' +
        (selectable ? '<label class="scan-check"><input type="checkbox" value="' + escapeHtml(app.id) + '"' + checked + '> Include</label>' : '') +
        '</button>'
    );
}

// Consent rejection describes access, not collector health or an empty inventory.
function renderConsentRequired() {
    if (!window.CleanHouseAccess?.consentRequired) return false;
    stopNetworkLiveUpdates();
    stopFilesLiveMonitoring();
    const message = 'Policy consent required. Data access is blocked until you review and accept the current policies.';
    const route = window.location.pathname === '/settings' ? '/overview' : window.location.pathname;
    const link = route + '?consent=required&return_to=' + encodeURIComponent(route);
    const markup = '<div class="empty-state" role="status">' + escapeHtml(message) +
        ' <a class="consent-review-link" href="' + escapeHtml(link) + '">Review policies</a></div>';
    ['app-grid', 'files-results', 'network-results'].forEach(id => {
        const element = byId(id);
        if (element && element.innerHTML !== markup) element.innerHTML = markup;
    });
    ['apps-area-status', 'files-status', 'network-area-status', 'network-action-summary', 'network-message', 'overview-threats'].forEach(id => setText(id, message));
    setText('overview-threat-count', '—');
    setText('files-activity-tag', 'ACCESS BLOCKED');
    setText('files-integrity-tag', 'CONSENT REQUIRED');
    setText('files-location-tag', '— LOCATIONS');
    setText('network-status-tag', 'ACCESS BLOCKED');
    setText('network-state-tag', 'CONSENT REQUIRED');
    ['network-status-tag', 'network-state-tag'].forEach(id => {
        const element = byId(id);
        if (element) element.dataset.state = 'unknown';
    });
    const reasons = byId('network-reason-tags');
    if (reasons) { reasons.hidden = true; reasons.innerHTML = ''; }
    document.querySelectorAll('[data-network-posture]').forEach(element => {
        const category = element.dataset.networkPosture;
        element.textContent = '— ' + category.charAt(0).toUpperCase() + category.slice(1);
    });
    return true;
}
window.addEventListener('cleanhouse:consent-required', renderConsentRequired);

function renderApplications() {
    if (renderConsentRequired()) return;
    const grid = byId('app-grid');
    if (!applications.length) {
        grid.innerHTML = '<div class="empty-state">No applications were discovered yet.</div>';
        return;
    }
    grid.innerHTML = applications.slice(0, APPLICATION_RENDER_LIMIT).map(app => appCard(app)).join('');
    grid.querySelectorAll('.app-card').forEach(card => {
        card.addEventListener('click', () => openAppDashboard(card.dataset.appId));
    });
    setText('apps-area-status', `${applications.length} apps, ${applications.filter(app => app.badge).length} new`);
    renderCustomApps();
}

function renderCustomApps() {
    const list = byId('custom-app-list');
    if (!list) return;
    list.innerHTML = applications.slice(0, APPLICATION_RENDER_LIMIT).map(app => appCard(app, true)).join('');
    list.querySelectorAll('.app-card').forEach(card => {
        card.addEventListener('click', event => {
            if (event.target && event.target.tagName === 'INPUT') return;
            const input = card.querySelector('input');
            if (input) input.checked = !input.checked;
        });
    });
}

async function loadApplications(refresh = false) {
    if (renderConsentRequired()) return;
    byId('app-grid').innerHTML = '<div class="empty-state">Loading applications from this Mac...</div>';
    const payload = await window.CleanHouseAPI.getApplications(refresh);
    if (renderConsentRequired()) return;
    applications = Array.isArray(payload.apps) ? payload.apps : [];
    applicationsLoaded = true;
    renderApplications();
}

function processRows(app, selectable = false) {
    const rows = Array.isArray(app.processes) ? app.processes : [];
    if (!rows.length) return '<div class="empty-state">No running processes are currently matched to this app.</div>';
    return rows.slice(0, PROCESS_RENDER_LIMIT).map(row =>
        '<label class="process-row">' +
        (selectable ? '  <input type="checkbox" value="' + escapeHtml(row.pid || '') + '">' : '') +
        '  <span><strong>' + escapeHtml(row.command || row.process || row.name || 'Process') + '</strong><small>PID ' + escapeHtml(row.pid || 'unknown') + '</small></span>' +
        '  <span>CPU ' + escapeHtml(row.cpu ?? row.cpu_percent ?? 'unknown') + '</span>' +
        '  <span>Memory ' + escapeHtml(row.rss_bytes ? `${Math.round(Number(row.rss_bytes) / 1024 / 1024)} MB` : row.mem ?? 'unknown') + '</span>' +
        '</label>'
    ).join('');
}

function openAppDashboard(appId) {
    selectedApp = applications.find(app => app.id === appId) || applications[0] || null;
    if (!selectedApp) return;
    setText('selected-app-name', selectedApp.name);
    setText('selected-app-subtitle', selectedApp.bundle_id);
    byId('selected-app-icon').src = selectedApp.icon_url;
    byId('selected-app-icon').alt = selectedApp.name;
    setText('app-identity-name', selectedApp.name);
    setText('app-identity-bundle', selectedApp.bundle_id);
    setText('app-identity-version', selectedApp.version);
    setText('app-identity-path', selectedApp.path);
    setText('app-running-state', selectedApp.running ? 'Running' : 'Not running');
    setText('app-audit-state', selectedApp.audit_status || 'adopted');
    setText('app-badge-state', selectedApp.badge || 'None');
    byId('app-process-list').innerHTML = processRows(selectedApp, false);
    byId('app-custom-process-list').innerHTML = processRows(selectedApp, true);
    byId('app-custom-scan-panel').hidden = true;
    byId('app-scan-result').hidden = true;
    byId('evidence').hidden = true;
    showView('app-dashboard');
    history.replaceState(null, '', `/applications/${encodeURIComponent(selectedApp.id)}`);
}

function findAppForNotification(notification) {
    const metadata = notification?.metadata && typeof notification.metadata === 'object' ? notification.metadata : {};
    const candidates = [
        notification?.app_id,
        notification?.application_id,
        notification?.application,
        notification?.app,
        notification?.app_name,
        notification?.subject,
        notification?.subject_name,
        metadata.app_id,
        metadata.application_id,
        metadata.application,
        metadata.app,
        metadata.app_name,
        metadata.bundle_id,
        metadata.bundle_identifier,
        metadata.process_name,
        metadata.path,
        metadata.file_path,
    ].filter(Boolean).map(normalizedText);
    const text = notificationText(notification);
    return applications.find(app => {
        const fields = [
            app.id,
            app.name,
            app.bundle_id,
            app.path,
        ].filter(Boolean).map(normalizedText);
        if (fields.some(field => candidates.includes(field))) return true;
        const name = normalizedText(app.name);
        const bundle = normalizedText(app.bundle_id);
        const path = normalizedText(app.path);
        return Boolean(
            (name && text.includes(name)) ||
            (bundle && text.includes(bundle)) ||
            (path && text.includes(path))
        );
    }) || null;
}

function routeForNotification(notification) {
    const text = notificationText(notification);
    const metadata = notification?.metadata && typeof notification.metadata === 'object' ? notification.metadata : {};
    const app = findAppForNotification(notification);
    if (app) {
        return {
            view: 'app-dashboard',
            appId: app.id,
            targetId: text.includes('process') || text.includes('pid') ? 'app-process-list' : 'app-dashboard',
            contextId: 'app-route-context',
            message: `Opened from notification: ${notification.summary || app.name}`,
        };
    }
    const surface = normalizedText(metadata.surface || metadata.domain || notification?.source || '');
    const type = normalizedText(notification?.notification_type || '');
    if (
        surface.includes('network') ||
        type.includes('port') ||
        type.includes('network') ||
        text.includes('opened port') ||
        text.includes('port ') ||
        text.includes('domain') ||
        text.includes('dns') ||
        text.includes('connection') ||
        text.includes('interface') ||
        text.includes('packet capture')
    ) {
        return {
            view: 'network',
            targetId: 'network-results',
            contextId: 'network-route-context',
            message: `Opened from notification: ${notification.summary || 'Network activity'}`,
        };
    }
    if (
        surface.includes('file') ||
        surface.includes('integrity') ||
        type.includes('file') ||
        type.includes('integrity') ||
        text.includes('file ') ||
        text.includes('folder') ||
        text.includes('created') ||
        text.includes('deleted') ||
        text.includes('modified') ||
        text.includes('integrity')
    ) {
        return {
            view: 'files',
            targetId: 'files-status',
            contextId: 'files-route-context',
            message: `Opened from notification: ${notification.summary || 'File activity'}`,
        };
    }
    if (type.includes('process') || text.includes('process') || text.includes('pid')) {
        return {
            view: 'applications',
            targetId: 'app-grid',
            contextId: '',
            message: '',
        };
    }
    return {
        view: 'home',
        targetId: 'home',
        contextId: '',
        message: '',
    };
}

function renderEvidence(report) {
    const evidence = report.evidence || {};
    byId('evidence').hidden = false;
    byId('evidence-timeline').innerHTML = '<p><strong>Question</strong></p><p>' + escapeHtml(report.question || 'Application scan') + '</p><p><strong>Status</strong></p><p>' + escapeHtml(report.status || 'unknown') + '</p>';
    byId('evidence-process').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.runtime_activity || {}, null, 2)) + '</pre>';
    byId('evidence-file').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.file_activity || {}, null, 2)) + '</pre>';
    byId('evidence-network').innerHTML = '<pre>' + escapeHtml(JSON.stringify(report.network_activity || {}, null, 2)) + '</pre>';
    byId('evidence-receipt').innerHTML =
        '<p><strong>Evidence artifact</strong></p><code>' + escapeHtml(evidence.evidence_artifact_path || 'Unavailable') + '</code>' +
        '<p><strong>Receipt artifact</strong></p><code>' + escapeHtml(evidence.receipt_artifact_path || 'Unavailable') + '</code>';
}

function renderAppScan(report) {
    const findings = Array.isArray(report.finding_objects) ? report.finding_objects : [];
    byId('app-scan-result').hidden = false;
    setText('app-result-title', findings[0]?.title || `${selectedApp?.name || 'App'} scan complete`);
    setText('app-result-summary', findings[0]?.summary || report.next_action || 'Scan complete.');
    byId('app-finding-list').innerHTML = findings.map(finding =>
        '<article class="operator-finding-card">' +
        '  <h4>' + escapeHtml(finding.title || 'Finding') + '</h4>' +
        '  <dl class="finding-meta">' +
        '    <div><dt>Severity</dt><dd>' + escapeHtml(finding.severity || 'Unknown') + '</dd></div>' +
        '    <div><dt>Confidence</dt><dd>' + escapeHtml(finding.confidence ?? 'Unknown') + '</dd></div>' +
        '    <div><dt>Evidence Strength</dt><dd>' + escapeHtml(finding.evidence_strength || 'Unknown') + '</dd></div>' +
        '  </dl>' +
        '  <p>' + escapeHtml(finding.next_action || report.next_action || 'No next action returned.') + '</p>' +
        '</article>'
    ).join('');
    renderEvidence(report);
}

async function scanSelectedApp() {
    if (!selectedApp) return;
    byId('scan-app-btn').disabled = true;
    setText('app-result-title', 'Scanning app...');
    try {
        const report = await window.CleanHouseAPI.runApplicationInvestigation({
            session_id: `app-scan-${selectedApp.id}`,
            question: `Scan ${selectedApp.name}.`,
            target: selectedApp.path,
            application: selectedApp.id,
        });
        renderAppScan(report);
    } catch (error) {
        byId('app-scan-result').hidden = false;
        setText('app-result-title', 'Scan failed');
        setText('app-result-summary', error.message || String(error));
    } finally {
        byId('scan-app-btn').disabled = false;
    }
}

function scanSelectedProcesses() {
    const selected = Array.from(byId('app-custom-process-list').querySelectorAll('input:checked')).map(input => input.value);
    if (!selected.length) {
        setText('app-custom-scan-status', 'Select at least one app process or component first.');
        return;
    }
    setText('app-custom-scan-status', `Custom app scan prepared for ${selected.length} process/component item(s). Evidence attaches to this app dashboard.`);
}

function toggleAppCustomScan() {
    const panel = byId('app-custom-scan-panel');
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) panel.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

async function runSystemScan() {
    byId('system-scan-btn').disabled = true;
    byId('scan-results').hidden = false;
    setText('scan-status', 'Scanning');
    renderOverviewScan({
        finding_count: 0,
        scan_time: 'Pending',
        llms_scanned: 'Pending',
        files_scanned: 'Pending',
        ports_scanned: 'Pending',
        allowed_threats: 'Pending',
    });
    try {
        const result = await window.CleanHouseAPI.runSystemScan();
        setText('scan-status', result.status || 'unknown');
        setText('scan-findings', String(result.finding_count ?? 0));
        setText('scan-evidence', result.evidence_ref || 'Unavailable');
        setText('scan-receipt', result.receipt_ref || 'Unavailable');
        setText('scan-next-action', result.next_action || 'Review app dashboards.');
        renderOverviewScan(result);
    } catch (error) {
        const message = error.message || String(error);
        setText('scan-status', 'failed');
        setText('scan-next-action', message);
        renderOverviewThreats([], 0, message);
    } finally {
        byId('system-scan-btn').disabled = false;
    }
}

function fileEventPath(event) {
    const refs = Array.isArray(event?.evidence_refs) ? event.evidence_refs : [];
    return String(event?.path || event?.raw_evidence_ref || refs[0] || '').trim();
}

function fileEventType(event) {
    return String(event?.event_type || 'file_event').trim();
}

function fileEventTime(event) {
    const value = event?.timestamp || '';
    if (!value) return 'Unavailable';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

function fileEventIsFileEvidence(event) {
    const type = fileEventType(event).toLowerCase();
    const source = String(event?.source_surface || '').toLowerCase();
    const actor = String(event?.actor_type || '').toLowerCase();
    return Boolean(fileEventPath(event)) && (
        source === 'filesystem_watcher' ||
        actor === 'filesystem' ||
        type.includes('file') ||
        ['created', 'modified', 'deleted', 'moved'].includes(type)
    );
}

function fileEventChangeLabel(event) {
    const type = fileEventType(event).toLowerCase();
    if (type.includes('deleted')) return 'Deleted';
    if (type.includes('created')) return 'Created';
    if (type.includes('modified')) return 'Modified';
    if (type.includes('moved')) return 'Moved';
    if (type.includes('integrity')) return 'Integrity';
    if (type.includes('mutation')) return 'Mutation';
    return 'Observed';
}

function fileEventDirectory(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    if (parts.length <= 1) return path || 'Unavailable';
    return '/' + parts.slice(0, -1).join('/');
}

function fileEventName(path) {
    const parts = String(path || '').split('/').filter(Boolean);
    return parts[parts.length - 1] || path || 'Unavailable';
}

function fileEventDataValue(event, keys) {
    const data = event?.data && typeof event.data === 'object' ? event.data : {};
    for (const key of keys) {
        const value = event?.[key] ?? data?.[key];
        if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
    }
    return '';
}

function fileEventActor(event) {
    const actor = fileEventDataValue(event, ['application_name', 'app_name', 'application', 'process_name', 'actor_name', 'process']);
    if (actor) return actor;
    const pid = fileEventDataValue(event, ['pid', 'process_id']);
    if (pid) return `PID ${pid}`;
    return String(event?.source_surface || '').toLowerCase() === 'filesystem_watcher'
        ? 'Filesystem watcher'
        : 'Unattributed';
}

function fileEventSource(event) {
    const provider = fileEventDataValue(event, ['provider']);
    if (provider === 'wazuh') return 'Wazuh FIM';
    if (provider === 'watchdog') return 'Watchdog fallback';
    return fileEventDataValue(event, ['source_surface', 'source', 'actor_type']) || 'event store';
}

function fileEventLocation(event) {
    return fileEventDataValue(event, ['watch_dir', 'watched_location']) || fileEventDirectory(fileEventPath(event));
}

function fileEventFindingText(event) {
    return [
        fileEventType(event),
        event?.summary,
        fileEventDataValue(event, ['severity', 'status', 'review_status', 'classification', 'reason']),
    ].filter(Boolean).join(' ').toLowerCase();
}

function fileEventIsFinding(event) {
    return /(integrity|suspicious|anomal|unexpected|drift|tamper|permission|ownership|replac|quarantine|review|critical|high|deleted)/.test(fileEventFindingText(event));
}

function fileEventPriority(event) {
    const text = fileEventFindingText(event);
    if (/(critical|tamper|quarantine)/.test(text)) return 'Critical';
    if (/(high|suspicious|unexpected|integrity|deleted|replac)/.test(text)) return 'Review';
    return 'Notice';
}

function fileEventTimestamp(event) {
    const value = new Date(event?.timestamp || '').getTime();
    return Number.isFinite(value) ? value : 0;
}

function fileEventEvidenceRefCount(event) {
    const refs = Array.isArray(event?.evidence_refs) ? event.evidence_refs.filter(Boolean) : [];
    return refs.length + (event?.raw_evidence_ref ? 1 : 0);
}

function fileLocationGroups(events) {
    const groups = new Map();
    events.forEach(event => {
        const location = fileEventLocation(event) || 'Unavailable';
        const current = groups.get(location) || {
            location,
            count: 0,
            latest: null,
            sources: new Set(),
            watched: false,
        };
        current.count += 1;
        current.sources.add(fileEventSource(event));
        current.watched = current.watched || Boolean(fileEventDataValue(event, ['watch_dir', 'watched_location']));
        if (!current.latest || fileEventTimestamp(event) > fileEventTimestamp(current.latest)) current.latest = event;
        groups.set(location, current);
    });
    return Array.from(groups.values()).sort((left, right) => {
        return fileEventTimestamp(right.latest) - fileEventTimestamp(left.latest) || left.location.localeCompare(right.location);
    });
}

function filteredFileEvents() {
    const query = filesSearchQuery.trim().toLowerCase();
    const events = currentFileEvents.slice().sort((left, right) => fileEventTimestamp(right) - fileEventTimestamp(left));
    if (!query) return events;
    return events.filter(event => [
        fileEventPath(event),
        fileEventName(fileEventPath(event)),
        fileEventChangeLabel(event),
        fileEventActor(event),
        fileEventSource(event),
        event?.summary,
    ].filter(Boolean).some(value => String(value).toLowerCase().includes(query)));
}

function renderFilesViewHeading(title, description, count) {
    return (
        '<div class="files-view-heading">' +
        '<div><h3>' + escapeHtml(title) + '</h3><p>' + escapeHtml(description) + '</p></div>' +
        '<span>' + escapeHtml(String(count)) + '</span>' +
        '</div>'
    );
}

function renderFileChanges(events) {
    const heading = renderFilesViewHeading('Recent Changes', 'File evidence retained in the current event window.', events.length);
    if (!events.length) return heading + '<div class="files-empty-state">No matching file changes are visible.</div>';
    const rows = events.slice(0, 80).map(event => {
        const path = fileEventPath(event);
        return (
            '<tr>' +
            '<td>' + escapeHtml(fileEventTime(event)) + '</td>' +
            '<td><span class="files-change-label">' + escapeHtml(fileEventChangeLabel(event)) + '</span></td>' +
            '<td><strong>' + escapeHtml(fileEventName(path)) + '</strong><small title="' + escapeHtml(path) + '">' + escapeHtml(path || 'Unavailable path') + '</small></td>' +
            '<td>' + escapeHtml(fileEventActor(event)) + '</td>' +
            '<td>' + escapeHtml(fileEventSource(event)) + '</td>' +
            '</tr>'
        );
    }).join('');
    return heading + (
        '<div class="files-table-wrap"><table class="files-table">' +
        '<thead><tr><th>Time</th><th>Change</th><th>File</th><th>Actor</th><th>Source</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div>'
    );
}

function filteredFileFindings() {
    const query = filesSearchQuery.trim().toLowerCase();
    if (!query) return currentFileFindings;
    return currentFileFindings.filter(finding => [
        finding.title,
        finding.reason,
        finding.context,
        finding.category,
        ...(Array.isArray(finding.paths) ? finding.paths : []),
    ].filter(Boolean).some(value => String(value).toLowerCase().includes(query)));
}

function renderFileFindings() {
    const findings = filteredFileFindings();
    const heading = renderFilesViewHeading('Findings', 'CleanHouse interpretations of related file changes and why they matter.', findings.length);
    if (!findings.length) return heading + '<div class="files-empty-state">No matching file findings are visible.</div>';
    return heading + '<div class="files-finding-list">' + findings.map(finding => {
        const paths = Array.isArray(finding.paths) ? finding.paths : [];
        return (
            '<details class="files-finding-item">' +
            '<summary><span><b>' + escapeHtml(String(finding.severity || 'Notice')) + '</b><strong>' + escapeHtml(finding.title || 'File finding') + '</strong></span><time>' + escapeHtml(fileEventTime({ timestamp: finding.latest_at })) + '</time></summary>' +
            '<div class="files-finding-detail">' +
            '<p class="files-finding-summary">' + escapeHtml(finding.reason || 'CleanHouse identified related file evidence for review.') + '</p>' +
            '<p class="file-event-path">' + escapeHtml(finding.context || paths[0] || 'Unavailable context') + '</p>' +
            '<dl class="file-event-meta">' +
            '<div><dt>Category</dt><dd>' + escapeHtml(finding.category || 'observation') + '</dd></div>' +
            '<div><dt>Confidence</dt><dd>' + escapeHtml(finding.confidence || 'medium') + '</dd></div>' +
            '<div><dt>Related changes</dt><dd>' + escapeHtml(String(finding.event_count || 0)) + '</dd></div>' +
            '<div><dt>Evidence refs</dt><dd>' + escapeHtml(String((finding.evidence_refs || []).length)) + '</dd></div>' +
            '</dl>' +
            (finding.suggestion ? '<p class="files-finding-summary"><strong>Optional mediation:</strong> ' + escapeHtml(finding.suggestion) + '</p>' : '') +
            '</div></details>'
        );
    }).join('') + '</div>';
}

function renderFileIntegrity(events) {
    const integrity = currentFileIntegrity && typeof currentFileIntegrity === 'object' ? currentFileIntegrity : {};
    const reconciliation = integrity.reconciliation && typeof integrity.reconciliation === 'object' ? integrity.reconciliation : {};
    const discrepancies = Array.isArray(reconciliation.discrepancies) ? reconciliation.discrepancies : [];
    const heading = renderFilesViewHeading('Integrity', 'Whether the current file state can be trusted and when it was last reconciled.', Number(integrity.finding_count || 0));
    const summary = (
        '<dl class="files-integrity-summary">' +
        '<div><dt>Trust state</dt><dd>' + escapeHtml(String(integrity.state || 'unknown').toUpperCase()) + '</dd></div>' +
        '<div><dt>Authorization</dt><dd>' + escapeHtml(String(integrity.authorization_state || 'not evaluated').replaceAll('_', ' ').toUpperCase()) + '</dd></div>' +
        '<div><dt>Generation</dt><dd>' + escapeHtml(String(integrity.generation || 0)) + '</dd></div>' +
        '<div><dt>Baseline entries</dt><dd>' + escapeHtml(String(integrity.entry_count || 0)) + '</dd></div>' +
        '<div><dt>Mutations</dt><dd>' + escapeHtml(String(integrity.mutation_count || events.length)) + '</dd></div>' +
        '<div><dt>Review signals</dt><dd>' + escapeHtml(String(integrity.finding_count || 0)) + '</dd></div>' +
        '<div><dt>Evidence refs</dt><dd>' + escapeHtml(String(integrity.evidence_ref_count || 0)) + '</dd></div>' +
        '</dl>'
    );
    const reconcileSummary = reconciliation.reconciled_at
        ? '<div class="files-integrity-row"><span></span><div><strong>Known lineage reconciled</strong><p>' + escapeHtml(`${reconciliation.present || 0} present · ${reconciliation.missing || 0} missing · ${reconciliation.unavailable || 0} unavailable`) + '</p></div><time>' + escapeHtml(fileEventTime({ timestamp: reconciliation.reconciled_at })) + '</time></div>'
        : '<div class="files-empty-state">No file reconciliation has been recorded yet.</div>';
    const discrepancyRows = discrepancies.map(path => (
        '<div class="files-integrity-row"><span></span><div><strong>' + escapeHtml(fileEventName(path)) + '</strong><p>' + escapeHtml(path) + '</p></div><time>Unresolved</time></div>'
    )).join('');
    return heading + summary + '<div class="files-integrity-list">' + reconcileSummary + discrepancyRows + '</div>';
}

function renderFileLocations() {
    const query = filesSearchQuery.trim().toLowerCase();
    const groups = currentFileLocations.filter(group => !query || [group.location, ...(group.sources || [])].some(value => String(value || '').toLowerCase().includes(query)));
    const heading = renderFilesViewHeading('Locations', 'Where CleanHouse is watching, where activity is happening, and unresolved coverage.', groups.length);
    if (!groups.length) return heading + '<div class="files-empty-state">No matching monitored locations are visible.</div>';
    return heading + (
        '<div class="files-location-list">' + groups.map(group => (
            '<div class="files-location-row">' +
            '<div><strong>' + escapeHtml(group.location) + '</strong><span>' + escapeHtml((group.sources || []).join(', ')) + '</span></div>' +
            '<span class="files-location-kind">' + escapeHtml(group.status || 'Observed') + '</span>' +
            '<span>' + escapeHtml(String(group.event_count || 0)) + ' events · ' + escapeHtml(String(group.unresolved_findings || 0)) + ' unresolved</span>' +
            '<time>' + escapeHtml(fileEventTime({ timestamp: group.latest_at })) + '</time>' +
            '</div>'
        )).join('') + '</div>'
    );
}

function renderFileTimeline(events) {
    const ordered = events.slice().sort((left, right) => fileEventTimestamp(left) - fileEventTimestamp(right));
    const heading = renderFilesViewHeading('Timeline', 'Chronological file lineage retained in the current event window.', ordered.length);
    if (!ordered.length) return heading + '<div class="files-empty-state">No matching file lineage events are visible.</div>';
    return heading + '<ol class="files-timeline">' + ordered.slice(-80).map(event => {
        const path = fileEventPath(event);
        return (
            '<li><span class="files-timeline-dot"></span><time>' + escapeHtml(fileEventTime(event)) + '</time>' +
            '<div><strong>' + escapeHtml(fileEventChangeLabel(event) + ' · ' + fileEventName(path)) + '</strong>' +
            '<p>' + escapeHtml(path || 'Unavailable path') + '</p><small>' + escapeHtml(fileEventActor(event) + ' · ' + fileEventSource(event)) + '</small></div></li>'
        );
    }).join('') + '</ol>';
}

function renderFilesDisplay() {
    if (renderConsentRequired()) return;
    const results = byId('files-results');
    if (!results) return;
    const events = filteredFileEvents();
    const renderers = {
        changes: renderFileChanges,
        findings: renderFileFindings,
        integrity: renderFileIntegrity,
        locations: renderFileLocations,
        timeline: renderFileTimeline,
    };
    results.innerHTML = (renderers[selectedFilesView] || renderFileChanges)(events);
}

function selectFilesView(view, options = {}) {
    const allowed = new Set(['changes', 'findings', 'integrity', 'locations', 'timeline']);
    selectedFilesView = allowed.has(view) ? view : 'changes';
    document.querySelectorAll('[data-files-view]').forEach(button => {
        const active = button.dataset.filesView === selectedFilesView;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
    });
    const results = byId('files-results');
    if (results) results.setAttribute('aria-labelledby', `files-tab-${selectedFilesView}`);
    renderFilesDisplay();
    if (options.focus) byId(`files-tab-${selectedFilesView}`)?.focus({ preventScroll: true });
}

function fileEvidenceStats(events) {
    const stats = {
        integrity: 0,
        mutation: 0,
        watchDirs: new Set(),
    };
    events.forEach(event => {
        const type = fileEventType(event).toLowerCase();
        if (type.includes('integrity')) stats.integrity += 1;
        if (type.includes('mutation') || ['created', 'modified', 'deleted', 'moved'].includes(type)) stats.mutation += 1;
        const watchDir = event?.data && typeof event.data === 'object' ? event.data.watch_dir : '';
        if (watchDir) stats.watchDirs.add(String(watchDir));
    });
    return stats;
}

function applyFilesSnapshot(snapshot) {
    if (renderConsentRequired()) return;
    if (!snapshot || typeof snapshot !== 'object') return;
    currentFileEvents = Array.isArray(snapshot.events) ? snapshot.events : [];
    currentFileFindings = Array.isArray(snapshot.findings) ? snapshot.findings : [];
    currentFileIntegrity = snapshot.integrity && typeof snapshot.integrity === 'object' ? snapshot.integrity : {};
    currentFileLocations = Array.isArray(snapshot.locations) ? snapshot.locations : [];
    currentFileSuggestions = Array.isArray(snapshot.suggestions) ? snapshot.suggestions : [];
    filesMediationQueue = Array.isArray(snapshot.mediations) ? snapshot.mediations : [];
    filesSnapshotCursor = String(snapshot.cursor || filesSnapshotCursor || '');
    filesLoaded = true;
    const monitoring = snapshot.monitoring && typeof snapshot.monitoring === 'object' ? snapshot.monitoring : {};
    const collector = snapshot.collector && typeof snapshot.collector === 'object' ? snapshot.collector : {};
    const state = String(collector.health || monitoring.status || 'unavailable').toLowerCase();
    const isLive = state === 'live';
    const isFallback = state === 'fallback';
    const activityLabels = {
        live: 'WAZUH LIVE',
        fallback: 'FALLBACK',
        warming: 'WARMING',
        no_data: 'NO DATA',
        degraded: 'DEGRADED',
        unavailable: 'UNAVAILABLE',
    };
    setText('files-activity-tag', activityLabels[state] || state.toUpperCase());
    setText('files-integrity-tag', currentFileFindings.length ? `${currentFileFindings.length} FINDING${currentFileFindings.length === 1 ? '' : 'S'}` : 'NO RECENT DEVIATIONS');
    setText('files-location-tag', `${currentFileLocations.length} LOCATION${currentFileLocations.length === 1 ? '' : 'S'}`);
    const latency = Number.isFinite(Number(collector.ingestion_latency_ms)) ? ` · ${Number(collector.ingestion_latency_ms)} ms ingestion` : '';
    setText('files-status', isLive
        ? `Authenticated Wazuh monitoring · ${currentFileEvents.length} recent file change${currentFileEvents.length === 1 ? '' : 's'}${latency}.`
        : isFallback
            ? `Watchdog fallback is observing locally. Evidence is not being presented as Wazuh.`
            : state === 'warming'
                ? 'Wazuh is connected and warming. No authenticated file evidence has arrived yet.'
                : state === 'no_data'
                    ? 'Wazuh is connected. No file events are currently available.'
                    : 'File monitoring is degraded or unavailable. Retained evidence remains visible.');
    const provider = byId('files-provider');
    if (provider) {
        provider.hidden = !snapshot.powered_by_wazuh;
        provider.setAttribute('aria-hidden', snapshot.powered_by_wazuh ? 'false' : 'true');
    }
    renderFilesDisplay();
    renderFilesMediationQueue(Number(snapshot.attention_count || 0));
}

async function loadFilesSnapshot() {
    if (renderConsentRequired()) return;
    setText('files-status', 'Connecting to live file monitoring...');
    try {
        const snapshot = await window.CleanHouseAPI.getFilesSnapshot(200);
        applyFilesSnapshot(snapshot);
    } catch (error) {
        setText('files-status', 'Live file evidence could not be loaded. Reconnecting...');
        renderFilesDisplay();
    }
}

function stopFilesLiveMonitoring() {
    if (filesLiveSource) filesLiveSource.close();
    filesLiveSource = null;
}

function startFilesLiveMonitoring() {
    if (renderConsentRequired()) return;
    if (typeof EventSource === 'undefined' || filesLiveSource) return;
    const source = new EventSource(window.CleanHouseAPI.getFilesLiveUrl(filesSnapshotCursor));
    filesLiveSource = source;
    source.addEventListener('files-snapshot', event => {
        try {
            applyFilesSnapshot(JSON.parse(event.data || '{}'));
        } catch (error) {
            reportFrontendDegraded(error);
        }
    });
    source.onerror = () => {
        if (renderConsentRequired()) return;
        setText('files-status', 'Live file monitoring is reconnecting...');
    };
}

async function reconcileFiles() {
    if (renderConsentRequired()) return;
    const button = byId('reconcile-files-btn');
    if (button) button.disabled = true;
    if (button) button.textContent = 'Reconciling...';
    setText('files-status', 'Reconciling known file lineage...');
    try {
        applyFilesSnapshot(await window.CleanHouseAPI.reconcileFiles());
    } catch (error) {
        setText('files-status', 'Known file lineage could not be reconciled. Live monitoring continues.');
    } finally {
        if (button) button.disabled = false;
        if (button) button.textContent = 'Reconcile Files';
    }
}

function syncFilesMediationComposers() {
    document.querySelectorAll('[data-mediation-request]').forEach(request => {
        if (request.value !== filesMediationDraft) request.value = filesMediationDraft;
    });
    document.querySelectorAll('[data-mediation-scope]').forEach(scope => {
        if (scope.value !== filesMediationScope) scope.value = filesMediationScope;
    });
    const evidenceCount = filesMediationEvidenceNames.length;
    document.querySelectorAll('[data-mediation-evidence-label]').forEach(label => {
        label.textContent = evidenceCount ? `${evidenceCount} file${evidenceCount === 1 ? '' : 's'}` : 'No evidence';
    });
    document.querySelectorAll('[data-mediation-submit]').forEach(submit => {
        submit.disabled = !filesMediationDraft.trim();
    });
}

function updateFilesMediationComposerState(event) {
    filesMediationDraft = String(event?.target?.value ?? filesMediationDraft);
    syncFilesMediationComposers();
}

function filesMediationItems(status) {
    return filesMediationQueue.filter(item => item.status === status);
}

function filesMediationAction(status) {
    if (status === 'queue') return { status: 'in_progress', label: 'Start' };
    if (status === 'in_progress') return { status: 'ready', label: 'Ready' };
    if (status === 'ready') return { status: 'completed', label: 'Complete' };
    return null;
}

function renderFilesMediationItems(containerId, items) {
    const container = byId(containerId);
    if (!container) return;
    container.replaceChildren();
    items.forEach(item => {
        const card = document.createElement('article');
        card.className = 'files-mediation-queue__card';
        card.dataset.mediationQueueId = item.id;
        const request = document.createElement('strong');
        request.textContent = item.request;
        const metadata = document.createElement('span');
        const evidenceCount = Array.isArray(item.evidence_names) ? item.evidence_names.length : 0;
        const evidenceLabel = evidenceCount
            ? `${evidenceCount} evidence file${evidenceCount === 1 ? '' : 's'}`
            : 'No attached evidence';
        metadata.textContent = `${String(item.status || 'queue').replace('_', ' ')} · ${item.scope === 'current' ? 'Current lineage' : 'All locations'} · ${evidenceLabel}`;
        card.append(request, metadata);
        const action = filesMediationAction(item.status);
        if (action) {
            const controls = document.createElement('div');
            controls.className = 'files-mediation-card__actions';
            const primary = document.createElement('button');
            primary.type = 'button';
            primary.textContent = action.label;
            primary.dataset.mediationTransition = action.status;
            primary.dataset.mediationId = item.id;
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.textContent = 'Cancel';
            cancel.dataset.mediationTransition = 'cancelled';
            cancel.dataset.mediationId = item.id;
            controls.append(primary, cancel);
            card.appendChild(controls);
        }
        container.appendChild(card);
    });
}

function renderFilesMediationQueue(attentionCount = null) {
    const queue = filesMediationItems('queue');
    const progress = filesMediationItems('in_progress');
    const ready = filesMediationItems('ready');
    const ledger = filesMediationQueue.filter(item => ['completed', 'cancelled'].includes(item.status));
    const counts = { queue: queue.length, progress: progress.length, ready: ready.length, ledger: ledger.length };
    setText('files-mediation-queue-count', String(counts.queue));
    setText('files-mediation-progress-count', String(counts.progress));
    setText('files-mediation-ready-count', String(counts.ready));
    setText('files-mediation-ledger-count', String(counts.ledger));
    setText('files-mediation-column-queue-count', String(counts.queue));
    setText('files-mediation-column-progress-count', String(counts.progress));
    setText('files-mediation-column-ready-count', String(counts.ready));
    setText('files-mediation-column-ledger-count', String(counts.ledger));
    setText('files-mediation-progress-lane-count', String(counts.progress));
    setText('files-mediation-ready-lane-count', String(counts.ready));
    setText('files-mediation-ledger-lane-count', String(counts.ledger));
    renderFilesMediationItems('files-mediation-queue-items', queue);
    renderFilesMediationItems('files-mediation-progress-items', progress);
    renderFilesMediationItems('files-mediation-ready-items', ready);
    const ledgerQuery = filesMediationSearchQuery.trim().toLowerCase();
    renderFilesMediationItems('files-mediation-ledger-items', ledger.filter(item => !ledgerQuery || String(item.request || '').toLowerCase().includes(ledgerQuery)));

    const suggestions = byId('files-mediation-suggestions');
    if (suggestions) {
        suggestions.replaceChildren();
        currentFileSuggestions.forEach(suggestion => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'files-mediation-suggestion';
            button.dataset.mediationSuggestion = suggestion.request;
            button.textContent = suggestion.request;
            suggestions.appendChild(button);
        });
    }

    const actionable = attentionCount === null
        ? currentFileSuggestions.length + counts.queue + counts.ready
        : Number(attentionCount || 0);
    const badge = byId('files-mediation-badge');
    if (badge) {
        badge.hidden = actionable <= 0;
        badge.textContent = actionable > 99 ? '99+' : String(actionable);
        badge.setAttribute('aria-label', `${actionable} mediation notification${actionable === 1 ? '' : 's'}`);
    }
}

function selectFilesMediationSuggestion(button) {
    const suggestion = String(button?.dataset?.mediationSuggestion || '').trim();
    if (!suggestion) return;
    filesMediationDraft = suggestion;
    syncFilesMediationComposers();
    const request = button.closest('#files-mediation-panel')
        ? byId('files-mediation-panel-request')
        : byId('files-mediation-request');
    request?.focus({ preventScroll: true });
}

async function queueFilesMediationRequest(event) {
    event?.preventDefault();
    const form = event?.currentTarget;
    const request = form?.querySelector('[data-mediation-request]');
    const value = filesMediationDraft.trim();
    if (!value) {
        request?.focus({ preventScroll: true });
        return;
    }
    const submit = form?.querySelector('[data-mediation-submit]');
    if (submit) submit.disabled = true;
    try {
        const result = await window.CleanHouseAPI.queueFileMediation({
            request: value,
            scope: filesMediationScope,
            evidence_names: filesMediationEvidenceNames,
        });
        applyFilesSnapshot(result.snapshot || result);
        filesMediationDraft = '';
        filesMediationEvidenceNames = [];
        document.querySelectorAll('[data-mediation-evidence]').forEach(evidence => {
            evidence.value = '';
        });
        syncFilesMediationComposers();
        request?.focus({ preventScroll: true });
    } catch (error) {
        reportFrontendDegraded(error);
    } finally {
        syncFilesMediationComposers();
    }
}

async function transitionFilesMediation(button) {
    const mediationId = String(button?.dataset?.mediationId || '');
    const status = String(button?.dataset?.mediationTransition || '');
    if (!mediationId || !status) return;
    button.disabled = true;
    try {
        const result = await window.CleanHouseAPI.transitionFileMediation(mediationId, status);
        applyFilesSnapshot(result.snapshot || result);
    } catch (error) {
        button.disabled = false;
        reportFrontendDegraded(error);
    }
}

function setFilesMediationPanelOpen(open, options = {}) {
    const panel = byId('files-mediation-panel');
    const toggle = byId('files-mediation-toggle');
    const filesView = byId('files');
    if (!panel || !toggle) return;
    const nextOpen = Boolean(open && filesView && !filesView.hidden);
    if (!nextOpen && filesMediationBoardOpen) {
        setFilesMediationBoardOpen(false, { restoreFocus: false });
    }
    filesMediationPanelOpen = nextOpen;
    const panelInteractive = nextOpen && !filesMediationBoardOpen;
    panel.classList.toggle('is-open', nextOpen);
    panel.setAttribute('aria-hidden', panelInteractive ? 'false' : 'true');
    panel.inert = !panelInteractive;
    toggle.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    toggle.setAttribute('aria-label', nextOpen ? 'Close mediation panel' : 'Open mediation panel');
    document.body.classList.toggle('files-mediation-panel-open', nextOpen);
    if (nextOpen && options.focus !== false) {
        byId('files-mediation-open-board')?.focus({ preventScroll: true });
    } else if (!nextOpen && options.focus !== false && options.restoreFocus !== false) {
        toggle.focus({ preventScroll: true });
    } else if (!nextOpen && panel.contains(document.activeElement) && !toggle.hidden) {
        toggle.focus({ preventScroll: true });
    }
}

function setFilesMediationBoardOpen(open, options = {}) {
    const board = byId('files-mediation-board');
    if (!board) return;
    const filesView = byId('files');
    const nextOpen = Boolean(open && filesView && !filesView.hidden);
    if (nextOpen && !filesMediationPanelOpen) {
        setFilesMediationPanelOpen(true, { focus: false });
    }
    if (nextOpen && actionSidebarOpen) {
        setActionSidebarOpen(false);
    }
    filesMediationBoardOpen = nextOpen;
    board.hidden = !nextOpen;
    board.setAttribute('aria-hidden', nextOpen ? 'false' : 'true');
    board.inert = !nextOpen;
    const panel = byId('files-mediation-panel');
    const panelInteractive = filesMediationPanelOpen && !nextOpen;
    if (panel) {
        panel.setAttribute('aria-hidden', panelInteractive ? 'false' : 'true');
        panel.inert = !panelInteractive;
    }
    byId('files-mediation-open-board')?.setAttribute('aria-expanded', nextOpen ? 'true' : 'false');
    document.body.classList.toggle('files-mediation-board-open', nextOpen);
    if (nextOpen && options.focus !== false) {
        byId('files-mediation-search')?.focus({ preventScroll: true });
    } else if (!nextOpen && options.restoreFocus !== false) {
        byId('files-mediation-open-board')?.focus({ preventScroll: true });
    } else if (!nextOpen && board.contains(document.activeElement)) {
        byId('files-mediation-toggle')?.focus({ preventScroll: true });
    }
}

function syncFilesMediationView(view) {
    const toggle = byId('files-mediation-toggle');
    if (toggle) toggle.hidden = view !== 'files';
    if (view === 'files') return;
    setFilesMediationBoardOpen(false, { restoreFocus: false });
    setFilesMediationPanelOpen(false, { focus: false });
}

function normalizeNetworkCursor(value) {
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    if (typeof value === 'string') return value.trim();
    if (!value || typeof value !== 'object') return '';
    const direct = [value.cursor, value.token, value.value, value.id]
        .map(item => normalizeNetworkCursor(item))
        .find(Boolean);
    if (direct) return direct;
    const sequence = normalizeNetworkCursor(value.sequence ?? value.collector_sequence ?? value.seq);
    if (!sequence) return '';
    const epoch = String(value.server_boot_id || value.epoch || value.generation || '').trim();
    return epoch ? `${epoch}:${sequence}` : sequence;
}

function networkCursorFromPayload(payload = {}, eventMeta = {}) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const summary = data.summary && typeof data.summary === 'object' ? data.summary : {};
    const collector = data.collector && typeof data.collector === 'object' ? data.collector : {};
    const cursor = [
        eventMeta.lastEventId,
        data.cursor,
        data.high_water_cursor,
        data.event_cursor,
        summary.cursor,
        summary.high_water_cursor,
        collector.cursor,
        collector.high_water_cursor,
    ].map(value => normalizeNetworkCursor(value)).find(Boolean);
    if (cursor) return cursor;
    const sequence = normalizeNetworkCursor(data.collector_sequence ?? data.sequence ?? data.seq);
    if (!sequence) return '';
    const epoch = String(data.server_boot_id || collector.server_boot_id || '').trim();
    return epoch ? `${epoch}:${sequence}` : sequence;
}

function networkEpochFromOpaqueCursor(cursor = '') {
    const normalized = normalizeNetworkCursor(cursor);
    const match = normalized.match(/^(.*):(\d+)$/);
    return match ? match[1] : '';
}

function networkCursorEpochFromPayload(payload = {}, cursor = '') {
    const data = payload && typeof payload === 'object' ? payload : {};
    const collector = data.collector && typeof data.collector === 'object' ? data.collector : {};
    return String(
        data.server_boot_id ||
        collector.server_boot_id ||
        data.cursor_epoch ||
        collector.cursor_epoch ||
        networkEpochFromOpaqueCursor(cursor) ||
        '',
    ).trim();
}

function networkAdoptCursorEpoch(epoch = '') {
    const normalized = String(epoch || '').trim();
    if (!normalized) return networkCursorEpoch;
    if (networkCursorEpoch && networkCursorEpoch !== normalized) {
        networkSnapshotCursor = '';
        networkLastAppliedCursor = '';
        networkLiveReplayBuffer = [];
        networkLiveSeenDeliveryKeys = new Set();
        networkLiveSeenDeliveryOrder = [];
    }
    networkCursorEpoch = normalized;
    return networkCursorEpoch;
}

function networkCursorComparableParts(cursor = '') {
    const normalized = normalizeNetworkCursor(cursor);
    if (!normalized) return null;
    const match = normalized.match(/^(.*?)(?::)?(\d+)$/);
    if (!match) return null;
    return { epoch: match[1] || '', sequence: Number(match[2]), cursor: normalized };
}

function compareNetworkCursors(left = '', right = '') {
    const leftParts = networkCursorComparableParts(left);
    const rightParts = networkCursorComparableParts(right);
    if (!leftParts || !rightParts || leftParts.epoch !== rightParts.epoch) return null;
    if (leftParts.sequence === rightParts.sequence) return 0;
    return leftParts.sequence > rightParts.sequence ? 1 : -1;
}

function advanceNetworkAppliedCursor(cursor = '', epoch = '', options = {}) {
    const normalized = normalizeNetworkCursor(cursor);
    if (!normalized) return networkLastAppliedCursor;
    networkAdoptCursorEpoch(epoch || networkEpochFromOpaqueCursor(normalized));
    if (!networkLastAppliedCursor) {
        networkLastAppliedCursor = normalized;
        return networkLastAppliedCursor;
    }
    const comparison = compareNetworkCursors(normalized, networkLastAppliedCursor);
    if (comparison > 0 || (comparison === null && options.ordered === true)) {
        networkLastAppliedCursor = normalized;
    }
    return networkLastAppliedCursor;
}

function networkLiveDeliveryKey(event = {}, eventMeta = {}) {
    const cursor = networkCursorFromPayload(event, eventMeta);
    const epoch = String(eventMeta.epoch || networkCursorEpochFromPayload(event, cursor) || networkCursorEpoch || '').trim();
    if (cursor) return `${epoch}|cursor:${cursor}`;
    const eventId = String(eventMeta.lastEventId || event.event_id || event.id || event.source_event_id || '').trim();
    if (eventId) return `${epoch}|event:${eventId}`;
    const fallback = [
        event.timestamp || event.time || '',
        event.packet_index ?? '',
        networkEventSource(event),
        networkEventDestination(event),
        event.protocol || '',
    ].map(value => String(value ?? '').trim()).join('|');
    return fallback.replace(/\|/g, '') ? `${epoch}|packet:${fallback}` : '';
}

function rememberNetworkLiveDelivery(deliveryKey = '') {
    const normalized = String(deliveryKey || '').trim();
    if (!normalized) return true;
    if (networkLiveSeenDeliveryKeys.has(normalized)) return false;
    networkLiveSeenDeliveryKeys.add(normalized);
    networkLiveSeenDeliveryOrder.push(normalized);
    while (networkLiveSeenDeliveryOrder.length > NETWORK_LIVE_DELIVERY_KEY_LIMIT) {
        const expired = networkLiveSeenDeliveryOrder.shift();
        if (expired) networkLiveSeenDeliveryKeys.delete(expired);
    }
    return true;
}

function rememberNetworkSnapshotDeliveries(events = [], epoch = networkCursorEpoch) {
    (Array.isArray(events) ? events : []).forEach(event => {
        rememberNetworkLiveDelivery(networkLiveDeliveryKey(event, { epoch }));
    });
}

function mergeNetworkSnapshotWithLiveReplay(snapshotData = {}, rawSnapshotEvents = [], epoch = networkCursorEpoch) {
    const snapshotKeys = new Set((Array.isArray(rawSnapshotEvents) ? rawSnapshotEvents : [])
        .map(event => networkLiveDeliveryKey(event, { epoch }))
        .filter(Boolean));
    let mergedData = snapshotData;
    networkLiveReplayBuffer.forEach(entry => {
        if (!entry || (epoch && entry.epoch && entry.epoch !== epoch)) return;
        if (entry.deliveryKey && snapshotKeys.has(entry.deliveryKey)) return;
        const merged = mergeNetworkLiveEventIntoTableData(mergedData, entry.event, entry.observedAt);
        mergedData = merged.data;
    });
    return mergedData;
}

async function loadNetworkEngine(refresh = false) {
    try {
        const response = await window.CleanHouseAPI.getNetwork({ refresh });
        if (normalizeNetworkContractState(response?.state) !== 'ERROR') {
            renderNetworkCapture(response || {});
            return;
        }
        renderNetworkUnavailable(response);
    } catch (error) {
        renderNetworkUnavailable({
            state: 'ERROR',
            events: [],
            summary: { reason: 'capture_failed' },
        });
    }
}

async function performNetworkHeaderSnapshot(refresh = false, options = {}) {
    if (renderConsentRequired()) return;
    const epoch = Number.isFinite(options.epoch) ? options.epoch : networkHydrationEpoch;
    const controller = options.controller || new AbortController();
    if (!options.controller) {
        abortNetworkSnapshotRequest();
        networkSnapshotAbortController = controller;
    }
    const signal = options.signal || controller.signal;
    const requestId = ++networkSnapshotRequestId;
    const coordinator = syncNetworkCoordinatorUiState();
    coordinator.requests.hydrationEpoch = epoch;
    coordinator.requests.snapshot = { requestId, status: 'loading' };
    networkHeaderSnapshotRequested = true;
    networkHeaderSnapshotInFlight = true;
    if (!window.CleanHouseAPI?.getNetwork) {
        networkHeaderSnapshotInFlight = false;
        return null;
    }
    try {
        const response = await window.CleanHouseAPI.getNetwork({ refresh, snapshot: true, signal });
        if (renderConsentRequired()) return null;
        if (!networkHydrationEpochMatches(epoch) || requestId !== networkSnapshotRequestId) return null;
        const state = normalizeNetworkContractState(response?.state || 'NO_DATA');
        const responseEvents = Array.isArray(response?.events) ? response.events : [];
        if (state === 'ERROR' && responseEvents.length === 0) {
            const errorData = {
                state: 'ERROR',
                events: [],
                summary: response?.summary || { reason: 'capture_failed' },
                assessments: Array.isArray(response?.assessments) ? response.assessments : [],
                assessment_refs: Array.isArray(response?.assessment_refs) ? response.assessment_refs : [],
                assessment_summary: response?.assessment_summary || null,
                assessment_filter: response?.assessment_filter || null,
                tags: response?.tags,
                collector: response?.collector || null,
                powered_by_wireshark: response?.powered_by_wireshark === true,
                __http_status: response?.__http_status,
            };
            submitNetworkHeaderEvidence('snapshot', errorData, { captureStatus: true });
            return errorData;
        }
        const lifecycle = observeNetworkServerBoot(response, options.reason || networkPagePhaseReason);
        const snapshotCursor = networkCursorFromPayload(response);
        const snapshotEpoch = networkCursorEpochFromPayload(response, snapshotCursor);
        networkAdoptCursorEpoch(snapshotEpoch);
        if (snapshotCursor) {
            networkSnapshotCursor = snapshotCursor;
            advanceNetworkAppliedCursor(snapshotCursor, snapshotEpoch);
        }
        const snapshotEvents = responseEvents;
        const snapshotData = {
            state,
            server_boot_id: response?.server_boot_id,
            server_lifecycle: lifecycle,
            cursor: snapshotCursor,
            high_water_cursor: response?.high_water_cursor || snapshotCursor,
            collector: response?.collector || null,
            powered_by_wireshark: response?.powered_by_wireshark === true,
            vvault: response?.vvault || null,
            events: snapshotEvents,
            summary: response?.summary || {},
            assessments: Array.isArray(response?.assessments) ? response.assessments : [],
            assessment_refs: Array.isArray(response?.assessment_refs) ? response.assessment_refs : [],
            assessment_summary: response?.assessment_summary || null,
            assessment_filter: response?.assessment_filter || null,
            event_count: response?.event_count,
            tags: response?.tags,
        };
        let tableSnapshotData = reconcileNetworkInventoryFromSnapshot(currentNetworkTableData, snapshotData, snapshotEvents);
        tableSnapshotData = mergeNetworkSnapshotWithLiveReplay(tableSnapshotData, snapshotEvents, snapshotEpoch || networkCursorEpoch);
        rememberNetworkSnapshotDeliveries(snapshotEvents, snapshotEpoch || networkCursorEpoch);
        setText('network-area-status', networkCaptureStatusText(state, snapshotData.summary));
        submitNetworkHeaderEvidence('snapshot', tableSnapshotData, { captureStatus: true });
        currentNetworkTableData = networkHeaderTableData();
        networkCoordinatorRememberSnapshot(currentNetworkTableData, epoch, requestId);
        networkSnapshotFailureCount = 0;
        networkSnapshotBackoffUntil = 0;
        return tableSnapshotData;
    } catch (error) {
        if (error?.name === 'AbortError') return null;
        networkSnapshotFailureCount += 1;
        networkSnapshotBackoffUntil = Date.now() + Math.min(
            NETWORK_SNAPSHOT_BACKOFF_MAX_MS,
            NETWORK_SNAPSHOT_BACKOFF_BASE_MS * (2 ** Math.min(networkSnapshotFailureCount - 1, 5))
        );
        // Header snapshots are best-effort; tab projections and live capture continue.
        return null;
    } finally {
        if (networkSnapshotAbortController === controller) {
            networkSnapshotAbortController = null;
        }
        networkHeaderSnapshotInFlight = false;
    }
}

function mergeNetworkSnapshotDemand(refresh = false, options = {}, waiters = []) {
    const previous = networkSnapshotPendingDemand;
    networkSnapshotPendingDemand = {
        refresh: Boolean(refresh || previous?.refresh),
        options: { ...(previous?.options || {}), ...options },
        waiters: [...(previous?.waiters || []), ...waiters],
    };
    return networkSnapshotPendingDemand;
}

function drainNetworkSnapshotDemand() {
    if (networkSnapshotActivePromise || !networkSnapshotPendingDemand) return;
    const demand = networkSnapshotPendingDemand;
    networkSnapshotPendingDemand = null;
    startNetworkSnapshotDemand(demand.refresh, demand.options).then(
        result => demand.waiters.forEach(waiter => waiter.resolve(result)),
        error => demand.waiters.forEach(waiter => waiter.reject(error))
    );
}

function startNetworkSnapshotDemand(refresh = false, options = {}) {
    networkHeaderSnapshotInFlight = true;
    const active = performNetworkHeaderSnapshot(refresh, options);
    networkSnapshotActivePromise = active;
    active.finally(() => {
        if (networkSnapshotActivePromise === active) networkSnapshotActivePromise = null;
        networkHeaderSnapshotInFlight = false;
        drainNetworkSnapshotDemand();
    });
    return active;
}

function loadNetworkHeaderSnapshot(refresh = false, options = {}) {
    const automatic = options.reason === 'quiet-refresh';
    if (automatic && !refresh && Date.now() < networkSnapshotBackoffUntil) {
        return Promise.resolve(null);
    }
    if (!networkSnapshotActivePromise) {
        return startNetworkSnapshotDemand(refresh, options);
    }
    return new Promise((resolve, reject) => {
        mergeNetworkSnapshotDemand(refresh, options, [{ resolve, reject }]);
    });
}

function cancelNetworkSnapshotLifecycle() {
    if (networkSnapshotAbortController) networkSnapshotAbortController.abort();
    networkSnapshotAbortController = null;
    const pending = networkSnapshotPendingDemand;
    networkSnapshotPendingDemand = null;
    (pending?.waiters || []).forEach(waiter => waiter.resolve(null));
    networkSnapshotRequestId += 1;
}

async function loadNotificationBadge() {
    const badge = byId('notification-center-badge');
    if (!badge || !window.CleanHouseAPI?.getRuntime) return;
    try {
        const runtime = await window.CleanHouseAPI.getRuntime();
        runtimeNotifications = Array.isArray(runtime?.runtime_notifications) ? runtime.runtime_notifications : [];
        const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
        badge.hidden = unread === 0;
        badge.textContent = unread > 99 ? '99+' : String(unread);
        renderNotificationCenter();
    } catch (error) {
        runtimeNotifications = [];
        badge.hidden = true;
        renderNotificationCenter('Notifications unavailable.');
    }
}

function notificationIcon(notification, app) {
    if (app?.icon_url) {
        return '<span class="notification-icon"><img src="' + escapeHtml(app.icon_url) + '" alt=""></span>';
    }
    const type = normalizedText(notification?.notification_type || notification?.source || '');
    if (type.includes('network') || type.includes('port')) return '<span class="notification-icon">NW</span>';
    if (type.includes('file') || type.includes('integrity')) return '<span class="notification-icon">FI</span>';
    if (type.includes('process')) return '<span class="notification-icon">PR</span>';
    return '<span class="notification-icon">CH</span>';
}

function renderNotificationCenter(errorMessage = '') {
    const list = byId('notification-list');
    const count = byId('notification-center-count');
    if (!list) return;
    const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
    if (count) count.textContent = unread ? `${unread} unread` : 'No unread';
    if (errorMessage) {
        list.innerHTML = '<p class="notification-empty">' + escapeHtml(errorMessage) + '</p>';
        return;
    }
    if (!runtimeNotifications.length) {
        list.innerHTML = '<p class="notification-empty">No live CleanHouse notifications.</p>';
        return;
    }
    list.innerHTML = runtimeNotifications.map((notification, index) => {
        const app = findAppForNotification(notification);
        const route = routeForNotification(notification);
        const summary = notification.summary || notification.notification_type || 'CleanHouse notification';
        const detail = route.view === 'app-dashboard'
            ? `Opens ${app?.name || 'app'} dashboard`
            : route.view === 'network'
                ? 'Opens Network evidence'
                : route.view === 'files'
                    ? 'Opens File evidence'
                    : 'Opens CleanHouse overview';
        return (
            '<button class="notification-item" type="button" role="menuitem" data-notification-index="' + index + '">' +
            notificationIcon(notification, app) +
            '<span class="notification-copy">' +
            '  <strong>' + escapeHtml(summary) + '</strong>' +
            '  <span>' + escapeHtml(detail) + '</span>' +
            '  <small>' + escapeHtml(notification.severity || notification.notification_type || 'notification') + '</small>' +
            '</span>' +
            '</button>'
        );
    }).join('');
    list.querySelectorAll('.notification-item').forEach(button => {
        button.addEventListener('click', () => openNotification(runtimeNotifications[Number(button.dataset.notificationIndex)]));
    });
}

function setNotificationDropdown(open) {
    const menu = byId('notification-center-menu');
    const button = byId('notification-center-button');
    if (!menu || !button) return;
    menu.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
}

async function openNotification(notification) {
    if (!notification) return;
    const route = routeForNotification(notification);
    setNotificationDropdown(false);
    if (notification.id && window.CleanHouseAPI?.ackNotification) {
        window.CleanHouseAPI.ackNotification(notification.id).catch(() => {});
        notification.acknowledged = true;
        renderNotificationCenter();
        const badge = byId('notification-center-badge');
        const unread = runtimeNotifications.filter(item => !item.acknowledged).length;
        if (badge) {
            badge.hidden = unread === 0;
            badge.textContent = unread > 99 ? '99+' : String(unread);
        }
    }
    if (route.view === 'app-dashboard') {
        openAppDashboard(route.appId);
    } else {
        showView(route.view);
    }
    if (route.contextId) routeContext(route.contextId, route.message);
    if (route.view === 'network' && route.message && !byId('network-results').textContent.trim()) {
        byId('network-results').innerHTML = '<details class="case-item" open><summary>Selected notification</summary><p>' + escapeHtml(route.message) + '</p></details>';
    }
    window.setTimeout(() => highlightElement(route.targetId), 50);
}

async function scanNetwork() {
    if (renderConsentRequired()) return;
    const button = byId('scan-network-btn');
    button.disabled = true;
    button.textContent = 'Refreshing';
    setNetworkPagePhase('refreshing', 'manual-refresh');
    setText('network-area-status', 'Refreshing network snapshot.');
    try {
        await hydrateNetworkView({ refresh: true, reason: 'manual-refresh' });
    } catch (error) {
        renderNetworkUnavailable({
            state: 'ERROR',
            events: [],
            summary: { reason: 'capture_failed' },
        });
    } finally {
        button.disabled = false;
    }
}

function networkProjectionViewForMode(mode = networkViewMode) {
    if (mode === 'bar') return 'trend';
    if (mode === 'pie') return 'distribution';
    if (['findings', 'timeline'].includes(mode)) return mode;
    return '';
}

function networkModeForProjectionView(view = '') {
    if (view === 'trend') return 'bar';
    if (view === 'distribution') return 'pie';
    if (view === 'findings' || view === 'timeline') return view;
    return '';
}

function networkModeUsesLiveStream(mode = networkViewMode) {
    return mode === 'table' || mode === 'bar';
}

function networkRuntimeHealthyForEmpty(data = {}) {
    const state = normalizeNetworkContractState(data.state || currentNetworkHeaderData.state || 'NO_DATA');
    const tags = data.tags || currentNetworkHeaderData.latestTags || {};
    const tagStatus = normalizeNetworkStatus(tags.status || currentNetworkTags.status || '');
    const tagState = normalizeNetworkState(tags.state || currentNetworkTags.state || '');
    if (networkWarmupState(state, data.summary || currentNetworkHeaderData.summary || {})) return false;
    if (['ERROR', 'CAPTURE_BLOCKED'].includes(state)) return false;
    if (tagStatus === 'OFFLINE' || tagState === 'DEGRADED' || tagState === 'CRITICAL') return false;
    return ['READY', 'CAPTURING', 'NO_DATA'].includes(state);
}

function networkTabLoadingCopy(mode = networkViewMode, phase = networkPagePhase) {
    const verb = phase === 'refreshing' ? 'Refreshing' : (phase === 'reconnecting' ? 'Reconnecting to' : 'Loading');
    const copy = {
        table: phase === 'refreshing' ? 'Refreshing network packets' : 'Loading live network packets',
        findings: `${verb} grouped network findings.`,
        bar: `${verb} saved and live network trend.`,
        pie: `${verb} app distribution for the selected snapshot.`,
        timeline: `${verb} network event history.`,
    };
    return copy[mode] || 'Loading live network packets';
}

function networkTabEmptyCopy(mode = networkViewMode) {
    const copy = {
        table: 'No active packet-backed connections observed yet.',
        findings: 'No grouped findings.',
        bar: 'No trend points for the selected range.',
        pie: 'No packet-supported app activity in the selected snapshot.',
        timeline: 'No notable events or continuity gaps in the selected window.',
    };
    return copy[mode] || 'No recent activity.';
}

function networkCaptureUnavailableCopy(summary = {}) {
    const reason = String(summary.capture_reason || summary.reason || '').trim();
    return {
        engine_unavailable: 'Capture engine unavailable.',
        permission_blocked: 'Permission blocks capture.',
        capture_failed: 'Network capture failed.',
        capture_backlog: 'Captured evidence is delayed while the ingestion pipeline catches up.',
        continuity_gap: 'Network evidence continuity gap.',
    }[reason] || 'Network capture unavailable.';
}

function networkTabDegradedCopy(mode = networkViewMode, data = {}) {
    const state = normalizeNetworkContractState(data.state || currentNetworkHeaderData.state || 'NO_DATA');
    const summary = data.summary || {};
    const reasonCopy = networkCaptureUnavailableCopy(summary);
    if (mode === 'table') {
        if (state === 'ERROR') {
            return reasonCopy;
        }
        return 'Loading live network packets';
    }
    if (state === 'CAPTURE_BLOCKED' || state === 'ERROR') return reasonCopy;
    return networkTabLoadingCopy(mode, networkPagePhase);
}

function networkTabSettledState(mode = networkViewMode, data = {}) {
    const events = Array.isArray(data?.events) ? data.events : [];
    if (events.length) return { phase: 'ready', copy: '' };
    if (!networkRuntimeHealthyForEmpty(data)) {
        return { phase: 'degraded', copy: networkTabDegradedCopy(mode, data) };
    }
    return { phase: 'empty', copy: networkTabEmptyCopy(mode) };
}

function networkTabViewState(renderModel = null) {
    const model = renderModel || buildNetworkRenderModel(networkViewMode);
    const coordinator = syncNetworkCoordinatorUiState();
    const mode = model.mode || networkViewMode;
    const data = model.data || {};
    const events = Array.isArray(data.events) ? data.events : [];
    if (mode === 'table' && events.length) {
        return { phase: 'ready', copy: '' };
    }
    const projectionLoading = model.projectionView &&
        coordinator.requests.projection.status === 'loading' &&
        coordinator.requests.projection.view === model.projectionView &&
        coordinator.requests.projection.selectedRange === model.selectedRange;
    if (networkPagePhase === 'starting') {
        return { phase: 'starting', copy: 'Starting network view.' };
    }
    if (networkPagePhase === 'reconnecting') {
        return { phase: 'reconnecting', copy: mode === 'table' ? 'Loading live network packets' : networkTabLoadingCopy(mode, networkPagePhase) };
    }
    if (mode === 'table' && coordinator.requests.snapshot.status === 'loading') {
        return { phase: networkPagePhase === 'refreshing' ? 'refreshing' : 'waiting', copy: networkTabLoadingCopy('table', networkPagePhase) };
    }
    if (projectionLoading && !events.length) {
        return { phase: networkPagePhase === 'refreshing' ? 'refreshing' : 'loading', copy: networkTabLoadingCopy(mode, networkPagePhase) };
    }
    return networkTabSettledState(mode, data);
}

function renderNetworkProjectionLoading(mode = networkViewMode) {
    const view = networkProjectionViewForMode(mode);
    if (!view) return;
    document.querySelectorAll('[data-network-view]').forEach(button => {
        const active = button.dataset.networkView === mode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
    });
    const graphToggle = document.querySelector('.network-graph-toggle');
    if (graphToggle) graphToggle.hidden = !['bar', 'pie'].includes(mode);
    document.querySelectorAll('[data-network-graph-view]').forEach(button => {
        const active = button.dataset.networkGraphView === mode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const activeTab = document.querySelector('[data-network-view="' + mode + '"]');
    const results = byId('network-results');
    if (results && activeTab?.id) results.setAttribute('aria-labelledby', activeTab.id);
    const label = view.charAt(0).toUpperCase() + view.slice(1);
    setText('network-area-status', networkTabLoadingCopy(mode, networkPagePhase));
    const selectedRange = networkCoordinatorSelectedRange(view);
    const effectiveFetchRange = networkCoordinatorEffectiveFetchRange(view, selectedRange);
    networkCoordinatorSetProjectionLoading(view, selectedRange, effectiveFetchRange, networkHydrationEpoch, networkProjectionRequestId);
    renderNetworkDisplay();
}

function deferNetworkProjectionLoad(mode = networkViewMode, refresh = false) {
    const run = () => loadNetworkProjection(mode, refresh);
    if (typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(() => window.setTimeout(run, 0));
        return;
    }
    window.setTimeout(run, 0);
}

function networkProjectionCacheKey(view, range = networkTimelineRangeMode) {
    return [view || '', range || '5s', view === 'trend' ? networkTrendMetric : ''].join(':');
}

function cloneNetworkProjectionData(data) {
    if (!data || typeof data !== 'object') return null;
    return {
        state: data.state || 'NO_DATA',
        events: Array.isArray(data.events) ? data.events.map(event => ({ ...event })) : [],
        summary: { ...(data.summary || {}) },
        assessments: Array.isArray(data.assessments) ? data.assessments.map(item => ({ ...item })) : [],
        assessment_refs: Array.isArray(data.assessment_refs) ? data.assessment_refs.slice() : [],
        assessment_summary: data.assessment_summary && typeof data.assessment_summary === 'object'
            ? { ...data.assessment_summary, counts: { ...(data.assessment_summary.counts || {}) } }
            : null,
        assessment_filter: data.assessment_filter && typeof data.assessment_filter === 'object' ? { ...data.assessment_filter } : null,
        tags: data.tags && typeof data.tags === 'object' ? { ...data.tags, reasons: Array.isArray(data.tags.reasons) ? data.tags.reasons.slice() : [] } : null,
        collector: data.collector && typeof data.collector === 'object' ? { ...data.collector } : null,
    };
}

function networkProjectionPlaceholderData(view, range = networkTimelineRangeMode) {
    return {
        state: 'CAPTURING',
        events: [],
        summary: {
            reason: 'projection',
            view: view || '',
            range: range || '5s',
            event_count: 0,
        },
        assessments: [],
        assessment_refs: [],
        assessment_summary: null,
        assessment_filter: null,
        tags: null,
    };
}

function networkSettledProjection(view) {
    const selectedRange = networkCoordinatorSelectedRange(view);
    const record = networkCoordinatorProjectionRecord(view, selectedRange);
    if (record) {
        return {
            view,
            range: selectedRange,
            epoch: record.epoch,
            data: cloneNetworkProjectionData(record.data),
        };
    }
    return view ? networkSettledProjectionState[view] || null : null;
}

function networkSettledProjectionData(view, range = networkTimelineRangeMode) {
    const selectedRange = networkCoordinatorSelectedRange(view);
    const settled = networkCoordinatorProjectionRecord(view, selectedRange)
        || networkSettledProjection(view);
    if (!settled) return null;
    const recordedRange = settled.range || settled.selectedRange;
    const effectiveFetchRange = settled.effectiveFetchRange;
    const matchesRange = recordedRange === range || effectiveFetchRange === range;
    if (!matchesRange) return null;
    if (view === 'trend') {
        if (!networkTrendDataMatchesTarget(settled.data, range)) return null;
        return networkTrendProjectionWithLive(settled.data, selectedRange);
    }
    return cloneNetworkProjectionData(settled.data);
}

function rememberNetworkSettledProjection(view, range, data, epoch = networkHydrationEpoch) {
    if (!view) return;
    const effectiveFetchRange = networkCoordinatorEffectiveFetchRange(view, range);
    networkSettledProjectionState[view] = {
        view,
        range,
        effectiveFetchRange,
        epoch,
        data: cloneNetworkProjectionData(data),
    };
    networkCoordinatorRememberProjection(view, range, effectiveFetchRange, data, epoch, networkProjectionRequestId);
}

function abortNetworkSnapshotRequest(options = {}) {
    if (options.cancel === true && networkSnapshotAbortController) {
        networkSnapshotAbortController.abort();
        networkSnapshotAbortController = null;
    }
    networkSnapshotRequestId += 1;
}

function abortNetworkProjectionRequest() {
    if (networkProjectionAbortController) {
        networkProjectionAbortController.abort();
        networkProjectionAbortController = null;
    }
    networkProjectionRequestId += 1;
    const coordinator = ensureNetworkCoordinatorState();
    coordinator.requests.projection.status = 'aborted';
}

function abortNetworkHydrationRequests() {
    abortNetworkSnapshotRequest();
    abortNetworkProjectionRequest();
}

function networkHydrationEpochMatches(epoch) {
    return Number(epoch) === Number(networkHydrationEpoch);
}

function networkProjectionRequestStillActive(view, selectedRange, effectiveFetchRange, epoch, requestId) {
    const coordinator = ensureNetworkCoordinatorState();
    return (
        networkHydrationEpochMatches(epoch) &&
        requestId === networkProjectionRequestId &&
        coordinator.requests.projection.requestId === requestId &&
        coordinator.requests.projection.view === view &&
        coordinator.requests.projection.selectedRange === selectedRange &&
        coordinator.requests.projection.effectiveFetchRange === effectiveFetchRange &&
        networkProjectionViewForMode(networkViewMode) === view &&
        networkCoordinatorSelectedRange(view) === selectedRange &&
        networkProjectionRangeForView(view) === effectiveFetchRange
    );
}

function networkDataHasEvents(data) {
    return Array.isArray(data?.events) && data.events.length > 0;
}

function networkTimelineDataWithSource(data, source) {
    const cloned = cloneNetworkProjectionData(data);
    if (!cloned) return null;
    cloned.summary = {
        ...(cloned.summary || {}),
        timeline_source: source,
    };
    return cloned;
}

function networkTimelineLiveFallbackData() {
    const candidates = [
        networkCoordinatorSnapshotTableData(),
        currentNetworkTableData,
        currentNetworkData,
    ];
    const live = candidates.find(networkDataHasEvents);
    return live ? networkTimelineDataWithSource(live, 'live') : null;
}

function networkTimelineBestData(projectionData, options = {}) {
    const selectedRange = options.selectedRange || networkCoordinatorSelectedRange('timeline');
    if (networkDataHasEvents(projectionData)) {
        return networkTimelineDataWithSource(projectionData, projectionData?.summary?.timeline_source || 'saved');
    }
    // Timeline owns its settled empty state. Snapshot or last-good rows must not
    // masquerade as event history for the currently selected window.
    if (projectionData && typeof projectionData === 'object') {
        return cloneNetworkProjectionData(projectionData);
    }
    return networkProjectionPlaceholderData('timeline', selectedRange);
}

function refreshNetworkTimelineDisplayIfVisible() {
    if (networkViewMode !== 'timeline') return false;
    if (networkProjectionViewForMode(networkViewMode) !== 'timeline') return false;
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('timeline');
        return false;
    }
    renderNetworkDisplay();
    return true;
}

function rememberNetworkTimelineData(data, options = {}) {
    if (!networkDataHasEvents(data)) return;
    networkTimelineLastGoodData = networkTimelineDataWithSource(data, data?.summary?.timeline_source || 'saved');
    networkTimelineLastGoodMeta = {
        range: options.range || networkCoordinatorSelectedRange('timeline'),
        epoch: Number.isFinite(options.epoch) ? options.epoch : networkHydrationEpoch,
    };
}

async function loadNetworkProjection(mode = networkViewMode, refresh = false, options = {}) {
    if (renderConsentRequired()) return;
    const projectionView = networkProjectionViewForMode(mode);
    if (!projectionView || !window.CleanHouseAPI?.getNetworkProjection) return;
    const selectedRange = networkCoordinatorSelectedRange(projectionView);
    const projectionRange = networkCoordinatorEffectiveFetchRange(projectionView, selectedRange);
    const requestedMetric = projectionView === 'trend' ? networkTrendMetric : undefined;
    const epoch = Number.isFinite(options.epoch) ? options.epoch : networkHydrationEpoch;
    const controller = options.controller || new AbortController();
    if (!options.controller) {
        abortNetworkProjectionRequest();
        networkProjectionAbortController = controller;
    }
    const signal = options.signal || controller.signal;
    const requestId = ++networkProjectionRequestId;
    networkCoordinatorSetProjectionLoading(projectionView, selectedRange, projectionRange, epoch, requestId);
    logNetworkStartup('projection_hydration_started', {
        view: projectionView,
        selectedRange,
        effectiveFetchRange: projectionRange,
        refresh,
        requestId,
    });
    const cacheKey = networkProjectionCacheKey(projectionView, projectionRange);
    const cached = cloneNetworkProjectionData(networkProjectionCache[cacheKey]);
    if (cached && (projectionView !== 'trend' || networkTrendDataMatchesTarget(cached, selectedRange)) && networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId)) {
        rememberNetworkSettledProjection(projectionView, selectedRange, cached, epoch);
        currentNetworkProjectionData = projectionView === 'trend'
            ? networkTrendProjectionWithLive(cached, selectedRange)
            : cached;
        if (projectionView === 'timeline') rememberNetworkTimelineData(currentNetworkProjectionData, { range: selectedRange, epoch });
        submitNetworkHeaderEvidence('projection:' + projectionView, currentNetworkProjectionData);
        renderNetworkDisplay();
    }
    try {
        const response = await window.CleanHouseAPI.getNetworkProjection(projectionView, projectionRange, {
            refresh,
            signal,
            metric: requestedMetric,
        });
        if (renderConsentRequired()) return null;
        if (!networkHydrationEpochMatches(epoch) || requestId !== networkProjectionRequestId ||
            (projectionView === 'trend' && (!networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId) || requestedMetric !== networkTrendMetric))) {
            logNetworkStartup('projection_hydration_dropped', {
                view: projectionView,
                selectedRange,
                effectiveFetchRange: projectionRange,
                requestId,
                activeRequestId: networkProjectionRequestId,
            });
            return null;
        }
        const responseSummary = projectionView === 'trend'
            ? { range: selectedRange, metric: requestedMetric, ...(response?.summary || {}) }
            : response?.summary;
        if (projectionView === 'trend' && !networkTrendDataMatchesTarget({ summary: responseSummary }, selectedRange)) {
            throw new Error('Trend response does not match the requested range and metric.');
        }
        const responseEvents = Array.isArray(response?.events) ? response.events : [];
        const supplementalDistribution = projectionView === 'distribution' &&
            Array.isArray(response?.summary?.owners) && response.summary.owners.length > 0;
        if (normalizeNetworkContractState(response?.state) === 'ERROR' && responseEvents.length === 0 && !supplementalDistribution) {
            const failedProjection = {
                state: 'ERROR',
                events: [],
                summary: responseSummary || { reason: 'capture_failed' },
                assessments: Array.isArray(response?.assessments) ? response.assessments : [],
                assessment_refs: Array.isArray(response?.assessment_refs) ? response.assessment_refs : [],
                assessment_summary: response?.assessment_summary || null,
                assessment_filter: response?.assessment_filter || null,
                tags: response?.tags || null,
                collector: response?.collector || null,
            };
            rememberNetworkSettledProjection(projectionView, selectedRange, failedProjection, epoch);
            currentNetworkProjectionData = failedProjection;
            submitNetworkHeaderEvidence('projection:' + projectionView, failedProjection, { captureStatus: true });
            if (networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId)) {
                renderNetworkDisplay();
                setText('network-area-status', networkCaptureUnavailableCopy(failedProjection.summary));
            }
            return failedProjection;
        }
        const state = normalizeNetworkContractState(response?.state || 'NO_DATA');
        const nextProjectionData = {
            state,
            events: responseEvents,
            summary: responseSummary || {},
            assessments: Array.isArray(response?.assessments) ? response.assessments : [],
            assessment_refs: Array.isArray(response?.assessment_refs) ? response.assessment_refs : [],
            assessment_summary: response?.assessment_summary || null,
            assessment_filter: response?.assessment_filter || null,
            tags: response?.tags || null,
            collector: response?.collector || null,
        };
        rememberNetworkSettledProjection(projectionView, selectedRange, nextProjectionData, epoch);
        submitNetworkHeaderEvidence('projection:' + projectionView, nextProjectionData);
        if (projectionView !== 'timeline' || networkDataHasEvents(nextProjectionData)) {
            networkProjectionCache[cacheKey] = cloneNetworkProjectionData(nextProjectionData);
        }
        if (projectionView === 'timeline') {
            rememberNetworkTimelineData(nextProjectionData, { range: selectedRange, epoch });
        }
        if (projectionView === 'trend') {
            currentNetworkTrendBaseData = {
                state,
                events: nextProjectionData.events.slice(),
                summary: { ...(nextProjectionData.summary || {}) },
                assessments: nextProjectionData.assessments.slice(),
                assessment_refs: nextProjectionData.assessment_refs.slice(),
                assessment_summary: nextProjectionData.assessment_summary,
                assessment_filter: nextProjectionData.assessment_filter,
            };
            currentNetworkProjectionData = networkTrendProjectionWithLive(currentNetworkTrendBaseData, selectedRange);
        } else {
            currentNetworkProjectionData = nextProjectionData;
        }
        if (networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId)) {
            renderNetworkDisplay();
            if (state === 'ERROR') {
                setText('network-area-status', networkCaptureUnavailableCopy(nextProjectionData.summary));
            }
        }
        logNetworkStartup('projection_hydration_completed', {
            view: projectionView,
            selectedRange,
            effectiveFetchRange: projectionRange,
            requestId,
            eventCount: nextProjectionData.events.length,
            historySources: nextProjectionData.summary?.history_sources || {},
            gapCount: Number(nextProjectionData.summary?.gap_count || 0),
        });
        return currentNetworkProjectionData;
    } catch (error) {
        if (error?.name === 'AbortError') return null;
        logNetworkStartup('projection_hydration_failed', {
            view: projectionView,
            selectedRange,
            effectiveFetchRange: projectionRange,
            requestId,
            error: String(error?.message || error || 'unknown'),
        });
        if (networkProjectionRequestStillActive(projectionView, selectedRange, projectionRange, epoch, requestId)) {
            renderNetworkUnavailable({
                state: 'ERROR',
                events: [],
                summary: { reason: 'capture_failed' },
            });
        }
        return null;
    } finally {
        if (networkProjectionAbortController === controller) {
            networkProjectionAbortController = null;
        }
    }
}

async function hydrateNetworkView(options = {}) {
    const refresh = Boolean(options.refresh);
    const reason = String(options.reason || '');
    const epoch = ++networkHydrationEpoch;
    networkStartupInstrumentation = { epoch, headerCountAvailable: false, firstRowRendered: false };
    logNetworkStartup('table_hydration_started', {
        refresh,
        reason,
        existingInventoryRows: Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events.length : 0,
    });
    networkTableSort = { key: 'time', direction: 'desc' };
    updateNetworkTableSortHeaders();
    networkLiveEvidenceEstablished = false;
    const coordinator = syncNetworkCoordinatorUiState();
    coordinator.requests.hydrationEpoch = epoch;
    setNetworkPagePhase(refresh ? 'refreshing' : (reason === 'view-enter' && !currentNetworkData ? 'starting' : 'waiting'), reason);
    abortNetworkHydrationRequests();
    coordinator.requests.snapshot = { requestId: networkSnapshotRequestId + 1, status: 'loading' };
    coordinator.viewStates.tabs.table = {
        phase: refresh ? 'refreshing' : 'waiting',
        copy: networkTabLoadingCopy('table', networkPagePhase),
    };
    networkEnginePanel();
    if (!currentNetworkData && !currentNetworkTableData && !currentNetworkProjectionData) {
        currentNetworkTableData = networkCoordinatorSnapshotTableData();
    }
    renderNetworkDisplay();
    const snapshot = await loadNetworkHeaderSnapshot(refresh, { epoch, reason });
    if (!networkHydrationEpochMatches(epoch)) return null;
    if (
        normalizeNetworkContractState(snapshot?.state || 'NO_DATA') === 'ERROR' &&
        !(Array.isArray(snapshot?.events) && snapshot.events.length > 0)
    ) {
        setNetworkPagePhase('ready', reason);
        const failedSnapshot = {
            state: 'ERROR',
            events: [],
            summary: snapshot?.summary || { reason: 'capture_failed' },
            tags: snapshot?.tags || null,
            collector: snapshot?.collector || null,
            powered_by_wireshark: false,
        };
        currentNetworkData = failedSnapshot;
        currentNetworkTableData = failedSnapshot;
        networkCoordinatorRememberSnapshot(currentNetworkTableData, epoch, networkSnapshotRequestId);
        const projectionView = networkProjectionViewForMode(networkViewMode);
        if (!projectionView) {
            renderNetworkUnavailable(snapshot);
            return snapshot;
        }
        // Capture health and retained projections are independent. An unavailable
        // capture engine must not prevent Findings, Trend, Distribution, or
        // Timeline from loading their durable evidence and continuity state.
        renderNetworkProjectionLoading(networkViewMode);
        await loadNetworkProjection(networkViewMode, refresh, { epoch });
        return snapshot;
    }
    setNetworkPagePhase('ready', reason);
    currentNetworkTableData = networkHeaderTableData();
    networkCoordinatorRememberSnapshot(currentNetworkTableData, epoch, networkSnapshotRequestId);
    renderNetworkDisplay();
    const expectedRows = networkTableVisibleRows(currentNetworkTableData?.events || [], {
        filterReason: '',
        pinnedEntityId: networkTablePinnedEntityId,
        limit: NETWORK_TABLE_DOM_ROW_LIMIT,
    }).length;
    logNetworkStartup('table_hydration_completed', {
        refresh,
        reason,
        inventoryRows: Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events.length : 0,
        expectedRows,
        renderedRows: document.querySelector('.network-table')?.querySelectorAll('tbody tr.network-row-evidence').length || 0,
    });
    if (networkModeUsesLiveStream(networkViewMode)) {
        startNetworkLiveUpdates();
    }
    const projectionView = networkProjectionViewForMode(networkViewMode);
    if (!projectionView) return snapshot;
    renderNetworkProjectionLoading(networkViewMode);
    await loadNetworkProjection(networkViewMode, refresh, { epoch });
    return snapshot;
}

function selectNetworkView(mode, options = {}) {
    persistNetworkViewMode(mode);
    networkActionFilterReason = '';
    syncNetworkCoordinatorUiState();
    if (networkViewMode !== 'table') clearNetworkTableFlushTimer();
    if (networkModeUsesLiveStream(networkViewMode)) startNetworkLiveUpdates();
    else stopNetworkLiveUpdates();
    renderNetworkDisplay();
    if (networkViewMode === 'table' && networkTableUiBuffer.length) {
        scheduleNetworkTableFlush();
    }
    const projectionView = networkProjectionViewForMode(networkViewMode);
    if (projectionView) deferNetworkProjectionLoad(networkViewMode, Boolean(options.refresh));
}

function selectNetworkRange(mode, options = {}) {
    if (networkViewMode === 'bar') {
        abortNetworkProjectionRequest();
        networkSettledProjectionState.trend = null;
        currentNetworkTrendBaseData = null;
        currentNetworkProjectionData = null;
    }
    persistNetworkTimelineRange(mode);
    syncNetworkCoordinatorUiState();
    if (networkViewMode === 'bar') {
        renderNetworkProjectionLoading('bar');
        deferNetworkProjectionLoad('bar', Boolean(options.refresh ?? true));
        return;
    }
    renderNetworkToolbarContext();
    renderNetworkDisplay();
    if (networkViewMode === 'timeline' || networkViewMode === 'bar') {
        deferNetworkProjectionLoad(networkViewMode, Boolean(options.refresh ?? true));
    }
}

function resumeNetworkViewHydration(reason = 'resume') {
    networkVisibilityPendingHydration = false;
    return hydrateNetworkView({ refresh: true, reason });
}

function networkEventSourceClosed(source = networkLiveSource) {
    return Boolean(source && Number(source.readyState) === 2);
}

function networkLiveUrlFromCursor() {
    const baseUrl = window.CleanHouseAPI.getNetworkLiveUrl();
    const cursor = normalizeNetworkCursor(networkLastAppliedCursor || networkSnapshotCursor);
    if (!cursor) return baseUrl;
    try {
        const url = new URL(baseUrl, window.location.origin);
        url.searchParams.set('after', cursor);
        return url.toString();
    } catch (error) {
        const separator = String(baseUrl).includes('?') ? '&' : '?';
        return `${baseUrl}${separator}after=${encodeURIComponent(cursor)}`;
    }
}

function observeNetworkStreamContinuity(payload = {}, event = {}, options = {}) {
    const cursor = networkCursorFromPayload(payload, event);
    const epoch = networkCursorEpochFromPayload(payload, cursor);
    networkAdoptCursorEpoch(epoch);
    if (options.advance && cursor) {
        advanceNetworkAppliedCursor(cursor, epoch, { ordered: true });
    }
    return { cursor, epoch: epoch || networkCursorEpoch };
}

function startNetworkLiveUpdates() {
    if (renderConsentRequired()) return;
    if (networkLiveSource && networkEventSourceClosed(networkLiveSource)) {
        networkLiveSource.close();
        networkLiveSource = null;
    }
    if (networkLiveSource) {
        if (!networkLiveRenderTimer) networkLiveRenderTimer = window.setInterval(renderNetworkTimeSensitiveView, 1000);
        return;
    }
    if (networkLiveStartTimer) return;
    if (!window.EventSource || !window.CleanHouseAPI?.getNetworkLiveUrl) {
        renderNetworkUnavailable({ state: 'ERROR', events: [], summary: { reason: 'capture_failed' } });
        return;
    }
    setNetworkPagePhase('waiting', 'live-start');
    networkEnginePanel('Reconnecting to runtime.', 'READY', 'Refresh Network');
    const startupPayload = currentNetworkTableData && typeof currentNetworkTableData === 'object'
        ? currentNetworkTableData
        : (currentNetworkData && typeof currentNetworkData === 'object'
            ? currentNetworkData
            : { state: 'READY', summary: { reason: 'ready' } });
    submitNetworkHeaderEvidence('live-status', startupPayload, { captureStatus: true, source: 'status' });
    networkLiveStartTimer = window.setTimeout(startNetworkLiveUpdatesNow, NETWORK_LIVE_START_DELAY_MS);
}

function startNetworkLiveUpdatesNow() {
    if (renderConsentRequired()) return;
    networkLiveStartTimer = null;
    if (networkLiveSource && networkEventSourceClosed(networkLiveSource)) {
        networkLiveSource.close();
        networkLiveSource = null;
    }
    if (networkLiveSource) return;
    if (!window.EventSource || !window.CleanHouseAPI?.getNetworkLiveUrl) {
        renderNetworkUnavailable({ state: 'ERROR', events: [], summary: { reason: 'capture_failed' } });
        return;
    }
    const source = new EventSource(networkLiveUrlFromCursor());
    networkLiveSource = source;
    source.addEventListener('open', () => {
        if (networkLiveSource !== source) return;
        setNetworkPagePhase('ready', 'live-open');
    });
    source.addEventListener('status', event => {
        if (networkLiveSource !== source) return;
        const payload = parseNetworkStreamPayload(event.data);
        observeNetworkStreamContinuity(payload, event);
        networkStreamTags = networkTagsFromContract(payload);
        submitNetworkHeaderEvidence('live-status', payload, { captureStatus: true, source: 'status' });
    });
    source.addEventListener('network-event', event => {
        if (networkLiveSource !== source) return;
        const payload = parseNetworkStreamPayload(event.data);
        const packetEvent = payload?.event && typeof payload.event === 'object'
            ? {
                ...payload.event,
                assessments: Array.isArray(payload.assessments) ? payload.assessments : payload.event.assessments,
                assessment_refs: Array.isArray(payload.assessment_refs) ? payload.assessment_refs : payload.event.assessment_refs,
                assessment_summary: payload.assessment_summary || payload.event.assessment_summary,
                assessment_filter: payload.assessment_filter || payload.event.assessment_filter,
            }
            : payload;
        appendNetworkLiveEvent(packetEvent, { lastEventId: event.lastEventId });
    });
    const handleContinuityNotice = (kind, event) => {
        if (networkLiveSource !== source) return;
        const payload = parseNetworkStreamPayload(event.data);
        observeNetworkStreamContinuity(payload, event, { advance: true });
        const failure = kind === 'failure';
        networkStreamTags = payload.tags && typeof payload.tags === 'object'
            ? networkTagsFromContract(payload)
            : {
                status: failure ? 'OFFLINE' : 'OBSERVING',
                state: 'DEGRADED',
                reasons: ['Capture engine limited'],
                explanation: String(payload.reason || kind),
            };
        submitNetworkHeaderEvidence(`live-${kind}`, {
            ...payload,
            state: payload.state || 'ERROR',
            tags: networkStreamTags,
            summary: payload.summary || { reason: kind === 'gap' ? 'continuity_gap' : 'capture_failed' },
        }, { captureStatus: true, source: kind });
    };
    source.addEventListener('gap', event => handleContinuityNotice('gap', event));
    source.addEventListener('failure', event => handleContinuityNotice('failure', event));
    source.onerror = () => {
        if (networkLiveSource !== source) return;
        setNetworkPagePhase('reconnecting', 'live-error');
        networkStreamTags = { status: 'OFFLINE', state: 'DEGRADED', reasons: ['Capture engine limited'], explanation: 'error' };
        submitNetworkHeaderEvidence('live-status', { state: 'ERROR', tags: networkStreamTags, summary: { reason: 'capture_failed' } }, { captureStatus: true, source: 'status' });
        if (networkEventSourceClosed(source)) {
            networkLiveSource = null;
            startNetworkLiveUpdates();
        }
    };
    if (!networkLiveQuietTimer) networkLiveQuietTimer = window.setInterval(() => {
        const now = Date.now();
        const lastSnapshotAt = currentNetworkHeaderData.lastSnapshotAt || networkLiveLastQuietSnapshotAt || 0;
        if (networkShouldSuspendDomWork()) {
            if (now - lastSnapshotAt >= NETWORK_LIVE_QUIET_MS) {
                networkVisibilityPendingHydration = true;
            }
            markNetworkDeferredRender('header');
            return;
        }
        if (now - lastSnapshotAt >= NETWORK_OS_SUMMARY_REFRESH_MS) {
            networkLiveLastQuietSnapshotAt = now;
            loadNetworkHeaderSnapshot(false, { reason: 'quiet-refresh' });
        }
    }, 1000);
    if (!networkLiveRenderTimer) networkLiveRenderTimer = window.setInterval(renderNetworkTimeSensitiveView, 1000);
}

function stopNetworkLiveUpdates() {
    if (networkLiveStartTimer) {
        window.clearTimeout(networkLiveStartTimer);
        networkLiveStartTimer = null;
    }
    if (networkLiveSource) {
        networkLiveSource.close();
        networkLiveSource = null;
    }
    if (networkLiveQuietTimer) {
        window.clearInterval(networkLiveQuietTimer);
        networkLiveQuietTimer = null;
    }
    if (networkLiveRenderTimer) {
        window.clearInterval(networkLiveRenderTimer);
        networkLiveRenderTimer = null;
    }
    networkLiveLastQuietSnapshotAt = 0;
    networkStreamTags = null;
}

function renderNetworkTimeSensitiveView() {
    if (networkShouldSuspendDomWork()) {
        if (networkViewMode === 'bar' && networkTrendLiveDirty) {
            markNetworkDeferredRender('trend');
        }
        return false;
    }
    if (networkViewMode === 'bar' && networkTrendLiveDirty) {
        networkTrendLiveDirty = false;
        renderNetworkDisplay();
    }
    if (networkViewMode === 'table' && networkTablePinnedEntityId) {
        flushNetworkTableRender({ force: true });
    }
    return true;
}

function networkEnginePanel(primary, statusText = 'Observing', buttonText = 'Refresh Network') {
    if (renderConsentRequired()) return;
    const panel = byId('network-engine-panel');
    if (!panel) return;
    panel.innerHTML =
        '<div class="network-status-row">' +
        '<span id="network-status-tag" class="network-status-pill network-activity-pill">QUIET</span>' +
        '<span id="network-state-tag" class="network-status-pill network-state-pill">UNKNOWN</span>' +
        '<span id="network-reason-tags" class="network-reason-tags" hidden></span>' +
        '</div>' +
        '<div id="network-posture-summary" class="network-posture-summary" aria-live="polite" aria-label="Network security posture">' +
        '<span data-network-posture="threats">— Threats</span>' +
        '<span data-network-posture="vulnerabilities">— Vulnerabilities</span>' +
        '<span data-network-posture="strengths">— Strengths</span>' +
        '</div>' +
        '<p id="network-message"></p>';
    const button = byId('scan-network-btn');
    if (button) button.textContent = buttonText;
    renderNetworkHeader();
    setNetworkConnectionCount();
}

function networkWarmupState(state, summary = {}) {
    return state === 'WARMING' || String(summary?.reason || '').trim() === 'waiting_for_capture';
}

function networkCaptureStatusText(state, summary = {}) {
    if (state === 'CAPTURING') return 'Capturing';
    if (networkWarmupState(state, summary)) return 'Reconnecting to runtime';
    if (state === 'NO_DATA') return 'No recent activity';
    if (state === 'CAPTURE_BLOCKED') return 'Network capture unavailable';
    return state;
}

function networkTableEmptyStateText(data = {}) {
    return networkTabViewState({ mode: 'table', data, events: Array.isArray(data.events) ? data.events : [] }).copy;
}

function parseNetworkStreamPayload(value) {
    try {
        const payload = JSON.parse(value || '{}');
        return payload && typeof payload === 'object' ? payload : {};
    } catch (error) {
        return {};
    }
}

function normalizeNetworkContractState(value) {
    const label = String(value || '').toUpperCase();
    return NETWORK_CONTRACT_STATES.has(label) ? label : 'ERROR';
}

function networkSummaryReason(summary = {}) {
    const reason = String(summary?.reason || '').trim();
    return NETWORK_REASON_LABELS[reason] || (reason ? 'capture_failed' : '');
}

function networkTagsFromContract(payload = {}) {
    if (payload?.tags && typeof payload.tags === 'object') {
        const tagState = normalizeNetworkState(payload.tags.state);
        const reason = Array.isArray(payload.tags.reasons)
            ? payload.tags.reasons.map(item => normalizeNetworkReason(item, tagState)).find(Boolean)
            : '';
        return {
            status: normalizeNetworkStatus(payload.tags.status),
            state: tagState,
            reasons: reason ? [reason] : [],
            explanation: payload.tags.explanation || '',
        };
    }
    const state = normalizeNetworkContractState(payload.state);
    const summary = payload.summary && typeof payload.summary === 'object' ? payload.summary : {};
    const reason = state === 'ERROR' ? networkSummaryReason(summary) || 'capture_failed' : '';
    return {
        status: normalizeNetworkStatus(state),
        state: normalizeNetworkState(state),
        reasons: reason ? [normalizeNetworkReason(reason, normalizeNetworkState(state))].filter(Boolean) : [],
        explanation: reason || state.toLowerCase(),
    };
}

function normalizeNetworkStatus(value) {
    const label = String(value || '').toUpperCase();
    if (NETWORK_STATUS_TAGS.has(label)) return label;
    if (['READY', 'CAPTURING'].includes(label)) return 'OBSERVING';
    if (label === 'WARMING') return 'QUIET';
    if (label === 'NO_DATA') return 'QUIET';
    if (['ERROR', 'CAPTURE_BLOCKED'].includes(label)) return 'OFFLINE';
    return 'OFFLINE';
}

function normalizeNetworkState(value) {
    const label = String(value || '').toUpperCase();
    if (NETWORK_STATE_TAGS.has(label)) return label;
    if (label === 'WARMING') return 'DEGRADED';
    if (['READY', 'CAPTURING', 'NO_DATA'].includes(label)) return 'HEALTHY';
    if (['ERROR', 'CAPTURE_BLOCKED'].includes(label)) return 'DEGRADED';
    return 'UNKNOWN';
}

function normalizeNetworkReason(value, state) {
    const label = String(value || '').trim();
    if (!['DEGRADED', 'CRITICAL'].includes(state)) return '';
    const legacy = {
        permission_blocked: 'Permission blocks capture',
        capture_failed: 'Capture engine limited',
        capture_backlog: 'Capture engine limited',
        timeout: 'Connection attempts failed',
        engine_unavailable: 'Capture engine limited',
    };
    const normalized = legacy[label] || NETWORK_REASON_LABELS[label] || label;
    if (NETWORK_REASON_TAGS.has(normalized)) return normalized;
    return '';
}

function networkTagsFromLegacyState(value, message = '') {
    const state = normalizeNetworkContractState(value);
    return { status: state, state, reasons: state === 'ERROR' ? ['capture_failed'] : [], explanation: message || state.toLowerCase() };
}

function networkHostIsLocal(host) {
    const value = String(host || '').trim().toLowerCase();
    return !value ||
        value === '*' ||
        value === '::1' ||
        value === 'localhost' ||
        value.startsWith('fd') ||
        value.startsWith('127.') ||
        value.startsWith('10.') ||
        value.startsWith('192.168.') ||
        value.startsWith('169.254.') ||
        /^172\.(1[6-9]|2\d|3[0-1])\./.test(value) ||
        value.startsWith('fe80:');
}

function networkEventIsExternal(event) {
    return Boolean(event?.dst_ip) && !networkHostIsLocal(event.dst_ip);
}

function networkEventHasReadableDestination(event) {
    return Boolean(event?.dns_query || event?.http_host || event?.tls_sni);
}

function eventCriticalReason(event) {
    const text = normalizedText([
        event?.reason,
        event?.severity,
        event?.category,
        event?.meaning,
        event?.summary,
    ].filter(Boolean).join(' '));
    if (event?.known_malicious || text.includes('known malicious')) return 'Known malicious endpoint';
    if (text.includes('blocked threat')) return 'Blocked threat active';
    if (text.includes('exfil')) return 'Data exfiltration suspected';
    if (text.includes('malware')) return 'Malware process active';
    if (text.includes('suspicious listener')) return 'Suspicious listener exposed';
    if (text.includes('unexpected inbound')) return 'Unexpected inbound access';
    if (text.includes('quarantine bypass')) return 'Quarantine bypass suspected';
    return '';
}

function eventDegradedReason(event) {
    const text = normalizedText([
        event?.reason,
        event?.category,
        event?.meaning,
        event?.summary,
        event?.protocol,
    ].filter(Boolean).join(' '));
    if (event?.event_type === 'network_timeline_gap') return 'Capture engine limited';
    if (text.includes('permission') || text.includes('operation not permitted')) return 'Permission blocks capture';
    if (text.includes('failed') || text.includes('refused') || text.includes('timeout')) return 'Connection attempts failed';
    if (networkEventIsExternal(event) && networkEventAppName(event) === 'Unknown app') return 'Unknown app active';
    if (event?.new_destination || text.includes('new destination')) return 'New destination seen';
    if (networkEventIsExternal(event) && String(event?.dst_port || '') === '80') return 'Unencrypted web request';
    const port = String(event?.dst_port || '').trim();
    const commonPorts = new Set(['22', '25', '53', '80', '123', '443', '465', '587', '993', '995', '5223', '5228']);
    if (networkEventIsExternal(event) && port && !commonPorts.has(port)) return 'Unusual port used';
    return '';
}

function networkCountHeadlineText(mode = networkViewMode, data = null) {
    const normalizedMode = normalizeNetworkModeValue(mode);
    const resolvedMode = networkProjectionViewForMode(normalizedMode) || normalizedMode;
    const resolvedData = data && typeof data === 'object' ? data : {};
    const summaryCounts = resolvedData.summary && typeof resolvedData.summary.counts === 'object' ? resolvedData.summary.counts : {};
    const totalCount = Number(
        resolvedData.total_connection_count ??
        summaryCounts.connections ??
        currentNetworkHeaderData.totalConnectionCount ??
        0
    );
    const total = Number.isFinite(totalCount) ? Math.max(0, Math.round(totalCount)) : 0;
    const capped = Boolean(
        resolvedData.displayed_connection_count_capped ??
        currentNetworkHeaderData.displayedConnectionCountCapped
    );
    const eventCount = Number(
        resolvedData.displayed_connection_count ??
        resolvedData.event_count ??
        resolvedData.activeConnectionCount ??
        (Array.isArray(resolvedData.events) ? resolvedData.events.length : 0)
    );
    const shownCount = Number.isFinite(eventCount) ? Math.max(0, Math.round(eventCount)) : 0;
    if (resolvedMode === 'table') {
        const connectionCount = total > 0 ? total : shownCount;
        return `${connectionCount} active ${connectionCount === 1 ? 'connection' : 'connections'}.`;
    }
    const viewState = networkTabViewState({
        mode: normalizedMode || networkViewMode,
        projectionView: networkProjectionViewForMode(normalizedMode),
        selectedRange: networkCoordinatorSelectedRange(networkProjectionViewForMode(normalizedMode) || normalizedMode),
        data: resolvedData,
        events: Array.isArray(resolvedData.events) ? resolvedData.events : [],
    });
    const distributionOwners = Array.isArray(resolvedData?.summary?.owners)
        ? resolvedData.summary.owners
        : [];
    const supplementalDistribution = resolvedMode === 'distribution' && distributionOwners.length > 0;
    if (!supplementalDistribution && viewState.phase !== 'ready' && viewState.copy) return viewState.copy;
    const timeviewRange = resolvedMode === 'timeline'
        ? networkTimelineDisplayRangeMode()
        : networkProjectionRangeForView(resolvedMode);
    const timeviewLabel = timeviewRange
        ? networkRangePlainLabel(NETWORK_TIMELINE_RANGES[timeviewRange] || NETWORK_TIMELINE_RANGES['5s'])
        : '';
    if (resolvedMode === 'findings') {
        const findingCount = Array.isArray(resolvedData.assessments) && resolvedData.assessments.length > 0
            ? resolvedData.assessments.length
            : shownCount;
        return `${findingCount} findings.`;
    }
    if (resolvedMode === 'trend') {
        const metricLabels = {
            connections: 'connections',
            strengths: 'strengths',
            vulnerabilities: 'vulnerabilities',
            threats: 'threats',
        };
        return `${shownCount} ${metricLabels[networkTrendMetric] || 'connections'} in the last ${timeviewLabel || 'selected window'}.`;
    }
    if (resolvedMode === 'distribution') {
        const appCount = distributionOwners.length || (Array.isArray(resolvedData.events) && resolvedData.events.length
            ? new Set(resolvedData.events.map(event => networkEventAppName(event)).filter(Boolean)).size
            : 0);
        return `${appCount} active apps.`;
    }
    if (resolvedMode === 'timeline') {
        return `${shownCount} events in the last ${timeviewLabel || 'selected window'}.`;
    }
    return `${total > 0 ? total : shownCount} network connections.`;
}

function networkCapturedPacketCount(data = {}) {
    return (Array.isArray(data?.events) ? data.events : []).reduce((total, event) => {
        const packetCount = Number(event?.packet_count);
        if (Number.isFinite(packetCount) && packetCount >= 0) return total + packetCount;
        if (Array.isArray(event?.raw_packet_events)) return total + event.raw_packet_events.length;
        return total + 1;
    }, 0);
}

function networkConnectionCountText(totalCount = 0, shownCount = 0, capped = false) {
    const totalNumeric = Number(totalCount);
    const shownNumeric = Number(shownCount);
    const total = Number.isFinite(totalNumeric) ? Math.max(0, Math.round(totalNumeric)) : 0;
    const shown = Number.isFinite(shownNumeric) ? Math.max(0, Math.round(shownNumeric)) : 0;
    if (total > 0) {
        return capped ? `${total} network connections · ${shown} shown` : `${total} network connections`;
    }
    if (capped) {
        return `${shown} shown`;
    }
    return `${shown} network connections`;
}

function buildNetworkRenderModel(mode = networkViewMode) {
    const coordinator = syncNetworkCoordinatorUiState();
    const resolvedMode = normalizeNetworkModeValue(mode) || 'table';
    const projectionView = networkProjectionViewForMode(resolvedMode);
    const selectedRange = projectionView ? networkCoordinatorSelectedRange(projectionView) : '';
    const effectiveFetchRange = projectionView ? networkCoordinatorEffectiveFetchRange(projectionView, selectedRange) : '';
    const settledProjection = projectionView ? networkSettledProjectionData(projectionView, selectedRange) : null;
    const snapshotTableData = networkCoordinatorSnapshotTableData();
    const tableData = currentNetworkTableData || snapshotTableData;
    let data = snapshotTableData;
    if (resolvedMode === 'table') {
        data = tableData || {};
    } else if (resolvedMode === 'findings') {
        data = settledProjection || networkProjectionPlaceholderData('findings', selectedRange);
    } else if (resolvedMode === 'timeline') {
        data = networkTimelineBestData(settledProjection, { selectedRange });
    } else if (resolvedMode === 'bar') {
        data = settledProjection || networkTrendProjectionWithLive(currentNetworkTrendBaseData || networkProjectionPlaceholderData('trend', selectedRange), selectedRange);
    } else if (resolvedMode === 'pie') {
        data = settledProjection || networkProjectionPlaceholderData('distribution', selectedRange);
    }
    const events = Array.isArray(data?.events) ? data.events : [];
    const headlineData = resolvedMode === 'table'
        ? (tableData || snapshotTableData)
        : data;
    const renderKey = [
        String(coordinator.requests.hydrationEpoch || 0),
        resolvedMode,
        projectionView || '',
        selectedRange || '',
        effectiveFetchRange || '',
        String(coordinator.snapshot?.version || 0),
        String(events.length),
    ].join(':');
    return {
        mode: resolvedMode,
        projectionView,
        selectedRange,
        effectiveFetchRange,
        data,
        events,
        headlineData,
        renderKey,
    };
}

function networkHeadlineDataForMode(mode = networkViewMode) {
    return buildNetworkRenderModel(mode).headlineData;
}

function networkHeaderCurrentCount(now = Date.now()) {
    const totalConnectionCount = Number(currentNetworkHeaderData.totalConnectionCount || 0);
    if (totalConnectionCount > 0) return totalConnectionCount;
    const activeSocketCount = Number(currentNetworkHeaderData.activeSocketCount || 0);
    if (activeSocketCount > 0) return activeSocketCount;
    const activeConnectionCount = Number(currentNetworkHeaderData.activeConnectionCount || 0);
    if (activeConnectionCount > 0) return activeConnectionCount;
    return 0;
}

function setNetworkConnectionCount(renderModel = null) {
    if (renderConsentRequired()) return;
    const model = renderModel || buildNetworkRenderModel(networkViewMode);
    setText('network-message', networkCountHeadlineText(networkViewMode, model.headlineData));
}

function updateNetworkWiresharkBranding(data = {}) {
    const provider = byId('network-provider');
    if (!provider) return;
    const collector = data.collector && typeof data.collector === 'object' ? data.collector : {};
    const explicit = data.powered_by_wireshark;
    const powered = explicit === true || (
        String(collector.state || '').toLowerCase() === 'running' &&
        Number(collector.last_packet_sequence || 0) > 0
    );
    const hasEvidence = explicit !== undefined || Object.keys(collector).length > 0;
    if (!hasEvidence) return;
    const collectorState = String(collector.state || '').toLowerCase();
    const state = powered ? 'verified' : (hasEvidence && collectorState ? 'degraded' : 'verifying');
    provider.dataset.providerState = state;
    provider.setAttribute('aria-label', `Powered by Wireshark — ${state}`);
}

function setNetworkHeaderData(data = {}, options = {}) {
    const hasEvents = Array.isArray(data.events);
    const events = hasEvents ? data.events : (Array.isArray(currentNetworkHeaderData.events) ? currentNetworkHeaderData.events : []);
    const state = normalizeNetworkContractState(data.state || currentNetworkHeaderData.state || 'NO_DATA');
    const summaryCounts = data.summary && typeof data.summary.counts === 'object' ? data.summary.counts : {};
    const totalConnectionCount = Number(summaryCounts.connections ?? data.totalConnectionCount ?? currentNetworkHeaderData.totalConnectionCount);
    const displayedEventCount = Number(data.event_count ?? data.activeConnectionCount ?? (hasEvents ? events.length : currentNetworkHeaderData.displayedConnectionCount));
    const displayedCount = Number.isFinite(displayedEventCount) ? Math.max(0, displayedEventCount) : events.length;
    const isLivePacketUpdate = options.source === 'live';
    const isStatusUpdate = options.source === 'status';
    const rawOsActiveConnectionCount = summaryCounts.os_active_connections;
    const nextOsActiveConnectionCount = Number(rawOsActiveConnectionCount);
    const hasOsActiveConnectionCount = rawOsActiveConnectionCount !== undefined &&
        rawOsActiveConnectionCount !== null && Number.isFinite(nextOsActiveConnectionCount);
    const totalCount = Number.isFinite(totalConnectionCount) ? Math.max(0, totalConnectionCount) : (Number(currentNetworkHeaderData.totalConnectionCount || 0) || 0);
    const capped = displayedCount >= NETWORK_LIVE_EVENT_LIMIT && (totalCount === 0 || totalCount > displayedCount);
    const previousActiveCount = Number(currentNetworkHeaderData.activeConnectionCount || 0);
    const activeSocketCount = isLivePacketUpdate ? Math.max(Number(currentNetworkHeaderData.activeSocketCount || 0), previousActiveCount) : Number(currentNetworkHeaderData.activeSocketCount || 0);
    const activeConnectionCount = totalCount > 0
        ? totalCount
        : Math.max(previousActiveCount, activeSocketCount);
    currentNetworkHeaderData = {
        ...currentNetworkHeaderData,
        state,
        events,
        summary: data.summary && typeof data.summary === 'object' ? data.summary : {},
        assessments: Array.isArray(data.assessments)
            ? data.assessments.map(item => ({ ...item }))
            : currentNetworkHeaderData.assessments,
        assessmentRefs: Array.isArray(data.assessment_refs)
            ? data.assessment_refs.slice()
            : currentNetworkHeaderData.assessmentRefs,
        assessmentSummary: data.assessment_summary && typeof data.assessment_summary === 'object'
            ? { ...data.assessment_summary, counts: { ...(data.assessment_summary.counts || {}) } }
            : currentNetworkHeaderData.assessmentSummary,
        assessmentFilter: data.assessment_filter && typeof data.assessment_filter === 'object'
            ? { ...data.assessment_filter }
            : currentNetworkHeaderData.assessmentFilter,
        osActiveConnectionCount: hasOsActiveConnectionCount
            ? Math.max(0, Math.round(nextOsActiveConnectionCount))
            : currentNetworkHeaderData.osActiveConnectionCount,
        totalConnectionCount: totalCount,
        displayedConnectionCount: displayedCount,
        displayedConnectionCountCapped: capped,
        activeConnectionCount,
        activeSocketCount,
        packetCount: Number(currentNetworkHeaderData.packetCount || 0),
        captureAvailable: !['ERROR', 'CAPTURE_BLOCKED'].includes(state),
        lastSnapshotAt: (isLivePacketUpdate || isStatusUpdate) ? currentNetworkHeaderData.lastSnapshotAt : Date.now(),
        latestTags: data.tags ? networkTagsFromContract(data) : currentNetworkHeaderData.latestTags,
    };
    updateNetworkWiresharkBranding(data);
    if (hasOsActiveConnectionCount && !networkStartupInstrumentation.headerCountAvailable) {
        networkStartupInstrumentation.headerCountAvailable = true;
        logNetworkStartup('header_count_available', {
            osActiveConnectionCount: currentNetworkHeaderData.osActiveConnectionCount,
            source: data.summary?.active_connection_source || 'macos_lsof',
        });
    }
}

function networkReasonState(reason, fallbackState = 'DEGRADED') {
    if (!reason) return '';
    return NETWORK_CRITICAL_REASONS.has(reason) ? 'CRITICAL' : normalizeNetworkState(fallbackState || 'DEGRADED');
}

function networkReasonPriority(reason, state = 'DEGRADED') {
    const normalizedState = normalizeNetworkState(state);
    const base = NETWORK_REASON_PRIORITIES[reason] || 0;
    return normalizedState === 'CRITICAL' ? Math.max(base, 90) : base;
}

function networkHeaderReasonEntry(reason, state, now = Date.now(), evidenceCount = 1) {
    const normalizedState = networkReasonState(reason, state);
    const normalizedReason = normalizeNetworkReason(reason, normalizedState);
    if (!normalizedReason) return null;
    return {
        reason: normalizedReason,
        state: normalizedState,
        priority: networkReasonPriority(normalizedReason, normalizedState),
        evidenceCount: Math.max(1, Number(evidenceCount) || 1),
        firstSeenAt: now,
        lastSeenAt: now,
    };
}

function mergeNetworkHeaderReasonEntries(entries = []) {
    const merged = new Map();
    entries.forEach(entry => {
        if (!entry?.reason) return;
        const state = networkReasonState(entry.reason, entry.state);
        const next = networkHeaderReasonEntry(entry.reason, state, entry.lastSeenAt || Date.now(), entry.evidenceCount || 1);
        if (!next) return;
        next.firstSeenAt = entry.firstSeenAt || next.firstSeenAt;
        next.lastSeenAt = entry.lastSeenAt || next.lastSeenAt;
        const existing = merged.get(next.reason);
        if (!existing) {
            merged.set(next.reason, next);
            return;
        }
        existing.state = existing.state === 'CRITICAL' || next.state === 'CRITICAL' ? 'CRITICAL' : 'DEGRADED';
        existing.priority = Math.max(existing.priority, next.priority);
        existing.evidenceCount += next.evidenceCount;
        existing.firstSeenAt = Math.min(existing.firstSeenAt || next.firstSeenAt, next.firstSeenAt);
        existing.lastSeenAt = Math.max(existing.lastSeenAt || next.lastSeenAt, next.lastSeenAt);
    });
    return Array.from(merged.values()).sort((a, b) => b.priority - a.priority || b.lastSeenAt - a.lastSeenAt || a.reason.localeCompare(b.reason));
}

function networkHeaderReasonsFromEvents(events = []) {
    const visibleEvents = Array.isArray(events) ? events : [];
    return mergeNetworkHeaderReasonEntries(visibleEvents.flatMap(event => {
        const reasons = [];
        const criticalReason = eventCriticalReason(event);
        if (criticalReason) reasons.push(networkHeaderReasonEntry(criticalReason, 'CRITICAL'));
        const degradedReason = eventDegradedReason(event);
        if (degradedReason) reasons.push(networkHeaderReasonEntry(degradedReason, 'DEGRADED'));
        return reasons.filter(Boolean);
    }));
}

function networkHeaderReasonFromEvents(events = []) {
    return networkHeaderReasonsFromEvents(events)[0] || null;
}

function networkHeaderReasonsFromTagsPayload(tags = {}) {
    const state = normalizeNetworkState(tags.state);
    if (!['DEGRADED', 'CRITICAL'].includes(state)) return [];
    const reasons = Array.isArray(tags.reasons) ? tags.reasons : [];
    return mergeNetworkHeaderReasonEntries(reasons.map(reason => networkHeaderReasonEntry(reason, state)).filter(Boolean));
}

function networkHeaderReasonFromTagsPayload(tags = {}) {
    return networkHeaderReasonsFromTagsPayload(tags)[0] || null;
}

function networkHeaderCandidateReasons(payload = {}) {
    const tags = networkTagsFromContract(payload);
    // Operational header reasons come only from the backend health contract.
    // Security posture is rendered separately from canonical assessments.
    return mergeNetworkHeaderReasonEntries(networkHeaderReasonsFromTagsPayload(tags));
}

function networkHeaderCandidateReason(payload = {}) {
    return networkHeaderCandidateReasons(payload)[0] || null;
}

function latchNetworkHeaderReasons(candidates = [], now = Date.now()) {
    const existing = Array.isArray(currentNetworkHeaderData.latchedReasons) ? currentNetworkHeaderData.latchedReasons : [];
    const next = mergeNetworkHeaderReasonEntries([
        ...existing,
        ...candidates.map(candidate => ({
            ...candidate,
            firstSeenAt: existing.find(item => item.reason === candidate.reason)?.firstSeenAt || now,
            lastSeenAt: now,
        })),
    ]);
    currentNetworkHeaderData.latchedReasons = next;
    const primary = next[0] || null;
    currentNetworkHeaderData.latchedReason = primary?.reason || '';
    currentNetworkHeaderData.latchedState = primary?.state || '';
    currentNetworkHeaderData.latchedPriority = primary?.priority || 0;
    currentNetworkHeaderData.latchedFirstSeenAt = primary?.firstSeenAt || 0;
    currentNetworkHeaderData.latchedLastSeenAt = primary?.lastSeenAt || 0;
}

function latchNetworkHeaderReason(candidate, now = Date.now()) {
    latchNetworkHeaderReasons(candidate ? [candidate] : [], now);
}

function clearNetworkHeaderReason(now = Date.now()) {
    currentNetworkHeaderData.latchedReason = '';
    currentNetworkHeaderData.latchedReasons = [];
    currentNetworkHeaderData.latchedState = '';
    currentNetworkHeaderData.latchedPriority = 0;
    currentNetworkHeaderData.latchedFirstSeenAt = 0;
    currentNetworkHeaderData.latchedLastSeenAt = 0;
    currentNetworkHeaderData.lastCleanSnapshotAt = now;
}

function clearResolvedNetworkCaptureReasons(payload = {}, now = Date.now()) {
    const tags = networkTagsFromContract(payload);
    const state = normalizeNetworkContractState(payload.state || currentNetworkHeaderData.state || 'NO_DATA');
    const summary = payload?.summary && typeof payload.summary === 'object' ? payload.summary : {};
    const captureReason = String(summary.capture_reason || summary.reason || '').trim().toLowerCase();
    const captureStillLimited = ['ERROR', 'CAPTURE_BLOCKED', 'WARMING'].includes(state) ||
        normalizeNetworkStatus(tags.status) === 'OFFLINE' ||
        ['capture_failed', 'capture_backlog', 'engine_unavailable', 'permission_blocked', 'waiting_for_capture'].includes(captureReason);
    if (captureStillLimited) return;
    const existing = Array.isArray(currentNetworkHeaderData.latchedReasons) ? currentNetworkHeaderData.latchedReasons : [];
    const retained = existing.filter(item => !NETWORK_CAPTURE_HEALTH_REASONS.has(String(item?.reason || '')));
    if (retained.length === existing.length) return;
    currentNetworkHeaderData.latchedReasons = retained;
    const primary = retained[0] || null;
    currentNetworkHeaderData.latchedReason = primary?.reason || '';
    currentNetworkHeaderData.latchedState = primary?.state || '';
    currentNetworkHeaderData.latchedPriority = primary?.priority || 0;
    currentNetworkHeaderData.latchedFirstSeenAt = primary?.firstSeenAt || 0;
    currentNetworkHeaderData.latchedLastSeenAt = primary?.lastSeenAt || 0;
    currentNetworkHeaderData.lastCleanSnapshotAt = now;
}

function setNetworkHeaderTags(tags = {}, options = {}) {
    currentNetworkHeaderData.latestTags = {
        status: normalizeNetworkStatus(tags.status),
        state: normalizeNetworkState(tags.state),
        reasons: Array.isArray(tags.reasons) ? tags.reasons : [],
        explanation: tags.explanation || '',
    };
    if (options.captureStatus) {
        currentNetworkHeaderData.captureAvailable = currentNetworkHeaderData.latestTags.status !== 'OFFLINE';
    }
}

function networkHeaderEvidenceIsCleanSnapshot(source, payload = {}, candidate = null) {
    if (!['snapshot', 'ready'].includes(source)) return false;
    if (candidate?.reason) return false;
    const tags = networkTagsFromContract(payload);
    const state = normalizeNetworkContractState(payload.state || currentNetworkHeaderData.state || 'NO_DATA');
    const tagState = normalizeNetworkState(tags.state);
    return !['ERROR', 'CAPTURE_BLOCKED'].includes(state) &&
        normalizeNetworkStatus(tags.status) !== 'OFFLINE' &&
        !['DEGRADED', 'CRITICAL'].includes(tagState);
}

function submitNetworkHeaderEvidence(source, payload = {}, options = {}) {
    const evidenceSource = String(source || 'unknown');
    const data = payload && typeof payload === 'object' ? payload : {};
    const now = Date.now();
    const candidates = networkHeaderCandidateReasons(data);
    currentNetworkHeaderData.evidenceBySource = {
        ...(currentNetworkHeaderData.evidenceBySource || {}),
        [evidenceSource]: {
            submittedAt: now,
            state: data.state || '',
            event_count: data.event_count ?? data.activeConnectionCount ?? (Array.isArray(data.events) ? data.events.length : 0),
            tags: data.tags || null,
            reasons: candidates.map(item => item.reason),
        },
    };
    if (!evidenceSource.startsWith('projection:')) {
        setNetworkHeaderData(data, options);
        setNetworkHeaderTags(networkTagsFromContract(data), options);
        if (options.captureStatus) clearResolvedNetworkCaptureReasons(data, now);
        if (options.packetAt) {
            currentNetworkHeaderData.lastPacketAt = options.packetAt;
        }
    }
    if (candidates.length) {
        latchNetworkHeaderReasons(candidates, now);
    } else if (networkHeaderEvidenceIsCleanSnapshot(evidenceSource, data, null)) {
        clearNetworkHeaderReason(now);
    }
    if (evidenceSource === 'live-packet') {
        if (options.establishedLiveEvidence) {
            flushNetworkHeaderRender({ force: true });
        } else {
            scheduleNetworkHeaderRender();
        }
        return;
    }
    flushNetworkHeaderRender({ force: true });
}

function networkHeaderTableData() {
    return {
        state: currentNetworkHeaderData.state || 'NO_DATA',
        events: Array.isArray(currentNetworkHeaderData.events) ? currentNetworkHeaderData.events : [],
        event_count: currentNetworkHeaderData.displayedConnectionCount || currentNetworkHeaderData.activeConnectionCount || 0,
        total_connection_count: currentNetworkHeaderData.totalConnectionCount || 0,
        displayed_connection_count: currentNetworkHeaderData.displayedConnectionCount || 0,
        displayed_connection_count_capped: Boolean(currentNetworkHeaderData.displayedConnectionCountCapped),
        summary: currentNetworkHeaderData.summary || {},
        assessments: Array.isArray(currentNetworkHeaderData.assessments) ? currentNetworkHeaderData.assessments : [],
        assessment_refs: Array.isArray(currentNetworkHeaderData.assessmentRefs) ? currentNetworkHeaderData.assessmentRefs : [],
        assessment_summary: currentNetworkHeaderData.assessmentSummary,
        assessment_filter: currentNetworkHeaderData.assessmentFilter,
        tags: currentNetworkTags,
    };
}

function networkCoordinatorSnapshotTableData() {
    const snapshot = ensureNetworkCoordinatorState().snapshot?.data;
    return snapshot ? cloneNetworkProjectionData(snapshot) : networkHeaderTableData();
}

function networkHeaderReasonFromTags(tags, state) {
    if (!tags || !['DEGRADED', 'CRITICAL'].includes(state)) return '';
    const reasons = Array.isArray(tags.reasons) ? tags.reasons : [];
    return reasons.map(item => normalizeNetworkReason(item, state)).find(Boolean) || '';
}

function classifyNetworkHeader() {
    const now = Date.now();
    const events = Array.isArray(currentNetworkHeaderData.events) ? currentNetworkHeaderData.events : [];
    const count = networkHeaderCurrentCount(now);
    const activeSocketCount = Number(currentNetworkHeaderData.activeSocketCount || 0);
    const state = normalizeNetworkContractState(currentNetworkHeaderData.state || 'NO_DATA');
    const tags = currentNetworkHeaderData.latestTags || {};
    const tagState = normalizeNetworkState(tags.state);
    const silenceMs = currentNetworkHeaderData.lastPacketAt ? now - currentNetworkHeaderData.lastPacketAt : Infinity;
    const hasRecentPacket = Number.isFinite(silenceMs) && silenceMs < NETWORK_LIVE_QUIET_MS;
    const collectorListening = state === 'READY' && normalizeNetworkStatus(tags.status) === 'OBSERVING';
    const hasActiveEvidence = activeSocketCount > 0 || hasRecentPacket || collectorListening;
    const captureUnavailable = !currentNetworkHeaderData.captureAvailable || ['ERROR', 'CAPTURE_BLOCKED'].includes(state) || normalizeNetworkStatus(tags.status) === 'OFFLINE';
    const activeReasons = networkHeaderCandidateReasons(currentNetworkHeaderData);
    const latchedReasons = Array.isArray(currentNetworkHeaderData.latchedReasons) ? currentNetworkHeaderData.latchedReasons : [];
    const visibleReasons = mergeNetworkHeaderReasonEntries(latchedReasons.length ? latchedReasons : activeReasons);
    if (captureUnavailable) {
        const offlineReasons = visibleReasons.length ? visibleReasons.map(item => item.reason) : ['Capture engine limited'];
        return { status: 'OFFLINE', state: 'DEGRADED', reasons: offlineReasons, explanation: offlineReasons[0] };
    }
    let headerState = 'HEALTHY';
    let reasons = [];
    if (visibleReasons.length) {
        headerState = visibleReasons.some(item => item.state === 'CRITICAL') ? 'CRITICAL' : 'DEGRADED';
        reasons = visibleReasons.map(item => item.reason);
    } else if (tagState === 'UNKNOWN') {
        headerState = 'UNKNOWN';
    }
    let status = 'QUIET';
    if (hasActiveEvidence) {
        status = 'OBSERVING';
    }
    if (headerState === 'HEALTHY') reasons = [];
    return { status, state: headerState, reasons, explanation: reasons[0] || status.toLowerCase() };
}

function networkShouldSuspendDomWork() {
    networkRenderSuspended = Boolean(document.hidden);
    return networkRenderSuspended;
}

function markNetworkDeferredRender(flag = 'display', options = {}) {
    if (Object.prototype.hasOwnProperty.call(networkDeferredRenderFlags, flag)) {
        networkDeferredRenderFlags[flag] = true;
    }
    if (options.hydrate !== false) {
        networkVisibilityPendingHydration = true;
    }
}

function clearNetworkDeferredRenderFlags() {
    Object.keys(networkDeferredRenderFlags).forEach(flag => {
        networkDeferredRenderFlags[flag] = false;
    });
}

function networkHasDeferredRenderWork() {
    return Object.values(networkDeferredRenderFlags).some(Boolean) ||
        networkHeaderRenderPending ||
        networkTableUiBuffer.length > 0 ||
        networkTrendLiveDirty;
}

function clearNetworkForegroundRecoveryTimer() {
    if (networkForegroundRecoveryTimer === null) return;
    window.clearTimeout(networkForegroundRecoveryTimer);
    networkForegroundRecoveryTimer = null;
}

function suspendNetworkRenderWork() {
    if (!networkShouldSuspendDomWork()) return false;
    clearNetworkForegroundRecoveryTimer();
    clearNetworkTableFlushTimer();
    clearNetworkHeaderRenderTimer();
    clearActionSidebarRenderSchedule();
    clearActionSidebarDeferredDetails();
    return true;
}

function resumeNetworkForegroundRendering(reason = 'resume') {
    clearNetworkForegroundRecoveryTimer();
    const wasSuspended = networkRenderSuspended || Boolean(networkDocumentHiddenAt);
    networkWindowBackgrounded = false;
    networkRenderSuspended = false;
    if (networkShouldSuspendDomWork()) return false;
    if (byId('network')?.hidden) {
        if (wasSuspended || networkHasDeferredRenderWork()) {
            networkVisibilityPendingHydration = true;
        }
        return false;
    }
    const hadDeferredWork = networkHasDeferredRenderWork();
    networkDocumentHiddenAt = 0;
    networkTableHiddenPacketCount = 0;
    clearNetworkDeferredRenderFlags();
    if (wasSuspended || hadDeferredWork || networkVisibilityPendingHydration) {
        networkVisibilityPendingHydration = false;
        resumeNetworkViewHydration(reason).catch(reportFrontendDegraded);
        return true;
    }
    return false;
}

function scheduleNetworkForegroundRendering(reason = 'resume') {
    if (networkShouldSuspendDomWork()) return false;
    if (networkForegroundRecoveryTimer !== null) return true;
    networkForegroundRecoveryTimer = window.setTimeout(() => {
        networkForegroundRecoveryTimer = null;
        resumeNetworkForegroundRendering(reason);
    }, 0);
    return true;
}

function renderNetworkHeader() {
    if (renderConsentRequired()) return;
    applyNetworkTags(classifyNetworkHeader());
    renderNetworkPostureSummary();
}

function renderNetworkPostureSummary() {
    const summary = currentNetworkHeaderData.assessmentSummary;
    const counts = summary && typeof summary.counts === 'object' ? summary.counts : {};
    ['threats', 'vulnerabilities', 'strengths'].forEach(category => {
        const element = document.querySelector('[data-network-posture="' + category + '"]');
        if (!element) return;
        const value = Number(counts[category]);
        const count = Number.isFinite(value) ? String(Math.max(0, Math.round(value))) : '—';
        const label = category.charAt(0).toUpperCase() + category.slice(1);
        element.textContent = count + ' ' + label;
        element.dataset.count = String(count);
    });
}

function clearNetworkHeaderRenderTimer() {
    if (!networkHeaderRenderTimer) return;
    window.clearTimeout(networkHeaderRenderTimer);
    networkHeaderRenderTimer = null;
}

function flushNetworkHeaderRender(options = {}) {
    if (networkShouldSuspendDomWork()) {
        networkHeaderRenderPending = true;
        markNetworkDeferredRender('header');
        return false;
    }
    clearNetworkHeaderRenderTimer();
    networkHeaderRenderPending = false;
    renderNetworkHeader();
    refreshNetworkTimelineDisplayIfVisible();
    return true;
}

function scheduleNetworkHeaderRender() {
    networkHeaderRenderPending = true;
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('header');
        return;
    }
    if (networkHeaderRenderTimer) return;
    networkHeaderRenderTimer = window.setTimeout(() => {
        networkHeaderRenderTimer = null;
        flushNetworkHeaderRender();
    }, NETWORK_HEADER_FLUSH_MS);
}

function classifyNetworkTags(events = [], options = {}) {
    const streamTags = options.streamTags || null;
    const networkState = normalizeNetworkContractState(options.networkState || currentNetworkData?.state || (events.length ? 'CAPTURING' : 'NO_DATA'));
    const visibleEvents = Array.isArray(events) ? events : [];
    const externalEvents = visibleEvents.filter(networkEventIsExternal);
    const onlyLocal = visibleEvents.length > 0 && externalEvents.length === 0;
    const unnamedExternal = externalEvents.some(event => !networkEventHasReadableDestination(event));
    const criticalReason = visibleEvents.map(eventCriticalReason).find(Boolean);
    const degradedEventReasons = visibleEvents.map(eventDegradedReason).filter(Boolean);
    const reasons = [];
    let status = visibleEvents.length ? (onlyLocal ? 'LOCAL ONLY' : 'OBSERVING') : (networkState === 'ERROR' ? 'OFFLINE' : 'QUIET');
    let state = networkState === 'ERROR' ? 'DEGRADED' : 'HEALTHY';
    let explanation = state.toLowerCase();

    if (options.forceQuiet && state !== 'DEGRADED') {
        status = 'QUIET';
    }
    if (onlyLocal) {
        explanation = 'local only';
    }
    if (unnamedExternal) {
        state = 'DEGRADED';
        explanation = 'Destination name missing';
    }
    if (visibleEvents.length >= 150) {
        state = 'DEGRADED';
        reasons.push('High connection volume');
        explanation = 'High connection volume';
    }
    reasons.push(...degradedEventReasons);
    if (criticalReason) {
        state = 'CRITICAL';
        reasons.push(criticalReason);
        explanation = criticalReason;
    } else if (reasons.length) {
        state = 'DEGRADED';
        explanation = reasons[0];
    }
    if (streamTags) {
        status = normalizeNetworkStatus(streamTags.status || status);
        const incomingState = normalizeNetworkState(streamTags.state || state);
        state = incomingState;
        if (Array.isArray(streamTags.reasons)) reasons.push(...streamTags.reasons);
        if (streamTags.explanation) explanation = streamTags.explanation;
    }

    if (!['DEGRADED', 'CRITICAL'].includes(state)) reasons.length = 0;
    const reason = reasons.map(item => normalizeNetworkReason(item, state)).find(Boolean);
    return { status, state, reasons: reason ? [reason] : [], explanation };
}

function applyNetworkTags(tags = {}) {
    if (renderConsentRequired()) return;
    const status = normalizeNetworkStatus(tags.status);
    const state = normalizeNetworkState(tags.state);
    const reasons = Array.isArray(tags.reasons)
        ? Array.from(new Set(tags.reasons.map(item => normalizeNetworkReason(item, state)).filter(Boolean)))
        : [];
    if (!['DEGRADED', 'CRITICAL'].includes(state)) reasons.length = 0;
    const reason = reasons[0] || '';
    currentNetworkTags = { status, state, reasons, explanation: tags.explanation || '' };
    const statusTag = byId('network-status-tag');
    const stateTag = byId('network-state-tag');
    const reasonTags = byId('network-reason-tags');
    const actionSummary = byId('network-action-summary');
    if (statusTag) {
        statusTag.textContent = status;
        statusTag.dataset.status = status.toLowerCase().replace(/\s+/g, '-');
    }
    if (stateTag) {
        stateTag.textContent = state;
        stateTag.dataset.state = state.toLowerCase();
    }
    if (reasonTags) {
        reasonTags.hidden = !reasons.length;
        reasonTags.innerHTML = reasons.map(item => (
            '<button class="network-status-pill network-reason-pill" type="button" data-network-reason="' + escapeHtml(item) + '" data-state="' + escapeHtml(state.toLowerCase()) + '">' +
            escapeHtml(item) +
            '</button>'
        )).join('');
        reasonTags.querySelectorAll('[data-network-reason]').forEach(button => {
            button.addEventListener('click', () => focusNetworkActionDigest(button.dataset.networkReason || ''));
        });
    }
    if (actionSummary) {
        actionSummary.hidden = !reason || !['DEGRADED', 'CRITICAL'].includes(state);
        actionSummary.textContent = reasons.length > 1
            ? reasons.map(item => networkActionSummary(item, state)).join(' • ')
            : (reason ? networkActionSummary(reason, state) : '');
    }
    setNetworkConnectionCount();
    renderNetworkActionDigest();
}

function networkReasonCopy(reason, state = 'ERROR') {
    const fallback = {
        title: reason || 'error',
        meaning: reason || 'error',
        summary: reason || 'error',
        primary: 'Retry capture',
        secondary: 'Open raw metadata',
    };
    const copy = {
        permission_blocked: { meaning: 'permission_blocked', summary: 'permission_blocked' },
        capture_failed: { title: 'Capture failed', meaning: 'Capture failed', summary: 'Capture failed' },
        capture_backlog: { title: 'Capture delayed', meaning: 'Captured evidence is delayed while the bounded ingestion pipeline catches up.', summary: 'Capture engine limited' },
        timeout: { meaning: 'timeout', summary: 'timeout' },
        engine_unavailable: { meaning: 'engine_unavailable', summary: 'engine_unavailable' },
        'Permission blocks capture': { meaning: 'Packet capture is blocked by system permissions.', summary: 'Permission blocks capture' },
        'Capture engine limited': { meaning: 'CleanHouse could not fully capture network history.', summary: 'Capture engine limited' },
        'Capture failed': { meaning: 'CleanHouse could not fully capture network history.', summary: 'Capture failed' },
        'Connection attempts failed': { meaning: 'Some network connection attempts failed or timed out.', summary: 'Connection attempts failed' },
        'Destination name missing': { meaning: 'CleanHouse saw external traffic without a readable destination name.', summary: 'Destination name missing' },
        'Restarting': { meaning: 'CleanHouse is waiting for network capture to warm back up after restart.', summary: 'Restarting' },
        'Unknown app active': { meaning: 'CleanHouse could not identify the app or service behind external traffic.', summary: 'Unknown app active' },
    };
    return { ...fallback, ...(copy[reason] || {}) };
}

function networkActionSummary(reason, state) {
    return networkReasonCopy(reason, state).summary;
}

function networkReasonPrimaryAction(reason) {
    return 'reconnect';
}

function networkReasonMatchesEvent(reason, event) {
    if (!reason || !event) return false;
    return eventDegradedReason(event) === reason || eventCriticalReason(event) === reason;
}

function networkAffectedEvents(reason, events = []) {
    const visibleEvents = Array.isArray(events) ? events : [];
    if (!reason) return [];
    return visibleEvents.filter(event => networkReasonMatchesEvent(reason, event));
}

function networkEvidenceEntityId(event = {}) {
    if (!event || typeof event !== 'object') return '';
    if (typeof event.connection_id === 'string' && event.connection_id.trim()) return event.connection_id.trim();
    const refCandidates = [
        event.event_id,
        event.id,
        event.raw_evidence_ref,
        event.path,
        ...(Array.isArray(event.evidence_refs) ? event.evidence_refs : []),
    ];
    for (const candidate of refCandidates) {
        if (typeof candidate === 'string') {
            const normalized = candidate.trim();
            if (normalized) return normalized;
        }
    }
    return '';
}

function networkEvidenceRelatedIds(event = {}) {
    if (!event || typeof event !== 'object') return [];
    const related = [
        event.source_event_id,
        event.timeline_event_id,
        ...(Array.isArray(event.related_event_ids) ? event.related_event_ids : []),
        ...(Array.isArray(event.evidence_refs) ? event.evidence_refs : []),
    ];
    return related.map(value => String(value || '').trim()).filter(Boolean);
}

function resolveNetworkAssessment(context = {}) {
    const targets = [
        context.source_entity_id,
        context.assessment_id,
        ...(Array.isArray(context.assessment_refs) ? context.assessment_refs : []),
        ...(Array.isArray(context.evidence_refs) ? context.evidence_refs : []),
    ].map(value => String(value || '').trim()).filter(Boolean);
    if (!targets.length) return null;
    const candidates = [];
    [currentNetworkProjectionData, currentNetworkData, currentNetworkTableData, currentNetworkHeaderData].forEach(data => {
        if (!data || !Array.isArray(data.assessments)) return;
        data.assessments.forEach(assessment => {
            if (assessment && typeof assessment === 'object') candidates.push(assessment);
        });
    });
    return candidates.find(assessment => {
        const values = [
            assessment.assessment_id,
            assessment.assessment_key,
            ...(Array.isArray(assessment.evidence_refs) ? assessment.evidence_refs : []),
        ].map(value => String(value || '').trim()).filter(Boolean);
        return targets.some(target => values.includes(target));
    }) || null;
}

function networkEvidenceRef(event = {}) {
    if (event && typeof event.raw_evidence_ref === 'string' && event.raw_evidence_ref.trim()) {
        return event.raw_evidence_ref.trim();
    }
    const id = networkEvidenceEntityId(event);
    return id && id.startsWith('local://') ? id : '';
}

function evidenceActionDescriptorFromRow(row) {
    if (!row) return null;
    const relatedIds = String(row.dataset.evidenceRelatedIds || '')
        .split('|')
        .map(value => value.trim())
        .filter(Boolean);
    const assessmentRefs = String(row.dataset.assessmentIds || '')
        .split('|')
        .map(value => value.trim())
        .filter(Boolean);
    return {
        surface: row.dataset.evidenceSurface || 'network',
        entityId: row.dataset.evidenceEntityId || '',
        sourceView: row.dataset.evidenceSourceView || 'table',
        ref: row.dataset.evidenceRef || '',
        relatedIds,
        assessmentRefs,
        owner: row.dataset.evidenceOwner || '',
        destination: row.dataset.evidenceDestination || '',
    };
}

function evidenceAttributes({ surface = 'network', entityId = '', ref = '', sourceView = 'table' } = {}) {
    return (
        ' data-evidence-surface="' + escapeHtml(surface || 'network') + '"' +
        ' data-evidence-entity-id="' + escapeHtml(entityId || '') + '"' +
        ' data-evidence-ref="' + escapeHtml(ref || '') + '"' +
        ' data-evidence-source-view="' + escapeHtml(sourceView || 'table') + '"'
    );
}

function networkEvidenceAttributes(event, sourceView = networkViewMode || 'table') {
    const related = networkEvidenceRelatedIds(event);
    const assessmentRefs = Array.isArray(event?.assessment_refs)
        ? event.assessment_refs.map(value => String(value || '').trim()).filter(Boolean)
        : [];
    const attrs = evidenceAttributes({
        surface: 'network',
        entityId: networkEvidenceEntityId(event),
        ref: networkEvidenceRef(event),
        sourceView: sourceView || 'table',
    });
    const owner = networkEventAppName(event);
    const destination = networkEventDestination(event);
    return attrs +
        (related.length ? ' data-evidence-related-ids="' + escapeHtml(related.join('|')) + '"' : '') +
        (assessmentRefs.length ? ' data-assessment-ids="' + escapeHtml(assessmentRefs.join('|')) + '"' : '') +
        (owner ? ' data-evidence-owner="' + escapeHtml(owner) + '"' : '') +
        (destination ? ' data-evidence-destination="' + escapeHtml(destination) + '"' : '');
}

function networkConnectionIdentityFields(event = {}) {
    const app = networkEventAppName(event) || 'Unknown app';
    const source = networkEventSource(event) || 'Unknown source';
    const destination = networkEventDestination(event) || 'Unknown destination';
    const protocol = String(event?.protocol || 'Network connection').trim() || 'Network connection';
    const port = String(event?.dst_port || event?.port || '').trim() || 'Unavailable';
    return { app, source, destination, protocol, port };
}

function networkConnectionIdentityKey(event = {}) {
    const fields = networkConnectionIdentityFields(event);
    return [fields.app, fields.source, fields.destination, fields.protocol, fields.port]
        .map(value => String(value || '').trim().toLowerCase())
        .join('|');
}

function networkConnectionEntityId(event = {}) {
    const key = networkConnectionIdentityKey(event);
    if (!key || key === 'unknown app|unknown source|unknown destination|network connection|unavailable') {
        return networkEvidenceEntityId(event);
    }
    return 'connection:' + encodeURIComponent(key);
}

function networkEventTimestampMs(event = {}) {
    const timestamp = event?.last_seen || event?.timestamp || event?.time;
    const ms = timestamp ? Date.parse(timestamp) : NaN;
    return Number.isFinite(ms) ? ms : 0;
}

function networkRawPacketSnapshot(event = {}) {
    return {
        event_id: event.event_id || event.id || '',
        timestamp: event.timestamp || event.time || '',
        app: networkEventAppName(event),
        source: networkEventSource(event),
        destination: networkEventDestination(event),
        protocol: event.protocol || 'Network connection',
        port: event.dst_port || event.port || 'Unavailable',
        pid: event.pid || '',
        socket_state: event.socket_state || '',
        socket_role: event.socket_role || '',
        packet_index: event.packet_index ?? null,
        packet_length: event.packet_length ?? null,
        raw_evidence_ref: event.raw_evidence_ref || '',
    };
}

function networkMergeConnectionEvent(existing = null, event = {}) {
    const base = existing && typeof existing === 'object' ? existing : null;
    const fields = networkConnectionIdentityFields(event);
    const connectionId = networkConnectionEntityId(event);
    const nowTimestamp = event.timestamp || event.time || new Date(networkLiveLastEventAt || Date.now()).toISOString();
    const previousRaw = Array.isArray(base?.raw_packet_events) ? base.raw_packet_events : [];
    const rawPacket = networkRawPacketSnapshot(event);
    const rawPacketKey = [
        rawPacket.event_id,
        rawPacket.timestamp,
        rawPacket.source,
        rawPacket.destination,
        rawPacket.packet_index,
    ].map(value => String(value ?? '')).join('|');
    let rawPacketAlreadyPresent = false;
    const nextRaw = previousRaw.filter(packet => {
        const key = [
            packet.event_id,
            packet.timestamp,
            packet.source,
            packet.destination,
            packet.packet_index,
        ].map(value => String(value ?? '')).join('|');
        if (key === rawPacketKey) rawPacketAlreadyPresent = true;
        return key !== rawPacketKey;
    });
    nextRaw.push(rawPacket);
    const boundedRaw = nextRaw.slice(-30);
    const relatedIds = [
        ...(Array.isArray(base?.related_event_ids) ? base.related_event_ids : []),
        ...(Array.isArray(event.related_event_ids) ? event.related_event_ids : []),
        base?.source_event_id,
        event.source_event_id,
        event.event_id,
        event.id,
    ].map(value => String(value || '').trim()).filter(Boolean);
    const evidenceRefs = [
        ...(Array.isArray(base?.evidence_refs) ? base.evidence_refs : []),
        ...(Array.isArray(event.evidence_refs) ? event.evidence_refs : []),
        base?.raw_evidence_ref,
        event.raw_evidence_ref,
    ].map(value => String(value || '').trim()).filter(Boolean);
    const assessmentRefs = Array.from(new Set([
        ...(Array.isArray(base?.assessment_refs) ? base.assessment_refs : []),
        ...(Array.isArray(event.assessment_refs) ? event.assessment_refs : []),
    ].map(value => String(value || '').trim()).filter(Boolean))).slice(0, 32);
    const firstSeen = base?.first_seen || base?.timestamp || event.first_seen || nowTimestamp;
    const latest = !base || networkEventTimestampMs(event) >= networkEventTimestampMs(base) ? event : base;
    return {
        ...(base || {}),
        ...latest,
        connection_id: connectionId,
        event_id: connectionId,
        id: connectionId,
        source_event_id: event.event_id || event.id || base?.source_event_id || '',
        process: fields.app,
        source_display: fields.source,
        destination_display: fields.destination,
        protocol: fields.protocol,
        dst_port: fields.port === 'Unavailable' ? '' : fields.port,
        first_seen: firstSeen,
        last_seen: nowTimestamp,
        timestamp: nowTimestamp,
        packet_count: Number(base?.packet_count || 0) + (rawPacketAlreadyPresent ? 0 : 1),
        raw_packet_events: boundedRaw,
        related_event_ids: Array.from(new Set(relatedIds)),
        evidence_refs: Array.from(new Set(evidenceRefs)),
        assessment_refs: assessmentRefs,
        summary: event.summary || base?.summary || `${fields.app} -> ${fields.destination}`,
    };
}

function networkDedupedConnectionRows(events = []) {
    const rowsByKey = new Map();
    (Array.isArray(events) ? events : []).forEach(event => {
        if (!event || typeof event !== 'object') return;
        const key = networkConnectionIdentityKey(event) || networkEvidenceEntityId(event);
        if (!key) return;
        rowsByKey.set(key, networkMergeConnectionEvent(rowsByKey.get(key), event));
    });
    return Array.from(rowsByKey.values()).sort((left, right) => networkEventTimestampMs(right) - networkEventTimestampMs(left));
}

function networkTableDataFromEvents(data = {}, events = []) {
    const observedAt = Date.now();
    const rows = networkDedupedConnectionRows(events).map(event => ({
        ...event,
        __networkLiveObservedAt: observedAt,
    }));
    const summary = data.summary && typeof data.summary === 'object' ? { ...data.summary } : {};
    summary.counts = { ...(summary.counts || {}), connections: rows.length };
    return {
        ...(data || {}),
        events: rows,
        event_count: rows.length,
        activeConnectionCount: rows.length,
        total_connection_count: rows.length,
        displayed_connection_count: rows.length,
        summary,
    };
}

function reconcileNetworkInventoryFromSnapshot(inventory = null, data = {}, events = []) {
    const existingRows = Array.isArray(inventory?.events) ? inventory.events.slice() : [];
    const rowsByKey = new Map(existingRows.map(event => [networkConnectionIdentityKey(event), event]));
    const observedAt = Date.now();
    (Array.isArray(events) ? events : []).forEach(event => {
        if (!event || typeof event !== 'object') return;
        const key = networkConnectionIdentityKey(event);
        if (!key) return;
        rowsByKey.set(key, {
            ...networkMergeConnectionEvent(rowsByKey.get(key), event),
            __networkLiveObservedAt: observedAt,
        });
    });
    const rows = Array.from(rowsByKey.values())
        .sort((left, right) => networkEventTimestampMs(right) - networkEventTimestampMs(left))
        .slice(0, NETWORK_LIVE_EVENT_LIMIT);
    const summary = data.summary && typeof data.summary === 'object' ? { ...data.summary } : {};
    summary.counts = { ...(summary.counts || {}), connections: rows.length };
    return {
        ...(inventory || {}),
        ...(data || {}),
        events: rows,
        event_count: rows.length,
        activeConnectionCount: rows.length,
        total_connection_count: rows.length,
        displayed_connection_count: rows.length,
        summary,
    };
}

function networkDistributionEvidenceAttributes(label, owner = {}) {
    const normalizedOwner = String(label || owner.name || '').trim() || 'Unknown app';
    const refs = Array.from(new Set(
        (Array.isArray(owner.evidence_refs) ? owner.evidence_refs : [])
            .map(value => String(value || '').trim()).filter(Boolean),
    )).slice(0, 32);
    const assessmentRefs = Array.from(new Set(
        (Array.isArray(owner.assessment_refs) ? owner.assessment_refs : [])
            .map(value => String(value || '').trim()).filter(Boolean),
    )).slice(0, 32);
    const ownerId = String(owner.owner_id || '').trim() || 'distribution:' + normalizedOwner;
    return evidenceAttributes({
        surface: 'network',
        entityId: ownerId,
        ref: '',
        sourceView: 'distribution',
    }) +
        (refs.length ? ' data-evidence-related-ids="' + escapeHtml(refs.join('|')) + '"' : '') +
        (assessmentRefs.length ? ' data-assessment-ids="' + escapeHtml(assessmentRefs.join('|')) + '"' : '') +
        ' data-evidence-owner="' + escapeHtml(normalizedOwner) + '"';
}

function cloneNetworkPinnedTableRow(event = {}, options = {}) {
    if (!event || typeof event !== 'object') return null;
    const clone = { ...event };
    if (options.stale) clone.__networkPinnedStale = true;
    else delete clone.__networkPinnedStale;
    return clone;
}

function findNetworkTableEventByEntityId(entityId = '', events = null) {
    const normalizedEntityId = String(entityId || '').trim();
    if (!normalizedEntityId) return null;
    const candidateEvents = Array.isArray(events)
        ? events
        : [
            ...(Array.isArray(currentNetworkTableData?.events) ? currentNetworkTableData.events : []),
            ...(Array.isArray(currentNetworkData?.events) ? currentNetworkData.events : []),
        ];
    return candidateEvents.find(event => networkEvidenceEntityId(event) === normalizedEntityId) || null;
}

function setPinnedNetworkTableSelection(entityId = '', event = null) {
    const normalizedEntityId = String(entityId || '').trim();
    networkTablePinnedEntityId = normalizedEntityId;
    if (!normalizedEntityId) {
        networkTablePinnedRowSnapshot = null;
        return;
    }
    const liveEvent = event && typeof event === 'object'
        ? event
        : findNetworkTableEventByEntityId(normalizedEntityId);
    networkTablePinnedRowSnapshot = liveEvent
        ? cloneNetworkPinnedTableRow(liveEvent)
        : cloneNetworkPinnedTableRow(networkTablePinnedRowSnapshot, { stale: true });
}

function syncNetworkTablePinnedSnapshot(events = null) {
    const pinnedEntityId = String(networkTablePinnedEntityId || '').trim();
    if (!pinnedEntityId) {
        networkTablePinnedRowSnapshot = null;
        return null;
    }
    const liveEvent = findNetworkTableEventByEntityId(pinnedEntityId, events);
    if (liveEvent) {
        const lastSeenAt = Number(liveEvent.__networkLiveObservedAt || 0) || networkEventTimestampMs(liveEvent);
        const inactive = Boolean(lastSeenAt && Date.now() - lastSeenAt > NETWORK_LIVE_QUIET_MS);
        networkTablePinnedRowSnapshot = cloneNetworkPinnedTableRow(liveEvent, { stale: inactive });
        return networkTablePinnedRowSnapshot;
    }
    if (networkTablePinnedRowSnapshot && networkEvidenceEntityId(networkTablePinnedRowSnapshot) === pinnedEntityId) {
        networkTablePinnedRowSnapshot = cloneNetworkPinnedTableRow(networkTablePinnedRowSnapshot, { stale: true });
        return networkTablePinnedRowSnapshot;
    }
    return null;
}

function openEvidenceActions({ surface = '', entityId = '', sourceView = 'table', ref = '', relatedIds = [], assessmentRefs = [], owner = '', destination = '' } = {}) {
    const normalizedSurface = String(surface || 'network').trim() || 'network';
    const normalizedEntityId = String(entityId || '').trim();
    const normalizedRef = String(ref || '').trim();
    const normalizedSourceView = String(sourceView || '').trim() || 'table';
    const params = {
        surface: normalizedSurface,
        entityId: normalizedEntityId,
        sourceView: normalizedSourceView,
        ref: normalizedRef,
        owner: String(owner || '').trim(),
        destination: String(destination || '').trim(),
    };
    const boundedRelatedIds = Array.from(new Set(
        (Array.isArray(relatedIds) ? relatedIds : [])
            .map(value => String(value || '').trim())
            .filter(Boolean),
    )).slice(0, 32);
    const boundedAssessmentRefs = Array.from(new Set(
        (Array.isArray(assessmentRefs) ? assessmentRefs : [])
            .map(value => String(value || '').trim())
            .filter(Boolean),
    )).slice(0, 32);
    const selectionKey = [
        params.surface,
        params.entityId,
        params.sourceView,
        params.ref,
        boundedRelatedIds.join(','),
        boundedAssessmentRefs.join(','),
    ].join('|');
    if (!normalizedRef && !normalizedEntityId) {
        actionSidebarRequestEpoch += 1;
        evidenceInsightRequestEpoch += 1;
        evidenceActionRequestEpoch += 1;
        evidenceCommandError = 'No evidence identifier was provided for this selection.';
        setCurrentEvidenceCommandSnapshot(null);
        evidenceInsightLoading = false;
        evidenceInsightError = '';
        evidenceInsightRequestKey = '';
        evidenceAutoInsightSelectionKey = '';
        evidenceCommandSelectionKey = '';
        resetActionSidebarDeferredDetails();
        actionSidebarPage = 'evidence';
        setActionSidebarOpen(true);
        return;
    }
    if (!evidenceCommandLoading && evidenceCommandSelectionKey === selectionKey && (evidenceCommandContext || evidenceCommandError)) {
        if (evidenceCommandSnapshot && evidenceCommandSnapshot.version !== actionSidebarRequestEpoch) {
            updateCurrentEvidenceCommandSnapshot({ version: actionSidebarRequestEpoch });
        }
        actionSidebarPage = 'evidence';
        setActionSidebarOpen(true);
        maybeRequestCtrlInsightForSelection(evidenceCommandContext);
        return;
    }
    const requestEpoch = ++actionSidebarRequestEpoch;
    evidenceInsightRequestEpoch += 1;
    evidenceActionRequestEpoch += 1;
    if (normalizedSurface === 'network' && normalizedSourceView === 'table' && normalizedEntityId) {
        setPinnedNetworkTableSelection(normalizedEntityId, findNetworkTableEventByEntityId(normalizedEntityId));
        if (networkViewMode === 'table') {
            flushNetworkTableRender({ force: true });
        }
    }
    evidenceCommandLoading = true;
    evidenceCommandSelectionKey = selectionKey;
    setCurrentEvidenceCommandSnapshot(null);
    evidenceCommandError = '';
    evidenceInsightLoading = false;
    evidenceInsightError = '';
    evidenceInsightRequestKey = '';
    actionSidebarDeferredRenderRequestId = requestEpoch;
    resetActionSidebarDeferredDetails();
    actionSidebarPage = 'evidence';
    setActionSidebarOpen(true);
    networkCtrlRouteTarget = buildNetworkCtrlRouteTarget({}, params);
    window.CleanHouseAPI.getEvidenceActions(params)
        .then(result => {
            if (requestEpoch !== actionSidebarRequestEpoch) return;
            if (!result || result.status !== 'ok' || !result.context) {
                throw new Error(result?.message || 'Unable to resolve evidence context.');
            }
            const context = {
                ...result.context,
                ...(normalizedSurface === 'network' && params.owner
                    ? { app_name: params.owner }
                    : {}),
                ...(normalizedSurface === 'network' && params.destination
                    ? { destination: params.destination }
                    : {}),
                evidence_refs: Array.from(new Set([
                    ...(Array.isArray(result.context.evidence_refs) ? result.context.evidence_refs : []),
                    ...boundedRelatedIds,
                ])).slice(0, 32),
                assessment_refs: Array.from(new Set([
                    ...(Array.isArray(result.context.assessment_refs) ? result.context.assessment_refs : []),
                    ...boundedAssessmentRefs,
                ])).slice(0, 32),
            };
            const nextSnapshot = buildEvidenceCommandSnapshot(context, {
                descriptor: { ...params, relatedIds: boundedRelatedIds, assessmentRefs: boundedAssessmentRefs },
                version: requestEpoch,
                selectionKey,
                actions: Array.isArray(result.actions) ? result.actions : [],
            });
            setCurrentEvidenceCommandSnapshot(nextSnapshot);
            networkCtrlRouteTarget = nextSnapshot.routeTarget;
        })
        .catch(error => {
            if (requestEpoch !== actionSidebarRequestEpoch) return;
            setCurrentEvidenceCommandSnapshot(null);
            resetActionSidebarDeferredDetails();
            evidenceCommandError = `Cannot open actions for ${normalizedSurface}/${normalizedEntityId || normalizedRef}. ${error?.message || error}`;
        })
        .finally(() => {
            if (requestEpoch !== actionSidebarRequestEpoch) return;
            evidenceCommandLoading = false;
            maybeRequestCtrlInsightForSelection(evidenceCommandContext);
            scheduleActionSidebarRender();
        });
}

function clearPinnedNetworkTableSelection() {
    if (!networkTablePinnedEntityId && !networkTablePinnedRowSnapshot) return;
    setPinnedNetworkTableSelection('');
    if (networkViewMode !== 'table') return;
    flushNetworkTableRender({ force: true });
}

function handleNetworkTablePinnedOutsideClick(event) {
    if (networkViewMode !== 'table' || !networkTablePinnedEntityId) return;
    const target = event?.target;
    if (!target || !(target instanceof Element)) return;
    const network = byId('network');
    if (!network || network.hidden) return;
    if (target.closest('#action-sidebar') || target.closest('#action-sidebar-toggle')) return;
    const table = target.closest('.network-table');
    if (table && target.closest('tr.network-row-evidence')) return;
    if (table && target.closest('.network-column-resizer')) return;
    clearPinnedNetworkTableSelection();
}

function currentEvidenceCommandNetworkData() {
    return currentNetworkData || currentNetworkTableData || currentNetworkProjectionData || {};
}

function currentEvidenceCommandSnapshot(context = evidenceCommandContext) {
    if (!evidenceCommandSnapshot) return null;
    if (!context || evidenceCommandSnapshot.context === context) return evidenceCommandSnapshot;
    return null;
}

function immutableEvidenceSelectionValue(value, seen = new WeakMap()) {
    if (!value || typeof value !== 'object') return value;
    if (seen.has(value)) return seen.get(value);
    const clone = Array.isArray(value) ? [] : {};
    seen.set(value, clone);
    Object.keys(value).forEach(key => {
        clone[key] = immutableEvidenceSelectionValue(value[key], seen);
    });
    return Object.freeze(clone);
}

function freezeEvidenceCommandSnapshot(snapshot = {}) {
    const frozen = immutableEvidenceSelectionValue(snapshot);
    return Object.freeze(frozen);
}

function setCurrentEvidenceCommandSnapshot(snapshot = null) {
    evidenceCommandSnapshot = snapshot ? freezeEvidenceCommandSnapshot(snapshot) : null;
    evidenceCommandContext = evidenceCommandSnapshot?.context || null;
    evidenceCommandActions = evidenceCommandSnapshot?.actions || [];
    evidenceInsightResult = evidenceCommandSnapshot?.insightResult || null;
    evidenceInsightReceipt = String(evidenceCommandSnapshot?.insightReceipt || '').trim();
    evidenceCommandStatus = String(evidenceCommandSnapshot?.commandStatus || '');
    return evidenceCommandSnapshot;
}

function updateCurrentEvidenceCommandSnapshot(patch = {}) {
    if (!evidenceCommandSnapshot) return null;
    return setCurrentEvidenceCommandSnapshot({
        ...evidenceCommandSnapshot,
        ...patch,
    });
}

function evidenceSelectionToken(snapshot = evidenceCommandSnapshot) {
    if (!snapshot) return null;
    return Object.freeze({
        version: Number(snapshot.version || 0),
        selectionKey: String(snapshot.selectionKey || ''),
        evidenceKey: String(snapshot.evidenceKey || snapshot.context?.evidence_key || ''),
    });
}

function evidenceSelectionTokenIsCurrent(token = null) {
    if (!token || !evidenceCommandSnapshot) return false;
    const current = evidenceSelectionToken(evidenceCommandSnapshot);
    return Boolean(
        current &&
        token.version === current.version &&
        token.version === actionSidebarRequestEpoch &&
        token.selectionKey === current.selectionKey &&
        token.evidenceKey === current.evidenceKey
    );
}

function clearActionSidebarDeferredDetails() {
    if (actionSidebarDeferredFrame !== null) {
        window.cancelAnimationFrame(actionSidebarDeferredFrame);
        actionSidebarDeferredFrame = null;
    }
    if (actionSidebarDeferredTimer !== null) {
        window.clearTimeout(actionSidebarDeferredTimer);
        actionSidebarDeferredTimer = null;
    }
}

function resetActionSidebarDeferredDetails() {
    clearActionSidebarDeferredDetails();
    actionSidebarDeferredDetailsReady = false;
}

function clearActionSidebarRenderSchedule() {
    if (actionSidebarRenderFrame !== null) {
        window.cancelAnimationFrame(actionSidebarRenderFrame);
        actionSidebarRenderFrame = null;
    }
    if (actionSidebarRenderTimer !== null) {
        window.clearTimeout(actionSidebarRenderTimer);
        actionSidebarRenderTimer = null;
    }
}

function scheduleActionSidebarRender() {
    if (!actionSidebarOpen) return;
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('sidebar');
        return;
    }
    if (actionSidebarRenderFrame !== null || actionSidebarRenderTimer !== null) return;
    actionSidebarRenderFrame = window.requestAnimationFrame(() => {
        actionSidebarRenderFrame = null;
        actionSidebarRenderTimer = window.setTimeout(() => {
            actionSidebarRenderTimer = null;
            if (!actionSidebarOpen) return;
            renderActionSidebar();
        }, 0);
    });
}

function scheduleActionSidebarDeferredDetails(requestId = actionSidebarDeferredRenderRequestId) {
    if (!actionSidebarOpen || evidenceCommandLoading || !evidenceCommandContext) return;
    if (actionSidebarDeferredDetailsReady) return;
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('sidebar');
        return;
    }
    if (actionSidebarDeferredFrame !== null || actionSidebarDeferredTimer !== null) return;
    actionSidebarDeferredFrame = window.requestAnimationFrame(() => {
        actionSidebarDeferredFrame = null;
        actionSidebarDeferredTimer = window.setTimeout(() => {
            actionSidebarDeferredTimer = null;
            if (!actionSidebarOpen) return;
            if (requestId !== actionSidebarDeferredRenderRequestId) return;
            if (evidenceCommandLoading || !evidenceCommandContext) return;
            actionSidebarDeferredDetailsReady = true;
            renderActionSidebar();
        }, 0);
    });
}

function buildEvidenceCommandSnapshot(context = {}, options = {}) {
    const cachedSnapshot = currentEvidenceCommandSnapshot(context);
    if (cachedSnapshot && !options.networkData && !options.descriptor) return cachedSnapshot;
    const networkData = options.networkData && typeof options.networkData === 'object'
        ? options.networkData
        : currentEvidenceCommandNetworkData();
    const descriptor = options.descriptor && typeof options.descriptor === 'object'
        ? options.descriptor
        : {};
    const mergedContext = cachedSnapshot?.context === context
        ? context
        : mergeNetworkEvidenceContext(context);
    const selectedEvent = mergedContext.__selectedEvent || resolveNetworkEvidenceEvent(mergedContext);
    const subject = buildNetworkCtrlSubject(mergedContext, descriptor, selectedEvent);
    const routeTarget = buildNetworkCtrlRouteTarget(mergedContext, subject);
    const technicalEvents = selectedEvent
        ? [selectedEvent]
        : (Array.isArray(networkData?.events) ? networkData.events.slice(0, 1) : []);
    const technicalData = selectedEvent
        ? { ...(networkData || {}), events: technicalEvents, event_count: technicalEvents.length }
        : (networkData || {});
    const selectionKey = String(
        options.selectionKey ||
        evidenceCommandSelectionKey ||
        [mergedContext.source_surface, mergedContext.source_entity_id, mergedContext.source_view, mergedContext.source_ref]
            .map(value => String(value || '').trim())
            .join('|'),
    );
    return freezeEvidenceCommandSnapshot({
        version: Number.isFinite(options.version) ? Number(options.version) : actionSidebarRequestEpoch,
        selectionKey,
        evidenceKey: String(mergedContext.evidence_key || '').trim(),
        descriptor: options.descriptor && typeof options.descriptor === 'object' ? options.descriptor : {},
        context: mergedContext,
        selectedEvent,
        subject,
        routeTarget,
        technicalEvents,
        technicalData,
        actions: Array.isArray(options.actions) ? options.actions : (cachedSnapshot?.actions || evidenceCommandActions || []),
        insightResult: options.insightResult || cachedSnapshot?.insightResult || null,
        insightReceipt: String(options.insightReceipt || cachedSnapshot?.insightReceipt || '').trim(),
        actionReceipt: options.actionReceipt || cachedSnapshot?.actionReceipt || null,
        commandStatus: String(options.commandStatus || cachedSnapshot?.commandStatus || ''),
    });
}

function requestEvidenceInsight(action) {
    if (!evidenceCommandContext) return;
    if (!window.CleanHouseAPI?.requestEvidenceInsight) {
        evidenceInsightError = 'Apple Intelligence Insight is unavailable in this environment.';
        renderActionSidebar();
        return;
    }
    const snapshot = currentEvidenceCommandSnapshot(evidenceCommandContext);
    const selectionToken = evidenceSelectionToken(snapshot);
    if (!snapshot || !selectionToken) return;
    const selectionContext = snapshot.context;
    const insightContext = networkCtrlInsightContextPayload(selectionContext, snapshot.selectedEvent || null);
    const evidenceKey = String(insightContext.evidence_key || snapshot.evidenceKey || selectionContext.evidence_key || '').trim();
    if (!evidenceKey) {
        evidenceInsightError = 'Evidence key is required before Insight can run.';
        renderActionSidebar();
        return;
    }
    const requestSourceView = selectionContext.source_view;
    const requestKey = evidenceKey + '|' + String(requestSourceView || '');
    const requestEpoch = ++evidenceInsightRequestEpoch;
    evidenceInsightRequestKey = requestKey;
    evidenceInsightLoading = true;
    evidenceInsightError = '';
    updateCurrentEvidenceCommandSnapshot({ insightResult: null, insightReceipt: '' });
    renderActionSidebar();
    window.CleanHouseAPI.requestEvidenceInsight({
        evidenceKey,
        sourceView: requestSourceView,
        invoker: 'operator',
        role: action?.required_role || 'Insight',
        evidenceContext: insightContext,
    }).then(result => {
        if (requestEpoch !== evidenceInsightRequestEpoch || evidenceInsightRequestKey !== requestKey || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'Apple Intelligence Insight could not run.');
        }
        updateCurrentEvidenceCommandSnapshot({
            insightResult: result,
            insightReceipt: String(result.audit?.id || '').trim(),
        });
    }).catch(error => {
        if (requestEpoch !== evidenceInsightRequestEpoch || evidenceInsightRequestKey !== requestKey || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
        updateCurrentEvidenceCommandSnapshot({ insightResult: null, insightReceipt: '' });
        evidenceInsightError = error?.message || 'Apple Intelligence Insight is unavailable.';
    }).finally(() => {
        if (requestEpoch !== evidenceInsightRequestEpoch || evidenceInsightRequestKey !== requestKey || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
        evidenceInsightLoading = false;
        renderActionSidebar();
    });
}

function maybeRequestCtrlInsightForSelection(context = {}) {
    if (!actionSidebarOpen) return;
    const targetContext = context || {};
    const evidenceKey = String(targetContext.evidence_key || '').trim();
    if (!evidenceKey) return;
    const sourceView = String(targetContext.source_view || '').trim();
    if (normalizedCtrlText(sourceView) === 'table') return;
    const evidenceRefs = Array.from(new Set(
        (Array.isArray(context.evidence_refs) ? context.evidence_refs : [])
            .map(value => String(value || '').trim())
            .filter(Boolean)
    )).slice(0, 32);
    const assessmentRefs = Array.from(new Set(
        (Array.isArray(context.assessment_refs) ? context.assessment_refs : [])
            .map(value => String(value || '').trim())
            .filter(Boolean)
    )).slice(0, 32);
    const selectionKey = [
        evidenceKey,
        sourceView,
        evidenceRefs.join(','),
        assessmentRefs.join(','),
    ].join('|');
    if (evidenceAutoInsightSelectionKey === selectionKey) return;
    evidenceAutoInsightSelectionKey = selectionKey;
    requestEvidenceInsight({ required_role: 'Insight' });
}

function executeEvidenceAction(action, actionOrigin = '') {
    if (!action || !action.enabled || !evidenceCommandContext) return;
    const selectionSnapshot = currentEvidenceCommandSnapshot(evidenceCommandContext);
    const selectionToken = evidenceSelectionToken(selectionSnapshot);
    if (!selectionSnapshot || !selectionToken || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
    const selectionContext = selectionSnapshot.context;
    const actionId = String(action.id || '').trim();
    if (!actionId) {
        updateCurrentEvidenceCommandSnapshot({ commandStatus: 'Action identifier is missing.' });
        renderActionSidebar();
        return;
    }
    if (actionId === 'ask_insight') {
        requestEvidenceInsight(action);
        return;
    }
    if (!window.CleanHouseAPI?.recordEvidenceAction) {
        updateCurrentEvidenceCommandSnapshot({ commandStatus: 'Action audit is unavailable in this environment.' });
        renderActionSidebar();
        return;
    }
    const actionRequestEpoch = ++evidenceActionRequestEpoch;
    const payload = {
        surface: selectionContext.source_surface,
        entityId: selectionContext.source_entity_id,
        sourceView: selectionContext.source_view,
        actionId,
        invoker: 'operator',
        role: action.required_role || 'viewer',
        actionRequestId: window.crypto?.randomUUID?.() || `action-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    };
    if (actionId === 'copy' || actionId === 'export') {
        payload.insightPayload = {
            evidence_context: networkCtrlInsightContextPayload(selectionContext, selectionSnapshot.selectedEvent || null),
            insight: selectionSnapshot.insightResult?.insight || {},
        };
    }
    const normalizedActionOrigin = String(actionOrigin || '').trim().toLowerCase();
    const normalizedActionId = normalizedCtrlText(actionId);
    if (
        (normalizedActionOrigin === 'ctrl' || normalizedActionOrigin === 'scan')
        && CTRL_REPORT_ACTION_IDS.has(normalizedActionId)
    ) {
        const subject = selectionSnapshot.subject || buildNetworkCtrlSubject(selectionContext);
        const evidenceRefs = Array.isArray(selectionContext.evidence_refs) ? selectionContext.evidence_refs : [];
        const evidenceLinks = evidenceRefs
            .map(value => String(value || '').trim())
            .filter((value, index, values) => value && values.indexOf(value) === index);
        const selectionReceipt = {
            evidence_key: String(selectionSnapshot.evidenceKey || selectionContext.evidence_key || '').trim(),
            source_surface: String(selectionContext.source_surface || '').trim() || 'network',
            source_view: String(selectionContext.source_view || '').trim() || 'table',
            source_entity_id: String(selectionContext.source_entity_id || '').trim(),
            source_refs: evidenceLinks,
            assessment_refs: Array.from(new Set(
                (Array.isArray(selectionContext.assessment_refs) ? selectionContext.assessment_refs : [])
                    .map(value => String(value || '').trim()).filter(Boolean),
            )).slice(0, 32),
        };
        const subjectName = String(subject.displayName || '').trim();
        const subjectType = String(subject.subjectType || 'event').trim() || 'event';
        if (subjectName && (evidenceLinks.length || selectionReceipt.evidence_key)) {
            payload.actionOrigin = normalizedActionOrigin;
            payload.create_report = true;
            payload.subject = { name: subjectName, type: subjectType };
            payload.selection_receipt = selectionReceipt;
            payload.evidence_links = evidenceLinks;
        }
    }
    if (normalizedActionOrigin === 'scan') {
        payload.actionOrigin = 'scan';
    }
    window.CleanHouseAPI.recordEvidenceAction(payload).then(result => {
        if (actionRequestEpoch !== evidenceActionRequestEpoch || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
        if (!result || result.status !== 'ok') {
            throw new Error(result?.message || 'Action could not be recorded.');
        }
        const copyText = String(result.effect?.copy_text || '');
        if (copyText && navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(copyText).catch(() => {});
        }
        updateCurrentEvidenceCommandSnapshot({
            actionReceipt: result,
            commandStatus: result.message || `${action.label} completed with receipt ${result.receipt_id || result.audit?.id || 'pending'}.`,
        });
        const route = action.source_navigation?.route;
        const routeType = action.source_navigation?.type;
        if (routeType === 'route' && route) {
            window.location.assign(route);
            return;
        }
        renderActionSidebar();
    }).catch(error => {
        if (actionRequestEpoch !== evidenceActionRequestEpoch || !evidenceSelectionTokenIsCurrent(selectionToken)) return;
        updateCurrentEvidenceCommandSnapshot({
            actionReceipt: null,
            commandStatus: error?.message || 'Action execution was not recorded.',
        });
        renderActionSidebar();
    });
}

function evidenceInsightHtml(context, snapshot = null) {
    const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context);
    const subject = snapshotState.subject || buildNetworkCtrlSubject(context);
    const routeTarget = snapshotState.routeTarget || buildNetworkCtrlRouteTarget(context, subject);
    const event = snapshotState.selectedEvent || resolveNetworkEvidenceEvent(context);
    const insight = snapshotState.insightResult?.insight && typeof snapshotState.insightResult.insight === 'object'
        ? snapshotState.insightResult.insight
        : {};
    const usefulText = (...values) => values
        .map(value => String(value || '').trim())
        .find(value => value && !isUnknownCtrlOwner(value) && !/^unavailable$/i.test(value)) || '';
    const evidenceEntityId = event ? networkEvidenceEntityId(event) : '';
    const destinationText = usefulText(
        event ? networkEventDestination(event) : '',
        context?.destination,
        context?.dst_host,
        context?.dst_ip,
        context?.host,
        context?.ip,
        context?.source_host,
        insight.destination,
        insight.destination_context
    );
    const eventLabel = [
        event ? networkEventTime(event) : '',
        event?.protocol || context?.protocol || '',
        event?.severity || context?.severity || context?.validation_state || '',
    ].map(value => String(value || '').trim()).filter(Boolean).join(' · ');
    const eventText = eventLabel || usefulText(event?.event_id, event?.id, context?.event_id, context?.eventId, context?.source_entity_id);
    const findingText = usefulText(
        event?.summary,
        context?.summary,
        context?.title,
        insight.finding,
        routeTarget?.findingId,
        context?.finding_id
    );
    const reasonText = usefulText(
        insight.plain_language_summary,
        insight.why_it_matters,
        event?.reason,
        event?.meaning,
        Array.isArray(context?.network_reasons) ? context.network_reasons[0] : '',
        context?.network_tags?.explanation
    );
    const changedText = reasonText || 'No change explanation is available for this evidence yet.';
    const findingId = String(routeTarget?.findingId || evidenceEntityId || routeTarget?.entityId || '').trim();
    const eventRouteId = String(routeTarget?.eventId || evidenceEntityId || event?.event_id || event?.id || '').trim();
    const destinationRoute = destinationText ? {
        ...routeTarget,
        view: 'table',
        entityId: evidenceEntityId || routeTarget?.entityId || '',
        destination: destinationText,
    } : null;
    const eventRoute = eventRouteId ? {
        ...routeTarget,
        view: 'timeline',
        eventId: eventRouteId,
        entityId: eventRouteId,
    } : null;
    const findingRoute = findingId ? {
        ...routeTarget,
        view: 'findings',
        findingId,
        entityId: findingId,
    } : null;
    const assessment = context?.__selectedAssessment && typeof context.__selectedAssessment === 'object'
        ? context.__selectedAssessment
        : resolveNetworkAssessment(context || {});
    const assessmentRule = assessment?.rule && typeof assessment.rule === 'object'
        ? [assessment.rule.id, assessment.rule.version]
            .map(value => String(value || '').trim())
            .filter(Boolean)
            .join(' · ')
        : String(context?.assessment_rule || '').trim();
    const assessmentRationale = usefulText(
        assessment?.rationale,
        Array.isArray(context?.network_reasons) ? context.network_reasons[0] : ''
    );
    const assessmentConfidence = assessment?.confidence && typeof assessment.confidence === 'object'
        ? [
            assessment.confidence.label,
            Number.isFinite(Number(assessment.confidence.score))
                ? Math.round(Number(assessment.confidence.score) * 100) + '%'
                : '',
        ].map(value => String(value || '').trim()).filter(Boolean).join(' ')
        : String(assessment?.confidence || '').trim();
    const assessmentMeta = assessment
        ? [
            assessment.category,
            assessment.severity,
            assessmentConfidence,
            assessment.lifecycle,
            assessmentRule,
        ].map(value => String(value || '').trim()).filter(Boolean).join(' · ')
        : '';
    const assessmentHtml = assessment
        ? (
            '<section class="action-sidebar-section action-sidebar-security-assessment">' +
            '<h3>Security assessment</h3>' +
            '<p class="action-sidebar-meta">' + escapeHtml(assessmentMeta || 'Assessment details unavailable') + '</p>' +
            '<p>' + escapeHtml(assessmentRationale || 'No assessment rationale is available for this evidence yet.') + '</p>' +
            '</section>'
        )
        : '';
    const sectionBodyFromRoute = (label, value, route, fallback = 'unavailable') => {
        const safeValue = String(value || '').trim();
        const routeAttrs = route
            ? ' data-ctrl-route="' + escapeHtml(route.view || '') + '"' + networkCtrlRouteTargetAttrs(route)
            : '';
        const heading = route
            ? '<button type="button" class="action-sidebar-route-link action-sidebar-heading-link"' + routeAttrs + '>' + escapeHtml(label) + '</button>'
            : escapeHtml(label);
        const detail = safeValue
            ? '<p>' + escapeHtml(safeValue) + '</p>'
            : '<p class="action-sidebar-empty">' + escapeHtml(fallback) + '</p>';
        return (
            '<section class="action-sidebar-section">' +
            '<h3>' + heading + '</h3>' +
            '<div class="action-sidebar-route-links">' + detail + '</div>' +
            '</section>'
        );
    };
    const recommendedNextStep = () => {
        const generated = Array.isArray(insight.recommended_next_steps)
            ? insight.recommended_next_steps.map(item => String(item || '').trim()).filter(Boolean)
            : [];
        if (generated.length) return generated.slice(0, 3);
        if (subject.subjectType === 'destination' || subject.subjectType === 'port') {
            return [
                'Use the options menu to observe this destination before taking enforcement action.',
                'Use Block only if this destination is not recognized.',
            ];
        }
        if (subject.subjectType === 'finding') {
            return [
                'Use the options menu to observe this finding before taking enforcement action.',
                'Mark this finding as read if this traffic is expected.',
            ];
        }
        return [
            'Use the options menu to observe the responsible app before taking enforcement action.',
            'Quarantine only if the owning app is suspicious or unauthorized.',
        ];
    };
    const loadingLine = evidenceInsightLoading
        ? '<p class="action-sidebar-meta">Apple Intelligence is checking this evidence.</p>'
        : '';
    return (
        '<section class="action-sidebar-section action-sidebar-insight-live">' +
        sectionBodyFromRoute(
            'Destination',
            destinationText,
            destinationRoute
        ) +
        sectionBodyFromRoute(
            'Event',
            eventText,
            eventRoute
        ) +
        sectionBodyFromRoute(
            'Finding',
            findingText,
            findingRoute
        ) +
        assessmentHtml +
        '<section class="action-sidebar-section">' +
        '<h3>What changed</h3>' +
        '<p>' + escapeHtml(changedText) + '</p>' +
        '</section>' +
        '<section class="action-sidebar-section">' +
        '<h3>Recommended next step</h3>' +
        '<ul class="action-sidebar-reference-list">' +
        recommendedNextStep().map(item => '<li>' + escapeHtml(item) + '</li>').join('') +
        '</ul>' +
        '</section>' +
        loadingLine +
        '</section>'
    );
}

function buildNetworkCtrlRouteTarget(context = {}, subject = {}) {
    const sourceView = normalizedCtrlText(context.source_view || subject.sourceView || 'table');
    const normalizedView = sourceView === 'pie' ? 'distribution' : sourceView;
    const mergedSubject = subject && typeof subject === 'object' && subject.displayName
        ? subject
        : buildNetworkCtrlSubject(context, subject || {});
    return {
        view: normalizedView || 'table',
        subjectType: normalizedCtrlText(mergedSubject.subjectType || context.subject_type || context.type || context.entity_type || context.evidence_type || context.kind || ''),
        owner: normalizeCtrlSubjectName(mergedSubject.displayName || 'Unknown app'),
        sourceSurface: String(context.source_surface || subject.surface || 'network').trim(),
        sourceView: sourceView || 'table',
        entityId: String(context.source_entity_id || subject.entityId || '').trim(),
        sourceRef: String(context.source_ref || context.ref || context.raw_evidence_ref || subject.ref || '').trim(),
        eventId: String(context.event_id || '').trim(),
        findingId: String(context.finding_id || '').trim(),
        destination: String(context.destination || context.dst_host || context.host || context.ip || context.source_host || '').trim(),
    };
}

function networkCtrlRouteTargetForSection(sectionView = '', context = {}, subject = {}) {
    const base = buildNetworkCtrlRouteTarget(context, subject);
    return {
        ...base,
        view: normalizedCtrlText(sectionView),
        entityId: String(base.entityId || base.eventId || '').trim(),
    };
}

function networkCtrlRouteTargetAttrs(routeTarget = {}) {
    if (!routeTarget || !routeTarget.view) return '';
    const target = {
        view: String(routeTarget.view || '').trim(),
        owner: String(routeTarget.owner || '').trim(),
        entityId: String(routeTarget.entityId || '').trim(),
        sourceSurface: String(routeTarget.sourceSurface || '').trim(),
        sourceView: String(routeTarget.sourceView || '').trim(),
        sourceRef: String(routeTarget.sourceRef || '').trim(),
        destination: String(routeTarget.destination || '').trim(),
        eventId: String(routeTarget.eventId || '').trim(),
        findingId: String(routeTarget.findingId || '').trim(),
    };
    return Object.entries(target)
        .filter(([, value]) => value)
        .map(([key, value]) => ` data-ctrl-route-${key.replace(/[A-Z]/g, match => '-' + match.toLowerCase())}="${escapeHtml(value)}"`)
        .join('');
}

function normalizeCtrlDistributionOwner(value = '') {
    return normalizeCtrlSubjectName(value).replace(/^distribution\s*:\s*/i, '').trim();
}

function normalizeCtrlDistributionBucketLabel(value = '') {
    const label = normalizeCtrlDistributionOwner(value);
    return label && !isUnknownCtrlOwner(label) ? label : 'Unknown app';
}

function networkDistributionSourceEvents() {
    const sources = [currentNetworkTableData, currentNetworkHeaderData, currentNetworkData, currentNetworkProjectionData];
    const source = sources.find(data => data && Array.isArray(data.events) && data.events.length);
    return source ? source.events : [];
}

function networkDistributionBucketForAppLabel(appLabel = '', events = networkDistributionSourceEvents()) {
    const candidate = normalizeCtrlDistributionBucketLabel(appLabel);
    const counts = networkGroupCountsBy(Array.isArray(events) ? events : [], event => normalizeCtrlDistributionBucketLabel(networkEventAppName(event)));
    const rankedEntries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    if (!rankedEntries.length) return candidate;
    const visibleEntries = rankedEntries.slice(0, 7);
    const visibleLabels = visibleEntries.map(([label]) => label);
    const visibleTotal = visibleEntries.reduce((sum, [, count]) => sum + count, 0);
    const otherCount = Math.max((Array.isArray(events) ? events.length : 0) - visibleTotal, 0);
    if (visibleLabels.includes(candidate)) return candidate;
    if (counts[candidate] && otherCount) return 'Other apps';
    return candidate === 'Unknown app' ? 'Unknown app' : networkDistributionBucketForAppLabel('Unknown app', events);
}

function resolveCtrlHeaderAppName(context = {}, selectedEvent = null) {
    const sourceView = normalizedCtrlText(context.source_view || '');
    if (sourceView === 'distribution' || sourceView === 'pie') {
        return normalizeCtrlDistributionBucketLabel(context.source_entity_id || context.owner || 'Unknown app');
    }
    const event = selectedEvent || resolveNetworkEvidenceEvent(context);
    if (event) {
        return normalizeCtrlDistributionBucketLabel(networkEventAppName(event));
    }
    const contextOwner = resolveCtrlEvidenceAppName(context);
    if (contextOwner) return normalizeCtrlDistributionBucketLabel(contextOwner);
    return 'Unknown app';
}

function networkCtrlHeaderHtml(context = {}, snapshot = null) {
    if (!context) return '';
    const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context);
    const headerAppName = resolveCtrlHeaderAppName(context, snapshotState.selectedEvent || null);
    const routeOwner = networkDistributionBucketForAppLabel(headerAppName);
    const headerRouteTarget = networkCtrlRouteTargetForSection('distribution', context, {
        displayName: routeOwner,
        sourceView: context.source_view || 'table',
    });
    return (
        '<h2 id="action-sidebar-title" class="action-sidebar-title">' +
        '<button type="button" class="action-sidebar-back-button" aria-label="Back to control panel" data-evidence-open-back>‹</button>' +
        '<button type="button" class="action-sidebar-route-link action-sidebar-subject-route" data-ctrl-route="' + escapeHtml(headerRouteTarget.view) + '"' +
        networkCtrlRouteTargetAttrs(headerRouteTarget) +
        '>' +
        escapeHtml(headerAppName) +
        '</button>' +
        '<span class="action-sidebar-more-wrap">' +
        '<button type="button" class="action-sidebar-more-toggle" title="More actions" aria-label="More actions" data-ctrl-menu-toggle>⋮</button>' +
        '<span class="action-sidebar-more-menu" data-ctrl-more-menu hidden></span>' +
        '</span>' +
        '</h2>'
    );
}

function controlPanelNetworkView(view) {
    const normalized = normalizedCtrlText(view);
    return NETWORK_CTRL_VIEW_ALIASES[normalized] || '';
}

function normalizedCtrlText(value = '') {
    return String(value || '').trim().toLowerCase();
}

function isUnknownCtrlOwner(value = '') {
    const text = String(value || '').trim();
    return (
        !text ||
        /^unknown\b/i.test(text) ||
        /^unknown app/i.test(text) ||
        /^network evidence context unavailable\.?$/i.test(text) ||
        /^evidence context unavailable\.?$/i.test(text)
    );
}

function normalizeCtrlSubjectName(value = '') {
    return String(value || '').trim().replace(/\s+/g, ' ').replace(/^[\s"'“”']+|[\s"'“”']+$/g, '');
}

function findApplicationOwnerByBundle(bundle = '') {
    const target = normalizedCtrlText(bundle);
    if (!target) return '';
    if (!Array.isArray(applications)) return '';
    const match = applications.find(item => {
        const candidates = [
            item?.id,
            item?.bundle_id,
            item?.bundle_identifier,
            item?.bundle,
            item?.bundleName,
            item?.name,
        ];
        return candidates.some(candidate => normalizedCtrlText(candidate) === target);
    });
    return match ? normalizeCtrlSubjectName(match?.name || match?.bundle_id || match?.id || '') : '';
}

function findApplicationOwnerByProcess(process = '') {
    const target = normalizedCtrlText(process);
    if (!target || !Array.isArray(applications) || !applications.length) return '';
    const normalizedProcessName = (value = '') => {
        const text = normalizeCtrlSubjectName(value);
        if (!text) return '';
        return normalizedCtrlText(text);
    };
    const processCandidate = normalizedProcessName(process);
    if (!processCandidate) return '';
    const processNames = processCandidate.includes(' / ')
        ? processCandidate.split(' / ').map(part => part.trim()).filter(Boolean)
        : [];
    for (const app of applications) {
        const appName = normalizeCtrlSubjectName(app?.name || '');
        if (!appName) continue;
        const normalizedApp = normalizedCtrlText(appName);
        const bundle = normalizedCtrlText(app?.bundle_id || app?.bundle_identifier || '');
        const processRows = Array.isArray(app.processes) ? app.processes : [];
        const appProcessValues = processRows.flatMap(row => [
            row?.command,
            row?.process,
            row?.name,
            row?.path,
        ]);
        const normalizedProcesses = appProcessValues.map(item => normalizedCtrlText(item));
        const hasPathFallback = normalizedProcesses.some(item => item && item.endsWith(processCandidate));
        if (
            normalizedProcesses.includes(processCandidate) ||
            normalizedProcesses.some(item => item && item.includes(processCandidate)) ||
            processCandidate.includes(normalizedApp) ||
            normalizedApp.includes(processCandidate) ||
            hasPathFallback
        ) {
            return appName;
        }
        const matchByParts = processNames.some(part => part && (
            normalizedProcesses.includes(part.toLowerCase()) ||
            normalizedProcesses.some(item => item && item.includes(part.toLowerCase()))
        ));
        if (matchByParts) {
            return appName;
        }
    }
    return '';
}

function resolveCtrlEvidenceAppName(context = {}) {
    const explicitCandidates = [
        context.app_display_name,
        context.app_name,
        context.application_name,
        context.application_display_name,
        context.owner_name,
        context.owner_app_name,
        context.app_owner,
        context.bundle_name,
        context.bundle_label,
    ];
    const explicit = explicitCandidates
        .map(value => normalizeCtrlSubjectName(value))
        .find(value => value && !isUnknownCtrlOwner(value));
    if (explicit) return explicit;

    const bundleCandidates = [
        context.bundle_id,
        context.bundle_identifier,
        context.app_bundle_id,
    ];
    for (const candidate of bundleCandidates) {
        const resolved = findApplicationOwnerByBundle(candidate);
        if (resolved) return resolved;
    }

    const processCandidates = [
        context.app_process,
        context.process_name,
        context.processName,
        context.process,
    ];
    const mappedProcessOwner = processCandidates
        .map(value => findApplicationOwnerByProcess(value))
        .find(value => value && !isUnknownCtrlOwner(value));
    if (mappedProcessOwner) return mappedProcessOwner;
    return '';
}

function resolveNetworkEvidenceEvent(context = {}) {
    if (!context || typeof context !== 'object') return null;
    const evidenceKey = String(context.evidence_key || '').trim();
    const evidenceKeyEntity = evidenceKey.startsWith('network:') ? evidenceKey.slice('network:'.length) : '';
    const targets = [
        context.source_entity_id,
        context.event_id,
        context.eventId,
        context.timeline_event_id,
        context.raw_evidence_ref,
        evidenceKey,
        evidenceKeyEntity,
        ...(Array.isArray(context.evidence_refs) ? context.evidence_refs : []),
    ].map(value => String(value || '').trim()).filter(Boolean);
    if (!targets.length) return null;
    const events = [];
    const seen = new Set();
    [currentNetworkData, currentNetworkTableData, currentNetworkProjectionData, currentNetworkHeaderData].forEach(data => {
        if (!data || !Array.isArray(data.events)) return;
        data.events.forEach(event => {
            if (!event || typeof event !== 'object') return;
            const key = networkEvidenceEntityId(event) || event.id || event.event_id || String(events.length);
            if (seen.has(key)) return;
            seen.add(key);
            events.push(event);
        });
    });
    return events.find(event => {
        const refs = Array.isArray(event.evidence_refs) ? event.evidence_refs : [];
        const related = Array.isArray(event.related_event_ids) ? event.related_event_ids : [];
        const values = [
            networkEvidenceEntityId(event),
            event.event_id,
            event.id,
            event.source_event_id,
            event.raw_evidence_ref,
            event.raw_ref,
            event.timeline_event_id,
            ...refs,
            ...related,
        ].map(value => String(value || '').trim()).filter(Boolean);
        return targets.some(target => values.includes(target));
    }) || null;
}

function mergeNetworkEvidenceContext(context = {}) {
    if (!context || typeof context !== 'object') return context;
    if (normalizedCtrlText(context.source_surface || '') !== 'network') return context;
    const assessment = resolveNetworkAssessment(context);
    const event = resolveNetworkEvidenceEvent(context);
    if (!event && !assessment) return context;
    const assessmentEvidenceRefs = Array.isArray(assessment?.evidence_refs) ? assessment.evidence_refs : [];
    const assessmentRule = assessment?.rule && typeof assessment.rule === 'object'
        ? [assessment.rule.id, assessment.rule.version].filter(Boolean).join(' · ')
        : '';
    const selectedEntity = String(context.source_entity_id || '').trim();
    const assessmentSelected = Boolean(assessment && (
        context.assessment_id ||
        selectedEntity === String(assessment.assessment_id || '').trim() ||
        selectedEntity === String(assessment.assessment_key || '').trim()
    ));
    if (assessment && !event) {
        const assessmentRefs = Array.from(new Set([
            ...(Array.isArray(context.assessment_refs) ? context.assessment_refs : []),
            assessment.assessment_id,
        ].map(value => String(value || '').trim()).filter(Boolean))).slice(0, 32);
        return {
            ...context,
            __selectedAssessment: assessment,
            source_entity_id: String(assessment.assessment_id || assessment.assessment_key || context.source_entity_id || '').trim(),
            assessment_id: String(assessment.assessment_id || '').trim(),
            assessment_category: String(assessment.category || '').trim(),
            assessment_lifecycle: String(assessment.lifecycle || '').trim(),
            assessment_rule: assessmentRule,
            evidence_refs: Array.from(new Set([...(Array.isArray(context.evidence_refs) ? context.evidence_refs : []), ...assessmentEvidenceRefs].map(value => String(value || '').trim()).filter(Boolean))),
            assessment_refs: assessmentRefs,
            summary: String(assessment.subject?.label || assessment.assessment_key || context.summary || '').trim(),
            severity: String(assessment.severity || context.severity || '').trim(),
            network_reasons: [String(assessment.rationale || '').trim()].filter(Boolean),
        };
    }
    const entityId = networkEvidenceEntityId(event) || String(context.source_entity_id || '').trim();
    const evidenceRefs = [
        ...(Array.isArray(context.evidence_refs) ? context.evidence_refs : []),
        ...assessmentEvidenceRefs,
        ...networkEvidenceRelatedIds(event),
        networkEvidenceRef(event),
    ].map(value => String(value || '').trim()).filter(Boolean);
    const reasons = [
        assessment?.rationale,
        event.reason,
        event.meaning,
        event.category,
        ...(Array.isArray(context.network_reasons) ? context.network_reasons : []),
    ].map(value => String(value || '').trim()).filter(Boolean);
    const assessmentRefs = Array.from(new Set([
        ...(Array.isArray(context.assessment_refs) ? context.assessment_refs : []),
        ...(Array.isArray(event.assessment_refs) ? event.assessment_refs : []),
        assessment?.assessment_id,
    ].map(value => String(value || '').trim()).filter(Boolean))).slice(0, 32);
    const evidenceKey = entityId && entityId.startsWith('network:')
        ? entityId
        : (String(context.evidence_key || '').trim() || (entityId ? 'network:' + entityId : ''));
    return {
        ...context,
        ...(assessment ? {
            __selectedAssessment: assessment,
            assessment_id: String(assessment.assessment_id || '').trim(),
            assessment_category: String(assessment.category || '').trim(),
            assessment_lifecycle: String(assessment.lifecycle || '').trim(),
            assessment_rule: assessmentRule,
        } : {}),
        __selectedEvent: event,
        evidence_key: evidenceKey,
        source_entity_id: assessmentSelected
            ? String(assessment.assessment_id || assessment.assessment_key || selectedEntity).trim()
            : (entityId || selectedEntity),
        evidence_refs: Array.from(new Set(evidenceRefs)),
        assessment_refs: assessmentRefs,
        summary: String(assessmentSelected ? (assessment.subject?.label || assessment.assessment_key || context.summary || event.summary) : (event.summary || context.summary || '')).trim(),
        severity: String(assessmentSelected ? (assessment.severity || context.severity || event.severity) : (event.severity || context.severity || '')).trim(),
        validation_state: String(context.validation_state || event.validation_state || event.finding_status || '').trim(),
        timeline_event_id: String(context.timeline_event_id || event.timeline_event_id || event.event_id || entityId || '').trim(),
        network_reasons: Array.from(new Set(reasons)).slice(0, 8),
    };
}

function networkCtrlInsightContextPayload(context = {}, selectedEvent = null) {
    const merged = currentEvidenceCommandSnapshot(context)?.context === context
        ? context
        : mergeNetworkEvidenceContext(context);
    if (!merged || typeof merged !== 'object') return {};
    const event = selectedEvent || resolveNetworkEvidenceEvent(merged);
    const entityId = String(merged.source_entity_id || (event ? networkEvidenceEntityId(event) : '') || '').trim();
    const evidenceRefs = [
        ...(Array.isArray(merged.evidence_refs) ? merged.evidence_refs : []),
        ...(event ? networkEvidenceRelatedIds(event) : []),
        event ? networkEvidenceRef(event) : '',
    ].map(value => String(value || '').trim()).filter(Boolean);
    const assessmentRefs = Array.from(new Set([
        ...(Array.isArray(merged.assessment_refs) ? merged.assessment_refs : []),
        ...(Array.isArray(event?.assessment_refs) ? event.assessment_refs : []),
    ].map(value => String(value || '').trim()).filter(Boolean))).slice(0, 32);
    const evidenceKey = entityId && entityId.startsWith('network:')
        ? entityId
        : String(merged.evidence_key || (entityId ? 'network:' + entityId : '') || '').trim();
    return {
        evidence_key: evidenceKey,
        source_surface: String(merged.source_surface || 'network').trim(),
        source_view: String(merged.source_view || 'table').trim(),
        source_entity_id: entityId,
        app: String(event?.process || event?.app || event?.application || '').trim(),
        source: event ? networkEventSource(event) : '',
        destination: event ? networkEventDestination(event) : '',
        protocol: String(event?.protocol || '').trim(),
        event_time: event ? networkEventTime(event) : '',
        summary: String(merged.summary || event?.summary || '').trim(),
        severity: String(merged.severity || event?.severity || '').trim(),
        validation_state: String(merged.validation_state || event?.finding_status || '').trim(),
        evidence_refs: Array.from(new Set(evidenceRefs)),
        assessment_refs: assessmentRefs,
        timeline_event_id: String(merged.timeline_event_id || event?.timeline_event_id || event?.event_id || entityId || '').trim(),
        network_reasons: Array.from(new Set([
            ...(Array.isArray(merged.network_reasons) ? merged.network_reasons : []),
            event?.reason,
            event?.meaning,
            event?.category,
        ].map(value => String(value || '').trim()).filter(Boolean))).slice(0, 8),
    };
}

function deriveFindingSubjectFromTitleTitleCase(title = '') {
    const rawTitle = normalizeCtrlSubjectName(title || '');
    if (!rawTitle) return '';
    const titleNoTrailingPhrases = rawTitle
        .replace(/\s+traffic\s*(?:was|is|were|has|is|to|on|via|observed|reported|seen)?[\s\w\W]*$/i, '')
        .replace(/\s+was\s+observed[\s\w\W]*$/i, '')
        .replace(/\s+is\s+using[\s\w\W]*$/i, '')
        .replace(/\s+is\s+communicating[\s\w\W]*$/i, '')
        .replace(/\s+was\s+reported[\s\w\W]*$/i, '')
        .trim();
    const actionCuts = [
        /^(.*?)\s+is\b/i,
        /^(.*?)\s+was\b/i,
        /^(.*?)\s+were\b/i,
        /^(.*?)\s+has\b/i,
        /^(.*?)\s+using\b/i,
    ];
    for (const pattern of actionCuts) {
        const match = rawTitle.match(pattern);
        if (match && normalizeCtrlSubjectName(match[1])) return normalizeCtrlSubjectName(match[1]);
    }
    if (titleNoTrailingPhrases) {
        const candidate = titleNoTrailingPhrases.replace(/[\s\W]+$/, '').trim();
        if (candidate && !/^traffic$/i.test(candidate) && !/^service$/i.test(candidate)) return normalizeCtrlSubjectName(candidate);
    }
    return '';
}

function deriveFindingSubjectNameFromContext(context = {}) {
    const event = resolveNetworkEvidenceEvent(context);
    const explicit = resolveCtrlEvidenceAppName(context);
    if (explicit) return explicit;
    if (!event) return '';
    const eventApp = resolveCtrlEvidenceAppName(event) || normalizeCtrlSubjectName(event.app || event.application || '');
    if (eventApp && !isUnknownCtrlOwner(eventApp)) return eventApp;
    const titleSubject = deriveFindingSubjectFromTitleTitleCase(context.summary || context.title || event.summary || event.title || '');
    if (titleSubject && !isUnknownCtrlOwner(titleSubject)) return titleSubject;
    return '';
}

function buildNetworkCtrlSubject(context = {}, descriptor = {}, selectedEvent = null) {
    const summary = String(context.summary || context.title || context.name || '').trim();
    const sourceSurface = normalizedCtrlText(context.source_surface || descriptor.surface || 'network');
    const resolvedAppName = sourceSurface === 'network'
        ? resolveCtrlHeaderAppName(context, selectedEvent)
        : resolveCtrlEvidenceAppName(context);
    let rawSubjectName = resolvedAppName || '';
    const normalizedView = normalizedCtrlText(context.source_view || descriptor.sourceView || 'table');
    if (!rawSubjectName && sourceSurface !== 'network' && normalizedView === 'findings') {
        rawSubjectName = deriveFindingSubjectFromTitleTitleCase(summary);
    }
    let subjectName = rawSubjectName;
    if (!subjectName) {
        subjectName = 'Unknown app';
    }
    const entityId = String(context.source_entity_id || descriptor.entityId || '').trim();
    const networkTags = context.network_tags && typeof context.network_tags === 'object' ? context.network_tags : {};
    const reasons = Array.isArray(context.network_reasons)
        ? context.network_reasons.map(item => String(item || '').trim()).filter(Boolean)
        : (Array.isArray(context.reasons) ? context.reasons.map(item => String(item || '').trim()).filter(Boolean) : []);
    const contextType = normalizedCtrlText(context.subject_type || context.type || context.entity_type || context.evidence_type || context.kind || '');
    const summaryLower = normalizedCtrlText(summary);
    const selectedEventTarget = selectedEvent && typeof selectedEvent === 'object' ? selectedEvent : {};
    const stateTags = {
        status: normalizedCtrlText(context.validation_state || context.status || context.result || ''),
        state: normalizedCtrlText(networkTags.state || ''),
        networkStatus: normalizedCtrlText(networkTags.status || ''),
    };
    const isActiveProcess = normalizedCtrlText(summaryLower).includes('pid')
        || normalizedCtrlText(context.process_state || context.processStatus).includes('active')
        || normalizedCtrlText(summaryLower).includes('active')
        || /^\d+$/.test(entityId);
    let subjectType = 'event';
    if (contextType && CTRL_SUBJECT_TYPES.has(contextType)) {
        subjectType = contextType;
    } else if (normalizedView === 'findings') {
        subjectType = 'finding';
    } else if (normalizedView === 'trend' || normalizedView === 'timeline') {
        subjectType = 'time_bucket';
    } else if (summaryLower.includes('process') || summaryLower.includes('pid') || normalizedCtrlText(context.process) || context.app_process) {
        subjectType = 'app_process';
    } else if (summaryLower.includes('artifact') || normalizedCtrlText(context.artifact)) {
        subjectType = 'aggregate_group';
    } else if (summaryLower.includes('time bucket') || summaryLower.includes('bucket')) {
        subjectType = 'time_bucket';
    } else if (normalizedView === 'distribution' || normalizedView === 'pie') {
        const hasPortSuffix = /:\d{1,5}$/.test(entityId);
        if (hasPortSuffix) {
            subjectType = 'port';
        } else if (/\b\d{1,3}(?:\.\d{1,3}){3}\b/.test(entityId) || /\[.*\]/.test(entityId) || summaryLower.includes('destination')) {
            subjectType = 'destination';
        } else {
            subjectType = 'aggregate_group';
        }
    } else if (sourceSurface.includes('file')) {
        subjectType = 'aggregate_group';
    }
    if (normalizedView === 'trend' || normalizedView === 'timeline') {
        subjectType = 'time_bucket';
    }
    const validatedType = CTRL_SUBJECT_TYPES.has(subjectType) ? subjectType : 'event';
    const reasonText = reasons.map(reason => normalizedCtrlText(reason)).join(' ');
    const severity = normalizedCtrlText(context.severity || '');
    const validation = normalizedCtrlText(context.validation_state || '');
    const isThreat = (
        CTRL_THREAT_REASONS.has(severity)
        || CTRL_THREAT_REASONS.has(validation)
        || CTRL_THREAT_REASONS.has(stateTags.networkStatus)
        || reasonText.split(' ').some(reason => CTRL_THREAT_REASONS.has(reason))
        || reasonText.includes('malicious')
        || reasonText.includes('threat')
    );
    const policyTarget = [
        entityId,
        context.evidence_key,
        context.source_entity_id,
        context.destination,
        context.dst_host,
        context.host,
        context.ip,
        context.dst_ip,
        context.domain,
        context.rule,
        selectedEventTarget.dst_ip,
        selectedEventTarget.dns_query,
        selectedEventTarget.http_host,
        selectedEventTarget.tls_sni,
        selectedEventTarget.dst_port,
        selectedEventTarget.process,
        selectedEventTarget.app,
        selectedEventTarget.application,
    ].map(value => String(value || '').trim()).find(Boolean) || '';
    return {
        displayName: subjectName,
        summary: summary || `Network ${normalizedView || 'evidence'} subject`,
        subjectType: validatedType,
        subjectId: entityId,
        sourceView: normalizedView || 'table',
        sourceSurface: String(context.source_surface || 'network').trim(),
        openBackRoute: String(context.open_back_route || '').trim(),
        evidenceKey: String(context.evidence_key || '').trim(),
        traceId: String(context.trace_id || '').trim(),
        assessmentId: String(context.assessment_id || '').trim(),
        assessmentCategory: String(context.assessment_category || '').trim(),
        assessmentLifecycle: String(context.assessment_lifecycle || '').trim(),
        assessmentRule: String(context.assessment_rule || '').trim(),
        evidenceRefs: Array.isArray(context.evidence_refs) ? context.evidence_refs.slice() : [],
        reasons: reasons.slice(0, 8),
        tags: {
            status: stateTags.status || validation || '',
            state: stateTags.state || '',
            reason: reasons[0] || '',
        },
        isActiveProcess,
        isThreat,
        hasPolicyTarget: Boolean(policyTarget),
        statusText: String(context.validation_state || 'unvalidated').trim(),
        isRead: Boolean(context.is_read),
        isUnread: !Boolean(context.is_read),
    };
}

function networkCtrlActionTargetText(subject = {}, context = {}) {
    const values = [
        subject.subjectId,
        context.destination,
        context.dst_host,
        context.host,
        context.ip,
        context.dst_ip,
        context.domain,
        context.rule,
        context.port,
        context.dst_port,
        context.source_entity_id,
    ];
    return values.map(value => String(value || '').trim()).find(Boolean) || '';
}

function networkCtrlSubjectHasBlockTarget(subject = {}, context = {}) {
    if (['destination', 'port'].includes(subject.subjectType)) return Boolean(networkCtrlActionTargetText(subject, context));
    const targetText = networkCtrlActionTargetText(subject, context);
    return Boolean(
        targetText &&
        (
            /\b\d{1,3}(?:\.\d{1,3}){3}\b/.test(targetText) ||
            /\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b/i.test(targetText) ||
            /:\d{1,5}$/.test(targetText) ||
            /^\d{1,5}$/.test(targetText)
        )
    );
}

function networkCtrlSubjectHasQuarantineTarget(subject = {}, context = {}) {
    if (subject.subjectType === 'app_process') return true;
    if (normalizedCtrlText(subject.sourceSurface).includes('file')) return true;
    const values = [
        subject.subjectId,
        context.file_path,
        context.path,
        context.executable_path,
        context.bundle_path,
        context.app_path,
        context.artifact,
    ];
    return values.some(value => /\.(app|dylib|pkg|sh|py|js|bin|exe)$/i.test(String(value || '').trim()) || String(value || '').includes('/'));
}

function networkCtrlSubjectCanAllow(subject = {}, context = {}) {
    const hasStableTarget = Boolean(subject.hasPolicyTarget || networkCtrlActionTargetText(subject, context) || subject.evidenceKey);
    if (!hasStableTarget) return false;
    if (subject.isThreat) return true;
    const policyState = [
        subject.statusText,
        subject.tags?.status,
        subject.tags?.state,
        context.validation_state,
        context.status,
        context.result,
        ...(Array.isArray(subject.reasons) ? subject.reasons : []),
        ...(Array.isArray(context.network_reasons) ? context.network_reasons : []),
    ].map(value => normalizedCtrlText(value)).filter(Boolean).join(' ');
    return /\b(blocked|restricted|quarantined|suspicious|degraded|critical|review|untrusted|unauthorized)\b/.test(policyState);
}

function networkCtrlActionApplicability(actionId, subject = {}, context = {}) {
    if (['mark_read', 'mark_unread', 'copy', 'export', 'observe'].includes(actionId)) return true;
    if (actionId === 'restrict') return ['app_process', 'destination', 'port'].includes(subject.subjectType);
    if (actionId === 'block') return networkCtrlSubjectHasBlockTarget(subject, context);
    if (actionId === 'quarantine') return networkCtrlSubjectHasQuarantineTarget(subject, context);
    if (actionId === 'terminate') return subject.subjectType === 'app_process' && Boolean(subject.isActiveProcess);
    if (actionId === 'allow') return networkCtrlSubjectCanAllow(subject, context);
    return false;
}

function networkCtrlActionCatalog(subject, context = {}) {
    return Object.keys(CTRL_ACTION_LABELS).map(actionId => {
        const item = {
            id: actionId,
            label: CTRL_ACTION_LABELS[actionId],
            enabled: networkCtrlActionApplicability(actionId, subject, context),
            style: ['mark_read', 'mark_unread'].includes(actionId) ? 'muted' : 'default',
        };
        const action = evidenceCommandActions.find(action => normalizedCtrlText(action.id) === item.id);
        if (!action) return { ...item, enabled: false, disabled_reason: 'Backend capability unavailable.' };
        return {
            ...item,
            label: String(action.label || item.label).trim() || item.label,
            enabled: item.enabled && action.enabled !== false,
            disabled_reason: action.disabled_reason || (item.enabled ? '' : 'Not applicable to this target.'),
            source_navigation: action.source_navigation,
            required_role: action.required_role,
        };
    });
}

function networkCtrlGroupedActions(actions = []) {
    const byId = new Map(actions.map(action => [normalizedCtrlText(action.id), action]));
    return CTRL_ACTION_GROUPS.map(group => ({
        ...group,
        actions: group.actions.map(actionId => byId.get(actionId)).filter(Boolean),
    })).filter(group => group.actions.length);
}

function networkCtrlTagsHtml(subject) {
    const allTags = [];
    const pushTag = label => {
        const normalized = String(label || '').trim();
        if (normalized && !allTags.includes(normalized)) allTags.push(normalized);
    };
    if (subject.tags.status) pushTag(`status: ${subject.tags.status}`);
    if (subject.tags.state) pushTag(`state: ${subject.tags.state}`);
    subject.reasons.forEach(reason => pushTag(`reason: ${String(reason || '').trim()}`));
    return allTags.length ? '<div class="action-sidebar-tag-row">' + allTags.map(tag => '<span>' + escapeHtml(tag) + '</span>').join('') + '</div>' : '';
}

function routeCtrlToNetworkView(view, routeTarget = {}) {
    const targetMode = normalizedCtrlText(view);
    const mode = controlPanelNetworkView(targetMode);
    if (!mode) return;
    const resolvedTarget = {
        ...(routeTarget && typeof routeTarget === 'object' ? routeTarget : {}),
        view: targetMode,
    };
    networkActionFilterReason = '';
    setPinnedNetworkTableSelection('');
    if (mode === 'table') {
        const pinEntity = networkCtrlRouteTableEntityId(resolvedTarget);
        setPinnedNetworkTableSelection(pinEntity, findNetworkTableEventByEntityId(pinEntity));
        if (pinEntity) {
            resolvedTarget.entityId = pinEntity;
        }
    } else {
        setPinnedNetworkTableSelection('');
    }
    networkCtrlRouteTarget = resolvedTarget;
    persistNetworkViewMode(mode);
    showView('network');
    if (mode === 'table') {
        currentNetworkData = currentNetworkTableData || currentNetworkData || networkHeaderTableData();
        renderNetworkDisplay();
        return;
    }
    const projectionView = networkProjectionViewForMode(mode);
    if (!projectionView) {
        currentNetworkData = currentNetworkTableData || currentNetworkData || networkHeaderTableData();
        renderNetworkDisplay();
        return;
    }
    if (!currentNetworkData && !currentNetworkTableData && !currentNetworkProjectionData) {
        currentNetworkData = networkHeaderTableData();
        renderNetworkDisplay();
    }
    deferNetworkProjectionLoad(mode, true);
}

function networkCtrlRouteTableEntityId(routeTarget = {}) {
    const events = Array.isArray(currentNetworkTableData?.events) && currentNetworkTableData.events.length
        ? currentNetworkTableData.events
        : (Array.isArray(currentNetworkData?.events) ? currentNetworkData.events : []);
    if (!events.length) return '';
    const explicitEntityId = String(routeTarget.entityId || routeTarget.eventId || routeTarget.findingId || '').trim();
    if (explicitEntityId) {
        const explicitMatch = events.find(event => networkEvidenceEntityId(event) === explicitEntityId);
        if (explicitMatch) return networkEvidenceEntityId(explicitMatch);
    }
    const destinationText = String(routeTarget.destination || '').trim().toLowerCase();
    const ownerText = String(routeTarget.owner || '').trim().toLowerCase();
    const subjectType = normalizedCtrlText(routeTarget.subjectType || '');
    const portHint = String(routeTarget.port || '').trim();
    const normalizedPortHint = portHint ? String(Number(portHint) || '').trim() : '';
    const selected = events.find(event => {
        const matchValues = [
            routeTarget.owner,
            networkEventDestination(event),
            event.destination,
            event.destination_display,
            event.dst_host,
            event.dst_ip,
            networkEventSource(event),
            event.process,
            event.app,
            event.application,
            String(event.dst_port || ''),
        ].map(item => String(item || '').trim().toLowerCase());
        if (normalizedPortHint) {
            if (matchValues.includes(normalizedPortHint)) return true;
        }
        if (subjectType === 'destination' && destinationText) {
            return matchValues.some(value => value && (value.includes(destinationText) || destinationText.includes(value)));
        }
        if (subjectType === 'port' && destinationText) {
            return destinationText === event.dst_port || String(event.dst_port || '') === destinationText;
        }
        if (destinationText) {
            return matchValues.some(value => value && (value.includes(destinationText) || destinationText.includes(value)));
        }
        if (ownerText) {
            return String(event.process || event.app || event.application || '').toLowerCase() === ownerText;
        }
        return false;
    });
    return selected ? networkEvidenceEntityId(selected) : '';
}

function networkCtrlRouteTargetEntityId(routeTarget = {}) {
    return networkCtrlRouteTableEntityId(routeTarget);
}
function cssSafeNetworkSelector(value = '') {
    const candidate = String(value || '');
    try {
        if (window.CSS && typeof window.CSS.escape === 'function') {
            return window.CSS.escape(candidate);
        }
    } catch (error) {
        // use fallback on older browsers.
    }
    return candidate.replace(/[!"#$%&'()*+,./:;<=>?@[\\\]^`{|}~]/g, '\\$&');
}

function findNetworkCtrlRouteTargetElement(view, entityId = '', fallbackText = '') {
    const lookup = String(entityId || fallbackText || '').trim();
    if (!view || !lookup) return null;
    const scopeClass = view === 'findings'
        ? '.network-findings-window'
        : '.network-' + view;
    const selector = scopeClass + ' [data-evidence-entity-id="' + cssSafeNetworkSelector(lookup) + '"]';
    const exact = byId('network-results')?.querySelector(selector);
    if (exact) return exact;
    const normalizedLookup = normalizedCtrlText(lookup).replace(/[^a-z0-9]+/g, ' ');
    const candidates = Array.from(byId('network-results')?.querySelectorAll(scopeClass + ' [data-evidence-entity-id]') || []);
    return candidates.find(element => {
        const candidate = normalizeCtrlSubjectName(element.getAttribute('data-evidence-entity-id') || '');
        const relatedIds = String(element.getAttribute('data-evidence-related-ids') || '')
            .split('|')
            .map(value => normalizeCtrlSubjectName(value))
            .filter(Boolean);
        if (relatedIds.includes(lookup)) return true;
        if (!candidate) return false;
        const normalizedCandidate = normalizedCtrlText(candidate).replace(/[^a-z0-9]+/g, ' ');
        if (relatedIds.some(value => normalizedCtrlText(value).replace(/[^a-z0-9]+/g, ' ') === normalizedLookup)) return true;
        return (
            normalizedCandidate === normalizedLookup ||
            normalizedCandidate.includes(normalizedLookup) ||
            normalizedLookup.includes(normalizedCandidate)
        );
    }) || null;
}

function readNetworkCtrlRouteTarget(element = null) {
    if (!element || !element.dataset) return null;
    const target = {
        view: String(element.dataset.ctrlRoute || '').trim(),
        entityId: String(element.dataset.ctrlRouteEntityId || '').trim(),
        sourceSurface: String(element.dataset.ctrlRouteSourceSurface || '').trim(),
        sourceView: String(element.dataset.ctrlRouteSourceView || '').trim(),
        sourceRef: String(element.dataset.ctrlRouteSourceRef || '').trim(),
        destination: String(element.dataset.ctrlRouteDestination || '').trim(),
        eventId: String(element.dataset.ctrlRouteEventId || '').trim(),
        findingId: String(element.dataset.ctrlRouteFindingId || '').trim(),
        owner: String(element.dataset.ctrlRouteOwner || '').trim(),
        subjectType: String(element.dataset.ctrlRouteSubjectType || '').trim(),
    };
    return Object.values(target).some(value => value)
        ? target
        : null;
}

function handleActionSidebarRouteClick(event) {
    if (!event || !actionSidebarOpen) return;
    const target = event.target;
    if (!target || !(target instanceof Element)) return;
    const sidebar = byId('action-sidebar');
    if (!sidebar) return;
    const routeButton = target.closest('[data-ctrl-route]');
    if (!routeButton || !sidebar.contains(routeButton)) return;
    event.preventDefault();
    const routeTarget = readNetworkCtrlRouteTarget(routeButton);
    routeCtrlToNetworkView(routeButton.dataset.ctrlRoute || '', routeTarget || {});
}

function ensureNetworkTablePinnedRowAtTop(tbody, entityId = '') {
    if (!tbody || !entityId) return;
    tbody.querySelectorAll('tr.network-row-evidence.network-row-pinned').forEach(pinnedRow => {
        pinnedRow.classList.toggle('network-row-pinned', pinnedRow.dataset.evidenceEntityId === entityId);
    });
    const row = tbody.querySelector('tr.network-row-evidence[data-evidence-entity-id="' + cssSafeNetworkSelector(entityId) + '"]');
    if (!row) return;
    row.classList.add('network-row-pinned');
    if (tbody.firstElementChild === row) return;
    tbody.removeChild(row);
    tbody.insertBefore(row, tbody.firstElementChild);
}

function applyNetworkCtrlRouteTarget() {
    const target = networkCtrlRouteTarget;
    if (!target || !target.view) return;
    const view = normalizedCtrlText(target.view);
    let applied = false;
    if (view === 'table') {
        const pinnedEntityId = networkCtrlRouteTargetEntityId(target);
        if (pinnedEntityId) {
            setPinnedNetworkTableSelection(pinnedEntityId, findNetworkTableEventByEntityId(pinnedEntityId));
            const table = byId('network-results')?.querySelector('.network-table');
            const row = table?.querySelector(`tr.network-row-evidence[data-evidence-entity-id="${cssSafeNetworkSelector(pinnedEntityId)}"]`);
            if (row) {
                const tbody = table?.querySelector('tbody');
                if (tbody) ensureNetworkTablePinnedRowAtTop(tbody, pinnedEntityId);
                row.classList.add('route-highlight');
                row.scrollIntoView({ block: 'center', behavior: 'smooth' });
                applied = true;
            }
        } else {
            applied = true;
        }
    } else if (view === 'findings') {
        const findingId = String(target.findingId || target.entityId || target.eventId || '').trim();
        const finding = findNetworkCtrlRouteTargetElement('findings', findingId);
        if (finding) {
            finding.setAttribute('open', 'open');
            finding.classList.add('route-highlight');
            finding.scrollIntoView({ block: 'center', behavior: 'smooth' });
            applied = true;
        }
    } else if (view === 'timeline') {
        const eventId = String(target.eventId || target.entityId || '').trim();
        const marker = findNetworkCtrlRouteTargetElement('timeline', eventId);
        if (marker) {
            marker.classList.add('route-highlight');
            marker.scrollIntoView({ block: 'center', behavior: 'smooth', inline: 'center' });
            applied = true;
        }
    } else if (view === 'distribution' || view === 'pie') {
        const owner = String(target.owner || target.entityId || target.destination || '').trim();
        const row = owner
            ? findNetworkCtrlRouteTargetElement('pie', owner) || findNetworkCtrlRouteTargetElement('distribution', owner) || byId('network-results')?.querySelector('.network-pie-slice[data-pie-label="' + cssSafeNetworkSelector(owner) + '"]')
            : null;
        if (row) {
            row.classList.add('selected');
            row.scrollIntoView({ block: 'center', behavior: 'smooth', inline: 'center' });
            applied = true;
        }
    }
    if (applied) networkCtrlRouteTarget = null;
}

function executeCtrlAction(actionId) {
    if (!evidenceCommandContext) return;
    const normalized = String(actionId || '').trim();
    if (!normalized) return;
    const selectedAction = evidenceCommandActions.find(action => normalizedCtrlText(action.id) === normalized);
    if (selectedAction && selectedAction.enabled !== false) {
        executeEvidenceAction(selectedAction, 'ctrl');
        return;
    }
    const selected = evidenceCommandActions.find(action => String(action.id || '') === normalized);
    if (!selected) {
        updateCurrentEvidenceCommandSnapshot({ commandStatus: `Action '${normalized}' is not currently available for this evidence selection.` });
        renderActionSidebar();
        return;
    }
    executeEvidenceAction(selected);
}

function evidenceSidebarEssentialHtml(context = {}, snapshot = null) {
    const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context);
    const subject = snapshotState.subject || buildNetworkCtrlSubject(context);
    const loadingCopy = actionSidebarDeferredDetailsReady
        ? ''
        : '<p class="action-sidebar-meta">Loading control details…</p>';
    return (
        '<section class="action-sidebar-card action-sidebar-card-compact">' +
        '<section class="action-sidebar-section">' +
        '<h3>Selection</h3>' +
        '<p>' + escapeHtml(subject.displayName || 'Unknown app') + '</p>' +
        '</section>' +
        (subject.summary
            ? '<section class="action-sidebar-section"><h3>Summary</h3><p>' + escapeHtml(subject.summary) + '</p></section>'
            : '') +
        networkCtrlTagsHtml(subject) +
        loadingCopy +
        '</section>'
    );
}

function evidenceSidebarSections(context = {}, networkData = {}, snapshot = null) {
    const snapshotState = snapshot || currentEvidenceCommandSnapshot(context) || buildEvidenceCommandSnapshot(context, { networkData });
    const subject = snapshotState.subject || buildNetworkCtrlSubject(context);
    const actions = networkCtrlActionCatalog(subject, context);
    const insightReceiptId = String(snapshotState.insightReceipt || snapshotState.insightResult?.audit?.id || '').trim();
    const actionButtons = networkCtrlGroupedActions(actions).map(group => (
        '<section class="action-sidebar-action-group" data-action-group="' + escapeHtml(group.key) + '">' +
        '<h3 class="action-sidebar-action-group-title">' + escapeHtml(group.label) + '</h3>' +
        '<ul class="action-sidebar-action-list">' + group.actions.map(action => (
            '<li class="action-sidebar-action-item">' +
            '<button type="button" class="action-sidebar-action-btn" data-ctrl-more-action="' + escapeHtml(action.id) + '"' + (action.enabled ? '' : ' disabled') + '>' +
            '<span>' + escapeHtml(action.label) + '</span>' +
            (!action.enabled && action.disabled_reason ? '<small>' + escapeHtml(action.disabled_reason) + '</small>' : '') +
            '</button>' +
            '</li>'
        )).join('') + '</ul>' +
        '</section>'
    )).join('');
    const insightHtml = evidenceInsightHtml(context, snapshotState);
    return (
        '<section class="action-sidebar-card">' +
        insightHtml +
        '<template data-ctrl-more-menu-content>' +
        actionButtons +
        '</template>' +
        (insightReceiptId
            ? '<section class="action-sidebar-section action-sidebar-footer">' +
            '<div class="action-sidebar-insight-receipt">' +
            '<h3>Source ID</h3>' +
            '<p class="action-sidebar-meta"><code>' + escapeHtml(insightReceiptId) + '</code></p>' +
            '</div>' +
            '</section>'
            : '') +
        networkTechnicalDetailsHtml(snapshotState.technicalData || {}, snapshotState.technicalEvents || []) +
        '</section>'
    );
}

function renderEvidenceActionSidebar() {
    const body = byId('action-sidebar-body');
    const sidebar = byId('action-sidebar');
    const toggle = byId('action-sidebar-toggle');
    if (!body || !sidebar || !toggle) return;
    syncActionSidebarShell();
    if (!actionSidebarOpen) return;
    const networkVisible = !byId('network')?.hidden;
    actionSidebarPage = networkVisible ? 'network' : actionSidebarPage;
    const networkData = currentEvidenceCommandNetworkData();
    const snapshot = evidenceCommandContext
        ? (currentEvidenceCommandSnapshot(evidenceCommandContext) || buildEvidenceCommandSnapshot(evidenceCommandContext, { networkData }))
        : null;
    if (snapshot && snapshot.context === evidenceCommandContext) {
        evidenceCommandSnapshot = snapshot;
    }
    const headerHtml = evidenceCommandContext ? networkCtrlHeaderHtml(evidenceCommandContext, snapshot) : '';
    let bodyHtml = '';
    if (evidenceCommandLoading) {
        bodyHtml = '<p class="action-sidebar-empty">Loading evidence action context…</p>';
    } else if (!evidenceCommandContext) {
        const recover = evidenceCommandError
            ? ('<p class="action-sidebar-empty">' + escapeHtml(evidenceCommandError) + '</p>')
            : '<p class="action-sidebar-empty">Select Network evidence from Table, Findings, Trend, Distribution, or Timeline to review or control it.</p>';
        bodyHtml = (
            '<section class="action-sidebar-card">' +
            recover +
            (evidenceCommandError ? '<p class="action-sidebar-meta">Recovery: open the source view from the evidence row and retry the action.</p>' : '') +
            '</section>'
        );
    } else {
        bodyHtml = actionSidebarDeferredDetailsReady
            ? evidenceSidebarSections(evidenceCommandContext, networkData, snapshot)
            : evidenceSidebarEssentialHtml(evidenceCommandContext, snapshot);
    }
    if (evidenceCommandStatus) {
        bodyHtml = '<p class="action-sidebar-status">' + escapeHtml(evidenceCommandStatus) + '</p>' + bodyHtml;
    }
    const fullBodyHtml = headerHtml + bodyHtml;
    if (fullBodyHtml !== actionSidebarLastBodyHtml) {
        body.innerHTML = fullBodyHtml;
        actionSidebarLastBodyHtml = fullBodyHtml;
    }
    bindEvidenceActionSidebar();
    if (evidenceCommandContext && !evidenceCommandLoading && !actionSidebarDeferredDetailsReady) {
        scheduleActionSidebarDeferredDetails(actionSidebarDeferredRenderRequestId);
    }
}

function syncActionSidebarShell() {
    const sidebar = byId('action-sidebar');
    const toggle = byId('action-sidebar-toggle');
    if (!sidebar || !toggle) return;
    sidebar.setAttribute('aria-hidden', actionSidebarOpen ? 'false' : 'true');
    toggle.setAttribute('aria-expanded', actionSidebarOpen ? 'true' : 'false');
    // Product lock: the control keeps one stable label; state belongs to aria-expanded and panel visibility.
    toggle.textContent = 'ctrl';
    toggle.setAttribute('aria-label', actionSidebarOpen ? 'Close control center' : 'Open control center');
    sidebar.classList.toggle('action-sidebar-open', actionSidebarOpen);
    toggle.classList.toggle('action-sidebar-open', actionSidebarOpen);
}

function renderActionSidebar() {
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('sidebar');
        return false;
    }
    renderEvidenceActionSidebar();
    return true;
}

function setActionSidebarOpen(open) {
    const nextOpen = Boolean(open);
    if (nextOpen && filesMediationBoardOpen) {
        setFilesMediationBoardOpen(false, { restoreFocus: false });
    }
    actionSidebarOpen = nextOpen;
    if (actionSidebarOpen) {
        if (evidenceCommandSnapshot && evidenceCommandSnapshot.version !== actionSidebarRequestEpoch) {
            updateCurrentEvidenceCommandSnapshot({ version: actionSidebarRequestEpoch });
        }
        clearNetworkTableFlushTimer();
        syncActionSidebarShell();
        scheduleActionSidebarRender();
        return;
    }
    clearActionSidebarRenderSchedule();
    clearActionSidebarDeferredDetails();
    actionSidebarDeferredDetailsReady = false;
    actionSidebarRequestEpoch += 1;
    evidenceInsightRequestEpoch += 1;
    evidenceActionRequestEpoch += 1;
    evidenceCommandLoading = false;
    evidenceInsightLoading = false;
    evidenceInsightRequestKey = '';
    syncActionSidebarShell();
    if (networkHeaderRenderPending) {
        flushNetworkHeaderRender({ force: true });
    }
    if (networkViewMode === 'table' && networkTableUiBuffer.length) {
        flushNetworkTableRender({ force: true });
    }
}

function bindEvidenceActionSidebar() {
    const sidebar = byId('action-sidebar');
    if (!sidebar) return;
    if (sidebar.dataset.ctrlRouteBound !== '1') {
        sidebar.addEventListener('click', handleActionSidebarRouteClick);
        sidebar.dataset.ctrlRouteBound = '1';
    }
    const menu = sidebar.querySelector('[data-ctrl-more-menu]');
    const menuToggle = sidebar.querySelector('[data-ctrl-menu-toggle]');
    const menuContent = sidebar.querySelector('[data-ctrl-more-menu-content]');
    if (menu && menuContent && menu.innerHTML !== menuContent.innerHTML) {
        menu.innerHTML = menuContent.innerHTML;
    }
    if (menu && menuToggle && menuToggle.dataset.bound !== '1') {
        menu.hidden = true;
        menuToggle.dataset.bound = '1';
        menuToggle.setAttribute('aria-expanded', 'false');
        menuToggle.setAttribute('aria-label', 'More actions');
        menuToggle.addEventListener('click', () => {
            const isHidden = menu.hasAttribute('hidden');
            menu.hidden = !isHidden;
            menuToggle.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        });
    }
    sidebar.querySelectorAll('[data-ctrl-more-action]').forEach(button => {
        if (button.dataset.bound === '1') return;
        button.dataset.bound = '1';
        button.addEventListener('click', () => {
            const action = button.dataset.ctrlMoreAction || '';
            executeCtrlAction(action);
        });
    });
    sidebar.querySelectorAll('[data-evidence-action-id]').forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = '1';
        button.addEventListener('click', () => {
            if (!evidenceCommandContext || !button.dataset.evidenceActionId) return;
            const action = evidenceCommandActions.find(item => String(item.id || '') === button.dataset.evidenceActionId);
            if (!action) return;
            executeEvidenceAction(action, button.dataset.evidenceActionOrigin || '');
        });
    });
    const back = sidebar.querySelector('[data-evidence-open-back]');
    if (!back || back.dataset.bound) return;
    back.dataset.bound = '1';
    back.addEventListener('click', () => {
        setCurrentEvidenceCommandSnapshot(null);
        evidenceCommandError = '';
        evidenceCommandLoading = false;
        evidenceInsightLoading = false;
        evidenceInsightRequestKey = '';
        actionSidebarRequestEpoch += 1;
        evidenceInsightRequestEpoch += 1;
        evidenceActionRequestEpoch += 1;
        actionSidebarLastBodyHtml = '';
        renderActionSidebar();
    });
}

function renderNetworkActionDigest() {
    renderActionSidebar();
}

function focusNetworkActionDigest(reason) {
    networkActionFilterReason = reason ? String(reason).trim() : '';
    setActionSidebarOpen(true);
    renderNetworkDisplay();
    byId('action-sidebar')?.focus?.({ preventScroll: true });
}

function networkTableVisibleRows(events, options = {}) {
    const rows = Array.isArray(events) ? events.slice() : [];
    const filterReason = String(options.filterReason || '').trim();
    const pinnedEntityId = String(options.pinnedEntityId || networkTablePinnedEntityId || '').trim();
    const pinnedSnapshot = pinnedEntityId ? syncNetworkTablePinnedSnapshot(rows) : null;
    let filteredRows = filterReason
        ? rows.filter(event => networkReasonMatchesEvent(filterReason, event))
        : rows;
    if (networkTableSort.key && networkTableSort.direction) {
        const direction = networkTableSort.direction === 'desc' ? -1 : 1;
        filteredRows = filteredRows.slice().sort((left, right) => {
            const leftValue = networkTableSortValue(left, networkTableSort.key);
            const rightValue = networkTableSortValue(right, networkTableSort.key);
            const comparison = networkTableSortCompare(leftValue, rightValue);
            if (comparison) return comparison * direction;
            return networkConnectionIdentityKey(left).localeCompare(networkConnectionIdentityKey(right));
        });
    }
    const pinnedIndex = pinnedEntityId
        ? filteredRows.findIndex(event => networkEvidenceEntityId(event) === pinnedEntityId)
        : -1;
    if (pinnedIndex >= 0 && pinnedSnapshot) {
        filteredRows[pinnedIndex] = pinnedSnapshot;
    }
    let orderedRows = pinnedIndex > 0
        ? [
            filteredRows[pinnedIndex],
            ...filteredRows.slice(0, pinnedIndex),
            ...filteredRows.slice(pinnedIndex + 1),
        ]
        : filteredRows;
    if (pinnedIndex < 0 && pinnedSnapshot) {
        orderedRows = [pinnedSnapshot, ...orderedRows];
    }
    const limit = Math.max(1, Number(options.limit || NETWORK_TABLE_DOM_ROW_LIMIT) || NETWORK_TABLE_DOM_ROW_LIMIT);
    if (orderedRows.length <= limit) return orderedRows;
    if (pinnedIndex >= 0 || (pinnedIndex < 0 && pinnedSnapshot)) {
        return [orderedRows[0], ...orderedRows.slice(1, limit)];
    }
    return orderedRows.slice(0, limit);
}

function networkTableSortValue(event = {}, key = '') {
    if (key === 'time') return networkEventTimestampMs(event);
    if (key === 'app') return networkEventAppName(event);
    if (key === 'source') return networkEventSource(event);
    if (key === 'destination') return networkEventDestination(event);
    if (key === 'protocol') return event.protocol || 'Network connection';
    if (key === 'port') return event.dst_port || event.port || '';
    if (key === 'translation') return networkEventMeaning(event);
    return '';
}

function networkTableSortCompare(left, right) {
    if (typeof left === 'number' && typeof right === 'number') return left - right;
    const leftText = String(left ?? '');
    const rightText = String(right ?? '');
    const leftNumber = Number(leftText);
    const rightNumber = Number(rightText);
    if (leftText && rightText && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
        return leftNumber - rightNumber;
    }
    return leftText.localeCompare(rightText, undefined, { numeric: true, sensitivity: 'base' });
}

function cycleNetworkTableSort(key = '') {
    if (!NETWORK_TABLE_COLUMNS.some(column => column.key === key)) return;
    if (key === 'time') {
        networkTableSort = {
            key: 'time',
            direction: networkTableSort.key === 'time' && networkTableSort.direction === 'asc' ? 'desc' : 'asc',
        };
    } else if (networkTableSort.key !== key) {
        networkTableSort = { key, direction: 'asc' };
    } else if (networkTableSort.direction === 'asc') {
        networkTableSort = { key, direction: 'desc' };
    } else {
        networkTableSort = { key: 'time', direction: 'desc' };
    }
    updateNetworkTableSortHeaders();
    flushNetworkTableRender({ force: true });
}

function updateNetworkTableSortHeaders(table = document.querySelector('.network-table')) {
    if (!table) return;
    table.querySelectorAll('th[data-column-key]').forEach(header => {
        const active = header.dataset.columnKey === networkTableSort.key && Boolean(networkTableSort.direction);
        header.setAttribute('aria-sort', active ? (networkTableSort.direction === 'asc' ? 'ascending' : 'descending') : 'none');
        header.dataset.sortDirection = active ? networkTableSort.direction : '';
    });
}

function enableNetworkColumnSort() {
    const table = document.querySelector('.network-table');
    if (!table) return;
    table.querySelectorAll('th[data-column-key]').forEach(header => {
        if (header.dataset.sortBound === '1') return;
        header.dataset.sortBound = '1';
        header.tabIndex = 0;
        header.addEventListener('click', event => {
            if (event.target.closest('.network-column-resizer')) return;
            cycleNetworkTableSort(header.dataset.columnKey || '');
        });
        header.addEventListener('keydown', event => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            cycleNetworkTableSort(header.dataset.columnKey || '');
        });
    });
    updateNetworkTableSortHeaders(table);
}

function networkTableRowSignature(event = {}) {
    return [
        networkEvidenceEntityId(event),
        event.timestamp || '',
        event.last_seen || '',
        event.packet_count || '',
        event.summary || '',
        event.reason || '',
        event.meaning || '',
        event.category || '',
        event.__networkPinnedStale ? 'inactive' : 'active',
    ].map(value => String(value ?? '')).join('|');
}

function networkTableShouldDeferFlush() {
    const networkHidden = Boolean(byId('network')?.hidden);
    return networkShouldSuspendDomWork() || networkHidden || networkViewMode !== 'table';
}

function clearNetworkTableFlushTimer() {
    if (!networkTableFlushTimer) return;
    window.clearTimeout(networkTableFlushTimer);
    networkTableFlushTimer = null;
}

function scheduleNetworkTableFlush() {
    if (networkTableShouldDeferFlush()) return;
    if (networkViewMode !== 'table') return;
    if (networkTableFlushTimer) return;
    networkTableFlushTimer = window.setTimeout(() => {
        networkTableFlushTimer = null;
        flushNetworkTableRender();
    }, NETWORK_TABLE_FLUSH_MS);
}

function createNetworkTableRowElement(event, reason = '') {
    const newRow = document.createElement('tbody');
    newRow.innerHTML = networkTableRowHtml(event, reason);
    return newRow.querySelector('tr');
}

function createNetworkTableEmptyRow() {
    const row = document.createElement('tr');
    row.className = 'network-table-empty-row';
    row.setAttribute('aria-hidden', 'true');
    NETWORK_TABLE_COLUMNS.forEach(() => row.appendChild(document.createElement('td')));
    return row;
}

function fillNetworkTableViewportRows(tbody) {
    if (!tbody) return;
    tbody.querySelectorAll('tr.network-table-empty-row').forEach(row => row.parentElement?.removeChild(row));
    const liveRows = tbody.querySelectorAll('tr.network-row-evidence').length;
    const viewportHeight = Number(tbody.clientHeight || 326);
    const sampleRow = tbody.querySelector('tr.network-row-evidence');
    const rowHeight = Math.max(1, Number(sampleRow?.getBoundingClientRect?.().height || 33));
    const rowCapacity = Math.max(1, Math.ceil(viewportHeight / rowHeight));
    for (let index = liveRows; index < rowCapacity; index += 1) {
        tbody.appendChild(createNetworkTableEmptyRow());
    }
}

function patchNetworkTableBody(rows, reason = '') {
    const table = document.querySelector('.network-table');
    const tbody = table?.querySelector('tbody');
    if (!tbody) return false;
    const existingRows = new Map(
        Array.from(tbody.querySelectorAll('tr.network-row-evidence')).map(row => [row.dataset.evidenceEntityId || '', row])
    );
    const fragment = document.createDocumentFragment();
    rows.forEach(event => {
        const key = networkEvidenceEntityId(event);
        let row = existingRows.get(key) || null;
        if (row) {
            const nextRow = createNetworkTableRowElement(event, reason);
            if (nextRow) {
                row.setAttribute('class', nextRow.className);
                row.innerHTML = nextRow.innerHTML;
                Array.from(nextRow.attributes).forEach(attribute => {
                    row.setAttribute(attribute.name, attribute.value);
                });
            }
            row.dataset.evidenceBound = '0';
        } else {
            row = createNetworkTableRowElement(event, reason);
        }
        if (!row) return;
        fragment.appendChild(row);
        existingRows.delete(key);
    });
    tbody.replaceChildren(fragment);
    fillNetworkTableViewportRows(tbody);
    bindNetworkEvidenceRows(tbody);
    if (rows.length && !networkStartupInstrumentation.firstRowRendered) {
        networkStartupInstrumentation.firstRowRendered = true;
        logNetworkStartup('first_table_row_rendered', {
            expectedRows: rows.length,
            renderedRows: tbody.querySelectorAll('tr.network-row-evidence').length,
        });
    }
    const pinnedEntityId = String(networkTablePinnedEntityId || '').trim();
    if (pinnedEntityId) ensureNetworkTablePinnedRowAtTop(tbody, pinnedEntityId);
    networkTableRenderState = {
        rowKeys: rows.map(event => networkEvidenceEntityId(event)),
        rowSignatures: rows.map(networkTableRowSignature),
        lastReason: reason,
        lastFilterReason: String(networkActionFilterReason || '').trim(),
    };
    return true;
}

function flushNetworkTableRender(options = {}) {
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender('table');
        return false;
    }
    if (!options.force && networkTableShouldDeferFlush()) return false;
    const results = byId('network-results');
    if (!results) return false;
    const data = currentNetworkTableData || currentNetworkData || networkHeaderTableData();
    const events = Array.isArray(data?.events) ? data.events : [];
    const reason = currentNetworkTags.reasons?.[0] || '';
    const filterReason = networkActionFilterReason && networkActionFilterReason === reason ? reason : '';
    const rows = networkTableVisibleRows(events, {
        filterReason,
        pinnedEntityId: networkTablePinnedEntityId,
        limit: NETWORK_TABLE_DOM_ROW_LIMIT,
    });
    const canPatch = Boolean(results.querySelector('.network-table tbody'));
    if (!canPatch) {
        renderNetworkDisplay();
        return true;
    }
    const changed = filterReason !== networkTableRenderState.lastFilterReason ||
        reason !== networkTableRenderState.lastReason ||
        rows.length !== networkTableRenderState.rowKeys.length ||
        rows.some((event, index) => networkEvidenceEntityId(event) !== networkTableRenderState.rowKeys[index]) ||
        rows.some((event, index) => networkTableRowSignature(event) !== networkTableRenderState.rowSignatures?.[index]);
    if (!changed) {
        networkTableUiBuffer = [];
        return true;
    }
    if (!patchNetworkTableBody(rows, reason)) return false;
    if (!networkTableShouldDeferFlush()) {
        refreshNetworkMetadataFooter();
    }
    networkTableUiBuffer = [];
    return true;
}

function mergeNetworkLiveEventIntoTableData(data = {}, event = {}, observedAt = Date.now()) {
    const baseData = data && typeof data === 'object' ? data : {};
    const events = Array.isArray(baseData.events) ? baseData.events.slice() : [];
    const connectionKey = networkConnectionIdentityKey(event);
    const existingIndex = events.findIndex(item => networkConnectionIdentityKey(item) === connectionKey);
    const mergedEvent = {
        ...networkMergeConnectionEvent(existingIndex >= 0 ? events[existingIndex] : null, event),
        __networkLiveObservedAt: observedAt,
    };
    if (existingIndex >= 0) {
        events[existingIndex] = mergedEvent;
    } else {
        events.unshift(mergedEvent);
    }
    events.sort((left, right) => networkEventTimestampMs(right) - networkEventTimestampMs(left));
    const pinnedEntityId = String(networkTablePinnedEntityId || '').trim();
    if (pinnedEntityId) {
        const pinnedIndex = events.findIndex(item => networkEvidenceEntityId(item) === pinnedEntityId);
        if (pinnedIndex > 0) {
            const [pinnedRow] = events.splice(pinnedIndex, 1);
            if (pinnedRow) events.unshift(pinnedRow);
        }
    }
    const boundedCount = Math.min(events.length, NETWORK_LIVE_EVENT_LIMIT);
    return {
        mergedEvent,
        data: {
            ...baseData,
            state: 'CAPTURING',
            events: events.slice(0, NETWORK_LIVE_EVENT_LIMIT),
            event_count: boundedCount,
            activeConnectionCount: boundedCount,
            total_connection_count: boundedCount,
            displayed_connection_count: boundedCount,
            summary: {
                ...(baseData.summary || {}),
                reason: 'events_observed',
                counts: { ...((baseData.summary || {}).counts || {}), connections: boundedCount },
            },
        },
    };
}

function appendNetworkLiveEvent(event, eventMeta = {}) {
    if (!event || typeof event !== 'object') return false;
    const continuity = observeNetworkStreamContinuity(event, eventMeta, { advance: false });
    const canonicalEvent = continuity.cursor && !event.cursor
        ? { ...event, cursor: continuity.cursor }
        : event;
    const deliveryKey = networkLiveDeliveryKey(canonicalEvent, {
        ...eventMeta,
        epoch: continuity.epoch,
    });
    if (!rememberNetworkLiveDelivery(deliveryKey)) return false;
    if (continuity.cursor) {
        advanceNetworkAppliedCursor(continuity.cursor, continuity.epoch, { ordered: true });
    }
    const observedAt = Date.now();
    const establishedLiveEvidence = !networkLiveEvidenceEstablished;
    networkLiveEvidenceEstablished = true;
    if (establishedLiveEvidence) setNetworkPagePhase('ready', 'live-evidence');
    networkLiveLastEventAt = observedAt;
    networkLiveEventOrdinal += 1;
    networkLiveReplayBuffer.push({
        ordinal: networkLiveEventOrdinal,
        cursor: continuity.cursor,
        epoch: continuity.epoch,
        deliveryKey,
        observedAt,
        event: { ...canonicalEvent },
    });
    if (networkLiveReplayBuffer.length > NETWORK_LIVE_REPLAY_LIMIT) {
        networkLiveReplayBuffer = networkLiveReplayBuffer.slice(-NETWORK_LIVE_REPLAY_LIMIT);
    }
    const data = currentNetworkTableData && typeof currentNetworkTableData === 'object'
        ? currentNetworkTableData
        : (currentNetworkData && typeof currentNetworkData === 'object' ? currentNetworkData : {});
    const merged = mergeNetworkLiveEventIntoTableData(data, canonicalEvent, observedAt);
    const mergedEvent = merged.mergedEvent;
    currentNetworkTableData = {
        ...merged.data,
        assessments: Array.isArray(canonicalEvent.assessments)
            ? canonicalEvent.assessments.map(item => ({ ...item }))
            : (Array.isArray(merged.data.assessments) ? merged.data.assessments : []),
        assessment_refs: Array.isArray(canonicalEvent.assessment_refs)
            ? canonicalEvent.assessment_refs.slice()
            : (Array.isArray(merged.data.assessment_refs) ? merged.data.assessment_refs : []),
        assessment_summary: canonicalEvent.assessment_summary || merged.data.assessment_summary || null,
        assessment_filter: canonicalEvent.assessment_filter || merged.data.assessment_filter || null,
    };
    rememberNetworkLiveTrendTick(canonicalEvent);
    syncNetworkTablePinnedSnapshot(currentNetworkTableData.events);
    submitNetworkHeaderEvidence('live-packet', currentNetworkTableData, {
        source: 'live',
        packetAt: networkLiveLastEventAt,
        establishedLiveEvidence,
    });
    setText('network-area-status', 'Capturing');
    if (networkViewMode === 'table') {
        currentNetworkData = currentNetworkTableData;
    } else if (networkViewMode === 'bar') {
        appendNetworkLiveTrendTick();
    }
    if (networkViewMode === 'table') {
        if (networkShouldSuspendDomWork()) {
            networkTableHiddenPacketCount = Math.min(networkTableHiddenPacketCount + 1, NETWORK_LIVE_EVENT_LIMIT);
            networkVisibilityPendingHydration = true;
            markNetworkDeferredRender('table');
            return true;
        }
        networkTableUiBuffer.push(networkEvidenceEntityId(mergedEvent));
        if (networkTableUiBuffer.length > NETWORK_TABLE_DOM_ROW_LIMIT) {
            networkTableUiBuffer = networkTableUiBuffer.slice(-NETWORK_TABLE_DOM_ROW_LIMIT);
        }
        scheduleNetworkTableFlush();
    }
    return true;
}

function renderNetworkUnavailable(response = {}) {
    if (renderConsentRequired()) return;
    const summary = response?.summary && typeof response.summary === 'object' ? response.summary : {};
    const reason = networkSummaryReason(summary) || 'capture_failed';
    const httpStatus = Number(response?.__http_status || summary?.http_status || 0);
    const errorLabel = httpStatus ? `Error ${httpStatus}` : networkCaptureUnavailableCopy(summary);
    setText('network-area-status', errorLabel);
    const preservingVisibleState = currentNetworkData && currentNetworkData.state !== 'ERROR';
    if (preservingVisibleState) {
        networkEnginePanel('RECONNECTING' + (reason ? ': ' + reason : ''), 'Reconnecting', 'Refresh Network');
        submitNetworkHeaderEvidence('capture-error', currentNetworkData, { captureStatus: true });
        reportFrontendDegraded(reason);
        return;
    }
    currentNetworkData = { state: 'ERROR', events: [], summary: { reason } };
    currentNetworkTableData = currentNetworkData;
    currentNetworkProjectionData = currentNetworkData;
    networkCoordinatorRememberSnapshot(currentNetworkTableData, networkHydrationEpoch, networkSnapshotRequestId);
    networkEnginePanel(errorLabel, 'DEGRADED');
    submitNetworkHeaderEvidence('capture-error', currentNetworkData, { captureStatus: true });
    if (networkViewMode === 'table') {
        renderNetworkDisplay();
        return;
    }
    const results = byId('network-results');
    if (results) results.innerHTML = '<div class="empty-state">' + escapeHtml(errorLabel) + '</div>';
}

function renderNetworkReady(data = {}) {
    currentNetworkData = { state: 'READY', events: [], summary: data.summary || { reason: 'ready' } };
    currentNetworkTableData = currentNetworkData;
    networkCoordinatorRememberSnapshot(currentNetworkTableData, networkHydrationEpoch, networkSnapshotRequestId);
    setText('network-area-status', 'Ready');
    const button = byId('scan-network-btn');
    if (button) button.textContent = 'Scan Network';
    networkEnginePanel(
        'READY',
        'READY'
    );
    submitNetworkHeaderEvidence('ready', currentNetworkData, { captureStatus: true });
}

function networkEventTitle(event) {
    if (event.summary) return event.summary;
    if (event.dns_query) return `DNS lookup for ${event.dns_query}`;
    if (event.http_host) return `HTTP connection to ${event.http_host}`;
    if (event.tls_sni) return `TLS connection to ${event.tls_sni}`;
    const destination = event.dst_ip || 'unknown destination';
    const port = event.dst_port ? `:${event.dst_port}` : '';
    return `${event.protocol || 'Network'} packet to ${destination}${port}`;
}

function networkEventTime(event) {
    const value = event.timestamp || event.time || '';
    if (!value) return 'Unavailable';
    const numeric = Number(value);
    const date = Number.isFinite(numeric) && numeric > 0 ? new Date(numeric * 1000) : new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function networkEndpoint(host, port) {
    const hostText = String(host || '').trim();
    if (!hostText) return '';
    const portText = String(port || '').trim();
    return portText && portText !== '0' ? `${hostText}:${portText}` : hostText;
}

function networkEventSource(event) {
    return event.source_display ||
        networkEndpoint(event.src_ip, event.src_port) ||
        'Unavailable';
}

function networkEventDestination(event) {
    return event.destination_display ||
        networkEndpoint(event.dns_query || event.http_host || event.tls_sni || event.dst_ip, event.dst_port) ||
        'Unknown destination';
}

function networkEventMeaning(event) {
    return event.meaning || event.category || networkEventDetail(event);
}

function networkEventAppName(event) {
    return event.process || event.app || event.application || 'Unknown app';
}

function networkEventTarget(event) {
    const destination = event.dns_query || event.http_host || event.tls_sni || event.dst_ip || event.destination || '';
    return String(destination || '').trim() || 'an unknown destination';
}

function networkExternalServiceLabel(event) {
    const target = networkEventTarget(event).toLowerCase();
    if (target.endsWith('.cloudfront.net') || target.includes('.cloudfront.net:')) return 'a CloudFront-hosted service';
    if (target.includes('akamai') || target.includes('akadns')) return 'an Akamai-hosted content delivery service';
    return 'an external service';
}

function networkExternalActivitySummary(app, event) {
    const service = networkExternalServiceLabel(event);
    if (String(event.dst_port || '') === '443') return `${app} is securely communicating with ${service}.`;
    if (String(event.dst_port || '') === '80') return `${app} is making an unencrypted web request to ${service}.`;
    return `${app} is communicating with ${service}.`;
}

function networkSummaryExposesRawExternalDestination(event) {
    const summary = String(event.summary || '').trim().toLowerCase();
    if (!summary) return false;
    const values = [
        event.destination_display,
        event.dns_query,
        event.http_host,
        event.tls_sni,
        event.dst_ip,
    ].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean);
    const port = String(event.dst_port || '').trim();
    const valuesWithPort = port ? values.map((value) => `${value}:${port}`) : [];
    if (summary.includes(' is connecting to ') && values.concat(valuesWithPort).some((value) => summary.includes(value))) {
        return true;
    }
    if (summary.includes('.cloudfront.net') || summary.includes('akamai') || summary.includes('akadns')) return true;
    return /\b[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d+\b/.test(summary);
}

function networkEventLooksLocalDiscovery(event) {
    const target = String(event.dst_ip || event.destination_display || '').toLowerCase();
    const protocol = String(event.protocol || '').toUpperCase();
    return target.startsWith('fe80:') ||
        target.startsWith('ff02:') ||
        target.startsWith('224.0.0.') ||
        String(event.dst_port || event.src_port || '') === '5353' ||
        protocol === 'ICMPV6' ||
        String(event.category || '').toLowerCase().includes('local');
}

function networkEventPlainLanguage(event) {
    // Findings renders backend semantics first; fallback copy only covers older
    // rows that do not yet carry summary/reason fields.
    const summaryExposesRawTarget = networkSummaryExposesRawExternalDestination(event);
    if (event.summary && event.reason && !summaryExposesRawTarget) {
        return {
            summary: String(event.summary),
            reason: String(event.reason),
        };
    }
    if (event.summary && event.meaning && !summaryExposesRawTarget) {
        return {
            summary: String(event.summary),
            reason: String(event.meaning),
        };
    }
    const app = networkEventAppName(event);
    const target = networkEventTarget(event);
    const protocol = String(event.protocol || event.category || event.meaning || '').toLowerCase();
    const isSecure = protocol.includes('https') || protocol.includes('tls') || String(event.dst_port || '') === '443';
    const isPush = protocol.includes('push') || ['5223', '5228'].includes(String(event.dst_port || ''));
    const isLocal = event.status === 'Local connection' || event.category === 'Local connection' || event.dst_ip === '127.0.0.1' || event.dst_ip === '::1';

    if (isLocal || networkEventLooksLocalDiscovery(event)) {
        return {
            summary: app === 'Unknown app' ? 'Unresolved local network service traffic was observed.' : `${app} is communicating on the local network.`,
            reason: 'This is usually normal local app, device discovery, or system traffic.',
        };
    }
    if (isPush) {
        return {
            summary: `${app} is keeping a notification connection open to ${target}.`,
            reason: `This is common for apps that receive messages or alerts, but worth reviewing if you did not expect ${app} to be active.`,
        };
    }
    if (isSecure) {
        return {
            summary: networkExternalActivitySummary(app, event),
            reason: `This is normal for web-connected apps, but worth reviewing if you did not expect ${app} to be active.`,
        };
    }
    return {
        summary: networkExternalActivitySummary(app, event),
        reason: `Review this if you do not recognize the app, destination, or reason ${app} should be using the network.`,
    };
}

function networkEventTranslation(event) {
    const plain = networkEventPlainLanguage(event);
    return `${plain.summary} ${plain.reason}`;
}

function networkEventDetail(event) {
    if (event.process || event.category || event.meaning) {
        const category = event.category || event.meaning || 'Network activity';
        const process = event.process && event.process !== 'Unknown app' ? event.process : category;
        const pid = event.pid ? `PID ${event.pid}` : 'PID unavailable';
        return `${process} · ${pid} · ${category}`;
    }
    const source = [event.src_ip, event.src_port].filter(Boolean).join(':') || 'Unknown source';
    const targetName = event.dns_query || event.http_host || event.tls_sni || event.dst_ip || 'Unknown destination';
    const target = [targetName, event.dst_port].filter(Boolean).join(':');
    return `${source} -> ${target}`;
}

function networkFindingPriority(event) {
    const severity = normalizedText(event?.severity);
    if (severity === 'critical') return { key: 'critical', label: 'Critical' };
    if (severity === 'high') return { key: 'high', label: 'High' };
    if (severity === 'warning' || severity === 'medium') return { key: 'medium', label: 'Medium' };
    return { key: 'low', label: 'Low' };
}

function renderNetworkCapture(data) {
    if (renderConsentRequired()) return;
    const rawEvents = Array.isArray(data.events) ? data.events : [];
    const tableData = reconcileNetworkInventoryFromSnapshot(currentNetworkTableData, data, rawEvents);
    const events = tableData.events;
    const state = normalizeNetworkContractState(data.state);
    const summary = data.summary && typeof data.summary === 'object' ? data.summary : {};
    currentNetworkTableData = { ...tableData, state, summary: tableData.summary || {} };
    syncNetworkTablePinnedSnapshot(events);
    networkCoordinatorRememberSnapshot(currentNetworkTableData, networkHydrationEpoch, networkSnapshotRequestId);
    setText('network-area-status', networkCaptureStatusText(state, summary));
    networkEnginePanel(events.length ? `${events.length} active connections.` : networkCaptureStatusText(state, summary), state);
    submitNetworkHeaderEvidence('snapshot', currentNetworkTableData, { captureStatus: true });

    if (networkViewMode === 'table') renderNetworkDisplay();
}

function networkRawEvent(event) {
    return {
        time: networkEventTime(event),
        first_seen: event.first_seen || '',
        last_seen: event.last_seen || event.timestamp || '',
        app: networkEventAppName(event),
        source: networkEventSource(event),
        destination: networkEventDestination(event),
        protocol: event.protocol || 'Network connection',
        port: event.dst_port || 'Unavailable',
        connection_id: event.connection_id || '',
        packet_count: event.packet_count || 1,
        pid: event.pid || 'Unavailable',
        socket_state: event.socket_state || 'Unavailable',
        socket_role: event.socket_role || 'Unavailable',
        socket_name: event.socket_name || '',
        packet_index: event.packet_index ?? null,
        packet_length: event.packet_length ?? null,
        raw_packet_events: Array.isArray(event.raw_packet_events) ? event.raw_packet_events : [],
    };
}

function networkRawMetadataPayload(data, events) {
    const visibleEvents = Array.isArray(events) ? events : [];
    const reason = currentNetworkTags.reasons?.[0] || '';
    const affectedEvents = reason ? networkAffectedEvents(reason, visibleEvents) : [];
    const sourceEvents = affectedEvents.length ? affectedEvents : visibleEvents;
    const shownEvents = sourceEvents.slice(0, 30);
    return {
        state: data.state || 'NO_DATA',
        connection_count: visibleEvents.length,
        raw_events_shown: shownEvents.reduce((count, event) => count + (Array.isArray(event.raw_packet_events) ? event.raw_packet_events.length : 1), 0),
        raw_events_omitted: Math.max(sourceEvents.length - shownEvents.length, 0),
        filtered_by_reason: affectedEvents.length ? reason : '',
        tags: currentNetworkTags,
        events: shownEvents.map(networkRawEvent),
    };
}

function networkTechnicalDetailsHtml(data, events, open = false) {
    const rawPayload = networkRawMetadataPayload(data, events);
    return (
        '<section class="action-sidebar-section action-sidebar-technical-section">' +
        '<details id="network-raw-metadata" class="case-item network-raw-metadata action-sidebar-technical-details"' + (open ? ' open' : '') + '>' +
        '<summary>Technical Details</summary>' +
        '<pre>' + escapeHtml(JSON.stringify(rawPayload, null, 2)) + '</pre>' +
        '</details>' +
        '</section>'
    );
}

function refreshNetworkMetadataFooter() {
    const existing = byId('network-raw-metadata');
    if (!existing) return;
    const open = existing.open;
    existing.outerHTML = networkTechnicalDetailsHtml(currentNetworkData || {}, currentNetworkData?.events || [], open);
    const next = byId('network-raw-metadata');
    if (next) next.open = open;
}

function renderNetworkDisplay() {
    if (renderConsentRequired()) return;
    const coordinator = syncNetworkCoordinatorUiState();
    const renderModel = buildNetworkRenderModel(networkViewMode);
    coordinator.render = {
        key: renderModel.renderKey,
        version: Number(coordinator.render?.version || 0) + 1,
        model: renderModel,
    };
    const data = renderModel.data || {};
    currentNetworkData = data;
    if (renderModel.projectionView) {
        currentNetworkProjectionData = data;
    }
    if (networkShouldSuspendDomWork()) {
        markNetworkDeferredRender(networkViewMode === 'table' ? 'table' : 'display');
        if (networkViewMode === 'timeline') markNetworkDeferredRender('timeline');
        if (networkViewMode === 'bar') markNetworkDeferredRender('trend');
        return false;
    }
    setNetworkConnectionCount(renderModel);
    const events = Array.isArray(data.events) ? data.events : [];
    document.querySelectorAll('[data-network-view]').forEach(button => {
        const active = button.dataset.networkView === networkViewMode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
    });
    const graphToggle = document.querySelector('.network-graph-toggle');
    if (graphToggle) graphToggle.hidden = !['bar', 'pie'].includes(networkViewMode);
    document.querySelectorAll('[data-network-graph-view]').forEach(button => {
        const active = button.dataset.networkGraphView === networkViewMode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    const activeTab = document.querySelector('[data-network-view="' + networkViewMode + '"]');
    const networkResults = byId('network-results');
    if (networkResults && activeTab?.id) networkResults.setAttribute('aria-labelledby', activeTab.id);
    renderNetworkToolbarContext();
    const tabState = networkTabViewState(renderModel);
    const reason = currentNetworkTags.reasons?.[0] || '';
    const filteredEvents = networkActionFilterReason && networkActionFilterReason === reason
        ? networkAffectedEvents(reason, events)
        : events;
    const hasSupplementalDistribution = networkViewMode === 'pie' &&
        Array.isArray(data?.summary?.owners) && data.summary.owners.length > 0;
    const hasCanonicalAssessments = networkViewMode === 'findings' && Array.isArray(data?.assessments) && data.assessments.length > 0;
    if (networkViewMode !== 'table' && !events.length && !hasCanonicalAssessments && tabState.phase !== 'ready' && !hasSupplementalDistribution) {
        const results = byId('network-results');
        if (results) {
            results.innerHTML =
                '<div class="empty-state">' + escapeHtml(tabState.copy || networkTabEmptyCopy(networkViewMode)) + '</div>';
        }
        renderActionSidebar();
        return;
    }
    const renderers = {
        findings: renderNetworkFindings,
        table: renderNetworkTable,
        bar: renderNetworkBarGraph,
        pie: renderNetworkPie,
        timeline: renderNetworkTimeline,
    };
    const results = byId('network-results');
    const existingTable = networkViewMode === 'table' ? results?.querySelector('.network-table') : null;
    const tableShellCreated = networkViewMode === 'table' && !existingTable;
    if (results && tableShellCreated) {
        results.innerHTML = renderNetworkTable(filteredEvents, data);
    } else if (results && networkViewMode === 'table') {
        const rows = networkTableVisibleRows(filteredEvents, {
            filterReason: networkActionFilterReason && networkActionFilterReason === reason ? reason : '',
            pinnedEntityId: networkTablePinnedEntityId,
            limit: NETWORK_TABLE_DOM_ROW_LIMIT,
        });
        patchNetworkTableBody(rows, reason);
    } else if (results) {
        results.innerHTML = (renderers[networkViewMode] || renderNetworkTable)(filteredEvents, data);
    }
    renderActionSidebar();
    if (networkViewMode === 'table') {
        if (tableShellCreated) {
            applyNetworkColumnWidths(results?.querySelector('.network-table'));
            fillNetworkTableViewportRows(results?.querySelector('.network-table tbody'));
            enableNetworkColumnResize();
            enableNetworkColumnSort();
            bindNetworkEvidenceRows();
            const renderedRows = results?.querySelectorAll('.network-table tbody tr.network-row-evidence').length || 0;
            if (renderedRows && !networkStartupInstrumentation.firstRowRendered) {
                networkStartupInstrumentation.firstRowRendered = true;
                logNetworkStartup('first_table_row_rendered', {
                    expectedRows: filteredEvents.length,
                    renderedRows,
                });
            }
        }
        if (networkTableUiBuffer.length && !networkTableShouldDeferFlush()) {
            scheduleNetworkTableFlush();
        }
    }
    if (networkViewMode === 'findings') {
        bindNetworkFindingsWindow();
    }
    if (networkViewMode === 'pie') {
        bindNetworkPieInteractions();
        bindNetworkEvidenceElements('.network-pie-layout [data-evidence-entity-id]');
    }
    if (networkViewMode === 'bar' || networkViewMode === 'timeline') {
        bindNetworkFloatingTooltips();
        bindNetworkEvidenceElements('.network-trend-bar[data-evidence-entity-id], .network-timeline-event[data-evidence-entity-id]');
        bindNetworkTimelineIntervals();
    }
    if (networkViewMode === 'timeline') {
        bindNetworkTimelineRangeControls();
    }
    if (networkViewMode === 'bar') {
        bindNetworkTrendYAxisControls();
    }
    applyNetworkCtrlRouteTarget();
    return true;
}

function networkAssessmentEvidenceAttributes(assessment = {}, sourceView = 'findings') {
    const refs = Array.isArray(assessment.evidence_refs) ? assessment.evidence_refs.map(value => String(value || '').trim()).filter(Boolean) : [];
    const entityId = String(assessment.assessment_id || assessment.assessment_key || refs[0] || '').trim();
    return evidenceAttributes({ surface: 'network', entityId, ref: refs[0] || '', sourceView }) +
        (refs.length ? ' data-evidence-related-ids="' + escapeHtml(refs.join('|')) + '"' : '') +
        (assessment.assessment_id ? ' data-assessment-id="' + escapeHtml(assessment.assessment_id) + '"' : '');
}

function renderNetworkFindings(events, data = {}) {
    const assessments = Array.isArray(data.assessments) ? data.assessments : [];
    if (!assessments.length && !events.length) {
        return '<div class="network-findings-window"><div class="network-findings-feed"><div class="network-findings-empty empty-state">No review-worthy network findings are visible in this window.</div></div></div>';
    }
    // Product lock: this is a grouped semantic review list. Do not rewire it to
    // packet rows, projection totals, or custom wheel scrolling.
    return '<div class="network-findings-window">' +
        '<div class="network-feed network-findings-feed">' + (assessments.length ? assessments.map(assessment => {
        const category = String(assessment.category || 'unclassified').toLowerCase();
        const confidence = assessment.confidence && typeof assessment.confidence === 'object'
            ? assessment.confidence.label || assessment.confidence.score
            : assessment.confidence;
        const subject = assessment.subject && typeof assessment.subject === 'object'
            ? assessment.subject.label || assessment.subject.id
            : '';
        const rule = assessment.rule && typeof assessment.rule === 'object'
            ? [assessment.rule.id, assessment.rule.version].filter(Boolean).join(' · ')
            : '';
        const title = subject || assessment.assessment_key || 'Network assessment';
        const metadata = [category, assessment.severity, confidence, assessment.lifecycle, rule].filter(value => value !== undefined && value !== null && value !== '').join(' · ');
        return (
            '<details class="case-item network-finding-item" data-assessment-category="' + escapeHtml(category) + '"' + networkAssessmentEvidenceAttributes(assessment, 'findings') + '>' +
            '<summary>' + escapeHtml(title) +
            '<span class="network-assessment-category" data-category="' + escapeHtml(category) + '">' + escapeHtml(category) + '</span>' +
            '</summary>' +
            '<p class="network-event-reason">' + escapeHtml(assessment.rationale || 'No rationale supplied by the assessment contract.') + '</p>' +
            '<small><a href="#" class="network-findings-body-action-link" data-half-step="1" aria-label="Open in ctrl for this assessment">' + escapeHtml(metadata) + '</a></small>' +
            '</details>'
        );
    }) : events.map(event => {
        const plain = networkEventPlainLanguage(event);
        const priority = networkFindingPriority(event);
        const metadata = escapeHtml([networkEventTime(event), event.protocol, event.severity].filter(Boolean).join(' · '));
        return (
            '<details class="case-item network-finding-item"' + networkEvidenceAttributes(event, 'findings') + '>' +
            '<summary>' + escapeHtml(plain.summary) +
            '<span class="network-priority-tag" data-priority="' + escapeHtml(priority.key) + '">' + escapeHtml(priority.label) + '</span>' +
            '</summary>' +
            '<p class="network-event-reason">' + escapeHtml(plain.reason) + '</p>' +
            '<p class="network-event-context">' + escapeHtml(networkEventDetail(event)) + '</p>' +
            '<small>' +
            '<a href="#" class="network-findings-body-action-link" data-half-step="1" aria-label="Open in ctrl for this finding">' +
            metadata +
            '</a>' +
            '</small>' +
            '</details>'
        );
    })).join('') + '</div></div>';
}

// A stable callback prevents repeated renders from retaining detached feeds.
// Resolve the current window at event time; resize never reloads evidence.
function updateNetworkFindingsFade() {
    const windowEl = document.querySelector('.network-findings-window');
    const feed = windowEl?.querySelector('.network-findings-feed');
    if (!windowEl || !feed) return;
    const atTop = feed.scrollTop <= 1;
    const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 1;
    windowEl.classList.toggle('has-top-fade', !atTop);
    windowEl.classList.toggle('has-bottom-fade', !atBottom);
}

function bindNetworkFindingsWindow() {
    const windowEl = document.querySelector('.network-findings-window');
    const feed = windowEl?.querySelector('.network-findings-feed');
    if (!windowEl || !feed) return;
    updateNetworkFindingsFade();
    feed.addEventListener('scroll', updateNetworkFindingsFade, { passive: true });
    window.addEventListener('resize', updateNetworkFindingsFade, { passive: true });
    feed.querySelectorAll('.network-finding-item').forEach(item => {
        const descriptor = () => evidenceActionDescriptorFromRow(item);
        const halfStep = item.querySelector('.network-findings-body-action-link');
        if (!halfStep || halfStep.dataset.halfStepBound === '1') return;
        halfStep.dataset.halfStepBound = '1';
        const openHalfStep = () => {
            openEvidenceActions(descriptor());
        };
        halfStep.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            openHalfStep();
        });
        halfStep.addEventListener('keydown', event => {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            event.stopPropagation();
            openHalfStep();
        });
    });
}

function handleActionSidebarOutsideClick(event) {
    // Product lock: outside-click dismissal is close-only. Consume the click so
    // the same pointer event cannot activate the surface underneath the panel.
    if (!actionSidebarOpen) return;
    const target = event?.target;
    if (!target || !(target instanceof Element)) return;
    const sidebar = byId('action-sidebar');
    const toggle = byId('action-sidebar-toggle');
    if ((sidebar && sidebar.contains(target)) || (toggle && toggle.contains(target))) return;
    const mediationPanel = byId('files-mediation-panel');
    const mediationBoard = byId('files-mediation-board');
    const mediationToggle = byId('files-mediation-toggle');
    if (
        (mediationPanel && mediationPanel.contains(target)) ||
        (mediationBoard && mediationBoard.contains(target)) ||
        (mediationToggle && mediationToggle.contains(target))
    ) return;
    if (target.closest('.network-table')) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    setActionSidebarOpen(false);
}

function handleFilesMediationOutsideClick(event) {
    if (!filesMediationPanelOpen && !filesMediationBoardOpen) return;
    const target = event?.target;
    if (!target || !(target instanceof Element)) return;
    const panel = byId('files-mediation-panel');
    const board = byId('files-mediation-board');
    const toggle = byId('files-mediation-toggle');
    if (
        (panel && panel.contains(target)) ||
        (board && board.contains(target)) ||
        (toggle && toggle.contains(target))
    ) return;
    const controlPanel = byId('action-sidebar');
    const controlToggle = byId('action-sidebar-toggle');
    if (
        (controlPanel && controlPanel.contains(target)) ||
        (controlToggle && controlToggle.contains(target))
    ) {
        if (filesMediationBoardOpen) {
            setFilesMediationBoardOpen(false, { restoreFocus: false });
        }
        return;
    }
    if (filesMediationBoardOpen) {
        setFilesMediationBoardOpen(false, { restoreFocus: false });
        return;
    }
    setFilesMediationPanelOpen(false, { restoreFocus: false });
}

function renderNetworkTable(events, data = {}) {
    const reason = currentNetworkTags.reasons?.[0] || '';
    const orderedRows = networkTableVisibleRows(events, {
        filterReason: networkActionFilterReason && networkActionFilterReason === reason ? reason : '',
        pinnedEntityId: networkTablePinnedEntityId,
        limit: NETWORK_TABLE_DOM_ROW_LIMIT,
    });
    networkTableRenderState = {
        rowKeys: orderedRows.map(event => networkEvidenceEntityId(event)),
        rowSignatures: orderedRows.map(networkTableRowSignature),
        lastReason: reason,
        lastFilterReason: networkActionFilterReason && networkActionFilterReason === reason ? reason : '',
    };
    networkTableUiBuffer = [];
    const bodyHtml = orderedRows.length
        ? orderedRows.map(event => networkTableRowHtml(event, reason)).join('')
        : '';
    return (
        '<div class="network-table-wrap"><table class="network-table">' +
        '<colgroup>' +
        NETWORK_TABLE_COLUMNS.map(column => {
            const width = networkColumnWidths[column.key];
            return '<col class="' + column.className + '" data-column-key="' + column.key + '"' + (width ? ' style="width:' + width + 'px"' : '') + '>';
        }).join('') +
        '</colgroup>' +
        '<thead><tr>' + NETWORK_TABLE_COLUMNS.map(column => {
            const activeDirection = column.key === networkTableSort.key ? networkTableSort.direction : '';
            const ariaSort = activeDirection === 'asc' ? 'ascending' : (activeDirection === 'desc' ? 'descending' : 'none');
            return '<th data-column-key="' + column.key + '" aria-sort="' + ariaSort + '" data-sort-direction="' + activeDirection + '">' +
            '<span>' + column.label + '</span>' +
            '<button class="network-column-resizer" type="button" aria-label="Resize ' + column.label + ' column" data-column-key="' + column.key + '"></button>' +
            '</th>';
        }).join('') + '</tr></thead>' +
        '<tbody>' + bodyHtml + '</tbody></table></div>'
    );
}

function networkTableRowHtml(event, reason = '') {
    const sourceView = networkViewMode || 'table';
    const isPinned = networkTablePinnedEntityId && networkEvidenceEntityId(event) === networkTablePinnedEntityId;
    const isPinnedStale = Boolean(isPinned && event?.__networkPinnedStale);
    const rowClass = `network-row-evidence${reason && networkReasonMatchesEvent(reason, event) ? ' network-row-affected' : ''}${isPinned ? ' network-row-pinned' : ''}${isPinnedStale ? ' network-row-pinned-stale' : ''}`;
    return (
        '<tr class="' + rowClass + '"' +
        networkEvidenceAttributes(event, sourceView) +
        (isPinnedStale ? ' data-network-row-stale="1"' : '') +
        ' tabindex="0"' +
        ' role="button">' +
        '<td>' + escapeHtml(networkEventTime(event)) + '</td>' +
        '<td>' + escapeHtml(event.process || 'Unknown app') + '</td>' +
        '<td>' + escapeHtml(networkEventSource(event)) + '</td>' +
        '<td>' + escapeHtml(networkEventDestination(event)) + '</td>' +
        '<td>' + escapeHtml(event.protocol || 'Network connection') + '</td>' +
        '<td>' + escapeHtml(event.dst_port || 'Unavailable') + '</td>' +
        '<td>' + escapeHtml(networkEventTranslation(event)) + '</td>' +
        '</tr>'
    );
}

function bindNetworkEvidenceRows(context = null) {
    const table = context ? context.closest('.network-table') : document.querySelector('.network-table');
    if (!table) return;
    table.querySelectorAll('tr.network-row-evidence').forEach(row => {
        if (row.dataset.evidenceBound === '1') return;
        row.dataset.evidenceBound = '1';
        row.addEventListener('click', () => {
            const descriptor = evidenceActionDescriptorFromRow(row);
            openEvidenceActions(descriptor);
        });
        row.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                const descriptor = evidenceActionDescriptorFromRow(row);
                openEvidenceActions(descriptor);
            }
        });
    });
}

function bindNetworkEvidenceElements(selector) {
    document.querySelectorAll(selector).forEach(element => {
        if (element.dataset.evidenceBound === '1') return;
        element.dataset.evidenceBound = '1';
        element.addEventListener('click', event => {
            const descriptor = evidenceActionDescriptorFromRow(element);
            if (!descriptor?.entityId && !descriptor?.ref) return;
            event.stopPropagation();
            openEvidenceActions(descriptor);
        });
        if (element.tagName.toLowerCase() !== 'button') {
            element.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    const descriptor = evidenceActionDescriptorFromRow(element);
                    if (!descriptor?.entityId && !descriptor?.ref) return;
                    openEvidenceActions(descriptor);
                }
            });
        }
    });
}

function enableNetworkColumnResize() {
    const table = document.querySelector('.network-table');
    if (!table) return;
    table.querySelectorAll('.network-column-resizer').forEach(handle => {
        handle.addEventListener('pointerdown', event => {
            event.preventDefault();
            event.stopPropagation();
            const key = handle.dataset.columnKey;
            const col = table.querySelector('col[data-column-key="' + key + '"]');
            const header = handle.closest('th');
            if (!col || !header) return;
            const startX = event.clientX;
            const startWidth = header.getBoundingClientRect().width;
            handle.setPointerCapture?.(event.pointerId);
            const move = moveEvent => {
                const nextWidth = Math.max(54, Math.round(startWidth + moveEvent.clientX - startX));
                networkColumnWidths[key] = nextWidth;
                col.style.width = nextWidth + 'px';
                table.style.setProperty(`--network-col-${key}`, nextWidth + 'px');
            };
            const end = () => {
                window.removeEventListener('pointermove', move);
                window.removeEventListener('pointerup', end);
                window.removeEventListener('pointercancel', end);
            };
            window.addEventListener('pointermove', move);
            window.addEventListener('pointerup', end);
            window.addEventListener('pointercancel', end);
        });
    });
}

function applyNetworkColumnWidths(table) {
    if (!table) return;
    Object.entries(networkColumnWidths).forEach(([key, width]) => {
        table.style.setProperty(`--network-col-${key}`, width + 'px');
    });
}

function networkGroupCounts(events, key) {
    return events.reduce((counts, event) => {
        const label = event[key] || 'Unknown';
        counts[label] = (counts[label] || 0) + 1;
        return counts;
    }, {});
}

function networkGroupCountsBy(events, labeler) {
    return events.reduce((counts, event) => {
        const label = labeler(event) || 'Unknown';
        counts[label] = (counts[label] || 0) + 1;
        return counts;
    }, {});
}

function networkEventDate(event) {
    const value = event.timestamp || event.time || '';
    if (!value) return null;
    const numeric = Number(value);
    const date = Number.isFinite(numeric) && numeric > 0 ? new Date(numeric * 1000) : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

function networkEventCategory(event) {
    const text = String(event.category || event.meaning || event.protocol || '').toLowerCase();
    if (eventCriticalReason(event)) return 'critical';
    if (eventDegradedReason(event) || (networkEventIsExternal(event) && !networkEventHasReadableDestination(event))) return 'review';
    if (text.includes('push')) return 'push';
    if (networkEventIsExternal(event)) return 'external';
    return 'local';
}

function networkTimelineBuckets(events, targetBuckets = 16) {
    const dated = events
        .map((event, index) => ({ event, index, date: networkEventDate(event) }))
        .filter(item => item.date);
    if (!dated.length) {
        return events.slice(0, targetBuckets).map((event, index) => ({
            events: [event],
            index,
            left: events.length <= 1 ? 50 : (index / Math.max(events.length - 1, 1)) * 100,
        }));
    }
    const min = Math.min(...dated.map(item => item.date.getTime()));
    const max = Math.max(...dated.map(item => item.date.getTime()));
    const span = Math.max(max - min, 1);
    const useSequence = span < 1000;
    const buckets = new Map();
    dated.forEach(item => {
        const left = useSequence
            ? (item.index / Math.max(events.length - 1, 1)) * 100
            : ((item.date.getTime() - min) / span) * 100;
        const key = Math.min(targetBuckets - 1, Math.max(0, Math.floor((left / 100) * targetBuckets)));
        if (!buckets.has(key)) buckets.set(key, { events: [], index: key, left: Math.min(98, Math.max(2, left)) });
        buckets.get(key).events.push(item.event);
    });
    return Array.from(buckets.values()).sort((a, b) => a.left - b.left);
}

function networkTimelineBucketMeta(bucket) {
    const events = bucket.events || [];
    const apps = Object.entries(networkGroupCountsBy(events, networkEventAppName)).sort((a, b) => b[1] - a[1]);
    const destinations = Object.entries(networkGroupCountsBy(events, networkEventDestination)).sort((a, b) => b[1] - a[1]);
    const protocols = Object.entries(networkGroupCountsBy(events, event => event.protocol || 'Network connection')).sort((a, b) => b[1] - a[1]);
    return {
        app: apps[0]?.[0] || 'Unknown app',
        destination: destinations[0]?.[0] || 'Unknown destination',
        protocol: protocols[0]?.[0] || 'Network connection',
    };
}

function networkSelectedRangeWindow(rangeKey) {
    const end = new Date();
    const baseRange = NETWORK_TIMELINE_RANGES[rangeKey] || NETWORK_TIMELINE_RANGES['5s'];
    const start = new Date(end.getTime() - baseRange.durationMs);
    if (rangeKey === '1mo') start.setMonth(end.getMonth() - 1);
    if (rangeKey === '3mo') start.setMonth(end.getMonth() - 3);
    if (rangeKey === '12mo') start.setFullYear(end.getFullYear() - 1);
    const range = { ...baseRange, durationMs: Math.max(end.getTime() - start.getTime(), 1) };
    return { start, end, range };
}

function networkRangeAxis(rangeKey) {
    const windowRange = networkSelectedRangeWindow(rangeKey);
    return {
        start: networkDateLabel(windowRange.start, rangeKey),
        end: networkDateLabel(windowRange.end, rangeKey),
    };
}

function networkTimelineEventsForRange(events, rangeKey) {
    const windowRange = networkSelectedRangeWindow(rangeKey);
    const range = windowRange.range;
    const startMs = windowRange.start.getTime();
    const endMs = windowRange.end.getTime();
    const dated = events
        .map((event, index) => ({ event, index, date: networkEventDate(event) }))
        .filter(item => item.date);
    if (!dated.length) {
        return events.slice(0, Math.max(range.maxMarkers * 2, 36));
    }
    const inWindow = dated
        .filter(item => {
            const time = item.date.getTime();
            return time >= startMs && time <= endMs;
        })
        .sort((a, b) => a.index - b.index)
        .map(item => item.event);
    return inWindow;
}

function networkRangeControlsHtml(label = 'Network range', options = {}) {
    const keys = Array.isArray(options.rangeKeys) && options.rangeKeys.length
        ? options.rangeKeys.filter(key => NETWORK_TIMELINE_RANGES[key])
        : Object.keys(NETWORK_TIMELINE_RANGES);
    const activeRange = options.activeRange || networkTimelineRangeMode;
    return (
        '<div class="network-timeline-range" aria-label="' + escapeHtml(label) + '">' +
        keys.map(key => NETWORK_TIMELINE_RANGES[key]).map((item, index) => {
            const key = keys[index];
            return '<button type="button" data-network-timeline-range="' + escapeHtml(key) + '"' + (key === activeRange ? ' class="active"' : '') + '>' + escapeHtml(item.label) + '</button>';
        }).join('') +
        '</div>'
    );
}

function networkTimelineRangeControlsHtml() {
    return networkRangeControlsHtml('Timeline range', {
        rangeKeys: NETWORK_TIMELINE_VISIBLE_RANGE_KEYS,
        activeRange: networkTimelineDisplayRangeMode(),
    });
}

function networkTrendYAxisControlsHtml() {
    return (
        '<div class="network-trend-y-controls" aria-label="Trend Y axis maximum">' +
        NETWORK_TREND_Y_AXIS_OPTIONS.slice().reverse().map(value => (
            '<button type="button" data-network-trend-y="' + escapeHtml(value) + '"' + (value === networkTrendYAxisMax ? ' class="active"' : '') + '>' + escapeHtml(value) + '</button>'
        )).join('') +
        '</div>'
    );
}

function networkTrendMetricControlsHtml() {
    const labels = {
        connections: 'Connections',
        strengths: 'Strengths',
        vulnerabilities: 'Vulnerabilities',
        threats: 'Threats',
    };
    return '<div class="network-trend-metric-controls" role="group" aria-label="Trend metric">' +
        Object.entries(labels).map(([metric, label]) => (
            '<button type="button" data-network-trend-metric="' + escapeHtml(metric) + '"' +
            (metric === networkTrendMetric ? ' class="active" aria-pressed="true"' : ' aria-pressed="false"') + '>' +
            escapeHtml(label) + '</button>'
        )).join('') + '</div>';
}
function networkTrendYAxisLabelsHtml(axisMax) {
    const labels = [axisMax, axisMax * 0.75, axisMax * 0.5, axisMax * 0.25, 0].map(value => Math.round(value));
    return '<div class="network-trend-y-axis" aria-hidden="true">' + labels.map(value => '<span>' + escapeHtml(value) + '</span>').join('') + '</div>';
}


function renderNetworkToolbarContext() {
    const context = byId('network-toolbar-context');
    if (!context) return;
    if (networkViewMode === 'bar') {
        document.querySelector('#network .network-toolbar')?.append(context);
        context.innerHTML = networkTrendMetricControlsHtml() + networkRangeControlsHtml('Trend range');
        context.hidden = false;
        // These controls remain usable while the results are loading or unavailable.
        bindNetworkTrendMetricControls();
        bindNetworkTimelineRangeControls();
        return;
    }
    document.querySelector('#network .network-toolbar-actions')?.prepend(context);
    if (networkViewMode === 'timeline') {
        context.innerHTML = networkTimelineRangeControlsHtml();
        context.hidden = false;
        return;
    }
    context.innerHTML = '';
    context.hidden = true;
}

function networkDateLabel(date, rangeKey = networkTimelineRangeMode) {
    if (!date || Number.isNaN(date.getTime())) return 'Unavailable';
    const range = NETWORK_TIMELINE_RANGES[rangeKey] || NETWORK_TIMELINE_RANGES['5s'];
    if (range.durationMs >= 24 * 60 * 60 * 1000) {
        return date.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    }
    return date.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function networkRangePlainLabel(rangeConfig) {
    return String(rangeConfig?.title || 'Last 5 seconds').replace(/^Last\s+/i, '').toLowerCase();
}

function networkTrendTapeKey(event) {
    return event?.tick_id || event?.event_id || [
        event?.packet_index,
        event?.timestamp,
        event?.src_ip,
        event?.src_port,
        event?.dst_ip,
        event?.dst_port,
    ].filter(Boolean).join('|');
}

function networkTrendSlotSizeMs(rangeKey = networkTimelineRangeMode) {
    const selectedWindow = networkSelectedRangeWindow(rangeKey);
    return Math.max(Math.round(selectedWindow.range.durationMs / selectedWindow.range.buckets), 1000);
}

function networkTrendBucketForLiveEvent(event, rangeKey = networkTimelineRangeMode) {
    const selectedWindow = networkSelectedRangeWindow(rangeKey);
    const date = networkEventDate(event) || new Date();
    const time = date.getTime();
    if (time < selectedWindow.start.getTime() || time > selectedWindow.end.getTime()) return null;
    const slotSize = networkTrendSlotSizeMs(rangeKey);
    const bucketStartMs = Math.floor(time / slotSize) * slotSize;
    const start = new Date(bucketStartMs);
    const end = new Date(bucketStartMs + slotSize);
    const tickKey = 'live-tick:' + rangeKey + ':' + bucketStartMs;
    const degraded = eventCriticalReason(event) || eventDegradedReason(event) || (networkEventIsExternal(event) && !networkEventHasReadableDestination(event));
    return {
        event_id: tickKey,
        tick_id: tickKey,
        bucket_key: tickKey,
        bucket_range: rangeKey,
        bucket_start: start.toISOString(),
        bucket_end: end.toISOString(),
        timestamp: date.toISOString(),
        sealed_at: end.toISOString(),
        immutable: Date.now() >= end.getTime(),
        connectionCount: 1,
        degradedCount: degraded ? 1 : 0,
        missingDestinationCount: networkEventIsExternal(event) && !networkEventHasReadableDestination(event) ? 1 : 0,
        externalOnlyCount: networkEventIsExternal(event) ? 1 : 0,
        source_event_id: event.event_id || '',
        related_event_ids: event.event_id ? [event.event_id] : [],
    };
}

function rememberNetworkLiveTrendTick(event) {
    if (!event || typeof event !== 'object') return false;
    let changed = false;
    Object.keys(NETWORK_TIMELINE_RANGES).forEach(rangeKey => {
        const tick = networkTrendBucketForLiveEvent(event, rangeKey);
        if (!tick) return;
        const key = networkTrendTapeKey(tick);
        if (!key) return;
        const existingIndex = networkTrendLiveTape.findIndex(item => networkTrendTapeKey(item) === key);
        if (existingIndex >= 0) {
            const existing = networkTrendLiveTape[existingIndex];
            const bucketEnd = new Date(existing.bucket_end || existing.sealed_at || '').getTime();
            if (Number.isFinite(bucketEnd) && Date.now() >= bucketEnd) return;
            const related = new Set([...(existing.related_event_ids || []), ...(tick.related_event_ids || [])].filter(Boolean));
            networkTrendLiveTape[existingIndex] = Object.freeze({
                ...existing,
                timestamp: tick.timestamp,
                immutable: tick.immutable,
                connectionCount: (Number(existing.connectionCount) || 0) + 1,
                degradedCount: (Number(existing.degradedCount) || 0) + (Number(tick.degradedCount) || 0),
                missingDestinationCount: (Number(existing.missingDestinationCount) || 0) + (Number(tick.missingDestinationCount) || 0),
                externalOnlyCount: (Number(existing.externalOnlyCount) || 0) + (Number(tick.externalOnlyCount) || 0),
                related_event_ids: Array.from(related).slice(-30),
            });
            changed = true;
            return;
        }
        networkTrendLiveTape.push(Object.freeze({ ...tick }));
        changed = true;
    });
    if (networkTrendLiveTape.length > NETWORK_TREND_LIVE_TICK_LIMIT) {
        networkTrendLiveTape = networkTrendLiveTape.slice(-NETWORK_TREND_LIVE_TICK_LIMIT);
    }
    return changed;
}

function networkTrendLiveTicksForRange(rangeKey = networkTimelineRangeMode) {
    const selectedWindow = networkSelectedRangeWindow(rangeKey);
    return networkTrendLiveTape.filter(tick => {
        if (tick.bucket_range !== rangeKey) return false;
        const start = new Date(tick.bucket_start || tick.timestamp || '').getTime();
        const end = new Date(tick.bucket_end || tick.timestamp || '').getTime();
        if (!Number.isFinite(start) || !Number.isFinite(end)) return false;
        return end >= selectedWindow.start.getTime() && start <= selectedWindow.end.getTime();
    });
}

function networkTrendDataMatchesTarget(data, rangeKey = networkTimelineRangeMode) {
    return data?.summary?.range === rangeKey && data?.summary?.metric === networkTrendMetric;
}

function networkTrendProjectionWithLive(baseData, rangeKey = networkTimelineRangeMode) {
    const data = networkTrendDataMatchesTarget(baseData, rangeKey)
        ? baseData
        : { state: 'CAPTURING', events: [], summary: { reason: 'projection', view: 'trend', range: rangeKey, metric: networkTrendMetric } };
    const baseState = normalizeNetworkContractState(data.state || 'NO_DATA');
    const captureUnavailable = ['ERROR', 'CAPTURE_BLOCKED'].includes(baseState);
    const events = Array.isArray(data.events) ? data.events.slice() : [];
    if (networkTrendMetric !== 'connections') return { ...data, events };
    const seen = new Set(events.map(item => String(item.tick_id || item.event_id || item.bucket_key || '')).filter(Boolean));
    networkTrendLiveTicksForRange(rangeKey).forEach(tick => {
        const key = String(tick.tick_id || tick.event_id || tick.bucket_key || '');
        if (!key || seen.has(key)) return;
        events.push(tick);
        seen.add(key);
    });
    return {
        ...data,
        state: captureUnavailable ? baseState : (events.length ? 'CAPTURING' : baseState),
        events,
        summary: {
            ...(data.summary || {}),
            reason: captureUnavailable ? (data.summary?.reason || 'capture_failed') : 'projection',
            view: 'trend',
            range: rangeKey,
            event_count: events.length,
            bucket_count: events.length,
            live_ticks: networkTrendLiveTape.length > 0,
            immutable_ticks: true,
        },
    };
}

function appendNetworkLiveTrendTick(event) {
    if (event) rememberNetworkLiveTrendTick(event);
    currentNetworkProjectionData = networkTrendProjectionWithLive(
        currentNetworkTrendBaseData || currentNetworkProjectionData,
        networkTimelineSelectedRangeMode(),
    );
    currentNetworkData = currentNetworkProjectionData;
    networkTrendLiveDirty = true;
}

function networkCommonExternalPort(port) {
    return ['80', '443', '53', '123', '5228', '853', '993', '995', '587', '465'].includes(String(port || ''));
}

function networkTimelineNotables(events, options = {}) {
    const visibleEvents = Array.isArray(events) ? events : [];
    const appCounts = networkGroupCountsBy(visibleEvents, networkEventAppName);
    const destinationCounts = networkGroupCountsBy(visibleEvents, networkEventDestination);
    const notableItems = visibleEvents.map((event, index) => {
        const assessmentTransition = event?.event_type === 'security_assessment_transition';
        const assessmentCategory = String(event?.category || event?.assessment_category || '').toLowerCase();
        const critical = eventCriticalReason(event);
        const degraded = eventDegradedReason(event);
        const app = networkEventAppName(event);
        const destination = networkEventDestination(event);
        const external = networkEventIsExternal(event);
        const missingName = external && !networkEventHasReadableDestination(event);
        const unknownApp = external && app === 'Unknown app';
        const unusualPort = external && event.dst_port && !networkCommonExternalPort(event.dst_port);
        const appVolume = appCounts[app] || 0;
        const destinationVolume = destinationCounts[destination] || 0;
        const highAppVolume = appVolume >= 10 && appVolume / Math.max(visibleEvents.length, 1) >= 0.25;
        const highDestinationVolume = destinationVolume >= 10 && destinationVolume / Math.max(visibleEvents.length, 1) >= 0.25;
        let priority = 0;
        let reason = '';
        if (assessmentTransition) {
            priority = assessmentCategory === 'threat' ? 4 : (assessmentCategory === 'vulnerability' ? 3 : 2);
            reason = String(event.rationale || event.reason || `${assessmentCategory || 'Security'} assessment transition`);
        } else if (critical) {
            priority = 4;
            reason = critical;
        } else if (degraded) {
            priority = 3;
            reason = degraded;
        } else if (missingName) {
            priority = 3;
            reason = 'Destination name missing';
        } else if (unknownApp) {
            priority = 3;
            reason = 'Unknown app active';
        } else if (unusualPort) {
            priority = 3;
            reason = 'Unusual port used';
        } else if (highAppVolume) {
            priority = 2;
            reason = 'High app activity';
        } else if (highDestinationVolume) {
            priority = 2;
            reason = 'Repeated destination';
        } else if (external) {
            priority = 1;
            reason = 'External connection';
        }
        return { event, index, priority, reason };
    });
    const minPriority = Number.isFinite(options.minPriority) ? options.minPriority : 2;
    const maxItems = Number.isFinite(options.maxItems) ? options.maxItems : 36;
    const priorityItems = notableItems.filter(item => item.priority >= minPriority);
    if (priorityItems.length) return priorityItems.slice(-maxItems);
    if (minPriority <= 1) return notableItems.filter(item => item.priority > 0).slice(-maxItems);
    return [];
}

function networkTimelineNotableBuckets(items, totalEvents, targetBuckets = 24, rangeKey = networkTimelineRangeMode, allEvents = []) {
    const dated = items
        .map((item, index) => ({ ...item, sequenceIndex: index, date: networkEventDate(item.event) }))
        .filter(item => item.date);
    const sourceItems = dated.length ? dated : items.map((item, index) => ({ ...item, sequenceIndex: index, date: null }));
    if (!sourceItems.length) return [];
    const selectedWindow = networkSelectedRangeWindow(rangeKey);
    const min = selectedWindow.start.getTime();
    const max = selectedWindow.end.getTime();
    const span = Math.max(max - min, 1);
    const times = sourceItems.map(item => item.date?.getTime()).filter(Number.isFinite);
    const useSequence = !times.length || span < 1000;
    const buckets = new Map();
    sourceItems.forEach(item => {
        const left = useSequence
            ? (item.sequenceIndex / Math.max(sourceItems.length - 1, 1)) * 100
            : ((item.date.getTime() - min) / span) * 100;
        const key = Math.min(targetBuckets - 1, Math.max(0, Math.floor((left / 100) * targetBuckets)));
        if (!buckets.has(key)) buckets.set(key, { items: [], index: key, left: Math.min(98, Math.max(2, left)) });
        buckets.get(key).items.push(item);
    });
    const completeBuckets = new Map();
    const completeEvents = Array.isArray(allEvents) ? allEvents : [];
    completeEvents.forEach((event, sequenceIndex) => {
        const date = networkEventDate(event);
        const left = date
            ? ((date.getTime() - min) / span) * 100
            : (sequenceIndex / Math.max(completeEvents.length - 1, 1)) * 100;
        const key = Math.min(targetBuckets - 1, Math.max(0, Math.floor((left / 100) * targetBuckets)));
        if (!completeBuckets.has(key)) completeBuckets.set(key, []);
        completeBuckets.get(key).push(event);
    });
    return Array.from(buckets.values()).map(bucket => {
        bucket.items.sort((a, b) => b.priority - a.priority || a.index - b.index);
        bucket.notableEvents = bucket.items.map(item => item.event);
        bucket.events = completeBuckets.get(bucket.index) || bucket.notableEvents;
        bucket.priority = bucket.items[0]?.priority || 0;
        bucket.reason = bucket.items[0]?.reason || '';
        bucket.totalEvents = totalEvents;
        return bucket;
    }).sort((a, b) => a.left - b.left);
}

function networkTimelineCategoryForPriority(priority, fallbackEvent) {
    if (priority >= 4) return 'critical';
    if (priority >= 3) return 'review';
    if (priority >= 2) return 'notable';
    return networkEventCategory(fallbackEvent);
}

function renderNetworkBarGraph(events) {
    const trendRangeMode = networkTimelineSelectedRangeMode();
    const rangeConfig = NETWORK_TIMELINE_RANGES[trendRangeMode] || NETWORK_TIMELINE_RANGES['5s'];
    const projectedBuckets = Array.isArray(events)
        ? events.filter(event => event && (event.bucket_key || event.bucket_start))
        : [];
    const selectedWindow = networkSelectedRangeWindow(trendRangeMode);
    const slotCount = selectedWindow.range.buckets;
    const slotSize = Math.max(selectedWindow.range.durationMs / slotCount, 1);
    const slotStart = selectedWindow.start.getTime();
    const slots = Array.from({ length: slotCount }, (_, index) => ({
        event: null,
        start: new Date(slotStart + index * slotSize),
        end: new Date(slotStart + (index + 1) * slotSize),
    }));
    const mergeNetworkEventList = (left, right) => {
        const merged = [];
        const seen = new Set();
        [...(Array.isArray(left) ? left : []), ...(Array.isArray(right) ? right : [])].forEach(value => {
            const text = String(value || '').trim();
            if (!text || seen.has(text)) return;
            seen.add(text);
            merged.push(text);
        });
        return merged.slice(0, 12);
    };
    projectedBuckets.forEach(bucket => {
        const bucketStart = new Date(bucket.bucket_start || bucket.timestamp || '').getTime();
        const bucketEnd = new Date(bucket.bucket_end || bucket.timestamp || '').getTime();
        if (!Number.isFinite(bucketStart) || bucketEnd <= slotStart || bucketStart >= selectedWindow.end.getTime()) return;
        // Missing coverage is never an observed zero or selectable evidence.
        if (bucket.gap || bucket.coverage_state === 'gap') return;
        const index = Math.min(slotCount - 1, Math.max(0, Math.floor((bucketStart - slotStart) / slotSize)));
        const existing = slots[index].event;
        if (!existing) {
            slots[index].event = { ...bucket };
            return;
        }
        slots[index].event = {
            ...existing,
            connectionCount: (Number(existing.connectionCount) || 0) + (Number(bucket.connectionCount) || 0),
            value: (Number(existing.value) || 0) + (Number(bucket.value) || 0),
            degradedCount: (Number(existing.degradedCount) || 0) + (Number(bucket.degradedCount) || 0),
            missingDestinationCount: (Number(existing.missingDestinationCount) || 0) + (Number(bucket.missingDestinationCount) || 0),
            externalOnlyCount: (Number(existing.externalOnlyCount) || 0) + (Number(bucket.externalOnlyCount) || 0),
            evidence_refs: mergeNetworkEventList(existing.evidence_refs, bucket.evidence_refs),
            assessment_refs: mergeNetworkEventList(existing.assessment_refs, bucket.assessment_refs),
            assessment_counts: Object.fromEntries(
                ['strengths', 'vulnerabilities', 'threats'].map(category => [
                    category,
                    (Number(existing.assessment_counts?.[category]) || 0) + (Number(bucket.assessment_counts?.[category]) || 0),
                ])
            ),
            related_event_ids: mergeNetworkEventList(existing.related_event_ids, bucket.related_event_ids),
        };
    });
    const range = networkRangeAxis(trendRangeMode);
    const rangeLabel = networkRangePlainLabel(rangeConfig);
    const axisMax = validNetworkTrendYAxisMax(networkTrendYAxisMax) || 250;
    const trendMetricLabels = { connections: 'connection', strengths: 'strength', vulnerabilities: 'vulnerability', threats: 'threat' };
    const trendMetricLabel = trendMetricLabels[networkTrendMetric] || 'connection';
    const chart = '<div class="network-trend-chart" aria-label="Network ' + escapeHtml(trendMetricLabel) + ' trend" style="grid-template-columns: repeat(' + escapeHtml(slots.length) + ', minmax(10px, 1fr));">' +
        slots.map(slot => {
            const bucket = slot.event;
            if (!bucket) {
                return '<div class="network-trend-bar is-empty" role="img" aria-label="No retained evidence for this interval" style="height:2%"></div>';
            }
            const metricValue = networkTrendMetric === 'connections' ? bucket.connectionCount : bucket.value;
            const connectionCount = Number(metricValue) || 0;
            const degradedCount = (Number(bucket.degradedCount) || 0) + (Number(bucket.missingDestinationCount) || 0);
            const cappedCount = Math.min(connectionCount, axisMax);
            const height = connectionCount === 0 ? 0 : Math.max(8, Math.round((cappedCount / axisMax) * 100));
            const isCapped = connectionCount > axisMax;
            const metricLabels = { connections: 'observed connection', strengths: 'strength', vulnerabilities: 'vulnerability', threats: 'threat' };
            const metricLabel = metricLabels[networkTrendMetric] || 'value';
            const pluralLabel = networkTrendMetric === 'vulnerabilities' ? 'vulnerabilities' : metricLabel + 's';
            const title = connectionCount + ' ' + (connectionCount === 1 ? metricLabel : pluralLabel);
            const bucketStart = slot.start;
            const bucketEnd = slot.end;
            const rangeLabel = bucketStart && bucketEnd ? networkDateLabel(bucketStart, trendRangeMode) + ' to ' + networkDateLabel(bucketEnd, trendRangeMode) : '';
            const tooltipBody = [
                'Frozen bucket snapshot.',
                isCapped ? 'This bucket exceeded the fixed chart ceiling of ' + axisMax + '.' : '',
                networkTrendMetric === 'connections' && degradedCount ? degradedCount + ' observed connection' + (degradedCount === 1 ? '' : 's') + ' need review.' : '',
            ].filter(Boolean).join(' ');
            const cappedLabel = isCapped ? '<span class="network-trend-cap-label">' + escapeHtml(connectionCount) + '</span>' : '';
            return (
                '<div class="network-trend-bar' + (isCapped ? ' is-capped' : '') + (connectionCount === 0 ? ' is-zero' : '') + '"' +
                networkEvidenceAttributes(bucket, 'trend') + ' tabindex="0" role="button"' +
                ' aria-label="' + escapeHtml(title + '. ' + rangeLabel) + '"' +
                ' data-floating-tooltip data-tooltip-title="' + escapeHtml(title) + '" data-tooltip-body="' + escapeHtml(tooltipBody) + '" data-tooltip-meta="' + escapeHtml(rangeLabel) + '" style="height:' + height + '%">' + cappedLabel + '</div>'
            );
        }).join('') +
        '</div>';
    const body =
        '<div class="network-trend-plot">' +
        networkTrendYAxisControlsHtml() +
        networkTrendYAxisLabelsHtml(axisMax) +
        '<div class="network-trend-graph">' +
        chart +
        '<div class="network-trend-axis"><span>' + escapeHtml(range.start) + '</span><span>' + escapeHtml(range.end) + '</span></div>' +
        '</div>' +
        '</div>';
    return (
        '<div class="network-trend" data-trend-metric="' + escapeHtml(networkTrendMetric) + '">' +
        body +
        '</div>'
    );
}

function networkDistributionOwners(events, data = {}) {
    const ownerName = value => String(value || '').trim().replace(/\s+/g, ' ') || 'Unknown app';
    // The projection's owner list is authoritative, including an explicit empty list.
    // Compatibility event payloads retain their own evidence, never GUI inventory.
    let owners = data?.summary?.owners;
    if (!Array.isArray(owners)) {
        const grouped = new Map();
        for (const event of Array.isArray(events) ? events : []) {
            const name = ownerName(networkEventAppName(event));
            const owner = grouped.get(name) || {name, owner_id: 'distribution:' + name, observed_network_events: 0, evidence_refs: [], assessment_refs: []};
            owner.observed_network_events += 1;
            owner.evidence_refs.push(...(Array.isArray(event.evidence_refs) ? event.evidence_refs : []));
            if (event.event_id) owner.evidence_refs.push('local://cleanhouse/network/' + event.event_id);
            owner.assessment_refs.push(...(Array.isArray(event.assessment_refs) ? event.assessment_refs : []));
            grouped.set(name, owner);
        }
        owners = Array.from(grouped.values());
    }
    return owners.filter(owner => owner && Number.isSafeInteger(Number(owner.observed_network_events)) && Number(owner.observed_network_events) > 0)
        .map(owner => ({...owner, name: ownerName(owner.name), observed_network_events: Number(owner.observed_network_events)}))
        .sort((left, right) => right.observed_network_events - left.observed_network_events || left.name.localeCompare(right.name) || String(left.owner_id || '').localeCompare(String(right.owner_id || '')));
}

function renderNetworkPie(events, data = {}) {
    const entries = networkDistributionOwners(events, data);
    if (!entries.length) {
        return '<div class="network-distribution">' +
            '<section class="network-distribution-section" aria-labelledby="network-observed-activity-title">' +
            '<h3 id="network-observed-activity-title">Observed network activity</h3>' +
            '<div class="empty-state">No packet-supported network activity is visible for this window.</div>' +
            '</section></div>';
    }
    const total = entries.reduce((sum, owner) => sum + Math.max(0, Number(owner.observed_network_events || 0)), 0);
    if (!total) {
        return '<div class="network-distribution"><section class="network-distribution-section" aria-labelledby="network-observed-activity-title"><h3 id="network-observed-activity-title">Observed network activity</h3><div class="empty-state">No packet-supported network activity is visible for this window.</div></section></div>';
    }
    let cursor = 0;
    const colors = ['#8ed6cc', '#9fb6ff', '#f0c36a', '#d88cff', '#ff8b8b', '#91d8a2', '#d5dee8', '#7baea7'];
    const slices = entries.map((owner, index) => {
        const label = owner.name || 'Unknown app';
        const count = Number(owner.observed_network_events || 0);
        const start = cursor;
        cursor += (count / total) * 100;
        return {
            label,
            count,
            owner,
            color: colors[index % colors.length],
            path: networkDonutSlicePath(start, cursor),
        };
    });
    const legendRows = slices.map((slice, index) => ({
        label: slice.label,
        count: slice.count,
        color: slice.color,
        pieIndex: String(index),
    }));
    return (
        '<div class="network-distribution">' +
        '<section class="network-distribution-section" aria-labelledby="network-observed-activity-title">' +
        '<h3 id="network-observed-activity-title">Observed network activity</h3>' +
        '<p class="network-distribution-source">Packet-supported retained evidence.</p>' +
        '<div class="network-pie-layout">' +
        '<div class="network-pie-shell">' +
        '<svg class="network-pie" viewBox="0 0 200 200" role="group" aria-label="Network activity distribution by app">' +
        slices.map((slice, index) => (
            '<path class="network-pie-slice" data-pie-index="' + index + '" data-pie-label="' + escapeHtml(slice.label) + '"' +
            networkDistributionEvidenceAttributes(slice.label, slice.owner) +
            ' tabindex="0" role="button" aria-label="' + escapeHtml(slice.label + ': ' + slice.count + ' observed network event' + (slice.count === 1 ? '' : 's')) + '" d="' + escapeHtml(slice.path) + '" fill="' + escapeHtml(slice.color) + '">' +
            '<title>' + escapeHtml(slice.label + ': ' + slice.count + ' observed network event' + (slice.count === 1 ? '' : 's')) + '</title>' +
            '</path>'
        )).join('') +
        '<circle class="network-pie-hole" cx="100" cy="100" r="54"></circle>' +
        '<text class="network-pie-total" x="100" y="107" text-anchor="middle">' + escapeHtml(total) + '</text>' +
        '</svg>' +
        '</div>' +
        '<dl class="network-pie-legend">' + legendRows.map(row => (
            '<div class="network-pie-legend-row" data-pie-index="' + escapeHtml(row.pieIndex) + '"' +
            networkDistributionEvidenceAttributes(row.label, slices[Number(row.pieIndex)]?.owner || {}) +
            ' tabindex="0" role="button" aria-label="' + escapeHtml(row.label + ': ' + row.count + ' observed network event' + (row.count === 1 ? '' : 's')) + '"><dt><span style="background:' + escapeHtml(row.color) + '"></span>' + escapeHtml(row.label) + '</dt><dd>' + escapeHtml(row.count) + '</dd></div>'
        )).join('') + '</dl>' +
        '</div></section>' +
        '</div>'
    );
}

function networkDonutSlicePath(startPercent, endPercent) {
    const startAngle = (startPercent / 100) * 360 - 90;
    const endAngle = ((endPercent >= 100 ? 99.999 : endPercent) / 100) * 360 - 90;
    const largeArc = endPercent - startPercent > 50 ? 1 : 0;
    const outerStart = networkPolarPoint(100, 100, 94, startAngle);
    const outerEnd = networkPolarPoint(100, 100, 94, endAngle);
    const innerEnd = networkPolarPoint(100, 100, 56, endAngle);
    const innerStart = networkPolarPoint(100, 100, 56, startAngle);
    return [
        'M', outerStart.x, outerStart.y,
        'A', 94, 94, 0, largeArc, 1, outerEnd.x, outerEnd.y,
        'L', innerEnd.x, innerEnd.y,
        'A', 56, 56, 0, largeArc, 0, innerStart.x, innerStart.y,
        'Z',
    ].join(' ');
}

function networkPolarPoint(cx, cy, radius, angleDegrees) {
    const angle = angleDegrees * Math.PI / 180;
    return {
        x: Number((cx + radius * Math.cos(angle)).toFixed(3)),
        y: Number((cy + radius * Math.sin(angle)).toFixed(3)),
    };
}

function networkPieTooltip() {
    let tooltip = byId('network-pie-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'network-pie-tooltip';
        tooltip.className = 'network-pie-tooltip';
        tooltip.hidden = true;
        document.body.appendChild(tooltip);
    }
    return tooltip;
}

function networkFloatingTooltip() {
    let tooltip = byId('network-floating-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'network-floating-tooltip';
        tooltip.className = 'network-floating-tooltip';
        tooltip.hidden = true;
        document.body.appendChild(tooltip);
    }
    return tooltip;
}

function showNetworkFloatingTooltip(element, event) {
    const tooltip = networkFloatingTooltip();
    const title = element.dataset.tooltipTitle || '';
    const body = element.dataset.tooltipBody || '';
    const meta = element.dataset.tooltipMeta || '';
    tooltip.innerHTML =
        (title ? '<strong>' + escapeHtml(title) + '</strong>' : '') +
        (body ? '<span>' + escapeHtml(body) + '</span>' : '') +
        (meta ? '<small>' + escapeHtml(meta) + '</small>' : '');
    tooltip.hidden = false;
    moveNetworkFloatingTooltip(event, element);
}

function moveNetworkFloatingTooltip(event, element) {
    const tooltip = networkFloatingTooltip();
    if (tooltip.hidden) return;
    const rect = element?.getBoundingClientRect?.();
    const preferredX = Number.isFinite(event?.clientX) ? event.clientX + 14 : (rect ? rect.right + 10 : 24);
    const preferredY = Number.isFinite(event?.clientY) ? event.clientY + 14 : (rect ? rect.top : 24);
    const tooltipWidth = tooltip.offsetWidth || 280;
    const tooltipHeight = tooltip.offsetHeight || 120;
    const x = Math.min(Math.max(preferredX, 12), window.innerWidth - tooltipWidth - 12);
    const y = Math.min(Math.max(preferredY, 12), window.innerHeight - tooltipHeight - 12);
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
}

function clearNetworkFloatingTooltip() {
    const tooltip = networkFloatingTooltip();
    tooltip.hidden = true;
}

function bindNetworkFloatingTooltips() {
    document.querySelectorAll('[data-floating-tooltip]').forEach(element => {
        element.addEventListener('mouseenter', event => showNetworkFloatingTooltip(element, event));
        element.addEventListener('mousemove', event => moveNetworkFloatingTooltip(event, element));
        element.addEventListener('mouseleave', clearNetworkFloatingTooltip);
        element.addEventListener('focus', event => showNetworkFloatingTooltip(element, event));
        element.addEventListener('blur', clearNetworkFloatingTooltip);
    });
}

function setNetworkPieSelection(index, event) {
    const tooltip = networkPieTooltip();
    document.querySelectorAll('[data-pie-index]').forEach(element => {
        element.classList.toggle('selected', element.dataset.pieIndex === index);
    });
    const slice = document.querySelector('.network-pie-slice[data-pie-index="' + index + '"]');
    const label = slice?.dataset.pieLabel || '';
    if (!label) return;
    tooltip.textContent = label;
    tooltip.hidden = false;
    moveNetworkPieTooltip(event);
}

function moveNetworkPieTooltip(event) {
    const tooltip = networkPieTooltip();
    if (!event || tooltip.hidden) return;
    if (Number.isFinite(event.clientX) && Number.isFinite(event.clientY)) {
        tooltip.style.left = (event.clientX + 14) + 'px';
        tooltip.style.top = (event.clientY + 14) + 'px';
        return;
    }
    const rect = event.currentTarget?.getBoundingClientRect?.();
    if (rect) {
        tooltip.style.left = (rect.right + 10) + 'px';
        tooltip.style.top = (rect.top + 8) + 'px';
    }
}

function clearNetworkPieSelection() {
    document.querySelectorAll('[data-pie-index]').forEach(element => element.classList.remove('selected'));
    const tooltip = networkPieTooltip();
    tooltip.hidden = true;
}

function bindNetworkPieInteractions() {
    const layout = document.querySelector('.network-pie-layout');
    if (!layout) return;
    layout.querySelectorAll('[data-pie-index]').forEach(element => {
        element.addEventListener('mouseenter', event => setNetworkPieSelection(element.dataset.pieIndex, event));
        element.addEventListener('mousemove', moveNetworkPieTooltip);
        element.addEventListener('mouseleave', clearNetworkPieSelection);
        element.addEventListener('focus', event => setNetworkPieSelection(element.dataset.pieIndex, event));
        element.addEventListener('blur', clearNetworkPieSelection);
    });
}

function renderNetworkRankedBars(entries, total) {
    const max = Math.max(...entries.map(([, count]) => count), 1);
    return '<div class="network-bars">' + entries.map(([label, count]) => (
        '<div class="network-bar-row">' +
        '<span>' + escapeHtml(label) + '</span>' +
        '<div><i style="width:' + Math.max(6, Math.round((count / max) * 100)) + '%"></i></div>' +
        '<strong>' + escapeHtml(Math.round((count / Math.max(total, 1)) * 100)) + '%</strong>' +
        '</div>'
    )).join('') + '</div>';
}

function networkTimelineTitle(events, data = {}) {
    const count = Array.isArray(events) ? events.length : 0;
    if (!count) return 'No network timeline evidence available';
    const source = normalizeNetworkModeValue(data?.summary?.timeline_source || '');
    const sourceLabel = source === 'live'
        ? 'live'
        : (source === 'last_good' ? 'last known' : 'saved');
    return count + ' ' + sourceLabel + ' network event' + (count === 1 ? '' : 's');
}

function renderNetworkTimeline(events, data = {}) {
    const selectedTimelineRangeMode = networkTimelineSelectedRangeMode();
    const projectionTimelineRangeMode = networkTimelineDisplayRangeMode(selectedTimelineRangeMode);
    const rangeConfig = NETWORK_TIMELINE_RANGES[projectionTimelineRangeMode] || NETWORK_TIMELINE_RANGES['1m'];
    const timelineRange = networkRangeAxis(projectionTimelineRangeMode);
    const timelineEvents = networkTimelineEventsForRange(Array.isArray(events) ? events.slice() : [], projectionTimelineRangeMode);
    const notableItems = networkTimelineNotables(timelineEvents, {
        minPriority: rangeConfig.minPriority,
        maxItems: rangeConfig.maxMarkers,
    });
    // Timeline is an evidence ledger for notable events and continuity gaps.
    // Routine packet rows belong to Table and must never become timeline markers
    // merely because the selected window contains no notable evidence.
    const markerItems = notableItems;
    const buckets = networkTimelineNotableBuckets(markerItems, timelineEvents.length, rangeConfig.maxMarkers, projectionTimelineRangeMode, timelineEvents);
    const track = buckets.length
        ? '<div class="network-timeline-track">' +
            '<div class="network-timeline-line"></div>' +
            buckets.map((bucket, bucketIndex) => {
                const event = bucket.events[0] || {};
                const count = bucket.events.length;
                const meta = networkTimelineBucketMeta(bucket);
                const category = networkTimelineCategoryForPriority(bucket.priority, event);
                const title = count + ' event' + (count === 1 ? '' : 's') + ' at ' + networkEventTime(event);
                const body = [
                    bucket.reason || networkEventMeaning(event),
                    meta.app + ' -> ' + meta.destination,
                    meta.protocol,
                ].filter(Boolean).join(' · ');
                const detail = [event.severity, event.confidence, event.event_id].filter(Boolean).join(' · ');
                return (
                    '<button class="network-timeline-marker" type="button" data-category="' + escapeHtml(category) + '" data-network-timeline-interval="' + bucketIndex + '" aria-controls="network-timeline-interval-' + bucketIndex + '" aria-expanded="false"' +
                    ' style="left:' + escapeHtml(bucket.left) + '%" data-floating-tooltip data-tooltip-title="' + escapeHtml(title) + '" data-tooltip-body="' + escapeHtml(body) + '" data-tooltip-meta="' + escapeHtml(detail) + '">' +
                    '<span class="network-timeline-dot">' + escapeHtml(String(Math.min(count, 99))) + '</span>' +
                    '</button>'
                );
            }).join('') +
            '</div>'
        : '<div class="empty-state">No stored network events are visible in the selected ' + escapeHtml(NETWORK_TIMELINE_RANGES[projectionTimelineRangeMode]?.label || NETWORK_TIMELINE_RANGES[selectedTimelineRangeMode]?.label || '-5s') + ' range.</div>';
    const intervalDetails = buckets.map((bucket, bucketIndex) => (
        '<details class="network-timeline-interval" id="network-timeline-interval-' + bucketIndex + '">' +
        '<summary>' + escapeHtml(bucket.events.length + ' event' + (bucket.events.length === 1 ? '' : 's') + ' at ' + networkEventTime(bucket.events[0] || {})) + '</summary>' +
        '<div class="network-timeline-interval-events">' + bucket.events.map(event => (
            '<button type="button" class="network-timeline-event"' + networkEvidenceAttributes(event, 'timeline') + '>' +
            '<strong>' + escapeHtml(networkEventMeaning(event)) + '</strong>' +
            '<span>' + escapeHtml([networkEventAppName(event), networkEventDestination(event), networkEventTime(event)].filter(Boolean).join(' · ')) + '</span>' +
            '</button>'
        )).join('') + '</div></details>'
    )).join('');
    return (
        '<div class="network-timeline" aria-label="Network event timeline">' +
        track +
        '<div class="network-timeline-intervals">' + intervalDetails + '</div>' +
        '<div class="network-timeline-legend">' +
        '<span data-category="critical">Critical</span>' +
        '<span data-category="review">Review</span>' +
        '<span data-category="notable">Notable</span>' +
        '<span data-category="local">Local</span>' +
        '<span>External</span>' +
        '</div>' +
        '<div class="network-timeline-axis"><span>' + escapeHtml(timelineRange.start) + '</span><span>' + escapeHtml(timelineRange.end) + '</span></div>' +
        '</div>'
    );
}

function bindNetworkTimelineRangeControls() {
    document.querySelectorAll('[data-network-timeline-range]').forEach(button => {
        button.addEventListener('click', () => {
            selectNetworkRange(button.dataset.networkTimelineRange || '5s', { refresh: true });
        });
    });
}

function bindNetworkTimelineIntervals() {
    document.querySelectorAll('[data-network-timeline-interval]').forEach(marker => {
        marker.addEventListener('click', () => {
            const details = byId(marker.getAttribute('aria-controls'));
            if (!details) return;
            details.open = true;
            marker.setAttribute('aria-expanded', 'true');
            details.scrollIntoView?.({ block: 'nearest' });
            details.querySelector('.network-timeline-event')?.focus();
        });
    });
}

function bindNetworkTrendYAxisControls() {
    document.querySelectorAll('[data-network-trend-y]').forEach(button => {
        button.addEventListener('click', () => {
            persistNetworkTrendYAxisMax(button.dataset.networkTrendY || '250');
            renderNetworkDisplay();
        });
    });
}

function bindNetworkTrendMetricControls() {
    document.querySelectorAll('[data-network-trend-metric]').forEach(button => {
        button.addEventListener('click', () => {
            const metric = validNetworkTrendMetric(button.dataset.networkTrendMetric);
            if (!metric || metric === networkTrendMetric) return;
            abortNetworkProjectionRequest();
            persistNetworkTrendMetric(metric);
            networkSettledProjectionState.trend = null;
            currentNetworkTrendBaseData = null;
            currentNetworkProjectionData = null;
            renderNetworkProjectionLoading('bar');
            deferNetworkProjectionLoad('bar', true);
        });
    });
}

function customFilterMatch(app, filter) {
    if (filter === 'running') return Boolean(app.running);
    if (filter === 'new') return Boolean(app.badge);
    if (filter === 'attention') return Boolean(app.badge) || Boolean(app.running);
    return app.category === filter;
}

function applyCustomFilter(filter) {
    selectedFilter = filter;
    renderCustomApps();
    setText('custom-scan-status', `Selected filter: ${filter}.`);
}

function runCustomScan() {
    const selected = Array.from(byId('custom-app-list').querySelectorAll('input:checked')).map(input => input.value);
    setText('custom-scan-status', selected.length ? `Custom scan prepared for ${selected.length} app(s).` : 'Choose at least one app or filter.');
}

function init() {
    restoreNetworkViewMode();
    document.querySelectorAll('[data-view]').forEach(link => {
        link.addEventListener('click', event => {
            event.preventDefault();
            showView(link.dataset.view);
            if (link.dataset.view === 'applications' && !applicationsLoaded) {
                loadApplications(false).catch(error => {
                    const appGrid = byId('app-grid');
                    if (appGrid) appGrid.innerHTML = '<div class="empty-state">Failed to load apps: ' + escapeHtml(error.message || error) + '</div>';
                    reportFrontendDegraded(error);
                });
            }
        });
    });
    byId('system-scan-btn')?.addEventListener('click', runSystemScan);
    byId('refresh-apps-btn')?.addEventListener('click', () => loadApplications(true).catch(reportFrontendDegraded));
    byId('scan-app-btn')?.addEventListener('click', scanSelectedApp);
    byId('app-custom-scan-toggle')?.addEventListener('click', toggleAppCustomScan);
    byId('scan-processes-btn')?.addEventListener('click', scanSelectedProcesses);
    byId('scan-network-btn')?.addEventListener('click', scanNetwork);
    const networkTabs = Array.from(document.querySelectorAll('[data-network-view]'));
    networkTabs.forEach((button, index) => {
        button.addEventListener('click', () => {
            selectNetworkView(button.dataset.networkView || 'table');
        });
        button.addEventListener('keydown', event => {
            let nextIndex = null;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % networkTabs.length;
            if (event.key === 'ArrowLeft') nextIndex = (index - 1 + networkTabs.length) % networkTabs.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = networkTabs.length - 1;
            if (nextIndex === null) return;
            event.preventDefault();
            const next = networkTabs[nextIndex];
            selectNetworkView(next.dataset.networkView || 'table');
            next.focus();
        });
    });
    document.querySelectorAll('[data-network-graph-view]').forEach(button => {
        button.addEventListener('click', () => {
            selectNetworkView(button.dataset.networkGraphView || 'bar');
        });
    });
    byId('reconcile-files-btn')?.addEventListener('click', reconcileFiles);
    const filesTabs = Array.from(document.querySelectorAll('[data-files-view]'));
    filesTabs.forEach((button, index) => {
        button.addEventListener('click', () => selectFilesView(button.dataset.filesView || 'changes'));
        button.addEventListener('keydown', event => {
            let nextIndex = null;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % filesTabs.length;
            if (event.key === 'ArrowLeft') nextIndex = (index - 1 + filesTabs.length) % filesTabs.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = filesTabs.length - 1;
            if (nextIndex === null) return;
            event.preventDefault();
            selectFilesView(filesTabs[nextIndex].dataset.filesView || 'changes', { focus: true });
        });
    });
    byId('files-search')?.addEventListener('input', event => {
        filesSearchQuery = String(event.target?.value || '');
        renderFilesDisplay();
    });
    byId('files-mediation-search')?.addEventListener('input', event => {
        filesMediationSearchQuery = String(event.target?.value || '');
        renderFilesMediationQueue();
    });
    selectFilesView(selectedFilesView);
    renderFilesMediationQueue();
    syncFilesMediationComposers();
    document.querySelectorAll('[data-mediation-composer]').forEach(form => {
        form.addEventListener('submit', queueFilesMediationRequest);
    });
    document.querySelectorAll('[data-mediation-request]').forEach(request => {
        request.addEventListener('input', updateFilesMediationComposerState);
        request.addEventListener('keydown', event => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                request.closest('[data-mediation-composer]')?.requestSubmit();
            }
        });
    });
    document.querySelectorAll('[data-mediation-suggestion]').forEach(button => {
        button.addEventListener('click', () => selectFilesMediationSuggestion(button));
    });
    byId('files-mediation-board')?.addEventListener('click', event => {
        const suggestion = event.target.closest('[data-mediation-suggestion]');
        if (suggestion) {
            selectFilesMediationSuggestion(suggestion);
            return;
        }
        const transition = event.target.closest('[data-mediation-transition]');
        if (transition) transitionFilesMediation(transition);
    });
    document.querySelectorAll('[data-mediation-add-evidence]').forEach(button => {
        button.addEventListener('click', () => {
            button.closest('[data-mediation-composer]')?.querySelector('[data-mediation-evidence]')?.click();
        });
    });
    document.querySelectorAll('[data-mediation-evidence]').forEach(evidence => {
        evidence.addEventListener('change', event => {
            filesMediationEvidenceNames = Array.from(event.target?.files || []).map(file => file.name);
            syncFilesMediationComposers();
        });
    });
    document.querySelectorAll('[data-mediation-scope]').forEach(scope => {
        scope.addEventListener('change', event => {
            filesMediationScope = String(event.target?.value || 'all');
            syncFilesMediationComposers();
        });
    });
    byId('files-mediation-toggle')?.addEventListener('click', () => {
        if (filesMediationBoardOpen) {
            setFilesMediationBoardOpen(false);
            return;
        }
        setFilesMediationPanelOpen(!filesMediationPanelOpen);
    });
    byId('files-mediation-open-board')?.addEventListener('click', () => setFilesMediationBoardOpen(true));
    byId('files-mediation-close-board')?.addEventListener('click', () => setFilesMediationBoardOpen(false));
    byId('run-custom-scan-btn')?.addEventListener('click', runCustomScan);
    document.querySelectorAll('[data-filter]').forEach(button => {
        button.addEventListener('click', () => applyCustomFilter(button.dataset.filter));
    });
    const notificationButton = byId('notification-center-button');
    if (notificationButton) {
        notificationButton.addEventListener('click', event => {
            event.preventDefault();
            const menu = byId('notification-center-menu');
            setNotificationDropdown(Boolean(menu?.hidden));
        });
    }
    byId('action-sidebar-toggle')?.addEventListener('click', () => setActionSidebarOpen(!actionSidebarOpen));
    document.addEventListener('click', event => {
        const center = byId('notification-center');
        if (center && !center.contains(event.target)) setNotificationDropdown(false);
        handleNetworkTablePinnedOutsideClick(event);
        handleFilesMediationOutsideClick(event);
        handleActionSidebarOutsideClick(event);
    }, true);
    // Product lock: bare Ctrl toggles ctrl; chords, repeats, and editable targets never toggle it.
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            if (filesMediationBoardOpen) {
                setFilesMediationBoardOpen(false);
                return;
            }
            if (filesMediationPanelOpen) {
                setFilesMediationPanelOpen(false);
                return;
            }
            setNotificationDropdown(false);
            setActionSidebarOpen(false);
            return;
        }
        if (event.key === 'Control') {
            if (event.repeat) {
                controlKeyChordActive = true;
                return;
            }
            controlKeyChordActive = false;
            return;
        }
        if (event.ctrlKey) controlKeyChordActive = true;
    });
    document.addEventListener('keyup', event => {
        if (event.key !== 'Control') return;
        const target = event.target;
        const editableTarget = target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
        if (editableTarget || controlKeyChordActive || event.altKey || event.metaKey || event.shiftKey) {
            controlKeyChordActive = false;
            return;
        }
        controlKeyChordActive = false;
        const wasActionSidebarOpen = actionSidebarOpen;
        setActionSidebarOpen(!actionSidebarOpen);
        if (actionSidebarOpen !== wasActionSidebarOpen) {
            window.CleanHouseClickTrace?.pushKeyNotice?.('Control');
        }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            networkDocumentHiddenAt = Date.now();
            suspendNetworkRenderWork();
            return;
        }
        scheduleNetworkForegroundRendering('resume');
    });
    const path = window.location.pathname;
    if (path.startsWith('/network')) showView('network');
    else if (path.startsWith('/files')) showView('files');
    else if (path.startsWith('/custom-scan')) showView('custom');
    else if (path.startsWith('/applications')) showView('applications');
    else showView('home');
    const shouldLoadApplications = path.startsWith('/applications');
    const applicationLoad = shouldLoadApplications ? loadApplications(false).then(() => {
        const match = decodeURIComponent(path.replace(/^\/applications\/?/, ''));
        if (match && match !== path) openAppDashboard(match);
    }) : Promise.resolve();
    applicationLoad.then(() => {
        return loadNotificationBadge();
    }).catch(error => {
        const appGrid = byId('app-grid');
        if (appGrid) appGrid.innerHTML = '<div class="empty-state">Failed to load apps: ' + escapeHtml(error.message || error) + '</div>';
        reportFrontendDegraded(error);
        loadNotificationBadge();
    });
    loadAllowedThreatCount().catch(reportFrontendDegraded);
    setText('apps-area-status', 'Open to load');
    setText('network-area-status', 'Open Network to check');
}

window.addEventListener('error', event => reportFrontendDegraded(event.error || event.message));
window.addEventListener('unhandledrejection', event => reportFrontendDegraded(event.reason));
window.addEventListener('focus', () => {
    networkWindowBackgrounded = false;
    scheduleNetworkForegroundRendering('focus');
});
window.addEventListener('blur', () => {
    networkWindowBackgrounded = true;
});
window.addEventListener('pageshow', event => {
    networkWindowBackgrounded = false;
    if (event.persisted) {
        scheduleNetworkForegroundRendering('pageshow');
    }
});
window.addEventListener('pagehide', () => {
    networkWindowBackgrounded = true;
    networkDocumentHiddenAt = Date.now();
    cancelNetworkSnapshotLifecycle();
    suspendNetworkRenderWork();
});
window.addEventListener('beforeunload', () => {
    clearNetworkForegroundRecoveryTimer();
    clearNetworkHeaderRenderTimer();
    cancelNetworkSnapshotLifecycle();
    stopNetworkLiveUpdates();
    stopFilesLiveMonitoring();
});
document.addEventListener('DOMContentLoaded', () => {
    try {
        init();
    } catch (error) {
        reportFrontendDegraded(error);
    }
});
