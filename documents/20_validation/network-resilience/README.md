# CleanHouse Network Resilience Checks

Purpose: make Network stale-state regressions runnable from Codex CLI or any shell before they reach the app runtime.

Canonical static command:

```bash
bash scripts/run-network-resilience-checks.sh
```

Repeat the static gate:

```bash
bash scripts/run-network-resilience-checks.sh --repeat 3
```

Static coverage:
- `python3 -m unittest tests.test_network_header_static`
- `node --test tests/network_resilience_node.test.mjs`

The static gate covers Network hydration epochs, abort controllers, canonical snapshot use, stale projection rejection, range persistence, timeline fallback behavior, trend live-tick fallback, grouped findings counts, and render-model/header count contracts.

Live endpoint smoke after CleanHouse is already running:

```bash
bash scripts/run-network-resilience-checks.sh --live --base-url http://127.0.0.1:3333
```

Live smoke coverage:
- `/network`
- `/cleanhouse/network`
- `/cleanhouse/network?snapshot=1`
- `/cleanhouse/status?ready=1`
- `/cleanhouse/status?refresh=1`
- `/health`
- `/cleanhouse/runtime`
- `/cleanhouse/network/projection?view=findings&range=12mo`
- `/cleanhouse/network/projection?view=trend&range=5s`
- `/cleanhouse/network/projection?view=timeline&range=1m`

The live smoke exits nonzero on blank Network HTML, non-JSON API payloads, HTTP 5xx responses, runtime restart-count increases during the run, or repeated latency spikes above the configured budget.

Tuning:

```bash
bash scripts/run-network-resilience-checks.sh --live --iterations 8 --sleep-seconds 0.5 --latency-threshold-ms 1500 --spike-budget 2
```

Environment equivalents:
- `CLEANHOUSE_NETWORK_RESILIENCE_LIVE=1`
- `CLEANHOUSE_NETWORK_BASE_URL=http://127.0.0.1:3333`
- `CLEANHOUSE_NETWORK_RESILIENCE_REPEAT=3`
- `CLEANHOUSE_NETWORK_RESILIENCE_ITERATIONS=8`
- `CLEANHOUSE_NETWORK_RESILIENCE_SLEEP_SECONDS=0.5`
- `CLEANHOUSE_NETWORK_RESILIENCE_LATENCY_THRESHOLD_MS=1500`
- `CLEANHOUSE_NETWORK_RESILIENCE_SPIKE_BUDGET=2`

## Deferred freshness bookmark

During the Files product pass on 2026-08-20, the Network table was observed displaying evidence roughly two minutes behind the wall clock. This pass intentionally does not change Network. A future focused investigation should measure capture time, persistence time, SSE delivery time, and row-render time separately before changing retention, polling, or buffering behavior.
