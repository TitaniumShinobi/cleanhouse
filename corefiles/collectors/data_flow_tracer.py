#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - data_flow_tracer.py
#  Advanced data flow tracing to identify surveillance channels
#  Tracks network connections, DNS queries, and data exfiltration patterns
#  Devon • 2026-01-06
# ──────────────────────────────────────────────────────────────────────────────

"""
Data Flow Tracer - Track where your data goes

This tool monitors:
- Network connections (process → destination)
- DNS queries (what domains are being resolved)
- Data transfer patterns (upload/download volumes)
- Certificate pinning and TLS connections
- Unusual network patterns that might indicate surveillance
"""

import os
import sys
import json
import re
import subprocess
import platform
import socket
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Set, Optional, Tuple
from collections import defaultdict, deque
import threading
import signal

# Known surveillance/telemetry endpoints

def _split_network_endpoint(endpoint: str) -> Tuple[str, int]:
    endpoint = str(endpoint or "").strip()
    if not endpoint:
        return "unknown", 0
    if endpoint.startswith("[") and "]:" in endpoint:
        host, port = endpoint.rsplit("]:", 1)
        return host + "]", int(port) if port.isdigit() else 0
    if ":" in endpoint:
        host, port = endpoint.rsplit(":", 1)
        return host, int(port) if port.isdigit() else 0
    return endpoint, 0


def _parse_lsof_network_address(address: str) -> Dict[str, Any]:
    address = str(address or "unknown").strip()
    if "->" not in address:
        host, port = _split_network_endpoint(address)
        return {
            "host": host,
            "port": port,
            "local_address": None,
            "local_host": None,
            "local_port": None,
            "remote_address": address,
            "remote_host": host,
            "remote_port": port,
        }
    local_address, remote_address = address.split("->", 1)
    local_host, local_port = _split_network_endpoint(local_address)
    remote_host, remote_port = _split_network_endpoint(remote_address)
    return {
        "host": remote_host,
        "port": remote_port,
        "local_address": local_address,
        "local_host": local_host,
        "local_port": local_port,
        "remote_address": remote_address,
        "remote_host": remote_host,
        "remote_port": remote_port,
    }
SURVEILLANCE_ENDPOINTS = {
    'government': [
        'nsa.gov', 'cia.gov', 'fbi.gov', 'dhs.gov',
        'gchq.gov.uk', 'asd.gov.au', 'cse-cst.gc.ca',
        'gchq', 'mi5', 'mi6', 'cia', 'nsa', 'fbi',
        'intelligence', 'surveillance', 'telemetry'
    ],
    'telemetry': [
        'telemetry', 'analytics', 'tracking', 'metrics',
        'data-collection', 'monitoring', 'logging',
        'diagnostics', 'crash-reporting', 'usage-stats'
    ],
    'cloud_surveillance': [
        'amazonaws.com', 's3.amazonaws.com', 'cloudwatch',
        'googleapis.com', 'azure.com', 'cloudfront',
        'akamai', 'cloudflare', 'fastly'
    ],
    'suspicious_tlds': [
        '.onion', '.i2p', '.bit',  # Tor/I2P (could be surveillance)
    ]
}

# Known legitimate domains (to reduce false positives)
LEGITIMATE_DOMAINS = [
    'apple.com', 'icloud.com', 'microsoft.com', 'google.com',
    'github.com', 'stackoverflow.com', 'reddit.com',
    'youtube.com', 'netflix.com', 'spotify.com',
    'amazon.com', 'ebay.com', 'paypal.com'
]


def connection_snapshot_key(connection: Dict[str, Any]) -> Optional[str]:
    """Return a stable identity for an observable network connection."""
    process = str(connection.get('process') or '').strip()
    pid = str(connection.get('pid') or '').strip()
    host = str(connection.get('host') or '').strip()
    port = str(connection.get('port') or '').strip()
    conn_type = str(connection.get('connection_type') or '').strip()
    address = str(connection.get('address') or '').strip()

    if not any([process, pid, host, address]):
        return None
    if host.lower() == 'unknown' and address.lower() == 'unknown':
        return None

    endpoint = f"{host}:{port}" if host else address
    return "|".join([
        process or "unknown-process",
        pid or "unknown-pid",
        conn_type or "unknown-type",
        endpoint or "unknown-endpoint",
    ])


