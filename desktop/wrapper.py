"""Deterministic launcher for the CleanHouse desktop wrapper."""

from __future__ import annotations

import json
import threading
import time
import logging
from pathlib import Path
import sys
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False
    webview = None

from backend.server import DEFAULT_HOST, app, _cleanhouse_port

MAX_STARTUP_WAIT_SECONDS = 20
STARTUP_POLL_SECONDS = 0.25


def _resolve_cleanhouse_host() -> str:
    """Resolve the wrapper host from env with explicit default."""
    return os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def _resolve_cleanhouse_port() -> int:
    """Resolve the wrapper port from env with explicit default."""
    return _cleanhouse_port()


def _base_url() -> str:
    host = _resolve_cleanhouse_host()
    port = _resolve_cleanhouse_port()
    return f"http://{host}:{port}"


def cleanhouse_url(path: str = "/dashboard") -> str:
    """Return a local CleanHouse URL for the given path."""
    return _base_url() + path

def start_server():
    """Start Flask server in background thread"""
    app.run(
        host=_resolve_cleanhouse_host(),
        port=_resolve_cleanhouse_port(),
        debug=False,
        threaded=True,
        use_reloader=False,
    )


def _http_probe(url: str) -> tuple[int | None, bytes]:
    """Probe a local URL and return (status_code, body)."""
    try:
        with urlopen(Request(url, headers={"User-Agent": "CleanHouse Desktop Launcher"}), timeout=1.0) as response:
            return response.getcode(), response.read()
    except (ConnectionError, TimeoutError, URLError, HTTPError):
        return None, b""


def _await_backend() -> None:
    """Wait until dashboard endpoint is reachable and verify status payload shape."""
    deadline = time.monotonic() + MAX_STARTUP_WAIT_SECONDS
    dashboard_url = cleanhouse_url("/dashboard")
    status_url = cleanhouse_url("/cleanhouse/status?ready=1")
    last_error = "backend not yet reachable"

    while time.monotonic() < deadline:
        code, body = _http_probe(dashboard_url)
        if code == 200:
            status_code, status_body = _http_probe(status_url)
            if status_code == 200:
                try:
                    json.loads(status_body.decode("utf-8"))
                except (TypeError, ValueError, UnicodeDecodeError):
                    logging.warning("Wrapper status probe warning: /cleanhouse/status is not JSON")
                else:
                    logging.info("Wrapper readiness: %s is reachable and /cleanhouse/status is available", dashboard_url)
            else:
                logging.warning(
                    "Wrapper status probe warning: /cleanhouse/status unavailable (status=%s)",
                    status_code,
                )

            logging.info("Wrapper readiness: %s is reachable", dashboard_url)
            return
        else:
            last_error = f"dashboard probe failed with status {code}" if code is not None else "dashboard probe connection unavailable"

        logging.debug("Startup probe not ready yet: %s", last_error)
        time.sleep(STARTUP_POLL_SECONDS)

    raise RuntimeError(
        f"backend did not become ready in {MAX_STARTUP_WAIT_SECONDS}s; last probe: {last_error}"
    )

def register_tool_hooks():
    """Register tool event hooks for Cursor/OpenCode/Codex/Copilot CLI boundaries.

    Calling this function enables the adapter to accept tool boundary events
    posted by tool CLI wrappers. In v1 this is a configuration placeholder;
    the HTTP endpoint ``POST /cleanhouse/tool-event`` is always available
    and no sidecar process is started.
    """
    pass  # Sidecar not needed in v1 — tools POST directly


def main():
    """Launch desktop application"""
    if not WEBVIEW_AVAILABLE:
        print("❌ pywebview not available. Install with: pip install pywebview")
        sys.exit(1)

    # Start Flask server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    try:
        _await_backend()
    except RuntimeError as error:
        print(f"❌ startup failed: {error}")
        print("Hint: verify CLEANHOUSE_HOST/CLEANHOUSE_PORT and backend dependencies.")
        sys.exit(1)

    # Create WebView window
    webview.create_window('CleanHouse', cleanhouse_url("/dashboard"), width=450, height=775, resizable=True, min_size=(450, 550))

    # Start WebView
    webview.start(debug=False)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
