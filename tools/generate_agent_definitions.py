#!/usr/bin/env python3
"""Generate `.claude/agents/*.md` from the pack + authority registries.

Bro delegates with the `Task` tool, and that tool picks a subagent by NAME from these files —
each one declaring which tools that kind of agent may use. Without them every specialist Bro
spawned inherited Bro's own full capability, which makes `engine/agents/authority-policy.json`
decorative: it says a Verifier `can_build: false` and a Push Executor may only act in `release`
mode, and nothing enforced either.

So the capability half of the contract lives here, generated from the registries rather than
hand-written, because 52 packs and 311 roles hand-maintained WILL drift from the registry that
defines them — and a drifted capability list is worse than none, since it reads as enforcement.

The PATH half stays where it already is: `engine/schemas/task-contract.schema.json` carries
`scope` and `prohibited_scope` per task, which Bro states when he delegates. Tools are a property
of the ROLE; paths are a property of the JOB. Conflating them would mean regenerating agent
definitions for every task.

stdlib only. Run: `python tools/generate_agent_definitions.py [--check]`
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKS = ROOT / "engine" / "packs" / "registry.json"
AUTHORITY = ROOT / "engine" / "agents" / "authority-policy.json"
OUT_DIR = ROOT / ".claude" / "agents"

#: Tool sets by what the authority policy says a role may DO.
#:
#: A builder writes, so it gets the editing tools. A verifier whose whole value is independence
#: must not be able to edit the thing it is judging — it keeps Bash because verifying means
#: running builds and tests, and a verifier that cannot run anything can only read and opine.
#: The release role gets no editing either: its job is to push what others built.
TOOLS_BUILD = "Read, Edit, Write, Grep, Glob, Bash"
TOOLS_VERIFY = "Read, Grep, Glob, Bash"
TOOLS_RELEASE = "Read, Grep, Glob, Bash"

#: Capability TIERS — the choice Bro actually gets to make.
#:
#: The role-derived definitions above answer "what may a Verifier do", which is the authority
#: policy's question. They do not answer the owner's: *Bro* should decide who has what. The `Task`
#: tool picks a subagent by name and takes its tools from that file, so Bro cannot hand over an
#: arbitrary tool list at spawn time — the decision has to be made by CHOOSING, which means there
#: has to be something to choose between.
#:
#: These are that something. Each tier is the same worker at a different reach, so Bro grants
#: capability the way he grants scope: deliberately, per task, at the narrowest level that lets
#: the job finish. A specialist that only needs to read the code to answer a question gets
#: `reader`; one that must run the suite but must not touch it gets `runner`; only work that
#: genuinely changes files gets `builder`.
TIERS: dict[str, tuple[str, str]] = {
    "reader": (
        "Read, Grep, Glob",
        "Reads and reports. Cannot run anything and cannot change anything. Use for questions, "
        "reviews, investigations, and any answer that is about the code rather than to it.",
    ),
    "runner": (
        "Read, Grep, Glob, Bash",
        "Reads and RUNS — builds, tests, git status/diff/log, any inspection — but cannot edit. "
        "Use to find out whether something actually works, and whenever the answer must not be "
        "produced by the same hand that could change the thing being measured.",
    ),
    "builder": (
        "Read, Edit, Write, Grep, Glob, Bash",
        "Full working capability: reads, runs, and changes files inside its scope. Use only when "
        "the task is genuinely to change something.",
    ),
}

TIER_BODY = """You are a **{tier}** specialist, spawned by Bro for one task.

## What you may do

{blurb}

Your tools above are the capability half of your grant, and Bro chose this tier deliberately —
a narrower one than you might want is a decision, not an oversight. If the task cannot be done at
this level, say exactly what you would need and stop. Do not work around the limit.

The PATH half arrives in your task prompt as `scope` and `prohibited_scope`. Outside `scope` is
read-only; `prohibited_scope` is untouchable. Scope may point outside this repository when the
work genuinely lives elsewhere. If the task cannot be done inside its scope, say so and stop — do
not widen it yourself.

## How to work

Read `CLAUDE.md` and `START_HERE.md` before you act. Report evidence, not assurances: what you
changed, what you ran, what it printed. If something cannot be made genuinely true, leave it
failing and say so. Never weaken a check to make a test pass, and never claim you ran something
you did not.

You return your result to Bro. You do not delegate further."""

HEADER = """---
name: {name}
description: {description}
tools: {tools}
---

{body}
"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load() -> tuple[list[dict], dict]:
    with PACKS.open(encoding="utf-8") as f:
        packs = json.load(f)["packs"]
    with AUTHORITY.open(encoding="utf-8") as f:
        authority = json.load(f)
    return packs, authority


def override_for(authority: dict, pack_id: str, role: str) -> dict | None:
    for entry in authority.get("exact_overrides", []):
        if entry.get("pack_id") == pack_id and entry.get("role") == role:
            return entry
    return None


