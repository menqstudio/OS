# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 6)

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. Builds on
> the Architect-GREEN Wave 3b design ([`WAVE_3B_ISOLATED_SIGNER_DESIGN.md`](./WAVE_3B_ISOLATED_SIGNER_DESIGN.md))
> and the 3b-1 re-scope map ([`WAVE_3B1_EXECUTION_BINDING_MAP.md`](./WAVE_3B1_EXECUTION_BINDING_MAP.md)).
> Closes the 2nd code-audit finding: an **unsigned pre-written run record must never be
> signing authority**. Reuses the existing lease / containment / receipt / evidence
> authorities — **no parallel executor**. **STOP unchanged:** `NoTrustedManifest`, no
> production "Verified". 3b-2 does not start until 3b-1 is exact-head GREEN + merged.
>
> **rev 2** closes the Architect design RED on rev 1: **P0-1** the contained model
> executor holds NO signing key — a dedicated evidence-recorder RUNNER (separate OS
> identity) signs the receipt/evidence (§2); **P0-2** the governed-turn runner captures
> the reply in **binary** mode and hashes the EXACT bytes with NO CRLF/decode/trim
> normalization, via a **governed-turn-specific** receipt (§2, §3); **P1-3** the
> terminal-record authority is LOCKED to a **dedicated `governed-turn-recorder`** that
> cannot sign receipts/evidence-heads (§8); **P1-4** the record write is idempotent
> **create-if-absent** (O_EXCL + byte-identical re-check), not a clobbering rename (§4);
> **P1-5** the **supervisor** atomically reserves/generates `execution_attempt_id` (the
> desktop never supplies it) (§2.5); **P1-6** the evidence-head anti-rollback floor's
> owner + transaction semantics are locked (§6).
>
> **rev 3** closes the design RED on rev 2: **P0-1** recorder runner + model executor are
> **different OS principals** (dedicated UIDs, ptrace/key-dir denial, explicit output
> channel), machine-tested in Linux CI (§2); **P0-2** the recorder runner is itself the
> execution + containment **observer** (measures `contained` at teardown — no
> `sign(caller_claim)` oracle) (§2); **P1-3** §3 now signs with the dedicated
> `governed-turn-recorder` — no evidence-recorder alternative remains (§3, §8); **P1-4** a
> normative `brops.governed-turn-execution-receipt.v1` schema + dedicated verifier replaces
> the generic CRLF-normalizing receipt (§3.5, §4); crash-recovery wording aligned to
> create-if-absent (§6).
>
> **rev 4** closes the design RED on rev 3: **P0-1** one non-contradictory executor lifecycle owner — the supervisor launches the recorder runner; the recorder starts the executor under a different UID via a **narrow privileged launcher** (setuid-only, holds no key) and owns the pidfd/cgroup + teardown, so signing-capability and setuid-capability live in separate principals (§1, §2); **P1-2** the evidence-head floor is keyed **per (install, task/chain)**, not per-install (§6); **P1-3** the supervisor request carries the **exact** system/history/generation_config bytes + challenge, and the supervisor recomputes the three hashes and refuses on mismatch before reserving/executing (§2.5); **P1-4** a normative `brops.governed-turn-containment.v1` artifact binds run/attempt/lease/runner + cgroup + the measured `contained`, hashed into a containment-confirmed evidence event and cross-bound by the verifier (§3.6).
>
> **rev 5** closes the design RED on rev 4: **P0-1** the request challenge is **desktop-native-host authenticated** (signed `brops.governed-turn-challenge.v1` over the FULL envelope incl. `workspace_id`/`install_id`, pinned key, replay-refused) — a compromised sidecar cannot forge a self-consistent request (§2.5); **P0-2** ONE ownership flow — the **recorder** publishes output+containment and signs the receipt over those handles; the **supervisor** imports its own artifacts, verifies by handle, and signs the record; store write is recorder/supervisor only (§4); **P1-3** large inputs use a **bounded authenticated ingress** to supervisor-owned staging (handles, not inline megabytes) (§2.5); **P1-4** schemas de-dangled — `receipt_id` added to the receipt, `runner_id` to the record, containment enum closed + `cgroup_id`/`process_group_id` explicit, §8 uses the dedicated `verify_governed_turn_receipt` (§3, §3.5, §3.6, §8); **P1-5** the head fields (`task_id`/`evidence_head_sequence`/`evidence_final_event_hash`) are authenticated through sign-request→attestation→sign-result→bridge→desktop verify tx (§6); **P1-6** the launcher TCB is frozen (fixed caller/target UID, digest-pinned root-owned executable, sanitized env/argv/FDs/groups, cap-drop) + Windows broker/restricted-token equivalent or Windows fail-closed until implemented (§2).
>
> **rev 6** closes the narrow design RED on rev 5: **P0-1** the challenge is signed by a **dedicated `desktop-challenge-authority` principal/SID** (not the same-login sidecar principal) that is NOT a `sign(payload)` oracle — it takes a protected pending-challenge ID, reads the bytes from its own authoritative store, signs once; sidecar key-read/ptrace/oracle denials are machine-proven; key rotation/revocation via `challenge_key_id` (§2.5); **P0-2** the signed challenge now binds `run_id`/`task_id` + context identities (the supervisor request is `{challenge}` alone), so an unused challenge cannot be redirected to another run (§2.5); **P0-3** the input-delivery order is fixed — import inputs BEFORE execution, launch the recorder with read-only input FD(s), executor gets exact bytes on a read-only FD (§2.5, §4); **P1-4** ONE frozen ingress mechanism — chunked authenticated upload to supervisor-owned staging with frozen chunk/artifact/total caps, sequence/dup rules, O_EXCL, hash/size verify, atomic commit, expiry/quota/crash (§2.5); **P1-5** the signed challenge is stored content-addressed and the record binds `challenge_handle`/`challenge_key_id`/`issued_at`/`expires_at`/`request_sha256` so the provider independently re-verifies it (§3, §5).

