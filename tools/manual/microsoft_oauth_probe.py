#!/usr/bin/env python3
"""
Test script for Microsoft OAuth integration
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

def test_microsoft_oauth():
    """Test Microsoft OAuth integration."""
    print("🧪 Testing Microsoft OAuth integration...")

    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - Microsoft OAuth Test")
    root.geometry("300x200")

    def on_auth_success(user_data):
        print(f"✅ Authentication successful: {user_data}")
        root.quit()

    # Create WebView auth
    auth = SimpleWebViewAuth(root, on_auth_success, ".")

    print("🔍 WebView authentication window should now open")
    print("   - Test Microsoft OAuth button")
    print("   - Check OAuth popup focus management")
    print("   - Test timeout handling (30 seconds)")
    print("   - Test credentials: admin@cleanhouse.local / admin123")
    print("   - Try Google, Apple, and Microsoft OAuth buttons")

    # Show WebView login
    auth.show_login()

    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_microsoft_oauth()