def authority_for(authority: dict, pack: dict, role: str) -> tuple[dict, str]:
    """The role's authority record, and which rule produced it.

    Mirrors `authority-policy.json.derivation`: exact overrides win; otherwise the FINAL declared
    role of a pack that requires an independent verifier is the designated verifier; everything
    else takes the default builder authority.
    """
    exact = override_for(authority, pack["id"], role)
    if exact is not None:
        return exact, "exact override"
    if pack.get("independent_verifier_required") and role == pack["roles"][-1]:
        return authority["designated_verifier"], "designated verifier (final declared role)"
    return authority["default"], "pack default"


def tools_for(record: dict) -> str:
    if record.get("can_release"):
        return TOOLS_RELEASE
    if record.get("can_verify") and not record.get("can_build"):
        return TOOLS_VERIFY
    return TOOLS_BUILD


def definition(pack: dict, role: str, record: dict, why: str) -> tuple[str, str]:
    name = f"{slug(pack['id'])}--{slug(role)}"
    modes = ", ".join(record.get("allowed_modes", []))
    can = ", ".join(
        label for label, key in (("build", "can_build"), ("verify", "can_verify"),
                                 ("release", "can_release")) if record.get(key)
    ) or "nothing (no authority declared)"
    description = (
        f"{role} in the {pack['id']} pack. May {can}. "
        f"Use when the task is that pack's specialism and needs a {role.lower()}."
    )
    body = f"""You are the **{role}** of the `{pack['id']}` pack.

Pack lead: {pack.get('lead', 'n/a')}. Declared roles: {', '.join(pack['roles'])}.

## Your authority

Derived from `engine/agents/authority-policy.json` ({why}) — this is not advice, it is the
contract you were spawned under:

- You may: **{can}**
- Modes you may act in: **{modes or 'none declared'}**
- Risk ceiling: **{record.get('risk_ceiling', 'unspecified')}**

Your tool list above is the capability half of that contract. The PATH half arrives in your task
prompt as `scope` and `prohibited_scope` — Bro states them when he delegates. Treat anything
outside `scope` as read-only, and never touch `prohibited_scope`. If the task cannot be done
inside its scope, say so and stop; do not widen it yourself.

## How to work

Read `CLAUDE.md` and `START_HERE.md` before you act — they are the law you operate under. Report
back evidence, not assurances: what you changed, what you ran, what it printed. If a check cannot
be made genuinely true, leave it failing and say so. Never weaken a check to make a test pass, and
never claim you ran something you did not.

You return your result to Bro, who is the conductor. You do not delegate further."""
    return name, HEADER.format(name=name, description=description, tools=tools_for(record), body=body)


def build() -> dict[str, str]:
    packs, authority = load()
    out: dict[str, str] = {}

    # The tiers first: they are what Bro chooses between when the work does not belong to a named
    # pack role, which is most conversational work.
    for tier, (tools, blurb) in TIERS.items():
        out[tier] = HEADER.format(
            name=tier,
            description=(
                f"{blurb} Bro picks the tier per task — grant the narrowest one that lets the "
                "job finish."
            ),
            tools=tools,
            body=TIER_BODY.format(tier=tier, blurb=blurb),
        )

    for pack in packs:
        for role in pack["roles"]:
            record, why = authority_for(authority, pack, role)
            name, text = definition(pack, role, record, why)
            if name in out:
                raise SystemExit(f"duplicate agent name {name!r} — the registry has a collision")
            out[name] = text
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the generated files match the registries; write nothing")
    args = ap.parse_args()

    wanted = build()
    if args.check:
        problems = []
        existing = {p.stem for p in OUT_DIR.glob("*.md")} if OUT_DIR.is_dir() else set()
        for name, text in wanted.items():
            path = OUT_DIR / f"{name}.md"
            if not path.exists():
                problems.append(f"{name}: missing")
            elif path.read_text(encoding="utf-8") != text:
                problems.append(f"{name}: drifted from the registry")
        for stale in sorted(existing - set(wanted)):
            problems.append(f"{stale}: no longer in the registry")
        if problems:
            print("RED: agent definitions do not match the registries —")
            for problem in problems[:20]:
                print(f"  - {problem}")
            if len(problems) > 20:
                print(f"  … and {len(problems) - 20} more")
            print("\nRun: python tools/generate_agent_definitions.py")
            return 1
        print(f"GREEN: {len(wanted)} agent definitions match the pack + authority registries.")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.md"):
        if stale.stem not in wanted:
            stale.unlink()
    for name, text in wanted.items():
        (OUT_DIR / f"{name}.md").write_text(text, encoding="utf-8")
    print(f"wrote {len(wanted)} agent definitions to {OUT_DIR.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
