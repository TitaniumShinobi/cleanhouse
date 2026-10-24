<div align="center">
  <img src="/assets/cleanhouse.png" alt="CleanHouse Logo">
</div>

# 🏠 CleanHouse

A local-first observability and evidence platform built with **Python**, **pywebview**, and **Flask** — designed for local process, file, and network observation with registry-aware authentication.

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/TitaniumShinobi/cleanhouse.git
cd cleanhouse
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file in the project root (optional):

```bash
# Optional: Override Chatty API URL for unified user registry
CHATTY_API_URL=http://localhost:5000
```

### 3. Run the Application

**Canonical operator runtime path:**
```bash
/bin/bash scripts/cleanhouse-up.sh
```

Then open your browser to: **http://localhost:3333/overview**

### 3c. Debug-only startup paths

Use these shell functions (from any folder):

```bash
cleanhouse() {
  /bin/bash "/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh" "$@"
}

cleanhouse-raw() {
  /bin/bash "/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-raw.sh" "$@"
}
```

`cleanhouse` is the operator-facing launcher:
- starts/reuses the local app from `127.0.0.1:3333`
- waits for `operator_ready=true` at `http://127.0.0.1:3333/cleanhouse/status`
- requires the explicit readiness contract: healthy state, warm startup, live supervisor/backend, one matching owned listener, fresh heartbeat, successful readiness probe, and no active runtime block
- treats bootstrap timestamps and LaunchAgent persistence as evidence only; neither can make a recovering or degraded runtime ready
- resolves the runtime interpreter deterministically and proves `backend.server` plus its transitive launch imports before supervisor start
- opens `http://localhost:3333/overview`
- prints `cleanhouse is running at http://localhost:3333/overview`

Debug-only paths (non-canonical):

- `cleanhouse-raw` calls `scripts/cleanhouse-raw.sh` directly for terminal-first troubleshooting.
- `python3 desktop/wrapper.py` is attach/debug oriented.
- `python3 -m backend.runtime_supervisor start` is backend-only troubleshooting.

Canonical launcher command (from any folder):

```bash
cd /tmp
/bin/bash "/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-up.sh"
```

If `repo_make_aliases` or `repo_up` rebinds `cleanhouse`/`cleanhouse-raw`, re-source the overlay:

```bash
source /Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/cleanhouse-shell-alias.sh
```

Stable avatar regression gate:

```bash
/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/run-avatar-gate.sh
/Users/devonwoodson/Documents/GitHub/cleanhouse/scripts/run-avatar-gate.sh --artifact-dir /tmp/cleanhouse-avatar-gate
```

The gate runs the avatar receipt regression harness headlessly and exits nonzero on behavioral drift.

### 3b. Production-prep local runbook
```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
CLEANHOUSE_HOST=127.0.0.1 CLEANHOUSE_PORT=3333 python3 desktop/wrapper.py
```

Smoke checks (after launch from a separate shell):
```bash
python3 - <<'PY'
import json
import urllib.request
print("overview:", urllib.request.urlopen("http://127.0.0.1:3333/overview").status)
print("status:", json.loads(urllib.request.urlopen("http://127.0.0.1:3333/cleanhouse/status").read().decode("utf-8")))
PY
```

Normal operator startup opens `/overview`; `/dashboard` remains available for its existing route.
If startup is blocked by an open runtime self-deviation, review the printed evidence and receipt, then run `cleanhouse --acknowledge-self-deviation` for one guarded restart attempt.

Delivery scope for v1: deterministic local install and launch. This is not an auto-update or remote-distribution workflow.

---

## 🔐 Authentication

CleanHouse features a unified authentication system that connects to Chatty's MongoDB user database, ensuring seamless account management across all your applications.

**Supported Authentication Methods:**
- **Email/Password** — Secure password-based authentication
- **OAuth Providers** — Google, Apple, Microsoft (opens in system browser)
- **Unified Registry** — Shared user database with Chatty and VVAULT
- **Local Fallback** — Automatic SQLite fallback if Chatty API unavailable
- **Runtime toggle** — Auth routes are available only when `CLEANHOUSE_ENABLE_AUTH=1`

**Features:**
- Native password manager support (Keychain, 1Password, Bitwarden, etc.)
- Automatic account creation with instant login
- Thread-safe signal handling
- Secure session management

---

## 🗂️ Core Features

### 🔒 Identity & Registry
- **Unified User Registry** — All apps (Chatty, VVAULT, CleanHouse) share the same MongoDB user database
- **Access Control Surface** — Session and permission handling via local auth and token flows
- **Observed process activity** — Process/platform observations reported from `corefiles/collectors/process_monitor.py`
- **Observed file-state activity** — Integrity baseline and hash observations from `corefiles/integrity.py`

### 🧹 File Management
- **File Change Visibility** — File add/modify/delete and hash drift are reported from local scans
- **Optional housekeeping commands** — Available where present in the CleanHouse codebase, not used as security enforcement
- **Backup/restore hooks** — Present as utility paths; runtime behavior remains local and opt-in

