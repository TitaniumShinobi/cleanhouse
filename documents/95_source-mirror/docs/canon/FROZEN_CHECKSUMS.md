# Frozen Runtime Module Checksums

**Generated:** 2026-05-22
**Purpose:** Detect accidental target drift before each implementation prompt.
**Validation:** Re-run `shasum -a 256` on each file and compare. Any mismatch means the file changed since freeze.

| File | Lines | SHA-256 |
|---|---|---|
| `corefiles/collectors/command_observer.py` | 123 | `75568ede66d4f682ac45749540112c07ce23c76fd0042026399a9a82f9cf5d29` |
| `backend/api/cleanhouse.py` | 221 | `9be3b53640dde4a9367ad156acc04a58e614914c75d6b8665dc3ce9b4b662130` |
| `backend/api/cleanhouse_monitoring.py` | 2078 | `6bdc6292865708fd8d1859beb062491e71103b82e636fa57226884a8cf6607b4` |
| `backend/server.py` | 118 | `54378e425e88264a2973e74957a4da38cadb801de1252df405124787c7cf6434` |
| `corefiles/config.py` | 254 | `daac51028abf42146731ee7b00cfa41d1ff42f6cf331fa1f0516c590130bcc6c` |
| `corefiles/monitor.py` | 306 | `31876fc140159e9fb2c0ef5655d949441ff4730a3566f0d883b3d8444f913985` |
| `corefiles/integrity.py` | 574 | `cdf39af2165bbc5bdeca6638ae367d0895164c0d915171f96deaf02e2bf18451` |
| `corefiles/collectors/process_monitor.py` | 327 | `35f581703cc2d7ac4dba06546501dd21eb5d0a9ac56823e4a1dde08918ee17a7` |
| `corefiles/collectors/agent_movement_monitor.py` | 619 | `4850f7a2cb831a2ed592d569d07b59bd3388dd82308ac51c9043991b67a3752b` |
| `corefiles/collectors/data_flow_tracer.py` | 492 | `8d51cafd48241f3264d0c12068aa46d8904555e70cc3058972d48e773e9eca15` |
| `tests/test_cleanhouse_monitoring_api.py` | 1116 | `bda0bd4e1dfb05a7a2c7a94ae3336173c5f38ef604b325a72fdd1a2bb34434c5` |
| `frontend/js/api-client.js` | 169 | `c62b0b13a96ca8878f8036c094e84ed7ce33fa28a34630e4a709e74ab0370265` |
| `desktop/wrapper.py` | 60 | `4175066c7d11f82869ba1cda5ecddb9bccaeca5fdb81b016f8c665c042734506` |

---

## Verification Command

```bash
shasum -a 256 \
  corefiles/collectors/command_observer.py \
  backend/api/cleanhouse.py \
  backend/api/cleanhouse_monitoring.py \
  backend/server.py \
  corefiles/config.py \
  corefiles/monitor.py \
  corefiles/integrity.py \
  corefiles/collectors/process_monitor.py \
  corefiles/collectors/agent_movement_monitor.py \
  corefiles/collectors/data_flow_tracer.py \
  tests/test_cleanhouse_monitoring_api.py \
  frontend/js/api-client.js \
  desktop/wrapper.py
```

Compare output against the table above. Any difference indicates a file changed since the freeze date.
