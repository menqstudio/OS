# Eleventh round — independent code audit at `main` @ `e3fc507`

**Date** 2026-10-09 · **Audited head** `e3fc507fc325506cd62333487ee25fe6a28fed54` ·
**Previous audited head** `75fca65` · **Range** `75fca65..e3fc507` (128 commits, 916 files,
107,396 insertions, 10,788 deletions) · **Verdict** **RED**.

This report changes no product code. It was written from the detached audit checkout and was not
committed or pushed.

## Executive result

The three production-gate refusals in `CLAUDE.md` section 6 are real at this head. None of PRs #367,
#368, #378 or #380 opens production `trusted_verified`. That is the good result.

It is not a GREEN result. The production path behind the refusals is internally inconsistent in two
places: the broker accepts and commits outputs it cannot frame back to the desktop, and it refuses the
desktop's own persisted `agent` role. Separately, an enabled automation with one ordinary non-ASCII
suffix panics the scheduler while it holds the only database mutex, after which every database command
fails closed. The native-confirmation surfaces also render attacker-controlled control/bidi text as
trusted dialog labels, and the newly granted trust self-test is classified read-only although on Windows
it can synchronously run an arbitrary configured shell command with no timeout.

No P0 was found. This round records **4 P1, 5 P2 and 1 P3** findings.

## Findings

### `K-01` — P1 — a verified output can be committed and then become undeliverable

**File and symbol.** `apps/desktop/src-tauri/core/src/governed_output_pull.rs`:
`MAX_OUTPUT_BYTES`; `apps/desktop/src-tauri/core/src/broker_orchestrator.rs`:
`run_governed_turn`; `apps/desktop/src-tauri/broker/src/main.rs` (Linux): `handle_conn`;
`apps/desktop/src-tauri/core/src/ipc_framing.rs`: `encode_frame`.

The verified output contract permits 8,388,608 bytes. `run_governed_turn` persists that body and returns
it inside `RendererGovernedTurnResult::committed`. `handle_conn` serialises the whole result and passes it
to an encoder capped at 8,192 payload bytes. The commit therefore precedes a transport failure for every
otherwise-valid result whose JSON exceeds the frame cap. The renderer receives no committed result even
though the database and durable turn ledger say committed; retry attaches to that committed turn and
cannot make the oversized frame fit.

**Reproduce.** Use the existing `broker_orchestrator::OkExecutor` pattern with a body longer than 8,192
bytes, run `run_governed_turn`, assert it returns `status == "committed"`, serialise that result, then call
`ipc_framing::encode_frame`. It returns `FrameError::Oversize`. The constants alone establish the wider
case: 8 MiB accepted versus 8 KiB framed.

**Fix.** Do not put the body in the bounded control reply. Return authenticated metadata plus a
capability and pull the already-verified body in bounded chunks, or make the same small cap an explicit
pre-execution/pre-commit contract. Add a real test crossing persistence and framing, including the lost
reply/retry case.

### `K-02` — P1 — a real desktop conversation blocks after its first agent reply

**File and symbol.** `apps/desktop/src-tauri/core/src/domain.rs`: `MESSAGE_ROLES`;
`apps/desktop/src-tauri/core/src/repo.rs`: `chat::post_message`;
`apps/desktop/src-tauri/core/src/governed_prepare.rs`: `HISTORY_ROLES`;
`apps/desktop/src-tauri/broker/src/ladder_executor.rs`: `SqliteTurnContent::read_window`.

The desktop stores generated replies with role `agent`; that is one of the three legal database roles.
The broker accepts only `user`, `assistant`, `system` and returns `UpstreamBlocked` for any other stored
role. Its positive fixture hand-inserts `assistant`, a role the real repository API will not accept. The
first governed turn may read only a user message; every later turn whose window includes the persisted
reply blocks before preparation.

