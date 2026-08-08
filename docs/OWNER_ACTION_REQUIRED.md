# Owner action required

Everything that cannot move without Gev. One page, kept current, so the answer to "what is waiting
on me" is never reconstructed from a chat log.

Nothing here is a suggestion to flip anything. `platform_governed_execution_supported()` is false
and `main()` keeps `UpstreamBlockedExecutor`; that stands until every item below is settled, a
**separate** audit passes, and the Owner approves — in that order.

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

## 1. O-2 — a decision only you can make

**O-2 cannot be closed on this product, by provisioning or by anything else, and that is a property
of the shape rather than a gap in the work.**

It requires `BRO_AUDIT_ANCHOR_SIGNER`: an executable outside `engine/`, run **under a principal that
cannot write the audit ledger**. A single-user desktop application has exactly one principal.
Provisioning can supply the key — the minted `evidence-recorder` key qualifies — but it cannot
supply a second person.

Shipping a signer helper the app invokes itself would produce anchors that verify and prove nothing,
because the account that signs the anchor is the account that can rewrite what it attests. That is
precisely the failure the item exists to name, so it was not built.

You chose the second principal, and it is built: a Windows service under a virtual account, its own
key, reached over the existing named pipe. Proved end to end against the real `bro_audit_log` — and
proved, in the same run, that it does not yet close O-2.

**Why.** `provision()` keeps every private half in the app's own trust store, and two of those keys
are anchor-capable. `verify_signed_payload` accepts any active registry key under either anchor
authority. So the ledger's writer can truncate the chain, re-sign it with a key it holds, and the
real verifier returns green. `bro_audit_log` states the assumption four lines above the constant —
*"The builder/writer of the ledger holds neither"* — and that stopped being true the moment the app
started minting its own root. Nothing failed, because the sentence is a comment.

**What closing it needs**, and why it is not a signer change: the registry must stop carrying an
anchor-capable key whose private half the app holds. The clean form is a dedicated anchor authority
that only the service ever possesses. That collides with O-3 and O-5, which both mint with
operator-root, so it is a custody restructure rather than a patch. It is next.

A self-destructing test holds the line meanwhile: it asserts the gap still exists and goes red the
day it is fixed.

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
