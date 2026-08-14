# Independent zero-trust audit — menqstudio/OS

**Target:** `main` @ `e0dd9693430b8251a00e6ecd485eeb1d0bad4cc1` (PR #98 merged; working tree clean, `git status --porcelain` empty)
**Brief:** the brief of [`2026-08-06-remediation-audit.md`](./2026-08-06-remediation-audit.md) — same central
question, same adversary model, same rule that a finding must be walked to a concrete attack.
**Commissioned by:** Gev (Owner). **Auditor role only — not the Builder.**
**Date:** 2026-08-14
**Mode:** READ-ONLY on the repository. No repository file was created, modified or deleted except this
report. No commit, no push, no branch, no PR. No gate was touched. Attack harnesses were written to a
scratchpad outside the tree and drive the repository's own modules unmodified; their sqlite ledgers live
in temp directories.

**The single question, unchanged from the previous round:**

> *Can any in-scope adversary cause the desktop app to commit a message with `trust_state =
> trusted_verified` and `production_verified = true` that the governed chain did not actually produce,
> bind and sign?*

**Standing instruction followed:** every `◑` in [`AUDIT_LEDGER.md`](./AUDIT_LEDGER.md) is the Builder's own
unverified claim. This audit tried to **refute** them, not to confirm them. Where a claim survived a real
attack it is recorded as surviving, because an audit that only reports kills is as useless as one that only
reports passes.

---

## 1. Verdict

# RED — but for materially fewer reasons than on 2026-08-06

The gate must stay closed. The Owner should not be asked to open it.

**The RED is now carried by a smaller and better-understood set of defects than the last round's.** The
previous audit's decisive P0 — the broker uid obtaining a signed run-attestation over bytes it authored —
**is closed, on both platforms, and I could not reopen it.** Several other blockers I attacked were closed
too, some of them properly. That is a real change and it should be stated first, because three consecutive
RED verdicts otherwise read as "nothing moved," and something did.

What keeps it RED:

| | |
|---|---|
| New findings this round | **5** (P2 1 · P3 4) |
| ◑ claims attacked | 14 |
| ◑ claims I could not refute (recommend → ✅) | **9** |
| ◑/⚠️ ledger rows found STALE (open in the file, closed in the code) | **4** |
| Ledger rows found false at this head | **2** |
| Test suites independently re-run and reproduced green | 2 |

**The P0 is closed. The anti-rollback floor is not.** `A-01` below shows the evidence-head floor — the
control the F-09 and F-02 rows both lean on — is scoped by a key the party it constrains chooses. This is
the *same* defect the ledger records as closed for `task_id`, surviving one level up at `install_id`, on
**both** platforms. I demonstrated it by driving the repository's own ledger code. It is not a forgery
path on its own, which is why it is P2 and not P0; it is a defence whose scope its adversary selects,
which the code's own docstring says is not a defence.

---

## 2. Findings

### `A-01` · The evidence-head anti-rollback floor is scoped by `install_id`, which the broker chooses — the R-07/R-10 bootstrap defect moved up one level rather than closing (P2, both platforms)

**The claim under attack.** [`AUDIT_LEDGER.md`](./AUDIT_LEDGER.md), Engine/bridge/tools sweep, "◑ Already
closed by later work":

> *P2 R1 `governed_supervisor_ledger.py:640` / `:645` — the anti-rollback floor is keyed on a `task_id` the
> broker chooses → `_evidence_floor_cas` compares against `_install_floor_ceiling` — the highest head
> recorded anywhere on the INSTALL, in any task bucket; `task_id` is only the idempotency key.*

**What was attacked.** The fix is real for the attack it names. My hypothesis was that scoping to the
install removes the *caller's ability to choose the scope* only if `install_id` is not itself caller-chosen.
So: (1) who mints `install_id`; (2) is it compared to anything supervisor-side; (3) does a fresh
`install_id` actually bypass the ceiling; (4) does the Rust twin behave the same, since Windows is the
platform the Owner runs.

**Why it failed.** `install_id` arrives on the wire and is never compared to anything.

* The **broker** puts it into `create-pending` (`broker/src/chain_executor.rs:388`, `"install_id":
  resolved.install_id`).
* `challenge_authority.validate_create_pending` bounds it and nothing else — `_bounded_id`, non-empty,
  `≤ MAX_ID_LEN` (128) (`challenge_authority.py:196`, `:204-215`, `:87-88`).
* The supervisor copies it verbatim out of the signed challenge payload
  (`governed_supervisor.py:665`, `install_id=payload["install_id"]`) after checking only that it is a
  non-empty string (`:540-543`). Contrast `supervisor_id`, which **is** pinned:
  `if payload["supervisor_id"] != config.supervisor_id` (`:643`). `SupervisorConfig` has no `install_id`
  field at all (`:440-453`), so there is nothing to compare it against.
* The floor is then keyed on that value: `_evidence_floor_cas(tx, acceptance["install_id"],
  acceptance["task_id"], …)` (`governed_supervisor_ledger.py:934`), and the ceiling query is
  `WHERE install_id = ?` (`:738-743`). With a fresh `install_id`, `ceiling is None`, the comparison at
  `:802` is skipped entirely, and the row is bootstrapped.

**Executed, against the repository's own code and its own DDL** (harness imports
`engine/runtime/governed_supervisor_ledger.py` unmodified; ledger is a temp-dir sqlite built from
`engine/runtime/supervisor_ledger.sql`):

