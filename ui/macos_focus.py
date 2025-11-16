# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - macos_focus.py
#  macOS-specific focus management for OAuth popups
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import platform
import subprocess
import threading
import time
import logging
from typing import Optional, List

class MacOSFocusManager:
    """
    Enhanced macOS focus management for OAuth popups and WebView windows.
    """
    
    def __init__(self):
        self.is_macos = platform.system() == 'Darwin'
        self.focus_attempts = 0
        self.max_attempts = 3
        
    def bring_window_to_front(self, process_name: str = "Python", delay: float = 0.5) -> bool:
        """
        Bring the specified process window to the front using AppleScript.
        
        Args:
            process_name: Name of the process to bring to front
            delay: Delay before attempting focus (seconds)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_macos:
            return False
            
        try:
            # Wait for the delay
            if delay > 0:
                time.sleep(delay)
            
            # Enhanced AppleScript with multiple strategies
            scripts = [
                # Strategy 1: Basic process focus
                f'''
                tell application "System Events"
                    set frontmost of process "{process_name}" to true
                end tell
                ''',
                
                # Strategy 2: Focus with activation
                f'''
                tell application "System Events"
                    activate process "{process_name}"
                    set frontmost of process "{process_name}" to true
                end tell
                ''',
                
                # Strategy 3: Focus with window management
                f'''
                tell application "System Events"
                    set frontmost of process "{process_name}" to true
                    delay 0.1
                    set frontmost of process "{process_name}" to true
                end tell
                '''
            ]
            
            for i, script in enumerate(scripts):
                try:
                    result = subprocess.run(
                        ['osascript', '-e', script],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        logging.info(f"macOS focus strategy {i+1} successful")
                        return True
                    else:
                        logging.warning(f"macOS focus strategy {i+1} failed: {result.stderr}")
                        
                except subprocess.TimeoutExpired:
                    logging.warning(f"macOS focus strategy {i+1} timed out")
                except Exception as e:
                    logging.warning(f"macOS focus strategy {i+1} error: {e}")
            
            return False
            
        except Exception as e:
            logging.error(f"macOS focus management error: {e}")
            return False
    
    def bring_webview_to_front(self, window_title: str = "CleanHouse", delay: float = 1.0) -> bool:
        """
        Specifically target WebView windows for focus management.
        
        Args:
            window_title: Title of the WebView window
            delay: Delay before attempting focus
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_macos:
            return False
            
        try:
            if delay > 0:
                time.sleep(delay)
            
            # Enhanced WebView focus script
            webview_script = f'''
            tell application "System Events"
                try
                    set frontmost of process "Python" to true
                    delay 0.2
                    set frontmost of process "Python" to true
                    
                    -- Try to focus on window with specific title
                    tell process "Python"
                        set frontmost to true
                        try
                            set frontmost of window 1 to true
                        end try
                    end tell
                end try
            end tell
            '''
            
            result = subprocess.run(
                ['osascript', '-e', webview_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logging.info("WebView focus successful")
                return True
            else:
                logging.warning(f"WebView focus failed: {result.stderr}")
                return False
                
        except Exception as e:
            logging.error(f"WebView focus error: {e}")
            return False
    
    def schedule_focus_attempts(self, process_name: str = "Python", 
                               initial_delay: float = 0.5, 
                               max_attempts: int = 3,
                               interval: float = 1.0) -> List[threading.Timer]:
        """
        Schedule multiple focus attempts with delays.
        
        Args:
            process_name: Name of the process to focus
            initial_delay: Initial delay before first attempt
            max_attempts: Maximum number of focus attempts
            interval: Interval between attempts
            
        Returns:
            List of Timer objects for the scheduled attempts
        """
        timers = []
        
        if not self.is_macos:
            return timers
            
        for i in range(max_attempts):
            delay = initial_delay + (i * interval)
            timer = threading.Timer(
                delay,
                self._scheduled_focus_attempt,
                args=[process_name, i+1]
            )
            timer.start()
            timers.append(timer)
            
        return timers
    
    def _scheduled_focus_attempt(self, process_name: str, attempt: int):
        """Internal method for scheduled focus attempts."""
        try:
            success = self.bring_window_to_front(process_name, delay=0)
            if success:
                logging.info(f"Scheduled focus attempt {attempt} successful")
            else:
                logging.warning(f"Scheduled focus attempt {attempt} failed")
        except Exception as e:
            logging.error(f"Scheduled focus attempt {attempt} error: {e}")
    
    def force_focus_with_retry(self, process_name: str = "Python", 
                             max_retries: int = 5, 
                             base_delay: float = 0.5) -> bool:
        """
        Force focus with exponential backoff retry strategy.
        
        Args:
            process_name: Name of the process to focus
            max_retries: Maximum number of retry attempts
            base_delay: Base delay for exponential backoff
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_macos:
            return False
            
        for attempt in range(max_retries):
            try:
                # Exponential backoff delay
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
                
                success = self.bring_window_to_front(process_name, delay=0)
                if success:
                    logging.info(f"Force focus successful on attempt {attempt + 1}")
                    return True
                else:
                    logging.warning(f"Force focus attempt {attempt + 1} failed")
                    
            except Exception as e:
                logging.error(f"Force focus attempt {attempt + 1} error: {e}")
        
        logging.error("All force focus attempts failed")
        return False
    
    def cleanup_focus_timers(self, timers: List[threading.Timer]):
        """Cancel all scheduled focus timers."""
        for timer in timers:
            try:
                timer.cancel()
            except Exception as e:
                logging.warning(f"Error canceling timer: {e}")
    
    def get_process_info(self) -> dict:
        """
        Get information about running Python processes.
        
        Returns:
            dict: Process information
        """
        if not self.is_macos:
            return {}
            
        try:
            # Get process information using ps
            result = subprocess.run(
                ['ps', 'aux'], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                python_processes = [line for line in lines if 'python' in line.lower()]
                return {
                    'total_processes': len(python_processes),
                    'processes': python_processes[:5]  # Limit to first 5
                }
            else:
                return {'error': 'Failed to get process info'}
                
        except Exception as e:
            logging.error(f"Error getting process info: {e}")
            return {'error': str(e)}


# Convenience functions for easy integration
def bring_window_to_front_mac(process_name: str = "Python", delay: float = 0.5) -> bool:
    """Convenience function for basic window focus."""
    manager = MacOSFocusManager()
    return manager.bring_window_to_front(process_name, delay)


def schedule_focus_for_webview(window_title: str = "CleanHouse", 
                              initial_delay: float = 1.0) -> List[threading.Timer]:
    """Convenience function for WebView focus scheduling."""
    manager = MacOSFocusManager()
    return manager.schedule_focus_attempts("Python", initial_delay, 3, 1.0)


def force_webview_focus() -> bool:
    """Convenience function for forced WebView focus."""
    manager = MacOSFocusManager()
    return manager.force_focus_with_retry("Python", 5, 0.5)
