# H-4 — The audit trail is forgeable by its own writer (unkeyed self-anchored chain + manifest-gated restore)

- **Severity:** High
- **Confidence:** High
- **Files:** `runtime/bro_audit_log.py:115-172` (`append`/`verify`), `tools/bro_backup.py:212-215` (`verify_archive`/`restore`)
- **Status:** Proposed patch (read-only audit)

## Problem
The audit ledger is a plain **unkeyed** SHA-256 hash chain plus a co-located plaintext `.head` sidecar written by the same unprivileged writer. `verify()` recomputes from `GENESIS` and checks the head — but anyone who can write the ledger (it lives beside the recovery store / session state the agent already writes) drops records, recomputes the chain, and rewrites `.head`; `verify()` returns green. `laws/registry.json` advertises `integrity_level: "Hash-Chained"` but the real property is `trust_source: "Self"`. The **evidence chain** (`bro_evidence.py`) does this correctly with an Ed25519 `evidence-head`; the audit ledger never adopted it.

Compounding: backup **restore** decides whether to chain-verify a file from the **attacker-supplied manifest** (`if entry.get("audit_chain") is not None`), and the SHA-256 it checks is attacker-chosen. A crafted archive listing a tampered `*.jsonl` with `"audit_chain": null` restores a forged ledger while `bro_backup` prints `GREEN: archive verified`.

## Fix
1. Sign the audit head with a recorder/operator Ed25519 authority (mirror `evidence-head`) and verify that signature inside `verify()`; a self-hashed head cannot resist the party that writes the log.
2. In `verify_archive`/`restore`, derive "is an append-only ledger" from the archived file's `*.jsonl` suffix (always chain-verify), not from `entry["audit_chain"]`.
3. Sign the backup manifest with the operator key and verify it before trusting any entry.

## Acceptance criteria
- [ ] A ledger with dropped records + recomputed chain + rewritten `.head` fails `verify()` (signature mismatch).
- [ ] Restoring an archive whose manifest sets `audit_chain: null` for a `*.jsonl` file is rejected.
- [ ] A tampered backup manifest fails restore.
- [ ] Legitimate append/verify/backup/restore round-trips still pass.
