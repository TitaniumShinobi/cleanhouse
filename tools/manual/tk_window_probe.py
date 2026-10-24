#!/usr/bin/env python3
"""
Simple test to verify Tkinter window visibility on macOS
"""

import tkinter as tk
import sys
import os

def test_basic_window():
    """Test basic Tkinter window visibility."""
    print("🧪 Testing basic Tkinter window...")

    root = tk.Tk()
    root.title("CleanHouse - Test Window")
    root.geometry("400x300")

    # Add some content
    label = tk.Label(root, text="CleanHouse Test Window", font=("Arial", 16, "bold"))
    label.pack(pady=50)

    button = tk.Button(root, text="Test Button", command=lambda: print("Button clicked!"))
    button.pack(pady=20)

    # macOS-specific fixes
    try:
        root.tk.call('wm', 'attributes', '.', '-topmost', True)
        root.tk.call('wm', 'attributes', '.', '-topmost', False)
        root.lift()
        root.focus_force()
        print("✅ Applied macOS window fixes")
    except Exception as e:
        print(f"⚠️  Could not apply macOS fixes: {e}")

    print("🔍 Window should now be visible")
    print("   - If you can see this window, Tkinter is working")
    print("   - If not, there's a macOS Tkinter issue")

    # Run for 5 seconds then close
    root.after(5000, root.quit)
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_basic_window()