**Reproduce.** Open the real core schema, create a conversation, call `chat::post_message` once with
`user` and once with `agent`, then pass that connection to `SqliteTurnContent::read_window`. It returns
`Err(UpstreamBlocked)`. Replacing the second role by the fixture-only `assistant` makes it pass.

**Fix.** Define one canonical stored-to-model role mapping (`agent` -> `assistant`) and hash the mapped
bytes, or make the shared vocabulary use `agent` end to end. Test through the real repository writer,
not a hand-created `messages` table.

### `K-03` — P1 — a Unicode automation trigger panics and poisons the application database mutex

**File and symbol.** `apps/desktop/src-tauri/core/src/repo.rs`:
`automations::parse_interval_ms` and `automations::run_due`;
`apps/desktop/src-tauri/src/lib.rs`: scheduler loop; `apps/desktop/src-tauri/src/commands.rs`: `locked`.

`parse_interval_ms` lowercases a UTF-8 `String` and calls
`rest.split_at(rest.len() - 1)`. `len()` is bytes; a final multi-byte scalar makes that index fall inside
the scalar and Rust panics. `create_automation` bounds character count but accepts the value. The
once-per-minute scheduler calls this parser while holding `state.db: Mutex<Connection>`. A panic poisons
that mutex, and `locked` deliberately refuses every later database command on a poisoned mutex.

**Reproduce.** Create and enable an automation whose trigger is `every: 5м` (or directly call
`parse_interval_ms("every: 5м")`). The byte split panics. Let the scheduler encounter that row; its task
dies holding the DB guard, and the next Tauri database command returns a poison error.

**Fix.** Parse the suffix with `strip_suffix` over the three ASCII units or with `char_indices`; never
derive a character boundary from byte length. Validate the complete trigger before persistence and add a
Unicode corpus test that drives the real scheduler under the mutex.

### `K-04` — P1 — native approval text can be visually forged by the payload being approved

**File and symbol.** `apps/desktop/src-tauri/src/commands.rs`: `confirm_approval`;
`apps/desktop/src-tauri/core/src/repo.rs`: `approvals::RunExecutionScope::dialog_text` and
`approvals::execution_payload`.

The native window and buttons are trustworthy; the body is not safely presented. Run intent, plan, step
title and step detail are renderer-created strings. They are length-bounded but control characters,
bidirectional overrides and label-looking newlines are accepted and interpolated into the native dialog.
An attacker can make the trusted OS dialog appear to contain a benign `Action:`/`Risk:`/`Step:` block
while moving or reversing the actual dangerous text. The digest can still bind the bytes perfectly; it
does not prove the human saw their unambiguous meaning.

**Reproduce.** Create a run/step whose title or detail begins with newlines and fabricated dialog labels,
or contains U+202E, request approval, and invoke `confirm_approval`. The raw characters reach
`message(dialog_body)`. Exact clipping/wrapping behaviour cannot be verified from the repository; the
settling experiment is a maximum-size fixture on each supported OS and dialog backend, photographed and
screen-reader inspected.

**Fix.** Reject C0/C1 and bidi controls at the write boundary, render every field in a structurally
separate escaped form, show immutable IDs and a canonical digest, and use a review surface whose complete
content is scrollable and measurable. Test the real native backend on every release OS.

### `K-05` — P2 — PR #378 grants a shell-running, unbounded command as tier R

**File and symbol.** `apps/desktop/src-tauri/capabilities/default.json`:
`allow-governed-trust-selftest`; `apps/desktop/src-tauri/command-policy.json`:
`governed_trust_selftest`; `apps/desktop/src-tauri/src/governed_selftest.rs`:
`run_selftest_model` and `governed_trust_selftest`.