```
[1] install-A / task-1     / head 99  -> BOOTSTRAPPED
[2] install-A / task-FRESH / head 3   -> REFUSED (StaleEvidence: head_sequence 3 below durable
                                        floor 99 (recorded for task 'task-1' on this install))
[3] install-B / task-FRESH / head 3   -> BOOTSTRAPPED      <-- the same rolled-back head
[4] install-B / task-FRESH2/ head 2   -> REFUSED (StaleEvidence: below durable floor 3)
```

Step [2] is the control: the fix the ledger describes genuinely works. Step [3] is the finding: the
identical rollback, refused under the deployment's own `install_id`, is accepted under a fresh one — and
step [4] shows the resulting floor is the attacker's, not the deployment's.

**The Windows twin has it too, so this is not Linux-only.** `core/src/supervisor_ledger.rs:931-1009`
implements the same two-stage decision — per-`(install,task)` idempotency first (`:936-943`), install-wide
ceiling second (`:971-991`), bootstrap when `stored.is_none()` (`:993-1008`) — over the same shared DDL. Its
`head.install_id` comes from the acceptance row, which the Windows supervisor fills from the wire exactly as
the Python one does: `win-live/src/servers.rs:174` (`get_str(o, "install_id")` in create-pending), `:782`
(stored into the `Acceptance`), `:1039` (handed to the floor). `:157` validates the ids only for
non-emptiness.

**Why it is P2 and not P0.** The floor's *value* is now sound — `head_sequence` comes from a durable
per-recorder counter (`governed_recorder.rs::next_head_sequence`, `win-live/src/head_sequence.rs`) rather
than a constant, and the chain the head is derived from is one the broker cannot write (see §3). So an
attacker who resets the floor still cannot mint an evidence head; they can only stop an old genuinely-signed
head from being refused as stale. Combined with `A-02` — `final_event_hash`, the field that decides
`EvidenceFork`, is never verified against the events it claims to summarise — the fork half of the control
is weaker than the rollback half. It is a broken defence, not an open door.

**The code already states the rule it breaks.** `governed_supervisor_ledger.py:762-765`, in the docstring of
the very function:

> *"`task_id` is not a supervisor secret: it arrives on the wire, `challenge_authority.validate_create_pending`
> accepts any bounded string for it… **A defence whose scope the attacker chooses is not a defence.**"*

`install_id` arrives on the same wire, through the same validator, from the same party.

**Honest fix, no invention required.** `install_id` should be held to the rule `supervisor_id` already
follows one line away: pin it in `SupervisorConfig` from provisioning and refuse a challenge whose
`install_id` disagrees (`governed_supervisor.py:643` is the exact shape). One deployment, one install, one
floor. The Rust twin needs the same pin in `SupervisorConfig`/`Acceptance`.

