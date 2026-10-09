# T-169 · The owner-command path — a design proposal, written to be attacked

**Date** 2026-10-09 · **Base** `main` after PR #380 · **Status** PROPOSAL. Nothing in this
document is built. No code, schema, capability or test described here exists unless a section says
"exists today" and names the symbol.

**Author** the Builder session (Claude), at the Owner's instruction. **Reviewer wanted** an
independent auditor. The Builder cannot review this: it wrote it, and the last recommendation it
made without looking (the Linux self-test, `docs/OWNER_ACTION_REQUIRED.md` 2h) was wrong on the
facts.

## 0. What the auditor is asked to do

Break it. The Owner's words: *go deep on every point, try hard to break it, so that if there is a
hole anywhere we close it.* Concretely:

1. **Section 2 is a statement of what the tree does today.** Every line names a symbol. Check each
   against the code. A wrong line there invalidates what is built on it, and a design that rests on
   a misreading is the cheapest thing to find now and the most expensive later.
2. **Section 5 is the attack list.** Each row is a claim the design makes, where it would be
   enforced, and the test that would have to exist. For each: does the claim hold, is the
   enforcement point the right one, is the test able to fail? Then add the rows that are missing.
   A list written by the designer is the list of attacks the designer thought of.
3. **Section 6 is where the Builder thinks the design is weakest.** Start there if time is short.
4. **Section 8 is six decisions.** Each carries a recommendation. Overrule any of them.
5. Return a verdict per section — ACCEPT, CHANGE (say what) or REJECT — and a list of everything
   that broke. A verdict of "ACCEPT, nothing found" on section 6 should be treated with suspicion
   by whoever reads it, including the auditor.

Nothing here opens the production gate. The three refusals in `CLAUDE.md` section 6 are not
touched, `governed_turn_execute` stays outside the window's capability set, and no model is called
anywhere on this path.

## 1. Why this exists

On 2026-10-09 the product was installed on a real machine for the first time (a locally built
`.deb`, Debian 13) and driven on that machine's own display. In order, what the installed
application showed:

