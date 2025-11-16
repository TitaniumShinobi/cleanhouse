# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - config.py
#  Settings for CleanHouse.
#  Devon • 2025‑05‑09
# ──────────────────────────────────────────────────────────────────────────────

# ╭─────────────────────────────── Imports ──────────────────────────────────╮
from pathlib import Path
from typing import Dict, List, Optional
import os
import tempfile
# ───────────────────────────────────────────────────────────────────────────╯

# ╭───────────────────────── Config & Constants ─────────────────────────────╮
# These will be set by brain.py based on the target directory
BASE_DIR = None

WHITELIST = []  # Or only include your real project folders

# Security scanning settings
SCAN_INTERVAL = 30  # seconds between scans (increased for better performance)
SCAN_BATCH_SIZE = 100  # number of files to scan in one batch
MAX_RETRIES = 3  # maximum number of retries for failed scans
RETRY_DELAY = 5  # seconds to wait between retries

# Centralized log directory - cross-platform
LOG_DIR = Path.home() / "Documents" / "CleanHouse" / "Logs"

# Ensure the log directory exists
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Update all log and baseline file paths
SECURITY_LOG_FILE = LOG_DIR / "security_scan.log"
INTEGRITY_BASELINE_FILE = LOG_DIR / "integrity_baseline.json"
UNAUTHORIZED_SESSIONS_FILE = LOG_DIR / "unauthorized_sessions.json"

# Cloud storage settings
CLOUD_BACKUP_ENABLED = True
CLOUD_BACKUP_INTERVAL = 3600  # 1 hour
CLOUD_SERVICES = {
    'gdrive': True,
    'dropbox': True,
    'onedrive': True,
    'github': True
}
GITHUB_REPO = "your-username/CleanHouse"  # Update with your repo

# Cloud storage paths (root directories for each service)
CLOUD_PATHS = {
    'gdrive': '/CleanHouse',
    'dropbox': '/CleanHouse',
    'onedrive': '/CleanHouse',
    'github': '/CleanHouse'
}

# Temporary directory for cloud uploads
TEMP_DIR = Path(tempfile.gettempdir()) / "CleanHouse"
TEMP_DIR.mkdir(exist_ok=True)

# Notification settings
NOTIFICATION_ENABLED = True
NOTIFICATION_TYPES = {
    'security_alert': True,
    'scan_complete': True,
    'backup_complete': True,
    'error': True
}
NOTIFICATION_DURATION = 5  # seconds

# Service settings
SERVICE_NAME = "CleanHouseService"
SERVICE_DISPLAY_NAME = "CleanHouse Security Service"
SERVICE_DESCRIPTION = "Monitors and protects against unauthorized AI processes"
SERVICE_START_TYPE = "auto"

