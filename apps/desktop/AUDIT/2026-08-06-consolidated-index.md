# menqstudio/OS — consolidated audit index

**Target:** `main` @ `219c76312e0a5204c4e9a4f1b012581742e93191`
**Date:** 2026-08-06
**Verdict:** **RED** — do not flip `platform_governed_execution_supported()`.

Three independent adversarial rounds, each cut a different way so that a defect invisible to one
decomposition would be visible to another. Every finding below survived an adversarial reviewer
instructed to destroy it, and rounds 2 and 3 additionally discarded anything that restated an
earlier finding.

| Round | Decomposition | Agents | New findings |
|---|---|---|---|
| 1 | by remediation blocker | 20 | 45 |
| 2 | by attack technique | 20 | 49 |
| 3 | by adversary, protocol, schema, spec, refusal path, coverage gaps | 20 | 28 |
| | | **60** | **122** |

Yield declined 45 -> 49 -> 28. Duplicates across rounds: **0**.

| Severity | Count |
|---|---|
| P0 | 1 |
| P1 | 7 |
| P2 | 32 |
| P3 | 82 |

## Full detail lives in

- `OS_REMEDIATION_AUDIT_2026-08-06.md` — round 1, plus the auditor's own test-execution evidence
- `OS_REMEDIATION_AUDIT_ROUND2_2026-08-06.md` — round 2
- `OS_REMEDIATION_AUDIT_ROUND3_2026-08-06.md` — round 3

Each finding there carries a walkthrough, the adversarial verdict, and an implementer gate that must
be filled in before any code is changed.

---

## All findings, ranked