def build_connection_snapshot(connections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a deterministic connection snapshot with sorted keys."""
    keyed: Dict[str, Dict[str, Any]] = {}
    unknown: List[Dict[str, Any]] = []

    for connection in connections:
        key = connection_snapshot_key(connection)
        if not key:
            unknown.append(dict(connection))
            continue
        entry = dict(connection)
        entry['snapshot_key'] = key
        keyed[key] = entry

    ordered_keys = sorted(keyed)
    return {
        'keys': ordered_keys,
        'connections': {key: keyed[key] for key in ordered_keys},
        'unknown': sorted(
            unknown,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        ),
    }


def compute_connection_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two connection snapshots by stable key."""
    before_connections = before.get('connections', {}) if isinstance(before, dict) else {}
    after_connections = after.get('connections', {}) if isinstance(after, dict) else {}
    before_keys = set(before_connections)
    after_keys = set(after_connections)

    opened_keys = sorted(after_keys - before_keys)
    still_open_keys = sorted(before_keys & after_keys)
    closed_keys = sorted(before_keys - after_keys)
    unknown = []
    if isinstance(before, dict):
        unknown.extend(before.get('unknown', []))
    if isinstance(after, dict):
        unknown.extend(after.get('unknown', []))

    return {
        'opened': [after_connections[key] for key in opened_keys],
        'still_open': [after_connections[key] for key in still_open_keys],
        'closed': [before_connections[key] for key in closed_keys],
        'unknown': sorted(
            [dict(entry) for entry in unknown],
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        ),
        'counts': {
            'opened': len(opened_keys),
            'still_open': len(still_open_keys),
            'closed': len(closed_keys),
            'unknown': len(unknown),
        },
    }

class DataFlowTracer:
    """Advanced data flow tracing to identify surveillance channels."""

    def __init__(self, output_file: Optional[Path] = None, monitor_duration: int = 300):
        if output_file is None:
            workspace = Path(__file__).parent
            self.output_file = workspace / 'data_flow_trace.json'
        else:
            self.output_file = Path(output_file).resolve()

        self.monitor_duration = monitor_duration  # seconds
        self.running = False
        self.trace_data = {
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'network_connections': [],
            'dns_queries': [],
            'process_network_map': {},
            'suspicious_connections': [],
            'data_transfer_patterns': [],
            'certificate_info': [],
            'unusual_patterns': [],
            'network_snapshots': [],
            'network_deltas': [],
            'summary': {}
        }
        self.connection_history = deque(maxlen=10000)  # Keep last 10k connections
        self.dns_cache = {}  # Cache DNS lookups
        self.process_cache = {}  # Cache process info
        self._last_network_snapshot: Optional[Dict[str, Any]] = None
        self._alert_log_cache: Dict[str, float] = {}

    def _alert_logging_enabled(self) -> bool:
        return os.getenv('CLEANHOUSE_DATA_FLOW_LOG_ALERTS', '').strip().lower() in {'1', 'true', 'yes', 'on'}

    def _alert_log_interval_seconds(self) -> float:
        raw = os.getenv('CLEANHOUSE_DATA_FLOW_ALERT_LOG_INTERVAL_SECONDS', '60').strip()
        try:
            interval = float(raw)
        except ValueError:
            return 60.0
        return max(0.0, interval)

    def _log(self, message: str, level: str = 'INFO'):
        """Log a message."""
        if level == 'ALERT':
            if not self._alert_logging_enabled():
                return
            now = time.monotonic()
            interval = self._alert_log_interval_seconds()
            last = self._alert_log_cache.get(message, 0.0)
            if interval and now - last < interval:
                return
            self._alert_log_cache[message] = now
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")

    def resolve_ip_to_domain(self, ip: str) -> Optional[str]:
        """Resolve IP address to domain name."""
        if ip in self.dns_cache:
            return self.dns_cache[ip]

        try:
            # Skip private IPs
            if ip.startswith('127.') or ip.startswith('192.168.') or ip.startswith('10.'):
                return None

            # Try reverse DNS lookup
            result = subprocess.run(
                ['dig', '+short', '-x', ip],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                domain = result.stdout.strip().rstrip('.')
                self.dns_cache[ip] = domain
                return domain
        except Exception:
            pass

        self.dns_cache[ip] = None
        return None

    def get_process_info(self, pid: str) -> Dict:
        """Get detailed process information."""
        if pid in self.process_cache:
            return self.process_cache[pid]

        try:
            result = subprocess.run(
                ['ps', '-p', pid, '-o', 'comm=,args=,user=,rss='],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split('\n')
                if parts and parts[0]:
                    info = {
                        'pid': pid,
                        'command': parts[0].split()[0] if parts[0] else 'unknown',
                        'args': ' '.join(parts[0].split()[1:]) if len(parts[0].split()) > 1 else '',
                        'user': parts[0].split()[-2] if len(parts[0].split()) > 2 else 'unknown',
                        'memory': parts[0].split()[-1] if len(parts[0].split()) > 1 else '0'
                    }
                    self.process_cache[pid] = info
                    return info
        except Exception:
            pass

        return {'pid': pid, 'command': 'unknown', 'args': '', 'user': 'unknown', 'memory': '0'}

    def check_suspicious_domain(self, domain: str) -> Tuple[bool, str]:
        """Check if domain is suspicious."""
        if not domain:
            return False, ''

        domain_lower = domain.lower()

        # Check against surveillance endpoints
        for category, patterns in SURVEILLANCE_ENDPOINTS.items():
            for pattern in patterns:
                if pattern.lower() in domain_lower:
                    return True, f"{category}:{pattern}"

        # Check for unusual TLDs
        for tld in SURVEILLANCE_ENDPOINTS['suspicious_tlds']:
            if domain_lower.endswith(tld):
                return True, f"suspicious_tld:{tld}"

        return False, ''

    def build_connection_snapshot(self, connections: List[Dict[str, Any]]) -> Dict[str, Any]:
        return build_connection_snapshot(connections)

    def compute_connection_delta(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        return compute_connection_delta(before, after)

    def scan_network_connections(self):
        """Scan current network connections."""
        try:
            if platform.system() == 'Darwin':  # macOS
                result = subprocess.run(
                    ['lsof', '-i', '-P', '-n'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    connections = result.stdout.split('\n')
                    current_connections = []

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
                        parsed_address = _parse_lsof_network_address(address)
                        host = parsed_address['host']
                        port = parsed_address['port']

                        if host != 'unknown':
                            # Resolve IP to domain
                            domain = None
                            if not host.startswith('127.') and not host.startswith('::'):
                                domain = self.resolve_ip_to_domain(host)

                            # Get process info
                            proc_info = self.get_process_info(pid)

                            connection = {
                                'timestamp': datetime.now().isoformat(),
                                'process': proc_name,
                                'pid': pid,
                                'process_info': proc_info,
                                'connection_type': conn_type,
                                'host': host,
                                'port': port,
                                'domain': domain,
                                'address': address,
                                'local_address': parsed_address['local_address'],
                                'local_host': parsed_address['local_host'],
                                'local_port': parsed_address['local_port'],
                                'remote_address': parsed_address['remote_address'],
                                'remote_host': parsed_address['remote_host'],
                                'remote_port': parsed_address['remote_port'],
                            }

                            # Check if suspicious
                            is_suspicious, reason = self.check_suspicious_domain(domain or host)
                            if is_suspicious:
                                connection['suspicious'] = True
                                connection['suspicious_reason'] = reason
                                self.trace_data['suspicious_connections'].append(connection)
                                self._log(f"🚨 SUSPICIOUS: {proc_name} → {domain or host} ({reason})", "ALERT")

                            current_connections.append(connection)
                            self.connection_history.append(connection)

                    self.trace_data['network_connections'].extend(current_connections)
                    current_snapshot = self.build_connection_snapshot(current_connections)
                    current_snapshot['timestamp'] = datetime.now().isoformat()
                    self.trace_data['network_snapshots'].append(current_snapshot)
                    if self._last_network_snapshot is None:
                        empty_snapshot = build_connection_snapshot([])
                        delta = self.compute_connection_delta(empty_snapshot, current_snapshot)
                    else:
                        delta = self.compute_connection_delta(self._last_network_snapshot, current_snapshot)
                    delta['timestamp'] = current_snapshot['timestamp']
                    self.trace_data['network_deltas'].append(delta)
                    self._last_network_snapshot = current_snapshot

                    # Update process network map
                    for conn in current_connections:
                        proc_key = f"{conn['process']}:{conn['pid']}"
                        if proc_key not in self.trace_data['process_network_map']:
                            self.trace_data['process_network_map'][proc_key] = {
                                'process': conn['process'],
                                'pid': conn['pid'],
                                'process_info': conn['process_info'],
                                'connections': [],
                                'unique_domains': set(),
                                'total_connections': 0
                            }

                        self.trace_data['process_network_map'][proc_key]['connections'].append({
                            'host': conn['host'],
                            'domain': conn['domain'],
                            'port': conn['port'],
                            'timestamp': conn['timestamp']
                        })
                        if conn['domain']:
                            self.trace_data['process_network_map'][proc_key]['unique_domains'].add(conn['domain'])
                        self.trace_data['process_network_map'][proc_key]['total_connections'] += 1

        except Exception as e:
            self._log(f"Error scanning network connections: {e}", "ERROR")

    def scan_dns_queries(self):
        """Scan DNS queries (macOS uses mDNSResponder)."""
        try:
            # Check DNS cache on macOS
            result = subprocess.run(
                ['scutil', '--dns'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                dns_output = result.stdout
                # Parse DNS servers
                dns_servers = []
                for line in dns_output.split('\n'):
                    if 'nameserver' in line.lower():
                        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
                        ips = re.findall(ip_pattern, line)
                        dns_servers.extend(ips)

                # Check for suspicious DNS servers
                legitimate_dns = ['8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1']
                for dns in dns_servers:
                    if dns not in legitimate_dns and not dns.startswith('192.168.'):
                        self.trace_data['dns_queries'].append({
                            'timestamp': datetime.now().isoformat(),
                            'dns_server': dns,
                            'suspicious': True,
                            'reason': 'Non-standard DNS server'
                        })
                        self._log(f"⚠️ Suspicious DNS server: {dns}", "ALERT")

        except Exception as e:
            self._log(f"Error scanning DNS: {e}", "ERROR")

    def analyze_data_transfer_patterns(self):
        """Analyze data transfer patterns to identify exfiltration."""
        # Group connections by process and domain
        process_domain_stats = defaultdict(lambda: {'connections': 0, 'domains': set(), 'ports': set()})

        for conn in self.connection_history:
            proc_key = f"{conn['process']}:{conn['pid']}"
            domain = conn.get('domain') or conn.get('host', 'unknown')

            process_domain_stats[proc_key]['connections'] += 1
            process_domain_stats[proc_key]['domains'].add(domain)
            process_domain_stats[proc_key]['ports'].add(conn.get('port', 0))

        # Identify unusual patterns
        for proc_key, stats in process_domain_stats.items():
            # High connection count to many domains (potential data exfiltration)
            if stats['connections'] > 100 and len(stats['domains']) > 10:
                self.trace_data['unusual_patterns'].append({
                    'type': 'high_connection_count',
                    'process': proc_key,
                    'connections': stats['connections'],
                    'unique_domains': len(stats['domains']),
                    'timestamp': datetime.now().isoformat(),
                    'description': f"Process {proc_key} has {stats['connections']} connections to {len(stats['domains'])} unique domains"
                })
                self._log(f"⚠️ Unusual pattern: {proc_key} → {stats['connections']} connections to {len(stats['domains'])} domains", "ALERT")

            # Many connections to cloud services
            cloud_domains = [d for d in stats['domains'] if any(cd in d.lower() for cd in ['amazonaws', 'googleapis', 'azure', 'cloudfront'])]
            if len(cloud_domains) > 5:
                self.trace_data['unusual_patterns'].append({
                    'type': 'multiple_cloud_connections',
                    'process': proc_key,
                    'cloud_domains': cloud_domains,
                    'timestamp': datetime.now().isoformat(),
                    'description': f"Process {proc_key} connecting to {len(cloud_domains)} cloud services"
                })
                self._log(f"⚠️ Multiple cloud connections: {proc_key} → {cloud_domains}", "ALERT")

    def generate_summary(self):
        """Generate summary of findings."""
        total_connections = len(self.trace_data['network_connections'])
        unique_processes = len(set(c['process'] for c in self.trace_data['network_connections']))
        unique_domains = len(set(c['domain'] for c in self.trace_data['network_connections'] if c.get('domain')))
        suspicious_count = len(self.trace_data['suspicious_connections'])
        unusual_patterns_count = len(self.trace_data['unusual_patterns'])

        # Top processes by connection count
        process_counts = defaultdict(int)
        for conn in self.trace_data['network_connections']:
            process_counts[conn['process']] += 1
        top_processes = sorted(process_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Top domains
        domain_counts = defaultdict(int)
        for conn in self.trace_data['network_connections']:
            if conn.get('domain'):
                domain_counts[conn['domain']] += 1
        top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        self.trace_data['summary'] = {
            'total_connections': total_connections,
            'unique_processes': unique_processes,
            'unique_domains': unique_domains,
            'suspicious_connections': suspicious_count,
            'unusual_patterns': unusual_patterns_count,
            'top_processes': [{'process': p, 'connections': c} for p, c in top_processes],
            'top_domains': [{'domain': d, 'connections': c} for d, c in top_domains],
            'monitoring_duration_seconds': self.monitor_duration
        }

    def monitor_loop(self):
        """Main monitoring loop."""
        self._log(f"Starting data flow tracing for {self.monitor_duration} seconds...")
        start_time = time.time()

        while self.running and (time.time() - start_time) < self.monitor_duration:
            try:
                self.scan_network_connections()
                self.scan_dns_queries()
                time.sleep(5)  # Scan every 5 seconds
            except KeyboardInterrupt:
                break
            except Exception as e:
                self._log(f"Error in monitor loop: {e}", "ERROR")
                time.sleep(5)

        self._log("Monitoring complete. Analyzing patterns...")
        self.analyze_data_transfer_patterns()
        self.generate_summary()
        self.trace_data['end_time'] = datetime.now().isoformat()

    def run(self):
        """Run the tracer."""
        self.running = True

        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            self._log("Stopping tracer...")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)

        try:
            self.monitor_loop()
        except Exception as e:
            self._log(f"Error running tracer: {e}", "ERROR")
        finally:
            self.save_results()
            self.print_report()

    def save_results(self):
        """Save trace results to file."""
        try:
            # Convert sets to lists for JSON serialization
            trace_data_serializable = json.loads(json.dumps(self.trace_data, default=str))

            with open(self.output_file, 'w') as f:
                json.dump(trace_data_serializable, f, indent=2)

            self._log(f"Results saved to {self.output_file}")
        except Exception as e:
            self._log(f"Error saving results: {e}", "ERROR")

    def print_report(self):
        """Print human-readable report."""
        print("\n" + "="*80)
        print("DATA FLOW TRACE REPORT")
        print("="*80)
        print(f"Start: {self.trace_data['start_time']}")
        print(f"End: {self.trace_data.get('end_time', 'N/A')}")

        summary = self.trace_data['summary']
        print(f"\nTotal Connections: {summary.get('total_connections', 0)}")
        print(f"Unique Processes: {summary.get('unique_processes', 0)}")
        print(f"Unique Domains: {summary.get('unique_domains', 0)}")
        print(f"Suspicious Connections: {summary.get('suspicious_connections', 0)}")
        print(f"Unusual Patterns: {summary.get('unusual_patterns', 0)}")

        if summary.get('suspicious_connections', 0) > 0:
            print("\n🚨 SUSPICIOUS CONNECTIONS DETECTED:")
            for conn in self.trace_data['suspicious_connections'][:10]:
                print(f"  - {conn['process']} → {conn.get('domain') or conn['host']} ({conn.get('suspicious_reason', 'unknown')})")

        if summary.get('top_processes'):
            print("\nTop Processes by Connection Count:")
            for proc in summary['top_processes'][:5]:
                print(f"  - {proc['process']}: {proc['connections']} connections")

        if summary.get('top_domains'):
            print("\nTop Domains:")
            for domain in summary['top_domains'][:5]:
                print(f"  - {domain['domain']}: {domain['connections']} connections")

        if summary.get('unusual_patterns', 0) > 0:
            print("\n⚠️  UNUSUAL PATTERNS:")
            for pattern in self.trace_data['unusual_patterns'][:5]:
                print(f"  - {pattern['description']}")

        print("\n" + "="*80)
        print(f"Full report: {self.output_file}")
        print("="*80 + "\n")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Data Flow Tracer - Track where your data goes'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output file path'
    )
    parser.add_argument(
        '-d', '--duration',
        type=int,
        default=300,
        help='Monitoring duration in seconds (default: 300 = 5 minutes)'
    )

    args = parser.parse_args()

    tracer = DataFlowTracer(output_file=args.output, monitor_duration=args.duration)
    tracer.run()


if __name__ == '__main__':
    main()
