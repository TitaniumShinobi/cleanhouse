# ──────────────────────────────────────────────────────────────────────────────
#  CleanHouse - brain.py
#  Alternative entry point for CleanHouse (launches GUI).
#  Devon • 2025‑10‑20
# ──────────────────────────────────────────────────────────────────────────────

import logging
import time
from pathlib import Path
import sys
import os
import signal
import threading
import argparse

# Setup logger BEFORE any other imports that might log
logger = logging.getLogger("cleanhouse")
logger.setLevel(logging.INFO)  # Default level, can be changed by --verbose

# Load environment variables from .env file (must be first!)
try:
    from dotenv import load_dotenv
    base_dir = Path(__file__).parent.parent
    env_file = base_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"Loaded environment variables from {env_file}")
    else:
        # Try current directory as fallback
        load_dotenv()
        logger.debug("Attempted to load .env from current directory")
except ImportError:
    logger.warning("python-dotenv not installed. Environment variables must be set manually.")

def setup_paths():
    """Setup Python paths for imports."""
    base_dir = Path(__file__).parent.parent
    paths_to_add = [
        str(base_dir), 
        str(base_dir / "corefiles"),
        str(base_dir / "ui"),
        str(base_dir / "models"),
        str(base_dir / "access_control")
    ]
    for path in paths_to_add:
        if path not in sys.path:
            sys.path.append(path)

def setup_logging(verbose: bool = False):
    """
    Setup comprehensive logging for CleanHouse.
    
    Args:
        verbose: If True, set log level to DEBUG for detailed output
    """
    log_dir = Path.home() / "Documents" / "CleanHouse" / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cleanhouse.log"
    
    # Determine log level
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Create formatters
    # Detailed format with module name and line number for file logs
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Simple format for console (like Chatty - faithful, with timestamps, no emojis)
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%I:%M:%S %p'
    )
    
    # File handler with detailed format
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    
    # Console handler with simple format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger (this will propagate to all child loggers)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # Clear any existing handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Configure cleanhouse logger (inherits from root, no need to add handlers again)
    logger.setLevel(log_level)
    # Don't add handlers to logger - it will use root logger's handlers via propagation
    
    logger.info("=" * 60)
    logger.info("CleanHouse logging initialized")
    logger.info(f"Log level: {logging.getLevelName(log_level)}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Verbose mode: {verbose}")
    logger.info("=" * 60)

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        """Handle SIGINT (Ctrl+C) and SIGTERM signals."""
        print("\n🛑 CleanHouse shutdown requested...")
        logging.info(f"Received signal {signum}, initiating graceful shutdown")
        
        # Set a flag to indicate shutdown is requested
        global shutdown_requested
        shutdown_requested = True
        
        # Give a moment for cleanup
        time.sleep(0.5)
        
        # Force exit if needed
        print("✅ CleanHouse terminated.")
        sys.exit(0)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Global flag for shutdown state
    global shutdown_requested
    shutdown_requested = False

def check_authentication():
    """Check if user is authenticated by reading token file."""
    try:
        cleanhouse_root = Path.home() / '.cleanhouse'
        auth_token_file = cleanhouse_root / '.auth_token'
        auth_user_file = cleanhouse_root / '.auth_user.json'
        
        if not auth_token_file.exists():
            logger.warning("No authentication token found. User must authenticate via web interface.")
            return None
        
        # Read token
        token = auth_token_file.read_text(encoding='utf-8').strip()
        
        # Verify token
        try:
            setup_paths()  # Ensure paths are set up for imports
            from backend.utils.jwt_utils import verify_jwt_token, get_user_from_token
            user_data = get_user_from_token(token)
            
            if user_data:
                # Load user data from file if available
                user_info = user_data
                if auth_user_file.exists():
                    import json
                    try:
                        file_user_data = json.loads(auth_user_file.read_text(encoding='utf-8'))
                        user_info = file_user_data
                    except Exception as e:
                        logger.warning(f"Could not load user data from file: {e}, using token data")
                
                logger.info(f"User authenticated: {user_info.get('email', 'unknown')}")
                return {
                    'token': token,
                    'user': user_info
                }
            else:
                logger.warning("Authentication token is invalid or expired.")
                # Clean up invalid token
                auth_token_file.unlink(missing_ok=True)
                auth_user_file.unlink(missing_ok=True)
                return None
        except ImportError as e:
            logger.warning(f"Could not verify token (JWT utils not available): {e}")
            # If we can't verify, still allow launch but log warning
            if auth_user_file.exists():
                import json
                try:
                    user_info = json.loads(auth_user_file.read_text(encoding='utf-8'))
                    logger.info(f"Using stored user data (token verification unavailable): {user_info.get('email', 'unknown')}")
                    return {
                        'token': token,
                        'user': user_info
                    }
                except Exception:
                    pass
            return None
        
    except Exception as e:
        logger.error(f"Error checking authentication: {e}", exc_info=True)
        return None

