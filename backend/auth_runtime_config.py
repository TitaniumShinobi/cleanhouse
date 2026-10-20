"""AUTH-aligned runtime configuration for CleanHouse OAuth providers.

The checked-in contract contains only public provider metadata. A local public
overlay supplies the OAuth client identifier, while provider secrets are read
from the process environment or the user's macOS Keychain.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT_PATH = REPO_ROOT / "config" / "auth-runtime.json"
DEFAULT_PUBLIC_OVERLAY_PATH = Path.home() / ".cleanhouse" / "auth" / "public.json"
INSTALLED_KEYCHAIN_HELPER = Path.home() / ".cleanhouse" / "auth" / "keychain-helper"

_runtime: dict[str, Any] | None = None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _origin(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _keychain_secret(service: str, account: str) -> str:
    if sys_platform() != "darwin" or not service or not account:
        return ""
    helper = Path(os.environ.get("CLEANHOUSE_KEYCHAIN_HELPER_PATH") or INSTALLED_KEYCHAIN_HELPER)
    read_fd, write_fd = os.pipe()
    try:
        result = subprocess.run(
            [str(helper)],
            input=json.dumps({
                "operation": "read",
                "service": service,
                "account": account,
                "responseFd": str(write_fd),
            }),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            pass_fds=(write_fd,),
        )
    except (OSError, subprocess.SubprocessError):
        os.close(read_fd)
        os.close(write_fd)
        return ""
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as response_pipe:
        secret = response_pipe.read().decode("utf-8")
    if result.returncode != 0:
        return ""
    return secret


def sys_platform() -> str:
    import sys

    return sys.platform


def _contract_path(env: Mapping[str, str]) -> Path:
    configured = str(env.get("CLEANHOUSE_AUTH_CONFIG_PATH") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CONTRACT_PATH


def _public_overlay_path(env: Mapping[str, str]) -> Path:
    configured = str(env.get("CLEANHOUSE_AUTH_PUBLIC_CONFIG_PATH") or "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PUBLIC_OVERLAY_PATH


def resolve_runtime_config(
    env: Mapping[str, str] | None = None,
    *,
    keychain_reader=_keychain_secret,
) -> dict[str, Any]:
    source = env if env is not None else os.environ
    contract = _read_json(_contract_path(source))
    overlay = _read_json(_public_overlay_path(source))
    allowed_origins = [
        normalized
        for value in contract.get("allowedOrigins", [])
        if (normalized := _origin(str(value)))
    ]
    configured_origin = _origin(str(source.get("CLEANHOUSE_PUBLIC_ORIGIN") or contract.get("publicOrigin") or ""))
    public_origin = configured_origin if configured_origin in allowed_origins else (allowed_origins[0] if allowed_origins else "")
    overlay_providers = overlay.get("providers") if isinstance(overlay.get("providers"), dict) else {}
    resolved_providers: dict[str, Any] = {}

    providers = contract.get("providers") if isinstance(contract.get("providers"), dict) else {}
    for provider, declaration in providers.items():
        if not isinstance(declaration, dict):
            continue
        provider_name = str(provider).lower()
        provider_overlay = overlay_providers.get(provider_name, {})
        if not isinstance(provider_overlay, dict):
            provider_overlay = {}
        client_id_env = str(declaration.get("clientIdEnvironment") or "")
        secret_env = str(declaration.get("clientSecretEnvironment") or "")
        client_id = str(
            source.get(client_id_env)
            or provider_overlay.get("clientId")
            or declaration.get("clientId")
            or ""
        ).strip()
        # Legacy names are direct-development compatibility only. The migration
        # command establishes the namespaced local public overlay for launchd.
        if not client_id and not source.get("CLEANHOUSE_LAUNCHD_OWNED"):
            client_id = str(source.get(f"{provider_name.upper()}_CLIENT_ID") or "").strip()
        secret = str(source.get(secret_env) or "").strip()
        keychain = declaration.get("clientSecretKeychain")
        if not secret and isinstance(keychain, dict):
            secret = keychain_reader(str(keychain.get("service") or ""), str(keychain.get("account") or ""))
        if not secret and not source.get("CLEANHOUSE_LAUNCHD_OWNED"):
            secret = str(source.get(f"{provider_name.upper()}_CLIENT_SECRET") or "").strip()
        callback_path = str(declaration.get("callbackPath") or f"/api/auth/{provider_name}/callback")
        callback_url = f"{public_origin}{callback_path}" if public_origin and callback_path.startswith("/") else ""
        enabled = declaration.get("enabled") is True
        resolved_providers[provider_name] = {
            "provider": provider_name,
            "label": str(declaration.get("label") or provider_name.title()),
            "enabled": enabled,
            "available": bool(enabled and client_id and secret and callback_url),
            "client_id": client_id,
            "client_secret": secret,
            "callback_url": callback_url,
        }

    return {
        "schema": contract.get("schema"),
        "app_id": contract.get("appId"),
        "allowed_origins": allowed_origins,
        "public_origin": public_origin,
        "providers": resolved_providers,
    }


def initialize_auth_runtime(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Resolve once and expose only compatibility variables required by legacy adapters."""
    global _runtime
    target = env if env is not None else os.environ
    _runtime = resolve_runtime_config(target)
    for provider, declaration in _runtime.get("providers", {}).items():
        provider_key = str(provider).upper()
        if declaration.get("client_id"):
            target.setdefault(f"CLEANHOUSE_{provider_key}_CLIENT_ID", declaration["client_id"])
        if declaration.get("callback_url"):
            target.setdefault(f"CLEANHOUSE_{provider_key}_CALLBACK_URL", declaration["callback_url"])
        # Only Google retains the historical aliases. Provider secrets are
        # never copied into the environment.
        if provider == "google":
            if declaration.get("client_id"):
                target.setdefault("GOOGLE_CLIENT_ID", declaration["client_id"])
            if declaration.get("callback_url"):
                target.setdefault("GOOGLE_CALLBACK_URL", declaration["callback_url"])
    return _runtime


def runtime_config() -> dict[str, Any]:
    return _runtime if _runtime is not None else initialize_auth_runtime()


def provider_config(provider: str) -> dict[str, Any]:
    return dict(runtime_config().get("providers", {}).get(str(provider).lower(), {}))


def public_config_payload() -> dict[str, Any]:
    config = runtime_config()
    return {
        "appId": config.get("app_id"),
        "allowedOrigins": list(config.get("allowed_origins", [])),
        "publicOrigin": config.get("public_origin"),
        "providers": [
            {
                "provider": item["provider"],
                "label": item["label"],
                "enabled": bool(item["enabled"]),
                "available": bool(item["available"]),
            }
            for item in config.get("providers", {}).values()
        ],
    }


def staged_public_contract(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return the public contract for staging; secret material is never included."""
    contract = _read_json(repo_root / "config" / "auth-runtime.json")
    overlay = _read_json(DEFAULT_PUBLIC_OVERLAY_PATH)
    overlay_providers = overlay.get("providers") if isinstance(overlay.get("providers"), dict) else {}
    providers = contract.get("providers") if isinstance(contract.get("providers"), dict) else {}
    for provider, declaration in providers.items():
        if not isinstance(declaration, dict):
            continue
        provider_overlay = overlay_providers.get(provider, {})
        if isinstance(provider_overlay, dict) and str(provider_overlay.get("clientId") or "").strip():
            declaration["clientId"] = str(provider_overlay["clientId"]).strip()
    return contract
