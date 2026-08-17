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
        # The function that turns raw JSON into this struct. Discriminator checks are looked for
        # INSIDE it and nowhere else — see `validates()`.
        "parser": "parse_verifier_receipt",
        # A test that feeds a WRONG discriminator and asserts refusal. Required, not optional.
        "negative_test": "rejects_bad_schema_version",
    },
    {
        "schema": "engine/schemas/evidence-event.schema.json",
        "rust": "apps/desktop/src-tauri/src/governance.rs",
        "struct": "EvidenceEvent",
        "reason": "the evidence chain the security page renders; a dropped field is a dropped fact.",
        "parser": "parse_evidence_event",
        # Added 2026-08-17. Before that there was no such test — which is how the auditor deleted
        # this parser's discriminator check and got 29 passed and a GREEN gate.
        "negative_test": "rejects_bad_evidence_schema_version",
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


def strip_comments(source: str) -> str:
    """Blank out `//` line comments and `/* */` blocks, keeping offsets stable. Pure/testable."""
    source = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def strip_test_modules(source: str) -> str:
    """Remove `#[cfg(test)] mod … { … }` bodies. Pure/testable.

    Brace-counted rather than regex-matched, because a test module contains braces and a lazy
    regex would stop at the first `}`. A test that mentions a check is not a check.
    """
    out, i = [], 0
    for m in re.finditer(r"#\[cfg\(test\)\]", source):
        start = source.find("{", m.end())
        if start == -1:
            continue
        depth, j = 0, start
        while j < len(source):
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(source[i:m.start()])
        i = j + 1
    out.append(source[i:])
    return "".join(out)


def function_body(source: str, name: str) -> str | None:
    """The body of `fn <name>`, brace-counted. Pure/testable. None when it is not there."""
    m = re.search(r"\bfn\s+%s\s*(?:<[^>]*>)?\s*\(" % re.escape(name), source)
    if not m:
        return None
    start = source.find("{", m.end())
    if start == -1:
        return None
    depth, j = 0, start
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
        j += 1
    return None


def validates(source: str, field: str, parser: str | None = None) -> bool:
    """Does the PARSER for this struct compare the field's raw value? Pure/testable.

    **This function is the sixth independent audit's `A-02`, and this docstring used to overstate
    it.** It said the fix *"made the rule stronger rather than weaker: a discriminator now has to
    be validated somewhere in the Rust source."* What it required was the SUBSTRING
    `get("schema")`, anywhere in the file — comments and `#[cfg(test)]` included — while both
    `MIRRORS` entries named the same file. The auditor measured five mutations that all left the
    gate GREEN, including deleting `parse_evidence_event`'s comparison outright while the
    receipt's own check kept the substring alive.

    Three changes, and the honest limit of each:

      * **Scoped to the parser.** The search now runs inside `fn <parser>`'s own body, so one
        struct's check can no longer stand in for another's. Kills mutation 1.
      * **Comments and test modules stripped first.** A comment saying the word, or a mention
        inside `#[cfg(test)]`, is not a check. Kills mutations 3 and 4.
      * **A negative test is required** (see `main`). That is the half a static reader cannot do:
        a comparison replaced by `false`, or inverted so every version is accepted, still contains
        the substring and still sits in the right function. Only running it catches those, so the
        gate requires the test to EXIST and `cargo` proves it passes.

    So: this gate proves the check is in the right place; the negative test proves it is right.
    Neither claim is made for the other, which is where the previous version went wrong.
    """
    hay = strip_test_modules(strip_comments(source))
    if parser:
        body = function_body(hay, parser)
        if body is None:
            return False
        hay = body
    return re.search(r'get\(\s*"%s"\s*\)' % re.escape(field), hay) is not None


def has_negative_test(source: str, name: str) -> bool:
    """Is there a `#[test] fn <name>` in this source? Pure/testable.

    Existence only. Whether it asserts the right thing is what running it establishes — and it IS
    run: `cargo test -p brops --lib` is a required job. The gate's job is to make sure a mirror
    cannot be added without one, because the mirror that had no negative test is exactly the one
    whose discriminator check could be deleted with 29 tests still passing.
    """
    return function_body(source, name) is not None


def compare(name: str, required: set[str], props: set[str], closed: bool,
            discriminators: set[str], fields: set[str], source: str,
            parser: str | None = None) -> list[str]:
    """The three directions that matter. Pure/testable."""
    failures = []
    for field in sorted(required - fields):
        if field in discriminators:
            # A constant may be checked and dropped — but it must be CHECKED, in THIS struct's
            # own parser. See validates(): file-wide was A-02.
            if not validates(source, field, parser):
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
                            fields, source, mirror.get("parser"))

        # The half a static reader cannot do (A-02). A comparison replaced by `false`, or inverted
        # so every version is accepted, still contains the substring and still sits in the right
        # function; only RUNNING a wrong-discriminator case catches those. So the table must name
        # such a test and it must exist — `cargo test -p brops --lib` is what then proves it.
        negative = mirror.get("negative_test")
        if not negative:
            failures.append(
                f"{mirror['struct']}: the MIRRORS table declares no `negative_test`. A mirror "
                f"without one is the state EvidenceEvent was in when its discriminator check was "
                f"deleted with 29 tests still passing and this gate GREEN.")
        elif not has_negative_test(source, negative):
            failures.append(
                f"{mirror['struct']}: declares negative test `{negative}`, which does not exist "
                f"in {mirror['rust']}. Renamed or removed — restore it or update the table; do "
                f"not leave the discriminator provable only by substring.")
        if not mirror.get("parser"):
            failures.append(
                f"{mirror['struct']}: the MIRRORS table declares no `parser`, so a discriminator "
                f"check would be searched for file-wide again — which is A-02 exactly.")

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
