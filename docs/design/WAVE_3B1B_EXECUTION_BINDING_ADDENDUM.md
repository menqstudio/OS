# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 9)

> **STATUS: ❌ DESIGN RED — NOT Architect-GREEN. 3b-1B code has NOT started.** The Architect
> reviewed **rev 8** (at exact HEAD `59a7f044af69951fb72aa0434b289392c4f61104`, with
> exact-head CI **#112** fully GREEN — **CI GREEN ≠ design GREEN**) and returned **Design RED**
> with **1 P0 + 3 P1 schema/atomicity blockers** (rev 8 correctly closed the pending-store
> direct-tampering boundary and the input-FD framing/size contradiction; four narrower
> contracts remained). **rev 9 (this document)** is the implementer's **proposed** closure of
> those four — it is **awaiting Architect design review** and is **NOT ratified**. The
> rev-8 → rev-9 blockers were: **P0-1** `challenge_accepted_at` was bound only in prose, not
> through exact **signed schemas** (the strict `execution-lease` and `brops.sign-request.v1`
> don't define it) → a versioned **`brops.governed-turn-lease.v1`** + a sign-request
> evidence extension carry it, with a frozen field-type/signed-byte formula, `issue_lease` /
> `validate_execution_lease` contract, a **byte-equality chain** across challenge → lease →
> attestation → sign-result → bridge → record, and mismatch/replay/clock negative tests
> (§2.6); **P1-2** the registry handle hashed only `JCS(payload)`, violating the
> protected-store law that a handle == `SHA256(exact stored bytes)` → **`registry_hash =
> SHA256(JCS(payload))`** (fork/epoch identity) is now split from **`challenge_registry_handle
> = SHA256(JCS({payload, root_sig}))`** (exact stored document), and the record binds the
> exact-document handle (§2.5, §3, §5); **P1-3** snapshot publication and floor advance were
> separable (a floor advance then a missing snapshot could brick recovery) → ONE
> crash-consistent sequence (verify → create-if-absent publish + `fsync` file & dir → durable
> floor tx persisting epoch/hash/handle/root → never expose a floor whose snapshot is
> absent/mismatched → crash-recovery at every cut point) (§2.5); **P1-4** historical
> verification only checked key *presence* → it now repeats the **complete key-validity
> predicate as of `challenge_accepted_at`** (exists once, schema, `key_epoch`, `valid_from ≤
> challenge_accepted_at ≤ valid_to`, `revoked_at` null-or-after, `sig` under that exact
> snapshot key, root sig + exact-document handle) (§2.5, §5). **These four remain OPEN until
> the Architect returns design-GREEN** — see `NEXT_CHAT.md` §3.3. Do not treat any part of this
> document as ratified until that GREEN. STOP gates: `NoTrustedManifest` unchanged, no
> production "Verified", 3b-2/3b-3 not started, PR #31 not merged.
>
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
>
> **rev 7** closes the narrow design RED on rev 6 (2 P0 + 3 P1 consistency blockers): **P0-1** the challenge-authority input path can no longer become a two-step `create_pending(bytes)→sign(id)` oracle — the authority **builds** the challenge from the **trusted desktop database** (caller supplies only an ID, never bytes) and the pending-challenge row is written **only by the app/package-identity-authenticated desktop host**, a channel the same-login sidecar lacks; the sidecar's inability to create a pending row or sign caller-chosen bytes is machine-proven (§2.5); **P0-2** the launcher FD contract is now ONE canonical table — FDs `3`/`4`/`5` read-only `system`/`history`/`generation_config` + FD `6` write-only output, validate modes, close every other — replacing the contradictory "close all but the output pipe" wording (§2, §2.5 step 4, §4 step 2); **P1-3** the **supervisor** is the sole publisher of the exact canonical signed challenge document with `challenge_handle = SHA256(JCS({payload,sig}))`, published in §4 step 1 and required to exist + re-hash before the record is signed (§3, §4); **P1-4** challenge-key trust no longer depends on the un-started 3b-2 manifest — a **self-contained 3b-1B root-pinned `brops.challenge-key-registry.v1`** (binary-pinned challenge-root anchor in the supervisor config) resolves `challenge_key_id` in-tx, removing the sequencing deadlock (§2.5); **P1-5** historical re-verification no longer breaks at challenge expiry — acceptance-time requires `now ∈ [issued_at, expires_at]`, but durable re-verification checks the **as-of-run** predicate `issued_at ≤ requested_at ≤ expires_at` and evaluates revocation **as of `requested_at`**, so a valid completed run stays verifiable forever (§5).
>
> **rev 8** closes the deeper-consistency design RED on rev 7 (2 P0 + 2 P1): **P0-1** "trusted desktop database" is not a real boundary between two same-UID Linux processes (a same-login sidecar RCE could edit the SQLite/store file directly) — the pending-challenge store is now **owned by a dedicated challenge-authority principal/UID** (`0700`, sidecar UID has no r/w/list), rows are created **only over an `SO_PEERCRED` channel admitting a UID distinct from the sidecar** (fail-closed where a platform can't separate the UIDs), and Linux CI proves the **direct file/DB-mutation** denial in addition to the API-insert denial (§2.5); **P0-2** the historical timestamp predicate used the wrong field (`issued_at ≤ requested_at` can never hold — `requested_at` precedes `issued_at`) — a **supervisor-stamped `challenge_accepted_at`** (bound to lease + record + attestation) is now the checked field: acceptance and re-verification require `requested_at ≤ challenge_accepted_at` and `issued_at ≤ challenge_accepted_at ≤ expires_at`, revocation as of `challenge_accepted_at` (§2.5 step 3, §3, §5); **P1-3** the challenge-key registry gains a **full durable trust contract** — normative top-level `brops.challenge-key-registry.v1` (schema + `registry_epoch`/`registry_hash`/`root_key_id`, JCS wire, same-epoch/different-hash rejection, durable anti-rollback floor, accepted-snapshot publication), with `challenge_registry_handle`/`challenge_registry_epoch`/`challenge_registry_root_key_id` **bound into the record** and re-verified from the stored snapshot so rotation never breaks a historical record (§2.5, §3, §4, §5); **P1-4** the input-FD framing/size contradiction is removed — FDs `3`/`4`/`5` are **read-only regular-file descriptors to the exact content-addressed bytes** (no u32 length prefix; the 256 KiB frame belongs only to the IPC/ingress path), launcher-validated (regular file, `O_RDONLY`, offset 0, per-artifact size ceiling incl. history ≤ 8 MiB, store-owned inode), read to EOF (§2).
>
> **rev 9** closes the schema/atomicity design RED on rev 8 (1 P0 + 3 P1; rev 8 was reviewed at HEAD `59a7f04`, exact-head CI #112 GREEN — CI GREEN ≠ design GREEN): **P0-1** `challenge_accepted_at` is now **machine-bound through exact signed schemas**, not prose — a versioned **`brops.governed-turn-lease.v1`** (superset of the strict base lease) carries it, the **`brops.sign-request.v1`** governed-turn attestation evidence + **`brops.sign-result.v1`** relay + bridge result carry it, with a frozen field-type/signed-byte formula, `issue_lease`/`validate_execution_lease` contract, a **byte-equality chain** challenge → lease → attestation → sign-result → bridge → record, refusal on any mismatch, and replay/backdating/expiry/clock-boundary negative tests (§2.6, §3, §5); **P1-2** the registry digest is split to obey the protected-store law — **`registry_hash = SHA256(JCS(payload))`** (fork/epoch identity, anti-rollback) vs **`challenge_registry_handle = SHA256(JCS({payload, root_sig}))`** (exact stored document bytes); the record binds the exact-document handle + `challenge_registry_hash`, and re-verification fetches the full doc by handle, re-hashes it, verifies `root_sig` over `JCS(payload)`, then recomputes `registry_hash` (§2.5, §3, §4, §5); **P1-3** snapshot publication + floor advance are ONE **crash-consistent** recoverable sequence (verify → create-if-absent publish + `fsync` file & dir → durable floor tx persisting `(epoch, registry_hash, handle, root_key_id)` → a floor is never usable unless its snapshot exists + re-hashes → crash-recovery at every cut point → same-epoch/different-hash + divergent-handle refused), so a floor advance with a missing snapshot is impossible (§2.5); **P1-4** historical verification repeats the **complete key-validity predicate as of `challenge_accepted_at`** (key present exactly once, `public_key` schema valid, `key_epoch` accepted, `valid_from ≤ challenge_accepted_at ≤ valid_to`, `revoked_at IS NULL OR > challenge_accepted_at`, challenge `sig` valid under that exact snapshot key, root sig + exact-document handle valid) — presence alone is insufficient (§2.5, §5).

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
recorder/executor/sidecar; before `exec` it **sanitizes** the environment, argv,
supplementary groups, and open FDs per the **canonical FD contract below**, and **drops all
capabilities**; it refuses any request to run a different target UID or executable. It
holds no signing key and performs no other action.

**Canonical launcher FD contract (P0-2, LOCKED — ONE table, resolving the earlier "close
all but the output pipe" wording).** The executor consumes the three exact input artifacts
on read-only FDs and writes only its reply — so the launcher preserves a **fixed, closed
set of FDs and closes every other**, rather than "all but the output pipe". The recorder
sets these up (from the store handles it received, §2.5 step 4) and the launcher validates
+ preserves exactly them:

| FD | Role | Mode (validated) | Source |
|---|---|---|---|
| `3` | `system` bytes | **read-only regular file** (`O_RDONLY`, `S_ISREG`, offset 0, size ≤ **256 KiB**) | recorder `open()`s the published `system` store artifact read-only |
| `4` | `history` bytes | **read-only regular file** (`O_RDONLY`, `S_ISREG`, offset 0, size ≤ **8 MiB**) | recorder `open()`s the published `history` store artifact read-only |
| `5` | `generation_config` bytes | **read-only regular file** (`O_RDONLY`, `S_ISREG`, offset 0, size ≤ **64 KiB**) | recorder `open()`s the published `generation_config` store artifact read-only |
| `6` | `output` pipe | **write-only** (`O_WRONLY`) | recorder-owned output pipe |

- **The input FDs are read-only regular-file descriptors to the EXACT content-addressed
  store bytes — NO framing prefix (P1-4, resolves the earlier "u32-framed 256 KiB"
  contradiction).** The u32-length-frame + 256 KiB cap belongs only to the **IPC / bounded
  ingress** path (§2.5) where messages arrive over a socket; the executor instead reads a
  **plain file** whose bytes ARE the hashed artifact, so a `history` up to its **8 MiB**
  per-artifact ceiling is delivered without any 256 KiB frame limit and without a length
  prefix that would otherwise be part of (and corrupt) the hashed content. Each FD's bytes,
  read `[0, EOF)`, re-hash to exactly the published `*_sha256` handle.
- The launcher **validates**, per the table, that FDs `3`/`4`/`5` are **`O_RDONLY` regular
  files at offset 0 whose size is ≤ the per-artifact ceiling** and whose backing inode is a
  file **owned by the supervisor in the protected store** (not a sidecar/executor-writable
  path, not a pipe/fifo/device/symlink), that FD `6` is `O_WRONLY`, then **closes every FD
  ≥ 7 and any of 0/1/2 not explicitly remapped**, and `setuid(executor) + exec`. The
  executor therefore has **exactly** the three read-only input files + the one write-only
  output FD — nothing else (no key FD, no store-dir FD, no extra inherited descriptor);
  it reads each input to **EOF**. This is the single normative statement; §2.5 step 4 and
  §4 step 2 reference this table.

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
- it is **not a `sign(payload)` oracle AND not a two-step `create_pending(bytes)→sign(id)`
  oracle (P0-1, LOCKED).** The threat: if any caller could populate the pending-challenge
  store with **caller-chosen bytes** and then ask the authority to sign that id, a
  compromised sidecar would have a two-step forgery oracle
  (`create_pending(attacker_payload) → sign(pending_id)`). This is closed by **removing the
  caller-bytes path entirely**:
  - **The authority CONSTRUCTS the challenge itself; the caller supplies only an ID, never
    bytes.** The `desktop-challenge-authority` reads the authoritative turn facts
    (`run_id`/`task_id`/context ids/`request_nonce`/the three `*_sha256`/`requested_at`)
    **directly from the trusted desktop database** — the same Wave-3a governed-turn /
    one-time-challenge tables the desktop authority owns — keyed by the pending-challenge
    ID, **builds** the `brops.governed-turn-challenge.v1` payload from those trusted rows,
    stamps `issued_at`/`expires_at`, and signs once (marking the id consumed). It **never
    accepts, stores, or signs caller-supplied challenge bytes/fields.**
  - **The pending-challenge store is OWNED by the challenge-authority principal; both the
    API-insert AND the direct-file-mutation paths are closed (P0-1, LOCKED for Linux).**
    "App/package identity" is a Windows/macOS notion and is **NOT** a boundary between two
    processes sharing one Linux UID — a same-login sidecar RCE (in scope) could otherwise
    just edit the SQLite/store file the desktop wrote. So the boundary is an **OS-identity**
    one, made concrete on Linux:
    - the pending-challenge store (the rows the authority reads its facts from) is a store
      **owned by the `desktop-challenge-authority`'s own dedicated principal/UID**, mode
      `0700`; the **sidecar UID has no read / write / list** on it — it can neither inject a
      row nor tamper the file/DB, so "read facts from a trusted store" is now backed by real
      file ownership, not trust-by-convention;
    - a pending-challenge row is created **only over an OS-authenticated creation channel**
      (an `AF_UNIX` socket the authority owns, admitting via `SO_PEERCRED` **only the desktop
      UI principal's UID**, which **must be a UID distinct from the sidecar**); the authority
      writes the row into its own store **itself** from the authenticated request — it never
      ingests a file some other principal wrote;
    - **platform gate (fail-closed):** this requires the desktop-UI/authority side to run
      under a principal **distinct from the sidecar UID**. Where a platform cannot yet
      provide that separation (e.g. desktop UI and sidecar forced to share a login UID),
      governed real-mode is **FAIL-CLOSED** there (mirroring the Windows-broker stance, §2) —
      never silently same-UID. 3b-1B ships the Linux dedicated-principal path first.
    A compromised sidecar can neither call the create channel (peer-UID denied) nor mutate
    the store directly (file-ownership denied); the most it can present is an **ID whose
    bytes it did not choose**, yielding a challenge over the authority's own trusted facts.
  - **Machine-proven (extended, P0-1):** the Linux `engine-isolation` job proves the sidecar
    principal cannot (a) read/list the authority key dir, (b) `ptrace` the authority,
    (c) create a pending-challenge record **via the authenticated channel** (peer-UID
    denied), (d) **directly read / write / list / mutate the pending-challenge store file(s)
    or DB** to inject or alter a row, or (e) obtain a signature over caller-chosen bytes;
    only a desktop-authority-created ID signs, and only over authority-built bytes;
- **key id / rotation / revocation — a SELF-CONTAINED 3b-1B challenge-key registry with a
  FULL durable trust contract (P1-3, LOCKED; NO dependency on 3b-2).** The challenge is
  signed under a `challenge_key_id` resolved against a **3b-1B-local, root-pinned
  challenge-key registry** — it does **not** depend on the 3b-2 operator receipt-key
  manifest (the STOP law forbids starting 3b-2 until all of 3b-1 is GREEN + merged; sourcing
  challenge trust from 3b-2 would be a sequencing deadlock). The registry is a normative,
  durably-anchored, snapshot-bound artifact — not just a `keys[]` list:
  - **Normative top-level schema `brops.challenge-key-registry.v1` (signed document):**
    ```jsonc
    { "payload": {
        "artifact_type": "brops.challenge-key-registry.v1",
        "root_key_id": "<challenge-root anchor id>",
        "registry_epoch": <int>,               // monotonically increasing
        "issued_at": "<ms>",
        "keys": [ { "challenge_key_id": "<string>", "public_key": "<b64url>",
                    "valid_from": "<ms>", "valid_to": "<ms>",
                    "key_epoch": <int>, "revoked": false, "revoked_at": null } ] },
      "root_sig": "<b64url Ed25519 over JCS(payload), by the pinned challenge-root>" }
    ```
    the signed bytes are detached Ed25519 over `JCS(payload)`.
  - **TWO distinct digests — payload hash vs exact-document store handle (P1-2, LOCKED).**
    The protected-store law is that a handle == `SHA256(exact stored bytes)` and one handle
    can never name other bytes. The signed registry document is the full `{payload,
    root_sig}` (that is what is stored), so:
    - **`registry_hash = SHA256(JCS(payload))`** — the *fork/epoch identity* used only for
      anti-rollback (same-epoch/different-hash detection). It is over `payload` alone so two
      documents that differ only in `root_sig` re-encoding still collide on epoch identity.
    - **`challenge_registry_handle = SHA256(JCS({payload, root_sig}))`** — the *exact stored
      document bytes*, used for protected-store lookup and terminal-record binding.
    These are different values; the record binds the **exact-document handle**, and
    `registry_hash` is a **separate** field (bound in the record + stored in the floor).
  - **Binary-pinned root:** `root_key_id` selects a **challenge-root anchor baked into the
    supervisor config** (root-owned, non-writable by recorder / executor / sidecar) — a
    **separate root + separate registry** from the receipt keys; an unknown/unpinned
    `root_key_id` is refused.
  - **Crash-consistent publish + floor advance — ONE recoverable sequence (P1-3, LOCKED).**
    The accepted snapshot and the anti-rollback floor are **not** independent operations; a
    floor advance followed by a missing snapshot must be **impossible**. The exact order is:
    1. **strict-parse + fully verify** the root-signed registry (`root_key_id` pinned;
       `root_sig` valid over `JCS(payload)`; schema exact);
    2. **atomically create-if-absent publish the exact signed document** (`{payload,
       root_sig}`) into the protected store under `challenge_registry_handle`
       (temp→verify size+sha256→`os.link`/`O_EXCL`; an existing identical handle is
       idempotent success; a **divergent existing handle is refused**);
    3. **`fsync` the snapshot file AND the protected-store directory**;
    4. **inside the durable floor transaction**, persist `(highest_registry_epoch,
       registry_hash, challenge_registry_handle, root_key_id)` — advancing the floor;
    5. **the new floor is never exposed/accepted unless its referenced snapshot exists and
       re-hashes** to `challenge_registry_handle`; a `registry_epoch < floor.epoch`, or
       `registry_epoch == floor.epoch && registry_hash != floor.hash` (fork), is **refused**;
    6. **crash recovery at every cut point:** a crash before step 4 leaves the floor
       unchanged (the snapshot is an orphan, swept); a crash after step 4 is safe because the
       snapshot was durably published + fsynced in steps 2–3 *before* the floor advanced; at
       startup the supervisor verifies the floor's referenced snapshot exists + re-hashes
       before treating the floor as usable, else it refuses (fail-closed) rather than
       bricking. (An explicit journal/state-machine providing the identical guarantee is an
       allowed implementation.)
  - **Resolve in-tx:** with the snapshot published + floor advanced, the supervisor resolves
    `challenge_key_id` in-tx against the accepted snapshot (the full **key-validity
    predicate** in the re-verification bullet below); revoked/out-of-window/unknown refused
    at acceptance.
  - **Bound into the terminal record + full historical predicate (P1-4, LOCKED).** The record
    binds `challenge_registry_handle` / `challenge_registry_hash` / `challenge_registry_epoch`
    / `challenge_registry_root_key_id` (§3). Durable re-verification fetches **that stored
    snapshot by `challenge_registry_handle`** (not the current live registry),
    **re-hashes the full stored document** (`== challenge_registry_handle`), verifies its
    `root_sig` over `JCS(payload)` under the pinned `challenge_registry_root_key_id`,
    **recomputes `registry_hash = SHA256(JCS(payload))`** (`== challenge_registry_hash`), and
    then re-checks the **complete key-validity predicate as of `challenge_accepted_at`** — it
    is **not** enough that the key is merely present:
    - `challenge_key_id` **exists exactly once** in the snapshot;
    - the key/`public_key` schema is valid; `key_epoch` is accepted;
    - `valid_from ≤ challenge_accepted_at ≤ valid_to`;
    - `revoked == false` as of acceptance, i.e. `revoked_at IS NULL OR revoked_at >
      challenge_accepted_at`;
    - the signed challenge's `sig` verifies **under that exact snapshot key**;
    - the registry `root_sig` + the exact-document handle are valid.
    So a key later rotated out of the live registry still verifies from the stored snapshot,
    and a key that was invalid/revoked *at acceptance* is refused even if it looks fine now.
  - this registry ships and is bootstrapped **in 3b-1B**; when 3b-2 later lands the operator
    manifest, migrating challenge keys onto it is an explicit **future** step, never a
    prerequisite for 3b-1B;
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
1. **Verify the signed challenge** against the `challenge_key_id` resolved from the
   root-signed challenge-key registry (not revoked as of now); refuse an expired challenge
   (`now > expires_at`) or a replayed/consumed `request_nonce` (durable one-time ledger) —
   **before** any attempt reservation. `run_id`/`task_id` + all context identities are taken
   from INSIDE the signature.
2. **Import the input artifacts BEFORE execution** — read `system`/`history`/
   `generation_config` from staging **by handle** (confirming `sha256(bytes) == handle`),
   publish them into the protected store, and **recompute the FULL `request_sha256`** over
   the complete canonical envelope (`protocol, workspace_id, install_id, request_nonce,
   system_sha256, history_sha256, generation_config_sha256, requested_at`); refuse on any
   mismatch.
3. **Reserve the attempt + issue the lease + STAMP `challenge_accepted_at` (P0-2).**
   Atomically reserve/generate a one-time `execution_attempt_id` (a `run_id` cannot yield two
   live racing attempts) and `issue_lease` for it. The supervisor stamps its own trusted
   clock as **`challenge_accepted_at`** (the attempt-reservation instant) and enforces the
   **acceptance-time window on THIS field, not on `requested_at`** — because `requested_at`
   is a *desktop* stamp from BEFORE the authority stamped `issued_at`, so the normal timeline
   is `requested_at < issued_at < challenge_accepted_at` and a naive `issued_at ≤
   requested_at` could never hold. The supervisor requires:
   `requested_at ≤ challenge_accepted_at` **and** `issued_at ≤ challenge_accepted_at ≤
   expires_at`, and evaluates key revocation **as of `challenge_accepted_at`**. This
   `challenge_accepted_at` is bound into the **lease**, the signed **terminal record** (§3),
   and the supervisor **attestation** (§6), so durable re-verification uses the exact same
   supervisor-authenticated instant — never a wall-clock `now` (§5).
4. **Launch the recorder with the immutable input handles + read-only input FDs**; the
   recorder's launcher (§2) preserves ONLY the **canonical FD set** (§2 FD contract: FDs
   `3`/`4`/`5` read-only `system`/`history`/`generation_config`, FD `6` write-only output)
   and closes every other, so the **executor receives the exact verified bytes** on
   read-only input FDs and returns its exact output on the output FD — the executor never
   reads the store or the keys.
5. **Recorder publishes output + containment and signs** the receipt/evidence over those
   handles; **supervisor verifies by handle and signs** the terminal record (§4). The
   attempt id + verified request hashes + the challenge context are bound INTO the signed
   record; a caller cannot choose an arbitrary pre-existing attempt. The supervisor returns
   `{execution_attempt_id, governed-result}`.

## 2.6 `challenge_accepted_at` is MACHINE-bound through exact signed schemas (P0-1)

A prose assertion that `challenge_accepted_at` is "bound into the lease / attestation /
record" is **insufficient** — it must ride the **exact signed artifacts + transport
schemas** so it is a chain-authenticated acceptance instant, not a terminal-record writer's
unilateral claim. The ratified base `execution-lease` and `brops.sign-request.v1` evidence
are **strict exact-key** schemas that do not define it (a bare new key would be rejected as
"unexpected"), so 3b-1B freezes a **versioned governed-turn variant** of each rather than
mutating the ratified artifacts:

1. **Versioned governed-turn lease — `brops.governed-turn-lease.v1`.** A new artifact type
   (not an ad-hoc field on `execution-lease`): a superset carrying the base lease fields
   (`lease_id`, `lease_nonce`, `run_id`, `execution_attempt_id`, `task_id`, identities,
   `issued_at`, `expires_at`) **plus** `challenge_accepted_at` and the challenge/registry
   bindings (`challenge_handle`, `challenge_key_id`, `challenge_registry_handle`,
   `challenge_registry_hash`, `challenge_registry_epoch`). `ARTIFACT_AUTHORITY[...]` = the
   lease issuer; signed bytes = detached Ed25519 over `JCS(payload)`.
2. **Field type + signed-byte formula.** `challenge_accepted_at` is an **integer epoch ms**
   (`> 0`), stamped from the **supervisor's trusted clock** at attempt reservation (§2.5
   step 3); it is a **`payload` field**, so it is covered by the lease/record/attestation
   signatures verbatim (no derived encoding).
3. **`issue_lease` / `validate_execution_lease` contract.** `issue_lease` (governed-turn
   variant) stamps `challenge_accepted_at`, enforces `requested_at ≤ challenge_accepted_at`
   and `issued_at ≤ challenge_accepted_at ≤ expires_at` at signing time, and signs the
   `brops.governed-turn-lease.v1`. `validate_execution_lease` (governed-turn variant)
   `verify_artifact`s it and returns the value; a lease missing/!int `challenge_accepted_at`
   is refused.
4. **Exact equality binding across the whole chain (all must be byte-equal).**
   `challenge_accepted_at` appears in, and is cross-checked equal across: **(a)** the accepted
   challenge context; **(b)** `brops.governed-turn-lease.v1`; **(c)** the supervisor
   attestation carried in **`brops.sign-request.v1`** evidence (the sign-request governed-turn
   evidence gains `challenge_accepted_at` + the registry-snapshot bindings); **(d)** the
   **`brops.sign-result.v1`** forensic relay; **(e)** the **bridge result**; **(f)**
   `brops.governed-turn-record.v1` (§3). The signer and `LiveRunStateProvider` **refuse** if
   any two differ.
5. **Refusal on mismatch (fail-closed):** any missing field, type error, or cross-artifact
   inequality Blocks — the record is never signed / never accepted.
6. **Negative tests (normative for the 3b-1B implementation):** a lease whose
   `challenge_accepted_at` disagrees with the record; a **backdated** `challenge_accepted_at`
   (`< issued_at` or `< requested_at`); an **expired** one (`> expires_at`);
   **clock-boundary** equality cases (`== issued_at`, `== expires_at`); a **replayed** lease
   from another attempt; and a sign-request/sign-result/bridge value that disagrees with the
   lease — each must Block.

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
    "challenge_handle": "<64hex>",         // == SHA256(JCS({payload,sig})) of the signed
                                           // challenge doc, published by the supervisor (§4 step 1)
    "challenge_key_id": "<string>",
    "challenge_issued_at": "<ms>", "challenge_expires_at": "<ms>",
    "challenge_accepted_at": "<ms>",       // P0-2: SUPERVISOR-stamped attempt-reservation
                                           // instant; the field the temporal window is
                                           // checked against (== the lease + attestation).
    // challenge-key-registry snapshot binding (P1-3/P1-2): the exact root-signed registry by
    // which challenge_key_id was accepted, so the record stays verifiable after rotation.
    "challenge_registry_handle": "<64hex>",   // == SHA256(JCS({payload,root_sig})) — EXACT stored
                                              // signed-document bytes (protected-store handle), published §4 step 1
    "challenge_registry_hash": "<64hex>",     // == SHA256(JCS(payload)) — fork/epoch identity (anti-rollback)
    "challenge_registry_epoch": <int>,
    "challenge_registry_root_key_id": "<string>",
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

1. **Supervisor imports the INPUTS first (before execution) AND publishes the signed
   challenge (P1-3).** After verifying the signed challenge (§2.5), the supervisor
   **atomically publishes the exact canonical signed challenge document** — the full
   `{payload, sig}` object serialized as `JCS({payload, sig})` — into the protected store,
   so that **`challenge_handle = SHA256(exact canonical signed challenge document bytes)`**;
   it also publishes the accepted root-signed challenge-key-registry snapshot as the exact
   signed document → **`challenge_registry_handle = SHA256(JCS({payload, root_sig}))`**, and
   advances the anti-rollback floor, under the **crash-consistent publish-then-floor sequence
   (§2.5 P1-3)** so the exact registry that admitted `challenge_key_id` is preserved for
   historical re-verification (distinct from `registry_hash = SHA256(JCS(payload))`, the
   fork/epoch identity, §2.5 P1-2);
   then from staging it **atomically publishes** `system`/`history`/`generation_config`
   (+ the `policy_bundle` it holds) into the protected store — every input, the signed
   challenge, and the registry snapshot exist as content-addressed handles *before* anything
   runs. Publishing uses the
   same create-if-absent atomic algorithm as every other artifact (temp→fsync→verify
   size+sha256→exclusive publish under the digest). The supervisor is the **sole publisher**
   of the signed challenge document (the recorder still owns output/containment only); a
   record may not be signed (step 5) unless `challenge_handle` already **exists in the store
   and re-hashes to its digest**. The supervisor never publishes output/containment.
2. **Reserve attempt + issue lease**, then **launch the recorder** handing it the immutable
   input handles + **read-only input FDs** (via the launcher, §2 canonical FD table: FDs
   `3`/`4`/`5`), so the executor receives the exact verified bytes on read-only FDs and
   returns output on the output FD `6` (it reads neither the store nor the keys).
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
| `request_nonce`, `system_sha256`, `history_sha256`, `generation_config_sha256`, `requested_at`, `request_sha256`, `challenge_accepted_at` | independently re-verified: fetch the signed challenge by `challenge_handle`, verify its `sig` under the challenge key resolved from the **bound registry snapshot** (row below), apply the **temporal + revocation semantics below (P0-2/P1-5)** against the record's `challenge_accepted_at` — NOT a wall-clock `now ∈ window` check — and confirm its `run_id`/`task_id`/`workspace_id`/`install_id`/`request_nonce`/`*_sha256`/`requested_at` equal the record's + `request_sha256 == sha256(JCS(envelope))` |
| `challenge_registry_handle`, `challenge_registry_hash`, `challenge_registry_epoch`, `challenge_registry_root_key_id` | fetch the **exact signed registry document** by `challenge_registry_handle`, **re-hash the full stored document** (`SHA256(JCS({payload,root_sig})) == challenge_registry_handle`), verify its `root_sig` over `JCS(payload)` under the pinned `challenge_registry_root_key_id`, **recompute `registry_hash = SHA256(JCS(payload)) == challenge_registry_hash`**, confirm `registry_epoch == challenge_registry_epoch`, then apply the **full key-validity predicate as of `challenge_accepted_at`** (§2.5 P1-4): `challenge_key_id` present exactly once, key/`public_key` schema valid, `key_epoch` accepted, `valid_from ≤ challenge_accepted_at ≤ valid_to`, `revoked_at IS NULL OR revoked_at > challenge_accepted_at`, and the challenge `sig` valid **under that exact snapshot key** — mere presence is insufficient |
| `challenge_accepted_at` (equality chain, P0-1) | **byte-equal** across the accepted challenge context, `brops.governed-turn-lease.v1`, the `brops.sign-request.v1` attestation evidence, the `brops.sign-result.v1` relay, the bridge result, and the record (§2.6); any inequality Blocks |
| `execution_attempt_id`, `run_id` | the requested handle |
| `lease_id`, `lease_nonce`, `challenge_accepted_at` | the verified **`brops.governed-turn-lease.v1`** (`verify_artifact` + governed-turn `validate_execution_lease`, §2.6); the lease's `challenge_accepted_at` must equal the record's |
| `policy_id`, `policy_version`, `policy_bundle_sha256` | the operator-authorized policy (the signer re-checks bundle digest, P1-7) |
| `containment_evidence_sha256` + `containment_event_id` | the `brops.governed-turn-containment.v1` artifact (§3.6) whose `run_id`/`execution_attempt_id`/`lease_id`/`runner_id` equal the record's + `contained==true`, recorded as a containment-confirmed evidence event whose `payload_hash == containment_evidence_sha256` |
| `receipt_id`, `output_sha256` | the verified governed-turn execution receipt (§3.5): receipt/attempt/lease ids match; the exact output bytes re-hash to `output_sha256 == output_handle` (binary, no normalization) |
| `task_id`, `evidence_final_event_hash`, `evidence_head_sequence` | the verified evidence head, authenticated via the supervisor attestation (§6 P1-5), with the sequence checked against the durable **per-(install, task/chain)** high-water mark (§6 P1-2, P1-6 anti-rollback) |

The `RunState` is built from the **verified signed record** only.

**Temporal + revocation semantics (P0-2 / P1-5, LOCKED) — acceptance-time gate vs.
historical re-verification, checked against `challenge_accepted_at`.** A challenge's
`expires_at`/revocation must gate **first use**, and must **not** retroactively invalidate
an already-accepted, signed historical record on later forensic re-verification (otherwise
every valid completed turn would turn "invalid" the moment its short-lived challenge
expired — a durability bug, not a security property). The window is checked against the
**supervisor-stamped `challenge_accepted_at`** (the attempt-reservation instant, §2.5
step 3), **not** the desktop's earlier `requested_at` — because the true timeline is
`requested_at < challenge_issued_at < challenge_accepted_at`, so testing the window against
`requested_at` (which precedes `issued_at`) would wrongly reject valid runs:
- **At execution acceptance (first use, §2.5 step 3):** the supervisor stamps
  `challenge_accepted_at` and requires `requested_at ≤ challenge_accepted_at` **and**
  `challenge_issued_at ≤ challenge_accepted_at ≤ challenge_expires_at`, the `request_nonce`
  unconsumed (durable one-time ledger), and the `challenge_key_id` **not revoked as of
  `challenge_accepted_at`**. An expired/replayed/revoked challenge is refused here, before
  any attempt is reserved. `challenge_accepted_at` is bound into the lease + record + attestation.
- **At durable re-verification (`LiveRunStateProvider`, restart / forensic / audit):** the
  provider verifies the signed challenge's `sig` and binding fields, then checks the **same
  as-of-acceptance** predicate against the **record's bound `challenge_accepted_at`** —
  `requested_at ≤ challenge_accepted_at` and `challenge_issued_at ≤ challenge_accepted_at ≤
  challenge_expires_at` — and **does not** compare the current wall clock to `expires_at`. A
  record whose `challenge_accepted_at` was in-window stays valid forever.
- **Revocation is evaluated as-of `challenge_accepted_at`, not as-of now.** Historical
  re-verification treats a `challenge_key_id` as revoked for this record **only if** the
  registry snapshot's `revoked_at` for that key is **≤ `challenge_accepted_at`** (the key was
  already revoked when the run was accepted). A routine later rotation/revocation (`revoked_at
  > challenge_accepted_at`) does **not** fail forensic re-verification. (A retroactive
  compromise-invalidation, if ever needed, is a separate explicit operator action —
  out of 3b-1B scope — never the default.)
- The signed challenge itself remains **immutable and re-verifiable**: its bytes are
  content-addressed by `challenge_handle` and its signature is checked at every
  re-verification regardless of age.

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
      `task_id`, `evidence_head_sequence`, `evidence_final_event_hash`, **and (P0-1/P1-2)
      `challenge_accepted_at` + the registry-snapshot bindings `challenge_registry_handle` /
      `challenge_registry_hash` / `challenge_registry_epoch` / `challenge_registry_root_key_id`**
      — so the supervisor **attestation** (`brops.run-attestation.v1`) covers them
      (JCS(evidence)) and `challenge_accepted_at` is a **chain-authenticated** acceptance
      instant, not a record-writer claim;
    - **sign-result** (`brops.sign-result.v1`, §4.2) echoes them into the forensic record
      alongside run/attempt/lease (incl. `challenge_accepted_at` + the registry bindings);
    - **bridge-result** `receipt` relays them (`task_id`, `evidence_head_sequence`,
      `evidence_final_event_hash`, `challenge_accepted_at`, registry bindings), and they equal
      the governed-turn-record's + the `brops.governed-turn-lease.v1`'s (§2.6 equality chain);
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
