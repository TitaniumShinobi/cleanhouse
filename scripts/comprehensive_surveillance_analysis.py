#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - comprehensive_surveillance_analysis.py
#  Comprehensive surveillance analysis combining multiple detection methods
#  Devon • 2026-01-06
# ──────────────────────────────────────────────────────────────────────────────

"""
Comprehensive Surveillance Analysis

Runs multiple detection tools and combines results to identify surveillance:
1. Surveillance Detector (file/process scanning)
2. Data Flow Tracer (network monitoring)
3. Cross-correlation analysis
"""

import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"

def run_surveillance_detector() -> Dict:
    """Run surveillance detector."""
    print("="*80)
    print("STEP 1: Running Surveillance Detector...")
    print("="*80)

    try:
        result = subprocess.run(
            ['python3', '-m', 'corefiles.collectors.surveillance_detector', '-q'],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minutes
            cwd=PROJECT_ROOT,
        )

        # Try to load results
        scan_file = PROJECT_ROOT / 'surveillance_scan.json'
        if scan_file.exists():
            with open(scan_file, 'r') as f:
                return json.load(f)

        return {'error': 'Could not load surveillance scan results'}
    except Exception as e:
        return {'error': str(e)}

def run_data_flow_tracer(duration: int = 300) -> Dict:
    """Run data flow tracer."""
    print("\n" + "="*80)
    print(f"STEP 2: Running Data Flow Tracer ({duration} seconds)...")
    print("="*80)
    print("This will monitor network connections for 5 minutes.")
    print("You can continue using your computer normally.")
    print("="*80 + "\n")

    try:
        result = subprocess.run(
            ['python3', '-m', 'corefiles.collectors.data_flow_tracer', '-d', str(duration)],
            timeout=duration + 60,  # Add buffer
            cwd=PROJECT_ROOT,
        )

        # Try to load results
        trace_file = PROJECT_ROOT / 'data_flow_trace.json'
        if trace_file.exists():
            with open(trace_file, 'r') as f:
                return json.load(f)

        return {'error': 'Could not load data flow trace results'}
    except subprocess.TimeoutExpired:
        # This is expected - the tracer runs for the duration
        trace_file = PROJECT_ROOT / 'data_flow_trace.json'
        if trace_file.exists():
            with open(trace_file, 'r') as f:
                return json.load(f)
        return {'error': 'Data flow tracer timed out'}
    except Exception as e:
        return {'error': str(e)}

def correlate_findings(surveillance_data: Dict, flow_data: Dict) -> Dict:
    """Correlate findings from both tools."""
    correlations = {
        'suspicious_processes': [],
        'data_exfiltration_paths': [],
        'surveillance_channels': [],
        'high_confidence_threats': []
    }

    # Find processes that appear in both scans
    surveillance_processes = set()
    if 'suspicious_processes' in surveillance_data:
        for proc in surveillance_data['suspicious_processes']:
            surveillance_processes.add(proc.get('process', ''))

    if 'process_network_map' in flow_data:
        for proc_key, proc_data in flow_data['process_network_map'].items():
            proc_name = proc_data.get('process', '')
            if proc_name in surveillance_processes:
                # This process was flagged AND has network activity
                correlations['suspicious_processes'].append({
                    'process': proc_name,
                    'pid': proc_data.get('pid'),
                    'connections': proc_data.get('total_connections', 0),
                    'domains': list(proc_data.get('unique_domains', set())),
                    'severity': 'high'
                })

    # Identify data exfiltration paths
    if 'suspicious_connections' in flow_data:
        for conn in flow_data['suspicious_connections']:
            correlations['data_exfiltration_paths'].append({
                'process': conn.get('process'),
                'destination': conn.get('domain') or conn.get('host'),
                'reason': conn.get('suspicious_reason'),
                'timestamp': conn.get('timestamp')
            })

    # Identify surveillance channels
    if 'unusual_patterns' in flow_data:
        for pattern in flow_data['unusual_patterns']:
            if 'cloud' in pattern.get('type', '').lower():
                correlations['surveillance_channels'].append({
                    'type': 'cloud_exfiltration',
                    'process': pattern.get('process'),
                    'description': pattern.get('description'),
                    'domains': pattern.get('cloud_domains', [])
                })

    # High confidence threats: processes with surveillance signatures AND suspicious network activity
    if 'keyloggers' in surveillance_data:
        for keylogger in surveillance_data['keyloggers']:
            file_path = keylogger.get('file', '')
            # Check if this process has network activity
            for proc_key, proc_data in flow_data.get('process_network_map', {}).items():
                if file_path in proc_data.get('process_info', {}).get('args', ''):
                    correlations['high_confidence_threats'].append({
                        'type': 'keylogger_with_network',
                        'file': file_path,
                        'process': proc_data.get('process'),
                        'connections': proc_data.get('total_connections', 0),
                        'severity': 'critical'
                    })

    return correlations

