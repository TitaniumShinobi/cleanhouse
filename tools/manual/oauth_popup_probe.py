#!/usr/bin/env python3
"""
Test script for OAuth popup fixes and focus management
"""

import tkinter as tk
import sys
import os
import logging
import time
from pathlib import Path

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ui.simple_webview_auth import SimpleWebViewAuth

def test_oauth_popup_fixes():
    """Test OAuth popup fixes and focus management."""
    print("🧪 Testing OAuth popup fixes...")

    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - OAuth Popup Test")
    root.geometry("300x200")

    def on_auth_success(user_data):
        print(f"✅ Authentication successful: {user_data}")
        root.quit()

    # Create WebView auth
    auth = SimpleWebViewAuth(root, on_auth_success, ".")

    print("🔍 WebView authentication window should now open")
    print("   - Test OAuth popup focus management")
    print("   - Try Google/Apple OAuth buttons")
    print("   - Check if popups appear in front")
    print("   - Test timeout handling (30 seconds)")
    print("   - Test credentials: admin@cleanhouse.local / admin123")

    # Show WebView login
    auth.show_login()

    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_oauth_popup_fixes()
