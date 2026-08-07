# H-4 — The audit trail is forgeable by its own writer (unkeyed self-anchored chain + manifest-gated restore)

- **Severity:** High
- **Confidence:** High
- **Files:** `runtime/bro_audit_log.py:115-172` (`append`/`verify`), `tools/bro_backup.py:212-215` (`verify_archive`/`restore`)
- **Status:** ◑ all three fixes landed in code; **deployment-blocked, not closed.** Tracked outside the engine as **O-2** (`docs/PHASE_10_PRODUCTION_ITEMS.md` §O-2, MEDIUM, OPEN): the anchor requires signing custody only the Owner can provide, so until it is provisioned every ledger is honestly `UNANCHORED` and refused. Verified 2026-08-07 at `0efa99e`; not independently re-audited.

## Problem
The audit ledger is a plain **unkeyed** SHA-256 hash chain plus a co-located plaintext `.head` sidecar written by the same unprivileged writer. `verify()` recomputes from `GENESIS` and checks the head — but anyone who can write the ledger (it lives beside the recovery store / session state the agent already writes) drops records, recomputes the chain, and rewrites `.head`; `verify()` returns green. `laws/registry.json` advertises `integrity_level: "Hash-Chained"` but the real property is `trust_source: "Self"`. The **evidence chain** (`bro_evidence.py`) does this correctly with an Ed25519 `evidence-head`; the audit ledger never adopted it.

Compounding: backup **restore** decides whether to chain-verify a file from the **attacker-supplied manifest** (`if entry.get("audit_chain") is not None`), and the SHA-256 it checks is attacker-chosen. A crafted archive listing a tampered `*.jsonl` with `"audit_chain": null` restores a forged ledger while `bro_backup` prints `GREEN: archive verified`.

## Fix
1. Sign the audit head with a recorder/operator Ed25519 authority (mirror `evidence-head`) and verify that signature inside `verify()`; a self-hashed head cannot resist the party that writes the log.
2. In `verify_archive`/`restore`, derive "is an append-only ledger" from the archived file's `*.jsonl` suffix (always chain-verify), not from `entry["audit_chain"]`.
3. Sign the backup manifest with the operator key and verify it before trusting any entry.

## Acceptance criteria
- [x] A ledger with dropped records + recomputed chain + rewritten `.head` fails `verify()` (signature mismatch).
  `append()` now attaches an Ed25519-signed head anchor and `verify(path, keys=…)` **requires** one;
  a ledger with no anchor raises the distinct `AuditAnchorMissing` rather than reading as intact
  (`runtime/bro_audit_log.py` — `verify` docstring and `_check_anchor_against_chain`). The anchor's
  artifact type is deliberately outside `bro_signature.ARTIFACT_AUTHORITY` and its payload field set
  is checked as an exact set, so a signer cannot smuggle fields. `tests/test_audit_head_anchor.py`
  pins the whole closure, including that the unkeyed structural check still reports the forged chain
  as intact (`:119-120`) — the reason keyless verification is no longer sufficient anywhere it
  matters.
  **Caveat, load-bearing:** without `keys` the check is structural only. Production callers must pass
  the registry; `tools/bro_backup.py` has no keyless mode at all (`_anchor_keys`: "There is
  deliberately no keyless mode"), but a caller that passes `keys=None` still gets the old, forgeable
  property.
- [x] Restoring an archive whose manifest sets `audit_chain: null` for a `*.jsonl` file is rejected.
  Ledger-ness is derived from the archived `*.jsonl` suffix in `_is_ledger`
  (`tools/bro_backup.py:107-110`, case-folded so `*.JSONL` cannot dodge it) and never from the
  manifest entry; `verify_archive` chain-verifies on that basis (`:328-339`). Covered by
  `tests/test_backup_restore.py` (grep `audit_chain`).
- [x] A tampered backup manifest fails restore.
  The manifest is an operator-signed `backup-manifest` artifact; `_read_manifest` refuses to verify
  without the signature once keys are available and refuses a stripped signature outright
  (`tools/bro_backup.py:269-289`), and `restore` requires the `{payload, signature}` shape
  (`:386-388`).
- [x] Legitimate append/verify/backup/restore round-trips still pass.
  Full suite green (1196 tests, 53 skipped, 2026-08-07), including
  `tests/test_audit_head_anchor.py` and `tests/test_backup_restore.py`.

**Why this ticket is still not closed.** The code is complete but the control is inert without
custody: `anchor_custody` refuses by name when `BRO_AUDIT_HEAD_SIGNER` / its key id are unset, and it
refuses a signing command that lives inside the engine (`runtime/bro_audit_log.py` — "an anchor it
signs proves nothing"). Provisioning that signer is the Owner's step, tracked as **O-2**.
