#!/usr/bin/env python3
"""
Test script to verify authentication window visibility
"""

import tkinter as tk
import sys
import os
from pathlib import Path

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ui.auth import AuthWindow
from ui.user_manager import UserManager

def test_auth_window():
    """Test the authentication window in isolation."""
    print("🧪 Testing authentication window...")

    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - Test Authentication")
    root.geometry("400x500")

    # Create user manager
    user_manager = UserManager()

    def on_success(user_data):
        print(f"✅ Authentication successful: {user_data['email']}")
        root.quit()

    def on_cancel():
        print("❌ Authentication cancelled")
        root.quit()

    # Create auth window
    auth_window = AuthWindow(root, on_success, ".")

    print("🔍 Authentication window should now be visible")
    print("   - Try logging in with: admin@cleanhouse.local / admin123")
    print("   - Or create a new account")

    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_auth_window()
