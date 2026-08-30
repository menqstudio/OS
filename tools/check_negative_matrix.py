#!/usr/bin/env python3
"""Every ID in the security negative-test matrix must say, truthfully, what establishes it.

**Why this gate exists.** `docs/design/SECURITY_NEGATIVE_TEST_MATRIX.md` enumerates 242
negative tests across 20 domains -- replay, time, registry, scope, frames, crash, concurrency,
output, evidence fork, filesystem, ACL, IPC, signer-oracle, TCB, capability, terminal refusal,
cross-binding, parity -- and states for each one the single fault to inject and the exact
fail-closed refusal that must come back. It is the Architect's required negative matrix.

At the head this gate landed on, **exactly one** of those 242 IDs appeared anywhere in the
tree's `.rs`, `.py` or `.ts` sources: `NM-XBIND-10`, in a docstring in
`engine/runtime/isolated_signer.py` whose own words are "This signer raises NEITHER". So the
document was 242 obligations and 0 bindings, and nothing could tell a reader which rows were
proven, which were impossible, and which nobody had looked at.

That is the defect shape this repository already gates against one level down.
`check_spec_references.py` exists because a `section` reference in a comment reads to a
reviewer as a statement that the section holds, and in this repository that was often false.
A test-matrix row is the same claim with more authority: it reads as *we test this*.

So a matrix row is now a CLAIM the build checks:

  * the ID set in the markdown and in `config/negative-matrix.json` must be IDENTICAL --
    neither file may carry a row the other does not;
  * a row declared `implemented` must NAME a test, that test must EXIST in the tree, and its
    body must carry the ID as a string -- so the binding is visible at the test, not only in
    a JSON file a reader will not open;
  * a row declared `blocked` must say what it is blocked ON. "Blocked" with no cause is
    indistinguishable from "not done";
  * a row declared `unreviewed` must be in `unreviewed_baseline`. Existing rows start there,
    which is honest -- nobody has checked them -- and a NEW markdown row therefore FAILS this
    gate until someone either establishes it or adds it to the baseline in a visible diff.

The last rule is the load-bearing one, and it is the same one `check_spec_references.py` uses:
the debt is frozen where it was found and cannot grow silently while it is paid down.

**What this gate does NOT prove.** It does not run the tests -- CI does that -- and it cannot
tell a test that genuinely fails when its control is removed from one that passes against a
gutted implementation. That is the repository's "a green test is not a passing check" rule and
no static check can discharge it; every row marked `implemented` here was mutation-verified by
hand instead, and the mutation is recorded beside it.

stdlib only, no network. Run: `python tools/check_negative_matrix.py [--root DIR]`
Exit 0 + "GREEN: ..." when every row is honest; exit 1 + the specific problems otherwise.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import generate_negative_matrix as generator  # noqa: E402

MATRIX = pathlib.Path("docs/design/SECURITY_NEGATIVE_TEST_MATRIX.md")
MIRROR = pathlib.Path("config/negative-matrix.json")

VALID_STATUSES = {"implemented", "blocked", "unreviewed"}

#: A test reference is `<path-from-repo-root>::<symbol>[::<symbol>...]`, e.g.
#: `engine/tests/test_negative_matrix.py::RegistryTests::test_nm_reg_04_unknown_root`.
#: File-plus-symbol rather than a language's own dotted module path, because the gate has to
#: LOCATE the function to read its body, and mapping `crate::module::tests::fn` back to a file
#: means re-implementing two module systems and guessing when they disagree.
TEST_REF = re.compile(r"^(?P<path>[A-Za-z0-9_./-]+\.(?:py|rs|ts|tsx))::(?P<symbols>[A-Za-z0-9_:]+)$")


def _python_body(text: str, name: str) -> str | None:
    """The source of `def <name>` including its decorators' block, by indentation."""
    pattern = re.compile(r"(?m)^(?P<indent>[ \t]*)(?:async\s+)?def\s+" + re.escape(name) + r"\s*\(")
    match = pattern.search(text)
    if not match:
        return None
    lines = text[match.start():].splitlines()
    indent = len(match.group("indent"))
    body = [lines[0]]
    for line in lines[1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def _braced_body(text: str, name: str) -> str | None:
    """The source of `fn <name>` / `function <name>` / `it("<name>")`, by brace matching."""
    pattern = re.compile(
        r"(?m)^[ \t]*(?:pub\s+)?(?:async\s+)?(?:fn|function)\s+" + re.escape(name) + r"\s*[(<]"
    )
    match = pattern.search(text)
    if not match:
        return None
    start = text.index("{", match.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    return None


def test_body(root: pathlib.Path, reference: str) -> tuple[str | None, str | None]:
    """(body, problem). The body of the LAST symbol in the reference, or why it was not found."""
    match = TEST_REF.match(reference)
    if not match:
        return None, (
            f"test reference {reference!r} is not `<path>::<symbol>` with a .py/.rs/.ts/.tsx path"
        )
    path = root / match.group("path")
    if not path.is_file():
        return None, f"names {match.group('path')}, which is not a file in the tree"
    text = path.read_text(encoding="utf-8", errors="replace")
    name = match.group("symbols").split("::")[-1]
    body = _python_body(text, name) if path.suffix == ".py" else _braced_body(text, name)
    if body is None:
        return None, f"names {name}, which is not defined in {match.group('path')}"
    return body, None


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []

    try:
        declared = generator.parse((root / MATRIX).read_text(encoding="utf-8"))
    except (OSError, generator.ParseError) as exc:
        return [f"cannot read the matrix: {exc}"]
    try:
        mirror = json.loads((root / MIRROR).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {MIRROR.as_posix()}: {exc}"]

    cases = mirror.get("cases")
    if not isinstance(cases, dict):
        return [f"{MIRROR.as_posix()} has no `cases` object"]
    baseline = mirror.get("unreviewed_baseline")
    if not isinstance(baseline, list):
        return [f"{MIRROR.as_posix()} has no `unreviewed_baseline` array"]
    baseline_set = set(baseline)

    # 1) The two ID sets must be identical, in both directions.
    for missing in sorted(set(declared) - set(cases)):
        problems.append(f"{missing}: declared in the matrix, missing from {MIRROR.as_posix()}")
    for extra in sorted(set(cases) - set(declared)):
        problems.append(f"{extra}: in {MIRROR.as_posix()}, declared by no matrix row")

    for stale in sorted(baseline_set - set(cases)):
        problems.append(f"{stale}: in unreviewed_baseline but is not a case (stale baseline)")

    counts = {"implemented": 0, "blocked": 0, "unreviewed": 0}
    for case_id in sorted(set(cases) & set(declared)):
        entry = cases[case_id]
        status = entry.get("status")
        if status not in VALID_STATUSES:
            problems.append(
                f"{case_id}: invalid status {status!r} (want one of {sorted(VALID_STATUSES)})"
            )
            continue
        counts[status] += 1

        if status == "implemented":
            # 2) The named test must exist, and 3) its body must carry the ID.
            reference = entry.get("test")
            if not isinstance(reference, str) or not reference.strip():
                problems.append(f"{case_id}: status 'implemented' with no `test`")
                continue
            body, problem = test_body(root, reference)
            if problem:
                problems.append(f"{case_id}: status 'implemented' but its test {problem}")
                continue
            if case_id not in body:
                problems.append(
                    f"{case_id}: its test {reference} does not carry the string "
                    f"{case_id!r} in its body, so nothing at the test binds it to this row"
                )
            if case_id.lower().replace("-", "_") not in reference.lower():
                problems.append(
                    f"{case_id}: its test name {reference} does not contain the ID, so the "
                    f"binding is not visible in a test-runner's output"
                )

        elif status == "blocked":
            # 4) Blocked must name a cause.
            blocked_on = entry.get("blocked_on")
            if not isinstance(blocked_on, str) or not blocked_on.strip():
                problems.append(
                    f"{case_id}: status 'blocked' with no `blocked_on`. 'Blocked' with no cause "
                    f"is indistinguishable from 'not done'"
                )

        else:
            # 5) New debt is refused; frozen debt is not.
            if case_id not in baseline_set:
                problems.append(
                    f"{case_id}: status 'unreviewed' but it is NOT in unreviewed_baseline. A new "
                    f"matrix row may not arrive as silent debt -- establish it, mark it blocked "
                    f"with a cause, or add it to the baseline in a reviewed diff"
                )
            if not str(entry.get("reason", "")).strip():
                problems.append(f"{case_id}: status 'unreviewed' with no `reason`")

    # A baseline that outgrew the rows it froze is debt growth wearing the freeze's clothes.
    unreviewed_now = {i for i, c in cases.items() if c.get("status") == "unreviewed"}
    grown = sorted(baseline_set - unreviewed_now)
    if grown:
        problems.append(
            f"unreviewed_baseline lists {len(grown)} ID(s) that are no longer unreviewed "
            f"({grown[:5]}{'...' if len(grown) > 5 else ''}). Remove them: a baseline that "
            f"keeps paid-down entries leaves room for new debt to be added without a diff"
        )

    if not problems:
        check.counts = counts  # type: ignore[attr-defined]
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = pathlib.Path(args.root)

    problems = check(root)
    if problems:
        print("RED: the negative-test matrix and its mirror disagree --", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). The matrix is normative; regenerate the mirror with "
            f"`python tools/generate_negative_matrix.py` and then make each row honest. "
            f"See {MIRROR.as_posix()}.",
            file=sys.stderr,
        )
        return 1

    counts = getattr(check, "counts", {})
    total = sum(counts.values())
    print(
        f"GREEN: {total} matrix cases, all bound -- {counts.get('implemented', 0)} implemented "
        f"(test exists and carries its ID), {counts.get('blocked', 0)} blocked (each naming what "
        f"must exist first), {counts.get('unreviewed', 0)} unreviewed and frozen in the baseline. "
        f"No new debt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
