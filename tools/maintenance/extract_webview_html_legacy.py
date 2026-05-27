#!/usr/bin/env python3
"""
Helper script to extract HTML/CSS/JS from simple_webview_auth.py
"""

import re
from pathlib import Path

def extract_html_content():
    """Extract HTML content from simple_webview_auth.py"""
    source_file = Path(__file__).resolve().parents[2] / "ui" / "simple_webview_auth.py"

    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract login HTML
    login_match = re.search(
        r'def _create_login_html\(self\) -> str:.*?return """(.*?)"""',
        content,
        re.DOTALL
    )

    # Extract signup HTML
    signup_match = re.search(
        r'def _create_signup_html\(self\) -> str:.*?return """(.*?)"""',
        content,
        re.DOTALL
    )

    if login_match:
        login_html = login_match.group(1).strip()
        return login_html, signup_match.group(1).strip() if signup_match else None

    return None, None

if __name__ == "__main__":
    login_html, signup_html = extract_html_content()
    if login_html:
        print("✅ Successfully extracted HTML content")
        print(f"Login HTML length: {len(login_html)} chars")
        if signup_html:
            print(f"Signup HTML length: {len(signup_html)} chars")
    else:
        print("❌ Failed to extract HTML content")
