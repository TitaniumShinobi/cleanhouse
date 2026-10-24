#!/usr/bin/env python3
"""
Cleanup script for WebView processes
Use this if CleanHouse doesn't close properly
"""

import subprocess
import platform
import sys

def cleanup_webview_processes():
    """Clean up any remaining WebView processes."""
    print("🧹 Cleaning up WebView processes...")

    try:
        if platform.system() == 'Darwin':  # macOS
            # Kill WebView-related processes
            processes_to_kill = [
                'webview',
                'WebKit',
                'Safari',
                'Python',
                'CleanHouse'
            ]

            for process in processes_to_kill:
                try:
                    result = subprocess.run(['pkill', '-f', process], capture_output=True)
                    if result.returncode == 0:
                        print(f"✅ Killed {process} processes")
                    else:
                        print(f"ℹ️  No {process} processes found")
                except Exception as e:
                    print(f"⚠️  Error killing {process}: {e}")

            print("✅ WebView cleanup completed")

        else:
            print("ℹ️  This script is designed for macOS")

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")

if __name__ == "__main__":
    cleanup_webview_processes()

