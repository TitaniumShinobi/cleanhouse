# CleanHouse Development Recap

## Overview
CleanHouse is a desktop security and file management application built with Python, Tkinter, and pywebview. This document summarizes recent development work and current state.

## Quick Summary (2025-11-09)

### ✅ Recent Achievements
1. **Unified User Registry** - All apps (Chatty, VVAULT, CleanHouse) now share the same MongoDB user database
2. **OAuth Browser Integration** - OAuth opens in system browser (no popup blocking)
3. **Bug Fixes** - Fixed Pathlib serialization, signal handler thread safety, and window closing APIs
4. **Signup Flow** - Complete account creation with automatic login

### 🔧 Current Status
- **Authentication:** Fully functional with unified registry + local fallback
- **OAuth:** Opens in system browser (callback handling pending)
- **User Registry:** Connected to Chatty's MongoDB (with SQLite fallback)
- **Dependencies:** All required packages installed (`requests` added)

### 📋 Quick Start
```bash
cd "/Users/devonwoodson/Documents/GitHub/cleanhouse"
source cleanhouse_env/bin/activate
python3 corefiles/brain.py
```

**Note:** For unified registry, ensure Chatty server is running at `http://localhost:5000`. If not, CleanHouse will use local SQLite fallback.

## Recent Fixes & Improvements

### 1. OAuth Popup Blocking Issue ✅ FIXED
**Problem:** Desktop app showed "Popup blocked. Please allow popups for this site" error when clicking OAuth buttons (Google/Apple/Microsoft).

**Solution:** Changed OAuth flow from popup-based (`window.open()`) to system browser-based authentication. OAuth URLs now open in the user's default browser, which is the standard approach for desktop applications.

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Added `openOAuthUrl()` method that uses Python's `webbrowser` module
  - Updated JavaScript OAuth functions to call Python API instead of `window.open()`
  - Removed popup blocking error messages

**Status:** ✅ Complete - OAuth buttons now open authentication in system browser

---

### 2. Signup Completion Flow ✅ FIXED
**Problem:** After creating an account, users weren't automatically logged in. The signup window would close but the user remained on the login screen.

**Solution:** 
- Modified `createAccount()` method to capture user data and automatically trigger login
- Updated signup form JavaScript to show "Logging you in..." message
- Ensured success callback is called with user data after account creation

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Updated `createAccount()` to store user data and call success callback
  - Added `_pending_user_data` attribute to track account creation
  - Updated signup form submission handler

**Status:** ✅ Complete - Users are now automatically logged in after signup

---

### 3. Signup Link Scrolling Issue ✅ FIXED
**Problem:** Clicking "Don't have an account? Create Account" link would scroll to top of page instead of showing signup form.

**Solution:** 
- Added `event.preventDefault()` to `showSignup()` function
- Added `return false` to onclick handlers
- Fixed both signup and login navigation links

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Updated `showSignup()` function to prevent default link behavior
  - Updated `showLogin()` function similarly
  - Added `return false` to link onclick handlers

**Status:** ✅ Complete - Navigation links now work correctly without scrolling

---

## Latest Updates (2025-11-09)

### 4. Unified User Registry System ✅ IMPLEMENTED
**Problem:** CleanHouse, Chatty, and VVAULT were using separate user databases, causing account fragmentation and signup issues.

**Solution:** Created unified user registry that connects CleanHouse to Chatty's MongoDB user database. All three applications now share the same user registry.

**Implementation:**
- Created `models/unified_user_registry.py` - Client that connects to Chatty's API
- Updated `ui/auth.py` - Uses unified registry for login/signup with local fallback
- Updated `ui/simple_webview_auth.py` - Uses unified registry for account creation
- Added `requests>=2.28.0` to `requirements.txt`

