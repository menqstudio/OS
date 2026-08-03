# Production Trust Root — Custody Ceremony

This is the honest graduation from the **compiled-in demonstration anchor** to a **real production root of
trust**. Today the TCB pins a demo public key whose private seed is embedded in `proof.rs` — so anyone with the
binary could forge a manifest. That is why the app truthfully labels every proof "demonstration custody" and
never flips live turns to `trusted_verified`.

After this ceremony, the root **private** key exists **only on your offline media** and never in any binary or
on the serving box. Only that offline private can sign a production manifest, and the broker will accept a
manifest **only** if it verifies under the public key compiled into the TCB. That is what makes a live
`trusted_verified` honest.

---

## What each party holds

| Material | Where it lives | Secret? |
|---|---|---|
| Root **private** seed (`root.private.seed`) | Your **offline** media only (USB / safe) | **YES — never on the serving box** |
| Root **public** hex | Compiled into `src-tauri/win-live/src/tcb.rs` (`ROOT_PUBLIC_KEY_HEX`) | No |
| Signer / supervisor / challenge seeds | The deployment dir on the serving box (`win_provision` generates them) | Operational (serving box) |
| `manifest.json` + `manifest.sig` + `floor.json` | The deployment dir on the serving box | No (signature is public) |

The pin is enforced two ways, both already proven:
- `win_provision` **refuses** (`exit 3`) any `--root-key` whose public ≠ the TCB-pinned public.
- The driver builds its `PinnedRoot` from `tcb.rs`, **never from config**, and rejects any manifest not signed
  by it.

---

## Prerequisites

- An **offline / airgapped** machine you trust (ideally never networked). The root private is generated and
  used only here.
- Removable media to carry the root private between the offline machine and provisioning.
- The Windows broker SID you will authorize (`S-1-5-21-…`) — the account the broker runs as.

---

## Step 1 — Generate the root offline

On the **offline machine**, from `apps/desktop/src-tauri/win-live`:

```
cargo run --bin win_gen_root -- --out D:\brops-root\root.private.seed
```

It prints:

```
RESULT: root keypair generated
  root_key_id      : brops-tcb-root-1
  ROOT_PUBLIC_KEY  : <64 hex chars>
  private_seed_file: D:\brops-root\root.private.seed   (KEEP OFFLINE)
```

- The **private seed is written to the file only** — it is never printed to the screen.
- The tool **refuses to overwrite** an existing file, so you cannot silently rotate an active root by accident.
- Record the `ROOT_PUBLIC_KEY` — that (and only that) is what goes into the build.

## Step 2 — Pin the public key in the TCB

Give **only** the `ROOT_PUBLIC_KEY` hex to the build. It replaces the demonstration value in
`src-tauri/win-live/src/tcb.rs`:

```rust
pub const ROOT_PUBLIC_KEY_HEX: &str = "<your ROOT_PUBLIC_KEY>"; // production root — private held offline
```

(The self-test keeps using a clearly-separate demonstration anchor, so it stays green and honestly labeled;
only the production path uses this pinned key.) Rebuild the broker/app after the swap.

## Step 3 — Provision a deployment, signing offline

On the **offline machine** (so the private never touches a networked box), feed the offline private to
`win_provision`:

```
cargo run --bin win_provision -- ^
  --root-dir  D:\brops-deploy ^
  --root-key  D:\brops-root\root.private.seed ^
  --allowed-broker-sid S-1-5-21-XXXXXXXXXX-XXXXXXXXXX-XXXXXXXXXX-1001 ^
  --executor-path C:\path\to\win_executor.exe
```

`win_provision`:
- verifies the private matches the TCB-pinned public (else `exit 3`),
- signs `manifest.json` → `manifest.sig` with the **root private**,
- writes the serving seeds + store + `config.json` into `D:\brops-deploy`,
- writes `config.json` with `root_seed: ""` — **the root private is never written into the deployment**.

## Step 4 — Move the deployment to the serving box

Copy the whole `D:\brops-deploy` dir to the serving box. **Keep `root.private.seed` on your offline media** —
it does not travel. The serving box now has everything the sidecar needs and nothing that can forge a new
manifest.

---

## Rotation & revocation

- **Rotate a serving key** (signer/supervisor/challenge): re-run `win_provision` with the same offline root at
  a higher `manifest_epoch`; the anti-rollback floor (`floor.json`, TCB-signed) refuses a downgrade.
- **Rotate the root** itself: run `win_gen_root --out <new file>` (to a new path), pin the new public in
  `tcb.rs`, rebuild, re-provision. Destroy the old private only after every serving box is on the new build.
- **Revoke a key**: set `"revoked": true` for that `key_id` in the manifest and re-provision at a higher epoch.

## Until this ceremony is done

The app stays **fail-closed**: live turns run under `NoTrustedManifest` and the UI never shows a production
`trusted_verified`. The in-process self-test still demonstrates the full crypto chain, explicitly under
**demonstration custody**. Nothing here fakes trust — a green appears only once a real offline-rooted manifest
verifies.
