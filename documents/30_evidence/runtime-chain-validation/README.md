# Runtime Chain Validation (Not Canonical)

This directory stores validation-only runtime chain captures.

Run folder format:

`<utc-timestamp>_<event-id>/`

Example:

`20260529T185712Z_domain_event_81a2620cb9d2f4ce/`

Each run folder must contain:

- `chain_ids.json`
- `outcome.json`
- `evidence_refs.json`
- `incident_receipt.json`
- `test_output.txt`
- `operator_screenshot.png`
- `manifest.json`

Use:

```bash
python3 scripts/capture_runtime_chain_validation.py \
  --event-id 'domain_event:example' \
  --incident-id 'incident:example' \
  --receipt-id 'incident_receipt:qpb_case:example' \
  --session-id 'runtime-global' \
  --incident-receipt-json-source /abs/path/incident_receipt.json \
  --test-output-source /abs/path/test_output.txt \
  --operator-screenshot-source /abs/path/operator_screenshot.png \
  --event-json-source /abs/path/event.json \
  --incident-json-source /abs/path/incident.json
```

Notes:

- `operator_screenshot.png` must be a real operator-captured PNG.
- `manifest.json` includes SHA-256 hashes for all artifacts and sets `validation_only: true`.
- Do not use this directory for canonical or official proof artifacts.
