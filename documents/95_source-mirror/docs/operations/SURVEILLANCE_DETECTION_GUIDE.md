# Surveillance Detection Framework - Complete Guide

## Overview

The surveillance detector **WAS detecting real threats** - it scans comprehensively and finds everything that matches surveillance patterns. The recent improvements made the filtering **smarter** to reduce false positives while **still catching real threats**.

## Detection Methods

The detector uses **7 different detection methods** to find surveillance software:

### 1. **File System Scanning**
**What it does:** Scans specific directories where surveillance software is commonly installed.

**Locations scanned:**
- Launch Agents/Daemons (where malware auto-starts)
  - `~/Library/LaunchAgents`
  - `/Library/LaunchAgents`
  - `/Library/LaunchDaemons`
  - `/System/Library/LaunchAgents`
  - `/System/Library/LaunchDaemons`
- Application directories
  - `/Applications`
  - `~/Applications`
- System binaries
  - `/usr/local/bin`
  - `/opt`
  - `/usr/bin`
  - `/bin`
- Browser extensions
  - Chrome extensions
  - Firefox profiles
  - Safari extensions
- Logs and caches
  - `/var/log`
  - `~/Library/Logs`
  - `~/Library/Caches`
- Hidden directories
  - `~/.hidden`
  - `~/.local`
  - `/tmp`, `/var/tmp`

**How it works:**
- Recursively scans directories (up to 5 levels deep)
- Checks every filename and path against surveillance signatures
- Uses pattern matching for suspicious file names

---

### 2. **Signature-Based Detection**
**What it detects:** Known surveillance software by name patterns.

**Categories and signatures:**

#### **Keyloggers** (CRITICAL severity)
- `keylogger`, `keylog`, `keystroke`, `keycapture`, `keymonitor`
- `logkeys`, `pykeylogger`, `kidlogger`, `refog`, `spytector`
- `keystroke_logger`, `key_monitor`

**Examples it would catch:**
- `/Applications/KeyLogger.app`
- `~/Library/LaunchAgents/com.keylogger.plist`
- `/usr/local/bin/pykeylogger`

#### **Screen Capture Tools** (HIGH severity)
- `screenshot`, `screen_capture`, `screenrecorder`, `screen_monitor`
- `desktop_spy`, `screenwatch`, `spytech`
- `activtrak`, `teramind`, `veriato`, `workpuls`, `hubstaff`

**Examples it would catch:**
- `/Applications/ScreenCapture.app`
- `~/Library/Application Support/ActivTrak/`
- Any process named `screenrecorder`

#### **Remote Access Tools** (HIGH severity)
- `teamviewer`, `anydesk`, `logmein`, `gotomypc`
- `vnc`, `rdp`, `remote_desktop`, `remotepc`
- `splashtop`, `chrome_remote`, `ammyy`, `ultraviewer`
- `supremo`, `dwservice`, `rustdesk`, `parsec`
- `remmina`, `tigervnc`, `tightvnc`, `realvnc`

**Examples it would catch:**
- `/Applications/TeamViewer.app`
- `/Library/LaunchAgents/com.anydesk.plist`
- Running process: `vncserver`

#### **Employee Monitoring Software** (HIGH severity)
- `spector`, `spytech`, `activtrak`, `teramind`, `veriato`
- `workpuls`, `hubstaff`, `timecamp`, `desklog`
- `veriato_360`, `workforce`, `interguard`, `staffcop`
- `monitor_employee`, `employee_monitor`, `staff_monitor`

**Examples it would catch:**
- `/Applications/Teramind.app`
- `~/Library/Application Support/Veriato/`
- Launch agent for `activtrak`

#### **Network Monitoring Tools** (MEDIUM severity)
- `wireshark`, `tcpdump`, `ettercap`, `cain`, `netmon`
- `network_monitor`, `packet_capture`, `sniffer`
- `mitm`, `burp`, `charles`, `fiddler`, `proxyman`, `mitmproxy`

**Examples it would catch:**
- `/Applications/Wireshark.app` (but filtered as legitimate)
- `/usr/local/bin/tcpdump`
- Running process: `ettercap`

