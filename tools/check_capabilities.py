#!/usr/bin/env python3
"""Capability-inventory consistency gate — the CI wall for T-010.

Tauri v2 gates only *plugin* commands by default; an app command registered in
`generate_handler!` but absent from the app manifest (`build.rs`) is invokable by the
webview with **no permission entry at all**. T-010 closes that by declaring every
command in the manifest and granting `allow-*` explicitly (deny-by-default). This
check keeps the three inventories from drifting apart as commands are added:

    registered commands  (src/lib.rs  generate_handler!)  MINUS the explicit
      INTENTIONALLY_UNGATED allowlist
      == AppManifest commands  (src-tauri/build.rs)
      == capability-policy inventory  (capabilities/command-policy.json)

and additionally asserts each policy `grant` matches the actual capability grants in
`capabilities/default.json` (allow-<cmd> / deny-<cmd>). A command added in one place
but not the others — or granted against its declared tier — **fails CI**. No manual
recount, no silently-ungated command: registered_commands() now captures EVERY module
prefix (not just commands::/files::), so a module-scoped command that is neither declared
under the wall nor named in INTENTIONALLY_UNGATED (with a reason) fails this check.

Usage:  python tools/check_capabilities.py [--root DIR]
Exit 0 + "GREEN: ..." when consistent; exit 1 + the problems otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

DESKTOP = pathlib.Path("apps/desktop/src-tauri")
LIB_RS = DESKTOP / "src" / "lib.rs"
BUILD_RS = DESKTOP / "build.rs"
POLICY = DESKTOP / "command-policy.json"
DEFAULT_CAP = DESKTOP / "capabilities" / "default.json"

# Commands deliberately registered OUTSIDE the window capability manifest. Tauri makes an
# app command that is registered in generate_handler! but absent from the manifest
# webview-invokable with NO permission entry, so every such command MUST be named here with
# a reason — this turns what used to be a silent regex blind spot (only commands::/files::
# were scanned) into an explicit, reviewed, CI-enforced decision. A NEW module-scoped
# command that is neither declared under the wall nor added here now FAILS this check.
#   - governed_turn_execute: the trusted-broker governed-turn proxy; gated by the broker
#       lease/challenge system and fails closed ("broker_unavailable") off the supported
#       path. Whether it should additionally sit under the window policy is an owner gate call.
#   - read_decision_ledger / read_evidence_chain / read_verifier_verdicts /
#       read_engine_approval_queue: READ-ONLY Phase-2 governance mirrors — hold no key/lease,
#       touch no DB, author no decision, and fail closed to Blocked/Unreachable.
#   - governed_trust_selftest: owner-visible in-process trust-chain self-test; never flips a
#       live AI turn.
INTENTIONALLY_UNGATED = {
    "governed_turn_execute",
    "read_decision_ledger",
    "read_evidence_chain",
    "read_verifier_verdicts",
    "read_engine_approval_queue",
    "governed_trust_selftest",
}


def registered_commands(root: pathlib.Path) -> set[str]:
    """Every command fn name inside `generate_handler![ ... ]` in lib.rs, regardless of the
    module path it is registered under (commands::, files::, governance::, governed_turn::,
    …). Capturing ALL module prefixes — not just commands::/files:: — is what lets the check
    see module-scoped commands that would otherwise be silently outside the capability wall."""
    text = (root / LIB_RS).read_text(encoding="utf-8")
    m = re.search(r"generate_handler!\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        raise SystemExit("RED: could not find generate_handler![ ... ] in lib.rs")
    body = m.group(1)
    # Strip line comments so commented-out entries don't count.
    body = re.sub(r"//[^\n]*", "", body)
    # `mod::fn` (one or more module segments) -> capture the final fn identifier.
    return set(re.findall(r"(?:[a-zA-Z_][a-zA-Z0-9_]*::)+([a-z0-9_]+)", body))


def manifest_commands(root: pathlib.Path) -> set[str]:
    """Command names in the `commands = [ ... ]` array wired into AppManifest."""
    text = (root / BUILD_RS).read_text(encoding="utf-8")
    # Matches both `const COMMANDS: &[&str] = &[ ... ];` and `let commands = [ ... ];`.
    m = re.search(
        r"(?:const\s+COMMANDS[^=]*|let\s+commands\s*)=\s*&?\[(.*?)\]\s*;",
        text,
        re.DOTALL,
    )
    if not m:
        raise SystemExit("RED: could not find the COMMANDS array in build.rs")
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return set(re.findall(r'"([a-z0-9_]+)"', body))


def policy_commands(root: pathlib.Path) -> dict[str, dict]:
    doc = json.loads((root / POLICY).read_text(encoding="utf-8"))
    return doc["commands"]


def capability_grants(root: pathlib.Path) -> dict[str, str]:
    """command fn name -> 'allow' | 'deny' from capabilities/default.json.

    Permission ids hyphenate the command name (`list_dir` -> `allow-list-dir`); map
    back to the underscored fn name so the sets are comparable.
    """
    doc = json.loads((root / DEFAULT_CAP).read_text(encoding="utf-8"))
    grants: dict[str, str] = {}
    for perm in doc["permissions"]:
        for kind in ("allow", "deny"):
            prefix = f"{kind}-"
            if perm.startswith(prefix) and not perm.startswith("core:"):
                cmd = perm[len(prefix):].replace("-", "_")
                grants[cmd] = kind
    return grants


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []

    registered = registered_commands(root)
    manifest = manifest_commands(root)
    policy = policy_commands(root)
    policy_set = set(policy)

    # 0) The intentionally-ungated allowlist must stay honest: every name in it must still be
    #    a registered command (no rot), and none of them may ALSO be declared under the wall
    #    (that would be a contradiction — they are outside the manifest by definition).
    stale = INTENTIONALLY_UNGATED - registered
    if stale:
        problems.append(
            f"INTENTIONALLY_UNGATED names command(s) not registered in lib.rs "
            f"(stale allowlist): {sorted(stale)}"
        )
    contradictory = INTENTIONALLY_UNGATED & (manifest | policy_set)
    if contradictory:
        problems.append(
            f"command(s) both allowlisted-ungated and declared under the wall "
            f"(pick one): {sorted(contradictory)}"
        )

    # The set that MUST live under the wall = everything registered except the explicit
    # ungated allowlist. A new module-scoped command not added to either side lands here and
    # fails the equality below, so it can never be silently ungated.
    gated = registered - INTENTIONALLY_UNGATED

    # 1) The three inventories must be the identical set.
    if gated != manifest:
        problems.append(
            f"gated-registered != manifest: only-in-lib.rs={sorted(gated - manifest)}; "
            f"only-in-build.rs={sorted(manifest - gated)}"
        )
    if gated != policy_set:
        problems.append(
            f"gated-registered != policy: only-in-lib.rs={sorted(gated - policy_set)}; "
            f"only-in-policy={sorted(policy_set - gated)}"
        )

    # 2) Every policy grant must match the actual capability grant.
    grants = capability_grants(root)
    grant_set = set(grants)
    # core:* permissions are excluded; the command grants must equal the gated command set.
    if grant_set != gated:
        problems.append(
            f"capability grants != gated-registered: "
            f"only-in-caps={sorted(grant_set - gated)}; "
            f"missing-from-caps={sorted(gated - grant_set)}"
        )
    valid_tiers = {"R", "L1", "L2", "A", "X"}
    # An L2 (hard-delete) command may be granted to the window ONLY if it declares a
    # real protection mode; otherwise it must be denied. Plain grant/policy parity does
    # not capture this — an "allow" can be consistent yet unsafe (irreversible delete
    # with no undo/confirmation).
    safe_protection = {"soft-delete", "native-confirm"}
    for cmd, spec in sorted(policy.items()):
        tier = spec.get("tier")
        grant = spec.get("grant")
        if tier not in valid_tiers:
            problems.append(f"{cmd}: invalid tier {tier!r} (want one of {sorted(valid_tiers)})")
        if grant not in ("allow", "deny"):
            problems.append(f"{cmd}: invalid grant {grant!r} (want allow|deny)")
            continue
        actual = grants.get(cmd)
        if actual is None:
            problems.append(f"{cmd}: policy grant {grant!r} but no capability entry")
        elif actual != grant:
            problems.append(
                f"{cmd}: policy says {grant!r} but capabilities/default.json says {actual!r}"
            )
        if tier == "L2" and grant == "allow" and spec.get("protection") not in safe_protection:
            problems.append(
                f"{cmd}: L2 (hard-delete) may be 'allow' only with a declared protection of "
                f"{sorted(safe_protection)} (plus a matching test); got "
                f"{spec.get('protection')!r}. Until protected it must be 'deny'."
            )

    # 3) Design invariant: generic decide_approval must be DENIED to the window
    #    (approve requires renderer-independent native confirmation, T-011).
    if grants.get("decide_approval") != "deny":
        problems.append(
            "decide_approval must be DENIED to the main window "
            "(approve => native confirmation, T-011); it is not"
        )
    if grants.get("reject_approval") != "allow":
        problems.append("reject_approval (fail-safe reject path) must be granted; it is not")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: capability inventory inconsistent —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). Keep generate_handler! (lib.rs), the "
            f"AppManifest list (build.rs), command-policy.json, and default.json in "
            f"lockstep. See docs/design/WAVE_2B_CAPABILITY_APPROVAL_DESIGN.md.",
            file=sys.stderr,
        )
        return 1
    n = len(policy_commands(root))
    print(
        f"GREEN: capability inventory consistent ({n} gated commands; gated-registered == "
        f"manifest == policy == capability grants; {len(INTENTIONALLY_UNGATED)} explicitly "
        f"allowlisted-ungated; decide_approval denied, reject_approval granted)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
