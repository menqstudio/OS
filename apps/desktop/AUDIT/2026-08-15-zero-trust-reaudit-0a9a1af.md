# Independent zero-trust RE-AUDIT — menqstudio/OS

**Target — pinned, and frozen:** `main` @ **`0a9a1afe7ed63e10cc38f0a608b2d45c7c9d74fc`** (PR #106 merged).

**How it was pinned, because it had to be.** `main` moved twice while this audit was running —
`e0dd969` → `0a9a1af` → `3b8acaf` — in a working tree another session is actively building in. An audit
whose target moves under it certifies nothing, so the tree was exported to a scratchpad
(`git archive 0a9a1af`) and every read, test and attack below ran against **that snapshot, never the
shared working tree**. The snapshot is provably the audited commit:

```
git rev-parse 0a9a1af^{tree}      = ca0b7de151ffc300b710ec80008575bd4bf46c2a
git write-tree (in the snapshot)  = ca0b7de151ffc300b710ec80008575bd4bf46c2a   ← identical
```

`3b8acaf`, the commit that landed after the pin, touches only `NEXT_CHAT.md`, `PROJECT_STATE.md`,
`TASKS.md`, `config/current_state.json` and `config/roadmap-order-exemptions.json` — **no code, no audit
surface** — so pinning to `0a9a1af` costs this audit nothing.

**Scope:** the five findings of the [third audit](./2026-08-14-zero-trust-audit-e0dd969.md) (`A-01`…`A-05`),
the fixes the Builder shipped for them in PRs #102–#105, and the ✅ promotions applied in PR #100.
**Prior report re-checked:** `2026-08-14-zero-trust-audit-e0dd969.md` — this auditor's own. Fixes to one's
own findings are the easiest thing in the world to wave through, so each was attacked on the assumption it
was wrong.

**Date:** 2026-08-15
**Mode:** READ-ONLY on the repository. No repository file created, modified or deleted except this report.
No commit, no push, no branch, no PR. Every mutation was applied to the disposable snapshot and restored,
with the restore verified by digest against the committed blob.

---

## 1. Verdict

# RED — and the remaining reason is one platform, not one mechanism

**Four of the five findings are closed and I could not reopen them.** `A-01` is closed on the
Linux/Python path — properly, with a real pin, a single door, and a mutation I reproduced myself — and
**open, unchanged, on the Windows twin**, while its ledger row is titled *"(P2, both platforms)"* and marked
"Builder claims closed" with a status text that describes only the Python fix.

That is not a nitpick about wording. It is, precisely, the failure this ledger's own header names as the
reason the file exists:

> *"The clearest case is **F-02**: it was marked CLOSED on the strength of the Linux remediation while the
> Windows twin still carried the four `evidence_*` deployment constants — and Windows is the only platform
> on which a `production_verified=true` has ever been shown to the Owner."*

| | |
|---|---|
| Prior findings re-attacked | **5** (`A-01`…`A-05`) |
| Closed, could not reopen | **4** (`A-02`, `A-03`, `A-04`, `A-05`-as-claimed) |
| Closed on one platform only | **1** (`A-01` — Linux ✅ / Windows 🔴) |
| New findings | **3** (P2 1 · P3 2) |
| Builder mutation claims independently reproduced | 1 of 1 attempted |
| ✅ promotions audited for overclaim | 9 of 9 — **none overclaimed** |

**The quality of the Builder's work this round was high, and saying so is part of the finding.** The `A-05`
row volunteers two things that were *not* done and names the test that still does not exist. The `A-02` row
reports that the fix caught a defect standing in the repository's own test fixture. `A-01`'s commit message
records a scripted edit that went wrong, how it was caught, and that it was reverted. That is the behaviour
these documents keep asking for. It also makes the one unqualified claim stand out more sharply, not less.

---

## 2. New findings

### `B-01` · `A-01` is fixed on the Linux/Python path and untouched on the Windows twin, under a row headed "both platforms" (P2, Windows)

**What was attacked.** `A-01` was reported against **both** platforms, with Windows evidence cited by line
(`win-live/src/servers.rs:157, :174, :782, :1039`). I checked whether the fix reached the twin.

**It did not.** The Windows in-process authority still takes the caller's value and validates only its
*shape*:

```rust
let ids = ["run_id", "task_id", "workspace_id", "install_id", "request_nonce"];
for k in ids {
    match get_str(o, k) { Some(s) if id_ok(&s) => {} _ => return refuse("create-pending", "malformed") }
}
…
let install_id = get_str(o, "install_id").unwrap();      // servers.rs:157-163, :174
```

and that value flows, unmediated, into the scope key of the anti-rollback floor:

```rust
let head = EvidenceHead { install_id: a.install_id.clone(), task_id: a.task_id.clone(), … };
                                                            // servers.rs:1078-1085
```

`evidence_floor_cas` then behaves exactly as the Python twin did before the fix: the per-`(install,task)`
row decides idempotency, the install-wide ceiling is consulted only `if let Some(...)`, and an unknown
`install_id` returns `FloorDecision::Bootstrapped`
(`core/src/supervisor_ledger.rs:936-943`, `:971-991`, `:993-1008`). A caller that names a fresh
`install_id` gets a fresh floor and any head it likes — the transcript from the third audit, unchanged, on
the platform the Owner runs.

**The pin is available and simply unwired.** `win-live/src/config.rs:113` already carries
`pub install_id: String`, and `ResolvedFacts` carries it too (`resolver.rs:31`, `:265`), so the deployment
*knows* its install id — the driver reads it from config and sends it (`bin/win_live_turn.rs:207`). What is
missing is the two-line shape the Python side just adopted: `SupervisorConfig`
(`win-live/src/servers.rs:343-367`) has **no** `install_id` field to compare against, so nothing refuses a
foreign one. The Python fix's own argument applies verbatim — *"an optional pin is not a pin."*

**Severity, stated fairly.** P2, not P0, for the same reasons the original `A-01` was P2: the floor's
*value* is sound (a durable counter, not a constant), the chain the head is derived from is one the caller
cannot write, and the Windows in-process path runs under a compiled-in demonstration root that can never
render `production_verified`. The exposure is the Windows **named-pipe** kit, whose create-pending peer is
the provisioned broker SID. It is a broken defence, not an open door — which is what `A-01` said, on the
platform where it is still true.

**Evidence.** `apps/desktop/src-tauri/win-live/src/servers.rs:157-163, :174, :180, :343-367 (SupervisorConfig,
no install_id), :782, :1078-1085; apps/desktop/src-tauri/core/src/supervisor_ledger.rs:931-1008;
apps/desktop/src-tauri/win-live/src/config.rs:113; apps/desktop/src-tauri/win-live/src/resolver.rs:31, :265;
apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:207; apps/desktop/AUDIT/AUDIT_LEDGER.md (the
`A-01` row, headed "P2, both platforms").`

---

### `B-02` · The `install_id` pin lives in the challenge authority, not in the supervisor that owns the floor — one check, in another service (P3, Linux)

**What was attacked.** The third audit's recommended fix was to pin `install_id` *in `SupervisorConfig`,
the way `supervisor_id` already is*. The Builder pinned it in `AuthorityConfig` instead and argued the
choice in writing — validated rather than substituted, so a misconfiguration fails at the door instead of
three hops away. **That argument is sound and I am not disputing it.** What I checked is what it leaves
standing.

**Result.** The supervisor still never compares `install_id` to anything. `governed_supervisor.py:643`
refuses a foreign `supervisor_id` against `config.supervisor_id`; the adjacent `install_id` is copied out of
the payload with only a non-empty check (`:540-543`, `:665`), and `SupervisorConfig` has no field for it
(`:440-453`). The floor code itself is unchanged and still bootstraps on an unknown install
(`governed_supervisor_ledger.py:801-816` — the ceiling is consulted only `if ceiling is not None`).

So the property now rests on **exactly one** comparison, in a **different process** from the floor it
protects, reached only via one op handler (`challenge_authority_server.py:207`). I confirmed that door is
genuinely single — `store.create_pending(...)` has exactly one non-test caller, on the line after the check
(`:212`) — so this is not a live bypass. It is depth: if the authority's `cfg["resolved"]["install_id"]`
ever diverges from the supervisor's deployment, or a future path reaches `accept_open` with a challenge
signed some other way, the floor is scope-selectable again and nothing downstream would notice.

**Cheap fix, already modelled in the file:** add the `install_id` comparison beside
`governed_supervisor.py:643`. Two checks in two services beats one check in one, for a control whose entire
job is to survive a caller that wants it not to.

**Evidence.** `engine/runtime/governed_supervisor.py:440-453, :540-543, :643, :665;
engine/runtime/governed_supervisor_ledger.py:801-816; engine/runtime/challenge_authority_server.py:193-212;
engine/ci/live/run_authority.py:57, :71-75.`

---

### `B-03` · Two rows were promoted to ✅ by the session that wrote them (P3, process)

`A-03` and `A-04` are marked **✅ CLOSED** in `AUDIT_LEDGER.md` by the commit that made the corrections
(`70ac893`), with the justification *"A documentation finding closes by correcting the document — there is
no code to re-verify."*

Under this file's own legend, ✅ means *"an independent audit confirmed it"*, and `START_HERE.md` states the
rule without an exception for documentation: **"Never promote your own work to ✅."** A corrected sentence is
still a claim until someone who did not write it has read it — that is the whole basis on which every other
row in the file is held at ◑.

**Substantively both corrections are fine, and I am confirming them now** (§3), so the marks end up where
they are. The finding is the precedent: "documentation fixes may be self-certified" is exactly the kind of
narrow exception the two prior RED rounds grew out of.

**Evidence.** `apps/desktop/AUDIT/AUDIT_LEDGER.md (the A-03 and A-04 rows); START_HERE.md ("Say what you did
not do"); AUDIT_LEDGER.md ("How to read the status column").`

---

## 3. The prior findings, re-attacked

### `A-01` — CLOSED on Linux/Python. Mutation independently reproduced. (Windows: see `B-01`.)

**Attacked, not accepted.** (1) Is the pin required or optional? (2) Is the refusal on the only door, or is
there a second path to a stored pending row? (3) Does the required field break a production construction
site? (4) Does the Builder's mutation claim hold when someone else runs it?

* **Required, not optional.** `AuthorityConfig.__init__` takes `install_id` positionally and raises on an
  empty one (`challenge_authority.py:440`, `:469-470`), with the security reason recorded rather than a
  schema note.
* **One door, and I checked for others.** `store.create_pending(...)` has exactly **one** non-test caller
  in the tree (`challenge_authority_server.py:212`), immediately after the comparison at `:207`.
* **No production site broken.** `AuthorityConfig(` is constructed in exactly one non-test place, and it
  passes the field (`run_authority.py:71-75`), sourced from `cfg["resolved"]["install_id"]` (`:57`) — a hard
  `KeyError` if a deployment omits it, i.e. fail-closed at startup rather than silently unpinned.
* **Mutation reproduced by this auditor, on the snapshot:**

```
BASELINE                          Ran 19 tests   OK
MUTANT (the pin block deleted)    FAILED (failures=1)
   test_foreign_install_id_in_create_pending_is_refused
   AssertionError: True is not false
RESTORED                          Ran 19 tests   OK
   sha256(restored file) = 41ff6e4fcdcf0843748f1c22a521dffb15913cceb5c72c5fbb1f2bcb6c5f4802
   sha256(git blob 0a9a1af) = 41ff6e4fcdcf0843748f1c22a521dffb15913cceb5c72c5fbb1f2bcb6c5f4802
```

The test is not decorative: deleting the enforcement fails it, and the restore is byte-exact against the
commit. This is the discipline the third audit named as its own biggest gap, and it now has one independent
instance.

### `A-02` — CLOSED, on both platforms. I tried to forge a chain past it and could not.

The link is genuinely verified now: each event's `previous_event_hash` must equal the digest of the whole
preceding event, the first must be `null`, and `final_event_hash` must be the last digest
(`governed_supervisor_ledger.py:701-712`; Rust equivalent in `win-live/src/servers.rs`). Attacked with five
forged chains through the real `derive_evidence_from_chain`:

```
(a) earlier event tampered, link hashes left as they were      -> REFUSED (InvalidHead: link broken at event 1)
(b) events reordered                                           -> REFUSED (InvalidHead: link broken at event 0)
(c) chain truncated from the front, counts repaired            -> REFUSED (InvalidHead: link broken at event 0)
(d) final_event_hash replaced (the EvidenceFork discriminator) -> REFUSED (InvalidHead: not the last digest)
(e) a fully self-consistent chain over broker-authored bytes   -> ACCEPTED
(f) that same forged chain vs the genuine output_handle        -> REFUSED (EvidenceMismatch)
```

(d) is the one that matters: the `EvidenceFork` discriminator is now bound to the events it summarises,
which is exactly what `A-02` said it was not. (e) is the honest limit and is unchanged — the link binds the
document to *itself*; what stops a wholesale forgery is custody of the directory plus the `output_handle`
check at (f). `A-02` was reported as defence-in-depth and it is now defence-in-depth that works.

**And I ran the risk this fix created.** The verifier now hashes with JCS (`canonical_bytes`) while **both
writers** still emit `serde_json::to_vec` (`governed_recorder.rs:960-963`, `win-live/src/execution.rs:161-173`).
Before `A-02` a divergence was harmless; now it would refuse a *genuine* turn. Reconstructing the exact
three-event shape the real writers produce and digesting it both ways:

```
per-event  serde_to_vec(e) == canonical_bytes(e)   ->  True
final_event_hash agrees                            ->  True
a chain written the way the real writers write it  ->  ACCEPTED
```

So the fix does not break the live path. **The invariant is still enforced by no test**, on either
platform — which the Builder states plainly for the Windows pair (*"No test feeds a Linux-written chain to
the Windows parser… the byte-compatibility claim remains a Builder's assertion"*). That disclosure is
accurate, and it now covers a load-bearing property rather than a cosmetic one. Recommended as the next
cheap test: assert `sha256(serde-form) == sha256(JCS-form)` over one real recorder event, in both suites.

### `A-03` — CLOSED. Correction verified truthful.

The corrected row states both halves as the code behaves: raw form CI-gated (true — `bro_custody.py:151-165`),
file form a **disclosed, deliberately un-custodied posture declaration** (true — `:131-149` applies no owner
check, no mode check, no custody call), with the circularity argument that justifies stopping there kept
rather than dropped. It quotes the module against itself accurately. Nothing overstated.

### `A-04` — CLOSED. Correction verified truthful, including the six symbol names.

The false clause is struck through in place with the reason beside it, and the replacement is exactly right:
`windows_broker` appears **zero** times in `config/reachability-declarations.json` at this head (verified),
and the six `rust_symbols` entries are named correctly — `pull_output`, `governed_pull_output`,
`governed_turn_output_read`, `prepare_governed_turn_v1b`, `resolve_governed_generation_config_v1b`,
`governed_turn_submit_prepared`. The module is recorded as unreachable-AND-undeclared, which is what it is,
and the decision about which to make is explicitly left open rather than quietly taken.

### `A-05` — CLOSED for what it claims, with the residual disclosed better than the finding asked.

The Windows **parser** now uses `crypto::jcs`, so the pair the finding named uses one rule; `brops-win-live`
is **102 passed, 0 failed** (reproduced here, matching the ledger). The row then volunteers the two things
*not* done — the Windows **writer** still emits `serde_json::to_vec`, and no test feeds a Linux-written chain
to the Windows parser — and says the byte-compatibility claim remains a Builder's assertion until one
exists. That is a more honest close than the finding demanded. Folded into `A-02` above: I ran the missing
comparison by hand and it passes today.

---

## 4. The ✅ promotions (PR #100) — audited for overclaim, and clean

A Builder applying an auditor's promotions is an obvious place to round upward. I checked all nine against
what the third audit actually wrote.

**No overclaim found.** The nine rows correspond one-to-one to §3 of that report; each carries what was
attacked rather than a verdict alone; the caveats travel with them — including the decisive one, that the
**Linux live kit was not run**, so every deployment-custody claim is a static read. The two items the audit
left unresolved (`build_tcb_pin_manifest.py` coverage-by-name; `run_supervisor.py`'s §0.1 gate) are
explicitly **not** promoted and are named as still unknown. Three stale ⚠️ rows were corrected; the fourth
item from that table (the 22 dead enforcement tests) became promotion #5 rather than being dropped.

One row deserves its wording noted approvingly: the Windows §2.5/anti-rollback row is promoted to ✅ **BOTH
HALVES EXIST** and immediately qualified — *"Read with `A-01`/`A-02` — those are defects **in** the floor,
not its absence, and they are open."* That is the distinction the promotion could have blurred and did not.

---

## 5. What the auditor ran, personally

All against the frozen snapshot of `0a9a1af` unless noted. Host: Windows 11, Python 3.12.10, cargo 1.96.1.

| What | Result |
|---|---|
| snapshot integrity — `git write-tree` vs `0a9a1af^{tree}` | **identical** (`ca0b7de1…`) |
| engine suite `BRO_ENV=ci python -B -m unittest discover -s tests` (snapshot) | **2001 ran, 43 skipped, 1 failure — and the failure is mine, not the tree's** (below) |
| `cargo test -p brops-win-live --lib` (working tree) | **102 passed, 0 failed** — matches the ledger |
| `tests.test_challenge_authority_server` baseline / mutant / restored | **19 OK / 1 FAILED / 19 OK**, restore digest-verified |
| `attack_a02.py` — six forged chains through the real verifier | 4 refused, 1 accepted-by-design, 1 refused by `EvidenceMismatch` |
| cross-canonicalisation check (serde form vs JCS form, real event shapes) | **agree** — the fix does not break the live path |
| `grep -c windows_broker config/reachability-declarations.json` | **0** — `A-04`'s correction is true |

**The one engine failure is an artefact of my own snapshot, and it is recorded here so it is never
mistaken for a defect in the tree.** On the export, `test_live_hook_deny.LiveHookWiringTests.`
`test_wired_command_denies_out_of_scope` fails with *"The refusal must NAME the missing binding."* The
export is a `git archive` that I then `git init`-ed to prove its tree hash — a repository with no remote and
no commit — and that test reads the workspace binding. Run against the **real** working tree, with a test
file that is byte-identical between `0a9a1af` and `HEAD` (`git diff` empty), it passes:

```
tests.test_live_hook_deny   Ran 2 tests   OK
```

So the ledger's **"2001 OK / 43 skipped"** is corroborated: I measure the same 2001 and the same 43, and my
single failure does not reproduce outside my own fixture. This is the same class of artefact the second
audit reported for its four `git ls-files` errors, and it is excluded from every count above for the same
reason.

**Not re-run this round** (unchanged since the third audit, and nothing in #99–#106 touches them): the 19
repo gates, `brops-core --lib`, and the DDL parity gate.

---

## 6. Coverage, and what this re-audit does NOT cover

* **The Linux live kit was not run**, again — this is a Windows host and the kit is Linux-only. Every
  deployment-custody statement is a static read of the provisioning script. In particular, `B-01`'s Windows
  named-pipe exposure is reasoned from source, not demonstrated on a provisioned box.
* **No Rust mutation.** `A-02`'s Rust half and `B-01` were established by reading and by running the
  existing suites. The Builder's Rust mutation claim (*"delete the Rust block and the new negative FAILS"*)
  is **not** independently reproduced here; only the Python one is.
* **The Windows floor attack was not executed**, only traced. The Python equivalent was executed against the
  real ledger in the third audit; the Rust path shares the same `evidence_floor_cas` body, which I read
  line by line, but I did not drive it.
* **Scope was the five findings and the promotions.** The ~40 other surviving findings of the 2026-08-06
  round were not re-examined. This is a re-audit, not a fourth full round.
* **`3b8acaf` was not audited** beyond confirming it touches no code.

**Process note, unchanged:** creating a file here normally requires the Builder's canonical read receipt
(`tools/check_prior_art.py --declare`). I did not perform that ritual and recorded no receipt I cannot back.
This report is left **uncommitted** for the Owner or Builder to land.

---

## 7. What would change the verdict

1. **`B-01`**: wire the pin into `win-live/src/servers.rs` — an `install_id` on `SupervisorConfig`, compared
   in `create_pending` — with a Rust negative that a mutation kills. Until then the `A-01` row must be
   re-titled to say Linux, not "both platforms."
2. **`B-02`**: the one-line comparison beside `governed_supervisor.py:643`.
3. **`A-02`/`A-05` residual**: one test per platform asserting the serde form and the JCS form of a real
   recorder event digest identically. It is now a load-bearing invariant with no enforcement.
4. **`B-03`**: hold documentation corrections at ◑ like everything else.
5. Then the two things that have not changed: a **separate** audit, and the **Owner's** approval.

---

*Auditor's closing note.* The right way to read this round is that the Builder fixed four findings cleanly,
disclosed more than was asked on the fifth, and applied nine promotions without inflating one of them — and
then shipped the headline fix on one of the two platforms the finding named, under a heading that says both.
The first four facts are why the remaining one is worth stating precisely rather than loudly. `A-01` was
never the most dangerous thing in this repository; it is the most *instructive*, because it has now moved
scope twice — `task_id` → `install_id` → Linux-only — and each move was a real fix that left the property
false somewhere else. The property is not "the floor is scoped correctly." It is "no caller chooses the
scope, on any platform that can serve a turn."
