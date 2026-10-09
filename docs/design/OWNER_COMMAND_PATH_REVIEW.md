# Independent review — owner-command path proposal

**Date:** 2026-10-09  
**Proposal reviewed:** `origin/design/owner-command:docs/design/OWNER_COMMAND_PATH_DESIGN.md`  
**Code base checked:** `e3fc507fc325506cd62333487ee25fe6a28fed54`  
**Overall verdict:** **REJECT before implementation**

This is a design review, not an implementation review. No owner-command code described by the
proposal exists at the audited head. I changed no product code, did not commit, and did not push.

The proposal correctly discovers that the two existing halves of the owner path do not meet. It
does not yet provide a safe way to join them. The most important break is simpler than the eight
OPEN rows: the proposed native dialog confirms `reason`, while the retained key signs only
`command_id`, `task_id`, `command` and its own identity/time fields. `reason`, `scope`,
`evidence_refs`, `expected_task_state`, and the command document's timestamps are mutable after the
human says yes. The engine would faithfully execute a different command document from the one the
human saw, and the transition would retain only the attestation digest, not the confirmed document.

The second release blocker is the one the proposal itself names in section 6.1. In the proposed
deployment, the desktop account owns the signing key and orchestration state and selects both the
verifier and trusted-key registry. A label saying “attribution only” does not turn that into a
security boundary. Decisions D1 and D2 would institutionalise the unproven write and the
single-principal deployment before their designs exist.

## Section verdicts

| Section | Verdict | Required change |
| --- | --- | --- |
| 0 — audit request | **ACCEPT** | The requested adversarial review and deliverables are well-defined. |
| 1 — motivation | **CHANGE** | Keep the code-derived “no shipped writer” conclusion, but label the three installed-machine observations as external evidence that cannot be verified from this repository. |
| 2 — current tree | **CHANGE** | C1–C5 are confirmed. Correct the task-ID claim, distinguish source-guaranteed permissions from installed observations, and replace search-based absence claims with a generated call/inclusion inventory. |
| 3 — scope | **REJECT** | Principal separation, trusted executable/config custody, authenticated task creation, and Windows path semantics are prerequisites, not follow-up scope. Excluding them invalidates the claimed boundary. |
| 4 — design | **REJECT** | Sign the exact canonical command document the human confirms; use an engine-owned clock; define authenticated replies and filesystem/custody invariants; remove the stale-lock split-brain window. |
| 5 — attack list | **REJECT** | Several claimed outcomes are false or weaker than stated, and multiple proposed tests can pass vacuously. The row-by-row ruling and missing attacks follow. |
| 6 — weakest points | **CHANGE** | Section 6.1 is the correct diagnosis, but its consequence must be “do not build this security claim yet,” not “label and proceed.” E3/E4 and D6 become release blockers once writes exist. |
| 7 — tests | **CHANGE** | Add deterministic concurrency/crash hooks, raw-byte parser tests, authenticated reply tests, permission/peer tests, and mutation of the complete signed document. A directory hash alone is not a crash-consistency proof. |
| 8 — decisions | **CHANGE** | Overrule D1 and D2; conditionally accept D3/D4/D6; replace the unmeasured D5 constant with a measured, engine-enforced lifetime. |
| 9 — provenance | **CHANGE** | Repository searches were repeatable. Installed display/filesystem observations cannot be verified from the repository and must be accompanied by captured evidence or rerun instructions. |

## Section 2 — every current-tree claim checked

### 2.1 Store

| Claim | Ruling |
| --- | --- |
| One directory per task with `contract.json` and sequenced records | **Confirmed** in `DurableOrchestrationRuntime`, `_task_dir`, `_contract`, `_records`, and `_append`. |
| `previous_record_sha256` / `record_sha256` form an unkeyed chain | **Confirmed.** `_hash_record` is plain SHA-256. A writer can rewrite the complete chain. |
| Appends use exclusive create under mutation/claim locks | **Confirmed, with a material qualification:** `O_EXCL` prevents one filename collision, but the lock may be stolen after 30 seconds while the original holder is alive. |
| `_task_dir` refuses only slash and backslash | **Confirmed.** It also refuses non-string/empty values, but accepts `.`/`..` and Windows device names. API `ID_RE` happens to reject dot-leading IDs; runtime defence is not equivalent. |

### 2.2 Writers and actor proof

