#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - surveillance_detector.py
#  Comprehensive surveillance/monitoring detection framework
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

"""
Surveillance Detection Framework

Scans the system for evidence of surveillance, monitoring, keyloggers,
remote access tools, and other tracking software.
"""

import os
import sys
import json
import re
import subprocess
import platform
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict
import hashlib

# ╭─────────────────────────────── Configuration ────────────────────────────╮

# Known surveillance software signatures
SURVEILLANCE_SIGNATURES = {
    'keyloggers': [
        'keylogger', 'keylog', 'keystroke', 'keycapture', 'keymonitor',
        'logkeys', 'pykeylogger', 'kidlogger', 'refog', 'spytector',
        'keylog', 'keystroke_logger', 'key_monitor'
    ],
    'screen_capture': [
        'screenshot', 'screen_capture', 'screenrecorder', 'screen_monitor',
        'desktop_spy', 'screenwatch', 'spytech', 'activtrak', 'teramind',
        'veriato', 'workpuls', 'hubstaff', 'timecamp', 'desklog'
    ],
    'remote_access': [
        'teamviewer', 'anydesk', 'logmein', 'gotomypc', 'vnc', 'rdp',
        'remote_desktop', 'remotepc', 'splashtop', 'chrome_remote',
        'ammyy', 'ultraviewer', 'supremo', 'dwservice', 'rustdesk',
        'parsec', 'remmina', 'tigervnc', 'tightvnc', 'realvnc'
    ],
    'monitoring_software': [
        'spector', 'spytech', 'activtrak', 'teramind', 'veriato',
        'workpuls', 'hubstaff', 'timecamp', 'desklog', 'activtrak',
        'veriato_360', 'workforce', 'interguard', 'staffcop',
        'monitor_employee', 'employee_monitor', 'staff_monitor',
        'workplace_monitor', 'productivity_monitor'
    ],
    'network_monitoring': [
        'wireshark', 'tcpdump', 'ettercap', 'cain', 'netmon',
        'network_monitor', 'packet_capture', 'sniffer', 'mitm',
        'burp', 'charles', 'fiddler', 'proxyman', 'mitmproxy'
    ],
    'system_modifiers': [
        'rootkit', 'bootkit', 'kernel_extension', 'kext', 'driver',
        'system_extension', 'kernel_module', 'syscall_hook'
    ],
    'browser_tracking': [
        'browser_extension', 'chrome_extension', 'firefox_addon',
        'safari_extension', 'tracking_extension', 'analytics_extension'
    ]
}

# Suspicious file patterns
SUSPICIOUS_PATTERNS = [
    r'\.log$', r'\.keylog$', r'\.capture$', r'\.spy$', r'\.monitor$',
    r'hidden', r'secret', r'stealth', r'covert', r'private_log',
    r'activity_log', r'keystroke', r'screenshot', r'desktop_capture'
]

# macOS-specific locations to check
MACOS_SURVEILLANCE_LOCATIONS = [
    # Launch Agents/Daemons (common surveillance installation points)
    Path.home() / 'Library' / 'LaunchAgents',
    Path('/Library/LaunchAgents'),
    Path('/Library/LaunchDaemons'),
    Path('/System/Library/LaunchAgents'),
    Path('/System/Library/LaunchDaemons'),

    # Application directories
    Path('/Applications'),
    Path.home() / 'Applications',

    # System binaries
    Path('/usr/local/bin'),
    Path('/opt'),
    Path('/usr/bin'),
    Path('/bin'),

    # Browser extensions
    Path.home() / 'Library/Application Support/Google/Chrome/Default/Extensions',
    Path.home() / 'Library/Application Support/Firefox/Profiles',
    Path.home() / 'Library/Safari/Extensions',

    # System logs and caches
    Path('/var/log'),
    Path('/private/var/log'),
    Path.home() / 'Library/Logs',
    Path.home() / 'Library/Caches',

    # Hidden directories
    Path.home() / '.hidden',
    Path.home() / '.local',
    Path('/.hidden'),

    # Temporary directories
    Path('/tmp'),
    Path('/var/tmp'),
    Path.home() / 'Library/Caches/TemporaryItems',
]

# Suspicious process patterns
SUSPICIOUS_PROCESSES = [
    'keylogger', 'keylog', 'keystroke', 'screen_capture', 'screenrecorder',
    'remote_access', 'vnc', 'rdp', 'teamviewer', 'anydesk', 'logmein',
    'spector', 'spytech', 'activtrak', 'teramind', 'veriato', 'workpuls',
    'hubstaff', 'timecamp', 'desklog', 'wireshark', 'tcpdump', 'ettercap',
    'mitm', 'burp', 'charles', 'fiddler', 'proxyman'
]

# Network monitoring ports
SUSPICIOUS_PORTS = [
    5900,  # VNC
    3389,  # RDP
    5938,  # TeamViewer
    7070,  # RealVNC
    5800,  # VNC HTTP
    8080,  # Various remote access
    8888,  # Various remote access
    9999,  # Various remote access
]

# ╭─────────────────────────────── Core Classes ──────────────────────────────╮

