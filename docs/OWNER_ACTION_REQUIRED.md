# Owner action required

Everything that cannot move without Gev. One page, kept current, so the answer to "what is waiting
on me" is never reconstructed from a chat log.

Nothing here is a suggestion to flip anything. The governed surfaces stay fail-closed until every
item below is settled, a **separate** audit passes, and the Owner approves — in that order.

> **FIFTH AUDIT, 2026-08-16 — RED, on `main` @ `5fe4740` (pin proved by tree digest).** It
> confirmed **all three production-gate refusals still closed** and found **no P0**. It also found
> **11 findings** and promoted **15 Builder claims to ✅** — the largest promotion this ledger has
> carried. Its headline is `A-01`: the round it audited **shipped a rendering regression in the one
> file whose header argues that a comment is not an honesty property.** The `sigbreathe` rule used
> the `animation` shorthand, which replaced `.reveal`'s entrance, so the Security integrity
> instrument rendered at **`opacity:0`** for the whole of the state the pulse was added to depict.
>
> **Nothing here could have seen it.** `vitest.config.ts` sets `css: false`, so 660 unit tests and
> the entire axe suite run against a DOM with **no stylesheet attached**. The test asserted that
> the class name was in the DOM — which was true — and said nothing about paint. That gap is the
> audit's most valuable finding, and it is §E of its report, not a numbered one.
>
> **All 11 are fixed as of 2026-08-16**, and the two that had no possible test now have a static
> one: `tools/check_c1_tokens.py::animation_clobber`. Building it found a **third** instance of the
> same family nobody had reported — `dec-stamp`'s final keyframe omitted `opacity`, so a stamped
> decision row animated in and then **faded back out to nothing**.
>
> **The standing audit verdict is RED — and as of 2026-08-15 it is NOT older than the code.**
> **Five** independent audits have run. This block said "two", "it is older than the code" and "it
> has never been re-run" until today, which was true when written and false the moment the third
> round finished — on the page every banner sends a cold reader to for what is blocked and on whom.
>
> * **Third**, [`2026-08-14-zero-trust-audit-e0dd969.md`](../apps/desktop/AUDIT/2026-08-14-zero-trust-audit-e0dd969.md),
>   of `main` @ `e0dd969`: **RED for materially fewer reasons.** It could **not reopen the second
>   round's P0** on either platform and **confirmed all three of the gate's refusals closed** at that
>   head. 5 new findings (`A-01`…`A-05`, P2 1 · P3 4); of 14 Builder claims attacked, **9 survived**
>   and are the first ✅ this repository's ledger has carried.
> * **Fourth**, [`2026-08-15-zero-trust-reaudit-0a9a1af.md`](../apps/desktop/AUDIT/2026-08-15-zero-trust-reaudit-0a9a1af.md),
>   a re-audit of those five fixes against a **pinned snapshot** (`main` moved three times mid-run;
>   the auditor proved the pin by tree digest): **still RED — now for one platform rather than one
>   mechanism.** Four of five could not be reopened. `B-01` found the fifth fixed on Linux only while
>   the ledger row claimed both platforms — closed on Windows the same day. **`B-02` stays OPEN.**
>
> **Prior:** [`2026-08-06-remediation-audit.md`](../apps/desktop/AUDIT/2026-08-06-remediation-audit.md),
> of `main` @ `219c763` — **4 of 18** blockers closed, **45 surviving findings** (1 P0, 5 P1, 13 P2,
> 26 P3). Its P0 was the supervisor copying the executing chain's own `output_handle` into the
> attestation it signed: the F-01 signing oracle surviving a fix that addressed F-01's symptom. That
> P0 is now closed and was attacked twice more without reopening.
>
> **What has not changed: the verdict is RED and the gate stays shut.** The index is
> [`apps/desktop/AUDIT/AUDIT_LEDGER.md`](../apps/desktop/AUDIT/AUDIT_LEDGER.md) and it is now on the
> canonical read manifest; ◑ there means the Builder believes it closed and nobody else has looked.
> Until 2026-08-09 that verdict appeared in **no** canonical document, while `NEXT_CHAT.md` opened
> with the FIRST audit's “all code facts CONFIRMED, none refuted” — so a cold reader concluded the
> audit had come back clean. It had not.

> **A correction worth reading before the rest.** This repository's history — and the standing
> instruction that produced it — names `platform_governed_execution_supported()` as the flag holding
> that line. **There is no such function.** The name appears in exactly two doc comments and in
> `WINDOWS_BROKER_DESIGN.md`; `grep -r "fn platform_governed_execution_supported" --include=*.rs`
> returns nothing. It is a specification symbol, and `config/spec-conformance.json` already records
> §0.1 as *partial — the platform gate as specified; it is a hardcoded false*.
>
> What actually refuses, all three verified in the source:
>
> | Where | What it does |
> |---|---|
> | `governed_verification_unconfigured()` — `apps/desktop/src-tauri/src/commands.rs` | returns `Some(...)` **unconditionally**, before the model is invoked |
> | `UpstreamBlockedExecutor` — `apps/desktop/src-tauri/broker/src/main.rs` | a real type; every turn returns `Err(TurnReason::UpstreamBlocked)` |
> | `connect_broker()` | refuses with `UnsupportedPlatform` off Linux |
>
> The line is held, and it was held all along — but by those, not by the name everyone was watching.
> Earlier prose in the HISTORY sections still uses the old name; that is what was believed when it
> was written, and it is left alone rather than rewritten.