**Evidence.** `engine/runtime/governed_supervisor_ledger.py:732-743 (_install_floor_ceiling), :746-780
(docstring, incl. :762-765), :786-799 (per-task idempotency), :801-816 (the ceiling), :928-935 (call site);
engine/runtime/governed_supervisor.py:540-543, :643 (supervisor_id IS pinned), :665, :440-453
(SupervisorConfig has no install_id); engine/runtime/challenge_authority.py:87-88, :196, :204-215;
apps/desktop/src-tauri/broker/src/chain_executor.rs:388, :172; apps/desktop/src-tauri/core/src/supervisor_ledger.rs:931-1009;
apps/desktop/src-tauri/win-live/src/servers.rs:157, :174, :782, :1039.`

---

### `A-02` · The run-evidence chain's hash link is still written and never checked, and `final_event_hash` — the field that decides `EvidenceFork` — is copied out of the document unverified (P3, both platforms)

**What was attacked.** The previous round's `R-08` said the chain's hash-linking is decorative: nothing reads
the `events` array, nothing recomputes `previous_event_hash`, nothing compares `final_event_hash` to the
digest of the last event. Both supervisors now *do* read the `events` array, so I re-ran the question
against the current consumers.

**What genuinely changed.** Both twins now parse the chain and check real properties of it: the protocol
tag; exactly one `output-captured` event; **that event's payload against its own `payload_sha256`**; that
`last_sequence == event_count`; that `event_count == events.len()`; and the decisive one, that the reported
`output_handle` equals the captured `output_sha256`. That is a substantial upgrade over three existence
checks (`governed_supervisor_ledger.py:640-685`; `win-live/src/servers.rs:386-430`).

**What did not change.** Neither consumer verifies the *link*. A repo-wide grep for `previous_event_hash`
returns the recorder that writes it (`governed_recorder.rs:912` comment, `:957` the field), the engine's
separate L-4 chain which *does* verify its own link (`bro_evidence.py:157`), tests and fixtures — and no
consumer of `brops.run-evidence-chain.v1`. `final_event_hash` is taken straight off the document with only a
format check (`governed_supervisor_ledger.py:669`, `:674-675`; `win-live/src/servers.rs:419`).

**Why it matters despite the recorder being trusted.** `final_event_hash` is not decoration: it is the
identity the anti-fork branch compares. `_evidence_floor_cas` raises `EvidenceFork("equal head_sequence with
divergent chain content")` on it (`:793-799`), and the Rust twin does the same (`supervisor_ledger.rs:958-966`).
So the fork detector's discriminator is a field nothing binds to the events it summarises, while the
`payload_sha256` check right beside it shows the authors knew how to bind one. Read with `A-01`: the floor's
scope is caller-chosen and its fork identity is unverified.

**Scope, stated plainly.** The chain is written by the recorder into a directory the broker cannot write
(§3), so this is defence-in-depth that is thinner than it looks, not a reachable forgery. P3.

**Evidence.** `engine/runtime/governed_supervisor_ledger.py:640-685 (esp. :655-656 payload digest IS checked,
:669 + :674-675 final_event_hash is NOT), :793-799; apps/desktop/src-tauri/win-live/src/servers.rs:386-430
(esp. :412-416 vs :419); apps/desktop/src-tauri/core/src/supervisor_ledger.rs:958-966;
apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:912, :957; engine/runtime/bro_evidence.py:157 (the
link check that exists for the OTHER chain).`

---

### `A-03` · The ledger claims the self-owned-pin acknowledgement file is custody-checked; the module that reads it explicitly says it is not (P3, honesty)

**The claim under attack.** [`AUDIT_LEDGER.md`](./AUDIT_LEDGER.md), Engine sweep, "◑ Already closed by later
work":

> *P2 R1 `bro_signature.py:263` — `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` is an ungated ambient env var → the raw
> variable is honoured only under `BRO_ENV=ci`; otherwise **a `_FILE` form under a principal this process
> cannot rewrite**, checked through `bro_custody` on both platforms.*

