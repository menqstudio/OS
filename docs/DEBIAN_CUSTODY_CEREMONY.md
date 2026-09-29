# Debian custody ceremony — the TCB production root on Linux

> **Հայերեն ամփոփում.** Սա քո ձեռքով արվող քայլերն են։ Root-ը ստեղծում ես offline մեքենայի վրա,
> Builder-ին տալիս ես միայն PUBLIC hex-ը, հետո offline ստորագրում ես մեկ ֆայլ։ Private-ը երբեք
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
| `manifest.json`, `manifest.sig` | carried between the two boxes | no |

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
python3 engine/ci/live/provision_keys.py --root-dir /opt/brops-live \
    --launcher-sha <sha> --executor-sha <sha> --emit-manifest /media/root/manifest.json
```

It writes the keys directory and the canonical manifest bytes, and **stops**: no config, no floor, no
root private. The manifest names the serving keys it just minted — which is why signing has to come
after it (T-108).

## Step 4 — sign, offline

```bash
python3 engine/ci/live/sign_manifest.py --manifest /media/root/manifest.json \
    --root-seed /media/root/root.private.seed --sig-out /media/root/manifest.sig \
    --expect-pub <the hex from step 1>
```

`--expect-pub` is the check that you are signing with the seed you meant: a different seed exits 4 and
writes nothing. The tool imports only the standard library and `cryptography`.

## Step 5 — phase 2 on the serving box

```bash
export BROPS_KEYS_IN=/opt/brops-live/keys BROPS_ROOT_ANCHOR_KEY_ID=brops-tcb-root-1 \
       BROPS_ROOT_ANCHOR_PUB_HEX=<hex> BROPS_MANIFEST_IN=/media/root/manifest.json \
       BROPS_MANIFEST_SIG_IN=/media/root/manifest.sig
sudo -E bash engine/ci/live/run_live_turn.sh
```

All five or none — the script refuses a partial set. `provision_keys.py` refuses before writing anything
unless the signature verifies under the anchor **and** the signed manifest names the keys in
`BROPS_KEYS_IN`.

**Not yet possible, and the next Builder row:** `run_live_turn.sh` is the §5 kit. The kit that starts
the real `brops-broker` is `run_ladder_turn.sh`, and it reads none of the five variables (measured:
zero occurrences on 2026-09-30). Until it does, this ceremony reaches a real root on the §5 path only.

## Not run on this box

Steps 3 and 5 provision `/opt/brops-live` and fixed-uid service accounts, which this machine does not
do; they run in CI with a kit-generated root. Steps 1 and 4 ran here, with a throwaway seed that was
deleted afterwards.
