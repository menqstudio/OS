#!/usr/bin/env python3
"""AI-entry-point inventory gate — the CI wall for "every AI execution is governed or explicitly tracked".

The security spine (Wave 3) makes the MAIN governed-chat seam run the challenge->execute->verify->persist
chain. But the desktop exposes several other Tauri commands that reach the model provider directly, and the
real risk is silent drift: a NEW command that calls `ai::generate` / `ai::generate_stream` slips in
UNCLASSIFIED, and nobody notices it bypasses governance. This gate makes that impossible to merge.

It does NOT change the security architecture and does NOT claim any surface is governed that isn't — it is
a deterministic, offline INVENTORY: every Tauri command that invokes the model provider must be listed in
`apps/desktop/src-tauri/ai-surface-policy.json` with an explicit, honest classification:

  - `governed`           — routes ONLY through `ai::governed_turn` (the full governed chain); must NOT reach
                           the generic `ai::generate` / `ai::generate_stream` (directly OR via a helper).
  - `ungoverned_tracked` — reaches a generic provider entry today; MUST carry a `tracking` reference (the
                           task / wave that will govern or gate it). This is the honest state of the four
                           current surfaces while Wave 3b is pending — recorded, not hidden.
  - `excluded`           — deliberately out of the production governed set (e.g. dev-only), with `tracking`.

Helper-hop hardening: a provider call does NOT have to sit directly in the command body to count. A
`#[tauri::command]` that calls a NON-command `pub` helper defined in the same file, where that helper
reaches `ai::generate` / `ai::generate_stream` / `ai::governed_turn`, is treated as an AI surface too —
resolved ONE call-hop deep. This closes the "hide the provider call behind a pub helper" bypass: the
command is still required in the policy, and it still cannot be labelled `governed` if the helper reaches a
generic provider entry.

Fail-closed: an AI-invoking command (direct OR one helper-hop) missing from the policy, a stale policy
entry, a policy entry that is not a command, a non-governed surface with no tracking, or a `governed`
surface that actually reaches a generic provider entry — all RED.

Usage:  python tools/check_ai_surfaces.py [--root DIR]
Exit 0 + "GREEN: ..." when consistent; exit 1 + the problems otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

COMMANDS_RS = "apps/desktop/src-tauri/src/commands.rs"
# The gate scans EVERY Rust source under src/ (not only commands.rs): a `#[tauri::command]` that reaches a
# provider entry lives in files.rs / governance.rs / governed_turn.rs / ai.rs too, and scanning one file
# left those permanently invisible while the gate still printed GREEN (audit F-21/F-37). All files are read
# and concatenated so cross-file `#[tauri::command]`s are inventoried and helper hops resolve tree-wide.
SRC_DIR = "apps/desktop/src-tauri/src"
POLICY = "apps/desktop/src-tauri/ai-surface-policy.json"

GOVERNANCE_STATES = ("governed", "ungoverned_tracked", "excluded")
# the generic, NON-governed provider entry points (a governed surface must never reach these).
GENERIC_PROVIDER_CALLS = ("generate", "generate_stream")
# the full set of provider entry points a command may reach (governed + generic).
_PROVIDER_RE = re.compile(r"(?:crate::)?ai::(generate_stream|generate|governed_turn)\b")
# a top-level fn head — `pub`, `pub(crate)`, or NON-pub, sync or async. Commands and helpers both match;
# the `#[tauri::command]` attribute above the head is what distinguishes a command from a helper. Matching
# `pub(crate)` and non-pub heads too (audit F-38) closes the "hide the provider call behind a pub(crate) /
# non-pub helper" evasion — such a helper is now a resolvable one-hop, not an invisible sink whose provider
# call is silently attributed to the preceding fn's slice.
_FN_RE = re.compile(r"^\s*(?:pub(?:\(crate\))? )?(?:async )?fn (\w+)\s*\(")
# any identifier used in call position `name(` — intersected with known fn names to find
# same-file helper calls (crate-local helpers appear as `helper(`, `self::helper(`,
# `crate::...::helper(`; the bare-name match before `(` catches all of these forms).
_CALL_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")


def _has_command_attr(lines: list[str], head_idx: int) -> bool:
    """True iff `#[tauri::command]` decorates the fn head at `head_idx`.

    Scan upward, skipping blank lines, `//`/`///` comments and OTHER `#[...]` attributes; the first
    substantive code line (a `}`, a statement, or another fn head) terminates the search. This binds an
    attribute to its OWN fn — unlike a fixed N-line window, it cannot leak a command attribute onto a plain
    helper that merely happens to sit a couple of lines below a command.
    """
    j = head_idx - 1
    while j >= 0:
        s = lines[j].strip()
        if s == "":
            j -= 1
            continue
        if s.startswith("#["):
            if "tauri::command" in s:
                return True
            j -= 1
            continue
        if s.startswith("//"):
            j -= 1
            continue
        return False  # substantive code — any attribute above this belongs to another item
    return False


def parse_command_ai_calls(src: str) -> dict:
    """Map each top-level `pub fn` -> {is_command, calls, local_calls}.

    - is_command:  True iff `#[tauri::command]` decorates this head (see `_has_command_attr`).
    - calls:       provider entry points (`generate` / `generate_stream` / `governed_turn`) referenced
                   DIRECTLY in this fn's body (sorted, de-duped).
    - local_calls: names of OTHER same-file `pub fn`s this fn invokes (sorted) — used to resolve a
                   provider call reached one hop through a helper. Self-references are excluded.

    Pure / testable — no I/O.
    """
    lines = src.splitlines()
    heads: list[tuple[str, bool, int]] = []
    for i, ln in enumerate(lines):
        m = _FN_RE.match(ln)
        if m:
            heads.append((m.group(1), _has_command_attr(lines, i), i))
    fn_names = {name for name, _, _ in heads}
    out: dict = {}
    for k, (name, is_cmd, start) in enumerate(heads):
        end = heads[k + 1][2] if k + 1 < len(heads) else len(lines)
        body = "\n".join(lines[start:end])
        called = set(_CALL_RE.findall(body))
        local_calls = sorted((called & fn_names) - {name})
        out[name] = {
            "is_command": is_cmd,
            "calls": sorted(set(_PROVIDER_RE.findall(body))),
            "local_calls": local_calls,
        }
    return out


def resolve_command_surfaces(parsed: dict) -> dict:
    """Resolve, for each command fn, the provider entry points it reaches DIRECTLY and ONE call-hop
    through a NON-command `pub` helper.

    Returns {cmd_name: {'direct': set, 'via_helper': {helper_name: set(providers)}, 'effective': set}}.
    Only `#[tauri::command]` fns are keys — helpers are resolution inputs, not surfaces themselves.
    Pure / testable.
    """
    out: dict = {}
    for name, v in parsed.items():
        if not v["is_command"]:
            continue
        direct = set(v["calls"])
        via_helper: dict = {}
        for callee in v["local_calls"]:
            helper = parsed.get(callee)
            # one hop, NON-command helpers only (a command is its own governed surface; don't chain
            # command->command), and never self.
            if helper is None or helper["is_command"] or callee == name:
                continue
            if helper["calls"]:
                via_helper[callee] = set(helper["calls"])
        effective = set(direct)
        for reached in via_helper.values():
            effective |= reached
        out[name] = {"direct": direct, "via_helper": via_helper, "effective": effective}
    return out


def _reach_desc(resolved_entry: dict, only: set | None = None) -> str:
    """Human description of HOW a command reaches provider entries (optionally filtered to `only`).
    e.g. "directly (generate_stream); via non-command helper 'build_prompt' (generate)"."""
    keep = (lambda s: s) if only is None else (lambda s: s & only)
    parts: list[str] = []
    direct = sorted(keep(resolved_entry["direct"]))
    if direct:
        parts.append(f"directly ({', '.join(direct)})")
    for helper, reached in sorted(resolved_entry["via_helper"].items()):
        via = sorted(keep(reached))
        if via:
            parts.append(f"via non-command helper '{helper}' ({', '.join(via)})")
    return "; ".join(parts) if parts else "(none)"


def check(commands_src: str, policy) -> list[str]:
    """Return a list of problems (empty == consistent). Pure/offline-testable."""
    problems: list[str] = []
    if not isinstance(policy, dict):
        return [f"{POLICY}: invalid JSON object"]
    parsed = parse_command_ai_calls(commands_src)
    resolved = resolve_command_surfaces(parsed)
    # a command is an AI surface if it reaches ANY provider entry directly OR one helper-hop away.
    ai_commands = {n: r for n, r in resolved.items() if r["effective"]}
    surfaces = policy.get("surfaces")
    if not isinstance(surfaces, list):
        return [f"{POLICY}: missing 'surfaces' array"]
    by_name = {}
    for p in surfaces:
        if isinstance(p, dict) and p.get("command"):
            by_name[p["command"]] = p

    # 1. every AI-invoking command MUST be classified (a new unclassified surface is the drift we block) —
    #    including one that reaches the provider only through a pub helper.
    for name, r in sorted(ai_commands.items()):
        if name not in by_name:
            problems.append(
                f"AI surface '{name}' reaches the model provider [{_reach_desc(r)}] but is NOT classified "
                f"in {POLICY} (fail-closed: add it as governed / ungoverned_tracked / excluded)")

    # 2. every policy entry must still be a real AI-invoking command, with a valid honest classification.
    for name, p in sorted(by_name.items()):
        parsed_entry = parsed.get(name)
        if parsed_entry is None:
            problems.append(f"{POLICY}: surface '{name}' is not a fn in commands.rs (stale entry — remove it)")
            continue
        if not parsed_entry["is_command"]:
            problems.append(f"{POLICY}: surface '{name}' is not a #[tauri::command] (only Tauri commands are "
                            f"AI surfaces — a bare helper cannot be a policy entry; remove it or promote it)")
            continue
        r = resolved[name]
        effective = r["effective"]
        if not effective:
            problems.append(f"{POLICY}: surface '{name}' no longer calls any AI provider entry (directly or via "
                            f"a one-hop helper) (stale classification)")
        state = p.get("governance")
        if state not in GOVERNANCE_STATES:
            problems.append(f"{POLICY}: surface '{name}' governance must be one of {GOVERNANCE_STATES}, got {state!r}")
        if state != "governed" and not (isinstance(p.get("tracking"), str) and p.get("tracking").strip()):
            problems.append(f"{POLICY}: surface '{name}' is {state!r} but has no non-empty 'tracking' reference "
                            f"(a non-governed AI surface must be tracked to a task/wave)")
        # 3. code vs. claimed-governance agreement — cannot label a generic-provider reacher 'governed',
        #    whether the generic entry is called directly OR hidden behind a pub helper one hop away.
        generic = effective & set(GENERIC_PROVIDER_CALLS)
        uses_generic = bool(generic)
        if state == "governed" and uses_generic:
            problems.append(f"{POLICY}: surface '{name}' is labelled 'governed' but reaches a GENERIC ungoverned "
                            f"provider entry {sorted(generic)} [{_reach_desc(r, generic)}] — a governed surface "
                            f"must route only through ai::governed_turn (a pub helper cannot launder it)")
        if state == "ungoverned_tracked" and not uses_generic:
            problems.append(f"{POLICY}: surface '{name}' is 'ungoverned_tracked' but reaches no generic provider "
                            f"entry (reaches={sorted(effective)}) — reclassify")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI-entry-point inventory gate")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    try:
        rs_files = sorted((root / SRC_DIR).rglob("*.rs"))
        if not rs_files:
            print(f"RED: no Rust sources under {SRC_DIR}", file=sys.stderr)
            return 1
        # Concatenate every src/**/*.rs so a #[tauri::command] in ANY module is inventoried (audit F-21).
        # Files end with `}`, which terminates _has_command_attr's upward scan, so no attribute leaks across
        # a file boundary; a blank-line join keeps every fn head line-anchored.
        commands_src = "\n".join(f.read_text(encoding="utf-8") for f in rs_files)
    except OSError as exc:
        print(f"RED: cannot read Rust sources under {SRC_DIR}: {exc}", file=sys.stderr)
        return 1
    try:
        policy = json.loads((root / POLICY).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"RED: cannot read {POLICY}: {exc}", file=sys.stderr)
        return 1

    problems = check(commands_src, policy)
    if problems:
        print("RED: AI-surface inventory inconsistent —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n{len(problems)} problem(s). Every AI-invoking command (direct or one helper-hop) must be "
              f"honestly classified in {POLICY} (governed / ungoverned_tracked / excluded).", file=sys.stderr)
        return 1
    n = len([p for p in policy.get("surfaces", []) if isinstance(p, dict)])
    print(f"GREEN: AI-surface inventory consistent ({n} classified surfaces; every provider-invoking "
          f"command is accounted for, including those reached one hop through a pub helper; no 'governed' "
          f"surface reaches a generic provider entry).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