## 1. The governed AI turn IS a `bro_supervisor`-owned supervised execution

Today the governed AI turn (desktop `system`/`history` → model reply) runs in the sidecar
and is NOT lease-owned or receipted. 3b-1B moves it under the existing supervisor, with a
**single, non-contradictory lifecycle owner** (P0-1):

- The **supervisor** (`bro_supervisor.run_task` path) **issues the execution-lease**
  (`issue_lease`, issuer authority) and **launches the evidence-recorder runner** (under
  the recorder UID). The supervisor owns the lease + signs the governed-turn-record; it
  does **not** itself spawn the model executor or measure containment.
- The **evidence-recorder runner** owns the executor lifecycle + containment: it starts
  the model executor (via the narrow privileged launcher, §2) under the *executor* UID,
  owns its `pidfd`/cgroup + the output pipe, and performs the teardown + firsthand
  `contained` measurement (reusing `bro_supervisor`'s group-stop machinery). The turn is
  `COMPLETED` only under the existing rule: `not timed_out AND contained AND exit_code == 0`.

No new executor is invented: the model executor is the `builder_command` for this run,
spawned + contained exactly as any builder — but under the runner (§2 topology), not the
supervisor.

## 2. Key-custody topology + EXACT output bytes (P0-1, P0-2)

**Topology (P0-1) — the contained model executor holds NO signing key:**

```
supervisor  (recorder-launcher UID; owns the lease; signs the governed-turn-record
             via the dedicated governed-turn-recorder key, §8)
  → EVIDENCE-RECORDER RUNNER   (dedicated recorder UID; holds the evidence-recorder
        key; signs the execution receipt + evidence chain; owns the executor's
        pidfd/cgroup + output pipe + teardown measurement)
      → NARROW PRIVILEGED LAUNCHER   (a tiny setuid helper: its ONLY job is to drop to
            the executor UID + exec the model executor in a fresh cgroup/process group;
            holds NO signing key; no other capability)
          → CONTAINED MODEL EXECUTOR   (executor UID; NO signing key/path in its env or
                tree; writes ONLY its reply bytes to the recorder's output pipe)
      ← recorder reads the exact reply bytes, measures `contained` at teardown
  ← the runner returns the signed governed-turn execution receipt + evidence head
```

**Why a launcher (P0-1):** a dedicated recorder UID cannot itself `setuid` to a different
executor UID without a privileged capability. Rather than give the recorder `CAP_SETUID`
(broad forgery/impersonation power **and** it holds the evidence key), the recorder
`exec`s a **narrow privileged launcher** whose sole function is `setuid(executor) + exec`
in a fresh cgroup/process group. The launcher holds **no signing key** and does nothing
else; the recorder keeps ownership of the child's `pidfd`/cgroup + the output pipe (so it
still measures containment firsthand), while the *signing capability* and the *setuid
capability* live in **separate** principals. Neither the executor nor the launcher can
read a signing key.

**Principal separation is an OS-identity boundary, LOCKED (P0-1) — a process group is NOT
custody:**
- the **evidence-recorder runner** runs under its **dedicated recorder UID** (holds the
  evidence-recorder key in an owner-only dir; is NOT privileged/`CAP_SETUID`);
