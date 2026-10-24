# Operator API Responsiveness Receipt (2026-05-30)

## Scope
Restore responsiveness for /cleanhouse/status, /cleanhouse/runtime, /cleanhouse/workstation and confirm dashboard dependency availability.

## Endpoint Timing Proof

### /cleanhouse/status
code=200 time=0.210825
{'status': 'safe', 'response_mode': 'fast', 'data_keys': ['collector_health', 'collector_manifest', 'degradation', 'runtime', 'sections']}

### /cleanhouse/runtime
code=200 time=0.209677
{'status': 'healthy', 'runtime_state': 'healthy', 'operator_ready': True, 'response_mode': 'fast'}

### /cleanhouse/workstation?session_id=product-reality-20260530
code=200 time=0.207953
{'status': 'ok', 'runtime_state': 'healthy', 'operator_ready': True, 'response_mode': 'fast', 'runtime_keys': ['active_context', 'backend', 'blocked_recovery', 'connected_accounts', 'domain_observer_matrix', 'heartbeat', 'interpreter', 'last_probe', 'last_start_attempt', 'listener', 'notifications', 'operator_ready', 'presence_mode', 'reason_codes', 'recovery_receipts', 'report_executor', 'response_mode', 'runtime_notifications', 'runtime_state', 'state_path', 'status', 'supervisor', 'updated_at', 'valid_states', 'visibility_proof_summary', 'visibility_state']}

### /dashboard
code=200 time=0.001367
   12246 /tmp/ch_resp.json

## Runtime Supervisor State
{'runtime_state': 'healthy', 'reason_codes': [], 'supervisor_pid': 85682, 'backend_pid': 86240, 'updated_at': '2026-05-30T22:25:36+00:00'}

## Receipt
Status: operator APIs responsive with runtime_state=healthy and dashboard returning HTTP 200.
