# CleanHouse Logging - Quick Start Guide

## Usage

### Normal Mode (INFO level)
```bash
python3 corefiles/brain.py
```

### Verbose Mode (DEBUG level - shows everything)
```bash
python3 corefiles/brain.py --verbose
```

## What You'll See

### Console Output (Simple Format)
```
12:54:23 PM [INFO] CleanHouse - Starting GUI...
12:54:24 PM [INFO] [UI] WebView started - login UI should now be visible
12:54:30 PM [INFO] [OAUTH] Opening Google authentication in your browser...
```

### Log File (Detailed Format)
Location: `~/Documents/CleanHouse/Logs/cleanhouse.log`

```
[2025-11-13 12:54:23] INFO [cleanhouse:134] CleanHouse - Starting GUI...
[2025-11-13 12:54:24] INFO [ui.simple_webview_auth:293] [UI] WebView started - login UI should now be visible
[2025-11-13 12:54:30] INFO [ui.simple_webview_auth:2945] [OAUTH] Opening google authentication in native system browser
```

## Log Prefixes

- `[UI]` - UI component events
- `[MAIN]` - Main application flow
- `[OAUTH]` - OAuth authentication
- `[JS]` - JavaScript bridge
- `[CLICK]`, `[INPUT]`, etc. - User interactions

## Viewing Logs

```bash
# Watch logs in real-time
tail -f ~/Documents/CleanHouse/Logs/cleanhouse.log

# Search for OAuth issues
grep "OAUTH" ~/Documents/CleanHouse/Logs/cleanhouse.log

# Search for errors
grep "ERROR" ~/Documents/CleanHouse/Logs/cleanhouse.log
```

