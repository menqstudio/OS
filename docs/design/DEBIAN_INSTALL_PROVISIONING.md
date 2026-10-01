# Debian install provisioning — the installer that mints trust as another uid · DESIGN

> **Հայերեն ամփոփում.** Debian-ի վրա ծրագիրը առաջին գործարկման ժամանակ trust ստեղծել չի կարող,
> որովհետև POSIX-ում ֆայլի տերը միշտ կարող է այն փոխել։ Ուրեմն trust-ը պիտի ստեղծի **installer-ը, root-ով**,
> ծրագրից առաջ։ Այս փաստաթուղթը նկարագրում է այդ installer-ը՝ մեկ privileged հրաման, որը `.deb`-ի
> `postinst`-ը կանչում է։ Այն ստեղծում է OS օգտվողներին, engine-ի trust anchor-ը, broker-ի root-ը (T-131)
> ու այն ամենը, ինչ CI-ի ladder kit-ն այսօր անում է։ Քեզանից key կամ քայլ պետք չէ (#78)։ Քո հաստատումն է
> պետք միայն այս դիզայնի համար։

Status: **APPROVED by the Owner on 2026-10-01** («այո»). Task `T-131`. Slice A landed in `T-135`;
slice B's ACCOUNTS step in `T-136` (`engine/install/brops_install.sh accounts`, which CI's two kit jobs
now call instead of running `useradd` themselves); slice D's engine anchor in `T-137`
(`provision::posix_install`, binary `brops_install_anchor`); the installer as the ONE entry point
and its packaging in `T-138`; slice C in `T-140` (the broker reads the floor-pinned anchor; the
production label stays behind `INSTALL_MINTED_CUSTODY_ACCEPTED = false`). Open: B's deployment step
(the 24 preflight rows) and the installer minting the broker root itself. Approval is of the design, not of any slice's code — every slice is ◑.
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
   `brops-executor`, `brops-sidecar`) as system users — uids 5001–5007 ✅ built in `T-136`; note
   `brops-sidecar`'s 5003 has no source in `provision_keys.py`, only in the installer — plus
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
* The CI kit keeps `kit_generated` and keeps its root private on disk. **Corrected 2026-10-01
  (slice C found it):** this page said the kit "can never satisfy the custody floor". That is false.
  The floor proves WHERE the anchor file sits and who can write it — not that the root private was
  destroyed. Any root-run provisioner satisfies it by writing one word, and the kit now carries
  exactly that control: its own root, private half still on disk, relabelled `install_minted` and
  pinned, and the broker accepts the label. It commits as `demonstration_custody` only because
  `INSTALL_MINTED_CUSTODY_ACCEPTED` is `false`. So the constant is not a formality: it is the only
  thing between a root-run kit and a production label, and this belongs in front of the auditor
  before anyone flips it.