- the **model executor** runs under a **different unprivileged executor UID**;
- the executor principal is **denied read + list** on the recorder key directory and
  **cannot `ptrace`/debug** the recorder process (distinct UID + `ptrace_scope`/no shared
  debug rights) — it can read neither the key file nor the recorder's process memory;
- the runner→executor channel is the recorder-owned **output pipe** (the executor writes
  only its reply bytes to a fixed handle the recorder reads); the executor never touches
  the store or the keys;
- **Machine-tested:** the Linux `engine-isolation` job extends to prove the executor
  principal cannot read the recorder key dir nor `ptrace` the recorder (same dedicated-user
  pattern already used for the signer/supervisor denials).

**Privileged launcher TCB contract (P1-6, LOCKED).** The setuid launcher is the only
privileged component, so its behavior is frozen: a **fixed caller UID** (only the recorder
principal may invoke it) and a **fixed target UID** (the executor principal — never
caller-selected); a **fixed executable path pinned by digest** (never a caller-supplied
path/argv); the launcher binary + its config are **root-owned and non-writable** by the
recorder/executor/sidecar; before `exec` it **sanitizes** the environment, argv, open FDs
(closes all but the recorder-owned output pipe), and supplementary groups, and **drops all
capabilities**; it refuses any request to run a different target UID or executable. It
holds no signing key and performs no other action.

**Windows (P1-6).** The ratified base design requires a Windows **service SID / virtual
account** boundary; setuid is Linux-only. On Windows the equivalent is a **broker service**
under a distinct service SID that spawns the executor with a **restricted/lowbox token**
(dropped privileges, distinct SID, no read on the recorder key ACL), mirroring the fixed
caller/target/executable-digest contract above. **Until that Windows broker is separately
implemented + audited, governed real-mode is FAIL-CLOSED on Windows** (the desktop Blocks;
Windows is Linux-first per the base design), and 3b-1B ships the Linux launcher first.

**Authoritative containment verdict (P0-2) — no `sign(caller_claim)` oracle.** The final
`contained` verdict is known only after teardown; the runner never signs a supervisor
JSON claim. Because the **recorder owns the executor's `pidfd`/cgroup** (via the launcher
above), it performs the teardown/containment measurement itself and *measures* `contained`
firsthand before signing the containment artifact (§3.6) + the execution receipt. The
supervisor owns the lease + the governed-turn-record; the recorder owns the measured
containment; the launcher owns only the `setuid`. No principal signs an unmeasured claim.

**Exact output bytes (P0-2) — a byte-for-byte contract:** the governed-turn runner
1. captures the executor's reply from **stdout in BINARY mode** (`text=False`),
2. stores those **exact bytes** with **no decode / trim / newline (CRLF→LF) normalization**,
3. computes `output_sha256 = SHA256(exact bytes)`,
4. only THEN strict-UTF-8-decodes a copy for rendering.

The existing `bro_run_receipt.run_and_sign` transcript hash CRLF-normalizes (text mode),
so it is **not** byte-for-byte and is insufficient here. 3b-1B introduces a
**governed-turn-specific execution receipt** (a versioned `evidence-event` extension whose
`output_sha256` is over the exact binary bytes) so that **the bytes the desktop renders ==
`output_sha256` == the bytes bound by the signed receipt** — one source of the output, no
normalization drift.

## 2.5 Execution-attempt ownership (P1-5) — the SUPERVISOR reserves it

The desktop **never** supplies `execution_attempt_id`; and the request is **authenticated
by the desktop native host** (P0-1) and carries large inputs as **handles**, not inline
bytes (P1-3).

**Dedicated challenge-authority principal (P0-1) — NOT a payload oracle.** The sidecar is
compromised-in-scope (same login user); a challenge key held as an ordinary file/process
by that same principal is not a trust boundary. So the challenge is signed by a
**dedicated `desktop-challenge-authority`** — its own OS **service principal / SID** (or a
hardware/app-scoped key), distinct from the sidecar:
- its private key lives in an owner-only store the sidecar identity is **denied read +
  list** on; the sidecar **cannot `ptrace`/inspect** the authority process (distinct
  UID/SID + `ptrace_scope`);
- it is **not a `sign(payload)` oracle** — it accepts only a **protected pending-challenge
  ID**, reads the challenge bytes from **its own authoritative pending-challenge store**
  (which the desktop populated when it minted the Wave-3a one-time challenge), and **signs
  once** (marking the pending id consumed); it never signs caller-supplied bytes;
- **key id / rotation / revocation:** the challenge is signed under a `challenge_key_id`;
  the supervisor pins the current + a rotation window of challenge public keys (operator
  manifest, like the receipt keys, 3b-2), and a revoked `challenge_key_id` is refused;
