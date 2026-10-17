# Staged account-creation dependency

`backend.launch_agent.stage_runtime` requires and copies `access_control` with
`models`. Account creation imports that policy from the staged release; it must
not fall back to an editable source checkout. Missing `access_control` raises
`FileNotFoundError` before the current release is replaced.

Run `python -m unittest -v tests.test_staged_account_dependency tests.test_launch_agent`.
The focused staged-account test copies actual account/policy modules into a
synthetic source, stages it, removes that source, and creates a synthetic account
in an isolated Python subprocess using only the staged modules. The failure test
proves that an existing disposable release survives a missing policy dependency.
No launchd command, installed service, account store, or credentials are used.
