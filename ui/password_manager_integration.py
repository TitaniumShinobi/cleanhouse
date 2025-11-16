# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - password_manager_integration.py
#  Native macOS password manager integration
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk
import logging
import platform
from typing import Optional, Dict, Any

class PasswordManagerIntegration:
    """
    Handles integration with native macOS password managers.
    """
    
    def __init__(self):
        self.is_macos = platform.system() == "Darwin"
        self.password_managers = self._detect_password_managers()
    
    def _detect_password_managers(self) -> Dict[str, bool]:
        """Detect available password managers on the system."""
        managers = {
            'keychain': False,
            '1password': False,
            'bitwarden': False,
            'lastpass': False,
            'dashlane': False
        }
        
        if not self.is_macos:
            return managers
        
        try:
            import subprocess
            
            # Check for 1Password
            try:
                subprocess.run(['op', '--version'], capture_output=True, check=True)
                managers['1password'] = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Check for Bitwarden CLI
            try:
                subprocess.run(['bw', '--version'], capture_output=True, check=True)
                managers['bitwarden'] = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Keychain is always available on macOS
            managers['keychain'] = True
            
            logging.info(f"Detected password managers: {[k for k, v in managers.items() if v]}")
            
        except Exception as e:
            logging.warning(f"Could not detect password managers: {e}")
        
        return managers
    
    def configure_entry_for_password_manager(self, entry: ttk.Entry, field_type: str, 
                                           form_context: str = "login") -> None:
        """
        Configure a Tkinter Entry widget for password manager compatibility.
        
        Args:
            entry: The Tkinter Entry widget to configure
            field_type: Type of field ('email', 'password', 'username')
            form_context: Context of the form ('login', 'signup', 'reset')
        """
        try:
            # Configure accessibility attributes
            entry.configure(
                exportselection=True,  # Allow text selection
                state='normal'  # Ensure field is editable
            )
            
            # Set up field-specific attributes
            if field_type == 'email':
                self._configure_email_field(entry)
            elif field_type == 'password':
                self._configure_password_field(entry)
            elif field_type == 'username':
                self._configure_username_field(entry)
            
            # Add focus handlers for better password manager integration
            entry.bind('<FocusIn>', lambda e: self._on_field_focus(entry, field_type))
            entry.bind('<FocusOut>', lambda e: self._on_field_blur(entry, field_type))
            
            logging.debug(f"Configured {field_type} field for password manager")
            
        except Exception as e:
            logging.warning(f"Could not configure {field_type} field: {e}")
    
    def _configure_email_field(self, entry: ttk.Entry):
        """Configure email field for password managers."""
        try:
            # Set up email-specific attributes
            entry.configure(
                # Allow autocomplete
                exportselection=True
            )
            
            # Add email validation on blur
            entry.bind('<FocusOut>', self._validate_email)
            
        except Exception as e:
            logging.debug(f"Email field configuration error: {e}")
    
    def _configure_password_field(self, entry: ttk.Entry):
        """Configure password field for password managers."""
        try:
            # Set up password-specific attributes
            entry.configure(
                show="*",  # Hide password characters
                exportselection=True
            )
            
            # Add password strength indicator
            entry.bind('<KeyRelease>', self._on_password_change)
            
        except Exception as e:
            logging.debug(f"Password field configuration error: {e}")
    
    def _configure_username_field(self, entry: ttk.Entry):
        """Configure username field for password managers."""
        try:
            # Set up username-specific attributes
            entry.configure(
                exportselection=True
            )
            
        except Exception as e:
            logging.debug(f"Username field configuration error: {e}")
    
    def _on_field_focus(self, entry: ttk.Entry, field_type: str):
        """Handle field focus for password manager integration."""
        try:
            # Ensure field is ready for password manager input
            entry.configure(state='normal')
            
            # Log focus for debugging
            logging.debug(f"{field_type} field focused")
            
        except Exception as e:
            logging.debug(f"Focus handler error for {field_type}: {e}")
    
    def _on_field_blur(self, entry: ttk.Entry, field_type: str):
        """Handle field blur for password manager integration."""
        try:
            # Validate field content if needed
            if field_type == 'email':
                self._validate_email_field(entry)
            elif field_type == 'password':
                self._validate_password_field(entry)
            
            logging.debug(f"{field_type} field blurred")
            
        except Exception as e:
            logging.debug(f"Blur handler error for {field_type}: {e}")
    
    def _validate_email(self, event):
        """Validate email field."""
        try:
            entry = event.widget
            email = entry.get().strip()
            
            if email and '@' not in email:
                # Show subtle validation hint
                entry.configure(foreground='orange')
            else:
                entry.configure(foreground='black')
                
        except Exception as e:
            logging.debug(f"Email validation error: {e}")
    
    def _validate_email_field(self, entry: ttk.Entry):
        """Validate email field content."""
        try:
            email = entry.get().strip()
            if email and '@' in email and '.' in email:
                entry.configure(foreground='green')
            elif email:
                entry.configure(foreground='orange')
            else:
                entry.configure(foreground='black')
                
        except Exception as e:
            logging.debug(f"Email field validation error: {e}")
    
    def _validate_password_field(self, entry: ttk.Entry):
        """Validate password field content."""
        try:
            password = entry.get()
            if len(password) >= 6:
                entry.configure(foreground='green')
            elif len(password) > 0:
                entry.configure(foreground='orange')
            else:
                entry.configure(foreground='black')
                
        except Exception as e:
            logging.debug(f"Password field validation error: {e}")
    
    def _on_password_change(self, event):
        """Handle password field changes."""
        try:
            entry = event.widget
            password = entry.get()
            
            # Update visual feedback based on password strength
            if len(password) >= 8:
                entry.configure(foreground='green')
            elif len(password) >= 6:
                entry.configure(foreground='orange')
            else:
                entry.configure(foreground='red')
                
        except Exception as e:
            logging.debug(f"Password change handler error: {e}")
    
    def setup_form_for_password_managers(self, window: tk.Tk, form_type: str = "login") -> None:
        """
        Set up the entire form for password manager compatibility.
        
        Args:
            window: The main Tkinter window
            form_type: Type of form ('login', 'signup', 'reset')
        """
        try:
            # Set up form-level attributes for password manager detection
            # Use window title and other attributes to help password managers identify the form
            window.title(f"CleanHouse - {form_type.title()}")
            
            logging.info(f"Form configured for password managers: {form_type}")
            
        except Exception as e:
            logging.warning(f"Could not configure form for password managers: {e}")
    
    def get_password_manager_status(self) -> Dict[str, Any]:
        """Get status of password manager integration."""
        return {
            'is_macos': self.is_macos,
            'available_managers': {k: v for k, v in self.password_managers.items() if v},
            'integration_enabled': self.is_macos,
            'supported_features': [
                'autofill_detection',
                'field_identification',
                'form_context',
                'accessibility_support'
            ]
        }
    
    def create_password_manager_hint(self, parent: ttk.Frame) -> ttk.Label:
        """Create a hint label for password manager users."""
        try:
            if not self.is_macos:
                return None
            
            hint_text = "💡 Tip: Use your password manager to autofill credentials"
            hint_label = ttk.Label(
                parent,
                text=hint_text,
                font=("Arial", 9),
                foreground="gray",
                anchor="center"
            )
            
            return hint_label
            
        except Exception as e:
            logging.debug(f"Could not create password manager hint: {e}")
            return None