def launch_gui():
    """Launch the CleanHouse GUI."""
    logger.info("=" * 60)
    logger.info("CleanHouse - Starting GUI...")
    logger.info("Press Ctrl+C to terminate CleanHouse")
    logger.info("=" * 60)
    
    # Check authentication
    auth_data = check_authentication()
    if auth_data:
        logger.info(f"Authenticated as: {auth_data['user'].get('email', 'unknown')}")
    else:
        logger.warning("Not authenticated. Some features may be limited.")
        logger.info("To authenticate, visit http://127.0.0.1:5000/login in your browser")
    
    try:
        logger.debug("Setting up Python paths...")
        setup_paths()
        logger.debug("Python paths configured")
        
        logger.info("Importing CleanHouseUI...")
        from ui import CleanHouseUI
        logger.info("CleanHouseUI imported successfully")
        
        logger.info("Creating CleanHouseUI instance...")
        # Pass auth data to UI if available
        app = CleanHouseUI(auth_data=auth_data if auth_data else None)
        logger.info("CleanHouseUI instance created successfully")
        
        # Set up signal handling for the GUI
        def gui_signal_handler(signum, frame):
            """Handle signals in GUI mode."""
            logger.warning(f"Received signal {signum} in GUI mode - initiating shutdown")
            
            # Close the GUI gracefully
            try:
                logger.debug("Quitting GUI application...")
                app.quit()
                app.destroy()
                logger.info("GUI closed successfully")
            except Exception as e:
                logger.error(f"Error during GUI shutdown: {e}", exc_info=True)
            
            logger.info("CleanHouse GUI terminated")
            sys.exit(0)
        
        # Set up signal handlers for GUI
        signal.signal(signal.SIGINT, gui_signal_handler)
        signal.signal(signal.SIGTERM, gui_signal_handler)
        logger.debug("Signal handlers configured for GUI")
        
        logger.info("Starting GUI mainloop...")
        app.mainloop()
        logger.info("GUI mainloop ended")
        
    except ImportError as e:
        logger.error(f"Failed to import GUI: {e}", exc_info=True)
        print(f"❌ Failed to import GUI: {e}")
        print("\n💡 Solutions:")
        print("  1. Use virtual environment:")
        print("     source cleanhouse_env/bin/activate")
        print("     python3 corefiles/brain.py")
        print("  2. Install dependencies in system Python:")
        print("     pip3 install -r requirements-core.txt")
        print("     python3 corefiles/brain.py")
        print("  3. Use CLI mode (no GUI required):")
        print("     python3 corefiles/brain.py --monitor")
        return False
    except Exception as e:
        logger.error(f"GUI startup failed: {e}", exc_info=True)
        print(f"❌ Failed to start GUI: {e}")
        return False
    
    return True

def cli_monitor(target_dir: Path | None = None, interval: int = 30, dry_run: bool = True):
    """Simple CLI monitoring mode (optional)."""
    if not target_dir:
        target_dir = Path.cwd()
    
    print(f"🔍 CleanHouse - CLI Monitor")
    print(f"Target: {target_dir}")
    print(f"Interval: {interval} seconds")
    print(f"Mode: {'Dry Run' if dry_run else 'Active'}")
    print("\nPress Ctrl+C to stop monitoring...\n")

    # Set up signal handlers for CLI mode
    setup_signal_handlers()

    try:
        while True:
            # Check if shutdown was requested
            if 'shutdown_requested' in globals() and shutdown_requested:
                print("\n✅ Monitoring stopped (shutdown requested).")
                break
                
            # Basic file count monitoring
            files = list(target_dir.rglob("*.py"))
            print(f"[{time.strftime('%H:%M:%S')}] Monitoring {len(files)} Python files...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n✅ Monitoring stopped.")

def main():
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='CleanHouse - Security & File Management',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging (DEBUG level)'
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Run in CLI monitoring mode'
    )
    parser.add_argument(
        '--target',
        type=Path,
        default=None,
        help='Target directory for monitoring mode'
    )
    
    args = parser.parse_args()
    
    # Setup logging with verbose flag
    setup_logging(verbose=args.verbose)
    
    logger.info("CleanHouse brain initialized")
    logger.debug(f"Command line arguments: {sys.argv}")
    logger.debug(f"Parsed arguments: {vars(args)}")
    
    # Set up signal handlers for the main process
    setup_signal_handlers()
    logger.debug("Signal handlers configured")
    
    # Route to appropriate mode
    if args.monitor:
        # CLI monitoring mode
        target = args.target if args.target else Path.cwd()
        logger.info(f"Starting CLI monitor mode (target: {target})")
        cli_monitor(target)
    else:
        # Default: launch GUI
        logger.info("Launching GUI mode...")
        success = launch_gui()
        if not success:
            logger.error("GUI launch failed")
            print("\n💡 Alternative: Use 'python3 ui.py' to launch GUI directly")

if __name__ == "__main__":
    main()