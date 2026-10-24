# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - integrity.py
#  File integrity and security monitoring.
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────────── Imports ──────────────────────────────────╮
import hashlib, os, json, shutil
from pathlib import Path
import sys
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import time
import threading
from queue import Queue

# Optional GUI imports - not required for core functionality
try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import tkinter as tk
    from tkinter import ttk
    GUI_AVAILABLE = True
except ImportError:
    # Create dummy classes for missing imports
    class FigureCanvasTkAgg:
        pass
    GUI_AVAILABLE = False

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import config
# ───────────────────────────────────────────────────────────────────────────╯

# ╭──────────────────────────── Quantum Security ────────────────────────────╮
class QuantumResistantHash:
    def __init__(self):
        self.hash_functions = [
            hashlib.sha3_512,  # Post-quantum resistant
            hashlib.blake2b,   # Post-quantum resistant
            hashlib.sha256     # Fallback
        ]

    def compute_hash(self, data: bytes) -> str:
        """Compute a quantum-resistant hash using multiple algorithms."""
        hashes = []
        for hash_func in self.hash_functions:
            hasher = hash_func()
            hasher.update(data)
            hashes.append(hasher.hexdigest())
        return "::".join(hashes)

# Initialize quantum-resistant hasher
quantum_hasher = QuantumResistantHash()

