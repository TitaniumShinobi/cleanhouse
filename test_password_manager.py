#!/usr/bin/env python3
"""
Test script to verify password manager integration
"""

import tkinter as tk
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.password_manager_integration import PasswordManagerIntegration

def test_password_manager_integration():
    """Test the password manager integration."""
    print("🧪 Testing password manager integration...")
    
    # Create root window
    root = tk.Tk()
    root.title("CleanHouse - Password Manager Test")
    root.geometry("400x300")
    
    # Create password manager integration
    pm_integration = PasswordManagerIntegration()
    
    # Display status
    status = pm_integration.get_password_manager_status()
    print(f"✅ Password Manager Status:")
    print(f"   - macOS: {status['is_macos']}")
    print(f"   - Available managers: {status['available_managers']}")
    print(f"   - Integration enabled: {status['integration_enabled']}")
    
    # Create test form
    main_frame = tk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
    
    # Title
    title_label = tk.Label(
        main_frame,
        text="Password Manager Integration Test",
        font=("Arial", 16, "bold")
    )
    title_label.pack(pady=(0, 20))
    
    # Email field
    email_frame = tk.Frame(main_frame)
    email_frame.pack(fill=tk.X, pady=(0, 15))
    
    tk.Label(email_frame, text="Email:").pack(anchor=tk.W)
    email_entry = tk.Entry(email_frame, width=30)
    email_entry.pack(fill=tk.X, pady=(5, 0))
    
    # Password field
    password_frame = tk.Frame(main_frame)
    password_frame.pack(fill=tk.X, pady=(0, 20))
    
    tk.Label(password_frame, text="Password:").pack(anchor=tk.W)
    password_entry = tk.Entry(password_frame, show="*", width=30)
    password_entry.pack(fill=tk.X, pady=(5, 0))
    
    # Configure for password managers
    pm_integration.setup_form_for_password_managers(root, "test")
    pm_integration.configure_entry_for_password_manager(email_entry, "email", "test")
    pm_integration.configure_entry_for_password_manager(password_entry, "password", "test")
    
    # Add hint
    hint_label = pm_integration.create_password_manager_hint(main_frame)
    if hint_label:
        hint_label.pack(pady=(10, 0))
    
    # Test button
    test_btn = tk.Button(
        main_frame,
        text="Test Password Manager",
        command=lambda: print("Password manager test completed!")
    )
    test_btn.pack(pady=20)
    
    print("🔍 Test window should now be visible")
    print("   - Try using your password manager to autofill")
    print("   - Check if fields are properly detected")
    print("   - Test keyboard navigation (Tab, Enter)")
    
    # Run the test
    root.mainloop()
    print("✅ Test completed")

if __name__ == "__main__":
    test_password_manager_integration()