| Step | What the Bridge page's mirror rows printed |
| --- | --- |
| as shipped | `Command read_decision_ledger not allowed by ACL` |
| after the Owner granted the four reads (PR #378) | `the governance mirror is not provisioned: BROPS_GOVERNANCE_STATE_DIR is unset` |
| started with the mirror's three settings and an empty directory | `ANSWERED · NOTHING TO MIRROR` |

The third row is the engine answering honestly through the whole path — window, host, sidecar,
engine. Asked directly, the sidecar gives the reason: `the orchestration runtime holds no tasks, so
nothing has been recorded`.

So the question became: what would put a task there? The answer, read in the code and set out in
section 2, is that **nothing in the product can** — and that the owner's half of the control room
is built as two pieces that do not meet. `O-4` in `docs/PHASE_10_PRODUCTION_ITEMS.md` records one
edge of this ("nothing outside tests calls `mint_control_room_command`") at severity LOW. The
consequence it does not draw is that the governance mirror, the Decisions page's engine ledger, the
approval queue and the verifier verdicts are windows onto a store that no shipped code path writes.

## 2. What exists today

Read on 2026-10-09 at the base named above. Symbols, not line numbers. Where something was
searched for and not found, the search is stated; a search that finds nothing is not proof of
absence.

### 2.1 The store

- `DurableOrchestrationRuntime` (`engine/runtime/bro_orchestration_runtime.py`) keeps one
  directory per task under `<state_dir>/tasks/<task_id>/`: `contract.json` and
  `records/<sequence>.json`.
- Records are chained by `previous_record_sha256` / `record_sha256` (`_records`, `_append`,
  `_hash_record`). **The chain is an unkeyed SHA-256.** Whoever can write the directory can rewrite
  every record and recompute the chain; `_records` would accept it. This is the same property `O-2`
  records for the audit ledger.
- Appends are exclusive-create (`_exclusive_json`) under `_mutation_guard` / `_claim_guard`, a lock
  file that a later caller may steal after `STALE_LOCK_SECONDS` (`_break_stale_lock`).
- `_task_dir` refuses a `task_id` containing `/` or `\` and nothing else.

### 2.2 Who may write, and how they are proven

- **`create_task(contract, queue_class, now_epoch, budget_limits)` asks for no actor at all.** It
  validates the contract (`validate_task_contract`) and writes the `draft` and `queued` transitions
  under the conductor's identity with `identity_basis = ACTOR_RUNTIME_ORIGINATED`. Whatever can
  call it creates a task. Searched for callers outside `engine/tests` — `.create_task(` across
  `engine/runtime`, `engine/tools`, `engine/ci`, `bridge` — none found.
- **`_prove_actor` can prove exactly one actor: the conductor**, by a `conductor-session` artifact
  verified with `verify_artifact` against `self.evidence_keys`, on the wall clock. For `owner`,
  `system` and `agent` it raises unconditionally (`_ACTOR_UNPROVABLE`).
- Therefore **every owner mutation in the runtime refuses today**: `retry_blocked`,
  `cancel_task(actor_type="owner")` and `recover_task` all call `_prove_actor("owner", …)`. Their
  docstrings say so ("this path refuses today").

### 2.3 The control room API

- `ControlRoomAPIV1` (`engine/runtime/bro_control_room_api.py`) is read-only views plus
  `governance_read` plus **one** entry that takes a command: `validate_command_intent`.
- `validate_command_intent` does prove an owner — `_prove_command_actor` verifies a
  `control-room-command` artifact and requires its `command_id`, `task_id` and `command` to equal
  the command in hand — and then returns `"valid": True, "executed": False,
  "mutation_authorized": False`. The last two are literals. It checks that validating did not
  change the store (`"command validation mutated runtime state"`).
- **There is no function that executes a validated command.** Searched: every method of
  `ControlRoomAPIV1`; `ControlRoomAPIV1(` is constructed in one place outside tests, the mirror
  read in `bridge/engine_sidecar.py`.

### 2.4 The signer

- `provision::mint_control_room_command(trust_dir, command_id, task_id, command, session_id,
  expires_at_epoch, out)` (`apps/desktop/src-tauri/provision/src/lib.rs`) signs the artifact with
  the retained `control-room` key and refuses an expiry that is not in the future. Callers: two
  test files, nothing else (`grep mint_control_room_command`).
- On the installed machine that key is `<app-data>/trust/keys/control-room.json`, mode `0600`,
  owned by the desktop account (observed 2026-10-09).

### 2.5 The transport

- `bridge/engine_sidecar.py` serves an op table `_OPS`: `governance.read` and `approval.request`.
  An unknown op is refused by name. There is no command op.
- The desktop reaches the sidecar by spawning `$BROPS_GOVERNED_PYTHON $BROPS_GOVERNED_SIDECAR`
  (`ai.rs`, `governed_sidecar_read`). **The installed package ships neither `engine/` nor
  `bridge/`.** An installed application has a sidecar only if it is pointed at a checkout.
- The engine's trusted keys come from `BROPS_GOVERNANCE_REGISTRY_ROOT`, an environment variable of
  the process that launched the desktop.

### 2.6 Five contradictions the reading turned up

These are findings in their own right. The design has to take a position on each.

- **C1 — the two halves of the owner path do not meet.** The API can prove an owner and will not
  execute; the runtime can execute and cannot prove an owner. No call sequence available today
  turns an owner's command into a transition.
- **C2 — two different answers to "what proves an owner".** `OWNER_ACTOR_UNPROVABLE` in the runtime
  says re-opening the owner path needs an artifact type registered against the **operator-root**
  authority. `_prove_command_actor` and `provision::mint_control_room_command` use the
  **delegated `control-room`** authority, and argue for it in their comments. One of the two texts
  is stale, and they disagree about which key may speak for the owner.
- **C3 — the command vocabulary and the runtime's mutations are not the same set.**
  `engine/orchestration/registry.json` defines `approve`, `deny`, `cancel`, `retry`, `reassign`,
  `request-verification`. The runtime offers `retry_blocked`, `cancel_task`, `recover_task`.
  `approve`, `deny`, `reassign` and `request-verification` have no owner-side mutation at all;
  `recover_task` has no command. And `retry` is allowed by policy in `blocked`, `failed`,
  `cancelled` while `retry_blocked` requires `blocked` or `waiting-approval`.
- **C4 — creation is the one unproven write.** Every other transition names a proof; `create_task`
  names none and records the conductor's identity for whoever called it.
- **C5 — a read writes.** Pointing the mirror at an empty directory created `tasks/` inside it
  (observed 2026-10-09). A read path that writes fails on a read-only store and changes what it
  was asked to observe.

## 3. Scope of the proposal

**One command, end to end: the owner cancels a queued task, and the mirror shows it.**

`cancel` is chosen because it is the only command that (a) the policy allows an owner in a state a
fresh task is actually in (`queued`), (b) the runtime already has a mutation for, with the proof
seam already in its signature (`cancel_task(..., actor_attestation=…)`), and (c) cannot make
anything run: a cancelled task is terminal. The first owner write should be the one that can only
stop things.

In scope:

1. A wire frame for an owner command, and a sidecar op that carries it.
2. An engine entry point that validates **and executes** one command atomically.
3. The runtime accepting a per-command owner proof — which requires resolving C2.
4. A desktop command, behind a native confirmation, that signs and sends.
5. Replay protection.
6. Fixing C5, since the mirror is how the result is seen.

Out of scope, named so that nobody reads them in:

- Task creation by the product (C4). See decision D1 — this slice needs a task to exist and says
  honestly how it gets there.
- The other five commands (C3). Each needs its own mapping and its own review.
- Where the engine lives in an installed product, and under which account (section 6.1, D2).
- `governed_turn_execute`, the production gate, any model call.
- Windows. The path is engine-side Python plus the sidecar; the desktop half is portable. Not
  examined beyond that.

## 4. The design

### 4.1 Principals and keys

| Thing | Where | Held by |
| --- | --- | --- |
| `control-room` signing key | `<app-data>/trust/keys/control-room.json`, `0600` | the desktop account; exists today |
| trusted-key registry | the provisioned registry under the machine anchor | root-owned, read by the engine |
| orchestration state | `<state_dir>/tasks/…` | **undecided — section 6.1** |

No new key and no new authority. The proposal uses the `control-room` authority exactly as
`_prove_command_actor` already does, and asks the audit to rule on C2 in that direction (D3).

### 4.2 The wire frame

A new op in `_OPS`, `control-room.command`, with protocol `brops.control-room-command.v1`.

Request, exact key set, refused if any key is missing or extra:

```
protocol            "brops.control-room-command.v1"
op                  "control-room.command"
command             the control-room-command schema object, all twelve required fields
actor_attestation   the signed control-room-command artifact document
```

Reply, always exit 0, verdict in the payload as every other op:

```
protocol, schema, ok
command_id, task_id, command
executed            true only when a transition was appended
transition          record_id, sequence, previous_state, next_state, record_sha256   (ok only)
actor               identity_basis, key_id, session_id, attestation_sha256           (ok only)
error               the engine's own words                                           (refusal only)
```

What does not cross: no private key, no lease, no registry path, no state directory path in the
request. The sidecar takes both from its own environment, as the mirror does.

### 4.3 The engine entry point

A new method beside `validate_command_intent`, proposed name `execute_command_intent`. One
function, one guard:

1. Take `_mutation_guard`. **Everything below happens under it**, so that the state a command was
   validated against is the state it is applied to.
2. Run the existing validation in full — schema, ID format, scope, normalisation, actor proof,
   policy, expected state.
3. **Replay check:** refuse if `command_id` already appears in this task's records. The records
   are the ledger; there is no second store to drift from them.
4. Map the command to the runtime mutation. In this slice the map has one row: `cancel` →
   `cancel_task`. Any other command is refused by name: *"not executable in this build"*.
5. Call the mutation, passing **the attestation document itself** — never the proof dictionary the
   API computed. The runtime verifies it again (4.4).
6. The transition record carries `command_id`, the attestation digest and the proof.
7. Return `executed: true` with the record's identity, or raise.

`validate_command_intent` stays as it is, including `"executed": False`: validating is a different
question from executing and callers should be able to ask it without side effects.

### 4.4 The runtime accepts an owner proof

`_prove_actor` gains one arm: for `("owner", "owner-gev")` it verifies a `control-room-command`
artifact with `verify_artifact`, on the wall clock, and requires the artifact's `command_id`,
`task_id` and `command` to equal those of the mutation being performed. The mutation therefore has
to tell `_prove_actor` which command it is — `cancel_task` and its siblings grow a `command_id`
argument on the owner path.

The proof is **re-derived in the runtime from the signed document**. A proof dictionary handed
down from the API would be the caller vouching for itself one layer lower, which is the defect the
module's own comments describe.

`OWNER_ACTOR_UNPROVABLE` is rewritten to say what is now true, and C2 is closed in one direction
or the other by the audit (D3).

### 4.5 Replay

Three bounds, each independent:

- **Single use.** A `command_id` may appear in a task's records at most once (4.3 step 3).
- **Short life.** The desktop mints with a short expiry — proposed 60 seconds — and the engine
  judges expiry on its own wall clock, as `_prove_command_actor` does today.
- **State binding.** `expected_task_state` must equal the current state under the guard. A replay
  after a successful cancel fails this even if the first bound were broken, because the task is
  terminal.

### 4.6 The desktop command

A new Tauri command, proposed name `issue_control_room_command`, declared in `build.rs`
`COMMANDS`, `command-policy.json` and `capabilities/default.json` at **tier A** (approval
authority), because it exercises the owner's authority.

- The renderer supplies **three things**: `task_id`, `command`, `reason`. Nothing else.
- The host supplies everything that identifies or times the command: `command_id` (a fresh UUID),
  `requested_by_type`/`requested_by`, both timestamps, `expected_task_state` (read from the mirror
  by the host, not echoed from the renderer), `scope`, `evidence_refs`.
- Before signing, the host raises the **native confirmation dialog** already used for approvals
  (`T-011`): renderer-independent, showing the task id, the command and the reason as the host
  holds them. A declined, dismissed or unshowable dialog signs nothing.
- Only after a yes does the host call `mint_control_room_command`, and it writes the artifact
  nowhere but the request it sends: the `out` path argument of the existing function writes a
  file, so the function is split into "sign" and "sign and write" and this path uses the first.
- The reply is shown as the engine gave it. `executed: false` is never rendered as done.

### 4.7 The mirror

No change to the read contract. After a successful cancel the `decisionLedger` surface carries the
`task-cancelled` transition with its `actor_proof`, and the page shows a row. That row is the
acceptance test of the whole slice, observed in an installed application.

### 4.8 The read that writes (C5)

Constructing the runtime for a read must not create anything. Either the constructor stops
creating `tasks/`, or the mirror constructs a read-only view. The test opens the state directory
read-only (mode `0500`) and performs all four reads.

## 5. The attack list

Each row: what an attacker tries, what the design says happens, where that is enforced, and the
test that has to exist. "Mutation" in the last column means: delete the enforcing check, confirm
the test goes red, restore. Rows the Builder could not answer are marked **OPEN** and repeated in
section 6.

### 5.1 The signature

| # | Attack | Claimed outcome | Enforced in | Test |
| --- | --- | --- | --- | --- |
| A1 | Send a command with no attestation | refused, owner unprovable | `_prove_command_actor`, and again `_prove_actor` | both layers, mutation on each |
| A2 | Attestation signed by a key not in the registry | refused | `verify_artifact` | real foreign key, not a corrupted signature |
| A3 | Attestation signed by a registered key of **another authority** (`builder`, `issuer`, `evidence-recorder`) | refused: artifact type not granted to that key | `verify_artifact` / `ARTIFACT_AUTHORITY` | one case per retained authority |
| A4 | A valid `conductor-session` presented as the owner's proof | refused: wrong artifact type for this actor | the `artifact_type` selection in `_prove_command_actor`; the new arm of `_prove_actor` | both layers |
| A5 | Valid attestation for command X sent with command Y (different `command_id`) | refused | field comparison after verify | re-signed so only the binding differs |
| A6 | Same, differing only in `task_id` | refused | same | same |
| A7 | Same, differing only in `command` (`cancel` signed, `retry` sent) | refused | same | same |
| A8 | Attestation with `role`/`agent_id` other than `owner`/`owner-gev` | refused | role/agent comparison | re-signed |
| A9 | Tamper any signed field after signing | refused | signature | one case per field |
| A10 | Attestation that is valid JSON with duplicate keys, a non-object, a huge document | refused before verify, bounded | the op's own parser | size cap stated and tested |

### 5.2 Time and replay

| # | Attack | Claimed outcome | Enforced in | Test |
| --- | --- | --- | --- | --- |
| B1 | Replay the identical request | second is refused: `command_id` already recorded | 4.3 step 3 | two sends, one process |
| B2 | Replay from a second process concurrently | exactly one executes | `_mutation_guard` + exclusive-create | two real processes, repeated |
| B3 | Send after the attestation expired | refused on the engine's wall clock | `_prove_actor` | expiry in the past by one second |
| B4 | Pass a `now_epoch` in the past to revive it | no effect: credential time is not the caller's | wall clock in both proof functions | caller time decades back |
| B5 | `expires_at_epoch` as `true`, a float, a string, absent | refused | the `isinstance` checks | one case each |
| B6 | Command whose `expected_task_state` is stale | refused | policy check under the guard | state changed between mint and send |
| B7 | Validate, then change the task, then execute | cannot happen: one guard | 4.3 step 1 | **OPEN — needs a test that can actually interleave** |
| B8 | Crash between appending the transition and replying | the task is cancelled; a retry of the same `command_id` is refused as a replay, and the caller learns the outcome from the mirror | records are the only store | kill the process at each write |
| B9 | Machine clock set back after minting | attestation lives longer than intended | **nothing** | **OPEN — section 6.4** |

### 5.3 The desktop

| # | Attack | Claimed outcome | Enforced in | Test |
| --- | --- | --- | --- | --- |
| C1 | Compromised renderer invokes the command directly | native dialog appears; no yes, no signature | the host handler | handler test with the dialog seam returning no |
| C2 | Renderer supplies its own `command_id`, timestamps or `requested_by` | ignored: not parameters of the command | the command's signature | the frame built from a hostile payload |
| C3 | Renderer supplies a `task_id` or `reason` crafted to mislead the dialog (newlines, bidi controls, a very long string) | dialog shows it escaped and bounded, or the host refuses it | the host | one case per shape |
| C4 | Renderer asks for a command other than `cancel` | refused by the host, and again by the engine | both | both layers |
| C5 | The attestation is left on disk and reused | it is not written to disk on this path | 4.6 | the trust directory is unchanged after a send |
| C6 | Another local account reads the `control-room` key | cannot: `0600` | install-time permissions | **exists**, in the provisioning tests |
| C7 | The command is granted to the window but the dialog is bypassed by a second code path | there is one caller of the signer | a source test over the host crate | grep-shaped test, as `check_capabilities` does |

### 5.4 The store

| # | Attack | Claimed outcome | Enforced in | Test |
| --- | --- | --- | --- | --- |
| D1 | `task_id` of `..`, `.`, an absolute path, a NUL byte, a Windows device name | refused | `ID_RE` in the API; `_task_dir` in the runtime | **OPEN — `_task_dir` refuses only `/` and `\`; `..` is not refused there** |
| D2 | Command against a task that does not exist | refused, nothing created | `_snapshot` | state directory unchanged |
| D3 | Command against a terminal task | refused | `cancel_task`, and the policy | each terminal state |
| D4 | Steal the lock from a live holder | not possible while the holder's mtime is fresh | `_break_stale_lock` | **OPEN — a long validation under the guard could outlive `STALE_LOCK_SECONDS`** |
| D5 | State directory read-only, full, or a symlink | refused cleanly, nothing half-written | the append path | each condition |
| D6 | Write a forged record directly into `records/` | **accepted** by `_records` if the chain is recomputed | **nothing** | **OPEN — section 6.1** |
| D7 | Scope strings that mean a forbidden thing without containing a forbidden token (`deployments`, `gitops`, `prod`, mixed case, Unicode look-alikes) | **passes** the scope check | `FORBIDDEN_SCOPE` is a token match | **OPEN — section 6.3** |

### 5.5 The transport and the environment

| # | Attack | Claimed outcome | Enforced in | Test |
| --- | --- | --- | --- | --- |
| E1 | An extra or missing key in the frame | refused | exact key-set check | one case each |
| E2 | The frame sent to the `governance.read` op, or a read frame sent here | refused by protocol and op | op dispatch | both directions |
| E3 | `BROPS_GOVERNANCE_REGISTRY_ROOT` pointed at an attacker's registry | the engine trusts the attacker's keys | **nothing** | **OPEN — section 6.2** |
| E4 | `BROPS_GOVERNED_SIDECAR` pointed at an attacker's script | the desktop talks to the attacker | **nothing** | **OPEN — section 6.2** |
| E5 | Registry set but unloadable | refusal, never an unkeyed downgrade | the sidecar, exists today for reads | reuse for this op |
| E6 | No registry at all | refused: the runtime holds no keys | both proof functions | exists for validate; add for execute |

## 6. Where the Builder thinks this is weakest

Stated plainly, because a design that hides its weak side is audited on its strong one.

### 6.1 One account holds everything, so the signature attributes and does not protect

On the machine as installed today the desktop account owns the signing key, would own the state
directory, and sets the variable that tells the engine which registry to trust. An attacker who is
that account does not need to forge a command: it can write `records/` directly (D6), or sign a
genuine one. `mint_control_room_command`'s own comment concedes the second half — *"an account that
can drive the control room can already issue the command by other means"*.

What the signature buys in that deployment is **attribution and intent**: a record that says which
key, which session and which document authorised a transition, and a native dialog between a
compromised renderer and that key. It is not a boundary against the account itself. The design
should say this on screen and in the record, with a word of its own, rather than letting a signed
transition read as a protected one. `demonstration_custody` is the precedent.

A real boundary needs the engine to be a **different principal**: the state directory owned by a
service account, the desktop able to reach it only through a socket that authenticates the peer,
and an anchor over the record chain that the writer cannot rewrite. The seven service accounts and
the peer-authenticated sockets exist for the governed turn. Whether the control room belongs
behind them is decision D2.

### 6.2 The engine is told what to trust by the environment

E3 and E4 are not defects of this design; they are how the mirror already works. They become more
serious when the same variables decide who may cancel a task. In the single-account deployment
they add nothing an attacker does not already have (6.1). In the separated deployment they must
not be environment variables of the desktop's launcher at all.

### 6.3 The scope check is a word list

`FORBIDDEN_SCOPE` refuses a scope whose tokens include `credential`, `deploy`, `git`, `production`,
`release`, `repository`, `brops`. It is a deny-list over free text and it is trivially stepped
around (D7). For `cancel` the scope has no effect on what happens, so this slice does not depend
on it — but the check will look like a control to the next person who adds a command that does.
Recommendation inside this design: the host sends a fixed scope for `cancel`, the engine requires
exactly that value, and the free-text deny-list is not relied on for anything.

### 6.4 Time

Expiry is the engine's wall clock. A machine whose clock can be set back extends every attestation
(B9). Single-use and state-binding still hold, so for `cancel` the damage is nil; for a command
that could be meaningfully replayed later it would not be. No monotonic or signed time source is
proposed here.

### 6.5 The mutation guard and long validation

Validation under the guard includes two `verify_artifact` calls and a full integrity scan. If that
can ever exceed `STALE_LOCK_SECONDS`, a second process may steal the lock mid-command (D4). The
Builder has not measured either number.

### 6.6 What has not been verified

- That the registry the install mints grants `control-room-command` to the `control-room` key.
  `docs/PHASE_10_PRODUCTION_ITEMS.md` says so; the installed registry file was opened and its key
  list was not found under the field names tried. **Not established.**
- That nothing outside tests writes an orchestration runtime. Three symbols were searched for in
  four directories.
- Anything about Windows.

## 7. Tests the implementation would owe

Beyond one test per row of section 5:

1. **Cross-language, real keys.** Rust mints with `mint_control_room_command`; Python verifies and
   executes. `provision/tests/python_verifier.rs` already does the first half for validation.
2. **End to end in a process tree.** The host spawns the real sidecar against a real state
   directory, cancels a real task, and reads it back through the real mirror.
3. **Every refusal leaves the store byte-identical.** A hash of the state directory before and
   after each negative case.
4. **Mutation.** Each enforcing check deleted once, its test watched red, restored. Five checks in
   `governed_verification.rs` were found on 2026-10-08 with tests that named them and did not
   exercise them; the same shape should be assumed here until shown otherwise.
5. **Observed.** The row appears in an installed application on a real display.

New rows for `docs/design/SECURITY_NEGATIVE_TEST_MATRIX.md`, one per attack, so the matrix gate
holds them.

## 8. Decisions

**D1 — how does a task come to exist for this slice?** The product cannot create one (C4).
Options: (a) an operator command-line tool that calls `create_task`, labelled as what it is; (b)
build conductor-created tasks first, on the `conductor-session` path (`O-3`); (c) let the owner
create tasks from the cockpit.
**Recommendation: (a) for this slice, (b) as the next design.** (a) is honest and small, and it
makes the cancel path testable now. (c) would give the cockpit the one unproven write in the
runtime and should not be done before C4 is closed. The cost of (a) is that the first task a
mirror ever shows is one an operator typed.

**D2 — does the control room go behind a separate principal?** Section 6.1.
**Recommendation: yes, and say so before building, but do not block this slice on it.** Build the
slice in the single-account shape with the attribution-only label, and open the separated
deployment as its own design. Building the separation first is the stronger order and delays any
observable result by a design, an audit and a deployment; the label keeps the weaker order honest.
If the audit judges that a signed-but-unprotected transition is too easily misread, reverse this.

**D3 — which authority proves an owner (C2)?** `operator-root` per the runtime's text, or the
delegated `control-room` per the API and the signer.
**Recommendation: `control-room`.** Owner decision #78 says no person holds a root, a per-command
artifact is a routine act, and the signer and the verifier already agree. The runtime's text is
the stale one.

**D4 — what tier is the desktop command?** **Recommendation: A, with the native confirmation.**
Not X: it starts nothing. Not R: it changes engine state.

**D5 — how long does an attestation live?** **Recommendation: 60 seconds.** Long enough for a
spawn and a verify, short enough that a leaked one is stale before it is useful. Not measured;
the implementation should measure the real round trip and set it from that.

**D6 — is C5 fixed here or separately?** **Recommendation: here, first, as its own commit.** The
mirror is the instrument this slice is observed through.

## 9. What was run to write this

- The installed application, driven on the machine's display, at three stages (section 1).
- The real sidecar, as an ordinary user, over an empty directory:
  `{"protocol":"brops.governance-read.v1","op":"governance.read","read_only":true,"surface":…,"task_id":null}`
  for each of the four surfaces. Three answered `ok: true, record_count: 0`; `evidenceChain`
  answered *"this runtime is not bound to an evidence store"*. The directory gained `tasks/`.
- `grep` for `DurableOrchestrationRuntime`, `ControlRoomAPIV1(`, `.create_task(` and
  `mint_control_room_command` over the paths named in section 2.
- `engine/orchestration/registry.json` read for the command policy.

No engine code was changed, and nothing was written to any engine state other than the empty
directory above.
