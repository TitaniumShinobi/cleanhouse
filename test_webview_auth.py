#!/usr/bin/env python3
"""
Test script for WebView authentication with native autofill
"""

import tkinter as tk
import sys
import os
import logging

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.webview_auth import WebViewAuth

def test_webview_auth():
    """Test WebView authentication."""
    print("🧪 Testing WebView authentication...")
    
    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - WebView Auth Test")
    root.geometry("300x200")
    
    def on_auth_success(user_data):
        print(f"✅ Authentication successful: {user_data}")
        root.quit()
    
    # Create WebView auth
    auth = WebViewAuth(root, on_auth_success, ".")
    
    print("🔍 WebView authentication window should now open")
    print("   - Try using your password manager's autofill")
    print("   - Test Google/Apple OAuth buttons")
    print("   - Check native autofill support")
    
    # Show WebView login
    auth.show_login()
    
    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_webview_auth()

