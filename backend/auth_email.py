"""Bounded transactional email delivery shared by CleanHouse auth flows."""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage

import requests


def deliver_auth_email(email: str, *, subject: str, text: str) -> None:
    sender = os.getenv("FROM_EMAIL", "").strip()
    service = os.getenv("EMAIL_SERVICE", "resend").strip().lower()
    if not sender:
        raise RuntimeError("authentication email delivery is not configured")
    if service == "resend":
        api_key = os.getenv("RESEND_API_KEY", "").strip()
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
