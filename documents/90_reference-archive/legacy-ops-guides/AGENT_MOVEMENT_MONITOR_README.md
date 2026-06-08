# Agent Movement Monitor

Monitors background agent activity and movements between different coding platforms.

## Platforms Monitored

- **VS Code** (Visual Studio Code)
- **Cursor**
- **Codex**
- **Gemini Antigravity**

## What It Monitors

### 1. **Process Activity**
- Detects when coding platform processes are running
- Tracks process names, PIDs, CPU/memory usage
- Identifies agent-related processes (AI assistants, code completion, etc.)

### 2. **File Access Patterns**
- Monitors configuration directories for each platform
- Detects recent file modifications (within 60 seconds)
- Tracks agent-related files (`.agent`, `agent.json`, cache files, etc.)

### 3. **Network Connections**
- Monitors network connections from coding platforms
- Detects API calls to AI services (OpenAI, Anthropic, Google)
- Tracks completion/suggestion API endpoints

### 4. **Platform Switching**
- Detects when agent activity moves between platforms
- Tracks timing of switches
- Logs cross-platform activity patterns

### 5. **Agent Pattern Detection**
- Identifies agent-related processes by name patterns
- Detects agent configuration files
- Monitors agent API network connections

## Usage

### Single Scan (One-time check)
```bash
python3 -m corefiles.collectors.agent_movement_monitor --once
```

### Continuous Monitoring
```bash
# Monitor until interrupted (Ctrl+C)
python3 -m corefiles.collectors.agent_movement_monitor

# Monitor for specific duration (e.g., 60 seconds)
python3 -m corefiles.collectors.agent_movement_monitor -d 60

# Quiet mode (less verbose)
python3 -m corefiles.collectors.agent_movement_monitor -q

# Custom output file
python3 -m corefiles.collectors.agent_movement_monitor -o /path/to/output.json
```

## Output

### Console Output
- Real-time activity logs
- Periodic summaries (every 30 seconds)
- Platform switches detected
- Agent detections

### JSON Log File
Saved to `results/agent_movement_log.json` (or custom path) containing:
- Platform activity timeline
- Process detections
- File access logs
- Network connections
- Platform switches
- Agent detections

## Example Output

```
================================================================================
AGENT MOVEMENT MONITORING SUMMARY
================================================================================
Time: 2026-01-03 11:15:00
Active platforms: vscode, cursor
Platform switches detected: 2
Agent detections: 3

VSCODE:
  Processes: 5
  File access: 12
  Network connections: 8
  Active periods: 3 (currently active: 1)

CURSOR:
  Processes: 3
  File access: 7
  Network connections: 5
  Active periods: 2 (currently active: 1)

Recent platform switches:
  2026-01-03T11:14:30: ['vscode'] → ['cursor']
  2026-01-03T11:14:45: ['cursor'] → ['vscode', 'cursor']

Recent agent detections:
  2026-01-03T11:14:32: network_pattern - vscode
  2026-01-03T11:14:35: process_pattern - cursor
  2026-01-03T11:14:50: file_pattern - vscode
================================================================================
```

## Detection Patterns

### Process Patterns
- `agent`, `ai.*assistant`, `code.*completion`, `autocomplete`
- `copilot`, `ghostwriter`, `code.*suggest`, `intellisense`
- `language.*server`, `lsp`, `background.*service`

### File Patterns
- `.agent`, `agent.json`, `.ai`
- `background.*log`, `agent.*cache`
- `completion.*cache`, `suggestion.*cache`

### Network Patterns
- `api.*openai`, `api.*anthropic`, `api.*google`
- `completion.*api`, `suggestion.*api`, `agent.*api`
- `codex.*api`

## Use Cases

1. **Detect AI agent activity** - See when AI assistants are active
2. **Track platform usage** - Monitor which coding platforms you use
3. **Identify agent switching** - See when agents move between platforms
4. **Monitor API usage** - Track AI API calls from coding platforms
5. **Security monitoring** - Detect unauthorized agent activity

## Notes

- Requires appropriate permissions to scan processes and network connections
- On macOS, may need to grant Terminal/IDE full disk access
- Process scanning requires elevated permissions in some cases
- Network monitoring requires network access permissions

## Integration

Can be integrated with the surveillance detector for comprehensive monitoring:

```bash
# Run both monitors
python3 -m corefiles.collectors.surveillance_detector &
python3 -m corefiles.collectors.agent_movement_monitor &
```
