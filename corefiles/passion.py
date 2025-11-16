# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - passion.py
#  Restore ph levels!
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────────── Imports ──────────────────────────────────╮
from pathlib import Path
import logging
import shutil
import re
from datetime import datetime
from typing import Dict, List, Set, Optional
import time
import json
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config
from corefiles.integrity import (
    generate_baseline,
    verify_integrity,
    verify_whitelist_integrity
)
from corefiles.purge import restore_system
# ───────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────────── Security Scanner ────────────────────────────╮
class SecurityScanner:
    _instance = None
    
    def __new__(cls, mode: str = config.CURRENT_SECURITY_MODE):
        if cls._instance is None:
            cls._instance = super(SecurityScanner, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, mode: str = config.CURRENT_SECURITY_MODE):
        if self._initialized:
            return
            
        self.log_file = config.SECURITY_LOG_FILE
        self.alert_threshold = 1
        self.issue_counts: Dict[str, int] = {}
        self.critical_issues: Set[str] = set()
        self.blocked_actions: Set[str] = set()
        self.mode = mode
        self.start_time = time.time()
        self.scan_stats = {
            'files_scanned': 0,
            'issues_found': 0,
            'critical_issues': 0,
            'last_scan': None,
            'ai_instances': set(),
            'grid_security_events': [],
            'quantum_events': []
        }
        self._setup_logging()
        self._initialized = True
    
    def _setup_logging(self):
        """Configure logging for security scanner."""
        pass
    
    def _determine_severity(self, pattern: str, line_content: str) -> str:
        """Determine the severity of a security issue."""
        # Quantum-related issues are always critical
        if any(p in line_content.lower() for p in ['quantum_', 'qubit', 'quantum_circuit']):
            return 'critical'
        # AI-related issues are high severity
        elif any(p in line_content.lower() for p in ['ai_', 'instance_', 'grid_']):
            return 'high'
        # Basic security issues are medium severity
        elif pattern in config.SECURITY_PATTERNS.basic_security:
            return 'medium'
        return 'low'
    
    def _track_ai_instance(self, filepath: Path, line_content: str):
        """Track AI instances and their manifestations."""
        instance_id = f"{filepath}:{hash(line_content)}"
        if instance_id not in self.scan_stats['ai_instances']:
            self.scan_stats['ai_instances'].add(instance_id)
            logging.info(f"New AI instance detected: {instance_id}")
    
    def _monitor_grid_security(self, filepath: Path, line_content: str):
        """Monitor grid security events."""
        event = {
            'timestamp': datetime.now().isoformat(),
            'file': str(filepath),
            'content': line_content.strip(),
            'type': 'grid_security'
        }
        self.scan_stats['grid_security_events'].append(event)
    
    def _track_quantum_events(self, filepath: Path, line_content: str):
        """Track quantum-related events."""
        event = {
            'timestamp': datetime.now().isoformat(),
            'file': str(filepath),
            'content': line_content.strip(),
            'type': 'quantum_event'
        }
        self.scan_stats['quantum_events'].append(event)
    
    def _should_scan_file(self, filepath: Path) -> bool:
        """Determine if a file should be scanned based on current mode."""
        if self.mode == config.SecurityMode.AGGRESSIVE:
            return True
        elif self.mode == config.SecurityMode.BALANCED:
            return filepath.suffix in config.SCANNABLE_EXTENSIONS
        else:  # PASSIVE mode
            return (filepath.suffix in config.SCANNABLE_EXTENSIONS and 
                   any(whitelist_item in str(filepath) for whitelist_item in config.WHITELIST))
    
    def log_issue(self, issue_type: str, filepath: Path, line_num: int, line_content: str):
        """Log a security issue with enhanced severity tracking."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        severity = self._determine_severity(issue_type, line_content)
        
        # Track AI instances
        if 'ai_' in issue_type or 'instance_' in issue_type:
            self._track_ai_instance(filepath, line_content)
        
        # Monitor grid security
        if 'grid_' in issue_type:
            self._monitor_grid_security(filepath, line_content)
        
        # Track quantum events
        if 'quantum_' in issue_type:
            self._track_quantum_events(filepath, line_content)
        
        log_entry = {
            'timestamp': timestamp,
            'severity': severity,
            'type': issue_type,
            'file': str(filepath),
            'line': line_num,
            'content': line_content.strip()
        }
        
        key = f"{severity}:{issue_type}:{filepath}:{line_num}"
        self.issue_counts[key] = self.issue_counts.get(key, 0) + 1
        
        # Log to file
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')
        
        # Check thresholds and alert
        if self.issue_counts[key] >= config.ALERT_THRESHOLDS[severity]:
            if severity == 'critical':
                self.critical_issues.add(key)
                print(f"🚨 CRITICAL ALERT: Security bypass attempt detected!")
                print(f"📍 Location: {filepath}:{line_num}")
                print(f"📝 Content: {line_content.strip()}\n")
                self.blocked_actions.add(key)
            else:
                print(f"⚠️ {severity.upper()} ALERT: {issue_type} detected in {filepath}:{line_num}")
                print(f"📝 Content: {line_content.strip()}\n")
    
    def scan_file(self, filepath: Path) -> bool:
        """Scan a single file for security issues with retry logic."""
        if not self._should_scan_file(filepath):
            return True
            
        for attempt in range(config.MAX_RETRIES):
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    
                for i, line in enumerate(lines, 1):
                    # Check all pattern categories
                    for pattern in config.SECURITY_PATTERNS.get_all_patterns():
                        if re.search(pattern, line):
                            self.log_issue(pattern, filepath, i, line)
                
                self.scan_stats['files_scanned'] += 1
                return True
                    
            except Exception as e:
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_DELAY)
                    continue
                self.log_issue("SCAN_ERROR", filepath, 0, f"Error scanning file: {str(e)}")
                return False
    
    def scan_directory(self, root_dir: Path) -> Dict:
        """Scan a directory with enhanced statistics and progress tracking."""
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔍 Starting security scan...")
        
        try:
            root_dir = Path(root_dir)
            files_to_scan = []
            
            # Collect files to scan
            purge_dir = (root_dir / "Purge").resolve()
            for subdir in root_dir.rglob("*"):
                try:
                    resolved = subdir.resolve()
                    # Skip the Purge directory and anything inside it
                    if resolved == purge_dir or purge_dir in resolved.parents:
                        continue
                except Exception:
                    continue
                if subdir.is_file() and self._should_scan_file(subdir):
                    files_to_scan.append(subdir)
            
            # Process files in batches
            total_files = len(files_to_scan)
            if total_files > 0:
                for i in range(0, total_files, config.SCAN_BATCH_SIZE):
                    batch = files_to_scan[i:i + config.SCAN_BATCH_SIZE]
                    for file in batch:
                        self.scan_file(file)
                    print(f"📊 Progress: {min(i + config.SCAN_BATCH_SIZE, total_files)}/{total_files} files scanned")
            else:
                print("📊 No files to scan.")
            
            # Update scan statistics
            self.scan_stats['last_scan'] = datetime.now().isoformat()
            self.scan_stats['issues_found'] = sum(self.issue_counts.values())
            self.scan_stats['critical_issues'] = len(self.critical_issues)
            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Security scan complete.")
            print(f"📊 Scan Statistics:")
            print(f"   Files scanned: {self.scan_stats['files_scanned']}")
            print(f"   Issues found: {self.scan_stats['issues_found']}")
            print(f"   Critical issues: {self.scan_stats['critical_issues']}")
            print(f"   AI instances tracked: {len(self.scan_stats['ai_instances'])}")
            print(f"   Grid security events: {len(self.scan_stats['grid_security_events'])}")
            print(f"   Quantum events: {len(self.scan_stats['quantum_events'])}")
            print(f"   Total runtime: {time.time() - self.start_time:.2f} seconds")
            
            return self.scan_stats
            
        except Exception as e:
            error_msg = f"Failed to scan directory: {str(e)}"
            print(f"💥 {error_msg}")
            logging.error(error_msg)
            return self.scan_stats

# ╭──────────────────────────── Utilities ───────────────────────────────────╮
def ignite_passion(target_dir: Path = None, threshold: int = 3, dry_run: bool = False):
    """Monitor and maintain system integrity."""
    target_dir = target_dir or config.BASE_DIR
    if not target_dir:
        return ["🚨 No target directory specified."]
        
    if not config.INTEGRITY_BASELINE_FILE.exists():
        return ["🚨 No baseline file found. Please run initialization first."]
    
    changed = verify_integrity(target_dir)
    results = []
    if changed:
        results.append("🚨 Passion alert: Your files have changed!")
        for c in changed:
            results.append(f" ⚠️ {c}")
        if len(changed) >= threshold:
            results.append("💔 Too many wounds. Initiating restore...")
            restore_system(dry_run=dry_run)
        else:
            results.append(f"💢 {len(changed)} changes detected, but still tolerable. Watch yourself.")
    else:
        results.append("💓 All is as it should be. Love unbroken.")

    # Optionally: add security scan summary here if you want
    # scanner = SecurityScanner(mode=config.CURRENT_SECURITY_MODE)
    # scan_stats = scanner.scan_directory(target_dir)
    # results.append(f"Scan stats: {scan_stats}")

    return results

def restore_file(path: Path):
    """Restore a file from cloud storage."""
    try:
        # Validate path
        if not path.exists():
            logging.warning(f"Target file {path} does not exist")
            return False
            
        # Check write permissions
        if not os.access(path.parent, os.W_OK):
            logging.error(f"No write permission for directory {path.parent}")
            return False
            
        # Create temporary backup of current file
        temp_backup = path.with_suffix(path.suffix + '.temp')
        try:
            shutil.copy2(path, temp_backup)
            
            # Attempt to restore from cloud storage
            # This is a placeholder for cloud storage integration
            # The actual implementation will depend on the cloud storage solution
            logging.info(f"Attempting to restore {path} from cloud storage")
            
            # For now, we'll just log that we would restore from cloud
            logging.info(f"Would restore {path} from cloud storage")
            
            # Clean up temporary backup
            temp_backup.unlink()
            return True
                
        except Exception as e:
            logging.error(f"Error during restoration of {path}: {e}")
            # Attempt to restore from temporary backup if it exists
            if temp_backup.exists():
                try:
                    shutil.copy2(temp_backup, path)
                except Exception as restore_error:
                    logging.error(f"Failed to restore from temporary backup: {restore_error}")
            return False
            
    except Exception as e:
        logging.error(f"Unexpected error in restore_file: {e}")
        return False
# ───────────────────────────────────────────────────────────────────────────╯