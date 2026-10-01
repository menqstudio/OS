# Evidence index — what to read, in what order, and what each thing does not establish

For a reviewer from outside this repository. **Nothing here is a new claim.** Every
statement is already written somewhere in the tree and is cited to the file that
says it; every number below was produced by running the tool named beside it and is
pasted, not remembered. Where something is worth saying and is written nowhere, it is
listed as a gap rather than asserted here.

**Read [What this repository does not establish](#what-this-repository-does-not-establish)
first.** If that section is missing or vague in a document like this, stop reading the
rest of it.

---

## 1 · Start with the position, not the code

**[`CLAUDE.md`](../CLAUDE.md)** — the operating law and the current position in both
English and Armenian. It states the production gate is shut, names the three refusals
that hold it, and records that the standing independent verdict is RED.

**[`apps/desktop/AUDIT/AUDIT_LEDGER.md`](../apps/desktop/AUDIT/AUDIT_LEDGER.md)** — the
audit position, and the only place it lives. `CLAUDE.md` §7 rule 3 says a documented
claim is not evidence; the ledger is where a tick in prose is checked against.

*Establishes:* what has been audited and to what verdict.
*Does not establish:* that anything merged since the audited head is confirmed. The
ledger names the head each round judged.

## 2 · The audit rounds themselves

Ten rounds, in `apps/desktop/AUDIT/`. The current one is
**[`apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md`](../apps/desktop/AUDIT/2026-09-19-tenth-audit-75fca65.md)**
— *"Tenth round — independent verification of the ninth round, at `main` @ `75fca65`"*, verdict RED
with no P0. Which round is current is the ledger's to say (§1); this section named the ninth for a
round after the tenth was filed.

**What kind of independence these have, and what kind they lack.** The tenth round's header reads
*"**Auditor role** delegated to Claude by the Owner, as recorded for the sixth round onward"*, and the
ninth round's own header states it: *"**Auditor:** Architect session, role-only. I did not write any
of the code judged here."* So the independence is **role separation within the same
AI system** — a session that did not write the code, judging it against the tree. It
is **not** third-party review, not a different organisation, and not a human auditor.
The word "independent" in these filenames means the first thing and not the second,
and a reviewer should read it that way.

## 3 · The two documents written to be checked rather than believed

**[`docs/EVIDENCE_BASH_GAP.md`](EVIDENCE_BASH_GAP.md)** — *"Status of every claim
below: `measured`. Each is followed by the command that produced it and what that
command printed. Nothing here is inferred, and nothing is the Builder's
recollection."*

**[`docs/README_CLAIM_HISTORY.md`](README_CLAIM_HISTORY.md)** — *"`README.md` is the
front page, and every measured number on it has been wrong at least once. This is the
record of what it claimed, what the claim was corrected to, and the command that
settled it."*

*Establish:* that specific numbers were measured, and how.
*Do not establish:* that the numbers are still current. Both are dated at a head.

## 4 · The machine registries — where a status is a value, not a sentence

Each is enforced by a gate, and the gate's own output is pasted. Run them yourself;
that is the point of them.

**`config/negative-matrix.json`** — `python3 tools/check_negative_matrix.py`:

```
GREEN: 242 matrix cases, all bound -- 155 implemented (test exists and carries its ID),
52 blocked (each naming what must exist first), 35 unreviewed and frozen in the baseline.
No new debt.
```

`unreviewed` means **nobody has looked**. *(Re-run and re-pasted 2026-10-01. This block said
29 / 12 / 201, with `unreviewed` "the largest of the three by far"; it is now the smallest.)*

**`config/spec-conformance.json`** — `python3 tools/check_spec_references.py`:

```
GREEN: every § reference in the source is declared (7 implemented, 1 not_implemented,
18 partial, 37 unreviewed).
```

**`docs/PHASE_10_PRODUCTION_ITEMS.md`** — `python3 tools/check_residual_items.py`:

```
GREEN: 5 residual engine items inventoried in docs/PHASE_10_PRODUCTION_ITEMS.md
(5 OPEN: O-1, O-2, O-3, O-4, O-5); severities agree with CLAUDE.md and
docs/SECURITY_MODEL.md; every cited engine path exists
```

**`config/required-checks.json`** — the branch protection `main` is expected to have.
**35 contexts** (`python3 -c "import json;print(len(json.load(open('config/required-checks.json'))['contexts']))"` → `35`).

**`config/deferred-enforcement.json`** — deferrals with a sign-off ceiling
(`max_days_without_sign_off`).

**`config/produced-artifact-contract.json`** — what the produced artifact must satisfy;
`python3 tools/check_produced_artifact.py` judges a store the code produced. **In a
fresh clone that gate is RED until something produces the artifact** — the store is not
committed.

**`config/reachability-declarations.json`** — `python3 tools/check_reachability.py`:

```
engine security symbols: 3 enforced with a real caller; 2 declared caller-less against
a named residual item.
src-tauri rust symbols: 4 enforced with a real caller; 1 declared caller-less with a
written reason.
```

## 5 · The trust model and what is blocked on whom

**[`docs/SECURITY_MODEL.md`](SECURITY_MODEL.md)** — the three production-gate refusals,
cited to source in its §2 ("Current posture — FAIL-CLOSED"): `governed_verification_unconfigured()` in
`apps/desktop/src-tauri/src/commands.rs`, `connect_broker()` in
`apps/desktop/src-tauri/src/governed_turn.rs`, and the `UpstreamBlockedExecutor`
fallback.

**[`docs/DEBIAN_DEPLOYMENT.md`](DEBIAN_DEPLOYMENT.md)** — *"`build-registry` hardcodes
`"production": false`"*, `broctl keygen --production` *"refuses outright"*, and
`bro_signature` *"refuses a non-production registry"* on the production path.

**[`docs/OWNER_ACTION_REQUIRED.md`](OWNER_ACTION_REQUIRED.md)** — the page of record for
what waits on the Owner.

---

## What this repository does not establish

Every line here is stated elsewhere in the tree and cited.

**The governed gate is SHUT.** `CLAUDE.md` §6: *"The production gate is SHUT, and only
the Owner opens it after an independent audit — not a green CI run, not the Builder's
confidence."* Three refusals hold it, listed in `docs/SECURITY_MODEL.md`.

**There is no path in this repository to a production trust root.**
`docs/DEBIAN_DEPLOYMENT.md`: `build-registry` hardcodes `"production": false` and
`broctl keygen --production` refuses. Everything runnable produces a **development**
trust root.

**On POSIX the app never provisions itself.** `CLAUDE.md` §6: a root installer does
(`brops_install_anchor`), and the application only finds and verifies the anchor that installer
wrote; on a machine where the install step did not run, first launch refuses. *(This paragraph
said "Provisioning is Windows-only … sealing the anchor refuses on POSIX and provisioning aborts
startup" and attributed it to `CLAUDE.md` §6, which no longer says that.)*

**The standing verdict is RED, and the audits are AI sessions in an auditor role** —
see §2 above for exactly what independence that is and is not. `CLAUDE.md` §7 rule 5:
*"✅ means independently confirmed; ◑ means the Builder's own claim. Never promote your
own work."* Work merged since the tenth round's head (`75fca65`) carries ◑.

**All five residual engine items are OPEN**, O-1 the only HIGH — `check_residual_items`
output in §4, inventory in `docs/PHASE_10_PRODUCTION_ITEMS.md`.

**The audit ledger is not tamper-evident against its own writer on any real
deployment** (O-2). `CLAUDE.md` §6 states it: nothing in the shipped product sets
`BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID`, `apps/desktop/src-tauri/tauri.conf.json` declares no
`externalBin`, and `append()` writes a plaintext `.head` with no `.head.sig`. On POSIX
the signer has never run.

**The produced agent cannot make a call.** `agent_bundle.rs::NOT_IMPLEMENTED` says so
in the code a caller reads: *"model steps: a governed turn is refused at this head"*;
*"What is NOT IMPLEMENTED is the TRANSPORT: an authorized call is still refused,
because nothing here opens a connection"*; and *"credential VALUES: there are none on this
side"* — what is bound to a slot is a reference the engine or the operator resolves.

**35 of 242 negative-matrix rows are `unreviewed`** — nobody has looked — and 52 are `blocked`.
**37 § references are `unreviewed`.** Both numbers are from the tools in §4, and both mean absence of
review, not absence of defect.

**A green CI run is not an audit, and a green pull request is not a green `main`.**
`CLAUDE.md` §7 rule 2 requires an all-green exact head read from `main`'s own runs.

### Gaps — worth saying, written nowhere, so not asserted here

* **No document states the total test count across the three suites in one place.** The
  numbers are in `CLAUDE.md` §4 as per-suite verify commands, and they are dated
  2026-08-29; a reviewer should run them rather than read them.
* **Nothing states how many of the nine audit rounds were run at a head that is still
  reachable.** `apps/desktop/AUDIT/AUDIT_LEDGER.md` names each head; whether each resolves today is not
  recorded anywhere.
