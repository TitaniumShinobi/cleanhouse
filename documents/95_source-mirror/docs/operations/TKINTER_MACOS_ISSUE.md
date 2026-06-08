# Tkinter macOS Compatibility Issue

## Problem

CleanHouse GUI fails to launch on macOS 15.x with the error:
```
macOS 15 (1507) or later required, have instead 15 (1506) !
```

This is a **system-level tkinter/Tcl/Tk compatibility issue**, not a CleanHouse bug.

## Root Cause

The Tcl/Tk libraries bundled with Python on macOS 15.x have a version check that incorrectly parses the macOS version, causing a fatal crash when creating tkinter windows.

## Solutions

### ✅ Option 1: Use CLI Mode (Recommended)

CleanHouse works perfectly in CLI mode without requiring tkinter:

```bash
python3 corefiles/brain.py --monitor
```

### ✅ Option 2: Use Backend Server (Web Interface)

Run CleanHouse as a web server and access it via browser:

```bash
python3 backend/server.py
```

Then visit: http://localhost:5000/login

### ⚠️ Option 3: Fix Tcl/Tk Installation

Try updating Tcl/Tk (may not resolve the issue):

```bash
brew install python-tk
```

Or use Homebrew Python:

```bash
brew install python@3.11
/opt/homebrew/bin/python3.11 corefiles/brain.py
```

### ⚠️ Option 4: Wait for System Update

This is often resolved by:
- macOS system updates
- Python/tkinter updates
- Tcl/Tk library updates

## Current Status

- ✅ **CLI Mode**: Fully functional
- ✅ **Backend Server**: Fully functional
- ❌ **GUI Mode**: Blocked by macOS/tkinter issue

## Testing

To test if tkinter works on your system:

```bash
python3 -c "import tkinter; root = tkinter.Tk(); root.destroy(); print('Works!')"
```

If this crashes, tkinter is incompatible with your macOS version.

## Related Issues

- macOS 15.x tkinter compatibility issues
- Tcl/Tk version checking on macOS
- Python tkinter on macOS 15.x