---

## The install does the ceremony now

There used to be a page here listing artifacts only the Owner could mint, and a runbook step for
each. Both are deleted. `apps/desktop/src-tauri/provision/` mints the trust material on first
launch: one Ed25519 key per authority the engine knows, a signed `trusted-key-registry` in exactly
the form `bro_signature.load_trusted_keys` accepts, the operator-root pin written outside the
registry root where the anchor rule requires it, and an anti-rollback floor so a superseded registry
cannot be replayed. Nothing expires — `not_after_epoch` is 9999-12-31 — so nothing will ever ask for
a renewal.

It is proven byte-compatible with the engine by a test that runs the **real** Python verifiers
against **real** Rust output: 29 checks through `load_trusted_keys`, `verify_conductor_session_token`
and `bro_deploy_preflight`. Not a Rust test asserting that its own encoding round-trips — the thing
that has to accept it, accepting it.

**What that posture claims, and does not.** Locally-minted trust material defends against an
attacker who arrives **later**. It does not defend against one who already owned the machine at
install time. An SSH host key makes the same trade. The deleted ceremony claimed more, and that
claim was right for a vendor-signs/customer-verifies fleet and wrong for a product with one user.

---

## 1. O-2 — the anchor's CUSTODY is closed on Windows; the ledger is still not tamper-evident on a shipped install

> **Read this before the four rounds below.** What those rounds closed is the *custody of the anchor
> directory*: the pin, the anti-rollback floor, the registry and the provisioning manifest are out of
> the app account's reach, and the forgery that used to work is refused by the operating system —
> proved by running it. That is real and it is not the same property as “the audit ledger cannot be
> rewritten”.
>
> **On a shipped install the ledger carries no signed head, and here is the chain of facts.**
> `bro_audit_log.append()` anchors only when `anchor_custody_configured()`, which is true only when
> `BRO_AUDIT_ANCHOR_SIGNER` or `BRO_AUDIT_ANCHOR_KEY_ID` is set. **Nothing in the shipped product
> sets either** — every occurrence in the tree is a test harness or a document; they are **not** part of
> `Provisioned::engine_env()` and cannot be (that list is the registry/pin/floor/session set, which IS
> exported since 2026-08-09). They come from `AnchorEnv::engine_env()`, which only exists after
> `audit_signer::verify_installed` has MEASURED an installed signer — an unmeasured
> `BRO_AUDIT_ANCHOR_SIGNER` would be an audit anchor claimed rather than proved;
> the `brops-audit-signer` service and the `brops-anchor-relay` shim are built by the workspace but
> appear in no installer (`tauri.conf.json` declares no `externalBin` and no `resources`); and
> `register::apply` has no caller outside tests. So `append()` takes its unconfigured path: it writes
> the record, rewrites the **plaintext** `.head` itself, and installs no `.head.sig`.
>
> The consequence, stated exactly: a party who can write the ledger can drop records, recompute the
> chain, rewrite `.head`, and an **unkeyed** `verify()` reports the result intact. A **keyed**
> `verify()` does refuse — but with `AuditAnchorMissing`, which it raises for every ledger this
> deployment has ever written, so it cannot separate “never anchored” from “tampered”. `bro_monitor`
> asks for the keyed check and reports that as a blind spot rather than downgrading silently, which
> is the honest behaviour and not a substitute for the anchor.
>
> **This is the property O-2 exists for, and it has never run outside a test.** `docs/PHASE_10_PRODUCTION_ITEMS.md`
> keeps O-2 OPEN, which is correct; what was misleading was the shape of the summary — “O-2 closed on
> Windows”, in this page's own heading until 2026-08-09. The heading now says which half.

### The custody half — closed on Windows, and what is left

The forgery that worked four rounds ago now fails, and it is proved by running it rather than by
argument. Every step is refused by the operating system — overwriting the pin, appending to it,
deleting it, renaming it aside, creating a new file beside it, raising the anti-rollback floor,
rewriting the manifest, renaming the anchor directory, **renaming its parent**, removing it — and
then the real `bro_audit_log.verify()` refuses the truncated ledger, with the signer's own anchor
still accepted in the same run.

Four rounds, and each ended by naming a gap instead of claiming closure:

1. `ANCHOR_AUTHORITIES` accepted two authorities the app holds → narrowed to a dedicated one.
2. The app held the operator root, which signs the registry → destroyed at install.
3. Destroying it was not enough: the **pin** was a file the app could rewrite → moved out of reach.
4. Sealing the leaf was not enough either: the **parent** could be renamed aside → the whole chain
   is now walked to the volume root.

The mechanism is the OWNER RIGHTS SID, and it needs no elevation, no service and no second login: an
owner implicitly holds `WRITE_DAC`, so "read-only" is theatre, but an access-allowed ACE for OWNER
RIGHTS *replaces* those implicit rights rather than adding to them.

`BRO_OPERATOR_ROOT_PIN_SELF_OWNED` is no longer set anywhere. The custody rules pass on their merits
instead of being switched off — and removing it exposed a second rule it had been hiding, which is
why the trusted-key registry moved out of the app's reach too.

### What is not done

