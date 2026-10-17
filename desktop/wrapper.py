"""Attach-only desktop wrapper for the supervised CleanHouse runtime."""

from __future__ import annotations

import logging
import os
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False
    webview = None

from backend import runtime_supervisor
from backend import launch_agent


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3333


class DesktopAuthApi:
    """Minimal system-browser handoff for the AUTH-configured Google flow."""

    def __init__(self, host: str, port: int):
        self.origin = f"http://{host}:{port}"

    def openOAuthUrl(self, transaction_id=None, provider: str = "") -> dict[str, object]:
        # Accept only a transaction identifier, never a caller-supplied URL or token.
        if not isinstance(transaction_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", transaction_id):
            return {"success": False, "message": "A prepared sign-in transaction is required."}
        opened = webbrowser.open(f"{self.origin}/api/auth/desktop/start/{transaction_id}")
        return {"success": bool(opened)}

    def activateExistingWindow(self) -> dict[str, object]:
        if WEBVIEW_AVAILABLE and webview.windows:
            window = webview.windows[0]
            window.restore()
            window.show()
            return {"success": True}
        return {"success": False}


def _resolve_cleanhouse_host() -> str:
    return os.getenv("CLEANHOUSE_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST


def _resolve_cleanhouse_port() -> int:
    raw = os.getenv("CLEANHOUSE_PORT", str(DEFAULT_PORT)).strip() or str(DEFAULT_PORT)
    try:
        port = int(raw)
    except ValueError:
        logging.warning("Invalid CLEANHOUSE_PORT=%r; falling back to %s", raw, DEFAULT_PORT)
        return DEFAULT_PORT
    return port


def cleanhouse_url(path: str = "/dashboard") -> str:
    return f"http://{_resolve_cleanhouse_host()}:{_resolve_cleanhouse_port()}{path}"


def register_tool_hooks():
    """Placeholder for tool hook registration; HTTP tool-event route is owned by the backend."""
    pass


def main() -> None:
    if not WEBVIEW_AVAILABLE:
        print("pywebview not available. Install with: pip install pywebview")
        sys.exit(1)

    host = _resolve_cleanhouse_host()
    port = _resolve_cleanhouse_port()
    if sys.platform == "darwin":
        launchd = launch_agent.install(sys.executable, host=host, port=port, start=True)
        if launchd.get("status") == "error":
            print(f"launch agent setup failed: {launchd.get('message')}")
            sys.exit(1)
    runtime = runtime_supervisor.ensure_runtime(host, port, timeout_seconds=30.0)
    if runtime.get("operator_ready") is not True:
        print(
            "startup failed: "
            f"operator_ready={runtime.get('operator_ready')} "
            f"runtime_state={runtime.get('runtime_state')} "
            f"reasons={runtime.get('reason_codes')}"
        )
        sys.exit(1)

    webview.create_window(
        "CleanHouse",
        cleanhouse_url("/dashboard"),
        js_api=DesktopAuthApi(host, port),
        width=450,
        height=775,
        resizable=True,
        min_size=(450, 550),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