| Claim | Ruling |
| --- | --- |
| `create_task` takes no actor proof and records conductor identity | **Confirmed.** Whoever reaches the method gets a conductor-attributed `draft`/`queued` write. |
| No non-test caller was found in the named four directories | **Confirmed for that search, not proof of absence.** A repository-wide Python call graph/import inventory is the settling check. |
| `_prove_actor` proves only the conductor; owner/system/agent refuse | **Confirmed.** The owner mutations therefore refuse today. |
| `retry_blocked`, owner `cancel_task`, and `recover_task` refuse | **Confirmed** for the current owner path. |

### 2.3 Control-room API

| Claim | Ruling |
| --- | --- |
| The API has reads plus one command-validation entry | **Confirmed.** `validate_command_intent` is non-mutating by contract. |
| It proves a per-command owner and returns `executed: false`, `mutation_authorized: false` | **Confirmed.** `_prove_command_actor` binds only `command_id`, `task_id`, and `command` from the command document, plus role/agent separately. |
| No API method executes a validated command | **Confirmed** at this head. |
| Only the sidecar mirror constructs `ControlRoomAPIV1` outside tests | **Confirmed for the repository search performed.** Dynamic imports cannot be disproved by grep alone. |

### 2.4 Signer

| Claim | Ruling |
| --- | --- |
| Rust mints a `control-room-command`, future-bounds it, and has only test callers | **Confirmed.** The payload does **not** sign the complete 12-field command document. |
| Installed key is mode `0600` and desktop-owned | **Cannot be verified from the repository.** The source requests owner-only file mode; actual ownership, ancestor permissions, ACLs and install result require `namei -l`, `stat`, and ACL inspection on a clean installed machine. |

### 2.5 Transport

| Claim | Ruling |
| --- | --- |
| `_OPS` exposes only `governance.read` and `approval.request`; unknown ops refuse | **Confirmed.** There is no command operation. |
| The desktop spawns the Python/sidecar paths selected by environment | **Confirmed.** This is also an executable-selection vulnerability once the path can mutate state. |
| The installed package ships neither `engine/` nor `bridge/` | **Confirmed for the package configuration/resources in this tree; installed bytes cannot be verified from the repository.** Install the artifact and enumerate its manifest to settle the latter. |
| Registry root comes from `BROPS_GOVERNANCE_REGISTRY_ROOT` | **Confirmed.** The same desktop-controlled environment chooses whom the engine trusts. |

### 2.6 The five contradictions

| ID | Verdict | Evidence and consequence |
| --- | --- | --- |
| C1 | **CONFIRMED** | API proves owner but does not execute; runtime executes but rejects owner. There is no joining call path. |
| C2 | **CONFIRMED** | Runtime refusal text requires operator-root while API, signature registry and Rust provisioner use delegated `control-room`. The current provisioner grants `control-room-command` to that retained authority; the runtime text/model is stale. |
| C3 | **CONFIRMED** | Registry and runtime command sets/states disagree exactly as stated. “retry” is not a sound alias for `retry_blocked`. |
| C4 | **CONFIRMED** | `create_task` is the actorless write and then attributes the write to the conductor. |
| C5 | **CONFIRMED from code** | Runtime construction unconditionally creates `tasks/`. The claimed installed observation is not needed to prove it, and itself cannot be verified here. |

One additional current-tree contradiction matters to the proposal: `ControlRoomAPIV1._now(now_epoch)`
accepts caller time for policy/command expiry, while `_prove_command_actor` separately uses wall time.
The design says the engine owns time, but the existing command-document validation does not.

## Section 5 — all 39 attack rows

Legend: **HOLDS** means the proposed claim is sound if implemented exactly with a non-vacuous test;
**CHANGE** means the direction is sound but enforcement/test is incomplete; **FALSE** means the
claimed outcome does not follow from the design.

### 5.1 Signature

