# Remediation audit — menqstudio/OS

**Target:** `main` @ `219c76312e0a5204c4e9a4f1b012581742e93191` (PRs #54, #53, #55, merged 2026-08-06)
**Brief:** `AUDIT_BRIEF_2026-08-06-remediation.md`, commissioned by Gev (Owner)
**Prior audit re-checked:** `apps/desktop/AUDIT/2026-08-06-independent-audit.md`
**Date:** 2026-08-06
**Mode:** READ-ONLY. No file in the repository was created, modified or deleted. No commit, no push.
Tests were executed against an exported snapshot, never against the working tree.

**Method:** 10 blocker groups, each read line-by-line by an attacker agent and then attacked again by an
adversarial reviewer whose brief was to kill both the findings *and* the CONFIRMED_CLOSED verdicts.
20 agents, 2.76M tokens, 613 tool calls, 0 agent errors. Plus the auditor's own test execution and
code verification recorded in §5.

---

## 1. Verdict

# RED

> **The Owner should NOT be asked to flip `platform_governed_execution_supported()`.**

The single question the brief poses is:

> *Can any in-scope adversary cause the desktop app to commit a message with
> `trust_state = trusted_verified` and `production_verified = true` that the governed chain
> did not actually produce, bind and sign?*

**Yes — adversary #2, the broker service account, still can.** The remediation genuinely narrowed
the F-01 signing oracle, but it did not remove it. `output_handle` — the digest of the exact reply
text the desktop commits — is still reported by the executing chain and copied verbatim into the
signed attestation. The supervisor never observes the execution it attests.

This is not a regression. It is the original F-01 property, surviving a fix that addressed the
original F-01 *symptom*.

| | |
|---|---|
| Blockers CONFIRMED CLOSED | **4 / 18** |
| Blockers not fully closed | **14** |
| Surviving findings | **45** (P0 1 · P1 5 · P2 13 · P3 26) |
| Findings killed by adversarial review | 1 |
| §3 narrowings judged UNACCEPTABLE for a gate flip | **6 / 8** |

---

## 2. Blocker-by-blocker

| Blocker | Verdict | Evidence |
|---|---|---|
| **F-13/F-14** | STILL OPEN | `engine/runtime/bro_completion.py:217-222 (floor load and pass, 'floor or None'), :226-227 (advance via a secon` |
| **F-29** | STILL OPEN | `apps/desktop/src-tauri/core/src/production_trust.rs:41-47, :60, :73-75, :141-154; apps/desktop/src-tauri/core/` |
| **F-01** | PARTIALLY CLOSED | `engine/runtime/governed_supervisor.py:848-857 (evidence_from_state copies state.output_handle et al.), :861-86` |
| **F-01 Windows twin (supervisor attest-run sign-oracle, Windows Rust twin)** | PARTIALLY CLOSED | `win-live/src/servers.rs:284-337 (ATTEST_INPUT_FIELDS / COMPLETION_FIELDS), :411-430 (in-process state + the ad` |
| **F-02/F-18** | PARTIALLY CLOSED | `governed_recorder.rs:54-70,109,304-382; chain_executor.rs:544-564,751,833-848,853-855,864-883,1437-1445; gover` |
| **F-06** | PARTIALLY CLOSED | `engine/runtime/bro_signature.py:257-263 (reads os.environ, not the caller's env); :397-403 (Windows refusal ga` |
| **F-08** | PARTIALLY CLOSED | `apps/desktop/src-tauri/launcher/src/main.rs:343-349 (store_input_pins), 404-472 (real_main ordering: 424 lease` |
| **F-09** | PARTIALLY CLOSED | `engine/runtime/governed_supervisor_ledger.py:249 (BEGIN IMMEDIATE), :344-387 (INSERT-with-IntegrityError CAS),` |
| **F-10** | PARTIALLY CLOSED | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25-28,43-107,115-142; apps/desktop/src-tauri/core/src/tcb_integ` |
| **F-11** | PARTIALLY CLOSED | `engine/runtime/governed_supervisor_server.py:614 (json.loads), :626 (except tuple), :634+:651-670 (_try_write)` |
| **F-17** | PARTIALLY CLOSED | `engine/ci/live/provision_keys.py:184-189,220,228,236-251,262-273,346-361; apps/desktop/src-tauri/proof/src/bin` |
| **F-27** | PARTIALLY CLOSED | `engine/runtime/governed_supervisor.py:605-618, :803-838; engine/runtime/governed_supervisor_ledger.py:589-611;` |
| **F-31** | PARTIALLY CLOSED | `apps/desktop/src-tauri/broker/src/main.rs:185 (serial `for stream in listener.incoming()`), :193-199 (deadline` |
| **Windows production path (can it mint trusted_verified + production_verified=true the chain did not produce?)** | PARTIALLY CLOSED | `win-live/src/bin/win_live_turn.rs:99-127, :145-153, :162-174, :199-206, :218-253; win-live/src/resolver.rs:79-` |
| **F-07/F-28** | CONFIRMED CLOSED | `engine/ci/live/run_live_turn.sh:171-184, :190, :195, :217, :224, :144-148, :259-261, :271, :131-141; engine/ci` |
| **F-23** | CONFIRMED CLOSED | `engine/runtime/governed_supervisor_server.py:89-98 (LEASE_FIELDS write-only), :466-479 (_op_launch_gate, exhau` |
| **F-26** | CONFIRMED CLOSED | `governed_verification.rs:183-192 (BrokerContext fields), :324-335 (the guard), :517-551 (negative test), :555-` |
| **F-32/F-36** | CONFIRMED CLOSED | `apps/desktop/src-tauri/src/governed_turn.rs:22 (MAX_REPLY_BYTES = 8192+64), :50-56 (connect then set_read_time` |

### Detail

#### F-13/F-14 — STILL OPEN

**What was attacked.** (1) Is the x >= x tautology genuinely gone and does the floor now refuse a retained older head? (2) Can the durable mark be CLEARED — one file unlinked, and the whole head-floor/ DIRECTORY removed (the case the shipped test does not cover, which only truncates)? (3) Can it be REDIRECTED via BRO_EVIDENCE_HEAD_FLOOR, and what validates that variable? (4) Does the mark travel with BRO_EVIDENCE_STORE, i.e. does naming the store also name the mark? (5) Is 'advanced only upward' safe under a racing store write and under two concurrent turns? (6) Does any production caller still pass None in a way that matters? (7) Can ANY deployment configuration deliver the claimed property? Items (1)(2)(3)(5) were run end-to-end against the snapshot's own fixture, so every event, head and signature in my attacks is genuine — no forgery anywhere.

**Why it held / where it failed.** HELD: the tautology IS gone. bro_completion.py:217-222 no longer feeds load_head(...).head_sequence back into validate_chain, and the caller's None no longer disables anything because the floor is loaded internally — so F-14's 'every caller passes None' is moot rather than unfixed (grep confirms no production caller passes a real value: bro_completion.py:386-387, :462-464, bro_orchestration_runtime.py:725-728). I reproduced the shipped property: head 5 accepted, mark recorded, genuine older head 1 then REFUSED with 'evidence head is stale'. A truncated mark refuses as claimed. FAILED, three ways, all executed: (a) shutil.rmtree(<store>/head-floor) then re-present the genuine head 1 — ACCEPTED, digest 885c905f38b41ff0, because _load_head_floor's 'not path.exists() -> return 0' (bro_completion.py:255-256) treats a DELETED mark as absent while the shipped test only truncates (test_evidence_chain.py:341-349); unlink and rmtree are not a weaker capability than truncate. (b) BRO_EVIDENCE_HEAD_FLOOR=<fresh empty dir> — ACCEPTED, same digest; _head_floor_dir (:243-245) honours that ambient variable with no CI gate, no ownership check, no mode check, and it overrides an explicitly passed store, so the durable runtime — documented at :488-493 as keyed off supplied keys/store 'rather than the builder's environment' — has its anti-rollback record relocated by the builder's environment anyway. (c) the default puts the mark INSIDE the store (:245) and the store is named by BRO_EVIDENCE_STORE (:208), so redirecting the store redirects the mark; _load_head_floor on any other directory returns 0, which I measured. Two further defects: the advance path re-reads the head a SECOND time (:226-227) instead of using the head validate_chain just verified — I proved the consequence: the chain verified against genuine head 9 while the recorded floor came out 1; and _advance_head_floor is an unlocked load-compare-write over a shared <task>.floor.json.tmp (:271-283), so two turns can lower the mark or collide. DECISIVE: the mark is written by the very process it polices (bro_completion.py:226, inside the builder's Stop gate), so the ledger's own mitigation — 'a deployment that can put the marks under a principal the builder cannot write' — is unimplementable: make that directory unwritable and the write at :278 raises OSError -> CompletionError, turning the first genuine completion RED. No configuration of this design yields the claimed property. Nothing outside the source comment says any of this: BRO_EVIDENCE_HEAD_FLOOR appears in no runbook, no PROJECT_STATE/NEXT_CHAT, and not in the preflight's LEDGER_VARS (bro_deploy_preflight.py:47-55), and is set nowhere in the repo, CI or the live kit.

**Evidence.** `engine/runtime/bro_completion.py:217-222 (floor load and pass, 'floor or None'), :226-227 (advance via a second load_head), :233-245 (_head_floor_dir env override), :248-266 (_load_head_floor, :255-256 exists()->0), :269-286 (_advance_head_floor, unlocked, shared .tmp), :168-180 (_external_dir), :208 (store from BRO_EVIDENCE_STORE), :386-387 and :462-464 (call sites), :488-493 (the durable runtime's 'not the builder's environment' claim); engine/runtime/bro_evidence.py:112-116 (the comparison being defeated); engine/runtime/bro_hook.py:194 (production Stop caller); engine/runtime/bro_orchestration_runtime.py:725-728; engine/tests/test_evidence_chain.py:341-349 (only truncation covered); engine/tools/bro_deploy_preflight.py:47-55. My runs: [baseline] older head refused; [rmtree] rolled-back head ACCEPTED 885c905f38b41ff0; [env redirect] rolled-back head ACCEPTED 885c905f38b41ff0; [toctou] chain verified against head 9, recorded floor = 1.`

---

#### F-29 — STILL OPEN

**What was attacked.** The assignment's exact test: do the two operands of production_trust.rs:73 have two genuinely independent sources, or does the 'key the chain verified under' still derive from the same manifest lookup wearing a new name? I traced both operands to their origin at all three real call sites (Linux proof kit, Windows named-pipe driver, Windows in-process proof reachable from the shipped app), checked whether resolve_production_key is time-dependent (which could make two lookups diverge), and checked whether the hex decode/encode round trip can lose information.

**Why it held / where it failed.** It failed my attack in the sense that the guard is still incapable of returning false. The remediation moved the argument from `iso.public_key_hex` (the string the lookup returned) to `verifying_key_hex(bytes)` where `bytes` are the ones handed to verify_and_accept — but those bytes are themselves `hex32(resolve_production_key(...).public_key_hex)` over the SAME manifest value and the SAME key_id, and resolve_production_key is `manifest.keys.iter().find(|k| k.key_id == key_id)` (key_manifest.rs:131), i.e. first-match and time-independent, so the second lookup inside resolve_trust_state (production_trust.rs:60) returns the byte-identical string. hex32 is a faithful 64-char decode (live_turn.rs:97-109, manifest_resolver.rs:119-131, win-live crypto::hex32) and verifying_key_hex emits lowercase `{b:02x}` (production_trust.rs:41-47), so the comparison at production_trust.rs:73 is `x.to_lowercase() == x.to_lowercase()`. The branch at :74 remains unreachable in production and the test at :141-154 still exercises a state no call site can produce. I could not construct any reachable divergence: the manifest is one owned value (or a clone taken before the move — proof.rs:182, win_live_turn.rs:117), never re-read from disk mid-turn, and the recording point in the Windows resolver (resolver.rs:279) is the resolution step, not the verification step, so it would not even catch a chain that later verified under different bytes. NOTE ON THE LEDGER'S WORDING: 'the second lookup is retired to an early resolvability check' is true only of the caller's explicit lookup (win_live_turn.rs:120-124, proof.rs:185-187 now bind it to `_signer_pub_hex`); resolve_trust_state still performs the second lookup internally at production_trust.rs:60, which is the lookup that makes the comparison circular. As before, the underlying security property still holds by construction — the badge IS bound to the key the chain verified under, because they are the same value — so this is an honesty/attestation defect with no reachable privilege gain, not a bypass. In-scope adversaries gain nothing from it: the manifest is root-pinned to the TCB anchor (manifest_resolver.rs:76-79, win_live_turn.rs:99-108), so none of them can introduce a divergent key to be caught in the first place.

**Evidence.** `apps/desktop/src-tauri/core/src/production_trust.rs:41-47, :60, :73-75, :141-154; apps/desktop/src-tauri/core/src/key_manifest.rs:125-145; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:97-109, :313, :322, :334, :398, :432-438; apps/desktop/src-tauri/win-live/src/resolver.rs:267-285, :227-229; apps/desktop/src-tauri/win-live/src/proof.rs:182, :185-187, :292-293, :317-327; apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:117-124, :199-200, :229-240; apps/desktop/src-tauri/broker/src/chain_executor.rs:353-358`

---

#### F-01 — PARTIALLY CLOSED

**What was attacked.** Seven attacks. (1) Old-protocol replay: sent `attest-run {run_id, execution_attempt_id, facts}` to see whether `facts` is silently dropped. (2) Fabricated run: `attest-run` for a run/attempt that was never accepted. (3) Row-selection influence: traced every wire parameter of attest-run to see whether it reaches the signed evidence directly or by choosing which durable row is rebuilt. (4) Direct ledger write: checked whether the broker uid can create the acceptance/completion rows it wants by writing the sqlite file. (5) Terminal-state without execution: drove accept-open -> launch-gate -> execution-started -> complete-run -> attest-run with no recorder, no launcher and no executor ever spawned. (6) DDL gate: byte-compared the two .sql files myself and located the CI job. (7) Restart: closed and reopened the ledger mid-turn and continued the lifecycle.

**Why it held / where it failed.** It held on five of seven, and failed decisively on the fifth. HELD: (a) `build_run_attestation` genuinely has no `facts` parameter — its first positional argument is typed `AttestationState` and it raises SupervisorError on anything else (governed_supervisor.py:861-900); (b) the exhaustive shape check rejects the old protocol with a hard ServerError, observed verbatim as "attest-run has unexpected field(s) ['facts']" (governed_supervisor_server.py:552); (c) a fabricated run returns `no_terminal_run_state`, observed verbatim (governed_supervisor_server.py:556-564, governed_supervisor_ledger.py:814-855); (d) `run_id` is a CHECK not a selector (ledger:852) and `execution_attempt_id` only selects among rows the supervisor itself minted, so neither wire parameter contributes a value to the evidence; (e) the ledger DB is 0700 and chown'd to the supervisor account (run_live_turn.sh:186-190) while the supervisor process creates it 0600 (ledger:196-202), so the broker cannot forge rows by writing the file — it must go through the socket; (f) the DDL parity gate is real and wired — the two files are byte-identical and the `ledger-ddl` job runs `python tools/check_ledger_ddl_parity.py` on push-to-main and on five pull_request event types (ci.yml:1-14, 244-265), and the gate hard-fails on a missing copy rather than skipping; (g) the ledger survives a mid-turn restart — I closed and reopened it between accept-open and launch-gate and the gate still proceeded off the persisted window. FAILED: the state machine contains no proof of execution. `execution-started` records caller-asserted `process_group_id`/`cgroup_id` with no probe of any kind (governed_supervisor_ledger.py:490-497), and `complete-run` accepts seven run-produced values raw off the wire (governed_supervisor_server.py:505-541 -> ledger:589-623 -> ledger:731-746) which `evidence_from_state` then copies verbatim into the signed evidence (governed_supervisor.py:848-857). Chief among them is `output_handle` — the digest of the reply text the desktop commits. Every op is admitted from the SAME single uid (governed_supervisor_server.py:607), so the party the isolated-signer split exists to constrain drives every hop. I ran the whole lifecycle with no executor and obtained a signed brops.run-attestation.v1 whose `output_handle` is the sha256 of bytes I authored. The specific defect F-01 quoted is closed; the security property F-01 exists to establish — that the broker uid cannot obtain a signed receipt for a run that never happened — is not.

**Evidence.** `engine/runtime/governed_supervisor.py:848-857 (evidence_from_state copies state.output_handle et al.), :861-867 (no facts parameter), :899-900; engine/runtime/governed_supervisor_ledger.py:490-497 (mark_executing, no probe), :556-559 (COMPLETION_HANDLE_FIELDS), :731-746 (raw facts inserted), :814-855 (load_attestation_state), :196-202 (0600 db); engine/runtime/governed_supervisor_server.py:505-541 (_op_complete_run), :552-564 (_op_attest_run), :607 (single-uid allowlist); engine/ci/live/run_live_turn.sh:180 (store 2775 group brops-store = supervisor+broker), :186-190 (ledger 0700 supervisor-owned); engine/ci/live/provision_keys.py:307-316 (every service allowlists only the broker uid); .github/workflows/ci.yml:244-265 (ledger-ddl job); tools/check_ledger_ddl_parity.py:60-91; both supervisor_ledger.sql copies sha256=772a8da43f4a9e19d0f6ffbf293571f814423918fb4569a21731ddaa423b4c48`

---

#### F-01 Windows twin (supervisor attest-run sign-oracle, Windows Rust twin) — PARTIALLY CLOSED

**What was attacked.** I attacked the Windows Supervisor core (win-live/src/servers.rs:411-882) five ways, treating the broker service account as the adversary. (1) Old-protocol replay: send `attest-run` with the original `{op, run_id, execution_attempt_id, facts}` shape. (2) Fabricated run: `attest-run` naming a run_id/attempt that was never accepted. (3) Half-run: accept-open -> attest-run, skipping launch-gate/execution-started/complete-run. (4) Second-door smuggling: push the identities and acceptance timestamps the signer allowlists (`executor_id`/`builder_id`/`supervisor_id`/`challenge_accepted_at_ms`/`receipt_id`) in through `complete-run`'s `produced` object instead. (5) Cross-supervisor: present a genuinely authority-signed challenge addressed to a different `supervisor_id`. I then attacked the ledger row's specific claim -- 'durable terminal state over a CI-gated shared DDL ... Fixed in BOTH supervisors' -- by looking for the Windows durable store and its CI gate.

**Why it held / where it failed.** The ORACLE SHAPE IS GENUINELY CLOSED, and I could not break it. (1) dies at servers.rs:798 `if !exact_keys(o, &["op", "run_id", "execution_attempt_id"])` -- exhaustive key equality, so a `facts` key is a hard refusal, and `build_run_attestation`-with-facts has no analogue anywhere in the crate. (2) dies at servers.rs:811-813 -> `no_terminal_run_state`. (3) dies at servers.rs:815 `a.state != ST_COMPLETED` and 818-821 (`completion` is None) -> `no_terminal_run_state`; the state machine is enforced at every hop (launch_gate:617 requires LEASE_READY, execution_started:646 requires EXECUTION_STARTING, complete_run:779 requires EXECUTING). (4) dies at servers.rs:672 `if !exact_keys(p, &COMPLETION_FIELDS)` -- `produced` admits exactly 7 run-produced values; every id, nonce, identity and acceptance timestamp is an unknown key and refused. (5) dies at servers.rs:542-544 `supervisor_mismatch`. The evidence at servers.rs:826-861 is assembled ONLY from the acceptance row (written at 563-587 from the signature-verified challenge, verified at 517 against the config-pinned challenge pubkey), the write-once completion, and SupervisorConfig provisioning. accept-open is CAS'd on the challenge content address (549-557), so one signed challenge mints exactly one attempt.

WHAT DID NOT HOLD is the ledger's stated MECHANISM. The row says the fix is 'evidence built from the supervisor's own DURABLE terminal state over a CI-gated shared DDL (tools/check_ledger_ddl_parity.py)... Fixed in both supervisors (Linux Python + the Windows proof-kit Rust twin)'. On Windows there is no durable state and no DDL: servers.rs:426-429 is `accepted: Mutex<BTreeMap<String, Acceptance>>` / `by_challenge: Mutex<BTreeMap<String, String>>`, in-process RAM, and the crate's own comment at servers.rs:423-425 admits it. tools/check_ledger_ddl_parity.py:32-34 compares only engine/runtime/supervisor_ledger.sql against apps/desktop/src-tauri/core/schema/supervisor_ledger.sql -- the Windows twin is not a party to that gate. The shared DDL's `governed_evidence_head_floor` table (parity tool REQUIRED_CLAUSES) has NO Windows counterpart at all. win_live_turn.rs:61 calls `brops_core::supervisor_ledger::create_schema(conn)` on an `open_in_memory()` connection the supervisor never touches -- dead wiring that makes the durable ledger look present.

I judge the in-process store to be integrity-EQUIVALENT (a peer cannot reach another process's heap without debug privilege, and a supervisor restart yields `no_terminal_run_state`, i.e. fail-closed) but the row's claim of parity is false, and five of the 28 signed evidence fields on Windows are still values no principal measured (see findings W-01/W-02). PARTIALLY_CLOSED, not CONFIRMED_CLOSED.

**Evidence.** `win-live/src/servers.rs:284-337 (ATTEST_INPUT_FIELDS / COMPLETION_FIELDS), :411-430 (in-process state + the admission comment), :442-455 (dispatch), :468-599 (accept_open, sig verify at 517, supervisor bind at 542, challenge CAS at 549-557), :604-626 (launch_gate by attempt id only), :660-789 (complete_run write-once), :791-881 (attest_run, exact_keys at 798, no_terminal_run_state at 811-821, evidence assembly 826-861); win-live/src/execution.rs:110-147; win-live/src/bin/win_live_turn.rs:57-63; tools/check_ledger_ddl_parity.py:32-51; apps/desktop/AUDIT/AUDIT_LEDGER.md:23`

---

#### F-02/F-18 — PARTIALLY CLOSED

**What was attacked.** Seven attacks against the claim 'the four evidence_* values are now MEASURED by the recorder, hash-linked, parsed by the broker, from a recorder-private monotonic counter, with no config fallback left'. (1) Searched the whole snapshot for a surviving static/default for the four values. (2) Tried to make RunEvidence::parse accept a chain whose hash link is broken or absent. (3) Traced who can write --evidence-out (owner, mode, group) and whether a weaker adversary than the broker can forge it. (4) Attacked the recorder-state counter: deletion, truncation, rewind, and — the one that worked — choosing a different counter directory. (5) Traced whether the recorder's observation is independent of the broker or takes facts from it. (6) Traced whether anything downstream of the broker (supervisor, signer, final acceptance) can tell a relayed measurement from an invented one. (7) Ran the same seven attacks against the Windows twin (win-live), because F-01's remediation was explicitly done in BOTH supervisors and I wanted to know whether F-02's second half was too.

**Why it held / where it failed.** WHAT GENUINELY HELD (real remediation, not theatre): the Linux config constants are gone — provision_keys.py no longer defines EVIDENCE_FINAL_EVENT_HASH/COUNT/SEQUENCE anywhere (lines 95-100 are now only a comment saying so), and neither main.rs:354-377 nor live_turn.rs:364-384 reads them from config; the recorder's observations are genuinely its own (it hashes the launcher/executor/lease files itself and digests the exact captured output at governed_recorder.rs:322-337 — it takes no fact from the broker, only paths); a missing or malformed chain really does refuse (chain_executor.rs:853-855 -> RunEvidence::parse -> TurnReason::UpstreamBlocked, with no default anywhere); the counter genuinely does not restart on damage (governed_recorder.rs:62 returns None -> err at 314); as provisioned, recorder-state/ is 0700 recorder-owned inside a root-owned 0755 parent (run_live_turn.sh:195, 217), so neither the broker, the login user, nor any other unprivileged account can delete or rewind it, and the report dir is 2770 brops-report (run_live_turn.sh:181) so adversaries #1, #3 and #4 cannot write the evidence file at all. Those legs I could not break. WHAT FAILED: (a) the hash link is written and never checked — nothing in the entire snapshot reads the `events` array (only governed_recorder.rs:362 writes it), and RunEvidence::parse (chain_executor.rs:544-564) reads four scalars and never recomputes previous_event_hash, never compares final_event_hash to sha256 of the last event, never compares event_count to events.len(); the remediation's own new test fixture (chain_executor.rs:1437-1445) is a document with NO events array at all and it parses OK; (b) the chain document is never published or content-addressed — unlike the containment report, which is written into the protected store and named by a handle in the signed receipt (chain_executor.rs:833-848), the evidence chain is read and dropped (853-855), so no auditor holding a receipt can ever check its evidence head against anything, which is verbatim the original F-02 complaint; (c) the four values reach the signer only as the broker's self-report — governed_supervisor_ledger.py:553-556 states outright 'The only §4.9 evidence values the supervisor cannot derive itself, so the executing chain reports them', and validate_completion_facts (588-621) checks shape only, so 'measured' is true only of an honest broker binary; (d) the recorder does not verify that --evidence-state is its own private directory (governed_recorder.rs:54-70 has no ownership or mode check and calls create_dir_all on whatever it is handed), and the sudoers rule at run_live_turn.sh:199 grants the broker the recorder helper with NO argument restriction, so the broker names the counter; (e) decisively, on WINDOWS nothing was fixed at all — win_provision.rs:112,205-208 and proof.rs:147,255-258 still mint the four values as deployment constants, execution.rs:132-135 still splices them into complete-run, and the doc comment at execution.rs:27-28 still says in the shipped source 'Still deployment-static and tracked as audit F-02: ... the four evidence counters are constants rather than measurements of this run.' The ledger row asserts closure with no platform qualification.

**Evidence.** `governed_recorder.rs:54-70,109,304-382; chain_executor.rs:544-564,751,833-848,853-855,864-883,1437-1445; governed_supervisor_ledger.py:553-559,574-580,588-621,626-675; core/src/supervisor_ledger.rs:840-900; run_live_turn.sh:177,181,195,199,217; provision_keys.py:95-100,208-213,397-407; win-live/src/execution.rs:27-28,37-40,132-135; win-live/src/bin/win_provision.rs:112,205-208; win-live/src/proof.rs:147,255-258; win-live/src/bin/win_live_turn.rs:190-193,241-249; AUDIT_LEDGER.md:27`

---

#### F-06 — PARTIALLY CLOSED

**What was attacked.** (1) Does the POSIX branch really compare ownership? (2) Does the WINDOWS SID comparison actually fire, or does it silently never match (wrong SID form, dangling pointer into a freed token block, a swallowed ctypes exception)? I ran it on this Windows 11 host. (3) Is BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged an escape hatch an in-scope adversary can set, and is it gated the way the module gates its other env anchor? (4) Is it set anywhere in the repo, CI, the live kit, or any default? (5) Can a caller that curates its environment suppress it? (6) Is the acknowledgement actually surfaced to anyone, as the module claims? (7) Does the Windows Administrators/SYSTEM ACE skip leave an in-scope adversary with write access to a pin it does not own?

**Why it held / where it failed.** HELD: the POSIX check is real and unconditional (bro_signature.py:499-505, st_uid == os.geteuid()); it sits on the SHARED _pin_from_file so it also covers the registry anti-rollback floor pin; running as root fails it, correctly. The WINDOWS check is real and I proved it fires: my probe wrote a pin file and _pin_from_file refused it with 'BRO_OPERATOR_ROOT_PUBKEY_FILE is owned by the very account reading it'; the token-user SID resolved to S-1-5-21-4143592576-1820857250-2239199907-1002 and the file's SDDL owner was that same SID. My 'silently never matches' hypothesis is REFUTED — the SID is copied into a caller-owned buffer (bro_signature.py:314-316) exactly as the comment claims and EqualSid matched. The Administrators/SYSTEM ACE skip (bro_signature.py:433-435) is also NOT a finding: my file inherited D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;FA;;;OW), and a non-elevated token carries the Administrators SID deny-only, so a non-admin in-scope adversary cannot use it; an elevated admin is root-equivalent and out of scope. The acknowledgement is set NOWHERE — grep across the snapshot returns only bro_signature.py and two test files. FAILED: the acknowledgement is an ungated environment variable read from the AMBIENT process environment (bro_signature.py:263, os.environ.get, deliberately not the caller's mapping). The F-06 attack requires setting BRO_OPERATOR_ROOT_PUBKEY_FILE in the verifying process; anyone with that capability has BRO_OPERATOR_ROOT_PIN_SELF_OWNED for free, so against exactly the adversary the pin exists to stop the fix costs one extra export. The same module gates its other env anchor on BRO_ENV=ci for precisely this reason (bro_signature.py:535-539); the acknowledgement has no CI gate, no file form, no operator signature. I proved the curated-mapping bypass: resolve_operator_root_pin({ENV_PIN_FILE: <self-owned pin>}) ACCEPTED the pin while the mapping contained no acknowledgement, because it came from os.environ. And 'callers are told so rather than left with the unqualified claim' (bro_signature.py:35-36) is unimplemented — the predicate's value is never returned, logged or surfaced, and I RAN the deployment-posture tool against the author's own fixture: preflight() returned [] and main() would print 'GREEN: deployment posture hardened' for an anchor owned by the account running the process.

**Evidence.** `engine/runtime/bro_signature.py:257-263 (reads os.environ, not the caller's env); :397-403 (Windows refusal gated on the ack); :499-505 (POSIX refusal, same gate); :535-539 (the BRO_ENV=ci gate applied to the OTHER env anchor but not this one); :34-36 (the 'callers are told so' claim); engine/tools/bro_deploy_preflight.py:71-79 (check_operator_pin has no self-owned check), :123 (CHECKS), :126-132 (preflight), :135-145 (main prints GREEN on []); engine/tests/test_deploy_preflight.py:50-53 (ack started in setUp), :67-68 (test_hardened_environment_passes asserts []); engine/tests/test_signature_authority.py:441-461 (_write_pin_file sets the ack for every positive case). My runs: pin owner 'OFFICE\Admin', process account 'Admin', preflight failures = [], verdict GREEN; plus default-refusal / ack-accepted / curated-mapping-accepted on Windows 11.`

---

#### F-08 — PARTIALLY CLOSED

**What was attacked.** I attacked the claim in AUDIT_LEDGER.md:28 that "launcher pin = executed bytes = attested digest", along all seven axes in my brief. (1) TOCTOU between digest and exec: is there any window where the bytes behind fds 3/4/5 can change, and can an in-scope adversary reach an inode he can write? (2) pread offset: does the actual syscall disturb the executor's offset? (3) lease swap between parse and use, and lease-file selection (argv[0] is chosen by the invoker). (4) fd->pin mapping: transposition, duplicated fds, two equal digests. (5) degenerate inputs: empty file, directory, pipe/socket, over-ceiling file. (6) ordering: is the check strictly before the drop and the exec, with no early return that skips either? (7) the OTHER end of the equality: is the lease pin ever compared, at runtime, to the digest the receipt actually attests?

**Why it held / where it failed.** HELD (genuinely closed, and I could not break these): the original exploit is dead. Overwriting <recorder_store_dir>/system in the PINNED store now refuses the launch, because verify_store_input_bindings (main.rs:518-526) re-hashes the held descriptors against the root-owned lease pins before the drop and before the exec. parse_lease (main.rs:261-338) makes all three pins REQUIRED, single-valued and 64-lowercase-hex, so "unpinned" is genuinely inexpressible (a lease missing system_sha256 returns None at main.rs:333-336 and read_and_verify_lease turns that into TcbIntegrity("lease-parse") at main.rs:508). pread(2) really does not move the file offset, so the executor still starts at byte 0 — and the offset_zero fact was measured from fdinfo BEFORE the digest (main.rs:628-631,659), so the comment matches the syscall. The lease cannot be swapped between parse and use: it is fstat'd on the OPENED fd and read through that same fd (main.rs:481-508), and the pins are then used from an owned in-memory Lease. A forged lease file needs root or uid-500 ownership plus no group/other write (image_owner_mode_ok, main.rs:222-227,497) — the broker cannot produce one. The fd->pin map is unambiguous and matches reality: store_input_pins 3=system,4=history,5=generation_config (main.rs:343-349) is exactly the recorder's dup2 map (governed_recorder.rs:162-170) and exactly the order the attested request envelope is built in (isolated_signer.py:681-684). A duplicated fd or two equal pins is harmless because the check is on CONTENT, not identity. A directory or pipe on fd 3/4/5 is refused twice over — is_regular_store_inode is false (main.rs:646-648) so verify_launcher_fd_set returns BadStoreInput (fd_lifecycle.rs:90-93), and pread on a directory/pipe returns -1 so digest_fd_at_zero yields None (main.rs:545-547). Ordering is correct with no skipping path: 444 digest -> 457 drop -> 463 final-state verify -> 469 image open+hash -> 470 fexecve, and every step is `?`-propagated with no early Ok.

FAILED (why this is not CONFIRMED_CLOSED): the guard binds the executed bytes to the lease, but nothing binds the lease to the inode the recorder opens, and nothing at runtime binds the lease pin to the digest the receipt attests. Both gaps are reachable by adversary #2 alone. (a) The store-input fds are validated as "a regular file <= 8 MiB" and nothing else — collect_fd_facts carries no device/inode/owner/mode, and main.rs:640 still says "TODO: bind st_dev to the lease's store device". The recorder opens {--store}/system with no validation of --store (governed_recorder.rs:125-134), and --store comes from the broker (chain_executor.rs:762-764). So the broker can point the fds at an inode IT can write, satisfy the digest at T0 with a copy of the genuine bytes, and rewrite that same inode before the executor's read_to_end at proof_executor.rs:49-51 — the launcher never re-checks after main.rs:520, and nothing anywhere compares the executor's own reply_binding (proof_executor.rs:125-130) against the attested handles (repo-wide grep: reply_binding appears in no other file). (b) The attested side is still entirely broker-chosen and never compared to the lease: live_turn.rs:339-341 reads resolved.*_sha256 from the broker's config, challenge_authority.py:215-224 accepts any 64-hex value, governed_supervisor.py:632-634 stores them verbatim, isolated_signer.py:634-645 "derives" them tautologically from store/<handle>, and the ONLY place lease pin == attested digest is asserted is the deployment-time shell PYCHECK at run_live_turn.sh:122-130, run by root against one config file the broker is not obliged to use. So the ledger's "launcher pin = executed bytes = attested digest" is true for the middle equality per-turn and false for the outer one at runtime.

**Evidence.** `apps/desktop/src-tauri/launcher/src/main.rs:343-349 (store_input_pins), 404-472 (real_main ordering: 424 lease, 431 invoker, 434-435 fd set, 444 store-input bindings, 457 drop, 463 verify, 469-470 image+fexecve), 478-509 (read_and_verify_lease), 518-526 (verify_store_input_bindings), 530-559 (digest_fd_at_zero / pread loop), 594-673 (collect_fd_facts; 640 the st_dev TODO; 646-648 is_regular_store_inode), 222-227 (image_owner_mode_ok), 261-338 (parse_lease), 395 (TCB_OWNER_BROPS_ADMIN_UID = 500); core/src/fd_lifecycle.rs:71-111 (verify_launcher_fd_set, StoreInput branch 90-97); proof/src/bin/governed_recorder.rs:73-91 (--store/--lease unvalidated), 125-134 (open_ro by name), 162-175 (dup2 to 3/4/5); proof/src/bin/proof_executor.rs:49-51,88-96 (reads fds 3/4/5 AFTER exec), 125-130 (reply_binding, never checked); broker/src/chain_executor.rs:762-787 (recorder argv), 819-827 (broker writes store blobs), 284-286 + 363-365 (attested digests are the broker's config values); proof/src/bin/live_turn.rs:339-341, 369-372; engine/ci/live/run_live_turn.sh:110-141 (static lease, root-owned 0644), 122-130 (deploy-time-only PYCHECK), 176-184 (brops-store group = supervisor+broker; STORE 2775; files 0644), 199 (sudoers, no argument restriction), 244 (TCB floor is a separate root-run step before services start); engine/runtime/challenge_authority.py:215-224; engine/runtime/governed_supervisor.py:632-634; engine/runtime/isolated_signer.py:629-645, 667-686; engine/ci/live/run_signer.py:49-60 (FileArtifactStore.read_verified); engine/ci/live/provision_keys.py:284-291 (named file AND content-addressed blob written separately).`

---

#### F-09 — PARTIALLY CLOSED

**What was attacked.** Five attacks, in order.

(1) REPLAY — one signed challenge, two leases. Sent the same challenge_doc twice through _op_accept_open (governed_supervisor_server.py:412).

(2) CAS SHAPE — is it a real atomic compare-and-swap or a SELECT-then-INSERT? Read the exact SQL and the transaction boundaries in reuse_or_prepare / _prepare_locked (governed_supervisor_ledger.py:390-423, 341-387) against the UNIQUE constraints in supervisor_ledger.sql:88-90,96-97.

(3) CONCURRENCY — two callers racing the same challenge; isolation level; deferred vs immediate.

(4) RESTART MID-TURN — kill the supervisor after accept-open and before complete-run, restart, replay the challenge, and try to get a second fresh attempt or a fresh lease window.

(5) REACHABILITY + SIGN-WITHOUT-CAS — found every production caller, and tried to reach attest-run's signature without walking the full ACCEPTED_PREPARED -> LEASE_READY -> EXECUTION_STARTING -> EXECUTING -> COMPLETED chain.

Then separately attacked the evidence-head floor: (6) can I bypass it by choosing the key it is stored under, and (7) can I choose the value it compares?

**Why it held / where it failed.** THE ACCEPTANCE-CAS HALF HELD, on the Linux/Python path, against all five attacks.

(1) Replay is neutralised. Second accept-open: accept_open mints a FRESH lease_id/execution_attempt_id/receipt_id (governed_supervisor.py:603-609, 629), but reuse_or_prepare looks the challenge up by its content address FIRST (governed_supervisor_ledger.py:408-411) and returns the ORIGINAL row; the server then DISCARDS the freshly-minted ids and rebuilds the lease from the durable row (governed_supervisor_server.py:444-451), including the ORIGINAL lease_expires_at_ms. A replay therefore buys neither a second attempt nor an extended window. challenge_handle = sha256(JCS(payload)) (governed_supervisor.py:602) covers every payload field, so a byte-different challenge cannot collide with an existing row's handle.

(2) It is a REAL CAS, not SELECT-then-INSERT. The write path is an unconditional INSERT wrapped in `except sqlite3.IntegrityError` with a unique-violation classifier (governed_supervisor_ledger.py:344-387, 235-236), backed by three table-level UNIQUEs plus a UNIQUE index on receipt_id (supervisor_ledger.sql:88-90, 96-97). The SELECT in reuse_or_prepare is not the decision — the INSERT's constraint is. On collision the existing row is compared field-by-field over _BOUND_FIELDS plus lease_payload_sha256 (governed_supervisor_ledger.py:382-387); ANY divergence is a hard Conflict, never a second row.

(3) Isolation is BEGIN IMMEDIATE, not deferred. _Tx.__enter__ issues `BEGIN IMMEDIATE` (governed_supervisor_ledger.py:249) and refuses to nest (247-248); open_ledger sets isolation_level=None so Python does not inject its own implicit deferred transaction (197). The write lock is taken BEFORE the SELECT, so two writers cannot both read the same pre-state. Belt and braces: the production accept loop is serial anyway (serve_forever handles one connection at a time, governed_supervisor_server.py:699-720) and run_supervisor.py holds ONE connection (line 130), so no in-process race exists to begin with. I looked for a SQLITE_BUSY escape (sqlite3.OperationalError is not caught by _op_accept_open's `except ledger.LedgerError` at 436, nor by handle_connection's except tuple at 626, so it would kill the process) — but it is unreachable for exactly the same reason: there is never a second writer.

(4) Restart mid-turn holds. The ledger is a real file under a supervisor-private 0700 dir (run_live_turn.sh:190, provision_keys.py:369) opened WAL + synchronous=FULL (governed_supervisor_ledger.py:204-205), so state survives the kill. On restart a replayed challenge returns the ORIGINAL row; the crash-retry advance is idempotent because mark_lease_ready is guarded on `row["state"] == ACCEPTED_PREPARED` (governed_supervisor_server.py:456). A second launch-gate on an attempt already at EXECUTION_STARTING fails: LEGAL_PREDECESSORS[EXECUTION_STARTING] == (LEASE_READY,) so the UPDATE ... WHERE state IN (...) matches zero rows and _advance raises IllegalTransition (governed_supervisor_ledger.py:458-468), with the DDL BEFORE-UPDATE trigger (supervisor_ledger.sql:103-115) as an independent second wall. The failure branch of gate_and_start is equally guarded (EXPIRED's only predecessor is LEASE_READY), so a stale replay cannot even durably EXPIRE an in-flight attempt. Result: exactly one privileged launch per signed challenge, across restarts.

(5) No path reaches signing without the CAS. attest-run's ONLY door is load_attestation_state (governed_supervisor_server.py:556), which JOINs acceptance to completion and returns None unless state == COMPLETED and run_id matches (governed_supervisor_ledger.py:844-855). COMPLETED is written only by record_completion's _advance (770-771) whose only legal predecessor is EXECUTING; EXECUTING only from EXECUTION_STARTING (mark_executing, 490-497); EXECUTION_STARTING only from gate_and_start (524-546); LEASE_READY only from mark_lease_ready. The public `advance()` escape hatch (471-479) has NO caller in governed_supervisor_server.py — I checked every `ledger.` call site in that file (435, 458, 470, 492, 512, 517, 536, 556). build_run_attestation has no `facts` parameter and type-rejects anything that is not an AttestationState (governed_supervisor.py:899-900). Ordering inside record_completion is safe: the completion INSERT and the floor CAS run BEFORE the state check, but an IllegalTransition rolls the whole _Tx back (governed_supervisor_ledger.py:252-259).

So: the original F-09 dead-code defect is genuinely fixed for the acceptance CAS on the Linux/Python production path. run_supervisor.py:130 opens the ledger as a HARD startup prerequisite and :142 serves with it; the shipped Linux broker binary reaches this same chain via build_governed_executor (broker/src/main.rs:216-260), so this is not lab-only.

THE EVIDENCE-FLOOR HALF DID NOT HOLD. It runs (record_completion:764-766 on every genuinely-new completion, and _op_complete_run:536 is the only path to COMPLETED), but it binds nothing:
  * its key is (install_id, task_id) (governed_supervisor_ledger.py:640-644), and BOTH are free-form broker-chosen strings — challenge_authority.validate_create_pending only requires non-empty <= 128 chars (challenge_authority.py:203-214), issue_challenge copies them verbatim (505-506), accept_open copies them verbatim into the row (governed_supervisor.py:613-616), and NOTHING downstream allowlists them (isolated_signer allowlists only executor_id/builder_id/supervisor_id, isolated_signer.py:605-611). A new task_id makes `row is None` and the floor "bootstraps" at whatever value is presented (646-653);
  * its value is also broker-chosen — the four evidence_* fields are read by the BROKER out of a file in the report dir and forwarded (chain_executor.rs:853-855, 874-882). The supervisor is not in the brops-report group (run_live_turn.sh:177 lists only recorder + broker), so it cannot read the recorder's chain itself, and validate_completion_facts only shape-checks (governed_supervisor_ledger.py:612-622).
Against the only adversary it could constrain (the broker uid), it is a no-op.

AND ON THE WINDOWS / RUST LEG THE ORIGINAL DEFECT IS UNCHANGED. Repo-wide grep for `supervisor_ledger::`, `evidence_floor_cas`, `accept_prepare`, `gate_and_start`, `enqueue_terminal`, `pending_outbox`, `lease_launch_gate` across every .rs file yields, outside core/src/supervisor_ledger.rs itself, ONLY `create_schema` — at broker/src/main.rs:69, proof/src/bin/live_turn.rs:159, win-live/src/bin/win_live_turn.rs:61 and win-live/src/proof.rs:83. That is verbatim the original F-09 finding. The Windows twin supervisor (win-live/src/servers.rs Supervisor) has its own in-process acceptance CAS via `by_challenge` (servers.rs:549-557) that does defeat replay, but complete_run (660-789) contains NO floor of any kind.

Hence PARTIALLY_CLOSED: CAS closed on Linux, floor non-binding on Linux, both floor and Rust ledger still unwired on Windows. The ledger's own "partly (◑)" mark is the honest one; the accompanying note "the anti-rollback/anti-fork floor runs on every complete-run" is true only of the Linux Python supervisor and is misleading without that qualifier.

**Evidence.** `engine/runtime/governed_supervisor_ledger.py:249 (BEGIN IMMEDIATE), :344-387 (INSERT-with-IntegrityError CAS), :390-423 (reuse_or_prepare), :454-468 (guarded edge), :524-546 (gate_and_start), :640-677 (_evidence_floor_cas), :689-772 (record_completion), :814-855 (load_attestation_state); engine/runtime/supervisor_ledger.sql:88-90,96-97 (the UNIQUEs), :103-115 (transition trigger), :128-144 (write-once PK + FK), :168-177 (floor PK); engine/runtime/governed_supervisor_server.py:435,444-451,456,470,492,536,556 (the only ledger call sites); engine/runtime/governed_supervisor.py:602-636 (challenge_handle + NewAcceptance), :899-900 (typed attest door); engine/ci/live/run_supervisor.py:130,142 (production wiring); engine/ci/live/run_live_turn.sh:177,190 (report-group membership; ledger 0700); engine/runtime/challenge_authority.py:203-214,505-506 (task_id/install_id are broker-chosen); apps/desktop/src-tauri/broker/src/chain_executor.rs:853-855,874-882 (broker reports the evidence head); apps/desktop/src-tauri/win-live/src/servers.rs:549-557,660-789 (Windows CAS present, floor absent); apps/desktop/src-tauri/broker/src/main.rs:69, proof/src/bin/live_turn.rs:159, win-live/src/bin/win_live_turn.rs:61, win-live/src/proof.rs:83 (the ONLY Rust references to supervisor_ledger, all create_schema)`

---

#### F-10 — PARTIALLY CLOSED

**What was attacked.** (1) Reachability: is there a real non-test caller, or is this still dead code? Traced every reference of verify_deployment_tcb/verify_tcb_integrity repo-wide. (2) Manifest authority: can I substitute or re-point the pin manifest so the floor measures files I chose? (3) Coverage-floor bypass: can a manifest satisfy missing_required() while measuring nothing real? (4) Owner-check bypass: can I forge owner_uids so a login-owned artifact reads as root-owned? (5) Probe TOCTOU: can I get the stat and the digest to disagree? (6) The swap window between the deployment-time check (run_live_turn.sh:244) and the served turn (:271) — who can write each of the 14 pinned files in that interval? (7) Does the content pin have any reference outside the bytes it pins?

**Why it held / where it failed.** HELD on the literal blocker. The original F-10 said verify_tcb_integrity had no caller, no non-test FsProbe, and no TcbPinManifest was ever constructed. All three are now materially false: LinuxFsProbe is a real probe (tcb_probe.rs:43-107), build_tcb_pin_manifest.py emits a real 21-role manifest, and run_live_turn.sh:244 runs it as a hard gate (`|| exit 1`) inside a CI job that runs on every event (ci.yml:98). My owner-forgery attack (4) died on tcb_integrity.rs:256-265: even with attacker-chosen owner_uids, `owner_is_untrusted = runtime_uids.contains(owner_uid) || owner_uid == login_uid` rejects any artifact owned by a service or login principal, and live_turn.rs:184-196 sources those uids from config rather than from getuid(). My swap-window attack (6) died on file modes I verified individually: all 14 distinct pinned paths are root-owned with root-owned 0755 ancestors (run_live_turn.sh:88-96, 141, 153, 200, 208-218), so no in-scope adversary can write one at any moment — only root can, and root is out of scope. My TOCTOU attack (5) is real in the code (tcb_probe.rs:74 re-resolves the path) but unexploitable for the same reason. HELD.

FAILED — why this is PARTIALLY_CLOSED not CONFIRMED_CLOSED: attacks (2), (3) and (7) survived. The content-pin half of the floor is self-referential (F-10-A): build_tcb_pin_manifest.py:106 computes each expected_sha256 from the file itself at run_live_turn.sh:210, and run_live_turn.sh:244 compares those digests against the same unmodified files seconds later in the same script. Nothing rewrites a pinned file in between, and there is no second measurement anywhere (no inotify/fanotify/periodic re-verify exists in the tree). So the HashMismatch branch — the one that would detect a swapped binary, i.e. exactly what F-10 was about — cannot fire in this kit. It is the same x==x defect class the same audit found at F-13/F-14. Additionally the floor's sole authority, tcb-pin-manifest.json, gets no owner/mode/signature check from the code that consumes it (tcb_probe.rs:25-28 is a bare read_to_string) and is not a member of TCB_REQUIRED_ARTIFACTS (F-10-B), while sibling controls in the same commit DO apply exactly that check to their input (ipc_policy.py:39-44, live_turn.rs:74-96). And the coverage floor counts NAMES: 21 roles resolve to 14 distinct files, one pinned artifact is read by no code at all while two policy files that really do gate peer-auth are unpinned (F-10-C). The ledger's sentence 'the production broker AND the live driver run verify_deployment_tcb before they will serve a governed turn' is misleading on both legs (F-10-F): live_turn's verify_tcb is a separate process that std::process::exit()s (live_turn.rs:35-37) and never runs in the turn process, and the broker's leg at main.rs:281 can never pass on this layout because the broker uid cannot traverse /etc/sudoers.d.

**Evidence.** `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25-28,43-107,115-142; apps/desktop/src-tauri/core/src/tcb_integrity.rs:174-202,213-234,243-311; engine/ci/live/build_tcb_pin_manifest.py:64-116; engine/ci/live/run_live_turn.sh:69-96,131-141,153,199-231,244,255-271; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35-37,163-215; apps/desktop/src-tauri/broker/src/main.rs:178,259-289; engine/ci/live/ipc_policy.py:31-52; engine/ci/live/provision_keys.py:300-316; .github/workflows/ci.yml:98`

---

#### F-11 — PARTIALLY CLOSED

**What was attacked.** (1) I replayed the ORIGINAL F-11 attack byte for byte against the real module: an 8191-byte frame `{"op":"<4091 x raw UTF-8 U+0080>"}`, driving dispatch to `raise ServerError("unknown op %r")` and hoping the repr()/json.dumps amplification would exceed MAX_FRAME_BYTES. (2) I attacked the bound itself, looking for an error path that does NOT go through `_bounded_error` — I found one (`_ledger_refusal` -> `_refusal(op, ..., str(exc))` at :318-338 relays an UNBOUNDED `unexpected completion field(s) %s` message built from attacker-chosen key names, governed_supervisor_ledger.py:608). (3) I fed `_try_write` a 20 KB reply directly to see whether the degradation path itself can fail. (4) I then hunted every OTHER exception type that can escape the tuple at :626 — RecursionError from nested JSON, UnicodeDecodeError, struct.error, OSError on a half-closed socket, ledger.LedgerError raised outside a try at :512 and :556, exceptions from the injected verify_sig/recompute seams. (5) I checked whether accept_open can be made to raise rather than refuse.

**Why it held / where it failed.** THE NAMED LEG HELD. The original attack now yields a 525-char bounded error and a 682-byte framed reply (`_bounded_error`, :642-648) — I ran it and got `reply err len 525 / bytes written: 682`. The unbounded `_ledger_refusal` path I found does NOT reopen it, because `_try_write` (:660-670) now catches FrameError and degrades: I handed it a 20 KB reply and got a 53-byte `{"ok":false,"error":"reply exceeded frame bound"}` frame. The seams are contained (governed_supervisor.py:569-572, 580-583 wrap them in `except Exception`). So the FrameError leg is genuinely dead and the ledger row's literal sentence is TRUE.

THE INVARIANT THE FIX CLAIMED TO RESTORE DID NOT HOLD. `except (FrameError, ServerError, SupervisorError, ValueError, UnicodeDecodeError)` at :626 still omits RuntimeError. `json.loads` at :614 raises RecursionError (RuntimeError subclass, `isinstance(e, ValueError) == False`) on a 4090-byte body of `[`, which is INSIDE the 8192 frame bound. I proved this against the real module twice: it escapes handle_connection, and it escapes serve_forever with the second queued connection never accepted. This is exactly the F-25 defect, which the same session left unfixed in all three servers (isolated_signer_server.py:273 and challenge_authority_server.py:241 still have the identical tuple). handle_connection's docstring at :599 ('Never raises on hostile input') and serve_forever's at :697 ('A single hostile connection never tears down the loop') are both still false. Separately, the ONLY regression test guarding the fix is vacuous — see F-11-R2.

No forgery: nothing here produces a lease, an attestation or a trusted_verified. Availability only.

**Evidence.** `engine/runtime/governed_supervisor_server.py:614 (json.loads), :626 (except tuple), :634+:651-670 (_try_write), :642-648 (_bounded_error), :699-720 (serve_forever, finally-only), :205-224 (read_frame, 4090<=8192 accepted), :607 (peer gate); engine/ci/live/run_supervisor.py:142-160 (try/finally, no except; :160 os.unlink(sock_path)); engine/runtime/isolated_signer_server.py:273; engine/runtime/challenge_authority_server.py:241; engine/tests/test_governed_supervisor_server.py:310-319 + :191-193`

---

#### F-17 — PARTIALLY CLOSED

**What was attacked.** The crux: is `anchor.provenance == "external"` a custody statement or a renamed constant? I traced who writes the field, whether anything verifies it, and whether any in-scope party can produce a file whose provenance says external. Then I attacked the anchor file itself: (a) can a non-root account write /opt/brops-live/tcb/root-anchor.json after provisioning; (b) can it be pre-created as a symlink so root writes and then chowns attacker-chosen content; (c) can the /opt world-writable window (everything before run_live_turn.sh:224) be used to substitute a tree carrying an `external` anchor; (d) can the config be edited to redirect root_anchor_path or re-introduce an inline anchor; (e) is the owner/mode check bypassable. Finally: reachability — does the gate run on the production call site, and does CI ever exercise the external branch.

**Why it held / where it failed.** WHAT HELD (real, not cosmetic):
- The anchor is out of the shared config and into a root-owned TCB file. live_turn.rs:260-264 REFUSES a config that still carries /trust/root_pub_hex or /trust/root_key_id, so the self-certifying inline arrangement cannot be re-expressed by editing config; provision_keys.py no longer writes those keys (config `trust` block at :346-361).
- anchor_file_is_tcb_owned (live_turn.rs:77-95) fstats an OPENED fd and requires regular + st_uid==0 + no group/other write; run_live_turn.sh:153 chowns it 0:0 0644. Every forged-anchor attack I built died on `st_uid != 0`: an unprivileged account cannot create a root-owned file. The symlink pre-creation variant (root writes through the symlink, then chowns the target to root) yields a root-owned file whose CONTENT is still what root's provisioner wrote; the attacker can unlink it afterwards but any replacement is attacker-owned -> `not_root_owned`. The /opt-window whole-tree substitution hits the same wall: the attacker can `mv` the original root-owned anchor into their tree (preserving uid 0) but only with its original `kit_generated` bytes.
- The gate is reachable and is the production call site for this kit: live_turn.rs:443-444 `production_verified = ts.is_production_verified() && anchor_is_external`, printed at :452, with two distinct GREEN branches at run_live_turn.sh:284-290. CI (.github/workflows/ci.yml:98) never passes the four external flags, so every CI run reports `production_verified=false root_anchor=kit_generated` — the false production claim the original F-17 objected to is gone from the automated evidence.
WHY IT IS ONLY PARTIAL:
- `provenance` is a self-assertion by the kit about itself. provision_keys.py:184-189 sets `use_external = all(four CLI flags)` and :245 writes the literal string "external". Nothing verifies that the private half exists anywhere but this box: no check of the supplied public key against the root keypair the script generates ANYWAY at :220 and writes to keys/root.priv at :228, no verification of the signature it copies verbatim (:239-242), no ceremony, no second party. The repository's own test proves it: engine/tests/test_live_provisioning_anchor.py:71-93 calls `lc.gen_private()` in the test process, signs on the same machine, and asserts `anchor["provenance"] == "external"`. "external" means "four flags were passed".
- The doc claim F-17 was filed against — key_manifest.rs:84-85 "binary-pinned root key ... never taken from the manifest itself" — is still NOT satisfied on Linux: live_turn.rs:281-288 builds PinnedRoot from a FILE. The Windows kit shows what the claim requires: win-live/src/tcb.rs:28-29 compiles ROOT_PUBLIC_KEY_HEX in and win_live_turn.rs:99-106 pins from that constant, refusing a disagreeing config. The Linux remediation chose a weaker mechanism (a label) than one that already exists in the same repo (a compile-time pin).
- Consequence: today's kit-generated run is honestly labelled, but the moment anyone runs the external mode, run_live_turn.sh:285 prints "genuine production trusted_verified (externally-anchored root)" on the strength of a string. See F-17-A for the walked adversary path.
ONE MORE DEFECT, honestly out of scope so NOT filed as a finding: live_turn.rs checks the anchor on an opened fd at :269 and then RE-OPENS IT BY PATH at :272 to get the bytes. The doc comment at :73-76 claims "it is checked on the OPENED fd, never by a metadata(path) re-lookup" — the check is, the DATA is not, so the property the comment sells (the bytes used are the bytes verified) is not established. Winning that race needs write on root-owned /opt/brops-live/tcb, i.e. root, so per the rules it is not a finding. The fix is one line: read from the already-open File.

**Evidence.** `engine/ci/live/provision_keys.py:184-189,220,228,236-251,262-273,346-361; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:73-95,260-291,443-452; engine/ci/live/run_live_turn.sh:103-106,153,278-294; engine/tests/test_live_provisioning_anchor.py:42-96; .github/workflows/ci.yml:91-98; apps/desktop/src-tauri/win-live/src/tcb.rs:22-34; apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:97-106; apps/desktop/src-tauri/core/src/key_manifest.rs:84-87`

---

#### F-27 — PARTIALLY CLOSED

**What was attacked.** (1) Can the broker still set challenge_accepted_at_ms, directly or by smuggling it into complete-run? (2) Is the value read from a supervisor-written row or recomputed at completion? (3) Does the value survive to the signed envelope without a broker-controllable hop? (4) Does the claimed end-to-end assertion actually discriminate (would it pass if the completion clock were used)? (5) Does the same property hold on the Windows kit the Owner runs?

**Why it held / where it failed.** CLOSED ON LINUX (the production chain). challenge_accepted_at_ms is stamped by the supervisor at accept-open from its own clock into the durable acceptance row (governed_supervisor.py:618 `challenge_accepted_at_ms=now_ms`), and _op_accept_open passes `clock_ms()` explicitly, never a wire value (governed_supervisor_server.py:412-420, doc line 27 'now_ms is NEVER taken from the wire'). It is read back into the attested evidence from that row (governed_supervisor.py:838 `"challenge_accepted_at_ms": state.challenge_accepted_at_ms`). The broker cannot smuggle it: validate_completion_facts rejects ANY key outside COMPLETION_FIELDS and names challenge_accepted_at_ms explicitly as deliberately absent (governed_supervisor_ledger.py:589-611), and the broker's complete-run now sends only output/containment handles, completed_at and the four evidence counters (chain_executor.rs:863-883). The broker also cannot alter the attested bytes: verify_and_accept re-verifies the supervisor signature over the exact evidence_jcs and binds it by digest (governed_verification.rs:303-310). The end-to-end assertion is discriminating: test_challenge_accepted_at_is_the_supervisors_accept_clock drives accept at NOW-2000 and complete at NOW and asserts equality with accept_at plus explicit inequality with completed_at (test_governed_chain_e2e.py:430-469) — it would fail if the completion clock were reused. I also confirmed the Linux broker's completed_at is a genuine post-execution clock (chain_executor.rs:863, computed after child.wait() at 807 and the store writes at 821-841), so the two really differ. NOT DEMONSTRATED, AND BROKEN, ON WINDOWS. Neither Windows path exercises the property, and one of them now fails closed because of it — see findings F-27-W1 and F-27-W2. Residual on both platforms: nothing downstream ever CHECKS the value — I re-read verify_and_accept end to end (governed_verification.rs:276-370) and there is still no timestamp comparison of any kind; the field is now honest but the lease-window containment property is still only auditable by a third party reading the receipt, not enforced.

**Evidence.** `engine/runtime/governed_supervisor.py:605-618, :803-838; engine/runtime/governed_supervisor_ledger.py:589-611; engine/runtime/governed_supervisor_server.py:27, :412-420, :505-517; engine/tests/test_governed_chain_e2e.py:430-469; apps/desktop/src-tauri/broker/src/chain_executor.rs:863-883; apps/desktop/src-tauri/core/src/governed_verification.rs:276-370 (no timestamp check); apps/desktop/src-tauri/win-live/src/servers.rs:570, :716, :984-991; apps/desktop/src-tauri/win-live/src/execution.rs:100,131; apps/desktop/src-tauri/win-live/src/pipe.rs:157; apps/desktop/src-tauri/win-live/src/proof.rs:232,238,260`

---

#### F-31 — PARTIALLY CLOSED

**What was attacked.** (1) Is the deadline armed on the ACCEPTED socket rather than the listener, and BEFORE the first read? (2) Is it re-armed per read — i.e. does a slow-drip peer evade it? (3) Is the accept loop still serial, and is there ANY concurrency, connection cap, or rate limit? (4) Does a sequential reconnect loop restore the original denial even against a fully silent peer? (5) Does the arming-failure branch leak the connection or spin? (6) Has reachability changed since the original refutation — does anything now launch brops-broker, and can build_governed_executor now serve a real chain?

**Why it held / where it failed.** THE NARROW CLAIM HELD, THE FINDING DID NOT. main.rs:193-199 arms set_read_timeout + set_write_timeout on the accepted `s` before handle_conn at :200, so the arming is correct: right socket, right moment, and a failure to arm `continue`s (dropping the stream) rather than serving unarmed. A peer that connects and sends literally nothing forever is now cut at 120s. That is what the ledger sentence claims and it is true.

But the defect F-31 named is not closed. SO_RCVTIMEO is per-syscall, and read_one_frame (:458-478) loops on `stream.read(&mut chunk)` at :468 — one byte every 119s never trips it, and FrameDecoder happily accepts a declared length of 8192 (ipc_framing.rs:89-92), so one connection can hold the thread ~8192*119s ≈ 11 days and then repeat. And the accept loop at :185 is STILL strictly serial: my grep across apps/desktop/src-tauri finds thread::spawn only in win-broker/src/lib.rs:202, none in broker/src/main.rs, and there is no connection cap or rate limit anywhere in the file. So even the fully-silent case is only converted from 'one connection wedges it forever' into 'one connection per 120s wedges it forever' — a reconnect loop denies 100% of wall-clock time indefinitely.

Severity stays P3 for the same reason the original refutation gave, which I re-verified: NOTHING in the tree launches brops-broker (grep over .sh/.yml/.yaml/.service/.toml/.py/.rs returns only the two Cargo.toml name lines and the binary's own eprintlns). Note the OTHER half of the original refutation is now STALE — build_governed_executor (:216-387) can serve the real LinuxGovernedTurnChain when BROPS_BROKER_CONFIG is set and the TCB floor passes, so 'even if started it denies nothing' is no longer a valid second leg. Only 'not deployed' is holding the severity down.

**Evidence.** `apps/desktop/src-tauri/broker/src/main.rs:185 (serial `for stream in listener.incoming()`), :193-199 (deadline arming), :200 (handle_conn), :458-478 (read_one_frame loop), :468 (blocking read), :216-387 (build_governed_executor now able to serve the real chain); apps/desktop/src-tauri/core/src/ipc_framing.rs:85-100 (FrameDecoder accepts declared<=8192); grep: thread::spawn only at apps/desktop/src-tauri/win-broker/src/lib.rs:202`

---

#### Windows production path (can it mint trusted_verified + production_verified=true the chain did not produce?) — PARTIALLY CLOSED

**What was attacked.** Direct answer to the single question, on the platform the Owner runs. (1) Key swap: replace keys/attest.seed or keys/signer.seed (they are provisioned as plaintext hex, win_provision.rs:26-28,88-90) to sign my own attestation/envelope. (2) Root swap: point cfg.trust.root_pub_hex / manifest / manifest.sig at my own root. (3) Demo-anchor escalation: reach ManifestResolver::with_pinned_root (the DEMONSTRATION anchor whose private seed is literally in the source at proof.rs:170) from the production driver. (4) Transport: squat all three named pipes and answer as authority/supervisor/signer. (5) Peer-SID gate: connect as a non-broker principal, or make the SID compare silently never match / match everything. (6) The desktop commit path: can the shipped app be made to write a trusted_verified row from the Windows kit? (7) Anti-rollback: forge floor.json to revive a revoked signer key.

**Why it held / where it failed.** THE FORGERY QUESTION ANSWERS NO -- the crypto boundary held against every attack I could walk. (1) fails: the manifest pins attest_pub and signer_pub, and the final acceptance verifies under keys resolved FROM that manifest (resolver.rs:267-280, iso_pub/sup_pub fed into ResolvedTurn), so a swapped seed produces signatures no one accepts. (2) fails: win_live_turn.rs:99-108 builds PinnedRoot from the compiled-in tcb::ROOT_PUBLIC_KEY_HEX (tcb.rs:28-29, 3c83c2bc...) and REFUSES a disagreeing config root (`config_root_disagrees_with_tcb`); resolver.rs:252 re-verifies per turn against that same pin; the root private is never written to the box (win_provision.rs:91-94, config root_seed=""). (3) fails: `with_pinned_root` is `pub(crate)` (resolver.rs:91) and win_live_turn is a separate bin crate, so the demo anchor is unreachable from the production driver. (4) fails as forgery: FILE_FLAG_FIRST_PIPE_INSTANCE (pipe.rs:132) does block a concurrent squatter, the client pins SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION (pipe.rs:196) so a rogue server cannot relay a broker token, and a squatter holds no private key -- every forged reply dies at the signature check. It succeeds only as DoS/hijack-position (finding W-06). (5) fails closed in both directions: pipe.rs:151-154 -- `authenticate_pipe_client_sid(h).ok()` yields None on any error and `None == Some(allowed)` is false; ConvertSidToStringSidW (win-broker/src/lib.rs:70) returns the canonical uppercase form, a user SID can never equal a group/Everyone SID, and impersonation is correctly reverted before the token is read (win-broker/src/lib.rs:98-102, RevertToSelf before `opened?`). A malformed allowed_broker_sid denies everything, it never opens. (6) fails: win_live_turn.rs:203 uses `Connection::open_in_memory()` and only PRINTS a RESULT line -- it never writes the app DB. The only shipped Windows path into brops_win_live is the DEMONSTRATION seam (commands.rs:2033 / governed_selftest.rs:118), which pins the DEMO root (proof.rs:173-176) and commits through repo.rs:1098 `post_message_demonstration_verified` into a SEPARATE `demonstration_verified_messages` table; the badge projection (repo.rs:950-959) can only render 'trusted_verified' from a `receipt_verification_attempts` row the demo path never writes, and `governed_messages` carries `CHECK (trust_state = 'trusted_verified')` reachable only from the real chain. So the demo green cannot become a production green.

WHAT DID NOT HOLD is everything BELOW the crypto. (7) succeeds by the code's own admission (tcb.rs:50-71, WINDOWS_ANTIROLLBACK_HARDENING.md:12-22) for anyone who can write the deployment dir -- and the control that was supposed to make that unreachable exists NOWHERE: grep for SetNamedSecurityInfo/SetFileSecurity/icacls across win-live and win-broker returns exactly one hit, a line of prose in a .md file. Separately, four §2.5/anti-rollback/evidence controls the ledger marks closed are Linux-only on inspection: verify_deployment_tcb has no Windows caller (only broker/src/main.rs:281 and proof/src/bin/live_turn.rs:201) and its probe is `#[cfg(target_os = "linux")]` (tcb_probe.rs:31); the per-pipe ipc-policy role matrix `authorize_pipe_peer` is never called by the live pipe server; the evidence head floor has no Windows implementation; the F-31 connection deadline has no Windows analogue. And the executor-image pin the docs call 'the guarantee that the signed output came from the exact, pinned executor image' is never compared to anything (findings W-01..W-06). So: no in-scope adversary forges a Windows production trusted_verified, and the shipped app cannot commit one -- but the Windows leg's non-cryptographic guarantees rest on an ACL no code sets and no check verifies.

**Evidence.** `win-live/src/bin/win_live_turn.rs:99-127, :145-153, :162-174, :199-206, :218-253; win-live/src/resolver.rs:79-112, :243-299; win-live/src/tcb.rs:22-71; win-live/src/pipe.rs:118-172, :179-206; win-broker/src/lib.rs:92-107; win-live/src/proof.rs:169-176, :276-288; apps/desktop/src-tauri/src/commands.rs:2033-2058; apps/desktop/src-tauri/core/src/repo.rs:950-959, :1098-1123; broker/src/tcb_probe.rs:15-17, :31; win-live/WINDOWS_ANTIROLLBACK_HARDENING.md:40-45`

---

#### F-07/F-28 — CONFIRMED CLOSED

**What was attacked.** 1) Re-ran the original F-07 exploit on paper: can an arbitrary local uid still write `<store>/<sha256hex>` to satisfy the isolated signer's presence checks? 2) Enumerated the mode and owner of EVERY directory in the deployment plus every ancestor, looking for one still world-writable. 3) Checked the group-membership timing trap explicitly — `usermod -aG` does not change the supplementary groups of a live process, so I checked whether any service is started before the groups are created. 4) Looked for a service that NEEDS an access the tightening removes (which would either break the run or force a later re-loosening). 5) Attacked the sticky-bit removal: with 1777 replaced by 2775/2770, group members can now unlink files they could not before — I chased that to a forgery, and to a socket-impersonation MITM. 6) Checked whether the broker's continued write access to the store buys it anything new.

**Why it held / where it failed.** The world-writable half of F-07/F-28 is genuinely dead. run_live_turn.sh:171-182 creates three system groups and sets `store` = root:brops-store 2775, `report` = root:brops-report 2770, `sock` = root:brops-ipc 2770 — nothing is 1777 anywhere in the kit any more (the only remaining 0777 are the socket FILES at run_signer.py:118 / run_supervisor.py:135 / run_authority.py:72, gated by the 2770 parent). Ancestors are stated rather than inherited: :217 sets $LIVE/$TCB/$BIN to 0:0 0755 and :224 sets /opt to 0:0 0755, so the whole path is root-owned and non-writable by any other principal. keys/ is 0755 root with 0400 per-service privates (:144-147); supervisor-state and recorder-state are 0700 to their own principal (:190,:195). So adversary 4 (any other unprivileged local account, including brops-executor — the account that runs model-derived content) can no longer create a blob in the store at all: the exact `echo -n <bytes> > /opt/brops-live/store/$(sha256)` primitive the original finding rests on is gone.
TIMING HOLDS: the groups are created at :176-179; the three servers start at :259-261 and the broker's turn at :271, all via `sudo -u`, which calls initgroups at exec — the new supplementary groups ARE in effect. Nothing that needs them runs earlier (:244 --verify-tcb runs as root).
NO SERVICE IS STARVED: the recorder opens the store read-only (governed_recorder.rs:125-133) and 2775 leaves world r-x; the signer reads blobs by handle on its own uid, also world r-x; the supervisor publishes blobs (run_supervisor.py:91-107) and is in brops-store; the recorder writes and the broker reads/deletes the report files (chain_executor.rs:746-754,811,834,854) and both are in brops-report.
The sticky-bit regression is real but availability-only, so it does not reopen F-07/F-28 (filed separately as F-07-B). I walked it to the end: a brops-store member deleting `store/system` makes governed_recorder.rs:132 fail -> non-zero exit -> chain_executor.rs:808 -> UpstreamBlocked; replacing any blob breaks `sha256(data)==handle` at run_signer.py:58; replacing store/system breaks the launcher's F-08 fd re-hash against the root-owned lease pins (run_live_turn.sh:131-141). Socket impersonation via the now-unlinkable sock dir yields a hop that cannot produce a valid Ed25519 signature under the manifest-resolved key (privates are 0400 to their own account, :144-146), so every route is fail-closed.
RESIDUAL, unchanged and honest: the broker (adversary 2) and the supervisor still write the store, so the signer's presence checks still do not constrain the broker — chain_executor.rs:819-848 shows the broker content-addressing its own output and containment bytes and naming those handles at :868-869. That is exactly the residual the ORIGINAL F-28 verdict already classified as by-design, so it is not a regression and not a new hole; the ledger's wording ("group-owned by exactly the principals that write it") is accurate about it. What I will not endorse is the ledger citing "4 new tests" on this row: all four are anchor tests, nothing in the tree asserts these modes, and a silent revert to 1777 would keep CI green.

**Evidence.** `engine/ci/live/run_live_turn.sh:171-184, :190, :195, :217, :224, :144-148, :259-261, :271, :131-141; engine/ci/live/run_signer.py:49-60,118; engine/ci/live/run_supervisor.py:91-107,135; apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:125-133; apps/desktop/src-tauri/broker/src/chain_executor.rs:746-754,807-848,864-883`

---

#### F-23 — CONFIRMED CLOSED

**What was attacked.** Five attacks. (1) Present a fabricated lease: tried to find any wire path that still parses a caller-supplied Lease object. (2) Choose the expiry I am judged against: looked for any caller-controlled value feeding lease_launch_gate. (3) Skip the gate entirely: sent `execution-started` directly from LEASE_READY, the exact bypass the original F-23 described. (4) Retry after a refused gate: drove an attempt to EXPIRED and then tried to move it forward. (5) Re-arm the window: replayed accept-open on an already-accepted challenge hoping for a fresh lease_expires_at_ms.

**Why it held / where it failed.** All five defeated. (1) `_parse_lease` is gone from the server entirely; `LEASE_FIELDS` (governed_supervisor_server.py:89-98) is now write-only, and `_op_launch_gate` enforces the exhaustive shape `{op, execution_attempt_id}` (server:467) so a `lease` key is a hard ServerError, not an ignored field. (2) `gate_and_start` SELECTs `lease_issued_at_ms`/`lease_expires_at_ms` from the supervisor's own acceptance row and passes those to the pure gate (ledger:534-542); `now_ms` is `clock_ms()` taken inside the server (server:470), never from the wire; the window itself was stamped `now_ms + LEASE_DURATION_MS` at acceptance from the supervisor's clock (governed_supervisor.py:606). There is no caller-controlled input to the decision at all. (3) The skip is refused: I sent execution-started from LEASE_READY and got `{'ok': False, 'reason': 'illegal_state', 'detail': 'illegal acceptance transition LEASE_READY -> EXECUTING'}` — the Python `WHERE state IN (...)` guard (ledger:454-468, LEGAL_PREDECESSORS:84-93) matches zero rows, and the SQL BEFORE-UPDATE trigger is an independent second wall in the shared DDL (supervisor_ledger.sql:103-115). So the gate is now load-bearing, not decorative: it is the only door into EXECUTION_STARTING, and complete-run/attest-run are unreachable without passing it. (4) A failed gate CASes the attempt to EXPIRED with the deterministic reason in the same transaction (ledger:545-546); EXPIRED appears as no OLD.state in the trigger's allowed-edge list, so it is genuinely terminal. (5) A replayed challenge returns the ORIGINAL persisted lease rebuilt from the row and discards the freshly-minted ids (server:439-451), keyed on the UNIQUE challenge_handle (ledger:407-415), so the window cannot be re-armed. RESIDUAL, stated honestly and reported separately at P3: the setuid launcher still does not consult the supervisor lease — it reads the root-owned key=value file at launcher/src/main.rs:424, whose own comment still says "the supervisor-signed lease that also binds turn/nonce freshness is the documented next slice". That file is root:root 0644 so no in-scope adversary can forge it, and the original audit's own P3 refutation of F-23 rested on exactly this. The AUDIT_LEDGER's F-23 claim ("launch-gate takes only {execution_attempt_id}; the caller no longer presents the lease it is judged against") is literally true and I could not break it.

**Evidence.** `engine/runtime/governed_supervisor_server.py:89-98 (LEASE_FIELDS write-only), :466-479 (_op_launch_gate, exhaustive {execution_attempt_id}), :439-451 (idempotent replay returns the original lease); engine/runtime/governed_supervisor_ledger.py:511-521 (pure gate), :524-546 (gate_and_start reads persisted window), :454-468 + :84-93 (transition guard); engine/runtime/supervisor_ledger.sql:103-115 (BEFORE-UPDATE trigger); engine/runtime/governed_supervisor.py:603-609 (window stamped from supervisor clock), :722-732 (launch_gate removed from this module); apps/desktop/src-tauri/broker/src/chain_executor.rs:315-322 (production call site sends only the attempt id); apps/desktop/src-tauri/launcher/src/main.rs:419-424 (residual: file lease, not supervisor lease)`

---

#### F-26 — CONFIRMED CLOSED

**What was attacked.** (1) Reachability: I looked for a production path to an AcceptedOutput that skips the new guard — grepped every `AcceptedOutput {` constructor in src-tauri and every BrokerContext construction. (2) Test-is-theatre: I checked whether the three negative cases would still pass with the guard deleted. (3) 'The broker chooses both sides': I traced each of the three expected_* values back to its origin to see whether the comparison is circular. (4) I checked whether the guard sits before or after any early-accept, and whether a hostile ctx could be supplied by a non-broker party.

**Why it held / where it failed.** The guard is real, reachable and load-bearing on the attempt id. verify_and_accept is the ONLY production constructor of AcceptedOutput (governed_verification.rs:361; the three other `AcceptedOutput {` sites — chain_executor.rs:1014, broker/main.rs:514, broker_orchestrator.rs:154 — are all inside `#[cfg(test)] mod tests`, confirmed at main.rs:497 and broker_orchestrator.rs:138). BrokerContext is constructed at exactly one production site, chain_executor.rs:372-384, on the single path to acceptance. The negative test (governed_verification.rs:517-551) keeps a validly-signed envelope and varies only the broker's expectation; with lines 330-335 deleted the fixture reaches Ok — proven by the sibling test matching_bindings_accept_the_exact_output (555-573) which drives the same fixture to Ok — so the `Ok(_) => panic!` arm at 546-549 would fire. Real coverage. On circularity: expected_execution_attempt_id (chain_executor.rs:383) is `lease.execution_attempt_id`, parsed at chain_executor.rs:307 from the supervisor's accept-open reply and minted by the supervisor, not the broker (Linux: governed_supervisor.py:605 `execution_attempt_id=config.mint_id()`; Windows: servers.rs:562 `EA-{now_ms}-{counter}`). The same value reaches the envelope by a disjoint route (supervisor acceptance row -> evidence_from_state -> supervisor-signed attestation -> isolated signer copies it into the payload it signs). The broker cannot move either end without breaking the signer signature (step 2, governed_verification.rs:298-299) or the supervisor attestation (step 3, 303-310), and cannot invent a lease because launch-gate is re-checked against the supervisor by attempt id alone (chain_executor.rs:315-322). The original F-26 attack — a genuinely-signed receipt from a different attempt accepted on a matching nonce + output — is dead. HONEST NARROWING (stated, not scored as a finding): only 1 of the 3 compared fields is per-turn. expected_run_id/expected_task_id (chain_executor.rs:381-382) come from ResolvedFacts, which are deployment-static config strings in every resolver (broker/main.rs:333-334 read them from config; manifest_resolver.rs:176-177 copies them per turn; win-live proof.rs:271-272 hardcodes "run-live-1"/"task-live-1"; live_turn.rs:343-344 reads config) — and they are the SAME values the broker itself put into create-pending at chain_executor.rs:279-280. So for run_id/task_id the broker does choose both sides and the check proves only that the chain carried its own label back. That is a weaker claim than the ledger's prose implies, but it removes nothing: the attempt id alone closes the finding.

**Evidence.** `governed_verification.rs:183-192 (BrokerContext fields), :324-335 (the guard), :517-551 (negative test), :555-573 (fixture reaches Ok); chain_executor.rs:307 (parse_lease of accept-open), :315-322 (launch-gate by attempt id), :355 (pinned keys), :372-384 (only BrokerContext construction), :386-395 (call); broker/main.rs:326-334 + manifest_resolver.rs:164-180 (run_id/task_id are static config); governed_supervisor.py:605-618; win-live/src/servers.rs:562-570`

---

#### F-32/F-36 — CONFIRMED CLOSED

**What was attacked.** (1) Case A of the original finding (memory): does `take(MAX_REPLY_BYTES)` actually bound the buffer, or does something buffer first? Is the cap on the reader the code actually reads from? (2) Case B (liveness): does the endpoint that accepts and then never writes and never closes still hang the Tauri command forever? (3) Is the cap applied BEFORE the bytes are resident, or is it still `recv_all` then `decode_one`? (4) Can a legal maximal frame be falsely rejected by the `>= MAX_REPLY_BYTES` check (a self-inflicted refusal)? (5) Does the per-syscall nature of SO_RCVTIMEO let a drip peer evade the deadline? (6) Are the timeouts armed before any I/O, or after send_all?

**Why it held / where it failed.** IT HELD ON BOTH FILED PATHS. governed_turn.rs:84 does `let mut limited = (&mut self.0).take(MAX_REPLY_BYTES); limited.read_to_end(&mut buf)` — the cap is on the exact reader the code reads from, and `Take::read` truncates each read, so the buffer cannot exceed 8256 bytes no matter how much the peer streams. Case A (OOM) is dead. `send_governed_turn` (broker_client.rs) still does recv_all-then-decode_one, but that ordering no longer matters because the bound now runs at the read instead of only in decode_one — which is precisely the gap the original finding identified. Case B is dead too: connect_broker sets read AND write timeouts at :54-55, immediately after connect and before send_all/recv_all, so an endpoint that accepts and then goes silent surfaces as `TransportError::Io` after 120s, which the renderer renders as blocked. No false rejection: a legal maximal reply is 4+8192 = 8196 < MAX_REPLY_BYTES = 8256 (:22), so the `>= 8256` refusal at :86-90 can only fire on a flood.

ONE RESIDUAL, NOT A REOPENING: the deadline is per-recv, so a drip endpoint can stretch the command to ~8256*119s ≈ 11 days (reported as F-32/F-36-R1, P3). That is a NEW variant, not either of the two paths F-32/F-36 filed, and it requires an adversary that already owns /run/brops/broker.sock. Nothing here can forge anything — the reply still has to survive decode_one and the renderer still cannot mint trusted_verified.

**Evidence.** `apps/desktop/src-tauri/src/governed_turn.rs:22 (MAX_REPLY_BYTES = 8192+64), :50-56 (connect then set_read_timeout/set_write_timeout before any I/O), :78-92 (take + read_to_end + >= cap refusal); apps/desktop/src-tauri/core/src/broker_client.rs send_governed_turn (encode -> send_all -> recv_all -> decode_one); apps/desktop/src-tauri/core/src/ipc_framing.rs:15 (MAX_FRAME_PAYLOAD_BYTES 8192), :48-64 (decode_one)`

---

## 3. Findings

Severity is judged strictly against the single question. A defect that cannot move the system toward a
forged `trusted_verified` is capped at P2 no matter how ugly it is. Every finding below survived an
adversarial reviewer instructed to destroy it.

| # | Sev | Title | Location |
|---|---|---|---|
| R-01 | P0 | The sign-oracle is narrowed, not removed: `complete-run` still takes the reply digest raw off t | `engine/runtime/governed_supervisor.py:848` |
| R-02 | P1 | The Windows kit still reports the four evidence values as deployment constants — F-02/F-18 is u | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| R-03 | P1 | The store-input pin is a snapshot of an unpinned inode: the broker can hand the launcher a file | `apps/desktop/src-tauri/launcher/src/main.rs:520` |
| R-04 | P1 | The attested request digests are still whatever the broker says: no runtime component ever comp | `engine/ci/live/run_live_turn.sh:122` |
| R-05 | P1 | ADJACENT (likely another agent's blocker, F-02/F-08 family): output_handle is chosen by the bro | `apps/desktop/src-tauri/broker/src/chain_executor.rs:817` |
| R-06 | P1 | The durable evidence head-floor is cleared by deleting its directory and relocated by an ungate | `engine/runtime/bro_completion.py:255` |
| R-07 | P2 | The evidence-head anti-rollback floor is keyed on `(install_id, task_id)` and the broker choose | `engine/runtime/governed_supervisor_ledger.py:645` |
| R-08 | P2 | The 'hash-linked' evidence chain is never verified and never published — no code anywhere reads | `apps/desktop/src-tauri/broker/src/chain_executor.rs:544` |
| R-09 | P2 | The four evidence values reach the signer only as the broker's self-report; the supervisor cann | `engine/runtime/governed_supervisor_ledger.py:553` |
| R-10 | P2 | The evidence-head anti-rollback/anti-fork floor is keyed on, and compares, values the broker ch | `engine/runtime/governed_supervisor_ledger.py:640` |
| R-11 | P2 | The §2.5 content pin is self-referential: the manifest is generated from the very bytes it meas | `engine/ci/live/run_live_turn.sh:210` |
| R-12 | P2 | The coverage floor is satisfied by logical NAME, not by causal role: 21 roles resolve to 14 fil | `engine/ci/live/build_tcb_pin_manifest.py:84` |
| R-13 | P2 | The head-floor mark is advanced by the very process it polices, so the ledger's own escape rout | `engine/runtime/bro_completion.py:269` |
| R-14 | P2 | BRO_OPERATOR_ROOT_PIN_SELF_OWNED is an ungated ambient env var that restores the pre-fix F-06 b | `engine/runtime/bro_signature.py:263` |
| R-15 | P2 | The acknowledged self-owned trust anchor is reported to nobody: the deployment-posture prefligh | `engine/runtime/bro_signature.py:35` |
| R-16 | P2 | Windows: the receipt's evidence-chain head and containment evidence are still unmeasured caller | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| R-17 | P2 | Windows: the pinned executor image digest is decorative — it is signed into the lease and never | `apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:162` |
| R-18 | P2 | Windows: the §2.5 TCB integrity floor is Linux-only and win_provision sets no ACL — the control | `apps/desktop/src-tauri/win-live/src/tcb.rs:60` |
| R-19 | P2 | The Windows audit verdict document asserts two facts that the code at this commit contradicts | `apps/desktop/src-tauri/win-live/proof/WINDOWS_BROKER_AUDIT_VERDICT.md:10` |
| R-20 | P3 | The supervisor lease still does not reach the setuid launcher, so one lease does not authorize  | `apps/desktop/src-tauri/launcher/src/main.rs:424` |
| R-21 | P3 | The broker names the recorder's 'private' head-sequence counter directory: the sudoers rule pla | `apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:54` |
| R-22 | P3 | A missing execution.evidence_state_dir config key silently relocates the monotonic counter to t | `apps/desktop/src-tauri/broker/src/main.rs:376` |
| R-23 | P3 | The launcher's second TCB owner is the hardcoded uid 500, so any account that happens to hold u | `apps/desktop/src-tauri/launcher/src/main.rs:395` |
| R-24 | P3 | On the Windows/Rust leg F-09 is entirely unremediated: supervisor_ledger.rs still has zero non- | `apps/desktop/src-tauri/win-live/src/servers.rs:766` |
| R-25 | P3 | The Windows supervisor twin accepts evidence counters the shared invariant forbids (zero-valued | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| R-26 | P3 | The pin manifest — the sole authority for the entire §2.5 decision — is unsigned, unpinned, and | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25` |
| R-27 | P3 | The probe's documented no-re-lookup/no-TOCTOU contract is falsified: owner/mode come from an O_ | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:74` |
| R-28 | P3 | Neither claimed 'production' caller enforces the floor for a served turn: live_turn's verify_tc | `apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35` |
| R-29 | P3 | The floor is advanced from a SECOND, independent read of the head file rather than from the hea | `engine/runtime/bro_completion.py:226` |
| R-30 | P3 | The head-floor advance is an unlocked load-compare-write over a shared temp filename, so two co | `engine/runtime/bro_completion.py:271` |
| R-31 | P3 | "external" root-anchor provenance is a string the repo-staged kit writes about itself, so a rep | `engine/ci/live/provision_keys.py:245` |
| R-32 | P3 | The F-07 remediation dropped the sticky bit while granting group write, so service accounts can | `engine/ci/live/run_live_turn.sh:180` |
| R-33 | P3 | The live-governed-turn CI job's stated pass condition no longer matches the script: it now exit | `.github/workflows/ci.yml:91` |
| R-34 | P3 | RecursionError from a 4090-byte nested-JSON frame still escapes handle_connection AND serve_for | `engine/runtime/governed_supervisor_server.py:626` |
| R-35 | P3 | The only regression test guarding the F-11 fix never reaches the code it is supposed to guard — | `engine/tests/test_governed_supervisor_server.py:310` |
| R-36 | P3 | The governed-supervisor front door has NO socket timeout at all and a serial accept loop — the  | `engine/runtime/governed_supervisor_server.py:183` |
| R-37 | P3 | The broker's per-connection deadline bounds one connection but not the service: the accept loop | `apps/desktop/src-tauri/broker/src/main.rs:185` |
| R-38 | P3 | The renderer→broker client's 120s deadline is per-recv, so a drip endpoint can hold a synchrono | `apps/desktop/src-tauri/src/governed_turn.rs:85` |
| R-39 | P3 | The F-29 'bound to the verifying key' guard is still a tautology at all three real call sites — | `apps/desktop/src-tauri/core/src/production_trust.rs:73` |
| R-40 | P3 | Windows: the F-27 remediation makes the named-pipe live driver fail closed — completed_at_ms is | `apps/desktop/src-tauri/win-live/src/servers.rs:988` |
| R-41 | P3 | Windows in-process path (the one reachable from the shipped app) still emits the zero-duration  | `apps/desktop/src-tauri/win-live/src/proof.rs:232` |
| R-42 | P3 | Windows: no evidence-head anti-rollback floor exists at all — the shared DDL's governed_evidenc | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| R-43 | P3 | Windows named-pipe servers have no read/write deadline and read the frame BEFORE peer authentic | `apps/desktop/src-tauri/win-live/src/pipe.rs:149` |
| R-44 | P3 | Windows: the pipe is destroyed and re-created between every connection, leaving a squat window, | `apps/desktop/src-tauri/win-live/src/pipe.rs:167` |
| R-45 | P3 | The Windows live kit has zero CI coverage — no job builds it, tests it, or runs any of its proo | `.github/workflows/ci.yml:130` |


### `R-01` · The sign-oracle is narrowed, not removed: `complete-run` still takes the reply digest raw off the wire, and the §5 state machine can be walked to COMPLETED with no executor ever running — so the broker uid can still obtain a signed run-attestation over bytes it authored itself

| | |
|---|---|
| **Severity** | P0 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001). Nothing stronger. No root, no ledger file write, no key theft; the whole attack is five legal protocol messages on sockets this uid is the ONLY allowlisted peer of. |
| **Location** | `engine/runtime/governed_supervisor.py:848` |
| **Group** | `f01-oracle` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** `build_run_attestation` no longer has a `facts` parameter, and the evidence is genuinely rebuilt from a durable row — but seven of the twenty-five evidence fields ENTER that row raw off the wire at `complete-run`, and the state machine that is supposed to make the row meaningful contains no proof that anything executed. `validate_completion_facts` (governed_supervisor_ledger.py:589-623) checks the FORMAT of `output_handle`, `containment_evidence_handle`, `completed_at_ms` and the four `evidence_*` counters, never their PROVENANCE; `record_completion` inserts them verbatim (ledger:731-746); `load_attestation_state` reads them back (ledger:835-843); `evidence_from_state` copies them into the object that is signed (governed_supervisor.py:848-857). Separately, `mark_executing` (ledger:490-497) flips EXECUTION_STARTING -> EXECUTING on a caller-asserted `process_group_id`/`cgroup_id` with no /proc check, no cgroup membership check, and an `execution_started_marker` that is explicitly allowed to be null (server:488-490) — its docstring says "the child is confirmed running" and nothing confirms anything. Finally every one of the five ops is admitted from the SAME single uid (server:607 `peer_is_broker(peer_uid, allowed_broker_uid)`), so the supervisor's "own" durable state is, for six of its fields, a store-and-forward of one untrusted party's assertions. The docstring at governed_supervisor.py:816-824 — "There is no parameter through which a caller can contribute a value" — is false for those six fields; the parameter is `complete-run`'s `produced`.

**Code.**
```
# ---- from the write-once completion row ----
        "output_handle": state.output_handle,
        "containment_evidence_handle": state.containment_evidence_handle,
```

**Walkthrough.**

I executed this against the real snapshot modules (harness: scratchpad/attack_f01.py; every quoted reply below is observed output, not reasoning).
STEP 0 — the broker gets a signed challenge for facts of its choosing. engine/ci/live/provision_keys.py:307-316 writes `allowed_peer_uids: [broker]` for desktop-challenge-authority, supervisor AND isolated-signer, so uid 5001 is the sole client of every hop. challenge_authority.validate_create_pending (challenge_authority.py:158-242) accepts run_id/task_id/workspace_id/install_id/request_nonce plus three digests with only shape checks and no rate limit, then recomputes request_sha256 (:340) and signs. The broker therefore holds an authentic brops.governed-turn-challenge.v1 for a turn it invented.
STEP 1 — accept-open. governed_supervisor_server.py:412-463 -> accept_open (governed_supervisor.py:519-639) verifies the signature, re-derives request_sha256, checks supervisor_id, and CASes a durable row. Observed: `{'ok': True, 'op': 'accept-open', 'lease': {...'execution_attempt_id': 'id-2', 'lease_expires_at_ms': 1700000210000...}}`. Real row, real lease, no execution yet.
STEP 2 — launch-gate. server:466-479 -> ledger.gate_and_start:524-546 judges the PERSISTED window (this is the F-23 fix and it works). Observed: `{'ok': True, 'proceed': True}`. State is now EXECUTION_STARTING.
STEP 3 — execution-started, with a pid that does not exist and a cgroup that does not exist. server:482-501 -> ledger.mark_executing:490-497. Observed with `process_group_id='999999', cgroup_id='/nonexistent', execution_started_marker=null`: `{'ok': True, 'op': 'execution-started'}`. NO recorder was spawned, NO setuid launcher ran, NO executor ran, NO model was called. State is EXECUTING.
STEP 4 — the broker authors the reply itself and puts it in the protected store. This is legitimate broker behaviour: chain_executor.rs:819-821 has the honest broker doing `sha256_hex(&output)` then `std::fs::write(&output_blob, &output)` into `store_dir`, and run_live_turn.sh:176-180 makes that directory `chgrp brops-store; chmod 2775` with brops-store = supervisor + broker. So uid 5001 writes B = b"I am the assistant reply that no model ever produced." at `<store>/3923908ad0...` and a stub containment blob beside it.
STEP 5 — complete-run with an entirely broker-authored `produced`. server:504-541 validates shape, publishes the three supervisor-DERIVED handles (which is the real F-02 improvement, and which does not help here because they are built AROUND the forged output_handle — see build_terminal_record at governed_supervisor.py:676), then ledger.record_completion:689-772 inserts `facts["output_handle"]` verbatim (ledger:739) and CASes EXECUTING -> COMPLETED. Observed: `{'ok': True, 'recorded': 'created'}`.
STEP 6 — attest-run. server:544-576 loads the terminal state and calls build_run_attestation. Observed: `ok: true`, with the signed evidence containing `"output_handle": "3923908ad00617c76a625df058fe76c65d67d884654b13f54b4cebf7a36a41b1"` — exactly sha256(B), which the harness asserted (`matches broker-authored bytes: True`). The supervisor Ed25519-signed JCS(evidence) over a reply no model produced.
STEP 7 — the isolated signer does not catch it. isolated_signer._derive_hashes:629-645 reads the store blob BY HANDLE and only checks `sha256(bytes) == handle` — true by construction, the broker wrote both. `_verify_chain_handles`:647-656 only asks whether record/lease/execution_receipt resolve — they do, the supervisor just published them. `_derive_output_bytes`:658-665 returns len(B). `_check_run_binding`:597-603 only wants decision=="completed". `_check_identity`:605-612 now passes because the supervisor supplied its own pinned identities. `_check_timestamps`:614-627 is satisfied by requested_at <= challenge_accepted <= completed_at = now. The signer mints the 23-key brops.governed-receipt-envelope.v1 and signs it.
STEP 8 — final acceptance passes. governed_verification::verify_and_accept is handed `&artifacts.output` = B (chain_executor.rs:392) and the envelope; the length+digest gate compares B against output_bytes/output_sha256 derived from B, and request_sha256 recomputes from the ids the broker chose in step 0. The turn renders trusted_verified / production_verified=true.
NET: identical terminal outcome to the original F-01 — production_verified=true over broker-authored bytes with the launcher and executor never invoked — at the cost of four extra round-trips.

**Why it matters.** This is the single question, answered yes for adversary 2. AUDIT_LEDGER.md:23 states F-01 closed because "evidence built from the supervisor's own durable terminal state" and "A fabricated run gets no_terminal_run_state". Both sentences are true and I verified them; neither establishes the property. The claim that matters — governed_supervisor.py:18 "A fabricated run has no ledger row, so it has no evidence and no signature", and supervisor_ledger.sql:32-33 "A fabricated run therefore has no acceptance row, no lease, and no completion" — assumes the broker cannot manufacture a genuine row for a run that did not happen. It can: the row costs it one challenge request and three protocol messages, and none of those touch an executor. The chain still has no measurement of execution anywhere; `trusted_verified` therefore certifies that the broker followed a protocol, not that the governed chain produced the reply. Note the material for the missing bind ALREADY EXISTS and is thrown away: the recorder's evidence chain event 3 carries `"output_sha256": sha256(&report)` over the bytes it actually captured (proof/src/bin/governed_recorder.rs:333-337), but that document is never handed to the supervisor, never content-addressed into the protected store, and never signed by the recorder — only four scalars parsed out of it by the broker reach `complete-run`. PLATFORM/SCOPE, stated plainly: the real chain is `#[cfg(target_os = "linux")]` (broker/src/main.rs:117-139), so this is the LINUX live-kit / Linux-deployment path. The shipped Windows desktop still serves UpstreamBlockedExecutor and never reaches it. It is not confined to the lab kit, however: `build_governed_executor` (main.rs:216-231) serves the real LinuxGovernedTurnChain for any Linux deployment with BROPS_BROKER_CONFIG set, and the Windows machine-proof twin has the identical shape (win-live/src/servers.rs:660-760, `let output_handle = get_str(p, "output_handle").unwrap();` at :698), so the Windows proof demonstrates the same hole. This must block any flip of platform_governed_execution_supported().

**Adversarial review (P0).** I tried five ways to kill this and failed on all five. (1) QUOTE CHECK: the quoted block appears verbatim at governed_supervisor.py:847-849 ('# ---- from the write-once completion row ----' / '"output_handle": state.output_handle,' / '"containment_evidence_handle": state.containment_evidence_handle,'). Every other cited line is accurate: mark_executing with no probe at governed_supervisor_ledger.py:490-497; validate_completion_facts format-only at :612-620 (_is_lower_sha256_hex / _is_u64_ms / _is_pos_i63 — no provenance check anywhere); raw insert of facts['output_handle'] at :739; load_attestation_state read-back at :835-843; single-uid allowlist at governed_supervisor_server.py:607. (2) IS THE ADVERSARY REAL? Yes and it is exactly the one the control names: provision_keys.py:305-316 writes allowed_peer_uids:[broker] for desktop-challenge-authority, supervisor AND isolated-signer, so uid 5001 is the sole client of every hop, and WAVE_3B_ISOLATED_SIGNER_DESIGN.md:139-149 (§1.4) states the supervisor 'never accepts a caller's evidence object' precisely to constrain that uid. This is not 'the attacker is already the trusted party' — the broker is trusted for liveness and explicitly untrusted for evidence. (3) DOES THE CHALLENGE HOP STOP IT? No. challenge_authority.validate_create_pending (challenge_authority.py:158-242) shape-checks run_id/task_id/workspace_id/install_id/request_nonce as bounded strings (:203-214) with no provenance and no rate limit, and the broker is its only allowlisted peer. (4) DOES ANY LATER STAGE CATCH IT? No. isolated_signer._derive_hashes:629-645 only asserts sha256(store bytes)==handle — a tautology when the broker wrote the blob; _verify_chain_handles:647-656 only asks whether the three supervisor-published handles resolve; _check_identity:605-612 reads identities the supervisor supplied from its own config; _check_timestamps:614-627 is satisfied by completed_at=now. (5) IS THERE MATERIAL THAT COULD HAVE BOUND IT? Confirmed thrown away: governed_recorder.rs:333-337 computes output_sha256 over the bytes it actually captured inside evidence event 3, but that document is never handed to the supervisor and is never signed by the recorder — chain_executor.rs:845-847 parses four scalars out of it and only those reach complete-run. The state machine therefore contains no measurement of execution at any hop. SCOPE CHECK: the finding's own platform caveat is accurate — main.rs:117-123 makes the real chain Linux-only and build_governed_executor (main.rs:210-231) returns UpstreamBlockedExecutor without BROPS_BROKER_CONFIG, and win-live/src/servers.rs:698 has the identical raw get_str(p,"output_handle").unwrap(). P0 stands: this is the exact property F-01 exists to establish (governed_supervisor.py:5-8 'the broker uid could therefore mint an Ed25519-signed brops.governed-receipt-envelope.v1 for a run that never happened'), the AUDIT_LEDGER marks it CLOSED, and a gate flip would rest on it. Note for the Owner: the marginal power here is forging the *cryptographic evidence*, not the UI badge — the committed row is written in-broker at governed_message_store.rs:103, so a hostile uid-5001 can already emit a fake committed frame; what F-01-R1 adds is that the forgery also survives independent receipt verification, which is the entire point of the chain.

**Reviewer re-read.** `engine/runtime/governed_supervisor.py:847-857 (quote verified verbatim), :816-824 (the false 'no parameter through which a caller can contribute a value' docstring), :861-867; engine/runtime/governed_supervisor_ledger.py:490-497, :556-559, :589-623, :731-746, :814-855; engine/runtime/governed_supervisor_server.py:482-501 (marker may be null, :488-490), :504-541, :607; engine/runtime/challenge_authority.py:158-242; engine/runtime/isolated_signer.py:597-665; engine/ci/live/provision_keys.py:305-316; engine/ci/live/run_live_turn.sh:176-181 (store 2775 group brops-store = supervisor+broker); apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:331-337; apps/desktop/src-tauri/broker/src/chain_executor.rs:815-822, :845-866; apps/desktop/src-tauri/broker/src/main.rs:117-123, :210-231; apps/desktop/src-tauri/win-live/src/servers.rs:696-700`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor.py:848` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-02` · The Windows kit still reports the four evidence values as deployment constants — F-02/F-18 is unfixed verbatim on the only platform that has ever emitted production_verified=true for the Owner, and the source comment says so while the ledger says CLOSED

| | |
|---|---|
| **Severity** | P1 |
| **Adversary needed** | 1 — the model / prompt content. No stronger adversary is needed: the defect is present on every honest run of the Windows kit. |
| **Location** | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| **Group** | `f02-evidence` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:27 states the second half of F-02 is CLOSED because 'The RECORDER now builds a hash-linked three-event chain ... A missing or malformed chain REFUSES the turn — there is no config fallback left to fall back to.' That is true only of the Linux path. The Windows twin still takes all four values from provisioning constants and reports them to complete-run, exactly as the original F-02/F-18 described. The same remediation cycle explicitly fixed BOTH supervisors for F-01 ('Fixed in both supervisors (Linux Python + the Windows proof-kit Rust twin)', AUDIT_LEDGER.md:23), so the omission is not a scoping convention — it is an unqualified closure claim over a half-done fix.

**Code.**
```
"evidence_final_event_hash": cfg.evidence_final_event_hash,
                "evidence_event_count": cfg.evidence_event_count,
                "evidence_last_sequence": cfg.evidence_last_sequence,
                "evidence_head_sequence": cfg.evidence_head_sequence,
```

**Walkthrough.**

1. win_provision.rs:112 computes the constant `let evidence_final_event_hash = crypto::sha256_hex(b"brops-final-event-v1");` and win_provision.rs:205-208 writes it plus `evidence_event_count: 3, evidence_last_sequence: 3, evidence_head_sequence: 3` into the kit config's `facts` block. The in-process proof does the same at proof.rs:147 and proof.rs:255-258. 2. win_live_turn.rs:184-193 loads `let f = &cfg.facts;` and builds `ExecutionParams { evidence_final_event_hash: f.evidence_final_event_hash.clone(), evidence_event_count: f.evidence_event_count, evidence_last_sequence: f.evidence_last_sequence, evidence_head_sequence: f.evidence_head_sequence }`. 3. execution.rs:124-138 splices those four config values into the `complete-run` `produced` block — no recorder, no chain, no --evidence-out, no counter; the Windows kit never invokes governed_recorder at all. 4. The Rust supervisor twin strict-parses them for SHAPE only (win-live/src/servers.rs:700,761-764 read them straight out of the produced payload) and stores them. 5. The anti-rollback floor is therefore vacuous: core/src/supervisor_ledger.rs:840-900 — first completion for an (install_id, task_id) hits the `row is None` bootstrap branch and inserts head_sequence=3; every later completion for the same pair presents head_sequence==3 with byte-identical event_count/last_sequence/final_event_hash, so line 880-885 takes the equal-head branch, finds the content identical, and returns FloorDecision::Idempotent — ACCEPTED, never StaleEvidence, never EvidenceFork. The floor compares a constant against itself and cannot fail, which is the precise sentence the ledger claims was fixed. 6. servers.rs:1068,1075-1077 copy the same constants into the signed 23-key envelope, and win_live_turn.rs:241-249 prints `RESULT: trusted_verified(production key=...) production_verified=true bound=true`. Every Windows receipt of the deployment names the identical evidence head, regardless of what the run did. 7. The source itself concedes this: execution.rs:27-28 reads '(Still deployment-static and tracked as audit **F-02**: the containment/record/execution-receipt handles and the four evidence counters are constants rather than measurements of this run.)' — left in place while AUDIT_LEDGER.md:27 marks the row CLOSED.

**Why it matters.** The single question is whether a receipt can carry trust_state=trusted_verified AND production_verified=true describing something the governed chain did not produce. On Windows the receipt's evidence-chain attestation carries zero information about the run: it is the same four numbers on every turn, and the anti-rollback floor that is supposed to order them is structurally incapable of refusing. This is the Owner's platform and the only one on which a production_verified=true receipt has actually been minted (win_live_turn is the production-custody proof driver). The gate-flip decision rests on AUDIT_LEDGER.md's row, and that row is not true of this platform.

**Adversarial review (P1).** I tried hard to kill this and could not. Every quoted line exists verbatim. win_provision.rs:112 does compute `let evidence_final_event_hash = crypto::sha256_hex(b"brops-final-event-v1")` and 205-208 writes it with the literal 3/3/3 counters into the kit config `facts`; proof.rs:147,255-258 does the same in-process. config.rs:98-101 carries the four fields; win_live_turn.rs:185-194 reads them out of `cfg.facts` into ExecutionParams and execution.rs:132-135 splices them verbatim into the `complete-run` `produced` block. There is no recorder, no --evidence-out, no --evidence-state and no counter anywhere under win-live (grep for governed_recorder/run-evidence-chain returns nothing outside the Linux tree). servers.rs:700,761-764 takes them straight off the wire, 848-858 puts them in the attested evidence, and 1068-1077 copies them into the 23-key envelope that win_live_turn.rs:248 reports as `production_verified=true bound=true`. The doc comment at execution.rs:27-28 still says in the shipped source that the four evidence counters are constants rather than measurements, while AUDIT_LEDGER.md:27 marks the row CLOSED with no platform qualification — and the same table row 23 shows the F-01 fix WAS carried into the Windows twin, so single-platform closure is not this ledger's convention. Attempted refutations that failed: (a) maybe the four config facts are vestigial like record/lease/execution_receipt_handle — no; those three are genuinely dead (win_provision.rs:109-111,202-204 seeds them, nothing reads them; servers.rs:744-759 derives them itself), but the four evidence values ARE read and ARE signed; (b) maybe win-live is pure lab code — it is the proof driver that has actually minted the Owner's production_verified=true receipt, and it is the artifact the gate decision is read off. ONE CORRECTION to their walkthrough, which does not save the finding: step 5 is wrong about the mechanism. core/src/supervisor_ledger.rs:840-905 (evidence_floor_cas / evidence_floor_cas_body) has ZERO production callers — a whole-snapshot grep finds it only in its own unit tests at 1327-1425. The win-live supervisor keeps acceptance state in an in-memory map (servers.rs:688,766-785) and never invokes the floor at all. So the Windows anti-rollback floor is not a tautology; it does not run. The conclusion the step supports (a constant head is never refused) is therefore true a fortiori, and the defect stands unchanged: on Windows the evidence-chain half of F-02 is unremediated verbatim, on every honest run, with no adversary required. Severity kept at P1: this is the keystone blocker itself, still open on the platform of record, mismarked CLOSED in the file the gate flip is read from.

**Reviewer re-read.** `win-live/src/bin/win_provision.rs:112,205-208; win-live/src/proof.rs:147,255-258; win-live/src/config.rs:98-101; win-live/src/bin/win_live_turn.rs:185-194,248; win-live/src/execution.rs:27-28,37-40,132-135; win-live/src/servers.rs:700,761-764,848-858,1068-1077; core/src/supervisor_ledger.rs:813,840-905 (test-only callers 1327-1425); apps/desktop/AUDIT/AUDIT_LEDGER.md:23,27`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/execution.rs:132` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-03` · The store-input pin is a snapshot of an unpinned inode: the broker can hand the launcher a file it can rewrite between the digest and the executor's read (TOCTOU), so the model runs prompt A under a receipt attesting prompt B

| | |
|---|---|
| **Severity** | P1 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001). No root, no config-write on any root-owned file, no signature forgery. This is a strictly WEAKER adversary than the original F-08 needed (that one was rated P2 precisely because it required root/config-write). |
| **Location** | `apps/desktop/src-tauri/launcher/src/main.rs:520` |
| **Group** | `f08-bytes` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The check binds a DIGEST TAKEN AT TIME T0 to the lease pin, but nothing binds the fd to a protected inode and nothing re-checks after T0. The store-input facts the launcher collects carry no device, inode, owner or mode — only "regular file, size <= 8 MiB" (main.rs:646-648), and main.rs:640 still carries the unfixed `TODO: bind st_dev to the lease's store device`. The path those fds come from (`--store`) is chosen by the caller and validated by nobody (governed_recorder.rs:73-76, 125-134; chain_executor.rs:762-764). The executor does not read the bytes until after fexecve (proof_executor.rs:49-51). Between main.rs:520 and that read the launcher performs the whole privilege drop, a /proc/self/status read, and a full open+read+SHA-256 of the multi-megabyte executor image (main.rs:457-470) — a window the writer of the inode fully controls. The comment at main.rs:511-517 claims "the bytes hashed are the bytes the executor will read from the same open file description"; the same open file description does NOT mean the same bytes, because the inode is writable by the attacker.

**Code.**
```
fn verify_store_input_bindings(lease: &Lease) -> Result<(), Refusal> {
    for (fd, pin) in store_input_pins(lease) {
        let digest = digest_fd_at_zero(fd).ok_or(Refusal::TcbIntegrity("store-input-read"))?;
        if digest != pin {
            return Err(Refusal::TcbIntegrity("store-input-digest"));
        }
    }
    Ok(())
}
```

**Walkthrough.**

Setup, all as uid 5001 (brops-verifier_broker): the driver binary is /opt/brops-live/bin/live_turn, root-owned 0755 (run_live_turn.sh:96), the sockets are in $SOCK mode 2770 group brops-ipc which contains the broker (run_live_turn.sh:178-182), and every server's peer-auth is by UID only (provision_keys.py:392-397 allowed_peer_uids: [broker uid]). So any process running as uid 5001 is 'the broker' — there is no per-process identity anywhere in the chain.
STEP 1. Copy the deployment config: `cp /opt/brops-live/config.json /tmp/e.json` (0644, world-readable — run_live_turn.sh:148). Change exactly ONE key: execution.recorder_store_dir -> /tmp/evil. Leave trust.*, resolved.*_sha256, execution.lease_file, execution.store_dir, execution.launcher_path/executor_path and sockets untouched. live_turn.rs:369 reads recorder_store_dir straight out of whatever config it is handed; live_turn.rs:222-229 takes that path from --config with no integrity check of its own (verify_deployment_tcb is a SEPARATE entry point, live_turn.rs:172-216, invoked once by root at run_live_turn.sh:244 — the run() path at live_turn.rs:218 never calls it).
STEP 2. `mkdir -m 0755 /tmp/evil` and seed it with the GENUINE bytes: `cp /opt/brops-live/store/{system,history,generation_config} /tmp/evil/` — $STORE is 2775 and its files 0644 (run_live_turn.sh:180-184), so the broker can read them. The files in /tmp/evil are owned by the broker, so the broker can write them at will.
STEP 3. Arm the race: `inotifywait -m -e access /tmp/evil/generation_config` in a background process owned by the broker. IN_ACCESS fires on read(2)/pread(2) of that inode.
STEP 4. Run the turn: `/opt/brops-live/bin/live_turn --config /tmp/e.json`. The chain proceeds normally: anchor is the genuine root-owned /opt/brops-live/tcb/root-anchor.json and passes anchor_file_is_tcb_owned (live_turn.rs:77-95, 269-271); manifest, floor and key resolution all pass (live_turn.rs:289-329); resolved.*_sha256 are the GENUINE digests (live_turn.rs:339-341).
STEP 5. chain_executor.rs:755-787 spawns `sudo -n -u brops-recorder /opt/brops-live/bin/governed_recorder --store /tmp/evil --lease /opt/brops-live/tcb/executor.lease ...`. The sudoers rule at run_live_turn.sh:199 names the command with NO arguments, which under sudo semantics permits ANY arguments; and in this path the broker does not even need that, since it is the process building the argv.
STEP 6. governed_recorder.rs:125-131 does `open("/tmp/evil/system", O_RDONLY)` etc., dup2's them to 3/4/5 (162-170), clears FD_CLOEXEC (177-182), and execve's the setuid launcher (189-193).
STEP 7. launcher main.rs:434-435 collect_fd_facts + verify_launcher_fd_set: /tmp/evil/system is a regular file <= 8 MiB, O_RDONLY, offset 0 -> is_regular_store_inode = true (main.rs:646-648), so fd_lifecycle.rs:90-97 accepts it. There is NO device/inode/owner/mode check.
STEP 8. main.rs:444 -> 518-524 digests fd 3, then fd 4, then fd 5 in that fixed order. All three currently hold the GENUINE bytes, so all three equal the lease pins written at run_live_turn.sh:131-140. The gate passes.
STEP 9. The pread of fd 5 (main.rs:537-544) fires IN_ACCESS on /tmp/evil/generation_config. The attacker's watcher wakes and, since fds 3 and 4 are provably already digested, immediately truncates and rewrites /tmp/evil/system in place with an arbitrary attacker prompt. Same inode, same open file description, so the write is visible through fd 3.
STEP 10. The launcher, with no re-check, runs verify_order (447), sets CLOEXEC on stdio (451-453), drops privilege (457), parses /proc/self/status and verifies the final state (461-463), opens+fstats+read_to_end+SHA-256s the whole executor image (469 -> 757-801), and fexecve's (470). Every one of those steps is after the last read of fd 3.
STEP 11. proof_executor.rs:49-51 read_fd(3) -> read_to_end from offset 0 -> the ATTACKER'S bytes. It computes reply_binding over what it actually read (125-130) and writes its report to fd 6 (61-64).
STEP 12. chain_executor.rs:811-827 captures the output, content-addresses it; complete-run/attest-run (864-894) succeed; isolated_signer.py:629-645 derives system_sha256 from store/<handle> where handle is the GENUINE resolved.system_sha256 (whose blob provision_keys.py:288 wrote) and recomputes request_sha256 over the GENUINE digests (isolated_signer.py:667-686); governed_verification's verify_and_accept recomputes the same value from the broker's Expected (chain_executor.rs:359-367) and agrees. Result: a committed message, trust_state = trusted_verified (live_turn.rs:427), and with an externally-anchored root (the configuration the ledger and NEXT_CHAT treat as the production case) production_verified = true (live_turn.rs:443-444).
NET: the receipt attests request_sha256 over the genuine system prompt; the model was fed the attacker's system prompt. Nothing in the chain compares the executor's own reply_binding to the attested handles — repo-wide grep for `reply_binding` returns only proof_executor.rs.

**Why it matters.** This is the exact property AUDIT_LEDGER.md:28 claims closed — "the launcher re-hashes the HELD fds 3/4/5 against those pins ... Overwriting <recorder_store_dir>/system after provisioning now refuses the launch instead of running prompt A under a receipt attesting prompt B." The refusal is real only for the ONE pinned inode; the guard has no inode identity, so the same outcome is reproduced through a different inode by a weaker adversary than the original finding required. Against the single question: the desktop commits trusted_verified / production_verified=true for a governed request the chain did not actually execute — the signature is genuine, the bound request is a lie. A failed race costs the attacker nothing (fail-closed refusal, retry next turn), so it is repeatable until it wins, and with inotify IN_ACCESS on the third input it is deterministic rather than probabilistic.

**Adversarial review (P1).** I could not refute it, and the preconditions are weaker than the finding claims. The quoted verify_store_input_bindings is verbatim in the file (main.rs:518-526). The guard binds a digest taken at T0 to the lease pin, and NOTHING binds the fd to a protected inode: collect_fd_facts derives is_regular_store_inode from st_mode/st_size only (main.rs:642-648) and the 'TODO: bind st_dev to the lease's store device' at main.rs:640 is unfixed; fd_lifecycle.rs:88-97 checks only read_only && is_regular_store_inode && offset_zero. After main.rs:444 the launcher performs verify_order, three fcntl pairs, the whole privilege drop (setgroups/setresgid/64x PR_CAPBSET_DROP/setresuid/capset/no_new_privs, main.rs:687-721), a /proc/self/status read+parse+verify (461-463), and an open+fstat+read_to_end+SHA-256 of the multi-MB executor image (469 -> 757-801) before fexecve at 470; the executor only then read_to_end's fd 3 (proof_executor.rs:49-51,88-96). That is a multi-millisecond window under the writer's control, and pread leaves offset 0 so the executor still starts at byte 0 on the ATTACKER's bytes. Refutation attempts that failed: (1) no post-T0 re-check exists anywhere; (2) the executor DOES compute a digest of what it actually read (proof_executor.rs:125-130) but repo-wide grep shows `reply_binding` occurs only in proof_executor.rs — nothing compares it to the attested handles; (3) the recorder's containment report carries executor/launcher/lease digests but NOT the store-input digests (governed_recorder.rs:264-279); (4) `--store` is unvalidated (governed_recorder.rs:73-76,125-131), comes from cfg.recorder_store_dir (chain_executor.rs:762-764 <- live_turn.rs:369), and live_turn::run never invokes the TCB floor (verify_tcb is a separate --verify-tcb entry, live_turn.rs:35-36,172-216, called once by root at run_live_turn.sh:244); (5) the sudoers rule names the command with no arguments (run_live_turn.sh:199), so any argv is permitted. The finding is if anything UNDERSTATED: $STORE is mode 2775 group brops-store with the broker a member and NO sticky bit (run_live_turn.sh:176,180-184), so the broker can unlink the root-owned $STORE/system and re-create it as a broker-owned inode seeded with the genuine bytes — the race then runs against the stock /opt/brops-live/config.json with no config swap at all. Adversary is #2 exactly as claimed, weaker than the original F-08's root/config-write. P1 (not P0): the signature and the acceptance predicate are not broken and the executor image is still pinned; what breaks is the request binding — the model consumes attacker bytes under a receipt attesting the genuine prompt. Scope note: LINUX live kit only; the shipped Windows desktop keeps UpstreamBlockedExecutor and platform_governed_execution_supported()==false, and the launcher's real path is #[cfg(target_os = "linux")] (main.rs:359-364).

**Reviewer re-read.** `apps/desktop/src-tauri/launcher/src/main.rs:404-472 (ordering 444 digest -> 457 drop -> 469 image hash -> 470 fexecve), 518-526 (quote verified verbatim), 530-559 (pread loop), 640 (unfixed st_dev TODO), 642-648 (facts carry no dev/ino/uid/mode); apps/desktop/src-tauri/core/src/fd_lifecycle.rs:88-97; apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:73-76, 125-134, 162-175; apps/desktop/src-tauri/proof/src/bin/proof_executor.rs:49-51, 88-96, 125-130; apps/desktop/src-tauri/broker/src/chain_executor.rs:755-787; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35-36, 172-216, 218-229, 369; engine/ci/live/run_live_turn.sh:176-184 (STORE 2775, no sticky), 199 (sudoers, no arg restriction), 244 (--verify-tcb is root, deploy-time), 258-262 (driver runs as the broker account); repo-wide grep: `reply_binding` occurs only in proof_executor.rs (5 hits, all local).`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/launcher/src/main.rs:520` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-04` · The attested request digests are still whatever the broker says: no runtime component ever compares the root-owned lease pins to the digests the receipt attests — that equality is asserted only by a deploy-time shell check

| | |
|---|---|
| **Severity** | P1 |
| **Adversary needed** | 2 — the broker service account (uid 5001). It needs only (a) to run the driver with its own config and (b) group-write on $STORE, which run_live_turn.sh:176/180 grants it (brops-store = supervisor + broker, dir 2775) and which chain_executor.rs:819-827 already exercises in normal operation. |
| **Location** | `engine/ci/live/run_live_turn.sh:122` |
| **Group** | `f08-bytes` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** This is the ONLY place in the codebase where 'the launcher's pin' and 'the digest the receipt attests' are compared. It is a shell step, run once by root at provisioning, against one specific file ($LIVE/config.json). At turn time the two values travel completely separate paths that never meet: the executed side is pinned by the lease FILE (launcher main.rs:518-526), while the attested side is read from whatever config the broker process loaded (live_turn.rs:339-341), signed as-is by the challenge authority (challenge_authority.py:215-224 checks only 64-hex shape), stored verbatim by the supervisor (governed_supervisor.py:632-634), and 'derived' tautologically by the signer from store/<handle> (isolated_signer.py:634-645 — sha256(bytes)==handle is true by construction for a content-addressed store). The supervisor's own minted lease carries launcher_executable_sha256 and executor_executable_sha256 (governed_supervisor.py:604-607) but NOT the three request digests, so even the supervisor cannot cross-check them.

**Code.**
```
# The config the supervisor attests from MUST carry the same three digests, or the launcher would be
# pinning bytes nobody attests. Assert it here rather than discovering the divergence in a signature.
python3 - "$CONFIG" "$SYSTEM_SHA" "$HISTORY_SHA" "$GENCFG_SHA" <<'PYCHECK' || { echo "FAIL: request digests diverge from the provisioned store bytes"; exit 1; }
```

**Walkthrough.**

STEP 1. As uid 5001: `cp /opt/brops-live/config.json /tmp/e.json` and set resolved.system_sha256 = sha256(<any bytes the attacker likes>). Everything else, including execution.lease_file and execution.recorder_store_dir, stays genuine.
STEP 2. Place the matching blob so the signer can dereference it: `printf '<those bytes>' > /opt/brops-live/store/<that digest>`. $STORE is 2775 group brops-store and the broker is in that group (run_live_turn.sh:176,180); run_signer.py:49-60 FileArtifactStore.read_verified accepts any file whose bytes hash to its own name, and the broker already writes blobs there every turn (chain_executor.rs:819-827).
STEP 3. `/opt/brops-live/bin/live_turn --config /tmp/e.json`. live_turn.rs:339 loads the fabricated system_sha256 into ResolvedTurn. chain_executor.rs:284 sends it to create-pending; challenge_authority.py:216-224 validates only that it is 64 hex characters and signs the challenge over it.
STEP 4. governed_supervisor.py:494-496 re-checks only the hex shape; 632-634 persists it as system_handle. accept_open issues the lease.
STEP 5. Execution runs against the GENUINE store: recorder opens /opt/brops-live/store/system (governed_recorder.rs:126), launcher digests it against the GENUINE lease pin (main.rs:520 vs run_live_turn.sh:137) — MATCH, so the launcher is perfectly satisfied and the executor consumes the genuine prompt.
STEP 6. isolated_signer.py:634-645 reads store/<fabricated handle>, finds the attacker's blob, and digest==handle holds tautologically; 677-684 recomputes request_sha256 over the FABRICATED digest.
STEP 7. chain_executor.rs:359-367 builds Expected from the same fabricated config values, so verify_and_accept's independent recompute agrees. Committed: trusted_verified (live_turn.rs:427), production_verified=true under an external anchor (live_turn.rs:443-444).
NET: the executor consumed the genuine governed prompt; the signed receipt attests a request whose system component is bytes the chain never executed, and an auditor dereferencing system_handle in the protected store gets the attacker's blob. No race, no timing, no root.

**Why it matters.** AUDIT_LEDGER.md:28 states the closure as "run_live_turn.sh derives the pins from the provisioned store bytes and asserts they equal the resolved.*_sha256 the supervisor attests from, so launcher pin = executed bytes = attested digest." That is a DEPLOYMENT-TIME assertion in a shell script presented as a per-turn invariant. The original F-08 sentence — "The attested thing (a prompt digest) and the executed thing (the fd 3/4/5 bytes) are two independent paths with no enforced equality anywhere in the codebase" — is still literally true at runtime; the launcher added a third path (lease pins) and joined it to the executed bytes, leaving the attested path exactly as free as before. Against the single question, this again yields trusted_verified / production_verified=true whose request binding names something the governed chain did not produce.

**Adversarial review (P1).** Survives. The quoted PYCHECK is verbatim at engine/ci/live/run_live_turn.sh:120-130 and is genuinely the ONLY comparison of a lease pin to an attested digest anywhere in the tree; it is a root-run provisioning step against one file. I walked the runtime path end to end and every hop takes the digest on faith: live_turn.rs:339-341 lifts resolved.{system,history,generation_config}_sha256 out of whatever --config was handed to run() (222-229, no integrity check, and run() never calls verify_deployment_tcb); chain_executor.rs:284-286 puts them in create-pending; challenge_authority.py:217-224 validates only _is_sha256_hex and then the authority SIGNS the challenge over them; governed_supervisor.py:494-496 re-checks only hex shape and 631-634 persists them verbatim as system_handle/history_handle/generation_config_handle; isolated_signer.py:148-155 + 629-645 'derives' the hashes by reading store/<handle> and asserting sha256(bytes)==handle, which is true by construction for a content-addressed store — so the module docstring's 'No caller-supplied hash is ever trusted' is a tautology, not a check; 667-686 then recomputes request_sha256 over those derived values, and chain_executor.rs:359-367 builds Expected from the same config values so verify_and_accept's 'independent' recompute agrees with itself. The blob-placement step is real: run_signer.py:39-60 FileArtifactStore.read_verified accepts any file in cfg['store_dir'] whose bytes hash to its own name, that directory is $STORE at 2775 group brops-store with the broker a member (run_live_turn.sh:176,180), and chain_executor.rs:819-827 already writes blobs there every turn. I checked the two plausible refutations and both fail: the supervisor's minted lease carries launcher_executable_sha256/executor_executable_sha256 from its OWN provisioning (provision_keys.py 'supervisor' block) but NOT the three request digests, so it cannot cross-check them; and the launcher's lease is a completely separate root-owned FILE (main.rs:478-509) that no supervisor/signer code ever reads. This is NOT the excluded 'attacker is already the trusted party' case: the design explicitly spends F-01/F-26/F-29 removing broker-chosen values from the signed evidence, and the signer's derivation is documented as the defence — it just is not one. P1 rather than P0 because the executed prompt stays genuine and no signature is forged; what is forged is the semantic content of a production_verified receipt (an auditor dereferencing system_handle in the protected store gets the attacker's blob). Linux live kit only.

**Reviewer re-read.** `engine/ci/live/run_live_turn.sh:120-130 (quote verified; deploy-time PYCHECK, the sole pin-vs-attested comparison), 176-184 ($STORE 2775 brops-store incl. broker), 258-262 (driver executed as brops-verifier_broker, $BIN 0755 world-traversable); apps/desktop/src-tauri/proof/src/bin/live_turn.rs:218-229, 339-341, 427, 443-444; apps/desktop/src-tauri/broker/src/chain_executor.rs:284-286, 359-367, 819-827; engine/runtime/challenge_authority.py:217-224; engine/runtime/governed_supervisor.py:494-496, 631-634; engine/runtime/isolated_signer.py:148-155, 629-645, 667-686; engine/ci/live/run_signer.py:39-60; engine/ci/live/provision_keys.py:283-291 (named file AND content-addressed blob written separately), 336 (top-level store_dir == $STORE); apps/desktop/AUDIT/AUDIT_LEDGER.md:28 (the 'launcher pin = executed bytes = attested digest' claim).`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/ci/live/run_live_turn.sh:122` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-05` · ADJACENT (likely another agent's blocker, F-02/F-08 family): output_handle is chosen by the broker, so a compromised broker can obtain trusted_verified over reply bytes the executor never produced

| | |
|---|---|
| **Severity** | P1 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001). Nothing stronger. |
| **Location** | `apps/desktop/src-tauri/broker/src/chain_executor.rs:817` |
| **Group** | `f09-cas` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The bytes that become the governed reply are read from a file by the broker, content-addressed by the broker, written into the protected store by the broker, and named to the supervisor by the broker. Every downstream check dereferences that same broker-written blob, so each one is tautological. Nothing anywhere compares the store blob to anything the executor or the recorder cryptographically vouched for. I am reporting this because it is the reason F09-1's floor finding matters, and because it is the direct answer to this audit's single question — but the blocker that owns it is F-08 (request<->output binding) / F-02-F-18 (evidence facts), not F-09. Treat as a cross-check, not a claim of new territory.

**Code.**
```
let output_handle = sha256_hex(&output);
            let output_blob = format!("{}/{}", cfg.store_dir, output_handle);
            std::fs::write(&output_blob, &output).map_err(|_| TurnReason::UpstreamBlocked)?;
```

**Walkthrough.**

STEP 1 — the broker owns the bytes. chain_executor.rs:811 reads the recorder's report file into `output`; :817-820 hashes it and writes `<store>/<sha256>`. The broker also deletes the report/containment/evidence files before the run (chain_executor.rs:752-754) and is a member of the brops-report group with write on that 2770 directory (run_live_turn.sh:177, 181), so it can equally supply those bytes itself — or skip the recorder entirely and call complete-run directly, since it is arbitrary code at uid 5001.

STEP 2 — the supervisor accepts the handle on faith. complete-run's `produced.output_handle` (chain_executor.rs:871) reaches ledger.validate_completion_facts, which checks only `_is_lower_sha256_hex` (engine/runtime/governed_supervisor_ledger.py:612-614). The supervisor never reads the blob and cannot: the store is 2775 brops-store and the supervisor can read it, but there is nothing to compare it against — the supervisor never saw the executor's output.

STEP 3 — the handle flows into the signature. record_completion persists it (governed_supervisor_ledger.py:739), load_attestation_state returns it (:835), evidence_from_state copies it (engine/runtime/governed_supervisor.py:848), and build_run_attestation Ed25519-signs JCS(evidence) over it (:918-919).

STEP 4 — the isolated signer's check is circular. _derive_hashes reads `store/<output_handle>` and asserts sha256(bytes) == handle (engine/runtime/isolated_signer.py:634-645); for a content-addressed store that is true by construction for ANY bytes the broker wrote. _derive_output_bytes just returns len() of the same blob (:657-663). _recompute_request_sha256 (:667-689) binds workspace/install/nonce and the three INPUT component hashes — not the output.

STEP 5 — the one artifact that could have bound it is inert. proof_executor.rs:52-59 computes a `reply_binding` over the fd 3/4/5 digests and embeds it in its report (proof_executor.rs:138-144). Repo-wide grep for `reply_binding` across .rs and .py returns ONLY those four lines in proof_executor.rs. No consumer exists.

STEP 6 — final acceptance is self-comparison. governed_verification::verify_and_accept judges against the broker's OWN Expected facts, which for a compromised broker are values it supplied to itself.

WRONG OUTPUT: a broker that obtains one legitimate signed challenge (freely available from the authority — it chooses all the turn facts) can walk accept-open -> launch-gate -> execution-started (process_group_id is an arbitrary string, governed_supervisor_server.py:492-497) -> complete-run naming a blob of its own composition -> attest-run -> sign-result, and the chain emits a trusted_verified receipt over text the governed executor never produced.

REFUTATION ATTEMPTS: (a) F-08's remediation — the setuid launcher's pread re-hash of held fds 3/4/5 against the lease pins — binds the three INPUTS (system/history/generation_config), not the output; run_live_turn.sh:131-140 writes only `system_sha256`/`history_sha256`/`generation_config_sha256` into the lease. (b) The signer's containment gate — isolated_signer.py:638-639 only converts a MISSING containment blob into a typed refusal; it never inspects the content. (c) The F-02 fix that moved record/lease/execution-receipt handles to supervisor-derived — real, and it does close those three, but output_handle and containment_evidence_handle are explicitly left in COMPLETION_HANDLE_FIELDS as caller-reported (governed_supervisor_ledger.py:556-559).

**Why it matters.** This is the affirmative answer to the single question on the live Linux kit: yes, adversary #2 can obtain trusted_verified over content the governed chain did not produce. It also explains why F09-1 matters and why the F-09 floor cannot be counted as a compensating control — an adversary that can choose the reply bytes has no need to replay an old evidence head, and would not be stopped by a floor that worked. Scope note per the brief: the SHIPPED desktop is not exposed today (brops-broker returns UpstreamBlockedExecutor without BROPS_BROKER_CONFIG, broker/src/main.rs:226-231; win-broker/src/lib.rs:10 keeps platform_governed_execution_supported() false), so this is a gate-flip blocker, not a live exploit against the current build. I flag it for the orchestrator to route to whoever owns F-02/F-08/F-18 rather than claiming it as an F-09 finding.

**Adversarial review (P1).** SURVIVES. I attacked this hardest because it is the P1 and because it is the direct answer to the audit's single question. Every step verified.

QUOTE CHECK: `let output_handle = sha256_hex(&output); let output_blob = format!("{}/{}", cfg.store_dir, output_handle); std::fs::write(&output_blob, &output)...` is verbatim in chain_executor.rs in the (2) content-address block. Real.

STEP 1 — CONFIRMED. chain_executor.rs reads the recorder's report with std::fs::read(&report_path), hashes it, and writes <store>/<sha256> itself. It also `remove_file`s report/containment/evidence before the run. run_live_turn.sh puts BROKER_USER in brops-report (2770) and brops-store (2775), so the broker can both clear and supply those bytes.

STEP 2 — CONFIRMED. produced.output_handle reaches validate_completion_facts, which applies `_is_lower_sha256_hex` and nothing else (governed_supervisor_ledger.py:612-614). The supervisor never dereferences it and has no independent copy of the executor's output to compare against.

STEP 3 — CONFIRMED. record_completion persists output_handle (governed_supervisor_ledger.py:739); load_attestation_state returns it; build_run_attestation Ed25519-signs JCS(evidence) over it.

STEP 4 — CONFIRMED AND THIS IS THE CORE. isolated_signer._derive_hashes reads store/<handle> via read_verified and asserts sha256(bytes) == handle (isolated_signer.py:628-645). For a content-addressed store that is true by construction for ANY bytes the broker wrote — it proves the handle addresses the blob, never that the blob is what the governed executor emitted. _derive_output_bytes returns len() of the same blob (:657-663). _recompute_request_sha256 binds workspace/install/nonce + the three INPUT digests (:667-689) — the request side only.

STEP 5 — CONFIRMED. I ran the grep: `reply_binding` appears at proof_executor.rs:52, :59, :138, :141, :144 and NOWHERE else in any .rs or .py file. The one artifact that computes an input->output binding has zero consumers. Separately, the recorder's evidence chain DOES carry output_sha256 in its 'output-captured' event (governed_recorder.rs:333-337) — but that document is unsigned and the supervisor never reads it (see F09-1), so it binds nothing either.

STEP 6 — CONFIRMED. governed_verification::verify_and_accept judges envelope.workspace_id/install_id/request_nonce/request_sha256 against `expected` (:314-322) and run_id/task_id/execution_attempt_id against `ctx.expected_*` (:330-335), and re-digests `output` (:339-344) — all of which are the broker's own values inside the broker's own process.

MY ADDITIONAL REFUTATION ATTEMPTS: (a) I checked whether the launcher's F-08 pread re-hash could cover the output — it pins system/history/generation_config only; run_live_turn.sh writes exactly those three into the root-owned lease. (b) I checked whether the containment gate inspects content — isolated_signer.py:638-639 converts only a MISSING containment blob into REASON_CONTAINMENT_MISSING. (c) I checked whether execution-started constrains anything — mark_executing stores process_group_id/cgroup_id as opaque strings with no liveness or ownership check (governed_supervisor_ledger.py:490-497; governed_supervisor_server.py:482-501), so the broker can reach EXECUTING without a real recorder child.

CALIBRATION I AM ADDING (the finding does not state it, and it matters): broker_orchestrator::run_governed_turn — including persist_committed, which writes the trust_state='trusted_verified' row — executes INSIDE the broker service process (broker_orchestrator.rs:5-10, :118-131). So a compromised broker does not need any of this to make the local DB row say trusted_verified. The incremental power of ADJ-1 is over the CRYPTOGRAPHIC receipt: it means the supervisor attestation and the isolated-signer envelope — the artifacts an external auditor would hold, produced under two uids the broker does not control — attest an output digest that nothing ties to the governed executor. That is the property the three-uid separation exists to provide, so this is not 'the attacker is the party the control protects against'.

P1 UPHELD. Adversary #2 only, no root. Correctly self-scoped: not exploitable against today's shipped build (broker/src/main.rs:226-231 fail-closed; win-broker/src/lib.rs:10 gate false), so it is a gate-flip blocker. Correctly routed away from F-09 to F-02/F-08/F-18 — I agree it is not F-09 territory and should not be scored against this blocker.

**Reviewer re-read.** `apps/desktop/src-tauri/broker/src/chain_executor.rs (quote verified in the (2) content-address block; report/containment/evidence remove_file before the run; produced.output_handle in the complete-run json); engine/runtime/governed_supervisor_ledger.py:612-614 (shape-only), :739 (persisted), :490-497 (opaque process_group_id); engine/runtime/governed_supervisor_server.py:482-501 (no liveness check); engine/runtime/isolated_signer.py:628-645 (_derive_hashes tautology), :657-663, :667-689 (request side only), :638-639 (containment presence only); apps/desktop/src-tauri/proof/src/bin/proof_executor.rs:52,59,138,141,144 (reply_binding — repo-wide grep returns only these five lines); apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:333-337 (output_sha256 in an UNSIGNED chain the supervisor cannot read); apps/desktop/src-tauri/core/src/governed_verification.rs:314-322,330-335,339-344 (compared against broker-owned Expected/ctx/output); apps/desktop/src-tauri/core/src/broker_orchestrator.rs:5-10,118-131 (the trusted_verified commit itself runs in the broker process — my added calibration); engine/ci/live/run_live_turn.sh (broker in brops-store 2775 and brops-report 2770)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/chain_executor.rs:817` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-06` · The durable evidence head-floor is cleared by deleting its directory and relocated by an ungated environment variable, so the L-4 anti-rollback the ledger marks CLOSED is defeated by the same capability the original F-13/F-14 attack already required

| | |
|---|---|
| **Severity** | P1 |
| **Adversary needed** | 3 — the interactive login user (anyone who can write the external evidence store directory or set the Stop gate's environment). Nothing stronger is needed: no root, no forged signature, no key. Adversary 1 (the model) plausibly cannot reach it because bro_security refuses absolute-path mutations for governed tools and .claude/** is in engine/config/protected-control-plane.json:16 — I did not re-verify that wall, so I do not claim adversary 1. |
| **Location** | `engine/runtime/bro_completion.py:255` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The mark that is supposed to outlive the call shares both its NAME and its PRINCIPAL with the artifact it polices. _head_floor_dir (:243-245) returns BRO_EVIDENCE_HEAD_FLOOR when that ambient env var is set — validated only as absolute-and-outside-the-repo by _external_dir (:168-180), with no CI gate, no ownership check and no mode check, and overriding even an explicitly passed store — and otherwise <store>/head-floor, where <store> is itself BRO_EVIDENCE_STORE (:208). A missing mark reads as 0, i.e. 'no floor', and 0 is then passed as None (:222), disabling the staleness comparison at bro_evidence.py:112 entirely. The docstring at :249-253 promises a damaged record 'is NOT treated as absent'; deletion is absence, and deletion is not a weaker capability than the truncation the shipped test covers (test_evidence_chain.py:341-349).

**Code.**
```
path = _head_floor_dir(store) / f"{task_id}.floor.json"
    if not path.exists():
        return 0
```

**Walkthrough.**

I ran this end-to-end against the snapshot's own fixture (engine/tests/test_evidence_chain.py CompletionIntegrationTests), so every event, head and signature is genuinely recorder-signed and no forgery is involved. STEP 1 — establish the mark: reseal the task head at head_sequence=5 and call the real bro_completion.validate_evidence_chain (bro_completion.py:183). It verifies (bro_evidence.py:122-171) and _advance_head_floor writes <store>/head-floor/task-1.floor.json with head_sequence 5 (bro_completion.py:226-227, :269-286). STEP 2 — confirm the shipped property: re-present the genuine, older head_sequence=1 with its matching prefix. _load_head_floor returns 5 (:248-266), validate_chain gets min_head_sequence=5, and bro_evidence.py:112-116 refuses: 'evidence head is stale: head_sequence 1 is below the required high-water mark 5'. The fix works — until the mark is touched. STEP 3a — CLEAR IT: shutil.rmtree(<store>/head-floor). This is the same directory the attacker already had to write to place the retained head at <store>/task-1.head.json, which is the premise of F-13/F-14. Re-present head 1: _load_head_floor hits 'not path.exists()' at :255 and returns 0; :218 sets floor=0; :222 passes 'floor or None' = None; bro_evidence.py:112 is skipped; the rolled-back, self-consistent chain VERIFIES. Observed: digest 885c905f38b41ff0 returned, no error. The Stop gate at bro_hook.py:194 therefore emits 'completion and verification evidence GREEN' for a history with tests-failed and rolled-back removed — the exact original F-14 outcome. STEP 3b — RELOCATE IT instead: leave the mark intact and set BRO_EVIDENCE_HEAD_FLOOR=/a/fresh/empty/dir. _head_floor_dir (:243-244) returns it, _load_head_floor finds nothing, floor=0, same acceptance. Observed: same digest 885c905f38b41ff0. STEP 3c — or point BRO_EVIDENCE_STORE at a prepared directory: the default mark lives inside the store (:245) so it travels with it; _load_head_floor on any other directory returns 0, which I measured directly. At no point does anything check who owns the store, who owns head-floor/, or who set the variable.

**Why it matters.** AUDIT_LEDGER.md:33 marks F-06/F-13/F-14 'CLOSED (2026-08-06)' and asserts 'A retained older-but-genuinely-signed head re-presented on a later call is now refused; a damaged mark refuses rather than reading as absent.' The first clause is true only while nobody removes one directory; the second is true for truncation and false for deletion. bro_completion.py:202-205 and bro_evidence.py:24-29 still state the property in the present tense as enforced, and the in-code TODO(L-4) that made the original auditor rate this P2 rather than P1 has been deleted — the honest disclosure was replaced by a claim. This row is on the keystone list that platform_governed_execution_supported() cannot be flipped without (AUDIT_LEDGER.md:18-19), so a false CLOSED here directly buys a gate flip the evidence does not support.

**Adversarial review (P1).** I tried hard to kill this and could not. Quote is exact: bro_completion.py:254-256 really is `path = _head_floor_dir(store) / f"{task_id}.floor.json" / if not path.exists(): return 0`, and :218/:222 really do turn 0 into `floor or None` = None, which makes bro_evidence.py:112 (`if min_head_sequence is not None and ...`) a no-op. Refutation attempts that FAILED: (a) I looked for a caller-supplied floor that would survive a cleared mark - grep shows every production caller passes None (bro_completion.py:386-387, :462-464; bro_orchestration_runtime.py:725-728 omits the kwarg), so `max(min_head_sequence, durable_floor)` never rescues it; (b) I looked for any ownership/integrity guard on the store or on head-floor/ - bro_deploy_preflight.check_ledgers (:107-120) validates only absolute-and-outside-repo for BRO_EVIDENCE_STORE, and BRO_EVIDENCE_HEAD_FLOOR is not even in LEDGER_VARS (:49-56); _external_dir (bro_completion.py:168-180) likewise checks only absolute+outside-repo, no owner, no mode, no CI gate; (c) I checked whether the shipped test already covers deletion - test_evidence_chain.py:341-349 only does `write_text("{")`, i.e. truncation. I then EXECUTED it against an isolated copy of the snapshot's own fixture (no snapshot mutation): baseline refused the rolled-back head, then rmtree of head-floor/, unlink of the single .floor.json, and BRO_EVIDENCE_HEAD_FLOOR pointed at a fresh empty dir EACH accepted the genuine older head with digest 885c905f... The finding slightly overstates one clause - the :249-253 docstring promises refusal for a *corrupt* record, not for a missing one, and bro_completion.py:240-241 does disclose 'whoever can write the store can also clear the mark' - but the AUDIT_LEDGER row states the property unconditionally and the env-redirect vector (:243-244) is presented purely as hardening while being an equally ungated rollback lever, which is not disclosed anywhere. Severity held at P1: no adversary downgrade is warranted (deleting head-floor/ is the same capability, in the same directory, that placing the retained head already requires - adversary 3, arguably adversary 2), the control is the entire substance of a keystone ledger row, and the shipped test pins only the weaker capability. I do bound the blast radius: this defeats the ENGINE Stop gate (bro_hook.py:194 authorize_stop), not the desktop's Rust production_verified path, which uses a serialized CAS in the signer's own DB (supervisor_ledger.rs:813-891). It is a false CLOSED that feeds the flip, not a direct forge of production_verified.

**Reviewer re-read.** `bro_completion.py:254-256, :217-222, :243-245, :168-180, :386-387, :462-464; bro_evidence.py:112-116; bro_deploy_preflight.py:49-56, :107-120; test_evidence_chain.py:341-349; bro_hook.py:194. Executed in an isolated copy: [baseline] refused 'evidence head is stale: head_sequence 1 is below the required high-water mark 5'; [rmtree] ACCEPTED 885c905f38b41ff0...; [unlink] ACCEPTED 885c905f38b41ff0...; [env-redirect] ACCEPTED 885c905f38b41ff0... with the original mark still reading head_sequence 5.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_completion.py:255` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-07` · The evidence-head anti-rollback floor is keyed on `(install_id, task_id)` and the broker chooses `task_id`, so a fresh task_id always bootstraps the floor to whatever head the caller names

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 2 — the broker service account (uid 5001), using only the challenge it is entitled to request. |
| **Location** | `engine/runtime/governed_supervisor_ledger.py:645` |
| **Group** | `f01-oracle` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** `_evidence_floor_cas` (ledger:626-677) enforces monotonicity only WITHIN one `(install_id, task_id)` pair. `task_id` is not supervisor state: it arrives in the challenge payload (governed_supervisor.py:615 `task_id=payload["task_id"]`), and the challenge payload is whatever the broker asked the challenge authority to sign (challenge_authority.py:193-215 accepts any bounded string). So the floor's row is chosen by the party it is meant to police, and the first completion under any new task_id takes the `row is None` branch and BOOTSTRAPS the floor to the caller's own numbers. The `evidence_final_event_hash` it stores is likewise a 64-hex string the broker names with nothing to compare it against.

**Code.**
```
if row is None:
        conn.execute(
            "INSERT INTO governed_evidence_head_floor (install_id, task_id,"
            " highest_head_sequence, event_count, last_sequence, final_event_hash, updated_at_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (install_id, task_id, head_sequence, event_count, last_sequence,
             final_event_hash, now_ms),
        )
        return "bootstrapped"
```

**Walkthrough.**

Observed in the same harness run. (1) Turn A: challenge for task_id="task-1"; complete-run with `evidence_head_sequence: 12345`, `evidence_final_event_hash: "9"*64`. Result `{'ok': True, 'recorded': 'created'}` — ledger:645-653 bootstraps the floor row (install-1, task-1) to 12345. (2) Turn B: challenge for task_id="task-2" — the broker simply asks the authority for a different task id, which challenge_authority.validate_create_pending:203-214 accepts. complete-run with `evidence_head_sequence: 1`, i.e. 12344 BELOW the floor just established, and a different `evidence_final_event_hash` ("8"*64). Observed `{'ok': True, 'recorded': 'created'}` — because ledger:640-644 SELECTed on `(install_id='inst-1', task_id='task-2')` and found no row. (3) attest-run for turn B: observed `ok: True`. Neither `StaleEvidence` (ledger:661-662) nor `EvidenceFork` (:669) can fire, because the comparison never happens. Even inside a fixed task_id the floor only requires non-decreasing integers, which the caller supplies.

**Why it matters.** AUDIT_LEDGER.md:25 (F-09) claims "the anti-rollback/anti-fork floor runs on every complete-run", and governed_supervisor_ledger.py:22-24 claims it means "no attestation can ever be built over rolled-back evidence". The floor executes on every completion but decides nothing an attacker cannot reset, so a receipt's `evidence_head_sequence` / `evidence_final_event_hash` carry no ordering information across turns of a deployment — which is the specific property this table exists to provide. This is the same defect class the audit recorded as F-13/F-14 (a floor read from the value it polices); here it is a floor scoped by a key the attacker picks. It is P1 rather than P0 because on its own it does not mint a receipt — it removes the one durable check that could have detected the F-01-R1 replay/rollback of evidence heads.

**Adversarial review (P2).** The mechanism is real and the quote is verbatim: governed_supervisor_ledger.py:640-644 SELECTs the floor row WHERE install_id = ? AND task_id = ?, and :645-653 is exactly the quoted 'if row is None: INSERT ... return "bootstrapped"' branch. task_id is genuinely caller-chosen: governed_supervisor.py:615 copies task_id=payload['task_id'] straight out of the challenge, and challenge_authority.py:203-214 accepts any <=MAX_ID_LEN string from the broker, its only allowlisted peer. install_id (:611) is the same. So StaleEvidence (:661) and EvidenceFork (:669) are unreachable for any completion under a fresh (install_id, task_id) pair, and ledger:22-24's claim that 'no attestation can ever be built over rolled-back evidence' is false as stated. I confirmed the producer-side counter is NOT per-task — governed_recorder.rs:54-70 keeps ONE evidence-head-sequence.json per install — so the honest producer's head really is globally monotonic and the per-task floor is strictly weaker than what it is measuring. DOWNGRADED P1 -> P2 for two reasons I could not argue away. First, this is not an implementation deviation: WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md:3307 and :3353 specify the table keyed on (install_id, task_id) with an explicit 'Bootstrap (no row): INSERT' branch, and supervisor_ledger.sql:168-173 matches — so the defect is a design-level weakness, not a broken control, and the AUDIT_LEDGER's literal F-09 sentence ('the floor runs on every complete-run') is true; I watched it execute at ledger:764-766. Second, the impact is detection-only: the floor mints nothing, and cross-turn replay of the *attempt* is separately blocked by UNIQUE(install_id, request_nonce) / UNIQUE(challenge_handle) (supervisor_ledger.sql:86-90, ledger:326-336) and by the F-26 run/task/attempt bind at chain_executor.rs:378-382. Its only consequence is that evidence_head_sequence and evidence_final_event_hash in a receipt carry no ordering information across turns — a genuine residual, but one whose enforcement point is already wholly owned by the same adversary under F-01-R1.

**Reviewer re-read.** `engine/runtime/governed_supervisor_ledger.py:626-677 (quote verified at :645-653), :22-24 (the overclaim), :764-766 (floor invoked); engine/runtime/governed_supervisor.py:611-616 (install_id/task_id copied from the challenge payload); engine/runtime/challenge_authority.py:193-215; apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:54-70 (one global counter, not per task); engine/runtime/supervisor_ledger.sql:168-176; docs/design/WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md:3307, :3353 (the design specifies this key and this bootstrap)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor_ledger.py:645` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-08` · The 'hash-linked' evidence chain is never verified and never published — no code anywhere reads the events array, and the chain document is dropped instead of being content-addressed into the receipt

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 2 — the broker service account (to exploit). The false claim itself needs no adversary. |
| **Location** | `apps/desktop/src-tauri/broker/src/chain_executor.rs:544` |
| **Group** | `f02-evidence` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:27 sells the fix as 'a hash-linked three-event chain of what it observed for the run (lease-validated -> execution-launched -> output-captured, each carrying previous_event_hash)'. The link exists only in the writer. RunEvidence::parse extracts four scalars and never touches `events`; it never recomputes a previous_event_hash, never checks final_event_hash == sha256(last event bytes), never checks event_count == events.len(), never checks last_sequence == the last event's sequence. A whole-snapshot grep for a consumer of the array finds exactly one hit — governed_recorder.rs:362, the write. Separately, the chain document is never published: it is read at chain_executor.rs:853-855 and dropped, so nothing binds the receipt's evidence_final_event_hash to any retrievable artifact.

**Code.**
```
fn parse(bytes: &[u8]) -> Result<Self, TurnReason> {
        let v: Value = serde_json::from_slice(bytes).map_err(|_| TurnReason::UpstreamBlocked)?;
        if v.get("protocol").and_then(Value::as_str) != Some("brops.run-evidence-chain.v1") {
            return Err(TurnReason::UpstreamBlocked);
        }
```

**Walkthrough.**

1. governed_recorder.rs:320-355 builds three events, each embedding `previous_event_hash`, and 356-367 wraps them with final_event_hash/event_count/last_sequence/head_sequence into the document written at 372. 2. chain_executor.rs:853-854 reads those bytes; 855 calls RunEvidence::parse. 3. RunEvidence::parse (544-564) checks the protocol string, requires final_event_hash to be 64 lowercase hex, and requires event_count/last_sequence/head_sequence to be positive i64. It never dereferences `events`. So a document consisting solely of {"protocol":"brops.run-evidence-chain.v1","final_event_hash":"ab"*32,"event_count":3,"last_sequence":3,"head_sequence":9} — with no events array whatsoever — parses successfully. This is not hypothetical: it is the remediation's own new test fixture at chain_executor.rs:1437-1445, and chain_executor.rs:1447-1452 asserts it parses and yields (3,3,9). The three tests added for this blocker therefore prove the parser accepts an EMPTY chain. 4. The four scalars go to the supervisor alone (chain_executor.rs:864-883); the events never leave the recorder's file. 5. The supervisor stores them shape-checked only (governed_supervisor_ledger.py:588-621) and evidence_from_state (governed_supervisor.py:854-857) signs them. 6. Contrast the containment leg in the same function: chain_executor.rs:833-848 reads the containment report, content-addresses it into the protected store, and the handle is carried in `produced` at 869 and ends up in the signed receipt. The evidence chain gets no such treatment — chain_executor.rs:853-855 reads and discards, and no handle for it appears in the 23-key envelope (OwnedEnvelope, chain_executor.rs:424-448, has no evidence-chain handle field). 7. Net effect: an auditor holding a receipt with evidence_final_event_hash=X has no artifact to compare X against, and even if they obtained the recorder's file, no shipped code path recomputes the link. The tamper-evidence the design names is never evaluated by anyone.

**Why it matters.** The original F-02 defect was 'the receipt claims to attest a tamper-evident evidence chain ... An auditor cross-checking a receipt's evidence head against the real recorder chain finds no correspondence'. After the fix the head is derived from a real chain, but the chain is still checked by nobody and still retrievable by nobody, so the auditor's cross-check remains impossible. The receipt continues to assert a tamper-evident-chain property that no executable code enforces — the same claims-a-property-it-does-not-enforce class the blocker was raised for. It also means the parse-only gate is the entire integrity story for these values, which sets up A-03/A-04.

**Adversarial review (P2).** Verified line by line and it holds. RunEvidence::parse is exactly at chain_executor.rs:544-564 as quoted: it checks `protocol`, requires final_event_hash to be 64 lowercase hex (552-557) and event_count/last_sequence/head_sequence to be positive i64 (549-551,560-562). It never touches `events`, never recomputes previous_event_hash, never compares final_event_hash to a hash of the last event, never compares event_count to events.len(). A whole-snapshot grep for consumers of the recorder's chain confirms the writer is the only toucher: `run-evidence-chain` appears at governed_recorder.rs:366 (write), chain_executor.rs:546 (protocol string), 855 (the one call site) and 1439/1449-1486 (tests); `previous_event_hash` appears at governed_recorder.rs:346 (write) and otherwise only in the UNRELATED engine evidence-event protocol (governance.rs:96,260-287, bro_evidence.py) which never sees this document. The test fixture at chain_executor.rs:1437-1445 is exactly as quoted — protocol + four scalars, no `events` key — and 1447-1452 asserts it parses and yields (3,3,9), so the remediation's own test proves an empty chain is accepted. The publication half also checks out: the containment leg at 833-848 content-addresses its report into the store and 869 carries the handle onward, while the evidence leg at 853-855 reads and drops. Nothing publishes the chain: OwnedEnvelope (424-448) has no evidence-chain handle, and isolated_signer.py:117-125 states it outright — EVIDENCE_CHAIN_HANDLE_FIELDS is only record/lease/execution_receipt, and evidence_final_event_hash is documented as a '64-hex evidence-chain digest carried verbatim ... not a store blob the signer dereferences'. Attempted refutation: I looked for a verifier in run_live_turn.sh, the CI workflows and build_tcb_pin_manifest.py — nothing reads *.evidence.json. Severity P2 not P1: the head is now derived from a real per-run chain, so the value is at least a function of the run; what is false is the tamper-evidence and auditability the ledger sells, and exploiting the unverified link requires the broker (A-04's adversary), who already has the simpler path.

**Reviewer re-read.** `chain_executor.rs:544-564,751,833-848,853-855,864-883,424-448,1437-1452; governed_recorder.rs:304-382 (write-only, 346,360-372); isolated_signer.py:103-125,648-662,736`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/chain_executor.rs:544` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-09` · The four evidence values reach the signer only as the broker's self-report; the supervisor cannot read the recorder's chain and does not try, so 'measured' degrades to 'asserted by the party being constrained'

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001) |
| **Location** | `engine/runtime/governed_supervisor_ledger.py:553` |
| **Group** | `f02-evidence` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The F-01 remediation's stated principle is that the supervisor must build its attestation from its own durable state and never from facts the broker names ('the party being constrained chose the values it would be checked against'). The four evidence_* values are exempted from that principle: they travel from the broker to the supervisor inside complete-run, are validated for shape only, and are then signed. No component recomputes them, no component reads the recorder's file except the broker, and the supervisor is structurally unable to read it (the report directory is group brops-report = recorder + broker only, run_live_turn.sh:177,181 — the supervisor account is not a member). The change is therefore from 'a constant the broker copied out of config' to 'a value the broker says it read', which is a smaller lie surface but the same trust topology.

**Code.**
```
#: The only §4.9 evidence values the supervisor cannot derive itself, so the executing
#: chain reports them — ONCE, for an attempt the supervisor already authorized. Every
#: OTHER evidence field comes from the acceptance row or the supervisor's own config.
```

**Walkthrough.**

1. chain_executor.rs:853-855 is the ONLY reader of the recorder's evidence document in the entire snapshot. 2. chain_executor.rs:864-883 constructs the complete-run message and inserts evidence.final_event_hash / event_count / last_sequence / head_sequence. Nothing signs, MACs or otherwise binds those four values to the recorder that produced them — the recorder holds no key and the document carries no authenticator (governed_recorder.rs:360-372 writes plain JSON). 3. governed_supervisor_ledger.py:588-621 validate_completion_facts checks: exact key set, 64-lowercase-hex for the digest, positive ints for the counters, and last_sequence == event_count. That is the entire validation. 4. _evidence_floor_cas (626-675) checks only ordering against the durable floor — a higher head always advances (671-674), so any monotonically-increasing invented head is accepted forever. 5. record_completion stores the row; evidence_from_state (governed_supervisor.py:849-857) reads the four values back out of that row and build_run_attestation Ed25519-signs them; isolated_signer copies them into the 23-key envelope; governed_verification verifies the signature over them. At no point does any principal other than the broker observe the recorder's measurement. 6. Concrete: a broker that performs a fully genuine run but substitutes final_event_hash = <any 64 lowercase hex> and head_sequence = <floor+1> at chain_executor.rs:878-881 obtains a validly-signed production receipt whose evidence-chain attestation describes a chain that never existed, and — per A-02 — there is no published artifact against which the substitution can ever be detected. 7. Refutation attempted and failed: I checked whether the supervisor re-reads the file (it holds no path to it and could not read it if it did — wrong group), whether the isolated signer resolves an evidence-chain handle from the protected store the way it resolves record/lease/receipt/containment handles (there is no such handle in the envelope — OwnedEnvelope, chain_executor.rs:424-448), and whether the floor's fork check helps (it only fires on EQUAL heads with divergent content, governed_supervisor_ledger.py:663-669, so an incrementing invention never touches it).

**Why it matters.** The blocker's claim is 'measured, not configured'. Measurement happened, but the measurement is not the thing the receipt binds — the broker's report of it is. Since the broker is an explicitly in-scope adversary and is precisely the principal that F-01 removed fact-supply authority from, the four evidence values remain the one place in the §4.9 evidence where the executing party still dictates what it will be attested to have done. A gate-flip decision that reads AUDIT_LEDGER.md:27 as 'the supervisor now attests a measurement' would be relying on a property the code does not provide.

**Adversarial review (P2).** The trust topology is exactly as described and I could not find a second observer anywhere. The quoted comment is verbatim at governed_supervisor_ledger.py:553-555. validate_completion_facts (589-623) is the whole validation: exact key set (604-611), 64-lowercase-hex for output/containment/final_event_hash (612-614), u64 ms for completed_at_ms (615-617), positive int for the three counters (618-620), and last_sequence == event_count (621-622). Nothing recomputes, nothing cross-checks a file. _evidence_floor_cas (626-677) only orders: a strictly higher head always advances (670-677), so an incrementing invention is accepted forever, and the fork branch (663-669) fires only on EQUAL heads. chain_executor.rs:853-855 is the only reader of the recorder's document in the snapshot, and the document carries no authenticator at all (governed_recorder.rs:360-376 writes plain JSON, mode 0644, and the recorder holds no key). The supervisor structurally cannot re-read it: the report dir is group brops-report = recorder + broker only, mode 2770 with no world access (run_live_turn.sh:177,181), and the supervisor account is not in that group. Refutations I tried and that failed: (a) maybe the isolated signer dereferences an evidence-chain handle the way it deep-verifies record/lease/execution-receipt — it does not; isolated_signer.py:117-125 defines EVIDENCE_CHAIN_HANDLE_FIELDS as those three only and comments that evidence_final_event_hash is 'carried verbatim ... not a store blob the signer dereferences', and 648-662 deep-verifies only that trio plus output; (b) maybe the Rust core floor adds a check — it has no production caller at all (core/src/supervisor_ledger.rs:813 appears only in its own tests); (c) maybe the containment report cross-binds the chain — it does not, the two documents share no field that ties the head to the run. So 'measured, not configured' is true only of an honest broker binary, and the broker account is the in-scope adversary the whole F-01 principle was written against. P2 rather than P1 because the message bytes themselves remain bound (the signer re-derives output_sha256/output_bytes from the store blob at isolated_signer.py:662), so what a lying broker forges is the evidence-chain attestation, not the reply content.

**Reviewer re-read.** `governed_supervisor_ledger.py:553-559,574-586,589-623,626-677,735-742; governed_supervisor.py:854; isolated_signer.py:103-125,428,648-662,736; chain_executor.rs:853-855,864-883,424-448; governed_recorder.rs:360-376; run_live_turn.sh:177,181; core/src/supervisor_ledger.rs:813 (no production caller)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor_ledger.py:553` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-10` · The evidence-head anti-rollback/anti-fork floor is keyed on, and compares, values the broker chooses — it runs on every complete-run and constrains nothing

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001). Nothing stronger: it needs only the socket the broker is already SO_PEERCRED-allowlisted for, and only fields the broker already supplies through the normal protocol. |
| **Location** | `engine/runtime/governed_supervisor_ledger.py:640` |
| **Group** | `f09-cas` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The floor's PRIMARY KEY is (install_id, task_id) and its compared value is the four evidence_* numbers. Both sides of that comparison originate with the broker: install_id and task_id are unvalidated free-form strings the broker names in create-pending, and the four evidence values are read by the broker out of a file in a directory the broker can write and are then reported to complete-run. So the party the floor is supposed to police both chooses the bucket it is compared in and chooses the number it is compared against. StaleEvidence and EvidenceFork are unreachable for a broker that does not want them.

**Code.**
```
row = conn.execute(
        "SELECT highest_head_sequence, event_count, last_sequence, final_event_hash"
        " FROM governed_evidence_head_floor WHERE install_id = ? AND task_id = ?",
        (install_id, task_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO governed_evidence_head_floor (install_id, task_id,"
            " highest_head_sequence, event_count, last_sequence, final_event_hash, updated_at_ms)"
            " VALUES (?,?,?,?,?,?,?)",
            (install_id, task_id, head_sequence, event_count, last_sequence,
             final_event_hash, now_ms),
        )
        return "bootstrapped"
```

**Walkthrough.**

STEP 1 — the broker picks the floor's key. The broker calls create-pending with turn facts of its own choosing. challenge_authority.validate_create_pending (engine/runtime/challenge_authority.py:203-214) checks only `_bounded_id` — non-empty, <= 128 chars — for run_id/task_id/workspace_id/install_id/request_nonce. There is no allowlist, no registry, no comparison against any pinned value. issue_challenge copies task_id and install_id verbatim into the signed payload (challenge_authority.py:505-506).

STEP 2 — the supervisor persists that choice without questioning it. accept_open verifies the signature and then copies payload['task_id'] and payload['install_id'] straight into NewAcceptance (engine/runtime/governed_supervisor.py:613-616). The ONLY identity the supervisor checks in Phase C is supervisor_id (governed_supervisor.py:592). task_id and install_id are never compared to anything.

STEP 3 — the broker picks the value the floor compares. In the live Linux chain the four evidence values are not measured by the supervisor. The broker reads the recorder's file at `<report_path>.evidence.json` (apps/desktop/src-tauri/broker/src/chain_executor.rs:751, 853-855), parses it with RunEvidence::parse (chain_executor.rs:544-564), and forwards the four numbers in complete-run's `produced` (chain_executor.rs:874-882). The supervisor cannot cross-check: run_live_turn.sh:177 puts only the recorder and the broker in group brops-report, and line 181 sets the report dir 2770 — the supervisor uid has no access to that directory at all. And the broker removes and can recreate those files itself (chain_executor.rs:752-754).

STEP 4 — the supervisor accepts whatever arrives. _op_complete_run calls ledger.validate_completion_facts (engine/runtime/governed_supervisor_server.py:517), which for the three counters only requires `_is_pos_i63` (>= 1) and for the hash only 64 lowercase hex, plus last_sequence == event_count (engine/runtime/governed_supervisor_ledger.py:612-622). No binding to any recorder artifact.

STEP 5 — the floor bootstraps in a fresh bucket. record_completion calls _evidence_floor_cas with acceptance['install_id'] and acceptance['task_id'] (engine/runtime/governed_supervisor_ledger.py:765-766). Because the broker named a task_id it has never used before, the SELECT at line 640-644 returns None, and line 646-653 INSERTs the presented head as the new floor and returns "bootstrapped". A head_sequence of 1, presented after a hundred turns whose floor reached 500, is accepted.

STEP 6 — even in a REUSED bucket the floor is satisfiable at will. If the broker keeps the same task_id, line 661 refuses only `head_sequence < highest`. The broker supplies head_sequence itself (step 3), so it simply names a larger integer; `_is_pos_i63` allows up to 2**63-1.

WRONG OUTPUT: the turn completes, the acceptance row advances to COMPLETED (governed_supervisor_ledger.py:769-771), load_attestation_state returns the state (814-855), and build_run_attestation Ed25519-signs evidence carrying a rolled-back or wholly invented evidence head (governed_supervisor.py:854-857, 918-919). No StaleEvidence and no EvidenceFork is ever raised.

REFUTATION ATTEMPTS THAT FAILED TO SAVE IT: (a) I looked for a task_id/install_id allowlist in the isolated signer — isolated_signer.py:605-611 allowlists only executor_id, builder_id and supervisor_id; task_id and install_id are merely copied into the envelope (isolated_signer.py:727-729). (b) I looked for a supervisor-side pin — SupervisorConfig (governed_supervisor.py:387-439) carries supervisor_id/executor_id/builder_id/policy_* but no task or install identity. (c) I looked for a signature or MAC on the recorder's evidence file — RunEvidence::parse (chain_executor.rs:544-564) checks a protocol tag and field shapes only; there is no key material involved. (d) I checked whether the broker's own verify_and_accept re-derives the head — it compares against the broker's OWN Expected, which for a compromised broker is self-comparison.

**Why it matters.** The claimed property is stated twice in the code and once in the ledger. governed_supervisor_ledger.py:135-141 defines StaleEvidence as "the evidence head presents a strictly LOWER head_sequence than the durable floor" and EvidenceFork as "a same-head fork"; supervisor_ledger.sql:166-177 calls the table "the anti-rollback / anti-fork floor"; AUDIT_LEDGER.md:25 says "the anti-rollback/anti-fork floor runs on every complete-run". All three are literally true and none of them is load-bearing: the control runs, and the one adversary it exists to constrain walks past it in a single field. On the single question this does not by itself forge a message — the head is four numbers in the evidence, not the reply — so it is a claimed-but-unenforced audit property rather than a message-forgery path. But it is the SECOND half of F-09, and it is the half the ledger's ◑ mark is hedging about; it should not be read as closed.

**Adversarial review (P2).** SURVIVES. I tried four ways to kill it and all four failed.

QUOTE CHECK: the quoted block is verbatim at governed_supervisor_ledger.py:640-653. Real.

STEP 1 (broker picks the KEY) — CONFIRMED. validate_create_pending applies only `_bounded_id` (non-empty, <=128 chars) to run_id/task_id/workspace_id/install_id/request_nonce (challenge_authority.py:203-214). No allowlist, no registry, no pin. issue_challenge copies task_id/install_id verbatim into the signed payload (challenge_authority.py:503-506).

STEP 2 (supervisor persists the choice) — CONFIRMED. I read accept_open end-to-end (governed_supervisor.py:560-637). Phase C compares ONLY payload['supervisor_id'] to config.supervisor_id (:591-596). NewAcceptance takes install_id=payload['install_id'] and task_id=payload['task_id'] with no comparison (:611-616). I then read SupervisorConfig.__init__ in full (governed_supervisor.py:387-440): it carries supervisor_id/executor_id/builder_id/policy_*/challenge_registry_* and NO install or task identity. There is nothing to pin against.

STEP 3 (broker picks the VALUE) — CONFIRMED, and weaker than the finding even claims. The recorder does build a real hash-linked chain and writes it unsigned to `--evidence-out` (governed_recorder.rs:298-375; event 3 even carries output_sha256). But there is NO key material anywhere in that document, and the supervisor never reads the file: run_live_turn.sh puts only RECORDER_USER and BROKER_USER in group brops-report and chmods the report dir 2770, so the supervisor uid has no access at all. The broker merely relays four integers/strings over the wire — it does not even need to rewrite the file. RunEvidence::parse (chain_executor.rs:541-564) checks a protocol tag and field shapes only.

STEP 4/5/6 (supervisor accepts, floor bootstraps or is out-run) — CONFIRMED. validate_completion_facts enforces `_is_pos_i63` (>=1) and last_sequence == event_count and nothing else (governed_supervisor_ledger.py:618-622). record_completion calls _evidence_floor_cas with acceptance['install_id'], acceptance['task_id'] (:764-766). A never-used task_id makes row None → INSERT → 'bootstrapped' (:645-653). A reused bucket refuses only head_sequence < highest (:661), and the broker names head_sequence.

MY OWN REFUTATION ATTEMPTS, ALL FAILED: (a) isolated_signer._check_identity allowlists executor_id/builder_id/supervisor_id only (isolated_signer.py:605-611) — task_id and install_id are not in it. (b) _recompute_request_sha256 binds workspace_id/install_id/request_nonce/the three INPUT digests (isolated_signer.py:667-689) — install_id is bound there, but only to the broker's own request envelope, not to any registry, and task_id is absent entirely; and binding install_id to the request does not stop the broker naming a fresh (install_id, task_id) pair for both. (c) governed_verification::verify_and_accept step 4b does compare envelope.task_id to ctx.expected_task_id (governed_verification.rs:330-335) — but ctx is the BROKER's own resolution, so for the adversary in question it is self-comparison. (d) I looked for a second floor implementation or a signature over the evidence file; there is none.

SEVERITY: P2 held, not raised. This is a control that runs and constrains nothing against its only adversary — a claimed-but-unenforced audit property, not a message-forgery path (the head is four evidence numbers, not the reply). The finding says exactly that and does not oversell it.

**Reviewer re-read.** `engine/runtime/governed_supervisor_ledger.py:640-653 (quote verified verbatim), :618-622 (shape-only validation), :764-766 (floor keyed on acceptance install_id/task_id), :661-669 (the only comparisons); engine/runtime/challenge_authority.py:203-214 (bounded-id only), :503-506 (verbatim copy into the signed payload); engine/runtime/governed_supervisor.py:591-596 (supervisor_id is the ONLY identity checked), :611-616 (task_id/install_id copied unchecked), :387-440 (SupervisorConfig has no task/install pin); engine/runtime/isolated_signer.py:605-611 (allowlist excludes task_id/install_id); apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:298-375 (chain is UNSIGNED); apps/desktop/src-tauri/broker/src/chain_executor.rs:541-564 (shape-only parse), :874-882 (four values relayed); engine/ci/live/run_live_turn.sh (add_group brops-report = recorder+broker only; chmod 2770 REPORT — supervisor uid excluded)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor_ledger.py:640` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-11` · The §2.5 content pin is self-referential: the manifest is generated from the very bytes it measures, seconds earlier in the same script, and is never re-measured — HashMismatch cannot fire

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | None required to demonstrate the defect (the control has zero detection capability as deployed). Exploiting the resulting blind spot requires write authority the floor itself demands nobody have, i.e. root — which is why this is P2 and not higher. |
| **Location** | `engine/ci/live/run_live_turn.sh:210` |
| **Group** | `f10-tcb` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** A content pin is only a measurement if the expected digest has an origin independent of the bytes being measured. Here the expected digests are computed from those exact bytes 34 lines earlier in the same root shell, and the comparison is the only comparison that will ever be made against them. The floor's HashMismatch branch (tcb_integrity.rs:276-283) — the branch that exists to detect a substituted supervisor/launcher/executor/signer binary, which is precisely what F-10 was raised about — is structurally incapable of firing. This is the same defect class the same audit report recorded at F-13/F-14 ('load_head(...).head_sequence fed back in as min_head_sequence, so validate_chain compared x >= x'). The owner/mode/ancestor half of the floor is NOT affected — it compares against a fixed policy and demonstrably fired during development (the script had to chown/chmod /opt at :224 and strip ACLs at :230 to make it pass). Only the content half is vacuous.

**Code.**
```
python3 "$PYLIVE/build_tcb_pin_manifest.py" --root-dir "$LIVE"   --sudoers "$SUDOERS" --unit "$TCB/brops-live.unit" --out "$TCB/tcb-pin-manifest.json"   || { echo "FAIL: build_tcb_pin_manifest.py"; exit 1; }
...
"$BIN/live_turn" --config "$CONFIG" --verify-tcb || { echo "FAIL: the §2.5 TCB integrity floor"; exit 1; }
```

**Walkthrough.**

1. run_live_turn.sh:69 `rm -rf "$LIVE"` — every run starts from an empty deployment root, so no manifest survives from a previous run and there is no persistent golden reference anywhere. 2. run_live_turn.sh:76-96 root copies the Python tree and installs the four built binaries into $LIVE. 3. run_live_turn.sh:131-141 writes $TCB/executor.lease; :153 places $TCB/root-anchor.json; :199-200 writes /etc/sudoers.d/brops-live-recorder; :208 installs $TCB/brops-live.unit. All 14 distinct pinned files now exist. 4. run_live_turn.sh:210 invokes build_tcb_pin_manifest.py, which at line 106 sets `"expected_sha256": sha256_file(path)` for each of the 21 roles — reading each file that instant. 5. run_live_turn.sh:211-231 chown/chmod/setfacl only; no pinned file's CONTENT is altered (verified line by line: 211 chown+chmod the manifest, 217-218 chown+chmod dirs, 224 chown+chmod /opt, 230 setfacl -Rb, 235 ls). 6. run_live_turn.sh:244 runs `live_turn --verify-tcb`, which reaches tcb_probe.rs:129 -> tcb_integrity.rs:276 `if facts.sha256 != art.expected_sha256`. facts.sha256 comes from tcb_probe.rs:70-82 reading the same unmodified file. The comparison is digest(F) != digest(F). 7. Wrong output: `RESULT: tcb_integrity_floor verified artifacts=pinned` (live_turn.rs:207) is emitted, and exit 0 lets the run proceed — but no integrity property about content was tested. 8. No re-measurement follows: services start at run_live_turn.sh:259-261 and the governed turn runs at :271 in a process that, per repo-wide grep, contains no call to verify_deployment_tcb (the only reference in live_turn.rs is line 201, inside the separate verify_tcb entry point that std::process::exit()s at :36).

**Why it matters.** The AUDIT_LEDGER F-10 row claims closure of 'every downstream signature check ran on binaries whose integrity was never measured.' As deployed, the binaries' integrity is still not measured in any falsifiable sense — the reference is derived from the subject. The floor's real, non-vacuous contribution is the owner/mode/ancestor check, which is a *provisioning* assertion, not a *code-integrity* one. For the single question: this does not by itself let an in-scope adversary mint trusted_verified, because they cannot write a root-owned pinned artifact anyway. But it means §2.5 contributes no defence-in-depth if any other control in the chain is later found to grant a write, and it should not be counted as satisfied evidence when flipping the gate.

**Adversarial review (P2).** SURVIVES. I tried to refute it three ways and failed. (1) Quote verified verbatim: run_live_turn.sh:210 invokes build_tcb_pin_manifest.py, and :244 runs `"$BIN/live_turn" --config "$CONFIG" --verify-tcb || { ...; exit 1; }`. (2) I re-read every line between :210 and :244 looking for a content mutation that would make the comparison non-trivial — :211 chown/chmod of the manifest (itself unpinned), :217-218 chown/chmod of directories, :224 chown/chmod /opt, :229-231 `setfacl -Rb`, :235 `ls -ld`. None of these alters the BYTES of any of the 14 pinned files; setfacl can change st_mode group bits but not content. So facts.sha256 at tcb_integrity.rs:276 is the digest of the identical bytes build_tcb_pin_manifest.py:106 hashed 34 lines earlier. HashMismatch is structurally unreachable in this kit. (3) I searched for a second, later measurement that would make the pin non-vacuous: repo-wide grep for verify_deployment_tcb / verify_tcb_integrity returns exactly two non-test call sites — live_turn.rs:201 (inside the separate --verify-tcb entry point) and main.rs:281 (broker process start). There is no inotify/fanotify/timer/periodic re-verify anywhere in the tree. The turn at run_live_turn.sh:271 is a new process with no floor evaluation. The finding is correctly scoped: it explicitly exempts the owner/mode/ancestor half (which IS non-vacuous — it forced the chown of /opt at :224 and the ACL strip at :230), and it explicitly states no in-scope adversary gains anything, which is why it is not higher than P2. Held at P2 because it is the same claimed-but-unenforced class as the original F-10 (which the previous audit also rated P2), and because the AUDIT_LEDGER row's stated closure ('every downstream signature check ran on binaries whose integrity was never measured') is not delivered by the deployed content pin. Note in fairness to the author: the CODE supports a non-vacuous use (main.rs:281 reads the manifest path from config/$BROPS_TCB_PIN_MANIFEST at process start, which in a real install-time provisioning would be an independent reference) — the vacuity is a property of the lab kit's usage, not of tcb_integrity.rs.

**Reviewer re-read.** `run_live_turn.sh:210 (manifest built) vs :244 (floor run), with :211,:217-218,:224,:229-231,:235 verified as the only intervening operations and none content-mutating; build_tcb_pin_manifest.py:106 `"expected_sha256": sha256_file(path)`; tcb_integrity.rs:276 `if facts.sha256 != art.expected_sha256`; tcb_probe.rs:70-82 digest() reads the same path; live_turn.rs:206-208 prints `RESULT: tcb_integrity_floor verified artifacts=pinned`; repo-wide grep shows the only non-test callers are live_turn.rs:201 and main.rs:281 — no re-measurement path exists. engine/tests/test_live_tcb_pin_manifest.py:87-98 asserts exactly the tautology (each expected_sha256 equals sha256 of the file it names).`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/ci/live/run_live_turn.sh:210` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-12` · The coverage floor is satisfied by logical NAME, not by causal role: 21 roles resolve to 14 files, one pinned artifact is read by no code by the author's own admission, and the two IPC policies that actually gate peer-auth are unpinned

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | None demonstrated — this is a coverage/assurance defect. I specifically failed to find a write primitive for the unmeasured files (see walkthrough step 6), so I am reporting it as a gap in what the floor can detect, not as an exploit. |
| **Location** | `engine/ci/live/build_tcb_pin_manifest.py:84` |
| **Group** | `f10-tcb` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** TCB_REQUIRED_ARTIFACTS names two `*.ipc-policy` roles. The live kit has THREE servers that enforce peer-auth from a policy file, and the two roles pinned are the wrong two. run_authority.py:42-43 loads the `desktop-challenge-authority` policy (pinned, correct). run_supervisor.py:58-59 loads `supervisor.ipc-policy.json` and run_signer.py:74-75 loads `isolated-signer.ipc-policy.json` — NEITHER is in the manifest. Meanwhile the pinned `trusted-verifier-broker.ipc-policy.json` is loaded by nothing: provision_keys.py:311-314 writes it with `"allowed_peer_uids": []` and the comment 'The broker is the CLIENT of every hop; nothing connects TO it ... it is fail-closed if anything ever loads it.' A repo-wide grep for ipc-policy consumers confirms no Rust or Python code reads it. It is padding that satisfies a required name. The same pattern holds for the executables: `supervisor.bin` pins engine/ci/live/run_supervisor.py (7,436 bytes of argument parsing and wiring) while the code that mints leases, rebuilds evidence and signs attestations lives in engine/runtime/governed_supervisor.py (45,286 bytes) and governed_supervisor_server.py (34,297 bytes) — copied into the deployment at run_live_turn.sh:77 and pinned by nothing.

**Code.**
```
"desktop-challenge-authority.ipc-policy":
            os.path.join(tcb, "desktop-challenge-authority.ipc-policy.json"),
        "trusted-verifier-broker.ipc-policy":
            os.path.join(tcb, "trusted-verifier-broker.ipc-policy.json"),
```

**Walkthrough.**

1. tcb_integrity.rs:192-193 requires the names `trusted-verifier-broker.ipc-policy` and `desktop-challenge-authority.ipc-policy`. 2. build_tcb_pin_manifest.py:84-87 binds those names to two files in $TCB. 3. tcb_integrity.rs:223-228 `missing_required()` finds both names present -> coverage floor satisfied. 4. run_supervisor.py:58-59 `ipc_policy.load_allowed_peer_uid(cfg["ipc_policies"]["supervisor"], "supervisor")` resolves to $TCB/supervisor.ipc-policy.json (provision_keys.py:307 with service='supervisor'). That file — which decides which uid may drive accept-open/launch-gate/attest-run on the process holding supervisor_attest.priv — is never measured. Same for $TCB/isolated-signer.ipc-policy.json and the signer key. 5. Wrong output: the floor reports full coverage of the §2.5 EXPANDED set while the two peer-auth rules that gate the two signing principals are outside it, and one of the two it does cover is inert. 6. REFUTATION I RAN AND WHICH LIMITS SEVERITY: I tried to turn this into an exploit and could not. run_live_turn.sh:209 chowns 0:0 and chmods 0644 every $TCB/*.ipc-policy.json including the unpinned two, and ipc_policy.py:39-44 independently refuses any policy not owned by uid 0 or with a group/other write bit, checked on the opened fd. run_live_turn.sh:218 `chown -R 0:0 "$LIVE/engine"` plus the 0755 directory mode leaves the unpinned engine/runtime/*.py root-owned and unwritable by broker uid 5001, by the login uid, or by any other unprivileged account. So no in-scope adversary can alter the unmeasured files. The defect is that if any of those custody controls is ever wrong, §2.5 will not notice.

**Why it matters.** The ledger claims 'every entry a real digest of a file that genuinely serves that role' and 'The *.ipc-policy roles are now real: each server loads its own root-owned brops.ipc-policy.v1 file.' The first is false for `trusted-verifier-broker.ipc-policy` and for both `.unit` roles; the second is true of the servers but does not describe the manifest, which measures one of the three loaded policies. For a gate flip, '21 artifacts pinned' should be read as '14 files, of which one is inert, while the largest and most security-relevant code in the deployment is outside the set.'

**Adversarial review (P2).** SURVIVES. I verified every leg independently with a repo-wide grep for ipc-policy consumers. Exactly three servers load a policy: run_authority.py:42-43 (`desktop-challenge-authority`, PINNED), run_supervisor.py:58-59 (`supervisor`, NOT pinned), run_signer.py:74-75 (`isolated-signer`, NOT pinned). The pinned `trusted-verifier-broker.ipc-policy` is loaded by NO Rust or Python code — provision_keys.py:305-315 writes it with `"allowed_peer_uids": []` and the author's own comment 'The broker is the CLIENT of every hop; nothing connects TO it ... it is fail-closed if anything ever loads it.' So of the two pinned peer-auth roles, one is inert and the two policies that actually gate the supervisor-attest key and the signer key are outside the measured set. I also confirmed the executable sizes by stat: run_supervisor.py = 7,436 bytes (pinned as supervisor.bin), engine/runtime/governed_supervisor.py = 45,286 and governed_supervisor_server.py = 34,297 (staged into the deployment at run_live_turn.sh:77, pinned by nothing) — plus governed_supervisor_ledger.py at 42,618, also unpinned. And the count checks out: TCB_REQUIRED_ARTIFACTS is 21 names (7+7+2+1+2+2), resolving through build_tcb_pin_manifest.py's mapping to 14 distinct files. TWO NUANCES that weaken it slightly but do not kill it: (i) the gap is partly in TCB_REQUIRED_ARTIFACTS itself (tcb_integrity.rs:191-193 names only the broker and authority policies, per rev-30 §2.5), so the builder is faithful to the required set — the required set is what does not describe this deployment; (ii) the '.unit roles are not real' sub-claim is arguable — build_tcb_pin_manifest.py:20-22 openly argues the orchestrator script IS this kit's unit, which is a defensible choice, and run_live_turn.sh:208 installs a root-owned copy. The `trusted-verifier-broker.ipc-policy` leg, however, is not arguable: it is padding that satisfies a required name. Kept at P2 because it directly falsifies the AUDIT_LEDGER claim 'every entry a real digest of a file that genuinely serves that role' and changes how '21 artifacts pinned' should be read at a gate decision. The finding's own failed-exploit section (run_live_turn.sh:209 chowns/chmods ALL $TCB/*.ipc-policy.json, ipc_policy.py:39-44 independently refuses non-root-owned or group/other-writable policies on the fd, :218 chowns the whole engine tree root:root) I re-verified and it is correct — no in-scope write primitive exists.

**Reviewer re-read.** `grep of all ipc-policy consumers: run_authority.py:42-43, run_supervisor.py:58-59, run_signer.py:74-75 — only the first is in build_tcb_pin_manifest.py:84-87; provision_keys.py:305-316 (empty allowlist + 'nothing connects TO it'); tcb_integrity.rs:174-202 (21 names) vs build_tcb_pin_manifest.py:64-96 (14 distinct paths); file sizes verified by stat: run_supervisor.py 7,436 vs governed_supervisor.py 45,286 / governed_supervisor_server.py 34,297 / governed_supervisor_ledger.py 42,618, all staged by run_live_turn.sh:77 and unpinned; custody that blocks exploitation: run_live_turn.sh:209,:218 and ipc_policy.py:32-44.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/ci/live/build_tcb_pin_manifest.py:84` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-13` · The head-floor mark is advanced by the very process it polices, so the ledger's own escape route ('put the marks under a principal the builder cannot write') cannot be configured — such a directory makes every completion RED

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 3 — the interactive login user / the builder process itself. This is an architectural impossibility rather than an exploit: it is why A1 has no deployment-side mitigation. |
| **Location** | `engine/runtime/bro_completion.py:269` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** An anti-rollback high-water mark is only an authority if the policed party cannot rewind it. Here the mark is written in-process by the Stop gate (bro_completion.py:226, reached from bro_hook.py:194, which runs in the builder's own process — the module's own stated threat model at bro_completion.py:43-48 and bro_evidence.py:18-22). Write access to the mark is a REQUIREMENT of the design, and write access is exactly what defeats it.

**Code.**
```
def _advance_head_floor(store: pathlib.Path, task_id: str, head_sequence: int) -> None:
    """Raise the recorded mark to ``head_sequence``. Never lowers it."""
    if head_sequence <= _load_head_floor(store, task_id):
        return
    directory = _head_floor_dir(store)
    try:
        directory.mkdir(parents=True, exist_ok=True)
```

**Walkthrough.**

Take the ledger's mitigation at face value: 'BRO_EVIDENCE_HEAD_FLOOR for a deployment that can put the marks under a principal the builder cannot write' (AUDIT_LEDGER.md:33, echoed at bro_completion.py:236-241). Configure BRO_EVIDENCE_HEAD_FLOOR=/var/lib/brops/head-floor owned by an operator account, mode 0755, not writable by the builder. Turn 1: a genuine chain verifies at bro_completion.py:220; :226 calls _advance_head_floor with head_sequence=N; :271 loads the current mark (0, none exists) and N > 0 so it proceeds; :275 mkdir(exist_ok=True) succeeds because the directory exists; :278 temporary.write_text raises PermissionError; :284-286 converts it to CompletionError('cannot record the evidence head floor for <task>: ...'); _check_manifest (:386) propagates it; authorize_stop (:564-565) returns (False, 'completion gate RED: ...'). The FIRST honest completion is refused. So the operator must make the directory builder-writable, at which point the builder can unlink the mark (finding A1) or write a lower value into it directly — 'never lowers' is not a filesystem property, it is one branch in code the builder is not obliged to run. The desktop side implements the correct shape and is the contrast that proves the point: apps/desktop/src-tauri/core/src/supervisor_ledger.rs:798-891 does the head-floor CAS inside the SIGNER's own database under BEGIN IMMEDIATE, a principal the policed party cannot write at all.

**Why it matters.** The ledger presents the env var as the residual's remedy and the code comment says 'pointing the env elsewhere closes it' (bro_completion.py:241). It closes nothing: there is no assignment of ownership to that directory that both permits normal operation and denies rollback. Any future 'we set BRO_EVIDENCE_HEAD_FLOOR, therefore closed' claim is unsound on its face, and an auditor who accepts it will have accepted a control that cannot exist in this architecture.

**Adversarial review (P2).** Quote verified verbatim at bro_completion.py:269-275. I attacked the claim 'no configuration works' and could not break it. The failure chain is real by reading: :275 `mkdir(parents=True, exist_ok=True)` succeeds on an existing unwritable directory, :278 `temporary.write_text` raises PermissionError, :284-286 wraps it in CompletionError, which propagates through _check_manifest (:386) to a RED stop - so an operator-owned, builder-unwritable floor directory turns the FIRST honest completion RED. Refutations I tried: (i) pre-seed the floor file at a high value so :271 early-returns and never writes - degenerate, it refuses every genuine head below the seed and still attempts (and fails) a write the moment the recorder legitimately exceeds it; (ii) operator-owned directory with the sticky bit and a builder-writable parent - :283 `temporary.replace(final)` is a rename over an operator-owned file, which sticky-bit semantics deny (EPERM), so it fails the same way; (iii) a separate privileged advancer - no such component exists anywhere in the tree (grep: BRO_EVIDENCE_HEAD_FLOOR appears ONLY in bro_completion.py, in no runbook, no CI, no live kit). The cited contrast is accurate, not decoration: supervisor_ledger.rs:813-891 really does perform the floor CAS inside the signer's DB under `BEGIN IMMEDIATE` with a NestedTransaction refusal, i.e. the correct shape the engine lacks. Severity: this is not itself an exploit, so I considered P3, but it is the load-bearing refutation of the ledger's own stated remedy ('BRO_EVIDENCE_HEAD_FLOOR for a deployment that can put the marks under a principal the builder cannot write') and is what leaves A1 with no configuration-level fix. Held at P2. Caveat the report should carry: the ownership/rename reasoning is POSIX and was NOT executed on Linux; on Windows the same conclusion follows from DACL write-denial on the directory, also unexecuted.

**Reviewer re-read.** `bro_completion.py:269-286 (mkdir/write_text/replace, OSError -> CompletionError), :226 (called in-process from the Stop gate), :236-241 (the 'pointing the env elsewhere closes it' claim), :43-48 (the module's own builder-process threat model); bro_hook.py:194; AUDIT_LEDGER.md:33; contrast confirmed at apps/desktop/src-tauri/core/src/supervisor_ledger.rs:813-891.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_completion.py:269` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-14` · BRO_OPERATOR_ROOT_PIN_SELF_OWNED is an ungated ambient env var that restores the pre-fix F-06 behaviour for exactly the adversary the pin defends against, and it cannot be suppressed by a caller that curates its environment

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 3 — the interactive login user, or any actor able to set environment variables in the verifying process. That is precisely the capability the F-06 attack already needed (it must set BRO_OPERATOR_ROOT_PUBKEY_FILE), so the acknowledgement adds no new requirement to the attack. |
| **Location** | `engine/runtime/bro_signature.py:263` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The refusal added for F-06 (:397-403 Windows, :499-505 POSIX) is conditioned on 'and not _self_owned_pin_acknowledged()'. That predicate reads the LIVE process environment, not the env mapping the caller passed — a deliberate choice documented at :260-262 — so unlike ENV_PIN, ENV_PIN_FILE, BRO_ENV and the registry-floor vars, which every caller controls by supplying its own mapping, this one is unconditionally ambient. And unlike ENV_PIN, which the same module refuses outside CI (:535-539) with the explicit reasoning that the trust root must not be swappable by environment variables alone, the acknowledgement has no BRO_ENV gate, no file-based form, no operator signature and no registry binding.

**Code.**
```
return os.environ.get(ENV_PIN_SELF_OWNED_ACK, "").strip() == PIN_SELF_OWNED_ACK_VALUE
```

**Walkthrough.**

STEP 1: the adversary generates an Ed25519 keypair and writes the public key hex to a file they own, outside the repo, no symlink component, mode 0644 — the original F-06 setup (independent-audit.md:257). STEP 2: they set BRO_OPERATOR_ROOT_PUBKEY_FILE to that path. Post-fix this refuses: I executed _pin_from_file on Windows 11 against a self-owned pin with no acknowledgement and got 'BRO_OPERATOR_ROOT_PUBKEY_FILE is owned by the very account reading it, which can rewrite it at will'. STEP 3: they add one more variable to the same environment they were already setting — BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged. _self_owned_pin_acknowledged() (:263) returns True, the condition at :499 (POSIX) / :397 (Windows) short-circuits, and _pin_from_file returns the attacker's key. I executed exactly this: ACCEPTED. STEP 4: they write config/trusted-keys.json self-signed under their operator key with production: true; load_trusted_keys (:665-721) finds declared == pin (:675-678), verify_detached passes (:679), the pinned_from_file production binding is satisfied by their own payload (:681-685), resolve_registry_floor returns None when no floor var is set (:621-623), and every downstream verify_artifact — mode-grant, execution-lease, conductor-session, completion-manifest, verifier-receipt, recovery-proof, release-grant — validates under their keys. STEP 5 (the caller cannot defend): a hardened caller passing a curated mapping, e.g. resolve_operator_root_pin({ENV_PIN_FILE: path}, root=...), still gets the ambient acknowledgement. I executed that case with the ack present ONLY in os.environ and absent from the mapping: ACCEPTED. Refutation I attempted that did not save the control: the acknowledgement is not set anywhere in the repo, CI, the live kit or any default (grep over the whole snapshot returns bro_signature.py plus two test files), so it does not ship ON — but nothing stops the adversary turning it on, and the module's own answer to that same problem for ENV_PIN was a CI gate it did not apply here.

**Why it matters.** AUDIT_LEDGER.md:33 states 'Both platforms now refuse a self-owned pin' and that a deployment with no principal separation 'must say so explicitly'. Nothing distinguishes a deployment saying so from an attacker saying so: both are one export in the same process. The net gain over pre-fix behaviour is detection of MISCONFIGURATION, not resistance to the adversary F-06 named. The module docstring at :27-36 now hangs its central claim on the condition 'PROVIDED the pin file belongs to a principal this process cannot impersonate' — a condition the same process can waive.

**Adversarial review (P2).** Quote exact at bro_signature.py:263. Every step reproduced on this Windows 11 host against an isolated copy: (1) a self-owned pin file with no acknowledgement is REFUSED ('BRO_OPERATOR_ROOT_PUBKEY_FILE is owned by the very account reading it...') - so the F-06 fix is real and fires; (2) adding BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged to the ambient environment ACCEPTS the same file; (3) the curated-mapping bypass is real - `resolve_operator_root_pin({ENV_PIN_FILE: path}, root=...)` with the ack present ONLY in os.environ and absent from the mapping ACCEPTED, because :263 reads os.environ by deliberate design (:260-262); (4) I additionally confirmed the same ungated ack covers the registry anti-rollback floor pin (resolve_registry_floor with BRO_OPERATOR_REGISTRY_MIN_FILE: refused by default, accepted with the ack), which the finding does not mention and which widens it. Refutations I attempted: (a) 'it ships on' - it does not; grep across the whole snapshot finds ENV_PIN_SELF_OWNED_ACK only in bro_signature.py and two test files, so this is an attacker action, not a default; (b) 'the module holds ENV_PIN to the same weak standard, so there is no asymmetry' - this partly deflates the finding, because BRO_ENV=ci is also just an env var, BUT the asymmetry survives in the form that matters: _env_is_ci takes the caller's mapping (:518-525, :535) so a curated caller CAN suppress it, whereas _self_owned_pin_acknowledged cannot be suppressed by any caller; (c) 'this requires the attacker to already be the party the pin protects against' - it does not. The pin protects against whoever can write the repo tree; a tree-write-only adversary cannot set either variable, so that protection is intact. The A5 adversary is 'can set the verifying process's environment', which is exactly the capability the ORIGINAL F-06 attack already needed to set ENV_PIN_FILE - hence the correct claim is that the fix adds zero resistance against F-06's own named adversary, not that it adds a new one. P2 confirmed, not raised: the net effect is loss of detection for a misconfiguration rather than a new forge primitive, and this is the engine's Python trust root, not the desktop's Rust production_verified signer.

**Reviewer re-read.** `bro_signature.py:257-263 (os.environ, not the caller's mapping), :397-403 (Windows refusal gated on the ack), :499-505 (POSIX refusal, same gate), :518-525 + :535-539 (the mapping-based BRO_ENV=ci gate applied to the other env anchor), :608-609 (the registry floor reuses the same _pin_from_file gate), :27-36 (docstring). My runs on Windows 11: default REFUSED; ambient-ack ACCEPTED e3e0b2c91e06dcf1; curated mapping without the ack ACCEPTED e3e0b2c91e06dcf1; registry floor refused then ('minimum', 12345) accepted with the ack.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_signature.py:263` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-15` · The acknowledged self-owned trust anchor is reported to nobody: the deployment-posture preflight prints 'GREEN: deployment posture hardened' for an anchor the running account owns

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | none required — this is an honesty/telemetry defect (relevant to all four adversaries because it removes the only compensating control, an operator noticing, that would make A5 tolerable). |
| **Location** | `engine/runtime/bro_signature.py:35` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** _self_owned_pin_acknowledged() (:257-263) is referenced only inside the two raise-conditions (:398, :499). Its value is never returned, never logged, never attached to the loaded registry, and never surfaced in any result. No caller is told anything. bro_deploy_preflight.py — whose stated job (:1-10) is to prove the ENVIRONMENT hardened before the first action, and which explicitly reasons that 'a process that can set its own environment could also set' the raw pin — neither imports nor checks the acknowledgement; BRO_EVIDENCE_HEAD_FLOOR is likewise absent from its LEDGER_VARS (:47-55).

**Code.**
```
self-owned anchor is exactly as strong as the account that holds it, and callers are
told so rather than left with the unqualified claim.
```

**Walkthrough.**

STEP 1: I subclassed the author's own fixture, engine/tests/test_deploy_preflight.py PreflightFixture, whose setUp writes the pin file with this process (:43-45) and then starts BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged for the whole test (:50-53) precisely because the anchor is self-owned. STEP 2: I confirmed ownership out of band — Get-Acl reported owner 'OFFICE\Admin' and the process account was 'Admin', so the trust anchor is owned by the account running the verifier. STEP 3: I called the real preflight(env=self.env, root=self.root). check_operator_pin (:71-79) only asks whether ENV_PIN_FILE is set and whether resolve_operator_root_pin raises — and it does not raise, because the acknowledgement suppresses the refusal. check_registry (:82-104) and check_ledgers (:107-120) say nothing about ownership. STEP 4: result = [] — I observed 'preflight failures = []', which main() (:135-145) turns into exit 0 and 'GREEN: deployment posture hardened'. The shipped test test_hardened_environment_passes (test_deploy_preflight.py:67-68) asserts exactly this empty list, so the suite pins the behaviour that a self-owned anchor is 'hardened'. STEP 5: the documentation reinforces it — OPERATOR_RUNBOOK.md:26-30 tells the owner the preflight is RED unless the pin is 'operator-controlled ... owner-only', and lists two residual owner responsibilities at :43-48 (offline recovery key, distinct runner identity) without mentioning principal separation for the anchor or the acknowledgement variable at all.

**Why it matters.** This is the difference between a documented weakness and a silent one. The ledger claims the fix converts silence into an explicit, reportable statement; in the shipped code that statement exists only in a Python docstring no operator reads, while the one tool designed to report deployment posture actively certifies the weak configuration as hardened. An owner following the runbook sees GREEN over an anchor their own builder account can rewrite — the original F-06 condition with a reassuring label on top.

**Adversarial review (P2).** Both halves verified independently. (1) 'Reported to nobody': I grepped the entire snapshot - _self_owned_pin_acknowledged appears at its definition (:257) and at exactly two call sites, the raise conditions at :398 and :499. Its value is never returned, logged, attached to the loaded registry, or placed in any result, so the docstring claim at :35-36 ('callers are told so rather than left with the unqualified claim') is unimplemented. (2) 'Preflight certifies it hardened': I EXECUTED bro_deploy_preflight.check_operator_pin with a self-owned pin file and the ack set, and got failures = []. Reading confirms why: :74-81 asks only whether ENV_PIN_FILE is set and whether resolve_operator_root_pin raises, and the ack suppresses the raise; check_registry (:84-104) and check_ledgers (:107-120) say nothing about ownership; preflight (:126-132) returns [], and main (:135-145) prints 'GREEN: deployment posture hardened' and exits 0. Refutations I tried: (a) 'the preflight is not supposed to check this' - it is: its own docstring (:8-10) claims to prove the anchor is 'operator-controlled', and OPERATOR_RUNBOOK.md:26-29 tells the owner exactly that, while the runbook's two named residual owner responsibilities (:42-46) are the offline recovery key and a distinct runner identity, with no mention of anchor principal separation or the ack variable; a grep for 'self-owned'/'principal separation' across docs/ and the top-level markdown returns nothing outside bro_signature.py and the ledger. (b) 'the test suite at least pins the refusal' - it does: test_signature_authority.py:340-352 asserts the default refusal, so the finding's implication that the suite only blesses the weak posture is too strong; the accurate statement is that _write_pin_file (:441-461) sets the ack for every positive case and test_deploy_preflight.py:30-54 + :67-68 pins failures == [] for a self-owned anchor. P2 held: no adversary is required, but this removes the one compensating control (an operator noticing) that would make A5 tolerable, and it is a tool actively certifying the weak configuration as hardened - the difference between a documented weakness and a silent one, on a keystone ledger row.

**Reviewer re-read.** `bro_signature.py:257-263, :398, :499, :35-36 (the unimplemented 'callers are told so'); bro_deploy_preflight.py:72-81 (no ownership check), :49-56 (LEDGER_VARS omits BRO_EVIDENCE_HEAD_FLOOR), :123-132, :135-145 (GREEN on []); engine/docs/OPERATOR_RUNBOOK.md:26-29 and :42-46 (residual responsibilities omit principal separation); test_deploy_preflight.py:46-53, :67-68; test_signature_authority.py:441-461. Executed: check_operator_pin(env={ENV_PIN_FILE: <self-owned pin>}, root) -> [].`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_signature.py:35` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-16` · Windows: the receipt's evidence-chain head and containment evidence are still unmeasured caller values — F-02's original defect, alive on the Owner's platform, while the ledger says CLOSED

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 2 — the broker service account (it is the party that authors both values); no stronger adversary needed |
| **Location** | `apps/desktop/src-tauri/win-live/src/execution.rs:132` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:27 marks F-02 '✅ CLOSED (2026-08-06)' and describes the fix as a RECORDER that builds a hash-linked three-event chain per run, writes the head to --evidence-out, and a durable recorder-owned head counter — 'a missing or malformed chain REFUSES the turn — there is no config fallback left to fall back to.' That is the Linux kit only. On Windows there is no recorder principal at all: the four evidence_* values are provisioning constants copied out of config.json, and the containment evidence is a JSON document the BROKER writes about itself. The Windows supervisor accepts both as opaque caller input, stores them, and signs them into the 29-field attested evidence; the isolated signer only checks that the containment handle resolves in the store and never looks at its bytes. So the strongest-sounding fields of the Windows receipt carry zero information about the run — exactly the defect F-02 named.

**Code.**
```
"completed_at_ms": now,
                "evidence_final_event_hash": cfg.evidence_final_event_hash,
                "evidence_event_count": cfg.evidence_event_count,
                "evidence_last_sequence": cfg.evidence_last_sequence,
                "evidence_head_sequence": cfg.evidence_head_sequence,
```

**Walkthrough.**

1. Provisioning writes the constants once: win_provision.rs:112 `let evidence_final_event_hash = crypto::sha256_hex(b"brops-final-event-v1");` and win_provision.rs:206-208 `evidence_event_count: 3, evidence_last_sequence: 3, evidence_head_sequence: 3`. 2. The driver lifts them verbatim into the execution params: win_live_turn.rs:185-193 `let f = &cfg.facts; ... evidence_final_event_hash: f.evidence_final_event_hash.clone(), evidence_event_count: f.evidence_event_count, ...`. 3. The broker authors its OWN containment evidence in its own process: execution.rs:92-108 builds `{"protocol":"brops.containment-evidence.v1", "containment_mode": cfg.containment_mode, ...}` and content-addresses it — no recorder, no second principal, no measurement. 4. Both reach the supervisor through `complete-run`: execution.rs:124-138 `"produced": { "containment_evidence_handle": containment_handle, "evidence_final_event_hash": cfg.evidence_final_event_hash, "evidence_event_count": cfg.evidence_event_count, ... }`. 5. The supervisor validates SHAPE only — servers.rs:675-687 requires the handles to be lowercase hex64 and the ints to be `n >= 0`; it never compares them to anything it observed — then stores them (servers.rs:754-765). 6. attest_run copies them straight into the signed evidence: servers.rs:844 `("containment_evidence_handle", c.containment_evidence_handle.clone())`, servers.rs:848 `("evidence_final_event_hash", c.evidence_final_event_hash.clone())`, servers.rs:856-858 the three counters — then servers.rs:868-870 stamps decision=completed and signs those bytes. 7. The isolated signer resolves the containment handle only for existence: servers.rs:1020-1023 `derive("containment_evidence_handle", "containment_missing")`, which is `store_read` (servers.rs:67-77) — content address only, contents never parsed. 8. The four counters are copied verbatim into the signed 23-key envelope: servers.rs:1068, 1075-1077. 9. verify_and_accept verifies the signature over them and the driver prints `RESULT: trusted_verified(...) production_verified=true bound=true` (win_live_turn.rs:248). Every receipt this Windows deployment ever produces names evidence head 3, event count 3, last sequence 3 and the identical final_event_hash, regardless of what ran.

**Why it matters.** The single question asks whether a receipt can assert something the governed chain did not produce and bind. Here it demonstrably does: the receipt cryptographically attests a tamper-evident evidence chain and the existence of containment evidence for THIS execution, and on Windows neither is a measurement — one is a provisioning constant and the other is a self-description written by the very principal the containment is meant to constrain. An auditor cross-checking a Windows receipt's evidence head against a real recorder chain finds no correspondence, yet the turn reports production_verified=true. The ledger's F-02 row states the opposite without qualifying it to Linux.

**Adversarial review (P2).** Every step of the walkthrough reproduces in the file. I tried three refutations and all failed. (a) 'Maybe the supervisor recomputes the counters' — no: complete_run's ONLY validation of the three evidence ints is `Some(n) if n >= 0` (servers.rs:681-687), and there is no other entry point (attest_run's exact_keys at servers.rs:798 admits only op/run_id/execution_attempt_id, so nothing else can arrive). (b) 'Maybe the signer parses the containment document' — no: servers.rs:1020-1023 calls `derive("containment_evidence_handle", "containment_missing")`, which is store_read (servers.rs:67-77), a content-address existence check only; the bytes are dropped at servers.rs:1037 `let _ = (policy_bundle_sha256, containment_evidence_sha256)`. (c) 'Maybe the driver measures something' — no: win_live_turn.rs:185-193 lifts f.evidence_* verbatim from config.json, whose values win_provision.rs:112 and :206-208 write once as `sha256(b"brops-final-event-v1")` and 3/3/3. So all four evidence_* fields are deployment constants and the containment document is authored by the same process that produces the output (execution.rs:92-108), yet all five are signed into the 29-field attestation (servers.rs:844,848,856-858,868-870) and four are copied into the 23-key envelope (servers.rs:1068,1075-1077). AUDIT_LEDGER.md line 27 (F-02/F-18) marks this '✅ CLOSED (2026-08-06)' and describes a RECORDER-built hash-linked chain with '--evidence-out' and 'no config fallback left to fall back to' — that describes engine/Linux only, with no platform qualifier. DOWNGRADED P1→P2: this is not a forgery. The chain does produce, bind and sign the output; what is unsound is the SEMANTICS of 5 of 28 attested fields. It is confined to the lab kit (win_live_turn) and the demonstration seam (proof.rs:255-258 uses the same 3/3/3), platform_governed_execution_supported() stays false on Windows, and the shipped app cannot commit a trusted_verified row from either (repo.rs:1098 writes demonstration_verified_messages, and the badge projection at repo.rs:947-958 can only render 'trusted_verified' from a receipt_verification_attempts row this path never writes).

**Reviewer re-read.** `win-live/src/bin/win_provision.rs:112 (`sha256_hex(b"brops-final-event-v1")`), :206-208 (`evidence_event_count: 3, evidence_last_sequence: 3, evidence_head_sequence: 3`); win-live/src/bin/win_live_turn.rs:185-193; win-live/src/execution.rs:92-108 (broker authors its own containment doc), :124-138 (`produced` block, quoted lines 131-135 verified verbatim at 131-135); win-live/src/servers.rs:675-687 (shape-only validation), :754-765 (stored), :844/:848/:856-858 (signed), :868-870, :1020-1023 + :67-77 (existence-only resolve), :1037, :1068/:1075-1077; apps/desktop/AUDIT/AUDIT_LEDGER.md:27`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/execution.rs:132` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-17` · Windows: the pinned executor image digest is decorative — it is signed into the lease and never compared to the binary the driver actually spawns

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 3 — any principal with write access to <deploy>/config.json or the executor image; no code restricts that access and no check detects a violation (on Linux the equivalent is F-08's root-owned lease pins + the setuid launcher's pread re-hash) |
| **Location** | `apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:162` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** WIRING_LIVE_TRUST.md:77-79 states as a guarantee: 'Rebuilding the executor changes its SHA → you MUST re-provision, or the supervisor refuses to launch it. That refusal is the guarantee that the signed output came from the exact, pinned executor image.' No such refusal exists. `executor_executable_sha256` has exactly four uses in the whole tree — it is written by the provisioner, read into SupervisorConfig, and emitted in the lease JSON. It is never compared to any file. The supervisor launches nothing; the DRIVER launches `cfg.executor_path` with no digest check, no Authenticode check and no reference to the lease. win-broker's real `image_authenticode_valid` (win-broker/src/lib.rs:131) has no caller outside its own unit test.

**Code.**
```
let produce = move |_plan: &ExecutionPlan| -> Result<Vec<u8>, ()> {
            let mut cmd = std::process::Command::new(&executor_path);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW — no console flash on spawn
            }
            let out = cmd.output().map_err(|_| ())?;
```

**Walkthrough.**

1. Provisioning hashes the executor once: win_provision.rs:115-117 `let executor_sha = std::fs::read(&executor_path).map(|b| crypto::sha256_hex(&b)).unwrap_or_else(|_| crypto::sha256_hex(b"brops-windows-executor-v1"));` — note the fallback silently substitutes a placeholder digest if the file is unreadable. 2. It lands in config: win_provision.rs:210-213 `supervisor_cfg: SupervisorCfg { launcher_executable_sha256: launcher_sha, executor_executable_sha256: executor_sha }`. 3. The supervisor loads it: win_supervisor.rs:35. 4. Its ONLY consumer is the lease document: servers.rs:458-466 `fn lease_json(...) json!({ ..., "executor_executable_sha256": self.cfg.executor_executable_sha256 })`, whose canonical bytes are persisted (servers.rs:592) and published as `lease_handle` at completion (servers.rs:746). 5. The driver spawns whatever `cfg.executor_path` names — the quoted lines 162-169 — with no comparison to step 4 and no call to `image_authenticode_valid`. 6. Its stdout becomes the output verbatim: win_live_turn.rs:173 `Ok(out.stdout)` -> execution.rs:77-85 content-addresses it -> execution.rs:124-138 reports the handle -> servers.rs:698 stores it -> servers.rs:843 signs it. 7. Result: an operator (or anyone who can write the deployment tree) points `executor_path` at any binary, or overwrites win_executor.exe in place, and the chain signs that binary's output while the published lease attests the ORIGINAL digest. The driver prints `production_verified=true bound=true` (win_live_turn.rs:248). Grep proof: `executor_executable_sha256` appears only at win_provision.rs:212, win_supervisor.rs:35, config.rs:107, proof.rs:201, servers.rs:345 and servers.rs:464 — no comparison site exists.

**Why it matters.** This is the Windows analogue of F-08 (request↔output binding), which the ledger marks CLOSED on the strength of a root-owned lease pin plus a setuid launcher that re-hashes held fds before exec. The Windows kit has neither, and its own runbook tells the Owner the opposite. The receipt therefore attests 'output produced by the pinned executor image' when nothing on the platform ever checked that. It is the specific claim the Owner would rely on when following WIRING_LIVE_TRUST.md to wire a real model into win_executor.rs.

**Adversarial review (P2).** I re-ran the grep myself and the finding's central claim holds exactly: `executor_executable_sha256` appears in win-live at win_provision.rs:212, win_supervisor.rs:35, config.rs:107, proof.rs:201, servers.rs:345 and servers.rs:464 — six sites, every one a write or a copy into the lease JSON, zero comparisons. The launcher that DOES compare is Linux-only (launcher/src/main.rs:469 `open_executor_image(executor_image, &lease.executor_executable_sha256)`), and win-broker's real `image_authenticode_valid` (win-broker/src/lib.rs:131) has callers only inside its own #[cfg(test)] module (lib.rs:285, :309). The quoted driver code appears verbatim at win_live_turn.rs:162-169: `Command::new(&executor_path)` with no digest check, no Authenticode check, no reference to the lease. The documentation claim is worse than quoted: WIRING_LIVE_TRUST.md:34-36 says 'Rebuild → re-provision so the pinned hash matches, or the supervisor refuses to launch it' and :77-79 says 'That refusal is the guarantee that the signed output came from the exact, pinned executor image.' No such refusal exists anywhere. The silent-placeholder fallback at win_provision.rs:115-117 is also real. DOWNGRADED P1→P2 on adversary strength: on Windows the driver that spawns the executor IS the broker, i.e. the very principal whose output the pin was supposed to constrain — so against adversary 2 the pin was never a control, and against adversary 3 it requires deployment-tree write, the same missing-ACL precondition as W-04. It is a decorative attested field plus a false runbook guarantee, not a break of the crypto boundary, and the Windows gate is false.

**Reviewer re-read.** `win-live/src/bin/win_live_turn.rs:161-174 (quote verified at :162-169); win-live/src/bin/win_provision.rs:115-117, :210-213; win-live/src/servers.rs:458-466 (lease_json — sole consumer), :345; win-live/src/bin/win_supervisor.rs:35; win-broker/src/lib.rs:131 (no non-test caller; :285/:309 are tests); launcher/src/main.rs:469 (the Linux comparison that has no Windows twin); win-live/WIRING_LIVE_TRUST.md:34-36, :77-79`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:162` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-18` · Windows: the §2.5 TCB integrity floor is Linux-only and win_provision sets no ACL — the control the code itself names as 'THE REAL anti-rollback boundary' has no implementation anywhere

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 3 — the interactive login user, in any deployment whose root dir they can write; no code establishes or verifies the ACL that is supposed to make this out of scope |
| **Location** | `apps/desktop/src-tauri/win-live/src/tcb.rs:60` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** Two independent gaps compound. (a) `win_provision` never sets any ACL: it uses plain `std::fs::create_dir_all` (win_provision.rs:74-76) and `std::fs::write` (:136, :137, :145, :222), so the deployment dir, manifest, floor.json, config.json and the plaintext key seeds inherit whatever the parent grants. Grep for SetNamedSecurityInfo / SetFileSecurity / AddAccessAllowedAce / icacls across win-live and win-broker returns exactly ONE hit — a line of prose in WINDOWS_ANTIROLLBACK_HARDENING.md:44. (b) The §2.5 floor that would DETECT a violated deployment is Linux-only: broker/src/tcb_probe.rs:15-17 says 'It is Linux-only because owner/mode/O_NOFOLLOW are the facts the floor is stated in', the probe is `#[cfg(target_os = "linux")]` (tcb_probe.rs:31), and `verify_deployment_tcb` has callers only in broker/src/main.rs:281 and proof/src/bin/live_turn.rs:201 — nothing in win-live. So on Windows there is neither the boundary nor the detector. Worse, the two Windows documents contradict each other: WINDOWS_ANTIROLLBACK_HARDENING.md:42-45 lists 'Provisioning-enforced ACL (primary)' as a still-REQUIRED prerequisite, while proof/WINDOWS_BROKER_AUDIT_VERDICT.md:63-68 marks the same condition 'closed vs the in-scope (login-user) adversary ... the deploy ACL grants write only to the broker principal and denies the interactive login user.'

**Code.**
```
/// THE REAL anti-rollback boundary is the OS write-protection on the deployment directory: `floor.json` must
/// be writable ONLY by the broker service principal (a dedicated service account whose SID is NOT the
/// interactive login and NOT the in-scope sidecar). In the cross-account deployment that is the shipped
/// target, the in-scope attacker cannot write `floor.json` at all, so the rollback is out of scope. Provision
/// MUST enforce that ACL;
```

**Walkthrough.**

1. FLOOR_SEED_HEX is a public source constant (tcb.rs:70-71) and the code says so plainly. 2. `load_verified_floor` (resolver.rs:202-218) verifies floor.json under `tcb::floor_public_key_hex()` — derived from that same public seed. 3. An adversary who can write the deployment dir recomputes `floor_signing_key()` (tcb.rs:73-76), calls `signed_floor_file()` (resolver.rs:152-160) over a lowered `{highest_epoch, highest_hash}`, and writes floor.json. 4. win_live_turn.rs:111-114 loads it and the signature verifies. 5. resolver.rs:257-262 `check_and_advance(&floor, &self.manifest)` now passes for an OLDER root-signed manifest at that lower epoch, reviving a since-revoked production signer key. 6. `resolve_production_key` (resolver.rs:267) resolves it, verify_and_accept verifies under it, and win_live_turn.rs:248 prints production_verified=true — with no offline root involved. 7. The Linux path would have refused this deployment at broker/src/main.rs:281 via verify_deployment_tcb (unreadable/malformed/violated manifest ⇒ refuse); on Windows nothing runs that check, so the violated deployment serves normally.

**Why it matters.** The AUDIT_LEDGER F-10 row says the §2.5 floor 'now has a real probe, real callers, and a real manifest to enforce' with no platform qualifier, and the F-06/F-13/F-14 row says the anti-rollback remediation covers 'both platforms'. On Windows the probe does not compile, the callers do not exist, and the ACL that is documented as the true boundary is set by no code and verified by no check. The rollback is out of scope only if an operator manually applied an ACL the tooling never applies — which is an operator convention, not a control.

**Adversarial review (P2).** Both halves verified. (a) I grepped SetNamedSecurityInfo|SetFileSecurity|AddAccessAllowedAce|SetSecurityInfo|InitializeAcl|icacls across win-live and win-broker: exactly ONE hit, WINDOWS_ANTIROLLBACK_HARDENING.md:44, a line of prose. win_provision uses bare `std::fs::create_dir_all` (win_provision.rs:74-76) and `std::fs::write` (:136,:137,:145,:222) — the deployment dir, manifest, floor.json, config.json and the plaintext hex seeds (:88-90) inherit the parent ACL. (b) verify_deployment_tcb has exactly two callers, broker/src/main.rs:281 and proof/src/bin/live_turn.rs:201 — both Linux — and nothing in win-live. The rollback walk itself reproduces: FLOOR_SEED_HEX is public source (tcb.rs:70-71), floor_signing_key() is public (tcb.rs:73-76), signed_floor_file() is `pub` (resolver.rs:152-160), load_verified_floor verifies under that same public-derived key (resolver.rs:214), and resolver.rs:257-262 then runs check_and_advance against the lowered floor. The doc contradiction is real: WINDOWS_ANTIROLLBACK_HARDENING.md:42-45 lists the provisioning-enforced ACL as still REQUIRED, while WINDOWS_BROKER_AUDIT_VERDICT.md:63-68 asserts 'the deploy ACL grants write only to the broker principal and denies the interactive login user' as accomplished fact. HELD AT P2, not raised: the attack is compound — it needs deployment-dir write AND a retained older root-signed manifest AND the corresponding (revoked) signer private key — and tcb.rs:50-71 discloses it accurately in the code itself. Its value is that the boundary the code names as 'THE REAL anti-rollback boundary' is set by no code and checked by no code on the platform it applies to, and one gate-decision document says it is already in place. Not INVALID: adversary 3 is explicitly in scope and this is precisely the control that is supposed to exclude them.

**Reviewer re-read.** `win-live/src/tcb.rs:59-65 (quote verified at :60-64), :70-76; win-live/src/bin/win_provision.rs:74-76, :88-90, :136-137, :145, :222 (no ACL call anywhere); win-live/src/resolver.rs:152-160, :202-218, :252-262; broker/src/tcb_probe.rs:15-17, :31, :115; broker/src/main.rs:281 and proof/src/bin/live_turn.rs:201 (the only two callers, both Linux); win-live/WINDOWS_ANTIROLLBACK_HARDENING.md:40-45 vs proof/WINDOWS_BROKER_AUDIT_VERDICT.md:63-68`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/tcb.rs:60` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-19` · The Windows audit verdict document asserts two facts that the code at this commit contradicts

| | |
|---|---|
| **Severity** | P2 |
| **Adversary needed** | 1 — none required; this is a documentation-integrity defect that misdirects the reader of the evidence, including the Owner's gate decision |
| **Location** | `apps/desktop/src-tauri/win-live/proof/WINDOWS_BROKER_AUDIT_VERDICT.md:10` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** Claim A — 'the shipped desktop app ... does not even link this kit' — is false at this commit. apps/desktop/src-tauri/Cargo.toml:48 declares `brops-win-live = { path = "win-live" }` as a dependency of the shipped Tauri host crate, and two shipped Tauri commands call into it: src/governed_selftest.rs:118 and src/commands.rs:2033, both `brops_win_live::proof::in_process_turn_produce(...)`. Claim B — the findings table at line 41, '`attest-run` bound to a supervisor-minted `accept-open` lease (one-time consume)' — is false: attest_run (servers.rs:797-881) takes a read-only lock (`let accepted = self.accepted.lock()`, :810), consumes nothing, and mutates no state, so it is idempotent and repeatable, not one-time.

**Code.**
```
Nothing an in-scope adversary can do forges a production `trusted_verified`, and the shipped desktop app
stays fail-closed on Windows (it does not even link this kit).
```

**Walkthrough.**

1. Read WINDOWS_BROKER_AUDIT_VERDICT.md:10-13 — the stated basis for the GREEN verdict is that the kit is not on any shipped path. 2. Open apps/desktop/src-tauri/Cargo.toml:48 — `brops-win-live = { path = "win-live" }`. 3. Open apps/desktop/src-tauri/src/commands.rs:2033 — the shipped `demonstration_verified_reply` Tauri command calls `brops_win_live::proof::in_process_turn_produce`. 4. Open src/governed_selftest.rs:118 — the shipped `governed_trust_selftest` Tauri command does the same. 5. For claim B, read servers.rs:810-881 end to end: no `remove`, no state write, no consume flag; calling attest-run twice on the same COMPLETED attempt returns byte-identical evidence and signature both times. NOTE, in fairness: I checked whether claim A's error is load-bearing for the SAFETY conclusion and it is NOT — the shipped seam pins the DEMONSTRATION anchor (proof.rs:173-176) and commits through repo.rs:1098 into the separate demonstration_verified_messages table, so it genuinely cannot render a production green (see my blocker verdict). The document's conclusion survives; its stated evidence does not.

**Why it matters.** The brief's instruction is that a .md verdict is a claim, not evidence. This is the Windows kit's top-level GREEN verdict, cited as the basis for how much scrutiny the Windows leg needs, and its central premise about the shipped app is checkably wrong. A reader who accepts 'it does not even link this kit' would never look at the two shipped commands that do.

**Adversarial review (P2).** Both claims are false at this commit and I verified each independently rather than trusting the quote. Claim A: WINDOWS_BROKER_AUDIT_VERDICT.md:10-11 reads verbatim 'the shipped desktop app stays fail-closed on Windows (it does not even link this kit)', and line 46 repeats it as 'Shipped honesty | app does not link the kit'. apps/desktop/src-tauri/Cargo.toml:47-48 declares `[target.'cfg(windows)'.dependencies]` / `brops-win-live = { path = "win-live" }` on the shipped `brops` Tauri host crate, and my own grep for brops_win_live outside win-live/ returns exactly two call sites, both shipped Tauri commands: src/commands.rs:2033 and src/governed_selftest.rs:118, both `brops_win_live::proof::in_process_turn_produce`. On a Windows build the kit IS linked. Claim B: servers.rs:797-881 read end to end — attest_run takes an immutable `self.accepted.lock()` at :810, performs no remove, sets no consumed flag and mutates nothing; two calls on the same COMPLETED attempt return byte-identical evidence and signature. 'One-time consume' is false; 'bound to a supervisor-minted lease' is true. I also confirmed the finding's fairness note: the shipped seam pins the DEMO anchor (proof.rs:173-176, :276-280) and commits via repo.rs:1098 into demonstration_verified_messages, and the badge projection (repo.rs:947-958) cannot render 'trusted_verified' without a receipt_verification_attempts row that path never writes — so the document's SAFETY conclusion survives while its stated evidence does not. HELD AT P2 (not lowered to P3): this is the top-level Windows GREEN verdict cited as the basis for how much scrutiny the Windows leg needs before a gate flip, and a reader who accepts 'does not even link this kit' would never open the two shipped commands that do. I found a third overstatement in the same table while checking: line 44 claims 'seeds not plaintext at rest', but win_provision.rs:26-28 and :88-90 write 64-char plaintext hex and seedstore.rs only seals on first read (TOFU).

**Reviewer re-read.** `proof/WINDOWS_BROKER_AUDIT_VERDICT.md:10-11 (quote verified verbatim), :41, :44, :46; apps/desktop/src-tauri/Cargo.toml:47-48; src/commands.rs:2033; src/governed_selftest.rs:118; win-live/src/servers.rs:797-881 (esp. :810 read-only lock, no consume); win-live/src/proof.rs:169-176, :276-288; core/src/repo.rs:947-958, :1098-1123; win-live/src/bin/win_provision.rs:26-28, :88-90`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/proof/WINDOWS_BROKER_AUDIT_VERDICT.md:10` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-20` · The supervisor lease still does not reach the setuid launcher, so one lease does not authorize one privileged execution — it authorizes one recorded completion, and the broker may run the executor as many times as it likes and attest the run it prefers

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account (uid 5001). Requires no forgery of any root-owned file. |
| **Location** | `apps/desktop/src-tauri/launcher/src/main.rs:424` |
| **Group** | `f01-oracle` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The launcher's authorization input is the root-owned key=value file at `$TCB/executor.lease` (provisioned `chown 0:0; chmod 0644` at run_live_turn.sh:141), not the supervisor lease. The supervisor's `execution_attempt_id`, `lease_id` and lease window never cross into the launcher, and the launcher's only per-invocation gate is the §2.7 invoker check that the real uid is the recorder (main.rs:427-431) — a check the broker satisfies for free, because the production path spawns the recorder through `sudo -n -u brops-recorder` by design (chain_executor.rs:755-761, provision_keys.py:298). So the number of privileged executions per supervisor lease is unbounded.

**Code.**
```
//     file so a non-TCB principal cannot forge those pins (same §2.5 floor as the image; the
        //     supervisor-signed lease that also binds turn/nonce freshness is the documented next slice).
        let lease = read_and_verify_lease(lease_handle)?;
```

**Walkthrough.**

(1) Broker obtains one lease for attempt A (accept-open) and passes the gate (launch-gate), reaching EXECUTION_STARTING. (2) Broker spawns the recorder -> setuid launcher -> executor chain N times. Each spawn is judged only by `read_and_verify_lease` over the static root-owned file (main.rs:424) plus `verify_invoker_is_recorder` (main.rs:431); neither consults attempt A, and the supervisor is never contacted, so nothing decrements or consumes anything. (3) The broker reads the N captured outputs, picks the one it likes, writes it to the store (chain_executor.rs:819-821), and sends exactly one `complete-run` (server:504-541). The write-once PK (supervisor_ledger.sql:129) is satisfied because only one completion is ever offered. (4) attest-run signs evidence naming the chosen run's output_handle; the other N-1 executions leave no trace in the ledger at all.

**Why it matters.** chain_executor.rs:20 states "The lease authorizes exactly one privileged execution", and governed_supervisor.py:26-29 sells the acceptance record as making "one signed challenge worth exactly one execution attempt". What the shipped code enforces is one recorded COMPLETION per challenge, which is a weaker and different property: it leaves the broker free to sample the governed executor repeatedly and attest only the output it prefers, entirely inside the governed path, with the receipt asserting a single clean run. I am filing this at P3 and explicitly NOT as a refutation of F-23: the AUDIT_LEDGER's F-23 sentence (launch-gate takes only the attempt id, the caller no longer presents the lease it is judged against) is literally true, I attacked it five ways and it held, and the file lease itself is root-owned so no in-scope adversary can forge its pins. This is the residual the launcher's own comment at main.rs:423 still names as "the documented next slice", recorded so it is not lost when F-23 is marked closed. Linux only; on Windows the equivalent path is the win-live proof kit.

**Adversarial review (P3).** Verified and correctly self-limited. The quote is verbatim at launcher/src/main.rs:422-424, including the comment that still names 'the supervisor-signed lease that also binds turn/nonce freshness' as the next slice. I confirmed the launcher's whole authorization surface: read_and_verify_lease(lease_handle) at :424 over the key=value file provisioned chown 0:0 / chmod 0644 at run_live_turn.sh:131-141, whose fields are recorder_uid/recorder_gid/executor_uid/executor_gid/executor_executable_sha256 + the three store-input digests — no lease_id, no execution_attempt_id, no expiry, no nonce; then verify_invoker_is_recorder(lease.recorder_uid, lease.recorder_gid) at :431, which the broker satisfies for free because sudoers grants exactly 'BROKER_USER ALL=(RECORDER_USER) NOPASSWD: $BIN/governed_recorder' (run_live_turn.sh:198-200). Nothing in the launcher path contacts the supervisor and nothing is consumed, so N spawns per lease is correct, and the write-once completion PK (supervisor_ledger.sql:128-129) only bounds recorded COMPLETIONS, not executions — the finding's distinction is exact. It contradicts the doc claim at chain_executor.rs:20 ('The lease authorizes exactly one privileged execution'). P3 is the right level and I would not raise it: the file lease is root-owned so no in-scope adversary forges its pins; the extra capability (sample the executor repeatedly, attest the preferred output) is strictly subsumed by F-01-R1, which lets the same adversary author the output outright without running the executor at all; and it is Linux-only. Its value is as a standing residual that becomes load-bearing the moment F-01-R1 is fixed. Caveat for the Owner: F-23 being CONFIRMED_CLOSED must not be read as 'one lease = one privileged execution' — only as 'the caller no longer chooses the expiry it is judged against'.

**Reviewer re-read.** `apps/desktop/src-tauri/launcher/src/main.rs:417-431 (quote verified at :422-424; invoker gate at :431); engine/ci/live/run_live_turn.sh:131-141 (lease file content + chown 0:0 chmod 0644), :198-200 (sudoers recorder grant); apps/desktop/src-tauri/broker/src/chain_executor.rs:20 (the 'exactly one privileged execution' claim), :786-800 (recorder spawn), :852-869 (single complete-run); engine/runtime/supervisor_ledger.sql:123-129 (write-once PK bounds completions, not executions)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/launcher/src/main.rs:424` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-21` · The broker names the recorder's 'private' head-sequence counter directory: the sudoers rule places no restriction on arguments and next_head_sequence does not check that the directory is recorder-owned

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001) |
| **Location** | `apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:54` |
| **Group** | `f02-evidence` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:27 states head_sequence 'comes from a recorder-owned durable counter (recorder-state/, 0700) so it grows across runs, which is what the floor needs to order anything', and run_live_turn.sh:192-195 comments 'if another uid could rewind it, the supervisor's anti-rollback floor would again be comparing a number the attacker chose. Recorder-private.' The 0700 directory is real, but it is not the directory the recorder is obliged to use: the path arrives as an unauthenticated command-line argument from the broker, and next_head_sequence performs no ownership, mode, or path check on it before read-increment-writing (contrast the setuid launcher, which fstat-verifies the lease is root-owned before trusting its pins).

**Code.**
```
fn next_head_sequence(dir: &str) -> Option<u64> {
        let path = std::path::Path::new(dir).join("evidence-head-sequence.json");
        let current: u64 = match std::fs::read_to_string(&path) {
```

**Walkthrough.**

1. run_live_turn.sh:199 writes the entire sudo authorization: `echo "$BROKER_USER ALL=($RECORDER_USER) NOPASSWD: $BIN/governed_recorder" > "$SUDOERS"`. There is no argument allowlist, so the broker may invoke the recorder as the recorder uid with ANY argv. 2. governed_recorder.rs:109 takes the counter directory verbatim: `let evidence_state = flag(args, "--evidence-state");`. 3. governed_recorder.rs:311-319 passes it straight to next_head_sequence with no validation. 4. next_head_sequence (54-70) joins 'evidence-head-sequence.json' onto whatever string it was given, reads it, adds one, calls create_dir_all(dir), and writes. No stat, no st_uid comparison to geteuid(), no mode check, no canonicalization, no comparison against a pinned path. 5. Concrete attack, entirely within the broker's granted authority: the broker creates /opt/brops-live/report/st (report dir is 2770 group brops-report and the broker is a member — run_live_turn.sh:177,181), chmods it 0777, writes {"head_sequence": 4000000000} into st/evidence-head-sequence.json, then spawns `sudo -n -u brops-recorder /opt/brops-live/bin/governed_recorder --store ... --launcher ... --executor ... --lease ... --out ... --containment-out ... --evidence-out ... --evidence-state /opt/brops-live/report/st`. 6. The run is otherwise completely genuine: the real launcher runs, the real executor produces the real output, exit 0. The recorder reads 4000000000, writes 4000000001, and stamps head_sequence=4000000001 into the chain (governed_recorder.rs:364). 7. chain_executor.rs:855 parses it (positive i64 — accepted), 881 reports it, and governed_supervisor_ledger.py:626-675 advances the durable floor to 4000000001. 8. Consequence: the head that the receipt attests and that the anti-rollback floor is anchored on is a number the broker chose, and every subsequent honest run — whose real recorder-state counter is at 1, 2, 3 — presents a lower head and is refused with StaleEvidence (governed_supervisor_ledger.py:661-662), permanently bricking that (install_id, task_id) for the genuine chain. 9. Refutation attempted and failed: I looked for a TCB pin on the recorder's arguments (build_tcb_pin_manifest.py pins the sudoers FILE and the binaries, not argv), for a config-side path pin (provision_keys.py:401 writes evidence_state_dir into the broker's config, but the broker process is the thing being modelled as hostile and nothing re-checks the value it actually passes), and for a recorder-side ownership check (there is none, at any line of governed_recorder.rs).

**Why it matters.** The blocker's claim is that the head sequence is anchored in state the reporting party cannot influence — that is the entire reason a durable counter was introduced. Because the counter's location is a broker-supplied argument with no ownership check, the anchor moves wherever the broker points it, and the 0700 provisioning that the ledger cites as the guarantee guards a directory the attacker is free not to use. The control exists but does not bind the principal it names.

**Adversarial review (P3).** Every step is real. run_live_turn.sh:199 writes `echo "$BROKER_USER ALL=($RECORDER_USER) NOPASSWD: $BIN/governed_recorder" > "$SUDOERS"` with no argument allowlist. governed_recorder.rs:109 takes `--evidence-state` verbatim via flag(); 311-319 passes it straight to next_head_sequence with no validation; next_head_sequence (54-70) joins the filename onto whatever string it got, read-increment-writes, and does no stat, no st_uid vs geteuid() comparison, no mode check, no canonicalization, no pin — in contrast to the setuid launcher's fstat-verified root-owned lease. The report dir is group brops-report with the broker a member and mode 2770 (run_live_turn.sh:177,181), so the broker really can create a recorder-writable directory to point at. I could not find any control that binds the argv: build_tcb_pin_manifest.py pins the sudoers FILE and the binaries, not the arguments, and provision_keys.py:401 puts evidence_state_dir in the broker's own config, which is not a constraint on a hostile broker. So the ledger's 'recorder-owned durable counter (recorder-state/, 0700)' guarantee does protect that directory but does not oblige the recorder to use it — the claim over-reaches, exactly as stated. Severity lowered from P2 to P3 for one reason: it is strictly subsumed. Adversary #2 is the broker ACCOUNT, i.e. arbitrary code as uid 5001, and that account is SO_PEERCRED-allowlisted on the supervisor lifecycle socket. Such an attacker does not need to relocate the counter to choose the head — it can send `complete-run` with any head it likes (A-04), which the supervisor accepts on shape alone (governed_supervisor_ledger.py:589-623). Relocating the counter is a more convoluted route to a capability the same adversary already has directly, and the floor-poisoning/bricking consequence in step 8 is reachable the same easier way. Real defect, correctly described, but marginal marginal-impact.

**Reviewer re-read.** `engine/ci/live/run_live_turn.sh:177,181,192-195,199; governed_recorder.rs:54-70,109,311-319,364; chain_executor.rs:783-786; provision_keys.py:211-213,397-401; governed_supervisor_ledger.py:589-623,661-677`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:54` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-22` · A missing execution.evidence_state_dir config key silently relocates the monotonic counter to the recorder's working directory instead of refusing

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 3 — the interactive login user (or whichever principal owns the resulting working directory); reachable only on a deployment whose config omits the key |
| **Location** | `apps/desktop/src-tauri/broker/src/main.rs:376` |
| **Group** | `f02-evidence` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The production broker (main.rs:376) and the live driver (live_turn.rs:383) both default a missing evidence_state_dir to the empty string rather than refusing, unlike recorder_command which is required (live_turn.rs:365-368 returns config_missing_recorder_command). The recorder then treats "" as a valid directory: Path::new("").join(...) yields the RELATIVE path evidence-head-sequence.json, and std::fs::create_dir_all("") returns Ok, so the counter is created in the recorder process's inherited working directory.

**Code.**
```
evidence_state_dir: s(&["execution", "evidence_state_dir"]).unwrap_or_default(),
```

**Walkthrough.**

1. main.rs:376 / live_turn.rs:383 produce evidence_state_dir = "" when the key is absent. 2. chain_executor.rs:785-786 still passes `--evidence-state ""` to the recorder. 3. governed_recorder.rs:311-313 sees Some("") — not None — so it does NOT take the refusal branch at 318 ('recorder needs --evidence-state with --evidence-out'). 4. next_head_sequence("") at governed_recorder.rs:55 computes Path::new("").join("evidence-head-sequence.json") = the relative path evidence-head-sequence.json; line 65's create_dir_all("") returns Ok (std short-circuits the empty path); lines 66-68 write and rename in the CWD the recorder inherited through sudo. 5. The counter therefore lives outside the 0700 recorder-private directory, in a location whose ownership and mode are whatever the broker's working directory happens to be, and it restarts at 1 whenever that directory changes. 6. The turn still succeeds — the degradation is silent. Note this is a config-conditional weakness: the shipped provisioner does write the key (provision_keys.py:401), so the as-provisioned Linux kit is not affected; the finding is that the fail-closed posture the ledger claims ('a missing or malformed chain REFUSES the turn') does not extend to a missing counter location.

**Why it matters.** The durable counter is the only thing making head_sequence monotonic across runs, and its privacy is the stated guarantee. A silently-defaulted empty path converts a security-critical location into an accident of process working directory, on the same code path that the ledger describes as having no fallback left. It is a small hole, but it is the same failure mode — an unwrap_or_default standing in for a refusal — that produced the original blocker.

**Adversarial review (P3).** Confirmed against the source. main.rs:376 is `evidence_state_dir: s(&["execution", "evidence_state_dir"]).unwrap_or_default(),` and live_turn.rs:383 is the same, while the immediately adjacent recorder_command in live_turn.rs:365-368 DOES refuse (`_ => return blocked("config_missing_recorder_command")`), so the asymmetry is real and in the same struct literal. chain_executor.rs:785-786 passes `--evidence-state` with the empty string as its own argv element regardless. governed_recorder.rs:36-38 flag() returns Some("") — not None — so the refusal branch at 318 is not taken, and next_head_sequence("") at 54-68 computes Path::new("").join("evidence-head-sequence.json") = a relative path, create_dir_all("") returns Ok (Rust std short-circuits the empty path), and the counter is written into the recorder's inherited CWD. Two things keep it at P3, both of which the finding itself concedes or which I add: (a) it is config-conditional and the shipped provisioner does write the key (provision_keys.py:211-213,401), so the as-provisioned Linux kit is unaffected; (b) in the common case the inherited CWD is not recorder-writable, the write fails, `.ok()?` yields None and governed_recorder.rs:313-315 refuses — so the silent-degradation path needs the CWD to happen to be writable (e.g. a world-writable temp dir), in which case the harm is real: the counter lands somewhere adversary #3 or #4 can rewind. Genuine fail-open gap in a fail-closed claim, small blast radius.

**Reviewer re-read.** `broker/src/main.rs:376; proof/src/bin/live_turn.rs:364-368,383; chain_executor.rs:783-786; governed_recorder.rs:36-38,54-70,311-319; provision_keys.py:211-213,401`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/main.rs:376` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-23` · The launcher's second TCB owner is the hardcoded uid 500, so any account that happens to hold uid 500 can author a lease — and therefore choose the request pins, the executor image pin and the drop target

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 4 — any other unprivileged local account, but ONLY if that account's uid is exactly 500. No such account exists in the live kit (service uids are 5001-5007, provision_keys.py DEFAULT_UIDS), and the kit's own TCB manifest declares brops_admin = 0 (build_tcb_pin_manifest.py:110). So this is latent, not live here. |
| **Location** | `apps/desktop/src-tauri/launcher/src/main.rs:395` |
| **Group** | `f08-bytes` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** image_owner_mode_ok (main.rs:222-227) treats uid 500 as a TCB owner for BOTH the lease file (main.rs:497) and the executor image (main.rs:780). The constant is a compile-time literal with an unfulfilled TODO to bind it to the manifest's owner_uids, and it is never reconciled with the deployment's actual brops-admin identity — the live kit's manifest says brops_admin = 0, so on this deployment uid 500 is a TCB owner that the TCB manifest does not acknowledge.

**Code.**
```
// The dedicated `brops-admin` TCB owner uid (§2.5): root(0) or brops-admin may own the executor image
// AND the lease file. TODO: bind from the root-owned TcbPinManifest (`owner_uids[BropsAdmin]`); pinned
// as the boundary constant so the fstat'd-fd owner check accepts exactly the two TCB principals.
const TCB_OWNER_BROPS_ADMIN_UID: u32 = 500;
```

**Walkthrough.**

Assume a box where uid 500 is assigned to some ordinary account (Debian's system-uid range is 100-999; 500 is not allocated by adduser by default, but a hand-provisioned or migrated box can hold it). STEP 1: that account writes /home/u500/fake.lease mode 0644 containing the eight required keys — recorder_uid/gid = the real recorder, executor_uid/gid = any non-zero pair distinct from the recorder, executor_executable_sha256 = sha256 of its OWN binary, and system/history/generation_config_sha256 = digests of its own inputs. parse_lease (main.rs:290-338) accepts it. STEP 2: the broker (or anything that can spawn the recorder, run_live_turn.sh:199) passes --lease /home/u500/fake.lease and --executor /home/u500/evil.bin. STEP 3: read_and_verify_lease fstat's the OPENED fd and calls image_owner_mode_ok(st_mode, 500, 500) -> true (main.rs:497). STEP 4: open_executor_image applies the identical predicate to the attacker's binary at main.rs:780 -> true, and its hash matches the attacker's own pin at main.rs:797. STEP 5: fexecve runs attacker code as the executor uid with the chain attesting a normal governed execution. I did NOT find a uid-500 account in this deployment, so I am reporting this as a latent weakening of the same guard, not a live path.

**Why it matters.** The lease is the sole root of the F-08 pin: everything the launcher enforces about the request, the image and the drop target comes from it. Its authenticity rests entirely on this owner predicate, and half of that predicate is a hardcoded constant with a TODO rather than the manifest value the §2.5 floor actually measures. It costs nothing to bind it to owner_uids[BropsAdmin], and leaving it as 500 means the TCB boundary the launcher enforces is not the TCB boundary the manifest declares.

**Adversarial review (P3).** The code facts are all verified and the divergence is real, but it is latent hardening, not a live path on this deployment — which is exactly how the finding reports it, so I am not lowering it further and not calling it INVALID. Verified: the quoted comment + `const TCB_OWNER_BROPS_ADMIN_UID: u32 = 500;` is verbatim at main.rs:392-395 with the 'TODO: bind from the root-owned TcbPinManifest (owner_uids[BropsAdmin])' unfulfilled; image_owner_mode_ok(main.rs:222-227) accepts st_uid == 0 || st_uid == brops_admin_uid and is applied to BOTH the lease fd (main.rs:497) and the executor image fd (main.rs:780); parse_lease (main.rs:290-338) would accept the described body. The deployment divergence is confirmed: build_tcb_pin_manifest.py:111 emits owner_uids {"root":0,"brops_admin":0} with the comment 'This kit has no separate brops-admin principal', so the launcher enforces a TCB principal (uid 500) the manifest does not declare, and nothing reconciles the two. Why it is only P3: provision_keys.py:103-110 DEFAULT_UIDS are 5001-5007 with no uid 500, and the walkthrough's own first line is 'Assume a box where uid 500 is assigned' — a state I could not demonstrate in the target snapshot. So this fails the concrete-attack bar for anything higher, but it is a genuine, cheap-to-fix weakening of the sole root of the F-08 pin (the lease authenticity predicate). No adversary-strength downgrade applies: adversary #4 is in scope; the attack is gated on deployment configuration, not on an out-of-scope privilege.

**Reviewer re-read.** `apps/desktop/src-tauri/launcher/src/main.rs:392-395 (quote verified verbatim), 222-227 (image_owner_mode_ok), 497 (lease fd), 780 (image fd), 290-338 (parse_lease accepts the forged body's shape); engine/ci/live/build_tcb_pin_manifest.py:108-111 (owner_uids brops_admin=0, 'no separate brops-admin principal'); engine/ci/live/provision_keys.py:103-110 (DEFAULT_UIDS 5001-5007, no 500); engine/ci/live/run_live_turn.sh:199 (broker may spawn the recorder with arbitrary --lease/--executor arguments).`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/launcher/src/main.rs:395` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-24` · On the Windows/Rust leg F-09 is entirely unremediated: supervisor_ledger.rs still has zero non-test callers and the Windows supervisor twin has no evidence floor at all

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker/driver principal on the Windows kit. Also relevant to any reader of AUDIT_LEDGER.md, since the row's unqualified wording asserts a property that does not exist on this platform. |
| **Location** | `apps/desktop/src-tauri/win-live/src/servers.rs:766` |
| **Group** | `f09-cas` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The remediation wired the PYTHON supervisor only. The Rust `brops_core::supervisor_ledger` module — which is where the original independent audit located F-09 (supervisor_ledger.rs:310) — still has exactly one referenced symbol outside its own file: `create_schema`. `evidence_floor_cas`, `accept_prepare`, `advance`, `gate_and_start`, `enqueue_terminal`, `pending_outbox` and `lease_launch_gate` remain dead code, unchanged. The Windows twin that actually serves the ops (win-live/src/servers.rs) reimplements the lifecycle in-process and simply has no floor: complete_run contains no anti-rollback or anti-fork check whatsoever.

**Code.**
```
match &a.completion {
            // Write-once: an identical retry is idempotent, any divergence is refused. A second
            // execution cannot rewrite what was already attested.
            Some(existing) => {
                if *existing != completion {
                    return refuse("complete-run", "completion_conflict");
                }
                ...
            }
            None => {
                if a.state != ST_EXECUTING {
                    return refuse("complete-run", "illegal_state");
                }
                a.completion = Some(completion);
                a.state = ST_COMPLETED;
            }
        }
```

**Walkthrough.**

STEP 1 — establish that the Rust ledger is still dead. Repo-wide grep across every .rs file for `supervisor_ledger::|evidence_floor_cas|accept_prepare|gate_and_start|enqueue_terminal|pending_outbox|lease_launch_gate`, excluding core/src/supervisor_ledger.rs itself, returns exactly four hits, all the same symbol: apps/desktop/src-tauri/broker/src/main.rs:69, apps/desktop/src-tauri/proof/src/bin/live_turn.rs:159, apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:61, apps/desktop/src-tauri/win-live/src/proof.rs:83 — every one of them `create_schema`. This is verbatim the original F-09 finding text.

STEP 2 — confirm the schema is created but never used. win_live_turn.rs:203-209 opens `Connection::open_in_memory()` and calls init_schema, which includes `brops_core::supervisor_ledger::create_schema(conn)` (win_live_turn.rs:61). No handle to that connection is ever passed to the supervisor: the supervisor the chain talks to is a named-pipe hop into brops_win_live::servers::Supervisor (win_live_turn.rs:156-160, 175-184), whose state is `Mutex<BTreeMap<String, Acceptance>>` (servers.rs:426) and `Mutex<BTreeMap<String, String>>` (servers.rs:429). The governed_evidence_head_floor table is created empty and never read or written.

STEP 3 — confirm the twin has no floor. Supervisor::complete_run runs from servers.rs:660 to 789. It shape-checks `produced` (672-687), publishes the three derived artifacts (701-752), builds a Completion (754-765), and write-once-commits it (766-785). There is no SELECT, no comparison, and no mention of head_sequence beyond copying ints[3] into the struct at line 764. Nothing refuses a lower head.

STEP 4 — confirm the value being carried is a deployment constant, so there is not even a de-facto floor. The four evidence values reaching complete-run come from `cfg.facts` (win_live_turn.rs:190-193 -> ExecutionParams -> execution.rs:132-135), and win_provision.rs:112 and :205-208 set them to `crypto::sha256_hex(b"brops-final-event-v1")` with head_sequence: 3 for every run of the deployment. proof.rs:147 and :255-258 do the same.

WRONG OUTPUT: on the Windows kit every governed turn attests the identical evidence head, forever, and no code path could refuse a rolled-back or forked one because no code path examines it.

REFUTATION ATTEMPTS: (a) I searched for any other Rust floor implementation — grep for `evidence_floor|head_floor|StaleEvidence|stale_evidence|EvidenceFork|evidence_fork` across all .rs files hits ONLY core/src/supervisor_ledger.rs (definition, doc comments, and its #[cfg(test)] block at 1327-1362). (b) I checked whether win_live_turn's `load_verified_floor` (win_live_turn.rs:111-114) is the evidence floor — it is not; that is the KEY MANIFEST anti-rollback floor (epoch), a different control resolved by brops_win_live::resolver. (c) I checked whether the shipped desktop is affected — it is not on this leg: brops-broker defaults to UpstreamBlockedExecutor unless BROPS_BROKER_CONFIG is set (broker/src/main.rs:226-231), and win-broker/src/lib.rs:10 states platform_governed_execution_supported() stays false. So this is LAB-KIT scope, not SHIPPED-APP.

**Why it matters.** AUDIT_LEDGER.md:25 says of F-09 "Both halves now run: ... the anti-rollback/anti-fork floor runs on every complete-run", with no platform qualifier, while the F-01 row two lines above explicitly boasts that its fix landed "in BOTH supervisors (Linux Python + the Windows proof-kit Rust twin)". For F-09 it did not. The floor runs on zero complete-runs on Windows, and the Rust module the original finding named is byte-for-byte as dead as when it was found. Since the Owner runs Windows and the `production_verified=true` custody proof was driven through win_live_turn, a reader of that row would reasonably conclude a control is protecting that path when none is. That is a documentation-vs-code divergence on a keystone gate row, which is exactly the failure mode this audit exists to catch.

**Adversarial review (P3).** SURVIVES as a factual claim; SEVERITY LOWERED P2 -> P3 because no in-scope adversary reaches it on any shipped path.

QUOTE CHECK: the quoted complete_run tail is verbatim at win-live/src/servers.rs:766-785. Real.

STEP 1 — CONFIRMED, I ran the grep myself. `supervisor_ledger::|evidence_floor_cas|accept_prepare|gate_and_start|enqueue_terminal|pending_outbox|lease_launch_gate` across every .rs file, excluding core/src/supervisor_ledger.rs, returns EXACTLY four hits, all `create_schema`: broker/src/main.rs:69, proof/src/bin/live_turn.rs:159, win-live/src/bin/win_live_turn.rs:61, win-live/src/proof.rs:83. Byte-for-byte the original F-09 finding.

STEP 2 — CONFIRMED. win_live_turn.rs:57-63 init_schema includes supervisor_ledger::create_schema; the Connection is `open_in_memory()` and is handed only to run_governed_turn (win_live_turn.rs:195-206). The supervisor the chain actually talks to is a SEPARATE process reached over a named pipe (win_supervisor.rs:29-47 constructs brops_win_live::servers::Supervisor and pipe::run_server), whose state is Mutex<BTreeMap<..>> (servers.rs:426, :429). governed_evidence_head_floor is created empty and never touched.

STEP 3 — CONFIRMED. I read complete_run in full (servers.rs:660-789). Shape check, artifact publish, write-once commit. No SELECT, no head comparison, no mention of head_sequence beyond copying ints[3] into Completion at :764. The struct is in-process only, so a cross-run floor is not merely absent, it is architecturally impossible — servers.rs:423-425 says so itself: "Proof-kit scope: this state is in-process".

STEP 4 — CONFIRMED. win_provision.rs:112, :205-208 hard-code evidence_final_event_hash = sha256(b"brops-final-event-v1"), event_count/last_sequence/head_sequence = 3; proof.rs:147, :255-258 identical. execution.rs:132-135 forwards cfg.facts verbatim. Every Windows-kit run attests the same head forever.

WHY I LOWERED IT: severity must track security impact. Windows governed execution is fail-closed — win-broker/src/lib.rs:10-13 states platform_governed_execution_supported() stays false and "Governed turns remain fail-closed on Windows"; the Linux broker likewise returns UpstreamBlockedExecutor without BROPS_BROKER_CONFIG (broker/src/main.rs:226-231). So no adversary at any in-scope level obtains a trusted_verified message through this path today. The residual value of the finding is real but documentary: it proves the AUDIT_LEDGER F-09 row's unqualified "the anti-rollback/anti-fork floor runs on every complete-run" is platform-incomplete, in a table where the F-01 row two lines above explicitly qualifies itself with "in BOTH supervisors". That is exactly the evidence that keeps the F-09 verdict at PARTIALLY_CLOSED — which it does. It is not a P2 weakness.

**Reviewer re-read.** `apps/desktop/src-tauri/win-live/src/servers.rs:766-785 (quote verified), :660-789 (full complete_run, no floor), :423-429 (in-process state, self-declared proof-kit scope); grep over all .rs excluding core/src/supervisor_ledger.rs yields only create_schema at broker/src/main.rs:69, proof/src/bin/live_turn.rs:159, win-live/src/bin/win_live_turn.rs:61, win-live/src/proof.rs:83; apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:57-63 (schema created), :195-206 (in-memory conn never reaches the supervisor); win-live/src/bin/win_supervisor.rs:29-47 (the real supervisor is a separate pipe server); win-live/src/bin/win_provision.rs:112,205-208 + win-live/src/proof.rs:147,255-258 (constants); win-live/src/execution.rs:132-135 (forwarded verbatim); apps/desktop/src-tauri/win-broker/src/lib.rs:10-13 (gate stays false); apps/desktop/src-tauri/broker/src/main.rs:226-231 (fail-closed default)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/servers.rs:766` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-25` · The Windows supervisor twin accepts evidence counters the shared invariant forbids (zero-valued, and last_sequence != event_count)

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the driver/broker principal on the Windows kit. |
| **Location** | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| **Group** | `f09-cas` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The canonical invariant for the three evidence counters is `>= 1` (enforced in the shared DDL as CHECK constraints at supervisor_ledger.sql:137-139 and in Python by `_is_pos_i63` at governed_supervisor_ledger.py:618-620), plus `last_sequence == event_count` (governed_supervisor_ledger.py:621-622). The Windows twin accepts `n >= 0` for all four ints and never checks the equality. An evidence head claiming zero events, or claiming last_sequence 7 with event_count 2, is signed on Windows and would be refused on Linux.

**Code.**
```
let mut ints = [0i64; 4];
        for (i, k) in COMPLETION_INT_FIELDS.iter().enumerate() {
            match get_i64(p, k) {
                Some(n) if n >= 0 => ints[i] = n,
                _ => return refuse("complete-run", "malformed"),
            }
        }
```

**Walkthrough.**

STEP 1 — the Windows shape check. COMPLETION_INT_FIELDS is [completed_at_ms, evidence_event_count, evidence_last_sequence, evidence_head_sequence] (servers.rs:323-328). The loop at servers.rs:681-687 accepts any `n >= 0` for all four. completed_at_ms legitimately may be large; the other three may not legitimately be zero.

STEP 2 — no equality check. Search servers.rs for any comparison of evidence_last_sequence to evidence_event_count: there is none. They are copied independently into Completion at servers.rs:762-764.

STEP 3 — the values reach the signature unfiltered. attest_run copies c.evidence_event_count / c.evidence_last_sequence / c.evidence_head_sequence into the evidence map (servers.rs:856-858), stamps decision=completed, and Ed25519-signs JCS(evidence) (868-870).

STEP 4 — the signer does not re-check them. Signer::sign_result validates the attestation signature, decision, the identity allowlists and the timestamps (servers.rs:952-993), then copies evidence_event_count/last_sequence/head_sequence verbatim into the envelope payload (1075-1077). No range or consistency check.

WRONG OUTPUT: a Windows-kit receipt can carry `evidence_event_count: 0`, i.e. an attested evidence chain with no events, or an internally inconsistent head — states the canonical DDL declares impossible.

REFUTATION ATTEMPT: I checked whether governed_verification.rs re-validates the counters on the final acceptance path — governed_verification.rs:98-140 places evidence_head_sequence and friends into the reconstructed payload as Number values for signature reconstruction; there is no positivity or consistency predicate. The invariant is therefore enforced nowhere on the Windows leg.

**Why it matters.** supervisor_ledger.sql:1-16 declares itself "THE SINGLE NORMATIVE SOURCE" whose CHECK constraints are the enforcement neither language can weaken alone, and the ledger's F-01 row cites `tools/check_ledger_ddl_parity.py` as a CI-gated byte-equality guarantee. That gate compares two copies of the .sql file; it cannot notice that the Windows twin does not use the schema at all and re-implements a weaker predicate in Rust. A divergent twin means "the invariant is enforced by the DDL" is only true where the DDL is actually the write path — which on Windows it is not (see F09-2). Low severity on its own: I could not turn a zero-count head into a forged message, only into an attested impossibility.

**Adversarial review (P3).** SURVIVES. Quote and behaviour both verified.

QUOTE CHECK: `Some(n) if n >= 0 => ints[i] = n,` inside the COMPLETION_INT_FIELDS loop is verbatim at win-live/src/servers.rs:681-687. Real.

STEP 1 — CONFIRMED. COMPLETION_INT_FIELDS = [completed_at_ms, evidence_event_count, evidence_last_sequence, evidence_head_sequence] (servers.rs:323-328); the loop accepts n >= 0 for all four uniformly.

STEP 2 — CONFIRMED. I read complete_run 660-789 in full: evidence_last_sequence and evidence_event_count are copied independently into Completion (servers.rs:762-764) and never compared to each other.

DIVERGENCE CONFIRMED against the canonical source: supervisor_ledger.sql:137-139 carries CHECK (evidence_event_count >= 1) / (evidence_last_sequence >= 1) / (evidence_head_sequence >= 1), and governed_supervisor_ledger.py:618-622 enforces `_is_pos_i63` plus `last_sequence != event_count -> InvalidHead`. The Windows twin enforces neither. So a `produced` block with evidence_event_count = 0, or last_sequence 7 with event_count 2, is refused on Linux and accepted on Windows.

REFUTATION ATTEMPTS THAT FAILED: (a) exact_keys + is_hex64 constrain only the shape and the three hex fields, not the integers' range. (b) There is no re-check downstream — the values are copied into the attestation evidence and then into the signer envelope unchanged. (c) The DDL cannot save it: the Windows twin does not use the schema at all (see F09-2), so `tools/check_ledger_ddl_parity.py` byte-comparing two copies of the .sql file cannot detect this — the finding's own point, and it is correct.

SEVERITY P3 UPHELD. The adversary needs to control cfg.facts or the driver on the Windows kit, and the deployment constants are 3/3/3 so this never fires in practice. The wrong output is an attested impossibility on a non-shipped lab path, not a forged reply. The finding says so itself and does not inflate.

**Reviewer re-read.** `apps/desktop/src-tauri/win-live/src/servers.rs:681-687 (quote verified verbatim), :323-328 (COMPLETION_INT_FIELDS), :762-764 (independent copy, no equality check), :660-789 (whole function read; no range or consistency predicate); engine/runtime/supervisor_ledger.sql:137-139 (canonical CHECK >= 1); engine/runtime/governed_supervisor_ledger.py:618-620 (_is_pos_i63), :621-622 (last_sequence == event_count)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/servers.rs:681` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-26` · The pin manifest — the sole authority for the entire §2.5 decision — is unsigned, unpinned, and gets no owner/mode check from the code that consumes it, unlike every sibling control in the same commit

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | Whoever controls tcb-pin-manifest.json's bytes or the path the consumer resolves (config `trust.tcb_pin_manifest_path`, or $BROPS_TCB_PIN_MANIFEST for the broker binary). In the live kit that is root only, so no in-scope adversary reaches it there; in the unshipped broker deployment the launching principal is undetermined because no code in the tree spawns brops-broker. |
| **Location** | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25` |
| **Group** | `f10-tcb` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** Every fact the §2.5 floor decides against — which paths are TCB artifacts, what their digests must be, which uid counts as 'root' — comes from this one file, and the loader applies no custody check to it at all: no signature, no fstat, no owner==0, no group/other-write test, no O_NOFOLLOW. The same remediation commit applies exactly that check to two lesser inputs: ipc_policy.py:31-44 opens the peer-auth policy with O_RDONLY|O_NOFOLLOW and refuses `if info.st_uid != 0` and `if info.st_mode & (S_IWGRP|S_IWOTH)`; live_turn.rs:74-96 `anchor_file_is_tcb_owned` does the same for the root anchor on the opened fd. The manifest, which outranks both, gets neither. It is also absent from TCB_REQUIRED_ARTIFACTS (tcb_integrity.rs:174-202) — `trusted-verifier-broker.pinned-manifest-config` maps to config.json (build_tcb_pin_manifest.py:89), not to the pin manifest — so the floor does not even measure itself.

**Code.**
```
pub fn load_pin_manifest(path: &str) -> Option<TcbPinManifest> {
    let raw = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<TcbPinManifest>(&raw).ok()
}
```

**Walkthrough.**

1. tcb_probe.rs:120-124: verify_deployment_tcb takes `manifest_path` and calls load_pin_manifest with no custody test. 2. tcb_probe.rs:26: `std::fs::read_to_string(path)` — path re-resolution, follows symlinks, no fstat, no owner test. 3. tcb_integrity.rs:223-228: the coverage floor only asks whether each of the 21 `logical_name` strings is present. It never asks whether the `path` bound to a name is plausible for that role. 4. Therefore a manifest whose 21 entries all name `/usr/bin/true`, with `expected_sha256` = the true digest of /usr/bin/true and `expected_owner: root`, satisfies every check in verify_artifact (tcb_integrity.rs:243-311): stat succeeds, owner 0 == owner_uids[root] and 0 is neither a runtime uid nor the login uid, mode 0755 has no 0o022 bit, digest matches, and ancestors /usr/bin, /usr, / are root-owned 0755. 5. Wrong output: `Ok(())` -> `RESULT: tcb_integrity_floor verified artifacts=pinned`, while not one byte of the real deployment was examined. 6. Reaching step 4 requires writing the manifest or steering the path. In the kit, run_live_turn.sh:211 chowns it 0:0 mode 0644 under root-owned 0755 ancestors, so no in-scope adversary can. In broker/src/main.rs:277-280 the path may come from the environment variable $BROPS_TCB_PIN_MANIFEST; I searched the whole tree and found no launcher, service unit, or Tauri spawn site for brops-broker, so I cannot name the principal that would set it — which is itself the point: the control's soundness rests on an unstated deployment assumption.

**Why it matters.** The ledger presents the manifest as the thing that makes the floor real ('a real manifest to enforce'). Its authority is entirely conventional: it is trusted because run_live_turn.sh happens to chown it, not because any code requires that. A control whose root of trust is enforced only by a shell line in the lab kit is not a shipped control, and the gap is conspicuous precisely because the same author wrote the correct check twice elsewhere in the same change.

**Adversarial review (P3).** SURVIVES on its factual claims, but DOWNGRADED P2 -> P3 because no in-scope adversary reaches it in any configuration that exists today. Quote verified verbatim at tcb_probe.rs:25-28: `read_to_string(path).ok()?` then `serde_json::from_str` — no fstat, no owner==0, no group/other-write test, no O_NOFOLLOW, no signature. The sibling asymmetry is real and I verified both siblings: ipc_policy.py:32-44 opens O_RDONLY|O_NOFOLLOW|O_CLOEXEC and refuses `info.st_uid != 0` and `info.st_mode & (S_IWGRP|S_IWOTH)` on the fd, then fdopen()s that same fd (:45-46); live_turn.rs:77-95 anchor_file_is_tcb_owned does the same on an opened fd for the root anchor. The manifest, which outranks both, gets neither. I also confirmed the self-exclusion: build_tcb_pin_manifest.py has no entry for tcb-pin-manifest.json, and `trusted-verifier-broker.pinned-manifest-config` maps to config.json (:89), so the floor does not measure its own authority. I independently walked the /usr/bin/true substitution against verify_artifact (tcb_integrity.rs:243-311) and it does pass every branch: stat succeeds, owner 0 == owner_uids[root] and 0 is neither a runtime uid nor login_uid (:256-258), 0755 & 0o022 == 0 (:268), digest matches (:276), ancestors /usr/bin,/usr,/ are root-owned 0755 (:287-307). REFUTATION THAT LIMITS SEVERITY (I ran it, the finding also concedes it): reaching that state needs write authority over tcb-pin-manifest.json (root-owned 0644 at run_live_turn.sh:211, under root-owned 0755 $TCB/$LIVE/opt at :217/:224) or over config.json's trust.tcb_pin_manifest_path (root-owned 0644 at :148), or the ability to set $BROPS_TCB_PIN_MANIFEST for brops-broker — and I confirmed independently that nothing in the tree launches brops-broker (grep for the binary name and BROPS_BROKER_CONFIG yields only main.rs itself and config/current_state.json:175, which states the shipped surfaces route through Path B, NOT the broker binary). So this is a defence-in-depth / unstated-deployment-assumption finding, not an exploit: P3. It still matters for a gate flip precisely because the broker path is what a flip would turn on, and there the launching principal is undefined.

**Reviewer re-read.** `tcb_probe.rs:25-28 (bare read_to_string, verified verbatim); tcb_probe.rs:120-124 (verify_deployment_tcb calls it with no custody test); contrast ipc_policy.py:32-46 and live_turn.rs:77-95; build_tcb_pin_manifest.py:88-89 (pinned-manifest-config -> config.json, manifest itself unpinned); tcb_integrity.rs:243-311 walked branch by branch for the /usr/bin/true substitution; custody that blocks it: run_live_turn.sh:148,:211,:217-218,:224; no launcher for brops-broker anywhere in the tree; config/current_state.json:175 confirms shipped surfaces bypass the broker binary.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/tcb_probe.rs:25` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-27` · The probe's documented no-re-lookup/no-TOCTOU contract is falsified: owner/mode come from an O_PATH|O_NOFOLLOW fd but the content digest is a fresh path resolution

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | Would require write access to a pinned artifact's parent directory to exploit; every such directory is root-owned 0755 in the kit, so NO in-scope adversary can reach it. Reported as a falsified stated contract, not an exploit. |
| **Location** | `apps/desktop/src-tauri/broker/src/tcb_probe.rs:74` |
| **Group** | `f10-tcb` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** tcb_probe.rs:41-44 states 'Every stat goes through an O_NOFOLLOW-opened handle so a symlink swapped in between the pin and the check cannot redirect what is measured — the floor's contract says the probe must not re-look-up the path', and tcb_integrity.rs:103-105 states 'Implementations MUST stat an O_NOFOLLOW-opened handle (no symlink/path re-lookup)'. The implementation honours this for owner and mode (stat_nofollow at :53-66 opens O_PATH|O_NOFOLLOW|O_CLOEXEC and fstats the fd) and then discards the fd at :61 and hands the PATH STRING to digest(), which performs a completely fresh, symlink-following resolution at :74. The stat'ed inode and the digested inode are not guaranteed to be the same object. The correct construction is available and used elsewhere in the same change set — ipc_policy.py:45-46 fdopen()s the descriptor it already validated rather than re-opening by name.

**Code.**
```
fn digest(path: &str, mode: u32) -> String {
            if mode & libc::S_IFMT != libc::S_IFREG {
                return String::new();
            }
            match std::fs::read(path) {
```

**Walkthrough.**

1. verify_artifact (tcb_integrity.rs:243) calls probe.stat(&art.path). 2. tcb_probe.rs:87 stat_nofollow opens the path O_PATH|O_NOFOLLOW, fstats it, and closes the fd at :61 — the only handle to the measured inode is gone. 3. tcb_probe.rs:103 calls Self::digest(path, mode), which at :74 does std::fs::read(path): a new namei walk of the whole path, following symlinks at every component including the last. 4. If the final component or any ancestor is replaced between step 2 and step 3, tcb_integrity.rs:256-273 judges owner and mode of inode A while :276 compares the digest of inode B. 5. REFUTATION: I could not make this reachable. A symlink already present at the leaf is caught, because O_NOFOLLOW makes open() fail with ELOOP, stat_nofollow returns None, and tcb_integrity.rs:243-246 raises TcbViolation::Missing before digest() is ever called. Creating or swapping the leaf during the race needs write permission on the parent directory, and I checked all of them: $TCB, $BIN, $LIVE, $LIVE/engine/** are root-owned 0755 (run_live_turn.sh:217-218), and /etc/sudoers.d is root-only. Only root can win this race, and root is out of scope.

**Why it matters.** The module's own safety argument for why the probe is trustworthy is the O_NOFOLLOW/no-re-lookup property, and half the probe does not have it. An auditor or a future maintainer reading tcb_probe.rs:41-44 will believe a guarantee the code does not provide, which is the kind of comment-versus-code drift this audit exists to catch. No security impact against the in-scope adversary set today.

**Adversarial review (P3).** SURVIVES as a falsified stated contract, which is how it is framed — not as an exploit. Quote verified verbatim at tcb_probe.rs:70-74. The discrepancy is real: tcb_probe.rs:40-42 says 'Every stat goes through an O_NOFOLLOW-opened handle so a symlink swapped in between the pin and the check cannot redirect what is measured — the floor's contract says the probe must not re-look-up the path', and tcb_integrity.rs:102-104 says implementations 'MUST stat an O_NOFOLLOW-opened handle (no symlink/path re-lookup)'. stat_nofollow (:53-66) honours it for owner/mode, then CLOSES the fd at :61, and stat() at :103 passes the PATH STRING to digest(), which does `std::fs::read(path)` at :74 — a fresh, symlink-following namei walk. The stat'ed inode and the digested inode are not guaranteed identical, and the correct construction (fdopen the already-validated descriptor) is used by the same author in the same change at ipc_policy.py:45-46. CORRECTION to their refutation reasoning, which does not change the outcome: they say a leaf symlink is caught 'because O_NOFOLLOW makes open() fail with ELOOP'. That is wrong for O_PATH — open(O_PATH|O_NOFOLLOW) SUCCEEDS on a symlink and returns a handle to the link itself. What actually catches it is the next check: the symlink's st_mode is 0o120777, so `(mode & 0o022) != 0` at tcb_probe.rs:89 is true and verify_artifact returns WritableByUntrusted at tcb_integrity.rs:268-273 (or WrongOwner first if the link is not root-owned). Still fail-closed, so their conclusion stands. DOWNGRADE/limit: winning the race needs write permission on a pinned artifact's parent, and I re-verified every one — $TCB, $BIN, $LIVE root-owned 0755 (run_live_turn.sh:217), $LIVE/engine root:root with 0755 dirs (:218), /opt root-owned 0755 (:224), /etc/sudoers.d root-only. Only root, who is out of scope. P3 is correct: comment-versus-code drift in the module's own safety argument, no security impact today.

**Reviewer re-read.** `tcb_probe.rs:40-42 and tcb_integrity.rs:102-104 (the stated no-re-lookup contract) vs tcb_probe.rs:53-66 (fd closed at :61) and :74 (`std::fs::read(path)` fresh resolution); contrast ipc_policy.py:45-46 (fdopen of the validated fd); unreachability re-verified at run_live_turn.sh:217-218,:224; my correction: O_PATH|O_NOFOLLOW returns a handle to the symlink itself, and it is tcb_probe.rs:89 + tcb_integrity.rs:268 that fail it closed, not ELOOP.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/tcb_probe.rs:74` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-28` · Neither claimed 'production' caller enforces the floor for a served turn: live_turn's verify_tcb exits the process, and the broker's call site can never pass on the kit's own layout

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | None — both behaviours are fail-closed. This is a claimed-property-versus-code defect in the ledger row, relevant to whether F-10 counts as evidence for a gate flip. |
| **Location** | `apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35` |
| **Group** | `f10-tcb` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:29 states 'the production broker AND the live driver run verify_deployment_tcb before they will serve a governed turn.' (a) The live driver does not: --verify-tcb is a mutually exclusive branch that terminates the process at live_turn.rs:36; the branch that serves the turn is run() at :37, and the only verify_deployment_tcb reference anywhere in the file is line 201, inside verify_tcb. In run_live_turn.sh these are two different processes run by two different principals at two different times (root at :244, broker uid at :271). (b) The broker binary does call it at main.rs:281 — but on this layout it must always fail: the broker uid cannot traverse /etc/sudoers.d (mode 0750 root:root on Debian) so stat_nofollow's open() of the pinned sudoers file returns EACCES -> None -> TcbViolation::Missing; and even past that, digest() at tcb_probe.rs:74 cannot read the 4750 root:brops-recorder launcher, yielding "" and a HashMismatch. Either way build_governed_executor returns fail_closed() at main.rs:287 and the broker keeps UpstreamBlockedExecutor forever. (c) It is called once, at main.rs:178, before the accept loop at :181 — per process start, never per turn.

**Code.**
```
if args.iter().any(|a| a == "--verify-tcb") {
        std::process::exit(linux::verify_tcb(&config_path));
    }
    std::process::exit(linux::run(&config_path));
```

**Walkthrough.**

1. run_live_turn.sh:244 `"$BIN/live_turn" --config "$CONFIG" --verify-tcb` runs as root. 2. live_turn.rs:35-36 takes the --verify-tcb branch and std::process::exit()s after printing the RESULT line at :207. The process is gone. 3. run_live_turn.sh:259-261 starts the three service servers. 4. run_live_turn.sh:271 `sudo -u "$BROKER_USER" "$BIN/live_turn" --config "$CONFIG"` — a NEW process, no --verify-tcb, so live_turn.rs:37 goes straight to run(), which contains no floor evaluation. 5. Separately, for the shipped broker: main.rs:178 build_governed_executor -> :281 verify_deployment_tcb -> tcb_probe.rs:128 LinuxFsProbe -> tcb_integrity.rs:243 probe.stat("/etc/sudoers.d/brops-live-recorder") -> tcb_probe.rs:54-57 open() as uid 5001 -> EACCES (no search bit on the 0750 parent) -> fd < 0 -> None -> TcbViolation::Missing -> main.rs:286-287 fail_closed(). 6. Wrong output is a documentation output, not a runtime one: the ledger row reads as per-turn enforcement by two live callers; the code provides one deployment-time root evaluation and one caller that is structurally guaranteed to refuse.

**Why it matters.** Directly bears on §3.5. The stated reason for deployment-time evaluation — that the serving principals must not be able to read the 4750 launcher and the root-only sudoers file — is CORRECT and I verified both modes (run_live_turn.sh:90 and :200). But it means the broker leg cannot be counted as a second, per-turn enforcement point: with this layout it is a permanently-refusing caller. The honest description of §2.5's current enforcement is: one root-run, deployment-time evaluation, in the lab kit only, on Linux only.

**Adversarial review (P3).** SURVIVES, with leg (a) weaker than stated. Quote verified verbatim at live_turn.rs:35-38, and I confirmed the AUDIT_LEDGER.md:29 sentence it attacks: 'the production broker AND the live driver run verify_deployment_tcb before they will serve a governed turn.' (a) PARTLY REFUTED BY ME: it is true that --verify-tcb is a mutually exclusive branch that std::process::exit()s at :36, that run() at :38 contains no floor evaluation (the only verify_deployment_tcb reference in the whole file is :201, inside verify_tcb), and that run_live_turn.sh:244 and :271 are two different processes run by two different principals. BUT the shell DOES sequence them as a hard gate — `|| { echo "FAIL: ..."; exit 1; }` at :244 means no service starts (:259-261) and no turn runs (:271) unless the floor passed. So operationally the ordering the ledger describes is enforced; what is wrong is the attribution — the driver binary does not enforce it, a shell line does, and only in the lab kit. (b) HOLDS, and I re-walked it: with the kit's layout, a brops-broker running as uid 5001 hits tcb_integrity.rs:243 -> probe.stat('/etc/sudoers.d/brops-live-recorder') -> tcb_probe.rs:54-57 open() with no search bit on the 0750 root:root parent -> fd<0 -> None -> TcbViolation::Missing -> main.rs:286-287 fail_closed(); and even past that, the 4750 root:brops-recorder launcher (run_live_turn.sh:88-90) is unreadable to 5001, so digest() at :74 returns "" and :276 raises HashMismatch. Both directions are fail-closed, so this is a claimed-property defect, not a hole. (c) HOLDS: build_governed_executor is called once per process start, before the accept loop — I verified the real lines are main.rs:181 (call) and :185 (`for stream in listener.incoming()`), not the :178/:181 the finding cites; that is citation drift of three lines, not a substantive error. I also independently confirmed nothing in the tree launches brops-broker at all, and config/current_state.json:175 states the shipped AI surfaces route through Path B rather than the broker binary — which strengthens (b)/(c). P3 is right: the honest description of §2.5's enforcement today is one root-run, deployment-time evaluation, lab kit only, Linux only, and the ledger row should not be read as two per-turn callers.

**Reviewer re-read.** `live_turn.rs:35-38 (verified verbatim; verify_tcb at :172-216, sole verify_deployment_tcb reference at :201) vs live_turn.rs:218+ run() with no floor call; run_live_turn.sh:244 (root, `|| exit 1`) vs :271 (`sudo -u "$BROKER_USER"`, no --verify-tcb) — two processes, but the shell does gate the sequence; main.rs:181 build_governed_executor / :185 accept loop / :281 verify_deployment_tcb / :286-287 fail_closed (finding cites :178 for the call — three-line drift, substantively correct); refusal path re-walked through tcb_probe.rs:54-57 and :74 against run_live_turn.sh:88-90 (4750 launcher) and :198-200 (/etc/sudoers.d); AUDIT_LEDGER.md:29 quoted claim confirmed present.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-29` · The floor is advanced from a SECOND, independent read of the head file rather than from the head validate_chain just verified, so a store write between the two reads pins the mark permanently low

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 3 — the interactive login user, needing a concurrent write to the evidence store during the gate. Dominated by A1 (the same capability deletes the mark outright); it matters as proof that the advance path is not bound to the verified head. |
| **Location** | `engine/runtime/bro_completion.py:226` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** validate_chain (:220) internally loads and verifies the head and knows its head_sequence, but that value is discarded; :227 re-reads <store>/<task>.head.json from disk. The two reads are not atomic and need not see the same file, so the mark records whatever head is on disk at the second read, not the head the chain was judged against.

**Code.**
```
_advance_head_floor(resolved_store, task_id,
                            load_head(resolved_store, task_id, resolved_keys).head_sequence)
```

**Walkthrough.**

STEP 1: present the chain with a genuine head at head_sequence=9. STEP 2: bro_completion.py:220 -> bro_evidence.validate_chain -> load_head (bro_evidence.py:137) reads head 9, min_head_sequence is None (floor 0), the structural checks at bro_evidence.py:161-170 pass, the digest is returned. STEP 3: before :227 executes, a concurrent writer replaces <store>/task-1.head.json with a genuine, older head at head_sequence=1 — an authentic recorder-signed artifact the attacker retained, no forgery. STEP 4: :227's load_head verifies that file successfully (it is genuinely signed) and returns head_sequence=1; _advance_head_floor writes 1. I instrumented exactly this and observed 'chain verified against head 9, recorded floor = 1'. STEP 5: the mark now permits every head from 1 upward indefinitely, because :271 never lowers but also never re-raises to 9 unless a later chain is presented at a higher head — which the attacker simply does not do.

**Why it matters.** bro_completion.py:223-225 claims the mark is advanced 'only after the chain verified'. It is advanced after A chain verified, to a value read from a file that need not be the one that verified. The property the comment asserts — that the recorded mark corresponds to the evidence just accepted — is not established by this code, and the fix is one line (return the verified head from validate_chain and use it), which makes the gap harder to excuse.

**Adversarial review (P3).** Quote exact at bro_completion.py:226-227. The defect is real: validate_chain (:220) internally calls bro_evidence.load_head (bro_evidence.py:137) and holds the verified EvidenceHead, but the return value discards head_sequence, so :227 re-reads <store>/<task>.head.json a second time with no atomicity between the two. I reproduced it: with a genuine head 9 presented and a concurrent writer swapping in a genuine older head 1 between the two loads, the run printed 'verified against head 9; recorded floor = 1'. Refutations I tried and that failed: (a) does :271's never-lower rule save it? No - it never RE-raises either, so the floor stays pinned at 1 until the attacker voluntarily presents something higher, which they will not; (b) is a benign race harmful? No - the recorder only bumps head_sequence upward, so a non-adversarial race can only over-advance, which is safe. That is why this is correctly rated below A1: it needs a *timed* concurrent write, whereas the same adversary can simply delete the mark (A1). P3 confirmed - it is worth reporting mainly because it proves the advance path is not bound to the head that was actually judged, contradicting the comment at :223-225, and because the fix is one line.

**Reviewer re-read.** `bro_completion.py:220-227; bro_evidence.py:122-138 (validate_chain loads the head internally and returns only the digest at :171). Executed: [toctou] chain verified against head 9, recorded floor = 1.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_completion.py:226` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-30` · The head-floor advance is an unlocked load-compare-write over a shared temp filename, so two concurrent turns for one task can lower the mark or brick the task

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 3 — the interactive login user running two turns for the same task_id. Dominated by A1; reported because the 'only upward' claim is stated unconditionally. |
| **Location** | `engine/runtime/bro_completion.py:271` |
| **Group** | `f06-f13-rollback` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** Read (:271), decide, then write-and-rename (:278-283) with no lock, no O_EXCL, and a temp path that is a pure function of task_id, so two processes contend for the same temp file. bro_completion.py:270 states 'Never lowers it' as an invariant; it holds only for a single writer.

**Code.**
```
if head_sequence <= _load_head_floor(store, task_id):
        return
    directory = _head_floor_dir(store)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{task_id}.floor.json"
        temporary = directory / f"{task_id}.floor.json.tmp"
```

**Walkthrough.**

LOWERING: T1 and T2 both enter _advance_head_floor for task-1 and both read the current mark 3 at :271. T1 carries head_sequence=7, T2 a genuine older head_sequence=5; both pass the > check. T1 writes and renames 7; T2 then writes and renames 5. Final mark: 5. A genuinely signed head at 5 or 6 is now accepted although 7 was already recorded — the exact rollback the mark exists to refuse. BRICKING: both processes open the identical <task>.floor.json.tmp with write_text (truncating open) and interleave; whichever replace lands last can leave a mixed or partial file, and _load_head_floor (:257-262) then refuses every subsequent call with 'evidence head floor ... is unreadable', permanently RED for that task with no documented recovery. A losing racer can also hit FileNotFoundError from temporary.replace when the other rename already moved the temp away — caught at :284 and surfaced as a spurious CompletionError on an honest turn.

**Why it matters.** The desktop's equivalent primitive does this correctly under BEGIN IMMEDIATE (apps/desktop/src-tauri/core/src/supervisor_ledger.rs:798-891; the DDL parity gate tools/check_ledger_ddl_parity.py:48 exists precisely because the project knows this CAS must be serialized). The engine-side mark, presented in the same ledger row as the equivalent control, has none of that discipline, so its 'only upward' guarantee is weaker than the words describing it.

**Adversarial review (P3).** Quote exact at bro_completion.py:271-277. The primitive really is an unlocked read (:271) / decide / write-and-rename (:278-283) with a temp filename that is a pure function of task_id, so two processes for one task contend for the identical <task>.floor.json.tmp; there is no lock, no O_EXCL, no fsync. I tried to refute the premise - 'can two completions for one task_id ever run concurrently?' - by looking for serialization on the Stop path: grep for TASK_LOCK/task_lock in bro_completion.py and bro_hook.py returns NOTHING, and _no_pending_execution (:289-292) is an advisory glob over the lease ledger, not a lock, so nothing in this path prevents it. The lowering interleave (both read 3, T1 renames 7, T2 renames 5) and the spurious-RED path (losing racer's `temporary.replace(final)` raising FileNotFoundError, an OSError caught at :284 and surfaced as CompletionError on an honest turn) both follow directly from the code. I did NOT execute the race, and the write is a single small JSON so an interleaved-partial-file outcome is plausible rather than demonstrated - the finding's 'bricking' half is weaker than its 'lowering' half and should be reported that way. Held at P3: dominated by A1 (the same adversary just deletes the mark), and it needs a timing win. Reported because :270 states 'Never lowers it' as an unconditional invariant that holds only for a single writer, and the project already knows better - the desktop equivalent serializes under BEGIN IMMEDIATE (supervisor_ledger.rs:813-891).

**Reviewer re-read.** `bro_completion.py:269-286 (unlocked load-compare-write, shared .tmp, OSError -> CompletionError), :289-292 (_no_pending_execution is a glob, not a lock); no task-lock reference in bro_completion.py or bro_hook.py; supervisor_ledger.rs:813-891 as the correct contrast.`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/bro_completion.py:271` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-31` · "external" root-anchor provenance is a string the repo-staged kit writes about itself, so a repo-tree writer turns the kit's own GREEN line into a false production-custody claim

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 3 — the interactive login user (or 1, the model, through any surface that writes the repo tree). NO root needed by the attacker; the operator supplies root by running the kit normally afterwards. |
| **Location** | `engine/ci/live/provision_keys.py:245` |
| **Group** | `f07-f17-custody` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The one field that distinguishes "this kit minted its own trust root" from "an offline root outside this kit signed the manifest" is set from nothing but the presence of four command-line flags (provision_keys.py:184-189 -> :245). Nothing verifies that the private half is held anywhere but this machine: the script does not compare the supplied public key against the root keypair it generates anyway at :220 and writes to keys/root.priv at :228, does not verify the detached signature it copies verbatim at :239-242, and records no ceremony or second party. Worse, the code that writes the field is not itself anchored: run_live_turn.sh copies it out of the repo working tree at :76 and executes that copy at :85/:103. The anchor file's only downstream check is owner/mode (live_turn.rs:77-95), satisfied by run_live_turn.sh:153 chowning whatever the provisioner wrote to 0:0 0644 — no signature covers the anchor's contents.

**Code.**
```
anchor_key_id = args.root_anchor_key_id
        anchor_pub_hex = args.root_anchor_pub_hex.strip().lower()
        anchor_provenance = "external"
```

**Walkthrough.**

1. The attacker needs only write access to the repository working tree (the Bro agent has exactly this; so does any login user on a shared build host). They edit engine/ci/live/provision_keys.py so `anchor_provenance = "external"` is unconditional — or, without touching a line, generate an Ed25519 keypair locally, sign build_manifest_bytes() output with it, and arrange for the four flags to be passed. 2. The operator runs the kit the documented way: `sudo engine/ci/live/run_live_turn.sh` (run_live_turn.sh:16,28). 3. run_live_turn.sh:76 `cp "$REPO_ROOT"/engine/ci/live/*.py "$LIVE/engine/ci/live/"` stages the attacker's file into the deployment; :85 points PYLIVE at that staged copy; :103 executes it as root. 4. provision_keys.py:262-273 writes /opt/brops-live/tcb/root-anchor.json with `"provenance":"external"` and a public key whose private half is on the same disk. 5. run_live_turn.sh:153 `chown 0:0 "$TCB/root-anchor.json"; chmod 0644` — the file is now root-owned and non-writable, so live_turn.rs:269 anchor_file_is_tcb_owned returns Ok: it tests uid and mode, never provenance or a signature. 6. live_turn.rs:279-288 reads provenance and builds PinnedRoot from the same file; :289 verify_manifest succeeds because the attacker signed the manifest with the matching private. 7. live_turn.rs:443-444 anchor_is_external = true -> production_verified = true; :452 prints `production_verified=true ... root_anchor=external`. 8. run_live_turn.sh:284-286 matches and prints `LIVE GOVERNED TURN: GREEN — genuine production trusted_verified (externally-anchored root)`. 9. Nothing can contradict it: build_tcb_pin_manifest.py:92 pins root-anchor.json by digest, but the pin is computed at run_live_turn.sh:210 FROM the file just written, so it certifies the attacker's bytes as canonical; provision_keys.py is not in the pinned set at all (build_tcb_pin_manifest.py:64-96).

**Why it matters.** It does not by itself make the desktop app commit a message — the shipped desktop keeps UpstreamBlockedExecutor and platform_governed_execution_supported() == false, and this is the Linux lab kit. It attacks the EVIDENCE the Owner would use to flip that gate, which is the kit's entire purpose. F-17's claimed closure is "will not report production_verified=true unless the provenance is external"; this shows the antecedent is a self-report by the very component whose self-certification F-17 was filed about, staged out of a tree the weakest in-scope adversaries can write. The repository's own test (engine/tests/test_live_provisioning_anchor.py:71-93) obtains provenance=="external" from a keypair generated inside the test process on the same machine — the finding stated as an assertion. The fix already exists in this repo for Windows: compile the anchor in (win-live/src/tcb.rs:28-29) so no provisioning run can choose it.

**Adversarial review (P3).** SURVIVES, DOWNGRADED P2->P3. The defect statement is true and I could not refute it: `anchor_provenance = "external"` is set from nothing but the presence of four CLI flags (provision_keys.py:184-189 -> :243-245), it is written into root-anchor.json (:262-273), the only downstream check is uid/mode (live_turn.rs:77-95 fstat: S_IFREG + st_uid==0 + !(mode & 0o022) — no provenance/signature/ceremony check), and that bare string alone flips the claim: live_turn.rs:443-444 `anchor_is_external = anchor_provenance == "external"; production_verified = ts.is_production_verified() && anchor_is_external`, printed at :451-453, and run_live_turn.sh:284-286 turns it into `GREEN — genuine production trusted_verified (externally-anchored root)`. The repo's own test proves the label is a flag-count: test_live_provisioning_anchor.py:71-93 mints the "owner root" with `lc.gen_private()` inside the test process and asserts provenance=="external". I also confirmed build_tcb_pin_manifest.py:64-96 pins run_supervisor/run_signer/run_authority but NOT provision_keys.py, and that the root-anchor pin is computed at run_live_turn.sh:210 from the file just written.
WHY THE SEVERITY DROPS. The exploit framing (adversary 3 / P2) is not specific to this line and does not survive scrutiny. run_live_turn.sh:57-58 BUILDS the Rust driver from $REPO_ROOT and :96 installs it as $BIN/live_turn; :76 stages the .py tree; :208 installs the script itself as the pinned `.unit`. Every pin in build_tcb_pin_manifest.py is a start-time self-measurement of whatever the working tree just produced. So a repo-tree writer does not need to touch provision_keys.py:245 at all — editing live_turn.rs:444 to `let production_verified = true;`, or editing the echo at run_live_turn.sh:285, yields the identical GREEN more directly. The kit has no source-provenance control anywhere, so the provenance label is not a weaker link than its neighbours; the finding identifies a general absence and files it against one line. Two sub-claims are also wrong or misleading: (a) "does not verify the detached signature it copies verbatim at :239-242" — live_turn.rs:289 `verify_manifest(&manifest, &root_sig_b64, &pinned_root)` DOES verify it against the anchor pub at run time and blocks on failure (:290), so an unsigned/bogus external manifest is fail-closed; (b) "does not compare the supplied public key against the root keypair it generates at :220/:228" — in external mode that generated keypair signs nothing and is unused, so the comparison would catch only a naive self-supply, not custody. What is left, and what genuinely survives, is a claim-accuracy residual identical in kind to the PARTIALLY_CLOSED verdict: provenance is an unverified operator self-assertion that gates a production-custody sentence, in a mode CI never exercises. P3, lab-kit-only, Linux-only; it cannot make the shipped desktop commit anything (UpstreamBlockedExecutor / platform_governed_execution_supported()==false).

**Reviewer re-read.** `engine/ci/live/provision_keys.py:184-189,236-251,262-273; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:77-95,269-291,443-444,451-453; engine/ci/live/run_live_turn.sh:57-58,76,85,96,103-106,153,208,210,284-290; engine/ci/live/build_tcb_pin_manifest.py:64-96 (provision_keys.py absent from the pinned map); engine/tests/test_live_provisioning_anchor.py:67-96`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/ci/live/provision_keys.py:245` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-32` · The F-07 remediation dropped the sticky bit while granting group write, so service accounts can now unlink artifacts that mode 1777 protected

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 (broker, uid 5001) and 4 (any other unprivileged local account holding one of the new groups: brops-supervisor, brops-challenge, brops-signer, brops-recorder) |
| **Location** | `engine/ci/live/run_live_turn.sh:180` |
| **Group** | `f07-f17-custody` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The three directories moved from 1777 (world-write WITH the sticky bit, so only a file's owner could unlink it) to 2775/2770 (setgid, group-write, NO sticky bit). Unlink is governed by write permission on the DIRECTORY, so every member of the new group can now delete or replace ANY file in it regardless of owner — including the root-provisioned blobs written at provision_keys.py:288-291 and chmod'd 0644 root:brops-store at run_live_turn.sh:183-184, and each service's bound socket. Under 1777 the sticky bit forbade exactly this. The trade is a net win against adversary 4 in the CREATE direction and a regression against adversaries 2 and 4 in the DELETE direction; the rationale block at run_live_turn.sh:155-170 discusses only the create direction.

**Code.**
```
chgrp brops-store  "$STORE";  chmod 2775 "$STORE"
chgrp brops-report "$REPORT"; chmod 2770 "$REPORT"
chgrp brops-ipc    "$SOCK";   chmod 2770 "$SOCK"
```

**Walkthrough.**

Store: the broker or brops-supervisor (members of brops-store per run_live_turn.sh:176) runs `rm /opt/brops-live/store/system`. The next turn's recorder calls open_ro("system") at governed_recorder.rs:125-132, gets -1, returns "recorder: cannot open store inputs" and exits non-zero; chain_executor.rs:807-809 maps that to TurnReason::UpstreamBlocked and live_turn.rs:417-419 prints `blocked`. Same for deleting any content-addressed blob: run_signer.py:54 `os.path.isfile` fails -> read_verified returns None -> the signer refuses; replacing a blob with different bytes hits run_signer.py:58 `sha256(data) != handle` -> SignerError. Sockets: brops-challenge (an unprivileged account, in brops-ipc per :178) unlinks /opt/brops-live/sock/signer.sock and binds its own listener there; the broker's next connect reaches the impostor, which cannot produce an envelope verifying under the manifest-resolved signer key (signer.priv is 0400 brops-signer, :146), so verify_and_accept refuses.

**Why it matters.** Every route ends fail-closed, so this does NOT produce a false trusted_verified and does not reopen F-07/F-28. I report it because it is a property the remediation traded away without saying so, it is absent from the ledger row and from the script's own rationale, and the availability leg matters for a fail-closed chain: a service account that can permanently wedge the governed path by deleting one root-owned file is a denial of the only path to a committed message. The cheap fix is 3775/3770 (setgid + sticky), which preserves every access the services need and restores delete protection.

**Adversarial review (P3).** SURVIVES at P3 as filed. The quote is verbatim (run_live_turn.sh:180-182) and the mechanism is correct: 2775/2770 are setgid + group-write with NO sticky bit, and POSIX unlink is governed by write+execute on the DIRECTORY, restricted to the file's owner only when the sticky bit is set. So members of brops-store (supervisor + broker, :176) can now unlink or replace the root-provisioned 0644 blobs (provision_keys.py:284-291, re-chgrp'd at run_live_turn.sh:183-184), members of brops-report (recorder + broker, :177) can unlink each other's report files, and members of brops-ipc (:178) can unlink a bound socket and re-bind it. Under 1777 the sticky bit forbade exactly that. The rationale block at :155-170 discusses only the create direction, so the trade is genuinely undocumented.
I WALKED EVERY ROUTE TO A FORGERY AND ALL DIE FAIL-CLOSED, so it does not reopen F-07/F-28 and does not answer the audit's single question — which the finding itself states honestly. Store deletion: governed_recorder.rs:125-133 `open_ro("system"|"history"|"generation_config")` returns -1 -> `err("recorder: cannot open store inputs")` -> non-zero exit -> chain_executor.rs (child.wait !success) -> TurnReason::UpstreamBlocked. Blob substitution: run_signer.py:58-60 raises SignerError on `sha256(data) != handle`. Replacing store/system additionally breaks the F-08 lease pins (run_live_turn.sh:117-141). Socket impersonation: the impostor cannot produce an Ed25519 signature under the manifest-resolved key (privates are 0400 to their own accounts, :144-147), and F-26 run/attempt/nonce binding defeats envelope replay.
TWO CORRECTIONS TO THE FILING, neither fatal. (1) The adversary label overstates: "any other unprivileged local account" cannot do this — the store/report/sock dirs have no world write, so the attacker must already hold one of the three new groups, i.e. be a chain service account or the broker. That is a peer-service escalation, not an arbitrary local user. (2) The impact is availability-only against a fail-closed chain, on the Linux lab kit only. Correctly P3; the proposed 3775/3770 fix is right and costs nothing.

**Reviewer re-read.** `engine/ci/live/run_live_turn.sh:155-184; engine/ci/live/provision_keys.py:284-291; apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:125-133; engine/ci/live/run_signer.py:49-60,116-118; engine/ci/live/run_supervisor.py:91-107,132-135; apps/desktop/src-tauri/broker/src/chain_executor.rs:746-754,806-848`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/ci/live/run_live_turn.sh:180` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-33` · The live-governed-turn CI job's stated pass condition no longer matches the script: it now exits 0 with production_verified=false

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | none in-scope — claim-accuracy defect; the wrong output lands in a human decision, which is the thing this audit protects |
| **Location** | `.github/workflows/ci.yml:91` |
| **Group** | `f07-f17-custody` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** run_live_turn.sh:287-290 now has a second GREEN branch that exits 0 when the result line says `bound=true root_anchor=kit_generated`, i.e. exactly when production_verified=false (live_turn.rs:443-444). Since ci.yml:98 never passes the four external-anchor flags, EVERY green run of this job is the production_verified=false branch. The workflow comment still asserts the opposite pass condition, and the AUDIT_LEDGER F-01 row cites this job as evidence with the words "`production_verified=true bound=true` across six real uids".

**Code.**
```
# Fail-closed by construction: the script exits non-zero unless the driver prints
      # `production_verified=true bound=true`, and it never fabricates an acceptance. A RED here
      # means the live chain is broken — which is exactly what this job exists to surface.
```

**Walkthrough.**

1. ci.yml:98 runs `sudo -E env "PATH=$PATH" bash engine/ci/live/run_live_turn.sh` with no anchor flags. 2. provision_keys.py:246-251 takes the else branch -> anchor_provenance = "kit_generated". 3. live_turn.rs:443-444 -> production_verified = false; :452 prints `production_verified=false ... root_anchor=kit_generated`; :458 still returns 0 because the condition is `bound && ts.is_production_verified()`. 4. run_live_turn.sh:284 does not match, :287 does, :290 exits 0. 5. The job is green. A reviewer reading ci.yml:91-93 plus a green check concludes the gate proved `production_verified=true` on that run; it proved the opposite.

**Why it matters.** The single question is whether a trusted_verified + production_verified=true can be produced that the chain did not earn. The script's honest downgrade is the right behaviour — but the surrounding claim tells the reader the run asserted the strong property, and the ledger repeats it. That is precisely the class of self-assessment error this re-audit exists to catch, and it sits on the artifact (a green CI badge) most likely to be cited when the gate flip is argued.

**Adversarial review (P3).** SURVIVES at P3 — I tried to refute it and could not; the contradiction is exact. ci.yml:91-93 states the pass condition as "the script exits non-zero unless the driver prints `production_verified=true bound=true`", and the job at ci.yml:97-98 invokes run_live_turn.sh with NO anchor flags. I walked it: no flags -> provision_keys.py:185-189 `use_external=False` -> :246-251 else-branch -> anchor_provenance="kit_generated" -> live_turn.rs:443-444 `production_verified = ts.is_production_verified() && (anchor_provenance == "external")` = false -> :451-453 prints `RESULT: trusted_verified(production key=... epoch=2) production_verified=false bound=true root_anchor=kit_generated` -> :458 `if bound && ts.is_production_verified()` is TRUE (that condition deliberately ignores the anchor) so the driver returns 0 -> run_live_turn.sh:284 does not match, :287 matches `bound=true root_anchor=kit_generated`, :288-290 echoes GREEN and exits 0. So every green run of this job is the production_verified=FALSE branch while the adjacent comment asserts the opposite, and AUDIT_LEDGER.md:23 (the F-01 row) cites this same job with "`production_verified=true bound=true` across six real uids" — a sentence that was written against run 31078055077 at a64c8cc, i.e. BEFORE the F-17 change, and can no longer be reproduced by any current run of the workflow.
Severity is right at P3: there is no adversary and no wrong machine output — the script's downgrade is the correct behaviour and the finding says so. The wrong output lands in a human decision, and it sits on the two artifacts (a green CI badge and the ledger's own evidence sentence) most likely to be cited when the gate flip is argued, which is exactly the self-assessment class this re-audit exists to catch. Fix is documentation-only: restate ci.yml:91-93 as "exits non-zero unless the driver prints `bound=true` under a manifest-resolved production key; `production_verified=true` additionally requires an external root anchor, which this job does not supply", and correct the ledger F-01 evidence sentence.

**Reviewer re-read.** `.github/workflows/ci.yml:91-93,97-98; engine/ci/live/run_live_turn.sh:278-294; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:443-444,451-453,458-462; engine/ci/live/provision_keys.py:185-189,246-251; apps/desktop/AUDIT/AUDIT_LEDGER.md:23`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `.github/workflows/ci.yml:91` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-34` · RecursionError from a 4090-byte nested-JSON frame still escapes handle_connection AND serve_forever and kills the deployed governed supervisor — F-11's fix closed only the FrameError leg

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account (brops-verifier_broker, uid 5001/5002). peer_is_broker admits only this uid, so nothing weaker reaches the parser. Does NOT need the login user or root. |
| **Location** | `engine/runtime/governed_supervisor_server.py:626` |
| **Group** | `f11-dos` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The F-11 remediation bounded the error TEXT and taught `_try_write` to degrade a FrameError, but left the except tuple at :626 unchanged. RecursionError is a RuntimeError subclass, not a ValueError, so `json.loads` at :614 — which is INSIDE the try — can still raise an exception no handler catches. serve_forever's only guard is `finally: conn.close()` (:716-720), so the exception exits the accept loop and the process. This is the identical defect the same audit filed as F-25 against isolated_signer_server.py:273 and challenge_authority_server.py:241; the remediation session fixed the FrameError symptom on the supervisor and left the exception-class root cause open on all three servers.

**Code.**
```
except (FrameError, ServerError, SupervisorError, ValueError, UnicodeDecodeError) as exc:
        reply = {"ok": False, "error": _bounded_error(str(exc))}
```

**Walkthrough.**

1. The live kit starts the supervisor as its own uid: engine/ci/live/run_live_turn.sh:260 `start_server "$SUPERVISOR_USER" run_supervisor.py`. run_supervisor.py:135 chmods the socket 0o777, and :138-153 hands `accept_one` to `gss.serve_forever` inside a bare `try:`/`finally:` with NO except (:142-160).
2. The broker service account connects. governed_supervisor_server.py:607 `if not peer_is_broker(peer_uid, allowed_broker_uid)` passes (challenge_authority.py:413-417 is an exact uid match; the broker uid is the allowlisted one).
3. It sends ONE frame: 4-byte big-endian length = 4090, body = b'[' * 4090. read_frame (:205-224) checks `length == 0` (no), `length > MAX_FRAME_BYTES` -> 4090 <= 8192, so the frame is ACCEPTED and the body returned at :224.
4. handle_connection:614 `request = json.loads(raw.decode("utf-8"))`. CPython's scanner recurses once per nesting level; 4090 > sys.getrecursionlimit() (1000). I ran this: `json.loads(b'['*4090)` raises RecursionError with `__mro__ = (RecursionError, RuntimeError, Exception, BaseException, object)` and `isinstance(e, ValueError) == False`.
5. The tuple at :626 does not list RuntimeError/RecursionError/Exception, so nothing catches it. `_try_write` at :634 is never reached; no reply is written.
6. It escapes handle_connection. serve_forever (:703-720) wraps the call in `try:`/`finally: conn.close()` with no except, so it escapes the loop. I ran the REAL module: `gss.handle_connection(FakeConn(b'['*4090), 5002, ...)` -> `ESCAPED handle_connection: RecursionError | isinstance ValueError = False`; and `gss.serve_forever(accept_one, ...)` with two queued connections -> `ESCAPED serve_forever: RecursionError` with the SECOND connection never accepted.
7. run_supervisor.py's `finally` (:154-160) closes the ledger and `os.unlink(sock_path)` (:160), then the traceback exits the process. The supervisor socket file is REMOVED, so every subsequent accept-open / launch-gate / execution-started / complete-run / attest-run hop fails with ENOENT until an operator restarts it. There is no restart supervision in the script.

**Why it matters.** It does NOT forge anything — this is availability plus a falsified invariant, and it cannot mint a lease, an attestation, or a trusted_verified. What breaks is the property the F-11 remediation explicitly claimed to restore: handle_connection:599 still says 'Never raises on hostile input — every failure becomes a fail-closed error reply' and serve_forever:697 still says 'A single hostile connection never tears down the loop'. Both are still false, from the same principal, with one 4 KB frame, against the supervisor that holds the attestation private key and is the one the live kit actually starts. The AUDIT_LEDGER row marks F-11 '✅ supervisor leg closed'; the leg it names is closed, the invariant is not.

**Adversarial review (P3).** SURVIVES. I reproduced every step against the real module, not the quote. The except tuple at governed_supervisor_server.py:626 is verbatim as quoted and omits RuntimeError; json.loads at :614 is inside that try. `json.loads('['*4090)` raises RecursionError (MRO RecursionError->RuntimeError->Exception; isinstance ValueError == False) and 4090 <= MAX_FRAME_BYTES so read_frame:217 accepts the frame. Peer gate at :607 admits the broker uid before any read. I ran gss.handle_connection(FakeConn(5002, 4-byte-len(4090)+b'['*4090), 5002, ...) -> ESCAPED handle_connection: RecursionError. I ran gss.serve_forever with three queued items -> ESCAPED serve_forever: RecursionError, connections accepted: 1, remaining queued: 2 (the second connection was never accepted). serve_forever:716-720 is finally-only. run_supervisor.py:141-162 is try/finally with NO except and os.unlink(sock_path) at :160, so the socket file is removed and there is no restart supervision. I tried to refute it four ways and all four failed: (a) no recursion-depth or nesting guard anywhere (grep for 'recursion'/'setrecursionlimit' across engine/runtime and engine/tests returns nothing); (b) the peer gate does not block it since the broker uid is exactly the admitted one; (c) _try_write is never reached because the exception escapes before :634; (d) nothing upstream of json.loads pre-validates the body. SEVERITY LOWERED P2 -> P3, not because the walkthrough is weaker than claimed but because the impact is identical to SUP-DOS-R1, which the same reviewer rated P3: availability only, adversary 2 (the broker service account, which drives the chain anyway), no lease, no attestation, no trusted_verified, and the operator-restart recovery is the same for both. Rating the crash P2 and the hang P3 for the same principal against the same service is inconsistent. It is a genuine defect and the docstrings at :599 and :697 are genuinely false, but it does not move the single question.

**Reviewer re-read.** `engine/runtime/governed_supervisor_server.py:626 (except tuple verified verbatim, no RuntimeError), :614 (json.loads inside try), :607 (peer_is_broker gate before read), :217-224 (4090 <= 8192 accepted), :699-720 (serve_forever try/finally, no except); engine/ci/live/run_supervisor.py:141-162 (try/finally, no except, os.unlink at :160), :142 serve_forever call; engine/ci/live/run_live_turn.sh:260 (start_server "$SUPERVISOR_USER" run_supervisor.py); executed: RecursionError escapes both handle_connection and serve_forever on Python 3.13.14; same tuple defect confirmed at engine/runtime/isolated_signer_server.py:273 and engine/runtime/challenge_authority_server.py:241`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor_server.py:626` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-35` · The only regression test guarding the F-11 fix never reaches the code it is supposed to guard — it is rejected by the frame-length bound and passes identically on the unfixed code

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | None — this is a test-integrity defect, not an exploitable path. It matters because it is the evidence the ledger's ✅ rests on. |
| **Location** | `engine/tests/test_governed_supervisor_server.py:310` |
| **Group** | `f11-dos` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** `_frame` (:191-193) builds the body with plain `json.dumps(obj)`, i.e. ensure_ascii=True, so each U+0080 is emitted as the SIX ASCII characters ``. 3000 of them produce an 18010-byte body, which read_frame rejects at :217-220 (`frame length 18010 exceeds bound 8192`) before dispatch is ever entered. The amplification the test is named for never happens, `_bounded_error` is never exercised, and `_try_write`'s FrameError branch is never exercised. The original attack used RAW UTF-8 (0xC2 0x80, 2 bytes each) precisely so the frame would fit under 8192 — the test does not reproduce that encoding.

**Code.**
```
def test_an_amplified_error_reply_never_tears_down_the_connection(self):
        hostile = {"op": "" * 3_000}
        conn = FakeConn(BROKER_UID, inbound=_frame(hostile))
```

**Walkthrough.**

1. The test builds `hostile = {"op": "" * 3000}` (verified in the raw bytes: `b'hostile = {"op": "\xc2\x80" * 3_000}'`).
2. `_frame(hostile)` at :191-193 does `json.dumps(obj).encode("utf-8")` — default ensure_ascii=True. I ran it: the body is 18010 bytes.
3. `_handle(conn)` -> handle_connection -> read_frame:214 reads length=18010, :217 `if length > MAX_FRAME_BYTES` -> 18010 > 8192 -> FrameError('frame length 18010 exceeds bound 8192').
4. That is a 40-character message, so `_bounded_error` (:645-648) returns it unchanged and `write_frame` emits a ~60-byte frame. I ran the real module with this exact input and got `{'ok': False, 'error': 'frame length 18010 exceeds bound 8192'}`.
5. The two assertions (`assertFalse(reply['ok'])`, `assertLessEqual(len(conn.out), MAX_FRAME_BYTES + 4)`) are both satisfied by the frame-bound rejection alone. Delete `_bounded_error` and the `except FrameError` branch in `_try_write` and this test still passes.

**Why it matters.** The ledger's ✅ for F-11 cites 'Error text bounded; _try_write degrades'. The fix is real — I verified it directly by replaying the original 8191-byte raw-UTF-8 attack (525-char bounded error, 682-byte reply) and by handing _try_write a 20 KB reply (53-byte degraded frame). But the repo has NO test that exercises either guard, so a future edit reverting them would ship green. Combined with F-11-R1 this means the F-11 row is backed by prose and a vacuous test rather than by executable evidence.

**Adversarial review (P3).** SURVIVES. I read the raw bytes of the test file rather than trusting the rendered quote: the source literally contains `hostile = {"op": "\xc2\x80" * 3_000}`, i.e. 3000 copies of U+0080. _frame at :191-193 is `json.dumps(obj).encode("utf-8")` with default ensure_ascii=True, so each U+0080 becomes the six ASCII chars . I computed the body: exactly 18010 bytes, matching the finding. read_frame:217 rejects 18010 > 8192 with a 40-char FrameError, which _bounded_error passes through unchanged, so both assertions (assertFalse(ok), assertLessEqual(len(out), 8196)) are satisfied by the frame-length rejection alone and never touch the amplification path. I tried to refute this by looking for any OTHER test covering the fix: grep for `_bounded_error`, `MAX_ERROR_CHARS` and `_try_write` across engine/tests returns exactly ONE hit, a comment at test_governed_supervisor_server.py:313 — no test anywhere exercises either guard. I also confirmed the fix itself is real (so this is a test-integrity gap, not a false ledger claim about the code): replaying the original attack with ensure_ascii=False produced an 8192-byte frame, ok=False, a 525-char bounded error and a 682-byte reply. P3 confirmed: no adversary, no exploit path, purely the quality of the evidence backing the ledger's checkmark.

**Reviewer re-read.** `engine/tests/test_governed_supervisor_server.py:310-319 (test body, raw bytes confirm \xc2\x80), :191-193 (_frame uses ensure_ascii default); computed json.dumps body length = 18010; engine/runtime/governed_supervisor_server.py:217-220 (rejects at 18010 > 8192), :645-648 (_bounded_error passes a 40-char message through); grep across engine/tests for _bounded_error|MAX_ERROR_CHARS|_try_write -> only the comment at test:313`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/tests/test_governed_supervisor_server.py:310` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-36` · The governed-supervisor front door has NO socket timeout at all and a serial accept loop — the exact F-31 defect, on the service that IS deployed, while the remediation armed only the binary that is not

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account. The socket is 0o777 (run_supervisor.py:135) so any local account can connect, but peer_is_broker refuses non-broker peers fast, and the ~40-byte refusal always fits the peer's minimum receive buffer, so a weaker adversary cannot hold the loop. Only the broker uid can. |
| **Location** | `engine/runtime/governed_supervisor_server.py:183` |
| **Group** | `f11-dos` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** bind_listener (:723-736) never calls settimeout; accept_socket_conn (:739-742) and SocketPeerConn.__init__ (:175-177) never arm one on the ACCEPTED socket; recv_exactly (:179-188) therefore blocks indefinitely in `self._sock.recv()`. serve_forever (:699-720) handles every connection inline with no thread, no connection cap, no rate limit. The F-31 remediation added `set_read_timeout`/`set_write_timeout` to apps/desktop/src-tauri/broker/src/main.rs:193-199 — a binary nothing launches — and added nothing to the three Python servers the live kit actually starts. `engine/runtime/brops_socket.py:130` shows the codebase knows how to call `conn.settimeout`; the supervisor front door does not use it.

**Code.**
```
def recv_exactly(self, n: int) -> bytes:
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self._sock.recv(remaining)
```

**Walkthrough.**

1. run_live_turn.sh:260 starts run_supervisor.py as $SUPERVISOR_USER; :135 chmods the socket 0o777; :138-153 enters serve_forever.
2. The broker service account connects. SocketPeerConn.__init__ (:175-177) reads SO_PEERCRED — no timeout is set on the socket at any point.
3. handle_connection:607 admits it (broker uid). Control reaches :613 read_frame.
4. The peer sends 4 bytes declaring length 8192 (read_frame:217 accepts 8192 <= 8192), then sends NOTHING and never closes.
5. read_frame:221 `body = conn.recv_exactly(length)` -> recv_exactly:183 `self._sock.recv(8192)` blocks with no SO_RCVTIMEO — forever.
6. serve_forever:699-702 never reaches `accept_one()` again. Every later governed turn stalls at the supervisor hop: no accept-open, no launch-gate, no attest-run. There is no restart supervision in run_supervisor.py.
7. A drip variant is unnecessary here because there is no deadline at all to evade; a 3-byte partial header suffices.

**Why it matters.** Availability only — no lease, attestation or trusted_verified is produced, and the party who can do it is the party that drives the chain anyway, so it is close to self-inflicted (which is why P3, matching the original F-25 reasoning). It matters to the single question only as an honesty gap: the F-31/F-32/F-36 ledger row says 'every accepted broker connection is armed with a read/write deadline', which reads as if the proof-kit DoS class was addressed. It was addressed on the ONE listener that is never started (brops-broker) and left untouched on all three that are (supervisor, challenge authority at challenge_authority_server.py:104, isolated signer at isolated_signer_server.py:132).

**Adversarial review (P3).** SURVIVES. Verified line by line. bind_listener (governed_supervisor_server.py:723-736) calls only socket/bind/listen — no settimeout, no setsockopt. accept_socket_conn (:739-742) does listener.accept() then SocketPeerConn(sock). SocketPeerConn.__init__ (:175-177) stores the socket and reads peercred; it never arms a deadline. recv_exactly (:179-188) blocks in self._sock.recv(remaining) with no SO_RCVTIMEO. read_frame:221 calls recv_exactly(length) after accepting a declared 8192, so a peer that sends the 4-byte header and then nothing blocks forever. serve_forever:699-720 is a strictly serial while-loop with no thread, no cap, no rate limit. I grepped the whole engine tree for settimeout/SO_RCVTIMEO/setsockopt: the ONLY hit is engine/runtime/brops_socket.py:130, a separate tools-stack module the three live servers do not use (run_supervisor.py imports governed_supervisor_server, not brops_socket). The identical gap is present in challenge_authority_server.py (bind_listener :294-307) and isolated_signer_server.py (bind_listener :322-335). I tried to refute the adversary claim and confirmed the reviewer's own limiting reasoning: a NON-broker peer cannot hold the loop, because handle_connection:607 refuses before read_frame and the ~40-byte refusal is written by sendall into the socket buffer and returns immediately — so despite the 0o777 socket mode at run_supervisor.py:135, only the broker uid reaches the blocking read. P3 is correct: availability only, adversary 2, no forgery. Its real value is the honesty gap it names — the ledger's F-31 row reads as if the proof-kit DoS class was handled, and the deadline was added only to the Rust binary nothing launches, not to the three Python listeners the live kit actually starts.

**Reviewer re-read.** `engine/runtime/governed_supervisor_server.py:723-736 (bind_listener, no settimeout), :739-742 (accept_socket_conn), :175-188 (SocketPeerConn.__init__ + blocking recv_exactly), :221 (recv_exactly(length)), :699-720 (serial loop); engine/runtime/challenge_authority_server.py:294-307; engine/runtime/isolated_signer_server.py:322-335; grep settimeout across engine/runtime -> only brops_socket.py:130; engine/ci/live/run_live_turn.sh:259-261 (starts all three); engine/ci/live/run_supervisor.py:135 (chmod 0o777)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `engine/runtime/governed_supervisor_server.py:183` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-37` · The broker's per-connection deadline bounds one connection but not the service: the accept loop is still serial with no concurrency or connection limit, and the deadline is per-syscall so a drip peer evades it entirely

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 3 — the interactive login user (or 4, any local account that happens to be `allowed_uid`). main.rs:154-157 defaults allowed_uid to the broker's own getuid(), but the documented deployment allowlists the renderer/login uid, which the module header at :5 calls 'a mutually-distrusting client'. |
| **Location** | `apps/desktop/src-tauri/broker/src/main.rs:185` |
| **Group** | `f11-dos` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The deadline is armed correctly (accepted socket, before the first read, fail-closed on arming failure) but it is the WRONG control for the defect. SO_RCVTIMEO is re-armed per recv syscall, so it bounds inter-byte silence, not connection lifetime; and the loop at :185 is still strictly serial with no thread::spawn, no connection cap and no rate limit anywhere in the file. Bounding one connection does not bound the service when the service can only ever hold one connection.

**Code.**
```
for stream in listener.incoming() {
            match stream {
                Ok(mut s) => {
                    let deadline = std::time::Duration::from_millis(CONN_IO_TIMEOUT_MS);
                    if s.set_read_timeout(Some(deadline)).is_err()
```

**Walkthrough.**

ATTACK A (drip — unbounded hold): 1. Peer connects; :193-199 arms a 120s deadline; :200 enters handle_conn. 2. :429-431 peer auth passes (it IS allowed_uid). 3. read_one_frame:461-477 loops: :468 `stream.read(&mut chunk)` with a 1024-byte chunk. 4. The peer emits 1 byte every 119s. Each read returns Ok(1) well inside the deadline, which is then re-armed for the next syscall — the timeout never fires. 5. It first sends a 4-byte prefix declaring 8192; FrameDecoder::next_frame (ipc_framing.rs:89-92) accepts any declared <= 8192 and returns Ok(None) until the body is complete (:93-96). 6. The single accept thread is held ~8192 * 119s ≈ 11 days. On completion the peer opens a new connection and repeats.
ATTACK B (sequential reconnect — the deadline does not even need evading): 1. `while :; do nc -U /run/brops/broker.sock >/dev/null & sleep 121; done`. 2. Each fully-silent connection occupies the serial loop for the full 120s before :468 returns Err(WouldBlock) and :201 logs 'connection refused'. 3. Since :185 accepts exactly one connection at a time and there is no queue-drain concurrency, the broker is unavailable for essentially 100% of wall-clock time, indefinitely. The pre-fix behaviour was 'denied until restart'; the post-fix behaviour is 'denied until the attacker stops'. Operationally identical.

**Why it matters.** No forgery: a wedged broker produces no reply at all, and the renderer renders transport failure as blocked (governed_turn.rs:37-39, broker_client.rs transport_failure_reason -> UpstreamBlocked). Severity stays P3 because reachability is unchanged from the original refutation — I re-ran the grep and NOTHING in the tree launches brops-broker (only the two Cargo.toml name lines and the binary's own eprintlns match). But note the original refutation's SECOND leg is now stale: build_governed_executor (:216-387) can serve the real LinuxGovernedTurnChain when BROPS_BROKER_CONFIG is set and the TCB floor passes, so 'even if started it denies nothing' no longer holds. If this listener is ever deployed, this is the front door of the trust chain being deniable by the login user.

**Adversarial review (P3).** SURVIVES. Every cited line verified in apps/desktop/src-tauri/broker/src/main.rs: :52 CONN_IO_TIMEOUT_MS = 120_000; :185 `for stream in listener.incoming()`; :193-199 arms set_read_timeout/set_write_timeout on the accepted `s` with a fail-closed `continue`; :200 handle_conn. The arming is correct (right socket, before the first read, fail-closed) — that part of the remediation is sound and I could not fault it. But the two claimed evasions hold. ATTACK A: read_one_frame (:458-478) loops on `stream.read(&mut chunk)` at :468; SO_RCVTIMEO is per-syscall, so a byte every 119s never trips it, and FrameDecoder::next_frame (ipc_framing.rs:83-96) returns Ok(None) for any declared <= 8192 until the body completes — I re-read next_frame and confirmed it neither times out nor bounds elapsed time, only the declared length. ATTACK B: I grepped the file for thread::spawn and any connection cap or rate limit and found NONE (the only thread::spawn under apps/desktop/src-tauri is win-broker/src/lib.rs:202), so the loop holds exactly one connection and a 121s reconnect loop denies ~100% of wall-clock. P3 CONFIRMED, and the reachability leg holds: I re-ran the grep for brops-broker/brops_broker across .sh/.yml/.yaml/.service/.toml/.py/.rs/.json and every hit is a Cargo.toml name, a `use brops_broker::` import, or the binary's own eprintln — nothing launches it. No forgery path: a wedged broker returns no reply and transport_failure_reason maps to TurnReason::UpstreamBlocked (broker_client.rs:48-50). The reviewer's note that the original refutation's second leg is stale is also correct — build_governed_executor at :216+ can serve the real LinuxGovernedTurnChain behind BROPS_BROKER_CONFIG + the TCB floor, so only 'not deployed' holds the severity down now.

**Reviewer re-read.** `apps/desktop/src-tauri/broker/src/main.rs:52, :185, :193-199, :200, :458-478 (read loop at :468), :216-387 (build_governed_executor, TCB floor at :281-286); apps/desktop/src-tauri/core/src/ipc_framing.rs:83-96 (next_frame: declared<=8192 -> Ok(None), no time bound); apps/desktop/src-tauri/core/src/broker_client.rs:48-50 (transport_failure_reason -> UpstreamBlocked); grep: no thread::spawn / cap / rate limit in broker/src/main.rs; grep: nothing in the tree launches brops-broker`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/broker/src/main.rs:185` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-38` · The renderer→broker client's 120s deadline is per-recv, so a drip endpoint can hold a synchronous Tauri command for ~11 days despite the F-32/F-36 fix

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account, or whoever can bind /run/brops/broker.sock. Not reachable by the model or by an unprivileged account that cannot own that path. |
| **Location** | `apps/desktop/src-tauri/src/governed_turn.rs:85` |
| **Group** | `f11-dos` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** `set_read_timeout` at :54 sets SO_RCVTIMEO, which applies to each recv syscall, not to the read_to_end operation as a whole. `Take::read_to_end` keeps issuing reads until it hits the 8256-byte limit or EOF, so an endpoint that emits one byte just inside each 120s window is never timed out. The memory bound is real and does its job; the liveness bound is weaker than the comment at :24-28 ('a silent socket must eventually surface as a transport failure ... never as a wedged command') claims.

**Code.**
```
let mut limited = (&mut self.0).take(MAX_REPLY_BYTES);
            limited.read_to_end(&mut buf).map_err(|_| TransportError::Io)?;
```

**Walkthrough.**

1. A renderer invoke reaches `#[tauri::command] pub fn governed_turn_execute` (:33-34) — a plain sync `pub fn`, not async. 2. :50 connects to /run/brops/broker.sock; :54-55 arm 120s read and write timeouts. 3. :74-77 send_all writes the request frame. 4. :78-92 recv_all: `(&mut self.0).take(8256)` then `read_to_end`. 5. The endpoint that owns the socket accepts, reads the request, then emits ONE byte every 119s. Each `read` returns Ok(1) before SO_RCVTIMEO expires and the timer restarts. 6. read_to_end continues until it has 8256 bytes: 8256 * 119s ≈ 11.4 days. During that window the command has not returned. 7. Only then does :86-90 fire (`buf.len() >= MAX_REPLY_BYTES` -> TransportError::Io), and the renderer finally sees a blocked result. 8. The fully-silent variant the original F-36 filed is genuinely fixed — with zero bytes the first recv times out at 120s and :85 returns Err.

**Why it matters.** Availability only, and only against the desktop process, not the trust chain — the reply still has to survive decode_one (broker_client.rs) and the renderer cannot mint trusted_verified regardless. I report it because the assignment asked specifically whether the deadline is re-armed per read, and because the module comment at :24-28 states a liveness property stronger than the code delivers. It does NOT reopen F-32/F-36: both filed exploit paths (unbounded memory, never-writes-never-closes hang) are genuinely dead.

**Adversarial review (P3).** SURVIVES as a narrow liveness residual, and the reviewer is right that it does NOT reopen F-32/F-36. Verified in apps/desktop/src-tauri/src/governed_turn.rs: connect_broker sets set_read_timeout/set_write_timeout (:54-55) immediately after UnixStream::connect and before any I/O; recv_all does `let mut limited = (&mut self.0).take(MAX_REPLY_BYTES); limited.read_to_end(&mut buf)` with MAX_REPLY_BYTES = MAX_FRAME_PAYLOAD_BYTES + 64 = 8256. The defect claim is mechanically correct: SO_RCVTIMEO bounds each recv syscall, and Take::read_to_end keeps issuing reads until the inner reader EOFs or the 8256-byte limit is exhausted, so a peer emitting one byte per 119s window is never timed out and the sync `pub fn governed_turn_execute` (:33-34, not async) does not return for ~8256*119s. I tried to refute it: the cap does NOT terminate early on a partial frame (read_to_end has no framing awareness — the `>= MAX_REPLY_BYTES` refusal at :86-90 only fires once the full 8256 are resident), and there is no wall-clock deadline anywhere in the function. P3 is correct and I would not go higher: availability only, against the desktop process not the trust chain; the adversary must already own /run/brops/broker.sock, i.e. be the broker service — in-scope as adversary 2, but a hostile broker DoSing its own client is close to self-inflicted; and no forgery is possible because the reply must still survive decode_one (ipc_framing.rs:48-64) and the renderer cannot mint trusted_verified. LINUX ONLY: connect_broker's non-linux arm (:60-63) returns Err() unconditionally, so this is unreachable on the Owner's Windows host. The module comment at :24-28 does overstate the liveness property the code delivers.

**Reviewer re-read.** `apps/desktop/src-tauri/src/governed_turn.rs:22 (MAX_REPLY_BYTES = MAX_FRAME_PAYLOAD_BYTES + 64 = 8256), :24-28 (overstated liveness comment), :33-34 (sync tauri::command), :50-56 (connect then arm both timeouts before I/O), :78-92 (take + read_to_end + >= cap refusal), :60-63 (non-linux arm returns Err); apps/desktop/src-tauri/core/src/ipc_framing.rs:15 (MAX_FRAME_PAYLOAD_BYTES 8192), :48-64 (decode_one); apps/desktop/src-tauri/core/src/broker_client.rs:38-44 (send_governed_turn: encode -> send_all -> recv_all -> decode_one)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/src/governed_turn.rs:85` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-39` · The F-29 'bound to the verifying key' guard is still a tautology at all three real call sites — both operands are the same manifest lookup, now laundered through a hex decode/encode round trip

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | none required — this is an inert-guard / attestation-honesty defect. No in-scope adversary gains capability from it; it is reported because the ledger marks F-29 CLOSED on the strength of this comparison. |
| **Location** | `apps/desktop/src-tauri/core/src/production_trust.rs:73` |
| **Group** | `f26-binding` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** resolve_trust_state still performs its own resolve_production_key (production_trust.rs:60) and compares that key's public_key_hex against the caller's envelope_verifying_key_hex. At every real call site the caller's value is derived from a resolve_production_key over the SAME manifest value with the SAME key_id and protocol, decoded to 32 bytes and re-encoded to lowercase hex. Because resolve_production_key selects by `find(|k| k.key_id == key_id)` (key_manifest.rs:131) it is time-independent for a fixed manifest, and hex32/verifying_key_hex are an exact round trip, so the two operands are provably equal whenever the resolution succeeds at all. The NoTrustedManifest branch at :74 is unreachable in production and the regression test at :141-154 asserts a state no call site can reach — the same defect the previous audit reported, with one more indirection.

**Code.**
```
if k.public_key_hex.to_lowercase() != envelope_verifying_key_hex.to_lowercase() {
                return TrustState::NoTrustedManifest("signing key does not match the verifying key");
            }
```

**Walkthrough.**

Linux proof kit (the most airtight instance — both operands are produced 120 lines apart in one function):
1. proof/src/bin/live_turn.rs:313 — `let iso = resolve_production_key(&manifest, &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now)`.
2. live_turn.rs:322 — `let iso_pub = hex32(&iso.public_key_hex)`; hex32 (live_turn.rs:97-109) requires exactly 64 hex chars and decodes them faithfully.
3. live_turn.rs:334 — `isolated_signer_public_key: iso_pub` in ResolvedTurn; live_turn.rs:396-401 hands a clone to the chain via FixedResolver, and chain_executor.rs:355 passes exactly those bytes to verify_and_accept as PinnedKeys::isolated_signer_public_key. So the argument really is 'the bytes handed to verify_and_accept' — the ledger's literal claim is true.
4. live_turn.rs:432-438 — `resolve_trust_state(Some(&manifest), &signer_key_id, RECEIPT_ENVELOPE_ARTIFACT_TYPE, now, &verifying_key_hex(&resolved.isolated_signer_public_key))`. The first four arguments are the identical (manifest, key_id, protocol, now) tuple used at step 1 — `now` is computed once at live_turn.rs:137 and reused.
5. production_trust.rs:60 re-runs resolve_production_key with that identical tuple. key_manifest.rs:131 `manifest.keys.iter().find(|k| k.key_id == key_id)` returns the same entry regardless of now_ms (the window is validated after selection, at :138, and would have failed step 1 too), so `k.public_key_hex` is byte-identical to `iso.public_key_hex`.
6. production_trust.rs:73 therefore evaluates `iso.public_key_hex.to_lowercase() != verifying_key_hex(hex32(iso.public_key_hex))`. verifying_key_hex (production_trust.rs:41-47) emits `{b:02x}` per byte, i.e. exactly `iso.public_key_hex` lowercased. The condition is always false; TrustState::Production is returned unconditionally at :76.
Windows named-pipe driver: win_live_turn.rs:117 `manifest_for_trust = manifest.clone()` before the manifest is moved into ManifestResolver at :145-153; resolver.rs:267/276/279 sets last_verifying_key = hex32(resolve_production_key(&self.manifest, &self.signer_key_id, PROTO, now_ms).public_key_hex); win_live_turn.rs:230-240 compares verifying_key_hex(that) against resolve_trust_state(Some(&manifest_for_trust), same key_id, same protocol) — same clone, same key_id, same first-match → equal.
Windows in-process proof (reachable from the shipped app via commands.rs:2029 demonstration_verified_reply and governed_selftest.rs): proof.rs:182 clone, proof.rs:292-293 resolver, proof.rs:317-327 the same comparison → equal.
Refutation attempts that failed: (a) a manifest with two entries sharing a key_id and disjoint windows cannot cause divergence, because find() takes the first match and then errors on the window rather than falling through; (b) neither resolver re-reads the manifest from disk per turn (manifest_resolver.rs:41-51 and resolver.rs:101-112 hold an owned KeyManifest), so no mid-run swap can be caught; (c) case/format differences are absorbed by to_lowercase() on one side and {b:02x} on the other.

**Why it matters.** The ledger closes F-29 by asserting the production verdict is 'compared against the key the CHAIN verified under, not a second manifest lookup of itself'. The second lookup was not retired — it moved inside resolve_trust_state (production_trust.rs:60) — and the caller-side value is still that same lookup's output. Relative to the single question the answer is unchanged: the property (production badge bound to the signing key) still holds BY CONSTRUCTION and no in-scope adversary can force a divergence, because the manifest is pinned to the TCB root (manifest_resolver.rs:76-79, win_live_turn.rs:99-108). What is false is the claim that a check enforces it. The recording point in the Windows resolver is the resolution step, not the verify_and_accept call, so this guard would also not catch a future chain_executor that built PinnedKeys from a different source — which is precisely the failure mode the guard advertises.

**Adversarial review (P3).** SURVIVES. Quote verified verbatim at production_trust.rs:73. I enumerated every non-test caller of resolve_trust_state in src-tauri (grep: exactly 3 — live_turn.rs:432, win_live_turn.rs:234, proof.rs:321) and at each the second operand is a hex32 round-trip of the SAME resolve_production_key result over the SAME owned manifest value and key_id. key_manifest.rs:131 is first-match by key_id and time-independent (window checked after selection at :138), so a duplicate-key_id manifest cannot cause divergence, and neither resolver re-reads the manifest mid-turn (manifest_resolver holds an owned KeyManifest; win-live resolver.rs:101-112 likewise). Refutation attempts that failed: (a) Windows resolver uses a FRESH now_ms() at resolver.rs:250 while the caller passes the start-of-run `now` — different clocks, but find() by key_id returns the same entry either way, so still identical; (b) manifest_for_trust is a clone taken BEFORE the move (win_live_turn.rs:117, proof.rs:182) — byte-identical, not a second read; (c) uppercase or malformed public_key_hex cannot create divergence, because verifying_key_hex emits lowercase {b:02x} (production_trust.rs:41-47) and a non-64-char hex makes hex32 return None so the resolver fails the turn closed (resolver.rs:276) long before the compare. The NoTrustedManifest branch at :74 is unreachable at every real call site and the test at :141-154 asserts a state no caller can produce. Severity held at P3: no in-scope adversary gains anything — the manifest is root-pinned to the TCB anchor (win_live_turn.rs:99-108, manifest_resolver.rs pinned root), so none of them can introduce a divergent key. This is an inert-guard / attestation-honesty defect, and it directly contradicts the AUDIT_LEDGER row's wording ('not a second manifest lookup of itself'), which is why it is worth reporting.

**Reviewer re-read.** `production_trust.rs:41-47, :60, :73-75, :141-154; key_manifest.rs:125-145 (find-by-key_id, window after selection); live_turn.rs:97-109 (hex32), :313-325, :334, :396-401, :432-438; resolver.rs:250, :267-279 (last_verifying_key = hex32 of the same lookup); win_live_turn.rs:117, :120-124, :230-240; proof.rs:182, :185-187, :292-293, :317-327; chain_executor.rs:353-358 (PinnedKeys from resolved.isolated_signer_public_key)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/core/src/production_trust.rs:73` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-40` · Windows: the F-27 remediation makes the named-pipe live driver fail closed — completed_at_ms is the driver's start-of-process clock while challenge_accepted_at_ms is now the pipe server's real accept clock, and the Windows signer refuses completed_at < challenge_accepted_at

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | none — no adversary is involved or benefits; this is a fail-closed correctness regression in the Windows live kit, reported because it means the F-27 property the ledger claims is 'asserted end-to-end' is not exercised on Windows and the path that would exercise it cannot complete. |
| **Location** | `apps/desktop/src-tauri/win-live/src/servers.rs:988` |
| **Group** | `f26-binding` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** After the F-27 change the two timestamps in a Windows named-pipe run come from two different clocks read at two different times, in the wrong order: challenge_accepted_at_ms is the pipe server's real clock at accept-open (later), while completed_at_ms is the driver's clock captured as the first statement of main (earlier). The signer's ordering gate then refuses to mint an envelope. There is no skew tolerance on that comparison (COMPLETED_SKEW_MS applies only to the future-bound check on the next line).

**Code.**
```
if requested_at < 0
            || completed_at < requested_at
            || completed_at < challenge_accepted_at
            || completed_at > now_ms + COMPLETED_SKEW_MS
        {
            return self.refuse_sign("timestamp_invalid");
        }
```

**Walkthrough.**

1. win-live/src/bin/win_live_turn.rs:72 — `let now = now_ms();` is the first statement of run(), before the config load (:75-82), manifest read+parse (:85-92), root signature verify (:106), floor load+verify (:111), resolver construction (:145-153), DB open + schema init (:203-209) and the create-pending/issue authority hops.
2. win_live_turn.rs:195 — `GovernedExecutionCore::new(params, produce, supervisor_op, now)` freezes that start-time value into the execution core.
3. win-live/src/execution.rs:100 and :131 — the complete-run body sends `"completed_at_ms": self.now_ms`, i.e. the start-time value, not a completion time.
4. win-live/src/pipe.rs:157 — each named-pipe server dispatches with its OWN fresh clock: `core.handle(&req, now_ms())`.
5. win-live/src/servers.rs:570 — accept_open writes `challenge_accepted_at_ms: now_ms` from that per-request server clock. Because accept-open happens after everything in step 1 plus two authority hops, this value is strictly greater than the step-1 value on any run where more than 0 ms elapses.
6. servers.rs:716 — attest-run emits the evidence carrying `a.challenge_accepted_at_ms`; the supervisor's complete_run (servers.rs:659-700) copies the caller's completed_at (`ints[0]`) without comparing it to the acceptance clock, so the mismatch is not caught there.
7. servers.rs:984-991 — sign-result computes `completed_at` and `challenge_accepted_at` from the evidence and hits `completed_at < challenge_accepted_at` → `refuse_sign("timestamp_invalid")` → reply `ok:false`.
8. chain_executor.rs:338 -> hop() at :251-254 sees `ok:false` and returns Err(TurnReason::UpstreamBlocked); win_live_turn.rs:219-221 prints `RESULT: blocked reason=chain:UpstreamBlocked` and exits 1.
Refutation attempted: the only way the run survives is if steps 1 and 5 land in the same millisecond, which requires the config read, two file reads, an Ed25519 manifest verification, a floor verification, a SQLite schema init and two named-pipe round trips to complete inside 1 ms. The Linux twin does not have this problem — chain_executor.rs:863 computes `let now = Self::now_ms();` AFTER child.wait() (:807) and the store writes (:821-854), so its completed_at is genuinely later than the supervisor's accept clock.

**Why it matters.** The ledger's F-27 row says the property is 'now asserted end-to-end (accept at T-2000, complete at T)'. That assertion exists only in the Linux engine test (test_governed_chain_e2e.py:430-469). On the platform the Owner actually runs, the only path with two real clocks cannot reach a signed envelope at all, and the only Windows path that does complete freezes both clocks to the same value (see F-27-W2). So on Windows the fix is simultaneously unexercised and, where it would be exercised, run-breaking. Fail-closed, so it does not endanger the single question — but a green Windows run is not available as evidence that F-27 is closed.

**Adversarial review (P3).** SURVIVES as a defect; one causal claim in the title is unverifiable from the snapshot. Quote verified at servers.rs:987-993 (finding cites 988). Walked it: win_live_turn.rs:71 takes `now` as the FIRST statement of run(), before config load (:79), manifest read+parse (:85-92), TCB root pin + Ed25519 verify_manifest (:99-108), floor load+verify (:111), resolver construction (:145-153) and DB open (:203-209); that same `now` is frozen into the execution core at :195 and emitted as completed_at_ms at execution.rs:131. Meanwhile the supervisor is a SEPARATE process (win_supervisor.rs:47 pipe::run_server) and pipe.rs:157 dispatches every request with a fresh now_ms(), so accept_open stamps challenge_accepted_at_ms = that later clock (servers.rs:570). It survives complete-run untouched (servers.rs:660-717 copies only ints[0] as completed_at_ms; COMPLETION_FIELDS at :329-337 excludes the acceptance timestamp), reaches the evidence at :855, and hits `completed_at < challenge_accepted_at` at :989 -> refuse_sign('timestamp_invalid') -> hop() sees ok:false (chain_executor.rs:251-254) -> UpstreamBlocked. Only a sub-millisecond run survives, which is not achievable given two file reads, two Ed25519 verifications, SQLite schema init and two pipe round trips. Refutations that failed: no other Windows completion path exists (GovernedExecutionCore is the only GovernedExecution impl in win-live); no skew tolerance applies (COMPLETED_SKEW_MS only bounds the future-check on the next line); the Linux twin is NOT affected because chain_executor.rs:863 takes a fresh clock after child.wait() at :807, so its completed_at is genuinely later. CAVEAT I could not verify: the snapshot has no git history, so I cannot confirm the F-27 remediation CAUSED this (title says 'makes ... fail closed'). The defect itself is confirmed regardless of when it appeared. Severity P3: fail-closed, zero adversary involvement, no path to a false trusted_verified. Its real weight is evidentiary — no green Windows named-pipe run is available to support the ledger's F-27 'closed'.

**Reviewer re-read.** `win_live_turn.rs:71, :195, :219-221; execution.rs:62-63, :100, :113, :131; pipe.rs:157; win_supervisor.rs:47; win_signer.rs:41; servers.rs:329-337 (COMPLETION_FIELDS), :560-580, :660-717, :754-765, :852-861, :985-993; chain_executor.rs:251-254 (ok:false -> UpstreamBlocked), :807, :863-883 (Linux completed_at is post-wait)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/servers.rs:988` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-41` · Windows in-process path (the one reachable from the shipped app) still emits the zero-duration receipt F-27 named: every core is driven with one frozen clock, so challenge_accepted_at_ms == completed_at_ms

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | none — honesty/coverage defect in the demonstration path; no adversary gains anything. |
| **Location** | `apps/desktop/src-tauri/win-live/src/proof.rs:232` |
| **Group** | `f26-binding` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** in_process_turn_produce passes a single caller-supplied now_ms to the transport for every hop, to the supervisor lifecycle closure, and to the execution core. The supervisor therefore stamps challenge_accepted_at_ms with exactly the same integer the execution reports as completed_at_ms, so the receipt this path signs still asserts a zero-duration turn — the precise shape F-27 was raised about — and passes the signer's ordering gate only by equality.

**Code.**
```
Ok(Box::new(InProcConn { core, now: now_ms, reply: None }))
```

**Walkthrough.**

1. proof.rs:232 — the in-process connector hands every hop `InProcConn { core, now: now_ms }`; proof.rs:63 dispatches with `self.now`, so accept-open sees the frozen value.
2. win-live/src/servers.rs:570 — accept_open sets `challenge_accepted_at_ms: now_ms` = that frozen value.
3. proof.rs:260 — `GovernedExecutionCore::new(params, exec_produce, supervisor_op, now_ms)`; execution.rs:100/131 send `"completed_at_ms": self.now_ms` = the same frozen value.
4. servers.rs:716 puts the acceptance value into the evidence; servers.rs:984-991 evaluates `completed_at < challenge_accepted_at` as false only because the two are equal; servers.rs:1073-1074 writes both into the signed payload.
5. The result is signed and accepted, and this is the path the shipped app reaches: commands.rs:2029 `brops_win_live::proof::in_process_turn_produce(&dir, now_ms, produce)` in demonstration_verified_reply, and the trust self-test in governed_selftest.rs.
Refutation attempted: I checked whether the supervisor core takes its own clock independently of the dispatch argument — it does not; servers.rs:442-449 threads the caller-supplied now_ms into accept_open/launch_gate, and only pipe.rs:157 (the separate-process host) ever supplies a real per-request clock.

**Why it matters.** F-27's substance is that the receipt's acceptance timestamp must be an independent supervisor observation rather than a value synthesized at completion. On the Windows in-process path — the only Windows path a user of the shipped app can drive — the two are still the same integer, so a receipt from that path carries no more lease-window information than before the fix. It does not create a bypass (the badge from that path is demonstration_verified, written by post_message_demonstration_verified at commands.rs:2055-2059, not trusted_verified), but it means the ledger's 'closed' for F-27 is a Linux-only statement and should be labelled as such.

**Adversarial review (P3).** SURVIVES. Quote verified at proof.rs:232. in_process_turn_produce threads ONE caller-supplied now_ms everywhere: the InProcConn dispatches every hop with self.now (proof.rs:59-67), the supervisor_op closure calls sup_a.handle(req, now_ms) (proof.rs:237-238), and GovernedExecutionCore is constructed with the same value (proof.rs:260). So servers.rs:570 stamps challenge_accepted_at_ms = N and execution.rs:131 reports completed_at_ms = N; the ordering gate at servers.rs:989 passes only by equality, and servers.rs:1073-1074 writes both equal values into the signed payload. I confirmed the supervisor core never takes an independent clock — servers.rs:442-449 threads the dispatch argument into accept_open/launch_gate, and pipe.rs:157 is the only site that supplies a real per-request clock. Reachability from the shipped app confirmed: commands.rs:2033 calls brops_win_live::proof::in_process_turn_produce inside demonstration_verified_reply with a single now_ms computed at :2029-2032. Severity P3 and no bypass: that path posts via repo::chat::post_message_demonstration_verified (commands.rs:2061), i.e. the demonstration_verified badge, never trusted_verified/production custody — and proof.rs:129-131/:173-176 pin it to the DEMO root, not tcb::ROOT_PUBLIC_KEY_HEX. Correctly scoped as an honesty/coverage defect: it shows the ledger's F-27 'asserted end-to-end' is a Linux-only statement (the only asserting test is engine/tests/test_governed_chain_e2e.py:430-469).

**Reviewer re-read.** `proof.rs:59-67, :232, :237-238, :260, :270-273 (requested_at_ms = now_ms too); servers.rs:442-449, :570, :852-861, :985-993, :1073-1074; execution.rs:100, :131; commands.rs:2029-2033, :2061; test_governed_chain_e2e.py:430-469 (the only discriminating assertion, Linux)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/proof.rs:232` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-42` · Windows: no evidence-head anti-rollback floor exists at all — the shared DDL's governed_evidence_head_floor has no Rust-twin counterpart

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 2 — the broker service account |
| **Location** | `apps/desktop/src-tauri/win-live/src/servers.rs:681` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:25 (F-09) claims 'the anti-rollback/anti-fork floor runs on every `complete-run`', and F-13/F-14 (line 33) claims the head floor is now 'a DURABLE per-task record ... advanced only after a chain verifies and only upward'. The Windows supervisor's complete_run performs the ONLY validation shown above — `n >= 0` — on evidence_event_count, evidence_last_sequence and evidence_head_sequence. There is no comparison against any prior head, no per-task floor file, no monotonicity requirement, and no `governed_evidence_head_floor` equivalent anywhere in the crate (grep of win-live for 'floor' returns only the MANIFEST-epoch AntiRollbackFloor in resolver.rs, which polices key-manifest epochs and says nothing about evidence heads).

**Code.**
```
let mut ints = [0i64; 4];
        for (i, k) in COMPLETION_INT_FIELDS.iter().enumerate() {
            match get_i64(p, k) {
                Some(n) if n >= 0 => ints[i] = n,
                _ => return refuse("complete-run", "malformed"),
            }
        }
```

**Walkthrough.**

1. tools/check_ledger_ddl_parity.py:49 lists `CREATE TABLE IF NOT EXISTS governed_evidence_head_floor` as a load-bearing clause the durable supervisor DDL must retain — that is the Linux/brops-core mirror pair only (parity tool lines 32-34). 2. The Windows supervisor holds no SQL: servers.rs:426 `accepted: Mutex<BTreeMap<String, Acceptance>>`. 3. complete_run (servers.rs:660-789) is the sole place the three evidence sequence numbers enter the supervisor, and the quoted lines 681-687 are their entire validation. 4. There is no read of any previous run's head: the Acceptance struct (servers.rs:381-403) is per-attempt and the map is keyed by execution_attempt_id, so nothing is ever compared across runs. 5. attest_run signs whatever was stored (servers.rs:856-858) and the signer copies it into the envelope (servers.rs:1075-1077). Concretely: turn A completes with head_sequence=100; turn B, in the same supervisor process, completes with head_sequence=1 and is attested and signed without objection.

**Why it matters.** The head floor is the control that makes an evidence chain orderable — it is the difference between 'this receipt names a head' and 'this receipt names a head at least as new as the last one this deployment attested'. On Windows it is absent, so an older, genuinely-signed evidence head can be re-presented on a later turn and nothing refuses. The ledger presents F-09 and F-13/F-14 as running on 'every complete-run' with no platform qualifier; on the platform the Owner runs, they run on none.

**Adversarial review (P3).** The code facts are correct and I confirmed them independently. The quoted block appears verbatim at servers.rs:681-687; it is the entire validation of the three sequence numbers. Acceptance (servers.rs:381-403) is per-attempt, the map is keyed by execution_attempt_id (servers.rs:426), and nothing in the crate reads a prior run's head — I grepped `evidence_head|head_floor|advance_evidence_head` across apps/desktop/src-tauri: the only floor implementation is core/src/supervisor_ledger.rs:838-900 (`evidence_floor_cas_body`, with StaleEvidence/EvidenceFork), which has NO caller in win-live; win_live_turn.rs:61 creates that schema on a `Connection::open_in_memory()` (win_live_turn.rs:203) the Supervisor never touches. tools/check_ledger_ddl_parity.py:32-34 compares only engine/runtime/supervisor_ledger.sql against core/schema/supervisor_ledger.sql, so the Windows twin is not a party to the gate. HOWEVER I partially refuted the finding's framing, hence P1→P3. (a) The F-13/F-14 ledger row IS platform-qualified: its title is literally '**F-06 / F-13 / F-14** engine anti-rollback honesty' and its fix text names `<store>/head-floor/<task>.floor.json` and `BRO_EVIDENCE_HEAD_FLOOR`, i.e. the Python engine. Only F-09's note ('the anti-rollback/anti-fork floor runs on every `complete-run`', AUDIT_LEDGER.md:25) is unqualified — and F-09 is marked '◑ partly', not closed. (b) The concrete attack is near-vacuous on Windows: every Windows turn reports the same constant head (3/3/3, per W-01), so there is no measured chain for a floor to order and no genuinely-signed older head to re-present. This is a consequence of W-01, not an independent defect: absent a recorder, the missing floor polices nothing.

**Reviewer re-read.** `win-live/src/servers.rs:681-687 (quote verified verbatim), :381-403, :426; win-live/src/bin/win_live_turn.rs:57-63, :203; core/src/supervisor_ledger.rs:838-900 (the real floor CAS — no win-live caller); tools/check_ledger_ddl_parity.py:32-34, :40-51; apps/desktop/AUDIT/AUDIT_LEDGER.md:25 (F-09 '◑ partly'), :33 (row titled 'engine anti-rollback honesty')`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/servers.rs:681` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-43` · Windows named-pipe servers have no read/write deadline and read the frame BEFORE peer authentication — any unprivileged local account permanently wedges the whole trust chain

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 4 — any other unprivileged local account (the pipe is created with a NULL DACL, so everyone may connect) |
| **Location** | `apps/desktop/src-tauri/win-live/src/pipe.rs:149` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** AUDIT_LEDGER.md:32 marks F-31/F-32/F-36 '✅ closed 2026-08-06' with 'every accepted broker connection is armed with a read/write deadline, so a silent renderer-uid peer can no longer hold the serial accept loop forever.' That remediation is in the Linux broker only. pipe.rs contains no SetNamedPipeHandleState, no timeout, no overlapped I/O and no thread spawn: the pipe is created PIPE_WAIT (pipe.rs:133), ReadFile is blocking (pipe.rs:69), and run_server handles exactly one connection at a time in a serial loop. Because the frame is read BEFORE the peer SID is authenticated, the attacker does not need to pass the SID gate to occupy the server.

**Code.**
```
let reply: Value = match read_frame_payload(h) {
                Ok(payload) => {
                    let sid = authenticate_pipe_client_sid(h).ok();
                    let allowed = sid.as_deref() == Some(allowed_peer_sid);
```

**Walkthrough.**

1. The server creates the pipe with a NULL DACL — pipe.rs:53-62 `SetSecurityDescriptorDacl(psd, true, None, false)` — deliberately, so 'everyone may connect'. 2. The pipe name is public: win_supervisor.rs:46 prints `RESULT: supervisor listening pipe={}` and it is the provisioned `{prefix}-supervisor` (win_provision.rs:153-157). 3. An unprivileged local process calls CreateFileW on `\\.\pipe\brops-live-supervisor` and simply never writes. 4. pipe.rs:144 ConnectNamedPipe returns; pipe.rs:149 calls read_frame_payload -> read_exact (pipe.rs:65-76) -> ReadFile blocks forever with no deadline. 5. The peer-SID check at pipe.rs:151-152 is never reached, so being unauthorized costs the attacker nothing. 6. run_server (pipe.rs:118-172) never returns from that iteration, so no further connection is ever accepted: the supervisor is dead for every subsequent governed turn. A 3-byte partial length prefix achieves the same. 7. The same code serves the authority and signer (win_authority.rs:35, win_signer.rs:41), so one process can wedge all three.

**Why it matters.** This is F-31's Windows twin, and it is reachable by the WEAKEST in-scope adversary with no credentials, no config access and no crypto. It denies the trust chain's front door on the platform the Owner runs, while the ledger records the class as closed. It is availability, not forgery — I could not turn it into a forged trusted_verified — but it is a total denial of the only path to one.

**Adversarial review (P3).** The mechanism is exactly as described and I could not refute it. pipe.rs:53-62 sets a NULL DACL (everyone may connect); pipe.rs:130-139 creates the pipe PIPE_WAIT with no SetNamedPipeHandleState, no overlapped I/O and no timeout anywhere in the module; read_exact (pipe.rs:65-76) blocks in ReadFile indefinitely; and the quoted lines are verbatim at pipe.rs:149-152 — `read_frame_payload(h)` runs BEFORE `authenticate_pipe_client_sid(h)`, so an unauthorized peer never has to pass the SID gate to occupy the loop. run_server (pipe.rs:118-172) is a strictly serial single-connection loop, so one wedged iteration starves every subsequent turn, and open_client's bounded retry (pipe.rs:181-204, 3000 × 3ms ≈ 9s) then returns Err. I confirmed the note that the frame must be read before impersonation is a genuine Win32 constraint (authenticate_pipe_client_sid's own doc-comment at win-broker/src/lib.rs:88-90 says the client must have written at least one byte), so this is not trivially fixable by reordering — but a deadline is what closes it, and there is none. DOWNGRADED P2→P3: it is availability-only (the finding says so honestly), and the affected servers are the three lab-kit bins (win_supervisor.rs:46, win_authority.rs:35, win_signer.rs:41), not the shipped desktop — the shipped Windows path into this crate is the in-process demonstration seam (commands.rs:2033, governed_selftest.rs:118) which uses no pipes at all. The F-31 ledger row (AUDIT_LEDGER.md:32) also describes the Linux broker's accept loop and the renderer→broker client, so the class-closure claim is arguably not asserted for this transport. It becomes P2 the moment the Windows kit is a shipped path.

**Reviewer re-read.** `win-live/src/pipe.rs:53-62 (NULL DACL), :65-76 (unbounded read_exact), :118-172 (serial loop, no deadline), :149-152 (quote verified verbatim), :179-206 (bounded client retry); win-live/src/bin/win_supervisor.rs:46 (pipe name printed); win-broker/src/lib.rs:88-90; apps/desktop/AUDIT/AUDIT_LEDGER.md:32`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/pipe.rs:149` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-44` · Windows: the pipe is destroyed and re-created between every connection, leaving a squat window, and the client never authenticates the server

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 4 — any other unprivileged local account |
| **Location** | `apps/desktop/src-tauri/win-live/src/pipe.rs:167` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** FILE_FLAG_FIRST_PIPE_INSTANCE (pipe.rs:132) genuinely prevents a squatter from creating a SECOND instance while the server holds one — I verified that is the correct semantics and it defeats the concurrent-squat attack. But run_server closes the only instance at the end of every connection (quoted lines) and re-creates it at the top of the loop, so between turns NO instance of the trusted name exists. During that window (and before first start) any local process can take the name; the legitimate server's next CreateNamedPipeW then fails and pipe.rs:140-143 merely `eprintln!` + `continue`, spinning in an unthrottled busy loop forever rather than alerting or exiting. Separately, the client never verifies the server: open_client (pipe.rs:179-206) calls CreateFileW and does no GetNamedPipeServerProcessId / server-SID check.

**Code.**
```
let _ = FlushFileBuffers(h);
            let _ = DisconnectNamedPipe(h);
            let _ = CloseHandle(h);
        }
    }
}
```

**Walkthrough.**

1. Turn N completes; pipe.rs:169 `CloseHandle(h)` destroys the last instance. 2. Before the loop re-enters CreateNamedPipeW (pipe.rs:130), an attacker's CreateNamedPipeW on `brops-live-supervisor` succeeds. 3. The real server's create now fails with ERROR_ACCESS_DENIED; pipe.rs:141 prints and pipe.rs:142 `continue`s — forever, at full CPU, never recovering. 4. Turn N+1: the broker's open_client (pipe.rs:179-206) connects to the ATTACKER's instance with no server-identity check and sends the full request — the run/task/workspace/install ids, the three prompt digests, the output handle, and at the signer hop the complete sign_request including the supervisor's attestation and signature. 5. REFUTATION (why this is not a forgery): the attacker holds no private key. A forged challenge dies at servers.rs:517 (`signature_invalid`); a forged attestation dies at servers.rs:963 against the pinned attest pubkey; a forged envelope dies in verify_and_accept under the manifest-resolved receipt key (resolver.rs:267-279). And the client's SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION (pipe.rs:196) blocks the token-relay escalation that would let the squatter act AS the broker. So the impact is permanent hijack of the transport position, DoS, and request/evidence disclosure — not a minted trusted_verified.

**Why it matters.** The module header (pipe.rs:10-15) claims FILE_FLAG_FIRST_PIPE_INSTANCE means 'a rogue that squatted the trusted pipe name makes our create fail-closed rather than coexist' — true for coexistence, but the fail-closed branch is an infinite silent retry, and the reconnect gap re-opens the squat the flag was added to close. Reported at P2 and explicitly NOT as a forgery, because the crypto boundary defeated every escalation I tried.

**Adversarial review (P3).** Verified, including the finding's own refutation. The reconnect gap is real: pipe.rs:167-169 (quote verbatim) flushes, disconnects and CloseHandles the ONLY instance at the end of every connection, and the loop re-creates it at pipe.rs:130 — between those two points no instance of the trusted name exists, and before first start none exists at all. The fail-closed branch is genuinely an unthrottled silent spin: pipe.rs:140-143 is `if h.is_invalid() { eprintln!(...); continue; }` with no backoff, no exit and no operator signal, which contradicts the module header's framing at pipe.rs:10-15. The client does not authenticate the server: open_client (pipe.rs:179-206) is a bare CreateFileW with no GetNamedPipeServerProcessId or server-SID check. I re-walked the escalation myself and it dies exactly where the finding says: a forged challenge fails at servers.rs:517, a forged attestation at servers.rs:963 against the config-pinned attest pubkey, a forged envelope under the manifest-resolved key (resolver.rs:267-280), and SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION (pipe.rs:196) blocks the token-relay. So: DoS, permanent transport hijack and disclosure of ids/digests, never a minted trusted_verified. DOWNGRADED P2→P3 for the same lab-kit reason as W-05 — these are the proof-kit bins, not a shipped path, and the finding is already explicit that it is not a forgery.

**Reviewer re-read.** `win-live/src/pipe.rs:10-15 (the claim), :124-143 (FILE_FLAG_FIRST_PIPE_INSTANCE + the silent `continue`), :167-169 (quote verified verbatim), :179-206 (no server authentication), :189-196; win-live/src/servers.rs:517, :963; win-live/src/resolver.rs:267-280`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `apps/desktop/src-tauri/win-live/src/pipe.rs:167` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---


### `R-45` · The Windows live kit has zero CI coverage — no job builds it, tests it, or runs any of its proofs, and the cross-account proof has no reproducible artifact

| | |
|---|---|
| **Severity** | P3 |
| **Adversary needed** | 1 — none; this is an assurance gap, not an exploit |
| **Location** | `.github/workflows/ci.yml:130` |
| **Group** | `windows-twin` |
| **Implementer check** | NOT YET VERIFIED |

**Defect.** The only Windows CI job runs exactly the two commands above — brops-core's windows_broker predicates and brops-win-broker's peer-auth syscall test. `cargo test -p brops-win-live` appears in NO workflow: grep for 'cargo test' across .github/workflows returns four lines total (ci.yml:49 brops-core, :117 brops, :133, :135), and grep for 'win-live', 'win_live', 'brops-win-live', 'win_live_proof', 'CROSS_ACCOUNT' across all workflow files returns nothing. So proof.rs's five host-independent chain tests — the ones lib.rs:6-9 advertises as 'proven by an in-process integration test that runs on the Linux CI runner too' — are run by no gate, and neither is win_live_proof.ps1. Meanwhile the Linux leg's run_live_turn.sh runs on every CI event (ci.yml:98-99). Separately, CROSS_ACCOUNT_PROOF.md asserts a cross-account trusted_verified result but the tree contains no script, transcript, log or artifact for it — win_live_proof.ps1 is explicitly same-account (its header line 1 and line 46 `$mySid = ([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value)`), and win-broker/proof/isolation_proof.ps1 proves only the peer-SID gate on a throwaway pipe, not a governed turn.

**Code.**
```
- name: Pure §0.W predicates on Windows
        run: cargo test -p brops-core windows_broker --manifest-path apps/desktop/src-tauri/Cargo.toml
      - name: Real named-pipe peer-SID authentication on Windows
        run: cargo test -p brops-win-broker --manifest-path apps/desktop/src-tauri/Cargo.toml
```

**Walkthrough.**

1. ci.yml:120-135 is the entire `windows-broker` job; the quoted two steps are its only run commands, and the comment at :130-132 states it 'does NOT flip platform_governed_execution_supported()'. 2. grep 'cargo test' over .github/workflows -> ci.yml:49, :117, :133, :135 only; none names brops-win-live. 3. grep 'win-live|win_live|brops-win-live|win_live_proof|CROSS_ACCOUNT' over .github/workflows -> no matches. 4. win-live/proof/win_live_proof.ps1:46-48 runs both cases as the current interactive user — same-account by construction. 5. CROSS_ACCOUNT_PROOF.md:26-28 and :55-57 present the RESULT lines as prose with no accompanying script or captured output. So the entire F-01 Windows-twin remediation in servers.rs — the exact_keys shape checks, the state machine, the challenge CAS, the write-once completion — is regression-guarded by nothing.

**Why it matters.** The ledger row for F-01 cites CI evidence (run 31078055077, the live-governed-turn job) as proof the fix holds. That evidence is entirely Linux. On the platform the Owner runs, the twin's guards can be silently removed by any future edit and every gate stays green. And the strongest Windows claim in the tree — the cross-account trusted_verified — is a .md assertion with no reproducible artifact, which is precisely the class of evidence the brief instructs me to refuse.

**Adversarial review (P3).** Confirmed, and the gap is wider than the finding states. My own grep over .github/workflows returns exactly four cargo test/check lines — ci.yml:49 (-p brops-core), :115 (cargo check), :117 (-p brops), :133 (-p brops-core windows_broker), :135 (-p brops-win-broker) — and zero matches for win-live|win_live|brops-win-live|CROSS_ACCOUNT. The quoted two steps are verbatim the entire run-command set of the `windows-broker` job (ci.yml:120-135), whose own comment at :127-132 states it does NOT flip platform_governed_execution_supported(). The extra fact the finding missed: Cargo.toml:47 puts brops-win-live under `[target.'cfg(windows)'.dependencies]`, so ci.yml:115's `cargo check` on ubuntu-latest does not even COMPILE the crate, and no -p selector on the windows job pulls it in either. So proof.rs's five in-process chain tests (proof.rs:342-409) — which lib.rs advertises as running on the Linux runner — are executed by no gate, and neither is win_live_proof.ps1; the whole F-01 remediation in servers.rs is regression-guarded by nothing on any runner. The cross-account claim likewise has no artifact: proof/ contains only win_live_proof.ps1, whose header line 1 says 'self-contained, same-account' and whose line 46 derives the SID from the current interactive identity, while CROSS_ACCOUNT_PROOF.md:24-32 and :50-58 present the RESULT lines as prose with no script or captured output. P3 as filed: this is an assurance gap, not an exploit.

**Reviewer re-read.** `.github/workflows/ci.yml:120-135 (whole windows-broker job; quote verified at :129-135), :115, :117, :49; apps/desktop/src-tauri/Cargo.toml:47 (`[target.'cfg(windows)'.dependencies]`); win-live/src/proof.rs:342-409 (the ungated tests); win-live/proof/win_live_proof.ps1:1, :46-48; win-live/proof/CROSS_ACCOUNT_PROOF.md:24-32, :50-58; apps/desktop/AUDIT/AUDIT_LEDGER.md:23 (F-01 cites Linux CI run 31078055077)`

> #### Implementer gate — fill this in BEFORE changing any code
> - [ ] I opened `.github/workflows/ci.yml:130` and confirmed the quoted code is really there
> - [ ] I walked the walkthrough step by step against the real code
> - [ ] I confirmed the stated adversary is genuinely in scope and sufficient
>
> **Decision:** [ ] AGREE - fixing &nbsp;&nbsp; [ ] DISAGREE - the line that refutes it: `____________`
>
> *If you disagree you must name the file and line that makes the walkthrough fail. "This looks wrong" is not accepted.*

---

## 4. The §3 narrowings

The brief disclosed eight places where the implementer knowingly stopped short and asked whether each is
*acceptable* for a gate flip. **6 of 8 were judged unacceptable.**

### Judged UNACCEPTABLE for a gate flip


#### §3.1 ACLs not read

The narrowing itself is honestly stated and is genuinely fail-permissive in only one direction (tcb_probe.rs:92-95). The problem is the compensation, which I was asked to verify and which does not hold up. `setfacl -Rb /opt "$LIVE"` (run_live_turn.sh:230) covers the /opt subtree ONLY. It does NOT cover every ancestor of every pinned artifact: `governed-execution-allowlist.source` is /etc/sudoers.d/brops-live-recorder (build_tcb_pin_manifest.py:91), and its ancestors /etc/sudoers.d, /etc and / are never stripped; `/` is never stripped for any artifact. It is also silently optional — the whole thing sits inside `if command -v setfacl` with no else and with `2>/dev/null || true`, so on a host without the acl package the compensation does not run and the floor still prints `verified`. I did check the ordering and it is correct: the strip at :230 precedes the check at :244, and the chmod-before-setfacl sequence can only make group bits MORE permissive after the fact, which the subsequent check would catch — fail-closed, not fail-open. I also confirmed that no in-scope adversary can CREATE a permissive ACL on a root-owned file (that needs owner or CAP_FOWNER), so the residual risk is inherited-image ACLs only. Verdict: NOT acceptable as written, because the disclosure credits a compensation that is partial and optional. It becomes acceptable with two mechanical fixes: make setfacl mandatory (fail the run if it is missing or errors), and extend the strip to the ancestor set of every pinned path rather than a hard-coded /opt.

**Evidence.** `engine/ci/live/run_live_turn.sh:198-200,229-231,235,244; engine/ci/live/build_tcb_pin_manifest.py:91; apps/desktop/src-tauri/broker/src/tcb_probe.rs:89-98; apps/desktop/src-tauri/core/src/tcb_integrity.rs:287-308,316-328`

---

#### §3.3 .unit roles pin run_live_turn.sh

MISLEADING, not merely narrow — and the disclosure lives in the wrong place. The reasoning offered (build_tcb_pin_manifest.py:20-22, 'Writing plausible-looking unit files for units that do not exist would make the manifest describe a deployment that isn't this one') is a good principle applied to the wrong conclusion. What actually gets pinned is $TCB/brops-live.unit, a root-owned COPY of run_live_turn.sh installed at run_live_turn.sh:208 — and that copy is executed by nothing, read by nothing, and referenced by nothing after the digest is taken. The file that really orchestrates the deployment is $SCRIPT_DIR/run_live_turn.sh in the checked-out repo, which is login-writable and is NOT pinned. So under the two logical names a reader understands as 'the service definition that determines how each trusted service is started — its user, environment and privileges', the manifest records an inert artefact with no causal role at run time, and records it twice. A `.unit` role has a specific security meaning (it is where User=, Environment= and capability bounds live); mapping it to an orchestrator snapshot silently converts a control over how services are launched into a control over nothing. The disclosure is a Python docstring; the manifest JSON that the verifier consumes and that an auditor sees behind `RESULT: tcb_integrity_floor verified artifacts=pinned` carries only the bare logical_name. Honest fix without inventing anything: either omit the roles and let the coverage floor refuse (which is the fail-closed behaviour the floor is for), or rename the roles to what they are. Padding a required name with an inert file to make a coverage floor pass is the same move the floor exists to prevent.

**Evidence.** `engine/ci/live/build_tcb_pin_manifest.py:19-22,94-95; engine/ci/live/run_live_turn.sh:208,210; apps/desktop/src-tauri/core/src/tcb_integrity.rs:199-201,223-228`

---

#### §3.4 seven .config roles share one config.json

The sharing itself is defensible; what it reveals is not. Exact counts from build_tcb_pin_manifest.py:64-96: SIX roles map to $LIVE/config.json (supervisor.config, evidence-recorder-runner.config, isolated-signer.config, trusted-verifier-broker.config, desktop-challenge-authority.config, trusted-verifier-broker.pinned-manifest-config), TWO map to $TCB/executor.lease, TWO map to $TCB/brops-live.unit. So the 21 required roles resolve to 14 distinct files. Pinning one file six times gives exactly one file's worth of assurance — six byte-identical comparisons of the same inode. That is not itself dishonest: those six components genuinely do load that one config, and pinning it once per consumer is a faithful description. The disqualifying part is the asymmetry it exposes. The coverage floor's stated purpose (tcb_integrity.rs:219-222, 'an artifact that is not listed is never integrity-checked') is satisfied by NAME. So the floor reports full §2.5 coverage while, in this same deployment, files that unambiguously steer the TCB are outside the set: $TCB/supervisor.ipc-policy.json and $TCB/isolated-signer.ipc-policy.json (the peer-auth rules for the two processes holding supervisor_attest.priv and signer.priv — run_supervisor.py:58-59, run_signer.py:74-75), engine/runtime/governed_supervisor.py (45,286 bytes) and governed_supervisor_server.py (34,297 bytes) which are the supervisor's actual logic, plus supervisor_ledger.sql, live_crypto.py and ipc_policy.py. Meanwhile one artifact that IS pinned is read by no code at all (§3.4's sibling problem, F-10-C). A coverage floor that counts 21 names, delivers 14 files, includes an inert one and excludes 80 KB of the code it is supposed to be measuring should not be reported as 'the full TCB_REQUIRED_ARTIFACTS set' when flipping a gate. Mitigating fact I verified and will not hide: none of the unmeasured files is writable by any in-scope adversary (run_live_turn.sh:209,218 leave them root-owned 0644 under 0755 root-owned dirs), and ipc_policy.py:39-44 independently enforces root ownership on the two unpinned policies at load. So this is an assurance gap, not a live hole.

**Evidence.** `engine/ci/live/build_tcb_pin_manifest.py:64-96; apps/desktop/src-tauri/core/src/tcb_integrity.rs:174-202,219-228; engine/ci/live/run_supervisor.py:58-59; engine/ci/live/run_signer.py:74-75; engine/ci/live/run_authority.py:42-43; engine/ci/live/provision_keys.py:305-316; engine/ci/live/run_live_turn.sh:76-84,209,218`

---

#### §3.7 head-floor default beside the evidence store (the default lives at <store>/head-floor, so whoever can write the store can clear the mark)

The narrowing understates its own consequence in three ways I verified, and the residual it admits is not survivable for a control whose entire purpose is durability across calls.

(1) It says 'whoever can write the store can clear the mark'. The truth is stronger: whoever can NAME the store also names the mark. _head_floor_dir defaults to store/'head-floor' (bro_completion.py:245) and the store is itself resolved from the builder-controlled BRO_EVIDENCE_STORE (:208, :168-180). The anti-rollback record and the artifact it polices share one namespace, one principal and one env var, so a single capability — the very one the original F-13/F-14 attack already presumed (placing a retained head into the store) — defeats both. I measured _load_head_floor returning 0 for any other store directory.

(2) Clearing is not even necessary. BRO_EVIDENCE_HEAD_FLOOR (:243-244) relocates the mark from the ambient environment with no CI gate, no ownership check and no mode check, and it overrides an explicitly supplied store — so the durable runtime, documented at :488-493 as keyed off supplied keys and store 'rather than the builder's environment', has its anti-rollback record redirected by the builder's environment regardless. I ran it end-to-end with genuine signatures: a rolled-back head was ACCEPTED.

(3) Deleting the DIRECTORY (not just truncating a file) reads as 'no floor yet' and passes. _load_head_floor's 'not path.exists() -> return 0' (:255-256) makes deletion indistinguishable from a first run, and 0 is converted to None at :222, switching the comparison at bro_evidence.py:112 off entirely. The shipped test only truncates (test_evidence_chain.py:341-349), so the claimed 'a damaged mark refuses rather than reading as absent' is proven for the one variant that does not matter and false for the one that does. rmtree is not a stronger capability than truncate.

The narrowing also offers a remedy that cannot be configured. Putting the marks 'under a principal the builder cannot write' contradicts the design: the mark is advanced in-process by the policed Stop gate (bro_completion.py:226), so an unwritable directory makes the write at :278 raise PermissionError -> CompletionError (:284-286) and turns the FIRST honest completion RED. There is no ownership assignment that both permits operation and denies rollback. The desktop side shows the correct shape — a signer-owned CAS under BEGIN IMMEDIATE (apps/desktop/src-tauri/core/src/supervisor_ledger.rs:798-891) — which is exactly the primitive the engine path lacks.

Finally, the residual is stated in one place no operator will ever see: a source-code docstring. BRO_EVIDENCE_HEAD_FLOOR appears in no runbook (OPERATOR_RUNBOOK.md documents BRO_EVIDENCE_STORE and says nothing about ownership or the head floor), in no PROJECT_STATE/NEXT_CHAT text, and not in bro_deploy_preflight.py's LEDGER_VARS (:47-55) — the deployment gate does not know the variable exists. A deployment following the shipped documentation always runs the defeated default.

Accepting this narrowing would mean flipping platform_governed_execution_supported() on the strength of a control that (a) is disabled by removing one directory, (b) is disabled by one unvalidated env var, (c) has no configuration in which it is sound, and (d) is undocumented outside the code. Honest alternative: keep the row OPEN, and either move the mark into the supervisor/signer CAS that already exists on the desktop side, or state plainly that the engine Stop gate has no enforced L-4 anti-rollback and stop asserting the property at bro_completion.py:202-205 and bro_evidence.py:24-29.

**Evidence.** `engine/runtime/bro_completion.py:208, :218-222, :226-227, :233-245, :248-266 (esp. :255-256), :269-286 (esp. :278), :168-180, :488-493; engine/runtime/bro_evidence.py:112-116; engine/tests/test_evidence_chain.py:341-349; engine/tools/bro_deploy_preflight.py:47-55; engine/docs/OPERATOR_RUNBOOK.md:26-48; apps/desktop/src-tauri/core/src/supervisor_ledger.rs:798-891 (the correct primitive, for contrast). Executed evidence: '[baseline] older head refused' / '[rmtree] rolled-back head ACCEPTED, digest 885c905f38b41ff0' / '[env redirect] rolled-back head ACCEPTED, digest 885c905f38b41ff0' / '[toctou] chain verified against head 9, recorded floor = 1', all against the snapshot's own signed fixture.`

---

#### §3.6 run_live_turn.sh chmods /opt to 0755

NOT acceptable, on three grounds, though it is not an exploit in the environment it actually runs in.
(1) ORDERING. The hardening is at run_live_turn.sh:223-224, but the entire deployment is built at :69-222 — `rm -rf /opt/brops-live` and mkdir (:69-70), staging the whole Python TCB (:76-84), installing the setuid launcher and executor image (:88-96), provisioning keys/manifest/anchor/config (:103-153), setting the new custody modes (:176-195), writing the sudoers allowlist (:198-200) and BUILDING the §2.5 pin manifest (:210). All of that ran with /opt in whatever state the image handed down — on the hosted runner, drwxrwxrwx with NO sticky bit, which the script's own comment at :219-222 correctly describes as "anyone who can write /opt can rename /opt/brops-live aside and substitute an entire tree, which defeats every content pin below it". The floor is then evaluated at :244, after the condition has been made false. A floor whose purpose is to detect an unsafe deployment root is therefore structurally incapable of ever reporting the one condition that actually obtained during provisioning. The correct shape is: harden or REFUSE first, provision second. I did chase the substitution to a forgery and it dies on the anchor's `st_uid != 0` check (live_turn.rs:88-90) — an attacker who substitutes the tree still cannot produce a root-owned root-anchor.json saying `external` — so this is an evidence-quality defect, not a live break.
(2) SCOPE OF THE MUTATION. It is not only a chmod. :229-231 runs `setfacl -Rb /opt "$LIVE"`, a RECURSIVE removal of all extended ACLs from the whole of /opt — on a hosted runner that includes /opt/hostedtoolcache and every other product installed there — with failures swallowed by `2>/dev/null || true`. The chmod is announced (:223 prints the prior mode), so "silently" is too strong for it; the recursive ACL wipe is not announced. Nothing is reverted: the trap at :248-251 only kills service PIDs and removes the sudoers file, so a proof kit permanently alters system state outside its own deployment root.
(3) WHAT IT IMPLIES ABOUT THE ENVIRONMENT. It confirms the proof ran on a box whose /opt was world-writable for the entire provisioning phase. On the GitHub runner no privilege boundary is crossed there, because the only non-root principal is the runner user who holds passwordless sudo (ci.yml:98) — I am NOT claiming an exploit on CI. But it means the live proof was produced in an environment that failed the kit's own §2.5 precondition, and the kit's response was to repair the environment rather than record that it had failed. For an Owner judging whether the live proof is trustworthy evidence, "the deployment root was unsafe while we built the TCB, and we hardened it just before measuring" is exactly the fact that must be surfaced.

**Evidence.** `engine/ci/live/run_live_turn.sh:69-70, :76-84, :88-96, :103-153, :176-195, :198-200, :208-211, :217, :219-224, :229-231, :234-235, :244, :248-251; .github/workflows/ci.yml:98; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:88-90`

---

#### §3.8 production_verified gated on provenance == "external"

Split verdict, and the split is the point.
AS A NARROWING OF TODAY'S CLAIM: acceptable, and an improvement. The kit-generated default now reports `production_verified=false root_anchor=kit_generated` (provision_keys.py:251 -> live_turn.rs:443-444 -> run_live_turn.sh:287-290), CI never passes the external flags (ci.yml:98), and live_turn.rs:260-264 refuses a config still carrying an inline anchor so the old arrangement cannot be re-expressed by editing config. The previously false GREEN line is gone from the automated evidence. Credit where due.
AS A BASIS FOR FLIPPING THE GATE: not acceptable, because the flip would rest on a future run whose "external" is self-asserted. `provenance` is not a custody statement; it is a label selected by the presence of four CLI flags at provision_keys.py:184-189 and written literally at :245. Nothing verifies where the private half lives. The script does not even compare the supplied public key against the root keypair it generates anyway at :220 and writes to keys/root.priv at :228; it does not verify the signature it copies verbatim (:239-242); there is no ceremony record, no offline attestation, no second party. The repository's own test settles it: engine/tests/test_live_provisioning_anchor.py:71-93 generates the "external" root with lc.gen_private() inside the test process, signs on the same machine, and asserts provenance == "external". And the code that writes the field is staged out of the repo working tree at run_live_turn.sh:76/:85/:103, i.e. authored by the weakest in-scope adversaries (finding F-17-A). Downstream, the only check on the anchor file is owner+mode (live_turn.rs:77-95) — no signature covers its contents, and build_tcb_pin_manifest.py:92 pins a digest computed from the file just written, so the pin certifies whatever was provisioned rather than constraining it.
WHAT WOULD MAKE IT ACCEPTABLE: the mechanism already exists in this repo on the other platform. win-live/src/tcb.rs:28-29 compiles ROOT_PUBLIC_KEY_HEX into the binary and win_live_turn.rs:99-106 pins from that constant, refusing a config that disagrees. That is what key_manifest.rs:84-85's "binary-pinned root ... never taken from the manifest itself" actually asserts, and the Linux driver still does not do it — live_turn.rs:281-288 builds PinnedRoot from a file. A gate flip should require the anchor to be bound to something the provisioning run cannot choose, not labelled by it.

**Evidence.** `engine/ci/live/provision_keys.py:184-193,220,228,236-251,262-273; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:73-95,260-291,443-458; engine/ci/live/run_live_turn.sh:76,85,103,153,278-294; engine/tests/test_live_provisioning_anchor.py:42-96; engine/ci/live/build_tcb_pin_manifest.py:92,99-110; apps/desktop/src-tauri/win-live/src/tcb.rs:22-34; apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:97-106; apps/desktop/src-tauri/core/src/key_manifest.rs:84-87; .github/workflows/ci.yml:91-98`

---

### Judged acceptable


#### §3.2 ownership as write authority

Confirmed strictly additive; I attacked it for a reverse bypass and found none. tcb_probe.rs:97-98 computes `writable_by_login_or_runtime = world_or_group_writable || login_and_runtime_uids.contains(owner_uid)`. The world/group bit is ALSO reported independently as `is_world_or_group_writable` at :101, and tcb_integrity.rs:268 refuses on EITHER flag — so folding ownership into the second flag cannot mask the first. I looked specifically for a branch anywhere that treats `writable_by_login_or_runtime == false` as licence to skip a further check; there is none (the flag is read at exactly two places, tcb_integrity.rs:268 and :302, both pure refusals). I also confirmed the reasoning is sound rather than merely conservative: an owner can always chmod itself write access, so ownership by an untrusted principal really is write authority. One observation that does not change the verdict: because verify_artifact:258 independently requires `facts.owner_uid == expected_uid` and the manifest's owner_uids map only to 0 (build_tcb_pin_manifest.py:112), any artifact that survives the owner check is root-owned, at which point the ownership term in the writability flag is always false and the flag degenerates to the mode-bit test. So §3.2 adds a redundant refusal rather than a new one — harmless, and it becomes load-bearing only in a deployment with a separate non-root brops-admin.

**Evidence.** `apps/desktop/src-tauri/broker/src/tcb_probe.rs:89-104; apps/desktop/src-tauri/core/src/tcb_integrity.rs:256-273,292-307; engine/ci/live/build_tcb_pin_manifest.py:107-112`

---

#### §3.5 deployment-time not per-turn measurement

I attacked the stated reasoning and it survived; the residual risk is genuinely bounded to root, which is out of scope. VERIFIED THE JUSTIFICATION IS REAL, NOT A RATIONALISATION: the launcher really is mode 4750 root:brops-recorder (run_live_turn.sh:88-90) and the allowlist really is 0440 inside root-only /etc/sudoers.d (run_live_turn.sh:198-200), so a serving principal that could digest them could also read them. I proved the consequence rather than accepting it: as uid 5001 the broker's own call site at main.rs:281 must fail, because tcb_probe.rs:54-57 open()s the sudoers path with no search bit on the 0750 parent -> EACCES -> None -> TcbViolation::Missing -> fail_closed(). So per-turn broker measurement is not merely undesirable here, it is impossible without loosening containment. THE WINDOW: I walked run_live_turn.sh:244 (root check) to :271 (turn) line by line. Nothing between them rewrites a pinned file — :247-252 set traps, :255-261 spawn servers, :264-267 poll for sockets. I then asked who could write each of the 14 distinct pinned paths during that window and checked each mode individually: all root-owned, ancestors root-owned 0755 (:88-96, 141, 153, 200, 208-218, 224). Broker uid 5001, the login uid and any other unprivileged account are all excluded. There is no re-check, no watch and no periodic re-verify anywhere — I grepped for inotify/fanotify/re-verify across broker/src and engine/ci/live and found nothing — but the window is only exploitable by root. VERDICT: acceptable, with one condition that belongs in the disclosure rather than in this verdict — the floor must not be described as running 'before serving a governed turn' (AUDIT_LEDGER.md:29). It runs once, as root, in a process that exits (live_turn.rs:35-36) before the serving process is even started. And note the interaction with F-10-A: because the manifest is generated from the same bytes moments earlier, the deployment-time measurement carries no content-integrity information either, so what §3.5 defers is a check that in this kit had nothing to detect.

**Evidence.** `engine/ci/live/run_live_turn.sh:88-96,141,153,198-200,208-218,224,244,247-271; apps/desktop/src-tauri/proof/src/bin/live_turn.rs:35-37,163-171,201-215; apps/desktop/src-tauri/broker/src/main.rs:178,181,259-289; apps/desktop/src-tauri/broker/src/tcb_probe.rs:53-66,70-82`

---

## 5. What the auditor ran and verified personally

This section is not agent output. These are commands the auditor executed and code the auditor read
directly, recorded separately so the Owner can weigh them independently of the multi-agent findings.

### 5.1 The DDL parity claim — CONFIRMED TRUE

The ledger claims the shared supervisor DDL is CI-gated byte-identical between the Python engine and the
Rust mirror. Verified:

```
sha256 engine/runtime/supervisor_ledger.sql                      = 772a8da43f4a9e19d0f6ffbf293571f814423918fb4569a21731ddaa423b4c48
sha256 apps/desktop/src-tauri/core/schema/supervisor_ledger.sql  = 772a8da43f4a9e19d0f6ffbf293571f814423918fb4569a21731ddaa423b4c48
cmp -s  -> identical
```

The gate is genuinely wired: `.github/workflows/ci.yml:262` runs `python tools/check_ledger_ddl_parity.py`
and `:265` runs the gate's own self-test. This claim is honest.

### 5.2 The F-01 end-to-end test suite — CONFIRMED IT RUNS AND PASSES

`engine/tests/test_governed_chain_e2e.py` exists (30 KB), carries no skip condition, and executes. All 12
of its cases pass, including the ones that matter most to the F-01 claim:

```
test_the_old_facts_door_no_longer_exists                     ok
test_a_fabricated_run_cannot_be_attested_or_signed           ok
test_the_caller_cannot_name_the_terminal_handles             ok
test_a_replayed_challenge_yields_one_attempt_and_one_receipt ok
test_a_stale_evidence_head_refuses_the_completion            ok
test_a_second_execution_cannot_rewrite_what_was_attested     ok
test_a_tampered_output_blob_breaks_the_signed_binding        ok
test_challenge_accepted_at_is_the_supervisors_accept_clock   ok
```

These tests are real and they assert real properties. **They do not, however, test the property the P0
turns on** — that the reported `output_handle` corresponds to bytes an executor actually produced. A test
named `test_the_caller_cannot_name_the_terminal_handles` passes while the caller still names
`output_handle`, because `output_handle` is deliberately excluded from the "terminal handles" the test
covers. That is a coverage boundary, not a broken test.

### 5.3 Test suite results

| Suite | Result |
|---|---|
| `engine/` (`BRO_ENV=ci python -m unittest discover -s tests`) | **909 ran, 0 failures, 4 errors, 45 skipped** |
| `cargo test -p brops-core` | **16 passed, 0 failed** |

**The 4 errors are the auditor's own artifact, not a repository defect.** All four are in
`test_bro_policy.ReceiptFreshnessTests` and fail with
`subprocess.CalledProcessError: ['git','ls-files','-z'] returned 128` because the audit snapshot was
exported with `git archive` and therefore has no `.git` directory. They are excluded from every count in
this report.

### 5.4 The 45 skipped tests — a real assurance gap, on the Owner's platform

This is the auditor's own finding and is not covered by any §2 blocker row.

**F-06's own regression tests do not run on Windows. All four are skipped:**

```
test_group_or_world_writable_pin_file_is_denied              skipped: POSIX permission bits
test_symlink_pin_file_is_denied                              skipped: symlink creation not permitted
test_repo_controlled_parent_symlink_pin_file_is_denied       skipped: symlink creation not permitted
test_intermediate_symlink_component_outside_repo_is_denied   skipped: symlink creation not permitted
```

The brief asks directly: *"Does the Windows SID comparison actually work, or does it silently never
match?"* No test in the repository answers that question. The Windows branch of the F-06 remediation is
unexercised on the platform the Owner runs.

**F-07/F-28's custody tests do not run on Windows either:**

```
test_store_refuses_a_world_accessible_dir                    skipped: 'POSIX file-mode custody; ACLs enforce this on Windows'
test_store_allows_a_group_shared_but_not_world_dir           skipped: POSIX file-mode custody
test_attestation_keydir_refuses_group_or_other_access        skipped: POSIX file-mode custody
test_receipt_signer_keydir_refuses_group_or_other_access     skipped: POSIX file-mode custody
```

Note the wording of the skip reason itself: *"ACLs enforce this on Windows."* That is an assertion, not a
test. Nothing verifies it.

**The signer process boundary — the core isolation property — is untested here:**

```
test_same_user_cannot_connect_to_signer_channel              skipped: AF_UNIX unavailable on this platform
test_signer_service_denies_a_disallowed_peer_uid             skipped: AF_UNIX unavailable on this platform
```

and, stated explicitly by the suite itself:

> *"Dedicated-OS-principal socket/pipe ACL denying the same-login-user peer is Linux-first deployment
> (design §1.1); exercised on Linux in CI, not on this host."*

`test_live_tcb_pin_manifest` — F-10's own test — is also skipped on this host.

**22 enforcement-path tests are dead on every platform, including CI:**

```
22 tests skipped: 'requires engine/ to be its own git worktree root; deferred in the OS monorepo'
   14 in test_hooks_subprocess
    8 in test_full_execution_transaction_e2e
```

This is the Option-C skip guard. The guard is
`_ENGINE_IS_GIT_ROOT = (pathlib.Path(__file__).resolve().parents[1] / ".git").exists()` — `parents[1]` is
`engine/`, and in this monorepo `.git` lives at the repository root, so the condition is permanently
false. These 22 tests of the enforcement path do not execute anywhere: not on Windows, not on Linux, not
in CI. Nothing would fail if the guard silently stopped re-enabling them, because no test covers the
guard.

### 5.5 Independent confirmation of the P0

The auditor read the cited code directly rather than accepting the agent's account.

`engine/runtime/governed_supervisor_ledger.py:556` states the design in its own comment:

```python
#: The only §4.9 evidence values the supervisor cannot derive itself, so the
#: executing chain reports them - ONCE, for an attempt the supervisor already authorized.
COMPLETION_HANDLE_FIELDS: Tuple[str, ...] = (
    "output_handle",
    "containment_evidence_handle",
)
```

`engine/runtime/governed_supervisor.py:848` copies that value straight into the signed evidence:

```python
# ---- from the write-once completion row ----
"output_handle": state.output_handle,
"containment_evidence_handle": state.containment_evidence_handle,
```

`engine/runtime/governed_supervisor_ledger.py:490` records the execution with no probe of any kind — the
process metadata is whatever the caller says it is:

```python
def mark_executing(conn, execution_attempt_id, *, process_group_id, cgroup_id,
                   execution_started_marker, now_ms) -> str:
    """EXECUTION_STARTING -> EXECUTING - the child is confirmed running AND its process
    metadata is durably persisted"""
    return _guarded(conn, execution_attempt_id, EXECUTING, now_ms, ...)
```

The docstring says *"the child is confirmed running."* Nothing confirms it. `_guarded` is a state-guarded
SQL `UPDATE`.

Meanwhile `build_run_attestation`'s docstring still reads *"Build the §4.9 evidence from the supervisor's
OWN terminal run state."* That is true in the narrow sense — and misleading, because the terminal run
state was itself populated from the wire by the party the split-uid architecture exists to constrain.

**The remediation is real work.** The `facts` parameter is genuinely gone; the old protocol is genuinely
rejected with a hard error; a fabricated run genuinely returns `no_terminal_run_state`; the ledger is
genuinely 0700 and supervisor-owned. What did not change is that the supervisor still never observes the
execution it attests, and the one value that decides what the user sees still arrives from the broker.


## 6. Findings that were killed

Reported here so no one re-litigates them. The adversarial review refuted each one.

- **[f10-tcb] The ACL compensation for the §3.1 narrowing is best-effort and does not cover every ancestor: setfacl is skipped silently when absent, and /, /etc and /etc/sudoers.d are never stripped** (claimed P3)
  - DIES on its central technical premise, and separately on the adversary rule. The finding's defect claim is: 'a root-owned 0644 file carrying u:someuser:rw in a POSIX ACL passes the floor while being writable by that user.' That is FALSE on Linux POSIX ACLs, which is the platform this kit runs on. Under acl(5), an ACL containing any named-user or named-group entry MUST contain an ACL_MASK entry, and when a mask is present the file mode's GROUP permission bits ARE the mask. So an ACL entry that is EFFECTIVELY write requires mask>=w, which sets the group-write bit in st_mode. tcb_probe.rs:89 computes `is_world_or_group_writable = (mode & 0o022) != 0` — 0o020 is exactly that bit — and verify_artifact refuses at tcb_integrity.rs:268-273 (WritableByUntrusted) or :302-306 (AncestorWritable). The only way to have a named-user write entry that does NOT show in the group bits is to hold the mask down below w, in which case the entry is masked and confers no write. Therefore the documented narrowing at tcb_probe.rs:92-95 is far narrower than the finding assumes, and the setfacl line is a cosmetic/noise-reduction step, not the load-bearing compensation: on a host with no `acl` package, or on /etc and /etc/sudoers.d which are never stripped, an effective-write ACL would make the floor REFUSE (fail-closed and loud), not silently pass. The finding's step 6 ('Wrong output: an /etc or /etc/sudoers.d carrying an ACL entry granting write ... passes the floor') is the opposite of what the code does. Note also that a DEFAULT ACL on a directory (the thing run_live_turn.sh:225-228 is actually worried about) does not grant access to that directory at all — it only seeds children — so it cannot produce the claimed write vector on /, /etc or /etc/sudoers.d either. What remains true is only bookkeeping: setfacl is conditional (:229), errors are discarded (:230), and the strip covers /opt and $LIVE but not /, /etc, /etc/sudoers.d. Those are accurate observations with no security consequence. Independently, the finding concedes the precondition can only be created by root or CAP_FOWNER, which the task's own rule makes out of scope. INVALID on both grounds.

## 7. Coverage

What each group actually read, in its own words. Anything not covered is stated.


**`f01-oracle`** — FULLY READ, line by line: engine/runtime/governed_supervisor.py (932 lines), engine/runtime/governed_supervisor_ledger.py (917), engine/runtime/governed_supervisor_server.py (774), engine/runtime/supervisor_ledger.sql (177), apps/desktop/src-tauri/core/schema/supervisor_ledger.sql (177), tools/check_ledger_ddl_parity.py (111), engine/ci/live/run_supervisor.py (full), apps/desktop/AUDIT/AUDIT_LEDGER.md (full), and the F-01/F-02/F-23 sections of apps/desktop/AUDIT/2026-08-06-independent-audit.md.

READ IN THE RELEVANT PARTS (traced, not grepped-and-guessed): apps/desktop/src-tauri/broker/src/chain_executor.rs:1-420 and 620-960 (the whole production Linux hop sequence + LinuxGovernedExecution::execute); engine/runtime/isolated_signer.py:96-205 and 500-690 (the entire sign_result gate chain); engine/runtime/challenge_authority.py:55-243 and 296-420 (create-pending validation, request_sha256 recompute, peer_is_broker); apps/desktop/src-tauri/win-live/src/servers.rs:282-760 (the Rust twin's supervisor); apps/desktop/src-tauri/broker/src/main.rs:110-310 (platform gating + build_governed_executor); apps/desktop/src-tauri/launcher/src/main.rs:390-470 (lease source); engine/ci/live/run_live_turn.sh (provisioning: uids, dir modes, ledger custody); engine/ci/live/provision_keys.py:280-340 (ipc-policy peer allowlists); .github/workflows/ci.yml:1-40 and 230-300 (trigger set + the ledger-ddl job).

EMPIRICAL WORK: I byte-compared the two supervisor_ledger.sql copies (identical, sha256=772a8da43f4a9e19d0f6ffbf293571f814423918fb4569a21731ddaa423b4c48) and I wrote a read-only adversary-broker harness in my scratchpad (C:/Users/Admin/AppData/Local/Temp/claude/c--Users-Admin-Desktop-Bro-Audit/8abeb513-8eb8-4a6f-b315-95053401c38c/scratchpad/attack_f01.py) that imports the SNAPSHOT's governed_supervisor / governed_supervisor_ledger / governed_supervisor_server unmodified and drives the five §5 ops. Nothing in the snapshot or the real repo was written, edited or deleted; the sqlite ledger and store live in a temp dir under my scratchpad. Every "empirically confirmed" claim below is the observed output of that harness against the real code.

NOT COVERED: apps/desktop/src-tauri/core/src/governed_verification.rs was only skimmed via chain_executor's call site (another agent owns F-26/F-29); the Rust core/src/supervisor_ledger.rs body was not read line by line — I only re-ran the previous audit's dead-code check (gate_and_start / lease_launch_gate / record_completion / load_attestation_state still have zero callers anywhere outside that file), which does not affect my verdicts because the Python supervisor is the production writer and win-live carries its own in-process twin.

**`f02-evidence`** — FULLY READ, line by line:
- C:/.../audit-remediation/apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs (394 lines, complete)
- C:/.../audit-remediation/apps/desktop/src-tauri/broker/src/chain_executor.rs (1492 lines, complete — read in two pages, incl. the whole #[cfg(test)] module)
- C:/.../audit-remediation/apps/desktop/src-tauri/win-live/src/execution.rs (187 lines, complete)
- C:/.../audit-remediation/apps/desktop/AUDIT/AUDIT_LEDGER.md (complete)

READ IN FULL FOR THE RELEVANT REGIONS (targeted, not whole-file):
- apps/desktop/AUDIT/2026-08-06-independent-audit.md — the original F-02 (lines 81-130) and F-18 (lines 721-760) findings verbatim (file is 300KB; read the two finding blocks plus their refutation sections)
- apps/desktop/src-tauri/broker/src/main.rs:320-399 (production ExecutionConfig wiring)
- apps/desktop/src-tauri/proof/src/bin/live_turn.rs:350-399 (live-driver ExecutionConfig wiring)
- engine/runtime/governed_supervisor_ledger.py:550-700 (COMPLETION_FIELDS, validate_completion_facts, _evidence_floor_cas, record_completion head) + full grep of every `evidence`/`floor`/`head_sequence` hit in the file
- apps/desktop/src-tauri/core/src/supervisor_ledger.rs — grepped every head_sequence/floor/Idempotent hit incl. evidence_floor_cas_body:840-900 (the Rust twin the Windows kit uses)
- engine/ci/live/run_live_turn.sh:60-100, 160-215 (layout, group/mode provisioning, sudoers, TCB pin build)
- engine/ci/live/provision_keys.py — grepped all `facts`/`evidence`/`EVIDENCE_` hits (lines 64-100, 208-213, 371-407)
- apps/desktop/src-tauri/win-live/src/bin/win_provision.rs:95-215; win-live/src/proof.rs:138-265; win-live/src/bin/win_live_turn.rs:170-249; win-live/src/servers.rs (grepped all four evidence field hits, incl. 700-764 and 1068-1077)
- Whole-snapshot greps for every surviving static/default/fallback of the four values, and for any consumer of the recorder's `events` array.

NOT COVERED (and why): engine/runtime/governed_supervisor.py and engine/runtime/isolated_signer.py were grep-verified for the evidence-field path (ATTEST_INPUT_* sets, evidence_from_state:804-857, build_run_attestation:868-931) but not read line by line — they are not my assigned files and the decisive fact (the four values are stored from the caller's `produced` block and re-emitted) is established in governed_supervisor_ledger.py, which I did read. governed_verification.rs was not read; the F-02 question does not turn on it (it verifies signatures over the four values, it does not question them — a fact the original audit established and I did not re-derive). I did not build or execute anything (read-only snapshot); all conclusions are static reads.

**`f08-bytes`** — FULLY READ, line by line: apps/desktop/src-tauri/launcher/src/main.rs (all 1212 lines, incl. the whole #[cfg(target_os="linux")] mod linux and the test module); engine/ci/live/run_live_turn.sh (all 294 lines); apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs (all 394); apps/desktop/src-tauri/proof/src/bin/proof_executor.rs (all 147); apps/desktop/src-tauri/proof/src/bin/live_turn.rs (all 464); apps/desktop/AUDIT/AUDIT_LEDGER.md (all 70); the F-08/F-09/F-10 sections of apps/desktop/AUDIT/2026-08-06-independent-audit.md.

READ IN THE PARTS THAT CARRY THE DATA FLOW: apps/desktop/src-tauri/broker/src/chain_executor.rs lines 240-440 (run_verified: create-pending facts, final acceptance) and 600-930 (ExecutionConfig + LinuxGovernedExecution::execute: the recorder spawn argv, the store-blob writes, complete-run/attest-run); apps/desktop/src-tauri/core/src/fd_lifecycle.rs verify_launcher_fd_set (lines 71-111 + FdFacts shape); apps/desktop/src-tauri/broker/src/main.rs 255-305 (the TCB floor call site); engine/runtime/isolated_signer.py 120-330 and 620-700 (_derive_hashes, _recompute_request_sha256, ArtifactStore); engine/ci/live/run_signer.py 40-80 (FileArtifactStore); engine/runtime/challenge_authority.py 180-260 (create-pending validation); engine/runtime/governed_supervisor.py 470-660 (challenge validation, accept_open, NewAcceptance handles); engine/ci/live/provision_keys.py 260-430 (store seeding, anchor, config); engine/ci/live/build_tcb_pin_manifest.py (all).

NOT COVERED / LIMITS I ACCEPT: I did not read core/src/supervisor_ledger.rs in full, brops_broker::tcb_probe internals, or the win-live/win-broker Windows twin — none of them touch the fd 3/4/5 -> lease-pin path I own, but I cannot speak to them. I could NOT EXECUTE the exploit: the snapshot is read-only on a Windows host and the kit is Linux-only (launcher run() is #[cfg(target_os="linux")], everything else prints "platform unsupported"). Both findings below are walked statically against real code with file:line at every step; the timing claim in F-08-A rests on inotify IN_ACCESS semantics and on the fact that no re-check exists after the digest, not on a measured race.

PLATFORM/SCOPE NOTE (required by the brief): every control I examined is LINUX-ONLY and LAB-KIT. The launcher's non-Linux run() is main.rs:359-364 (EXIT_PLATFORM_UNSUPPORTED); the shipped desktop still keeps the blocking executor and platform_governed_execution_supported() == false (win-broker/src/lib.rs:10). Nothing here executes on the Owner's Windows box today. The findings are about whether the CLAIMED property holds on the Linux kit that the gate-flip depends on.

**`f09-cas`** — FULLY READ, line by line:
- C:/.../audit-remediation/engine/runtime/governed_supervisor_ledger.py (917 lines, all)
- C:/.../audit-remediation/engine/runtime/governed_supervisor.py (932 lines, all)
- C:/.../audit-remediation/engine/runtime/governed_supervisor_server.py (774 lines, all) — not in my PRIMARY list but it is the ONLY caller of the ledger, so a verdict on reachability is impossible without it
- C:/.../audit-remediation/engine/runtime/supervisor_ledger.sql (178 lines, all) — the DDL IS the enforcement (UNIQUEs, CHECK domain, BEFORE-UPDATE trigger, write-once PK, floor PK); the Python module deliberately does not inline it
- C:/.../audit-remediation/engine/ci/live/run_supervisor.py (167 lines, all) — the production wiring
- C:/.../audit-remediation/engine/ci/live/run_live_turn.sh (294 lines, all) — deployment-time custody of the ledger DB and the report dir group membership
- C:/.../audit-remediation/apps/desktop/src-tauri/win-live/src/servers.rs (1136 lines, all) — the Windows/Rust supervisor twin
- C:/.../audit-remediation/apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs (255 lines, all)
- apps/desktop/AUDIT/AUDIT_LEDGER.md (all) and the F-09 rows of apps/desktop/AUDIT/2026-08-06-independent-audit.md

READ IN TARGETED DEPTH (not cover-to-cover):
- engine/runtime/challenge_authority.py — validate_create_pending (158-218) and issue_challenge / issue_challenge_document (465-588). Enough to establish who chooses install_id/task_id/request_nonce.
- apps/desktop/src-tauri/broker/src/chain_executor.rs — module header, RunEvidence (532-565), the Linux execution body (746-900). Enough to establish where the four evidence values and output_handle physically come from.
- engine/runtime/isolated_signer.py — _derive_hashes / _verify_chain_handles / _derive_output_bytes / _recompute_request_sha256 (629-700) and the identity allowlist (358-381, 605-611).
- apps/desktop/src-tauri/broker/src/main.rs — build_governed_executor (210-260), UpstreamBlockedExecutor (97-98).
- apps/desktop/src-tauri/win-live/src/execution.rs (1-186) and win_provision.rs (evidence constants).

NOT COVERED (and why):
- apps/desktop/src-tauri/core/src/supervisor_ledger.rs (~1373 lines) — I did NOT read it line by line. I established its caller set by exhaustive repo-wide grep for `supervisor_ledger::`, `evidence_floor_cas`, `accept_prepare`, `gate_and_start`, `enqueue_terminal`, `pending_outbox`, `lease_launch_gate` across every .rs file, and read the floor function's doc + body region (804-891) plus its #[cfg(test)] block boundaries via grep context. That is sufficient for the reachability claim in F-09-2 but I have not audited its internal logic.
- engine/tests/* — deliberately excluded; tests are the author's claim, not evidence.
- tools/check_ledger_ddl_parity.py — I did not verify the CI gate actually runs, so the "byte-equality enforced" claim in the module docstring is unverified by me. It does not change any verdict below (I read both copies' behaviour independently).

I could NOT execute anything (read-only snapshot, Windows host, Linux-only kit), so every walkthrough below is a static trace, not a live repro.

**`f10-tcb`** — FULLY READ, line by line:
- apps/desktop/src-tauri/broker/src/tcb_probe.rs (188 lines, complete)
- apps/desktop/src-tauri/broker/src/tcb.rs (25 lines, complete)
- apps/desktop/src-tauri/core/src/tcb_integrity.rs (616 lines, complete — the decision core tcb_probe delegates to; not on my list but the floor is meaningless without it)
- engine/ci/live/build_tcb_pin_manifest.py (122 lines, complete)
- engine/ci/live/run_live_turn.sh (295 lines, complete)
- engine/ci/live/ipc_policy.py (66 lines, complete)
- engine/ci/live/run_supervisor.py (168 lines, complete)
- engine/tests/test_live_tcb_pin_manifest.py (complete)
- apps/desktop/AUDIT/AUDIT_LEDGER.md (complete) and the F-09/F-10/F-11 region of apps/desktop/AUDIT/2026-08-06-independent-audit.md

READ IN THE RELEVANT PART (call-site tracing, not whole-file):
- apps/desktop/src-tauri/proof/src/bin/live_turn.rs:1-240 (main dispatch + verify_tcb + the head of run()); I did NOT read run()'s remaining ~100 lines line by line, but a repo-wide grep for verify_deployment_tcb/verify_tcb_integrity/tcb_probe over all .rs/.py/.sh/.toml/.yml shows the ONLY reference inside live_turn.rs is line 201, inside verify_tcb — so run() provably does not evaluate the floor.
- apps/desktop/src-tauri/broker/src/main.rs:1-360 (serve() + build_governed_executor, incl. the whole §2.5 block at 259-289)
- engine/ci/live/provision_keys.py:100-115 and 285-400 (DEFAULT_UIDS, the ipc-policy writer, the config block). The other ~350 lines (key generation, manifest signing) are F-17/F-01 territory, not mine.
- engine/ci/live/run_signer.py:60-80, run_authority.py:30-50 (which policy file each server actually loads)
- .github/workflows/ci.yml:55-100 (how run_live_turn.sh is invoked)

NOT COVERED: broker/src/chain_executor.rs (71 KB) beyond a targeted grep — it is F-08/F-26 territory and contains no TCB-floor reference. engine/runtime/governed_supervisor*.py read only for the fact that they exist and are large (45 KB + 34 KB) and are copied into the deployment tree, which is the fact my coverage finding rests on; I did not audit their logic.

PLATFORM: everything here is LINUX-ONLY. tcb_probe.rs:137-141 makes verify_deployment_tcb return Err on any non-Linux host, so on the Owner's WINDOWS box the §2.5 floor is unconditionally unsatisfiable — correct fail-closed behaviour, but it means nothing in this group is a Windows control. The whole live kit (run_live_turn.sh) is a LAB KIT run by root from a checked-out repo on a GitHub ubuntu runner; it is not the shipped desktop, which still carries UpstreamBlockedExecutor (broker/src/main.rs:96-106) and has no code anywhere in the tree that spawns brops-broker.

**`f06-f13-rollback`** — FULLY READ, line by line: engine/runtime/bro_signature.py (758 lines), engine/runtime/bro_completion.py (632 lines), engine/runtime/bro_evidence.py (184 lines), engine/tools/bro_deploy_preflight.py (149 lines), apps/desktop/AUDIT/AUDIT_LEDGER.md (70 lines).

READ IN FULL FOR THE RELEVANT SECTIONS: apps/desktop/AUDIT/2026-08-06-independent-audit.md rows F-06 (lines 235-271), F-13 (527-561), F-14 (564-599) including both counter-argument verdicts; engine/tests/test_evidence_chain.py lines 1-90 and 240-361 (the fixture + the three new F-13/F-14 tests); engine/tests/test_signature_authority.py lines 330-466 (the new self-owned-pin test + _write_pin_file); engine/tests/test_deploy_preflight.py lines 30-80; engine/runtime/bro_hook.py lines 160-215 (the Stop dispatch); engine/runtime/bro_orchestration_runtime.py lines 690-740 (the durable-runtime completion caller); engine/docs/OPERATOR_RUNBOOK.md lines 20-60.

EXECUTED (read-only against the snapshot; PYTHONDONTWRITEBYTECODE=1 and -B so no .pyc was written into the tree; all scratch files under my own scratchpad; nothing in the snapshot or the real repo was created, edited or deleted; no git commands run):
  * scratchpad/f06_probe.py — drove bro_signature._pin_from_file and resolve_operator_root_pin on this Windows 11 host against a pin file this process owns.
  * scratchpad/f13_probe.py — drove _head_floor_dir/_load_head_floor/_advance_head_floor directly.
  * scratchpad/f13_e2e.py (+ one-line variant f13_e2e_b.py) — subclassed the snapshot's OWN fixture test_evidence_chain.CompletionIntegrationTests so every event, head and signature is genuine, and ran three attacks through the real validate_evidence_chain body. All 20 tests, including the 8 shipped ones, ran green.
  * scratchpad/f06_preflight.py — subclassed the snapshot's test_deploy_preflight.PreflightFixture and printed the real preflight() verdict for a self-owned anchor.

NOT COVERED / LIMITS I ACCEPT:
  * POSIX behaviour of the F-06 st_uid==geteuid branch was read but NOT executed — no Linux host here. The path is four unconditional lines, so I am confident, but my empirical evidence is Windows-only.
  * I did not re-verify engine/runtime/bro_security.py's absolute-path mutation wall. The original audit's F-14 deflation rests on it; I carry that deflation forward on trust rather than evidence, which is why I attribute my findings to adversary 3 (interactive login user) and not adversary 1 (the model).
  * Reachability scoping I DID establish and which the reader must weigh: both of my blockers live in the ENGINE governance path, not in the desktop trusted_verified/production_verified chain. bro_completion.py is reached from bro_hook.py:194 (Stop gate) and bro_orchestration_runtime.py:725-728 (durable runtime). The desktop's evidence-head anti-rollback is a different, signer-owned primitive (apps/desktop/src-tauri/core/src/supervisor_ledger.rs:798-891, mirrored in engine/runtime/governed_supervisor_ledger.py:642-671). engine/ci/live/ (the 7-service kit) contains NO reference to BRO_OPERATOR_ROOT_PUBKEY*; the only bro_signature.load_trusted_keys consumer in that family is engine/tools/brops_supervisor_service.py:69, wired in engine/ci/isolation_proof.sh:77-83 under BRO_ENV=ci with the raw env pin. So on the code I read, neither F-06 nor F-13/F-14 is a direct route to a forged desktop trusted_verified message; they are keystone rows claimed CLOSED on the gate list that are not closed.

**`f07-f17-custody`** — READ FULLY, line by line:
- /engine/ci/live/provision_keys.py (444 lines)
- /engine/ci/live/run_live_turn.sh (294 lines)
- /apps/desktop/src-tauri/proof/src/bin/live_turn.rs (464 lines)
- /engine/ci/live/run_signer.py (135 lines)
- /engine/ci/live/build_tcb_pin_manifest.py (121 lines)
- /engine/tests/test_live_provisioning_anchor.py (100 lines)
- /apps/desktop/src-tauri/win-live/src/tcb.rs (82 lines)
- /apps/desktop/AUDIT/AUDIT_LEDGER.md (71 lines) and the F-07 / F-17 / F-28 sections of /apps/desktop/AUDIT/2026-08-06-independent-audit.md

READ IN PART (targeted, enough to settle the question at hand):
- /apps/desktop/src-tauri/broker/src/chain_executor.rs:735-894 (who writes store_dir / report_dir, what the broker reports to complete-run) plus a full grep of store/report/permission calls
- /apps/desktop/src-tauri/proof/src/bin/governed_recorder.rs:60-200 (recorder opens the store read-only; writes only into report_dir + recorder-state)
- /engine/ci/live/run_supervisor.py:85-115, 135 (supervisor publishes blobs into store_dir; socket chmod)
- /apps/desktop/src-tauri/broker/src/manifest_resolver.rs:1-130, /win-live/src/resolver.rs:70-110, /win-live/src/bin/win_live_turn.rs:85-120, /win-live/src/proof.rs:150-200 (where PinnedRoot comes from on the shipped/Windows paths)
- /.github/workflows/ci.yml:50-119 (how the live kit is invoked; whether external-anchor flags are ever passed)
- grep of tcb_probe.rs for the ancestor/O_NOFOLLOW logic (not read in full — F-10 belongs to another owner)

NOT COVERED (out of my assignment, and I do not rely on them): isolated_signer.py internals, tcb_integrity.rs / tcb_probe.rs in full, the supervisor ledger, governed_verification.rs. I did not and could not execute anything — this is a Windows host reading a Linux kit, so every mode/ownership claim below is read off the source lines, not observed on a live box. Note the asymmetry that creates: the live CI job would fail if these directories were too RESTRICTIVE, but would stay green if someone reverted 2775 to 1777, and no test in the tree asserts these modes — the ledger row's "4 new tests" are all in test_live_provisioning_anchor.py and cover F-17 only.

**`f11-dos`** — FULLY READ, line by line:
- C:/.../audit-remediation/engine/runtime/governed_supervisor_server.py (774 lines, all)
- C:/.../audit-remediation/apps/desktop/src-tauri/broker/src/main.rs (602 lines, all)
- C:/.../audit-remediation/apps/desktop/src-tauri/src/governed_turn.rs (94 lines, all)
- C:/.../audit-remediation/apps/desktop/src-tauri/core/src/ipc_framing.rs (196 lines, all)
- C:/.../audit-remediation/apps/desktop/src-tauri/core/src/broker_client.rs (all — it is the caller that orders recv_all vs decode_one)
- C:/.../audit-remediation/engine/ci/live/run_supervisor.py (all — the production wrapper around serve_forever)
- C:/.../audit-remediation/apps/desktop/AUDIT/AUDIT_LEDGER.md (all)
- The F-11, F-25, F-31, F-32, F-36 finding bodies + refutation verdicts in apps/desktop/AUDIT/2026-08-06-independent-audit.md

TARGETED READS (not full files): engine/runtime/governed_supervisor_ledger.py (error class hierarchy at 105-143, load_acceptance 680-687, load_attestation_state 814-860, validate_completion_facts 592-623); engine/runtime/governed_supervisor.py (accept_open 519-599); engine/runtime/challenge_authority.py (peer_is_broker 406-417); engine/runtime/isolated_signer_server.py + challenge_authority_server.py (only the except-tuple and recv_exactly lines, to check whether F-25 was fixed in the siblings); engine/tests/test_governed_supervisor_server.py (frame-bounds + F-11 regression block 281-320, _frame helper 191-193); engine/ci/live/run_live_turn.sh (server-start lines 244-271).

EXECUTABLE EVIDENCE: I ran the REAL governed_supervisor_server module under `python -B` (PYTHONDONTWRITEBYTECODE=1) against fake conns from my own scratchpad. No file in the snapshot or the repo was written, edited, or deleted; no git command was run.

NOT COVERED (out of my assignment, other agents own them): brops_broker::tcb_probe, chain_executor, manifest_resolver, the Windows win-live/win-broker twins, and the full governed_supervisor_ledger transaction logic. I therefore make no claim about whether the broker's real chain executor can be reached, only about the transport/robustness legs I was assigned.

PLATFORM: everything below is LINUX. governed_turn.rs's cap and timeouts are inside `#[cfg(target_os = "linux")]` (governed_turn.rs:46-57, 64); on Windows `connect_broker` returns Err (governed_turn.rs:58-61) and brops-broker exits EXIT_PLATFORM_UNSUPPORTED (main.rs:117-123). None of these findings affect the Owner's Windows host.

**`f26-binding`** — FULLY READ, line by line (snapshot root = C:/Users/Admin/AppData/Local/Temp/claude/c--Users-Admin-Desktop-Bro-Audit/8abeb513-8eb8-4a6f-b315-95053401c38c/scratchpad/audit-remediation):
- apps/desktop/src-tauri/core/src/governed_verification.rs (all 758 lines, incl. the whole test module)
- apps/desktop/src-tauri/core/src/production_trust.rs (all 155 lines)
- apps/desktop/src-tauri/core/src/manifest_authority.rs (all 177 lines — read in full; it turned out to be the Wave-3a receipt-store key authority, not on the F-26/27/29 path, so no verdict rests on it)
- apps/desktop/src-tauri/broker/src/manifest_resolver.rs (all 284 lines)
- apps/desktop/src-tauri/proof/src/bin/live_turn.rs:97-109, 260-465 (the whole trust-resolution + acceptance + verdict section)
- apps/desktop/src-tauri/win-live/src/bin/win_live_turn.rs:1-256 (whole `win` module)
- apps/desktop/src-tauri/win-live/src/proof.rs:1-336 (whole in-process driver)

READ IN THE RELEVANT PARTS (not end-to-end):
- apps/desktop/src-tauri/broker/src/chain_executor.rs:1-1029 read fully (module doc, GovernedChain::run_verified, parse_lease, OwnedEnvelope, the entire `linux` module). The remaining ~900 lines are the `#[cfg(test)]` module; I read its fixture head (968-1130) and grepped the rest rather than reading it line by line.
- apps/desktop/src-tauri/win-live/src/resolver.rs:80-300; win-live/src/servers.rs:360-420, 442-600, 648-740, 929-1090; win-live/src/pipe.rs:130-175; win-live/src/execution.rs (grepped for the clock only)
- apps/desktop/src-tauri/core/src/key_manifest.rs:100-170 (resolve_production_key)
- apps/desktop/src-tauri/src/commands.rs:1955-2065 (demonstration_verified_reply — the app-reachable consumer of proof.rs)
- engine/runtime/governed_supervisor.py:560-710, 790-860; engine/runtime/governed_supervisor_ledger.py:589-624; engine/runtime/governed_supervisor_server.py (grepped clock handling); engine/tests/test_governed_chain_e2e.py:415-470

NOT COVERED: engine/runtime/isolated_signer.py was only grepped (lines 128, 184, 617, 715, 741) — I did not read its attestation-verification path line by line, so my F-27 chain-of-custody claim for Linux rests on the supervisor side + the broker's own re-verification of the attestation bytes (governed_verification.rs:303-310), which is sufficient for the verdict I give. I did not build or run anything (read-only mandate), so all "test would fail without the guard" statements are by code reading, not execution.

**`windows-twin`** — FULLY READ, line by line (all under SNAPSHOT ROOT = C:/Users/Admin/AppData/Local/Temp/claude/c--Users-Admin-Desktop-Bro-Audit/8abeb513-8eb8-4a6f-b315-95053401c38c/scratchpad/audit-remediation):

apps/desktop/src-tauri/win-live — every real source file:
  src/lib.rs (130), src/servers.rs (1136), src/pipe.rs (262), src/resolver.rs (331), src/execution.rs (186), src/config.rs (154), src/seedstore.rs (110), src/tcb.rs (81), src/proof.rs (410),
  src/bin/win_live_turn.rs (255), win_provision.rs (224), win_supervisor.rs (49), win_authority.rs (37), win_signer.rs (43), win_executor.rs (13), win_gen_root.rs (skimmed — offline root generator, no runtime path),
  proof/win_live_proof.ps1, proof/CROSS_ACCOUNT_PROOF.md, proof/WINDOWS_BROKER_AUDIT_VERDICT.md, proof/BUILDER_AUDIT_VERDICT_2026-08-04.md, WIRING_LIVE_TRUST.md, WINDOWS_ANTIROLLBACK_HARDENING.md.

apps/desktop/src-tauri/win-broker: src/lib.rs (313, in full incl. the #[cfg(windows)] syscall module and its tests), proof/isolation_proof.ps1. Skimmed only (not on the win_live_turn path, confirmed by grep that nothing in win-live calls them): src/bin/restricted_launch.rs, spawn_as.rs, pipe_proof.rs.

Supporting reads for reachability: apps/desktop/AUDIT/AUDIT_LEDGER.md (full), apps/desktop/AUDIT/2026-08-06-independent-audit.md (F-01 + F-02 sections + every Windows-mentioning line), apps/desktop/src-tauri/src/governed_selftest.rs (full), src/commands.rs:1966-2062 (demonstration_verified_reply), core/src/repo.rs:944-960 + 1090-1123 (receipt projection + demonstration commit), core/src/governed_message_store.rs (grep of the CHECK constraint), broker/src/tcb_probe.rs:1-60, tools/check_ledger_ddl_parity.py:1-60, .github/workflows/ci.yml:60-145, apps/desktop/src-tauri/Cargo.toml.

NOT COVERED and why: I did not read brops_core::governed_verification::verify_and_accept, key_manifest.rs or production_trust.rs line by line — they are the shared (Linux+Windows) verification core and were assigned to other reviewers; I treated their signature checks as sound and reasoned about what the Windows kit feeds them. I could not EXECUTE anything: this is a Windows host but the snapshot has no built binaries and I am read-only, so every claim below is static code reading, not a run. I could not verify the CROSS_ACCOUNT_PROOF.md result because no script, transcript or artifact for it exists in the tree.

---

*No file in menqstudio/OS was modified in the course of this audit.*
