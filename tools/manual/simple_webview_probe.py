#!/usr/bin/env python3
"""
Test script for simple WebView authentication with native autofill
"""

import tkinter as tk
import sys
import os
import logging
from pathlib import Path

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ui.simple_webview_auth import SimpleWebViewAuth

def test_simple_webview_auth():
    """Test simple WebView authentication."""
    print("🧪 Testing Simple WebView authentication...")

    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - Simple WebView Auth Test")
    root.geometry("300x200")

    def on_auth_success(user_data):
        print(f"✅ Authentication successful: {user_data}")
        root.quit()

    # Create WebView auth
    auth = SimpleWebViewAuth(root, on_auth_success, ".")

    print("🔍 WebView authentication window should now open")
    print("   - Try using your password manager's autofill")
    print("   - Test Google/Apple OAuth buttons")
    print("   - Check native autofill support")
    print("   - Test credentials: admin@cleanhouse.local / admin123")

    # Show WebView login
    auth.show_login()

    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_simple_webview_auth()
