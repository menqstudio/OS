#!/usr/bin/env python3
"""Fail-closed CI gate: GitHub Action pins must be consistent and auditable.

**Why this exists (independent audit F-46).** `.github/workflows/release.yml` pinned
`actions/setup-node` to `0b93645e9fea7318ecaed2b359559ac225c90a2b` — which is
actions/setup-**python**'s v5.3.0 commit. That commit does not exist in the setup-node
repository, so GitHub could not resolve the action and EVERY `v*` tag push failed at that
step, before `npm ci`, before the bundle, before signing. No installer was ever produced by
that workflow. The trailing `# v4.1.0` comment is the human-auditable half of a SHA pin; when
a pin is copied between actions the comment names the wrong version and review value is lost.

Nothing in CI could catch it, because a pin is only wrong RELATIVE to other pins. This gate
encodes exactly that relation, with no network access:

  1. every third-party `uses:` is pinned to a 40-hex commit SHA (or is an explicitly declared
     exception below);
  2. every SHA-pinned action carries a trailing `# <version>` comment;
  3. one action → ONE (sha, version) pair across the whole repository;
  4. **one SHA → ONE action.** This is the rule that catches F-46: the moment a commit from
     `actions/setup-python` appears under `actions/setup-node`, the SHA is claimed by two
     different repositories and the gate goes RED.

Exit 0 = consistent. Exit 1 = a violation. No other outcome.
"""

from __future__ import annotations

import pathlib
import re
import sys
from collections import defaultdict

#: The workflows GitHub actually DISPATCHES (it reads only the repository root — audit F-22).
#: Rules 1–3 apply here: these are the pins that can break a real run.
DISPATCHED_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
)

#: Every workflow file in the tree, including the vendored subtree copies under
#: `apps/desktop/.github` and `engine/.github`. GitHub never runs those (F-22), and they carry
#: their own independently-consistent pin history, so holding them to the root's exact versions
#: would fail on a difference that harms nobody. Rule 4 — one commit belongs to one repository —
#: is a fact about git, not about versions, so it applies to ALL of them.
ALL_GLOBS = DISPATCHED_GLOBS + (
    "apps/desktop/.github/workflows/*.yml",
    "engine/.github/workflows/*.yml",
)

#: Actions that are NOT SHA-pinned, each with the reason it is exempt. An entry here is a
#: DECLARED exception, reviewable in the diff — never a silent one. Removing an entry must make
#: the gate fail, so an exception cannot quietly become the norm.
FLOATING_ALLOWED = {
    # Independent audit F-15: this step receives TAURI_SIGNING_PRIVATE_KEY and a contents:write
    # token while resolving a MUTABLE major tag. It is owner-gated (pinning it changes release
    # behaviour), so it is declared here rather than silently tolerated. Closing F-15 means
    # replacing the tag with a SHA and deleting this entry.
    "tauri-apps/tauri-action": "audit F-15, owner-gated: mutable @v0 tag on the signing step",
}

#: First-party reusable/local actions (`./path`) are not pinned and are not third-party.
_USES_RE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[^\s@#]+)@(?P<ref>[^\s#]+)\s*(?:#\s*(?P<comment>.*?))?\s*$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _iter_uses(root: pathlib.Path, globs=DISPATCHED_GLOBS):
    """Yield (file, lineno, action, ref, comment) for every `uses:` in the given workflows."""
    for glob in globs:
        for path in sorted(root.glob(glob)):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                yield (path, 0, None, None, f"unreadable: {exc}")
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = _USES_RE.match(line)
                if not m:
                    continue
                action = m.group("action")
                if action.startswith("./") or action.startswith("docker://"):
                    continue  # local / container action: not a third-party pin
                yield (
                    path.relative_to(root).as_posix(),
                    lineno,
                    action,
                    m.group("ref"),
                    (m.group("comment") or "").strip(),
                )


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    seen_any = False
    by_action: dict[str, set[tuple[str, str]]] = defaultdict(set)
    where: dict[tuple[str, str], list[str]] = defaultdict(list)

    # ---- rules 1–3, over the workflows GitHub actually dispatches ----
    for rel, lineno, action, ref, comment in _iter_uses(root, DISPATCHED_GLOBS):
        if action is None:
            problems.append(f"{rel}: {comment}")
            continue
        seen_any = True
        site = f"{rel}:{lineno}"
        if not _SHA_RE.match(ref):
            if action in FLOATING_ALLOWED:
                continue  # declared exception, reason recorded above
            problems.append(
                f"{site}: {action}@{ref} is not pinned to a 40-hex commit SHA "
                f"(add a SHA pin, or declare the exception in FLOATING_ALLOWED with a reason)"
            )
            continue
        if not comment:
            problems.append(
                f"{site}: {action}@{ref[:12]}… has no trailing `# <version>` comment — a SHA "
                f"with no version annotation cannot be reviewed"
            )
        by_action[action].add((ref, comment))
        where[(action, ref)].append(site)

    if not seen_any:
        # A gate that finds nothing to check must not print GREEN (audit F-16/F-19 class).
        problems.append(
            "no workflow `uses:` entries found — the gate verified nothing; check DISPATCHED_GLOBS"
        )

    for action, pins in sorted(by_action.items()):
        if len(pins) > 1:
            rendered = "; ".join(
                f"{ref[:12]}… ({comment or 'no comment'}) at {', '.join(where[(action, ref)])}"
                for ref, comment in sorted(pins)
            )
            problems.append(f"{action} is pinned inconsistently: {rendered}")

    # ---- rule 4 (the F-46 rule), over EVERY workflow file in the tree ----
    by_sha: dict[str, set[str]] = defaultdict(set)
    sha_sites: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rel, lineno, action, ref, _comment in _iter_uses(root, ALL_GLOBS):
        if action is None or not _SHA_RE.match(ref or ""):
            continue
        by_sha[ref].add(action)
        sha_sites[(action, ref)].append(f"{rel}:{lineno}")

    for sha, actions in sorted(by_sha.items()):
        if len(actions) > 1:
            sites = ", ".join(site for a in sorted(actions) for site in sha_sites[(a, sha)])
            problems.append(
                f"commit {sha[:12]}… is claimed by MORE THAN ONE action "
                f"({', '.join(sorted(actions))}) at {sites} — a commit exists in exactly one "
                f"repository, so at least one of these pins is unresolvable (this is audit F-46)"
            )

    return problems


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    problems = check(root)
    if problems:
        print("RED: GitHub Action pin gate failed")
        for p in problems:
            print(f"  - {p}")
        return 1
    actions = {a for _, _, a, _, _ in _iter_uses(root) if a}
    print(
        f"GREEN: action pins consistent ({len(actions)} distinct actions; one sha per action, "
        f"one action per sha; {len(FLOATING_ALLOWED)} declared floating-tag exception(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