def generate_report(surveillance_data: Dict, flow_data: Dict, correlations: Dict):
    """Generate comprehensive report."""
    report = {
        'timestamp': datetime.now().isoformat(),
        'surveillance_detection': {
            'total_findings': surveillance_data.get('summary', {}).get('total_findings', 0),
            'critical': surveillance_data.get('summary', {}).get('critical', 0),
            'high': surveillance_data.get('summary', {}).get('high', 0),
            'surveillance_detected': surveillance_data.get('summary', {}).get('total_findings', 0) > 0
        },
        'network_analysis': {
            'total_connections': flow_data.get('summary', {}).get('total_connections', 0),
            'unique_processes': flow_data.get('summary', {}).get('unique_processes', 0),
            'unique_domains': flow_data.get('summary', {}).get('unique_domains', 0),
            'suspicious_connections': flow_data.get('summary', {}).get('suspicious_connections', 0),
            'unusual_patterns': flow_data.get('summary', {}).get('unusual_patterns', 0)
        },
        'correlations': correlations,
        'recommendations': []
    }

    # Generate recommendations
    if correlations['high_confidence_threats']:
        report['recommendations'].append({
            'priority': 'critical',
            'action': 'Immediately investigate high-confidence threats',
            'details': f"{len(correlations['high_confidence_threats'])} processes show both surveillance signatures and network activity"
        })

    if correlations['data_exfiltration_paths']:
        report['recommendations'].append({
            'priority': 'high',
            'action': 'Review data exfiltration paths',
            'details': f"{len(correlations['data_exfiltration_paths'])} suspicious network connections detected"
        })

    if correlations['surveillance_channels']:
        report['recommendations'].append({
            'priority': 'high',
            'action': 'Investigate cloud surveillance channels',
            'details': f"{len(correlations['surveillance_channels'])} unusual cloud connection patterns detected"
        })

    return report

def print_final_report(report: Dict):
    """Print final comprehensive report."""
    print("\n" + "="*80)
    print("COMPREHENSIVE SURVEILLANCE ANALYSIS REPORT")
    print("="*80)

    print(f"\nAnalysis Date: {report['timestamp']}")

    print("\n" + "-"*80)
    print("SURVEILLANCE DETECTION")
    print("-"*80)
    sd = report['surveillance_detection']
    print(f"Total Findings: {sd['total_findings']}")
    print(f"Critical: {sd['critical']}")
    print(f"High: {sd['high']}")
    print(f"Surveillance Detected: {'YES' if sd['surveillance_detected'] else 'NO'}")

    print("\n" + "-"*80)
    print("NETWORK ANALYSIS")
    print("-"*80)
    na = report['network_analysis']
    print(f"Total Connections: {na['total_connections']}")
    print(f"Unique Processes: {na['unique_processes']}")
    print(f"Unique Domains: {na['unique_domains']}")
    print(f"Suspicious Connections: {na['suspicious_connections']}")
    print(f"Unusual Patterns: {na['unusual_patterns']}")

    print("\n" + "-"*80)
    print("CORRELATED FINDINGS")
    print("-"*80)
    corr = report['correlations']
    print(f"Suspicious Processes with Network Activity: {len(corr['suspicious_processes'])}")
    print(f"Data Exfiltration Paths: {len(corr['data_exfiltration_paths'])}")
    print(f"Surveillance Channels: {len(corr['surveillance_channels'])}")
    print(f"High-Confidence Threats: {len(corr['high_confidence_threats'])}")

    if corr['high_confidence_threats']:
        print("\n🚨 HIGH-CONFIDENCE THREATS:")
        for threat in corr['high_confidence_threats'][:5]:
            print(f"  - {threat['type']}: {threat.get('process', 'unknown')} ({threat.get('file', 'N/A')})")

    if corr['data_exfiltration_paths']:
        print("\n⚠️  DATA EXFILTRATION PATHS:")
        for path in corr['data_exfiltration_paths'][:5]:
            print(f"  - {path['process']} → {path['destination']} ({path.get('reason', 'unknown')})")

    if report['recommendations']:
        print("\n" + "-"*80)
        print("RECOMMENDATIONS")
        print("-"*80)
        for rec in report['recommendations']:
            print(f"\n[{rec['priority'].upper()}] {rec['action']}")
            print(f"  {rec['details']}")

    print("\n" + "="*80)
    print("Analysis complete. Review detailed reports:")
    print("  - surveillance_scan.json")
    print("  - data_flow_trace.json")
    print("  - comprehensive_analysis.json")
    print("="*80 + "\n")

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Comprehensive Surveillance Analysis'
    )
    parser.add_argument(
        '-d', '--duration',
        type=int,
        default=300,
        help='Data flow tracer duration in seconds (default: 300 = 5 minutes)'
    )
    parser.add_argument(
        '--skip-detector',
        action='store_true',
        help='Skip surveillance detector (use existing scan)'
    )
    parser.add_argument(
        '--skip-tracer',
        action='store_true',
        help='Skip data flow tracer (use existing trace)'
    )

    args = parser.parse_args()

    # Run surveillance detector
    if not args.skip_detector:
        surveillance_data = run_surveillance_detector()
    else:
        scan_file = PROJECT_ROOT / 'surveillance_scan.json'
        if scan_file.exists():
            with open(scan_file, 'r') as f:
                surveillance_data = json.load(f)
        else:
            print("Error: surveillance_scan.json not found. Run without --skip-detector")
            sys.exit(1)

    # Run data flow tracer
    if not args.skip_tracer:
        flow_data = run_data_flow_tracer(duration=args.duration)
    else:
        trace_file = PROJECT_ROOT / 'data_flow_trace.json'
        if trace_file.exists():
            with open(trace_file, 'r') as f:
                flow_data = json.load(f)
        else:
            print("Error: data_flow_trace.json not found. Run without --skip-tracer")
            sys.exit(1)

    # Correlate findings
    print("\n" + "="*80)
    print("STEP 3: Correlating Findings...")
    print("="*80)
    correlations = correlate_findings(surveillance_data, flow_data)

    # Generate report
    report = generate_report(surveillance_data, flow_data, correlations)

    # Save report
    report_file = Path('comprehensive_analysis.json')
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)

    # Print report
    print_final_report(report)

if __name__ == '__main__':
    main()
