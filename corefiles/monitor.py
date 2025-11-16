import os
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import threading
from typing import Dict, List, Set
import numpy as np
from scipy import stats

from . import config
from corefiles.error_handler import error_handler

class MonitoringStats:
    """Handles detailed monitoring statistics and trend analysis."""
    
    def __init__(self):
        self.stats = {
            'file_operations': defaultdict(int),
            'security_events': defaultdict(int),
            'performance_metrics': defaultdict(list),
            'access_patterns': defaultdict(int),
            'error_rates': defaultdict(int),
            'scan_times': [],
            'file_sizes': defaultdict(list),
            'change_frequency': defaultdict(list)
        }
        self.trends = {
            'file_operations': {},
            'security_events': {},
            'performance': {},
            'access_patterns': {},
            'error_rates': {}
        }
        self.lock = threading.Lock()
    
    def record_file_operation(self, operation: str, file_path: Path):
        """Record a file operation with timestamp."""
        with self.lock:
            timestamp = datetime.now()
            self.stats['file_operations'][operation] += 1
            self.stats['change_frequency'][str(file_path)].append(timestamp)
    
    def record_security_event(self, event_type: str, severity: str):
        """Record a security event with severity."""
        with self.lock:
            self.stats['security_events'][f"{event_type}_{severity}"] += 1
    
    def record_performance_metric(self, metric: str, value: float):
        """Record a performance metric."""
        with self.lock:
            self.stats['performance_metrics'][metric].append(value)
    
    def record_access_pattern(self, pattern: str):
        """Record an access pattern."""
        with self.lock:
            self.stats['access_patterns'][pattern] += 1
    
    def record_error(self, error_type: str):
        """Record an error occurrence."""
        with self.lock:
            self.stats['error_rates'][error_type] += 1
    
    def record_scan_time(self, duration: float):
        """Record scan duration."""
        with self.lock:
            self.stats['scan_times'].append(duration)
    
    def record_file_size(self, file_path: Path, size: int):
        """Record file size for trend analysis."""
        with self.lock:
            self.stats['file_sizes'][str(file_path)].append(size)
    
    def analyze_trends(self):
        """Analyze trends in the collected data."""
        with self.lock:
            # Analyze file operation trends
            for operation, count in self.stats['file_operations'].items():
                self.trends['file_operations'][operation] = {
                    'total': count,
                    'rate': count / (time.time() - self.stats['scan_times'][0] if self.stats['scan_times'] else 1)
                }
            
            # Analyze security event trends
            for event, count in self.stats['security_events'].items():
                self.trends['security_events'][event] = {
                    'total': count,
                    'severity_distribution': self._calculate_severity_distribution(event)
                }
            
            # Analyze performance trends
            for metric, values in self.stats['performance_metrics'].items():
                if values:
                    self.trends['performance'][metric] = {
                        'mean': np.mean(values),
                        'std': np.std(values),
                        'trend': self._calculate_trend(values)
                    }
            
            # Analyze access pattern trends
            for pattern, count in self.stats['access_patterns'].items():
                self.trends['access_patterns'][pattern] = {
                    'total': count,
                    'frequency': count / (time.time() - self.stats['scan_times'][0] if self.stats['scan_times'] else 1)
                }
            
            # Analyze error rate trends
            for error_type, count in self.stats['error_rates'].items():
                self.trends['error_rates'][error_type] = {
                    'total': count,
                    'rate': count / (time.time() - self.stats['scan_times'][0] if self.stats['scan_times'] else 1)
                }
    
    def _calculate_severity_distribution(self, event: str) -> Dict[str, float]:
        """Calculate severity distribution for an event type."""
        total = sum(1 for k in self.stats['security_events'] if k.startswith(event))
        if total == 0:
            return {}
        return {
            severity: count / total
            for severity, count in self.stats['security_events'].items()
            if severity.startswith(event)
        }
    
    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction and significance."""
        if len(values) < 2:
            return "insufficient_data"
        
        x = np.arange(len(values))
        slope, _, r_value, p_value, _ = stats.linregress(x, values)
        
        if p_value > 0.05:
            return "no_significant_trend"
        elif slope > 0:
            return "increasing"
        else:
            return "decreasing"
    
    def get_performance_report(self) -> Dict:
        """Generate a comprehensive performance report."""
        self.analyze_trends()
        return {
            'file_operations': self.trends['file_operations'],
            'security_events': self.trends['security_events'],
            'performance': self.trends['performance'],
            'access_patterns': self.trends['access_patterns'],
            'error_rates': self.trends['error_rates'],
            'scan_statistics': {
                'total_scans': len(self.stats['scan_times']),
                'average_scan_time': np.mean(self.stats['scan_times']) if self.stats['scan_times'] else 0,
                'scan_time_trend': self._calculate_trend(self.stats['scan_times'])
            }
        }

class FileSystemMonitor:
    """Enhanced file system monitoring with detailed statistics."""
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.running = False
        self.monitor_thread = None
        self.stats = MonitoringStats()
        self.last_check = {}
        self.activity_log = []
        self._initialize_baseline()
    
    def _initialize_baseline(self):
        """Initialize monitoring baseline with performance tracking."""
        start_time = time.time()
        for path in self.root_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    with open(path, 'rb') as f:
                        content = f.read()
                        self.last_check[str(path)] = {
                            'hash': self._compute_hash(content),
                            'size': len(content),
                            'mtime': path.stat().st_mtime
                        }
                        self.stats.record_file_size(path, len(content))
                except Exception as e:
                    logging.error(f"Failed to initialize baseline for {path}: {e}")
                    self.stats.record_error('baseline_init')
        
        duration = time.time() - start_time
        self.stats.record_scan_time(duration)
        self.stats.record_performance_metric('baseline_init_time', duration)
    
    def start_monitoring(self):
        """Start monitoring with performance tracking."""
        if self.running:
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.stats.record_security_event('monitoring_started', 'info')
    
    def stop_monitoring(self):
        """Stop monitoring and generate final statistics."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        self.stats.record_security_event('monitoring_stopped', 'info')
        return self.stats.get_performance_report()
    
    def _monitor_loop(self):
        """Enhanced monitoring loop with detailed statistics."""
        while self.running:
            try:
                start_time = time.time()
                self._check_directory()
                duration = time.time() - start_time
                self.stats.record_scan_time(duration)
                self.stats.record_performance_metric('scan_duration', duration)
                time.sleep(config.MONITOR_INTERVAL)
            except Exception as e:
                logging.error(f"Error in monitor loop: {e}")
                self.stats.record_error('monitor_loop')
                time.sleep(5)
    
    def _check_directory(self):
        """Check directory for changes with enhanced tracking."""
        for path in self.root_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    current_mtime = path.stat().st_mtime
                    str_path = str(path)
                    
                    if str_path not in self.last_check:
                        self._handle_new_file(path)
                    elif current_mtime > self.last_check[str_path]['mtime']:
                        self._handle_modified_file(path)
                    
                    # Update access patterns
                    self.stats.record_access_pattern(str(path.parent))
                    
                except Exception as e:
                    logging.error(f"Error checking {path}: {e}")
                    self.stats.record_error('file_check')
    
    def _handle_new_file(self, path: Path):
        """Handle new file detection with statistics."""
        try:
            with open(path, 'rb') as f:
                content = f.read()
                self.last_check[str(path)] = {
                    'hash': self._compute_hash(content),
                    'size': len(content),
                    'mtime': path.stat().st_mtime
                }
                self.stats.record_file_operation('new_file', path)
                self.stats.record_file_size(path, len(content))
                self.stats.record_security_event('new_file_detected', 'warning')
        except Exception as e:
            logging.error(f"Error handling new file {path}: {e}")
            self.stats.record_error('new_file_handling')
    
    def _handle_modified_file(self, path: Path):
        """Handle modified file detection with statistics."""
        try:
            with open(path, 'rb') as f:
                content = f.read()
                new_hash = self._compute_hash(content)
                new_size = len(content)
                
                if new_hash != self.last_check[str(path)]['hash']:
                    self.stats.record_file_operation('modified_file', path)
                    self.stats.record_file_size(path, new_size)
                    self.stats.record_security_event('file_modified', 'warning')
                    
                    # Check for suspicious changes
                    if self._is_suspicious_change(path, content):
                        self.stats.record_security_event('suspicious_modification', 'critical')
                
                self.last_check[str(path)].update({
                    'hash': new_hash,
                    'size': new_size,
                    'mtime': path.stat().st_mtime
                })
        except Exception as e:
            logging.error(f"Error handling modified file {path}: {e}")
            self.stats.record_error('modified_file_handling')
    
    def _is_suspicious_change(self, path: Path, content: bytes) -> bool:
        """Check for suspicious changes in file content."""
        # Implement suspicious change detection logic here
        # This is a placeholder for actual implementation
        return False
    
    def _compute_hash(self, content: bytes) -> str:
        """Compute hash of file content."""
        # Implement hash computation logic here
        # This is a placeholder for actual implementation
        return str(hash(content))
    
    def get_activity_log(self) -> List[Dict]:
        """Get the activity log with enhanced statistics."""
        return self.activity_log
    
    def get_stats(self) -> Dict:
        """Get current monitoring statistics."""
        return self.stats.get_performance_report() 