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
from datetime import datetime, timezone
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
        self.latest_delivery_result = None
        self._delivery_result_lock = threading.Lock()
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
            payload = self.notification_queue.get()
            title = "unknown"
            level = "error"
            try:
                if isinstance(payload, dict):
                    title = payload.get("title", "unknown")
                    message = payload.get("message", "")
                    level = payload.get("level", "error")
                    metadata = payload.get("metadata")
                    click_url = payload.get("click_url")
                    preferred_backend = payload.get("preferred_backend")
                    fanout_all_backends = bool(payload.get("fanout_all_backends", False))
                    enqueued_at = float(payload.get("enqueued_at", 0) or 0)
                    max_queue_age_seconds_raw = payload.get("max_queue_age_seconds")
                    try:
                        max_queue_age_seconds = float(max_queue_age_seconds_raw)
                    except (TypeError, ValueError):
                        max_queue_age_seconds = float(os.getenv("CLEANHOUSE_NATIVE_LIVE_MAX_AGE_SECONDS", "3") or 3)
                    if enqueued_at > 0 and max_queue_age_seconds > 0 and (time.time() - enqueued_at) > max_queue_age_seconds:
                        self._record_delivery_result(self._delivery_result(
                            "skipped",
                            "notification_queue",
                            title=title,
                            level=level,
                            metadata=metadata,
                            click_url=click_url,
                            reason="queued_notification_stale",
                        ))
                        continue
                elif len(payload) == 3:
                    title, message, level = payload
                    metadata = None
                    click_url = None
                    preferred_backend = None
                    fanout_all_backends = False
                else:
                    title, message, level, metadata, click_url = payload
                    preferred_backend = None
                    fanout_all_backends = False
                result = self._show_notification(
                    title,
                    message,
                    level,
                    metadata=metadata,
                    click_url=click_url,
                    preferred_backend=preferred_backend,
                    fanout_all_backends=fanout_all_backends,
                )
                self._record_delivery_result(result)
            except Exception as e:
                logging.error(f"Error in notification worker: {e}")
                self._record_delivery_result(self._delivery_result(
                    "failed",
                    "notification_worker",
                    title=title,
                    level=level,
                    reason="worker_exception",
                    error=e,
                ))
            finally:
                self.notification_queue.task_done()

    def _show_notification(
        self,
        title,
        message,
        level="info",
        metadata=None,
        click_url=None,
        preferred_backend=None,
        fanout_all_backends=False,
    ):
        """Show a desktop notification."""
        if platform.system() == "Darwin":
            result = self._show_macos_notification(
                title,
                message,
                level=level,
                metadata=metadata,
                click_url=click_url,
                preferred_backend=preferred_backend,
                fanout_all_backends=fanout_all_backends,
            )
            if result.get("status") == "delivered":
                return result
            print(f"Notification: {title} - {message} ({level})")
            result = dict(result)
            result["stdout_fallback"] = True
            return result

        if not WINDOWS_AVAILABLE:
            print(f"Notification: {title} - {message} ({level})")
            return self._delivery_result(
                "failed",
                "stdout_fallback",
                title=title,
                level=level,
                metadata=metadata,
                click_url=click_url,
                reason="native_notifications_unavailable",
            )

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
            return self._delivery_result(
                "delivered",
                "windows_shell_notify_icon",
                title=title,
                level=level,
                metadata=metadata,
                click_url=click_url,
            )

        except Exception as e:
            logging.error(f"Failed to show notification: {e}")
            return self._delivery_result(
                "failed",
                "windows_shell_notify_icon",
                title=title,
                level=level,
                metadata=metadata,
                click_url=click_url,
                reason="windows_delivery_exception",
                error=e,
            )

    def _show_macos_notification(
        self,
        title,
        message,
        level="info",
        metadata=None,
        click_url=None,
        preferred_backend=None,
        fanout_all_backends=False,
    ):
        attempts = []
        backend_order = ["terminal-notifier", "osascript"]
        preferred_backend = str(preferred_backend or "").strip()
        if preferred_backend in backend_order:
            backend_order = [preferred_backend] + [item for item in backend_order if item != preferred_backend]
        delivered_backends = []
        for backend in backend_order:
            if backend == "terminal-notifier":
                terminal_notifier = shutil.which("terminal-notifier")
                if not terminal_notifier:
                    attempts.append({
                        "backend": "terminal-notifier",
                        "status": "unavailable",
                        "reason": "terminal_notifier_not_found",
                    })
                    continue
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
                        attempts.append({"backend": "terminal-notifier", "status": "delivered"})
                        delivered_backends.append("terminal-notifier")
                        if not fanout_all_backends:
                            return self._delivery_result(
                                "delivered",
                                "terminal-notifier",
                                title=title,
                                level=level,
                                metadata=metadata,
                                click_url=click_url,
                                attempts=attempts,
                            )
                        continue
                    attempts.append({
                        "backend": "terminal-notifier",
                        "status": "failed",
                        "returncode": completed.returncode,
                    })
                except Exception as e:
                    logging.error(f"Failed to show terminal-notifier notification: {e}")
                    attempts.append({
                        "backend": "terminal-notifier",
                        "status": "failed",
                        "error_type": e.__class__.__name__,
                        "reason": str(e)[:160],
                    })
            elif backend == "osascript":
                osascript = shutil.which("osascript")
                if not osascript:
                    attempts.append({
                        "backend": "osascript",
                        "status": "unavailable",
                        "reason": "osascript_not_found",
                    })
                    continue
                script = (
                    "display notification "
                    + _applescript_string(str(message))
                    + " with title "
                    + _applescript_string(str(title))
                )
                try:
                    completed = subprocess.run([osascript, "-e", script], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if completed.returncode == 0:
                        attempts.append({"backend": "osascript", "status": "delivered"})
                        delivered_backends.append("osascript")
                        if not fanout_all_backends:
                            return self._delivery_result(
                                "delivered",
                                "osascript",
                                title=title,
                                level=level,
                                metadata=metadata,
                                click_url=click_url,
                                attempts=attempts,
                            )
                        continue
                    attempts.append({
                        "backend": "osascript",
                        "status": "failed",
                        "returncode": completed.returncode,
                    })
                except Exception as e:
                    logging.error(f"Failed to show AppleScript notification: {e}")
                    attempts.append({
                        "backend": "osascript",
                        "status": "failed",
                        "error_type": e.__class__.__name__,
                        "reason": str(e)[:160],
                    })
        if delivered_backends:
            return self._delivery_result(
                "delivered",
                delivered_backends[0],
                title=title,
                level=level,
                metadata=metadata,
                click_url=click_url,
                attempts=attempts,
            )
        return self._delivery_result(
            "failed",
            "macos_native_notification",
            title=title,
            level=level,
            metadata=metadata,
            click_url=click_url,
            reason="native_notifier_unavailable_or_failed",
            attempts=attempts,
        )

    def send_notification(
        self,
        title,
        message,
        level="info",
        metadata=None,
        click_url=None,
        wait_for_delivery=False,
        preferred_backend=None,
        fanout_all_backends=False,
    ):
        """Queue or synchronously deliver a notification, returning bounded delivery evidence."""
        if wait_for_delivery:
            result = self._show_notification(
                title,
                message,
                level,
                metadata=metadata,
                click_url=click_url,
                preferred_backend=preferred_backend,
                fanout_all_backends=fanout_all_backends,
            )
            self._record_delivery_result(result)
            return result
        result = self._delivery_result(
            "queued",
            "notification_queue",
            title=title,
            level=level,
            metadata=metadata,
            click_url=click_url,
        )
        self._record_delivery_result(result)
        self.notification_queue.put({
            "title": title,
            "message": message,
            "level": level,
            "metadata": metadata,
            "click_url": click_url,
            "preferred_backend": preferred_backend,
            "fanout_all_backends": bool(fanout_all_backends),
            "enqueued_at": time.time(),
            "max_queue_age_seconds": float(os.getenv("CLEANHOUSE_NATIVE_LIVE_MAX_AGE_SECONDS", "3") or 3),
        })
        return result

    def get_latest_delivery_result(self):
        with self._delivery_result_lock:
            return dict(self.latest_delivery_result or {})

    def _record_delivery_result(self, result):
        if not isinstance(result, dict):
            result = self._delivery_result(
                "unknown",
                "notification_manager",
                title="unknown",
                level="info",
                reason="non_dict_delivery_result",
            )
        with self._delivery_result_lock:
            self.latest_delivery_result = dict(result)

    def _delivery_result(
        self,
        status,
        backend,
        *,
        title,
        level,
        metadata=None,
        click_url=None,
        reason=None,
        error=None,
        attempts=None,
    ):
        metadata = metadata if isinstance(metadata, dict) else {}
        result = {
            "status": str(status),
            "backend": str(backend),
            "level": str(level),
            "title": str(title)[:120],
            "notification_id": str(metadata.get("notification_id", "")),
            "notification_type": str(metadata.get("notification_type", "")),
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        if click_url:
            result["click_url"] = str(click_url)[:500]
        if reason:
            result["reason"] = str(reason)[:200]
        if error is not None:
            result["error_type"] = error.__class__.__name__
            result["error_detail"] = str(error)[:300] or error.__class__.__name__
        if attempts:
            result["attempts"] = attempts[-3:]
        return result

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
