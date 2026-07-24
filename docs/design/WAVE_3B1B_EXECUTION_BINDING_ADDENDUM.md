# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 16 — CONSOLIDATED)

> **STATUS: ❌ DESIGN RED being closed — rev 16 is a PROPOSED design-GREEN candidate, NOT
> Architect-GREEN. 3b-1B code has NOT started.** rev 15 was Architect-reviewed at exact HEAD
> `848f2a665b04cdef64783a8ff452f24dec274831` (exact-head CI **#119 / run 30065934684**
> SUCCESS — **CI GREEN ≠ design GREEN**); the Architect returned **Design RED** with **3 P0 + 3 P1
> protocol/proxy/state-consistency findings** and directed a **mandatory parallel fan-out + one
> integrator + a fresh independent red-team, NOT a rewrite.** rev 16 was produced exactly that way:
> **six independent read-only audit tracks** (A protocol-compat/routing · B output proxy ·
> C challenge two-phase verify · D state/reason enums · E retry/crash idempotency · F adversarial
> E2E) read the real repo code, a **single integrator** consolidated their evidence and edited in
> place, and a **fresh independent red-team** re-checked the diff. The rev-15 → rev-16 findings
> closed here: **P0-1** rev 15 still said the shipped `brops.governed-result.v1` constant/emitter/
> consumer must be "renamed together" (would break the GREEN 3b-1A path) → **KEEP** the shipped
> `GOVERNED_RESULT_PROTOCOL` unchanged + **ADD a parallel** `GOVERNED_TURN_RESULT_PROTOCOL`
> (new emitter/consumer/schema/tests, nothing old renamed) + one canonical positive-`protocol`-const
> bridge rule (§2.2); **P0-2** the supervisor-side output pull had no desktop→sidecar route → a
> complete **`bridge.governed-turn-output-read.v1`** request/reply, a per-chunk one-shot-subprocess
> Tauri command, and a durable supervisor **`governed_output_streams`** table (43-char base64url
> capability token, `OUTPUT_STREAM_TTL_MS = 360000`, restart-survival, same-id retry) (§4.10(f));
> **P0-3** `governed-turn-open` referenced the §7 as-of-`challenge_accepted_at_ms` predicate that
> does not exist at open → **two-phase verification** (open-time preliminary as-of
> `challenge_issued_at_ms` + a **canonicality gate** `decoded == JCS({payload,sig})`; acceptance-time
> authoritative **re-resolves the current registry** as-of `challenge_accepted_at_ms`) (§4.10(a0),
> §5, §7); **P1-4** `EXPIRED` was CAS'd but not in the state enum and `evidence_fork`/several reasons
> were prose-only → a **closed 9-value state enum + one `GOVERNED_REFUSAL_REASONS` union** enumerated
> in every relay (no "mirrors §4.5") (§5, §4.5, §4.6, §4.10); **P1-5** §7 never bounded
> `completed_at_ms ≤ lease_expires_at_ms` and the launch gate had zero slack → **`MIN_LAUNCH_REMAINING_MS
> = 180000`** + the full chain `lease_issued ≤ started ≤ finished ≤ completed ≤ lease_expires`
> (§5, §7, §4.7); **P1-6** a lost reply stranded an upload (`duplicate_open`/`duplicate_session`/
> `seq_mismatch`) → **exact idempotency** (same-bytes retry → same handle/session/ack; conflict →
> `retry_conflict`) + durable session/per-chunk columns for restart survival (§2.4, §4.10). **All
> contracts below are OPEN until the Architect returns design-GREEN at the exact pushed HEAD.**
> STOP gates: `NoTrustedManifest` unchanged, no production "Verified", 3b-2/3b-3 not started, PR #31
> not merged.

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. It reuses the
> existing lease / containment / receipt / evidence authorities — **no parallel executor**.
> **This document is the single normative source for the 3b-1B contracts; where any other
> file (including the 3b-1 map) and this document disagree, THIS document wins and the other
> is a bug to fix.**

---

## 0. Scope & topology

The governed AI turn (desktop `system`/`history` → model reply) becomes a
**`bro_supervisor`-owned supervised execution** that **atomically emits a signed terminal
record**. No unsigned run-state JSON is ever signing authority. The model executor is the
`builder_command` for this run — spawned + contained exactly as any builder, but under the
recorder (below), holding **no signing key**.

```
supervisor (owns the acceptance ledger §5 + the governed-turn lease issuer + the
            governed-turn-recorder key; signs the TERMINAL RECORD only)
  → EVIDENCE-RECORDER RUNNER  (dedicated recorder UID; holds the evidence-recorder key;
        signs the governed-turn execution RECEIPT + evidence chain/head; owns the
        executor pidfd/cgroup + output pipe + teardown measurement)
      → NARROW PRIVILEGED LAUNCHER  (tiny setuid helper: only setuid(executor)+exec the
            pinned model executor in a fresh cgroup/process group; holds NO key)
          → CONTAINED MODEL EXECUTOR  (executor UID; NO key/store access; reads 3 read-only
                input FDs, writes 1 output FD — nothing else, §2)
```

Distinct OS principals: **desktop-UI/challenge-authority**, **sidecar** (compromised
in-scope, same login user), **supervisor**, **evidence-recorder runner** (the
`brops-recorder` principal that writes `store/rec/`), **privileged launcher**, **contained
executor**, **isolated receipt signer**. The **`governed-turn-recorder` is NOT a distinct OS
principal** — it is a supervisor-held **signing-key authority** (an `ARTIFACT_AUTHORITY` key
class owned by the `brops-supervisor` principal) that signs the terminal record only (§8, P1-5);
do not confuse it with the `brops-recorder` OS principal above.
Threat scope (from the ratified base design): sidecar RCE at the **same login user** is
IN scope; admin/root/kernel is OUT of scope. Where a platform cannot separate the
desktop-UI principal from the sidecar UID, governed real-mode is **FAIL-CLOSED** on that
platform (Windows is fail-closed until its broker is separately audited).

---

## 1. Canonical time model (P0-1) — ONE unit, explicit names

**Every governed-turn artifact uses integer epoch MILLISECONDS**, and **every field name
ends in `_ms`** so the unit is visible at the call site. The ratified base `execution-lease`
(`issued_at_epoch`/`expires_at_epoch`, epoch **seconds** via `int(time.time())`) is **left
unchanged and is NOT reused** by the governed-turn chain — the governed-turn lease is a
**separate artifact** with its own `_ms` fields (§4.3), never the base `*_epoch` names with
silently changed units.

- **LEGACY epoch-seconds reused artifacts (P1-4, LOCKED — do NOT mutate).** The reused
  **`bro_evidence` event/head** (`issued_at_epoch`) is epoch **seconds** (minted by `broctl`
  as `int(time.time())`; `EVENT_FIELDS`/`HEAD_FIELDS` are exact-set-matched + Ed25519-signed,
  so changing the unit is a breaking re-sign of every stored chain). It stays epoch-seconds
  and is a **legacy exception** to the `_ms` rule: its `issued_at_epoch` is **NEVER** compared
  against any governed-turn ms window. Only the evidence chain's **structural** bindings
  (`event_hash`, `sequence`, `final_event_hash`, `head_sequence`) cross into the governed-turn
  record — no time comparison — so the seconds field never touches the ms logic. The desktop's
  own receipt-freshness window is ms (`FreshnessWindow{future_skew_ms, max_age_ms}` vs
  `now_ms`) and applies only to governed-turn `_ms` fields, never to the evidence seconds.

- Canonical fields: `requested_at_ms`, `challenge_issued_at_ms`, `challenge_expires_at_ms`,
  `challenge_accepted_at_ms`, `lease_issued_at_ms`, `lease_expires_at_ms`, `started_at_ms`,
  `finished_at_ms`, `completed_at_ms`, `measured_at_ms`, `registry_issued_at_ms`,
  key `valid_from_ms` / `valid_to_ms` / `revoked_at_ms`.
- Type: JSON **integer**, `1 ≤ v ≤ 2^53-1` (fits an f64/i64 both sides; overflow/negative
  rejected). The desktop's Wave-3a `requested_at` is normalized to `requested_at_ms` (ms)
  **when the challenge authority builds the challenge** (§4.1); the whole chain is ms after
  that point.
- **`challenge_accepted_at_ms` is produced by exactly one supervisor clock read** (§5 step
  2) and is the **only** field the validity/expiry/revocation window is checked against.
- **Boundaries are inclusive on both ends:** a time `t` is in a window iff
  `lo_ms ≤ t ≤ hi_ms`. The acceptance predicate (§5, §7) is
  `requested_at_ms ≤ challenge_accepted_at_ms` **and**
  `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤ challenge_expires_at_ms`.
- **Freshness + window nesting (P1-6, LOCKED).** The desktop freshness window is the real
  `FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}` (`receipt_store.rs`). Every
  engine-side governed-turn window MUST nest inside `max_age_ms = 300000` so a legitimately
  executed turn is never refused as stale: governed **challenge TTL** `≤ 30000 ms`;
  **`EXECUTION_TIMEOUT_MS = 120000`** (§4.7); governed **lease window** `≥ EXECUTION_TIMEOUT_MS`
  + teardown; and engine↔desktop wall-clock skew bounded `≤ 60000 ms` (shared NTP) because the
  desktop stale check has **no** skew allowance on the old side. Elapsed timeouts use a MONOTONIC
  clock; only signed `_ms` fields use the wall clock (§4.7).
- **Negative tests (normative):** a value that is plausibly seconds not ms (≈10 digits vs
  ≈13) is rejected by range/consistency; overflow, negative, zero, far-future-skew, and each
  inclusive boundary (`== lo_ms`, `== hi_ms`, `lo-1`, `hi+1`) are covered. Cross-language
  (Python engine ↔ Rust desktop) parity asserts identical ms integers.

---

## 2. Principals & capabilities (P0-3) — the executor inherits NO builder authority

The base lease task classes (`STANDARD_BUILDER`, `SECURITY_MAINTENANCE`) each grant
`{EXECUTE_CODE, WRITE_FILESYSTEM, WRITE_REPOSITORY}` and are built around repos/worktrees.
The governed model executor's locked topology gives it **only three read-only input FDs and
one write-only output FD** (§4.7). It therefore uses a **dedicated, closed capability
profile — NOT a base-lease superset**:

- **task class `governed-model-turn-v1`** with a **CLOSED** capability set
  `["INVOKE_GOVERNED_MODEL"]` — the single narrow capability "run the pinned model executor
  once, read the three input FDs, write the one output FD". It **MUST NOT** include
  `EXECUTE_CODE`, `WRITE_FILESYSTEM`, `WRITE_REPOSITORY`, arbitrary path access, arbitrary
  executable selection, or arbitrary tool invocation. `validate_governed_turn_lease` (§4.3)
  rejects any lease whose `allowed_capabilities` is not exactly `["INVOKE_GOVERNED_MODEL"]`.
- **`max_tool_calls = 0`** — tool use is out of 3b-1B scope and **fails closed**. (If tool
  execution is ever added, it needs a separately-mediated, exactly-scoped tool-broker
  contract; builder capabilities are never inherited implicitly.)
- The **pinned launcher executable digest** (`launcher_executable_sha256`) and the **model
  profile** (`model_profile_id`) are explicit lease fields with real verifiers (§4.3): the
  launcher refuses any other executable/target UID (§4.7), and the recorder refuses a
  `model_profile_id` not in its allow-set.
- The governed-turn lease **omits** the builder-only fields `repository`, `branch`,
  `worktree`, `head_sha`, `tree_identity`, and `protected_scope` — none has a verifier for a
  model turn. (If a future justified use reintroduces `protected_scope`, its type is an
  **array of exact non-pattern paths**, never a string.)

### 2.1 Challenge-authority trust boundary + creation channel (P0-2, NORMATIVE — no oracle)

