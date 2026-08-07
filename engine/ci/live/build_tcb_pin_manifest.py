#!/usr/bin/env python3
"""Build the root-owned §2.5 TCB pin manifest for the live kit (audit **F-10**).

`brops_core::tcb_integrity::verify_tcb_integrity` decides the whole §2.5 floor — owner, writability,
start-time content pin, ancestor safety, and a coverage floor that refuses an under-specified
manifest. It was fully implemented and, until the broker's `tcb_probe` landed, fully unwired. The
probe closed one half; this closes the other: the live kit had no `TcbPinManifest` to present, so the
floor could only ever refuse for absence, which is fail-closed but proves nothing.

This emits a manifest covering the complete `TCB_REQUIRED_ARTIFACTS` set for THIS deployment. Every
entry points at a file that genuinely serves that role here, and where one file serves several roles
it is pinned under each of them rather than a stand-in being invented:

  * the three Python service front doors ARE the supervisor / signer / challenge-authority
    executables in this kit — they are what runs, so they are what gets measured;
  * the launcher's and the executor's configuration IS the §4.3 lease (uids, the image pin, and now
    the three request digests), so both `.config` roles point at it;
  * the remaining `.config` roles and the broker's pinned-manifest configuration are the one shared
    `config.json` each of those components actually loads;
  * this kit is orchestrated by `run_live_turn.sh`, not by systemd, so a root-owned copy of that
    script is what the two `.unit` roles pin. Writing plausible-looking unit files for units that do
    not exist would make the manifest describe a deployment that isn't this one.

Run AFTER everything exists (the lease and the sudoers allowlist are written late), and BEFORE the
services start — the pin is a start-time measurement, so anything provisioned after it is not
covered by it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit the live kit's §2.5 TCB pin manifest")
    ap.add_argument("--root-dir", required=True, help="e.g. /opt/brops-live")
    ap.add_argument("--sudoers", required=True, help="the governed-execution allowlist source")
    ap.add_argument("--unit", required=True, help="root-owned copy of the orchestrator script")
    ap.add_argument("--out", required=True, help="where to write the manifest JSON")
    args = ap.parse_args()

    root = os.path.abspath(args.root_dir)
    tcb = os.path.join(root, "tcb")
    live = os.path.join(root, "engine", "ci", "live")
    binaries = os.path.join(root, "bin")
    config = os.path.join(root, "config.json")
    lease = os.path.join(tcb, "executor.lease")

    # logical_name -> (path, owner). Every name in TCB_REQUIRED_ARTIFACTS must appear, or the
    # verifier's coverage floor refuses the manifest — which is the behaviour we want if this map
    # ever falls behind the required set.
    mapping = {
        # ---- the seven trusted executables ----
        "supervisor.bin": os.path.join(live, "run_supervisor.py"),
        "evidence-recorder-runner.bin": os.path.join(binaries, "governed_recorder"),
        "privileged-launcher.bin": os.path.join(tcb, "privileged-launcher.bin"),
        "contained-executor.bin": os.path.join(tcb, "contained-executor.bin"),
        "isolated-signer.bin": os.path.join(live, "run_signer.py"),
        "trusted-verifier-broker.bin": os.path.join(binaries, "live_turn"),
        "desktop-challenge-authority.bin": os.path.join(live, "run_authority.py"),
        # ---- each executable's configuration ----
        "supervisor.config": config,
        # The recorder's configuration is NOT the shared config.json — it never reads that file. It
        # reads exactly one root-owned document, at a path compiled into the binary, and takes the
        # launcher/executor/lease/store/state paths and the two image digests from it. Pinning
        # config.json here would have measured a file the recorder does not consult while leaving the
        # file that actually steers it unmeasured.
        "evidence-recorder-runner.config": os.path.join(tcb, "recorder-policy.json"),
        # The launcher takes its invoker/drop-target uids, its image pin and (F-08) the three
        # request digests from the lease. That file IS its configuration.
        "privileged-launcher.config": lease,
        "contained-executor.config": lease,
        "isolated-signer.config": config,
        "trusted-verifier-broker.config": config,
        "desktop-challenge-authority.config": config,
        # ---- IPC / peer-auth policies ----
        "desktop-challenge-authority.ipc-policy":
            os.path.join(tcb, "desktop-challenge-authority.ipc-policy.json"),
        "trusted-verifier-broker.ipc-policy":
            os.path.join(tcb, "trusted-verifier-broker.ipc-policy.json"),
        # ---- broker pinned-manifest configuration ----
        "trusted-verifier-broker.pinned-manifest-config": config,
        # ---- launch steering + trust roots ----
        "governed-execution-allowlist.source": os.path.abspath(args.sudoers),
        "key-manifest.root-anchor": os.path.join(tcb, "root-anchor.json"),
        # ---- the two service "units" ----
        "trusted-verifier-broker.unit": os.path.abspath(args.unit),
        "desktop-challenge-authority.unit": os.path.abspath(args.unit),
    }

    artifacts = []
    for logical_name, path in sorted(mapping.items()):
        if not os.path.isfile(path):
            print("FAIL: %s is missing for %s" % (path, logical_name), file=sys.stderr)
            return 1
        artifacts.append({
            "logical_name": logical_name,
            "path": path,
            "expected_sha256": sha256_file(path),
            # This kit has no separate brops-admin principal: root owns every TCB artifact, and the
            # manifest says so rather than naming an owner that does not exist here.
            "expected_owner": "root",
        })

    manifest = {"artifacts": artifacts, "owner_uids": {"root": 0, "brops_admin": 0}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
    os.chmod(args.out, 0o644)
    print("tcb pin manifest: %d artifacts -> %s" % (len(artifacts), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
