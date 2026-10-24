# CleanHouse Low-Processing Gate 0

CleanHouse emergency mode must stay useful on a stressed Mac without becoming a competing workload. Gate 0 keeps the default surface to a runtime pulse and makes evidence/history work explicit.

## Hard Caps And Lazy Rules

| Area | Hard cap | Lazy rule | Targeted verification |
| --- | ---: | --- | --- |
| Default dashboard load | sessions + runtime + cached active context | No full evidence fan-out on load or session selection | `python3 -m pytest tests/test_cleanhouse_low_processing_static.py` |
| Polling | 30 seconds minimum, one in-flight refresh | Auto-refresh stays off by default and pauses when hidden | `rg -n "DASHBOARD_AUTO_REFRESH_INTERVAL_MS|document.hidden|refreshEmergencySummary" frontend/js/dashboard.js` |
| Event query | default 20, max 200 | Manual Refresh is the evidence action | `python3 -m pytest tests/test_events_api.py -k "events_endpoint_rejects_limit_above_maximum"` |
| Domain events | default 50, max 200 | Filtered reads stay bounded | `python3 -m pytest tests/test_cleanhouse_monitoring_api.py -k "domain_events_route_validates_limit"` |
| Report history | default 10, max 50, summary-only | Full report body loads only when opened | `python3 -m pytest tests/test_cleanhouse_monitoring_api.py -k "get_reports_filters_limits_and_summarizes_login_reports"` |
| Receipts and approvals | receipts 5, approvals 5 | Replay/bundle remains explicit, not default history fan-out | `rg -n "LOW_PROCESSING_RECEIPT_LIMIT|LOW_PROCESSING_APPROVAL_LIMIT|scope_evidence" backend/api/cleanhouse.py frontend/js/dashboard.js` |
| UI rendering | 10 rows per dashboard panel, 5 inline refs | Deeper rows need an explicit follow-up surface | `rg -n "DASHBOARD_RENDER_ROW_LIMIT|DASHBOARD_INLINE_REF_LIMIT|APPLICATION_RENDER_LIMIT|PROCESS_RENDER_LIMIT" frontend/js/dashboard.js frontend/js/investigations.js` |

## Non-Goals

- No Zaelith redesign.
- No collector architecture changes.
- No speculative prefetching or new background timer.
- No full-suite verification for this gate.
