# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - service.py
#  Background service functionality
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
# Windows-specific imports (optional)
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    import win32gui
    import win32con
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

import socket

# Additional Windows-specific imports (optional)
try:
    import win32api
except ImportError:
    win32api = None

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config
from corefiles.integrity import verify_integrity
from corefiles.passion import ignite_passion
from corefiles.notifications import NotificationManager

if WINDOWS_AVAILABLE:
    class CleanHouseService(win32serviceutil.ServiceFramework):
        _svc_name_ = "CleanHouseService"
        _svc_display_name_ = "CleanHouse Observability Service"
        _svc_description_ = "Monitors local process, file integrity, and network signals"

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.running = False
            self.notification_manager = NotificationManager()
            self.monitor_thread = None
            self.last_scan_time = None
            self.scan_interval = config.SCAN_INTERVAL

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            self.running = False

        def SvcDoRun(self):
            self.running = True
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, '')
            )
            self.main()

        def main(self):
            while self.running:
                try:
                    # Check if it's time for a scan
                    current_time = datetime.now()
                    if (self.last_scan_time is None or 
                        (current_time - self.last_scan_time).total_seconds() >= self.scan_interval):
                        
                        # Perform integrity check
                        issues = verify_integrity(config.BASE_DIR)
                        
                        if issues:
                            # Send notification for issues
                            self.notification_manager.send_notification(
                                "Security Alert",
                                f"Detected {len(issues)} security issues",
                                "warning"
                            )
                            
                            # Log issues
                            logging.warning(f"Security issues detected: {issues}")
                            
                            # Take action based on severity
                            if len(issues) >= config.ALERT_THRESHOLDS['critical']:
                                ignite_passion(config.BASE_DIR, dry_run=False)
                        
                        self.last_scan_time = current_time
                    
                    # Sleep for a short interval
                    time.sleep(1)
                    
                except Exception as e:
                    logging.error(f"Service error: {str(e)}")
                    self.notification_manager.send_notification(
                        "Service Error",
                        str(e),
                        "error"
                    )
                    time.sleep(5)  # Wait before retrying
else:
    # Fallback for non-Windows systems
    class CleanHouseService:
        def __init__(self, *args, **kwargs):
            pass

def install_service():
    """Install the CleanHouse service."""
    if not WINDOWS_AVAILABLE:
        print("Service installation is only supported on Windows")
        return False
    
    try:
        win32serviceutil.InstallService(
            pythonClassString = "corefiles.service.CleanHouseService",
            serviceName = "CleanHouseService",
            displayName = "CleanHouse Observability Service",
            description = "Monitors local process, file integrity, and network signals",
            startType = win32service.SERVICE_AUTO_START
        )
        print("Service installed successfully")
        return True
    except Exception as e:
        print(f"Failed to install service: {str(e)}")
        return False

def remove_service():
    """Remove the CleanHouse service."""
    if not WINDOWS_AVAILABLE:
        print("Service removal is only supported on Windows")
        return False
    
    try:
        win32serviceutil.RemoveService("CleanHouseService")
        print("Service removed successfully")
        return True
    except Exception as e:
        print(f"Failed to remove service: {str(e)}")
        return False

if __name__ == '__main__':
    if not WINDOWS_AVAILABLE:
        print("Service functionality is only supported on Windows")
        sys.exit(1)
    
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(CleanHouseService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(CleanHouseService) 