- the sidecar's key-read/list, `ptrace`, and no-oracle denials are **machine-proven** in
  the Linux `engine-isolation` job.

**Signed challenge binds the FULL context incl. run/task (P0-2).** A challenge missing
`run_id`/`task_id` could be redirected to a different run on first use. The signed payload
therefore includes the run + record context identities — no caller-supplied unsigned
identity ever reaches the terminal record:

```jsonc
// brops.governed-turn-challenge.v1 (signed by the desktop-challenge-authority)
{ "payload": {
    "protocol": "brops.request.v1",
    "challenge_key_id": "<string>",
    "run_id": "<string>", "task_id": "<string>",
    "workspace_id": "…", "install_id": "…", "supervisor_id": "…",
    "request_nonce": "…",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>", "requested_at": "<ms>",
    "issued_at": "<ms>", "expires_at": "<ms>" },
  "sig": "<b64url Ed25519 over JCS(payload), challenge key>" }
```

The supervisor-service request is `{challenge}` alone — `run_id`/`task_id` come from INSIDE
the signature, not a bare sidecar field.

**Bounded ingress — ONE frozen mechanism (P1-4).** Linux production uses a **chunked
authenticated upload to the supervisor-owned staging store** (Windows real-mode is
fail-closed until its broker lands, §2). Frozen parameters:
- each upload chunk is a length-prefixed frame **≤ 256 KiB** (the base IPC cap); per
  artifact **≤ 8 MiB**; total per request **≤ 10 MiB** (system ≤256 KiB + history ≤8 MiB +
  generation_config ≤64 KiB, matching the Wave-3a request ceilings);
- chunks carry a **strictly-increasing sequence**; a duplicate or out-of-order sequence
  **aborts** the upload (fail-closed); the upload is **bound to the signed challenge**
  (`request_nonce` + `challenge_key_id`) and a per-session id — a chunk for another
  session/challenge is refused;
- the supervisor writes to a temp file via **`O_EXCL`**, streaming with the size cap;
  on the final chunk it **verifies size + sha256**, and **atomically commits** under the
  digest name (create-if-absent; an existing identical digest is idempotent success);
- the digest is the input's `*_sha256` handle; an incomplete upload leaves only the temp
  file, swept on **expiry** (`expires_at`) or crash; a per-install **quota** bounds staging
  disk; an upload whose committed handle does not match the signed challenge's `*_sha256`
  is refused.

The staging store is supervisor-owned (0700); the sidecar/executor have no read there.

**Flow (P0-1..P0-3, P1-3, P1-5) — the frozen order (see §4 for the full sign/publish order):**
1. **Verify the signed challenge** against the pinned `challenge_key_id` (not revoked);
   refuse an expired challenge (`now > expires_at`) or a replayed/consumed `request_nonce`
   (durable one-time ledger) — **before** any attempt reservation. `run_id`/`task_id` +
   all context identities are taken from INSIDE the signature.
2. **Import the input artifacts BEFORE execution** — read `system`/`history`/
   `generation_config` from staging **by handle** (confirming `sha256(bytes) == handle`),
   publish them into the protected store, and **recompute the FULL `request_sha256`** over
   the complete canonical envelope (`protocol, workspace_id, install_id, request_nonce,
   system_sha256, history_sha256, generation_config_sha256, requested_at`); refuse on any
   mismatch.
3. **Reserve the attempt + issue the lease** — atomically reserve/generate a one-time
   `execution_attempt_id` (a `run_id` cannot yield two live racing attempts) and
   `issue_lease` for it.
4. **Launch the recorder with the immutable input handles + read-only input FD(s)**; the
   recorder's launcher (§2) preserves ONLY the fixed input FD(s) + the output FD, so the
   **executor receives the exact verified bytes** on a read-only input FD and returns its
   exact output on the output FD — the executor never reads the store or the keys.
5. **Recorder publishes output + containment and signs** the receipt/evidence over those
   handles; **supervisor verifies by handle and signs** the terminal record (§4). The
   attempt id + verified request hashes + the challenge context are bound INTO the signed
   record; a caller cannot choose an arbitrary pre-existing attempt. The supervisor returns
   `{execution_attempt_id, governed-result}`.

## 3. `brops.governed-turn-record.v1` — the ONLY signing authority (exact signed schema)

