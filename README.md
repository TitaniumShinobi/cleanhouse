<div align="center">
  <img src="/assets/cleanhouse.png" alt="CleanHouse Logo">
</div>

# 🏠 CleanHouse

A desktop security and file management application built with **Python**, **pywebview**, and **Flask** — designed for secure authentication, file cleanup, integrity monitoring, and unified user management across your digital workspace.

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/TitaniumShinobi/cleanhouse.git
cd cleanhouse
python3 -m venv cleanhouse_env
source cleanhouse_env/bin/activate
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file in the project root (optional):

```bash
# Optional: Override Chatty API URL for unified user registry
CHATTY_API_URL=http://localhost:5000
```

### 3. Run the Application

**Desktop App (Recommended):**
```bash
source cleanhouse_env/bin/activate
python3 corefiles/brain.py
```

**Browser Testing (Development):**
```bash
source cleanhouse_env/bin/activate
python3 backend/server.py
```

Then open your browser to: **http://localhost:5000/login**

---

## 🔐 Authentication

CleanHouse features a unified authentication system that connects to Chatty's MongoDB user database, ensuring seamless account management across all your applications.

**Supported Authentication Methods:**
- **Email/Password** — Secure password-based authentication
- **OAuth Providers** — Google, Apple, Microsoft (opens in system browser)
- **Unified Registry** — Shared user database with Chatty and VVAULT
- **Local Fallback** — Automatic SQLite fallback if Chatty API unavailable

**Features:**
- Native password manager support (Keychain, 1Password, Bitwarden, etc.)
- Automatic account creation with instant login
- Thread-safe signal handling
- Secure session management

---

## 🗂️ Core Features

### 🔒 Security & Access Control
- **Unified User Registry** — All apps (Chatty, VVAULT, CleanHouse) share the same MongoDB user database
- **Access Control System** — Granular permissions and session management
- **Integrity Monitoring** — Real-time file and system integrity checks
- **Security Scanning** — Automated security audits and threat detection

### 🧹 File Management
- **Smart Cleanup** — Automated file organization and cleanup
- **Backup Management** — Secure backup and restore functionality
- **Storage Monitoring** — Track disk usage and file changes
- **Purge Operations** — Safe file deletion with integrity checks

### 🧠 Intelligence & Monitoring
- **Zaelith Integration** — Advanced lie detection and behavioral analysis
- **Signal Validation** — Monitor and validate system signals
- **Logging Infrastructure** — Comprehensive logging and audit trails
- **Notification System** — Real-time alerts and system notifications

### 🌐 WebView Interface
- **Native OS Integration** — Uses pywebview for native desktop experience
- **Responsive UI** — Modern, responsive web-based interface
- **OAuth Browser Flow** — Secure OAuth authentication via system browser
- **Form Validation** — Client-side and server-side validation

---

## 🧩 Developer Notes

CleanHouse consists of multiple integrated components:

**Component** | **Location** | **Description**
------------|-------------|----------------
Brain | `corefiles/brain.py` | Main application entry point
UI | `ui/` | WebView-based user interface
Backend API | `backend/server.py` | Flask REST API server
Models | `models/` | Database models and user registry
Access Control | `access_control/` | Permission and session management
Zaelith | `zaelith/` | Advanced detection and analysis

### Tech Stack
- **GUI Framework:** pywebview, Tkinter (fallback)
- **Backend:** Flask, Flask-CORS
- **Database:** MongoDB (unified registry), SQLite (local fallback)
- **Authentication:** JWT, bcrypt, OAuth 2.0
- **Security:** PyJWT, cryptography, keyring
- **Logging:** Python logging with file rotation

---

## 📋 Requirements

### Required Dependencies
```bash
pywebview>=6.0          # WebView GUI framework
flask>=3.0.0            # Web framework
flask-cors>=6.0.0       # CORS support
bcrypt>=4.0.0           # Password hashing
PyJWT>=2.8.0            # JWT tokens
requests>=2.28.0        # HTTP client (unified registry)
python-dotenv>=1.0.0    # Environment variables
```

### Optional Dependencies
```bash
matplotlib>=3.5.0      # Data visualization
dropbox                # Cloud storage integration
cryptography           # Advanced encryption
keyring                # Secure credential storage
```

---

## 🔧 Configuration

### Unified User Registry

CleanHouse connects to Chatty's MongoDB for unified user management:

1. **Primary:** Connects to Chatty API at `http://localhost:5000/api/auth/`
2. **Fallback:** Automatically falls back to local SQLite (`user_auth.db`) if Chatty unavailable
3. **Integration:** All apps (Chatty, VVAULT, CleanHouse) share the same user database

**Note:** For unified registry, ensure Chatty server is running. If not, CleanHouse will use local SQLite fallback.

### Environment Variables

```bash
# Optional: Override Chatty API URL
CHATTY_API_URL=http://localhost:5000

# Optional: Database configuration
DATABASE_URL=sqlite:///user_auth.db
```

---

## 🧪 Testing

### Run Tests

```bash
source cleanhouse_env/bin/activate
pytest tests/
```

### Manual Testing Checklist

- [x] OAuth buttons open in system browser (no popup errors)
- [x] Signup form creates account via unified registry
- [x] Signup auto-logs in after account creation
- [x] Login authenticates via unified registry
- [x] Fallback to local DB when Chatty unavailable
- [x] Navigation links work without scrolling
- [x] Form validation works (email format, password strength)
- [x] Error messages display correctly

---

## 🐛 Troubleshooting

### Unified Registry Connection Issues
**Problem:** "Cannot connect to Chatty API"  
**Solution:** Ensure Chatty server is running at `http://localhost:5000`  
**Fallback:** CleanHouse will automatically use local SQLite database

### Port Already in Use
**Problem:** Port 5000 already in use  
**Solution:** Change the port in `backend/server.py`:
```python
app.run(host='127.0.0.1', port=5001, ...)
```

### Module Not Found Errors
**Problem:** `ModuleNotFoundError: No module named 'flask'`  
**Solution:**
```bash
source cleanhouse_env/bin/activate
pip install -r requirements.txt
```

### Frontend Files Not Found
**Problem:** Frontend files missing  
**Solution:** Run extraction scripts:
```bash
python3 scripts/extract_frontend.py
python3 scripts/separate_css_js.py
```

---

## 📚 Documentation

- **Quick Start:** `QUICK_START.md`
- **Installation Guide:** `INSTALLATION_GUIDE.md`
- **Authentication System:** `AUTHENTICATION_SYSTEM.md`
- **Comprehensive Summary:** `COMPREHENSIVE_SUMMARY.md`
- **Zaelith Integration:** `ZAELITH_INTEGRATION.md`

---

## 🧬 Credits

Built and maintained by Devon Allen Woodson  
Design, architecture, and framework extensions by Katana Systems

© 2025 Woodson & Associates / WRECK LLC  
All rights reserved.

---

## 📝 License

See `LICENSE` file for details.

---

**Version:** 1.1.0  
**Last Updated:** 2025-11-16  
**Status:** ✅ Production Ready

