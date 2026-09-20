#!/usr/bin/env python3
"""Write the `$BROPS_BROKER_CONFIG` document — the file nothing in this tree has ever written.

WHY THIS DID NOT EXIST
----------------------
`build_governed_executor` (`apps/desktop/src-tauri/broker/src/main.rs:268-270`) reads one
environment variable and serves the fail-closed `UpstreamBlockedExecutor` when it is unset. Fifty-odd
places in this repository describe that fact; a tree-wide search on 2026-09-21 for anything that
SETS the variable or writes the document it names found none of them doing it. That is not an
oversight — the fail-closed posture is deliberate and stays — but it left the whole provisioned path
with no producer: `brops-preflight` can tell an operator which of the twenty-five keys is missing,
and nothing could then produce a file that had them.

The live kit comes closest and is deliberately not this. `run_ladder_turn.sh` builds
`$TCB/ladder-driver.json` inside an inline heredoc, for `target/debug/ladder_turn` — the Rust proof
driver whose own banner says in four places that it "is NOT the `brops-broker` binary". That
document is a DRIVER's config: it carries a `db.path` the broker never reads (the broker derives its
database from argv) and it names no §2.5 pin manifest, because the kit that writes it states
outright that it does not run the TCB integrity floor.

WHAT THIS IS
------------
A writer for the real thing, for an operator's own machine, with the broker's own contract as its
specification:

  * every key in `preflight::CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR` is produced, and
    `engine/tests/test_live_broker_config.py` extracts that list out of the Rust source and fails if
    this file and that constant disagree in EITHER direction. The list below is a mirror, and the
    repository has now found the same duplicate-implementation defect often enough that an unchecked
    mirror is not worth writing;
  * the `sidecar` block is validated against `SidecarPrincipal::from_config`'s five rules here,
    where the message can name the key, rather than at broker start-up where every refusal renders
    as the same `blocked` reply;
  * the §2.5 pin manifest is READ and its coverage checked before its path is written down. A
    config naming a manifest that does not cover `TCB_REQUIRED_ARTIFACTS` is a config that
    fail-closes at the floor — which is correct, and is exactly the "gap hidden behind a file that
    looks complete" that `preflight.rs`'s own header warns an installer not to produce.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
  * **It provisions nothing.** It writes one JSON document out of values it is handed. It creates no
    account, no socket, no key, no manifest, no signature and no floor. Every one of those is an
    input here and must already exist; where one is a file, this refuses rather than name a path
    that is not there.
  * **It never handles a private key.** It copies a fixed ALLOWLIST of keys out of the base config
    rather than the base config wholesale, so a secret that ends up in that file cannot reach this
    document by accident. `--emit` prints the document; there is no argument that takes a seed.
  * **It does not make a governed turn reachable.** The other two refusals that hold that line are
    untouched and are not this file's to move: `commands.rs::governed_verification_unconfigured`
    returns `Some(...)` unconditionally before the model is invoked, and `governed_turn.rs::
    connect_broker` refuses off Linux. A desktop build with this document on disk still refuses
    every user-facing governed turn, and the product still writes no such document — an operator
    running this on their own machine does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

#: Every configuration key `build_governed_executor` reads, dotted — the mirror of
#: `broker/src/preflight.rs::CONFIG_KEYS_READ_BY_BUILD_GOVERNED_EXECUTOR`. Bound to that constant by
#: `test_the_key_set_is_the_brokers_own`, in both directions.
BROKER_READ_KEYS = (
    "content.messages_db",
    "content.system",
    "content.window",
    "resolved.author",
    "resolved.generation_config_sha256",
    "resolved.history_sha256",
    "resolved.install_id",
    "resolved.requested_at",
    "resolved.requested_at_ms",
    "resolved.run_id",
    "resolved.system_sha256",
    "resolved.task_id",
    "resolved.workspace_id",
    "sidecar",
    "sidecar.cwd",
    "sidecar.python",
    "sidecar.script",
    "sockets.authority",
    "trust.floor_path",
    "trust.manifest_path",
    "trust.manifest_sig_path",
    "trust.signer_key_id",
    "trust.supervisor_attestation_key_id",
    "trust.tcb_pin_manifest_path",
    "uids",
)

#: The §2.5 roster, mirroring `brops_core::tcb_integrity::TCB_REQUIRED_ARTIFACTS`. Bound to it by
#: `test_the_tcb_roster_is_the_floors_own`, in both directions.
TCB_REQUIRED_ARTIFACTS = (
    "supervisor.bin",
    "evidence-recorder-runner.bin",
    "privileged-launcher.bin",
    "contained-executor.bin",
    "isolated-signer.bin",
    "trusted-verifier-broker.bin",
    "desktop-challenge-authority.bin",
    "supervisor.config",
    "evidence-recorder-runner.config",
    "privileged-launcher.config",
    "contained-executor.config",
    "isolated-signer.config",
    "trusted-verifier-broker.config",
    "desktop-challenge-authority.config",
    "trusted-verifier-broker.ipc-policy",
    "desktop-challenge-authority.ipc-policy",
    "trusted-verifier-broker.pinned-manifest-config",
    "governed-execution-allowlist.source",
    "key-manifest.root-anchor",
    "trusted-verifier-broker.unit",
    "desktop-challenge-authority.unit",
)

#: Copied VERBATIM out of the base config, by name. Everything else in that file stays there. The
#: broker reads `resolved.*` and `uids` and `sockets.authority` and four `trust.*` strings; nothing
#: else it holds belongs in this document.
COPIED_FROM_BASE = (
    "resolved.author",
    "resolved.generation_config_sha256",
    "resolved.history_sha256",
    "resolved.install_id",
    "resolved.requested_at",
    "resolved.requested_at_ms",
    "resolved.run_id",
    "resolved.system_sha256",
    "resolved.task_id",
    "resolved.workspace_id",
    "sockets.authority",
    "trust.manifest_path",
    "trust.manifest_sig_path",
    "trust.signer_key_id",
    "trust.supervisor_attestation_key_id",
    "uids",
)

#: `governed_sidecar.rs:311-318`. Mirrored, and bound to those constants by
#: `test_the_sidecar_rules_are_the_brokers_own`.
PRINCIPAL_KEY = "principal"
INVOKER_KEY = "invoker"
ENV_PROGRAM = "env"
MIN_INVOKER_TOKENS = 4

#: `provision_keys.py` records the anchor as a TCB FILE. A config carrying the root's public half
#: inline re-expresses "which root this deployment trusts" as an editable string, which is the F-17
#: arrangement the driver refuses outright; refuse it here too, where the message is about the
#: document being written rather than about a turn that failed.
INLINE_ROOT_ANCHOR_KEYS = ("root_pub_hex", "root_key_id")


class Refused(Exception):
    """A refusal to write. The message names the key and, where there is one, the provisioner."""


def get_dotted(document, dotted):
    """The value at `dotted`, or `None` if any segment is absent or not an object on the way."""
    current = document
    for segment in dotted.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def set_dotted(document, dotted, value):
    segments = dotted.split(".")
    current = document
    for segment in segments[:-1]:
        current = current.setdefault(segment, {})
    current[segments[-1]] = value


def read_json(path, what):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        raise Refused("%s is not readable at %s (%s)" % (what, path, exc.strerror or exc))
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Refused("%s at %s is not valid JSON (%s)" % (what, path, exc))


def validate_sidecar(block):
    """`SidecarPrincipal::from_config`'s five rules, refused here by name.

    Every one of these is already enforced at broker start-up, and every one of them renders there as
    the same observable: a `blocked` reply. Checking them at WRITE time is the difference between an
    operator reading which key is wrong and an operator reading that a turn did not happen.
    """
    account = block.get(PRINCIPAL_KEY)
    if not isinstance(account, str) or not account.strip():
        raise Refused(
            "`sidecar.%s` must be a non-empty string: 2.6 requires the sidecar to be its own OS "
            "account, and an account with no name cannot be checked for" % PRINCIPAL_KEY)
    account = account.strip()

    invoker = block.get(INVOKER_KEY)
    if not isinstance(invoker, list):
        raise Refused(
            "`sidecar.%s` must be an array: it is the argv prefix that lands the interpreter on "
            "`%s`, e.g. [\"/usr/bin/sudo\", \"-n\", \"-u\", \"%s\", \"/usr/bin/%s\"]"
            % (INVOKER_KEY, account, account, ENV_PROGRAM))
    if len(invoker) < MIN_INVOKER_TOKENS:
        raise Refused(
            "`sidecar.%s` has %d tokens; the shortest prefix that can both change principal and "
            "materialize an environment has %d" % (INVOKER_KEY, len(invoker), MIN_INVOKER_TOKENS))
    for index, token in enumerate(invoker):
        if not isinstance(token, str):
            raise Refused(
                "`sidecar.%s[%d]` is not a string: every token is one argv argument, and there is "
                "no rendering of a number or an object that this could safely be assumed to have "
                "meant" % (INVOKER_KEY, index))
        if not token:
            raise Refused(
                "`sidecar.%s[%d]` is empty; an empty argv token is an argument the invoker will "
                "still receive, not an absent one" % (INVOKER_KEY, index))
        if "\0" in token:
            raise Refused(
                "`sidecar.%s[%d]` contains a NUL byte, which no argv token may carry"
                % (INVOKER_KEY, index))
    if not invoker[0].startswith("/"):
        raise Refused(
            "`sidecar.%s[0]` is `%s`, which is not an absolute path: a bare program name is "
            "resolved through the BROKER's own $PATH, and the broker's environment is not a "
            "TCB-owned input" % (INVOKER_KEY, invoker[0]))
    last = len(invoker) - 1
    if invoker[last].rsplit("/", 1)[-1] != ENV_PROGRAM:
        raise Refused(
            "`sidecar.%s` ends in `%s` rather than `%s`: changing principal resets the child "
            "environment, so the provisioned trust set has to travel as explicit NAME=VALUE "
            "arguments, and a trailing `%s` is what applies them"
            % (INVOKER_KEY, invoker[last], ENV_PROGRAM, ENV_PROGRAM))
    if account not in invoker[1:last]:
        raise Refused(
            "`sidecar.%s` never names the account `%s`, so it does not change principal. A sidecar "
            "spawned as the broker collapses two 2.6 principals, which the supervisor refuses "
            "outright and every sidecar-facing service refuses by uid" % (INVOKER_KEY, account))


def validate_pin_manifest(path):
    """Read the 2.5 pin manifest and check its coverage BEFORE its path is written down.

    `verify_deployment_tcb` refuses an under-covering manifest, so a config that names one is a
    config whose every turn ends `blocked` at the floor. Writing that path without looking is how a
    document comes to look complete while being unusable, which is the thing `preflight.rs`'s header
    tells an installer not to build.

    Returns the count of pinned artifacts, for the report.
    """
    manifest = read_json(path, "the 2.5 TCB pin manifest")
    if not isinstance(manifest, dict):
        raise Refused("the 2.5 TCB pin manifest at %s is not a JSON object" % path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise Refused("the 2.5 TCB pin manifest at %s has no `artifacts` array" % path)
    pinned = {a.get("logical_name") for a in artifacts if isinstance(a, dict)}
    missing = [name for name in TCB_REQUIRED_ARTIFACTS if name not in pinned]
    if missing:
        raise Refused(
            "the 2.5 TCB pin manifest at %s does not cover %d of the %d required artifacts (%s). "
            "verify_deployment_tcb refuses an under-covering manifest, so naming this path would "
            "produce a config that fail-closes at the floor while looking provisioned"
            % (path, len(missing), len(TCB_REQUIRED_ARTIFACTS), ", ".join(missing)))
    if not isinstance(manifest.get("owner_uids"), dict) or not manifest["owner_uids"]:
        raise Refused(
            "the 2.5 TCB pin manifest at %s resolves no `owner_uids`: the floor compares every "
            "artifact's owner against them, and an empty map makes every comparison fail" % path)
    return len(artifacts)


def build(base, *, messages_db, system, window, sidecar, floor_path, pin_manifest_path):
    """The document, assembled by ALLOWLIST out of `base` plus the deployment's own values."""
    document = {}
    for dotted in COPIED_FROM_BASE:
        value = get_dotted(base, dotted)
        if value is None:
            raise Refused(
                "the base config does not carry `%s`, which build_governed_executor reads. It is "
                "written by engine/ci/live/provision_keys.py; a base config without it was not "
                "produced by a completed provisioning run" % dotted)
        set_dotted(document, dotted, value)

    # The BASE's trust block, not the assembled one. The allowlist above copies four `trust.*`
    # strings by name, so an inline anchor could never reach `document` and a check against
    # `document["trust"]` would be a refusal that cannot fire. What is worth refusing is a base
    # config that carries one at all: it means this deployment was provisioned by something that
    # re-expressed the trusted root as an editable string, and every other `trust.*` value copied
    # out of it came from that same provisioner.
    base_trust = get_dotted(base, "trust")
    for key in INLINE_ROOT_ANCHOR_KEYS:
        if isinstance(base_trust, dict) and key in base_trust:
            raise Refused(
                "the base config carries `trust.%s`. The root anchor is a TCB FILE, not a config "
                "string: a document that names the trusted root inline lets an editor of that file "
                "choose which root the deployment trusts" % key)

    set_dotted(document, "content.messages_db", messages_db)
    set_dotted(document, "content.system", system)
    set_dotted(document, "content.window", window)
    set_dotted(document, "trust.floor_path", floor_path)
    set_dotted(document, "trust.tcb_pin_manifest_path", pin_manifest_path)
    document["sidecar"] = sidecar

    missing = [key for key in BROKER_READ_KEYS if get_dotted(document, key) is None]
    if missing:
        # Unreachable while the allowlist above covers the read set, which the bound test asserts.
        # Written rather than assumed: this is the last gate before a file is created, and the
        # failure it would catch is a document the broker reads a `None` out of.
        raise Refused(
            "the assembled document is missing %s, which build_governed_executor reads"
            % ", ".join(missing))
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Write the $BROPS_BROKER_CONFIG document for a provisioned deployment")
    parser.add_argument("--base-config", required=True,
                        help="the deployment's provisioned config (engine/ci/live/provision_keys.py "
                             "writes one); uids, sockets, resolved and four trust strings are "
                             "copied out of it BY NAME")
    parser.add_argument("--out", required=True, help="where to write the document")
    parser.add_argument("--messages-db", required=True,
                        help="content.messages_db: the conversation source the ladder derives its "
                             "three artifact digests from")
    parser.add_argument("--system-file", required=True,
                        help="a file holding content.system, the agent's system prompt. A FILE "
                             "rather than a string: a prompt is multi-line and an argv-mangled one "
                             "would change every digest derived from it")
    parser.add_argument("--window", type=int, required=True,
                        help="content.window: how many of the most recent messages are sent")
    parser.add_argument("--floor-path", required=True,
                        help="trust.floor_path: the anti-rollback floor. MUST be writable only by "
                             "the broker service principal - the resolver advances it in place")
    parser.add_argument("--tcb-pin-manifest", required=True,
                        help="trust.tcb_pin_manifest_path: the root-owned 2.5 pin manifest. "
                             "Required, not optional: the env fallback exists for a deployment that "
                             "sets it, and a document that names neither fail-closes at the floor")
    parser.add_argument("--sidecar-python", required=True, help="sidecar.python: absolute interpreter")
    parser.add_argument("--sidecar-script", required=True, help="sidecar.script: the bridge front door")
    parser.add_argument("--sidecar-cwd", required=True, help="sidecar.cwd: the child's sandbox")
    parser.add_argument("--sidecar-principal", required=True,
                        help="sidecar.principal: the 2.6 sidecar OS account, distinct from the broker's")
    parser.add_argument("--sidecar-invoker", required=True, metavar="JSON_ARRAY",
                        help="sidecar.invoker as a JSON array of argv tokens, e.g. "
                             "'[\"/usr/bin/sudo\",\"-n\",\"-u\",\"brops-sidecar\",\"/usr/bin/env\"]'. "
                             "ONE argument holding the array rather than a repeated flag: the "
                             "prefix's own tokens start with `-` (`-n`, `-u`), and a repeated flag "
                             "hands those to the argument parser as options. This is also the exact "
                             "value that lands in the document")
    parser.add_argument("--emit", action="store_true",
                        help="also print the document to stdout (it holds no secret; the allowlist "
                             "above is why)")
    args = parser.parse_args(argv)

    try:
        base = read_json(args.base_config, "the base config")
        if not isinstance(base, dict):
            raise Refused("the base config at %s is not a JSON object" % args.base_config)

        try:
            with open(args.system_file, "rb") as handle:
                system = handle.read().decode("utf-8")
        except OSError as exc:
            raise Refused("--system-file %s is not readable (%s)"
                          % (args.system_file, exc.strerror or exc))
        except UnicodeDecodeError as exc:
            raise Refused("--system-file %s is not UTF-8 (%s)" % (args.system_file, exc))
        if not system:
            raise Refused(
                "--system-file %s is empty. `content.system` is refused empty by "
                "build_governed_executor, and a turn with no system prompt is not one this "
                "deployment meant to serve" % args.system_file)

        if args.window <= 0:
            raise Refused("--window is %d; build_governed_executor refuses a window that is not "
                          "positive" % args.window)

        for label, path in (("--messages-db", args.messages_db),
                            ("--floor-path", args.floor_path),
                            ("--sidecar-python", args.sidecar_python),
                            ("--sidecar-script", args.sidecar_script)):
            if not os.path.isfile(path):
                raise Refused(
                    "%s is %s, which is not a file. This writes a document out of values it is "
                    "handed and provisions none of them; a path that is not there now will not be "
                    "there when the broker reads it" % (label, path))
        if not os.path.isdir(args.sidecar_cwd):
            raise Refused("--sidecar-cwd is %s, which is not a directory" % args.sidecar_cwd)

        try:
            invoker = json.loads(args.sidecar_invoker)
        except ValueError as exc:
            raise Refused("--sidecar-invoker is not valid JSON (%s). It is the argv prefix as a "
                          "JSON array, e.g. '[\"/usr/bin/sudo\",\"-n\",\"-u\",\"acct\","
                          "\"/usr/bin/env\"]'" % exc)

        sidecar = {
            "python": args.sidecar_python,
            "script": args.sidecar_script,
            "cwd": args.sidecar_cwd,
            PRINCIPAL_KEY: args.sidecar_principal,
            INVOKER_KEY: invoker,
        }
        validate_sidecar(sidecar)

        pinned = validate_pin_manifest(args.tcb_pin_manifest)

        document = build(
            base,
            messages_db=args.messages_db,
            system=system,
            window=args.window,
            sidecar=sidecar,
            floor_path=args.floor_path,
            pin_manifest_path=args.tcb_pin_manifest,
        )
    except Refused as refusal:
        print("FAIL: %s" % refusal, file=sys.stderr)
        return 1

    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    os.chmod(args.out, 0o644)
    if args.emit:
        sys.stdout.write(rendered)

    print("broker config: %d keys -> %s" % (len(BROKER_READ_KEYS), args.out))
    print("  2.5 pin manifest : %s (%d artifacts, full coverage)" % (args.tcb_pin_manifest, pinned))
    print("  sidecar principal: %s via %s" % (args.sidecar_principal, " ".join(sidecar[INVOKER_KEY])))
    print("  export BROPS_BROKER_CONFIG=%s before starting brops-broker." % os.path.abspath(args.out))
    print("  This document alone does NOT open a governed surface: "
          "governed_verification_unconfigured and connect_broker are untouched, and no shipped "
          "product writes this file.")
    return 0


#: Extractors used by `engine/tests/test_live_broker_config.py` to bind the three mirrors above to
#: the Rust constants they mirror. They live here, beside the mirrors, so a reader who edits a list
#: finds the thing that checks it in the same file.
def rust_string_list(source: str, const_name: str):
    """The string literals of `pub const <const_name>: &[&str] = &[ ... ];`, in source order."""
    match = re.search(
        r"pub const " + re.escape(const_name) + r"\s*:\s*&\[&str\]\s*=\s*&\[(.*?)\n\];",
        source, re.DOTALL)
    if match is None:
        raise ValueError("no `pub const %s: &[&str]` in that source" % const_name)
    body = re.sub(r"//[^\n]*", "", match.group(1))
    return re.findall(r'"([^"\\]*)"', body)


if __name__ == "__main__":
    raise SystemExit(main())