| Row | Ruling | Enforcement and whether the test can fail |
| --- | --- | --- |
| A1 | **HOLDS** | Both proof layers must independently reject a missing document. Delete each check separately; one test per layer can fail. |
| A2 | **HOLDS** | `verify_artifact` at both boundaries is correct. Use a valid signature from an unregistered key, not malformed bytes. |
| A3 | **CHANGE** | Correct authority boundary, but “one per retained authority” will go stale. Generate cases from the registry and prove every non-`control-room` authority refuses. |
| A4 | **HOLDS** | Artifact-type selection is the right point. Mutate each layer independently. |
| A5 | **HOLDS, too narrow** | `command_id` comparison works; it does not cure the unsigned fields omitted by A5–A7. |
| A6 | **HOLDS, too narrow** | Same for `task_id`. |
| A7 | **HOLDS, too narrow** | Same for `command`. |
| A8 | **HOLDS** | Role/agent comparisons are correct; re-sign both variants. |
| A9 | **FALSE as stated** | Only fields in the attestation payload are protected. Mutating `reason`, `scope`, `evidence_refs`, `expected_task_state`, or command-document times after confirmation is accepted. The test must enumerate every field of one canonical signed command, not merely every field of the smaller artifact. |
| A10 | **FALSE today / CHANGE** | Sidecar input uses ordinary `json.loads`, which accepts duplicate keys; a local experiment retained the last value. Enforce duplicate rejection and a byte cap in the raw stdin parser before dispatch. Object validation after parsing is too late. |

### 5.2 Time and replay

| Row | Ruling | Enforcement and whether the test can fail |
| --- | --- | --- |
| B1 | **CHANGE** | Per-task record lookup prevents same-task replay only. Define whether `command_id` is globally unique; otherwise the same ID can be used on another task and audit correlation is ambiguous. |
| B2 | **FALSE** | A live holder can exceed `STALE_LOCK_SECONDS`; another process may unlink/replace its lock while it continues. Exclusive record creation does not provide exactly-once across different next sequence choices. Test with a deterministic barrier beyond 30 seconds. |
| B3 | **HOLDS** | Runtime wall-clock verification of the signed artifact is the right layer. Test equal-to-now as well as one second past. |
| B4 | **FALSE/underspecified** | The credential uses wall time, but command policy currently trusts caller `now_epoch`. The new entry point must take no caller clock and derive one instant internally for every time check. |
| B5 | **CHANGE** | `isinstance(True, int)` is true in Python. Current policy may still refuse `true` because it is numerically stale, so the proposed test can pass vacuously. Assert a specific type error and use `type(value) is int` or an explicit bool rejection. |
| B6 | **HOLDS** | State comparison under one valid guard is the right point. Test that no record/lock residue remains. |
| B7 | **CHANGE** | The claim requires injectable barriers around snapshot/validation/append; sleeps cannot prove non-interleaving. It also depends on fixing B2 first. |
| B8 | **CHANGE** | “Kill at each write” is not defined enough. Name exact cut points: temp/write, file fsync, rename/exclusive publication, directory fsync, state visible, reply serialization/write. Test restart and authenticated outcome discovery at every point. |
| B9 | **ACCEPTED RISK only for one terminal cancel** | Rollback extends credential life. Record it as a bounded assumption, but do not generalise this replay model to any non-terminal command. |

### 5.3 Desktop

| Row | Ruling | Enforcement and whether the test can fail |
| --- | --- | --- |
| C1 | **HOLDS** | A host-owned native-confirmation seam can prove no signature on decline/dismiss/error. Include direct IPC invocation. |
| C2 | **CHANGE** | A typed Rust signature excludes host-owned fields, but hostile raw IPC must be tested for exact parameter rejection, not silently ignored extras. |
| C3 | **CHANGE** | This is required and current native-dialog code does not provide it. Reject C0/C1 and bidi controls, bound by rendered units, and test the actual OS backends for clipping/wrapping/accessibility. |
| C4 | **HOLDS** | Independent host and engine allowlists are correct; mutation-test both. |
| C5 | **CHANGE** | An unchanged trust directory does not prove no artifact was written elsewhere. Instrument the signer/filesystem and assert the signed document exists only in memory and the outbound frame. |
| C6 | **FALSE as a complete claim** | `0600` on the key file is insufficient without owner, directory ancestry, ACL, symlink and real-UID checks. Installed permissions cannot be verified from this repository. Test as a second real local account. |
| C7 | **CHANGE** | A grep test is rename/indirection-sensitive and can miss FFI or helper paths. Maintain a signer call inventory plus a runtime signer seam that asserts native confirmation issued the exact digest. |

### 5.4 Store