**How It Works:**
1. **Primary:** CleanHouse connects to Chatty's MongoDB via API (`http://localhost:5000/api/auth/`)
2. **Fallback:** If Chatty API unavailable, falls back to local SQLite database
3. **Unified:** All three apps (Chatty, VVAULT, CleanHouse) use the same user database

**Files Modified:**
- `models/unified_user_registry.py` (NEW) - Unified registry client
- `ui/auth.py` - Integrated unified registry with fallback
- `ui/simple_webview_auth.py` - Integrated unified registry
- `requirements.txt` - Added `requests>=2.28.0`

**Status:** ✅ Complete - Unified user registry functional with automatic fallback

---

### 5. Pathlib Serialization Errors ✅ FIXED
**Problem:** pywebview was trying to serialize `Path` objects to JavaScript, causing errors:
```
[pywebview] Error while processing base_dir._drv: 'pathlib.PosixPath' object has no attribute '_drv'
```

**Solution:** Convert `Path` objects to strings immediately in `__init__` to avoid serialization issues.

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Changed `self.base_dir = Path(base_dir)` to `self.base_dir = str(Path(base_dir))`
  - Updated file path operations to convert back to Path when needed

**Status:** ✅ Complete - Pathlib serialization errors resolved

---

### 6. Signal Handler Thread Safety ✅ FIXED
**Problem:** Signal handlers were being set up in non-main threads, causing:
```
ValueError: signal only works in main thread of the main interpreter
```

**Solution:** Made signal handler setup conditional - only runs in main thread, gracefully skips otherwise.

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Updated `_setup_signal_handlers()` to check thread before setting up handlers
  - Added proper exception handling for thread safety

**Status:** ✅ Complete - Signal handlers now thread-safe

---

### 7. WebView Window Closing API ✅ FIXED
**Problem:** Code was calling `webview.destroy_window()` which doesn't exist in current pywebview version.

**Solution:** Added compatibility checks for different pywebview APIs with graceful fallback.

**Files Modified:**
- `ui/simple_webview_auth.py`
  - Updated `cleanup()`, `force_cleanup()`, `showLogin()`, `_on_login_success()`
  - Added `hasattr()` checks for different window closing methods
  - Handles both `window.destroy()` and `webview.destroy_window()` APIs

**Status:** ✅ Complete - Window closing now works across pywebview versions

---

## Technical Architecture

### Authentication System
- **WebView-based UI:** Uses `pywebview` for native OS integration
- **Native Autofill:** Supports password managers (Keychain, 1Password, Bitwarden, etc.)
- **OAuth Support:** Google, Apple, Microsoft (opens in system browser)
- **Account Creation:** Full signup flow with automatic login

### Key Components

#### `ui/simple_webview_auth.py`
Main authentication module with:
- `SimpleWebViewAuth` class - Handles login/signup WebView windows
- `createAccount()` - Creates new user accounts and auto-logs in
- `openOAuthUrl()` - Opens OAuth URLs in system browser
- `showLogin()` / `showSignup()` - Navigation between login/signup views

#### `ui/auth.py`
Backend authentication system:
- `AuthWindow` class - Core auth logic
- `create_account()` - Database account creation
- User service integration

### Dependencies
- `pywebview>=6.0` - WebView GUI framework
- `requests>=2.28.0` - HTTP client for unified registry (REQUIRED)
- `bcrypt>=4.0.0` - Password hashing
- `tkinter` - Standard library GUI (fallback)
- `sqlite3` - Standard library database (fallback)
- Optional: `matplotlib`, `dropbox`, `cryptography`, `keyring` (for advanced features)

---

## Current State

### ✅ Working Features
1. **Unified User Registry:** All apps share same MongoDB database (Chatty, VVAULT, CleanHouse)
2. **Login Flow:** Email/password authentication via unified registry with local fallback
3. **Signup Flow:** Complete account creation via unified registry with automatic login
4. **OAuth Buttons:** Open authentication in system browser (no popup blocking)
5. **Navigation:** Login ↔ Signup switching works correctly
6. **Form Validation:** Email format, password strength, matching passwords
7. **Error Handling:** Clear error messages for failed operations
8. **Automatic Fallback:** Falls back to local SQLite if Chatty API unavailable
9. **Thread Safety:** Signal handlers and WebView operations are thread-safe
10. **Pathlib Compatibility:** Path objects properly handled for pywebview serialization

