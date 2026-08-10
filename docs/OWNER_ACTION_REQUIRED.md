# Owner action required

Everything that cannot move without Gev. One page, kept current, so the answer to "what is waiting
on me" is never reconstructed from a chat log.

Nothing here is a suggestion to flip anything. The governed surfaces stay fail-closed until every
item below is settled, a **separate** audit passes, and the Owner approves — in that order.

> **The standing audit verdict is RED, and it is older than the code.** Two independent audits have
> run. The second — [`apps/desktop/AUDIT/2026-08-06-remediation-audit.md`](../apps/desktop/AUDIT/2026-08-06-remediation-audit.md),
> of `main` @ `219c763`, AFTER the first round's remediation — confirmed **4 of 18** blockers closed
> and left **122 surviving findings** (1 P0, 7 P1, 32 P2, 82 P3). Its P0 was that the supervisor
> still copied the executing chain's own `output_handle` into the attestation it signed: the F-01
> signing oracle surviving a fix that addressed F-01's symptom. **It has never been re-run**, on that
> head or on any of the later ones, so nothing since is independently confirmed. The index is
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

## 1b. The engine's head floor has no posture that satisfies its own two rules

**What you have to decide: where the write happens.** Not a patch — a deployment topology choice.

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

**The real options, both needing your call:**
1. **A floor-writer service** — a small always-on principal that owns the marks directory and accepts
   append-only advance requests from the builder.
2. **A setuid helper** — the same idea without a resident service; the repo already ships a setuid launcher
   pattern for the Linux live kit.

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

## 1d. Who spawns the recorder — the broker egress is a topology decision, not a bug

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

**Concretely, as of 2026-08-09:** the last independent audit returned **RED** with 122 surviving
findings, it assessed `main` @ `219c763`, and `main` is now `b3010f6` — so a large part of that
verdict describes code that has since changed, in both directions, and **nobody who did not build
this has looked at any of it.** Findings closed since are the Builder's claims. This is the item on
this page with the longest lead time and nothing else on it substitutes for it.

---

## 3. Open, and not waiting on you

Recorded so nothing reads as closed that is not. These are being worked.

- **O-3 — the engine can now see it.** `BRO_TRUSTED_REGISTRY_ROOT` redirects where the registry is
  read, fail-closed, with the operator-root pin deliberately staying where it was: a redirect that
  carried the anchor along would have handed over the whole thing. Proven in both directions against
  the real verifier, including that a token accepted by *a* provisioned registry is still refused by
  *this* deployment's. **The startup wiring landed on 2026-08-09.** `Provisioned::engine_env()` now
  returns all **five** variables — `BRO_TRUSTED_REGISTRY_ROOT` plus `BRO_OPERATOR_ROOT_PUBKEY_FILE`,
  `BRO_OPERATOR_REGISTRY_MIN_FILE`, `BRO_CONDUCTOR_SESSION_TOKEN` and `BRO_SESSION_ID` — and
  `apps/desktop/src-tauri/src/engine_trust.rs` applies the set to the engine child at the one seam
  that launches it, whole or not at all, refusing by name when an inherited anchor disagrees.
  `apps/desktop/src-tauri/tests/o3_conductor_session.rs` proves it against the real Python:
  accepted with the export, refused without it and refused pointed elsewhere. What is left is **not**
  an export — it is that the desktop's engine entry point (the bridge sidecar's real mode) is itself
  fail-closed until Wave 3b, so a desktop turn does not yet reach `authorize_conductor_stop`.
  *(This bullet has been corrected twice: it once said "the variable ... it already writes", then
  said nothing exported any of the five. Neither is true now.)*
- **The committed `engine/config/trusted-keys.json` is a fixture, not a deployment default.** It is
  `production: false`, carries no private half anywhere in the tree, and a real deployment with a
  file pin has never been able to anchor on it. Its cost is confusion rather than forgery: it is the
  thing that answers, which makes provisioned trust look absent. The recommendation is to relocate
  it under `engine/tests/fixtures/` so an unconfigured deployment fails closed with "cannot read
  trusted key registry" instead of quietly loading a development registry. Four dependents would
  name it explicitly. Not done unilaterally — CI depends on it today.
- **O-5 — deliberately not minted at install.** At install no task exists, and an anchor the app
  mints by reading the store the check polices would restate the store's own claim under a
  signature: worse than none, because it looks like corroboration. `mint_floor_anchor` exists and is
  proven against the real verifier; when it is called is a design question, not a provisioning one.
- **O-1 — a packaged install gives it for free.** The item wants the control plane unwritable by the
  account that runs the engine. `Program Files`, `/Applications` and `/opt` are not writable by that
  account. Needs verifying on a packaged build rather than asserting.
- **Windows key-material permissions are inherited, not set.** `secure_owner_only_file` has no
  non-unix branch, so on Windows the private keys carry the app data directory's ACL — per-user by
  default, plus SYSTEM and Administrators. Failing closed there would mean the app never starts on
  its primary platform, so it is recorded honestly instead: in `PROVISIONING.json`, in
  `POSTURE.txt`, and on stderr at first launch.
- **The minted registry grants `control-room-command`**, which the committed engine registry grants
  to nobody. O-4's code half is closed, so pointing the engine at this registry also provisions
  O-4's key. A consequence worth a decision rather than a silent side effect.

---

*Update this file in the same commit as any change to what it claims. A page about what is blocked
is worthless the moment it is stale, and staleness here reads as progress.*
