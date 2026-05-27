# CleanHouse Frontend

This directory contains the extracted frontend files (HTML/CSS/JS) for CleanHouse authentication.

## Structure

```
frontend/
├── login.html          # Login page
├── signup.html         # Signup page
├── css/
│   └── auth.css       # Shared authentication styles
└── js/
    └── auth.js        # Shared authentication JavaScript
```

## Development

### Browser Testing
Open `login.html` or `signup.html` directly in a browser for testing.

### With Backend
The backend API should be running on `http://localhost:3333` for full functionality.

## Notes

- These files were extracted from `ui/simple_webview_auth.py`
- The JavaScript uses `window.pywebview.api` for desktop integration
- For web deployment, replace `window.pywebview.api` calls with HTTP fetch calls