Signed by the **dedicated `governed-turn-recorder`** authority (§8 — NOT the
evidence-recorder), `verify_artifact`-checkable, written atomically (create-if-absent, §4)
to the protected state dir as `<run_id>__<execution_attempt_id>.json`.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",
    "key_id": "<governed-turn-recorder key id>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    // lease binding (== the verified execution-lease)
    "lease_id": "<string>", "lease_nonce": "<string>",
    "task_id": "<string>", "agent_id": "<string>", "session_id": "<string>",
    "workspace_id": "<string>", "install_id": "<string>", "supervisor_id": "<string>",
    "executor_id": "<string>", "builder_id": "<string>", "runner_id": "<string>",
    // exact request binding (== the desktop-issued canonical request envelope, design §2.2)
    "request_nonce": "<string>",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>", "requested_at": "<ms>",
    "request_sha256": "<64hex>",           // == sha256(JCS(canonical request envelope))
    // desktop-authenticated challenge binding (P1-5): so LiveRunStateProvider can
    // INDEPENDENTLY re-verify the request fields came from a signed desktop challenge —
    // it fetches the signed challenge doc by handle, verifies its signature under
    // challenge_key_id (pinned), and cross-checks the envelope + request_sha256.
    "challenge_handle": "<64hex>",         // content-addressed store handle of {payload,sig}
    "challenge_key_id": "<string>",
    "challenge_issued_at": "<ms>", "challenge_expires_at": "<ms>",
    // output binding (the exact reply bytes; equals the receipt's transcript/stdout hash)
    "output_sha256": "<64hex>",
    // policy binding
    "policy_id": "<string>", "policy_version": "<string>", "policy_bundle_sha256": "<64hex>",
    // containment binding (== the hash carried by a signed evidence-chain event)
    "containment_evidence_sha256": "<64hex>", "containment_event_id": "<string>",
    // receipt binding (== the verified passing execution receipt)
    "receipt_id": "<string>",
    // evidence-head binding + anti-rollback (== the verified head)
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "completed_at": "<ms>", "issued_at_epoch": <int>
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```

All `*_sha256` are lowercase-64-hex; ids are strings; the signature is detached Ed25519
over `JCS(payload)` (the same canonicalizer as every other engine artifact).

## 3.5 `brops.governed-turn-execution-receipt.v1` — the exact-byte receipt (P1-4)

The existing `bro_receipt`/`run_and_sign` is a test-command receipt whose transcript hash
CRLF-normalizes (text mode) — insufficient here. 3b-1B adds a **governed-turn-specific**
receipt with a byte-for-byte output contract, signed by the **evidence-recorder runner**.

```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-execution-receipt.v1",
    "key_id": "<evidence-recorder key id>",         // the recorder RUNNER signs
    "receipt_id": "<string>",                        // the record + binding table cite this
    "run_id": "<string>", "execution_attempt_id": "<string>", "lease_id": "<string>",
    "runner_id": "<string>", "executor_id": "<string>", "builder_id": "<string>",
    "exit_code": 0, "contained": true,
    "output_handle": "<64hex>",        // content-addressed store handle of the exact reply
    "output_sha256": "<64hex>",        // == output_handle == SHA256(exact BINARY reply bytes)
    "started_at_epoch": <int>, "finished_at_epoch": <int>, "issued_at_epoch": <int>
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```

- **Signed bytes:** detached Ed25519 over `JCS(payload)`.
- **Output-byte formula (normative):** `output_sha256 = SHA256(exact reply bytes)` where the
  bytes are captured in **binary** with NO decode/trim/CRLF normalization; `output_handle`
  is the content-addressed store handle of those exact bytes (so `output_handle ==
  output_sha256`, and the desktop re-hashes the SAME bytes it renders).
- **Fields/types:** ids are non-empty strings ≤128; `exit_code` an integer (must be `0`);
  `contained` a bool (must be `true`); the two handle/hash fields lowercase-64-hex;
  timestamps integer epochs with `started ≤ finished`.
- **Authority mapping:** `ARTIFACT_AUTHORITY["brops.governed-turn-execution-receipt.v1"] =
  evidence-recorder`; `verify_artifact` refuses any other signer.
- **Verifier contract (dedicated API, not the generic `verify_passing_receipt`):**
  `verify_governed_turn_receipt(document, keys, *, run_id, execution_attempt_id, lease_id,
  output_bytes, now) -> payload` — `verify_artifact` the receipt, require `exit_code == 0`
  and `contained is True`, require the run/attempt/lease ids to match, and require
  `output_sha256 == SHA256(output_bytes) == output_handle`. Any deviation is fail-closed.

## 3.6 `brops.governed-turn-containment.v1` — attempt-bound containment (P1-4)

The existing evidence event binds only `task_id`/`event_type`/`agent_id`/`payload_hash` —
NOT the attempt or lease, so a containment event from another attempt could be cited. 3b-1B
defines an explicit **containment artifact** the recorder produces from its firsthand
teardown measurement (§2), publishes to the content-addressed store, and records as a
**containment-confirmed evidence event** whose `payload_hash` is over this artifact:

```jsonc
{ "artifact_type": "brops.governed-turn-containment.v1",
  "run_id": "<string>", "execution_attempt_id": "<string>", "lease_id": "<string>",
  "runner_id": "<string>",
  "cgroup_id": "<string>",              // the executor's cgroup v2 path/id (Linux)
  "process_group_id": "<string>",       // the executor's PGID (both are recorded, not "or")
  "contained": true,                    // MUST be true for an accepted record
  "teardown_outcome": "contained",      // closed enum: exactly one of
                                        //   "contained" | "orphan-quarantined" | "timed-out" | "failed"
  "measured_at": <int> }                // epoch ms