The sidecar is compromised-in-scope (same login user). The desktop signed challenge
(artifact #1) is minted by a **dedicated `desktop-challenge-authority`** that is neither a
`sign(payload)` oracle nor a `create_pending(arbitrary_bytes) → sign(id)` two-step oracle.
The exact current contract (not history):

- **Store ownership:** the **pending-challenge store** (the trusted rows the authority builds
  challenges from) and the authority private key are owned by the authority's **own dedicated
  OS principal (UID/SID)**, mode owner-only (`0700`). **The sidecar UID can neither read, nor
  write, nor list** it — so it can neither exfiltrate the key nor tamper a row directly.
- **Distinct principals:** the **desktop-UI principal MUST be a UID distinct from the
  sidecar** principal. Where a platform cannot provide that separation, governed real-mode is
  **FAIL-CLOSED** on that platform (mirrors the Windows-broker stance, §0).
- **Creation channel:** pending-challenge rows are created **only** through an
  **authority-owned `AF_UNIX` channel**; on Linux the authority authenticates the peer with
  **`SO_PEERCRED`, allowlisting the exact desktop-UI UID** — the sidecar UID is denied. The
  caller supplies **structured authoritative turn facts** (`run_id`/`task_id`/context +
  `system_sha256`/`history_sha256`/`generation_config_sha256`/`request_sha256`/
  `requested_at_ms`) **or** an **authority-resolved protected row identifier** — **never
  challenge bytes and never a caller-chosen canonical payload.**
- **Authority builds the payload itself:** from its protected state the authority
  **constructs** the exact `brops.governed-turn-challenge.v1` payload (§4.1), stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, and signs once (consuming the pending
  id). It never signs caller-supplied bytes/fields.
- **How desktop facts cross the boundary without giving the sidecar the same capability:** the
  desktop-UI principal (a **distinct UID**) is the only peer the `SO_PEERCRED` allowlist
  admits; it hands the structured facts over the authenticated channel, and the authority
  writes its **own** store. The sidecar (a different UID) is denied the channel by
  `SO_PEERCRED` **and** the store by file ownership — so it can present neither facts the
  authority will trust nor bytes the authority will sign.
- **Mandatory Linux isolation tests:** the sidecar principal cannot (a) read/list the
  authority key dir, (b) `ptrace` the authority, (c) create a pending row via the channel
  (peer-UID denied), (d) directly read/write/list/mutate the pending store file(s)/DB, or
  (e) obtain a signature over caller-chosen bytes — all machine-proven, alongside the 3b-1A
  denials.

Full principal/ACL matrix in Appendix B. The acceptance ledger + protected content-addressed
store: **acceptance ledger** is supervisor-only `0700`; the **published content-addressed
store** is the group-shared model of §2.3 (NOT a literal `0700` — see §2.3); executor/sidecar
have no store or key access.

### 2.2 Protocol versioning (P0-1) — NEVER mutate the GREEN 3b-1A v1 protocols

The governed turn introduces new fields (integer `_ms` timestamps, no `builder_id`, new
echoes, new refusal reasons) that the **already-GREEN 3b-1A** strict `additionalProperties:
false` v1 schemas would reject. The ratified protocols — **`brops.sign-request.v1`**
(requires `builder_id` + string `requested_at`/`completed_at`), **`brops.sign-result.v1`**
(closed 12-value `reason` enum), **`brops.evidence-request.v1`**, **`brops.governed-result.v1`**
(the EXISTING supervisor→sidecar shape already shipped in 3b-1A: `{protocol, status, output
(top-level string), receipt:{envelope_jcs_b64, signature_b64, containment_evidence_b64,
attestation_*, run_id, execution_attempt_id, lease_id}}` for `signed` and `{protocol, status,
reason}` for `refused` — the constant `GOVERNED_RESULT_PROTOCOL` + emitter in
`brops_supervisor_service.py` + the `engine_sidecar.py` consumer), the **`bridge.result`**
receipt (whose `receipt` object **already REQUIRES `envelope_jcs_b64`** — `bridge-result.schema.json`),
and the **`bridge.task-request`** — are all **frozen byte-for-byte** and MUST NOT be
redefined; the 3b-1A signer-isolation positive control (`brops_isolation_prover.py` +
`test_brops_services.py` + `test_brops_isolation.py`) + the shipped governed-result emitter
depend on them exactly. **The 3b-1B result therefore uses a NEW name (`brops.governed-turn-result.v1`),
NOT the taken `brops.governed-result.v1` (P0-1).**

The governed turn therefore uses a **separate `brops.governed-*` / `bridge.governed-*`
protocol family, in its own schema files**, selected by a **positive `protocol` const in both
directions** (the one canonical bridge rule, P0-1: the FROZEN `bridge.result` has **NO** top-level
`protocol` key and is `additionalProperties:false`, so it rejects any governed frame (unknown
top-level key); every NEW `bridge.governed-*` schema **REQUIRES** its explicit top-level `protocol`
const, so it rejects any `bridge.result` (missing const) — do NOT discriminate on
`receipt.envelope_jcs_b64`, which is required in both):
- **`brops.governed-turn-open.v1`** (+ `-result`) — the signed-challenge submission (P0-2),
  COMPLETE in §4.10(a0)
- **`brops.governed-sign-request.v1`** — `engine/contracts/brops-governed-sign-request.v1.schema.json`
- **`brops.governed-sign-result.v1`** — `engine/contracts/brops-governed-sign-result.v1.schema.json`
- **`brops.governed-evidence-request.v1`** — the sidecar→supervisor execute/finalize trigger,
  COMPLETE in §4.10(d) (the governed path uses THIS, never the v1 `brops.evidence-request.v1`)
- **`brops.governed-turn-result.v1`** — `engine/contracts/brops-governed-turn-result.v1.schema.json`
  (the supervisor→sidecar tagged union, COMPLETE in §4.10(e); a **NEW name distinct from the
  frozen `brops.governed-result.v1`** shipped in 3b-1A, P0-1). **KEEP + ADD, never rename (P0-1,
  LOCKED):** the shipped `GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` constant, its
  emitter (`brops_supervisor_service.py`), its `engine_sidecar.py` consumer, its schema and its
  positive-control tests stay **byte-for-byte unchanged**; 3b-1B **ADDS in parallel** a new
  `GOVERNED_TURN_RESULT_PROTOCOL = "brops.governed-turn-result.v1"` constant, a **new emitter
  branch**, a **new consumer branch**, a new schema and new tests. **Nothing old is renamed or
  repurposed** — the two coexist, selected by the `protocol` const.
- **`brops.governed-staging-open/-chunk/-final.v1`** (+ their `-result` replies) — the bounded
  ingress control plane, COMPLETE in §4.10(a–c) (§2.4)
- **`brops.governed-turn-output-read.v1`** (+ `-result`, supervisor hop) **and
  `bridge.governed-turn-output-read.v1`** (+ `-result`, desktop→sidecar hop) — the **pull-based**
  result-return (P0-2/P0-3), COMPLETE in §4.10(f): one idempotent request/response per chunk on
  each hop (the real `brops_socket` is one-request/one-response and the sidecar is a one-shot
  subprocess, so NO push stream); the desktop re-invokes the sidecar per chunk, the sidecar proxies
  one supervisor read. Backed by the durable supervisor `governed_output_streams` table (§4.10(f)).
- **`brops.governed-receipt-envelope.v1`** — the isolated-signer receipt envelope (§4.9)
- **`bridge.governed-turn-result.v1`** — `bridge/contracts/bridge-governed-turn-result.schema.json`
  (the COMPLETE parent, §4.6; a distinct schema + a distinct sidecar emit branch). **Discriminator
  (P0-1, CORRECTED):** it carries an explicit **top-level `"protocol": "bridge.governed-turn-result.v1"`
  const** in its `required` set. The frozen `bridge.result` (`additionalProperties:false`, no
  `protocol` key) therefore **rejects** any governed document (unknown top-level `protocol` key),
  and the new schema **rejects** any `bridge.result` (missing required `protocol` const) — true
  bidirectional disjointness via a positive discriminator. (The earlier claim that
  `receipt.envelope_jcs_b64` is "absent from `bridge.result`" was FALSE — it is a REQUIRED key of
  `bridge.result.receipt` — and MUST NOT be used to discriminate.) `bridge.result` stays untouched.

**Compatibility rule (LOCKED + tested):** the old/frozen path accepts ONLY its own documents and
**refuses** any new governed document; the new governed path accepts ONLY new-governed documents
(routed by `protocol` const) and **refuses** any frozen document. No shared file, enum, or
required-key list. The frozen v1/`bridge.result`/`brops.governed-result.v1` schema files, parser
functions, and tests are unchanged, and their positive-control round-trip runs identically.
**Compatibility tests (LOCKED):** (1) old `brops.governed-result.v1` (`signed`+`refused`) emitted
+ consumed by the shipped path with its exact shipped shape (golden/regression); (2) new
`brops.governed-turn-result.v1` emitted + consumed by the new branch; (3) an old doc fed to the new
consumer/schema → refuse; (4) a new doc fed to the old `brops.governed-result.v1` consumer/schema →
refuse; (5) `bridge-result.schema.json` rejects a `bridge.governed-turn-result.v1` doc (unknown
top-level `protocol`) and `bridge-governed-turn-result.schema.json` rejects a `bridge.result`
(missing required `protocol`), asserting discrimination is NOT via `envelope_jcs_b64`; (6) the
frozen positive-control (`brops_isolation_prover.py` + `test_brops_services.py` +
`test_brops_isolation.py`) still passes byte-for-byte after the ADD.

### 2.3 Protected-store namespaces + ACL (P0-1, LOCKED) — enforceable owner-write / shared-read

A single `0700` dir cannot be written by two distinct principals (supervisor + recorder) and
read by a third (signer) — so the store is **group-shared for READ**. But a `2770` (group-
write) dir is **also wrong**: under real POSIX, directory create/rename/unlink needs **`w`+`x`
on the dir**, so `2770` would let *every* `brops-store` member (incl. the signer and the other
namespace's owner) create/rename/unlink — breaking "signer read-only", "recorder cannot write
`sup/`", and "supervisor cannot write `rec/`". The 3b-1A CI today provisions `store` at `2770`
with the signer in the group (`isolation_proof.sh`), so that write leak is real and its
isolation prover (which runs only as the login user) does **not** currently prove the
recorder/signer write-denials. The corrected, enforceable model is **`2750` owner-write /
group read-traverse**:
- **Shared READ group `brops-store`** = `brops-supervisor`, **`brops-recorder`** (a dedicated
  recorder OS principal — NEW for 3b-1B; the 3b-1A key `evidence-recorder` is a signing-key
  authority, not this OS principal), and `brops-signer` (**read-only** member).
- **Store root** and both namespaces at mode **`2750`** (owner `rwx`, group `r-x` **— NO group
  `w`**, other `---`): `store/sup/` owner `brops-supervisor:brops-store` (supervisor writes:
  challenge doc, registry snapshot, inputs, self-resolved policy bundle, lease, terminal
  record) and `store/rec/` owner `brops-recorder:brops-store` (recorder writes: output,
  containment, execution-receipt). **Only the namespace owner may create/rename/unlink** in its
  own dir; the other owner and the signer get group `r-x` = **read + traverse only, no write**.
- **`setgid` bit stays set** on the dirs **only** to make new files inherit group `brops-store`
  (so the signer can read them); it does **not** grant directory write. Artifacts are **`0640`**
  (owner rw, group r, no world) — so a non-owner group member cannot even overwrite an existing
  artifact (needs `w` on the file), and `chmod`/symlink-swap needs file/dir ownership it lacks.
- **`umask 0027`** for every service process (new files ≤ `0640`, new dirs ≤ `0750`).
- **Runtime enforcement:** `brops_evidence_store._harden_dir` (which today refuses only world-
  write `S_IRWXO`) MUST additionally **refuse `S_IWGRP`** on the store dirs, so a re-introduced
  `2770` fails closed at load, not just in CI.
- **Private-key dirs stay strictly `0700`** owner-only (`signerkeys`→`brops-signer`,
  attestation keys→`brops-supervisor`, evidence-recorder key→`brops-recorder`, **governed-turn-
  recorder key→`brops-supervisor`** — an owner-only `0700` dir held by the supervisor principal,
  NOT a separate principal, P1-5). The **evidence-head floor DB** (§7 P1-7) is `brops-signer`-owned, dir `0700`/
  file `0600`. The **acceptance ledger + `governed_turn_staging` store** (§2.4/§5) are
  supervisor-only `0700`.
- **`sidecar`, `executor`, and `desktop` are in NEITHER `brops-store` nor any owner** ⇒ no
  read/write/list of the published store or any key.
- IPC stays `AF_UNIX` + `SO_PEERCRED` allow-lists (unchanged).
- **Machine tests (run AS each OS principal — the 3b-1A login-user prover does NOT cover
  these):** for supervisor, recorder, signer, sidecar, executor, attempt
  create/overwrite/rename/unlink/chmod/symlink-attack + list + read in **both** `sup/` and
  `rec/`, asserting exactly: signer = **DENY all writes** (incl. chmod/symlink) in both, ALLOW
  list+read; recorder = ALLOW writes in `rec/`, **DENY all writes in `sup/`**, ALLOW read/list
  `sup/`; supervisor = ALLOW writes `sup/`, **DENY all writes in `rec/`**, ALLOW read/list
  `rec/`; sidecar+executor = DENY every op incl. list/read. Plus a **mode-regression guard**:
  `stat` store root/`sup/`/`rec/` MUST equal `2750` (setgid set, **group-write bit clear**) —
  fail closed if anyone re-introduces `2770`.

### 2.4 Bounded input ingress (P0-2, LOCKED) — a PRE-ACCEPT chunked upload to supervisor staging

The signed challenge carries only input **hashes**; before execution the exact **raw**
system/history/generation_config bytes must reach the supervisor's protected store. **The
sidecar is compromised-in-scope, so it uploads ONLY the three desktop-originated artifacts and
NEVER `policy_bundle`** (policy is a supervisor authority — see the policy note below). ONE
frozen Linux mechanism (Windows real-mode stays fail-closed): an **authenticated chunked upload
to a supervisor-owned staging store**, over a supervisor-owned `AF_UNIX` + `SO_PEERCRED`
channel (the sidecar is the untrusted sender; it can never *read* staging). Reuses
`brops_evidence_store.publish` (temp→fsync→verify size+sha256→`os.link`/`O_EXCL` create-if-
absent→`_verify_idempotent` divergent-refuse→fsync dir) for the final publish.

**No staging↔acceptance deadlock (P0-2):** staging is gated by the **verified signed
challenge**, NOT by an acceptance-ledger row (a row that, by §5, does not yet exist). The
supervisor keeps a durable, supervisor-only **`governed_turn_staging`** row (`0700`), distinct
from the acceptance ledger and carrying **no `execution_attempt_id` and no execution right**:
```sql
CREATE TABLE governed_turn_staging (
  install_id TEXT NOT NULL, request_nonce TEXT NOT NULL, challenge_handle TEXT NOT NULL, -- 64hex
  run_id TEXT NOT NULL, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
  system_sha256 TEXT NOT NULL, history_sha256 TEXT NOT NULL, generation_config_sha256 TEXT NOT NULL,
  system_handle TEXT, history_handle TEXT, generation_config_handle TEXT,   -- set as each publishes
  state TEXT NOT NULL,                    -- VERIFYING(transient) → UPLOADING → INPUTS_READY
  challenge_expires_at_ms INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce), UNIQUE (challenge_handle) );
-- Per-artifact upload session (durable, survives restart — P1-6 idempotency + restart recovery):
CREATE TABLE governed_turn_staging_session (
  staging_session_id TEXT PRIMARY KEY,   -- opaque
  challenge_handle TEXT NOT NULL, artifact TEXT NOT NULL,   -- system|history|generation_config
  declared_len INTEGER NOT NULL, declared_sha256 TEXT NOT NULL,
  next_seq INTEGER NOT NULL, running_sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL,
  tmp_path TEXT NOT NULL,                 -- the O_EXCL .tmp-*.part holding the accepted prefix
  published_handle TEXT,                  -- set on final publish
  UNIQUE (challenge_handle, artifact) );
-- Per-chunk digest (durable — answers "is this re-sent seq<next_seq chunk byte-identical?"):
CREATE TABLE governed_turn_staging_chunk (
  staging_session_id TEXT NOT NULL, seq INTEGER NOT NULL,
  chunk_sha256 TEXT NOT NULL, chunk_len INTEGER NOT NULL,
  PRIMARY KEY (staging_session_id, seq) );
```
**Idempotency + restart survival (P1-6, LOCKED):** all session cursors (`next_seq`,
`running_sha256`, `byte_count`, `tmp_path`) and per-chunk digests are **durable columns**, not
in-memory — so a supervisor restart mid-upload rehydrates the cursor + re-attaches the accepted-prefix
temp and the upload resumes rather than stranding; a lost reply after ANY committed
open/chunk/final is safely re-driven to the SAME handle/session/state (§4.10(a0/a/b/c)). A
`governed-turn-open` re-open with the byte-identical canonical challenge doc returns the existing
`challenge_handle` + current state; a differing doc under the same `(install_id,request_nonce)` ⇒
`retry_conflict`. An abandoned session is swept **without consuming the challenge nonce**.
Staging states: **`VERIFYING`** (uncommitted — happens inside **`brops.governed-turn-open.v1`**
(§4.10(a0)), where the sidecar delivers the EXACT signed challenge document bytes and the
supervisor decodes them, computes the handle, verifies the `sig`+registry+context, publishes the
challenge doc, and CAS-creates the row; **do NOT read the acceptance clock, do NOT consume the
challenge nonce**) → **`UPLOADING`** (the three `*_sha256` copied from the *verified*
challenge) → **`INPUTS_READY`** (all three published + re-hashed). Because the supervisor only
holds a `challenge_handle` after `governed-turn-open`, the challenge document **must** arrive over
the wire there (P0-2) — a handle alone can neither be re-hashed nor signature-verified. Frozen
protocol:
- **`brops.governed-staging-open.v1`** `{install_id, challenge_handle, request_nonce, artifact
  ∈ {system,history,generation_config}, declared_len, declared_sha256}` — sent **only after a
  successful `governed-turn-open.v1`**; the supervisor authenticates the peer UID, **requires an
  existing `UPLOADING` `governed_turn_staging` row** for `(install_id, request_nonce,
  challenge_handle)` (it does NOT create one — that was `governed-turn-open`; a missing row ⇒
  `no_staging_row`), requires `declared_sha256 == the verified challenge's committed *_sha256` for
  that artifact, rejects `declared_len` over the per-artifact ceiling, and returns an opaque
  `staging_session_id` bound to exactly `(challenge_handle, request_nonce, install_id,
  artifact)`; one in-flight session per (tuple, artifact) — a **byte-identical re-open returns the
  SAME session_id + current `next_seq`** (idempotent, P1-6), a conflicting re-open ⇒ `retry_conflict`.
  `policy_bundle` is **not** an accepted `artifact` value (refused).
- **`brops.governed-staging-chunk.v1`** `{staging_session_id, seq, bytes_b64}` — each chunk ≤
  **`MAX_STAGING_CHUNK_BYTES = 184320` decoded bytes (180 KiB, P1-4)**. Per session `{next_seq
  (0-based, strictly increasing), running_sha256, byte_count, O_EXCL temp fd}`: `seq != next_seq`
  ⇒ refuse (dup / gap / out-of-order in one predicate); `byte_count+len > declared_len` (or >
  ceiling) ⇒ refuse.
- **`brops.governed-staging-final.v1`** `{staging_session_id, seq==next_seq}` — fsync temp,
  assert `byte_count == declared_len` and `running_sha256 == declared_sha256`, compute
  `handle = digest`, and **require `handle == the challenge's committed `*_sha256`** for that
  artifact (else refuse — never publish bytes the challenge did not authorize); then atomic
  create-if-absent publish into `store/sup/` (divergent existing handle refused); record the
  handle on the staging row. When all three input handles are set, the row advances to
  `INPUTS_READY`.
- **Frame sizing proof (P1-4, LOCKED):** the IPC frame body cap is `MAX_FRAME_BYTES = 262144`
  (`brops_protocol.py`, body-only, compact JSON, base64url **no padding**). A `184320`-byte
  decoded chunk base64url-encodes to `4·⌈184320/3⌉ = 245760` bytes; plus the chunk-frame JSON
  envelope (`{"protocol":"brops.governed-staging-chunk.v1","staging_session_id":"…",
  "seq":<int>,"bytes_b64":"…"}`, ≤ ~211 bytes with a ≤128-char session id + ≤10-digit seq) =
  **≤ 245971 ≤ 262144** (≥ 16 KiB headroom). A 256 KiB decoded chunk would encode to `349526` +
  envelope > 262144 — **rejected**. The validator MUST check **BOTH** caps independently and
  fail-closed: (1) `decoded_len ≤ 184320`, **and** (2) the serialized frame ≤ `262144` (reuse
  `encode_frame`/`read_frame`). Tests: exact-max (184320 → accept), max+1 (184321 → refuse on
  the DECODED cap even though its frame still fits), oversized-serialized-frame (refuse on the
  FRAME cap before decode), and a `256 KiB`-decoded regression (refused by both).
- **Per-artifact ceilings (LOCKED):** `system ≤ 256 KiB`, `history ≤ 8 MiB`,
  `generation_config ≤ 64 KiB` (match the desktop's real `ai.rs` caps); `policy_bundle ≤ 64 KiB`
  applies only to the **supervisor-self-published** bundle (below), never to a sidecar upload.
  Total sidecar-uploaded request `≤ 8.5 MiB`.
- **Policy authority (P0-2, LOCKED — sidecar NEVER supplies policy):** the signed challenge
  commits `system_sha256`/`history_sha256`/`generation_config_sha256`/`request_sha256` and has
  **no** `policy_bundle_sha256` (§4.1) — so there is nothing to bind a sidecar-uploaded policy
  against, and policy must not traverse the untrusted sidecar. Instead the **supervisor
  self-resolves** `policy_id`/`policy_version`/`policy_bundle` bytes from **its own authoritative
  policy registry/config** (the real `brops_supervisor_attest.RunState.policy_bundle`, published
  via `store.publish`), binds `policy_bundle_sha256 = SHA256(raw bundle)` itself, and the
  isolated signer independently re-checks it against the operator-provisioned
  `BROPS_EXPECTED_POLICY_BUNDLE_SHA256` (`brops_receipt_signer` authorization policy). The
  desktop ships only a placeholder policy hash (used only on the never-active Trusted path).
- **Quota / expiry / crash:** per-`install_id` staging quota; a session/row **TTL bound to the
  signed challenge's own `challenge_expires_at_ms`** (NOT an acceptance window — none exists
  yet); startup + sweep unlink orphan `.tmp-*.part` and delete expired/abandoned staging rows
  **WITHOUT consuming the challenge nonce** — the desktop may re-issue against the same signed
  challenge until the challenge itself expires (this denies the sidecar a nonce-burning DoS). A
  partial temp is never linked to a handle; `read(handle)` re-verifies sha.
- **Isolation:** `governed_turn_staging` + staging blob root are `0700` supervisor-only;
  sidecar/executor have **no read**; the executor receives only post-publish read-only FDs (§4.7).
- **Ordering:** acceptance/lease/execution (§5) may proceed **only after** the staging row is
  `INPUTS_READY` (every declared input exists in the store and re-hashes to the challenge's
  committed digest) **and** the supervisor has self-published+bound the policy bundle.

---

## 3. THE ARTIFACT MATRIX (single normative source)

Every 3b-1B artifact, locked. A **handle** is always `SHA256(exact stored bytes)`, but "the
bytes" differ by kind: **signed-document** handles hash `JCS(exact signed document)`
(`{payload, sig}`), **raw-artifact** handles (system/history/generation_config/output/
policy) hash the exact **raw** bytes (see Appendix B). "Signed bytes" = detached Ed25519 over
`JCS(payload)` unless noted. A field has **one name, one type, one unit, one authority**
everywhere; §4 gives the exact key sets.

| # | Artifact / protocol | Producer | Signer / authority | Verifier / consumer | Time unit | Handle formula | Durable owner | Replay/idempotency key | Key cross-bindings |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `brops.governed-turn-challenge.v1` | desktop-UI **challenge-authority** | `desktop-challenge-authority` key (`challenge_key_id`) | supervisor §5; `LiveRunStateProvider` §7 | ms | `challenge_handle = SHA256(JCS({payload,sig}))` | supervisor store (published §6) | `request_nonce` (one-time) | binds `run_id`/`task_id`/context + `*_sha256` |
| 2 | `brops.challenge-key-registry.v1` | operator (root-signed) | challenge-**root** anchor (`root_key_id`) | supervisor §5; provider §7 | ms | `challenge_registry_handle = SHA256(JCS({payload,root_sig}))` | supervisor store | `registry_epoch` + `registry_hash` (anti-rollback) | `registry_hash = SHA256(JCS(payload))` (identity, ≠ handle) |
| 3 | acceptance-ledger row (§5) | supervisor | — (durable DB, not signed) | supervisor (recovery); provider (indirect) | ms | — | supervisor acceptance DB (`0700`) | `UNIQUE(install_id,request_nonce)`, `UNIQUE(challenge_handle)`, `UNIQUE(execution_attempt_id)` | holds lease_payload bytes + state |
| 4 | `brops.governed-turn-lease.v1` | supervisor **governed-turn lease issuer** | lease-issuer key | recorder; supervisor; provider §7 | ms | `lease_handle = SHA256(JCS({payload,signature}))` | supervisor store | `nonce` (lease) + `execution_attempt_id` | binds challenge #1 via `challenge_handle`/`challenge_key_id` + registry #2 + `challenge_accepted_at_ms` |
| 5 | `brops.governed-sign-request.v1` (attested evidence) | supervisor | **supervisor attestation** key (`supervisor_attestation_key_id`) over `JCS(evidence)` | isolated signer §6.1; desktop re-verifies the attestation bytes | ms | (transported, not stored) | — | `request_nonce` + `execution_attempt_id` | echoes #4/#6 handles; every `*_sha256` DERIVED by signer |
| 6 | `brops.governed-turn-execution-receipt.v1` | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7; `verify_governed_turn_receipt` | ms | `execution_receipt_handle = SHA256(JCS({payload,signature}))` | recorder store namespace (§2.3) | `receipt_id` (global unique) | `output_handle == output_sha256`; binds attempt/lease |
| 7 | `brops.governed-turn-containment.v1` | recorder runner | evidence event (evidence-recorder) | provider §7 | ms | `containment_evidence_sha256 = SHA256(JCS(artifact))` | recorder store namespace | attempt+lease | `contained==true`, closed `teardown_outcome` enum |
| 8 | evidence event / head (`bro_evidence`, REUSED) | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7 | **legacy epoch-seconds (never compared to ms)** | `event_hash` chain | evidence chain + **signer-owned `governed_evidence_head_floor`** (§7 P1-7) | signer-owned `head_sequence` vs durable `highest_sequence` high-water (BEGIN IMMEDIATE CAS) | head seq strictly-increasing per chain (structural) |
| 9 | `brops.governed-sign-result.v1` | isolated signer | signer key (the receipt envelope #12) | supervisor → bridge → desktop | ms | (transported) | — | `receipt_id` | tagged union `signed`/`refused`; echoes TRANSPORT-ONLY |
| 10 | `bridge.governed-turn-result.v1` (metadata-only, top-level `protocol` discriminator) + `brops.governed-turn-output-read.v1` pull | sidecar (transport/proxy) | — (carries #9/#12 signed bytes; output pulled) | **desktop verifies signatures + whole-output SHA256, NO store access** | ms | (transported; output via §4.10(f) pull) | — | `receipt_id` + `output_stream_id` | echoes TRANSPORT-ONLY; desktop equality-checks vs the verified signed envelope #12; output digest vs #12 |
| 11 | `brops.governed-turn-record.v1` | supervisor | **`governed-turn-recorder`** key (dedicated) | isolated signer's `LiveRunStateProvider` §7 | ms | `record_handle = SHA256(JCS({payload,signature}))` (also create-if-absent at `<run_id>__<execution_attempt_id>.json`) | supervisor store namespace | `(run_id, execution_attempt_id)` | binds ALL of #1,#2,#4 (via `lease_handle`),#6 (via `execution_receipt_handle`),#7,#8 + `challenge_accepted_at_ms` |
| 12 | governed **receipt envelope** (`brops.governed-receipt-envelope.v1`) | isolated signer | **isolated-signer** key (pinned by desktop) | **desktop** (§6.1 step 14) | ms | (inside `envelope_jcs_b64`) | — | `receipt_id` | binds `record_handle`/`lease_handle`/`execution_receipt_handle`/`request_nonce`/`execution_attempt_id`/head fields/attestation digest/`output_sha256`/`output_bytes` |

**Refusal is fail-closed everywhere:** any missing/extra key, wrong type/unit, handle
mismatch, signature failure, cross-binding inequality, or ledger conflict Blocks; nothing
renders.

---

## 4. Exact schemas (backing the matrix)

Strict decode for **every** artifact: exact required-key set, **unknown-field rejection**,
**duplicate-key rejection**, UTF-8, integers for `_ms`/epoch/counts, lowercase-64-hex for
`*_handle`/`*_hash`/`*_sha256`. `artifact_type`/`key_id` are injected by the signer and
echoed. Signed bytes = detached Ed25519 over `JCS(payload)` unless noted.

### 4.1 `brops.governed-turn-challenge.v1` (artifact #1)
```jsonc
{ "payload": {
    "protocol": "brops.governed-turn-challenge.v1",
    "challenge_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "task_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",
    "supervisor_id": "<string ≤128>",
    "request_nonce": "<string ≤128>",                         // one-time (Wave-3a nonce)
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>",
    "request_sha256": "<64hex>",                              // == sha256(JCS(request envelope))
    "requested_at_ms": <int>, "challenge_issued_at_ms": <int>,
    "challenge_expires_at_ms": <int> },
  "sig": "<b64url Ed25519 over JCS(payload), by the desktop-challenge-authority key>" }
```
The authority **builds** this from the trusted desktop DB (caller supplies only a
protected pending-challenge ID, never bytes; §5 P0-1 history); it does **not** carry
`challenge_accepted_at_ms` (the supervisor stamps that later — §1/§5).

### 4.2 `brops.challenge-key-registry.v1` (artifact #2)
```jsonc
{ "payload": {
    "artifact_type": "brops.challenge-key-registry.v1",
    "root_key_id": "<string ≤128>", "registry_epoch": <int>, "registry_issued_at_ms": <int>,
    "keys": [ { "challenge_key_id": "<string ≤128>", "public_key": "<b64url 32B→43 chars>",
                "valid_from_ms": <int>, "valid_to_ms": <int>, "key_epoch": <int>,
                "revoked": <bool>, "revoked_at_ms": <int epoch-ms> | null } ] },
  "root_sig": "<b64url Ed25519 over JCS(payload), by the pinned challenge-root>" }
```
**Key-entry revocation invariant (P1-3, LOCKED — the schema must be able to REPRESENT a
revoked key, not hardcode `false`/`null`):**
- `revoked` is a boolean; `revoked_at_ms` is an integer epoch-ms **or** `null`, discriminated:
  `revoked == false` ⇒ `revoked_at_ms` **MUST be `null`**; `revoked == true` ⇒ `revoked_at_ms`
  **MUST be an integer within the canonical ms range (§1)** and **`>= valid_from_ms`**.
- **Acceptance (§5)** refuses a key with `revoked == true && revoked_at_ms <=
  challenge_accepted_at_ms`.
- **Historical verification (§7)** accepts a record only when the bound key's
  `revoked_at_ms IS NULL OR revoked_at_ms > challenge_accepted_at_ms` (as-of-run).
- **Uniqueness + bounds:** duplicate `challenge_key_id` entries are **refused**; `keys` length
  ≤ **256**; the full registry document ≤ **256 KiB**.
- **Negative tests:** `revoked==true` with `null` time; `revoked==false` with a non-null
  time; `revoked_at_ms < valid_from_ms`; a seconds-not-ms value; duplicate key ids; and the
  boundary `revoked_at_ms == challenge_accepted_at_ms` (refused at acceptance).

Two distinct digests (protected-store law): `registry_hash = SHA256(JCS(payload))`
(fork/epoch identity, anti-rollback) vs `challenge_registry_handle = SHA256(JCS({payload,
root_sig}))` (exact stored document bytes, store lookup + record binding). `root_key_id`
selects a **binary-pinned challenge-root anchor baked into the supervisor config**
(root-owned; separate root + registry from the receipt keys); an unknown root is refused.

### 4.3 `brops.governed-turn-lease.v1` (artifact #4) — dedicated, closed
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-lease.v1",   // injected + echoed
    "key_id": "<lease-issuer key id>",                  // injected + echoed
    "schema": 1,
    "lease_id": "<string ≤128>", "nonce": "<string 16..128>",   // LEASE nonce (not lease_nonce)
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "agent_id": "<string ≤128>", "session_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "task_class": "governed-model-turn-v1",
    "allowed_capabilities": ["INVOKE_GOVERNED_MODEL"],  // CLOSED; exactly this
    "max_tool_calls": 0,
    "launcher_executable_sha256": "<64hex>",            // pinned setuid launcher digest
    "model_profile_id": "<string ≤128>",               // bound model endpoint/profile
    "lease_issued_at_ms": <int>, "lease_expires_at_ms": <int>,
    "challenge_accepted_at_ms": <int>,                  // supervisor-stamped (§5)
    "request_nonce": "<string ≤128>",                   // == challenge #1 request_nonce
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>"
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
- **Authority:** `ARTIFACT_AUTHORITY["brops.governed-turn-lease.v1"] = the governed-turn
  lease issuer` (the supervisor's lease-issuing authority; signs **leases only**, never
  receipts/records/evidence). `verify_artifact` refuses any other signer.
- **`issue_governed_turn_lease`:** the sole issuer; called **inside §5 step 4/6** with the
  accepted challenge, reserved `execution_attempt_id`, stamped `challenge_accepted_at_ms`, and
  resolved registry bindings. **Lease time is frozen, not issuer-chosen (P0-4, LOCKED):**
  `lease_issued_at_ms == challenge_accepted_at_ms` (equality — the exact lease payload bytes are
  persisted in the same acceptance tx, §5 step 4) and `lease_expires_at_ms == lease_issued_at_ms
  + LEASE_DURATION_MS` where **`LEASE_DURATION_MS = 210000` (210 s)** — one locked constant, not
  a signed input degree of freedom. `LEASE_DURATION_MS` covers the whole lease-scoped critical
  path: `~30000` post-acceptance pre-launch + `MIN_LAUNCH_REMAINING_MS 180000` (= `EXECUTION_TIMEOUT_MS`
  120000 + grace 5000 + teardown 10000 + post-exec signing to `completed_at_ms` 40000 = 175000
  worst-case + 5000 launch/scheduling slack) = **210000** exactly (§4.7 additive budget, §5 step 8a).
  It still nests inside the desktop `max_age_ms = 300000` freshness window (challenge TTL ≤30000 +
  210000 = 240000 < 300000, §1). It also enforces `requested_at_ms ≤ challenge_accepted_at_ms`; signs.
- **`validate_governed_turn_lease`:** `verify_artifact` (issuer) → strict-decode the exact
  key set → return fields. Refuses a missing/extra key, non-int `_ms`, `schema != 1`,
  `nonce` length ∉ [16,128], `allowed_capabilities != ["INVOKE_GOVERNED_MODEL"]`,
  `max_tool_calls != 0`. **Separate** from the base `validate_execution_lease` (which would
  reject the governed-turn keys as unexpected — a governed-turn lease presented to the base
  validator MUST be refused, tested).

### 4.4 `brops.governed-sign-request.v1` — attested evidence (artifact #5), COMPLETE schema
**NEW governed protocol (§2.2) — the ratified `brops.sign-request.v1` is untouched.**
`additionalProperties:false` on both objects; unknown-field + duplicate-key rejection;
`_ms` are integers; `*_handle`/`*_hash` lowercase-64-hex; frame ≤ 256 KiB; large inputs are
handles, never inline. There is **no `builder_id`** on the governed-model path (no builder
authority) — only `executor_id` + `runner_id`.
```jsonc
{ "protocol": "brops.governed-sign-request.v1",
  "attestation": {
    "attestation_protocol": "brops.run-attestation.v1",
    "supervisor_key_id": "<string ≤128>",
    "sig": "<b64url no-pad, 86 chars: Ed25519 over JCS(evidence)>" },
  "evidence": {
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "task_id": "<string ≤128>", "request_nonce": "<string ≤128>", "receipt_id": "<string ≤128>",
    "decision": "completed",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "executor_id": "<string ≤128>", "runner_id": "<string ≤128>",
    "policy_id": "<string ≤128>", "policy_version": "<string ≤128>",
    "requested_at_ms": <int>, "completed_at_ms": <int>, "challenge_accepted_at_ms": <int>,
    "system_handle": "<64hex>", "history_handle": "<64hex>", "generation_config_handle": "<64hex>",
    "output_handle": "<64hex>", "containment_evidence_handle": "<64hex>", "policy_bundle_handle": "<64hex>",
    "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } }
```
`evidence` is authoritative ONLY because `attestation.sig` covers `JCS(evidence)`; every
`*_handle`/`*_sha256` is **DERIVED by the signer** from the store bytes, never trusted from
the wire. Malformed/oversize ⇒ `refused` (§4.5).

### 4.5 `brops.governed-sign-result.v1` — (artifact #9), COMPLETE tagged union
**NEW governed protocol (§2.2) — the ratified `brops.sign-result.v1` is untouched.**
`additionalProperties:false` per member; unknown/duplicate-key rejection; frame ≤ 64 KiB
(**machine-checked, P1-6:** worst-case signed body = `envelope_jcs_b64 ≤ 2848` +
`attestation_evidence_jcs_b64 ≤ 4664` + two 86-char sigs + echoes ≈ **9865 ≤ 65536** — cannot
exceed 64 KiB at full schema max).
```jsonc
// status == "signed":
{ "protocol": "brops.governed-sign-result.v1", "status": "signed",
  "receipt_id": "<string ≤128>",
  "envelope_jcs_b64": "<b64url ≤ 2848 bytes>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
  // ── TRANSPORT-ONLY echoes (desktop equality-checks against verified authority) ──
  "task_id": "<string ≤128>", "challenge_accepted_at_ms": <int>,
  "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
  "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
  "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
  "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
  "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" }
// status == "refused":
{ "protocol": "brops.governed-sign-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<enum>" }
```
**The CLOSED governed refusal-reason enum `GOVERNED_REFUSAL_REASONS` (P1-4, LOCKED — the single
union; SEPARATE from the frozen 12-value `brops.sign-result.v1` enum, which is untouched):** the
ratified 12 (`attestation_invalid, not_completed, run_binding_invalid, nonce_mismatch,
handle_missing, hash_mismatch, policy_mismatch, containment_missing, identity_denied,
timestamp_invalid, oversize, malformed`) + the governed additions (`challenge_replay,
acceptance_conflict, lease_not_ready, output_oversize, output_timeout, evidence_fork, lease_expired,
challenge_invalidated, retry_conflict, stream_unknown, stream_expired, stream_binding_mismatch,
seq_out_of_range`). The previously-prose-only reasons (`evidence_fork` from §7, `lease_expired`/
`EXPIRED` from the §7 lease-time invariants, acceptance-time `challenge_invalidated`, idempotency
`retry_conflict`, output-stream `stream_expired`/`stream_binding_mismatch`) are now closed members —
no reason is prose-only. (The §4.10 a0/a/b/c internal supervisor↔sidecar producer codes —
`peer_denied`, `noncanonical`, `session_unknown`, `seq_mismatch`, `oversize_chunk`, … — live in
their own per-message reply schemas; the desktop-facing relays carry the `GOVERNED_REFUSAL_REASONS`
union per the relay-superset rule below.) A `signed` result REQUIRES both `envelope_jcs_b64` and
`signature_b64`; anything else ⇒ the desktop Blocks.

**Relay-superset rule (P1-4, LOCKED):** every bridge/relay reason enum — §4.6
`bridge.governed-turn-result.v1.error.reason` and §4.10(e) `brops.governed-turn-result.v1.reason`,
and the bridge output-read `error.reason` (§4.10(f)) — is the **literal enumerated
`GOVERNED_REFUSAL_REASONS` union** (or a declared superset), **never** an inferred "mirrors §4.5". A
staging/open/output-read producer reason that must reach the desktop through the bridge therefore
always has a representable code. No prose-only reason exists outside a closed schema.

### 4.6 `bridge.governed-turn-result.v1` — COMPLETE metadata-only parent (artifact #10)
**NEW bridge protocol (§2.2, renamed from the P0-1-collided `bridge.governed-result.v1`) — the
ratified `bridge.result` is untouched.** This is the **full outer object**, NOT the inner receipt
alone. **Discriminator (P0-1, CORRECTED):** it carries an explicit **top-level `"protocol"`
const** in its `required` set; the frozen `bridge.result` (`additionalProperties:false`, no
`protocol` key) rejects it (unknown top-level key) and this schema rejects a `bridge.result`
(missing required `protocol`). Do **not** use `receipt.envelope_jcs_b64` to discriminate — it is a
REQUIRED key of `bridge.result.receipt` too. `additionalProperties:false` on both objects;
`receipt` non-null iff `ok==true`; `error` non-null iff `ok==false`.

**ALWAYS-STREAM output (P0-3 + P1-6, LOCKED) — output is NEVER inlined in this frame.** The
governed reply text does **not** ride an unauthenticated `bridge.result.result` string, and it is
**not** carried inline here (a full-schema inline frame provably OVERFLOWS `262144` — output_b64
at even 128 KiB plus the co-resident `containment_evidence_b64 ≤ 65536` + `evidence[]` +
envelope/attestation reaches ~266707 > 262144). Instead the summary is **metadata-only** and the
exact bytes are pulled via the §4.10(f) `brops.governed-turn-output-read.v1` request/response loop.
Removing inline output drops this frame's worst case to **≈9.9 KiB** (§4.10 frame-fit proof).
```jsonc
{ "protocol": "bridge.governed-turn-result.v1",   // REQUIRED top-level discriminator (P0-1)
  "ok": <bool>,
  "output_stream_id": "<43-char base64url capability §4.10(f)> | null",     // non-null iff ok==true; drives the §4.10(f) pull
  "receipt": {                                     // non-null iff ok==true; ALL fields TRANSPORT-ONLY
    "task_id": "<string ≤128>", "status": "<string ≤64>", "exit_code": <int> | null,
    "evidence": ["<string ≤256>", ...],           // ≤ 64 entries (maxItems 64, each maxLength 256)
    "envelope_jcs_b64": "<b64url, ≤ 2848 bytes>", "signature_b64": "<b64url 86>",
    "containment_evidence_b64": "<b64url ≤ 65536 bytes>" | null,
    "attestation_evidence_jcs_b64": "<b64url, ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
    "supervisor_attestation_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "challenge_accepted_at_ms": <int>,
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "output_sha256": "<64hex>", "output_bytes": <int 0..8388608>,
    "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } | null,
  "error": { "reason": "<enum ∈ GOVERNED_REFUSAL_REASONS, §4.5>", "receipt_id": "<string ≤128>" | null } | null }
```
**Exact frame-fit (P1-6, machine-checked):** every b64 field has a frozen **encoded-byte**
`maxLength` — `envelope_jcs_b64 ≤ 2848` (= `4·⌈2135/3⌉`, the §4.9 payload at schema max),
`attestation_evidence_jcs_b64 ≤ 4664` (= `4·⌈3498/3⌉`, the §4.4 evidence at schema max),
`containment_evidence_b64 ≤ 65536`, `evidence[]` `maxItems 64 × maxLength 256`. A generated
maximum-size compact-JSON instance MUST assert `len(encoded_frame_body) ≤ MAX_FRAME_BYTES =
262144` in CI (worst case ≈ 92 KiB with containment+evidence at max; ≈ 9.9 KiB typical). No
approximate "≈" proof; the test constructs the literal maximum.

**Output binding (P0-3, LOCKED).** The desktop obtains the exact output bytes by driving the
§4.10(f) pull loop **through the sidecar** and reassembling into a bounded ≤ 8 MiB buffer, then —
**before any normalization/render and OUTSIDE any DB transaction** — asserts `len(bytes) ==
envelope.output_bytes` (length gate) and `SHA256(bytes) == envelope.output_sha256` (digest gate,
raw bytes — **no trim/NFC/NFKC/CRLF/lossy decode**); only then strict-UTF8 decode for UI display
(invalid UTF-8 ⇒ Block, unless the product explicitly supports binary output); render only after
the `BEGIN IMMEDIATE` tx commits (§6.1 step 14). Negative tests: substitution, one-byte mutation,
truncation, appended byte, Unicode-normalization (NFC/NFKC), CRLF conversion, invalid-UTF8→U+FFFD,
wrong-length, and a tampered/mis-ordered/short/replayed-stream chunk (each MUST Block).

**Authority rule (LOCKED, P0-3) — the desktop verifies SIGNATURES, it does NOT read the
protected store.** The protected store is on the engine host, group-`brops-store`, and is
**not readable by the desktop principal** (§2.3); the desktop may also be a different runtime/
host. So the **deep protected-store verification** (fetch record/lease/receipt/challenge/
registry/containment/head **by handle**, re-hash, re-verify each signature, cross-check
bindings) is performed by the **isolated signer's `LiveRunStateProvider`** (§6.1 step 11, §7),
**not** by the desktop. The isolated signer then emits a **signed receipt envelope** (#12,
§4.9) that binds `record_handle`/`lease_handle`/`execution_receipt_handle`/`request_nonce`/
`execution_attempt_id`/head fields/attestation digest. The **desktop** takes authority ONLY
from: (a) the **isolated-signer receipt-envelope signature** (Ed25519 over `envelope_jcs_b64`,
pinned key); (b) the **supervisor-attestation signature** over `attestation_evidence_jcs_b64`
(re-verified against the manifest `supervisor_attestation` key) and its equality to the
envelope; (c) `request_nonce` one-time consume; (d) `receipt_id` global uniqueness; (e)
receipt-freshness (`_ms`); then it **equality-checks** every bridge/sign-result echo against
the verified envelope. **A bare bridge/sign-result echo never authorizes anything; the
desktop never dereferences a store handle;** a mismatch Blocks.

### 4.7 `brops.governed-turn-execution-receipt.v1` (artifact #6) — COMPLETE schema
Recorder-runner signed (**evidence-recorder** key); `additionalProperties:false`; unknown/
duplicate-key rejection; verified by **`verify_governed_turn_receipt`** (NOT
`verify_passing_receipt` — that CRLF-normalizes). Signed bytes = detached Ed25519 over
`JCS(payload)`; `execution_receipt_handle = SHA256(JCS({payload,signature}))`.
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-execution-receipt.v1",   // injected + echoed
    "key_id": "<evidence-recorder key id>",                         // injected + echoed
    "receipt_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "runner_id": "<string ≤128>", "executor_id": "<string ≤128>",
    "exit_code": 0,                                                 // MUST be integer 0
    "contained": true,                                             // MUST be true
    "output_handle": "<64hex>",                                    // == output_sha256
    "output_sha256": "<64hex>",                                    // SHA256(exact binary reply bytes)
    "output_bytes": <int>,                                        // 0 ≤ n ≤ 8388608 (8 MiB, P1-6)
    "started_at_ms": <int>, "finished_at_ms": <int> },            // started ≤ finished
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
- `output_handle == output_sha256 == SHA256(exact binary reply bytes)` (**no decode/trim/CRLF
  normalization**); `output_bytes` equals the accepted byte count; `started_at_ms ≤
  finished_at_ms`. Authority: `ARTIFACT_AUTHORITY[...] = evidence-recorder`; any other signer
  refused.

**Input FDs + OUTPUT BOUND (P1-6, canonical):** FDs `3`/`4`/`5` are **read-only regular-file
descriptors** to the exact content-addressed `system`/`history`/`generation_config` bytes (no
length prefix); FD `6` is the write-only output pipe. The launcher validates each input FD is
`O_RDONLY`, `S_ISREG`, offset 0, size ≤ the per-artifact ceiling (system ≤256 KiB, history
≤8 MiB, generation_config ≤64 KiB), backed by a `brops-store` store inode; it closes every
other FD, validates the pinned `launcher_executable_sha256` + fixed caller/target UID, drops
caps, then `setuid(executor)+exec`. The executor reads each input to EOF and writes only its
reply. **The output channel is BOUNDED:**
- **`MAX_OUTPUT_BYTES = 8 MiB`** (8388608; matches the desktop's real `MAX_ASSISTANT_OUTPUT`/
  `MAX_HTTP_BODY`, `ai.rs`). The recorder reads FD 6 into a **bounded** buffer with a hard
  ceiling; on the (`MAX_OUTPUT_BYTES + 1`)-th byte it **stops reading, terminates the executor
  (SIGKILL) + tears down its cgroup/process-group**, produces **no** receipt/evidence/terminal
  record, and returns refused reason **`output_oversize`** (§4.5).
- **`EXECUTION_TIMEOUT_MS = 120000` (120 s, LOCKED, P1-6).** Chosen so the **entire** pipeline
  nests inside the desktop freshness window `max_age_ms = 300000` (`receipt_store.rs`): worst
  case cross-host skew 60000 + pre-execution (challenge/ingress/acceptance/lease) 30000 +
  execution 120000 + post-execution signing (recorder receipt + record + isolated-signer deep
  verify + envelope + bridge + desktop tx) 40000 = 250000 < 300000 (50000 ms slack). It matches
  the desktop's shipping per-model-call bound (120 s, `ai.rs`); the 180 s streaming deadline is
  **NOT** reused (180000 + skew + pre + post would breach 300000). **Clock discipline:** the
  elapsed timeout is measured with a **MONOTONIC** clock (immune to NTP steps); **only** signed
  `_ms` fields use the wall clock. **Window nesting (LOCKED):** the governed challenge TTL
  `challenge_expires_at_ms − challenge_issued_at_ms ≤ 30000`; the governed lease window
  `lease_expires_at_ms − lease_issued_at_ms ≥ EXECUTION_TIMEOUT_MS + teardown`; and engine↔desktop
  wall-clock skew MUST be bounded ≤ 60000 (shared NTP) since the desktop stale check has no skew
  allowance on the old side. On timeout the recorder discards the buffer, produces no
  receipt/record, and returns **`output_timeout`**.
- **Termination + teardown (LOCKED, recorder-owned):** on `elapsed_monotonic ≥ EXECUTION_TIMEOUT_MS`
  (or the oversize path), **immediate `SIGKILL`** to the whole process-group / `cgroup.kill` (NOT
  SIGTERM→SIGKILL — the executor holds no key/store and only the FD-6 pipe already being
  discarded, and is treated as potentially hostile); **termination grace = 5000 ms** for the
  kernel to reap the process group; **cgroup teardown deadline = 10000 ms** to confirm
  `cgroup.procs` empty and `rmdir` the leaf cgroup. Success ⇒ `teardown_outcome = "contained"`
  (only this + `contained:true` yields a record, §4.7b); not-empty by the deadline ⇒
  `orphan-quarantined`/`timed-out` ⇒ **no accepted record**. **Budget model (P1-5, canonical —
  ADDITIVE):** the launch-gate remaining requirement is `EXECUTION_TIMEOUT_MS(120000) +
  grace(5000) + teardown(10000) + post_exec_signing_reserve(40000) = 175000` worst-case critical
  path (grace + teardown are **added to**, NOT absorbed by, the 40000 signing reserve); the gate
  threshold `MIN_LAUNCH_REMAINING_MS = 180000` adds 5000 launch/scheduling slack, and
  `LEASE_DURATION_MS = 210000 = ~30000 pre-launch + 180000` (§4.3, §5 step 8a).
- **Backpressure:** the recorder reads the pipe continuously into the bounded buffer so a slow
  reader cannot be exploited; a full buffer triggers the `output_oversize` path (never
  unbounded growth).
- **`output_handle`/`output_sha256` are computed ONLY over a COMPLETE, accepted byte stream**
  (executor exited `0`, within `MAX_OUTPUT_BYTES`, before timeout, `contained==true`). A
  truncated/partial output (crash/timeout/oversize) yields **no** published output artifact and
  **no** signed receipt — fail-closed.
- **Partial-output cleanup:** the recorder's bounded buffer/temp is discarded (never published)
  on any oversize/timeout/crash; a partial temp is never linked to a handle.
- **Negative tests:** `output_bytes` at `MAX-1` (accept), `MAX` (accept), `MAX+1`
  (`output_oversize`, no receipt), timeout mid-stream (`output_timeout`, no receipt), and a
  partial-write crash (no receipt, ledger → `RECOVERY_REQUIRED`/`BLOCKED`).

### 4.7b `brops.governed-turn-containment.v1` (artifact #7) — COMPLETE schema
Recorder-measured firsthand; `additionalProperties:false`; recorded as a containment-confirmed
`bro_evidence` event whose `payload_hash == containment_evidence_sha256`.
```jsonc
{ "artifact_type": "brops.governed-turn-containment.v1",
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
  "runner_id": "<string ≤128>", "executor_id": "<string ≤128>",
  "cgroup_id": "<string ≤256>", "process_group_id": "<string ≤64>",   // both always present
  "contained": true,                                                  // MUST be true for an accepted record
  "teardown_outcome": "contained",                                    // closed enum ↓
  "measured_at_ms": <int> }
```
`teardown_outcome` closed enum = `contained | orphan-quarantined | timed-out | failed`; only
`contained` (with `contained: true`) yields an accepted record. Canonical bytes = `JCS(artifact)`;
**`containment_evidence_sha256 = SHA256(JCS(artifact))`** (a JCS-document digest — the `_sha256`
suffix is retained for continuity but it hashes the JCS artifact, not raw bytes; see Appendix B).

### 4.8 `brops.governed-turn-record.v1` (artifact #11) — the ONLY terminal authority, COMPLETE schema
Signed by the dedicated **`governed-turn-recorder`** key; `additionalProperties:false`;
unknown/duplicate-key rejection; written atomically (create-if-absent, §6) into `store/sup/`
and also mirrored at `<run_id>__<execution_attempt_id>.json`. Signed bytes = detached Ed25519
over `JCS(payload)`; **`record_handle = SHA256(JCS({payload,signature}))`**.
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",   // injected + echoed
    "key_id": "<governed-turn-recorder key id>",         // injected + echoed
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "agent_id": "<string ≤128>", "session_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "executor_id": "<string ≤128>", "runner_id": "<string ≤128>",
    // lease binding
    "lease_id": "<string ≤128>", "lease_nonce": "<string 16..128>",   // == the lease's `nonce`
    "lease_issued_at_ms": <int>, "lease_expires_at_ms": <int>, "lease_handle": "<64hex>",
    // request binding
    "request_nonce": "<string ≤128>",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>", "generation_config_sha256": "<64hex>",
    "requested_at_ms": <int>, "request_sha256": "<64hex>",
    // challenge binding (challenge_accepted_at_ms is SUPERVISOR-stamped, not in the challenge)
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_issued_at_ms": <int>, "challenge_expires_at_ms": <int>, "challenge_accepted_at_ms": <int>,
    // registry snapshot binding
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    // output / policy / containment / receipt
    "output_sha256": "<64hex>", "output_bytes": <int>,
    "policy_id": "<string ≤128>", "policy_version": "<string ≤128>", "policy_bundle_sha256": "<64hex>",
    "containment_evidence_sha256": "<64hex>", "containment_event_id": "<string ≤128>",
    "receipt_id": "<string ≤128>", "execution_receipt_handle": "<64hex>",
    // evidence head (bro_evidence is LEGACY epoch-seconds; only these structural fields cross in)
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "completed_at_ms": <int> },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
Authority: `ARTIFACT_AUTHORITY[...] = governed-turn-recorder` (§8); any other signer refused.
`lease_handle`/`execution_receipt_handle` are the exact signed-document handles (§4.3/§4.7) so
the verifier fetches + re-verifies the exact lease/receipt documents (§7). `evidence_*` are the
**structural** bindings of the legacy epoch-seconds `bro_evidence` head (§1) — never compared
to an ms window.

### 4.9 `brops.governed-receipt-envelope.v1` (artifact #12) — the isolated-signer's signed envelope, COMPLETE schema
The isolated signer, **after** its `LiveRunStateProvider` deep-verifies the protected chain
(§7), constructs + signs this envelope; it is the ONLY thing the desktop trusts (the desktop
has no store access, §4.6/§2.3). `additionalProperties:false`; signed bytes = detached Ed25519
over `JCS(payload)` under the **isolated-signer key pinned by the desktop manifest**;
`envelope_jcs_b64 = base64url(JCS(payload))`, `signature_b64 = base64url(signature)` (both ride
`brops.governed-sign-result.v1` §4.5 + `bridge.governed-turn-result.v1` §4.6).
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-receipt-envelope.v1",
    "key_id": "<isolated-signer key id, pinned by the desktop manifest>",
    "receipt_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",
    "request_nonce": "<string ≤128>", "request_sha256": "<64hex>",
    "record_handle": "<64hex>", "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "output_sha256": "<64hex>", "output_bytes": <int>,
    "challenge_accepted_at_ms": <int>, "completed_at_ms": <int>,
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "supervisor_attestation_key_id": "<string ≤128>",
    "attestation_evidence_sha256": "<64hex>" },   // SHA256(the JCS(governed-sign-request evidence) the supervisor attested
  "signature": "<detached Ed25519 over JCS(payload), isolated-signer key>" }
```
The desktop (§6.1 step 14) verifies this signature under the pinned isolated-signer key, then
verifies the supervisor attestation and confirms `attestation_evidence_sha256` matches, then
consumes `request_nonce` + checks `receipt_id` uniqueness + freshness, then equality-checks the
bridge echoes — all without any protected-store access.

### 4.10 Control-plane protocols (P1-5) — staging, execute-trigger, supervisor→sidecar result

Every named governed protocol has ONE complete normative schema, a `protocol` const
discriminator, a producer, a consumer, and strict rejection of any v1 document (and vice
versa). `additionalProperties:false` + unknown/duplicate-key rejection everywhere; requests are
schema-validated **before** any side effect. These complete the challenge-submission open (P0-2), the two names that previously had no
§4 schema (`brops.governed-turn-result.v1`, `brops.governed-evidence-request.v1`), the three
staging messages, and the pull-based output read (P0-3) that were field-lists only.

**(a0) `brops.governed-turn-open.v1`** — sidecar→supervisor, the **signed-challenge submission
(P0-2)**. Reply `brops.governed-turn-open-result.v1`. Frame ≤ **8 KiB** (the challenge document
JCS is small — ≤ ~2.3 KiB base64url, far under this). This is the FIRST governed message; without
it the supervisor has only a `challenge_handle` and cannot verify a signature or recompute the
handle (verify-by-handle-before-possession is impossible).
```jsonc
// request:
{ "protocol": "brops.governed-turn-open.v1", "install_id": "<string ≤128>",
  "request_nonce": "<string ≤128>",
  "challenge_doc_b64": "<b64url of the EXACT signed challenge document JCS({payload,sig}), decoded ≤ 4096>" }
// reply (opened): { "protocol": "brops.governed-turn-open-result.v1", "status": "opened", "challenge_handle": "<64hex>" }
// reply (refused): { "protocol": "brops.governed-turn-open-result.v1", "status": "refused", "reason": "<enum>" }
```
**OPEN-TIME PRELIMINARY verification (P0-3, LOCKED — this is NOT the final §7 predicate; the
authoritative as-of-acceptance predicate runs at §5/§7 because `challenge_accepted_at_ms` does not
exist yet at open).** The supervisor MUST, in order: authenticate the peer UID; base64url-decode
`challenge_doc_b64`; strict UTF-8 JSON decode of the §4.1 `{payload,sig}` (unknown-field +
**duplicate-key** rejection; `decoded ≤ 4096`); **canonicality gate (P0-3, LOCKED):** require
`decoded_document_bytes == canonical_bytes({payload, sig})` (`bro_signature.canonical_bytes` — JCS)
else refuse `noncanonical` — so the transported bytes, the computed handle, and the stored document
can never diverge; `challenge_handle = SHA256(decoded_document_bytes)` (now identical to
`SHA256(JCS({payload,sig}))`); resolve the current accepted root-signed
`brops.challenge-key-registry.v1` **from its own supervisor state** (§4.2 pinned root anchor +
registry floor — the registry is NEVER supplied by the sidecar); verify `root_sig`, key presence,
and the challenge `sig` under the resolved snapshot key, with key validity **as of
`challenge_issued_at_ms`** (`valid_from_ms ≤ challenge_issued_at_ms ≤ valid_to_ms`, `revoked_at_ms
IS NULL OR revoked_at_ms > challenge_issued_at_ms`); verify `run_id`/`task_id`/`install_id`/window
context + recompute `request_sha256`; **atomically create-if-absent publish the EXACT
`decoded_document_bytes`** into `store/sup/` (the §6 step-1 publish); CAS-create the
`governed_turn_staging` row `absent→VERIFYING→UPLOADING` keyed
`UNIQUE(install_id,request_nonce)`+`UNIQUE(challenge_handle)`; return `challenge_handle`. **No clock
read, no nonce consume, no execution right — this only *admits* the turn to upload; the binding
authority is the acceptance-time re-verification (§5).** Refused reasons: `peer_denied, doc_oversize,
malformed, noncanonical, handle_mismatch, registry_unknown, key_invalid, sig_invalid,
context_mismatch, retry_conflict` (idempotent re-open, P1-6). The untrusted sidecar transports bytes
only; the challenge signature + supervisor-resolved registry are the authority.

**(a) `brops.governed-staging-open.v1`** — sidecar→supervisor (§2.4), **only after a successful
`governed-turn-open.v1`** (requires the `UPLOADING` `governed_turn_staging` row). Reply
`brops.governed-staging-open-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request:
{ "protocol": "brops.governed-staging-open.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>",
  "artifact": "system" | "history" | "generation_config",     // policy_bundle REFUSED
  "declared_len": <int 0..8388608>, "declared_sha256": "<64hex>" }
// reply (opened):
{ "protocol": "brops.governed-staging-open-result.v1", "status": "opened",
  "staging_session_id": "<opaque string ≤128>", "next_seq": 0 }
// reply (refused): { "protocol": "brops.governed-staging-open-result.v1", "status": "refused", "reason": "<enum>" }
```
Refused reasons: `peer_denied, no_staging_row, artifact_invalid, digest_mismatch, oversize,
retry_conflict, malformed`. `declared_sha256` MUST equal the verified challenge's committed
`*_sha256` for `artifact`; `declared_len` ≤ that artifact's ceiling (§2.4). **Idempotent re-open
(P1-6, LOCKED):** a re-open with the SAME `(challenge_handle, request_nonce, install_id, artifact,
declared_len, declared_sha256)` returns the **SAME** `staging_session_id` + the current `next_seq`
(re-emitting the original `opened` reply — a lost reply is safely retried); a re-open of the same
`(tuple, artifact)` with any differing `declared_len`/`declared_sha256` ⇒ `retry_conflict`.

**(b) `brops.governed-staging-chunk.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-chunk-result.v1`. Frame ≤ `MAX_FRAME_BYTES = 262144`.
```jsonc
// request:
{ "protocol": "brops.governed-staging-chunk.v1", "staging_session_id": "<string ≤128>",
  "seq": <int ≥0>, "bytes_b64": "<b64url, decoded ≤ 184320 (P1-4)>" }
// reply: { "protocol": "brops.governed-staging-chunk-result.v1", "status": "ack" | "refused",
//          "next_seq": <int>, "reason": "<enum>" | null }
```
Refused reasons: `session_unknown, seq_mismatch, retry_conflict, oversize_chunk, oversize_frame,
over_declared, malformed`. Validator enforces **both** `len(decode(bytes_b64)) ≤ 184320` **and**
serialized frame ≤ 262144 (§2.4 P1-4). **Idempotent chunk (P1-6, LOCKED — the `seq != next_seq`
predicate is split three ways):** `seq == next_seq` ⇒ append once (persist the per-chunk
`(seq → chunk_sha256, chunk_len)`), advance `next_seq`, ACK; `seq < next_seq` **and** the bytes are
byte-identical to the persisted per-chunk digest at that `seq` ⇒ idempotent ACK + current `next_seq`
(NO re-append; `byte_count`/`running_sha256` unchanged — a lost ACK is safely retried); `seq <
next_seq` **and** the bytes differ ⇒ `retry_conflict`; `seq > next_seq` ⇒ `seq_mismatch` (a true gap).

**(c) `brops.governed-staging-final.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-final-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request: { "protocol": "brops.governed-staging-final.v1", "staging_session_id": "<string ≤128>", "seq": <int ≥0> }
// reply (published):
{ "protocol": "brops.governed-staging-final-result.v1", "status": "published",
  "artifact": "system" | "history" | "generation_config", "handle": "<64hex>",
  "inputs_ready": <bool> }          // true once all three inputs are published + re-hashed
// reply (refused): { ..., "status": "refused", "reason": "<enum>" }
```
Refused reasons: `session_unknown, seq_mismatch, len_mismatch, sha_mismatch, handle_not_challenge,
publish_divergent, retry_conflict, malformed`. Requires `handle == the challenge's committed
*_sha256`. **Idempotent final (P1-6, LOCKED):** the first valid final publishes (reusing the
already-idempotent `os.link`/`O_EXCL` create-if-absent, `brops_evidence_store.publish`) and records
the `*_handle` + advances `inputs_ready`; an identical retry re-returns the SAME
`{status:"published", artifact, handle, inputs_ready}` from the recorded `*_handle` (a lost reply is
safe); a conflicting retry (session diverged / different declared digest) ⇒ `retry_conflict` /
`publish_divergent`.

**(d) `brops.governed-evidence-request.v1`** — sidecar→supervisor **execute/finalize trigger**
(the message that, once the staging row is `INPUTS_READY`, asks the supervisor to run the
governed turn and produce the signed result). Replaces the mis-named use of the v1
`brops.evidence-request.v1` const on the governed path. Reply is `brops.governed-turn-result.v1` (e).
Frame ≤ 4 KiB.
```jsonc
{ "protocol": "brops.governed-evidence-request.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>" }
```
The supervisor authenticates the peer UID, requires the `INPUTS_READY` staging row for
`(install_id, request_nonce, challenge_handle)`, then drives §5 acceptance→lease→execution→
record and the isolated-signer flow (§6.1). It carries **no** `execution_attempt_id` (the
supervisor reserves it, §5) and grants no authority by itself.

**(e) `brops.governed-turn-result.v1`** — supervisor→sidecar **COMPLETE metadata-only tagged
union** (a NEW name; the existing `GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` in
`brops_supervisor_service.py` is FROZEN with its shipped shape — §2.2 P0-1). The sidecar re-frames
it into `bridge.governed-turn-result.v1` (§4.6). Frame ≤ `MAX_FRAME_BYTES = 262144`; **the output
is NEVER inlined** — the summary carries only `output_bytes`/`output_sha256`/`output_stream_id` and
the output is pulled via §4.10(f). All non-signature fields TRANSPORT-ONLY.
```jsonc
// status == "signed":
{ "protocol": "brops.governed-turn-result.v1", "status": "signed", "receipt_id": "<string ≤128>",
  "output_stream_id": "<43-char base64url capability, §4.10(f)>", "output_bytes": <int 0..8388608>, "output_sha256": "<64hex>",
  "envelope_jcs_b64": "<b64url ≤ 2848 bytes>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "containment_evidence_b64": "<b64url ≤ 65536 bytes>" | null,
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>" }
// status == "refused":
{ "protocol": "brops.governed-turn-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<enum ∈ GOVERNED_REFUSAL_REASONS, §4.5>" }
```
A `signed` result REQUIRES `envelope_jcs_b64` + `signature_b64` + `output_stream_id`; anything
else ⇒ Block. The desktop's authority for the output is always the signed envelope's
`output_sha256`/`output_bytes`, applied to the §4.10(f)-reassembled bytes (§4.6/§7.1).

**(f) Output-read PULL (P0-2/P0-3) — the ONLY egress path, complete on BOTH hops.** The output is
NEVER pushed (the real `brops_socket` is one-request/one-response and the supervisor is a pure
responder; the real `engine_sidecar` reads ONE stdin request, writes ONE stdout result, exits).
The desktop therefore **drives a pull loop by re-invoking the sidecar once per chunk** (a fresh
one-shot subprocess each read); the sidecar is a **stateless proxy** that forwards exactly one
supervisor read and reframes the reply.

**Capability token (P0-2, LOCKED).** `output_stream_id` = **32 cryptographically-random bytes,
base64url no-pad, EXACTLY 43 chars** (256-bit) — an unguessable, non-enumerable capability. It is
generated server-side and bound in the durable `governed_output_streams` table (below) to
`(receipt_id, execution_attempt_id, output_handle, output_bytes, output_sha256)`; a client can
neither forge nor enumerate it (the SHA256 gate guarantees output *integrity*; the 256-bit token
guarantees cross-turn output *confidentiality* — the sidecar proxies **all** turns).

**Durable mapping (P0-2, LOCKED — supervisor-owned `0700` DB, survives restart):**
```sql
CREATE TABLE governed_output_streams (
  output_stream_id     TEXT PRIMARY KEY,          -- 43-char base64url, 256-bit
  receipt_id           TEXT NOT NULL UNIQUE,
  execution_attempt_id TEXT NOT NULL UNIQUE,
  output_handle        TEXT NOT NULL,             -- content-addressed store handle (store/rec)
  output_bytes         INTEGER NOT NULL,
  output_sha256        TEXT NOT NULL,
  created_at_ms        INTEGER NOT NULL,
  expires_at_ms        INTEGER NOT NULL );        -- created_at_ms + OUTPUT_STREAM_TTL_MS
```
The row is **durably committed BEFORE** the §4.10(e) result summary is returned; a supervisor
restart preserves it, and a `COMPLETED` retry returns the **same** `output_stream_id`. Each read
re-checks `output_handle`/length/hash and serves `store.read(output_handle)[seq·184320 …]` (the
supervisor has group read on `store/rec`, §2.3). **`OUTPUT_STREAM_TTL_MS = 360000`** (the desktop
`max_age_ms 300000` + `future_skew_ms 60000`, `receipt_store.rs`) — a stream must outlive the widest
window in which the desktop may still accept the receipt; after `expires_at_ms` the supervisor
returns `stream_expired`. No stream enumeration is ever exposed.

**Supervisor hop — `brops.governed-turn-output-read.v1`** (sidecar→supervisor, one-req/one-resp
`brops_socket`). Frame ≤ `MAX_FRAME_BYTES = 262144`.
```jsonc
// request:
{ "protocol": "brops.governed-turn-output-read.v1", "output_stream_id": "<43-char b64url>", "seq": <int 0..45> }
// reply (ok): { "protocol": "brops.governed-turn-output-read-result.v1", "ok": true,
//   "output_stream_id": "<same>", "seq": <same>,
//   "bytes_b64": "<b64url of output[seq·184320 : (seq+1)·184320], decoded ≤ 184320>", "eof": <bool>, "error": null }
// reply (refused): { "protocol": "brops.governed-turn-output-read-result.v1", "ok": false,
//   "output_stream_id": "<same or null>", "seq": <int or null>, "bytes_b64": null, "eof": null,
//   "error": { "reason": "<enum>" } }
```
Refused reasons: `stream_unknown, stream_expired, stream_binding_mismatch, seq_out_of_range, malformed`.

**Desktop hop — `bridge.governed-turn-output-read.v1`** (desktop→sidecar) + its
`bridge.governed-turn-output-read-result.v1` reply (P0-2 — the previously-missing bridge side).
Each is one stdin request / one stdout reply of a **fresh one-shot sidecar subprocess**, invoked by
a NEW Tauri command (`governed_turn_output_read`, registered in `lib.rs` `generate_handler!`,
mirroring `governed_engine`); a NEW `protocol`-keyed branch in `engine_sidecar` validates the bridge
request, forwards exactly ONE `brops.governed-turn-output-read.v1` to the supervisor socket,
validates the reply, reframes and exits. `bridge.task-request` is untouched.
```jsonc
// desktop→sidecar request:
{ "protocol": "bridge.governed-turn-output-read.v1", "output_stream_id": "<43-char b64url>", "seq": <int 0..45> }
// sidecar→desktop reply (ok):
{ "protocol": "bridge.governed-turn-output-read-result.v1", "ok": true, "output_stream_id": "<same>",
  "seq": <same>, "bytes_b64": "<b64url ≤ 245760>", "eof": <bool>, "error": null }
// sidecar→desktop reply (refused):
{ "protocol": "bridge.governed-turn-output-read-result.v1", "ok": false, "output_stream_id": "<same or null>",
  "seq": <int or null>, "bytes_b64": null, "eof": null, "error": { "reason": "<enum, superset of the supervisor's>" } }
```
Chunk size = **184320** decoded (= 245760 b64url + a small JSON envelope ≤ 262144). For an 8 MiB
output: `ceil(8388608 / 184320) = 46` chunks, **`seq` 0..45** (last chunk 94208 bytes, `eof=true`).
Reads are **idempotent**: the same `seq` always returns the exact same byte range (offset
`seq · 184320`); a lost reply is safely retried (no `next_seq` consume). The desktop reassembles all
chunks into a bounded ≤ 8 MiB buffer **outside any DB transaction** (never hold `BEGIN IMMEDIATE`
across the per-chunk subprocess/socket I/O — `receipt_store.rs::in_immediate_tx` rejects a nested
tx), then asserts `reassembled_len == envelope.output_bytes` **and** `SHA256(reassembled) ==
envelope.output_sha256` **before** any normalization/render (§7.1). The **signed envelope** is the
sole authority, so a tampered/re-ordered/dropped/cross-turn chunk fails the whole-output digest →
Block. Tests: exact-max chunk, `seq` out-of-range, `stream_expired` after TTL, `stream_binding_mismatch`
on a replayed other-turn token, supervisor-restart-mid-pull re-drives from the durable row,
`COMPLETED` retry returns the same token, idempotent re-read returns identical bytes, and a
1-byte-tampered chunk (whole-output SHA256 → Block).

**Routing/rejection (LOCKED + tested):** each control-plane message
is dispatched by its `protocol` const; a governed handler refuses any v1 `protocol` value and
each v1 handler refuses any `brops.governed-*` value — no shared schema file, enum, or
required-key list.

---

## 5. Durable supervisor acceptance — state machine + outbox (P0-2)

A database transaction **cannot** atomically include an external private-key signature and a
filesystem publish. Acceptance is therefore a **durable state machine with an outbox**, not a
single "issue-or-prepare" step.

**Acceptance ledger (supervisor-owned durable DB, `0700`):**
```sql
CREATE TABLE governed_turn_acceptance (
  install_id                     TEXT NOT NULL,
  request_nonce                  TEXT NOT NULL,
  challenge_handle               TEXT NOT NULL,   -- 64hex
  run_id                         TEXT NOT NULL,
  task_id                        TEXT NOT NULL,
  workspace_id                   TEXT NOT NULL,
  execution_attempt_id           TEXT NOT NULL,
  challenge_accepted_at_ms       INTEGER NOT NULL,
  challenge_registry_handle      TEXT NOT NULL,
  challenge_registry_hash        TEXT NOT NULL,
  challenge_registry_epoch       INTEGER NOT NULL,
  challenge_registry_root_key_id TEXT NOT NULL,
  lease_payload_sha256           TEXT NOT NULL,   -- sha256 of the EXACT canonical lease payload bytes
  lease_payload_bytes            BLOB NOT NULL,    -- the exact JCS(payload) to be signed
  lease_handle                   TEXT,             -- 64hex, set at LEASE_READY
  state                          TEXT NOT NULL,    -- enum below
  execution_started_marker       TEXT,
  cgroup_id                      TEXT,
  process_group_id               TEXT,
  terminal_record_handle         TEXT,
  failure_reason                 TEXT,
  created_at_ms                  INTEGER NOT NULL,
  updated_at_ms                  INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce),
  UNIQUE (challenge_handle),
  UNIQUE (execution_attempt_id)
);
```
The three `UNIQUE` constraints (not a single composite "at least" key) mean: a reused
`request_nonce` collides on `(install_id, request_nonce)`; a reused `challenge_handle`
collides on `challenge_handle`; one challenge maps to **exactly one** `execution_attempt_id`.
A retry that presents a nonce/challenge pairing different from the stored row (different
`run_id`/`task_id`/`workspace_id`/`challenge_handle`) is a **conflict** and is refused. Any
new attempt requires a **new signed challenge + new nonce**.

**State enum (full lifecycle across the two tables) — CLOSED (P1-4):**
pre-accept in `governed_turn_staging` (§2.4): `VERIFYING` → `UPLOADING` → `INPUTS_READY`
(no `execution_attempt_id`, **no execution right**); then in `governed_turn_acceptance` the exact
9-value closed enum `UNSEEN` (absent) → `ACCEPTED_PREPARED` → `LEASE_READY` → `EXECUTION_STARTING` →
`EXECUTING` → `COMPLETED`; terminal `BLOCKED`, `FAILED`, **`EXPIRED`** (the lease-expiry terminal,
§5 step 8a / §6.1 — a member of the enum, not a prose-only transition), `RECOVERY_REQUIRED`. There is **no
circular dependency**: staging is gated by the *verified signed challenge* (§2.4), and the
acceptance row is created only **after** the staging row reaches `INPUTS_READY` — the two never
depend on each other.

**Outbox sequence (exact):**
1. **Pre-accept ingress (§2.4) — OPEN-TIME PRELIMINARY only:** `brops.governed-turn-open.v1`
   (§4.10(a0)) delivers the exact signed challenge document; the supervisor runs the **open-time
   preliminary** verification (canonicality gate; root sig; challenge sig; key validity **as of
   `challenge_issued_at_ms`**; context) — NOT the final §7 as-of-acceptance predicate — publishes
   the exact challenge bytes, and creates the `governed_turn_staging` row (`VERIFYING`→`UPLOADING`);
   the sidecar uploads only system/history/generation_config; the **supervisor self-resolves +
   publishes + binds** the policy bundle (§2.4 policy note). When all three inputs are published +
   re-hash to the challenge digests, the staging row is `INPUTS_READY`. **No acceptance/clock/
   nonce-consume happens here.**
2. Only once the staging row is `INPUTS_READY`, read the supervisor clock **exactly once** →
   `challenge_accepted_at_ms`.
3. **ACCEPTANCE-TIME AUTHORITATIVE verification (P0-3):** **re-resolve the CURRENT accepted
   root-signed registry snapshot** (a fresh `load_trusted_keys`-style reload + floor — do NOT reuse
   the open-time snapshot), re-verify the challenge `sig` under **that** snapshot, and apply the
   **full §7 key-validity predicate as of `challenge_accepted_at_ms`** (`valid_from_ms ≤
   challenge_accepted_at_ms ≤ valid_to_ms`, `revoked_at_ms IS NULL OR revoked_at_ms >
   challenge_accepted_at_ms`, `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
   challenge_expires_at_ms`, `requested_at_ms ≤ challenge_accepted_at_ms`). A key revoked/removed or
   a registry rotated between open and acceptance is refused here (`challenge_invalidated`). Bind
   this exact acceptance-time `challenge_registry_handle`/`_hash`/`_epoch`/`_root_key_id` into the
   acceptance row → lease → record → attestation → envelope.
4. **One DB transaction:** CAS insert `absent → ACCEPTED_PREPARED` into `governed_turn_acceptance`
   (the three UNIQUE constraints enforce the CAS); reserve `execution_attempt_id`; persist every
   authoritative binding (challenge/registry/context/policy/`challenge_accepted_at_ms`); compute
   and persist the **exact canonical lease payload bytes** (`lease_payload_bytes` +
   `lease_payload_sha256`).
5. **Commit.**
6. **Idempotently sign + atomically publish** that exact persisted lease document
   (create-if-absent under `lease_handle = SHA256(JCS({payload,signature}))`; an existing
   identical handle is idempotent success).
7. CAS `ACCEPTED_PREPARED → LEASE_READY` **only after** the lease document exists in the
   store and **re-hashes + re-verifies** (`validate_governed_turn_lease`), recording
   `lease_handle`.
8. **Execution is forbidden before `LEASE_READY`.**
8a. **Lease-expiry launch gate (P0-4/P1-5, LOCKED) — checked immediately before the CAS in step 9,
    on every first launch AND every recovery.** Read the **wall clock once** → `now_ms` and
    require ALL: (i) not-pre-valid / not-expired `lease_issued_at_ms ≤ now_ms ≤
    lease_expires_at_ms`; (ii) sufficient remaining budget `lease_expires_at_ms − now_ms ≥
    MIN_LAUNCH_REMAINING_MS = 180000`, where `180000 = EXECUTION_TIMEOUT_MS(120000) + grace(5000) +
    teardown(10000) + post_exec_signing_reserve(40000) = 175000` worst-case critical path **+ 5000
    launch/scheduling slack** (the gate reads `now_ms` before the CAS + launcher fsync-marker +
    setuid + exec + cgroup setup + model-endpoint connect, whose latency `L` must not push
    `completed_at_ms` past `lease_expires_at_ms`). This guarantees `finished_at_ms` **and**
    `completed_at_ms` land inside the lease window. Exact-`175000` remaining **refuses**;
    exact-`180000` **proceeds**. If either check fails → CAS `LEASE_READY → EXPIRED` (or `BLOCKED`);
    **do NOT launch**; a new execution requires a newly signed challenge + new `request_nonce` + new
    `execution_attempt_id` (no reuse). The gate uses the **wall clock** (it compares signed `_ms`
    fields); the in-execution timeout then uses the **monotonic** clock (§4.7).
9. Persist `LEASE_READY → EXECUTION_STARTING` **before** launching the recorder/executor (only
   after the step-8a gate passes).
   Optionally, the privileged launcher writes + `fsync`s an **immutable launch-start marker**
   (`execution_started_marker`: attempt id + launch nonce + cgroup binding) before `exec`, for
   forensics — **but that marker MUST NOT authorize any re-execution.**
10. **NO AUTO-RELAUNCH AFTER `EXECUTION_STARTING` (P0-1, LOCKED).** `LEASE_READY` is the **last
    state from which an automatic first launch is permitted**. The launch is preceded by a CAS
    `LEASE_READY → EXECUTION_STARTING`; **once `EXECUTION_STARTING` is durable the attempt is
    NEVER automatically relaunched** — the child may already have started, issued a remote
    model request, or produced external effects and then exited before `EXECUTING`/process
    metadata became durable, so "no live child + no output" does **not** prove non-execution.
    A restart finding `EXECUTION_STARTING` or `EXECUTING` without **complete terminal proof**
    moves to `RECOVERY_REQUIRED`/`BLOCKED` (fail-closed). An owner/operator may **inspect**
    evidence but MUST NOT reuse the same `challenge_handle` / `request_nonce` /
    `execution_attempt_id` for another execution; **a new execution requires a newly signed
    challenge + new `request_nonce` + new attempt.**
11. A `COMPLETED` retry returns **only** the same attempt's independently re-verified
    terminal record/result (idempotent).
12. A failed or conflicting retry **never** creates a new attempt.

**Crash recovery at every cut point** (each maps to a durable state; auto-launch is possible
ONLY from `LEASE_READY`):
crash in `VERIFYING`/`UPLOADING`/`INPUTS_READY` (pre-accept staging) → the staging row alone
**never** authorizes execution; a sweep unlinks orphan `.tmp-*.part` and deletes an expired/
abandoned staging row **WITHOUT consuming the challenge nonce** (the desktop may re-issue against
the same signed challenge until `challenge_expires_at_ms`); before acceptance commit → no
acceptance row persisted, clean retry; after commit before signature →
`ACCEPTED_PREPARED`, re-sign from `lease_payload_bytes` (deterministic); after signature
before publish → publish is create-if-absent, idempotent; after publish before `LEASE_READY`
→ re-hash/re-verify then advance; **`LEASE_READY` (the only auto-launchable state) → the
supervisor re-runs the step-8a lease-expiry gate on the current wall clock and, ONLY if it
passes, CASes to `EXECUTION_STARTING` then launches once — an expired or
insufficient-remaining-budget `LEASE_READY` found on restart moves to `BLOCKED`/`EXPIRED` and is
NEVER auto-launched (P0-4);** **after `EXECUTION_STARTING`
commit but before the launcher call → `RECOVERY_REQUIRED`/`BLOCKED`, never relaunch;** **crash
inside the launcher before `exec` → `RECOVERY_REQUIRED`/`BLOCKED`;** **crash immediately after
`exec` / child exits before `EXECUTING` persistence / a remote model call occurred but no
output/receipt exists → `RECOVERY_REQUIRED`/`BLOCKED`, never relaunch;** after receipt/evidence
before terminal record → re-drive record signing from the already-published verified artifacts
(idempotent create-if-absent, no new execution); after terminal record before ledger
`COMPLETED` → set `COMPLETED` from the existing verified record.

**Negative tests (normative):** concurrent duplicate submissions (exactly one
`ACCEPTED_PREPARED` + one attempt; losers get the idempotent result, never a 2nd execution);
same-nonce/different-challenge (refused); same-challenge/different-nonce (refused);
conflicting `run_id`/`task_id` on retry (refused); and — proving **zero automatic second
execution** — crash **after `EXECUTION_STARTING` commit before the launcher call**, crash
**inside the launcher before `exec`**, crash **immediately after `exec`**, **child exits
before `EXECUTING` persistence**, and **a remote model call occurred but no output/receipt
exists**: each must land in `RECOVERY_REQUIRED`/`BLOCKED` with no relaunch. **Lease-expiry gate
(P0-4):** expired-`LEASE_READY` recovery (`now_ms > lease_expires_at_ms` on restart →
`BLOCKED`/`EXPIRED`, zero launch); exact-expiry boundary (`now_ms == lease_expires_at_ms` passes
(i) but must fail remaining-budget (ii); `now_ms == lease_expires_at_ms + 1` → expired);
insufficient-remaining-budget at the true threshold boundary (`lease_expires_at_ms − now_ms ==
179999` → blocked; `== 180000` → proceeds); and a wall-clock **NTP step** between `LEASE_READY`
persist and the gate re-evaluates on
the stepped clock and blocks if expired (the monotonic in-execution timeout must not smuggle an
expired lease past the wall-clock gate).

**Relationship to the desktop nonce (both hold):** the desktop's `request_nonce`
compare-and-consume in `verify_and_record_receipt` still governs final **receipt**
acceptance (whole-turn replay + `receipt_id` uniqueness, §7); the supervisor ledger above
governs **execution** replay. Neither substitutes for the other.

---

## 6. Atomic publish order (who signs what they published)

1. **Supervisor publishes into `store/sup/`, before execution:** the signed challenge document
   (`challenge_handle`), the accepted registry snapshot (`challenge_registry_handle`) under
   the crash-consistent publish→floor sequence (§7 anti-rollback), the **three sidecar-uploaded
   input artifacts** (system/history/generation_config, which arrive **only** via the §2.4
   authenticated pre-accept bounded ingress — each must exist + re-hash to the challenge's
   committed `*_sha256` before this point), the **supervisor-self-resolved `policy_bundle`**
   (published by the supervisor from its own authoritative policy registry/config — never a
   sidecar upload, §2.4 policy note — binding `policy_bundle_sha256`), and the governed-turn
   lease (`lease_handle`, §5 step 6). All are content-addressed create-if-absent
   (temp→fsync→verify size+sha256→exclusive publish).
2. **Recorder publishes what IT owns + signs over those handles:** the exact `output` bytes
   (`output_handle`), the containment artifact (`containment_evidence_sha256`), and the exact
   signed **`brops.governed-turn-execution-receipt.v1`** document (published content-addressed
   create-if-absent → `execution_receipt_handle`), plus the containment-confirmed evidence
   event + head (evidence-recorder key).
3. **Supervisor verifies the recorder chain by handle** (fetch the receipt by
   `execution_receipt_handle`, re-hash, `verify_governed_turn_receipt`; `load_head`+
   `validate_chain`; containment cross-bind) and **signs the terminal record**
   (`governed-turn-recorder` key) binding every verified handle/id/hash — including
   `lease_handle` + `execution_receipt_handle` — + the ledger's `challenge_accepted_at_ms`;
   never a caller input. The `execution_receipt_handle` (and `lease_handle`) MUST already
   exist + re-hash before the record is signed.
4. **Atomic terminal write:** temp→fsync→`os.link`/`O_CREAT|O_EXCL` into
   `<run_id>__<execution_attempt_id>.json`; `EEXIST` ⇒ byte-compare (identical=idempotent,
   differ=refuse); fsync dir. A crash before this leaves no record ⇒ Block; after ⇒ a
   complete re-verifiable record and ledger `COMPLETED`.

Store ACL (§2.3): supervisor writes `store/sup/` (challenge, registry, inputs, lease,
record), recorder writes `store/rec/` (output, containment, receipt); the isolated signer
reads both (group `brops-store`, read-only); executor/sidecar/desktop have no store or key
access.

### 6.1 The COMPLETE end-to-end order (LOCKED, P1-5) — through the isolated signer + desktop

No output renders before step 14 commits.
1. **Challenge open + OPEN-TIME PRELIMINARY verify + publish (P0-2/P0-3):** the sidecar sends
   **`brops.governed-turn-open.v1`** (§4.10(a0)) carrying the **exact signed challenge document
   bytes** (`challenge_doc_b64`). The supervisor strict-decodes, applies the **canonicality gate**
   (`decoded == canonical_bytes({payload,sig})` else `noncanonical`), computes `challenge_handle =
   SHA256(decoded_document_bytes)`, resolves the current accepted root-signed challenge-key registry
   **from its own state** (§4.2 root pin + floor), runs the **open-time preliminary** predicate (key
   validity **as of `challenge_issued_at_ms`**, NOT the as-of-acceptance §7 predicate) +
   `sig`/context, **atomically publishes the exact `decoded_document_bytes` into `store/sup/`**, and
   CAS-creates the `governed_turn_staging` row `VERIFYING→UPLOADING`. **No clock read, no nonce
   consume** here — this only admits the turn to upload; the binding authority is the acceptance-time
   re-verification (step 3). (The supervisor now *possesses* the exact challenge bytes.)
2. **Bounded input staging** (§2.4): `governed-staging-open/-chunk/-final` publish the three
   sidecar-uploaded inputs (each `== the challenge's committed *_sha256`); the supervisor
   self-resolves+publishes+binds `policy_bundle`; the row advances to `INPUTS_READY`.
3. **Acceptance ledger / outbox** (§5): on the execute trigger (§4.10(d)), read the clock once →
   `challenge_accepted_at_ms`; CAS `UNSEEN → ACCEPTED_PREPARED`; reserve `execution_attempt_id`;
   persist bindings + exact lease payload bytes; commit.
4. **Lease publication + `LEASE_READY`**: idempotently sign + publish the governed-turn lease
   (`lease_handle`, `lease_issued_at_ms == challenge_accepted_at_ms`, `lease_expires_at_ms =
   +LEASE_DURATION_MS`); CAS to `LEASE_READY` only after it re-hashes + `validate_governed_turn_lease`.
5. **Lease-expiry gate + one-time recorder/executor launch (P0-4/P1-5):** run the §5 step-8a gate
   (read `now_ms`; require the lease valid + `lease_expires_at_ms − now_ms ≥ MIN_LAUNCH_REMAINING_MS
   = 180000`), else `EXPIRED`/`BLOCKED`; only if it passes, CAS `LEASE_READY → EXECUTION_STARTING`
   (never auto-relaunch after, §5 P0-1); the launcher enforces the FD/executable contract (§4.7).
6. **Output + containment publication** by the recorder (`output_handle`,
   `containment_evidence_sha256`).
7. **Governed execution receipt + evidence/head publication** by the recorder
   (`execution_receipt_handle`, evidence-recorder key).
8. **Supervisor verification** of the recorder chain by handle.
9. **Terminal governed-turn record publication** (`governed-turn-recorder` key), binding
   `lease_handle` + `execution_receipt_handle` + all §4.8 fields (atomic create-if-absent).
10. **Supervisor constructs the exact attested `brops.governed-sign-request.v1`** (§4.4) and
    signs it with the supervisor attestation key.
11. **Isolated signer invokes `LiveRunStateProvider`** (§7) — the ONLY deep protected-store
    verifier — to verify the terminal chain (record + lease-by-handle + receipt-by-handle +
    challenge + registry + containment + evidence head, incl. the lease-time invariants (P0-4)
    and the **signer-owned durable head-floor CAS `governed_evidence_head_floor`**, committed
    before the envelope is minted, §7 P1-7). The desktop never does this (no store access).
12. **Isolated signer builds + signs the `brops.governed-receipt-envelope.v1`** (§4.9,
    isolated-signer key) binding record/lease/receipt handles + nonce/attempt + head +
    attestation digest + `output_sha256`/`output_bytes` (the output authority), and returns
    **`brops.governed-sign-result.v1`** (§4.5) — `signed` (envelope + signature + attestation
    record) or `refused`.
13. **Supervisor→sidecar `brops.governed-turn-result.v1`** (§4.10(e)) — a metadata-only summary
    (envelope/attestation + `output_bytes`/`output_sha256` + a transport `output_stream_id`, NO
    inline output); the sidecar re-frames it as **`bridge.governed-turn-result.v1`** (§4.6,
    top-level `protocol` discriminator) — transport-only. The desktop then pulls the output
    **through the sidecar** via idempotent **`brops.governed-turn-output-read.v1`** reads
    (§4.10(f)) and reassembles the bytes; the signed envelope's `output_sha256`/`output_bytes`
    (not the transport `output_stream_id`) is the authority.
14. **Desktop final acceptance (P0-3 ordering):** FIRST, **outside** any DB transaction, obtain
    the output bytes by driving the §4.10(f) pull loop (reassemble into a bounded ≤ 8 MiB
    buffer) and verify the envelope signature + attestation, then assert `len(bytes) ==
    envelope.output_bytes` **and** `SHA256(bytes) == envelope.output_sha256` (raw bytes, **no
    normalization before the check**), keeping the verified immutable bytes. THEN open one
    `BEGIN IMMEDIATE` tx (NO store access, NO network I/O inside the lock): **equality-check**
    every bridge/sign-result echo against the verified envelope → strict-UTF8 decode for display
    only (invalid UTF-8 ⇒ Block) → consume the one-time `request_nonce` (`receipt_challenges`) →
    assert `receipt_id` global uniqueness (`receipt_ids_seen`) → check receipt freshness (`_ms`)
    → persist. A stale/rolled-back evidence head was already refused by the signer's durable
    head-floor (step 11, §7 P1-7). Only on commit does the desktop render.

---

## 7. Verification — `LiveRunStateProvider` (runs INSIDE the isolated signer; all cross-bindings)

**`LiveRunStateProvider` is executed by the isolated signer** (which has `brops-store`
read access, §2.3), NOT by the desktop. `verify_artifact(record,
"brops.governed-turn-record.v1")` first (a forged/edited record fails here — no unsigned JSON
is authority), then require, all fail-closed:

- **Lease (fetch by handle):** fetch the exact signed lease document by the record's
  **`lease_handle`**, **re-hash the exact document bytes** (`== lease_handle`), verify the
  issuer signature, then `validate_governed_turn_lease` (§4.3, NOT the base validator); the
  record's `lease_id`/`lease_nonce`(==lease `nonce`)/`challenge_accepted_at_ms` +
  challenge/registry bindings equal the lease's; `allowed_capabilities ==
  ["INVOKE_GOVERNED_MODEL"]`, `max_tool_calls == 0`.
- **Lease-time invariants (P0-4/P1-5, all fail-closed):** on the fetched lease, `lease_issued_at_ms
  == challenge_accepted_at_ms` and `lease_expires_at_ms − lease_issued_at_ms == LEASE_DURATION_MS
  (210000)`; and the **complete** execution time-chain must fall **inside** the lease window:
  `lease_issued_at_ms ≤ started_at_ms ≤ finished_at_ms ≤ completed_at_ms ≤ lease_expires_at_ms`
  (P1-5 — `completed_at_ms ≤ lease_expires_at_ms` is the durable, verify-time guarantee that the
  launch gate alone cannot provide since it is never re-checked after launch; `completed_at_ms` is
  the §4.8 terminal-record field, supervisor-stamped at record publication). A receipt/record
  produced under an expired lease (any inequality violated) is refused here — the isolated signer
  will not mint an envelope for it. (Tests: started-before-lease, finished-after-lease,
  `completed < finished`, **`completed_at_ms > lease_expires_at_ms` with `finished` in-window** →
  refuse, a wall-clock NTP step during execution that stamps `completed` past `lease_expires` →
  refuse, duration/equality mismatch — each refuses; boundary `completed == lease_expires_at_ms`
  accepts.)
- **Challenge (fetch by handle + re-hash, P0-3):** fetch the exact signed challenge document by
  `challenge_handle`, **re-hash the exact stored bytes** (`SHA256(bytes) == challenge_handle`, and
  `bytes == canonical_bytes({payload,sig})` — closing the canonicality gap, matching the registry
  step below), verify `sig` under the key resolved from the bound **acceptance-time** registry
  snapshot; recompute `request_sha256`; the challenge's identities/`*_sha256`/`requested_at_ms`
  equal the record's. The challenge does **not** contain `challenge_accepted_at_ms`. (This §7
  predicate is the **acceptance-time authority** — evaluated as-of `challenge_accepted_at_ms`; the
  §4.10(a0) open-time check is preliminary only, as-of `challenge_issued_at_ms`.)
- **Registry snapshot:** fetch the exact signed document by `challenge_registry_handle`,
  re-hash the full document (`== challenge_registry_handle`), verify `root_sig` over
  `JCS(payload)` under the pinned `challenge_registry_root_key_id`, recompute `registry_hash
  == challenge_registry_hash`, `registry_epoch == challenge_registry_epoch`; then the **full
  key-validity predicate as of `challenge_accepted_at_ms`**: `challenge_key_id` present
  exactly once, `public_key` schema valid, `key_epoch` accepted,
  `valid_from_ms ≤ challenge_accepted_at_ms ≤ valid_to_ms`,
  `revoked_at_ms IS NULL OR revoked_at_ms > challenge_accepted_at_ms`, and the challenge
  `sig` valid under that exact snapshot key — presence alone is insufficient.
- **Temporal (as-of-acceptance, never wall-clock now):** `requested_at_ms ≤
  challenge_accepted_at_ms` and `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
  challenge_expires_at_ms`; a record in-window stays valid forever.
- **`challenge_accepted_at_ms` equality chain (supervisor-authoritative only):** byte-equal
  across `brops.governed-turn-lease.v1` → `brops.governed-sign-request.v1` attestation →
  `brops.governed-sign-result.v1` → `bridge.governed-turn-result.v1` → record → the signer
  envelope (§4.9). It is **not** a challenge field.
- **Receipt/output (fetch by handle):** fetch the exact signed execution-receipt document by
  the record's **`execution_receipt_handle`**, **re-hash the exact document bytes**
  (`== execution_receipt_handle`), verify the **evidence-recorder** signature, then
  `verify_governed_turn_receipt`; `output_sha256 == output_handle == SHA256(exact output
  bytes)`; the receipt's `receipt_id`/`execution_attempt_id`/`lease_id` equal the record's.
- **Containment:** the containment artifact's run/attempt/lease/runner equal the record's,
  `contained==true`, its evidence event `payload_hash == containment_evidence_sha256`.
- **Evidence head + anti-rollback (SIGNER-OWNED durable floor, P1-7 — NO desktop head-floor
  table).** The reused `bro_evidence` head/chain has no timestamp comparison; its anti-truncation
  is **structural** (`event_hash`/`sequence`/`final_event_hash`/`head_sequence`). Today
  `min_head_sequence` is a caller-only parameter never persisted (`brops_live_runstate.py` calls
  `load_head`/`validate_chain` with **no** floor → a no-op); the fix makes it a **durable
  `brops-signer`-owned floor DB**, separate from the read-only `brops-store` artifact store (the
  signer is read-only there, §2.3), dir `0700` / file `0600`:
  ```sql
  CREATE TABLE governed_evidence_head_floor (
    install_id       TEXT NOT NULL, task_id TEXT NOT NULL,
    highest_sequence INTEGER NOT NULL, final_event_hash TEXT NOT NULL, updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (install_id, task_id) );
  ```
  Inside `LiveRunStateProvider`, **before minting the §4.9 envelope**, the signer runs `load_head`
  + `validate_chain` structurally → `(head_sequence, final_event_hash)`, then in **one
  `BEGIN IMMEDIATE`** tx (write-lock up front, reject nested — the proven `receipt_store.rs`
  `in_immediate_tx` shape) `SELECT … WHERE install_id=? AND task_id=?` and decide: **no row** →
  `INSERT`; **`head_sequence < highest_sequence`** → **refuse** (stale/rolled-back); **`==` with
  different `final_event_hash`** → **refuse** (fork at same seq); **`==` with same hash** →
  **idempotent** (do not advance; re-sign the byte-identical envelope, deterministic from the
  verified record); **`head_sequence > highest_sequence`** → **advance ONLY IF the new chain
  extends the stored floor (P1-7 extend-or-scope):** the validated chain MUST descend from the
  stored floor — some event carries `previous_event_hash == the stored floor's final_event_hash`
  and the stored `highest_sequence` prefix reproduces byte-for-byte — then `UPDATE … SET
  highest_sequence=?, final_event_hash=?, updated_at_ms=?`. If a higher `head_sequence` does NOT
  descend from the stored `final_event_hash` it is a **divergent lineage → refuse as
  `evidence_fork`**. (A divergent higher head that is nonetheless validly signed would require
  **evidence-recorder key compromise**, which is **OUT of the §0 threat model** — the signer does
  not silently bless it; it refuses.) **Commit the floor BEFORE returning the signed envelope**;
  concurrent same-chain attempts serialize on `BEGIN IMMEDIATE` + the `(install_id, task_id)` PK
  (closing the TOCTOU). Crash after floor-commit before response → the retry hits the
  equal-seq/equal-hash branch and re-signs the identical envelope (no second advance, no
  re-execution). **Startup integrity (scoped honestly, P1-7 — Option A):** on open, verify each
  floor row is internally self-consistent (`final_event_hash` is 64-hex, `highest_sequence ≥ 1`)
  and refuse a malformed/corrupt DB, fail-closed. This floor detects and refuses — **against the
  current persisted floor** — a stale head (`<`) and a same-sequence fork (`==` different hash),
  i.e. rollback mounted **through the running signer** by the in-scope sidecar (which per §2.3
  cannot read or write this `brops-signer` `0700`/`0600` DB at all). **This local table CANNOT
  detect a full-DB restore to an older self-consistent backup** — no external anchor exists to
  compare against, and the restored DB returns the restored (lower) floor as authoritative.
  Offline/root/admin backup restore of the signer-owned DB requires privileges that are **OUT of
  the §0 threat model** (admin/root/kernel), so it is **not** defended here. **External monotonic
  anti-rollback anchoring** (an operator-held pin outside the DB, mirroring `resolve_registry_floor`'s
  `BRO_OPERATOR_REGISTRY_MIN_FILE`, or a hardware monotonic counter) is **DEFERRED to 3b-2**;
  unlike the registry floor (whose strength comes from that external anchor), this evidence-head
  floor makes **no** cross-restart backup-rollback claim. The envelope binds `evidence_head_sequence`/
  `evidence_final_event_hash` (§4.9) so the signed artifact commits to the exact floor. **Tests:**
  concurrent (exactly one advances), crash-after-commit (identical re-sign), same-seq/same-hash
  (idempotent), same-seq/different-hash (refuse), lower-seq (refuse), greater-seq-that-extends
  (advance), greater-seq-divergent-lineage (refuse `evidence_fork`). (The Wave-3a desktop SQLite
  has **no** `evidence_head_floor` table — this primitive is signer-side; a stale head is refused
  here at the signer, before any envelope is minted.)
- **Registry anti-rollback (supervisor side, crash-consistent):** verify full signed
  registry → create-if-absent publish exact doc + fsync file&dir → durable floor tx persists
  `(highest_registry_epoch, registry_hash, challenge_registry_handle, root_key_id)` → the
  floor is never usable unless its snapshot exists + re-hashes → same-epoch/different-hash +
  divergent-handle refused; startup verifies the floor's snapshot before use, else
  fail-closed.

`RunState` is built from the verified signed record only. On success the signer mints the
`brops.governed-receipt-envelope.v1` (§4.9); on any failure it returns `refused` (§4.5).

### 7.1 Desktop acceptance (§6.1 step 14) — signatures only, NO store access

The desktop verifies the **isolated-signer envelope** (§4.9) + the **supervisor attestation**,
equality-checks the transport echoes, and binds the real Wave-3a desktop replay primitives —
all without reaching the protected store. **Ordering (P0-3):** the envelope-signature +
attestation verification and the **output fetch/reassemble/hash happen FIRST, OUTSIDE the DB
transaction** (the §4.10(f) pull loop is network/subprocess I/O and must never run while holding
`BEGIN IMMEDIATE` — `receipt_store.rs::in_immediate_tx` rejects a nested tx); the verified
immutable bytes are kept, THEN the tx opens for the replay/persist steps below.
- **Envelope signature** — Ed25519 over `JCS(envelope.payload)` under the **pinned
  isolated-signer manifest key**; a bad signature Blocks.
- **Attestation** — verify the supervisor attestation signature over
  `attestation_evidence_jcs_b64` against the manifest `supervisor_attestation` key, and confirm
  `SHA256(that JCS) == envelope.attestation_evidence_sha256`.
- **One-time nonce** — compare-and-consume `receipt_challenges` (`nonce` PK, bound to
  `request_sha256`; `UPDATE … SET consumed_at=? WHERE nonce=? AND consumed_at IS NULL`).
- **`receipt_id` global uniqueness** — insert into `receipt_ids_seen` (PK) only on ACCEPT.
- **Freshness** — the `_ms` window (`FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}`
  vs `now_ms`, the real `receipt_store.rs` values); every governed-turn `_ms` field nests inside
  it (§1 window-nesting).
- **Output binding (P0-3, done OUTSIDE the tx)** — obtain the exact output bytes by driving the
  §4.10(f) `brops.governed-turn-output-read.v1` pull loop through the sidecar into a bounded ≤ 8
  MiB buffer; assert `len(bytes) == envelope.output_bytes` **and** `SHA256(bytes) ==
  envelope.output_sha256` over the **raw** bytes with **no trim/NFC/NFKC/CRLF/lossy** normalization;
  only then strict-UTF8 decode for display (invalid UTF-8 Blocks). A mismatch/wrong-length/
  tampered/replayed-chunk Blocks. Restores the binding the v1 path had at `receipt.rs`
  (`sha256_hex(output) == output_sha256`).
- **Echo equality** — every `bridge.governed-turn-result.v1`/`brops.governed-turn-result.v1` echo
  equals the verified envelope; a mismatch Blocks. A bare echo never authorizes anything.
The nonce-consume + `receipt_id` uniqueness + freshness + echo-equality + persist run in one
`BEGIN IMMEDIATE` tx (the already-verified output bytes are used, no I/O in the lock); render only
on commit.

---

## 8. Authorities (governed-turn functions only)

- **Lease:** `issue_governed_turn_lease` (governed-turn lease issuer) +
  `validate_governed_turn_lease` (§4.3). The base `issue_lease`/`validate_execution_lease`
  are **NOT** used for this path (a governed-turn lease presented to the base validator is
  refused).
- **Terminal record:** the **`governed-turn-recorder`** is a **supervisor-held signing-key
  authority, NOT a distinct OS principal** (P1-5). It is registered as a `bro_signature`
  `AUTHORITY_TYPES` entry + a `broctl` key class + an `ARTIFACT_AUTHORITY` mapping, its key held
  in a `0700` owner-only dir under the **`brops-supervisor`** principal (alongside the
  attestation key). The supervisor invokes **only** the exact terminal-record constructor
  (`broctl sign --artifact brops.governed-turn-record.v1`, mirroring the existing
  `broctl` artifact-authority gate) — there is **no public `sign(payload)` oracle** (`bro_signature`
  only ever verifies). It signs **only** `brops.governed-turn-record.v1`; it MUST NOT sign
  `evidence-event`/`evidence-head`/any lease, and `verify_artifact` refuses a record signed by
  any other authority. (The separate `brops-recorder` OS principal holds the distinct
  **evidence-recorder** key and writes `store/rec/`, §2.3 — the two are different things.)
- **Receipt + evidence:** `brops.governed-turn-execution-receipt.v1` and the containment/
  evidence events/head are signed by the **evidence-recorder runner** and verified by
  `verify_governed_turn_receipt` (NOT the generic `bro_run_receipt.run_and_sign` /
  `verify_passing_receipt`).
- **Challenge:** the dedicated `desktop-challenge-authority` (its own principal/UID; §2.1).
- **Registry root:** the binary-pinned challenge-root anchor (separate from the receipt keys).
- **Supervisor attestation:** the supervisor-attestation key signs **only**
  `brops.governed-sign-request.v1` evidence (`brops.run-attestation.v1`); re-verified by the
  isolated signer and the desktop against the manifest `supervisor_attestation` key.
- **Governed receipt envelope:** the **isolated-signer** key signs **only**
  `brops.governed-receipt-envelope.v1` (§4.9); it is the desktop's sole trust root for the
  turn (pinned in the desktop manifest). It MUST NOT sign leases/records/evidence.
- **Authority separation is total:** no authority may sign another class's artifact
  (Appendix B authority matrix).

---

## 9. Acceptance criteria (for 3b-1B implementation, AFTER Architect design-GREEN)

Positive: a real desktop→sidecar→supervisor(accept+execute+record)→signer E2E yielding a
`signed` governed-result whose receipt binds the exact request + output; the Linux isolation
job's positive control uses a genuinely-executed record. Negative matrix: forged/edited
record; replayed old evidence head; output/containment/nonce not matching the signed
artifacts; missing lease/receipt; the §1/§2/§5/§7 negative tests (mixed-unit timestamps,
capability overgrant, ledger replay/conflict, crash-cut recovery, historical key-validity,
transport-only echo mismatch). Engine + isolation exact-head CI GREEN. **STOP unchanged:**
`NoTrustedManifest`, no production "Verified".

---

## Appendix A — NON-NORMATIVE revision history (does not define current contracts)

The current normative design is §0–§9 above. This log is historical only.
- **rev 1–5:** initial 3b-1B design-lock, closing Architect REDs on topology, oracle removal,
  containment binding, ingress, launcher TCB, schema de-dangling.
- **rev 6:** dedicated `desktop-challenge-authority`; challenge binds run/task; fixed input
  delivery; one bounded ingress; challenge bound in record.
- **rev 7:** authority builds challenge from trusted DB (no caller bytes); canonical launcher
  FD table; supervisor publishes signed challenge; self-contained challenge-key registry;
  as-of-run historical verification.
- **rev 8:** dedicated-principal pending-store + direct-file-mutation CI denial; supervisor
  `challenge_accepted_at`; full registry trust contract; read-only regular-file input FDs.
- **rev 9:** registry payload-hash vs exact-document handle split; crash-consistent
  snapshot-publish→floor; full historical key-validity predicate; (attempted) signed
  `challenge_accepted_at` schema.
- **rev 10:** supervisor atomic challenge consumption (first cut); governed-turn-lease as a
  "superset" (had unit/field conflicts + an impossible challenge equality).
- **rev 11:** one-pass consolidation — canonical ms time model; dedicated durable acceptance
  state machine + outbox; closed `governed-model-turn-v1` capability profile; relay schemas +
  transport-only echoes; §8 governed-turn functions; single artifact matrix as the source of
  truth; revision history demoted to this appendix.
- **rev 12:** surgical corrections to the rev-11 structure — no auto-relaunch after
  `EXECUTION_STARTING`; full challenge-authority creation-channel contract restored (§2.1);
  registry `revoked`/`revoked_at_ms` invariant; relay schemas + `builder_id` removed; terminal
  record binds `lease_handle` + `execution_receipt_handle` + 13-step E2E; CLAUDE.md doc-law loop
  corrected.
- **rev 13:** implementation-readiness closure via a 6-track fan-out — **P0-1** separate
  `brops.governed-*`/`bridge.governed-*` protocol family so the GREEN 3b-1A v1 schemas stay
  byte-for-byte (§2.2, §4.4–4.6); **P0-2** one authenticated bounded chunked-upload ingress to
  supervisor staging + per-artifact caps (§2.4); **P0-3** the `brops-store` group ACL model + a
  desktop-vs-signer authority split — the signer's `LiveRunStateProvider` deep-verifies the store
  and emits a signed receipt envelope the desktop verifies with no store access (§2.3, §4.6, §4.9,
  §6.1, §7.1); **P1-4** `bro_evidence` marked legacy epoch-seconds; **P1-5** complete receipt/
  containment/record/envelope schemas + one `execution_receipt_handle` name + `record_handle`;
  **P1-6** `MAX_OUTPUT_BYTES = 8 MiB` output ceiling.
- **rev 14:** 7-track fan-out closure — `2750` owner-write ACL; pre-accept `governed_turn_staging`
  FSM + supervisor-self-resolved policy; `output_b64` desktop hash gate; `MAX_STAGING_CHUNK_BYTES
  = 184320`; §4.10 control-plane schemas + bridge parent; `EXECUTION_TIMEOUT_MS = 120000`;
  signer-owned `governed_evidence_head_floor` CAS.
- **rev 15:** transport/version/lease closure — freeze the shipped `brops.governed-result.v1`,
  rename the 3b-1B result `brops.governed-turn-result.v1`/`bridge.governed-turn-result.v1` with a
  top-level `protocol` const; `brops.governed-turn-open.v1` challenge submission; idempotent PULL
  output-read; `LEASE_DURATION_MS = 210000` + pre-launch gate; governed-turn-recorder = supervisor
  key authority; always-stream metadata-only summary; Option-A evidence-floor scope + extend-or-scope.
- **rev 16 (this doc):** targeted protocol/proxy/state-consistency closure via a mandatory **6-track
  fan-out (A protocol-compat/routing · B output proxy · C challenge two-phase verify · D state/
  reason enums · E retry/crash idempotency · F adversarial E2E) + one integrator + a fresh
  independent red-team** — **P0-1** rev 15 still instructed renaming the **shipped**
  `brops.governed-result.v1` constant/emitter/consumer → **KEEP** it unchanged + **ADD a parallel**
  `GOVERNED_TURN_RESULT_PROTOCOL` (new emitter/consumer/schema/tests, nothing old renamed) + one
  canonical positive-`protocol`-const bridge rule (§2.2); **P0-2** the supervisor output pull had no
  desktop→sidecar route → a complete **`bridge.governed-turn-output-read.v1`** request/reply, a
  per-chunk one-shot-subprocess Tauri command, and a durable **`governed_output_streams`** table
  (43-char base64url capability, `OUTPUT_STREAM_TTL_MS = 360000`, restart-survival, same-id retry)
  (§4.10(f)); **P0-3** `governed-turn-open` referenced the as-of-`challenge_accepted_at_ms` §7
  predicate (nonexistent at open) → **two-phase verification** (open-time preliminary as-of
  `challenge_issued_at_ms` + a **canonicality gate** `decoded == JCS({payload,sig})`; acceptance-time
  authoritative **re-resolves the current registry**) (§4.10(a0), §5, §7); **P1-4** `EXPIRED` CAS'd
  but not in the enum + prose-only reasons → **closed 9-value state enum + one
  `GOVERNED_REFUSAL_REASONS` union** enumerated in every relay (§5, §4.5, §4.6, §4.10); **P1-5** §7
  never bounded `completed_at_ms ≤ lease_expires_at_ms` + zero launch slack → **`MIN_LAUNCH_REMAINING_MS
  = 180000`** + the full chain `lease_issued ≤ started ≤ finished ≤ completed ≤ lease_expires`
  (§5, §7, §4.7); **P1-6** a lost reply stranded an upload → **exact idempotency** (same-bytes retry
  → same handle/session/ack; conflict → `retry_conflict`) + durable session/per-chunk columns for
  restart survival (§2.4, §4.10).

## Appendix B — consistency-audit matrices (verification aids, non-normative)

- **Authority matrix:** challenge-authority→challenge only; challenge-root→registry only;
  lease-issuer→governed-turn-lease only; evidence-recorder→receipt/containment/evidence only;
  governed-turn-recorder (a supervisor-held key class, NOT a principal, P1-5)→terminal record only; supervisor-attestation→governed-sign-request
  attestation only; isolated-signer→governed-receipt-envelope only. No authority may sign
  another class's artifact (each artifact's validator pins its own `artifact_type`).
- **Handle matrix (a handle is always `SHA256(exact stored bytes)`, but "the bytes" differ by
  kind):**
  - **signed-document handles** (`challenge_handle`, `challenge_registry_handle`,
    `lease_handle`, `execution_receipt_handle`, **`record_handle`**) =
    `SHA256(JCS(exact signed document))`, i.e. `SHA256(JCS({payload, sig|root_sig|signature}))`;
  - **raw-artifact handles** (`system_handle`, `history_handle`,
    `generation_config_handle`, `output_handle`, `policy_bundle_handle`) =
    `SHA256(exact RAW artifact bytes)` (no JCS, no prefix) — these equal their `*_sha256`;
  - **containment handle** `containment_evidence_sha256` = `SHA256(JCS(containment artifact))`
    (a JCS-document digest; the `_sha256` suffix is legacy naming, not a raw-byte handle);
  - the **signer receipt envelope** (#12) is **transported**, not stored — no store handle;
  - **payload/identity hashes** (`registry_hash`, `request_sha256`, raw `*_sha256`,
    `attestation_evidence_sha256`) are digests, distinct from the document handles above and
    never used as a store lookup for a signed document.
- **Time matrix:** all governed-turn fields `_ms` integer; the reused **`bro_evidence`
  event/head is LEGACY epoch-seconds** (`issued_at_epoch`) and is **never compared to an ms
  window** (only its structural bindings cross in); base `execution-lease` `*_epoch` (seconds)
  untouched and unused here.
- **Replay matrix:** challenge `request_nonce` (one-time, desktop `receipt_challenges`) +
  `governed_turn_staging` (`UNIQUE(install_id,request_nonce)`+`UNIQUE(challenge_handle)`,
  pre-accept, no execution right) + supervisor acceptance ledger (execution, three UNIQUE
  constraints) + lease `nonce` + `receipt_id` (global, desktop `receipt_ids_seen`) +
  `execution_attempt_id` (unique) + `registry_epoch`/`registry_hash` (registry floor) +
  **signer-owned durable** evidence-head floor `governed_evidence_head_floor` (BEGIN IMMEDIATE
  CAS; `head_sequence` vs `highest_sequence`; NO desktop head-floor table exists).
- **Principal/ACL matrix (P0-1 mode-fix `2750` owner-write / group read-only):** `brops-store`
  group = {`brops-supervisor`, `brops-recorder`, `brops-signer`(read-only)}; `store/sup/` owner
  `brops-supervisor` **`2750`**, `store/rec/` owner `brops-recorder` **`2750`** (group `r-x`,
  **NO group `w`** — only the namespace owner creates/renames/unlinks; the other owner + signer
  read/traverse only), artifacts `0640`, `umask 0027`, setgid kept only for group-inheritance;
  `_harden_dir` refuses `S_IWGRP`. Private-key dirs `0700` owner-only (incl. the
  **`governed-turn-recorder` key under `brops-supervisor`** — a supervisor-held key class, NOT a
  separate principal, P1-5); **evidence-head floor DB** `brops-signer` `0700`/`0600`; acceptance
  ledger + `governed_turn_staging` (+ its session/chunk tables, P1-6) + **`governed_output_streams`**
  (P0-2) `0700` supervisor-only; sidecar/executor/desktop = none.
- **Capability matrix:** executor = `INVOKE_GOVERNED_MODEL` only; `max_tool_calls=0`; no
  builder grants; launcher digest + model profile pinned.
- **Protocol matrix (P0-1 — KEEP shipped + ADD parallel, nothing renamed):** FROZEN
  (`brops.sign-request.v1`/`brops.sign-result.v1`/`brops.evidence-request.v1`/
  **`brops.governed-result.v1`** (the shipped `{status,output,receipt}` shape — `GOVERNED_RESULT_PROTOCOL`
  constant + emitter + `engine_sidecar` consumer stay byte-for-byte)/`bridge.result`/`bridge.task-request`)
  UNCHANGED; the NEW governed family — added in parallel (new `GOVERNED_TURN_RESULT_PROTOCOL`) —
  (`brops.governed-turn-open.v1` / `brops.governed-sign-request.v1` / `brops.governed-sign-result.v1`
  / `brops.governed-evidence-request.v1` / **`brops.governed-turn-result.v1`** / the ingress
  `brops.governed-staging-open/-chunk/-final.v1` / the egress **pull**
  `brops.governed-turn-output-read.v1` (supervisor) + **`bridge.governed-turn-output-read.v1`**
  (desktop→sidecar) / `brops.governed-receipt-envelope.v1` / **`bridge.governed-turn-result.v1`** and
  their `-result` replies, §4.10) is disjoint; every governed protocol has ONE complete schema +
  `protocol` const discriminator + producer/consumer (§4.4–4.10); each path refuses the other's
  documents. Every `bridge.governed-*` schema is disjoint from `bridge.result` via its **required
  top-level `protocol` const** (NOT via `envelope_jcs_b64`, which is required in `bridge.result`
  too). All governed refusals draw from the closed **`GOVERNED_REFUSAL_REASONS`** union (§4.5, P1-4);
  the acceptance state enum is the closed 9-value set incl. **`EXPIRED`** (§5, P1-4).
