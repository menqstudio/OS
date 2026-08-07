# Bridge sidecar op protocol

**Scope:** `bridge/engine_sidecar.py` — the one process the desktop shells out to.
**Status:** implemented; `governance.read` is the first registered op.

## The problem this records

The desktop and the sidecar exchange exactly one JSON document each way over
stdin/stdout. For a long time that round trip could only mean one thing: *run a
governed turn*. Two separate pieces of work then hit the same wall from opposite
sides:

* The Phase-2 governance mirror (`apps/desktop/src-tauri/src/governance.rs`) sent a
  well-formed `brops.governance-read.v1` request and got the execution path's
  fail-closed answer back, because that is all the sidecar could produce. The engine
  had a real three-valued reply (`engine/runtime/bro_control_room_api.py`), the
  desktop had a real reader for it, and nothing in between routed one to the other,
  so every governance page rendered its honest blocked state forever.
* Phase 9's `probe_integration` could not be registered at all — there was no route
  from the desktop to anything that answers a question.

## The envelope

The request document now carries an optional top-level `op`.

| request | goes to | reply document |
| --- | --- | --- |
| no `op` key | the governed turn, unchanged | `bridge.result` (`bridge/contracts/bridge-result.schema.json`) |
| `"op": "governance.read"` | `bro_control_room_api.ControlRoomAPIV1.governance_read` | `brops.governance-read.v1`, relayed verbatim |
| any other `op` | nothing | `bridge.op.v1` refusal, naming the op |

A `bridge.task-request` can never grow an `op` by accident: its schema is
`additionalProperties: false`. And `governance.read` needs no envelope wrapper —
`op` is already a field of the engine's own request contract, so the document the
desktop builds is forwarded byte-for-byte.

Registering an op is one row in `_OPS`: `op -> (handler, refusal factory)`. The
refusal factory is per-op so a refusal stays inside the protocol the caller was
speaking. An op absent from that table is refused **by name** — the reply says which
op was asked for and which ops the build serves. It is never ignored, and never
answered with an empty success.

## The three-valued read, and why it must stay three-valued

`brops.governance-read.v1` distinguishes three answers, and the sidecar preserves all
three across the hop:

```
ok:true  + records:[...]              the store was read and holds these records
ok:true  + records:[] + empty:true    the store was read and holds NOTHING
ok:false + error:"..."                the engine could not read, and says why
```

The middle value is the fragile one. "I looked and there is nothing" and "I could
not look" are different facts, and a transport that blurs them eventually paints a
calm, empty governance page over a blind engine — which is worse than an error,
because nobody investigates a page that looks fine.

Two rules keep them apart:

1. **No refusal carries a `records` key.** Not the engine's, not the sidecar's. There
   is no shape in which a refusal can be misread as a satisfied, empty read; a
   consumer reaching for `records` finds nothing to read rather than an empty list to
   believe. The sidecar emits refusals in the engine's own refusal shape, and
   re-issues (stripped) any `ok:false` reply that somehow arrives carrying `records`.
2. **Nothing is invented to look empty.** An unprovisioned mirror, a state directory
   that does not exist, an evidence store that is not there, a key registry that will
   not load — every one of those is a refusal with a reason, never an empty mirror.
   In particular the sidecar refuses to create a state directory and then report it
   as empty.

## A decision record says how its actor was established

The runtime proves a privileged lifecycle actor with an operator-root-signed
`conductor-session` artifact and persists the outcome as `actor_identity_basis`
inside the hash-chained transition (`bro_orchestration_runtime._prove_actor`;
`bro_control_room_api._prove_command_actor` does the same for control-room
commands). That basis was durable but invisible: the `decisionLedger` wire record
published `actor_type` and `actor_id` and nothing about how — or whether — the
identity behind them was established, so a mirror consumer read a signed conductor
decision and a bare caller claim as the same fact.

Each `decisionLedger` record now carries two more fields:

| field | value |
| --- | --- |
| `actor_identity_basis` | the string the runtime persisted, verbatim — `operator-signed-conductor-session`, `runtime-originated`, `contract-assignee-under-runtime-issued-claim-lease`, `unproven-caller-claim` — or `null` when the record carries none. The mirror mints no basis of its own. |
| `actor_identity_established` | the derived reading: `"proven"`, `"unproven"`, or `"unknown"`. |