**What held.** The first half is true and is a good fix. `bro_custody.self_owned_acknowledged` refuses the
raw variable outside CI, loudly and by name rather than by silent ignore (`bro_custody.py:151-165`), holding
the acknowledgement to the same `BRO_ENV=ci` gate its two sibling anchors already used — which is exactly
what `R-14` asked for.

**What failed.** The second half. The file form gets **no custody check of any kind**: `self_owned_acknowledged`
reads the path and compares its content to `"acknowledged"` (`bro_custody.py:131-149`). There is no owner
check, no mode check, no `bro_custody` custody call on that path — any file the process can read will do.

The module says so itself, at `bro_custody.py:73-81`:

> *"**What the file form is NOT: a custody-checked artifact.** … It raises the cost from one `export` to an
> `export` plus a file the operator wrote… nothing more."*

And its reasoning for stopping there is sound and worth preserving: making the acknowledgement unforgeable
means making it operator-signed, and verifying that signature needs the very pin whose custody rule the
acknowledgement suppresses. The code is honest. **The ledger row is not** — "under a principal this process
cannot rewrite" describes custody the code deliberately does not implement, in the one file whose purpose is
that a claim and its evidence do not drift apart.

**Fix.** Correct the row to what the code does: *raw form CI-gated; file form is a disclosed, deliberately
un-custodied posture declaration, with the circularity argument recorded.*

**Evidence.** `engine/runtime/bro_custody.py:53-86 (the block comment, esp. :73-81), :109-166 (esp. :131-149
the unchecked file read, :151-165 the CI gate); engine/runtime/bro_signature.py:85-87, :397-403, :499-527;
apps/desktop/AUDIT/AUDIT_LEDGER.md (Engine sweep, "already closed" table, bro_signature.py:263 row).`

---

### `A-04` · A ledger row that a later sweep proved false is still in the file, uncorrected, and is still false at this head (P3, honesty)

**What was attacked.** The Desktop-surface sweep's "◑ Deliberately NOT fixed" list says of
`core/src/windows_broker.rs:272`:

> *"Already declared with written reasons in `config/reachability-declarations.json`."*

The later Windows sweep records that this is **FALSE** and explains why it matters. I checked the current
head rather than either sweep.

**Result: still false at `e0dd969`.** `grep -c windows_broker config/reachability-declarations.json` = **0**.
The file's `rust_symbols` block holds exactly six entries — `pull_output`, `governed_pull_output`,
`governed_turn_output_read`, `prepare_governed_turn_v1b`, `resolve_governed_generation_config_v1b`,
`governed_turn_submit_prepared` — and names no symbol in `windows_broker.rs`. By that file's
own vocabulary the module remains "unreachable-AND-undeclared — the state in which nobody can tell which of
those it is."

**Why it is a finding and not bookkeeping.** This ledger's stated rule for a disagreement is *"the row wins
and the prose is the defect."* Here two **rows** disagree, in the same file, and the false one is the one a
reader hits first. The Windows sweep chose to report rather than silently edit — right for a Builder, and
exactly why an auditor exists to close it. I am closing it: **strike the Desktop-sweep clause**, and either
declare the symbol in `config/reachability-declarations.json` or record that it is undeclared.

**Evidence.** `config/reachability-declarations.json (keys: $comment, tauri_commands, engine_symbols,
rust_symbols, tools_gates; rust_symbols has 6 entries, zero matching windows_broker);
apps/desktop/AUDIT/AUDIT_LEDGER.md (Desktop-surface sweep "Deliberately NOT fixed" vs Windows sweep
"Deliberately NOT fixed").`

---

### `A-05` · The two twins compute the same document's payload digest by two different rules, while a JCS helper sits unused three lines away (P3, both platforms)

**What was attacked.** The F-02 row's claim that the Windows chain is *"byte-compatible with the Linux
recorder's"* and that *"both platforms derive the head the same way from the same document"*
(`win-live/src/servers.rs:384-385`).

**What I found.** They do not derive it the same way. Checking the `output-captured` payload against its own
`payload_sha256`:

