#!/usr/bin/env python3
"""Capability-inventory consistency gate — the CI wall for T-010.

Tauri v2 gates only *plugin* commands by default; an app command registered in
`generate_handler!` but absent from the app manifest (`build.rs`) is invokable by the
webview with **no permission entry at all**. T-010 closes that by declaring every
command in the manifest and granting `allow-*` explicitly (deny-by-default). This
check keeps the three inventories from drifting apart as commands are added:

    registered commands  (src/lib.rs  generate_handler!)
      == AppManifest commands  (src-tauri/build.rs)
      == capability-policy inventory  (capabilities/command-policy.json)

and additionally asserts each policy `grant` matches the actual capability grants in
`capabilities/default.json` (allow-<cmd> / deny-<cmd>). A command added in one place
but not the others — or granted against its declared tier — **fails CI**. No manual
recount, no silently-ungated command.

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


def registered_commands(root: pathlib.Path) -> set[str]:
    """Command fn names inside `generate_handler![ ... ]` in lib.rs."""
    text = (root / LIB_RS).read_text(encoding="utf-8")
    m = re.search(r"generate_handler!\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        raise SystemExit("RED: could not find generate_handler![ ... ] in lib.rs")
    body = m.group(1)
    # Strip line comments so commented-out entries don't count.
    body = re.sub(r"//[^\n]*", "", body)
    return set(re.findall(r"(?:commands|files)::([a-z0-9_]+)", body))


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

    # 1) The three inventories must be the identical set.
    if registered != manifest:
        problems.append(
            f"registered != manifest: only-in-lib.rs={sorted(registered - manifest)}; "
            f"only-in-build.rs={sorted(manifest - registered)}"
        )
    if registered != policy_set:
        problems.append(
            f"registered != policy: only-in-lib.rs={sorted(registered - policy_set)}; "
            f"only-in-policy={sorted(policy_set - registered)}"
        )

    # 2) Every policy grant must match the actual capability grant.
    grants = capability_grants(root)
    grant_set = set(grants)
    # core:* permissions are excluded; the command grants must equal the command set.
    if grant_set != registered:
        problems.append(
            f"capability grants != registered: "
            f"only-in-caps={sorted(grant_set - registered)}; "
            f"missing-from-caps={sorted(registered - grant_set)}"
        )
    valid_tiers = {"R", "L1", "L2", "A", "X"}
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
        f"GREEN: capability inventory consistent ({n} commands; registered == manifest "
        f"== policy == capability grants; decide_approval denied, reject_approval granted)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
