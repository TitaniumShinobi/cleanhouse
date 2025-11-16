# CleanHouse Frontend - Quick Start Guide

## Prerequisites

Make sure Flask is installed:
```bash
source cleanhouse_env/bin/activate
pip install flask flask-cors
```

## Running the Server

### Option 1: Browser Testing (Recommended for Development)
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
source cleanhouse_env/bin/activate
python3 backend/server.py
```

Then open your browser to: **http://localhost:5000/login**

### Option 2: Desktop App
```bash
cd /Users/devonwoodson/Documents/GitHub/cleanhouse
source cleanhouse_env/bin/activate
python3 desktop/wrapper.py
```

## What You'll See

- **Login Page**: http://localhost:5000/login
- **Signup Page**: http://localhost:5000/signup
- **API Endpoints**: http://localhost:5000/api/auth/*

## Troubleshooting

### ModuleNotFoundError: No module named 'flask'
```bash
source cleanhouse_env/bin/activate
pip install flask flask-cors
```

### Port 5000 already in use
Change the port in `backend/server.py`:
```python
app.run(host='127.0.0.1', port=5001, ...)  # Use different port
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