* Linux: `_sha256_hex(canonical_bytes(payload))` — JCS (`governed_supervisor_ledger.py:655`).
* Windows: `crypto::sha256_hex(&serde_json::to_vec(payload)?)` — plain serde serialization
  (`win-live/src/servers.rs:412-413`).

The same file uses `crypto::jcs(...)` for the record and receipt documents it builds thirty lines later
(`:949`, `:971`), so the canonical helper was available and was not used here.

**Severity.** Low, and it fails in the safe direction: for the payloads this chain actually carries the two
encodings agree, and where they ever diverged the effect is a refused turn (`derive_evidence` returns `None`
→ `malformed_state`), not an accepted forgery. It is recorded because "byte-compatible" is asserted in a
comment, is the basis of a cross-platform claim in the ledger, and is enforced by nothing — no test compares
a Linux-written chain against the Windows parser. That is the shape this repository keeps finding.

**Evidence.** `apps/desktop/src-tauri/win-live/src/servers.rs:384-385 (the claim), :412-413 (serde), :949, :971
(crypto::jcs, used for other documents); engine/runtime/governed_supervisor_ledger.py:655 (canonical_bytes).`

---

## 3. ◑ claims I attacked and could NOT refute

These are recommended for promotion to ✅ — an independent auditor looked, tried to break them, and failed.
Each names what I actually did, so a later reader can judge the strength of the confirmation.

**The three production-gate refusals — CONFIRMED CLOSED.** Verified by reading, not by trusting the prose.
`governed_verification_unconfigured()` is `Some(GOVERNED_VERIFICATION_UNCONFIGURED)` unconditionally, with no
branch (`src/commands.rs:1161-1164`). `connect_broker` is `#[cfg(target_os = "linux")]` with every other host
returning `UnsupportedPlatform` (`src/governed_turn.rs:225-232`). `build_governed_executor` returns
`fail_closed()` — `UpstreamBlockedExecutor` — unless `$BROPS_BROKER_CONFIG` is set and non-empty, and again if
the config is unreadable or malformed (`broker/src/main.rs:266-280`). **The gate is closed at this head.**

**F-01's second half — the `output_handle` sign-oracle — CONFIRMED CLOSED on both platforms.** This was the
previous round's P0 and the reason for its RED. I attacked the mechanism, not the wording.
* The supervisor derives the evidence head from the recorder's chain and refuses a completion whose
  `output_handle` is not the digest the recorder captured (`governed_supervisor_ledger.py:624-685`, the check
  at `:661-666`), reached on the only path to `COMPLETED` (`governed_supervisor_server.py:794-806`).
* The chain is read from the recorder's own directory by supervisor-minted attempt id, with traversal
  refused and a 1 MiB bound, and an unreadable or absent chain is a refusal, not a default
  (`run_supervisor.py:103-116`; `governed_supervisor_server.py:799-802`).
* The custody the claim rests on is real in the kit: `chown -R "$RECORDER_USER":"$SUPERVISOR_USER"
  "$RECSTATE"; chmod 0750` (`run_live_turn.sh:278`) — recorder writes, supervisor group-reads, the broker has
  no access at all.
* The wall the previous audit would have walked around is closed too: the broker used to choose the
  recorder's `--launcher`/`--executor`/`--store`/`--lease` on the command line, so it could have had the
  *recorder* write an authentic chain for an execution the *broker* authored. The recorder now reads all of
  them from a root-owned policy at a path compiled into the binary and refuses any argv that disagrees
  (`run_live_turn.sh:149-204`).
* The Windows twin performs the same binding and refuses `evidence_mismatch`
  (`win-live/src/servers.rs:941-947`).
* It is covered by a genuine end-to-end negative test, not an assertion: the broker substitutes its own reply
  text after a real accept→gate→start sequence and the supervisor answers `evidence_mismatch`, with a second
  assertion that nothing downstream can be signed (`test_governed_chain_e2e.py:657-684`, and
  `test_a_run_the_supervisor_cannot_observe_is_not_recordable` beside it).