| Row | Ruling | Enforcement and whether the test can fail |
| --- | --- | --- |
| D1 | **FALSE** | API `ID_RE` rejects `.`, `..`, absolute paths and NUL but accepts names such as `CON`; runtime checks only slash/backslash/empty. Define a cross-platform canonical ID grammar and enforce it in both layers. |
| D2 | **HOLDS if C5 is fixed** | `_snapshot` should not create. Test against a byte-identical non-existent task under a read-only state root. |
| D3 | **CHANGE** | Enumerate terminal states from the registry, not a hand list, and reconcile the registry/runtime state mismatch before testing. |
| D4 | **FALSE beyond 30 seconds** | The proposal states only “while fresh,” but uses that lock to claim atomic exactly-once execution. Replace stale-by-mtime theft with an OS-held lock/lease with owner liveness and fencing. |
| D5 | **CHANGE** | Include symlinked descendants, ancestor replacement, Windows reparse points, permission loss and disk-full at each durability cut point. “Nothing half-written” requires directory fsync/restart assertions. |
| D6 | **CONFIRMED FATAL** | A same-account writer can forge the full unkeyed chain. This cannot remain OPEN if the UI presents the record as protected. Separate custody and externally anchor the chain before release. |
| D7 | **FALSE, correctly admitted** | Replace the free-text denylist with one fixed canonical cancel scope and exact equality. Delete the denylist from the security argument. |

### 5.5 Transport and environment

| Row | Ruling | Enforcement and whether the test can fail |
| --- | --- | --- |
| E1 | **HOLDS** | Exact key-set checks at the raw operation boundary are correct; combine with A10's byte/parser limits. |
| E2 | **HOLDS** | Protocol and op must both match; mutate them independently so a shared always-refuse setup cannot make both tests green. |
| E3 | **CONFIRMED FATAL** | Desktop-selected registry means the requester selects who proves it. Pin registry/config under a principal the desktop cannot write, then test hostile environment override. |
| E4 | **CONFIRMED FATAL** | Desktop-selected sidecar means a hostile script can claim success, steal signed commands, or return forged records. Pin/measure the executable and authenticate the engine reply/peer. |
| E5 | **HOLDS** | Reuse the unloadable-registry refusal but assert no fallback verifier and no state change. |
| E6 | **HOLDS** | Both proof functions must refuse absent keys; independently mutate both checks. |

## Missing attacks

The proposal needs at least these additional rows:

1. **Mutate what the human confirmed after “yes”.** Change each unsigned command field while
   retaining the valid three-field attestation. Expected result: refusal because the signature must
   cover the canonical complete command document.
2. **Backdate the command policy clock.** Supply a caller-controlled old `now_epoch` while the signed
   credential remains otherwise valid. Expected result: there must be no caller time parameter.
3. **Reuse one `command_id` on another task.** Decide and enforce global or explicitly task-local
   uniqueness; do not leave audit identity ambiguous.
4. **Swap a path component.** Replace `tasks`, a task directory, `records`, or the lock with a
   symlink/reparse point, including between validation and open.
5. **Cross-account state access.** A second local account attempts to read/write the key, registry,
   socket and state through file permissions and ACLs.
6. **Lose or forge the reply.** Drop the connection after commit; then have a fake sidecar return an
   `executed: true` record. The desktop must learn truth only from an authenticated engine/mirror.
7. **Dialog semantic mismatch.** Test truncation, normalization, bidi, control characters, very long
   grapheme clusters, and screen-reader order on every supported native backend. The bytes signed must
   have a deterministic displayed representation.
8. **Replace the verifier under the same account.** Swap Python, sidecar, registry, state, or inherited
   environment between confirmation and spawn. Pin descriptors/digests and authenticate the peer.
9. **Crash at every persistence edge.** Inject failure before/after write, fsync, publish, directory
   fsync and reply. Restart and prove either no transition or one complete durable transition.
10. **Mutate state outside the guard.** Exercise every runtime write entry point concurrently and prove
    all of them share the same fencing domain.
11. **Native-dialog re-entrancy and request mix-up.** Open two confirmations concurrently and ensure a
    “yes” can authorize only the digest shown in that exact dialog.
12. **Output/resource exhaustion.** Bound request, attestation, reply, error, record count and integrity
    scan time before taking the global mutation guard.

## Section 6 — security consequence

Section 6.1 is the strongest part of the proposal and the reason to stop. With one account controlling
the key, state, executable and registry, the signature supplies an attribution format, not an integrity
boundary. Even the attribution is forgeable after the fact because that account can rewrite the
unkeyed record chain. A UI label is useful disclosure but is not a compensating control.

Required architecture before implementation:

- run the mutating engine as a separate OS principal;
- give that principal exclusive state custody and a pinned root/config it—not the desktop—selects;
- authenticate the desktop peer and authenticate replies;
- fence all state writers with an OS-held lock or monotonic fencing token;
- anchor records outside the writer's rewrite authority; and
- package/pin the engine rather than spawning an environment-selected checkout script.

Section 6.2's E3/E4 are therefore defects of the proposed mutating design even if they pre-exist in a
read-only mirror. Section 6.3's exact fixed scope is accepted. Section 6.4 is an explicit residual risk
only for terminal cancel. Section 6.5 requires measurement but cannot be solved by choosing a larger
mtime threshold. Section 6.6's generated registry claim is confirmed in source: `ARTIFACT_AUTHORITY`
and the current Rust provisioner grant `control-room-command` to `control-room`; the actual installed
registry **cannot be verified from the repository**. Mint into a temporary provision root and run the
Python verifier, then separately inspect the installed registry, to settle both facts.

## Section 8 — decisions overruled or conditioned

| Decision | Ruling |
| --- | --- |
| D1 — operator CLI creates a task | **OVERRULE.** Do not turn the actorless `create_task` seam into a product tool. For tests, use a fixture explicitly outside product packaging. For product operation, design conductor-authenticated creation first. |
| D2 — separate principal, but do not block | **OVERRULE.** Separate custody, pinned verifier/config and authenticated transport are prerequisites. Otherwise the new path must not claim security, integrity or non-repudiation and should not be shipped. |
| D3 — delegated `control-room` authority | **ACCEPT conditionally.** It is the existing registry/provisioner model and avoids an online root. Accept only after the exact complete command is signed and the key is isolated from renderer and state custody. |
| D4 — tier A | **ACCEPT conditionally.** A native confirmation is appropriate for a state-changing stop action, provided the exact canonical signed bytes have an unambiguous display and concurrency binding. |
| D5 — 60 seconds | **CHANGE.** Sixty seconds is unsupported. Measure p99 launch/verify/interaction time on each release OS, choose the smallest justified cap, and have the engine derive all time from one owned instant. |
| D6 — fix read-before-write | **ACCEPT.** Make runtime reads side-effect free first and prove all four surfaces against a read-only existing directory and an absent directory. |

## Everything broken

1. Native confirmation and signature cover different documents.
2. The transition retains an attestation digest but cannot reconstruct/prove the full human-confirmed
   intent.
3. The desktop account controls key, state, verifier and registry; no integrity boundary exists.
4. `create_task` would be productised without authentication under D1.
5. The stale-mtime lock permits two live mutation holders and invalidates exactly-once claims.
6. Command-policy time remains caller-controlled unless the new entry point removes that parameter.
7. Duplicate JSON keys are accepted by the current parser; A10 is not designed at the raw boundary.
8. Boolean integers can make B5 pass for the wrong reason.
9. Replay identity is only per task and global collision semantics are unspecified.
10. Runtime and API task-ID validation disagree and do not define Windows device-name behaviour.
11. `0600` alone does not establish key custody.
12. Environment-selected registry and sidecar become authority/execution substitution attacks.
13. The record chain is rewriteable by its writer.
14. Crash durability, directory fsync and lost-reply recovery have no precise state machine/test
    points.
15. Native dialog escaping, clipping, normalization, accessibility and concurrent-dialog binding are
    unspecified.
16. The proposed signer-call grep and trust-directory comparison can pass while alternate paths or
    writes remain.
17. The scope denylist is not a security control.
18. Windows was excluded even though identifiers, filesystem semantics and the desktop command are
    cross-platform concerns.

## What cannot be verified from the repository

The installed machine's actual key owner/mode/ACLs, generated registry contents, package contents,
displayed mirror rows, native-dialog rendering, service account layout, and real CI/PR discussion
**cannot be verified from the repository**. Settle them with, respectively: `namei`/`stat`/ACL checks
as a second account; a fresh temporary provisioning plus Python verification and installed-file
inspection; artifact manifest extraction; captured sidecar/display transcripts; real-backend dialog
tests on all release OSes; process/socket/peer-credential inspection; and pinned CI/PR logs.

## Final verdict

**REJECT.** Preserve the useful inventory and the C1–C5 diagnosis, then redesign around separate
custody and one canonical fully signed command. Only after that should the 39 corrected attacks plus
the 12 missing attacks become mutation-tested acceptance criteria.
