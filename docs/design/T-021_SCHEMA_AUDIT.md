# T-021 · audit of the `approval-request` schema, before the transport that carries it

**Date** 2026-09-19 · **Head** `main` @ `ee6cf80` · **Subject**
`contracts/approval-request.schema.json` (vendored byte-identical at
`engine/schemas/approval-request.schema.json`) · **Auditor role** delegated to Claude by the Owner.

## Why this document exists before the code

`docs/OWNER_ACTION_REQUIRED.md` decided this path by **refusing both options on offer** — *build it
now* added an input to the engine's trust boundary under a RED verdict, *carry it* is how an obligation
disappears — and instead opened `T-021` with five contract invariants fixed in advance. The fifth is
that **the engine schema change is audited before it lands**, and the reason is written beside it:

> Fixing them now means the contract test is not designed by whoever is trying to pass it.

So this is an audit of the schema against that list, performed as an attack on it, and the attacks
that succeed are written down as plainly as the ones that fail. Nothing in this change sends or
receives an approval request: there is no engine endpoint and no desktop command yet, so the trust
boundary is not widened by this landing. What lands is the definition, and the tests that hold it.

## The five invariants, one at a time

### 1. No key, lease, nonce or verdict crosses the wall in this direction

**Held, structurally.** `additionalProperties: false` with a property set of twelve names, and
`engine/tests/test_approval_request_contract.py` asserts that set **by enumeration** — adding a field
is a failing test rather than a silent widening. A second test refuses any property whose *name*
contains `key`, `signature`, `sig`, `nonce`, `lease`, `verdict`, `secret`, `token`, `credential`,
`password`, `private`, `seed`, `cert` or `attest`.

Proved by breaking it: opening the property set kills
`test_additional_properties_are_refused` and `test_a_request_carrying_a_key_is_refused` **by
assertion**; declaring a `key_id` property kills four tests including
`test_the_signed_command_and_this_document_are_different_artifacts`.

**And here is what it does NOT hold, which the invariant's wording invites a reader to believe.**
`reason` is free text up to 2 000 characters. `requested_by`, `expected_task_state`, `request_id`,
`task_id` and every element of `evidence_refs` are strings with no grammar tighter than an id pattern
on two of them. **A secret can be typed into `reason`.** That is `A-09` route 1, in this direction, and
the answer has to be the same one this repository already gives rather than a new heuristic: a
credential is defined by what a remote system will accept, so no shape test can separate a token from a
sentence, and a high-entropy detector that read as proof would be worse than the stated gap. What is
established is the enumeration: **six leaves can carry arbitrary text, and they are named here.** The
invariant is exact about declared fields and must be read that way.

### 2. The desktop requests and never decides

**Held for what a schema can hold.** `requested_command` is an enum of exactly three asks —
`approve`, `deny`, `request-verification` — named with the vocabulary
`control-room-command.schema.json` already uses, so the two artifacts cannot drift into two dialects
for the same three acts. `cancel`, `retry` and `reassign` are deliberately absent: they are commands
and not approvals, and a request shape wide enough to drive the whole control-room surface would be a
command channel with a softer name. There is no `granted`, `decision`, `outcome`, `state`,
`adjudicated` or `result` property, so the document has nowhere to write what the sender wishes had
happened.

Proved by breaking it: adding `cancel` to the enum kills three named tests.

**Obligation carried to the transport (not enforceable here):** the engine's reply must be a separate,
named document with **no field a consumer could read as GRANTED**, in the same way
`bridge/engine_sidecar.py::_op_refusal` has no `records` key so that *"I could not look"* is
unmistakable for *"I looked and found nothing"*. If the reply ever carries a disposition, invariant 2
is broken on the way back and this schema will not have noticed.

### 3. The desktop's own T-010/T-011 authority stays separately named

**Held, and tested against the other artifact rather than asserted.**
`test_the_signed_command_and_this_document_are_different_artifacts` reads
`control-room-command.schema.json` and requires that it has `key_id` and `signature` and that this one
has neither. The approvals page's existing grant/deny/escalate drive the desktop's own SQLite approval
system behind a native confirmation the webview cannot forge; this document drives nothing. If the two
ever converge, a test fails instead of a reader noticing.

### 4. `RECORDS_ARE_AUTHENTICATED` stays false

**Held.** `requested_by_type` is an enum of exactly one value, `desktop-operator`, and a test requires
that the signed command is the artifact allowed to say `owner` or `bro`. `requested_by` is documented
as *"a NAME, never an authenticated identity"*, and a test reads that description rather than trusting
it — because the honesty of this field is the field's entire content.

Proved by breaking it: adding `owner` to the enum kills
`test_the_requester_type_cannot_claim_to_be_the_owner` and
`test_a_request_claiming_to_be_the_owner_is_refused`.

### 5. Audited before it lands

This document, in the same change as the schema, with the attacks above run rather than described.

## Findings the schema cannot close, carried to the transport step as required tests

A schema states what a document may contain. Four of the guarantees this path needs are about what the
**engine does on receipt**, and they are listed here so the next step is not designed by whoever is
trying to pass it either.

| # | Obligation on the engine endpoint (`T-021b`) | Why the schema cannot hold it |
|---|---|---|
| `O-1` | A repeated `request_id` is recorded as a **duplicate ask**, never as a second decision, and the reply says which. | `request_id` is a correlation id the caller generates; nothing in a document can stop it arriving twice. |
| `O-2` | A request whose `expected_task_state` disagrees with the state the engine holds is **refused by name**, so a stale cockpit cannot ask about a task that has moved on. | The field is a claim about the engine's state, made by something that cannot see it. |
| `O-3` | `requested_at_epoch` is recorded as **claimed**, beside the engine's own receive time. | It is the desktop's clock. A schema can require an integer and nothing more. |
| `O-4` | `evidence_refs` are resolved **only** inside the engine's own store, and an unresolvable ref is refused by name rather than fetched. | A ref is a string here. What it points at is decided on receipt. |

And one obligation on the transport rather than the engine:

| # | Obligation | Why |
|---|---|---|
| `O-5` | The request path uses the **framed** readers rather than an unbounded read, asserted by a test. | Measured here rather than deferred: `engine/runtime/brops_protocol.py:24` sets `MAX_FRAME_BYTES = 256 * 1024` and refuses at read time — `if len(raw) > MAX_FRAME_BYTES: raise ProtocolError(f"frame body is {len(raw)} bytes, over the {MAX_FRAME_BYTES} cap")` — and the desktop's own framed IPC caps a payload at 8 192 bytes (`ipc_framing::MAX_FRAME_PAYLOAD_BYTES`). So the cap exists **before** parsing in both directions and a 2 000-character `reason` fits either with room to spare. What is left for `T-021b` is narrower and is the part a new endpoint can get wrong: that it reads through those framed readers, and not through a bare `readline()` beside them. |

## Verdict

**The schema may land.** It satisfies invariants 1–4 as far as a document definition can, each held by a
test that dies by assertion when the invariant is broken, and it widens no trust boundary on its own
because nothing sends or receives it yet. Invariant 1's wording is exact about declared fields and is
**not** a claim that no secret can cross — six named leaves carry free text, and that is `A-09` route 1
in this direction, answered by enumeration rather than by a heuristic, exactly as the read half answered
it.

**Five obligations (`O-1`…`O-5`) are recorded as conditions on `T-021b`, before it is written.**