- **POSIX is specified and refuses rather than pretending.** `seal` returns `Unsupported`, naming
  what a POSIX deployment must provide: the directory created by another uid, provisioning run once
  as that uid. An owner may always `chmod` a directory it owns, and POSIX has no OWNER RIGHTS
  equivalent. That branch has never executed.
- **`bro_custody`'s Windows rule still reads one descriptor** and cannot see an ancestor. The
  property holds because *provisioning* walks the chain; the engine alone would accept a sealed leaf
  under a renameable parent. It is a shared rule across the pin, the registry root, the evidence
  floor and the evidence store, so widening it is a named follow-up rather than an end-of-session
  edit.
- **The boundary is the app's unelevated token.** On a machine whose user is a local administrator,
  one UAC consent gives full control. Provisioning fails closed if the token ever holds
  `SeTakeOwnership` or `SeRestore`, so an elevated run refuses rather than quietly proceeding — but
  that is the residual, and it is what having no second principal ultimately costs.
- **The installer interaction is untested**, and one mutation stayed green (a redundant proof whose
  removal nothing notices).

---

## 1a. A guard that cannot fail — F-29, and it is not closed

`apps/desktop/src-tauri/core/src/production_trust.rs` carries the comparison that is supposed to
bind the production verdict to the key the chain actually verified under. **It cannot fail.** Every
call site derives `envelope_verifying_key_hex` from `verifying_key_hex(...)` over bytes that the
same `resolve_production_key` lookup produced, over the same manifest, selecting by first match, and
the hex round trip is exact — so the two sides are one value compared with itself. Two rounds of
“fix” each added an indirection and neither changed that. The code says so in its own words, and it
draws the right conclusion: *a guard that cannot fail is worse than no guard: it is a claim of a
check that is not happening.*

What is being done about it, and what is not:

* The comparison is **kept**, fail-closed, as defence in depth for a future call site that obtains
  its key some other way. That costs nothing and is worth having.
* The **claim** is what was wrong. The property that holds today holds by *construction* — one
  source of the key, not two agreeing ones — which is weaker than a check, and is a property a
  future refactor can remove silently.
* `AUDIT_LEDGER.md` was corrected when that comment was written. **`NEXT_CHAT.md` listed F-29 as
  CLOSED for three more days**, and this page did not mention it at all. Both are corrected
  2026-08-09.

**Your decision, not the Builder's:** whether the honest form is to make one call site obtain the
verifying key independently (so the comparison has two sources and can fail), or to accept
construction as the property and delete the guard rather than keep a check that reads as one. Doing
neither leaves a keystone blocker open, which is where it stands today.

## 1b. RESOLVED 2026-08-14 — a floor-writer service owns the marks; not a setuid helper

**The Owner's decision, taken 2026-08-14: option 1, the floor-writer service.** A small always-on
principal owns the marks directory and accepts append-only advance requests from the builder. The
setuid helper is not taken.

**Why, in the order the reasons decided it.**

