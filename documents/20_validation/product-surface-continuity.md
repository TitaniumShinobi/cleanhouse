# Product surface continuity

This source foundation preserves the existing Zaelith, Identity, Reports, Allowed
Threats, Help, and Advanced surfaces. `/dashboard` remains a redirect to
`/advanced`. Overview retains its existing views and gains the existing page
navigation links. Zaelith's existing connection page and referenced styles,
fonts, scripts, and API methods are included with the pages.

The extraction is limited to these surfaces: the shared API retains canonical
network, Files, collector, startup, and login-report behavior. Allowed Threats
uses its existing local JSON state contract. Reports reuses the existing report
ledger; detail lookup and Zaelith report creation are restored. No provider,
account, or authentication policy is changed. No services are started by the
source tests.

Run the focused dependency tests in a Python environment with Flask installed:

```sh
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest -v tests.test_product_surface_dependencies
python scripts/run-auth-regression.py
```

The dependency tests execute selected actual route functions in an isolated
Flask app, exercise disposable Allowed Threats storage, construct and read back
a report in memory, and verify page navigation and transitive static assets.
They deliberately do not import the production server or start collectors.
They are not a substitute for live UI, provider connection, or production
storage acceptance. Existing page feature limitations are preserved rather than
reinterpreted during source isolation.

## Structural preservation gate

The unchanged `scripts/verify-product-surfaces.py` reads the unchanged
`.cleanhouse/product-surface-baseline.json` and checks eleven owner-established
surfaces for file existence, expected text markers, and route declarations.
It uses Python's standard library. Missing files/markers/routes fail with exit1;
unreadable or invalid inputs also return a nonzero Python error. It does not
validate authorization, visual rendering, endpoint execution, or baseline
provenance. The focused test requires the eleven-surface success receipt.

```sh
python -B scripts/verify-product-surfaces.py
python -B -m unittest -v tests.test_product_surface_baseline tests.test_product_surface_dependencies
```

The existing authentication workflow now runs these commands after the auth
gate on every push/PR. The tests remove each of eleven files/markers/routes
in disposable fixtures (33 cases), require failure naming the affected surface,
and restore the fixture. No repository or live state is mutated by those cases.
No remote required-check setting is changed here.

Security boundary: the later source API-admission repair removes the blanket
`/cleanhouse/` exemption while retaining exact direct-loopback readiness probes
and existing stricter endpoint policies. See `cleanhouse-auth-acceptance.md` for
identity validation, origin checks, and tests. Surface tests alone still do not
establish authorization or live production acceptance.
