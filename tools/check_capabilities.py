#!/usr/bin/env python3
"""Capability-inventory consistency gate — the CI wall for T-010.

Tauri v2 gates only *plugin* commands by default: while an app declares NO manifest, every
command in `generate_handler!` is invokable by the webview with no permission entry at all.
T-010 closes that by declaring an app manifest (`build.rs`) and granting `allow-*`
explicitly (deny-by-default). This check keeps the three inventories from drifting apart
as commands are added:

    registered commands  (src/lib.rs  generate_handler!)  MINUS the explicit
      INTENTIONALLY_UNGATED allowlist
      == AppManifest commands  (src-tauri/build.rs)
      == capability-policy inventory  (src-tauri/command-policy.json)

It also holds `capabilities/default.json` to being the ONLY capability source. Tauri enables
every file under `capabilities/` (tauri-build parses `./capabilities/**/*`) unless
`tauri.conf.json` names a list, and this gate reads one file; a second one would grant
commands it never looked at.

T-052 adds two rules over the execution/spend tier: every tier-X `allow` command must
DECLARE a `protection` (`native-confirm` or, honestly, `none`), and a command that claims
`native-confirm` must be backed by the enforcing constants in the Rust authority layer --
so the policy file cannot award itself a gate it does not have.

T-153 adds two more. `native-confirm` has a second form -- the command's own handler raises
a native OS dialog and writes only on an affirmative answer -- and a command claiming it is
held to `src/commands.rs` (NATIVE_DIALOG_ENFORCEMENT). And a command named `delete_*` may be
`allow` only with a declared `soft-delete` or `native-confirm`, WHATEVER its tier:
`delete_automation` was an irreversible hard delete granted with protection `none`, because
it was classified X and the hard-delete rule looked only at L2.

and additionally asserts each policy `grant` matches the actual capability grants in
`capabilities/default.json` (allow-<cmd> / deny-<cmd>). A command added in one place
but not the others — or granted against its declared tier — **fails CI**. No manual
recount, no silently-ungated command: registered_commands() captures EVERY entry of the
list, under any module prefix or under none, so a command that is neither declared under
the wall nor named in INTENTIONALLY_UNGATED (with a reason) fails this check.

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
CAPABILITIES_DIR = DESKTOP / "capabilities"
DEFAULT_CAP = CAPABILITIES_DIR / "default.json"
REPO_RS = DESKTOP / "core" / "src" / "repo.rs"
COMMANDS_RS = DESKTOP / "src" / "commands.rs"

# T-052. A tier-X command claiming `"protection": "native-confirm"` is claiming that a
# natively confirmed approval grant is verified and consumed in the authority layer before
# its write commits. That claim is checked against the source, not believed: each of these
# names the constants `repo::approvals::require_and_consume` must be called with for that
# command. A policy file can therefore not award itself a protection it does not have --
# which is this repository's characteristic defect, an honest sentence that stopped being
# true and nothing noticed.
NATIVE_CONFIRM_ENFORCEMENT = {
    "set_integration_auth_ref": ("INTEGRATION_ENTITY_TYPE", "INTEGRATION_AUTH_REF_ACTION_TYPE"),
    "set_integration_status": ("INTEGRATION_ENTITY_TYPE", "INTEGRATION_STATUS_ACTION_TYPE"),
    "set_automation_enabled": ("AUTOMATION_ENTITY_TYPE", "AUTOMATION_ENABLED_ACTION_TYPE"),
}

# T-153. The second form of `native-confirm`: no approval grant is consumed; the command's
# own handler raises a native OS dialog from Rust and performs its write only on an
# affirmative answer. The claim is held to the handler's source, in four parts, because a
# dialog that exists beside a write is not a dialog in front of it:
#   - the handler takes the window and shows a blocking native dialog under the
#     single-dialog guard (`HANDLER_MARKERS`);
#   - the handler does not perform the write itself;
#   - the write has exactly ONE call site in production code, and it is inside `gate`;
#   - inside `gate`, the question (`ask`) comes before the write.
# What this does NOT establish: that the gate returns on a declined answer. That is
# behaviour, and the Rust tests in commands.rs prove it by declining
# (`a_declined_native_dialog_deletes_nothing` and its neighbours).
NATIVE_DIALOG_ENFORCEMENT = {
    "delete_automation": {
        "gate": "delete_automation_after_native_confirmation",
        "ask": "confirm(delete_automation_prompt(",
        "write": "repo::automations::delete(",
    },
}
HANDLER_MARKERS = (
    "window: tauri::Window",
    "ConfirmationGuard::acquire()?",
    ".blocking_show()",
)
_TEST_MODULE = "\n#[cfg(test)]\nmod tests {"

# Commands deliberately registered OUTSIDE the window capability manifest. Every such
# command MUST be named here with a reason — this turns what used to be a silent regex blind
# spot (only commands::/files:: were scanned) into an explicit, reviewed, CI-enforced
# decision. A NEW command that is neither declared under the wall nor added here FAILS.
#
# WHAT THE NAME GETS WRONG. This comment said such a command is "webview-invokable with NO
# permission entry". That is Tauri's behaviour for an app with no manifest at all; this app
# has one, and with one the opposite holds. tauri 2.11.5 (the version Cargo.lock pins),
# `src/webview/mod.rs`: a command is REJECTED when `has_app_acl_manifest && invoke.acl
# .is_none()`, and a command absent from the manifest resolves no ACL. So what is listed here is not
# ungated — the window is refused it, and its caller in `src/services/desktop.ts`
# cannot reach it. Established by reading that source, and then OBSERVED in the installed
# application on 2026-10-09 (`Command governed_turn_execute not allowed by ACL`).
# The set is kept, and kept under its old name because `build.rs` and
# `docs/REACHABILITY_GATE.md` cite it; what it now records is "registered, and deliberately
# not grantable to the window". Whether to grant one (a manifest entry plus an `allow-*`)
# or remove its caller is the Owner's decision: it changes what the window may invoke.
#   - governed_turn_execute: the trusted-broker governed-turn proxy; gated by the broker
#       lease/challenge system and fails closed ("broker_unavailable") off the supported
#       path. Whether it should additionally sit under the window policy is an owner gate call.
# 2026-10-09: FIVE of the six left this set. The first real install (a locally built .deb on the
# Debian development box) showed the refusal on screen -- `Command read_decision_ledger not
# allowed by ACL` -- and the Owner granted the four governance reads and the trust self-test.
# They are declared under the wall now, tier R. What stays here is the one command a governed
# result travels through, until an independent audit has it in scope.
INTENTIONALLY_UNGATED = {
    "governed_turn_execute",
}


_HANDLER_ENTRY = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*::)*([A-Za-z_][A-Za-z0-9_]*)")


def registered_commands(root: pathlib.Path) -> set[str]:
    """Every command fn name inside `generate_handler![ ... ]` in lib.rs, regardless of the
    module path it is registered under (commands::, files::, governance::, governed_turn::,
    …) — or under none.

    The list is read ENTRY BY ENTRY. The first cut scanned only `commands::`/`files::`; the
    second matched any `mod::fn` and so still dropped a bare `greet` brought in by a `use`,
    which is a registered command this gate then never compared with anything. An entry
    that is not a plain path is refused rather than skipped: a list this cannot read in
    full is not one it can call consistent."""
    text = (root / LIB_RS).read_text(encoding="utf-8")
    m = re.search(r"generate_handler!\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        raise SystemExit("RED: could not find generate_handler![ ... ] in lib.rs")
    body = m.group(1)
    # Strip line comments so commented-out entries don't count.
    body = re.sub(r"//[^\n]*", "", body)
    names: set[str] = set()
    for entry in body.split(","):
        entry = entry.strip()
        if not entry:
            continue
        found = _HANDLER_ENTRY.fullmatch(entry)
        if not found:
            raise SystemExit(
                f"RED: generate_handler![ ... ] in lib.rs holds an entry this gate cannot "
                f"read as a command path: {entry!r}")
        names.add(found.group(1))
    return names


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


def grants_from_permissions(permissions: list) -> dict[str, str]:
    """command fn name -> 'allow' | 'deny' for a capability file's `permissions` list.

    Permission ids hyphenate the command name (`list_dir` -> `allow-list-dir`); map
    back to the underscored fn name so the sets are comparable. `core:default` and plugin
    permissions (`dialog:allow-open`) open with their plugin's name, not with `allow-`, and
    are not app commands.

    The ONE place this mapping is written: `check_reachability.capability_grants` calls it
    rather than carrying its own copy.
    """
    grants: dict[str, str] = {}
    for perm in permissions:
        for kind in ("allow", "deny"):
            prefix = f"{kind}-"
            # No separate `core:` test: a string that opens `allow-` cannot open `core:`.
            # There was one here, and no input could make it matter.
            if perm.startswith(prefix):
                cmd = perm[len(prefix):].replace("-", "_")
                grants[cmd] = kind
    return grants


def capability_grants(root: pathlib.Path) -> dict[str, str]:
    """command fn name -> 'allow' | 'deny' from capabilities/default.json."""
    doc = json.loads((root / DEFAULT_CAP).read_text(encoding="utf-8"))
    return grants_from_permissions(doc["permissions"])


def capability_source_problems(root: pathlib.Path) -> list[str]:
    """`capabilities/default.json` must be the only place a window grant can come from.

    Tauri does not read "the default capability": tauri-build 2.6.3 parses
    `./capabilities/**/*` and enables every file it finds, unless `app.security.capabilities`
    in the Tauri config names a list (which may also carry capabilities INLINE). This gate
    parses one file, so either of those is a grant it would print GREEN over.
    """
    problems: list[str] = []
    directory = root / CAPABILITIES_DIR
    extra = sorted(p.relative_to(root).as_posix() for p in directory.rglob("*")
                   if p.is_file() and p != root / DEFAULT_CAP)
    if extra:
        problems.append(
            f"{CAPABILITIES_DIR.as_posix()}/ holds capability file(s) this gate does not read: "
            f"{extra}. Tauri enables every file there, so each can grant a command unseen. "
            f"Put the grant in default.json, where it is compared with the policy.")
    for conf in sorted((root / DESKTOP).glob("tauri*.conf.json")):
        rel = conf.relative_to(root).as_posix()
        try:
            doc = json.loads(conf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{rel} is not valid JSON ({exc}), so whether it names its own "
                            f"capability list cannot be read")
            continue
        security = (doc.get("app") or {}).get("security") if isinstance(doc, dict) else None
        if isinstance(security, dict) and "capabilities" in security:
            problems.append(
                f"{rel} sets app.security.capabilities, which replaces 'every file under "
                f"capabilities/' with its own list and may hold capabilities inline. This "
                f"gate reads {DEFAULT_CAP.as_posix()} only; remove the key.")
    return problems


def production_source(text: str) -> str:
    """`commands.rs` up to its test module. The tests name the same functions and calls, and
    a mention there is not a production call."""
    return text.split(_TEST_MODULE)[0]


def function_text(production: str, name: str) -> str | None:
    """The text of one top-level `fn name(` / `fn name<`: from its `fn` to the first `}` in
    column 0. None when there is no such function."""
    m = re.search(rf"\bfn {re.escape(name)}[(<]", production)
    if not m:
        return None
    end = production.find("\n}\n", m.start())
    return production[m.start():] if end == -1 else production[m.start():end]


def native_dialog_problems(cmd: str, spec: dict[str, str], commands_src: str) -> list[str]:
    """Hold one `native-confirm` claim of the dialog form to `src/commands.rs`."""
    if not commands_src:
        return [f"{cmd}: claims 'native-confirm' by a native dialog but {COMMANDS_RS} is "
                f"missing, so nothing checks the claim"]
    production = production_source(commands_src)
    problems: list[str] = []
    handler = function_text(production, cmd)
    if handler is None:
        return [f"{cmd}: claims 'native-confirm' by a native dialog but {COMMANDS_RS} has "
                f"no handler `fn {cmd}`"]
    for marker in HANDLER_MARKERS:
        if marker not in handler:
            problems.append(
                f"{cmd}: claims 'native-confirm' by a native dialog but its handler lacks "
                f"`{marker}`")
    if f"{spec['gate']}(" not in handler:
        problems.append(
            f"{cmd}: claims 'native-confirm' by a native dialog but its handler never calls "
            f"`{spec['gate']}`, the function that asks before it writes")
    if spec["write"] in handler:
        problems.append(
            f"{cmd}: its handler calls `{spec['write']}` itself, outside the function that "
            f"asks first")
    sites = production.count(spec["write"])
    if sites != 1:
        problems.append(
            f"{cmd}: `{spec['write']}` has {sites} production call site(s) in {COMMANDS_RS}; "
            f"exactly one is allowed, and each further one is a way around the dialog")
    gate = function_text(production, spec["gate"])
    if gate is None:
        problems.append(f"{cmd}: {COMMANDS_RS} has no `fn {spec['gate']}`")
        return problems
    asked, wrote = gate.find(spec["ask"]), gate.find(spec["write"])
    if asked == -1:
        problems.append(f"{cmd}: `{spec['gate']}` never asks (`{spec['ask']}` is absent)")
    if wrote == -1:
        problems.append(f"{cmd}: the write `{spec['write']}` is not inside `{spec['gate']}`")
    if asked != -1 and wrote != -1 and wrote < asked:
        problems.append(f"{cmd}: `{spec['gate']}` writes before it asks")
    return problems


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = capability_source_problems(root)

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
    # X may honestly declare itself ungated; L2 may not.
    x_protection = {"native-confirm", "none"}
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
        # T-052: X is the execution/spend tier. Every X 'allow' must SAY whether it is
        # gated. It may say 'none' -- 18 of the 21 do, and that is the honest record of an
        # ungated execution-tier command rather than the silence this file kept before.
        if tier == "X" and grant == "allow":
            declared = spec.get("protection")
            if declared not in x_protection:
                problems.append(
                    f"{cmd}: tier X (execution/spend) with grant 'allow' must declare a "
                    f"'protection' of {sorted(x_protection)}; got {declared!r}. Say 'none' "
                    f"if it is ungated -- an undeclared execution-tier command is how the "
                    f"three T-052 commands stayed ungated without anything saying so."
                )
        # T-153: a row delete is a row delete under any tier. The L2 rule above is keyed on
        # the tier a person typed, so classifying a hard delete X took it out of that rule's
        # sight and let it say 'none' -- which is exactly what delete_automation did.
        if (cmd.startswith("delete_") and grant == "allow" and tier != "L2"
                and spec.get("protection") not in safe_protection):
            problems.append(
                f"{cmd}: a delete_* command may be 'allow' only with a declared protection of "
                f"{sorted(safe_protection)}, whatever its tier (here {tier!r}); got "
                f"{spec.get('protection')!r}. Classifying a hard delete outside L2 does not "
                f"exempt it."
            )

    # T-052: a claimed 'native-confirm' must be backed by the enforcing constants in the
    # authority layer, in the same repository, at this head. A missing authority layer is
    # RED, not an exception and not a pass: a claim nothing can be checked against is
    # exactly the thing this rule exists to refuse.
    repo_path = root / REPO_RS
    repo_src = repo_path.read_text(encoding="utf-8") if repo_path.exists() else ""
    if not repo_src and any(
        s.get("protection") == "native-confirm" for s in policy.values()
    ):
        problems.append(
            f"{REPO_RS} is missing, so no 'native-confirm' claim in the policy can be "
            f"checked against the authority layer that is supposed to enforce it"
        )
    commands_path = root / COMMANDS_RS
    commands_src = commands_path.read_text(encoding="utf-8") if commands_path.exists() else ""
    for cmd, spec in sorted(policy.items()):
        if spec.get("protection") != "native-confirm" or spec.get("tier") != "X":
            continue
        if cmd in NATIVE_DIALOG_ENFORCEMENT:
            problems.extend(
                native_dialog_problems(cmd, NATIVE_DIALOG_ENFORCEMENT[cmd], commands_src))
            continue
        consts = NATIVE_CONFIRM_ENFORCEMENT.get(cmd)
        if consts is None:
            problems.append(
                f"{cmd}: claims 'native-confirm' but NATIVE_CONFIRM_ENFORCEMENT names no "
                f"enforcing constants for it and NATIVE_DIALOG_ENFORCEMENT names no dialog "
                f"gate, so nothing checks the claim"
            )
            continue
        missing = [c for c in consts if f"approvals::{c}," not in repo_src]
        if missing:
            problems.append(
                f"{cmd}: claims 'native-confirm' but {REPO_RS} never passes "
                f"{missing} to the approval gate"
            )
    # The trailing "(" matters: without it this matched `require_and_consume_RENAMED`
    # as a prefix and the mutation test came back GREEN -- a check testing nothing, the
    # exact failure mode CLAUDE.md's "a green test is not a passing check" rule sweeps for.
    if repo_src and "approvals::require_and_consume(" not in repo_src:
        problems.append(
            "repo.rs has no `approvals::require_and_consume` call: the shared "
            "verify-and-consume helper every 'native-confirm' claim rests on is gone"
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
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
    policy = policy_commands(root)
    n = len(policy)
    x_allow = [c for c, s in policy.items() if s.get("tier") == "X" and s.get("grant") == "allow"]
    confirmed = [c for c in x_allow if policy[c].get("protection") == "native-confirm"]
    by_dialog = [c for c in confirmed if c in NATIVE_DIALOG_ENFORCEMENT]
    print(
        f"GREEN: capability inventory consistent ({n} gated commands; gated-registered == "
        f"manifest == policy == capability grants; default.json is the only capability "
        f"source; {len(INTENTIONALLY_UNGATED)} registered outside the manifest by name, which "
        f"the window is refused; decide_approval denied, reject_approval granted; "
        f"{len(x_allow)} tier-X allow commands all declare a protection, "
        f"{len(confirmed)} of them 'native-confirm': {len(confirmed) - len(by_dialog)} "
        f"backed by the enforcing constants in repo.rs, {len(by_dialog)} by a native dialog "
        f"in the handler, held to commands.rs; no delete_* command is granted without a "
        f"declared protection)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