On Windows, if `BROPS_SELFTEST_MODEL_CMD` is set, this command runs `cmd /C <value>`, writes a prompt to
it and waits with `wait_with_output()` with no deadline or stdout cap. PR #378 made any matching webview
able to trigger it and classified it tier R / read-only. The renderer does not choose the command text,
but it now chooses when and how often the configured process runs. A compromised renderer can cause
side effects, resource exhaustion or a permanent command hang. The commit message's claim that the five
new grants “write nothing” is false for this one (it also creates a temporary trust-chain directory).

**Reproduce.** On Windows, set `BROPS_SELFTEST_MODEL_CMD` to a command that appends to a marker file or
never exits, launch the production host, and invoke `governed_trust_selftest` from the window. The marker
is written or the invocation does not return. This Windows execution could not be run in this Linux
checkout; the source path is unconditional under `cfg(windows)` and the exact experiment above settles
the platform observation.

**Fix.** Do not grant the model-running seam as R. Split the pure chain self-test from model execution;
keep only the pure test window-callable. Put any process-running diagnostic behind native confirmation,
an argv-based configuration, a total deadline, output caps and rate limiting.

### `K-06` — P2 — delete confirmation is both text-spoofable and incomplete under TOCTOU

**File and symbol.** `apps/desktop/src-tauri/src/commands.rs`:
`delete_automation_prompt` and `delete_automation_after_native_confirmation`.

PR #321 correctly moved deletion behind a native dialog and re-reads the row before deletion. Two
properties remain broken. First, stored `name`, `trigger` and `action` are only truncated; newlines,
controls and bidi characters reach the trusted prompt verbatim. Second, the prompt displays `enabled`,
but the post-dialog equality check compares only name/trigger/action. A concurrent toggle changes a fact
the human saw while deletion still proceeds.

**Reproduce.** Create an automation with a newline/bidi name or action and inspect the native prompt.
For the race, open the prompt for an enabled row, call `set_automation_enabled(id, false)` while it is
open, then confirm: the equality check passes and deletes a row different from the one displayed.

**Fix.** Apply the same display-safety contract as `K-04`; compare every displayed field or, better, a
row version/digest in the same transaction as deletion.

### `K-07` — P2 — signer corruption escapes the promised typed-refusal boundary

**File and symbol.** `engine/runtime/isolated_signer.py`: `ArtifactStore.read_verified`,
`IsolatedSigner.sign_result`, `IsolatedSigner._derive_hashes`.

`read_verified` raises `SignerError` on a digest drift. `_derive_hashes` contains a nominal
`hash_mismatch` refusal after that call, but the store has already raised, and `sign_result` catches only
`_Refuse`. This contradicts the public contract “never raises on hostile input” and makes the published
`hash_mismatch` result unreachable for store corruption. It fails closed and signs nothing, but a service
request becomes an exception/availability event rather than a protocol verdict.

**Reproduce.** Build the ordinary test signer, replace
`store._blobs[handles["output_handle"]]` after `put`, and call `sign_result` with the otherwise-valid test
request. At this head the result was `RAISED SignerError store corruption: blob digest != handle` and
the signing recorder remained empty.

**Fix.** Translate integrity failures to `_Refuse(REASON_HASH_MISMATCH)` inside the public operation (or
make `read_verified` return a typed integrity result). Add the corrupt-after-put case through
`sign_result`, with a positive signing control.

### `K-08` — P2 — a failed run step does not fail the run, so later steps remain executable

**File and symbol.** `apps/desktop/src-tauri/core/src/repo.rs`:
`runs::fail_step_execution` and `runs::next_runnable_step`;
`apps/desktop/src-tauri/src/commands.rs`: `stream_run_step` / `fail_attempt!`.

On provider or governed failure, `fail_attempt!` marks only the claimed step `failed`. The run remains
non-terminal. `next_runnable_step` looks for `active`, then returns the first `pending` step and never
checks for an earlier failure. A second renderer invocation can therefore execute step N+1 after step N
failed, including after a safety/precondition step failed. The run becomes failed only if a later
successful step happens to call `advance` and no pending step remains.

