# CleanHouse Evidence Audit

**Repository vs. Canonical Standards Cross-Reference**
*2026-05-22 — Line-cited against every component*

---

## A. Confirmed Implemented

| Component | Citation | Code Location | Verified |
|---|---|---|---|
| Process scan via `ps aux` | Thesis §1 | `corefiles/collectors/process_monitor.py:82-120` | ✅ Runs with `--once` |
| Platform classification (4 platforms, substring) | Thesis §1 | `corefiles/collectors/process_monitor.py:30-47, 123-132` | ✅ VS Code, Cursor, Codex, Gemini Antigravity |
| Agent pattern match on process name | Thesis §1 | `corefiles/collectors/process_monitor.py:50-54, 134-140` | ✅ Regex match against 10 patterns |
| Integrity baseline (SHA-256) | Thesis §2 | `corefiles/integrity.py:223-258` | ✅ Walks dir, hashes, saves JSON |
| Integrity verification (hash diff) | Thesis §2 | `corefiles/integrity.py:294-348` | ✅ Compares current vs baseline |
| Content regex scan (eval, exec, API keys) | Thesis §2 | `corefiles/integrity.py:260-292` | ✅ Matches patterns from `config.py:79-100` |
| Real-time file monitor (threaded) | Thesis §2 | `corefiles/integrity.py:60-153` | ✅ Polls on interval, pushes to Queue |
| Network scan via `lsof` | Thesis §3 | `corefiles/collectors/agent_movement_monitor.py:316-384` | ✅ Runs with `--once` |
| AI API endpoint pattern match | Thesis §3 | `corefiles/collectors/agent_movement_monitor.py:112-118, 359-369` | ✅ Regex match on connection address |
| Platform switch detection (set diff) | Thesis §3 | `corefiles/collectors/agent_movement_monitor.py:386-411` | ✅ Records from/to/timestamp |
| Zaelith regex deception analysis | Thesis Limits | `Zaelith/detector.py:94-211` | ✅ 8 criteria, weighted score, summary grade |
| Flask server + login frontend | Thesis Runtime | `backend/server.py`, `frontend/login.html` | ✅ Serves on port 3333 |
| Auth API (JWT, createAccount, login, OAuth) | Thesis Runtime | `backend/api/auth.py:59-561` | ✅ Disabled by default (`CLEANHOUSE_ENABLE_AUTH=1`) |
| Test files exist | Audit §A | `tests/test_*.py` (4 files, ~55KB total) | ✅ Exist, not executed in this audit |

---

## B. Partially Implemented

| Component | What Works | What's Incomplete | Lines |
|---|---|---|---|
| IntegrityMonitor graph display | Plots 4 subplots | All plots are constant-value lines (`value * len(timestamps)`) — zero variance | `corefiles/integrity.py:163-199` |
| UI scan results counter | Displays files_scanned and issues_found | Increments per output line, not per file scanned. Issues counter triggers on any line containing substring "issue" or "error" | `ui/hooks.py:152-161` |
| Performance monitoring | Reads CPU% and memory via psutil | Tied to tkinter event loop (`.after(5000)`). No headless/CLI fallback | `ui/hooks.py:269-298` |
| Agent movement log output | Writes JSON to file | Default path uses workspace root, not `~/.cleanhouse/`. Falls back to `results/` dir if it exists | `corefiles/collectors/agent_movement_monitor.py:136-141` |
| User data isolation (scan history, prefs) | Full CRUD methods for user-scoped data | Requires `self.user_manager` — only available after tkinter auth. Dead code outside tkinter | `ui/hooks.py:440-503` |

---

## C. Fragmented

