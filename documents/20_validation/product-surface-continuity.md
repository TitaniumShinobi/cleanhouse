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