**Reproduce.** Create a two-step run, claim step 1, call `fail_step_execution`, then call
`next_runnable_step`; it returns step 2. `stream_run_step` accepts the still-running run and claims it.

**Fix.** Atomically fail the run with the step (as rejection and abandoned-execution paths already do),
or make all runnable/claim paths refuse any run containing a failed predecessor. Add a two-step negative
test through `stream_run_step`.

### `K-09` — P2 — release CI builds POSIX packages whose first launch cannot provision trust

**File and symbol.** `apps/desktop/src-tauri/tauri.conf.json`: `bundle.targets` and Linux `deb` files;
`apps/desktop/src-tauri/provision/src/anchor.rs`: `preprovision_refusal`;
`apps/desktop/src-tauri/provision/src/lib.rs`: `provision_with_anchor`;
`.github/workflows/release.yml`: release matrix.

Every non-Windows first launch requires a root-created anchor and deliberately aborts when it is absent.
Only the Debian bundle has a `postInstallScript` and ships `brops_install_anchor`. Yet the Tauri target is
`all`, and release CI builds Linux bundles and a macOS application. AppImage/RPM/macOS users receive no
in-repository installer step that can create the required anchor, so a clean first launch refuses by
design. Signing/notarisation checks do not test launchability.

**Reproduce.** Build/install a non-deb POSIX artifact on a clean machine with no
`/var/lib/brops-trust-anchor/trust-anchor/PROVISIONING.json`, then launch. `preprovision_refusal` aborts
before minting. This audit did not install those packages; that clean-VM experiment is required to
observe each packager's UX.

**Fix.** Stop publishing unsupported targets, or provide and test an appropriate privileged install
ceremony for each target. Release CI must install each produced artifact in a clean VM and complete the
first launch.

### `K-10` — P3 — a successful full test claim is not reproducible in the audit environment

**File and symbol.** `CLAUDE.md` section 6; `config/counted-claims.json` `engine_tests`;
`engine/tests` full discovery.

The loader counts 2,741 cases, matching the document, but the instructed full command did not pass in
the managed non-root audit environment: it reported 2,728 run, 17 skipped, 14 failures and 70 errors.
The failures observed were dominated by environment facts (AF_UNIX bind returns EPERM and `/tmp` is
owned by uid 65534, while custody fixtures expect root/uid 1000), not evidence of 84 product regressions.
The result is nevertheless not “2741 OK” on this checkout, and the command has no prerequisite probe that
turns those environmental assumptions into named skips/refusals.

**Reproduce.** Run `cd engine && BRO_ENV=ci python3 -m unittest discover -s tests` in this managed audit
container. Contrast with the targeted pure suites below, which pass.

**Fix.** Add an explicit environment preflight and skip only tests whose real OS proof is unavailable,
or provide the documented container/runner identity and socket policy that reproduces the claimed run.
Keep the measured environment beside every counted claim.

## The three production-gate refusals

| Refusal in `CLAUDE.md` §6 | Verdict from code | Exact qualification |
|---|---|---|
| 1. desktop provisioning probe refuses before a model | **CONFIRMED for the shipped build** | `commands.rs::governed_verification_unconfigured` measures five constants/collections: manifest false, two non-digests, empty executor roster, empty builder roster. All five are absent and callers block before model execution. The helper can return `None` for provisioned inputs, so it is not an unconditional refusal in every hypothetical build. |
| 2. broker connection is unsupported off Linux | **CONFIRMED** | `governed_turn.rs::connect_broker` returns `UnsupportedPlatform` under `cfg(not(target_os="linux"))`. PR #368 adds a Windows job that runs the one named test and asserts `1 passed`; the workflow is correctly written. Whether GitHub actually executed that job **cannot be verified from the repository**. The settling experiment is the run log for commit `9b138d1`/the audit head, or the exact filtered test on a Windows runner. |
| 3. broker falls back to `UpstreamBlockedExecutor` | **CONFIRMED for shipped configuration; REFUTED if read as unconditional** | `broker/src/main.rs::build_governed_executor` selects the blocker when `BROPS_BROKER_CONFIG` is absent, malformed, incomplete or fails the TCB/trust floor. No shipped package sets that variable. A valid external deployment can select `LadderChain`; therefore the code is not permanently blocked. `INSTALL_MINTED_CUSTODY_ACCEPTED == false` keeps install-minted custody demonstrational, while an independently provisioned external root may qualify. |

