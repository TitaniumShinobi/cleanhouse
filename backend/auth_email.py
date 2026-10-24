"""Bounded transactional email delivery shared by CleanHouse auth flows."""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests


DEFAULT_FROM_EMAIL = "info@thewreck.org"
DEFAULT_RESEND_KEY_FILE = Path.home() / ".cleanhouse" / "auth" / "resend-api-key"


def _owner_secret_file(path: Path) -> str:
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _resend_key() -> str:
    configured = os.getenv("RESEND_API_KEY", "").strip()
    if configured:
        return configured
    path = Path(os.getenv("CLEANHOUSE_RESEND_API_KEY_FILE", str(DEFAULT_RESEND_KEY_FILE))).expanduser()
    return _owner_secret_file(path)


def email_delivery_available() -> bool:
    service = os.getenv("EMAIL_SERVICE", "resend").strip().lower()
    if service == "resend":
        return bool((os.getenv("FROM_EMAIL", "").strip() or DEFAULT_FROM_EMAIL) and _resend_key())
    return bool(os.getenv("FROM_EMAIL", "").strip() and os.getenv("EMAIL_HOST", "").strip())


def deliver_auth_email(email: str, *, subject: str, text: str) -> None:
    sender = os.getenv("FROM_EMAIL", "").strip() or DEFAULT_FROM_EMAIL
    service = os.getenv("EMAIL_SERVICE", "resend").strip().lower()
    if not sender:
        raise RuntimeError("authentication email delivery is not configured")
    if service == "resend":
        api_key = _resend_key()
        if not api_key:
            raise RuntimeError("authentication email delivery is not configured")
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            data=json.dumps({"from": sender, "to": [email], "subject": subject, "text": text}),
            timeout=10,
        )
        response.raise_for_status()
        return
    host = os.getenv("EMAIL_HOST", "").strip()
    if not host:
        raise RuntimeError("authentication email delivery is not configured")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, email, subject
    message.set_content(text)
    port = int(os.getenv("EMAIL_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=10) as client:
        client.starttls()
        user, password = os.getenv("EMAIL_USER", ""), os.getenv("EMAIL_PASS", "")
        if user:
            client.login(user, password)
        client.send_message(message)
