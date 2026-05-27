# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - notifications.py
#  Desktop notification system
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import logging
import platform
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
# Windows-specific imports (optional)
try:
    import win32api
    import win32con
    import win32gui
    import win32gui_struct
    import win32timezone
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False
    win32api = None
    win32con = None
    win32gui = None
    win32gui_struct = None
    win32timezone = None
import threading
import queue
import time

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config

class NotificationManager:
    def __init__(self):
        self.notification_queue = queue.Queue()
        self.notification_thread = threading.Thread(target=self._notification_worker, daemon=True)
        self.notification_thread.start()
        if WINDOWS_AVAILABLE:
            self._create_window()
        else:
            self.hwnd = None

    def _create_window(self):
        """Create a hidden window for notifications."""
        if not WINDOWS_AVAILABLE:
            return

        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "CleanHouseNotification"
        wc.style = 0
        wc.hbrBackground = win32gui.GetStockObject(win32con.WHITE_BRUSH)
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = win32gui.GetModuleHandle(None)
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hIcon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        try:
            win32gui.RegisterClass(wc)
        except Exception as e:
            logging.error(f"Failed to register window class: {e}")
            return

        self.hwnd = win32gui.CreateWindow(
            wc.lpszClassName,
            "CleanHouse Notifications",
            win32con.WS_OVERLAPPED,
            0, 0, 0, 0,
            0, 0, wc.hInstance, None
        )

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure for handling notifications."""
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _notification_worker(self):
        """Background worker for processing notifications."""
        while True:
            try:
                payload = self.notification_queue.get()
                if len(payload) == 3:
                    title, message, level = payload
                    metadata = None
                    click_url = None
                else:
                    title, message, level, metadata, click_url = payload
                self._show_notification(title, message, level, metadata=metadata, click_url=click_url)
                self.notification_queue.task_done()
            except Exception as e:
                logging.error(f"Error in notification worker: {e}")

    def _show_notification(self, title, message, level="info", metadata=None, click_url=None):
        """Show a desktop notification."""
        if platform.system() == "Darwin":
            if self._show_macos_notification(title, message, level=level, metadata=metadata, click_url=click_url):
                return
            print(f"Notification: {title} - {message} ({level})")
            return

        if not WINDOWS_AVAILABLE:
            print(f"Notification: {title} - {message} ({level})")
            return

        try:
            # Set icon based on level
            icon = {
                "info": win32con.IDI_INFORMATION,
                "warning": win32con.IDI_WARNING,
                "critical": win32con.IDI_ERROR,
                "error": win32con.IDI_ERROR
            }.get(level, win32con.IDI_INFORMATION)

            # Create notification
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            nid = (self.hwnd, 0, flags, win32con.WM_USER+20, icon, "CleanHouse")
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

            # Show notification
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_MODIFY,
                (self.hwnd, 0, win32gui.NIF_INFO, win32con.WM_USER+20,
                 icon, "CleanHouse", message, 0, title)
            )

            # Remove notification after 5 seconds
            threading.Timer(5.0, lambda: win32gui.Shell_NotifyIcon(
                win32gui.NIM_DELETE, (self.hwnd, 0)
            )).start()

        except Exception as e:
            logging.error(f"Failed to show notification: {e}")

    def _show_macos_notification(self, title, message, level="info", metadata=None, click_url=None):
        terminal_notifier = shutil.which("terminal-notifier")
        if terminal_notifier:
            cmd = [
                terminal_notifier,
                "-title",
                str(title),
                "-message",
                str(message),
                "-group",
                str((metadata or {}).get("notification_id") or "cleanhouse-operator"),
            ]
            if click_url:
                cmd.extend(["-open", str(click_url)])
            try:
                completed = subprocess.run(cmd, check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if completed.returncode == 0:
                    return True
            except Exception as e:
                logging.error(f"Failed to show terminal-notifier notification: {e}")

        osascript = shutil.which("osascript")
        if not osascript:
            return False
        script = (
            "display notification "
            + _applescript_string(str(message))
            + " with title "
            + _applescript_string(str(title))
        )
        try:
            subprocess.run([osascript, "-e", script], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logging.error(f"Failed to show AppleScript notification: {e}")
            return False

    def send_notification(self, title, message, level="info", metadata=None, click_url=None):
        """Queue a notification to be shown."""
        self.notification_queue.put((title, message, level, metadata, click_url))

    def cleanup(self):
        """Clean up notification resources."""
        if not WINDOWS_AVAILABLE or self.hwnd is None:
            return
        try:
            win32gui.DestroyWindow(self.hwnd)
        except Exception as e:
            logging.error(f"Error cleaning up notifications: {e}")


def _applescript_string(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

class PersistentErrorHandler:
    def __init__(self):
        self.error_history = {}
        self.error_messages = {
            'cloud_init': {
                'gdrive': "Google Drive integration is not configured. Please set up credentials in the Cloud tab.",
                'dropbox': "Dropbox integration is not configured. Please set up credentials in the Cloud tab.",
                'onedrive': "OneDrive integration is not configured. Please set up credentials in the Cloud tab.",
                'github': "GitHub integration is not configured. Please set up credentials in the Cloud tab."
            },
            'service_init': "Service initialization failed. Please check system permissions.",
            'baseline': "Baseline generation failed. Please ensure you have write permissions.",
            'monitoring': "Monitoring service failed to start. Please check system resources."
        }
        self.error_threshold = 3  # Number of times to show the same error before summarizing
        self.error_cooldown = 3600  # Seconds to wait before showing the same error again

    def should_log_error(self, error_type: str, error_key: str) -> bool:
        """Determine if an error should be logged based on its history."""
        current_time = time.time()
        key = f"{error_type}:{error_key}"

        if key not in self.error_history:
            self.error_history[key] = {
                'count': 1,
                'first_seen': current_time,
                'last_seen': current_time
            }
            return True

        history = self.error_history[key]
        history['count'] += 1
        history['last_seen'] = current_time

        # Always log first occurrence
        if history['count'] == 1:
            return True

        # If we've seen this error too many times, only log if cooldown has passed
        if history['count'] > self.error_threshold:
            if current_time - history['last_seen'] > self.error_cooldown:
                return True
            return False

        return True

    def get_error_message(self, error_type: str, error_key: str) -> str:
        """Get a user-friendly error message."""
        if error_type in self.error_messages:
            if isinstance(self.error_messages[error_type], dict):
                return self.error_messages[error_type].get(error_key, "An unknown error occurred.")
            return self.error_messages[error_type]
        return "An unknown error occurred."

    def get_error_summary(self, error_type: str, error_key: str) -> str:
        """Get a summary of repeated errors."""
        key = f"{error_type}:{error_key}"
        if key in self.error_history:
            history = self.error_history[key]
            if history['count'] > self.error_threshold:
                return f"This error has occurred {history['count']} times since {datetime.fromtimestamp(history['first_seen']).strftime('%Y-%m-%d %H:%M:%S')}"
        return None

    def reset_error(self, error_type: str, error_key: str):
        """Reset the error history for a specific error."""
        key = f"{error_type}:{error_key}"
        if key in self.error_history:
            del self.error_history[key]

# Initialize the error handler
error_handler = PersistentErrorHandler()

class CustomLogHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)

            # Check if this is an error that should be handled by PersistentErrorHandler
            if record.levelno >= logging.ERROR:
                error_type = getattr(record, 'error_type', 'unknown')
                error_key = getattr(record, 'error_key', 'unknown')

                if not error_handler.should_log_error(error_type, error_key):
                    return

                # Get user-friendly message and summary
                user_msg = error_handler.get_error_message(error_type, error_key)
                summary = error_handler.get_error_summary(error_type, error_key)

                if summary:
                    msg = f"{user_msg}\n{summary}"
                else:
                    msg = user_msg

            # Add to queue with metadata for UI display
            self.log_queue.put({
                'timestamp': record.created,
                'level': record.levelname,
                'message': msg,
                'raw_message': record.getMessage(),
                'error_type': getattr(record, 'error_type', None),
                'error_key': getattr(record, 'error_key', None)
            })

        except Exception as e:
            self.handleError(record)
