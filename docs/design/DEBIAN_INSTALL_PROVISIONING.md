# Debian install provisioning — the installer that mints trust as another uid · DESIGN

> **Հայերեն ամփոփում.** Debian-ի վրա ծրագիրը առաջին գործարկման ժամանակ trust ստեղծել չի կարող,
> որովհետև POSIX-ում ֆայլի տերը միշտ կարող է այն փոխել։ Ուրեմն trust-ը պիտի ստեղծի **installer-ը, root-ով**,
> ծրագրից առաջ։ Այս փաստաթուղթը նկարագրում է այդ installer-ը՝ մեկ privileged հրաման, որը `.deb`-ի
> `postinst`-ը կանչում է։ Այն ստեղծում է OS օգտվողներին, engine-ի trust anchor-ը, broker-ի root-ը (T-131)
> ու այն ամենը, ինչ CI-ի ladder kit-ն այսօր անում է։ Քեզանից key կամ քայլ պետք չէ (#78)։ Քո հաստատումն է
> պետք միայն այս դիզայնի համար։

Status: **PROPOSED, not approved.** Task `T-131`. Written 2026-10-01. Nothing here is built.
Every claim below is marked ✅ read in code at `4b25650`, or ◑ inference / proposal.

## 1 · The decision this serves

The Owner decided on 2026-08-09 (#78): *install it, and everything is already done; no keys to carry,
nothing ever asked again, on any OS.* On Windows the install does it (`provision/`). On Debian nothing
does, and the code says so in its own words ✅ (`provision/src/anchor.rs:270-277`): *"no shipped tool
creates it yet — the installer that mints an anchor as another uid is not written, so this platform
is NOT supported for a first launch today."*

## 2 · Why the app cannot do it itself (✅, and not negotiable)

`anchor.rs:76-82`: there is no unprivileged POSIX construction. An owner may always `chmod` what it
owns, so any anchor the app's own account built is one it could rewrite — the pin-rewrite attack
`audit-signer/tests/anchor_end_to_end.py` case `pin-rewrite` ran for real. So the anchor must exist,
owned by a different uid, **before the app starts**; and when it does, `provision_with_anchor`
already verifies and uses it ✅ (`provision/src/lib.rs:1380-1382`). The missing piece is exactly one
privileged step at install time.

## 3 · What one install step must leave behind

Measured from what is missing, not invented:

| need | today | source |
|---|---|---|
| engine trust anchor at `/var/lib/brops-trust-anchor/trust-anchor`, root-owned 0755, pin/floor/manifest 0644 | nothing creates it ✅ | `anchor.rs:132`, `:270-277` |
| broker TCB root that someone actually controls (`custody.tcb_root_manifest_signature`) | compiled pin, private held by nobody ✅ | `broker/src/tcb.rs:9-17`, `preflight.rs:324` |
| 13 installer + 11 machine-admin preflight rows | only the CI kit provides them ✅ | `preflight.rs:144-341`; `engine/ci/live/run_ladder_turn.sh` |
| a second principal for O-1 (engine tree not writable by the enforcing account), O-2 (audit signer account), O-3 | none on POSIX ✅ | `docs/PHASE_10_PRODUCTION_ITEMS.md`; `audit-signer/src/register.rs:401-412` |

The CI ladder kit already performs most of the third row as root ✅ — accounts, setuid launcher,
sudoers, store modes, `$BROPS_BROKER_CONFIG`, the §2.5 pin manifest. It is the working prototype.

## 4 · The construction (◑ proposal)

**One binary, `brops-install`, in the `provision` crate, run once as root by the package's
`postinst`, idempotent.** It refuses unless `euid == 0`, and it is the only code path allowed to
create anything under `/var/lib/brops-trust-anchor` or `/opt/brops`.

1. **Accounts.** Create the seven fixed principals the kit uses ✅ (`run_ladder_turn.sh:89-95`:
   `brops-verifier_broker`, `brops-challenge`, `brops-supervisor`, `brops-recorder`, `brops-signer`,
   `brops-executor`, `brops-sidecar`) as system users, plus
   `brops-anchor` for the anchors. Pairwise distinct; refuse if any exists with a different shape.
2. **Engine anchor.** Run the existing `mint` for the **desktop user** named on the command line
   (`--user`, which `postinst` takes from `SUDO_USER` or debconf), with `machine_root` =
   `/var/lib/brops-trust-anchor` owned by `brops-anchor`. The user's `<app_data>/trust` is chowned to
   that user; the anchor stays `brops-anchor`-owned. The operator-root private is destroyed before
   `mint` returns, exactly as on Windows (`lib.rs:1351-1356`).
3. **Broker root (T-131).** Generate a fresh Ed25519 root, sign the broker `KeyManifest` naming the
   serving keys minted in the same run, write `root-anchor.json` into the root-owned TCB directory,
   and **destroy the root private before exit**. Nothing keeps it — not the kit's `keys/root.priv`
   habit, not a backup. Rotation = reinstall (§7).
4. **Deployment.** Everything the ladder kit does today for the 24 rows, from the same code:
   setuid launcher 4750, sudoers fragments, store/floor modes, `write_broker_config.py`'s config,
   the §2.5 pin manifest built **after** every pinned file is in place, and `BROPS_BROKER_CONFIG`
   set in the broker's systemd unit `Environment=`.
5. **Proof before exit.** Run `ladder_turn --verify-tcb` and the broker's own preflight as the
   broker uid; on any refusal, exit non-zero so `dpkg` reports the install failed — never a
   half-provisioned box that looks provisioned.

## 5 · The trust change, and the one rule that keeps it honest (◑ proposal)

Today the production root is a **compiled** constant, so a config writer cannot swap it ✅
(`tcb.rs:1-6`). An install-minted root cannot be compiled in. The replacement:

* A new provenance, **`install_minted`**, beside `external` / `kit_generated` / `demonstration` in
  `core/src/key_manifest.rs:102`. It is the only one that supports a production claim; `External`
  (an offline holder) stops being reachable at all, which is what #78 means.
* The broker reads the root from `root-anchor.json` in the TCB directory, and accepts
  `install_minted` **only** when that file passes the §2.5 floor: root/`brops-anchor`-owned, every
  ancestor too, not writable by the broker uid, and pinned by the pin manifest. A file that says
  `install_minted` anywhere else is refused, as T-126 refuses `external` today.
* **The rule:** *the label is earned by WHERE the file sits and WHO can write it, never by what the
  file says.* That is the same lesson as T-126, and the throwaway-relabel negative in CI extends to
  it: the kit writes `install_minted` into a broker-writable path and the driver must refuse.
* The CI kit keeps `kit_generated` and keeps its root private on disk; it can never satisfy the
  custody floor, so it can never render production.

**What this claims, and does not** (the #78 trade, unchanged): it defends against an attacker who
arrives after install without root. It does not defend against one who owned root at install, and
it cannot prove the root private was destroyed — only that no file on the box holds it, which
`tools/check_root_anchor_custody.py`'s sweep idea can be extended to check on the installed box.

## 6 · Alternatives considered

* **The app mints at first launch on Linux too.** Refused by §2: an anchor the app's account built
  is one it can rewrite. Not an option, a measured attack.
* **A `pkexec`/polkit helper at first launch instead of `postinst`.** Workable, and it would let the
  user be known for certain. But it adds an interactive privilege prompt to every first launch and a
  setuid/polkit surface that lives forever. Rejected in favour of the one-shot install step.
* **Keep the compiled pin and let the install re-sign under it.** Impossible: nobody holds its
  private half, and #78 forbids anyone holding one.

**Recommendation: §4 as written — one idempotent `brops-install` run by `postinst`, with
`install_minted` earned only by the §2.5 custody floor.** It is the only option that needs no person,
no prompt and no key, and its prototype (the CI kit) is already green on every run.

## 7 · What it costs, said now

* Rotating the broker root, or the engine anchor, means reinstall — same cost `POSTURE.txt` already
  states for the Windows trust store.
* A per-user product: `--user` binds the trust store to one desktop account. A second user means a
  second install. Acceptable for a one-user product; stated so it is not discovered.
* `tauri.conf.json` must carry a `postinst` script and bundle `brops-install` plus the service
  binaries. ◑ Whether Tauri 2's deb bundler exposes a post-install hook in our version is **not yet
  verified** — first task of slice A.

## 8 · Slices (they parallelise once this is approved)

* **A — packaging:** Tauri deb hook, bundling, systemd units. Verifies §7's open question first.
* **B — `brops-install` accounts + deployment:** port the ladder kit's root steps to Rust/Python
  under one entry point; CI runs it in a container and then runs the existing ladder phases against
  the result instead of against the kit.
* **C — broker root (T-131 proper):** `install_minted` provenance, the anchor-file resolver, the
  custody-floor gate, the relabel negative; retire `ROOT_PUBLIC_KEY_HEX` and `OfflineRootCustodian`.
* **D — engine anchor on POSIX:** `mint` with `brops-anchor` as the anchor owner; O-2's signer
  account and O-1's tree ownership ride on the accounts from B.

A and D are independent; B and C share the TCB directory layout, so C starts after B fixes it.
Merges stay one at a time.

## 9 · What needs the Owner

Approval of this design, nothing else. No key, no ceremony, no step on any machine.
