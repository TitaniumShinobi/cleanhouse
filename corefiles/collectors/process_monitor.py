#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - process_monitor.py
#  Real-time process monitor with platform and agent detection
#  Devon • 2026-01-03
# ──────────────────────────────────────────────────────────────────────────────

"""
Process Monitor

Real-time process monitoring with:
- Process list (like Activity Monitor)
- Platform associations (VS Code, Cursor, etc.)
- Agent pattern detection
- CPU and Memory usage
- Auto-refreshing display
"""

import os
import sys
import subprocess
import platform
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import re

# Coding platforms to identify
CODING_PLATFORMS = {
    'VS Code': {
        'patterns': ['code', 'Code', 'Visual Studio Code', 'electron'],
        'color': '\033[94m',  # Blue
    },
    'Cursor': {
        'patterns': ['Cursor', 'cursor'],
        'color': '\033[92m',  # Green
    },
    'Codex': {
        'patterns': ['codex', 'Codex'],
        'color': '\033[93m',  # Yellow
    },
    'Gemini Antigravity': {
        'patterns': ['Antigravity', 'antigravity', 'gemini'],
        'color': '\033[95m',  # Magenta
    },
}

# Agent patterns
AGENT_PATTERNS = [
    r'agent', r'ai.*assistant', r'code.*completion', r'autocomplete',
    r'copilot', r'ghostwriter', r'code.*suggest', r'intellisense',
    r'language.*server', r'lsp', r'background.*service',
]

# Colors
RESET = '\033[0m'
BOLD = '\033[1m'
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'

