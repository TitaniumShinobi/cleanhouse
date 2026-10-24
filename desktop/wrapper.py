"""Attach-only desktop wrapper for the supervised CleanHouse runtime."""

from __future__ import annotations

import logging
import os
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
from backend import auth_runtime_config


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3333


class DesktopAuthApi:
    """Minimal system-browser handoff for the AUTH-configured Google flow."""

    def __init__(self, host: str, port: int):
        runtime_origin = str(auth_runtime_config.runtime_config().get("public_origin") or "").rstrip("/")
        self.origin = runtime_origin or f"http://{host}:{port}"

    def openOAuthUrl(self, _unused=None, provider: str = "") -> dict[str, object]:
        normalized = str(provider or "").strip().lower()
        if normalized != "google":
            return {"success": False, "message": "This sign-in provider is unavailable."}
        opened = webbrowser.open(f"{self.origin}/api/auth/oauth/google")
        return {
            "success": bool(opened),
            "message": "Opening Google authentication in your browser. Please complete sign-in there."
            if opened else "The system browser could not be opened.",
        }


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


def cleanhouse_url(path: str = "/overview") -> str:
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
        cleanhouse_url("/overview"),
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
