# Vendored: prompt_injection_sdk 0.1.0

A byte-for-byte copy of the scanner part of the team's internal
`prompt_injection_sdk` (wheel `prompt_injection_sdk-0.1.0-py3-none-any.whl`,
copied 2026-10-18). It ships with the app, so the phone needs no `pip` step.

**Do not edit these files.** Ledgerline's own tuning lives in
`app/analyst/injection_guard.py` and uses only the SDK's public API
(`add_pattern(..., replace=True)`), so a newer SDK version can be dropped in
over this folder unchanged.

## What was copied

| File | Why |
|---|---|
| `__init__.py`, `py.typed` | package root |
| `injection/__init__.py` | the SDK's public names |
| `injection/normalize.py` | strips disguises: leetspeak, look-alike letters, invisible characters, spacing, base64 |
| `injection/patterns.py` | the 11 built-in rules and the custom-rule registry |
| `injection/scanner.py` | the verdict and the formal refusal message |
| `injection/audit_bridge.py` | imported by `injection/__init__.py`; inert here (it only writes when `audit_client_sdk` is installed, which it is not) |

All of the above use the Python standard library only (PyYAML is needed only
for YAML custom-pattern files, which Ledgerline does not use).

## What was left out

- `injection/scanner_client.py`: records each scan in PostgreSQL
  (`tbl_prompt_injection_scanner`) and needs `asyncpg`. Ledgerline blocks
  without keeping a record, by the owner's choice.
- `admin/`: creates that table and its database role.
- The SDK's tests for the two parts above (`test_audit.py`,
  `test_client_config.py`).

The SDK's own tests for what *was* copied run in Ledgerline's suite:
`backend/tests/vendored_prompt_injection/`.

## Updating

Replace the files listed above with the new version's, keep this note's
version and date current, and run the test suite.
