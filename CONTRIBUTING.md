# Contributing to CleanHouse

CleanHouse is evidence infrastructure. Changes must preserve append-only raw
evidence, distinguish observation from authorization, fail honestly when a
provider is unavailable, and keep credentials out of source and logs.

Before contributing:

1. Read `LICENSE`, `TRADEMARK.md`, and `CLA.md`.
2. Sign the external CLA check when it is enabled for the repository.
3. Use a focused branch and avoid unrelated cleanup.
4. Add focused tests for the contract you change.
5. Document third-party packages, checksums, licenses, source offers, and any
   privileged operation.

Do not submit generated evidence databases, enrollment credentials, TLS keys,
administrator credentials, or Wazuh secrets. Security reports should use the
private reporting channel configured in the repository rather than a public
issue.

The CLA Assistant check and branch-protection rule are repository-host settings;
they must be enabled by an authorized GitHub administrator before external
contributions are accepted.