1. **`setuid` does not exist on Windows** — and Windows is where this problem was found. Every posture
   in the table below was driven against a real Windows directory. Choosing the helper solves Linux
   and leaves the platform that surfaced the defect needing a service anyway: **two mechanisms for one
   contract**, which is the defect that made you retire the direct AF_UNIX chain on 2026-08-12
   (§1d RESOLVED — *"keeping two implementations of one contract is the defect this repository found
   eight times in three days"*).
2. **The transport already exists and is green in CI on both platforms** — AF_UNIX + `SO_PEERCRED` on
   Linux, the named-pipe peer-auth broker on Windows (`§0.W broker syscall proof`). A floor-writer is a
   small append-only op over paths that are already gated.
3. **`A-01` argues for it, and this reason is newer than the question.** The third audit
   ([`2026-08-14-zero-trust-audit-e0dd969.md`](../apps/desktop/AUDIT/2026-08-14-zero-trust-audit-e0dd969.md))
   found the floor's **scope key** (`install_id`) is chosen by the party the floor constrains. 1b is
   about the floor's **writer** being that same party. They are two faces of one defect: *the floor is
   controlled by its own subject.* A resident principal that **owns** the marks directory is the
   natural place to pin `install_id` from trusted config as well — one principal, one trusted config,
   both defects closed at the same boundary. A setuid helper cannot do that: it is invoked **by** the
   builder, so the scope key stays in the caller's hand.

**Constraints that travel with the decision.**

- **Fail closed.** If the service is down, completion refuses. An unavailable floor must never read as
  "no floor required" — that exact coercion is what audit R-06 closed for the directory case.
- **Not inside the broker.** The broker runs the builder's work; giving it the floor write recreates
  the defect one level up, exactly as `task_id` → `install_id` did.
- **§I change-control.** This is a deployment-topology change, so: Owner approval (given, here) →
  Architect audit → implement. **No implementation lands on this decision alone.**

**The analysis that produced the question is kept below as the record.**

---

## 1b (superseded). The engine's head floor has no posture that satisfies its own two rules

**What had to be decided: where the write happens.** Not a patch — a deployment topology choice.

`bro_completion`'s anti-rollback floor asks two things of the directory holding its marks: `bro_custody`
refuses a directory the polices account can rewrite, and the code has to be able to write a mark into it.
Every posture was driven against a real directory on Windows, and none satisfies both:

| posture | result |
|---|---|
| writable, self-owned | custody REFUSES — "can be rewritten by the very account it polices" |
| DENY ACE on WD/AD/DC | the write REFUSES `[Errno 13]`, **and custody still refuses**, because the process owns the directory and so holds `WRITE_DAC` |
| `BRO_OPERATOR_ROOT_PIN_SELF_OWNED` declared | it advances — with every custody rule in the runtime switched off |

The reason is structural: **the builder is the writer.** The floor exists to stop the builder rolling
evidence back, and the builder is the only principal that ever writes it. On POSIX the weaker form holds —
creating `<task>.floor.json.tmp` and renaming needs `w+x` on the directory, which the custody rule refuses.

**What was already tried and is now closed off.** On 2026-08-10 the obvious escape — "route it to the
supervisor's durable ledger, which already has a floor written by a different uid" — was investigated and
**disproved by execution**, not by argument. The two floors measure different numbers: the ledger counts per
INSTALL and, deliberately, as an install-wide ceiling; this one counts per TASK with every task's first
anchor at 1. Offering two real signed heads (task-1 seq 1, task-2 seq 1) to the ledger refuses the second
with `EvidenceFork` — so routing completion there would make **the second task in any deployment permanently
un-completable**. It is also unreachable from the completion path (Linux-only AF_UNIX + `SO_PEERCRED`,
broker uid only), **absent entirely on Windows** (open finding R-42), and has no column for
`evidence_head_sha256`, which drives the "same sequence, different signed head" refusal. The docstrings that
recommended that route have been corrected so the next reader does not repeat it.

**The real options — decided 2026-08-14, option 1 taken (see the RESOLVED block above):**
1. ✅ **A floor-writer service** — a small always-on principal that owns the marks directory and accepts
   append-only advance requests from the builder. **TAKEN.**
2. ❌ **A setuid helper** — the same idea without a resident service; the repo already ships a setuid launcher
   pattern for the Linux live kit. **Not taken:** `setuid` does not exist on Windows, which is the platform
   every posture in the table above was driven against, so it would have required the service anyway.

Until one of them exists, the floor's custody rule is satisfiable only by the acknowledgement, which
switches off every custody rule at once. That is recorded in the code as a contradiction rather than papered
over: `HeadFloorConfigurationContradictionTests` asks both rules of a real directory and skips by name where
a posture needs elevation, and both `_head_floor_dir` and `_advance_head_floor` carry warnings saying the
escape route in their own text cannot be configured.

## 1c. RESOLVED 2026-08-10 — `challenge_handle` covers `{payload, sig}` (Architect decision, taken)

**This is closed. It is kept on this page as the record of what was decided and on what grounds, not as
something waiting on you.** No Owner action is required for 1c.

**The contradiction.** rev-30 defined one field two ways. §3's artifact matrix, §4.10(a0) and Appendix B's
handle matrix all said `challenge_handle = SHA256(JCS({payload, sig}))`. The shipped
`governed_supervisor.accept_open` computed `SHA256(JCS(payload))` — the payload alone — and §5's own summary
table recorded that as correct. The §4.10(a0) open path landed on 2026-08-10 followed the §3 half, so for one
and the same turn the staging row's handle and the acceptance row's handle were digests of DIFFERENT byte
strings and §4.10(d)'s join on `(install_id, request_nonce, challenge_handle)` could not succeed.

**The ruling: §3 / §4.10(a0) / Appendix B are normative. `accept_open` was wrong and is corrected; §5's
summary table is corrected to match.**

**Why, in increasing order of force.**

1. §3 and §4.10(a0) *define* the field. §5's table was *describing* what the code happened to do. A
   definition outranks a description, and §0 says the design document wins over the code.
2. `{payload, sig}` is the strictly stronger binding — two distinct signatures over one payload get two
   distinct handles, which is the property a content address should have.
3. **Decisive, and it is not an argument from authority.** §7's challenge predicate fetches the stored
   document BY `challenge_handle` and re-hashes the exact stored bytes: `SHA256(bytes) == challenge_handle`
   AND `bytes == canonical_bytes({payload, sig})`. The stored document *is* the signed `{payload, sig}`
   envelope (§2.1.1 `issued_challenge_document`, §6 step-1 publish). Under the payload-only form that
   predicate could never pass for ANY turn. §5's half was therefore not a weaker-but-workable alternative;
   it was incompatible with §7, and no reading of the document makes it work.

**What the §5 form bought, and why losing it costs nothing.** Hashing the payload alone made two different
signatures over one payload collapse to ONE handle, so a re-signed replay hit `UNIQUE(challenge_handle)` and
was served the original lease. Under the `{payload, sig}` form it misses that lookup — and then collides on
`UNIQUE(install_id, request_nonce)` and is refused `nonce_rebound_to_different_turn`
(`governed_supervisor_ledger._prepare_locked`). It still buys **zero** additional execution attempts. The only
change is that a re-signed document is refused instead of quietly served the original lease, which is the
fail-closed direction. This was checked by reading the CAS path, not assumed.

**Blast radius, established by searching before anything was changed.** Producers of `challenge_handle`:
`governed_turn_open.verify_open_request` (§4.10(a0), already the `{payload, sig}` form — unchanged),
`governed_supervisor.accept_open` (corrected), and the win-live kit's `servers.rs::accept_open` (corrected the
same way). Consumers: the two `supervisor_ledger.sql` copies' `UNIQUE(challenge_handle)` and the staging
table's, `governed_supervisor_ledger.reuse_or_prepare` / `_prepare_locked` / `_BOUND_FIELDS`,
`governed_staging_ledger.load_staging_by_handle`, `build_terminal_record`, `core/src/supervisor_ledger.rs`,
and the win-live terminal record — every one of them is opaque to the formula and takes the handle as given.