The production gate is therefore closed today. That does not mitigate `K-01`/`K-02`; it postpones
their reachability until refusal 3 is legitimately cleared.

## Requested PRs and changes

| Change | Audit result |
|---|---|
| #313 (`73e5ccb`) | The bare-`&` shell-classifier hole is closed in the then-current parser; the root floor-writer uses dir-fd relative `O_EXCL|O_NOFOLLOW` publication. Later T-159 replaced the shell grammar; the current parser was read, not the obsolete patch trusted. No regression found in these two fixes. |
| #314 (`712163a`) | Large mechanical repair wave. Security-relevant gate/runtime changes were read against current code. No single claim of “405 fixed” was accepted as evidence; current gates and source were checked. `K-07` remains one of the explicitly documented items it did not close. |
| #321 (`cf5f134`) | The capability tightening is real: generic message/status/delete paths are denied or structurally refusing. The native automation delete is not safe enough as presented (`K-06`). |
| T-020 / #219 (`2a50081`) | Current floor-writer and its custody/locking tests were read although the merge predates the diff base. The full environment-dependent proof could not run here because of uid/socket restrictions; targeted pure logic remains fail-closed. |
| T-021a / #254 | The request schema is exact and cannot carry decision authority. The free-text secret route remains explicitly open (`A-09` route 1). |
| T-021b / #255 | The engine appends an unauthenticated request, never a verdict; duplicate/state/evidence rules are present. The log is local hash chaining, not an authenticated boundary. |
| T-021c / #256 | The host request builder supplies a closed request and refuses decision-shaped replies. No key/lease/database parameter crosses this API. |
| T-021d / #257 | The page labels the engine queue separately and is gated on a readable mirror. It still points at a store no shipped writer populates; OWNER_ACTION_REQUIRED 2g is confirmed, not cured by the UI. |
| #367 (`cbe4a76`) | The five formerly unexercised verification checks now have direct negative tests and positive controls. I found no test that could pass solely because setup always refused in those five cases. |
| #368 (`9b138d1`) | The workflow runs the non-Linux refusal test and rejects a zero-match filter. Correct as source; actual Windows CI execution cannot be verified from the repository. |
| #378 (`d064a69`) | Four mirror reads are read-only. The fifth grant, the trust self-test, is not: `K-05`. |
| #380 (`17fa94f`) | Making `brops-win-live` unconditional lets the in-process chain compile/run on Linux. Off Windows the model seam is a fixed placeholder and does not execute `BROPS_SELFTEST_MODEL_CMD`; that particular widening is correctly contained. |

## `OWNER_ACTION_REQUIRED` checks

- Item 5 is **confirmed**, with an executable reproduction: `K-07`.
- Item 6's requested scope was used as the audit perimeter; claims in the document were rechecked in
  code.
- Item 2g is **confirmed**: integrations can be declared but no transport/configuration path connects
  them, and the automation/produced-agent authority remains deliberately unarmed from the cockpit.
- Item 2h is partly superseded: PR #378 grants the self-test and PR #380 compiles/runs its chain on
  Linux. The Windows model seam creates the new classification/reachability problem in `K-05`.

## Tests and experiments

- `BRO_ENV=ci python3 -m unittest tests.test_isolated_signer tests.test_control_room_api tests.test_orchestration_runtime tests.test_approval_requests`: **128 passed**.
- `python3 -m unittest discover -s bridge/tests -p 'test_*.py'`: **228 passed** (ResourceWarnings for
  test SQLite handles, no failure).