### 🔧 Known Issues / Future Improvements
1. **OAuth Callback Handling:** Currently OAuth opens in browser but callback handling needs implementation
2. **Guest Mode:** Fallback guest user available when WebView unavailable
3. **Terms/Privacy:** Links exist but content display needs enhancement
4. **Email Verification:** Email verification flow exists but needs configuration

---

## File Structure

```
cleanhouse/
├── ui/
│   ├── simple_webview_auth.py  # Main WebView authentication (RECENTLY MODIFIED)
│   ├── auth.py                  # Backend auth system (RECENTLY MODIFIED)
│   └── ...
├── models/
│   ├── unified_user_registry.py # Unified registry client (NEW)
│   ├── user_model.py            # User data model
│   └── database.py              # Database manager
├── corefiles/
│   └── brain.py                 # Application entry point
├── zaelith/                     # Lie detection system
├── access_control/              # Access control system
├── requirements.txt             # Python dependencies (UPDATED)
├── cleanhouse_env/              # Virtual environment
└── user_auth.db                 # Local SQLite database (fallback)
```

---

## How to Run

1. **Activate virtual environment:**
   ```bash
   cd "/Users/devonwoodson/Documents/GitHub/cleanhouse"
   source cleanhouse_env/bin/activate
   ```

2. **Launch application:**
   ```bash
   python3 corefiles/brain.py
   ```

3. **Test signup flow:**
   - Click "Don't have an account? Create Account"
   - Fill out form (name, email, password, role)
   - Check terms checkbox
   - Click "Create Account"
   - Should automatically log in

---

## Recent Code Changes Summary

### `ui/simple_webview_auth.py`
1. **OAuth Flow (Lines ~526-604):** Changed from popup to system browser
2. **Account Creation (Lines ~1229-1279):** Added auto-login after signup
3. **Navigation Links (Lines ~473, 607-627, 1039, 1205-1216):** Fixed scrolling issues
4. **Pathlib Serialization (Line 41):** Convert Path to string immediately
5. **Signal Handlers (Lines 51-85):** Made thread-safe with main thread check
6. **Window Closing (Lines 1372-1387, 1428-1461):** Added API compatibility checks

### Key Methods Added/Modified:
- `openOAuthUrl(url, provider)` - Opens OAuth in system browser
- `createAccount()` - Now uses unified registry, triggers auto-login
- `showSignup()` - Prevents default link behavior
- `showLogin()` - Prevents default link behavior, fixed window closing
- `_setup_signal_handlers()` - Thread-safe signal handler setup
- `cleanup()` / `force_cleanup()` - Fixed window closing API

### `ui/auth.py`
1. **Unified Registry Integration (Lines 21, 40-44):** Added UnifiedUserRegistry
2. **Login Flow (Lines 293-323):** Uses unified registry with fallback
3. **Signup Flow (Lines 349-380):** Uses unified registry with fallback
4. **Verification Success (Lines 433-447):** Uses unified registry

### `models/unified_user_registry.py` (NEW)
- `UnifiedUserRegistry` class - Connects to Chatty's MongoDB
- `create_user()` - Creates users via Chatty API
- `authenticate_user()` - Authenticates via Chatty API
- `get_user_by_email()` - Queries user by email
- Automatic fallback handling

---

## Current Architecture

### User Registry System
- **Primary:** Unified registry via Chatty API (MongoDB)
- **Fallback:** Local SQLite database (`user_auth.db`)
- **Integration:** All apps (Chatty, VVAULT, CleanHouse) share same user database

