# contracts/ 📜

**The source of record for every schema both halves consume.** The plan is
[`../docs/design/CONTRACTS_DEDUPE_PLAN.md`](../docs/design/CONTRACTS_DEDUPE_PLAN.md); the machine
index is [`index.json`](./index.json); the gate is
[`../tools/check_contracts_single_source.py`](../tools/check_contracts_single_source.py).

## English

When the cockpit (Rust) and the engine (Python) exchange security-relevant objects, they must
validate against **one** definition — not two that drift apart. Until 2026-08-29 this directory was
a README describing that intention and nothing else, while the files lived in `engine/schemas/`. The
ninth independent audit filed that as `I-13`: the roadmap called the box blocked by the production
gate, and it was not blocked by anything.

**What is here now.** The five schemas that cross the wall, as the source:

[`execution-lease`](./execution-lease.schema.json) ·
[`mode-grant`](./mode-grant.schema.json) ·
[`task-contract`](./task-contract.schema.json) ·
[`verifier-receipt`](./verifier-receipt.schema.json) ·
[`evidence-event`](./evidence-event.schema.json)

**What "single source" means here, exactly.** `engine/schemas/` keeps a **byte-identical** copy and
the engine goes on loading that one. Editing either side alone is RED in CI, naming the file and the
direction of the drift. That is a weaker claim than *"only one file exists"*, and it is said plainly
rather than dressed up — what it buys is the property the roadmap box asks for, one definition both
halves are held to, at no cost to audited security code.

**Why the copy stays**, so nobody "finishes" the job by deleting it: the engine resolves every schema
path relative to its **own root** (`engine/schemas/registry.json` holds root-relative paths, read by
`bro_contracts.validate_registered_schemas` and `bro_orchestration`), and `engine/` is a **git subtree**
of [`menqstudio/Bro`](https://github.com/menqstudio/Bro). Pointing those loaders at `../contracts/`
makes the engine read outside its root — a deliberate change to the containment model its perimeter is
built on — and moving files out forks the vendored half from upstream. That relocation is M2's last
step and needs its own audited engine branch. It is **not** blocked by the production gate, by any
service principal, launcher, broker or deployment.

**What the gate checks** (six things, each with a mutation test that proves it can go red): the
source exists · the copy is byte-identical · the engine registry still lists it · the declared
version matches the schema's own `const` · every schema in `engine/schemas/` is classified
cross-half **or** engine-internal, so a new one cannot default into silence · no `*.schema.json`
exists anywhere outside the four declared homes.

**Two things this page used to get wrong**, both found by measuring rather than by reading it:

- It said *"Phase 3 extracts them here so both sides consume the same files."* Phase 3's Contracts
  row says the opposite — *reference, do not yet relocate* — and asks for the migration plan for the
  final dedupe milestone, which is **Phase 10**.
- It listed **`approval`** among the canonical schemas. **There is no `approval` schema**, anywhere
  in the tree. The approval path across the wall exists on neither side; it is `T-021`, sequenced
  behind the standing audit.

`bridge/contracts/` and `engine/contracts/` stay where they are: they are wire protocols between two
**named processes**, not shared domain objects (M3, recorded as a decision).

## Հայերեն

Cockpit-ը (Rust) ու engine-ը (Python) security-relevant object-եր փոխանակելիս պիտի validate անեն
**մեկ** սահմանման դեմ։ Մինչև 2026-08-29 այս պանակը միայն README էր, որ նկարագրում էր մի մտադրություն,
իսկ ֆայլերը `engine/schemas/`-ում էին։ Իններորդ անկախ աուդիտը դա գրանցեց որպես `I-13`՝ roadmap-ը
այս box-ը ներկայացնում էր որպես production gate-ով փակ, իսկ այն ոչ մի բանով փակ չէր։

**Հիմա այստեղ** պատով անցնող հինգ schema-ն են՝ որպես **աղբյուր**։ `engine/schemas/`-ը պահում ա
**բայթ առ բայթ նույն** պատճենը, ու engine-ը շարունակում ա հենց դա բեռնել։ Մի կողմը փոխելը ու մյուսը
չփոխելը CI-ում **RED** ա՝ ֆայլի անունով ու շեղման ուղղությամբ։

**Ինչու ա պատճենը մնում** (որ մեկը «չավարտի» գործը՝ ջնջելով). engine-ը ամեն schema-ի ուղին լուծում ա
**իր սեփական root-ի** նկատմամբ, ու `engine/`-ը `menqstudio/Bro`-ի **git subtree** ա։ Loader-ները
`../contracts/`-ին ուղղելը նշանակում ա, որ engine-ը կարդում ա իր root-ից դուրս — դա միտումնավոր
փոփոխություն ա այն containment մոդելում, որի վրա կանգնած ա իր perimeter-ը — իսկ ֆայլերը դուրս
տանելը vendored կեսը կպոկի upstream-ից։ Այդ տեղափոխումը M2-ի վերջին քայլն ա ու պահանջում ա իր
առանձին **audited** engine branch։ Production gate-ի, service principal-ի, launcher-ի, broker-ի կամ
deployment-ի հետ կապ **չունի**։

`bridge/contracts/`-ը ու `engine/contracts/`-ը մնում են տեղում՝ դրանք երկու **անվանված պրոցեսի**
միջև wire protocol են, ոչ թե ընդհանուր domain object (M3, գրանցված որպես որոշում)։
