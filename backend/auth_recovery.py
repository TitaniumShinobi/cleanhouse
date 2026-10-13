"""Product-native, single-use CleanHouse account recovery."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import smtplib
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import requests


def _database_path() -> Path:
    configured = os.getenv("CLEANHOUSE_AUTH_RECOVERY_DB", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".cleanhouse" / "auth" / "recovery.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE IF NOT EXISTS recovery_tokens (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL,
        expires_at TEXT NOT NULL, used_at TEXT
    )""")
    connection.commit()
    return connection


def issue_recovery(user_id: str, email: str, lifetime_minutes: int = 30) -> str:
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(minutes=lifetime_minutes)
    with closing(_connect()) as connection:
        connection.execute("DELETE FROM recovery_tokens WHERE user_id = ? AND used_at IS NULL", (user_id,))
        connection.execute(
            "INSERT INTO recovery_tokens(token_hash,user_id,email,expires_at,used_at) VALUES(?,?,?,?,NULL)",
            (digest, user_id, email.lower(), expires.isoformat()),
        )
        connection.commit()
    return raw


def consume_recovery(raw: str) -> dict[str, str] | None:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT user_id,email,expires_at,used_at FROM recovery_tokens WHERE token_hash = ?", (digest,)
        ).fetchone()
        if not row or row[3] is not None:
            return None
        try:
            expires = datetime.fromisoformat(row[2])
        except ValueError:
            return None
        if expires <= now:
            return None
        updated = connection.execute(
            "UPDATE recovery_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL",
            (now.isoformat(), digest),
        )
        connection.commit()
        if updated.rowcount != 1:
            return None
        return {"user_id": row[0], "email": row[1]}


def deliver_recovery(email: str, token: str, public_origin: str) -> None:
    link = f"{public_origin.rstrip('/')}/password-reset?token={quote(token)}"
    sender = os.getenv("FROM_EMAIL", "").strip()
    service = os.getenv("EMAIL_SERVICE", "resend").strip().lower()
    if service == "resend":
        api_key = os.getenv("RESEND_API_KEY", "").strip()
        if not api_key or not sender:
            raise RuntimeError("recovery delivery is not configured")
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            data=json.dumps({"from": sender, "to": [email], "subject": "Reset your CleanHouse password", "text": f"Reset your CleanHouse password: {link}\nThis link expires in 30 minutes."}),
            timeout=10,
        )
        response.raise_for_status()
        return
    host = os.getenv("EMAIL_HOST", "").strip()
    if not host or not sender:
        raise RuntimeError("recovery delivery is not configured")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, email, "Reset your CleanHouse password"
    message.set_content(f"Reset your CleanHouse password: {link}\nThis link expires in 30 minutes.")
    port = int(os.getenv("EMAIL_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=10) as client:
        client.starttls()
        user, password = os.getenv("EMAIL_USER", ""), os.getenv("EMAIL_PASS", "")
        if user:
            client.login(user, password)
        client.send_message(message)