**No durable artifact was invalidated.** No committed fixture, receipt, attestation, evidence row or recorded
proof under `apps/desktop/AUDIT/` or `apps/desktop/src-tauri/win-live/proof/` contains a `challenge_handle`
VALUE at all. Established by grepping every tracked file for a `"challenge_handle"` JSON field with a 64-hex
value (no hits) and every 64-hex literal in those directories (5 hits: 4 are the `supervisor_ledger.sql`
digest, 1 is an `output_handle`). `apps/desktop/AUDIT/2026-08-06-remediation-audit.md:166` *describes* the old
formula in prose — it is a historical record of the code at `219c763` and is deliberately left as written.

**Nothing was unlocked by this.** `governed_verification_unconfigured()`, `UpstreamBlockedExecutor` and
`connect_broker()` are untouched; no governed surface became reachable and no production `trusted_verified`
can be produced. §4.10(d) itself is still NOT IMPLEMENTED — this only makes the join it will need
satisfiable.

## 1d. RESOLVED 2026-08-12 — §4.10(g) is the real path; the direct-AF_UNIX one is retired

**The Owner's decision, taken 2026-08-12: the §4.10(g) sidecar ladder is the production path, and the
broker's direct-AF_UNIX `GovernedChain` is removed rather than kept beside it.**

The decisive fact, and the reason this was not a matter of taste. `broker/src/manifest_resolver.rs`'s
`ProductionResolver` supplies `system_sha256`, `history_sha256` and `generation_config_sha256` from
**static deployment config** — its own doc comment calls per-conversation facts "a follow-up protocol
slice". So on the shipped path the signed envelope binds *what the config says*, not what the user typed.
A "Verified" badge over that would claim a binding to the conversation that does not exist. The §4.10(g)
ladder computes all three from the actual conversation.

Two supporting reasons. The ladder is **proven end to end on a real Linux runner** — seven principals,
`SO_PEERCRED`, the setuid launcher, the real contained execution, the §4.10(f) pull, and four negatives
refused by name (runs 31606043144 and 31621209556). And keeping two implementations of one contract is the
defect this repository found **eight times in three days**; the decision that ends the pair is worth more
than either implementation.

**What this decision does NOT authorise.** The shipped gate stays shut. `main()` keeps
`UpstreamBlockedExecutor`, `governed_verification_unconfigured` keeps returning `Some(...)`
unconditionally, and no production `trusted_verified` becomes producible. Building the broker's new path
and *serving* it are separate steps: the second still requires every blocker closed, a **separate**
independent audit, and the Owner's approval. That constraint is unchanged by this decision and is not
implied by it.

**The superseded question is kept below as the record.**

## 1d (superseded). Who spawns the recorder — the broker egress is a topology decision, not a bug

**What you have to decide: which principal runs the model, and therefore who publishes its output.**

I sent an agent to make the broker *pull* its output through §4.10(f) instead of reading it off the disk.
It stopped before changing anything and proved the change is not available. Five independent blockers, each
sufficient alone:

1. **There is no sidecar principal.** The live kit provisions six accounts — broker, challenge, supervisor,
   recorder, signer, executor. No `brops-sidecar` exists, and nothing proxies anything.
2. **The supervisor serves no reads and mints no streams.** `run_supervisor.py` constructs no
   `OutputReadService`, and without one every output-read is refused **and** `complete-run` mints no token.
   The two are deliberately paired in the code.
3. **The broker's uid is refused by construction** even if it were configured: the read gate requires the
   *sidecar* uid, and §2.6 requires broker and sidecar to be distinct principals. A broker-direct read is a
   permanent refusal.
4. **The ordering is circular.** The token reaches a client only through the §4.10(e) frame, which is
   reached only through a sidecar-gated evidence request the live path never knocks on — and the mint
   happens *inside* `complete-run`, which requires the output's own digest. So at the line where the read
   sits, no stream can exist yet; and after `complete-run` there is no token to present.
5. **The broker binary has no sidecar spawn and cannot acquire one locally.** Its only `Command::new` is
   the recorder; the one hardened spawn in the tree lives in a *binary* crate that cannot be depended on.

**And the honest correction to how I described this.** "The broker reads output off disk" reads worse than
it is. `verify_and_accept` still applies the §7.1 length-and-digest gate against the signed envelope, and
`complete-run` cross-checks the output handle against the recorder's own evidence chain — so this is a
**confinement** divergence, not an output-integrity hole. The sharper violation is the one neither I nor the
audit named: **the broker is a member of `brops-store` and writes the signer's inputs**, performing the
recorder's own §2.3 publication duty inside the protected store. §2.3 says the broker is in neither
`brops-store` nor any owner group.

**The two real options:**
1. **Build the designed topology** — a 7th `brops-sidecar` principal with its sudoers and ACLs, a running
   sidecar server, the supervisor's four services wired, §4.10(g) implemented, and a supervisor-side
   `ExecutionService` so the *supervisor* spawns the recorder rather than the broker. The Python half of
   that already exists (`governed_acceptance.ExecutionService`) and its only non-refusing implementation is
   a test fake; the privileged execution exists solely as the broker's Rust `LinuxGovernedExecution`. The
   two halves of §6.1 step 5 live in different processes on different sides of this divergence.
