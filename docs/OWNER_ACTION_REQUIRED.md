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

Phase 10's exit criteria allow "closed **or owner-signed-deferred**". This is the deferral case.
The decision is yours: accept O-2 as a documented residual for the desktop shape, or require a
second principal — a service account, a separate machine — and accept that the product then needs
one.

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

- **O-3 — the artifact verifies; the engine cannot see it.** `load_trusted_keys` reads
  `<root>/config/trusted-keys.json` and `bro_hook.py` passes the engine's own tree, so the
  app-provisioned registry is invisible to it and a different, older, development registry answers
  instead. The minted token is accepted the moment the registry is at that root — the cross-language
  test proves both directions. Wiring the engine to the provisioned store is the remaining work.
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