class SurveillanceDetector:
    """Comprehensive surveillance detection framework."""

    def __init__(self, output_file: Optional[Path] = None, verbose: bool = True):
        if output_file is None:
            # Default to workspace directory if available, otherwise home
            try:
                workspace = Path(__file__).parent
                self.output_file = workspace / 'surveillance_scan.json'
            except:
                self.output_file = Path.home() / 'Documents' / 'CleanHouse' / 'surveillance_scan.json'
        else:
            # Convert to absolute path
            self.output_file = Path(output_file).resolve()
        self.verbose = verbose
        self.findings = {
            'timestamp': datetime.now().isoformat(),
            'system_info': self._get_system_info(),
            'keyloggers': [],
            'screen_capture': [],
            'remote_access': [],
            'monitoring_software': [],
            'network_monitoring': [],
            'suspicious_files': [],
            'suspicious_processes': [],
            'suspicious_network_connections': [],
            'launch_agents': [],
            'browser_extensions': [],
            'system_modifications': [],
            'hidden_files': [],
            'audio_surveillance': [],
            'bluetooth_monitoring': [],
            'wifi_monitoring': [],
            'dns_hijacking': [],
            'arp_spoofing': [],
            'screen_sharing_active': [],
            'cloud_surveillance': [],
            'data_exfiltration': [],
            'summary': {
                'total_findings': 0,
                'critical': 0,
                'high': 0,
                'medium': 0,
                'low': 0
            }
        }
        self.scanned_paths = set()
        self.scanned_files = 0

    def _get_system_info(self) -> Dict:
        """Get system information."""
        return {
            'platform': platform.system(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'hostname': platform.node(),
            'user': os.getenv('USER', 'unknown')
        }

    def _log(self, message: str, level: str = 'INFO'):
        """Log a message."""
        if self.verbose:
            print(f"[{level}] {message}")

    def scan_all(self) -> Dict:
        """Run comprehensive surveillance scan."""
        self._log("Starting comprehensive surveillance detection scan...")

        # Scan file system
        self._log("Scanning file system for surveillance software...")
        self._scan_filesystem()

        # Check running processes
        self._log("Checking running processes...")
        self._scan_processes()

        # Check network connections
        self._log("Checking network connections...")
        self._scan_network_connections()

        # Check launch agents/daemons
        self._log("Checking launch agents and daemons...")
        self._scan_launch_agents()

        # Check browser extensions
        self._log("Checking browser extensions...")
        self._scan_browser_extensions()

        # Check system modifications
        self._log("Checking for system modifications...")
        self._scan_system_modifications()

        # Check for hidden files
        self._log("Checking for hidden surveillance files...")
        self._scan_hidden_files()

        # Check audio/microphone access
        self._log("Checking audio/microphone access...")
        self._scan_audio_access()

        # Check Bluetooth connections
        self._log("Checking Bluetooth connections...")
        self._scan_bluetooth_connections()

        # Check WiFi/router security
        self._log("Checking WiFi/router security (DNS hijacking, ARP spoofing)...")
        self._scan_wifi_security()

        # Check for active screen sharing
        self._log("Checking for active screen sharing...")
        self._scan_screen_sharing()

        # Check for cloud service surveillance
        self._log("Checking for cloud service surveillance (AWS, iCloud, etc.)...")
        self._scan_cloud_surveillance()

        # Check for data exfiltration
        self._log("Monitoring for unauthorized data collection...")
        self._scan_data_exfiltration()

        # Calculate summary
        self._calculate_summary()

        # Determine if surveillance is detected
        surveillance_detected = self._is_surveillance_detected()

        # Legacy direct desktop notification path is disabled by default to avoid
        # untethered alert spam; CleanHouse operator notifications are the canonical path.
        if surveillance_detected:
            summary = self.findings['summary']
            critical = summary.get('critical', 0)
            high = summary.get('high', 0)

            notification_title = "🚨 Surveillance Detected"
            notification_message = f"Found {critical} critical and {high} high-severity surveillance indicators on your system!"
            legacy_notifications_enabled = os.getenv("CLEANHOUSE_LEGACY_SURVEILLANCE_NOTIFICATIONS", "").strip().lower() in {"1", "true", "yes", "on"}
            if legacy_notifications_enabled:
                self._send_macos_notification(notification_title, notification_message, sound="Basso")
                self._log("Surveillance detected - notification sent", "ALERT")
            else:
                self._log(
                    "Surveillance detected - desktop notification suppressed (use operator notification pipeline)",
                    "ALERT",
                )
        else:
            self._log("No surveillance detected", "INFO")

        # Save results
        self._save_results()

        self._log(f"Scan complete. Found {self.findings['summary']['total_findings']} findings.")
        return self.findings

    def _scan_filesystem(self):
        """Scan filesystem for surveillance software."""
        for location in MACOS_SURVEILLANCE_LOCATIONS:
            if not location.exists():
                continue

            try:
                if location.is_file():
                    self._check_file(location)
                elif location.is_dir():
                    self._scan_directory(location, max_depth=5)
            except PermissionError:
                self._log(f"Permission denied: {location}", "WARNING")
            except Exception as e:
                self._log(f"Error scanning {location}: {e}", "ERROR")

    def _scan_directory(self, directory: Path, max_depth: int = 5, current_depth: int = 0):
        """Recursively scan directory."""
        if current_depth >= max_depth:
            return

        try:
            for item in directory.iterdir():
                if item in self.scanned_paths:
                    continue
                self.scanned_paths.add(item)

                try:
                    if item.is_file():
                        self._check_file(item)
                        self.scanned_files += 1
                    elif item.is_dir() and not item.is_symlink():
                        self._scan_directory(item, max_depth, current_depth + 1)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass

    def _check_file(self, filepath: Path):
        """Check a single file for surveillance indicators."""
        filename_lower = filepath.name.lower()
        path_str_lower = str(filepath).lower()

        # Check filename against signatures
        for category, signatures in SURVEILLANCE_SIGNATURES.items():
            for sig in signatures:
                if sig.lower() in filename_lower or sig.lower() in path_str_lower:
                    finding = {
                        'file': str(filepath),
                        'category': category,
                        'signature': sig,
                        'severity': self._determine_severity(category),
                        'detected_at': datetime.now().isoformat()
                    }
                    self.findings[category].append(finding)
                    self._log(f"Found {category}: {filepath}", "ALERT")

        # Check for suspicious patterns
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, filename_lower) or re.search(pattern, path_str_lower):
                finding = {
                    'file': str(filepath),
                    'pattern': pattern,
                    'severity': 'medium',
                    'detected_at': datetime.now().isoformat()
                }
                self.findings['suspicious_files'].append(finding)

    def _scan_processes(self):
        """Scan running processes for surveillance software."""
        try:
            if platform.system() == 'Darwin':  # macOS
                result = subprocess.run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                processes = result.stdout.split('\n')

                for proc_line in processes:
                    if not proc_line.strip():
                        continue

                    proc_lower = proc_line.lower()
                    for category, signatures in SURVEILLANCE_SIGNATURES.items():
                        for sig in signatures:
                            if sig.lower() in proc_lower:
                                # Extract process info
                                parts = proc_line.split()
                                if len(parts) >= 11:
                                    finding = {
                                        'process': parts[10] if len(parts) > 10 else 'unknown',
                                        'pid': parts[1] if len(parts) > 1 else 'unknown',
                                        'user': parts[0] if len(parts) > 0 else 'unknown',
                                        'category': category,
                                        'signature': sig,
                                        'severity': self._determine_severity(category),
                                        'command_line': ' '.join(parts[10:]) if len(parts) > 10 else proc_line,
                                        'detected_at': datetime.now().isoformat()
                                    }
                                    self.findings['suspicious_processes'].append(finding)
                                    self._log(f"Found suspicious process: {finding['process']}", "ALERT")
        except Exception as e:
            self._log(f"Error scanning processes: {e}", "ERROR")

    def _scan_network_connections(self):
        """Scan network connections for suspicious activity."""
        try:
            if platform.system() == 'Darwin':  # macOS
                # Check listening ports
                result = subprocess.run(
                    ['lsof', '-i', '-P', '-n'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                connections = result.stdout.split('\n')
                for conn_line in connections[1:]:  # Skip header
                    if not conn_line.strip():
                        continue

                    parts = conn_line.split()
                    if len(parts) >= 9:
                        try:
                            port_info = parts[8]  # Usually contains port info
                            if ':' in port_info:
                                port = int(port_info.split(':')[-1])
                                if port in SUSPICIOUS_PORTS:
                                    finding = {
                                        'process': parts[0] if len(parts) > 0 else 'unknown',
                                        'pid': parts[1] if len(parts) > 1 else 'unknown',
                                        'port': port,
                                        'connection': port_info,
                                        'severity': 'high',
                                        'detected_at': datetime.now().isoformat()
                                    }
                                    self.findings['suspicious_network_connections'].append(finding)
                                    self._log(f"Found suspicious network connection on port {port}", "ALERT")
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            self._log(f"Error scanning network connections: {e}", "ERROR")

    def _scan_launch_agents(self):
        """Scan launch agents and daemons for surveillance software."""
        launch_locations = [
            Path.home() / 'Library/LaunchAgents',
            Path('/Library/LaunchAgents'),
            Path('/Library/LaunchDaemons'),
            Path('/System/Library/LaunchAgents'),
            Path('/System/Library/LaunchDaemons'),
        ]

        for location in launch_locations:
            if not location.exists():
                continue

            try:
                for plist_file in location.glob('*.plist'):
                    self._check_launch_agent(plist_file)
            except PermissionError:
                self._log(f"Permission denied: {location}", "WARNING")
            except Exception as e:
                self._log(f"Error scanning {location}: {e}", "ERROR")

    def _check_launch_agent(self, plist_file: Path):
        """Check a launch agent plist file."""
        try:
            # Try to read plist using plutil or defaults
            result = subprocess.run(
                ['plutil', '-convert', 'json', '-o', '-', str(plist_file)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                plist_data = json.loads(result.stdout)
                plist_str = json.dumps(plist_data).lower()

                # Check for surveillance indicators
                for category, signatures in SURVEILLANCE_SIGNATURES.items():
                    for sig in signatures:
                        if sig.lower() in plist_str or sig.lower() in plist_file.name.lower():
                            finding = {
                                'plist_file': str(plist_file),
                                'category': category,
                                'signature': sig,
                                'program': plist_data.get('Program', plist_data.get('ProgramArguments', ['unknown'])),
                                'severity': self._determine_severity(category),
                                'detected_at': datetime.now().isoformat()
                            }
                            self.findings['launch_agents'].append(finding)
                            self._log(f"Found suspicious launch agent: {plist_file}", "ALERT")
        except Exception as e:
            # If plutil fails, check filename
            filename_lower = plist_file.name.lower()
            for category, signatures in SURVEILLANCE_SIGNATURES.items():
                for sig in signatures:
                    if sig.lower() in filename_lower:
                        finding = {
                            'plist_file': str(plist_file),
                            'category': category,
                            'signature': sig,
                            'severity': self._determine_severity(category),
                            'detected_at': datetime.now().isoformat()
                        }
                        self.findings['launch_agents'].append(finding)
                        self._log(f"Found suspicious launch agent: {plist_file}", "ALERT")

    def _scan_browser_extensions(self):
        """Scan browser extensions for tracking/surveillance."""
        extension_locations = [
            Path.home() / 'Library/Application Support/Google/Chrome/Default/Extensions',
            Path.home() / 'Library/Application Support/Firefox/Profiles',
            Path.home() / 'Library/Safari/Extensions',
        ]

        for location in extension_locations:
            if not location.exists():
                continue

            try:
                if 'Chrome' in str(location):
                    # Chrome extensions are in versioned folders
                    for ext_dir in location.iterdir():
                        if ext_dir.is_dir():
                            self._check_chrome_extension(ext_dir)
                elif 'Firefox' in str(location):
                    # Firefox profiles
                    for profile_dir in location.iterdir():
                        if profile_dir.is_dir():
                            extensions_dir = profile_dir / 'extensions'
                            if extensions_dir.exists():
                                for ext_file in extensions_dir.glob('*.xpi'):
                                    self._check_firefox_extension(ext_file)
                elif 'Safari' in str(location):
                    for ext_file in location.glob('*.safariextz'):
                        self._check_safari_extension(ext_file)
            except Exception as e:
                self._log(f"Error scanning browser extensions: {e}", "ERROR")

    def _check_chrome_extension(self, ext_dir: Path):
        """Check a Chrome extension directory."""
        manifest_file = ext_dir / 'manifest.json'
        if manifest_file.exists():
            try:
                with open(manifest_file, 'r') as f:
                    manifest = json.load(f)
                    manifest_str = json.dumps(manifest).lower()

                    # Check for suspicious permissions or names
                    permissions = manifest.get('permissions', [])
                    suspicious_perms = ['tabs', 'history', 'bookmarks', 'downloads',
                                       'management', 'privacy', 'system.storage']

                    if any(perm in permissions for perm in suspicious_perms):
                        finding = {
                            'extension_id': ext_dir.name,
                            'name': manifest.get('name', 'unknown'),
                            'version': manifest.get('version', 'unknown'),
                            'permissions': permissions,
                            'severity': 'medium',
                            'detected_at': datetime.now().isoformat()
                        }
                        self.findings['browser_extensions'].append(finding)
            except Exception as e:
                pass

    def _check_firefox_extension(self, ext_file: Path):
        """Check a Firefox extension."""
        # Firefox extensions are ZIP files, would need to extract to check
        filename_lower = ext_file.name.lower()
        for sig in ['keylog', 'monitor', 'track', 'spy']:
            if sig in filename_lower:
                finding = {
                    'extension_file': str(ext_file),
                    'signature': sig,
                    'severity': 'medium',
                    'detected_at': datetime.now().isoformat()
                }
                self.findings['browser_extensions'].append(finding)

    def _check_safari_extension(self, ext_file: Path):
        """Check a Safari extension."""
        filename_lower = ext_file.name.lower()
        for sig in ['keylog', 'monitor', 'track', 'spy']:
            if sig in filename_lower:
                finding = {
                    'extension_file': str(ext_file),
                    'signature': sig,
                    'severity': 'medium',
                    'detected_at': datetime.now().isoformat()
                }
                self.findings['browser_extensions'].append(finding)

    def _scan_system_modifications(self):
        """Check for system modifications that enable surveillance."""
        # Check System Integrity Protection status
        try:
            result = subprocess.run(
                ['csrutil', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if 'disabled' in result.stdout.lower():
                finding = {
                    'modification': 'System Integrity Protection (SIP) is disabled',
                    'severity': 'critical',
                    'description': 'SIP disabled allows system modifications that could enable surveillance',
                    'detected_at': datetime.now().isoformat()
                }
                self.findings['system_modifications'].append(finding)
                self._log("System Integrity Protection is disabled!", "CRITICAL")
        except Exception:
            pass

        # Check for kernel extensions
        try:
            result = subprocess.run(
                ['kextstat'],
                capture_output=True,
                text=True,
                timeout=10
            )
            kext_output = result.stdout.lower()
            for sig in ['keylog', 'monitor', 'spy', 'track']:
                if sig in kext_output:
                    finding = {
                        'modification': f'Kernel extension containing "{sig}"',
                        'severity': 'critical',
                        'description': 'Kernel extensions can monitor system activity at low level',
                        'detected_at': datetime.now().isoformat()
                    }
                    self.findings['system_modifications'].append(finding)
        except Exception:
            pass

    def _scan_hidden_files(self):
        """Scan for hidden surveillance files."""
        hidden_locations = [
            Path.home(),
            Path('/'),
            Path('/tmp'),
            Path('/var/tmp'),
        ]

        for location in hidden_locations:
            if not location.exists():
                continue

            try:
                # Look for files starting with . that match patterns
                for item in location.iterdir():
                    if item.name.startswith('.') and item.is_file():
                        filename_lower = item.name.lower()
                        for pattern in SUSPICIOUS_PATTERNS:
                            if re.search(pattern, filename_lower):
                                finding = {
                                    'file': str(item),
                                    'pattern': pattern,
                                    'severity': 'medium',
                                    'detected_at': datetime.now().isoformat()
                                }
                                self.findings['hidden_files'].append(finding)
            except (PermissionError, OSError):
                continue

    def _scan_audio_access(self):
        """Check for audio/microphone access and surveillance."""
        try:
            # Check TCC (Transparency, Consent, and Control) database for microphone access
            tcc_db = Path.home() / 'Library/Application Support/com.apple.TCC/TCC.db'

            if tcc_db.exists():
                # Check for processes with microphone access
                result = subprocess.run(
                    ['sqlite3', str(tcc_db),
                     "SELECT service, client FROM access WHERE service='kTCCServiceMicrophone' AND allowed=1;"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0 and result.stdout.strip():
                    clients = result.stdout.strip().split('\n')
                    for client in clients:
                        if client and 'com.apple.' not in client.lower():
                            # Extract client name from output
                            client_name = client.split('|')[-1].strip() if '|' in client else client.strip()
                            if client_name:
                                finding = {
                                    'client': client_name,
                                    'access_type': 'microphone',
                                    'severity': 'high',
                                    'description': 'Application has microphone access',
                                    'detected_at': datetime.now().isoformat()
                                }
                                self.findings['audio_surveillance'].append(finding)
                                self._log(f"Found microphone access: {client_name}", "ALERT")

            # Check for running audio capture processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=30
            )

            audio_keywords = ['soundflower', 'blackhole', 'loopback', 'audio_capture',
                            'mic_monitor', 'sound_recorder', 'voice_monitor']

            for line in result.stdout.split('\n'):
                line_lower = line.lower()
                for keyword in audio_keywords:
                    if keyword in line_lower and 'com.apple.' not in line_lower:
                        parts = line.split()
                        if len(parts) >= 11:
                            proc_name = ' '.join(parts[10:])[:60]
                            finding = {
                                'process': proc_name,
                                'pid': parts[1] if len(parts) > 1 else 'unknown',
                                'keyword': keyword,
                                'severity': 'high',
                                'detected_at': datetime.now().isoformat()
                            }
                            self.findings['audio_surveillance'].append(finding)
                            self._log(f"Found audio capture process: {proc_name}", "ALERT")
                            break

        except subprocess.TimeoutExpired:
            self._log("Audio access scan timed out", "WARNING")
        except PermissionError:
            self._log("Permission denied accessing TCC database (may need Full Disk Access)", "WARNING")
        except FileNotFoundError:
            self._log("sqlite3 not found - skipping TCC database check", "WARNING")
        except Exception as e:
            self._log(f"Error scanning audio access: {e}", "ERROR")

    def _scan_bluetooth_connections(self):
        """Check for suspicious Bluetooth connections."""
        try:
            # Check active Bluetooth connections
            result = subprocess.run(
                ['system_profiler', 'SPBluetoothDataType'],
                capture_output=True,
                text=True,
                timeout=15
            )

            if result.returncode == 0:
                bluetooth_output = result.stdout

                # Check for connected devices
                lines = bluetooth_output.split('\n')
                current_device = None
                device_connected = False

                for i, line in enumerate(lines):
                    line_lower = line.lower()

                    # Look for device name
                    if 'name:' in line_lower:
                        current_device = line.split(':', 1)[-1].strip()
                        device_connected = False

                    # Check if device is connected
                    if 'connected: yes' in line_lower or 'state: connected' in line_lower:
                        device_connected = True

                    # If we found a connected device, log it
                    if device_connected and current_device:
                        finding = {
                            'device_name': current_device,
                            'status': 'connected',
                            'severity': 'medium',
                            'description': 'Active Bluetooth connection detected',
                            'detected_at': datetime.now().isoformat()
                        }
                        self.findings['bluetooth_monitoring'].append(finding)
                        self._log(f"Found active Bluetooth connection: {current_device}", "ALERT")
                        device_connected = False  # Reset to avoid duplicate entries
                        current_device = None

        except subprocess.TimeoutExpired:
            self._log("Bluetooth scan timed out", "WARNING")
        except FileNotFoundError:
            self._log("system_profiler not found - skipping Bluetooth check", "WARNING")
        except Exception as e:
            self._log(f"Error scanning Bluetooth: {e}", "ERROR")

    def _scan_wifi_security(self):
        """Check for WiFi/router-level monitoring threats."""
        try:
            # Check DNS servers (potential DNS hijacking)
            result = subprocess.run(
                ['scutil', '--dns'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                dns_output = result.stdout
                # Known legitimate DNS servers
                legitimate_dns = ['8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1',
                                 '208.67.222.222', '208.67.220.220', '9.9.9.9', '149.112.112.112']
                suspicious_dns = []

                for line in dns_output.split('\n'):
                    if 'nameserver' in line.lower() or 'nameserver[' in line.lower():
                        # Extract IP addresses from the line
                        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
                        ips = re.findall(ip_pattern, line)

                        for ip in ips:
                            # Check if it's a legitimate DNS
                            if ip not in legitimate_dns:
                                # Check if it's a local/private IP (router - usually OK)
                                if not (ip.startswith('192.168.') or ip.startswith('10.') or
                                       ip.startswith('172.16.') or ip.startswith('172.17.') or
                                       ip.startswith('172.18.') or ip.startswith('172.19.') or
                                       ip.startswith('172.20.') or ip.startswith('172.21.') or
                                       ip.startswith('172.22.') or ip.startswith('172.23.') or
                                       ip.startswith('172.24.') or ip.startswith('172.25.') or
                                       ip.startswith('172.26.') or ip.startswith('172.27.') or
                                       ip.startswith('172.28.') or ip.startswith('172.29.') or
                                       ip.startswith('172.30.') or ip.startswith('172.31.') or
                                       ip == '127.0.0.1' or ip == '::1'):
                                    if ip not in suspicious_dns:
                                        suspicious_dns.append(ip)

                if suspicious_dns:
                    finding = {
                        'dns_servers': suspicious_dns,
                        'severity': 'high',
                        'description': 'Unusual DNS servers detected (possible DNS hijacking)',
                        'detected_at': datetime.now().isoformat()
                    }
                    self.findings['dns_hijacking'].append(finding)
                    self._log(f"Found suspicious DNS servers: {suspicious_dns}", "ALERT")

            # Check ARP table for potential ARP spoofing
            result = subprocess.run(
                ['arp', '-a'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                arp_output = result.stdout
                # Look for multiple MAC addresses with same IP (ARP spoofing indicator)
                ip_to_mac = {}

                for line in arp_output.split('\n'):
                    if '(' in line and ')' in line:
                        try:
                            # Extract IP address (between parentheses)
                            ip_match = re.search(r'\(([^)]+)\)', line)
                            if ip_match:
                                ip = ip_match.group(1)

                                # Extract MAC address (after "at ")
                                mac_match = re.search(r'at\s+([0-9a-fA-F:]{17})', line)
                                if mac_match:
                                    mac = mac_match.group(1)

                                    if ip in ip_to_mac:
                                        if ip_to_mac[ip] != mac:
                                            finding = {
                                                'ip': ip,
                                                'mac_addresses': [ip_to_mac[ip], mac],
                                                'severity': 'critical',
                                                'description': 'Multiple MAC addresses for same IP (possible ARP spoofing)',
                                                'detected_at': datetime.now().isoformat()
                                            }
                                            self.findings['arp_spoofing'].append(finding)
                                            self._log(f"⚠️ ARP SPOOFING DETECTED: IP {ip} has multiple MAC addresses!", "CRITICAL")
                                    else:
                                        ip_to_mac[ip] = mac
                        except Exception:
                            continue

            # Check for WiFi monitoring tools
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=30
            )

            wifi_monitoring_keywords = ['airport', 'wifi_sniffer', 'packet_capture',
                                       'ettercap', 'aircrack', 'kismet', 'wireshark']

            for line in result.stdout.split('\n'):
                line_lower = line.lower()
                for keyword in wifi_monitoring_keywords:
                    if keyword in line_lower and 'com.apple.' not in line_lower:
                        parts = line.split()
                        if len(parts) >= 11:
                            proc_name = ' '.join(parts[10:])[:60]
                            # Filter out legitimate system processes
                            if 'airport' in keyword and 'airportd' not in proc_name.lower():
                                finding = {
                                    'process': proc_name,
                                    'pid': parts[1] if len(parts) > 1 else 'unknown',
                                    'keyword': keyword,
                                    'severity': 'high',
                                    'detected_at': datetime.now().isoformat()
                                }
                                self.findings['wifi_monitoring'].append(finding)
                                self._log(f"Found WiFi monitoring process: {proc_name}", "ALERT")
                                break

        except subprocess.TimeoutExpired:
            self._log("WiFi security scan timed out", "WARNING")
        except Exception as e:
            self._log(f"Error scanning WiFi security: {e}", "ERROR")

    def _scan_screen_sharing(self):
        """Check for active screen sharing/remote viewing."""
        try:
            # Check for screen sharing processes
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=30
            )

            screen_sharing_keywords = ['screen sharing', 'screen_sharing', 'remote desktop',
                                      'vnc', 'teamviewer', 'anydesk', 'logmein', 'gotomypc',
                                      'splashtop', 'chrome remote', 'rdp']

            for line in result.stdout.split('\n'):
                line_lower = line.lower()
                for keyword in screen_sharing_keywords:
                    if keyword in line_lower:
                        parts = line.split()
                        if len(parts) >= 11:
                            proc_name = ' '.join(parts[10:])[:60]
                            finding = {
                                'process': proc_name,
                                'pid': parts[1] if len(parts) > 1 else 'unknown',
                                'keyword': keyword,
                                'severity': 'critical',
                                'description': 'Active screen sharing detected',
                                'detected_at': datetime.now().isoformat()
                            }
                            self.findings['screen_sharing_active'].append(finding)
                            self._log(f"🚨 ACTIVE SCREEN SHARING: {proc_name}", "CRITICAL")
                            break

            # Check for screen sharing network connections
            result = subprocess.run(
                ['lsof', '-i', '-P', '-n'],
                capture_output=True,
                text=True,
                timeout=30
            )

            screen_sharing_ports = [5900, 3389, 5938, 7070, 5800]  # VNC, RDP, TeamViewer, etc.

            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        port_info = parts[8]
                        if ':' in port_info:
                            port = int(port_info.split(':')[-1])
                            if port in screen_sharing_ports:
                                proc_name = parts[0] if len(parts) > 0 else 'unknown'
                                finding = {
                                    'process': proc_name,
                                    'port': port,
                                    'connection': port_info,
                                    'severity': 'critical',
                                    'description': f'Screen sharing connection on port {port}',
                                    'detected_at': datetime.now().isoformat()
                                }
                                self.findings['screen_sharing_active'].append(finding)
                                self._log(f"🚨 SCREEN SHARING CONNECTION: {proc_name} on port {port}", "CRITICAL")
                    except (ValueError, IndexError):
                        continue

        except subprocess.TimeoutExpired:
            self._log("Screen sharing scan timed out", "WARNING")
        except Exception as e:
            self._log(f"Error scanning screen sharing: {e}", "ERROR")

    def _scan_cloud_surveillance(self):
        """Check for cloud services being used as surveillance mechanisms."""
        try:
            # Cloud service domains that could be used for surveillance
            cloud_surveillance_domains = [
                'amazonaws.com', 's3.amazonaws.com', 'cloudwatch.amazonaws.com',
                'logs.amazonaws.com', 'cloudtrail.amazonaws.com',
                'icloud.com', 'icloud-content.com', 'mzstatic.com',
                'googleapis.com', 'googlecloud.com', 'storage.googleapis.com',
                'azure.com', 'blob.core.windows.net', 'azurewebsites.net',
                'dropbox.com', 'dropboxapi.com', 'dropboxusercontent.com',
                'onedrive.com', 'live.com', 'microsoft.com',
                'box.com', 'boxcloud.com',
                'backblaze.com', 'wasabi.com'
            ]

            # Check network connections to cloud services
            result = subprocess.run(
                ['lsof', '-i', '-P', '-n'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                connections = result.stdout.split('\n')
                cloud_connections = {}

                for conn_line in connections[1:]:  # Skip header
                    if not conn_line.strip():
                        continue

                    parts = conn_line.split()
                    if len(parts) >= 9:
                        try:
                            # Extract connection info
                            conn_info = parts[8] if len(parts) > 8 else ''
                            proc_name = parts[0] if len(parts) > 0 else 'unknown'

                            # Check if connection is to a cloud service
                            for domain in cloud_surveillance_domains:
                                if domain in conn_info.lower():
                                    # Check if this is a suspicious process
                                    proc_lower = proc_name.lower()

                                    # Filter out legitimate system processes
                                    legitimate_processes = [
                                        'com.apple.', 'safari', 'chrome', 'firefox',
                                        'mail', 'calendar', 'photos', 'notes',
                                        'finder', 'system', 'kernel'
                                    ]

                                    is_legitimate = any(legit in proc_lower for legit in legitimate_processes)

                                    if not is_legitimate:
                                        # Check for suspicious patterns
                                        suspicious_patterns = [
                                            'python', 'node', 'ruby', 'perl', 'bash', 'sh',
                                            'curl', 'wget', 'nc', 'netcat', 'socat',
                                            'aws', 'gcloud', 'az', 'terraform',
                                            'screen', 'tmux', 'nohup'
                                        ]

                                        is_suspicious = any(pattern in proc_lower for pattern in suspicious_patterns)

                                        if is_suspicious or proc_name not in cloud_connections:
                                            if proc_name not in cloud_connections:
                                                cloud_connections[proc_name] = []
                                            cloud_connections[proc_name].append({
                                                'connection': conn_info,
                                                'domain': domain,
                                                'pid': parts[1] if len(parts) > 1 else 'unknown'
                                            })
                        except (ValueError, IndexError):
                            continue

                # Report suspicious cloud connections
                for proc_name, conns in cloud_connections.items():
                    for conn in conns:
                        finding = {
                            'process': proc_name,
                            'connection': conn['connection'],
                            'cloud_service': conn['domain'],
                            'pid': conn['pid'],
                            'severity': 'high',
                            'description': f'Suspicious connection to {conn["domain"]} from {proc_name}',
                            'detected_at': datetime.now().isoformat()
                        }
                        self.findings['cloud_surveillance'].append(finding)
                        self._log(f"⚠️ Cloud surveillance: {proc_name} → {conn['domain']}", "ALERT")

            # Check for cloud CLI tools being used
            cloud_cli_tools = ['aws', 'gcloud', 'az', 'terraform', 'cloudformation']

            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line_lower = line.lower()
                    for tool in cloud_cli_tools:
                        if tool in line_lower:
                            # Check for suspicious operations
                            suspicious_ops = [
                                's3 cp', 's3 sync', 's3 mv', 's3 put',
                                'logs put', 'logs create', 'logs describe',
                                'cloudwatch put-metric', 'cloudwatch put-log',
                                'cloudtrail create-trail', 'cloudtrail start-logging',
                                'upload', 'sync', 'export', 'backup'
                            ]

                            parts = line.split()
                            if len(parts) >= 11:
                                cmd_line = ' '.join(parts[10:]).lower()

                                # Check if it's a suspicious operation
                                for op in suspicious_ops:
                                    if op in cmd_line:
                                        proc_name = ' '.join(parts[10:])[:60]
                                        finding = {
                                            'process': proc_name,
                                            'pid': parts[1] if len(parts) > 1 else 'unknown',
                                            'tool': tool,
                                            'operation': op,
                                            'severity': 'high',
                                            'description': f'Cloud CLI tool ({tool}) performing suspicious operation: {op}',
                                            'detected_at': datetime.now().isoformat()
                                        }
                                        self.findings['cloud_surveillance'].append(finding)
                                        self._log(f"⚠️ Suspicious cloud operation: {tool} - {op}", "ALERT")
                                        break

            # Check for cloud credentials in suspicious locations
            cloud_credential_paths = [
                Path.home() / '.aws' / 'credentials',
                Path.home() / '.aws' / 'config',
                Path.home() / '.config' / 'gcloud' / 'credentials',
                Path.home() / '.azure' / 'credentials',
                Path('/tmp') / '.aws',
                Path('/tmp') / '.gcloud',
            ]

            for cred_path in cloud_credential_paths:
                if cred_path.exists():
                    # Check if credentials are world-readable (security issue)
                    try:
                        stat_info = cred_path.stat()
                        if stat_info.st_mode & 0o004:  # World-readable
                            finding = {
                                'credential_file': str(cred_path),
                                'severity': 'high',
                                'description': f'Cloud credentials file is world-readable: {cred_path}',
                                'detected_at': datetime.now().isoformat()
                            }
                            self.findings['cloud_surveillance'].append(finding)
                            self._log(f"⚠️ Insecure cloud credentials: {cred_path}", "ALERT")
                    except (OSError, PermissionError):
                        pass

            # Check for iCloud sync of sensitive directories
            icloud_sync_paths = [
                Path.home() / 'Library' / 'Mobile Documents' / 'com~apple~CloudDocs',
                Path.home() / 'Library' / 'Application Support' / 'MobileSync' / 'Backup',
            ]

            # Check if sensitive directories are being synced
            sensitive_patterns = ['keylog', 'capture', 'monitor', 'spy', 'surveillance']

            for sync_path in icloud_sync_paths:
                if sync_path.exists():
                    try:
                        for item in sync_path.rglob('*'):
                            if item.is_file():
                                item_name_lower = item.name.lower()
                                for pattern in sensitive_patterns:
                                    if pattern in item_name_lower:
                                        finding = {
                                            'file': str(item),
                                            'sync_location': str(sync_path),
                                            'pattern': pattern,
                                            'severity': 'high',
                                            'description': f'Sensitive file syncing to iCloud: {item.name}',
                                            'detected_at': datetime.now().isoformat()
                                        }
                                        self.findings['cloud_surveillance'].append(finding)
                                        self._log(f"⚠️ Sensitive file in iCloud sync: {item.name}", "ALERT")
                                        break
                    except (PermissionError, OSError):
                        pass

        except subprocess.TimeoutExpired:
            self._log("Cloud surveillance scan timed out", "WARNING")
        except Exception as e:
            self._log(f"Error scanning cloud surveillance: {e}", "ERROR")

    def _scan_data_exfiltration(self):
        """Monitor for unauthorized data collection and exfiltration."""
        try:
            # Sensitive data patterns that should NOT be collected
            sensitive_data_patterns = [
                'password', 'passwd', 'secret', 'key', 'token', 'credential',
                'ssn', 'social_security', 'credit_card', 'card_number',
                'bank_account', 'routing_number', 'pin', 'pii',
                'keystroke', 'keylog', 'screenshot', 'screen_capture',
                'browser_history', 'cookies', 'autofill', 'bookmarks',
                'contacts', 'calendar', 'messages', 'emails',
                'location', 'gps', 'coordinates', 'address',
                'biometric', 'fingerprint', 'face_id', 'touch_id'
            ]

            # Cloud service domains
            cloud_domains = [
                'amazonaws.com', 's3.amazonaws.com', 'cloudwatch',
                'icloud.com', 'googleapis.com', 'azure.com',
                'dropbox.com', 'onedrive.com', 'box.com'
            ]

            # Get network connections to cloud services
            result = subprocess.run(
                ['lsof', '-i', '-P', '-n'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                cloud_connected_processes = {}

                # First pass: identify processes connected to cloud services
                for line in result.stdout.split('\n'):
                    if not line.strip():
                        continue

                    parts = line.split()
                    if len(parts) >= 9:
                        try:
                            proc_name = parts[0]
                            pid = parts[1]
                            conn_info = parts[8] if len(parts) > 8 else ''

                            # Check if connection is to a cloud service
                            for domain in cloud_domains:
                                if domain in conn_info.lower():
                                    if proc_name not in cloud_connected_processes:
                                        cloud_connected_processes[proc_name] = {
                                            'pid': pid,
                                            'connections': []
                                        }
                                    cloud_connected_processes[proc_name]['connections'].append({
                                        'domain': domain,
                                        'connection': conn_info
                                    })
                        except (ValueError, IndexError):
                            continue

                # Second pass: check what files these processes have open
                for proc_name, proc_info in cloud_connected_processes.items():
                    pid = proc_info['pid']

                    # Skip system processes
                    proc_lower = proc_name.lower()
                    if any(x in proc_lower for x in ['com.apple.', 'system', 'kernel']):
                        continue

                    try:
                        # Get files opened by this process
                        file_result = subprocess.run(
                            ['lsof', '-p', pid],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )

                        if file_result.returncode == 0:
                            sensitive_files_found = []

                            for file_line in file_result.stdout.split('\n'):
                                if not file_line.strip() or 'COMMAND' in file_line:
                                    continue

                                file_lower = file_line.lower()

                                # Check if file matches sensitive patterns
                                for pattern in sensitive_data_patterns:
                                    if pattern in file_lower:
                                        # Extract file path
                                        file_parts = file_line.split()
                                        if len(file_parts) >= 9:
                                            file_path = file_parts[-1]

                                            # Check if it's a regular file (not a device/socket)
                                            if 'REG' in file_line or 'txt' in file_path.lower() or 'log' in file_path.lower():
                                                sensitive_files_found.append({
                                                    'file': file_path,
                                                    'pattern': pattern,
                                                    'file_info': file_line
                                                })

                                            finding = {
                                                'process': proc_name,
                                                'pid': pid,
                                                'file': file_path,
                                                'sensitive_data_type': pattern,
                                                'cloud_service': proc_info['connections'][0]['domain'] if proc_info['connections'] else 'unknown',
                                                'connection': proc_info['connections'][0]['connection'] if proc_info['connections'] else 'unknown',
                                                'severity': 'critical',
                                                'description': f'Process {proc_name} accessing {pattern} data while connected to cloud service',
                                                'detected_at': datetime.now().isoformat()
                                            }
                                            self.findings['data_exfiltration'].append(finding)
                                            self._log(f"🚨 DATA EXFILTRATION: {proc_name} accessing {pattern} → {proc_info['connections'][0]['domain'] if proc_info['connections'] else 'cloud'}", "CRITICAL")
                                            break
                    except subprocess.TimeoutExpired:
                        continue
                    except Exception:
                        continue

            # Monitor iCloud sync for sensitive files
            icloud_path = Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs'
            if icloud_path.exists():
                sensitive_extensions = ['.keylog', '.log', '.db', '.sqlite', '.pcap', '.txt']
                sensitive_file_patterns = ['password', 'secret', 'key', 'credential', 'keylog', 'screenshot']

                try:
                    for file_path in icloud_path.rglob('*'):
                        if file_path.is_file():
                            file_name_lower = file_path.name.lower()

                            # Check file extension
                            if any(file_path.suffix.lower() == ext for ext in sensitive_extensions):
                                # Additional check: skip system files
                                if 'com.apple' not in str(file_path) and 'Library' not in str(file_path).split('/')[-3:]:
                                    finding = {
                                        'file': str(file_path),
                                        'location': 'iCloud Drive',
                                        'file_type': file_path.suffix,
                                        'severity': 'high',
                                        'description': f'Sensitive file type syncing to iCloud: {file_path.name}',
                                        'detected_at': datetime.now().isoformat()
                                    }
                                    self.findings['data_exfiltration'].append(finding)
                                    self._log(f"⚠️ Sensitive file in iCloud: {file_path.name}", "ALERT")

                            # Check file name patterns
                            for pattern in sensitive_file_patterns:
                                if pattern in file_name_lower:
                                    finding = {
                                        'file': str(file_path),
                                        'location': 'iCloud Drive',
                                        'pattern': pattern,
                                        'severity': 'critical',
                                        'description': f'File with sensitive pattern "{pattern}" syncing to iCloud: {file_path.name}',
                                        'detected_at': datetime.now().isoformat()
                                    }
                                    self.findings['data_exfiltration'].append(finding)
                                    self._log(f"🚨 CRITICAL: Sensitive file pattern in iCloud: {file_path.name}", "CRITICAL")
                                    break
                except (PermissionError, OSError) as e:
                    self._log(f"Permission denied scanning iCloud: {e}", "WARNING")
                except Exception as e:
                    self._log(f"Error scanning iCloud: {e}", "ERROR")

            # Check for suspicious file access patterns
            try:
                result = subprocess.run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    suspicious_processes = []

                    for line in result.stdout.split('\n'):
                        line_lower = line.lower()
                        parts = line.split()

                        if len(parts) >= 11:
                            cmd_line = ' '.join(parts[10:]).lower()

                            # Check for processes that might be collecting data
                            data_collection_keywords = [
                                'curl', 'wget', 'scp', 'rsync', 'sftp',
                                'upload', 'sync', 'backup', 'export',
                                'keylog', 'capture', 'record', 'monitor'
                            ]

                            for keyword in data_collection_keywords:
                                if keyword in cmd_line:
                                    # Check if it's uploading to cloud
                                    for domain in cloud_domains:
                                        if domain in cmd_line:
                                            proc_name = ' '.join(parts[10:])[:60]
                                            finding = {
                                                'process': proc_name,
                                                'pid': parts[1] if len(parts) > 1 else 'unknown',
                                                'keyword': keyword,
                                                'cloud_service': domain,
                                                'severity': 'high',
                                                'description': f'Process using {keyword} to transfer data to {domain}',
                                                'detected_at': datetime.now().isoformat()
                                            }
                                            self.findings['data_exfiltration'].append(finding)
                                            self._log(f"⚠️ Data collection detected: {keyword} → {domain}", "ALERT")
                                            break
            except Exception as e:
                self._log(f"Error checking process patterns: {e}", "ERROR")

        except subprocess.TimeoutExpired:
            self._log("Data exfiltration scan timed out", "WARNING")
        except Exception as e:
            self._log(f"Error scanning data exfiltration: {e}", "ERROR")

    def _determine_severity(self, category: str) -> str:
        """Determine severity based on category."""
        severity_map = {
            'keyloggers': 'critical',
            'screen_capture': 'high',
            'remote_access': 'high',
            'monitoring_software': 'high',
            'network_monitoring': 'medium',
            'system_modifiers': 'critical',
            'browser_tracking': 'low',
            'audio_surveillance': 'high',
            'bluetooth_monitoring': 'medium',
            'wifi_monitoring': 'high',
            'dns_hijacking': 'high',
            'arp_spoofing': 'critical',
            'screen_sharing_active': 'critical',
            'cloud_surveillance': 'high',
            'data_exfiltration': 'critical'
        }
        return severity_map.get(category, 'medium')

    def _send_macos_notification(self, title: str, message: str, sound: str = "Basso"):
        """Send macOS notification using osascript."""
        try:
            # Clean and escape message for AppleScript
            # Remove emojis and special chars that might break AppleScript
            clean_title = title.replace('🚨', '').replace('⚠️', '').strip()
            clean_message = message.replace('🚨', '').replace('⚠️', '').strip()

            # Escape quotes
            title_escaped = clean_title.replace('"', '\\"')
            message_escaped = clean_message.replace('"', '\\"')

            # Use simple notification (sound parameter has syntax issues in some macOS versions)
            script = f'display notification "{message_escaped}" with title "{title_escaped}"'

            result = subprocess.run(
                ['osascript', '-e', script],
                timeout=5,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                self._log(f"Notification sent: {title}", "INFO")
            else:
                self._log(f"Notification failed: {result.stderr}", "WARNING")

        except subprocess.TimeoutExpired:
            self._log("Notification timed out", "WARNING")
        except Exception as e:
            self._log(f"Error sending notification: {e}", "ERROR")

    def _is_surveillance_detected(self) -> bool:
        """Determine if surveillance is detected (yes/no) - filters out false positives intelligently."""
        # Known false positive patterns (legitimate macOS/system files)
        FALSE_POSITIVE_PATTERNS = [
            '/System/Library/',  # macOS system files
            '/Applications/',  # Installed applications (but check executables separately)
            'Extensions/',  # Browser extensions
            'homebrew/include',  # Development headers
            'homebrew/share/man',  # Manual pages
            'homebrew/Cellar',  # Homebrew packages
            'homebrew/lib/node_modules',  # Node modules
            '/opt/homebrew/',  # Homebrew opt directory
            '.h',  # Header files
            '.hpp',  # C++ header files
            'include/',  # Include directories
            'share/man/',  # Manual pages
            'ThirdPartyNotices',  # License files
            'COPYING-',  # License files
            'thirdpartynotices',  # License files
            '3rdpartylicenses',  # License files
            'XrmParseCommand',  # X11 man pages
            'recordproto',  # X11 protocol files
            'mitmisc',  # X11 MIT extension (not MITM attack)
            'parsecd',  # Apple's Parsec framework (not Parsec remote access)
            'com.apple.',  # Apple system processes
            '_driverkit',  # System driver processes
            'DriverExtensions',  # System drivers
            'SafariLinkExtension',  # Safari extension
            'Visual Studio Code',  # VS Code files (legitimate)
            'generator-code',  # VS Code generator (legitimate)
            'xorgproto',  # X11 protocol files (legitimate)
            '.sqlite',  # Database files (not surveillance)
            '.sqlite-shm',  # SQLite shared memory
            '.sqlite-wal',  # SQLite write-ahead log
            'wireshark',  # Wireshark - legitimate network analysis tool
            'Wireshark',  # Wireshark (capitalized)
        ]

        # Helper function for case-insensitive pattern matching
        def is_false_positive(file_path: str) -> bool:
            """Check if file path matches any false positive pattern."""
            file_path_lower = file_path.lower()
            return any(pattern.lower() in file_path_lower for pattern in FALSE_POSITIVE_PATTERNS)

        def is_executable_file(file_path: str) -> bool:
            """Check if file is likely an executable (not a text/doc file)."""
            file_path_lower = file_path.lower()
            # Exclude text/document files
            text_extensions = ['.txt', '.md', '.log', '.json', '.xml', '.plist', '.css', '.js', '.svg', '.html', '.sqlite', '.db']
            if any(file_path_lower.endswith(ext) for ext in text_extensions):
                # But plist files in LaunchDaemons/LaunchAgents are important
                if '.plist' in file_path_lower and ('LaunchDaemons' in file_path_lower or 'LaunchAgents' in file_path_lower):
                    return True
                return False
            # Include executables
            executable_indicators = ['.app', '/bin/', '/sbin/', '.dmg', '.pkg', 'exec', 'binary']
            return any(indicator in file_path_lower for indicator in executable_indicators)

        def is_user_installed_location(file_path: str) -> bool:
            """Check if file is in a user-installed location (not system)."""
            user_locations = [
                '/Users/',  # User home directory
                '/usr/local/',  # User-installed software
                '/opt/',  # Optional software
                '/Library/LaunchAgents',  # User launch agents
                '/Library/LaunchDaemons',  # User launch daemons (but be careful)
            ]
            return any(loc in file_path for loc in user_locations) and '/System/' not in file_path

        # Count only real surveillance indicators (excluding false positives)
        real_surveillance_count = 0
        high_confidence_threats = []

        # Keyloggers are ALWAYS high-confidence threats (if not false positive)
        keyloggers = self.findings.get('keyloggers', [])
        for item in keyloggers:
            file_path = item.get('file', '')
            if not is_false_positive(file_path):
                real_surveillance_count += 1
                high_confidence_threats.append(('keylogger', file_path))

        # Screen capture tools - only count if executable and in user space
        screen_capture = self.findings.get('screen_capture', [])
        for item in screen_capture:
            file_path = item.get('file', '')
            if not is_false_positive(file_path):
                # Only count if it's an actual executable, not just a config file
                if is_executable_file(file_path) or is_user_installed_location(file_path):
                    real_surveillance_count += 1
                    high_confidence_threats.append(('screen_capture', file_path))

        # Remote access tools - high confidence if executable and user-installed
        remote_access = self.findings.get('remote_access', [])
        for item in remote_access:
            file_path = item.get('file', '')
            if not is_false_positive(file_path):
                # Only count executables or user-installed locations
                if is_executable_file(file_path) or (is_user_installed_location(file_path) and not file_path.endswith('.txt')):
                    real_surveillance_count += 1
                    high_confidence_threats.append(('remote_access', file_path))

        # Monitoring software - high confidence
        monitoring = self.findings.get('monitoring_software', [])
        for item in monitoring:
            file_path = item.get('file', '')
            if not is_false_positive(file_path):
                if is_executable_file(file_path) or is_user_installed_location(file_path):
                    real_surveillance_count += 1
                    high_confidence_threats.append(('monitoring_software', file_path))

        # Network monitoring - only count actual executables/plists, not headers
        network_monitoring = self.findings.get('network_monitoring', [])
        for item in network_monitoring:
            file_path = item.get('file', '')
            if not is_false_positive(file_path):
                # Must be executable or plist in LaunchDaemons/LaunchAgents
                if is_executable_file(file_path) or ('LaunchDaemons' in file_path or 'LaunchAgents' in file_path):
                    # Additional check: if it's a plist, it must be in user space
                    if '.plist' in file_path.lower():
                        if is_user_installed_location(file_path):
                            real_surveillance_count += 1
                            high_confidence_threats.append(('network_monitoring', file_path))
                    else:
                        real_surveillance_count += 1
                        high_confidence_threats.append(('network_monitoring', file_path))

        # Suspicious processes - high confidence (they're running!)
        suspicious_processes = self.findings.get('suspicious_processes', [])
        for proc in suspicious_processes:
            proc_path = proc.get('process', '')
            user = proc.get('user', '')
            # Skip system processes
            if not is_false_positive(proc_path) and user != '_driverkit':
                real_surveillance_count += 1
                high_confidence_threats.append(('suspicious_process', proc_path))

        # Launch agents - only count user-installed, non-system agents
        launch_agents = self.findings.get('launch_agents', [])
        for agent in launch_agents:
            plist_file = agent.get('plist_file', '')
            # Skip system launch agents
            if '/System/Library/' not in plist_file:
                if not is_false_positive(plist_file):
                    # Only count if it's in user space
                    if is_user_installed_location(plist_file):
                        real_surveillance_count += 1
                        high_confidence_threats.append(('launch_agent', plist_file))

        # Audio surveillance - high confidence (all findings count)
        audio_surveillance = self.findings.get('audio_surveillance', [])
        for item in audio_surveillance:
            real_surveillance_count += 1
            client_or_process = item.get('client', item.get('process', 'unknown'))
            high_confidence_threats.append(('audio_surveillance', client_or_process))

        # Screen sharing active - CRITICAL (immediate threat)
        screen_sharing = self.findings.get('screen_sharing_active', [])
        for item in screen_sharing:
            real_surveillance_count += 1
            proc_name = item.get('process', 'unknown')
            high_confidence_threats.append(('screen_sharing', proc_name))

        # DNS hijacking - high confidence (all findings count)
        dns_hijacking = self.findings.get('dns_hijacking', [])
        for item in dns_hijacking:
            real_surveillance_count += 1
            dns_servers = str(item.get('dns_servers', []))
            high_confidence_threats.append(('dns_hijacking', dns_servers))

        # ARP spoofing - CRITICAL (immediate threat)
        arp_spoofing = self.findings.get('arp_spoofing', [])
        for item in arp_spoofing:
            real_surveillance_count += 1
            ip = item.get('ip', 'unknown')
            high_confidence_threats.append(('arp_spoofing', ip))

        # WiFi monitoring - count executable processes only
        wifi_monitoring = self.findings.get('wifi_monitoring', [])
        for item in wifi_monitoring:
            proc_name = item.get('process', '')
            if proc_name and not is_false_positive(proc_name):
                real_surveillance_count += 1
                high_confidence_threats.append(('wifi_monitoring', proc_name))

        # Cloud surveillance - high confidence (all findings count)
        cloud_surveillance = self.findings.get('cloud_surveillance', [])
        for item in cloud_surveillance:
            real_surveillance_count += 1
            proc_or_file = item.get('process', item.get('credential_file', item.get('file', 'unknown')))
            high_confidence_threats.append(('cloud_surveillance', proc_or_file))

        # Data exfiltration - CRITICAL (all findings count)
        data_exfiltration = self.findings.get('data_exfiltration', [])
        for item in data_exfiltration:
            real_surveillance_count += 1
            proc_or_file = item.get('process', item.get('file', 'unknown'))
            high_confidence_threats.append(('data_exfiltration', proc_or_file))

        # Log high-confidence threats for debugging
        if high_confidence_threats and self.verbose:
            self._log(f"High-confidence threats detected: {len(high_confidence_threats)}", "ALERT")
            for threat_type, path in high_confidence_threats[:5]:  # Show first 5
                self._log(f"  - {threat_type}: {path[:80]}", "ALERT")

        return real_surveillance_count > 0

    def _calculate_summary(self):
        """Calculate summary statistics."""
        total = 0
        critical = 0
        high = 0
        medium = 0
        low = 0

        for category in ['keyloggers', 'screen_capture', 'remote_access',
                         'monitoring_software', 'network_monitoring',
                         'suspicious_files', 'suspicious_processes',
                         'suspicious_network_connections', 'launch_agents',
                         'browser_extensions', 'system_modifications', 'hidden_files',
                         'audio_surveillance', 'bluetooth_monitoring', 'wifi_monitoring',
                         'dns_hijacking', 'arp_spoofing', 'screen_sharing_active',
                         'cloud_surveillance', 'data_exfiltration']:
            for finding in self.findings[category]:
                total += 1
                severity = finding.get('severity', 'medium')
                if severity == 'critical':
                    critical += 1
                elif severity == 'high':
                    high += 1
                elif severity == 'medium':
                    medium += 1
                else:
                    low += 1

        self.findings['summary'] = {
            'total_findings': total,
            'critical': critical,
            'high': high,
            'medium': medium,
            'low': low,
            'files_scanned': self.scanned_files
        }

    def _save_results(self):
        """Save scan results to file."""
        # Try multiple fallback locations
        save_locations = [
            Path(self.output_file),  # Original location
            Path.cwd() / self.output_file.name,  # Current directory
            Path.cwd() / 'results' / self.output_file.name,  # Results subdirectory
            Path.cwd() / 'logs' / self.output_file.name,  # Logs subdirectory
        ]

        for output_path in save_locations:
            try:
                # Ensure parent directory exists
                output_path.parent.mkdir(parents=True, exist_ok=True)

                # Check if we can write to parent directory
                if not os.access(output_path.parent, os.W_OK):
                    continue

                # Write results
                with open(output_path, 'w') as f:
                    json.dump(self.findings, f, indent=2)

                self._log(f"Results saved to {output_path.absolute()}")
                self.output_file = output_path  # Update to actual saved location
                return True
            except (PermissionError, OSError) as e:
                continue
            except Exception as e:
                self._log(f"Error saving to {output_path}: {e}", "WARNING")
                continue

        # If all locations failed, try to write to stdout as JSON
        self._log("Could not save to file. Outputting to stdout...", "WARNING")
        try:
            print("\n=== SCAN RESULTS (JSON) ===")
            print(json.dumps(self.findings, indent=2))
            print("=== END SCAN RESULTS ===")
            return True
        except Exception as e:
            self._log(f"Error outputting results: {e}", "ERROR")
            return False

    def print_report(self):
        """Print a human-readable report with simple yes/no answer."""
        # Determine if surveillance is detected
        surveillance_detected = self._is_surveillance_detected()

        print("\n" + "="*80)
        print("SURVEILLANCE DETECTION RESULT")
        print("="*80)
        print(f"Scan Date: {self.findings['timestamp']}")
        print(f"System: {self.findings['system_info']['platform']}")
        print(f"Hostname: {self.findings['system_info']['hostname']}")
        print("\n" + "-"*80)
        print("RESULT")
        print("-"*80)

        if surveillance_detected:
            print("🚨 SURVEILLANCE DETECTED: YES")
            print("\n⚠️  Your system shows evidence of surveillance or monitoring software.")
            summary = self.findings['summary']
            print(f"\nFindings: {summary['critical']} critical, {summary['high']} high-severity indicators")
        else:
            print("✅ SURVEILLANCE DETECTED: NO")
            print("\n✓ No active surveillance or monitoring software detected.")
            print("  (Some system files may match patterns but are not surveillance tools)")

        print("\n" + "="*80)
        print(f"Detailed report saved to: {self.output_file}")
        print("="*80 + "\n")


# ╭─────────────────────────────── Main Entry ───────────────────────────────╮

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Surveillance Detection Framework - Scan for monitoring/surveillance software'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output file path (default: ~/Documents/CleanHouse/surveillance_scan.json)'
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Quiet mode (less verbose output)'
    )
    parser.add_argument(
        '--report-only',
        action='store_true',
        help='Only print report, do not run scan (requires existing scan file)'
    )

    args = parser.parse_args()

    if args.report_only:
        # Load and print existing report
        output_file = args.output or Path.home() / 'Documents' / 'CleanHouse' / 'surveillance_scan.json'
        if not output_file.exists():
            print(f"Error: Scan file not found: {output_file}")
            print("Run a scan first without --report-only")
            sys.exit(1)

        with open(output_file, 'r') as f:
            findings = json.load(f)

        detector = SurveillanceDetector(output_file=output_file, verbose=False)
        detector.findings = findings
        detector.print_report()
    else:
        # Run scan
        detector = SurveillanceDetector(
            output_file=args.output,
            verbose=not args.quiet
        )
        findings = detector.scan_all()

        # Determine surveillance status
        surveillance_detected = detector._is_surveillance_detected()

        # Print simple yes/no report
        detector.print_report()

        # Exit with error code if surveillance detected
        if surveillance_detected:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    main()
