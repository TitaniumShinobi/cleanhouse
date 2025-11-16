# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - email_verification.py
#  Email verification UI with 6-digit passcode input
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import Callable, Optional
from datetime import datetime

class EmailVerificationWindow:
    """
    Email verification window for 6-digit passcode input.
    """
    
    def __init__(self, parent, email: str, on_success: Callable, on_resend: Callable):
        self.parent = parent
        self.email = email
        self.on_success = on_success
        self.on_resend = on_resend
        self.window = None
        self.attempts = 0
        self.max_attempts = 3
        
        self._create_window()
    
    def _create_window(self):
        """Create the email verification window."""
        self.window = tk.Toplevel(self.parent)
        self.window.title("Email Verification")
        self.window.geometry("450x500")
        self.window.resizable(False, False)
        
        # Center the window
        self.window.transient(self.parent)
        self.window.grab_set()
        
        # Create main frame
        main_frame = ttk.Frame(self.window, padding="30")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="📧 Email Verification",
            font=("Arial", 20, "bold")
        )
        title_label.pack(pady=(0, 10))
        
        # Email display
        email_frame = ttk.Frame(main_frame)
        email_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(email_frame, text="We sent a 6-digit code to:", font=("Arial", 12)).pack()
        email_label = ttk.Label(
            email_frame,
            text=self.email,
            font=("Arial", 12, "bold"),
            foreground="#2c3e50"
        )
        email_label.pack(pady=(5, 0))
        
        # Code input section
        code_frame = ttk.LabelFrame(main_frame, text="Enter Verification Code", padding="20")
        code_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Code input
        ttk.Label(code_frame, text="6-Digit Code:", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        self.code_var = tk.StringVar()
        self.code_var.trace('w', self._on_code_change)
        
        # Create 6 individual input boxes
        self.code_entries = []
        code_input_frame = ttk.Frame(code_frame)
        code_input_frame.pack(pady=(0, 15))
        
        for i in range(6):
            entry = ttk.Entry(
                code_input_frame,
                textvariable=tk.StringVar(),
                width=3,
                font=("Arial", 16, "bold"),
                justify=tk.CENTER
            )
            entry.pack(side=tk.LEFT, padx=2)
            entry.bind('<KeyPress>', lambda e, idx=i: self._on_key_press(e, idx))
            entry.bind('<KeyRelease>', lambda e, idx=i: self._on_key_release(e, idx))
            self.code_entries.append(entry)
        
        # Verify button
        self.verify_btn = ttk.Button(
            code_frame,
            text="✅ Verify Code",
            command=self._verify_code,
            style="Accent.TButton",
            state=tk.DISABLED
        )
        self.verify_btn.pack(pady=(10, 0))
        
        # Status label
        self.status_label = ttk.Label(
            code_frame,
            text="",
            font=("Arial", 10),
            foreground="gray"
        )
        self.status_label.pack(pady=(10, 0))
        
        # Resend section
        resend_frame = ttk.Frame(main_frame)
        resend_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(resend_frame, text="Didn't receive the code?", font=("Arial", 11)).pack()
        
        self.resend_btn = ttk.Button(
            resend_frame,
            text="📤 Resend Code",
            command=self._resend_code
        )
        self.resend_btn.pack(pady=(5, 0))
        
        # Timer label
        self.timer_label = ttk.Label(
            resend_frame,
            text="",
            font=("Arial", 10),
            foreground="orange"
        )
        self.timer_label.pack(pady=(5, 0))
        
        # Action buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        # Back button
        back_btn = ttk.Button(
            button_frame,
            text="← Back to Login",
            command=self._go_back
        )
        back_btn.pack(side=tk.LEFT)
        
        # Cancel button
        cancel_btn = ttk.Button(
            button_frame,
            text="❌ Cancel",
            command=self.window.destroy
        )
        cancel_btn.pack(side=tk.RIGHT)
        
        # Start timer
        self._start_timer()
    
    def _on_code_change(self, *args):
        """Handle code input changes."""
        # This method is called when the code variable changes
        pass
    
    def _on_key_press(self, event, index):
        """Handle key press in code entry."""
        # Allow only digits
        if not event.char.isdigit() and event.keysym not in ['BackSpace', 'Delete', 'Left', 'Right', 'Tab']:
            return 'break'
    
    def _on_key_release(self, event, index):
        """Handle key release in code entry."""
        entry = self.code_entries[index]
        value = entry.get()
        
        # Auto-advance to next field
        if value and index < 5:
            self.code_entries[index + 1].focus()
        
        # Auto-backspace to previous field
        if not value and event.keysym == 'BackSpace' and index > 0:
            self.code_entries[index - 1].focus()
        
        # Update verify button state
        self._update_verify_button()
    
    def _update_verify_button(self):
        """Update verify button state based on code input."""
        code = self._get_entered_code()
        if len(code) == 6 and code.isdigit():
            self.verify_btn.config(state=tk.NORMAL)
        else:
            self.verify_btn.config(state=tk.DISABLED)
    
    def _get_entered_code(self) -> str:
        """Get the currently entered code."""
        return ''.join([entry.get() for entry in self.code_entries])
    
    def _verify_code(self):
        """Verify the entered code."""
        code = self._get_entered_code()
        
        if len(code) != 6 or not code.isdigit():
            self._show_error("Please enter a valid 6-digit code.")
            return
        
        self.attempts += 1
        
        # Call the verification function
        try:
            result = self.on_resend(code)  # This should be the verification function
            if result.get('valid', False):
                self._show_success("Email verified successfully!")
                self.window.after(1000, self._on_verification_success)
            else:
                error_msg = result.get('error', 'Invalid verification code')
                attempts_remaining = result.get('attempts_remaining', 0)
                
                if attempts_remaining > 0:
                    self._show_error(f"{error_msg}\n{attempts_remaining} attempts remaining.")
                else:
                    self._show_error(f"{error_msg}\nPlease request a new code.")
                    self.resend_btn.config(state=tk.NORMAL)
                    
        except Exception as e:
            logging.error(f"Error verifying code: {e}")
            self._show_error("Verification failed. Please try again.")
    
    def _resend_code(self):
        """Resend verification code."""
        try:
            result = self.on_resend(self.email)  # This should be the resend function
            if result.get('success', False):
                self._show_success("New verification code sent!")
                self._clear_code_input()
                self._start_timer()
                self.resend_btn.config(state=tk.DISABLED)
            else:
                error_msg = result.get('error', 'Failed to resend code')
                self._show_error(f"Failed to resend code: {error_msg}")
                
        except Exception as e:
            logging.error(f"Error resending code: {e}")
            self._show_error("Failed to resend code. Please try again.")
    
    def _start_timer(self):
        """Start the resend timer."""
        self.resend_btn.config(state=tk.DISABLED)
        self._update_timer(60)  # 60 seconds
    
    def _update_timer(self, seconds):
        """Update the timer display."""
        if seconds > 0:
            self.timer_label.config(text=f"Resend available in {seconds} seconds")
            self.window.after(1000, lambda: self._update_timer(seconds - 1))
        else:
            self.timer_label.config(text="")
            self.resend_btn.config(state=tk.NORMAL)
    
    def _clear_code_input(self):
        """Clear the code input fields."""
        for entry in self.code_entries:
            entry.delete(0, tk.END)
        self.code_entries[0].focus()
        self._update_verify_button()
    
    def _show_error(self, message: str):
        """Show error message."""
        self.status_label.config(text=message, foreground="red")
    
    def _show_success(self, message: str):
        """Show success message."""
        self.status_label.config(text=message, foreground="green")
    
    def _on_verification_success(self):
        """Handle successful verification."""
        self.window.destroy()
        self.on_success()
    
    def _go_back(self):
        """Go back to login screen."""
        self.window.destroy()
    
    def show(self):
        """Show the verification window."""
        if self.window:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
    
    def destroy(self):
        """Destroy the verification window."""
        if self.window:
            self.window.destroy()