**What this claims, and does not** (the #78 trade, unchanged): it defends against an attacker who
arrives after install without root. It does not defend against one who owned root at install, and
it cannot prove the root private was destroyed — only that no file on the box holds it, which
`tools/check_root_anchor_custody.py`'s sweep idea can be extended to check on the installed box.

### 5.1 Slice C in detail (written 2026-10-01, after reading the broker)

What the code already does ✅: `build_governed_executor` runs `verify_broker_tcb` BEFORE it reads
any trust material (`broker/src/main.rs:321-331`), and that floor already pins the role
`key-manifest.root-anchor` (`core/src/tcb_integrity.rs:200`) — owner, mode and digest of
`tcb/root-anchor.json`. But the broker never READS that file: `ProductionResolver::provisioned`
builds its `PinnedRoot` from the compiled constants (`broker/src/manifest_resolver.rs:93-107`), and
`root_provenance` answers `External` by key id (`:154-159`). So the change is narrow:

1. `RootProvenance::InstallMinted` (`"install_minted"`) in `core/src/key_manifest.rs`.
2. After the floor passes, the broker takes the anchor from **the path the pin manifest pinned
   for `key-manifest.root-anchor`** — never from a config field — and builds the resolver from that
   file's key and provenance. `external` stays subject to `check_declared_external_anchor`.
3. `kit_generated` and `demonstration` resolve to `DemonstrationCustody`, as in the drivers today.
   The product broker therefore completes a turn under a kit root and labels it
   `demonstration_custody` — which CI can then prove end to end with the real binary.
4. `preflight.rs`'s `OfflineRootCustodian` provisioner and its row are renamed for what they now
   are (an install-minted root), and the retired provisioner name returns to the ceremony gate's
   phrase list.

**The production label stays behind the Owner's gate — a Builder decision, for the Owner to veto.**
`install_minted` is the only provenance that CAN support a production claim, but it does so only
when a compile-time constant, `INSTALL_MINTED_CUSTODY_ACCEPTED`, is `true`. It ships `false`.
While it is `false` an install-minted root resolves to `DemonstrationCustody { root_provenance:
InstallMinted }`: the whole chain runs and binds, and nothing renders `production_verified=true`.
Flipping it is one line, and it is the Owner's line, after the independent audit — the same rule
CLAUDE.md §6 states for the gate as a whole. Building C does not open the gate; it removes the last
piece that made opening it impossible.

**Built in `T-140`, with these differences from the list above.** `External` still supports a
production claim (it stays unreachable: `parse_root_anchor` accepts it only for the compiled root
nobody holds). `ROOT_PUBLIC_KEY_HEX` is kept, not retired — `check_declared_external_anchor` and
`tools/check_root_anchor_custody.py` use it. The resolver takes a `FloorPinnedAnchor`, a type only
the floor's verdict can construct, and the anchor bytes it parses must hash to the pinned digest.
**To do in the same change that flips the constant:** `TrustState::Production` carries no
provenance and `root_provenance()` answers `External` for it, which would misname an
install-minted root on that day.

What does NOT change: the desktop's own refusal (`governed_verification_unconfigured`, five
compile-time absences) and `connect_broker` off Linux. Windows keeps its compiled pin until a
Windows slice exists.

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
* `tauri.conf.json` carries the `postinst` script ✅ (`T-135`): `bundle.linux.deb.postInstallScript`
  exists in `tauri-utils` 2.9.3 `src/config.rs:372` (`DebConfig`, `deny_unknown_fields`), and
  `tauri-build` accepted the config here. ✅ MEASURED in `T-138` on a real `tauri build --debug
  --bundles deb`: `dpkg-deb -e` shows `postinst` at 0755, byte-identical; `deb.files` is
  `{destination: source}` with the source relative to `src-tauri` (a path reaching outside it is
  accepted), and the mode comes from the source. `tauri build` does NOT build workspace bins, so a
  `beforeBundleCommand` stages `brops_install_anchor`. The package is named `bro-ps`; resources
  would land in `/usr/lib/BroPS`, a third spelling beside `/usr/lib/brops`. No `dpkg -i` was run.

### 7.1 Open questions slice A found (2026-10-01), none decided yet

* **The user to bind to — DECIDED by the Builder in `T-138`, for the Owner to veto.** An explicit
  `--user`; else `$SUDO_USER`; else `$PKEXEC_UID` (what a graphical install sets); else the ONLY
  human account in the passwd database; otherwise a refusal that names the candidates. Never a
  guess, never root, never a service account. Still open: an account that lives only in a directory
  service resolves here through `getent` and is then refused by the anchor tool, which reads
  `/etc/passwd`; and a session that sets `XDG_DATA_HOME` needs `--app-data`.
* **rpm and AppImage do not provision.** `bundle.targets` is `"all"`; rpm has its own
  `postInstallScript` key, unwired, and AppImage has no install step at all.
* **Purge removes nothing.** No `postrm` deletes the anchor or the accounts.

### 7.2 What slice D settled, and what it left (2026-10-01)

Built ✅ and run as root here and in CI: root mints with the existing `mint` into a root-owned handoff
directory, never inside the desktop account's tree; a child that has dropped to the desktop uid
copies the store into `<app_data>/trust`; and success is declared only after the application's own
`verify_existing` passes **as that uid** plus a static owner/mode floor root measures. 48 write,
rename and replace attempts as the desktop uid, all denied by the kernel.

