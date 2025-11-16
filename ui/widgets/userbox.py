# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - userbox.py
#  User information and controls widget
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import Dict, Any, Callable

class UserBox:
    """
    Widget displaying current user information and controls.
    """
    
    def __init__(self, parent, user_data: Dict[str, Any], on_logout: Callable):
        self.parent = parent
        self.user_data = user_data
        self.on_logout = on_logout
        
        # Create the user box frame
        self.frame = ttk.Frame(parent)
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the user box widgets."""
        # User info frame
        info_frame = ttk.Frame(self.frame)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # User icon and name
        user_frame = ttk.Frame(info_frame)
        user_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # User icon (simple circle with first letter)
        icon_frame = ttk.Frame(user_frame)
        icon_frame.pack(side=tk.LEFT, padx=(0, 10))
        
        self.icon_label = ttk.Label(
            icon_frame,
            text=self.user_data["email"][0].upper(),
            font=("Arial", 12, "bold"),
            foreground="white",
            background="#007ACC",
            width=3,
            anchor=tk.CENTER
        )
        self.icon_label.pack()
        
        # User details
        details_frame = ttk.Frame(user_frame)
        details_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Email
        self.email_label = ttk.Label(
            details_frame,
            text=self.user_data["email"],
            font=("Arial", 10, "bold")
        )
        self.email_label.pack(anchor=tk.W)
        
        # Role
        role_text = f"Role: {self.user_data['role'].title()}"
        if self.user_data['role'] == 'dev':
            role_text += " (Developer)"
        
        self.role_label = ttk.Label(
            details_frame,
            text=role_text,
            font=("Arial", 9),
            foreground="gray"
        )
        self.role_label.pack(anchor=tk.W)
        
        # Controls frame
        controls_frame = ttk.Frame(self.frame)
        controls_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Settings button
        settings_btn = ttk.Button(
            controls_frame,
            text="⚙️",
            command=self._show_settings,
            width=3
        )
        settings_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # Logout button
        logout_btn = ttk.Button(
            controls_frame,
            text="Logout",
            command=self._handle_logout,
            style="Accent.TButton"
        )
        logout_btn.pack(side=tk.LEFT)
    
    def _show_settings(self):
        """Show user settings dialog."""
        settings_window = tk.Toplevel(self.parent)
        settings_window.title("User Settings")
        settings_window.geometry("400x300")
        settings_window.resizable(False, False)
        
        # Center the window
        settings_window.transient(self.parent)
        settings_window.grab_set()
        
        # Main frame
        main_frame = ttk.Frame(settings_window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="User Settings",
            font=("Arial", 16, "bold")
        )
        title_label.pack(pady=(0, 20))
        
        # User info section
        info_frame = ttk.LabelFrame(main_frame, text="Account Information", padding="10")
        info_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Email (read-only)
        email_frame = ttk.Frame(info_frame)
        email_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(email_frame, text="Email:").pack(side=tk.LEFT)
        email_value = ttk.Label(
            email_frame,
            text=self.user_data["email"],
            font=("Arial", 10, "bold")
        )
        email_value.pack(side=tk.RIGHT)
        
        # Role (read-only)
        role_frame = ttk.Frame(info_frame)
        role_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(role_frame, text="Role:").pack(side=tk.LEFT)
        role_value = ttk.Label(
            role_frame,
            text=self.user_data["role"].title(),
            font=("Arial", 10, "bold")
        )
        role_value.pack(side=tk.RIGHT)
        
        # Preferences section
        prefs_frame = ttk.LabelFrame(main_frame, text="Preferences", padding="10")
        prefs_frame.pack(fill=tk.BOTH, expand=True)
        
        # Theme selection
        theme_frame = ttk.Frame(prefs_frame)
        theme_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(theme_frame, text="Theme:").pack(side=tk.LEFT)
        theme_var = tk.StringVar(value=self.user_data.get("preferences", {}).get("theme", "default"))
        theme_combo = ttk.Combobox(
            theme_frame,
            textvariable=theme_var,
            values=["default", "dark", "light"],
            state="readonly",
            width=15
        )
        theme_combo.pack(side=tk.RIGHT)
        
        # Notifications
        notif_var = tk.BooleanVar(value=self.user_data.get("preferences", {}).get("notifications", True))
        notif_check = ttk.Checkbutton(
            prefs_frame,
            text="Enable notifications",
            variable=notif_var
        )
        notif_check.pack(anchor=tk.W, pady=(0, 10))
        
        # Auto scan
        auto_scan_var = tk.BooleanVar(value=self.user_data.get("preferences", {}).get("auto_scan", False))
        auto_scan_check = ttk.Checkbutton(
            prefs_frame,
            text="Enable auto-scan on startup",
            variable=auto_scan_var
        )
        auto_scan_check.pack(anchor=tk.W, pady=(0, 20))
        
        # Buttons
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X)
        
        # Save button
        save_btn = ttk.Button(
            buttons_frame,
            text="Save",
            command=lambda: self._save_settings(settings_window, {
                "theme": theme_var.get(),
                "notifications": notif_var.get(),
                "auto_scan": auto_scan_var.get()
            })
        )
        save_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Cancel button
        cancel_btn = ttk.Button(
            buttons_frame,
            text="Cancel",
            command=settings_window.destroy
        )
        cancel_btn.pack(side=tk.RIGHT)
    
    def _save_settings(self, window, preferences):
        """Save user preferences."""
        try:
            # Update user data
            self.user_data["preferences"] = preferences
            
            # Here you would typically save to the database
            # For now, we'll just show a success message
            messagebox.showinfo("Success", "Settings saved successfully!")
            window.destroy()
            
        except Exception as e:
            logging.error(f"Failed to save settings: {e}")
            messagebox.showerror("Error", "Failed to save settings.")
    
    def _handle_logout(self):
        """Handle logout."""
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.on_logout()
    
    def update_user_data(self, user_data: Dict[str, Any]):
        """Update the user data and refresh the display."""
        self.user_data = user_data
        
        # Update email
        self.email_label.config(text=user_data["email"])
        
        # Update role
        role_text = f"Role: {user_data['role'].title()}"
        if user_data['role'] == 'dev':
            role_text += " (Developer)"
        self.role_label.config(text=role_text)
        
        # Update icon
        self.icon_label.config(text=user_data["email"][0].upper())
    
    def pack(self, **kwargs):
        """Pack the user box frame."""
        self.frame.pack(**kwargs)
    
    def grid(self, **kwargs):
        """Grid the user box frame."""
        self.frame.grid(**kwargs)

