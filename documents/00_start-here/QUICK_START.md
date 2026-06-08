# CleanHouse Frontend - Quick Start Guide

## Prerequisites

Create one local environment and install the runtime dependencies:
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Server

### Canonical Operator Runtime
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
/bin/bash scripts/cleanhouse-up.sh
```

This resolves the interpreter deterministically, starts the supervised runtime, waits for readiness, and opens: **http://localhost:3333/dashboard**

### Debug-Only Startup Paths (Non-Canonical)

Desktop wrapper:
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
source .venv/bin/activate
python3 desktop/wrapper.py
```

Backend-only path:
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
source .venv/bin/activate
python3 -m backend.runtime_supervisor start
```

## What You'll See

- **Login Page**: http://localhost:3333/login
- **Signup Page**: http://localhost:3333/signup
- **API Endpoints**: http://localhost:3333/api/auth/* (only when `CLEANHOUSE_ENABLE_AUTH=1`)

## Troubleshooting

### ModuleNotFoundError: No module named 'flask'
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Port 3333 already in use
Set `CLEANHOUSE_PORT` before starting the supervisor:
```sh
CLEANHOUSE_PORT=3334 python3 -m backend.runtime_supervisor start
```

### Frontend files not found
Make sure you've run the extraction scripts:
```bash
python3 scripts/extract_frontend.py
python3 scripts/separate_css_js.py
```

## Development Tips

- **Hot Reload**: Just refresh your browser after making changes
- **Debugging**: Use browser DevTools (F12) for console, network, etc.
- **API Testing**: Use browser console or Postman to test `/api/auth/*` endpoints

## Notification Probe (Canonical)

```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
python3 -m scripts.native_notification_runtime_probe --output /tmp/cleanhouse-native-notification-probe.json
```

Check the probe artifact for:

- `native_delivery_result.status`
- local `evidence_refs`
- deep-link `click_url` fields
- cooldown/burst suppression metadata

Delivery metadata is transport evidence and is not guaranteed OS-visible interruption proof by itself.