**`R-04` / F-08's outer equality — CONFIRMED CLOSED, and this was a real gap.** The previous round found
"launcher pin = executed bytes = attested digest" true for the middle equality and false for the outer one,
asserted only by a deployment-time shell check. There is now a runtime comparison:
`verify_lease_matches_attested_request` compares all three lease pins against the attested request and
refuses per-slot (`launcher/src/main.rs:491-505`), called in `real_main` before any drop or exec (`:592`),
with the attested config read from a **compile-time** path so the broker has no runtime input that redirects
it (`:586-591`).

**`R-03`'s store-input custody — CONFIRMED CLOSED.** The fds 3/4/5 check is no longer "a regular file ≤ 8 MiB":
each must name a regular inode owned by root/brops-admin with no group or other write bit, so no principal
outside the TCB can rewrite the bytes under the executor (`launcher/src/main.rs:600-605` and the IDX-3 note).

**The 45-skipped-test gap from §5.4 — CONFIRMED CLOSED, and it is the cleanest fix in the wave.** The
previous audit's own finding was that 22 enforcement-path tests were dead on every platform, because
`_ENGINE_IS_GIT_ROOT` can never be true in this monorepo. The skip is gone: `engine/tests/_engine_git_root.py`
*manufactures* the precondition — copies the tree, `git init`s it, commits, adds a remote — and both modules
now run against it (`_engine_git_root.py:158-194`). The two `skipUnless` lines a grep still finds are inside
docstrings describing the old state (`test_hooks_subprocess.py:120-140`). Reproduced empirically: the previous audit measured
**909 ran / 45 skipped**, of which 22 were this guard; I measure **1995 ran / 43 skipped**, and the
git-root skip is not among them. The fixture's own removal of two known displacers
(`PYTHONDONTWRITEBYTECODE`, the O-1 acknowledgement) is documented with what it *subtracts* from the proofs —
which is the honest way to do it.

**The CI wiring claims — CONFIRMED TRUE.** Read from `.github/workflows/ci.yml`, not from the ledger:
* `governed-crates` really does test all six production crates: `-p brops-launcher -p brops-executor -p
  brops-broker -p brops-governed-live -p brops-win-live -p brops-win-broker` (`ci.yml:68-70`). The "52 tests
  in no CI job" row is closed, and the Tauri host crate's exclusion is stated rather than papered over
  (`:65-67`).
* `engine-windows` really runs the engine suite on `windows-latest`, with `-v` and a stated reason for it
  (`ci.yml:226-258`). The old "every F-06 test is skipped on Windows" gap is closed.
* The F-08 negative case is real and is wired: the live job runs `run_live_turn.sh` (`ci.yml:118-119`), which
  tampers with a pinned store input and requires the launcher to refuse — and asserts the **cause**, not
  merely that something was blocked (`run_live_turn.sh:431-449`, `:465-482`). Two further negatives sit
  beside it (argv-steering, `$RECSTATE` made group-writable at `:578-587`). This is the shape the ledger
  claims: a test that deleting the enforcement cannot pass.

**The DDL parity gate — CONFIRMED TRUE.** `check_ledger_ddl_parity.py` returns GREEN at this head, and the
job is wired.

**The repository's own gates — CONFIRMED HONEST.** I ran all 19 `tools/check_*.py`. Sixteen GREEN; three
print usage because they require arguments (`check_canonical_sync`, `check_prior_art`, `check_read_receipt`);
one RED for the documented reason (`check_bundle_budget` wants a Vite manifest from `npm run build`). This
matches `START_HERE.md`'s description exactly, including its correction of the older "15 gates, all green"
sentence. `check_runbook_snippets` is GREEN once `cryptography` is installed, as documented.