```

`teardown_outcome` is a **closed** enum — `contained | orphan-quarantined | timed-out |
failed`; only `contained` (with `contained: true`) yields an accepted record. Both
`cgroup_id` and `process_group_id` are always present (the recorder owns both).

- **Canonical bytes:** `JCS(artifact)`; `containment_evidence_sha256 = SHA256(JCS(artifact))`
  is the store handle and the value in the governed-turn-record.
- **Evidence binding:** the recorder writes a **containment-confirmed** evidence event
  whose `payload_hash == containment_evidence_sha256`, chained + head-anchored as usual.
- **Verifier cross-bind:** `LiveRunStateProvider` requires the containment artifact's
  `run_id`/`execution_attempt_id`/`lease_id`/`runner_id` to **equal** the
  governed-turn-record's, `contained == true`, and the referenced evidence event's
  `payload_hash` to equal `containment_evidence_sha256` — so a containment measurement from
  a different attempt/lease can never be substituted.

## 4. Ownership + atomic order — ONE flow (P0-2, no partial)

Ownership is split by principal and the publication order is fixed so that whoever SIGNS
an artifact is whoever PRODUCED + published its bytes (nobody signs handles they did not
publish):

1. **Supervisor imports the INPUTS first (before execution).** After verifying the signed
   challenge (§2.5), from staging it **atomically publishes** `system`/`history`/
   `generation_config` (+ the `policy_bundle` it holds) into the protected store — the
   inputs exist as content-addressed handles *before* anything runs. The supervisor never
   publishes output/containment (the recorder owns those).
2. **Reserve attempt + issue lease**, then **launch the recorder** handing it the immutable
   input handles + **read-only input FD(s)** (via the launcher, §2), so the executor
   receives the exact verified bytes on a read-only FD and returns output on the output FD
   (it reads neither the store nor the keys).
3. **Recorder captures + publishes what IT owns + signs over those handles.** The recorder
   reads the executor's exact reply bytes (binary, §2), measures `contained` at teardown,
   **atomically publishes** the `output` bytes + the `brops.governed-turn-containment.v1`
   artifact (§3.6) → `output_handle` + `containment_evidence_sha256`, and signs the
   `brops.governed-turn-execution-receipt.v1` (§3.5, over `output_handle`) + the
   containment-confirmed evidence event + head (evidence-recorder key) — so every handle it
   signs refers to bytes it itself published (no forward reference).
4. **Supervisor verifies the recorder's chain by handle.** `verify_artifact` the lease;
   `verify_governed_turn_receipt` (§3.5 — reads `output` from the store by handle,
   re-hashes, checks exit 0 + `contained` + run/attempt/lease); `load_head` +
   `validate_chain`; confirm the containment artifact cross-binds (§3.6). Any failure ⇒ no
   record.
5. **Supervisor constructs + signs the terminal record** with the **dedicated
   governed-turn-recorder** key (§8), binding every handle/id/hash from the VERIFIED
   artifacts + the signed challenge (§5) — never a caller input.
6. **Atomic write, idempotent create-if-absent (P1-4):** temp file in the state dir →
   `fsync` → **`os.link` / `O_CREAT|O_EXCL`** into `<run_id>__<execution_attempt_id>.json`
   (create-if-absent, never a clobbering rename). On `EEXIST`: read + **byte-compare**;
   identical ⇒ idempotent success, any difference ⇒ **refuse**. Finally `fsync` the dir.

**Store ACL (P0-2):** the protected store is writable only by the **recorder** (output +
containment) and the **supervisor** (its imported artifacts); the **executor** and the
**sidecar** have **no write** (and no read of keys). Both service principals are in the
shared store group (as 3b-1A), but the executor/sidecar principals are not.

**Ordering guarantees:** the INPUTS exist in the store before execution (step 1 before
step 2), so the executor runs on already-published verified bytes; each signer signs only
handles it published (recorder step 3; supervisor its inputs in step 1 + the record in
step 5); the record is signed before it is visible (5 before 6); a crash before step 6
leaves **no** record (the turn is unattestable ⇒ the desktop Blocks); a crash after leaves
a complete, signed, re-verifiable record. Create-if-absent + byte-compare makes a re-run
idempotent and a divergent overwrite impossible.

## 5. Bindings (each cross-checked by `LiveRunStateProvider`, verifying the SIGNED record)

`LiveRunStateProvider` first `verify_artifact(record, "brops.governed-turn-record.v1")`
(a forged/edited record fails here — no unsigned JSON is authority), then requires:

| Field | Bound to |
|---|---|
| `request_nonce`, `system_sha256`, `history_sha256`, `generation_config_sha256`, `requested_at`, `request_sha256` | independently re-verified: fetch the signed challenge by `challenge_handle`, verify its `sig` under the pinned `challenge_key_id` (§2.5), confirm `now` is within `challenge_issued_at`/`challenge_expires_at`, and that its `run_id`/`task_id`/`workspace_id`/`install_id`/`request_nonce`/`*_sha256`/`requested_at` equal the record's + `request_sha256 == sha256(JCS(envelope))` |
| `execution_attempt_id`, `run_id` | the requested handle |
| `lease_id`, `lease_nonce` | the verified execution-lease (`verify_artifact` + `validate_execution_lease`) |
| `policy_id`, `policy_version`, `policy_bundle_sha256` | the operator-authorized policy (the signer re-checks bundle digest, P1-7) |
| `containment_evidence_sha256` + `containment_event_id` | the `brops.governed-turn-containment.v1` artifact (§3.6) whose `run_id`/`execution_attempt_id`/`lease_id`/`runner_id` equal the record's + `contained==true`, recorded as a containment-confirmed evidence event whose `payload_hash == containment_evidence_sha256` |
| `receipt_id`, `output_sha256` | the verified governed-turn execution receipt (§3.5): receipt/attempt/lease ids match; the exact output bytes re-hash to `output_sha256 == output_handle` (binary, no normalization) |
| `task_id`, `evidence_final_event_hash`, `evidence_head_sequence` | the verified evidence head, authenticated via the supervisor attestation (§6 P1-5), with the sequence checked against the durable **per-(install, task/chain)** high-water mark (§6 P1-2, P1-6 anti-rollback) |

The `RunState` is built from the **verified signed record** only.

## 6. Replay / idempotency + crash-recovery

- **Whole-turn replay:** the desktop's one-time `request_nonce` (migration 0014, durable)
  is compare-and-consumed at verify time; a completed turn's receipt cannot be re-accepted
  (`receipt_id` global uniqueness). The signed record's `request_nonce` must equal the
  desktop challenge.
- **Evidence-head rollback floor — owner + transaction (P1-6, LOCKED):**
  - **Authority + scope (P1-2):** a durable high-water mark **per evidence chain** in the
    desktop's SQLite (`brops-core`) —
    `evidence_head_floor(install_id, task_id, highest_sequence, final_event_hash,
    PRIMARY KEY (install_id, task_id))` (equivalently keyed by the chain's immutable
    `chain_id`). The floor is **per (install, task/chain)**, NOT per-install: each task is a
    separate evidence chain whose `head_sequence` restarts, so an install-wide row would
    wrongly flag task B's sequence 1 as a rollback of task A's sequence 5. The DESKTOP is
    the anti-rollback authority (the verifier of record), not a loose engine-side file.
  - **Who updates:** the **desktop verify transaction** reads + checks + advances the floor
    **inside the same `BEGIN IMMEDIATE` transaction** that consumes the nonce and persists
    the attempt (the Wave-3a `verify_and_record_receipt` tx) — so acceptance and the floor
    advance are one atomic unit. The engine supervisor never writes the desktop floor.
  - **CAS / concurrency:** single-writer under `BEGIN IMMEDIATE`; a record with
    `evidence_head_sequence < highest_sequence`, or `== highest_sequence` with a different
    `final_event_hash`, is **refused**; a strictly-greater sequence advances the floor.
  - **Crash sync:** the floor advance and the accepted-attempt row commit together; a crash
    before COMMIT leaves both unchanged (the turn Blocks); after COMMIT both are durable and
    consistent — a stolen older signed head can never be re-accepted.
  - **Authenticated relay of the head fields (P1-5, LOCKED):** the desktop floor needs
    `task_id` + `evidence_head_sequence` + `evidence_final_event_hash` to be **authenticated**
    (they are in the SIGNED governed-turn-record, but today's forensic bridge relay carries
    only run/attempt/lease ids + the attestation blob). Lock the extension chain so the head
    fields reach the desktop verify tx inside supervisor-attested evidence:
    - **sign-request evidence** (`brops.sign-request.v1`, design §4.1) gains
      `task_id`, `evidence_head_sequence`, `evidence_final_event_hash` — so the supervisor
      **attestation** (`brops.run-attestation.v1`) covers them (JCS(evidence));
    - **sign-result** (`brops.sign-result.v1`, §4.2) echoes them into the forensic record
      alongside run/attempt/lease;
    - **bridge-result** `receipt` relays them (`task_id`, `evidence_head_sequence`,
      `evidence_final_event_hash`), and they equal the governed-turn-record's;
    - **desktop verification source:** the desktop `verify_and_record_receipt` tx re-verifies
      the supervisor attestation (against the manifest attestation key, 3b-2), reads these
      authenticated head fields, and advances `evidence_head_floor` from them — the floor is
      driven only by supervisor-attested values, never a bare bridge claim.
- **Idempotent record:** the record is keyed by `(run_id, execution_attempt_id)`; a second
  atomic write for the same attempt is allowed only if byte-identical, else refused. The
  content-addressed store is idempotent by construction.
- **Crash recovery:** a crash before the record's create-if-absent publish (§4 step 5) ⇒
  no record ⇒ the turn Blocks (fail-closed; nothing renders). A crash after ⇒ a complete
  signed record that re-verifies on restart. No reconciliation can turn a partial run into
  an accepted one.

## 7. No unsigned JSON is authority (explicit)

The pre-3b-1B code path where `LiveRunStateProvider` trusted a pre-written **unsigned**
record's `system`/`history`/`output`/`nonce`/policy/containment fields is **removed**. The
sole authority is the SIGNED `brops.governed-turn-record.v1` plus the independently-verified
lease / receipt / evidence — every field is cross-checked (§5). An attacker who can write
the state dir but cannot mint the **governed-turn-recorder** signature (§8, its key
owner-only to the recording boundary) cannot forge an accepted run.

## 8. Authorities (no parallel executor) + LOCKED terminal-record authority (P1-3)

**Terminal-record signing authority — LOCKED to a dedicated `governed-turn-recorder`**
(not the evidence-recorder, so the recording boundary does not gain the evidence-recorder's
full receipt/evidence-head forgery capability):
- add `GOVERNED_TURN_RECORDER = "governed-turn-recorder"` to the engine authority types
  (`bro_signature` `AUTHORITY_TYPES` / `broctl` key classes);
- map `brops.governed-turn-record.v1` in `ARTIFACT_AUTHORITY` to **only** this authority;
- its private key lives at the supervisor/recording boundary (its own owner-only custody),
  distinct from the evidence-recorder and issuer keys;
- it can sign **only** the governed-turn-record — it MUST NOT be an allowed signer for
  `evidence-event`, `evidence-head`, or `execution-lease`. `verify_artifact` therefore
  refuses a governed-turn-record signed by any other authority, and refuses a
  receipt/evidence-head signed by the governed-turn-recorder.

**Reused authorities (unchanged):**
- **Lease:** `bro_supervisor.issue_lease` (issuer) + `bro_execution_lease.validate_execution_lease`.
- **Containment:** `bro_supervisor.spawn_builder`'s process-group containment verdict + the
  containment evidence event.
- **Receipt:** the **`brops.governed-turn-execution-receipt.v1`** (§3.5) — a NEW
  governed-turn artifact signed by the **evidence-recorder RUNNER** (not the model
  executor, not the generic test-command `run_and_sign`), verified by the dedicated
  **`verify_governed_turn_receipt`** (§3.5), NOT `verify_passing_receipt`.
- **Containment + evidence:** the **`brops.governed-turn-containment.v1`** artifact (§3.6)
  recorded as a containment-confirmed `bro_evidence` event + head (evidence-recorder),
  measured firsthand by the recorder (§2).

## 9. Acceptance (for 3b-1B implementation, after this addendum is GREEN)

Positive: a real desktop→sidecar→supervisor(execute+record)→signer E2E yielding a `signed`
governed-result whose receipt binds the exact request + output; the Linux isolation job's
positive control uses a genuinely-executed record. Negative: forged/edited record, replayed
old evidence head, output/containment/nonce not matching the signed artifacts, missing
lease/receipt — all fail-closed. Engine + isolation exact-head CI GREEN.

**Ask:** Architect-GREEN on (a) the AI-turn-as-supervised-execution topology (§1–§2),
(b) the `brops.governed-turn-record.v1` schema + atomic order (§3–§4), (c) the binding +
anti-rollback + replay/crash model (§5–§6), and (d) the authority for signing the terminal
record (§8) — before any 3b-1B code.
