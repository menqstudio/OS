# Debian custody ceremony — the TCB production root on Linux

> **Հայերեն ամփոփում.** Սա քո ձեռքով արվող քայլերն են։ Root-ը ստեղծում ես offline մեքենայի վրա,
> Builder-ին տալիս ես միայն PUBLIC hex-ը, հետո offline ստորագրում ես **երկու** ֆայլ (manifest ու
> registry)։ Private-ը երբեք
> serving box-ի վրա չի հայտնվում։ Ամեն հրաման ստորև գոյություն ունի և 2026-09-30-ին վազել ա այս
> Debian-ի վրա, բացի նրանցից, որոնք նշված են որպես ոչ-վազած։

This is OWNER_ACTION_REQUIRED §0 row 6. The only ceremony in the tree before it was
`apps/desktop/src-tauri/win-live/CUSTODY_CEREMONY.md`, Windows end to end. This one is for the key
compiled into `apps/desktop/src-tauri/broker/src/tcb.rs` as `ROOT_PUBLIC_KEY_HEX` — **not** the engine's
operator root, which is [`DEBIAN_DEPLOYMENT.md`](DEBIAN_DEPLOYMENT.md) and a different key.

## What it does not do

A completed ceremony does **not** open the production gate. `governed_verification_unconfigured()`
still returns `Some(...)` unconditionally before the model is invoked, and the independent verdict is
still RED. What it changes is one fact: a manifest signed by a root whose private half only you hold.

## Who holds what

| Material | Where | Secret |
|---|---|---|
| root private seed | your offline media only | **yes** |
| root public hex | `broker/src/tcb.rs` and `win-live/src/tcb.rs`, both `ROOT_PUBLIC_KEY_HEX` | no |
| serving keys (`keys/`) | the serving box, minted in phase 1 | operational |
| `manifest.json`, `manifest.sig`, `registry.bytes`, `registry.sig` | carried between the two boxes | no |

## Step 1 — mint the root, offline

On the airgapped machine, from a checkout:

```bash
cargo build --manifest-path apps/desktop/src-tauri/Cargo.toml -p brops-win-live --bin win_gen_root
apps/desktop/src-tauri/target/debug/win_gen_root --out /media/root/root.private.seed
stat -c %a /media/root/root.private.seed        # must print 600
```

It is cross-platform by its own doc. It prints `ROOT_PUBLIC_KEY : <64 hex>` and never the private; it
refuses to overwrite an existing file. The seed file holds **64 lowercase hex characters**.

*Measured 2026-09-30 on this box, and fixed in the same change as this page:* the file came out mode
**0664** (`std::fs::write` honours the umask) — it is now created 0600 with `create_new`. And
`sign_manifest.py` accepted only 32 raw bytes, so step 4 refused the file step 1 wrote (exit 3); it now
takes the hex file as written.

## Step 2 — hand over the PUBLIC hex

Send only the `ROOT_PUBLIC_KEY` line. The Builder changes `ROOT_PUBLIC_KEY_HEX` in both `tcb.rs`
files; `tools/check_root_anchor_custody.py` holds the two in agreement, because one Owner holds one
root. Nothing below verifies until a build carries the new pin.

## Step 3 — phase 1 on the serving box: mint the serving keys, emit the bytes

```bash
python3 engine/ci/live/provision_keys.py --root-dir /var/lib/brops-ceremony \
    --launcher-sha <sha> --executor-sha <sha> --emit-manifest /media/root/manifest.json
python3 engine/ci/live/provision_ladder.py --root-dir /var/lib/brops-ceremony \
    --emit-registry /media/root/registry.bytes \
    --keys-in /var/lib/brops-ceremony/keys --root-key-id brops-tcb-root-1
```

It writes the keys directory and the canonical bytes of the **two** things the root signs, and
**stops**: no config, no floor, no root private. Both name the serving keys it just minted — which is
why signing has to come after it (T-108).

**Not under `/opt/brops-live`.** Both kits `rm -rf /opt/brops-live` before they provision, and
`--keys-in` is read after that; this page said `/opt/brops-live` until T-126, so the keys would have
been gone. The kits now refuse a `BROPS_KEYS_IN` inside it. **The keys directory must stay on this box
until step 5** — the signatures name these keys and no others.

The registry is the §4.2 challenge-key registry. The ladder kit's root signed it with
`keys/root.priv`, which external mode never writes, so a manifest signature alone could not provision
the kit that starts the real broker (T-126).

## Step 4 — sign both, offline

```bash
python3 engine/ci/live/sign_manifest.py --manifest /media/root/manifest.json \
    --root-seed /media/root/root.private.seed --sig-out /media/root/manifest.sig \
    --expect-pub <the hex from step 1>
python3 engine/ci/live/sign_manifest.py --manifest /media/root/registry.bytes \
    --root-seed /media/root/root.private.seed --sig-out /media/root/registry.sig \
    --expect-pub <the hex from step 1>
```

The same tool signs any bytes; its output line says "KeyManifest" for both.

`--expect-pub` is the check that you are signing with the seed you meant: a different seed exits 4 and
writes nothing. The tool imports only the standard library and `cryptography`.

## Step 5 — phase 2 on the serving box

The kit that starts the real `brops-broker` — six variables, all or none:

```bash
export BROPS_KEYS_IN=/var/lib/brops-ceremony/keys BROPS_ROOT_ANCHOR_KEY_ID=brops-tcb-root-1 \
       BROPS_ROOT_ANCHOR_PUB_HEX=<hex> BROPS_MANIFEST_IN=/media/root/manifest.json \
       BROPS_MANIFEST_SIG_IN=/media/root/manifest.sig BROPS_REGISTRY_SIG_IN=/media/root/registry.sig
sudo -E bash engine/ci/live/run_ladder_turn.sh
```

The §5 kit, `run_live_turn.sh`, takes the first five. `provision_keys.py` refuses before writing
anything unless the manifest signature verifies under the anchor **and** names the keys in
`BROPS_KEYS_IN`; `provision_ladder.py` refuses before writing anything unless the registry signature
verifies under the same anchor.

**A throwaway root cannot pass this.** The anchor file says `external`, and both drivers
(`ladder_turn`, `live_turn`) refuse `external` unless its key is `ROOT_PUBLIC_KEY_HEX` compiled into
`broker/src/tcb.rs` (`check_declared_external_anchor`, T-126). Before T-126 the file's word was the
whole claim: the §5 kit already took the five variables, so any root exported through them would have
rendered `production_verified=true` (read from the code; not run). CI runs the refusal on every ladder
run, with the kit's own root relabelled `external`.

What step 5 prints under your root has **never been observed**: the driver must commit
`trusted_verified` with `production_verified=true`, and `brops-broker` must still refuse the turn,
because the production gate is shut independently of the root.

## Not run on this box

Step 5 provisions `/opt/brops-live` and fixed-uid service accounts, which this machine does not do; it
runs in CI with a kit-generated root. Steps 1 and 4 ran here, with a throwaway seed that was deleted
afterwards; step 3 and both phase-2 provisioners ran here against a scratch directory in T-126's tests
(`LadderRegistryExternalRootTests`), never against `/var/lib/brops-ceremony`.
