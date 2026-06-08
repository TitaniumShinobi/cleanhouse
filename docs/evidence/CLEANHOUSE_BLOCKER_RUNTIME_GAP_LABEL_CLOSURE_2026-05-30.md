# CleanHouse Blocker Closure Evidence

Date: 2026-05-30
Blocker: Collector dependency/permission fragility being labeled as `unknown`, degrading receipt verdict quality.

## Change Summary

- Updated runtime gap labeling to classify known collector states explicitly:
  - `dependency_missing` -> `unsupported`
  - `permission_denied` -> `permission_blocked`
  - `inactive`/`no_baseline` -> `partial`
  - `unknown` remains `unknown`

## Targeted Verification

Command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Users/devonwoodson/Documents/GitHub/cleanhouse/.venv/bin/python -m unittest tests.test_cleanhouse_monitoring_api.CleanHouseMonitoringApiTests.test_runtime_gaps_classify_known_collector_failures_without_unknown
```

Result:

- `Ran 1 test in 0.000s`
- `OK`

## Outcome

Known collector failure states now surface as explicit, actionable gap labels instead of collapsing into `unknown`.
