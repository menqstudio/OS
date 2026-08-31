# Floor-writer service — the principal that owns the anti-rollback marks · DESIGN PROPOSAL (rev 1)

> **Status: PROPOSAL. Not Architect-audited. No product code lands under this document.**
> This is **roadmap §I step 1** ("Propose — open a PR describing the change and its blast radius;
> do **not** implement yet") for the Owner decision recorded in
> [`docs/OWNER_ACTION_REQUIRED.md`](../OWNER_ACTION_REQUIRED.md) §1b, **taken 2026-08-14**: *option 1,
> the floor-writer service. A small always-on principal owns the marks directory and accepts
> append-only advance requests from the builder. The setuid helper is not taken.* That decision ships
> with its own process — **"Owner approval (given, here) → Architect audit → implement. No
> implementation lands on this decision alone."** — and the Architect has had nothing to audit, because
> no such design existed. This is that missing artifact and nothing more.
>
> **It is also an amendment request to a document that is already DESIGN GREEN.** An eighth resident
> principal changes [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md)
> §2.5 (`TCB_ARTIFACTS`) and §2.6 (**"The SEVEN runtime service UIDs (NORMATIVE)"**). Those are
> normative clauses of a rev-30 the Architect has passed. **Only the Architect may ratify that
> change**; §6 states it as a blocking gate rather than folding it in silently.
>
> **Every claim about current code in this document is ◑ — the Builder's own reading, with
> `file:line` beside it so it can be refuted cheaply.** Nobody independent has checked any of it. The
> standing independent-audit verdict on this repository is **RED**
> ([`apps/desktop/AUDIT/AUDIT_LEDGER.md`](../../apps/desktop/AUDIT/AUDIT_LEDGER.md)), and nothing here
> changes that or asks to.
>
> **No gate moves.** `governed_verification_unconfigured()`, `UpstreamBlockedExecutor` and
> `connect_broker()` are not mentioned again except to say they are untouched by every slice below.
>
> **Հայերեն:** Սա **առաջարկ** ա, ոչ իրականացում։ 1b որոշումը Տիրոջն ա ու տրված ա; հաջորդ քայլը
> Architect-ի աուդիտն ա։ Այս փաստաթղթի տակ ոչ մի product code չի land-ում, ու ոչ մի դարպաս չի բացվում։
>
> **Revision history (non-normative appendix rule: history never redefines a current contract).**
> - **rev 1** — first proposal. Authored 2026-08-15 against `main` @ `dc8d867`.
> - **rev 1, re-verified 2026-08-31 against `main` @ `363c51c`** — no clause changed; this line records
>   what was re-measured, because a sixteen-day-old design that nobody re-read is a design nobody can cite.
>   **It is NOT superseded by [`PRODUCTION_HALF_DESIGN.md`](./PRODUCTION_HALF_DESIGN.md)**, which designs the
>   OUTPUT half and says so in its own scope note — *"It does not extend the containment half"*. This is a
>   containment-half defect: who may write the anti-rollback marks. That document cites the anti-rollback
>   floor (§4, the credential store's custody argument) as an EXISTING guard, which is the same floor whose
>   writer this proposal is about.
>   **Every `file:line` in §0 still resolves**, checked one by one rather than assumed:
>   `bro_completion.py:541` is still `def _refuse_self_owned_floor`, `:805` is still `def _advance_head_floor`,
>   the `.. warning::` block quoted from `:488-503` still names *"a floor-writer service or a setuid helper"*
>   at `:502`, `bro_custody.py:87` is still `ENV_PIN_SELF_OWNED_ACK`, and
>   `test_completion_head_binding.HeadFloorConfigurationContradictionTests` still exists (`:594`).
>   The `B-02` row that points here by path moved to
>   [`AUDIT_LEDGER_ARCHIVE.md`](../../apps/desktop/AUDIT/AUDIT_LEDGER_ARCHIVE.md); the pointer survived the move.
>   Still **PROPOSAL**, still waiting on §I step 2 — the Architect audit. Nothing here was implemented.

---

## 0. The defect this closes, stated as three verified facts

### 0.1 The floor's writer is the party the floor exists to constrain (this is 1b)

`bro_completion`'s anti-rollback floor asks two things of the directory holding its marks, and the
two have **no intersection**:

| Where | What it requires |
|---|---|
| `engine/runtime/bro_completion.py:541` `_refuse_self_owned_floor` | the policed account must **not** be able to rewrite the directory — POSIX owner/permission/parent-rename verdicts via `bro_custody`, Windows `FILE_DELETE_CHILD`-class rights via the same DACL walk the operator pin uses |
| `engine/runtime/bro_completion.py:805` `_advance_head_floor` | it writes `<task>.floor.json.tmp` and renames it over the mark — **in the very process the mark polices** — so it needs exactly the capability the rule above refuses |

The function's own docstring (`:488-503`) already says this, and names the resolution: *"the write has
to move to a second principal, and that is an Owner/Architect decision."* The only satisfiable posture
today is `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` (`bro_custody.py:87`), which
**short-circuits every custody rule in the runtime**, not just this one. Both postures are driven
against a real directory by `engine/tests/test_completion_head_binding.py`
`HeadFloorConfigurationContradictionTests` — that class is the proof the contradiction is real, and
under this proposal it becomes the **positive control** (§7).

### 0.2 The floor's scope is chosen by its subject, and pinned by a principal that does not own the floor

This is the *other* floor — the per-**install** evidence-head ceiling on the governed-turn path — and
it is audit `A-01` + `B-02`:

* `engine/runtime/governed_supervisor_ledger.py:760` `_install_floor_ceiling` scopes the floor by
  `install_id`, and `:774` `_evidence_floor_cas` states the rule in its own words: *"A defence whose
  scope the attacker chooses is not a defence."*
* The pin exists, and it is in a **different service**: `challenge_authority.py:432-470`
  (`AuthorityConfig` **requires** `install_id`) and `challenge_authority_server.py:194-209` (a
  `create-pending` naming a foreign `install_id` is refused). Closed on Windows 2026-08-15 (`B-01`).
* The **supervisor never checks it against anything of its own.** `supervisor_id` is config-pinned at
  both sites (`governed_acceptance.py:355`, `:405`); `install_id` is not pinned at the supervisor at
  all — it arrives inside the challenge the authority signed, and the supervisor trusts that
  validation transitively.

The Owner's reason 3 for taking option 1 is exactly this: *"A resident principal that **owns** the
marks directory is the natural place to pin `install_id` from trusted config as well — one principal,
one trusted config, both defects closed at the same boundary."*

### 0.3 A finding this proposal turned up: the per-install floor's owner is named three different ways

Found while establishing 0.2, and reported rather than fixed — it is the same topology question `B-02`
raises, in its full form:

| Source | Says the floor is owned by |
|---|---|
| `WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md:1142` and `:3355` (§7 P1-7, normative) | *"a durable **`brops-signer`-owned** floor DB … dir `0700` / file `0600`"* |
| `apps/desktop/src-tauri/core/src/supervisor_ledger.rs:20` | *"The **signer-owned** durable evidence-head floor CAS"* |
| The code | the **supervisor**. The DDL is in `engine/runtime/supervisor_ledger.sql:168`, the CAS at `governed_supervisor_ledger.py:774` runs **inside the supervisor's completion transaction**, and the ledger file is opened only by `engine/ci/live/run_supervisor.py:155` / `run_ladder_supervisor.py:550` as the supervisor account. `engine/runtime/isolated_signer.py` opens **no sqlite at all** — its single mention of the table (`:130`) is a comment. |
| `challenge_authority.py` | the **scope key**'s pin, i.e. a third principal holds the one input that decides what the floor measures |

Three documents and the code do not agree about which principal owns one anti-rollback floor. **This
proposal does not resolve that** — §9 puts it in front of the Architect, because deciding it is §I
items 1 and 2.

---

## 1. Proposed boundaries — the decisions the Architect is asked to ratify

### 1.1 One principal, two duties, one trusted config

A resident service — **`brops-floor`** on POSIX (a dedicated uid), **`NT SERVICE\BroPSFloorWriter`** on
Windows (a virtual service account, SID derived from the service name) — that owns:

1. **the marks store** for `bro_completion`'s per-task anti-rollback floor, and
2. **the deployment's `install_id`**, read from its own TCB-owned config and served to the two
   principals that need it.

One principal, because splitting them is *two mechanisms for one contract* — the defect the Owner's
reason 1 invoked when rejecting the setuid helper, and the one this repository has now found **eight**
times.

### 1.2 The policed account gets no access at all, not merely no write

The marks live in the service's own state directory
(`%ProgramData%\BroPS\floor-writer\marks` · `/var/lib/brops/floor-writer/marks`), **not** beside the
evidence store. Two reasons, both from existing code:

* `_refuse_self_owned_floor`'s third verdict (`bro_completion.py:593-600`) is the **parent-rename**
  vector — a floor whose own mode is fine but whose parent the subject can write can be renamed aside
  and replaced with an empty one. Keeping the marks under `BRO_EVIDENCE_STORE` (today's default,
  `:535`) leaves that vector by construction.
* With no read grant either, the policed process holds **no parser for a mark file**. `_load_head_floor`
  (`:657`), `_load_floor_index` (`:632`) and the `_FLOOR_INDEX` roster stop being client code. One
  parser, in the principal that owns the bytes.

### 1.3 The service decides; the client's copy of the number is a courtesy

`floor.advance` performs the whole **load → compare → write** and answers `advanced` / `idempotent` /
`refused{reason}`. `floor.get` exists only because `validate_evidence_chain` needs a number **before**
it validates the chain (`bro_completion.py:245` → `:254` → `:257`), and its answer is **never
authoritative**: a client that ignores it, or lies to itself about it, still cannot advance below the
floor, because `advance` re-checks against the store it owns.

Stated plainly, because it is the limit of what moving the write buys: **the mark becomes unforgeable;
the check does not become unskippable.** `validate_evidence_chain` runs in the policed process and a
process that never calls it is not stopped by this service. What the floor defends is a *later*
verification against a truncated-chain replay, and that defence is exactly as strong as the mark's
custody. Any wording that suggests more should be refused in review.

### 1.4 Fail closed, and no fallback exists

* Service unreachable / timeout / malformed reply / refusal ⇒ `CompletionError`. **An unavailable
  floor must never read as "no floor required"** — that coercion is what audit `R-06` closed for the
  directory case (`bro_completion.py:632-648`), and it is a constraint the Owner attached to the
  decision.
* **One resolver, a closed two-state result, no path between the states.** The floor posture resolves
  once to either `ServiceFloor(endpoint)` or `AcknowledgedLocalFloor` (today's behaviour, available
  only under the existing `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` disclosure, so a
  single-principal developer box and the current CI suites keep working). There is **no third state and
  no fallback from the first to the second**: when the service is configured, the local write path is
  unreachable, and the acknowledgement **cannot** re-enable it. A fallback would leave the old
  behaviour live while looking replaced — the same reason the §4.10(g) ladder decision (§1d) removed
  the direct chain instead of keeping it beside the new one.

### 1.5 The scope pin: one owner, resolved at start, enforced at both sites

* The challenge authority and the supervisor each resolve `install_id` from the service **once at
  start-up**, not per turn, and cache it for the process's life. Absence, a refusal, or an
  unreachable service ⇒ governed real-mode is **not enabled** — the same shape as
  `verify_distinct_principals()` / `verify_tcb_integrity()` in addendum §2.5/§2.6, so the failure mode
  is one the design already has a name for.
* **The authority keeps its door check.** `B-02`'s objection to *moving* the pin was that a
  misconfiguration caught today at `create-pending` would otherwise travel three hops before failing.
  It still fails at the door.
* **No second configured value is created.** `B-02`'s objection to *duplicating* the pin was a second
  site that must agree with the first about which `install_id` is this install's. There is one
  configured value, in one principal's TCB-owned config; the other two sites *read* it. Two readers of
  one value is not two implementations of one contract.
* Per-turn cost: **zero hops**. Every turn compares locally against a value fixed at start.
* `supervisor_id` is deliberately **not** widened into this — it is already config-pinned at both its
  sites (§0.2), and moving a working pin is not in scope.

### 1.6 The service holds no key

It is the first second-principal in this repository whose authority is **custodial rather than
cryptographic**. Consequences, both directions:

* **In its favour:** compromising it yields no signature. It cannot mint an anchor, a receipt, a lease
  or a registry entry, and it is in no `ARTIFACT_AUTHORITY` mapping.
* **Against it:** a compromised floor-writer can lie about a floor, which is the whole defence. That is
  why §1.11 puts its binary, config and unit file inside `TCB_ARTIFACTS` and why it must hold nothing
  else.
* **Therefore its replies are unsigned, deliberately.** The party that must not be able to lie is the
  **subject**, and the subject is the client. A client that forges a reply to itself only refuses its
  own completion. What does need authenticating is the **server**, for `scope.pin` — §1.7.

### 1.7 Transport: reuse, on both platforms, with one framing and one cap

Nothing new is invented here; the Owner's reason 2 for taking option 1 was that the transport already
exists and is green in CI on both platforms.

| | Linux | Windows |
|---|---|---|
| Endpoint | AF_UNIX socket in a directory only `brops-floor` may write | `\\.\pipe\brops-floor-writer` |
| Client authentication | `SO_PEERCRED` uid, captured at accept time from the kernel, strict integer equality, `bool` excluded — the `isolated_signer_server.py:82-117` shape | `authenticate_pipe_client_sid` (kernel-attested SID via `ImpersonateNamedPipeClient`) — the `win-live/src/pipe.rs:237-324` shape |
| Server authentication (why a client cannot be answered by an impostor) | the socket's directory is not writable by any other runtime principal, checked through `bro_custody` — the same rule §2.5 already applies to every TCB path and its ancestors | the explicit DACL from `pipe_acl::pipe_dacl_plan` withholds `FILE_CREATE_PIPE_INSTANCE` from every non-server principal, and the server creates the successor instance **before** closing the served one, so the name is never unowned (audit `R3`, `pipe.rs:9-32`) |
| Framing | `brops_protocol` — 4-byte big-endian length prefix, strict decode | `brops_core::ipc_framing` — the same 4-byte big-endian prefix |

**One cap, one number, both directions.** This repository has already found three framing codecs
disagreeing (8192 / 8192 / 512 KiB) with the deployed client capping at 8192 in both directions, making
one gate unreachable. So: **`MAX_FLOOR_FRAME_BYTES = 4096`**, enforced identically on both ends and on
both platforms, with the constant defined once per language and pinned by a cross-language drift test.
The arithmetic that justifies it, to be **confirmed through the real encoder in FW-1 rather than
asserted here**: the largest legal request is an `advance` carrying `task_id` (≤128), a `head_sequence`
integer, a 64-hex digest and the fixed keys — computed at well under 512 bytes, leaving a factor of
roughly eight. If the measured maximum ever approaches the cap, the cap moves in the design, not in one
end's code.

### 1.8 A per-op peer allowlist — this part is genuinely new

Every existing door in the tree admits exactly **one** peer (`peer_is_broker`,
`load_allowed_peer_uid` returns exactly one uid and refuses two). This service has **two client
classes**, and an op each:

| Op | Admitted peers |
|---|---|
| `floor.get`, `floor.advance` | the completion principal only |
| `scope.pin` | the challenge-authority principal and the supervisor principal only |

A peer is authenticated **before any frame is read**, and an op is refused if the authenticated peer is
not on **that op's** list — not merely on the union of them. A `scope.pin` peer must not be able to
advance a floor, and the completion principal must not be able to ask what the pin is.

### 1.9 One writer process, so the cross-process lock disappears

`_floor_write_lock` (`bro_completion.py:705`) and `_floor_lock_is_held` (`:770`) exist because the
compare and the write used to be two steps in N processes — audit `R1`, whose two consequences were
that **the mark could go DOWN** and that a roster entry could vanish, making a later mark-deletion read
as a first sighting. With a single-writer service handling **one connection at a time** (the
`isolated_signer_server` loop shape), that class of defect is structurally impossible rather than
serialized. The lock, the `msvcrt`/`fcntl` platform split and the "a platform with neither primitive
REFUSES" branch all leave the client.

### 1.10 A provisioning generation — narrows O-5, does not close it

`_require_establishable_mark` (`bro_completion.py:439`) exists because *"a floor that was deleted and
re-provisioned is indistinguishable from a first sighting"*. The service's own state carries a
**monotonic provisioning generation**, minted once when the service is provisioned and served with
every reply, so a re-provisioned floor is **visibly new** rather than **silently empty**.

**What that does not do**, stated because the temptation to overclaim here is exactly the pattern four
audits have punished: it does not survive an offline restore of the service's own state directory by an
administrator. That requires privileges outside the threat model (§2), and it is the same honest limit
addendum §7 P1-7 already draws for the governed floor (*"This local table CANNOT detect a full-DB
restore to an older self-consistent backup"*). **O-5 stays OPEN**, the `BRO_EVIDENCE_FLOOR_ANCHOR`
owner-signed path (`bro_completion.py:302`, `:390`) stays exactly as it is, and no `evidence-floor-anchor`
becomes mintable by this service.

### 1.11 TCB and principal-count consequences — the amendment request

* **§2.5 `TCB_ARTIFACTS`** gains the floor-writer **executable**, its **config**, its **IPC/peer-auth
  policy** and its **service/unit file** — with the section's existing floor applying unchanged: owned
  by a TCB principal, non-writable by any runtime or login principal, no writable ancestor, hash-pinned
  and verified at start.
* **§2.6** says *"The **SEVEN** runtime service UIDs (NORMATIVE)"* and requires them pairwise-distinct
  and all ≠ the login uid. It becomes **eight**, and `verify_distinct_principals()` must count eight.
* Both are normative clauses of rev-30, which is **Architect DESIGN GREEN**. This document **requests**
  the amendment; §6 makes ratifying it a gate on FW-3 rather than something a Builder folds in.

---

## 2. Threat model — what each boundary defeats, and what it does not

**Scope, inherited unchanged from addendum §0 and §7 P1-7:** a compromised client running as the
policed principal is **in scope**; local administrator / root / `SYSTEM` / kernel is **out of scope**
(already inside the TCB).

| Threat | Defeated by | Residual |
|---|---|---|
| The policed account rewinds its own mark | the mark is written by a principal the subject cannot write, and §1.2 gives the subject no access at all | none within scope |
| The policed account deletes the mark and restarts the floor at zero (`R-06`) | the roster and the marks are both inside the service's custody; deletion needs the service's consent | none within scope |
| The policed account renames the floor's **parent** aside | the marks are not under any directory the subject can write (§1.2) | none within scope |
| Two concurrent completions lower the mark (`R1`) | one writer, one connection at a time (§1.9) | none |
| The client lies about the current floor to `validate_chain` | `advance` re-checks against the service's own store; `floor.get` is not authoritative (§1.3) | a client that never calls the check at all — **out of what a mark can defend** (§1.3) |
| The subject chooses the floor's scope (`A-01`) | `install_id` comes from the service's TCB-owned config, resolved at start, and is never on the marks wire at all (§1.5, §4.3) | a mis-provisioned service config — refused at start by the §2.5 custody/hash check, not by this service |
| One check in a different service (`B-02`) | one configured value, one owner, two readers; the authority's door check survives | the ruling in §0.3 is still owed |
| An impostor answers `scope.pin` and widens the anti-rollback scope | socket-directory custody (POSIX) / pipe DACL + first-instance ownership (Windows), plus resolution happening at start under the §2.5 peer-auth-policy check | POSIX: a writable ancestor of the socket directory — the same `bro_custody` rule and the same **named open follow-up** as the pin (`OWNER_ACTION_REQUIRED.md` §1: the Windows rule *"still reads one descriptor and cannot see an ancestor"*) |
| Service compromise | nothing — it is in the TCB by §1.11 and holds no key by §1.6 | full defeat of the floor. This is the cost of the design and is stated, not mitigated |
| Offline restore of the service's state | nothing | out of scope; **O-5 stays OPEN** (§1.10) |
| DoS: the service is down | every completion **refuses** (§1.4) | availability is deliberately traded for the fail-closed direction, per the Owner's constraint |

---

## 3. Reuse vs build

**REUSE (exists, unchanged — this is most of it):**

* `engine/runtime/brops_protocol.py` framing and strict decode; `brops_core::ipc_framing` on the Rust
  side.
* `engine/runtime/brops_socket.py` + the `isolated_signer_server.py` / `challenge_authority_server.py`
  server shape: peer credentials at accept time, an allowlist, one bounded frame in, one framed reply
  out, an injectable `accept_one` so the deny/bounds/dispatch behaviour is testable without a socket.
* `win-live/src/pipe.rs::run_server` + `pipe_acl::pipe_dacl_plan` + `authenticate_pipe_client_sid`,
  unchanged — the module's own docs say the cross-account case is the one it wants.
* `provision/src/audit_signer.rs` as the **specification template**: virtual-service-account choice and
  its rejected alternatives, offline-derivable SID (`service_account_sid`), `DaclPlan` / `Ace` /
  `plan_as_facts` / `ReadbackProof`, `AppTokenPosture` / `Separation`, and the refusal enum shape.
  `audit-signer/src/register.rs` as the service-registration template.
* `bro_custody` for every custody question, on every platform — including the rule that a platform with
  no branch **refuses**.
* The whole decision content of `bro_completion`'s floor: the A-01-shaped comparison rules, the digest
  binding (`O-5`), the roster semantics, the refusal texts. **The rule does not change; only the
  principal that executes it does** (§6, FW-1's stop condition).

**BUILD (net-new):**

1. The **service**: the marks store, the per-op peer allowlist (§1.8), the `brops.floor-writer.v1`
   dispatch, the provisioning generation, the atomic mark publish.
2. The **client seam** in `bro_completion`: a resolver returning the closed two-state posture (§1.4) and
   two call sites — `_load_head_floor` (`:245`) and `_advance_head_floor` (`:288`) — which are the
   **only** production call sites of the floor primitives.
3. **Windows service provisioning + registration**, mirroring the audit-signer's machinery.
4. The **scope-pin resolution** at start in the challenge authority and the supervisor (§1.5).
5. The **§2.5/§2.6 amendments** — after ratification only.

---

## 4. Normative interface (what FW-0 locks, if the Architect agrees)

> JSON, UTF-8, strict: duplicate keys rejected, unknown keys rejected, fixed types, no NaN/Inf.
> Digests are lowercase-hex sha256. One length-prefixed frame per direction, whole frame
> ≤ `MAX_FLOOR_FRAME_BYTES` (§1.7). One connection = one request = one reply, then disconnect.

### 4.1 `brops.floor-writer.v1` — requests

```jsonc
{ "protocol": "brops.floor-writer.v1", "op": "floor.get",     "task_id": "<≤128>" }

{ "protocol": "brops.floor-writer.v1", "op": "floor.advance", "task_id": "<≤128>",
  "head_sequence": <int ≥ 1>,
  "evidence_head_sha256": "<64-hex>" }          // the digest of the SIGNED head document

{ "protocol": "brops.floor-writer.v1", "op": "scope.pin" }
```

**No request carries `install_id`, and none may.** The scope is the service's own; accepting it on the
wire would reproduce `A-01` inside the fix. This is the single most important negative in §7.

### 4.2 Replies

```jsonc
{ "ok": true,  "op": "floor.get",     "head_sequence": <int ≥ 0>,
  "evidence_head_sha256": "<64-hex>" | null, "known": <bool>, "generation": <int ≥ 1> }

{ "ok": true,  "op": "floor.advance", "outcome": "advanced" | "idempotent",
  "head_sequence": <int ≥ 1>, "evidence_head_sha256": "<64-hex>", "generation": <int ≥ 1> }

{ "ok": true,  "op": "scope.pin",     "install_id": "<≤128>", "generation": <int ≥ 1> }

{ "ok": false, "reason": "<closed enum, below>" }        // ≤512 bytes, no paths, no traceback
```

A refusal carries `ok: false` and **no result field at all**, so it cannot be mistaken for a result —
the `audit-signer/src/lib.rs:91` rule, adopted verbatim.

**Refusal enum (closed):** `peer_denied` · `unknown_op` · `malformed` · `oversize` · `floor_absent` ·
`mark_removed` · `mark_corrupt` · `no_head_digest` · `stale_floor` · `head_digest_changed` ·
`scope_unavailable` · `internal`.

Two of those change meaning under service custody, and the design should say so rather than let a
reader assume the old one: `mark_removed` (`bro_completion.py:673-677`) and `mark_corrupt` (`:679-693`)
stop being **attack** signals — nothing outside the service can remove or truncate a mark — and become
**self-damage** signals. They still refuse. `floor_absent` (`:643-648`) stops being a client-bootstrappable
state: the roster is created by the service's own provisioning, so a deployment can no longer bootstrap
a floor by writing `{"tasks": []}`.

### 4.3 Marks store (service-private)

* Layout `marks/<install_id>/<task_id>.floor.json` — the install scoping is **internal**, from the
  service's config, and is what makes §4.1's "no `install_id` on the wire" implementable.
* Records exactly today's two fields (`head_sequence`, `evidence_head_sha256`) plus the roster, so the
  rule is preserved byte-for-byte in meaning (§6 FW-1).
* Atomic publish: private temp in the same directory → `flush` + `fsync` → rename over the mark →
  `fsync` the directory. This is addendum §4.0's published algorithm minus the content-addressing it
  does not need.
* Directory `0700` / files `0600` on POSIX; on Windows the `DaclPlan` shape from
  `provision/src/audit_signer.rs::key_dacl_plan` with the app/login principal **absent**.

### 4.4 Configuration

| Variable | Read by | Meaning |
|---|---|---|
| `BRO_EVIDENCE_FLOOR_WRITER` | the completion process, the challenge authority, the supervisor | the endpoint. Set ⇒ `ServiceFloor`, and the local write path is unreachable (§1.4) |
| `BRO_EVIDENCE_HEAD_FLOOR` | the completion process | **unchanged**, and meaningful only in the `AcknowledgedLocalFloor` posture |
| `BROPS_FLOOR_WRITER_CONFIG` | the service | its own TCB-owned config: `install_id`, the marks root, the per-op peer allowlist. Mirrors `BROPS_BROKER_CONFIG`'s shape |

---

## 5. Alternatives, and why each is rejected — with the evidence rather than the preference

| Alternative | Why not |
|---|---|
| **A setuid helper** | The Owner's decision, reason 1: `setuid` does not exist on Windows, which is the platform every posture in §1b's table was driven against, so it needs the service anyway — two mechanisms for one contract. |
| **The supervisor owns the marks** (reuse a resident principal, avoid an eighth) | Its door is **Linux-only AF_UNIX + `SO_PEERCRED`, admitting the broker uid alone, with an op set documented as exhaustive** (`bro_completion.py:516-521`), so this means a new op and a new peer class on the principal that **issues every lease** — the largest TCB component. And there is **no Windows supervisor service at all** (open finding `R-42`, `:522-525`), while the completion path runs on Windows. Bigger, riskier, and unavailable where it is needed. This is the same shape as the Owner's constraint *"not inside the broker"*: do not give the floor write to the principal that runs the work. |
| **The supervisor's durable ledger holds the marks** | Disproved by execution on 2026-08-10 and documented at `bro_completion.py:505-530`: the ledger counter is per-**install** and deliberately an install-wide ceiling, this floor is per-**task** with every task's first anchor at 1, so offering `(task-1, seq 1)` and `(task-2, seq 1)` refuses the second with `EvidenceFork` — **the second task in any deployment becomes permanently un-completable.** It also has no column for `evidence_head_sha256`, and no equivalent of the roster or the anchor bootstrap. |
| **Extend the existing `brops-audit-signer` service** | It is the **closest sibling** and the machinery to copy, but it **holds the audit-anchor signing key**, and a floor-writing bug in that process reaches that key (§1.6 is the property being bought). Its engine contract is a one-shot `argv`/stdin exec through a relay shim (`audit-signer/src/lib.rs:13-36`) — there is no persistent op set to extend. It is Windows-only in practice, appears in **no installer**, and `register::apply` has no caller outside tests (`OWNER_ACTION_REQUIRED.md` §1). |
| **A trusted config file both sites read, instead of `scope.pin`** | It needs a correct custody check at **four** sites (two readers × two platforms) instead of one authenticated channel, and the Windows custody rule *"still reads one descriptor and cannot see an ancestor"* — a named open follow-up in `OWNER_ACTION_REQUIRED.md` §1, i.e. the weakest available primitive at the widest fan-out. **Recorded as the runner-up**, because it has one real advantage: no liveness dependency at all. If the Architect prefers it, §1.5's start-time resolution is what changes, and nothing else in this document does. |
| **Move the per-install `_evidence_floor_cas` behind the service** | `governed_supervisor_ledger.py:774-781` folds the floor into the completion's **single** `BEGIN IMMEDIATE` transaction precisely so *"a refused floor cannot leave a completion behind"*. Moving it out means either losing that atomicity or inventing a two-phase commit across a socket. **Not proposed.** |
| **Resolve `scope.pin` per turn instead of at start** | Puts a liveness dependency on `create-pending` — every governed turn gains a hop to a service that has nothing per-turn to say. Start-time resolution gives the same property at zero per-turn cost, and the failure mode already has a name (§2.5/§2.6 start-time verification). |
| **Sign the service's replies** | The subject cannot gain by forging a reply to itself (§1.6); server authenticity is a transport property here, and a key in this process is exactly what §1.6 exists to avoid. |

---

## 6. Slicing and stop conditions

* **FW-0 — this proposal. Architect audit is mandatory before any code** (roadmap §I step 2; the §1b
  decision's own text; the ownership matrix's *any `engine/` security code* row: 🔨 proposal · 📐
  **mandatory** · 🛑 **before implementation**).
* **FW-1 — the service, the protocol, the Linux transport, and the client seam.**
  **Stop conditions:** the floor **rule** does not change — same comparisons, same refusal texts, same
  two stored fields — because moving the write and changing the rule in one slice makes a regression
  indistinguishable from the move. Does not touch the governed-turn path. Does not touch any gate.
  `HeadFloorConfigurationContradictionTests` must pass in the `ServiceFloor` posture **and keep
  failing in the local one** (§7).
* **FW-2 — Windows: the service, the virtual account, provisioning and registration.** Mirrors the
  audit-signer. **Stop condition:** `A-01`'s own lesson (`B-01`) — **no row, box or ledger entry may be
  marked closed on one platform's evidence.** Until FW-2 lands, FW-1's claim is *"Linux only"*, in
  those words.
* **FW-3 — the scope pin (`A-01`'s root, `B-02`).** Start-time resolution in the challenge authority
  and the supervisor. **Blocked on the Architect ratifying the §2.5/§2.6 amendments (§1.11)** — bypassing
  §I is itself a stop condition, and this is the clause that needs it.
* **Global stop.** No slice changes `governed_verification_unconfigured()`, `UpstreamBlockedExecutor` or
  `connect_broker()`; none makes a `trusted_verified` producible; none closes `O-2`, `O-5` or `F-29`.
  **`B-02` closes when this design is Architect-GREEN and built — not when this document merges.**

---

## 7. Acceptance criteria and the negative matrix

The load-bearing test is the one that is impossible today:

> **Both rules of one real directory, satisfied at once.** With the service configured, a completion
> advances the floor **while the policed account cannot write, delete or list the marks** — asked of a
> real directory on the running platform, not of a fixture. `HeadFloorConfigurationContradictionTests`
> keeps its existing cases as the **positive control**: in the `AcknowledgedLocalFloor` posture the
> contradiction must still be demonstrable. A version of this suite that passes in both postures for
> the same reason is testing nothing.

Negatives, each refused **by name** (the enum in §4.2), each with a positive control beside it so a
refuse-everything arm cannot satisfy it:

1. Service down / socket absent / pipe absent ⇒ completion refuses; **and the refusal is not
   "no floor required"** — asserted on the message, because that substitution is the `R-06` defect.
2. `advance` with `head_sequence` below the stored mark ⇒ `stale_floor`, **even when the same client's
   `floor.get` returned something lower** (drive it with a deliberately-lying client).
3. `advance` with the stored `head_sequence` and a **different** digest ⇒ `head_digest_changed`
   (`bro_completion.py:275-279`'s rule, preserved).
4. `advance` twice with the same head ⇒ `idempotent`, exactly once written. Required, because
   `validate_evidence_chain` is called **twice per completion** — `_check_manifest:972` and
   `_check_verifier_receipt:1053`.
5. A request carrying an `install_id` field ⇒ `malformed` (unknown key), **not** silently ignored.
6. `floor.get`/`floor.advance` from the `scope.pin` peers ⇒ `peer_denied`; `scope.pin` from the
   completion peer ⇒ `peer_denied`. Both directions, per §1.8.
7. An unauthenticated / unlisted peer ⇒ refused **before a frame is read**.
8. Oversize, short, truncated and non-JSON frames ⇒ `oversize` / `malformed`; a frame at exactly the
   cap ⇒ accepted (the boundary tested on both sides of the number).
9. `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` while the service is configured ⇒ the local write
   path stays unreachable (§1.4).
10. Two concurrent advances ⇒ the mark never goes down and the roster keeps both tasks (`R1`).
11. Crash between the temp write and the rename ⇒ the old mark is intact and readable.
12. A marks store whose custody the service cannot verify at start ⇒ the service **refuses to start**.
13. FW-3: a challenge whose `install_id` differs from the served pin ⇒ refused at the authority's door
    **and** at the supervisor; the service unavailable at start ⇒ governed real-mode not enabled.

**Discipline that applies to every one of them**, from `START_HERE.md`'s four rules and this
repository's own history:

* **Delete each new check once and confirm its test goes red**, then restore. Report any that comes back
  green — in the last wave, four did, meaning four tests were testing nothing.
* **No fixture may be built with the rule of the code under test.** A marks fixture written by the
  service's own writer, fed to the service's own reader, is a tautology — the `A-05` lesson, where
  `linux_written_chain_tests` had to build the chain with the *writer's* encoder to mean anything.
* **No test may assert *how* something failed** where the answer is a platform fact. A test pinning an
  exception name, a `sudo` behaviour or an errno is a test that can only pass where it was written —
  found five times in one week.
* **A mutation harness must be crash-safe**: pristine bytes and digests written to disk before the first
  edit, a sentinel, `--restore`, a post-run byte-identity check. A killed process does not run its
  `finally` block, and that has already left a live mutant in this tree once.

---

## 8. Non-goals — what this does not close, said plainly

* **`O-2`** (the audit ledger is not tamper-evident against its own writer on a shipped install) and
  **`O-5`** (the evidence high-water anchor) stay OPEN. §1.10 narrows O-5's gap and does not close it.
* **`F-29`** (a guard that cannot fail, `production_trust.rs`) is untouched — it is an Owner decision.
* The **acknowledgement escape** is not removed from the other four custody sites (the pin, the registry
  root, the evidence floor and the evidence store share one rule; widening or removing it there is a
  separate audited change).
* The **per-install floor's location** does not move (§5), and the **ruling in §0.3 is not made here**.
* **No production `trusted_verified`**, no gate movement, and no change to the standing **RED** audit
  verdict.

---

## 9. Findings and questions for the Architect

Five things this proposal cannot decide, listed so the audit has a checklist rather than a document:

1. **§0.3 — which principal owns the per-install evidence-head floor?** The addendum §7 P1-7 and
   `supervisor_ledger.rs:20` say `brops-signer`; the DDL, the CAS and the process that opens the file
   say the supervisor; the scope pin says the challenge authority. One of those three documents is
   wrong and should be corrected in whichever direction the Architect rules. **§I items 1 and 2.**
2. **§1.11 — ratify or refuse the §2.5/§2.6 amendment** (seven runtime principals → eight,
   `TCB_ARTIFACTS` gains four paths). FW-3 is blocked on this.
3. **§1.5 versus §5's runner-up** — the served pin (one authenticated channel, a start-time liveness
   dependency) or the TCB-owned config file both sites read (no liveness dependency, four custody
   sites on the weakest available primitive). The rest of this design is unchanged either way.
4. **Should the per-task floor adopt the governed floor's A–E matrix** (addendum §7 P1-7), which
   distinguishes a legitimate unchanged-chain **re-anchor** from a **fork** using
   `(event_count, last_sequence, final_event_hash)`? This proposal deliberately says **not in FW-1** —
   moving the write and changing the rule together makes a regression unattributable — but the two
   floors will then still measure differently, and whether that is a bug or the design is the
   Architect's.
5. **`_head_floor_dir`'s warning becomes false the day FW-1 lands.** It currently states that the
   escape route *"cannot be configured"*. That sentence must be rewritten in the same commit that makes
   it configurable — this repository's characteristic defect is an honest comment written the moment it
   was true and never revisited, and this is a scheduled instance of it.

---

## 10. Provenance

Authored 2026-08-15 by the Builder against `main` @ `dc8d867`, under a session-side canonical full-read
receipt (16 files, digest `93f770e902a5`), roadmap Phase 1 declared, prior-art search recorded for this
path. **Nothing in this document has been independently reviewed.** It is a proposal; the next event on
it is an Architect audit, and no implementation may begin before that verdict.
