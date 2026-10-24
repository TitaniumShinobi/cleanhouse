#!/usr/bin/env python3
"""Short curl-based CleanHouse Network resilience smoke/soak check."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:3333"
DEFAULT_ITERATIONS = 6
DEFAULT_SLEEP_SECONDS = 1.0
DEFAULT_LATENCY_THRESHOLD_MS = 1200.0
DEFAULT_SPIKE_BUDGET = 2
NETWORK_HTML_MARKERS = ("id=\"network-message\"", "<h2>Network</h2>", "network-toolbar-context")
AUTH_REDIRECT_MARKERS = ("href=\"/login\"", "href='/login'", "Redirecting")


@dataclass(frozen=True)
class EndpointProbe:
    path: str
    kind: str


ENDPOINTS = [
    EndpointProbe("/health", "json"),
    EndpointProbe("/cleanhouse/status?ready=1", "json"),
    EndpointProbe("/cleanhouse/runtime", "json"),
    EndpointProbe("/network", "html"),
    EndpointProbe("/cleanhouse/network", "json"),
    EndpointProbe("/cleanhouse/status?refresh=1", "json"),
    EndpointProbe("/cleanhouse/network?snapshot=1", "json"),
    EndpointProbe("/cleanhouse/network/projection?view=findings&range=12mo", "json"),
    EndpointProbe("/cleanhouse/network/projection?view=trend&range=5s", "json"),
    EndpointProbe("/cleanhouse/network/projection?view=timeline&range=1m", "json"),
]


def curl_request(base_url: str, path: str, timeout_seconds: float = 5.0) -> tuple[int, str, float]:
    url = base_url.rstrip("/") + path
    started = time.monotonic()
    completed = subprocess.run(
        [
            "curl",
            "-fsS",
            "--max-time",
            f"{timeout_seconds:g}",
            "-w",
            "\n%{http_code}",
            url,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"curl failed for {path}: {stderr[:500]}")
    body, _, status_line = completed.stdout.rpartition("\n")
    try:
        status_code = int(status_line.strip())
    except ValueError as exc:
        raise RuntimeError(f"curl did not return an HTTP status for {path}") from exc
    return status_code, body, elapsed_ms


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 2)
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return round(ordered[rank], 2)


def ensure_html_ok(path: str, body: str) -> None:
    if not body.strip():
        raise RuntimeError(f"{path} returned blank HTML")
    if any(marker in body for marker in AUTH_REDIRECT_MARKERS):
        return
    if not any(marker in body for marker in NETWORK_HTML_MARKERS):
        raise RuntimeError(f"{path} did not include a recognizable Network page marker or local auth redirect")


def ensure_json_ok(path: str, status_code: int, body: str) -> dict[str, Any]:
    if status_code >= 500:
        raise RuntimeError(f"{path} returned HTTP {status_code}")
    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} returned non-JSON content") from exc
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"{path} returned an empty or non-object JSON payload")
    return payload


def runtime_restart_count(payload: dict[str, Any]) -> int | None:
    candidates = [
        payload.get("supervisor", {}).get("restart_count") if isinstance(payload.get("supervisor"), dict) else None,
        payload.get("runtime", {}).get("supervisor", {}).get("restart_count")
        if isinstance(payload.get("runtime"), dict) and isinstance(payload.get("runtime", {}).get("supervisor"), dict)
        else None,
        payload.get("data", {}).get("runtime", {}).get("supervisor", {}).get("restart_count")
        if isinstance(payload.get("data"), dict)
        and isinstance(payload.get("data", {}).get("runtime"), dict)
        and isinstance(payload.get("data", {}).get("runtime", {}).get("supervisor"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, (int, float)):
            return int(candidate)
    return None


def runtime_state(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("runtime_state"),
        payload.get("status"),
        payload.get("runtime", {}).get("runtime_state") if isinstance(payload.get("runtime"), dict) else None,
        payload.get("data", {}).get("runtime", {}).get("runtime_state")
        if isinstance(payload.get("data"), dict) and isinstance(payload.get("data", {}).get("runtime"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return "unknown"


def run_smoke(
    *,
    base_url: str,
    iterations: int,
    sleep_seconds: float,
    latency_threshold_ms: float,
    spike_budget: int,
) -> dict[str, Any]:
    endpoint_latencies: dict[str, list[float]] = {probe.path: [] for probe in ENDPOINTS}
    endpoint_spikes: dict[str, int] = {probe.path: 0 for probe in ENDPOINTS}
    endpoint_counts: dict[str, int] = {probe.path: 0 for probe in ENDPOINTS}
    restart_history: list[int] = []
    runtime_states: list[str] = []
    first_failure: dict[str, Any] | None = None

    for iteration in range(iterations):
        for probe in ENDPOINTS:
            try:
                status_code, body, elapsed_ms = curl_request(base_url, probe.path)
                endpoint_counts[probe.path] += 1
                endpoint_latencies[probe.path].append(elapsed_ms)
                if elapsed_ms > latency_threshold_ms:
                    endpoint_spikes[probe.path] += 1
                if status_code >= 500:
                    raise RuntimeError(f"{probe.path} returned HTTP {status_code}")
                if probe.kind == "html":
                    ensure_html_ok(probe.path, body)
                else:
                    payload = ensure_json_ok(probe.path, status_code, body)
                    if probe.path in {"/cleanhouse/runtime", "/cleanhouse/status?refresh=1"}:
                        restart = runtime_restart_count(payload)
                        if restart is not None:
                            restart_history.append(restart)
                            if len(restart_history) == 1:
                                pass
                            elif restart > restart_history[0]:
                                raise RuntimeError(
                                    f"{probe.path} restart_count increased from {restart_history[0]} to {restart}"
                                )
                        runtime_states.append(runtime_state(payload))
            except Exception as exc:  # noqa: BLE001
                first_failure = {
                    "iteration": iteration + 1,
                    "endpoint": probe.path,
                    "message": str(exc),
                }
                return {
                    "status": "fail",
                    "base_url": base_url,
                    "iterations": iterations,
                    "endpoint_counts": endpoint_counts,
                    "latency_ms": {
                        path: {
                            "max": round(max(values), 2) if values else 0.0,
                            "p95": p95(values),
                        }
                        for path, values in endpoint_latencies.items()
                    },
                    "spike_counts": endpoint_spikes,
                    "restart_count": {
                        "start": restart_history[0] if restart_history else None,
                        "end": restart_history[-1] if restart_history else None,
                    },
                    "runtime_states": runtime_states,
                    "first_failure": first_failure,
                }
        if iteration < iterations - 1:
            time.sleep(max(0.0, sleep_seconds))

    repeated_spikes = {
        path: count for path, count in endpoint_spikes.items() if count > spike_budget
    }
    summary = {
        "status": "pass" if not repeated_spikes else "fail",
        "base_url": base_url,
        "iterations": iterations,
        "endpoint_counts": endpoint_counts,
        "latency_ms": {
            path: {
                "max": round(max(values), 2) if values else 0.0,
                "p95": p95(values),
                "mean": round(statistics.mean(values), 2) if values else 0.0,
            }
            for path, values in endpoint_latencies.items()
        },
        "spike_counts": endpoint_spikes,
        "latency_threshold_ms": latency_threshold_ms,
        "spike_budget": spike_budget,
        "restart_count": {
            "start": restart_history[0] if restart_history else None,
            "end": restart_history[-1] if restart_history else None,
        },
        "runtime_states": runtime_states,
        "first_failure": None,
    }
    if repeated_spikes:
        summary["first_failure"] = {
            "endpoint": sorted(repeated_spikes)[0],
            "message": f"repeated latency spikes exceeded spike budget: {repeated_spikes}",
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Short curl-based CleanHouse Network resilience smoke/soak check.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--sleep-seconds", type=float, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--latency-threshold-ms", type=float, default=DEFAULT_LATENCY_THRESHOLD_MS)
    parser.add_argument("--spike-budget", type=int, default=DEFAULT_SPIKE_BUDGET)
    args = parser.parse_args()

    result = run_smoke(
        base_url=args.base_url,
        iterations=max(1, int(args.iterations)),
        sleep_seconds=max(0.0, float(args.sleep_seconds)),
        latency_threshold_ms=max(1.0, float(args.latency_threshold_ms)),
        spike_budget=max(0, int(args.spike_budget)),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