2. **Take the narrow confinement fix first** — remove the broker from `brops-store` and stop it writing the
   signer's store, by moving the output and containment publication to the recorder, which already writes
   both. That is a live-kit and recorder change, not an egress change, and it closes the §2.3 violation
   without waiting on the topology.

Option 2 is available now and is strictly smaller. Option 1 is what §4.10(f) actually describes. **Neither
was taken without your decision**, because the change is "who spawns the recorder", and that is not a
Builder's call.

## 2. The independent audit, then your approval

The gate does not open when these settle. It needs an audit of the whole chain **by someone who did
not build it**, and then your approval.

A green CI is not an audit. CI runs the tests we wrote. Audits on this repository have come back RED
on rows the builder had marked closed — which is why a tick in these documents means *independently
confirmed* and a half-tick means *the builder's unverified claim*.

**Concretely, as of 2026-08-15:** two more independent rounds have run since, and the header of this
page carries what they found. The gate is still shut and the standing verdict is still **RED**, but
the *reason* has changed shape: it is no longer "nobody who did not build this has looked."

This paragraph used to end with exactly that sentence — *"nobody who did not build this has looked at
any of it"* — beside *"as of 2026-08-09"* and *"`main` is now `b3010f6`"*. All three went false when
the third round ran, and the fix landed on the block at the top of this page while **this** paragraph,
four hundred lines down and on the same subject, kept saying the opposite. A page can contradict
itself in two places and still look maintained from either one; that is the whole failure mode this
document exists against.

What has **not** changed, and is still the item on this page with the longest lead time: an audit
covering the **whole chain** at a **current** head. Rounds three and four were scoped — five findings
and then a re-audit of those five fixes — and `main` has moved many times since `0a9a1af`. Everything
closed since is the Builder's claim until someone who did not build it says otherwise.

---

## 2a. RESOLVED 2026-08-15 — both Phase-2 decisions taken, by delegation

> **You delegated both** — *"decide for me, and let it be the strongest and most correct, not the
> easiest and fastest"* — so they are taken, and what follows records **what was decided and why**,
> including the part where the easiest answer was also the one already written down as correct.
> Phase 2 is now **8 of 11** boxes ticked. The three that stay open are one fact, tracked as `T-021`.
>
> **(i) `sigbreathe` — DECIDED: apply it, bound to state. Built.** The recommendation on this page
> an hour earlier was to amend §D and keep the surface still. Reading `Security.tsx` instead of the
> argument about it changed the answer: **the page was already breathing.** `.mc-halo` carried an
> unconditional `secHalo 2.6s infinite`, so the instrument pulsed hardest in `blocked` — the exact
> state its own comment two hundred lines above forbade motion in. *An honesty argument written in a
> comment is not an honesty property of the page.* Amending §D would have ratified the still surface
> the page did not actually have.
>
> "Never animate" and "animate always" were never the only options. The pulse is now bound:
> `checking` (a chain read genuinely in flight) breathes, `broken` takes the faster danger cadence
> §D asks for, `blocked` is **still** — which it was not before. It says *"this surface is reading
> the chain right now"*, a fact, and never *"the chain is alive"*, which the desktop cannot
> establish. And the obvious third reading — gate the pulse on a **confirmed** chain — was rejected
> on inspection: `RECORDS_ARE_AUTHENTICATED` is permanently `false`, so that branch could never run,
> and a branch that cannot run is the shape this repository deletes rather than ships.
>
> **(ii) approval-request — DECIDED: opened as `T-021`, still not built here.** Neither option on
> offer was right. *Build it now* adds a new input to the engine's trust boundary while the standing
> verdict is **RED**, and breaks Phase 2's own scope line. *Carry it* is how an obligation
> disappears — and this one is in Phase 2's **acceptance criteria** (*"owner can request an approval
> that the engine adjudicates"*), so the phase would have closed over a promise kept only in prose.
> So the task exists, **sequenced explicitly behind the standing audit**, with its five contract
> invariants written down **now** — no key/lease/nonce/verdict crosses; the desktop requests and
> never decides; the desktop's own T-010/T-011 authority stays separately named in the UI;
> `RECORDS_ARE_AUTHENTICATED` stays false; the engine schema change is audited **before** it lands.
> Fixing them now means the contract test is not designed by whoever is trying to pass it.
>
> **Nothing here opened the gate, and nothing here is a claim about the audit.** Both marks are the
> Builder's until someone who did not write them looks.

*The original statement of the two decisions is kept below, because a decision is only legible
beside the question it answered.*

## 2a (as posed). Phase 2 is finished except for two decisions, and both are yours

Phase 2 was **checked against the code before anything was built** (T-019, 2026-08-15) — all four
governance pages already existed when the exemption unlocked the phase, so the first act was
verification. Six of eleven boxes are ticked with file/line/test evidence. The five that are not
reduce to **two facts, and neither is a missing page or a build task.** They are on this page because
the roadmap routes both here, and until today this page did not name either.

