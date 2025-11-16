"""
Desktop wrapper for CleanHouse using pywebview.
Serves the frontend via Flask and displays it in a WebView window.
"""

import threading
import time
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False
    webview = None

from backend.server import app

def start_server():
    """Start Flask server in background thread"""
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True, use_reloader=False)

def main():
    """Launch desktop application"""
    if not WEBVIEW_AVAILABLE:
        print("❌ pywebview not available. Install with: pip install pywebview")
        sys.exit(1)
    
    # Start Flask server in background
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(1)
    
    # Create WebView window
    webview.create_window(
        'CleanHouse - Sign In',
        'http://127.0.0.1:5000/login',
        width=450,
        height=775,
        resizable=True,
        min_size=(450, 550)
    )
    
    # Start WebView
    webview.start(debug=False)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()

