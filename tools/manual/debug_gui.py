#!/usr/bin/env python3
"""
Debug version of CleanHouse GUI to test visibility issues
"""

import tkinter as tk
import sys
import os
import logging
from pathlib import Path

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def test_simple_window():
    """Test basic Tkinter window visibility."""
    print("🧪 Testing basic Tkinter window...")

    root = tk.Tk()
    root.title("CleanHouse - Debug Test")
    root.geometry("400x300")

    # Add some content
    label = tk.Label(root, text="CleanHouse Debug Test", font=("Arial", 16, "bold"))
    label.pack(pady=50)

    button = tk.Button(root, text="Click Me", command=lambda: print("Button clicked!"))
    button.pack(pady=20)

    print("🔍 Basic window should now be visible")
    root.mainloop()
    print("✅ Basic test completed")

def test_auth_flow():
    """Test the authentication flow."""
    print("🧪 Testing authentication flow...")

    try:
        from ui.main import CleanHouseUI

        print("🔍 Creating CleanHouse UI...")
        app = CleanHouseUI()

        print("🔍 Starting mainloop...")
        app.mainloop()

    except Exception as e:
        print(f"❌ Error in authentication flow: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 CleanHouse GUI Debug Tool")
    print("=" * 50)

    choice = input("Choose test:\n1. Basic window\n2. Authentication flow\nEnter choice (1 or 2): ")

    if choice == "1":
        test_simple_window()
    elif choice == "2":
        test_auth_flow()
    else:
        print("Invalid choice")