**One of the three "not re-verified deeply enough to claim either way" items — RESOLVED in the Builder's
favour.** The engine sweep declined to judge whether *"the two F-01 regression tests assert only that an
unknown attempt id is refused"* (`test_governed_chain_e2e.py:487`). They do not. The module carries **16**
tests, including the substituted-reply negative quoted above, a no-chain-at-all negative, a smuggled-field
negative, and an F-27 clock test that pins accept-at-T−2000 against complete-at-T. The row can be marked
closed. The other two items (`build_tcb_pin_manifest.py` coverage-by-name, `run_supervisor.py`'s §0.1 gate)
I did not drive either, and they stay unknown — see §6.

---

## 4. Ledger rows that are STALE at this head

Reported so the Owner is not reading open findings that the code has closed. I did not edit the ledger; that
is the Builder's commit to make.

| Row | Marked | Actually, at `e0dd969` |
|---|---|---|
| `NULL DACL makes FILE_FLAG_FIRST_PIPE_INSTANCE inert` (Round-2 table) | ⚠️ OPEN | **Closed.** `win-live/src/pipe.rs` builds a real DACL (`:62`, `:146-150`) and a test asserts the pipe must **not** have a NULL DACL (`:572`), with a note that a regression restores it (`:470`). |
| `Windows kit: no §2.5 floor, no anti-rollback floor` (Round-2 table) | ⚠️ OPEN | **Both halves now exist.** `win-live/src/tcb_floor.rs` is 834 lines; the anti-rollback floor runs through `brops_core::supervisor_ledger::evidence_floor_cas` with `head_sequence` from the durable counter in `win-live/src/head_sequence.rs`. Subject to `A-01`/`A-02`, which are defects *in* the floor, not its absence. |
| `bound is a tautology (CommittedMessage::new hardcodes trust_state)` (Round-2 table) | ⚠️ OPEN | **Wrong row, as the Desktop sweep already said.** `trust_state` is a parameter (`core/src/governed_turn_ipc.rs:239-245`). The sweep recorded the correction and the row was never changed; it should be. |
| 22 enforcement-path tests dead on every platform (audit §5.4) | open finding | **Closed** — see §3. |

Two further rows are false rather than stale and are written up as findings: `A-03` and `A-04`.

---

## 5. What the auditor ran, personally

Not agent output. Commands executed on this host (Windows 11, Python 3.12.10, cargo 1.96.1, node 22.22.3)
against the clean `e0dd969` working tree.

| What | Result |
|---|---|
| `git rev-parse HEAD` / `git status --porcelain` | `e0dd969…`, clean — the tree audited is the tree named |
| engine suite: `BRO_ENV=ci python -B -m unittest discover -s tests` | **1995 tests, OK (skipped=43)**, 408 s |
| `cargo test -p brops-core --lib` | **471 passed, 0 failed, 0 ignored** |
| all 19 `tools/check_*.py` | 16 GREEN · 3 usage (args required) · 1 RED (`check_bundle_budget`, no Vite build) |
| `attack_floor.py` — drives the real `_evidence_floor_cas` over the real DDL | **`A-01` reproduced**, transcript in §2 |
| `grep -c windows_broker config/reachability-declarations.json` | **0** — `A-04` |

On test counts: the ledger's sweeps recorded **1915/43** for the engine suite and **376** for
`brops-core --lib` at their own commits. I measure **1995/43** and **471**. The deltas are growth across the
PRs merged since, in the right direction, and both suites are green on a host that is not CI. The ledger's
numbers are credible.

**One environment change I made, disclosed:** the engine suite cannot run here without `cryptography`, which
was absent. I installed `engine/requirements-ci.txt` (`cryptography 46.0.3`, `cffi 2.1.0`,
`typing-extensions 4.16.0`) into the user's Python — outside the repository, and the same set CI installs. My
first run, before it, reported *519 tests, 70 errors*: that number is an artefact of my box and is recorded
here only so it is never mistaken for a defect in the tree.

---

## 6. Coverage, and what this audit does NOT cover

Stated because the brief requires it and because an audit that hides its edges is the thing this repository
keeps catching.

**Read closely and attacked:** `governed_supervisor_ledger.py` (evidence/floor/completion paths),
`governed_supervisor.py` (challenge validation, accept_open, config binding), `governed_supervisor_server.py`
(`complete_governed_run`), `bro_custody.py`, `run_supervisor.py`, `run_live_turn.sh` (custody, recorder
policy, negatives), `launcher/src/main.rs` (`real_main` ordering, lease/attested comparison),
`broker/src/main.rs` (the gate), `src/commands.rs` + `src/governed_turn.rs` (the other two refusals),
`core/src/supervisor_ledger.rs:904-1010`, `win-live/src/servers.rs` (evidence derivation, complete_run),
`win-live/src/head_sequence.rs`, `.github/workflows/ci.yml`, `config/reachability-declarations.json`, the
full `AUDIT_LEDGER.md`, and the brief-bearing sections of the remediation audit.

**NOT covered — no verdict should be read into these:**
* **The Linux 7-service live kit was never executed.** This is a Windows host and the kit is Linux-only. Every
  claim about deployment custody — modes, uids, group membership, the sudoers rule — is a **static read of
  the provisioning script**, not an observed system state. `A-01`'s harness drives the ledger code directly,
  not the kit.
* **Only `brops-core` was compiled and tested.** `brops-win-live`, `brops-launcher`, `brops-executor`,
  `brops-broker`, `brops-governed-live`, `brops-win-broker` were read, not run. The ledger's per-crate counts
  for them are unverified by me.
* **No mutation testing.** The ledger's mutation results (13/2, 17/3, 16/2 across three sweeps) are **not**
  confirmed here. I did not delete a check and watch a test go red. That discipline is the repository's, and
  re-running it is the single highest-value thing a next audit could do — `A-02` is precisely the kind of
  gap a mutation of `derive_evidence_from_chain` would have surfaced.
* **The isolated signer, the challenge authority server, the desktop UI surface and the frontend suites** were
  touched only where a trail led into them. `isolated_signer.py`'s `_CHAIN_AGREEMENT` was read but not
  attacked; note that the ledger itself already records why that comparison cannot fail — the documents it
  compares are built by one supervisor from one pair of rows.
* **The other 40-odd surviving findings** of the 2026-08-06 round were not individually re-checked. This
  audit attacked 14 `◑` claims chosen for how much the gate leans on them; it is not a full re-run of that
  round.
* **Nothing elevated was run**, so the Windows custody tests with declared elevation prerequisites remain
  unexercised here, exactly as the ledger says.

**Process note.** Creating a file in this repository normally requires the Builder's canonical full-read
receipt (`tools/check_prior_art.py --declare`). I did not perform that ritual and did not record a receipt I
cannot back: I read `START_HERE.md` and `AUDIT_LEDGER.md` in full and the other canonical documents only in
the parts this brief reached. This report is therefore left **uncommitted** for the Owner or the Builder to
land. No branch, no PR, no push.

---

## 7. What would change the verdict

Not a fix list — the conditions under which an auditor could stop writing RED.

1. **`A-01` closed**: `install_id` pinned in `SupervisorConfig` and refused on mismatch, on both twins, the
   way `supervisor_id` already is — with a negative test that presents a fresh `install_id` and a rolled-back
   head and requires `StaleEvidence`.
2. **`A-02` closed or consciously accepted**: either verify the link (`final_event_hash` == digest of the last
   event; `previous_event_hash` recomputed across the chain) in both consumers, or stop describing the chain
   as hash-linked evidence and record that its head fields are trusted because the recorder wrote them.
3. **`A-03` and `A-04` corrected in the ledger** — both are one-line edits, and both are exactly the drift
   that file exists to prevent.
4. **A mutation round over the F-01 evidence path**, since that path is now the load-bearing one and its
   decisive check has a single test.
5. Then, and only then, the two things the ledger has always said: a **separate** audit, and the **Owner's**
   approval. Not a green CI run, and not this document.

---

*Auditor's closing note.* Three rounds have now returned RED, and it would be easy to read that as no
progress. It is not what I found. The P0 that carried the last verdict is genuinely dead; the F-08 equality
that was asserted by a shell script now runs in the launcher before the exec; the recorder can no longer be
steered by broker argv; 22 tests that ran nowhere now run; and the negatives in the live kit assert *why*
they refused. What I found instead is one control that was fixed against the attack it was named for and not
against the attack it invites — and four places where a document says more than its code does. That is a
better class of RED than the last one.
