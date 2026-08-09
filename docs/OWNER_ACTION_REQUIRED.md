# Owner action required

Everything that cannot move without Gev. One page, kept current, so the answer to "what is waiting
on me" is never reconstructed from a chat log.

Nothing here is a suggestion to flip anything. The governed surfaces stay fail-closed until every
item below is settled, a **separate** audit passes, and the Owner approves — in that order.

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

## 1. O-2 — closed on Windows, and what is left

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

## 2. The independent audit, then your approval

The gate does not open when these settle. It needs an audit of the whole chain **by someone who did
not build it**, and then your approval.

A green CI is not an audit. CI runs the tests we wrote. Three audits on this repository have come
back RED on rows the builder had marked closed, which is why a tick in these documents means
*independently confirmed* and a half-tick means *the builder's unverified claim*.

---

## 3. Open, and not waiting on you

Recorded so nothing reads as closed that is not. These are being worked.

- **O-3 — the engine can now see it.** `BRO_TRUSTED_REGISTRY_ROOT` redirects where the registry is
  read, fail-closed, with the operator-root pin deliberately staying where it was: a redirect that
  carried the anchor along would have handed over the whole thing. Proven in both directions against
  the real verifier, including that a token accepted by *a* provisioned registry is still refused by
  *this* deployment's. What remains is one line in the app's startup — exporting the variable
  alongside the pin and floor it already writes.
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