**(i) The `sigbreathe` integrity pulse — a §D wording question.** §D specifies a breathing pulse as
`security`'s motion. `Security.tsx` renders a **non-live** wire instead — *"the chain does not flow —
nothing is confirmed"* — because the integrity posture is `blocked`. Applying the pulse would satisfy
§D's letter by painting liveness onto a surface that has established nothing. A Builder resolving this
by adding the motion would be choosing the spec's letter over its meaning on its own authority, so it
is left here. **You are deciding between two readings of your own spec**, not approving a change:

| Option | What it means |
|---|---|
| Amend §D | motion is conditional on a *confirmed* chain; the still wire is correct and box 1 · 9 ticks as-is |
| Keep §D literal | the pulse is applied unconditionally, and the page animates a chain it cannot verify |

The recommendation is the first: every other surface in this repository is built to refuse rather
than to imply. But §D is yours.

**(ii) The approval-REQUEST path does not exist, on either side — and this phase pre-authorised
that.** There is no `approval-request` schema in `engine/schemas/` (21 schemas; none is one) and no
desktop→engine command. The `approvals` page's grant/deny/escalate are real and correctly gated —
behind a native confirmation the webview cannot forge — but they drive the **desktop's own** approval
system (T-010/T-011 over local SQLite), not a request across the wall. Phase 2's own **Contracts**
row says an `approval-request` needing an engine schema change is *"an audited engine task, flagged,
not done here."* It is flagged. **What is yours: whether to open that audited engine task now, or
carry it into a later phase.** Nothing is blocked on it today — the read half is complete and wired
end to end.

Boxes 2 · 7 · 11 are unticked for (ii); boxes 1 · 9 for (i). A box whose surface exists but whose
obligation is unmet stays unticked and says which obligation — which is why five look open on a phase
that has nothing left to build.

---

## 2b. Who reviews a §I design proposal when there is no Architect (PR #112)

