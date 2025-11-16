# CleanHouse Installation Guide

## Overview

CleanHouse has been successfully modularized and now launches from `corefiles/brain.py`. However, there's a common issue on macOS where tkinter (required for the GUI) isn't available in virtual environments.

## Installation Steps

### 1. Install Core Dependencies

The core dependencies have been installed in your virtual environment:

```bash
source cleanhouse_env/bin/activate
pip install -r requirements-core.txt
```

### 2. GUI Launch Options

Due to tkinter limitations on macOS, you have several options to launch the GUI:

#### Option A: Use System Python (Recommended)
```bash
# Deactivate virtual environment first
deactivate

# Launch GUI with system Python
python3 corefiles/brain.py
```

#### Option B: Install tkinter for Virtual Environment
```bash
# Install tkinter support (if available)
brew install python-tk

# Then try launching
source cleanhouse_env/bin/activate
python3 corefiles/brain.py
```

#### Option C: Use Alternative Python Installation
```bash
# Install Python with tkinter support
brew install python@3.11

# Use the specific Python version
/opt/homebrew/bin/python3.11 corefiles/brain.py
```

## Current Status

✅ **Modular UI Architecture**: Complete and working
✅ **Brain.py Integration**: Fully functional
✅ **Core Dependencies**: Installed successfully
✅ **CLI Mode**: Working (no GUI required)
⚠️ **GUI Mode**: Requires tkinter (see options above)

## Testing the Installation

### Test CLI Mode (No GUI Required)
```bash
python3 corefiles/brain.py --monitor
```

### Test GUI Mode (Requires tkinter)
```bash
python3 corefiles/brain.py
```

## Troubleshooting

### Common Issues

1. **"No module named '_tkinter'"**
   - This is expected in virtual environments on macOS
   - Use system Python or install tkinter support

2. **"Module not found" errors**
   - Make sure you're in the CleanHouse directory
   - Check that all core dependencies are installed

3. **Import errors**
   - Ensure the virtual environment is activated for core dependencies
   - Use system Python for GUI launch

## File Structure

The modular UI is organized as follows:

```
ui/
├── __init__.py          # Exports CleanHouseUI
├── main.py              # Main CleanHouseUI class
├── layout.py            # UI layout and styling
├── events.py            # Event handling
├── hooks.py             # Business logic integration
├── widgets/             # Custom UI components
└── assets/              # Images and icons
```

## Next Steps

1. **For Development**: Use the virtual environment for core dependencies
2. **For GUI**: Use system Python to launch the GUI
3. **For Production**: Consider using a different Python distribution with tkinter support

## Alternative Launch Methods

If you prefer to avoid the tkinter issue entirely, you can:

1. **Use CLI Mode**: `python3 corefiles/brain.py --monitor`
2. **Direct Import**: Import and use CleanHouse functions programmatically
3. **Docker**: Use a containerized environment with tkinter support

The modular architecture is complete and ready for use!
