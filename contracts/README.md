# contracts/ 📜

**Empty on purpose, until Phase 10.** The plan that says why, and what moves when, is
[`../docs/design/CONTRACTS_DEDUPE_PLAN.md`](../docs/design/CONTRACTS_DEDUPE_PLAN.md).

## English

When the cockpit (Rust) and the engine (Python) exchange security-relevant objects, they must
validate against **one** definition — not two that drift apart. This directory is where those
definitions will live.

Two corrections to what this page used to say, both found by measuring rather than by reading it:

- It said **"Phase 3 extracts them here so both sides consume the same files."** Phase 3's own
  Contracts row says the opposite — *reference, do not yet relocate* — and asks for the migration
  plan for the final dedupe milestone, which is **Phase 10**. A reader who trusted this page arrived
  expecting files Phase 3 was never going to move.
- It listed **`approval`** among the canonical schemas. **There is no `approval` schema** — not in
  `engine/schemas/` (21 files), not in `bridge/contracts/`, not in `engine/contracts/`, nowhere in
  the tree. The approval path across the wall exists on neither side; it is tracked as `T-021`,
  sequenced behind the standing audit.

The four that are real and cross the halves:
[`execution-lease`](../engine/schemas/execution-lease.schema.json) ·
[`mode-grant`](../engine/schemas/mode-grant.schema.json) ·
[`task-contract`](../engine/schemas/task-contract.schema.json) ·
[`verifier-receipt`](../engine/schemas/verifier-receipt.schema.json), with
[`evidence-event`](../engine/schemas/evidence-event.schema.json) beside them.

They live in [`../engine/schemas/`](../engine/schemas/) today, and the desktop **hand-mirrors** them
in Rust types bound to nothing but a doc comment. That — not a duplicated file, of which this
repository has none — is the drift the milestone exists to close, which is why its first step is a
gate and not a move.

## Հայերեն

Cockpit-ը (Rust) ու engine-ը (Python) security-relevant object-եր փոխանակելիս պիտի validate անեն
**մեկ** սահմանման դեմ։ Այս պանակը դատարկ ա **միտումնավոր** — ֆայլերը տեղափոխվում են **Phase 10-ում**,
ոչ Phase 3-ում, ու պլանը
[`../docs/design/CONTRACTS_DEDUPE_PLAN.md`](../docs/design/CONTRACTS_DEDUPE_PLAN.md)-ում ա։

Այս էջը երկու սուտ ա կրել՝ թե Phase 3-ը ֆայլերը կտեղափոխի (չի տեղափոխի — roadmap-ը ասում ա
*reference, do not yet relocate*), ու թե `approval` schema կա (**չկա** — ոչ մի տեղ ծառի մեջ;
`T-021` ա, աուդիտից հետո)։

Իրական drift-ը կրկնվող ֆայլը չի — այդպիսին այս repo-ում չկա — այլ Python-ի schema-ի ու Rust-ի
ձեռքով գրած տիպի միջև եղած կապը, որը միայն doc comment ա։ Դրա համար ա milestone-ի առաջին քայլը
**gate**, ոչ թե տեղափոխում։
