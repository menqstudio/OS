#!/usr/bin/env python3
"""M1 of the `contracts/` dedupe: bind the Rust mirrors to the schemas they claim to mirror.

`docs/design/CONTRACTS_DEDUPE_PLAN.md` establishes that this repository has **no duplicated schema
file** — the drift it actually carries is a Python-owned JSON Schema and a hand-written Rust struct
that must agree with it, **bound by nothing but a doc comment**:

    /// A verifier verdict receipt — the read shape of
    /// `engine/schemas/verifier-receipt.schema.json`.
    pub struct VerifierReceipt { … }

A comment is not a binding. Today the schema can gain a required field, or the struct can lose one,
and nothing notices until a real payload fails somewhere that is expensive to debug.

That is why the plan's first milestone is a GATE and not a file move: relocating the schemas would
re-file the Python side and leave every Rust mirror exactly as unbound as it is now. M1 needs no
file to move, and it is provable — delete a field from a schema and watch this go red.

WHAT IT CHECKS, and what it deliberately does not.

  * Every field the schema marks REQUIRED must exist on the Rust struct. That direction is the one
    that breaks reads: a required field the struct does not name is a fact the desktop silently
    drops.
  * Every field the struct names must exist in the schema, when the schema is
    `additionalProperties: false`. That direction catches a mirror inventing a field the engine
    will never send.
  * It does NOT compare types. The schemas here type most things as strings with patterns; the
    Rust side deliberately narrows some (`i64` for epochs, `Vec<String>` for id lists) and the
    narrowing is the point. A type check would either be vacuous or would fight the useful part.
  * It does NOT read `serde` renames beyond `rename_all = "snake_case"`/absent, which is what
    these structs use. A rename it cannot see is reported rather than assumed away.

Run:  python tools/check_schema_mirrors.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Each pair is a claim the code already makes in a doc comment, made checkable. Adding a mirror
#: here is how a new hand-written shape joins the gate; the reason field is not decoration — a
#: pair with no stated reason is a pair nobody can review.
MIRRORS = [
    {
        "schema": "engine/schemas/verifier-receipt.schema.json",
        "rust": "apps/desktop/src-tauri/src/governance.rs",
        "struct": "VerifierReceipt",
        "reason": "governance.rs parses verifier receipts read-only; the schema is the engine's.",
    },
    {
        "schema": "engine/schemas/evidence-event.schema.json",
        "rust": "apps/desktop/src-tauri/src/governance.rs",
        "struct": "EvidenceEvent",
        "reason": "the evidence chain the security page renders; a dropped field is a dropped fact.",
    },
]


def schema_fields(path: pathlib.Path) -> tuple[set[str], set[str], bool, set[str]]:
    """(required, all properties, closed?, discriminators) — pure/testable.

    A property declared with `const` is a DISCRIMINATOR, not data: `schema: {const: 1}` and
    `artifact_type: {const: "verifier-receipt"}` say what this object IS. Carrying a constant into
    a parsed struct adds nothing — the useful act is to CHECK it and drop it, which is exactly what
    `governance.rs` does on the raw value before building the struct.

    The first version of this gate did not know that and reported both mirrors as broken for
    omitting `schema`. That was wrong, and fixing it made the rule stronger rather than weaker: a
    discriminator now has to be **validated somewhere in the Rust source**, and a discriminator
    that is neither carried nor checked is a finding the loose version would have missed.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    properties = doc.get("properties") or {}
    props = set(properties.keys())
    discriminators = {k for k, v in properties.items() if isinstance(v, dict) and "const" in v}
    return set(doc.get("required") or []), props, doc.get("additionalProperties") is False, discriminators


def rust_struct_fields(source: str, name: str) -> set[str] | None:
    """The field names of `pub struct <name>`, or None when it is not in this source.

    Deliberately literal: it reads the declaration, not a macro-expanded view. A struct built by a
    macro would return the wrong answer confidently, so the caller reports "not found" rather than
    guessing — see `main`.
    """
    # `\n\s*\}` rather than `\n\}`: a struct is not always at column 0 (a test fixture, a module
    # body), and a regex that only matched the top-level layout would report "not found" — which
    # this gate escalates to a failure — for a struct that is simply indented.
    m = re.search(r"pub struct %s\s*\{(.*?)\n\s*\}" % re.escape(name), source, re.S)
    if not m:
        return None
    body = re.sub(r"//[^\n]*", "", m.group(1))          # strip line comments
    body = re.sub(r"#\[[^\]]*\]", "", body)             # strip attributes
    return set(re.findall(r"\bpub\s+([a-z_][a-z0-9_]*)\s*:", body))


def validates(source: str, field: str) -> bool:
    """Does the Rust source COMPARE this field's raw value anywhere? Pure/testable.

    Deliberately shallow: it looks for the field name quoted next to a `get(...)`, which is how a
    raw-value discriminator check is written here. It cannot prove the comparison is the RIGHT one
    — that is what the surrounding unit tests are for — but it can prove the field was not simply
    forgotten, which is the failure this gate exists to catch.
    """
    return re.search(r'get\(\s*"%s"\s*\)' % re.escape(field), source) is not None


def compare(name: str, required: set[str], props: set[str], closed: bool,
            discriminators: set[str], fields: set[str], source: str) -> list[str]:
    """The three directions that matter. Pure/testable."""
    failures = []
    for field in sorted(required - fields):
        if field in discriminators:
            # A constant may be checked and dropped — but it must be CHECKED.
            if not validates(source, field):
                failures.append(
                    f"{name}: `{field}` is a schema discriminator (declared `const`) that the Rust "
                    f"struct does not carry AND the source never compares. A discriminator that is "
                    f"neither kept nor checked means this shape is parsed on the strength of its "
                    f"other fields alone — anything with the same field names would be accepted.")
            continue
        failures.append(
            f"{name}: the schema REQUIRES `{field}` and the Rust struct does not name it — a "
            f"required field the mirror drops is a fact the desktop silently loses.")
    if closed:
        invented = sorted(fields - props)
        if invented:
            failures.append(
                f"{name}: the Rust struct names {', '.join(invented)}, which the schema does not "
                f"define and (additionalProperties: false) forbids — the engine will never send "
                f"{'these' if len(invented) > 1 else 'this'}")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    failures: list[str] = []
    checked = 0
    for mirror in MIRRORS:
        schema_path = root / mirror["schema"]
        rust_path = root / mirror["rust"]
        if not schema_path.exists():
            failures.append(f"{mirror['struct']}: schema {mirror['schema']} does not exist")
            continue
        if not rust_path.exists():
            failures.append(f"{mirror['struct']}: {mirror['rust']} does not exist")
            continue
        required, props, closed, discriminators = schema_fields(schema_path)
        source = rust_path.read_text(encoding="utf-8")
        fields = rust_struct_fields(source, mirror["struct"])
        if fields is None:
            # Fail closed: a mirror that cannot be found is a mirror that cannot be checked, and
            # silently skipping it would make this gate weakest exactly where a rename happened.
            failures.append(
                f"{mirror['struct']}: not found as a `pub struct` in {mirror['rust']} — renamed, "
                f"moved, or macro-generated. Update the MIRRORS table; do not leave it unchecked.")
            continue
        checked += 1
        failures += compare(mirror["struct"], required, props, closed, discriminators,
                            fields, source)

    if failures:
        print("RED: a Rust mirror disagrees with the schema it claims to mirror —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s). The doc comment is the claim; this is the check.",
              file=sys.stderr)
        return 1
    print(f"GREEN: {checked} Rust mirror(s) agree with their engine schemas on every required and "
          f"permitted field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
