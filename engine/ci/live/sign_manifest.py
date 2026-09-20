#!/usr/bin/env python3
"""Sign a live-kit KeyManifest with the offline root private key. Owner-only, airgapped machine.

WHY THIS FILE EXISTS. `provision_keys.py --emit-manifest` writes the canonical `KeyManifest` bytes the
Linux broker will verify; `key_manifest.rs` wants "a detached Ed25519 signature over
`manifest.canonical_bytes()`", standard base64. Until 2026-09-20 nothing in this repository produced
that signature on Linux. `build_manifest_bytes` was reachable from no flag, `live_crypto.sign_b64std`
was a library function with no entry point, and the only in-tree manifest signer was
`win-live/src/bin/win_provision.rs` — Windows-shaped, and it mints its OWN keypairs rather than signing
supplied bytes. So the external-root path had a specification and no tool.

THE BOUNDARY THIS FILE KEEPS. The Builder never generates, reads, holds or transports the production
root private half. This tool READS a seed the Owner already has, on a machine the Owner controls, and
emits a signature. It prints the derived PUBLIC hex so the Owner can check it against the pin in
`broker/src/tcb.rs` before trusting the result; it never prints, copies or transmits the private.

It imports only `live_crypto` and the standard library, so it runs on an airgapped box with the engine's
pinned `cryptography` and nothing else.

    python engine/ci/live/sign_manifest.py \\
        --manifest /media/root/manifest.json \\
        --root-seed /media/root/root.private.seed \\
        --sig-out  /media/root/manifest.sig \\
        --expect-pub 3c83c2bc...        # optional, and worth passing

Exit 0 signed · 2 usage · 3 the seed is not a 32-byte Ed25519 seed · 4 the derived public does not match
`--expect-pub` · 5 the signature did not verify against its own message (a self-check, so a broken
install cannot hand back an unusable signature that looks fine).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_crypto as lc  # noqa: E402  (path-dependent import, as the live runners do)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sign a live-kit KeyManifest with the offline root private key (Owner-only)")
    ap.add_argument("--manifest", required=True,
                    help="the canonical KeyManifest bytes, as written by "
                         "`provision_keys.py --emit-manifest`")
    ap.add_argument("--root-seed", required=True,
                    help="the raw 32-byte Ed25519 root seed. Read, never printed or copied.")
    ap.add_argument("--sig-out", default=None,
                    help="write the detached signature here (standard base64). Without it the "
                         "signature is printed and nothing is written.")
    ap.add_argument("--expect-pub", default=None,
                    help="refuse unless the seed derives this 64-hex public key. Pass the value "
                         "pinned in apps/desktop/src-tauri/broker/src/tcb.rs — it turns 'I hope this "
                         "is the right seed file' into a check.")
    args = ap.parse_args()

    try:
        with open(args.manifest, "rb") as f:
            manifest_bytes = f.read()
    except OSError as exc:
        print("FAIL: cannot read --manifest %s (%s)" % (args.manifest, exc), file=sys.stderr)
        return 2
    if not manifest_bytes:
        print("FAIL: --manifest %s is empty; there is nothing to sign" % args.manifest,
              file=sys.stderr)
        return 2

    try:
        with open(args.root_seed, "rb") as f:
            seed = f.read()
    except OSError as exc:
        print("FAIL: cannot read --root-seed (%s)" % exc, file=sys.stderr)
        return 2
    if len(seed) != 32:
        # The length is reported; the bytes never are.
        print("FAIL: --root-seed is %d bytes, not a raw 32-byte Ed25519 seed. `win_gen_root` writes "
              "exactly 32 raw bytes." % len(seed), file=sys.stderr)
        return 3

    root = lc.load_private(seed)
    pub_hex = lc.pub_hex(root)

    if args.expect_pub:
        want = args.expect_pub.strip().lower()
        if want != pub_hex:
            print("FAIL: this seed derives %s, not the --expect-pub %s you named. This is the check "
                  "that catches signing with the wrong seed file, so nothing was written."
                  % (pub_hex, want), file=sys.stderr)
            return 4

    sig_std = lc.sign_b64std(root, manifest_bytes)

    # A self-check, not ceremony. If the local `cryptography` is broken or the seed was truncated in a
    # way that still loaded, the Owner should learn it here and not from a broker refusal days later.
    if not lc.verify_b64std(lc.load_public_hex(pub_hex), manifest_bytes, sig_std):
        print("FAIL: the signature this machine just produced does not verify against its own "
              "message. Nothing was written.", file=sys.stderr)
        return 5

    if args.sig_out:
        out = os.path.abspath(args.sig_out)
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(sig_std + "\n")
        os.chmod(out, 0o644)

    print("signed the KeyManifest with the offline root")
    print("  manifest        : %s (%d bytes, sha256=%s)"
          % (os.path.abspath(args.manifest), len(manifest_bytes),
             hashlib.sha256(manifest_bytes).hexdigest()))
    print("  root public hex : %s" % pub_hex)
    print("     ^ this must equal ROOT_PUBLIC_KEY_HEX in apps/desktop/src-tauri/broker/src/tcb.rs")
    print("  signature       : %s" % sig_std)
    if args.sig_out:
        print("  written to      : %s" % os.path.abspath(args.sig_out))
    print("")
    print("  Phase 2, on the serving box:")
    print("    python engine/ci/live/provision_keys.py --root-dir <LIVE> \\")
    print("        --launcher-sha <sha> --executor-sha <sha> \\")
    print("        --keys-in <LIVE>/keys \\")
    print("        --root-anchor-key-id <id> --root-anchor-pub-hex %s \\" % pub_hex)
    print("        --manifest-in <manifest.json> --manifest-sig-in <manifest.sig>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
