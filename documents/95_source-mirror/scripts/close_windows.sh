#!/bin/bash
# Script to close all CleanHouse windows and processes

echo "Closing CleanHouse windows and processes..."

# Kill Python processes running brain.py
pkill -f "python.*brain.py" 2>/dev/null && echo "✓ Closed brain.py processes"

# Kill webview processes
pkill -f "webview" 2>/dev/null && echo "✓ Closed webview processes"

# Kill any Python processes that might be CleanHouse
killall -9 Python 2>/dev/null && echo "✓ Closed Python processes"

# Use osascript to close CleanHouse windows via AppleScript
osascript -e 'tell application "System Events" to tell (every process whose name contains "CleanHouse") to quit' 2>/dev/null && echo "✓ Closed CleanHouse windows"

echo "Done! All CleanHouse windows should be closed."
