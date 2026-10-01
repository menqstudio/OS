#!/usr/bin/env python3
"""Generate `.claude/agents/*.md` from the pack + authority registries.

Bro delegates with the `Task` tool, and that tool picks a subagent by NAME from these files —
each one declaring which tools that kind of agent may use. Without them every specialist Bro
spawned inherited Bro's own full capability, which makes `engine/agents/authority-policy.json`
decorative: it says a Verifier `can_build: false` and a Push Executor may only act in `release`
mode, and nothing enforced either.

So the capability half of the contract lives here, generated from the registries rather than
hand-written, because 52 packs and their roles hand-maintained WILL drift from the registry that
defines them — and a drifted capability list is worse than none, since it reads as enforcement.

WHAT IT DOES NOT GENERATE, stated because this paragraph used to say "311 roles" and the tool has
never written that many: it walks `packs[*].roles` — the 259 DECLARED roles — and adds the three
tiers, 262 files. The engine registers 311 identities, because `registry.json.mandatory_roles`
appends an `Automation & Flow Engineer` to every one of the 52 packs
(`engine/runtime/bro_identity.pack_roles()`), and that sixth role has NO definition here and is
not on any file's "Declared roles" line. `test_generate_agent_definitions.py` pins the 52 by name
so the gap cannot be forgotten, and it is a gap, not a decision: closing it changes a count that
`config/counted-claims.json`, `README.md` and the desktop app's prose all carry.

WHAT A TOOL LIST IS NOT. A definition without `Edit`/`Write` is a role that was not HANDED the
edit tools. It is not a role that cannot write: every list here keeps `Bash`, and a shell can
write any file. The root wall does not refuse that in advance — `.claude/hooks/
canonical_law_gate.py` says so under "SHELL IS NOT GATED BEFORE THE FACT" — it detects it after
the write has landed, and only in a session whose project root is this checkout. The generated
text says exactly that and no more.

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
#: is not handed them — and keeps Bash, because verifying means running builds and tests, and a
#: verifier that cannot run anything can only read and opine. That is a narrower grant, not an
#: inability: Bash writes files, so "must not edit what it judges" is carried by `NO_EDIT_NOTE`
#: as an instruction and by the wall's after-the-fact detection, not by this list.
#:
#: The release role gets the same list: its job is to push what others built. There were two
#: constants here, `TOOLS_VERIFY` and `TOOLS_RELEASE`, holding the same string, which read as two
#: grants. There is one. What separates a Push Executor from a verifier is its `allowed_modes`
#: (`release` only), and no tool list expresses a mode — the engine's lease does.
TOOLS_BUILD = "Read, Edit, Write, Grep, Glob, Bash"
TOOLS_NO_EDIT = "Read, Grep, Glob, Bash"

#: What a role without the edit tools is told about the shell it still holds.
NO_EDIT_NOTE = (
    "You were not given `Edit` or `Write`, and that is deliberate: your value is that you did not "
    "produce what you are judging or pushing. You keep `Bash` because the work means running "
    "things. Bash can also write files, and nothing refuses that before it happens — a shell write "
    "is at best detected afterwards. So that half of the limit rests on you: do not use the shell "
    "to change the thing you were asked to judge, and if the task cannot be done without changing "
    "it, say so and stop."
)

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
        "Reads and RUNS — builds, tests, git status/diff/log, any inspection — and holds no Edit "
        "or Write tool. Bash can still write a file, and nothing refuses that in advance, so not "
        "changing anything is an instruction here, not an enforced limit. "
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

Read every path in `config/canonical-read-manifest.json`, in the order it lists them, before you
act — that file is the read order, and the only one. Report evidence, not assurances: what you
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


def render(name: str, description: str, tools: str, body: str) -> str:
    """One definition file.

    The description goes out as a double-quoted scalar. Plain, `builder.md` was not valid YAML:
    its description opens "Full working capability: reads, ..." and a `: ` inside a plain scalar
    starts a nested mapping (PyYAML: "mapping values are not allowed here, line 3, column 37").
    A JSON string is a YAML double-quoted scalar, so `json.dumps` is the quoting.
    """
    return HEADER.format(name=name, description=json.dumps(description, ensure_ascii=False),
                         tools=tools, body=body)


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

    This is a SECOND derivation: the enforced one is `engine/runtime/bro_authority.py`
    (`resolve_role_authority`). It stays here because this file also needs to say WHICH rule
    answered, which the engine does not return — and `test_generate_agent_definitions.py` holds
    the two to the same record for every pack and role, so they cannot drift apart unseen.
    """
    exact = override_for(authority, pack["id"], role)
    if exact is not None:
        return exact, "exact override"
    if pack.get("independent_verifier_required") is True and role == pack["roles"][-1]:
        return authority["designated_verifier"], "designated verifier (final declared role)"
    return authority["default"], "pack default"


def tools_for(record: dict) -> str:
    if record.get("can_release"):
        return TOOLS_NO_EDIT
    if record.get("can_verify") and not record.get("can_build"):
        return TOOLS_NO_EDIT
    return TOOLS_BUILD


def definition(pack: dict, role: str, record: dict, why: str) -> tuple[str, str]:
    name = f"{slug(pack['id'])}--{slug(role)}"
    modes = ", ".join(record.get("allowed_modes", []))
    can = ", ".join(
        label for label, key in (("build", "can_build"), ("verify", "can_verify"),
                                 ("release", "can_release")) if record.get(key)
    ) or "nothing (no authority declared)"
    # The role's own spelling, not `role.lower()`: this is the text the Task tool reads to pick
    # an agent, and lowercasing turned it into "needs a sre lead" and "needs a api architect".
    description = (
        f"{role} in the {pack['id']} pack. May {can}. "
        f"Use when the task is that pack's specialism and calls for the {role}."
    )
    tools = tools_for(record)
    no_edit = f"\n\n{NO_EDIT_NOTE}" if tools == TOOLS_NO_EDIT else ""
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
inside its scope, say so and stop; do not widen it yourself.{no_edit}

## How to work

Read every path in `config/canonical-read-manifest.json`, in the order it lists them, before you
act — that file is the read order, and the only one, and those documents are the law you operate
under. Report back evidence, not assurances: what you changed, what you ran, what it printed. If a
check cannot be made genuinely true, leave it failing and say so. Never weaken a check to make a
test pass, and never claim you ran something you did not.

You return your result to Bro, who is the conductor. You do not delegate further."""
    return name, render(name, description, tools, body)


def build() -> dict[str, str]:
    packs, authority = load()
    out: dict[str, str] = {}

    # The tiers first: they are what Bro chooses between when the work does not belong to a named
    # pack role, which is most conversational work.
    for tier, (tools, blurb) in TIERS.items():
        out[tier] = render(
            tier,
            f"{blurb} Bro picks the tier per task — grant the narrowest one that lets the "
            "job finish.",
            tools,
            TIER_BODY.format(tier=tier, blurb=blurb),
        )

    for pack in packs:
        for role in pack["roles"]:
            record, why = authority_for(authority, pack, role)
            name, text = definition(pack, role, record, why)
            if name in out:
                raise SystemExit(f"duplicate agent name {name!r} — the registry has a collision")
            out[name] = text
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the generated files match the registries; write nothing")
    args = ap.parse_args(argv)

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
