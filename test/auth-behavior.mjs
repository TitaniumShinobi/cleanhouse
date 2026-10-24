// Product-owned behavioral acceptance. Command changes require product review.
import { spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const spec = {
  "argv": [
    "python",
    "-B",
    "scripts/run-auth-regression.py"
  ],
  "timeoutMs": 210000,
  "executableEnvironment": "CLEANHOUSE_TEST_PYTHON"
};
const root = fileURLToPath(new URL('../', import.meta.url));
const executable = spec.executableEnvironment ? process.env[spec.executableEnvironment] : spec.argv[0] === '$NODE' ? process.execPath : spec.argv[0];
if (!executable) { console.error('PRODUCT_TEST_EXECUTABLE_REQUIRED'); process.exit(2); }
// Never pass a shell, interpolate arguments, or print environment contents.
const env = { ...process.env };
delete env.NODE_TEST_CONTEXT;
delete env.PRODUCT_TEST_WITNESS_FILE; delete env.PRODUCT_TEST_WITNESS_NONCE;
const result = spawnSync(executable, spec.argv.slice(1), { cwd: root, env, shell: false, stdio: 'inherit', timeout: spec.timeoutMs, killSignal: 'SIGKILL' });
if (result.error) { console.error(result.error.code === 'ETIMEDOUT' ? 'PRODUCT_TEST_TIMEOUT' : 'PRODUCT_TEST_EXECUTION_FAILED'); process.exit(2); }
if (result.signal || result.status === null) { console.error('PRODUCT_TEST_INTERRUPTED'); process.exit(2); }
if (result.status === 0 && process.env.PRODUCT_TEST_WITNESS_FILE && process.env.PRODUCT_TEST_WITNESS_NONCE) writeFileSync(process.env.PRODUCT_TEST_WITNESS_FILE, process.env.PRODUCT_TEST_WITNESS_NONCE, {flag:'wx',mode:0o600});
process.exit(result.status);
