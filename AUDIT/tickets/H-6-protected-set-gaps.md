# H-6 — Integrity-coverage gaps: trust-granting & CI-executed files sit outside the protected/digest set

- **Severity:** High
- **Confidence:** High
- **Files:** `config/protected-control-plane.json` (`protected_roots` / `digest_roots`)
- **Status:** Proposed patch (read-only audit)

## Problem
The protected set covers `config/**`, `runtime/**`, `schemas/**`, `laws/**`, `.github/workflows/**`, but misses files that grant or gate trust:

- **`tools/`** — only 3 of 14 protected. Unprotected include `bro_traceability.py` (the **registered validator** for `meta-layer`/`runtime-dependencies` in `config/sst-registry.json`), `bro_live_validate.py` (CI's enforcement-liveness gate), `bro_supervisor.py` (issues leases), `broctl.py` (builds `trusted-keys.json`), `bro_authorize_specialist.py`, `bro_run_receipt.py`. Editing `bro_live_validate`/`bro_traceability` to always-pass neuters validation without tripping access denial or lease digest mismatch.
- **`requirements-ci.txt`** — the sole CI supply-chain input (installed `--require-hashes`); a standard builder can append a malicious package with self-supplied matching hashes; not in `digest_roots`, so the tamper doesn't perturb the lease-bound `control_plane_digest`.
- **`tests/**`** — CI gates on `unittest discover -s tests`; a builder can weaken policy tests in the same change that weakens the runtime and stay green.
- **`.bro/policy.json`** — selects the operating mode (`default_mode`); unprotected → flip `review` → `work`, removing the default-deny posture.

## Fix
Add to **both** `protected_roots` and `digest_roots`:
- `tools/**` (at minimum every file named in `sst-registry.json` validators and every file CI executes)
- `tests/**` (at minimum `tests/catalog.json` + the policy-test suites)
- `requirements-ci.txt`
- `.bro/policy.json` (or move it under `config/`)

## Acceptance criteria
- [ ] Editing `bro_traceability.py`, `bro_live_validate.py`, `requirements-ci.txt`, a policy test, or `.bro/policy.json` is denied by the access gate and/or changes the `control_plane_digest`.
- [ ] The digest computation still terminates and CI's digest check passes on a clean tree.
- [ ] No legitimate build artifact (e.g. `__pycache__`) is pulled into the protected set.
