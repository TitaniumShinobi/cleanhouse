#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - agent_movement_monitor.py
#  Monitor agent background movements between coding platforms
#  Devon • 2026-01-03
# ──────────────────────────────────────────────────────────────────────────────

"""
Agent Movement Monitor

Monitors background agent activity between different coding platforms:
- VS Code
- Cursor
- Codex
- Gemini Antigravity

Tracks:
- Process activity
- File access patterns
- Network connections
- Shared resources
- Configuration changes
"""

import os
import sys
import json
import re
import subprocess
import platform
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple
from collections import defaultdict, deque
import threading
import signal

# ╭─────────────────────────────── Configuration ────────────────────────────╮

# Coding platforms to monitor
CODING_PLATFORMS = {
    'vscode': {
        'process_names': ['code', 'Code', 'Visual Studio Code', 'electron'],
        'app_paths': [
            '/Applications/Visual Studio Code.app',
            '~/Applications/Visual Studio Code.app',
            '/Applications/Visual Studio Code - Insiders.app',
        ],
        'config_paths': [
            '~/Library/Application Support/Code',
            '~/.vscode',
        ],
        'extensions_path': '~/Library/Application Support/Code/User/extensions',
        'workspace_patterns': ['.vscode', 'settings.json', 'launch.json'],
    },
    'cursor': {
        'process_names': ['Cursor', 'cursor', 'Electron'],
        'app_paths': [
            '/Applications/Cursor.app',
            '~/Applications/Cursor.app',
        ],
        'config_paths': [
            '~/Library/Application Support/Cursor',
            '~/.cursor',
        ],
        'extensions_path': '~/Library/Application Support/Cursor/User/extensions',
        'workspace_patterns': ['.cursor', 'cursor.json'],
    },
    'codex': {
        'process_names': ['codex', 'Codex', 'codex-agent'],
        'app_paths': [
            '/Applications/Codex.app',
            '~/Applications/Codex.app',
        ],
        'config_paths': [
            '~/Library/Application Support/Codex',
            '~/.codex',
        ],
        'extensions_path': None,
        'workspace_patterns': ['.codex', 'codex.json'],
    },
    'gemini_antigravity': {
        'process_names': ['gemini', 'Gemini', 'antigravity', 'Antigravity', 'gemini-antigravity'],
        'app_paths': [
            '/Applications/Gemini Antigravity.app',
            '~/Applications/Gemini Antigravity.app',
            '/Applications/Gemini.app',
        ],
        'config_paths': [
            '~/Library/Application Support/Gemini',
            '~/Library/Application Support/Antigravity',
            '~/.gemini',
            '~/.antigravity',
        ],
        'extensions_path': None,
        'workspace_patterns': ['.gemini', '.antigravity', 'gemini.json'],
    },
}

# Agent-related patterns to detect
AGENT_PATTERNS = {
    'process_patterns': [
        r'agent', r'ai.*assistant', r'code.*completion', r'autocomplete',
        r'copilot', r'ghostwriter', r'code.*suggest', r'intellisense',
        r'language.*server', r'lsp', r'background.*service',
    ],
    'file_patterns': [
        r'\.agent', r'agent\.json', r'\.ai', r'background.*log',
        r'agent.*cache', r'completion.*cache', r'suggestion.*cache',
    ],
    'network_patterns': [
        r'api.*openai', r'api.*anthropic', r'api.*google', r'completion.*api',
        r'suggestion.*api', r'agent.*api', r'codex.*api',
        r'cursor.*api', r'cursor\.ai', r'cursor\.com',  # Cursor AI endpoints
        r'claude', r'gpt', r'chatgpt',  # AI service names
    ],
}

# Monitoring intervals (seconds)
MONITOR_INTERVALS = {
    'process_check': 2.0,  # Check processes every 2 seconds
    'file_check': 5.0,     # Check file access every 5 seconds
    'network_check': 3.0,  # Check network every 3 seconds
    'summary_interval': 30.0,  # Print summary every 30 seconds
}

