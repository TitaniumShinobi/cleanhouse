"""
CleanHouse UI Main Entry Point

This module serves as the main entry point for the CleanHouse UI application.
It orchestrates the UI components and maintains compatibility with brain.py.
"""

import tkinter as tk
import os
import logging
import signal
import sys
from pathlib import Path
from typing import Optional, Dict, Any

from .layout import UILayout
from .events import UIEvents
from .hooks import UIHooks
from .auth import AuthWindow
# Defer SimpleWebViewAuth import to avoid pywebview import crash on macOS
# from .simple_webview_auth import SimpleWebViewAuth
from .user_manager import UserManager
from .widgets.userbox import UserBox
from corefiles import config
from corefiles.passion import ignite_passion

# Set up logging format for human-readable logs
# Handle permission errors gracefully - use console-only if file logging fails
handlers = [logging.StreamHandler()]
try:
    # Try to create logs directory and file handler
    os.makedirs('logs', exist_ok=True)
    file_handler = logging.FileHandler('logs/cleanhouse.log', encoding='utf-8')
    handlers.append(file_handler)
except (PermissionError, OSError):
    # If file logging fails, use console-only logging
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=handlers
)


class CleanHouseUI(tk.Tk):
    """
    Main CleanHouse UI Application

    This class orchestrates all UI components and maintains compatibility
    with the existing brain.py integration.
    """

    def __init__(self, auth_data=None):
        super().__init__()

        # Store authentication data
        self.auth_data = auth_data
        if auth_data:
            logging.info(f"CleanHouseUI initialized with authentication for: {auth_data['user'].get('email', 'unknown')}")
        else:
            logging.info("CleanHouseUI initialized without authentication")

        # Initialize base directory if not set - use actual CleanHouse directory
        if not config.BASE_DIR:
            # Try to find CleanHouse directory
            possible_paths = [
                Path(__file__).parent.parent,  # ui/../ = cleanhouse/
                Path.cwd(),
                Path.home() / "Documents" / "GitHub" / "cleanhouse",
                Path.home() / "Documents" / "GitHub" / "CleanHouse",
            ]
            for path in possible_paths:
                if path.exists() and (path / "docs" / "legal" / "CLEANHOUSE_TERMS_OF_SERVICE.md").exists():
                    config.BASE_DIR = path.resolve()
                    break
            else:
                # Fallback to current directory
                config.BASE_DIR = Path.cwd().resolve()

        # Initialize user manager
        self.user_manager = UserManager(str(config.BASE_DIR))
        self.current_user = None

        # Initialize UI components (will be created after authentication)
        self.layout = None
        self.hooks = None
        self.events = None
        self.user_box = None
        self.auth_window = None

        # Set up signal handling for graceful shutdown
        self._setup_signal_handlers()

        # macOS-specific fixes
        self._setup_macos_fixes()

        # Set up proper cleanup on window close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Show authentication window or proceed if already authenticated
        if self.auth_data:
            # User is already authenticated, proceed directly to main UI
            logging.info("[MAIN] User already authenticated, skipping auth window")
            self._on_auth_success(self.auth_data['user'])
        else:
            # Show authentication window
            self._show_auth()

    def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            """Handle SIGINT (Ctrl+C) and SIGTERM signals in GUI mode."""
            print(f"\n🛑 CleanHouse GUI received signal {signum}, shutting down...")
            logging.info(f"Received signal {signum} in GUI mode")

            # Perform graceful shutdown
            try:
                self._on_closing()
            except Exception as e:
                logging.error(f"Error during signal-based shutdown: {e}")
                # Force quit if graceful shutdown fails
                import os
                os._exit(0)

        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logging.info("Signal handlers set up for graceful shutdown")

    def _setup_macos_fixes(self):
        """Apply basic macOS window setup without aggressive layering."""
        try:
            # Basic window setup without forcing to top
            self.lift()  # Just bring to front once, no forcing

            logging.info("Applied basic macOS window setup")
        except Exception as e:
            logging.warning(f"Could not apply basic macOS setup: {e}")

    def _show_auth(self):
        """Show authentication window."""
        # Hide main window during authentication
        self.withdraw()

        logging.info("[MAIN] Showing WebView authentication")
        logging.info(f"[MAIN] BASE_DIR: {config.BASE_DIR}")

        # Create WebView auth window (lazy import to avoid pywebview crash)
        logging.info("[MAIN] Creating SimpleWebViewAuth instance...")
        try:
            # Import only when needed to avoid pywebview import crash
            from .simple_webview_auth import SimpleWebViewAuth
            self.auth_window = SimpleWebViewAuth(
                self,
                self._on_auth_success,
                self._on_signup_requested,
                str(config.BASE_DIR)
            )
            logging.info("[MAIN] SimpleWebViewAuth instance created")

            # Show WebView login
            logging.info("[MAIN] Calling show_login()...")
            self.auth_window.show_login()
            logging.info("[MAIN] show_login() returned - UI should be loading")
        except (ImportError, RuntimeError, SystemError, OSError, Exception) as e:
            logging.error(f"[MAIN] Failed to create or use WebView auth: {e}")
            # Fallback: proceed without authentication
            logging.warning("[MAIN] Proceeding without authentication - using guest mode")
            if self._on_auth_success:
                self._on_auth_success({"email": "guest@localhost", "name": "Guest User"})

    def _on_signup_requested(self):
        """Handle signup request from login window."""
        logging.info("User requested signup")

        # Close current auth window
        if self.auth_window:
            self.auth_window.cleanup()

        # Show signup using the same SimpleWebViewAuth (lazy import)
        try:
            from .simple_webview_auth import SimpleWebViewAuth
            self.auth_window = SimpleWebViewAuth(
                self,
                self._on_auth_success,
                self._on_signup_requested,
                str(config.BASE_DIR)
            )
        except (ImportError, RuntimeError, SystemError, OSError, Exception) as e:
            logging.error(f"[MAIN] Failed to create WebView auth for signup: {e}")
            return

        # Show WebView signup
        self.auth_window.show_signup()


    def _on_auth_success(self, user_data: Dict[str, Any]):
        """Handle successful authentication."""
        self.current_user = user_data
        logging.info(f"User {user_data['email']} authenticated successfully")

        # Clear the auth window content
        for widget in self.winfo_children():
            widget.destroy()

        # Initialize UI components with user context
        self._initialize_ui_components()

        # Update window properties for main UI
        self.title("CleanHouse")
        self.geometry("900x600")
        self.resizable(True, True)

        # Ensure window is visible
        self.deiconify()
        self.lift()
        self.focus_force()

    def _initialize_ui_components(self):
        """Initialize UI components after authentication."""
        # Initialize UI components
        self.layout = UILayout(self)
        self.hooks = UIHooks(self)
        self.events = UIEvents(self)

        # Set up cross-references to avoid circular dependencies
        self.hooks.events = self.events

        # Set user context in hooks
        self.hooks.current_user = self.current_user
        self.hooks.user_manager = self.user_manager

        # Initialize the UI
        self._initialize_ui()

        # Add user box to the UI
        self._add_user_box()

        # Start periodic updates
        self.periodic_log_update()
        self.periodic_status_update()

    def _add_user_box(self):
        """Add user information box to the UI."""
        if self.current_user and self.layout:
            # Create user box
            self.user_box = UserBox(
                self.layout.root,
                self.current_user,
                self._handle_logout
            )

            # Pack user box at the top
            self.user_box.pack(fill=tk.X, padx=10, pady=5)

    def _handle_logout(self):
        """Handle user logout."""
        # Logout user
        self.user_manager.logout()
        self.current_user = None

        # Clear UI components
        if self.layout:
            # Clear all widgets
            for widget in self.winfo_children():
                widget.destroy()

        # Reset components
        self.layout = None
        self.hooks = None
        self.events = None
        self.user_box = None

        # Clean up WebView auth if it exists
        if hasattr(self, 'auth_window') and self.auth_window:
            self.auth_window.cleanup()
            self.auth_window = None

        # Show auth window again
        self._show_auth()

    def _on_closing(self):
        """Handle application closing with proper cleanup."""
        try:
            logging.info("Application closing - starting cleanup")

            # Clean up WebView auth if it exists
            if hasattr(self, 'auth_window') and self.auth_window:
                try:
                    self.auth_window.cleanup()
                    self.auth_window.force_cleanup()
                except Exception as e:
                    logging.warning(f"Error cleaning up auth window: {e}")
                self.auth_window = None

            # Clean up signup window if it exists
            if hasattr(self, 'signup_window') and self.signup_window:
                try:
                    self.signup_window.cleanup()
                    self.signup_window.force_cleanup()
                except Exception as e:
                    logging.warning(f"Error cleaning up signup window: {e}")
                self.signup_window = None

            # Force cleanup of any remaining WebView processes
            try:
                import subprocess
                import platform

                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["pkill", "-f", "webview"], check=False)
                elif platform.system() == "Windows":
                    subprocess.run(["taskkill", "/f", "/im", "webview.exe"], check=False)
                else:  # Linux
                    subprocess.run(["pkill", "-f", "webview"], check=False)

                logging.info("Force cleaned up WebView processes")
            except Exception as e:
                logging.warning(f"Error force cleaning WebView: {e}")

            # Destroy the main window
            self.destroy()

            # Force quit if needed
            import sys
            sys.exit(0)

        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
            # Force quit even if cleanup fails
            import sys
            sys.exit(0)

    def _initialize_ui(self):
        """Initialize the main UI (called after authentication)."""
        if not self.layout:
            return

        # Set up window properties
        self.title("CleanHouse")
        self.geometry("900x600")
        self.minsize(800, 500)
        self.configure(bg="#f4f6fa")

        # Add window close handler
        self.protocol("WM_DELETE_WINDOW", self.events.on_closing)

        # Create UI layout
        self.layout.create_menu()
        self.layout.create_tabs()

        # Initialize status
        self.hooks.update_status("Protected", "#4caf50")

        # Start directory statistics update
        self.hooks.update_directory_stats()

    def periodic_log_update(self):
        """Periodically update the log display."""
        if hasattr(self.layout, 'update_log_display'):
            self.layout.update_log_display()
        self.after(1000, self.periodic_log_update)

    def periodic_status_update(self):
        """Periodically update the status display."""
        self.after(2000, self.periodic_status_update)

    def ignite_passion(self, target_dir=None, threshold=3, dry_run=True):
        """
        Main entry point for CleanHouse functionality.
        Maintains compatibility with brain.py integration.
        """
        return self.hooks.ignite_passion(target_dir, threshold, dry_run)


if __name__ == "__main__":
    app = CleanHouseUI()
    app.mainloop()
