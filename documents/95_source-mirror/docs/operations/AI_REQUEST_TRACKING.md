# AI Request Tracking

## How It Works

When you send a message to an AI assistant (like me, Auto/Cursor's AI), here's what happens:

### 1. **I Don't Run Locally**
- I (the AI assistant) run on **remote servers**, not as a process on your Mac
- You won't see "Auto" or "Cursor AI" as a local process

### 2. **But Cursor Shows Activity**
- When you send a message, **Cursor's local processes** become active
- The process monitor will show:
  - Cursor processes with increased CPU/memory usage
  - Network connections from Cursor to AI API endpoints
  - File activity in Cursor's config directories

### 3. **What Gets Detected**

#### Process Monitor (`corefiles/collectors/process_monitor.py`)
- Shows Cursor processes when active
- Highlights agent-related processes
- Shows CPU/memory spikes when processing requests

#### Agent Movement Monitor (`corefiles/collectors/agent_movement_monitor.py`)
- Detects network connections to AI services:
  - `cursor.ai`, `cursor.com` (Cursor's AI endpoints)
  - `api.openai.com` (OpenAI API)
  - `api.anthropic.com` (Claude API)
  - `api.google.com` (Gemini API)
- Logs "AI Request Processing" events
- Tracks when requests are sent/received

### 4. **What You'll See**

When you send a message to me:

**In Process Monitor:**
```
Cursor processes with higher CPU usage
[AGENT] tags on relevant processes
```

**In Agent Movement Monitor:**
```
[INFO] 🤖 AI processing user request via cursor → api.cursor.ai
[ALERT] Agent API connection from cursor: api.cursor.ai:443
```

**In the JSON log:**
```json
{
  "ai_request_events": [
    {
      "event": "ai_request_processing",
      "platform": "cursor",
      "endpoint": "api.cursor.ai:443",
      "timestamp": "2026-01-03T11:30:00",
      "description": "AI assistant processing request from cursor"
    }
  ]
}
```

## Real-Time Monitoring

To see AI request activity in real-time:

```bash
# Monitor processes (see Cursor activity)
python3 -m corefiles.collectors.process_monitor -i 1

# Monitor agent movements (see API calls)
python3 -m corefiles.collectors.agent_movement_monitor
```

## What Gets Logged

1. **Network connections** - When Cursor connects to AI APIs
2. **Process activity** - Cursor's CPU/memory usage spikes
3. **File activity** - Config/log files updated
4. **Request events** - Timestamped AI request processing events

## Limitations

- Can't see the actual message content (privacy)
- Can't see AI's internal processing (runs remotely)
- Can only detect local activity (Cursor's side of the communication)

## Example Timeline

```
11:30:00 - You type a message in Cursor
11:30:01 - Cursor process CPU spikes (detected by process_monitor)
11:30:01 - Network connection to api.cursor.ai (detected by agent_monitor)
11:30:01 - AI request event logged
11:30:02 - Response received, Cursor processes it
11:30:03 - File activity in Cursor config (cache/logs updated)
```

The monitors track **when** and **how** Cursor communicates with AI services, but not the actual conversation content.