Three values, not two. `proven` means a signature this engine verified — the
conductor-session artifact, and nothing else. `unproven` means a basis was recorded
and it is not a verified signature (the runtime's own bookkeeping, a claim lease it
minted, or a bare caller claim; `actor_identity_basis` says which). `unknown` means
the record does not establish one — it predates the field, or carries a value this
build cannot read. `unknown` is deliberately **not** `unproven`: "we never recorded
it" is a third fact, and demoting it to either pole tells a reader something the
record never said. It is a string rather than a nullable boolean for the same
reason — `if (record.actor_proven)` reads `null` as `false`.

Fail-closed both ways: an unrecognised basis is never `proven`, and an absent one is
never ranked as though it had been judged. The vocabulary is imported from the
writer, and `engine/tests/test_governance_read.py` holds the mirror's two classified
sets against every basis constant `bro_orchestration_runtime` declares, so a fifth
one cannot appear unclassified.

**The field-set equality rule does not refuse it.** `_governance_request` checks
`set(request) == _GOVERNANCE_REQUEST_FIELDS` on the **request** only — an unknown
request field is a question this build does not understand. There is no equality
rule on the reply: `_op_governance_read` forwards the request unmodified and relays
the reply verbatim, and the single reply-shape rule it enforces is that an
`ok:false` reply must not carry `records`. A new field inside a record therefore
travels on its own, and nothing in `bridge/engine_sidecar.py` needs to change.

**What the desktop reader would need.** Nothing, to receive it:
`governance.rs::parse_identified_record` validates only that a decision record is an
object with a non-empty string `id` and passes the whole record through verbatim, so
both fields already reach the frontend. To *show* it, the reader must render three
states — and must not collapse `unknown` into either pole, which is the one way to
reintroduce the defect at the last hop. Note also that `RECORDS_ARE_AUTHENTICATED`
stays `false` and `record_authentication` for this surface stays
`runtime-hash-chain-verified`: a record may say its actor was proven by a signature
the ENGINE verified, and that is still not a signature the DESKTOP verified.

## Provisioning (operator, not desktop)

Read provisioning is deliberately disjoint from the governed turn's `_PROVISION_ENV`:
a half-provisioned builder can neither enable nor disable the mirror, and
provisioning the mirror grants no step toward running anything.

| variable | required | meaning |
| --- | --- | --- |
| `BROPS_GOVERNANCE_STATE_DIR` | yes | the engine's orchestration runtime state directory. Must already exist. |
| `BROPS_GOVERNANCE_EVIDENCE_STORE` | no | the signed evidence store. Must exist if set. Absent ⇒ the engine refuses `evidenceChain` in its own words ("a refusal, not an empty chain"). |
| `BROPS_GOVERNANCE_REGISTRY_ROOT` | no | root of the operator-signed trusted-key registry. Set-but-unloadable is a refusal, never a silent downgrade to unkeyed — an unkeyed runtime refuses the signed surfaces with a reason that would blame the wrong thing. |

Without `BROPS_GOVERNANCE_STATE_DIR` the mirror refuses and names the variable. The
desktop passes none of these and cannot: it inherits the sidecar's environment and
strips fake-mode flags before spawning.

## A read never executes

Ops are reads. Nothing dispatched here reaches `_real_callables`, the supervisor
socket, the isolated signer, or the builder. `_real_callables` still raises
unconditionally, pending the Wave 3b-1B supervisor-reserved execution attempt and the
authoritative execution→receipt binding; that is correct and unchanged. A read must
not even be able to knock on it — being refused by the execution path is precisely
how the mirror broke in the first place.

Self-test flags (`--self-test`, `--self-test-signed`) answer the **turn** path only.
A read carrying them still reaches the engine or refuses; it is never handed canned
data.

## Tests

* `bridge/tests/test_sidecar_ops.py` — dispatch, refusal shapes, provisioning
  refusals, relay honesty, protocol-drift guard against the engine's constants.
* `engine/tests/test_governance_sidecar_route.py` — the join: a real orchestration
  runtime on one side, the sidecar's stdout on the other, including a real subprocess
  pipe. Each of the three values is asserted crossing the bridge.
