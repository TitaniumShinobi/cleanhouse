# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - email_config.py
#  Email configuration UI for SMTP settings
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox
import json
import logging
from pathlib import Path
from typing import Dict, Any

class EmailConfigWindow:
    """
    Email configuration window for SMTP settings.
    """
    
    def __init__(self, parent, email_service):
        self.parent = parent
        self.email_service = email_service
        self.window = None
        self._create_window()
    
    def _create_window(self):
        """Create the email configuration window."""
        self.window = tk.Toplevel(self.parent)
        self.window.title("Email Configuration")
        self.window.geometry("500x600")
        self.window.resizable(False, False)
        
        # Center the window
        self.window.transient(self.parent)
        self.window.grab_set()
        
        # Create main frame
        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="📧 Email Configuration",
            font=("Arial", 18, "bold")
        )
        title_label.pack(pady=(0, 20))
        
        # Description
        desc_label = ttk.Label(
            main_frame,
            text="Configure SMTP settings to enable email verification with 6-digit passcodes.",
            font=("Arial", 10),
            wraplength=450
        )
        desc_label.pack(pady=(0, 20))
        
        # Configuration form
        self._create_config_form(main_frame)
        
        # Buttons
        self._create_buttons(main_frame)
        
        # Load current configuration
        self._load_current_config()
    
    def _create_config_form(self, parent):
        """Create the configuration form."""
        form_frame = ttk.LabelFrame(parent, text="SMTP Configuration", padding="15")
        form_frame.pack(fill=tk.X, pady=(0, 20))
        
        # SMTP Server
        ttk.Label(form_frame, text="SMTP Server:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.smtp_server_var = tk.StringVar(value="smtp.gmail.com")
        smtp_entry = ttk.Entry(form_frame, textvariable=self.smtp_server_var, width=40)
        smtp_entry.grid(row=0, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        
        # SMTP Port
        ttk.Label(form_frame, text="SMTP Port:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.smtp_port_var = tk.StringVar(value="587")
        port_entry = ttk.Entry(form_frame, textvariable=self.smtp_port_var, width=40)
        port_entry.grid(row=1, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        
        # Sender Email
        ttk.Label(form_frame, text="Sender Email:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.sender_email_var = tk.StringVar()
        email_entry = ttk.Entry(form_frame, textvariable=self.sender_email_var, width=40)
        email_entry.grid(row=2, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        
        # Sender Password
        ttk.Label(form_frame, text="App Password:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.sender_password_var = tk.StringVar()
        password_entry = ttk.Entry(form_frame, textvariable=self.sender_password_var, show="*", width=40)
        password_entry.grid(row=3, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        
        # Sender Name
        ttk.Label(form_frame, text="Sender Name:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.sender_name_var = tk.StringVar(value="CleanHouse Security")
        name_entry = ttk.Entry(form_frame, textvariable=self.sender_name_var, width=40)
        name_entry.grid(row=4, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        
        # Use TLS
        self.use_tls_var = tk.BooleanVar(value=True)
        tls_check = ttk.Checkbutton(
            form_frame,
            text="Use TLS (recommended)",
            variable=self.use_tls_var
        )
        tls_check.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=10)
        
        # Help text
        help_text = ttk.Label(
            form_frame,
            text="💡 For Gmail: Use your email and an App Password (not your regular password)",
            font=("Arial", 9),
            foreground="blue",
            wraplength=400
        )
        help_text.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
    
    def _create_buttons(self, parent):
        """Create action buttons."""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Test button
        test_btn = ttk.Button(
            button_frame,
            text="🧪 Test Configuration",
            command=self._test_configuration
        )
        test_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Save button
        save_btn = ttk.Button(
            button_frame,
            text="💾 Save Configuration",
            command=self._save_configuration,
            style="Accent.TButton"
        )
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Cancel button
        cancel_btn = ttk.Button(
            button_frame,
            text="❌ Cancel",
            command=self.window.destroy
        )
        cancel_btn.pack(side=tk.LEFT)
        
        # Help button
        help_btn = ttk.Button(
            button_frame,
            text="❓ Help",
            command=self._show_help
        )
        help_btn.pack(side=tk.RIGHT)
    
    def _load_current_config(self):
        """Load current configuration."""
        try:
            config = self.email_service.config
            
            self.smtp_server_var.set(config.get('smtp_server', 'smtp.gmail.com'))
            self.smtp_port_var.set(str(config.get('smtp_port', 587)))
            self.sender_email_var.set(config.get('sender_email', ''))
            self.sender_password_var.set(config.get('sender_password', ''))
            self.sender_name_var.set(config.get('sender_name', 'CleanHouse Security'))
            self.use_tls_var.set(config.get('use_tls', True))
            
        except Exception as e:
            logging.error(f"Failed to load current config: {e}")
    
    def _test_configuration(self):
        """Test the email configuration."""
        try:
            # Get configuration values
            config = {
                'smtp_server': self.smtp_server_var.get(),
                'smtp_port': int(self.smtp_port_var.get()),
                'sender_email': self.sender_email_var.get(),
                'sender_password': self.sender_password_var.get(),
                'sender_name': self.sender_name_var.get(),
                'use_tls': self.use_tls_var.get()
            }
            
            # Validate required fields
            if not config['sender_email'] or not config['sender_password']:
                messagebox.showerror("Error", "Please enter both sender email and password.")
                return
            
            # Test email sending
            test_result = self.email_service.send_verification_code(config['sender_email'])
            
            if test_result['success']:
                messagebox.showinfo(
                    "Test Successful",
                    f"Test email sent successfully!\n\n"
                    f"Check your inbox at {config['sender_email']} for the verification code."
                )
            else:
                messagebox.showerror(
                    "Test Failed",
                    f"Failed to send test email:\n{test_result.get('error', 'Unknown error')}"
                )
                
        except Exception as e:
            logging.error(f"Error testing configuration: {e}")
            messagebox.showerror("Error", f"Configuration test failed: {e}")
    
    def _save_configuration(self):
        """Save the email configuration."""
        try:
            config = {
                'smtp_server': self.smtp_server_var.get(),
                'smtp_port': int(self.smtp_port_var.get()),
                'sender_email': self.sender_email_var.get(),
                'sender_password': self.sender_password_var.get(),
                'sender_name': self.sender_name_var.get(),
                'use_tls': self.use_tls_var.get(),
                'verification_code_expiry_minutes': 10,
                'max_attempts': 3
            }
            
            # Update email service configuration
            self.email_service.config.update(config)
            self.email_service._save_config(config)
            
            messagebox.showinfo("Success", "Email configuration saved successfully!")
            self.window.destroy()
            
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
    
    def _show_help(self):
        """Show help dialog."""
        help_text = """
📧 Email Configuration Help

SMTP Settings:
• Gmail: smtp.gmail.com, port 587, use TLS
• Outlook: smtp-mail.outlook.com, port 587, use TLS
• Yahoo: smtp.mail.yahoo.com, port 587, use TLS

Gmail Setup:
1. Enable 2-Factor Authentication
2. Generate an App Password:
   - Go to Google Account settings
   - Security → 2-Step Verification → App passwords
   - Generate password for "Mail"
3. Use your Gmail address and the App Password

Security Notes:
• Never use your regular email password
• App passwords are more secure
• Keep your configuration file secure

Troubleshooting:
• Check firewall settings
• Verify SMTP server and port
• Ensure App Password is correct
• Check internet connection
        """
        
        help_window = tk.Toplevel(self.window)
        help_window.title("Email Configuration Help")
        help_window.geometry("500x400")
        
        text_widget = tk.Text(help_window, wrap=tk.WORD, padx=20, pady=20)
        text_widget.pack(fill=tk.BOTH, expand=True)
        text_widget.insert(tk.END, help_text)
        text_widget.config(state=tk.DISABLED)
        
        ttk.Button(help_window, text="Close", command=help_window.destroy).pack(pady=10)