| Sev | Round | Title | Location |
|---|---|---|---|
| P0 | R1 | The sign-oracle is narrowed, not removed: `complete-run` still takes the reply digest raw off the wire, and th | `engine/runtime/governed_supervisor.py:848` |
| P1 | R1 | The Windows kit still reports the four evidence values as deployment constants — F-02/F-18 is unfixed verbatim | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| P1 | R1 | The store-input pin is a snapshot of an unpinned inode: the broker can hand the launcher a file it can rewrite | `apps/desktop/src-tauri/launcher/src/main.rs:520` |
| P1 | R1 | The attested request digests are still whatever the broker says: no runtime component ever compares the root-o | `engine/ci/live/run_live_turn.sh:122` |
| P1 | R1 | ADJACENT (likely another agent's blocker, F-02/F-08 family): output_handle is chosen by the broker, so a compr | `apps/desktop/src-tauri/broker/src/chain_executor.rs:817` |
| P1 | R1 | The durable evidence head-floor is cleared by deleting its directory and relocated by an ungated environment v | `engine/runtime/bro_completion.py:255` |
| P1 | R2 | Windows: both signing privates are written plaintext by the provisioner and sealed only trust-on-first-use, so | `apps/desktop/src-tauri/win-live/src/bin/win_provision.rs:26` |
| P1 | R3 | §7 deep verification does not exist in the isolated signer: the entire protected-chain check is three existenc | `engine/runtime/isolated_signer.py:647` |
| P2 | R1 | The evidence-head anti-rollback floor is keyed on `(install_id, task_id)` and the broker chooses `task_id`, so | `engine/runtime/governed_supervisor_ledger.py:645` |
| P2 | R1 | The 'hash-linked' evidence chain is never verified and never published — no code anywhere reads the events arr | `apps/desktop/src-tauri/broker/src/chain_executor.rs:544` |
| P2 | R1 | The four evidence values reach the signer only as the broker's self-report; the supervisor cannot read the rec | `engine/runtime/governed_supervisor_ledger.py:553` |
| P2 | R1 | The evidence-head anti-rollback/anti-fork floor is keyed on, and compares, values the broker chooses — it runs | `engine/runtime/governed_supervisor_ledger.py:640` |
| P2 | R1 | The §2.5 content pin is self-referential: the manifest is generated from the very bytes it measures, seconds e | `engine/ci/live/run_live_turn.sh:210` |
| P2 | R1 | The coverage floor is satisfied by logical NAME, not by causal role: 21 roles resolve to 14 files, one pinned  | `engine/ci/live/build_tcb_pin_manifest.py:84` |
| P2 | R1 | The head-floor mark is advanced by the very process it polices, so the ledger's own escape route ('put the mar | `engine/runtime/bro_completion.py:269` |
| P2 | R1 | BRO_OPERATOR_ROOT_PIN_SELF_OWNED is an ungated ambient env var that restores the pre-fix F-06 behaviour for ex | `engine/runtime/bro_signature.py:263` |
| P2 | R1 | The acknowledged self-owned trust anchor is reported to nobody: the deployment-posture preflight prints 'GREEN | `engine/runtime/bro_signature.py:35` |
| P2 | R1 | Windows: the receipt's evidence-chain head and containment evidence are still unmeasured caller values — F-02' | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| P2 | R1 | Windows: the pinned executor image digest is decorative — it is signed into the lease and never compared to th | `apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:162` |
| P2 | R1 | Windows: the §2.5 TCB integrity floor is Linux-only and win_provision sets no ACL — the control the code itsel | `apps/desktop/src-tauri/win-live/src/tcb.rs:60` |
| P2 | R1 | The Windows audit verdict document asserts two facts that the code at this commit contradicts | `apps/desktop/src-tauri/win-live/proof/WINDOWS_BROKER_AUDIT_VERDICT.md:10` |
| P2 | R2 | §7.1 step 4 "Request binding" is a self-comparison of one deployment constant, and on the Windows leg the exec | `apps/desktop/src-tauri/core/src/governed_verification.rs:320` |
| P2 | R2 | Every test the ledger cites to close F-08 and F-10 lives in a crate no CI job ever runs `cargo test` on — 52 ` | `.github/workflows/ci.yml:49` |
| P2 | R2 | F-08's four cited tests exercise a string parser and a getter; the digest-and-compare that IS F-08 has zero te | `apps/desktop/src-tauri/launcher/src/main.rs:444` |
| P2 | R2 | The CI isolation job's `4_supervisor_oracle` denial is decided by a protocol-name mismatch, so the shape guard | `engine/tools/brops_isolation_prover.py:84` |
| P2 | R2 | The only trust badge the shipped app can display is licensed by a receipt over a synthetic constant request, a | `apps/desktop/src-tauri/src/commands.rs:2033` |
| P2 | R2 | §7.1(d) global-unique receipt_id is enforced by nothing on the Windows path: the supervisor mints a predictabl | `apps/desktop/src-tauri/win-live/src/servers.rs:576` |
| P2 | R2 | Windows: the executor has already exited before execution-started is sent, and the pid reported is the driver' | `apps/desktop/src-tauri/win-live/src/execution.rs:115` |
| P2 | R2 | The NULL DACL grants every local account FILE_CREATE_PIPE_INSTANCE, so FILE_FLAG_FIRST_PIPE_INSTANCE (the ship | `apps/desktop/src-tauri/win-live/src/pipe.rs:56` |
| P2 | R2 | Every server-side trust anchor on Windows — the peer-SID allowlist, the signer's attestation verification key, | `apps/desktop/src-tauri/win-live/src/bin/win_signer.rs:33` |
| P2 | R2 | The challenge-authority key is outside the root-signed manifest, and the root-provenance the chain records (an | `engine/ci/live/provision_keys.py:383` |
| P2 | R2 | No CI job ever compiles the shipped host crate on Windows, so the only code that can emit trusted_verified / a | `.github/workflows/ci.yml:100` |
| P2 | R2 | The Windows live machine-proof harness cannot run at this commit: it feeds win_provision the DEMONSTRATION roo | `apps/desktop/src-tauri/win-live/proof/win_live_proof.ps1:30` |
| P2 | R3 | Message bodies are concatenated into an unescaped "Name: text" speaker protocol inside each history turn, so a | `apps/desktop/src-tauri/src/commands.rs:1064` |
| P2 | R3 | Coding-agent mode gives model output auto-approved Write/Edit over the repository that contains bridge/engine_ | `apps/desktop/src-tauri/src/ai.rs:1072` |
| P2 | R3 | The Windows proof harness reads all seven brops-* service-account passwords in cleartext from a path its own h | `apps/desktop/src-tauri/win-broker/proof/isolation_proof.ps1:20` |
| P2 | R3 | The Windows provisioner adopts a pre-existing deployment root, so any local account can pre-create the well-kn | `apps/desktop/src-tauri/win-live/src/bin/win_provision.rs:74` |
| P2 | R3 | The isolated signer's front door has no catch-all: a store blob the broker uid can plant makes `SignerError` e | `engine/runtime/isolated_signer_server.py:273` |
| P2 | R3 | One undocumented env var turns every shipped chat command into a Bash-enabled, auto-approving coding agent — w | `apps/desktop/src-tauri/src/ai.rs:1072` |
| P2 | R3 | No upper time bound survives the pre-launch lease gate: §7's lease-window invariants are unimplemented and com | `engine/runtime/governed_supervisor_ledger.py:575` |
| P3 | R1 | The supervisor lease still does not reach the setuid launcher, so one lease does not authorize one privileged  | `apps/desktop/src-tauri/launcher/src/main.rs:424` |
| P3 | R1 | The broker names the recorder's 'private' head-sequence counter directory: the sudoers rule places no restrict | `apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:54` |
| P3 | R1 | A missing execution.evidence_state_dir config key silently relocates the monotonic counter to the recorder's w | `apps/desktop/src-tauri/broker/src/main.rs:376` |
| P3 | R1 | The launcher's second TCB owner is the hardcoded uid 500, so any account that happens to hold uid 500 can auth | `apps/desktop/src-tauri/launcher/src/main.rs:395` |
| P3 | R1 | On the Windows/Rust leg F-09 is entirely unremediated: supervisor_ledger.rs still has zero non-test callers an | `apps/desktop/src-tauri/win-live/src/servers.rs:766` |
| P3 | R1 | The Windows supervisor twin accepts evidence counters the shared invariant forbids (zero-valued, and last_sequ | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| P3 | R1 | The pin manifest — the sole authority for the entire §2.5 decision — is unsigned, unpinned, and gets no owner/ | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25` |
| P3 | R1 | The probe's documented no-re-lookup/no-TOCTOU contract is falsified: owner/mode come from an O_PATH|O_NOFOLLOW | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:74` |
| P3 | R1 | Neither claimed 'production' caller enforces the floor for a served turn: live_turn's verify_tcb exits the pro | `apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35` |
| P3 | R1 | The floor is advanced from a SECOND, independent read of the head file rather than from the head validate_chai | `engine/runtime/bro_completion.py:226` |
| P3 | R1 | The head-floor advance is an unlocked load-compare-write over a shared temp filename, so two concurrent turns  | `engine/runtime/bro_completion.py:271` |
| P3 | R1 | "external" root-anchor provenance is a string the repo-staged kit writes about itself, so a repo-tree writer t | `engine/ci/live/provision_keys.py:245` |
| P3 | R1 | The F-07 remediation dropped the sticky bit while granting group write, so service accounts can now unlink art | `engine/ci/live/run_live_turn.sh:180` |
| P3 | R1 | The live-governed-turn CI job's stated pass condition no longer matches the script: it now exits 0 with produc | `.github/workflows/ci.yml:91` |
| P3 | R1 | RecursionError from a 4090-byte nested-JSON frame still escapes handle_connection AND serve_forever and kills  | `engine/runtime/governed_supervisor_server.py:626` |
| P3 | R1 | The only regression test guarding the F-11 fix never reaches the code it is supposed to guard — it is rejected | `engine/tests/test_governed_supervisor_server.py:310` |
| P3 | R1 | The governed-supervisor front door has NO socket timeout at all and a serial accept loop — the exact F-31 defe | `engine/runtime/governed_supervisor_server.py:183` |
| P3 | R1 | The broker's per-connection deadline bounds one connection but not the service: the accept loop is still seria | `apps/desktop/src-tauri/broker/src/main.rs:185` |
| P3 | R1 | The renderer→broker client's 120s deadline is per-recv, so a drip endpoint can hold a synchronous Tauri comman | `apps/desktop/src-tauri/src/governed_turn.rs:85` |
| P3 | R1 | The F-29 'bound to the verifying key' guard is still a tautology at all three real call sites — both operands  | `apps/desktop/src-tauri/core/src/production_trust.rs:73` |
| P3 | R1 | Windows: the F-27 remediation makes the named-pipe live driver fail closed — completed_at_ms is the driver's s | `apps/desktop/src-tauri/win-live/src/servers.rs:988` |
| P3 | R1 | Windows in-process path (the one reachable from the shipped app) still emits the zero-duration receipt F-27 na | `apps/desktop/src-tauri/win-live/src/proof.rs:232` |
| P3 | R1 | Windows: no evidence-head anti-rollback floor exists at all — the shared DDL's governed_evidence_head_floor ha | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| P3 | R1 | Windows named-pipe servers have no read/write deadline and read the frame BEFORE peer authentication — any unp | `apps/desktop/src-tauri/win-live/src/pipe.rs:149` |
| P3 | R1 | Windows: the pipe is destroyed and re-created between every connection, leaving a squat window, and the client | `apps/desktop/src-tauri/win-live/src/pipe.rs:167` |
| P3 | R1 | The Windows live kit has zero CI coverage — no job builds it, tests it, or runs any of its proofs, and the cro | `.github/workflows/ci.yml:130` |
| P3 | R2 | The §7.1(c)/(d) replay defence has no durable implementation anywhere: every production construction site inje | `apps/desktop/src-tauri/win-live/src/proof.rs:293` |
| P3 | R2 | The containment-evidence and policy-bundle digests are re-derived by the isolated signer and then explicitly d | `apps/desktop/src-tauri/win-live/src/servers.rs:1037` |
| P3 | R2 | The isolated signer's `_check_run_binding` — the "independent authorization gate (§1.5)" — binds nothing: its  | `engine/runtime/isolated_signer.py:599` |
| P3 | R2 | The setuid launcher verifies the compile-time drop-order constant instead of the sequence it actually performs | `apps/desktop/src-tauri/launcher/src/main.rs:447` |
| P3 | R2 | The entire Windows peer-authorization and image-integrity policy layer in core/src/windows_broker.rs is unreac | `apps/desktop/src-tauri/core/src/windows_broker.rs:272` |
| P3 | R2 | A failed model invocation is silently replaced by a hard-coded constant, which the governed chain then really  | `apps/desktop/src-tauri/src/governed_selftest.rs:88` |
| P3 | R2 | The manifest anti-rollback CAS returns the advanced floor "to persist" and both Linux call sites throw it away | `apps/desktop/src-tauri/broker/src/manifest_resolver.rs:151` |
| P3 | R2 | A missing `uids` block in the broker config silently deletes the "never a runtime UID" half of the §2.5 TCB ow | `apps/desktop/src-tauri/broker/src/main.rs:267` |
| P3 | R2 | The two regression tests named for the F-01 sign-oracle assert only that an *unknown attempt id* is refused; t | `engine/tests/test_governed_chain_e2e.py:487` |
| P3 | R2 | The F-07/F-28 custody-mode half of a keystone ledger row has zero tests: all four tests it cites are in `test_ | `engine/ci/live/run_live_turn.sh:180` |
| P3 | R2 | The '3 new tests' closing F-02's evidence-chain half all test a five-field JSON shape validator; the recorder  | `apps/desktop/src-tauri/broker/src/chain_executor.rs:1447` |
| P3 | R2 | The demonstration badge is a bare flag row: every artifact that could substantiate it is destroyed before the  | `apps/desktop/src-tauri/core/src/repo.rs:1116` |
| P3 | R2 | Settings states Governance = "Fail-closed, verified-receipt-mandatory" unconditionally, on a build where no ch | `apps/desktop/src/features/Settings.tsx:361` |
| P3 | R2 | Pressing Demo-verify makes the thread render every message of the current session twice, under colliding React | `apps/desktop/src/features/Conversations.tsx:372` |
| P3 | R2 | The M-1 self-approval guard can never fire on the only production call site, and the test that claims to lock  | `apps/desktop/src-tauri/core/src/repo.rs:660` |
| P3 | R2 | The Windows live driver commits its trusted_verified message into a throwaway in-memory database, so every wri | `apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:203` |
| P3 | R2 | persist_committed and settle are two separate transactions, so a crash in the window between them leaves a dur | `apps/desktop/src-tauri/core/src/broker_orchestrator.rs:127` |
| P3 | R2 | `bound` is a tautology: CommittedMessage::new hardcodes trust_state, so the shipped desktop gate `outcome.boun | `apps/desktop/src-tauri/core/src/governed_turn_ipc.rs:239` |
| P3 | R2 | The claim-lock's reentrancy check is PID equality, so a stale lock file left by a dead process whose PID has b | `engine/runtime/bro_orchestration_runtime.py:380` |
| P3 | R2 | The §7.1(c)/(d) replay defence has no durable implementation anywhere in the tree — InMemoryLedger is the only | `apps/desktop/src-tauri/core/src/governed_verification.rs:209` |
| P3 | R2 | The isolated signer's identity allowlist and the supervisor's identity block are two reads of the same config  | `engine/ci/live/run_signer.py:103` |
| P3 | R2 | The only reproducible Windows same-account proof harness cannot run at this commit: its checked-in root seed d | `apps/desktop/src-tauri/win-live/proof/win_live_proof.ps1:30` |
| P3 | R2 | production_verified never consults which root anchor verified the manifest — a manifest signed by the compiled | `apps/desktop/src-tauri/core/src/production_trust.rs:49` |
| P3 | R2 | win_provision hardcodes manifest_epoch = 2 and rewrites floor.json on every run, so the anti-rollback epoch ca | `apps/desktop/src-tauri/win-live/src/bin/win_provision.rs:121` |
| P3 | R2 | The §5 execution-started gate on Windows reports the DRIVER's own PID as the executor's process group, and is  | `apps/desktop/src-tauri/win-live/src/execution.rs:118` |
| P3 | R2 | DPAPI seal-on-first-use fails open and silently: a CryptProtectData failure leaves the seed plaintext forever  | `apps/desktop/src-tauri/win-live/src/config.rs:140` |
| P3 | R2 | The isolated signer pins its supervisor-attestation verifying key from the deployment config, not the root-sig | `engine/ci/live/run_signer.py:83` |
| P3 | R2 | The §7.1(c)/(d) one-time-nonce and receipt-id replay ledger is an in-process HashSet in every shipped caller,  | `apps/desktop/src-tauri/broker/src/main.rs:384` |
| P3 | R2 | The broker, launcher and executor crates' 52 unit tests are run by no CI job, and brops-executor is never comp | `.github/workflows/ci.yml:51` |
| P3 | R2 | The only workflow that produces the installer the Owner runs resolves a mutable third-party tag while holding  | `.github/workflows/release.yml:59` |
| P3 | R2 | The npm supply-chain gate reports PASS when `npm audit` errors out, because the filter treats an error documen | `.github/supply-chain/npm_audit_filter.py:124` |
| P3 | R2 | design-gates.yml names aios.css as the file it protects; the checker it runs cannot read aios.css, which decla | `.github/workflows/design-gates.yml:3` |
| P3 | R2 | Both Windows 'machine-proof' harnesses print their expected verdict beside an unexamined result and exit 0 unc | `apps/desktop/src-tauri/win-broker/proof/isolation_proof.ps1:46` |
| P3 | R2 | The Linux isolation proof's fourth denial sends the signer's protocol to the supervisor, so it is refused by t | `engine/tools/brops_isolation_prover.py:84` |
| P3 | R2 | governedTurn.ts declares itself the sole route to a 'Verified' badge, but has zero UI callers while a shipped  | `apps/desktop/src/services/governedTurn.ts:121` |
| P3 | R2 | First-run onboarding tells the Owner that anything reaching the AI model runs through a lease and a verified r | `apps/desktop/src/features/Onboarding.strings.ts:21` |
| P3 | R3 | Participant-roster names are interpolated raw into the system prompt of every subsequent turn, unbounded and c | `apps/desktop/src-tauri/src/commands.rs:1072` |
| P3 | R3 | Broker crashes the isolated signer for all future turns by planting a content-mismatched store blob (uncaught  | `engine/runtime/isolated_signer_server.py:273` |
| P3 | R3 | The desktop governance mirror renders GREEN verifier verdicts and an "evidence chain" from an unauthenticated  | `apps/desktop/src-tauri/src/governance.rs:248` |
| P3 | R3 | An EMPTY governance record set is reported as `ok` and awards the green evidence-chain node — `{"ok":true,"rec | `apps/desktop/src/features/Decisions.tsx:321` |
| P3 | R3 | The Windows launcher primitive takes a service-account password as a command-line argument, where any local ac | `apps/desktop/src-tauri/win-broker/src/bin/spawn_as.rs:141` |
| P3 | R3 | `brops_protocol` — the strict IPC codec the design names as the signer/supervisor boundary — has no deployed c | `engine/runtime/challenge_authority_server.py:239` |
| P3 | R3 | The chat trust badge is an unverified stored string joined on a non-unique column, and the projection whitelis | `apps/desktop/src-tauri/core/src/repo.rs:954` |
| P3 | R3 | The evidence-head floor validates final_event_hash case-insensitively but compares it case-sensitively, and th | `apps/desktop/src-tauri/core/src/supervisor_ledger.rs:779` |
| P3 | R3 | accept_prepare's idempotency comparison, documented as exhaustive over the durable binding, silently omits eve | `apps/desktop/src-tauri/core/src/supervisor_ledger.rs:358` |
| P3 | R3 | files.rs returns two distinguishable error strings, giving a compromised renderer a whole-filesystem existence | `apps/desktop/src-tauri/src/files.rs:200` |
| P3 | R3 | 0014's "cannot be turned into a storage-DoS vector" is false: the evidence tables have a per-row cap but no ro | `apps/desktop/src-tauri/core/schema/0014_receipt_verification.sql:57` |
| P3 | R3 | §4.3 governed-turn lease is not implemented: the signed 25-field artifact is an unsigned 5-field blob, so the  | `engine/runtime/governed_supervisor.py:710` |
| P3 | R3 | §0.1's platform capability gate has no implementation: the predicate the design calls Windows's "explicit, tes | `engine/ci/live/run_supervisor.py:130` |
| P3 | R3 | §7.1's mandatory freshness step is absent from the broker's final acceptance predicate — verify_and_accept tak | `apps/desktop/src-tauri/core/src/governed_verification.rs:276` |
| P3 | R3 | §4.7 execution receipt is not implemented: the only artifact that would assert exit_code == 0 and bind the out | `engine/runtime/governed_supervisor.py:688` |
| P3 | R3 | §1.5 step 4 — the signer's policy-authorization check — was dropped in the rev-30 signer: REASON_POLICY_MISMAT | `engine/runtime/isolated_signer.py:199` |
| P3 | R3 | §2.3's runtime store-ACL enforcement is unimplemented and, on the production kit, never runs at all | `engine/runtime/brops_evidence_store.py:76` |
| P3 | R3 | The only rollback action on the Linux refuse path kills `sudo`, not the privileged execution — a refused turn  | `apps/desktop/src-tauri/broker/src/chain_executor.rs:803` |
| P3 | R3 | Windows supervisor: `complete-run` publishes its three terminal artifacts into the protected store BEFORE the  | `apps/desktop/src-tauri/win-live/src/servers.rs:744` |
| P3 | R3 | The entire §4.10(f) output-stream refusal ladder — one-shot capability token, TTL tombstone, sweep, per-instal | `apps/desktop/src-tauri/core/src/governed_output_stream.rs:128` |

---

*No file in menqstudio/OS was modified in the course of these audits.*