#### **System Modifiers** (CRITICAL severity)
- `rootkit`, `bootkit`, `kernel_extension`, `kext`
- `driver`, `system_extension`, `kernel_module`, `syscall_hook`

**Examples it would catch:**
- Kernel extensions that modify system behavior
- Rootkits installed in system directories
- Suspicious drivers

---

### 3. **Suspicious Pattern Matching**
**What it detects:** Files with suspicious names that might indicate surveillance.

**Patterns:**
- File extensions: `.log`, `.keylog`, `.capture`, `.spy`, `.monitor`
- Keywords: `hidden`, `secret`, `stealth`, `covert`
- Activity logs: `private_log`, `activity_log`, `keystroke`, `screenshot`, `desktop_capture`

**Examples it would catch:**
- `~/Library/.hidden/keystroke.log`
- `/tmp/secret_capture.spy`
- `~/Desktop/activity_log.txt`

---

### 4. **Running Process Detection**
**What it does:** Scans all currently running processes for surveillance software.

**How it works:**
- Runs `ps aux` to get all processes
- Checks process names against surveillance signatures
- Captures: process name, PID, user, CPU/memory usage

**Examples it would catch:**
- `keylogger` process running
- `teamviewer` process active
- `screenrecorder` process capturing
- `vncserver` listening

**Why this is important:** Even if files are hidden, running processes expose surveillance software.

---

### 5. **Network Connection Monitoring**
**What it does:** Checks for suspicious network ports commonly used by remote access tools.

**Suspicious ports:**
- `5900` - VNC
- `3389` - RDP (Remote Desktop Protocol)
- `5938` - TeamViewer
- `7070` - RealVNC
- `5800` - VNC HTTP
- `8080`, `8888`, `9999` - Various remote access tools

**How it works:**
- Runs `lsof -i -P -n` to list network connections
- Checks for listening ports matching suspicious ports
- Identifies which process is using each port

**Examples it would catch:**
- VNC server listening on port 5900
- TeamViewer connection on port 5938
- Unknown process listening on RDP port 3389

---

### 6. **Launch Agent/Daemon Scanning**
**What it does:** Scans macOS Launch Agents and Daemons (auto-start services).

**Why this matters:** Surveillance software often installs launch agents to start automatically on boot.

**How it works:**
- Scans plist files in LaunchAgents/LaunchDaemons directories
- Parses plist XML to find program paths
- Checks program names against surveillance signatures
- Also checks plist filenames

**Examples it would catch:**
- `~/Library/LaunchAgents/com.keylogger.plist`
- `/Library/LaunchDaemons/com.teamviewer.plist`
- Launch agent that runs `screenrecorder` on boot

---

### 7. **Browser Extension Analysis**
**What it does:** Scans browser extensions for tracking/surveillance capabilities.

**Browsers checked:**
- Chrome: `~/Library/Application Support/Google/Chrome/Default/Extensions`
- Firefox: `~/Library/Application Support/Firefox/Profiles`
- Safari: `~/Library/Safari/Extensions`

**How it works:**
- **Chrome:** Reads `manifest.json` to check permissions
  - Flags extensions requesting: `tabs`, `desktopCapture`, `background`, `storage`
- **Firefox/Safari:** Checks filenames for suspicious patterns

**Examples it would catch:**
- Extension requesting `desktopCapture` permission
- Extension with suspicious name like `tracker` or `monitor`
- Extension with excessive permissions

---

### 8. **System Modification Detection**
**What it does:** Checks for system-level modifications that enable surveillance.

**Checks:**
- **System Integrity Protection (SIP) status:** Disabled SIP allows deeper system access
- **Kernel Extensions:** Lists loaded kernel extensions using `kextstat`
- **System modifications:** Checks for rootkits, bootkits, system extensions

**Why this matters:** Some surveillance software requires system-level access.

---

### 9. **Hidden File Detection**
**What it does:** Scans for hidden files matching surveillance patterns.