| Capability | Files | Problem |
|---|---|---|
| "ignite_passion" (integrity scan entry point) | `corefiles/passion.py:245-273`, `ui/hooks.py:36-55`, `ui/main.py:371-388` | Three implementations. `corefiles/passion.py` calls `verify_integrity()` directly. `ui/hooks.py` imports from `corefiles.passion` AND separately calls `verify_integrity()`. `ui/main.py` has its own standalone method. |
| Platform/agent definitions | `corefiles/collectors/process_monitor.py:30-54`, `corefiles/collectors/agent_movement_monitor.py:42-118` | Two separate copies. `corefiles/collectors/process_monitor.py` has 10 agent patterns. `corefiles/collectors/agent_movement_monitor.py` has 3 categories (process: 10, file: 6, network: 14). The Gemini Antigravity entry in `corefiles/collectors/agent_movement_monitor.py:83-98` references app paths that do not exist. |
| Integrity baseline storage | `corefiles/config.py:34` → `~/Documents/CleanHouse/Logs/integrity_baseline.json`. Project root also has `integrity_baseline.json` pointing at `C:\MockDirtyHouse\` | Two baseline files with different content. One references a Windows mock directory. |
| Log storage destinations | `config.py:27` → `~/Documents/CleanHouse/Logs/`. `brain.py:58` → project `logs/`. Other modules use Python default logging | Four different log destinations. No shared log configuration. |
| OAuth flow | `backend/api/auth.py:173-393`, `ui/simple_webview_auth.py:75-119`, `frontend/js/api-client.js:57-67` | Three OAuth implementations: server-side token exchange, local HTTP callback server for pywebview, dual-mode JS client. All must be kept in sync. |

---

## D. Placeholder

| Component | File | What It Claims | What It Actually Does |
|---|---|---|---|
| Cloud file restore | `corefiles/passion.py:293-299` | Restore file from cloud | `logging.info("Would restore {path} from cloud storage")` — no-op |
| Unauthorized sessions counter | `corefiles/integrity.py:71` | Track unauthorized sessions | Integer `0`, never incremented anywhere |
| Integrity restorations counter | `corefiles/integrity.py:72` | Track file restorations | Integer `0`, never incremented |
| Cloud uploads counter | `corefiles/integrity.py:73` | Track cloud sync | Integer `0`, never incremented |
| "Unauthorized Sessions" graph | `corefiles/integrity.py:185-186` | Show unauthorized sessions over time | Flat line at 0 (counter never changes) |
| `restore_system()` call | `corefiles/passion.py:261-262` | Restore all changed files | Function does not exist — would raise `NameError` at runtime |
| `config/` directory | `config/__init__.py` | User-facing configuration | Empty `__init__.py` (33 bytes) |
| OAuth client IDs | `.env:18-23` | Microsoft, Apple, GitHub integration | All use `your-*-client-id` — no real credentials |
| Directory history | `config/directory_history.json` (implied by `layout.py:773`) | Persist recent target directories | File does not exist |

---

## E. Deprecated

| Component | Reason | Lines |
|---|---|---|
| tkinter UI (`ui/main.py`, `ui/layout.py`, `ui/hooks.py`) | `ModuleNotFoundError: No module named '_tkinter'` on Python 3.14 Homebrew. Entire tree crashes at import. | `ui/main.py:8` |
| `ui/simple_webview_auth.py` | Imports `tkinter` at module level (line 7). Same `_tkinter` crash. Contains 2000+ lines of duplicated inline HTML/JS duplicating `frontend/` files. | `simple_webview_auth.py:7`, lines 471-2700+ |
| `cleanup_report.json` / `cleanup_log.txt` | References `C:\Users\woods\...` — Windows paths from another machine. Stale cleanup artifact from Oct 2025. | Root of repo |
| `integrity_baseline.json` (root) | Points to `C:\MockDirtyHouse\` — Windows test data. All hashes are either empty-file hash or from non-existent directory. | Root of repo |
| `backend/utils/csrf.py` / `jwt_utils.py` | Auth routes disabled by default (`CLEANHOUSE_ENABLE_AUTH=1`). Code exists but feature intentionally off. | `backend/api/auth.py:init` |
| Two `brain.py` files | `corefiles/brain.py` (431 lines, main launcher) + `Zaelith/brain.py` (119 lines, CLI deception tool) | Same name, different purposes, different directories |

---

## F. Missing

| Requirement | Origin | What's Absent | Impact |
|---|---|---|---|
| Entry point command | Rubric §5 (MVP), §10 (E.1) | No `setup.py`, `pyproject.toml`, `__main__.py`, console_scripts | **Blocking** — `cleanhouse` is not runnable as a command |
| Unified log schema | Rubric §8 | No shared LogEntry class or dict template | Each module formats logs differently |
| Config file for patterns | Rubric §9 (D.3) | All platform/agent patterns hardcoded in Python dicts | Every pattern change requires a code edit |
| Tests for regex patterns | Rubric §9 (D.4) | `tests/` exists but no test exercises `corefiles/collectors/process_monitor.py` or `corefiles/collectors/agent_movement_monitor.py` patterns | Pattern changes cannot be regression-tested |
| User-visible confidence markers | Rubric §6 | No observation includes "matched pattern X" language. UI says "Protected" unconditionally | User cannot distinguish "nothing seen" from "nothing wrong" |
| `--once` on integrity module | Rubric §9 (D.4) | `corefiles/integrity.py` has no CLI entry point | Integrity verification has no single-shot mode |
| Fails-closed with specific error | Rubric §10 (E.2) | `simple_webview_auth.py:358-368` falls back to guest mode on pywebview failure | Silent fallback masks the actual error |

---

## G. Overclaimed

| Claim | Location | What Code Actually Does | Gap |
|---|---|---|---|
| **UI status "Protected"** | `ui/layout.py:55` | Default string value, never verified. Only changes during specific operations | Status implies enforcement that does not exist |
| **"Quantum-resistant hash"** | `corefiles/integrity.py:39-57` | Combines SHA-3-512 + BLAKE2b + SHA-256 | Algorithm name is misleading. "Quantum-resistant" is a property claim, not an implementation property. No post-quantum key exchange. |
| **"Unauthorized sessions"** | `corefiles/integrity.py:71` | Integer `0`, never incremented | Label implies detection mechanism that does not exist |
| **"Integrity restorations"** | `corefiles/integrity.py:72` | Integer `0`, never incremented. `restore_file()` is a no-op. `restore_system()` is undefined | Label implies recovery mechanism that does not exist |
| **`[AGENT]` tag on processes** | `corefiles/collectors/process_monitor.py:173` | Substring matches against "copilot", "agent", "intellisense", "lsp" in process command line | Tags any process whose command contains these strings. Not agent detection — it's text matching. |
| **"AI assistant processing request"** | `corefiles/collectors/agent_movement_monitor.py:373-379` | Network address contains strings like "cursor", "claude", "gpt" | Infers AI request from address pattern. A DNS lookup to cursor.com triggers this. |
| **"Deception Analysis"** | `ui/layout.py:552-694`, `Zaelith/detector.py:94-211` | Regex matching against hardcoded phrases ("as you know", "...", "is there anything else I can help") | Heuristic pattern matching with weighted scoring. Not psycholinguistic deception detection. 3 hardcoded facts for incongruence. |
| **"European Electronic Communications Code Disclosure"** | Referenced in `simple_webview_auth.py:3685-3686` | Opens a markdown file for an EU directive | Compliance theater — local-first tool with no data transmission has no reason to reference this directive |

---

## H. Runtime Verification

| Command | Result | Detail |
|---|---|---|
| `python -m corefiles.collectors.process_monitor --once` | ✅ | Parses `ps aux`, classifies platforms, exits |
| `python -m corefiles.collectors.agent_movement_monitor --once` | ✅ | 3 scans (process, file, network), writes JSON, exits |
| `./cleanhouse_env/bin/python backend/server.py` | ✅ | Flask on port 3333, auth routes disabled |
| `./cleanhouse_env/bin/python desktop/wrapper.py` (import) | ✅ | Loads, warns auth disabled, would open window on display |
| `./cleanhouse_env/bin/python Zaelith/brain.py` | ✅ | CLI deception analysis, multi-line input, report output |
| `python ui/main.py` | ❌ | `_tkinter: ModuleNotFoundError` |
| `python ui/simple_webview_auth.py` | ❌ | `_tkinter: ModuleNotFoundError` at line 7 |
| `cleanhouse` (bare) | ❌ | Command not found — no entry point |

---

## I. Next-Gap Analysis (Ranked by Impact)

1. **No entry point.** Add `__main__.py` dispatching to `corefiles/collectors/process_monitor.py`, `corefiles/collectors/agent_movement_monitor.py`, or `backend/server.py`. Zero-dependency fix, unblocks the `cleanhouse` command.

2. **tkinter blocks pywebview auth.** `ui/simple_webview_auth.py:7` imports `tkinter` at module level. Fix: defer the import to inside the methods that use it, or remove tkinter dependency from the auth module.

3. **No unified `monitor` command.** Three observability modules cannot run together. Add a dispatcher that starts all three in threads with a shared output format.

4. **Duplicated platform definitions.** `corefiles/collectors/process_monitor.py` and `corefiles/collectors/agent_movement_monitor.py` have separate copies. Extract to `corefiles/config.py`.

5. **`restore_system()` undefined.** `corefiles/passion.py:262` calls `restore_system(dry_run=dry_run)` — function does not exist. Would raise `NameError` if threshold exceeded.