class ProcessMonitor:
    """Real-time process monitor with platform and agent detection."""

    def __init__(self, refresh_interval: float = 2.0, show_all: bool = False):
        self.refresh_interval = refresh_interval
        self.show_all = show_all
        self.running = True

    def clear_screen(self):
        """Clear terminal screen."""
        os.system('clear' if os.name != 'nt' else 'cls')

    def get_processes(self) -> List[Dict]:
        """Get list of all processes."""
        processes = []

        try:
            if platform.system() == 'Darwin':  # macOS
                result = subprocess.run(
                    [
                        'ps',
                        'axww',
                        '-o',
                        'user=,pid=,ppid=,%cpu=,%mem=,vsz=,rss=,tt=,stat=,lstart=,time=,command=',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                lines = result.stdout.split('\n')

                for line in lines:
                    if not line.strip():
                        continue

                    parts = line.split(maxsplit=15)
                    if len(parts) < 16:
                        continue

                    try:
                        start_time = ' '.join(parts[9:14])
                        command = parts[15] if len(parts) > 15 else ''
                        process = {
                            'user': parts[0],
                            'pid': parts[1],
                            'ppid': parts[2],
                            'cpu': float(parts[3]),
                            'mem': float(parts[4]),
                            'vsz': parts[5],
                            'rss': parts[6],
                            'tt': parts[7],
                            'stat': parts[8],
                            'start': start_time,
                            'start_time': start_time,
                            'time': parts[14],
                            'command': command,
                            'args': command,
                            'source_command': command,
                        }
                        processes.append(process)
                    except (ValueError, IndexError):
                        continue

        except Exception as e:
            print(f"Error getting processes: {e}")

        return processes

    def identify_platform(self, command: str) -> Optional[Tuple[str, str]]:
        """Identify which platform a process belongs to."""
        command_lower = command.lower()

        for platform_name, platform_info in CODING_PLATFORMS.items():
            for pattern in platform_info['patterns']:
                if pattern.lower() in command_lower:
                    return (platform_name, platform_info['color'])

        return None

    def identify_platform_detail(self, command: str) -> Optional[Tuple[str, str, str]]:
        """Identify platform and the specific pattern that matched.

        Returns (platform_name, color, matched_pattern) or None.
        """
        command_lower = command.lower()
        for platform_name, platform_info in CODING_PLATFORMS.items():
            for pattern in platform_info['patterns']:
                if pattern.lower() in command_lower:
                    return (platform_name, platform_info['color'], pattern)
        return None

    def is_agent_process(self, command: str) -> bool:
        """Check if process matches agent patterns."""
        command_lower = command.lower()
        for pattern in AGENT_PATTERNS:
            if re.search(pattern, command_lower, re.IGNORECASE):
                return True
        return False

    def is_agent_process_detail(self, command: str) -> Tuple[bool, Optional[str]]:
        """Check if process matches agent patterns and return which pattern.

        Returns (is_match, matched_pattern_string) or (False, None).
        """
        command_lower = command.lower()
        for pattern in AGENT_PATTERNS:
            if re.search(pattern, command_lower, re.IGNORECASE):
                return (True, pattern)
        return (False, None)

    def is_system_process(self, command: str, user: str) -> bool:
        """Check if process is a system process."""
        if user in ['_driverkit', 'root', '_windowserver', '_coreaudiod']:
            return True
        if '/System/' in command or '/usr/libexec/' in command:
            return True
        return False

    def format_process_line(self, proc: Dict, max_width: int = 120) -> str:
        """Format a single process line for display."""
        pid = proc['pid'].rjust(6)
        cpu = f"{proc['cpu']:5.1f}%"
        mem = f"{proc['mem']:5.1f}%"
        user = proc['user'][:10].ljust(10)
        command = proc['command']

        # Truncate command if too long
        if len(command) > max_width - 50:
            command = command[:max_width - 53] + '...'

        # Identify platform
        platform_info = self.identify_platform(command)
        if platform_info:
            platform_name, color = platform_info
            platform_tag = f"{color}[{platform_name}]{RESET} "
        else:
            platform_tag = ""

        # Check for agent
        agent_tag = ""
        if self.is_agent_process(command):
            agent_tag = f"{YELLOW}[AGENT]{RESET} "

        # System process indicator
        system_tag = ""
        if self.is_system_process(command, proc['user']):
            system_tag = f"{CYAN}[SYS]{RESET} "

        return f"{pid} {cpu} {mem} {user} {system_tag}{platform_tag}{agent_tag}{command}"

    def display_processes(self, processes: List[Dict]):
        """Display processes in a chart-like format."""
        self.clear_screen()

        # Header
        print(f"{BOLD}{'='*120}{RESET}")
        print(f"{BOLD}PROCESS MONITOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
        print(f"{BOLD}{'='*120}{RESET}")
        print()

        # Filter processes
        if not self.show_all:
            # Show only coding platform processes and high CPU/memory processes
            filtered = []
            for proc in processes:
                platform_info = self.identify_platform(proc['command'])
                is_agent = self.is_agent_process(proc['command'])
                high_usage = proc['cpu'] > 1.0 or proc['mem'] > 1.0

                if platform_info or is_agent or high_usage:
                    filtered.append(proc)

            # Sort by CPU (descending)
            filtered.sort(key=lambda x: x['cpu'], reverse=True)
            display_processes = filtered[:50]  # Top 50
        else:
            # Sort all processes by CPU
            processes.sort(key=lambda x: x['cpu'], reverse=True)
            display_processes = processes[:100]  # Top 100

        # Column headers
        print(f"{BOLD}{'PID':<6} {'CPU%':<6} {'MEM%':<6} {'USER':<10} {'PROCESS':<80}{RESET}")
        print(f"{BOLD}{'-'*120}{RESET}")

        # Process list
        platform_counts = defaultdict(int)
        agent_count = 0

        for proc in display_processes:
            line = self.format_process_line(proc)
            print(line)

            # Count platforms
            platform_info = self.identify_platform(proc['command'])
            if platform_info:
                platform_counts[platform_info[0]] += 1

            if self.is_agent_process(proc['command']):
                agent_count += 1

        # Summary
        print()
        print(f"{BOLD}{'='*120}{RESET}")
        print(f"{BOLD}SUMMARY{RESET}")
        print(f"{BOLD}{'-'*120}{RESET}")
        print(f"Total processes displayed: {len(display_processes)}")
        print(f"Total processes in system: {len(processes)}")
        print()

        if platform_counts:
            print(f"{BOLD}Platform Activity:{RESET}")
            for platform_name, count in sorted(platform_counts.items(), key=lambda x: x[1], reverse=True):
                color = CODING_PLATFORMS.get(platform_name, {}).get('color', '')
                print(f"  {color}{platform_name}:{RESET} {count} processes")
            print()

        if agent_count > 0:
            print(f"{BOLD}Agent Processes:{RESET} {YELLOW}{agent_count}{RESET}")
            print()

        print(f"{BOLD}Controls:{RESET} Press Ctrl+C to exit | {'Show all' if not self.show_all else 'Show filtered'} processes")
        print(f"{BOLD}{'='*120}{RESET}")

    def run(self):
        """Run the monitor loop."""
        try:
            while self.running:
                processes = self.get_processes()
                self.display_processes(processes)
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            print(f"\n{BOLD}Monitor stopped.{RESET}")
            self.running = False

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Real-time process monitor with platform and agent detection'
    )
    parser.add_argument(
        '-i', '--interval',
        type=float,
        default=2.0,
        help='Refresh interval in seconds (default: 2.0)'
    )
    parser.add_argument(
        '-a', '--all',
        action='store_true',
        help='Show all processes (not just coding platforms and high usage)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run once and exit (no continuous monitoring)'
    )

    args = parser.parse_args()

    monitor = ProcessMonitor(
        refresh_interval=args.interval,
        show_all=args.all
    )

    if args.once:
        processes = monitor.get_processes()
        monitor.display_processes(processes)
    else:
        monitor.run()

if __name__ == '__main__':
    main()