**PR #112 is open and deliberately not merged.** It is the floor-writer service design (T-020) — the
implementation route for §1b, which you resolved on 2026-08-14 in favour of a service over a setuid
helper. It is a **§I design proposal**, and §I requires a design review the Builder cannot perform on
its own work. The session that wrote it caught itself recommending its own merge and corrected that
before handing over; the precedent (PR #30) is merge only **after** a design review.

There is no Architect. This is the same problem the independent audit had, and the same answer is
available: **a separate clean-context session in an auditor role** — which is what this repository
has always meant by "independent", and what produced rounds three and four.

If that route is used, the verdict must be recorded as **what it is**. `OWNER_APPROVED_NOT_ARCHITECT_AUDITED`
exists for exactly this distinction and is already the value of `CURRENT_DESIGN_GATE`. A design review
by an auditor session is **not** Architect GREEN, and recording it as one would be the F-02 pattern —
a claim promoted a grade above what produced it — in the one place a promotion is hardest to see.

`B-02` from the fourth audit sits beside this and stays **OPEN**: the anti-rollback floor has **three**
claimed owners — the rev-30 addendum §7 P1-7 and `supervisor_ledger.rs:20` say `brops-signer`; the
DDL, the CAS and the only process that opens the file say the supervisor; the scope-key pin is the
challenge authority's. The design also introduces an **eighth principal**, which amends the addendum's
normative §2.5/§2.6 — *"the SEVEN runtime service UIDs"* — and FW-3 is blocked on that amendment.
Both are §I territory, which is to say: the same review.

**A structural note, found by parking it.** PR #112 went `MERGEABLE` → `CONFLICTING` the moment
anything else merged, and it will do so again after every merge. It is not a bad rebase — the PR
writes `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md` and `config/current_state.json`, which are the
**carrier** files every merge rewrites by ritual. A design proposal that claims the carrier cannot be
parked; it can only be merged or rebased forever. Worth fixing in whichever direction you choose:
either a §I proposal stays off the carrier files and lives in `docs/design/` alone, or design
proposals are reviewed and merged promptly rather than parked. Recorded, not acted on — changing
what a design PR is allowed to touch is itself §I.

---

## 2d. DECISIONS TAKEN 2026-08-17 — four answers, and what each one commits us to

The Owner was given the open decisions as options with a recommendation each, and answered all
four. Recorded here as **decisions**, not as status, so the next reader inherits the reasoning and
not just the outcome.

**A — the sixth independent audit runs NOW, on `main` @ `35cc40b`.** Not after `T-021`/`T-022`
land. Twenty-four merged pull requests have accumulated since the fifth round's pinned head and
**not one of them has been looked at by anyone who did not write it**. Waiting would have doubled
that, and the deferred work is itself sequenced *behind* the audit — so "audit once, later" was a
plan that could never start. The fifth round found a rendering regression **one round** after it
shipped; the cost of accumulation is measured, not hypothetical.

**B — `T-021`, `T-022` and Phase 9's connectors are built AFTER the audit, if it passes.** Each is a
**new input to the engine's trust boundary** and the standing verdict is RED. The boxes stay
**open** in the meantime.

> The Owner was offered a third option — amend the phase scope so those boxes leave by definition,
> which is the **only** way phases 1–9 could read 100% today — **and declined it.** That is the
> decision worth recording: a phase that closes because its scope was trimmed to fit is the exact
> shape every audit round has punished, and 1–9 will reach 100% by being finished, not by being
> re-described.

**C — PR #112's §I design review goes to a separate auditor-role session.** The same route that
produced rounds three and four. Its verdict is recorded as **what it is**:
`OWNER_APPROVED_NOT_ARCHITECT_AUDITED`, never as Architect GREEN. Note the standing cost of the
delay — #112 writes the four carrier files, so it **conflicts after every merge** and will need a
rebase whenever it is finally taken.

**D — O-1 is to be DONE, not deferred.** It is the only **HIGH** of the five and the only one with
a written way to accept the risk instead; the Owner chose the fix. **O-2…O-5 keep no new
instruction and therefore stay OPEN** — which §2c says plainly is the one answer that is not a
decision. They remain five sentences away from being settled.

**What O-1 needs from you, exactly.** Make the control-plane tree **unwritable by the account that
runs the engine**, then *prove it on the real install* — the item's own words are that a packaged
install *"gives it for free"* on `Program Files` / `/opt` / `/Applications`, and that this
**"needs verifying on a packaged build rather than asserting."** The assertion is not the closure;
the verification is. On Debian that is a bind mount
([`DEBIAN_DEPLOYMENT.md`](./DEBIAN_DEPLOYMENT.md)). When it is verified, the item's status line
moves to `CLOSED` **with a `Sign-off:` line** — `tools/check_residual_items.py` refuses the change
without one.

---

## 2c. O-1 … O-5 — all five are waiting on you, and this page said four of them were not

You gave the go on `T-004` (2026-08-16). Working it turned out to mean **reading what each item is
actually blocked on** — and the answer is the same five times: **the code half is built and the
remaining half is a deployment act only you can perform.** Not one of them needs a Builder change.

**And §3 below listed four of them under *"Open, and not waiting on you."*** That heading was false
for O-1, O-3, O-4 and O-5. It is the same failure this page has now been corrected for three times:
the one page that answers *"what is waiting on me"* answering **no** when the answer was **yes**.
Corrected here; §3 keeps only what genuinely is not yours.

Phase 10's exit criterion is *"O-1..O-5 **closed or owner-signed-deferred** (each audited)"*, and
the mechanism for the second half already exists: `tools/check_residual_items.py` accepts
`OWNER-DEFERRED` and **refuses any status change without a `Sign-off:` line**. So each of these is
one decision with two legal answers — **do the act**, or **defer it by name**. Leaving it OPEN is
the only answer that is not a decision.

| item | sev | the one act that closes it |
|---|---|---|
| **O-1** | **HIGH** | Make the control-plane tree **unwritable by the account that runs the engine** — on Debian a bind mount ([`DEBIAN_DEPLOYMENT.md`](./DEBIAN_DEPLOYMENT.md)). A box that will not do this may **accept the residual risk by name**: `BRO_CONTROL_PLANE_WRITABLE_ACKNOWLEDGED=accepted-o1-residual-risk`. The item's own words: *"that is an owner/deployment decision."* |
| **O-2** | MEDIUM | **Provision the anchor signer's custody.** The signer mints its own Ed25519 key — no offline root artefact is needed — but until custody is configured `append()` writes a plaintext head and **no deployment is anchored**. 26 tests already prove the refusal works, including a ledger whose head was rewritten over dropped records. |
| **O-3** | MEDIUM | A **deploy step** that mints and rotates the operator-root-signed `conductor-session` artifact and exports `BRO_CONDUCTOR_SESSION_TOKEN` to the harness. The code fails closed and the shipped policy already requires it. |
| **O-4** | LOW | **Pin `control-room-command` in the operator-signed registry.** Both actors are signature-verified today; the shipped registry grants the type to nobody, so the check can never pass on a real install. |
| **O-5** | LOW | **Mint the evidence-floor anchor offline**, grant its type to that key in the operator-signed registry, and present the file **under a principal the policed account cannot write**. The manifest binding is built and enforced; this is the credential half. |

**None of the five needs an offline-root-signed Owner secret** — the `Owner secret needed: no` in
the inventory is accurate. What they need is a deployment posture and two provisioning steps.
O-1 is the only **HIGH**, and it is also the only one with a written, named way to accept the risk
instead of fixing it.

**What a Builder can still do here is nothing**, and saying so is the point of writing it down:
every remaining half is an act on a machine you control, with credentials you hold.

---

## 3. Open, and not waiting on you

Recorded so nothing reads as closed that is not. These are being worked.

> **Four O-items used to be listed here and are not any more** — they moved to §2c, because their
> remaining halves are yours. What stays below is genuinely not waiting on you.

- **The committed `engine/config/trusted-keys.json` is a fixture, not a deployment default.** It is
  `production: false`, carries no private half anywhere in the tree, and a real deployment with a
  file pin has never been able to anchor on it. Its cost is confusion rather than forgery: it is the
  thing that answers, which makes provisioned trust look absent. The recommendation is to relocate
  it under `engine/tests/fixtures/` so an unconfigured deployment fails closed with "cannot read
  trusted key registry" instead of quietly loading a development registry. Four dependents would
  name it explicitly. Not done unilaterally — CI depends on it today.
- **Windows key-material permissions are inherited, not set.** `secure_owner_only_file` has no
  non-unix branch, so on Windows the private keys carry the app data directory's ACL — per-user by
  default, plus SYSTEM and Administrators. Failing closed there would mean the app never starts on
  its primary platform, so it is recorded honestly instead: in `PROVISIONING.json`, in
  `POSTURE.txt`, and on stderr at first launch.
---

*Update this file in the same commit as any change to what it claims. A page about what is blocked
is worthless the moment it is stale, and staleness here reads as progress.*
