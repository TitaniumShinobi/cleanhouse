# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - auth.py
#  User authentication UI
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from pathlib import Path
from typing import Callable, Optional

from .email_service import EmailVerificationService
from .email_verification import EmailVerificationWindow
from .email_config import EmailConfigWindow
from .password_manager_integration import PasswordManagerIntegration

# Import our account system (local database only)
from models import User, UserService, DatabaseManager
from access_control.access_control import access_control

class AuthWindow:
    """
    Authentication window for user login and signup.
    """
    
    def __init__(self, parent, on_success: Callable, base_dir: str = None):
        self.parent = parent
        self.on_success = on_success
        self.email_service = EmailVerificationService()
        self.password_manager = PasswordManagerIntegration()
        self.window = None
        self.is_signup = False
        self.pending_email = None
        self.pending_password = None
        self.pending_role = None
        
        # Initialize local database (CleanHouse's own user registry)
        self.db_manager = DatabaseManager()
        self.user_service = UserService(db_manager=self.db_manager)
        
        # Create the authentication window
        self._create_window()
    
    def _create_window(self):
        """Create the authentication window."""
        # Use the parent window directly instead of Toplevel
        self.window = self.parent
        
        # Clear any existing content
        for widget in self.window.winfo_children():
            widget.destroy()
        
        # Create main frame
        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="CleanHouse", 
            font=("Arial", 24, "bold")
        )
        title_label.pack(pady=(0, 10))
        
        subtitle_label = ttk.Label(
            main_frame, 
            text="Security & File Management", 
            font=("Arial", 12)
        )
        subtitle_label.pack(pady=(0, 30))
        
        # Create form frame
        self.form_frame = ttk.Frame(main_frame)
        self.form_frame.pack(fill=tk.BOTH, expand=True)
        
        # Show login form initially
        self._show_login_form()
    
    def _show_login_form(self):
        """Show the login form."""
        self.is_signup = False
        
        # Clear form frame
        for widget in self.form_frame.winfo_children():
            widget.destroy()
        
        # Login form
        login_label = ttk.Label(
            self.form_frame, 
            text="Sign In", 
            font=("Arial", 16, "bold")
        )
        login_label.pack(pady=(0, 20))
        
        # Email field
        email_frame = ttk.Frame(self.form_frame)
        email_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(email_frame, text="Email:").pack(anchor=tk.W)
        self.email_var = tk.StringVar()
        self.email_entry = ttk.Entry(
            email_frame, 
            textvariable=self.email_var,
            font=("Arial", 11),
            width=30
        )
        self.email_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Password field
        password_frame = ttk.Frame(self.form_frame)
        password_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(password_frame, text="Password:").pack(anchor=tk.W)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            password_frame, 
            textvariable=self.password_var,
            show="*",
            font=("Arial", 11),
            width=30
        )
        self.password_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Configure for password managers
        self._configure_password_manager_fields()
        
        # Remember me checkbox
        self.remember_var = tk.BooleanVar()
        remember_check = ttk.Checkbutton(
            self.form_frame,
            text="Remember me",
            variable=self.remember_var
        )
        remember_check.pack(pady=(0, 20))
        
        # Buttons frame
        buttons_frame = ttk.Frame(self.form_frame)
        buttons_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Login button
        login_btn = ttk.Button(
            buttons_frame,
            text="Sign In",
            command=self._handle_login,
            style="Accent.TButton"
        )
        login_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Sign up button
        signup_btn = ttk.Button(
            buttons_frame,
            text="Sign Up",
            command=self._show_signup_form
        )
        signup_btn.pack(side=tk.LEFT)
        
        # Bind Enter key to login
        self.window.bind('<Return>', lambda e: self._handle_login())
        
        # Focus on email field
        self.email_entry.focus()
    
    def _show_signup_form(self):
        """Show the signup form."""
        self.is_signup = True
        
        # Clear form frame
        for widget in self.form_frame.winfo_children():
            widget.destroy()
        
        # Signup form
        signup_label = ttk.Label(
            self.form_frame, 
            text="Create Account", 
            font=("Arial", 16, "bold")
        )
        signup_label.pack(pady=(0, 20))
        
        # Email field
        email_frame = ttk.Frame(self.form_frame)
        email_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(email_frame, text="Email:").pack(anchor=tk.W)
        self.email_var = tk.StringVar()
        self.email_entry = ttk.Entry(
            email_frame, 
            textvariable=self.email_var,
            font=("Arial", 11),
            width=30
        )
        self.email_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Password field
        password_frame = ttk.Frame(self.form_frame)
        password_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(password_frame, text="Password:").pack(anchor=tk.W)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            password_frame, 
            textvariable=self.password_var,
            show="*",
            font=("Arial", 11),
            width=30
        )
        self.password_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Confirm password field
        confirm_frame = ttk.Frame(self.form_frame)
        confirm_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(confirm_frame, text="Confirm Password:").pack(anchor=tk.W)
        self.confirm_var = tk.StringVar()
        self.confirm_entry = ttk.Entry(
            confirm_frame, 
            textvariable=self.confirm_var,
            show="*",
            font=("Arial", 11),
            width=30
        )
        self.confirm_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Role selection
        role_frame = ttk.Frame(self.form_frame)
        role_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(role_frame, text="Account Type:").pack(anchor=tk.W)
        self.role_var = tk.StringVar(value="user")
        role_combo = ttk.Combobox(
            role_frame,
            textvariable=self.role_var,
            values=["user", "dev"],
            state="readonly",
            width=27
        )
        role_combo.pack(fill=tk.X, pady=(5, 0))
        
        # Buttons frame
        buttons_frame = ttk.Frame(self.form_frame)
        buttons_frame.pack(fill=tk.X, pady=(0, 20))
        
        # Create account button
        create_btn = ttk.Button(
            buttons_frame,
            text="Create Account",
            command=self._handle_signup,
            style="Accent.TButton"
        )
        create_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Email configuration button
        email_config_btn = ttk.Button(
            buttons_frame,
            text="⚙️ Email Config",
            command=self._show_email_config
        )
        email_config_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Back to login button
        back_btn = ttk.Button(
            buttons_frame,
            text="Back to Sign In",
            command=self._show_login_form
        )
        back_btn.pack(side=tk.LEFT)
        
        # Bind Enter key to signup
        self.window.bind('<Return>', lambda e: self._handle_signup())
        
        # Configure for password managers
        self._configure_password_manager_fields()
        
        # Focus on email field
        self.email_entry.focus()
    
    def _handle_login(self):
        """Handle login attempt."""
        email = self.email_var.get().strip()
        password = self.password_var.get()
        
        if not email or not password:
            messagebox.showerror("Error", "Please enter both email and password.")
            return
        
        # Authenticate user via local database
        try:
            user = self.user_service.authenticate_user(email, password)
            
            if user:
                logging.info(f"User {email} logged in successfully")
                # Convert User object to dict format expected by on_success
                user_data = {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": "user",  # Default role, can be extended later
                    "created_at": user.created_at.isoformat() if user.created_at else None
                }
                self.window.destroy()
                self.on_success(user_data)
            else:
                messagebox.showerror("Error", "Invalid email or password.")
                self.password_var.set("")
                self.password_entry.focus()
        except Exception as e:
            logging.error(f"Authentication error: {e}")
            messagebox.showerror("Error", "An error occurred during authentication.")
            self.password_var.set("")
            self.password_entry.focus()
    
    def _handle_signup(self):
        """Handle signup attempt."""
        email = self.email_var.get().strip()
        password = self.password_var.get()
        confirm_password = self.confirm_var.get()
        role = self.role_var.get()
        
        # Validation
        if not email or not password or not confirm_password:
            messagebox.showerror("Error", "Please fill in all fields.")
            return
        
        if "@" not in email or "." not in email:
            messagebox.showerror("Error", "Please enter a valid email address.")
            return
        
        if len(password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters long.")
            return
        
        if password != confirm_password:
            messagebox.showerror("Error", "Passwords do not match.")
            return
        
        # Check if email verification is configured
        if not self.email_service.get_config_status()['configured']:
            # Create user in local database
            try:
                # Use email prefix as name if full name not provided
                full_name = email.split('@')[0] if not hasattr(self, 'full_name_var') else self.full_name_var.get().strip()
                if not full_name:
                    full_name = email.split('@')[0]
                
                user = self.user_service.create_user(full_name, email, password)
                
                if user:
                    messagebox.showinfo("Success", "Account created successfully! Please sign in.")
                    self._show_login_form()
                    self.email_var.set(email)
                    self.password_entry.focus()
                else:
                    messagebox.showerror("Error", "Failed to create account.")
            except ValueError as e:
                # Email already exists or validation failed
                messagebox.showerror("Error", str(e))
            except PermissionError as e:
                # Access control denied
                messagebox.showerror("Error", str(e))
            except Exception as e:
                logging.error(f"Unexpected error creating user: {e}")
                messagebox.showerror("Error", f"Failed to create account: {str(e)}")
            return
        
        # Store pending signup data
        self.pending_email = email
        self.pending_password = password
        self.pending_role = role
        
        # Send verification email
        self._send_verification_email()
    
    def _send_verification_email(self):
        """Send verification email."""
        try:
            result = self.email_service.send_verification_code(self.pending_email)
            
            if result['success']:
                # Show verification window
                self._show_verification_window()
            else:
                messagebox.showerror("Error", f"Failed to send verification email: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            logging.error(f"Error sending verification email: {e}")
            messagebox.showerror("Error", "Failed to send verification email. Please try again.")
    
    def _show_verification_window(self):
        """Show email verification window."""
        try:
            # Clear current form
            for widget in self.form_frame.winfo_children():
                widget.destroy()
            
            # Show verification window
            self.verification_window = EmailVerificationWindow(
                self.window,
                self.pending_email,
                self._on_verification_success,
                self._handle_verification
            )
            
        except Exception as e:
            logging.error(f"Error showing verification window: {e}")
            messagebox.showerror("Error", "Failed to show verification window.")
    
    def _handle_verification(self, code_or_email):
        """Handle verification code or resend request."""
        if isinstance(code_or_email, str) and len(code_or_email) == 6:
            # Verify code
            return self.email_service.verify_code(self.pending_email, code_or_email)
        else:
            # Resend code
            return self.email_service.send_verification_code(self.pending_email)
    
    def _on_verification_success(self):
        """Handle successful email verification."""
        try:
            # Create user account in local database
            name = self.pending_email.split('@')[0]  # Use email prefix as name
            user = self.user_service.create_user(
                name,
                self.pending_email,
                self.pending_password
            )
            
            if user:
                messagebox.showinfo("Success", "Account created and verified successfully! Please sign in.")
                self._show_login_form()
                self.email_var.set(self.pending_email)
                self.password_entry.focus()
            else:
                messagebox.showerror("Error", "Failed to create account after verification.")
                
        except ValueError as e:
            messagebox.showerror("Error", str(e))
        except PermissionError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logging.error(f"Error creating account after verification: {e}")
            messagebox.showerror("Error", "Failed to create account after verification.")
        finally:
            # Clear pending data
            self.pending_email = None
            self.pending_password = None
            self.pending_role = None
    
    def _show_email_config(self):
        """Show email configuration window."""
        try:
            EmailConfigWindow(self.window, self.email_service)
        except Exception as e:
            logging.error(f"Error showing email config: {e}")
            messagebox.showerror("Error", "Failed to show email configuration.")
    
    def _configure_password_manager_fields(self):
        """Configure form fields for password manager compatibility."""
        try:
            # Use the advanced password manager integration
            form_type = "signup" if self.is_signup else "login"
            
            # Set up the form for password managers
            self.password_manager.setup_form_for_password_managers(self.window, form_type)
            
            # Configure email field
            self.password_manager.configure_entry_for_password_manager(
                self.email_entry, 
                "email", 
                form_type
            )
            
            # Configure password field
            self.password_manager.configure_entry_for_password_manager(
                self.password_entry, 
                "password", 
                form_type
            )
            
            # Set up keyboard navigation
            self.email_entry.bind('<Return>', lambda e: self.password_entry.focus())
            if self.is_signup:
                self.password_entry.bind('<Return>', lambda e: self._handle_signup())
            else:
                self.password_entry.bind('<Return>', lambda e: self._handle_login())
            
            # Add password manager hint if on macOS
            if self.password_manager.is_macos:
                hint_label = self.password_manager.create_password_manager_hint(self.form_frame)
                if hint_label:
                    hint_label.pack(pady=(10, 0))
            
            logging.info("Password manager fields configured successfully")
            
        except Exception as e:
            logging.warning(f"Could not configure password manager fields: {e}")
    
    
    def show(self):
        """Show the authentication window."""
        if self.window:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
    
    def create_account(self, full_name: str, email: str, password: str, role: str = "user", invite_token: str = None) -> bool:
        """
        Create a new user account with the new account system.
        
        Args:
            full_name: User's full name
            email: User's email address
            password: Plain text password
            role: User role (user or dev)
            invite_token: Optional invite token for developer mode
            
        Returns:
            bool: True if account created successfully, False otherwise
        """
        try:
            # Validate role
            if role not in ["user", "dev"]:
                role = "user"  # Default to user if invalid role
            
            # Create user account
            user = self.user_service.create_user(
                full_name=full_name,
                email=email,
                password=password,
                invite_token=invite_token
            )
            
            logging.info(f"Account created successfully: {user.email} with role: {role}")
            
            # Call success callback with user data
            user_data = {
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email,
                'role': role,
                'created_at': user.created_at.isoformat() if user.created_at else None
            }
            
            self.on_success(user_data)
            return True
            
        except PermissionError as e:
            logging.warning(f"Access denied for account creation: {e}")
            messagebox.showerror("Access Denied", str(e))
            return False
            
        except ValueError as e:
            logging.warning(f"Validation error during account creation: {e}")
            messagebox.showerror("Validation Error", str(e))
            return False
            
        except Exception as e:
            logging.error(f"Account creation failed: {e}")
            messagebox.showerror("Error", f"Failed to create account: {e}")
            return False
    
    def destroy(self):
        """Destroy the authentication window."""
        # Clear the window content
        if self.window:
            for widget in self.window.winfo_children():
                widget.destroy()
