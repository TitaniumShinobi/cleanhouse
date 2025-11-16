# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - error_handler.py
#  Error handling and logging management
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

import time
from datetime import datetime
import logging
import queue

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

# Initialize the error handler
error_handler = PersistentErrorHandler() 