# ╭──────────────────────────── Real-time Monitor ───────────────────────────╮
class IntegrityMonitor:
    def __init__(self, root_dir: Path, interval: int = 5):
        self.root_dir = root_dir
        self.interval = interval
        self.running = False
        self.monitor_thread = None
        self.change_queue = Queue()
        self.last_check = {}
        self.activity_log = []
        self.stats = {
            'files_scanned': 0,
            'timestamps': []
        }
        self._initialize_baseline()

    def _initialize_baseline(self):
        """Initialize the baseline for real-time monitoring."""
        for path in self.root_dir.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    with open(path, 'rb') as f:
                        self.last_check[str(path)] = quantum_hasher.compute_hash(f.read())
                except Exception as e:
                    logging.error(f"Failed to initialize baseline for {path}: {e}")

    def start_monitoring(self):
        """Start real-time integrity monitoring."""
        if self.running:
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def stop_monitoring(self):
        """Stop real-time integrity monitoring."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                current_time = datetime.now()
                self.stats['timestamps'].append(current_time)

                for path in self.root_dir.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        try:
                            with open(path, 'rb') as f:
                                current_hash = quantum_hasher.compute_hash(f.read())
                                path_str = str(path)

                                if path_str in self.last_check:
                                    if current_hash != self.last_check[path_str]:
                                        self.change_queue.put(("modified", path))
                                        self.activity_log.append({
                                            'timestamp': current_time,
                                            'type': 'file_modified',
                                            'path': path_str
                                        })
                                else:
                                    self.change_queue.put(("new", path))
                                    self.activity_log.append({
                                        'timestamp': current_time,
                                        'type': 'new_file',
                                        'path': path_str
                                    })

                                self.last_check[path_str] = current_hash
                                self.stats['files_scanned'] += 1

                        except Exception as e:
                            logging.error(f"Error monitoring {path}: {e}")
                            self.activity_log.append({
                                'timestamp': current_time,
                                'type': 'error',
                                'message': f"Error monitoring {path}: {e}"
                            })

                time.sleep(self.interval)
            except Exception as e:
                logging.error(f"Error in monitor loop: {e}")
                self.activity_log.append({
                    'timestamp': current_time,
                    'type': 'error',
                    'message': f"Error in monitor loop: {e}"
                })
                time.sleep(self.interval)

    def get_activity_log(self, limit: int = 100) -> List[Dict]:
        """Get recent activity log entries."""
        return self.activity_log[-limit:]

    def get_stats(self) -> Dict:
        """Get current monitoring statistics."""
        return self.stats

    def update_graphs(self, canvas):
        """Update monitoring graphs."""
        if not GUI_AVAILABLE:
            return

        try:
            fig = canvas.figure
            fig.clear()

            # Only render metrics backed by runtime data.
            ax1 = fig.add_subplot(111)  # Files Scanned

            # Plot data
            timestamps = [t.strftime('%H:%M:%S') for t in self.stats['timestamps']]

            ax1.plot(timestamps, [self.stats['files_scanned']] * len(timestamps), 'b-')
            ax1.set_title('Files Scanned')
            ax1.tick_params(axis='x', rotation=45)

            fig.tight_layout()
            if hasattr(canvas, 'draw'):
                canvas.draw()

        except Exception as e:
            logging.error(f"Error updating graphs: {e}")

# ╭──────────────────────────── Utilities ───────────────────────────────────╮
def hash_file(path: Path) -> str:
    """Generate quantum-resistant hash of a file."""
    try:
        # Skip symlinks and special files
        if not path.is_file() or path.is_symlink():
            return None

        # Skip the baseline file itself
        if path == config.INTEGRITY_BASELINE_FILE:
            return None

        # Read file in chunks to handle large files
        with open(path, 'rb') as f:
            return quantum_hasher.compute_hash(f.read())
    except Exception as e:
        logging.error(f"Failed to hash file {path}: {str(e)}")
        return None

def generate_baseline(root_dir: Path) -> None:
    """Generate initial integrity baseline."""
    try:
        # Validate root directory
        root_dir = Path(root_dir)
        if not root_dir.exists():
            raise ValueError(f"Target directory does not exist: {root_dir}")
        if not root_dir.is_dir():
            raise ValueError(f"Target path is not a directory: {root_dir}")

        baseline = {}

        # Walk through directory
        for path in root_dir.rglob("*"):
            if path.is_file():
                try:
                    # Calculate hash
                    file_hash = hash_file(path)
                    if file_hash:  # Only add if hash was successful
                        baseline[str(path.relative_to(root_dir))] = file_hash
                        logging.info(f"Added {path} to baseline")

                except Exception as e:
                    logging.error(f"Error processing {path}: {e}")
                    continue

        # Save baseline to centralized location
        config.INTEGRITY_BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.INTEGRITY_BASELINE_FILE, 'w') as f:
            json.dump(baseline, f, indent=2)

        logging.info(f"Successfully generated baseline for {root_dir}")

    except Exception as e:
        logging.error(f"Failed to generate baseline: {e}")
        raise

def scan_file_security(file_path: Path) -> List[str]:
    """Scan a single file for security issues."""
    issues = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

            # Check for API keys and credentials
            for pattern in config.SECURITY_PATTERNS.ai_specific:
                if re.search(pattern, content, re.IGNORECASE):
                    issues.append(f"Potential API key or credential exposure in {file_path}")

            # Check for behavioral patterns
            for pattern in config.SECURITY_PATTERNS.behavioral:
                if re.search(pattern, content, re.IGNORECASE):
                    issues.append(f"Potential security bypass attempt in {file_path}")

            # Check for basic security issues
            for pattern in config.SECURITY_PATTERNS.basic_security:
                if re.search(pattern, content, re.IGNORECASE):
                    issues.append(f"Potential security vulnerability in {file_path}")

            # Check for custom patterns
            for category, patterns in config.SECURITY_PATTERNS.custom_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        issues.append(f"Custom security issue ({category}) in {file_path}")

    except Exception as e:
        issues.append(f"Error scanning {file_path}: {str(e)}")

    return issues

def verify_integrity(root_dir: Path) -> List[str]:
    """Verify file integrity and security of all files in directory."""
    changes = []
    security_issues = []

    # Initialize real-time monitor if not already running
    if not hasattr(verify_integrity, 'monitor'):
        verify_integrity.monitor = IntegrityMonitor(root_dir)
        verify_integrity.monitor.start_monitoring()

    # Check for real-time changes
    while not verify_integrity.monitor.change_queue.empty():
        change_type, path = verify_integrity.monitor.change_queue.get()
        if change_type == "modified":
            changes.append(f"Modified: {path}")
        elif change_type == "new":
            changes.append(f"New file: {path}")

    # Load baseline
    if config.INTEGRITY_BASELINE_FILE is None:
        raise ValueError("INTEGRITY_BASELINE_FILE is not set!")
    if not Path(config.INTEGRITY_BASELINE_FILE).exists():
        return ["No baseline found. Run generate_baseline first."]

    try:
        with open(config.INTEGRITY_BASELINE_FILE, 'r') as f:
            baseline = json.load(f)
    except Exception as e:
        return [f"Error loading baseline: {str(e)}"]

    def should_scan_file(file_path: Path) -> bool:
        """Determine if a file should be scanned based on security mode."""
        if file_path.suffix not in config.SCANNABLE_EXTENSIONS:
            return False

        if not config.SCANNABLE_EXTENSIONS[file_path.suffix]:
            return False

        # Skip files in whitelist
        for whitelist_dir in config.WHITELIST:
            if whitelist_dir in file_path.parts:
                return False

        return True

    def check_directory(directory: Path):
        """Recursively check directory for changes and security issues."""
        try:
            for item in directory.iterdir():
                if item.is_file():
                    rel_path = str(item.relative_to(root_dir))

                    # Skip baseline file (by path or name)
                    if item == config.INTEGRITY_BASELINE_FILE or item.name == config.INTEGRITY_BASELINE_FILE.name:
                        continue

                    # Check file integrity
                    if rel_path in baseline:
                        current_hash = hash_file(item)
                        if current_hash != baseline[rel_path]:
                            changes.append(f"File modified: {rel_path}")
                    else:
                        changes.append(f"New file detected: {rel_path}")

                    # Check file security
                    if should_scan_file(item):
                        issues = scan_file_security(item)
                        if issues:
                            security_issues.extend(issues)

                elif item.is_dir():
                    check_directory(item)

        except Exception as e:
            changes.append(f"Error checking directory {directory}: {str(e)}")

    # Start checking
    check_directory(root_dir)

    # Log security issues
    if security_issues:
        log_security_issues(security_issues)

    # Return a summary
    if not changes and not security_issues:
        return ["No integrity or policy signals observed."]
    return changes + security_issues


def scan_integrity(root_dir: Optional[Path] = None) -> dict:
    """One-shot integrity scan against existing baseline.

    Returns dict with keys:
        status: "ok" | "no_baseline" | "error"
        baseline_path: str
        files_scanned: int
        baseline_count: int
        changes: list of {rel_path, change_type, baseline_hash, current_hash}
        security_issues: list of str
        scan_timestamp: ISO 8601 string
    """
    root_dir = Path(root_dir if root_dir is not None else Path.cwd())
    baseline_path = config.INTEGRITY_BASELINE_FILE
    now = datetime.now().isoformat()

    if not baseline_path or not Path(baseline_path).exists():
        return {
            "status": "no_baseline",
            "baseline_path": str(baseline_path) if baseline_path else "",
            "files_scanned": 0,
            "baseline_count": 0,
            "changes": [],
            "security_issues": [],
            "scan_timestamp": now,
        }

    try:
        with open(baseline_path) as f:
            baseline: Dict[str, str] = json.load(f)
    except Exception as e:
        return {
            "status": "error",
            "baseline_path": str(baseline_path),
            "files_scanned": 0,
            "baseline_count": 0,
            "changes": [],
            "security_issues": [],
            "scan_timestamp": now,
            "error": str(e),
        }

    changes: List[Dict[str, Any]] = []
    security_issues: List[str] = []
    seen: Set[str] = set()

    for path in root_dir.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path == baseline_path:
            continue
        rel_path = str(path.relative_to(root_dir))
        seen.add(rel_path)

        current_hash = hash_file(path)
        if rel_path in baseline:
            if current_hash is None:
                continue
            if current_hash != baseline[rel_path]:
                changes.append({
                    "rel_path": rel_path,
                    "change_type": "modified",
                    "baseline_hash": baseline[rel_path],
                    "current_hash": current_hash,
                })
        else:
            changes.append({
                "rel_path": rel_path,
                "change_type": "new",
                "baseline_hash": None,
                "current_hash": current_hash,
            })

        if path.suffix in config.SCANNABLE_EXTENSIONS:
            issues = scan_file_security(path)
            if issues:
                security_issues.extend(issues)

    for rel_path in baseline:
        if rel_path not in seen:
            changes.append({
                "rel_path": rel_path,
                "change_type": "missing",
                "baseline_hash": baseline[rel_path],
                "current_hash": None,
            })

    return {
        "status": "ok",
        "baseline_path": str(baseline_path),
        "files_scanned": len(seen),
        "baseline_count": len(baseline),
        "changes": changes,
        "security_issues": security_issues,
        "scan_timestamp": now,
    }


def log_security_issues(issues: List[str]):
    """Log security issues to the security log file."""
    try:
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "issues": issues
        }

        with open(config.SECURITY_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"Error logging security issues: {str(e)}")

def get_security_summary() -> Dict[str, int]:
    """Get a summary of security issues by category."""
    summary = {
        "api_keys": 0,
        "behavioral": 0,
        "basic_security": 0,
        "custom": 0
    }

    try:
        with open(config.SECURITY_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                entry = json.loads(line)
                for issue in entry["issues"]:
                    if "API key" in issue or "credential" in issue:
                        summary["api_keys"] += 1
                    elif "bypass" in issue or "security" in issue:
                        summary["behavioral"] += 1
                    elif "vulnerability" in issue:
                        summary["basic_security"] += 1
                    else:
                        summary["custom"] += 1
    except Exception as e:
        print(f"Error getting security summary: {str(e)}")

    return summary

def verify_whitelist_integrity(base_dir: Path, whitelist: list, hash_db: Path, logger=None) -> None:
    """Verify integrity of whitelisted projects."""
    try:
        if not Path(hash_db).exists():
            msg = "⚠️  No checksum baseline found."
            print(msg)
            if logger:
                logger.warning(msg)
            return

        with open(hash_db, 'r') as f:
            baseline = json.load(f)

        for proj in whitelist:
            proj_path = base_dir / proj
            if not proj_path.exists():
                msg = f"❌ {proj} → Missing entirely."
                print(msg)
                if logger:
                    logger.warning(f"{proj} is missing from system.")
                continue

            modified = []
            # Only process regular files, skip symlinks and special files
            for file in proj_path.rglob("*"):
                try:
                    if file.is_file() and not file.is_symlink():
                        # Convert paths to strings for comparison
                        file_str = str(file)
                        current_hash = hash_file(file)
                        stored_hash = baseline.get(file_str, None)
                        if stored_hash and current_hash != stored_hash:
                            modified.append(file)
                except Exception as e:
                    if logger:
                        logger.error(f"Failed to process file {file}: {str(e)}")
                    continue

            if modified:
                print(f"🟥 {proj} → {len(modified)} tampered file(s):")
                for file in modified:
                    msg = f"   ⚠️  {file}"
                    print(msg)
                    if logger:
                        logger.warning(f"{proj} - File changed: {file}")
            else:
                print(f"🟩 {proj} → Clean")

    except Exception as e:
        error_msg = f"Failed to verify whitelist integrity: {str(e)}"
        print(f"💥 {error_msg}")
        if logger:
            logger.error(error_msg)
# ───────────────────────────────────────────────────────────────────────────╯
