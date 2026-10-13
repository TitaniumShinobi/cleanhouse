#!/usr/bin/env python3
"""Migrate CleanHouse's existing Google OAuth settings without disclosing them."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
PUBLIC_PATH = Path.home() / ".cleanhouse" / "auth" / "public.json"
KEYCHAIN_SERVICE = "org.cleanhouse.auth.google"
KEYCHAIN_ACCOUNT = "client-secret-v2"
KEYCHAIN_HELPER = REPO_ROOT / "backend" / "keychain_secret.swift"
INSTALLED_KEYCHAIN_HELPER = Path.home() / ".cleanhouse" / "auth" / "keychain-helper"


def _dotenv_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def store_keychain_secret(secret: str, *, runner=subprocess.run) -> None:
    INSTALLED_KEYCHAIN_HELPER.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(INSTALLED_KEYCHAIN_HELPER.parent, 0o700)
    compiled = runner(
        ["/usr/bin/xcrun", "swiftc", str(KEYCHAIN_HELPER), "-o", str(INSTALLED_KEYCHAIN_HELPER)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if compiled.returncode != 0:
        raise RuntimeError("Keychain helper compilation failed")
    os.chmod(INSTALLED_KEYCHAIN_HELPER, 0o700)
    request = json.dumps({
        "operation": "upsert",
        "service": KEYCHAIN_SERVICE,
        "account": KEYCHAIN_ACCOUNT,
        "value": secret,
    })
    completed = runner(
        [str(INSTALLED_KEYCHAIN_HELPER)],
        input=request,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        response = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        response = {}
    if completed.returncode != 0 or response.get("ok") is not True:
        raise RuntimeError("Keychain provisioning failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize", action="store_true", help="authorize the bounded Keychain/public-config migration")
    args = parser.parse_args()
    if not args.authorize:
        parser.error("--authorize is required")
    if os.uname().sysname != "Darwin":
        raise SystemExit("CleanHouse Keychain provisioning requires macOS")
    values = _dotenv_values(ENV_PATH)
    client_id = values.get("CLEANHOUSE_GOOGLE_CLIENT_ID") or values.get("GOOGLE_CLIENT_ID") or ""
    secret = values.get("CLEANHOUSE_GOOGLE_CLIENT_SECRET") or values.get("GOOGLE_CLIENT_SECRET") or ""
    if not client_id or not secret:
        raise SystemExit("existing Google OAuth client ID and secret are required")

    try:
        store_keychain_secret(secret)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        raise SystemExit("Keychain provisioning failed")

    PUBLIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "cleanhouse.auth-public.v1",
        "providers": {"google": {"clientId": client_id}},
    }
    fd, temporary_name = tempfile.mkstemp(prefix=".public.", suffix=".json", dir=str(PUBLIC_PATH.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, PUBLIC_PATH)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print("CleanHouse Google OAuth configuration provisioned (credential values withheld).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
