# AUDIT — Bro (harness)

Security audit of **`menqstudio/Bro`** @ `979e564` — the agent-orchestration security-governance harness.

- **Mode:** READ-ONLY. Nothing was changed in the runtime; all tickets are *proposed* patches.
- **Method:** 7 parallel Fable 5 auditors (one per security subsystem) → Opus verification of every Critical/High against source, including reconciling a Critical↔High disagreement.
- **Threat model:** a contained, possibly-malicious specialist agent trying to defeat a control (escape containment, forge trust, bypass the gate).
- **Date:** 2026-07-19

## How to use with agents
Each file in [`tickets/`](tickets/) is self-contained: location (`file:line`), the problem, a concrete fix, and acceptance criteria. Hand a coding agent one ticket:
> "Apply the fix in `AUDIT/tickets/C-1-find-readonly-bypass.md` to this repo. Verify against its acceptance criteria. Touch only the listed files, and do not weaken any test."

The Medium and Low findings are batched (`MEDIUM-findings.md`, `LOW-findings.md`); each item inside is independently actionable.

## Index

| # | Ticket | Severity | Subsystem |
|---|---|---|---|
| C-1 | [find/read-only shell bypass](tickets/C-1-find-readonly-bypass.md) | 🔴 Critical | command classifier |
| H-1 | [unsigned workspace binding](tickets/H-1-unsigned-workspace-binding.md) | 🟠 High | workspace scope |
| H-2 | [Windows emit fail-closed crash](tickets/H-2-windows-emit-crash.md) | 🟠 High | hook / fail-closed |
| H-3 | [Windows fail-OPEN wall](tickets/H-3-windows-fail-open-wiring.md) | 🟠 High | hook wiring / CI |
| H-4 | [forgeable audit trail](tickets/H-4-forgeable-audit-trail.md) | 🟠 High | audit / backup |
| H-5 | [defeatable key revocation](tickets/H-5-registry-anti-rollback.md) | 🟠 High | trust root |
| H-6 | [protected-set coverage gaps](tickets/H-6-protected-set-gaps.md) | 🟠 High | integrity coverage |
| M | [9 Medium findings](tickets/MEDIUM-findings.md) | 🟡 Medium ×9 | mixed |
| L | [13 Low findings](tickets/LOW-findings.md) | ⚪ Low ×13 | mixed |

Full narrative: [BroCore_Audit_Report.md](BroCore_Audit_Report.md)

## Three themes
1. **Windows is second-class** — controls degrade/fail on the target OS (H-2, H-3, M-2, M-3, L-9).
2. **Signed-vs-unsigned asymmetry** — Ed25519 is applied well to leases/contracts/protected-authority/evidence, but a few anchors rest on unsigned env/JSON (H-1, H-5, M-1, M-4, H-4).
3. **Integrity coverage gaps** — protected/digest set misses `tools/`, `tests/`, `requirements-ci.txt`, `.bro/policy.json` (H-6).

## Verified CLEAN — do not re-investigate
Lease binding/forgery/expiry/double-spend, capability ceiling (no DELETE/WRITE_EXTERNAL leasable), shell/deserialization injection (no shell=True/eval/pickle/yaml.load; split_shell blocks `$()`/backtick/redirection), contract & artifact Ed25519 signing, builder≠verifier, mode-elevation gating, CI content (permissions/SHA-pins/`--require-hashes`), no committed secrets (238 commits).

## Suggested order
C-1 → H-2/H-3 (Windows wall) → H-1 → H-4/H-5 → H-6 → Mediums → Lows.