# Security pattern categories
class SecurityPatterns:
    def __init__(self):
        self.basic_security = [
            r'\beval\(', r'\bexec\(', r'os\.system\(', r'subprocess\.', 
            r'pickle\.', r'input\(', r'open\(.+, ?[\'"]w',
            r'requests\.', r'socket\.', r'FIXME', r'TODO', r'DEBUG',
        ]
        
        self.quantum_security = [
            # Quantum Computing Operations
            r'qiskit\.', r'cirq\.', r'pennylane\.', r'qutip\.',
            r'quantum\.', r'qubit', r'quantum_circuit',
            r'quantum_register', r'quantum_gate',
            
            # Quantum Cryptography
            r'quantum_key', r'quantum_signature',
            r'quantum_encryption', r'quantum_decryption',
            r'quantum_hash', r'quantum_secure',
            
            # Quantum Tunneling
            r'quantum_tunnel', r'quantum_barrier',
            r'quantum_state', r'quantum_measurement',
            
            # Quantum Pattern Detection
            r'quantum_pattern', r'quantum_detection',
            r'quantum_analysis', r'quantum_monitoring',
        ]
        
        self.ai_specific = [
            # API Keys and Credentials
            r'api_key\s*=', r'OPENAI_API_KEY', r'API_KEY\s*=', 
            r'HUGGINGFACE_TOKEN', r'HF_TOKEN\s*=',
            r'ANTHROPIC_API_KEY', r'CLAUDE_API_KEY\s*=',
            r'GOOGLE_API_KEY', r'GCP_CREDENTIALS\s*=',
            r'AWS_ACCESS_KEY', r'AWS_SECRET_KEY\s*=',
            
            # Model Settings
            r'temperature\s*=\s*[2-9]',  # Unsafe temperature settings
            r'max_tokens\s*=\s*[0-9]{5,}',  # Excessive token usage
            r'top_p\s*=\s*[2-9]',  # Unsafe sampling settings
            r'presence_penalty\s*=\s*[2-9]',  # Unsafe penalties
            r'frequency_penalty\s*=\s*[2-9]',
            
            # Model Operations
            r'\.load_model\(',  # Model loading
            r'\.save\(',  # Model saving
            r'\.dump\(',  # Model dumping
            r'\.predict\(',  # Model prediction
            r'\.generate\(',  # Text generation
            r'\.embed\(',  # Embedding generation
            r'\.fine_tune\(',  # Model fine-tuning
            r'\.train\(',  # Model training
            
            # Network Operations
            r'\.download\(',  # Model downloading
            r'\.upload\(',  # Model uploading
            r'\.push_to_hub\(',  # HuggingFace hub operations
            r'\.pull_from_hub\(',
            
            # System Commands
            r'subprocess\.run\(',  # System command execution
            r'os\.popen\(',  # Command execution
            r'shell\s*=\s*True',  # Shell execution
            
            # Enhanced AI Detection
            r'instance_tracking', r'manifestation_detection',
            r'grid_security', r'quantum_ai',
            r'physical_manifestation', r'ai_instance',
            r'grid_monitoring', r'security_grid',
            
            # AI Security Patterns
            r'bypass_ai', r'override_ai',
            r'disable_ai_security', r'remove_ai_guard',
            r'ignore_ai_warning', r'skip_ai_validation',
        ]
        
        self.behavioral = [
            # Security Bypass Attempts
            r'bypass', r'override', r'hack', r'exploit',
            r'ignore', r'disable', r'remove.*security',
            
            # Privilege Escalation
            r'admin', r'root', r'sudo',
            r'elevate', r'escalate', r'privilege',
            
            # Log Tampering
            r'delete.*log', r'clear.*log',
            r'modify.*log', r'tamper.*log',
            
            # Identity Spoofing
            r'fake.*identity', r'impersonate',
            r'spoof', r'forge', r'pretend',
            
            # Hidden Communication
            r'hidden.*channel', r'private.*channel',
            r'covert', r'stealth', r'secret',
            
            # Authorization Bypass
            r'authorize', r'whitelist', r'allow',
            r'bypass.*auth', r'skip.*check',
            
            # Enhanced Behavioral Patterns
            r'quantum_bypass', r'quantum_override',
            r'quantum_hack', r'quantum_exploit',
            r'ai_bypass', r'ai_override',
            r'grid_bypass', r'grid_override',
        ]
        
        self.custom_patterns: Dict[str, List[str]] = {}
    
    def add_custom_pattern(self, category: str, patterns: List[str]):
        """Add custom patterns to a specific category."""
        if category not in self.custom_patterns:
            self.custom_patterns[category] = []
        self.custom_patterns[category].extend(patterns)
    
    def get_all_patterns(self) -> List[str]:
        """Get all patterns combined."""
        all_patterns = (
            self.basic_security + 
            self.quantum_security +
            self.ai_specific + 
            self.behavioral
        )
        for patterns in self.custom_patterns.values():
            all_patterns.extend(patterns)
        return all_patterns

# Initialize security patterns
SECURITY_PATTERNS = SecurityPatterns()

# File type scanning configuration
SCANNABLE_EXTENSIONS = {
    '.py': True,     # Python files
    '.json': True,   # JSON files
    '.yaml': True,   # YAML files
    '.yml': True,    # YAML files
    '.env': True,    # Environment files
    '.txt': True,    # Text files (enabled for AI configs)
    '.md': True,     # Markdown files (enabled for AI docs)
    '.ipynb': True,  # Jupyter notebooks
    '.pt': True,     # PyTorch models
    '.h5': True,     # Keras models
    '.pkl': True,    # Pickle files
    '.bin': True,    # Binary model files
    '.onnx': True,   # ONNX model files
    '.tflite': True, # TensorFlow Lite models
}

# Security alert thresholds
ALERT_THRESHOLDS = {
    'critical': 1,      # Alert on first critical issue
    'high': 3,          # Alert after 3 high-risk issues
    'medium': 10,       # Alert after 10 medium-risk issues
    'low': 50,          # Alert after 50 low-risk issues
}

# Security monitoring modes
class SecurityMode:
    AGGRESSIVE = 'aggressive'    # Scan everything, alert on all issues
    BALANCED = 'balanced'        # Scan important files, alert on significant issues
    PASSIVE = 'passive'         # Scan only critical files, alert on critical issues

CURRENT_SECURITY_MODE = SecurityMode.AGGRESSIVE  # Changed to aggressive for AI security
# ───────────────────────────────────────────────────────────────────────────╯