### 🧠 Intelligence & Monitoring
- **Zaelith Integration (manual)** — Optional prompt-response review workflow
- **Signal Reporting** — Observed signals and aggregate summaries are surfaced in API outputs
- **Logging Infrastructure** — Comprehensive logging and event auditing
- **Notification System** — Alerts are reports, not enforcement actions
- **Notification visibility rule** — Native delivery metadata is transport evidence; it does not guarantee operator-visible interruption without acknowledgement

### 🌐 WebView Interface
- **Native OS Integration** — Uses pywebview for native desktop experience
- **Responsive UI** — Modern, responsive web-based interface
- **OAuth Browser Flow** — OAuth authentication via system browser when auth routes are enabled
- **Form Validation** — Client-side and server-side validation

## 🧭 Endpoint Boundary (v1)

- v1 behavior is constrained to the `/cleanhouse/*` routes in `backend/api/cleanhouse.py` with no endpoint names removed (for example: `/cleanhouse/status`, `/cleanhouse/processes`, `/cleanhouse/network`, `/cleanhouse/ai-activity`, `/cleanhouse/integrity`, `/cleanhouse/commands`, `/cleanhouse/report`).
- Endpoint claims are observational: they report snapshots, matches, events, and classifications generated by local collectors and adapters (`corefiles/collectors/process_monitor.py`, `corefiles/collectors/agent_movement_monitor.py`, `corefiles/integrity.py`, `corefiles/config.py`, `backend/api/cleanhouse.py`, `backend/api/cleanhouse_monitoring.py`).
- This doc does not claim prevention, policy enforcement, or threat-judgment behavior unless the claim is directly implemented in code.

---

## 🧩 Developer Notes

CleanHouse consists of multiple integrated components:

**Component** | **Location** | **Description**
------------|-------------|----------------
Desktop Launcher | `desktop/wrapper.py` | Primary executable entry path
UI | `ui/` | WebView-based user interface
Backend API | `backend/server.py` | Flask REST API server used by the supervisor-managed runtime
Models | `models/` | Database models and user registry
Access Control | `access_control/` | Permission and session management
Zaelith | `zaelith/` | Optional manual prompt-response review integration

### Tech Stack
- **GUI Framework:** pywebview, Tkinter (fallback)
- **Backend:** Flask, Flask-CORS
- **Database:** MongoDB (unified registry), SQLite (local fallback)
- **Authentication:** JWT, bcrypt, OAuth 2.0
- **Cryptography/Auth helpers:** PyJWT, cryptography, keyring
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
requests>=2.28.0        # HTTP client
python-dotenv>=1.0.0    # Environment variables
```

### Optional Dependencies
```bash
# Optional build/test tooling (not required to run v1)
pyinstaller>=6.6.0
pytest>=7.0.0
pytest-cov>=4.0.0
# matplotlib>=3.5.0      # Data visualization
# dropbox                # Cloud storage integration
# cryptography           # Advanced encryption
# keyring                # Secure credential storage
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
source .venv/bin/activate
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
**Problem:** Port 3333 already in use
**Solution:** Set `CLEANHOUSE_PORT` before starting the supervisor:
```sh
CLEANHOUSE_PORT=3334 python3 -m backend.runtime_supervisor start
```

### Module Not Found Errors
**Problem:** `ModuleNotFoundError: No module named 'flask'`
**Solution:**
```bash
source .venv/bin/activate
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

### Runtime supervision

On macOS, `scripts/cleanhouse-up.sh` installs and starts the current user's
`org.cleanhouse.runtime` LaunchAgent. The launcher can exit while `launchd`
keeps the supervisor alive. Persistence alone is not readiness: the explicit
operator contract still requires healthy/warm state, live process and listener
ownership, a fresh heartbeat, a passing readiness probe, and no active runtime
block. A stale state file or bootstrap timestamp is never sufficient evidence.

### Wazuh agent packaging

The Wazuh `4.14.7` Apple-silicon bundle is vendored locally with its agent
package, corresponding source archive, manifest, upstream license, notices,
and source-compliance record. Vendoring fails closed unless the fixed package
and source SHA-512 pins, exact Wazuh signer and fingerprint, trusted Apple
notarization, and source-archive readability all verify. The separately
reviewed LaunchAgent prerequisite stages the complete shipping closure into its
isolated runtime. Manager deployment, administrator-authorized installation or
enrollment, hosted smoke testing, and VVAULT work remain operator-gated. See
`documents/20_validation/wazuh-agent-packaging.md`.

- **Quick Start:** `QUICK_START.md`
- **Documentation Index:** `docs/README.md`
- **Installation Guide:** `docs/operations/INSTALLATION_GUIDE.md`
- **Authentication System:** `docs/auth/AUTHENTICATION_SYSTEM.md`
- **Comprehensive Summary:** `docs/reports/COMPREHENSIVE_SUMMARY.md`
- **Zaelith Integration:** `docs/operations/ZAELITH_INTEGRATION.md`

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
**Status:** Draft-to-Execution (rubric-scored; see `docs/canon/CLEANHOUSE_RUBRIC.md`)