Left open, each needing a decision or a later slice:

* **Anchor owner is root, not `brops-anchor`** as §4.1 proposed. Both give the property; a dedicated
  account is not built.
* **`postinst` reaches it since `T-138`.** `brops-install --user` (stepless = `all`) resolves the
  user, runs `accounts`, then runs `brops_install_anchor --user --app-data <passwd home>/.local/share/
  studio.menq.brops` — Tauri's `app_data_dir()` read from source (`tauri` 2.11.5
  `src/path/desktop.rs:247-251`). Never run as root end to end: that needs a real install.
* **A deleted store strands the anchor.** If the user removes `<app_data>/trust`, the root-owned
  anchor stays, the installer refuses it as unverifiable, and the app cannot rename it aside.
* **Not atomic against power loss**: a run killed after the manifest is written leaves an anchor
  the next run refuses.
* **Accounts outside `/etc/passwd`** (LDAP, systemd-homed) are refused by name.

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

## 10 · The real-turn gap — MEASURED 2026-10-01 (`T-143`), not designed

CI now proves `brops-broker` completes a governed turn. Three read-only measurements asked how far
that is from a turn a person runs from the desktop. Every line below was read at `c7eba6a` by an
agent that changed nothing; file:line evidence is in the pull request that added this section. ◑.

**The kit must not be ported wholesale.** It stages one proven turn, and a real install is not that.

*Execution.* The contained executor the kit installs is `proof_executor`: it hashes its three inputs
and writes a report — no model is called, and no real-execution executor exists in the tree. A real
one needs an egress path and a credential channel; the launcher execs with an empty environment and
four descriptors, `egress_proxy.rs` says its transport is not implemented, and the launcher's
cgroup/rlimit step is not performed. And the deployment executes **one conversation**: the
root-owned lease file pins three request digests, so a turn with a different history is refused
before spawn (`run_ladder_supervisor.py:215-224`, reproduced in-process). A per-turn lease is minted
but unsigned and the launcher does not consume it; the code calls lifting that an Architect
decision. The supervisor that serves the ladder exists only as the CI harness.

*Desktop.* There are TWO governed paths. Chat goes through a sidecar and is closed by five
compile-time constants; it never reaches the broker. The Bridge panel reaches `connect_broker` and
never consults those constants — and the renderer rejects any commit that is not `trusted_verified`
(`governedTurn.ts:95`), so a `demonstration_custody` commit shows as a malformed reply. Nothing
starts the broker or the three services outside the kit: no systemd unit, nothing creates
`/run/brops`, the socket's mode is never set, a login-uid peer has never been exercised, and the
committed message is read by nothing on the desktop side.

*Installer.* The honest port list is: the tree and modes, the staged Python, launcher, recorder,
`brops-broker`, serving keys, the manifest/registry/anchor from an in-memory root, IPC policies,
configs, the three groups, one floor, both sudoers fragments made permanent, and the broker pin
manifest built last. NOT to port: `proof_executor`, `ladder_turn`, every `ladder-driver*.json`, the
relabelled anchors, the seeded `messages.db`, `keys/root.priv`. Three things an install needs that
the kit does not have at all: systemd units, `/run/brops`, and a `uids` block naming the sidecar —
preflight row `principals.tcb_floor_covers_the_sidecar` is NOT MET by the kit today. For
`install_minted`, the root signs exactly two artifacts (the manifest and the §4.2 registry) in two
processes, which is the only reason its private half touches disk; an install mint signs both in
one process and never writes it. Two binaries compile in `/opt/brops-live/...`, so the installer
cannot relocate the root.

**What this means for the plan.** Slices A–D and the entry point are real and stay. "B's deployment
step" as §8 wrote it is not one slice: it waits on a real executor, per-turn execution, and a
shipped supervisor — product work, with an Architect decision inside it — and until those exist an
installer could only deploy a fixture. That is the next thing to put in front of the Owner.