### Authentication Flow
1. **Login:** Attempts unified registry → Falls back to local DB if unavailable
2. **Signup:** Creates account in unified registry → Falls back to local DB if unavailable
3. **OAuth:** Opens in system browser (no popup blocking)

### Key Components

#### `models/unified_user_registry.py` (NEW)
- `UnifiedUserRegistry` class - Connects to Chatty's MongoDB
- `create_user()` - Creates users via Chatty API
- `authenticate_user()` - Authenticates via Chatty API
- `get_user_by_email()` - Queries user by email
- Automatic fallback handling

#### `ui/simple_webview_auth.py`
- `SimpleWebViewAuth` class - WebView authentication handler
- `createAccount()` - Creates accounts via unified registry
- `openOAuthUrl()` - Opens OAuth in system browser
- Thread-safe signal handling
- Pathlib-safe serialization

#### `ui/auth.py`
- `AuthWindow` class - Tkinter authentication window
- Integrated with unified registry
- Local database fallback

---

## Dependencies

### Required
- `pywebview>=6.0` - WebView GUI framework
- `requests>=2.28.0` - HTTP client for unified registry
- `bcrypt>=4.0.0` - Password hashing
- `tkinter` - Standard library GUI (fallback)
- `sqlite3` - Standard library database (fallback)

### Optional
- `matplotlib` - Data visualization
- `dropbox` - Cloud storage integration
- `cryptography` - Advanced encryption
- `keyring` - Secure credential storage

---

## Setup & Configuration

### Environment Variables
```bash
# Optional: Override Chatty API URL
CHATTY_API_URL=http://localhost:5000
```

### Prerequisites
1. **Chatty Server** (for unified registry):
   - Should be running at `http://localhost:5000`
   - If not running, CleanHouse falls back to local SQLite

2. **Virtual Environment:**
   ```bash
   source cleanhouse_env/bin/activate
   ```

3. **Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Testing Checklist

### Authentication
- [x] OAuth buttons open in system browser (no popup errors)
- [x] Signup form creates account via unified registry
- [x] Signup auto-logs in after account creation
- [x] Login authenticates via unified registry
- [x] Fallback to local DB when Chatty unavailable
- [x] Navigation links work without scrolling
- [x] Form validation works (email format, password strength)
- [x] Error messages display correctly

### Technical
- [x] Pathlib serialization errors resolved
- [x] Signal handler thread safety fixed
- [x] Window closing API compatibility fixed
- [x] Unified registry connection working
- [x] Local database fallback working

---

## Known Issues & Future Work

### Current Limitations
1. **OAuth Callback Handling:** OAuth opens in browser but callback handling needs implementation
2. **Email Verification:** Email verification flow exists but needs configuration
3. **Terms/Privacy Display:** Links exist but content display needs enhancement

### Future Enhancements
1. **OAuth Callback Server:** Set up local server to handle OAuth redirects
2. **Session Management:** Implement proper session handling after login
3. **Password Reset:** Add forgot password functionality
4. **Multi-Factor Auth:** Add 2FA support
5. **Account Management:** User profile editing, password change

---

## Troubleshooting

### Unified Registry Connection Issues
**Problem:** "Cannot connect to Chatty API"
- **Solution:** Ensure Chatty server is running at `http://localhost:5000`
- **Fallback:** CleanHouse will automatically use local SQLite database

### Pathlib Errors
**Problem:** Path serialization errors in logs
- **Status:** ✅ Fixed - Path objects now converted to strings

### Signal Handler Errors
**Problem:** "signal only works in main thread"
- **Status:** ✅ Fixed - Signal handlers only set up in main thread

### Window Closing Errors
**Problem:** "module 'webview' has no attribute 'destroy_window'"
- **Status:** ✅ Fixed - Added compatibility checks for different APIs

---

**Last Updated:** 2025-11-09
**Status:** ✅ Authentication system functional with unified user registry
**Version:** 1.1.0