- `npm run typecheck`: **passed**.
- `npm run build`: **passed** (132 modules transformed; production bundle emitted).
- `npm test`: **1,151 passed, 2 failed**. Both failures are
  `debPackage.wiring.test.ts` observing an empty stdout/stderr from the staging helper in this managed
  environment; they are not counted as product passes.
- `python3 -m unittest discover -s tools/tests`: **1,769 passed**.
- `cargo test --workspace`: did not complete cleanly in this managed environment. The reached
  `brops-broker` library result was **171 passed, 5 failed**; all five failures were Linux transport
  fixtures whose `UnixListener::bind` returned `EPERM`, the same unavailable socket operation seen by
  the Python suite. The command stopped at that crate, so this is not represented as a full-workspace
  pass.
- Full engine suite: **not clean here**; exact result and environmental causes are in `K-10`.
- Direct signer-corruption experiment: raised `SignerError`, zero signed messages (`K-07`).
- Duplicate-key experiment: Python `json.loads` accepted the duplicate and retained the last value;
  this matters to JOB 2's proposed parser, not to an existing claimed strict parser.
- A direct sweep of the executable repository gates produced a mixture of zero and nonzero exits;
  several gates intentionally reject a detached/audit checkout or stale/generated coordination state.
  Their own unit suite above is the reproducible result; the direct sweep is not represented as a
  release-gate pass.
- After filing this report, `python3 tools/check_audit_reports.py` correctly returned RED because
  `AUDIT_LEDGER.md` and `config/current_state.json` still name the tenth audit. The brief permits only
  reports and forbids fixes/commits, so those canonical pointers were deliberately not changed here.

## What I did not read or could not verify

The 916-file diff was enumerated and mechanically scanned in full. I read the changed source and tests in
the requested security perimeter (`engine/runtime`, `engine/tools`, `bridge`, `apps/desktop/src-tauri`),
the changed `tools/` gates and `.github/` workflows, then the changed desktop service/surface paths. I
also read the cited PR diffs and the current implementations they changed.

I did **not** semantically read every one of the 265 generated `.claude/agents/*.md` profiles or every
line of the large archived whole-repository-read JSON/Markdown evidence dumps; their diffs were included
in path/count/control-character scans. I did not reread every unchanged historical source file outside
the requested perimeter. Those are the explicit unread portions; this report does not call the entire
repository line-by-line reviewed.

The following cannot be verified from the repository alone:

- actual GitHub PR discussion, Owner-waiver text outside committed records, or CI run outcomes (network
  was unavailable);
- Windows named-pipe/DACL/`cmd /C` runtime behaviour and macOS native dialog/package behaviour;
- the permissions and contents of an installed machine's provisioned registry/state, including whether
  its generated registry grants `control-room-command` to `control-room` (the Rust generator does);
- the appearance, clipping, bidi rendering and accessibility of maximum-size native dialogs;
- clean-install behaviour of every produced package.

The settling experiments are, respectively: inspect pinned CI logs; run the named Windows tests and
marker command on a Windows runner; mint into a fresh temporary provision root and verify it with the
Python verifier; run the dialog corpus on all three OS backends; install every release artifact in a
clean VM and complete first launch. No access was made to `/var/lib/brops-trust-anchor` or
`~/.local/share/studio.menq.brops`.

## Verdict

**RED.** The production gate remains shut, but that is not evidence that the path behind it is ready.
`K-01`, `K-02` and `K-04` invalidate the end-to-end integrity/usability claim of a future governed path;
`K-03` is a reachable whole-app availability failure today. `K-05` also means PR #378 widened execution
authority while describing it as a read. Do not open the production gate or treat the owner-command
proposal as implementable until the corresponding design review is resolved.
