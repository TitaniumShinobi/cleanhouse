# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - cross_platform_focus.py
#  Cross-platform focus management for OAuth popups
#  Devon • 2025‑01‑27
# ──────────────────────────────────────────────────────────────────────────────

import platform
import logging
from typing import Optional, List
from .macos_focus import MacOSFocusManager

class CrossPlatformFocusManager:
    """
    Cross-platform focus management that adapts to the current operating system.
    """
    
    def __init__(self):
        self.system = platform.system()
        self.macos_manager = MacOSFocusManager() if self.system == 'Darwin' else None
        
    def is_macos(self) -> bool:
        """Check if running on macOS."""
        return self.system == 'Darwin'
    
    def is_windows(self) -> bool:
        """Check if running on Windows."""
        return self.system == 'Windows'
    
    def is_linux(self) -> bool:
        """Check if running on Linux."""
        return self.system == 'Linux'
    
    def bring_window_to_front(self, process_name: str = "Python", delay: float = 0.5) -> bool:
        """
        Bring window to front using platform-specific methods.
        
        Args:
            process_name: Name of the process to focus
            delay: Delay before attempting focus
            
        Returns:
            bool: True if successful, False otherwise
        """
        if self.is_macos():
            return self._macos_focus(process_name, delay)
        elif self.is_windows():
            return self._windows_focus(process_name, delay)
        elif self.is_linux():
            return self._linux_focus(process_name, delay)
        else:
            logging.warning(f"Unsupported platform: {self.system}")
            return False
    
    def _macos_focus(self, process_name: str, delay: float) -> bool:
        """macOS-specific focus management."""
        if self.macos_manager:
            return self.macos_manager.bring_window_to_front(process_name, delay)
        return False
    
    def _windows_focus(self, process_name: str, delay: float) -> bool:
        """Windows-specific focus management."""
        try:
            import subprocess
            import time
            
            if delay > 0:
                time.sleep(delay)
            
            # Use Windows API to bring window to front
            # This is a simplified approach - in production you might want to use win32gui
            try:
                # Try using PowerShell to bring window to front
                ps_script = f'''
                Add-Type -TypeDefinition @"
                using System;
                using System.Runtime.InteropServices;
                public class Win32 {{
                    [DllImport("user32.dll")]
                    public static extern bool SetForegroundWindow(IntPtr hWnd);
                    [DllImport("user32.dll")]
                    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
                }}
"@
                $hwnd = [Win32]::FindWindow($null, "{process_name}")
                if ($hwnd -ne [IntPtr]::Zero) {{
                    [Win32]::SetForegroundWindow($hwnd)
                }}
                '''
                
                result = subprocess.run(
                    ['powershell', '-Command', ps_script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    logging.info("Windows focus successful")
                    return True
                else:
                    logging.warning(f"Windows focus failed: {result.stderr}")
                    return False
                    
            except Exception as e:
                logging.warning(f"Windows focus error: {e}")
                return False
                
        except ImportError:
            logging.warning("Windows focus management not available")
            return False
    
    def _linux_focus(self, process_name: str, delay: float) -> bool:
        """Linux-specific focus management."""
        try:
            import subprocess
            import time
            
            if delay > 0:
                time.sleep(delay)
            
            # Try using wmctrl if available
            try:
                result = subprocess.run(
                    ['which', 'wmctrl'], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                
                if result.returncode == 0:
                    # Use wmctrl to bring window to front
                    wmctrl_result = subprocess.run(
                        ['wmctrl', '-a', process_name],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if wmctrl_result.returncode == 0:
                        logging.info("Linux focus successful with wmctrl")
                        return True
                    else:
                        logging.warning(f"wmctrl focus failed: {wmctrl_result.stderr}")
                
            except Exception as e:
                logging.warning(f"wmctrl not available: {e}")
            
            # Fallback: try using xdotool if available
            try:
                result = subprocess.run(
                    ['which', 'xdotool'], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                
                if result.returncode == 0:
                    # Use xdotool to bring window to front
                    xdotool_result = subprocess.run(
                        ['xdotool', 'search', '--name', process_name, 'windowactivate'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if xdotool_result.returncode == 0:
                        logging.info("Linux focus successful with xdotool")
                        return True
                    else:
                        logging.warning(f"xdotool focus failed: {xdotool_result.stderr}")
                
            except Exception as e:
                logging.warning(f"xdotool not available: {e}")
            
            # If neither wmctrl nor xdotool are available, log a warning
            logging.warning("No Linux focus management tools available (wmctrl or xdotool)")
            return False
            
        except Exception as e:
            logging.error(f"Linux focus error: {e}")
            return False
    
    def schedule_focus_attempts(self, process_name: str = "Python", 
                               initial_delay: float = 0.5, 
                               max_attempts: int = 3,
                               interval: float = 1.0) -> List:
        """
        Schedule focus attempts using platform-specific methods.
        
        Args:
            process_name: Name of the process to focus
            initial_delay: Initial delay before first attempt
            max_attempts: Maximum number of focus attempts
            interval: Interval between attempts
            
        Returns:
            List of scheduled focus attempts (timers, etc.)
        """
        if self.is_macos() and self.macos_manager:
            return self.macos_manager.schedule_focus_attempts(
                process_name, initial_delay, max_attempts, interval
            )
        else:
            # For Windows and Linux, we'll use a simpler approach
            import threading
            timers = []
            
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
    
    def cleanup_focus_timers(self, timers: List):
        """Clean up scheduled focus timers."""
        if self.is_macos() and self.macos_manager:
            self.macos_manager.cleanup_focus_timers(timers)
        else:
            # For Windows and Linux timers
            for timer in timers:
                try:
                    timer.cancel()
                except Exception as e:
                    logging.warning(f"Error canceling timer: {e}")
    
    def get_platform_info(self) -> dict:
        """
        Get information about the current platform and available focus methods.
        
        Returns:
            dict: Platform information
        """
        info = {
            'system': self.system,
            'is_macos': self.is_macos(),
            'is_windows': self.is_windows(),
            'is_linux': self.is_linux(),
            'focus_methods': []
        }
        
        if self.is_macos():
            info['focus_methods'] = ['AppleScript', 'System Events']
        elif self.is_windows():
            info['focus_methods'] = ['PowerShell', 'Win32 API']
        elif self.is_linux():
            # Check for available tools
            available_tools = []
            try:
                import subprocess
                
                # Check for wmctrl
                result = subprocess.run(['which', 'wmctrl'], capture_output=True, timeout=5)
                if result.returncode == 0:
                    available_tools.append('wmctrl')
                
                # Check for xdotool
                result = subprocess.run(['which', 'xdotool'], capture_output=True, timeout=5)
                if result.returncode == 0:
                    available_tools.append('xdotool')
                    
            except Exception:
                pass
            
            info['focus_methods'] = available_tools
        
        return info


# Convenience functions for easy integration
def get_platform_focus_manager() -> CrossPlatformFocusManager:
    """Get a platform-appropriate focus manager."""
    return CrossPlatformFocusManager()


def bring_window_to_front_cross_platform(process_name: str = "Python", delay: float = 0.5) -> bool:
    """Cross-platform window focus function."""
    manager = get_platform_focus_manager()
    return manager.bring_window_to_front(process_name, delay)


def schedule_focus_cross_platform(process_name: str = "Python", 
                                 initial_delay: float = 0.5, 
                                 max_attempts: int = 3) -> List:
    """Cross-platform focus scheduling function."""
    manager = get_platform_focus_manager()
    return manager.schedule_focus_attempts(process_name, initial_delay, max_attempts, 1.0)