# ╭─────────────────────────────── Core Classes ──────────────────────────────╮

class AgentMovementMonitor:
    """Monitor agent background movements between coding platforms."""

    def __init__(self, output_file: Optional[Path] = None, verbose: bool = True):
        if output_file is None:
            workspace = Path(__file__).parent
            # Save to results directory if it exists, otherwise workspace
            results_dir = workspace / 'results'
            if results_dir.exists():
                self.output_file = results_dir / 'agent_movement_log.json'
            else:
                self.output_file = workspace / 'agent_movement_log.json'
        else:
            self.output_file = Path(output_file).resolve()

        self.verbose = verbose
        self.running = True
        self.monitoring = False

        # Activity tracking
        self.activity_log = {
            'start_time': datetime.now().isoformat(),
            'platform_activity': defaultdict(lambda: {
                'process_detections': [],
                'file_access': [],
                'network_connections': [],
                'active_periods': [],
                'switches': [],
            }),
            'agent_detections': [],
            'cross_platform_activity': [],
            'suspicious_patterns': [],
            'ai_request_events': [],  # Track when AI processes user requests
        }

        # State tracking
        self.previous_processes = set()
        self.active_platforms = set()
        self.file_access_history = deque(maxlen=1000)
        self.network_connections = {}
        self.platform_switches = []

        # Threading
        self.monitor_thread = None
        self.stop_event = threading.Event()

    def _log(self, message: str, level: str = 'INFO'):
        """Log a message."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        if self.verbose:
            print(f"[{timestamp}] [{level}] {message}")

    def _expand_path(self, path: str) -> Path:
        """Expand user path."""
        return Path(path).expanduser()

    def scan_processes(self) -> Dict[str, List[Dict]]:
        """Scan for processes related to coding platforms."""
        platform_processes = defaultdict(list)

        try:
            if platform.system() == 'Darwin':  # macOS
                result = subprocess.run(
                    ['ps', 'aux'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                processes = result.stdout.split('\n')

                for proc_line in processes:
                    if not proc_line.strip():
                        continue

                    proc_lower = proc_line.lower()
                    parts = proc_line.split()
                    if len(parts) < 11:
                        continue

                    proc_name = parts[10] if len(parts) > 10 else 'unknown'
                    pid = parts[1]
                    user = parts[0]
                    cpu = parts[2] if len(parts) > 2 else '0'
                    mem = parts[3] if len(parts) > 3 else '0'

                    # Check each platform
                    for platform_name, platform_info in CODING_PLATFORMS.items():
                        for proc_pattern in platform_info['process_names']:
                            if proc_pattern.lower() in proc_lower:
                                process_info = {
                                    'pid': pid,
                                    'name': proc_name,
                                    'user': user,
                                    'cpu': cpu,
                                    'memory': mem,
                                    'command': ' '.join(parts[10:]) if len(parts) > 10 else proc_name,
                                    'detected_at': datetime.now().isoformat(),
                                }
                                platform_processes[platform_name].append(process_info)

                                # Check for agent patterns in process
                                for pattern in AGENT_PATTERNS['process_patterns']:
                                    if re.search(pattern, proc_lower, re.IGNORECASE):
                                        self._log(f"Agent pattern in {platform_name} process: {proc_name}", "ALERT")
                                        self.activity_log['agent_detections'].append({
                                            'type': 'process_pattern',
                                            'platform': platform_name,
                                            'process': proc_name,
                                            'pattern': pattern,
                                            'timestamp': datetime.now().isoformat(),
                                        })

                    # Check for standalone agent processes
                    for pattern in AGENT_PATTERNS['process_patterns']:
                        if re.search(pattern, proc_lower, re.IGNORECASE):
                            # Check if it's not already associated with a platform
                            is_platform_process = False
                            for platform_info in CODING_PLATFORMS.values():
                                for proc_pattern in platform_info['process_names']:
                                    if proc_pattern.lower() in proc_lower:
                                        is_platform_process = True
                                        break
                                if is_platform_process:
                                    break

                            if not is_platform_process:
                                self._log(f"Standalone agent process detected: {proc_name}", "ALERT")
                                self.activity_log['agent_detections'].append({
                                    'type': 'standalone_agent',
                                    'process': proc_name,
                                    'pid': pid,
                                    'pattern': pattern,
                                    'timestamp': datetime.now().isoformat(),
                                })

        except Exception as e:
            self._log(f"Error scanning processes: {e}", "ERROR")

        return dict(platform_processes)

    def scan_file_access(self) -> Dict[str, List[Dict]]:
        """Scan for file access patterns related to coding platforms."""
        platform_files = defaultdict(list)

        try:
            # Check for recent file modifications in platform config directories
            for platform_name, platform_info in CODING_PLATFORMS.items():
                for config_path_str in platform_info['config_paths']:
                    config_path = self._expand_path(config_path_str)
                    if config_path.exists():
                        try:
                            # Check for recently modified files
                            for item in config_path.rglob('*'):
                                if item.is_file():
                                    try:
                                        mtime = item.stat().st_mtime
                                        # Files modified in last 60 seconds
                                        if time.time() - mtime < 60:
                                            file_info = {
                                                'path': str(item),
                                                'modified': datetime.fromtimestamp(mtime).isoformat(),
                                                'size': item.stat().st_size,
                                                'detected_at': datetime.now().isoformat(),
                                            }
                                            platform_files[platform_name].append(file_info)

                                            # Check for agent patterns
                                            for pattern in AGENT_PATTERNS['file_patterns']:
                                                if re.search(pattern, str(item), re.IGNORECASE):
                                                    self._log(f"Agent file pattern in {platform_name}: {item.name}", "ALERT")
                                                    self.activity_log['agent_detections'].append({
                                                        'type': 'file_pattern',
                                                        'platform': platform_name,
                                                        'file': str(item),
                                                        'pattern': pattern,
                                                        'timestamp': datetime.now().isoformat(),
                                                    })
                                    except (OSError, PermissionError):
                                        continue
                        except (OSError, PermissionError):
                            continue
        except Exception as e:
            self._log(f"Error scanning file access: {e}", "ERROR")

        return dict(platform_files)

    def scan_network_connections(self) -> Dict[str, List[Dict]]:
        """Scan for network connections from coding platforms."""
        platform_connections = defaultdict(list)

        try:
            if platform.system() == 'Darwin':  # macOS
                result = subprocess.run(
                    ['lsof', '-i', '-P', '-n'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                connections = result.stdout.split('\n')

                for conn_line in connections[1:]:  # Skip header
                    if not conn_line.strip():
                        continue

                    parts = conn_line.split()
                    if len(parts) < 9:
                        continue

                    proc_name = parts[0]
                    pid = parts[1]
                    conn_type = parts[4] if len(parts) > 4 else 'unknown'
                    address = parts[8] if len(parts) > 8 else 'unknown'

                    proc_lower = proc_name.lower()

                    # Check each platform
                    for platform_name, platform_info in CODING_PLATFORMS.items():
                        for proc_pattern in platform_info['process_names']:
                            if proc_pattern.lower() in proc_lower:
                                conn_info = {
                                    'pid': pid,
                                    'process': proc_name,
                                    'type': conn_type,
                                    'address': address,
                                    'detected_at': datetime.now().isoformat(),
                                }
                                platform_connections[platform_name].append(conn_info)

                                # Check for agent API patterns
                                for pattern in AGENT_PATTERNS['network_patterns']:
                                    if re.search(pattern, address, re.IGNORECASE):
                                        self._log(f"Agent API connection from {platform_name}: {address}", "ALERT")
                                        detection = {
                                            'type': 'network_pattern',
                                            'platform': platform_name,
                                            'address': address,
                                            'pattern': pattern,
                                            'timestamp': datetime.now().isoformat(),
                                        }
                                        self.activity_log['agent_detections'].append(detection)

                                        # Track AI request processing events
                                        if any(x in address.lower() for x in ['cursor', 'claude', 'gpt', 'chatgpt', 'openai', 'anthropic']):
                                            self.activity_log['ai_request_events'].append({
                                                'event': 'ai_request_processing',
                                                'platform': platform_name,
                                                'endpoint': address,
                                                'timestamp': datetime.now().isoformat(),
                                                'description': f'AI assistant processing request from {platform_name}',
                                            })
                                            self._log(f"🤖 AI processing user request via {platform_name} → {address}", "INFO")
        except Exception as e:
            self._log(f"Error scanning network: {e}", "ERROR")

        return dict(platform_connections)

    def detect_platform_switches(self, current_platforms: Set[str]):
        """Detect when agent activity switches between platforms."""
        previous_platforms = self.active_platforms.copy()
        self.active_platforms = current_platforms

        # Detect switches
        if previous_platforms and current_platforms:
            switched_from = previous_platforms - current_platforms
            switched_to = current_platforms - previous_platforms

            if switched_from or switched_to:
                switch_info = {
                    'from': list(switched_from),
                    'to': list(switched_to),
                    'timestamp': datetime.now().isoformat(),
                    'duration': None,  # Could calculate if we track start times
                }
                self.platform_switches.append(switch_info)
                self.activity_log['cross_platform_activity'].append(switch_info)

                if switched_from and switched_to:
                    self._log(f"Agent switch detected: {list(switched_from)} → {list(switched_to)}", "ALERT")
                elif switched_to:
                    self._log(f"New platform activated: {list(switched_to)}", "INFO")
                elif switched_from:
                    self._log(f"Platform deactivated: {list(switched_from)}", "INFO")

    def monitor_loop(self):
        """Main monitoring loop."""
        last_process_check = 0
        last_file_check = 0
        last_network_check = 0
        last_summary = 0

        self._log("Starting agent movement monitoring...", "INFO")

        while not self.stop_event.is_set():
            current_time = time.time()

            # Process monitoring
            if current_time - last_process_check >= MONITOR_INTERVALS['process_check']:
                processes = self.scan_processes()
                current_platforms = set(processes.keys())

                # Update activity log
                for platform_name, proc_list in processes.items():
                    self.activity_log['platform_activity'][platform_name]['process_detections'].extend(proc_list)
                    if proc_list:
                        # Track active period
                        now = datetime.now().isoformat()
                        activity = self.activity_log['platform_activity'][platform_name]
                        if not activity['active_periods'] or activity['active_periods'][-1].get('end'):
                            activity['active_periods'].append({'start': now})
                        elif activity['active_periods']:
                            activity['active_periods'][-1]['end'] = now

                self.detect_platform_switches(current_platforms)
                last_process_check = current_time

            # File access monitoring
            if current_time - last_file_check >= MONITOR_INTERVALS['file_check']:
                files = self.scan_file_access()
                for platform_name, file_list in files.items():
                    self.activity_log['platform_activity'][platform_name]['file_access'].extend(file_list)
                last_file_check = current_time

            # Network monitoring
            if current_time - last_network_check >= MONITOR_INTERVALS['network_check']:
                connections = self.scan_network_connections()
                for platform_name, conn_list in connections.items():
                    self.activity_log['platform_activity'][platform_name]['network_connections'].extend(conn_list)
                last_network_check = current_time

            # Periodic summary
            if current_time - last_summary >= MONITOR_INTERVALS['summary_interval']:
                self.print_summary()
                last_summary = current_time

            time.sleep(0.5)  # Small sleep to prevent CPU spinning

    def print_summary(self):
        """Print current monitoring summary."""
        print("\n" + "="*80)
        print("AGENT MOVEMENT MONITORING SUMMARY")
        print("="*80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Active platforms: {', '.join(self.active_platforms) if self.active_platforms else 'None'}")
        print(f"Platform switches detected: {len(self.platform_switches)}")
        print(f"Agent detections: {len(self.activity_log['agent_detections'])}")
        print()

        # Platform activity
        for platform_name, activity in self.activity_log['platform_activity'].items():
            if activity['process_detections'] or activity['file_access'] or activity['network_connections']:
                print(f"{platform_name.upper()}:")
                print(f"  Processes: {len(activity['process_detections'])}")
                print(f"  File access: {len(activity['file_access'])}")
                print(f"  Network connections: {len(activity['network_connections'])}")
                if activity['active_periods']:
                    active_count = sum(1 for p in activity['active_periods'] if not p.get('end'))
                    print(f"  Active periods: {len(activity['active_periods'])} (currently active: {active_count})")
                print()

        # Recent switches
        if self.platform_switches:
            print("Recent platform switches:")
            for switch in self.platform_switches[-5:]:  # Last 5
                print(f"  {switch['timestamp']}: {switch['from']} → {switch['to']}")
            print()

        # Recent agent detections
        if self.activity_log['agent_detections']:
            print("Recent agent detections:")
            for detection in self.activity_log['agent_detections'][-5:]:  # Last 5
                print(f"  {detection['timestamp']}: {detection['type']} - {detection.get('platform', 'N/A')}")
            print()

        print("="*80 + "\n")

    def start_monitoring(self):
        """Start monitoring in background thread."""
        if self.monitoring:
            self._log("Monitoring already running", "WARNING")
            return

        self.monitoring = True
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()
        self._log("Monitoring started", "INFO")

    def stop_monitoring(self):
        """Stop monitoring."""
        self.monitoring = False
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        self._log("Monitoring stopped", "INFO")

    def save_results(self):
        """Save monitoring results to file."""
        self.activity_log['end_time'] = datetime.now().isoformat()
        self.activity_log['total_switches'] = len(self.platform_switches)
        self.activity_log['total_agent_detections'] = len(self.activity_log['agent_detections'])

        try:
            with open(self.output_file, 'w') as f:
                json.dump(self.activity_log, f, indent=2)
            self._log(f"Results saved to {self.output_file}", "INFO")
        except Exception as e:
            self._log(f"Error saving results: {e}", "ERROR")

# ╭─────────────────────────────── Main Entry ───────────────────────────────╮

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Monitor agent background movements between coding platforms'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output file path (default: agent_movement_log.json)'
    )
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Quiet mode (less verbose output)'
    )
    parser.add_argument(
        '-d', '--duration',
        type=int,
        help='Monitor duration in seconds (default: run until interrupted)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run single scan and exit (no continuous monitoring)'
    )

    args = parser.parse_args()

    monitor = AgentMovementMonitor(
        output_file=args.output,
        verbose=not args.quiet
    )

    def signal_handler(sig, frame):
        """Handle interrupt signal."""
        print("\nStopping monitor...")
        monitor.stop_monitoring()
        monitor.save_results()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.once:
        # Single scan mode
        print("Running single scan...")
        processes = monitor.scan_processes()
        files = monitor.scan_file_access()
        connections = monitor.scan_network_connections()

        print("\n=== SCAN RESULTS ===")
        print(f"Active platforms: {', '.join(processes.keys()) if processes else 'None'}")
        print(f"Platforms with file activity: {', '.join(files.keys()) if files else 'None'}")
        print(f"Platforms with network activity: {', '.join(connections.keys()) if connections else 'None'}")
        print(f"Agent detections: {len(monitor.activity_log['agent_detections'])}")

        monitor.save_results()
    else:
        # Continuous monitoring mode
        monitor.start_monitoring()

        try:
            if args.duration:
                time.sleep(args.duration)
                monitor.stop_monitoring()
            else:
                # Run until interrupted
                while monitor.monitoring:
                    time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            monitor.stop_monitoring()
            monitor.save_results()
            print("\nMonitoring complete. Results saved.")

if __name__ == '__main__':
    main()