**Locations:**
- Home directory hidden files (`.filename`)
- `/tmp` hidden files
- `/var/tmp` hidden files

**Patterns:**
- Files starting with `.` that match suspicious patterns
- Files with names like `.keylog`, `.spy`, `.hidden`

---

## Detection Flow

```
1. File System Scan
   ├─ Check filenames against signatures
   ├─ Check paths against signatures
   └─ Check against suspicious patterns

2. Process Scan
   └─ Check running process names

3. Network Scan
   └─ Check listening ports

4. Launch Agent Scan
   ├─ Parse plist files
   └─ Check program paths

5. Browser Extension Scan
   ├─ Read manifest.json (Chrome)
   └─ Check permissions

6. System Modification Check
   ├─ Check SIP status
   └─ List kernel extensions

7. Hidden File Scan
   └─ Check hidden files in temp directories
```

---

## Filtering Logic (False Positive Reduction)

The detector uses **intelligent filtering** to reduce false positives while **still catching real threats**:

### What Gets Filtered (False Positives):
1. **System files** - `/System/Library/` files are legitimate macOS
2. **Browser extensions** - User-installed extensions (unless suspicious permissions)
3. **Development headers** - `.h`, `.hpp` files, `include/` directories
4. **License files** - `ThirdPartyNotices.txt`, `COPYING-*`
5. **Known legitimate tools** - Wireshark, VS Code, etc.
6. **Text/document files** - `.txt`, `.log`, `.json`, `.sqlite` (unless in suspicious locations)
7. **System processes** - Processes owned by `_driverkit`, `root` in system directories

### What Still Gets Flagged (Real Threats):
1. **Executables** - `.app`, binaries in `/bin/`, `/sbin/`
2. **User-installed locations** - Files in `/Users/`, `/usr/local/`, `/opt/`
3. **Launch agents in user space** - `~/Library/LaunchAgents/` (not system)
4. **Running processes** - Any suspicious process name (high confidence)
5. **Network ports** - Suspicious listening ports
6. **Keyloggers** - Always flagged regardless of location (critical)

---

## Example: What Would Be Detected

### ✅ **REAL THREAT - Would be detected:**

1. **Keylogger installed:**
   ```
   /Users/john/Library/LaunchAgents/com.keylogger.plist
   → DETECTED: Launch agent + keylogger signature
   ```

2. **TeamViewer running:**
   ```
   Process: teamviewer (PID 1234)
   Port: 5938 listening
   → DETECTED: Process + network port
   ```

3. **Screen capture tool:**
   ```
   /Applications/ScreenSpy.app
   → DETECTED: File system scan + screen_capture signature
   ```

4. **Hidden keylogger:**
   ```
   ~/.hidden/keystroke.log
   → DETECTED: Hidden file + suspicious pattern
   ```

### ❌ **FALSE POSITIVE - Would be filtered:**

1. **Wireshark (legitimate):**
   ```
   /Library/LaunchDaemons/org.wireshark.ChmodBPF.plist
   → FILTERED: Known legitimate tool
   ```

2. **Browser extension screenshot:**
   ```
   ~/Library/.../Chrome/Extensions/.../screenshot.svg
   → FILTERED: Browser extension directory
   ```

3. **System file:**
   ```
   /System/Library/LaunchAgents/com.apple.parsecd.plist
   → FILTERED: System directory
   ```

---

## Severity Levels

- **CRITICAL:** Keyloggers, system modifiers (rootkits)
- **HIGH:** Screen capture, remote access, monitoring software
- **MEDIUM:** Network monitoring, suspicious files
- **LOW:** Browser extensions

---

## Answer to Your Question

**"Was it detecting real threats before?"**

**YES!** The detector was (and still is) detecting real threats. The improvements made the filtering **smarter**:

- **Before:** Flagged everything matching patterns (including false positives)
- **Now:** Still flags everything, but filters out known false positives before the final YES/NO decision

**The detector still finds all threats** - it just makes a smarter decision about what's actually surveillance vs. legitimate software.

The detailed JSON report still contains **everything** it found, so you can review it manually if needed.
