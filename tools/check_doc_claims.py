"""Every checkable claim in a canonical document must be checkable, and true.

Every defect found while cutting the read set down had one shape: **something was written
down, and nothing checked that it was true.** Not one of them was carelessness — each was
written by someone honest at a moment when it was correct, and then the world moved.

  * `START_HERE.md` named `main` at a head **seven merges** stale. Its own text says so:
    "Nothing checks it."
  * `CLAUDE.md` said the engine suite was 1282 tests. It is 2002.
  * Five canonical documents said this was a Windows box and that `cargo` needed
    PowerShell. It is a Debian box and `cargo` runs from an ordinary shell.
  * `CLAUDE.md`'s Armenian half said the second audit left **122** findings beside a
    breakdown summing to 45.
  * The ledger cited a fifth-round audit report **that was never written to the
    directory**, and the eighth round found the same defect had recurred for the seventh.
  * The commit trailer said `Opus 4.8` while Opus 5 wrote the commits, and the roadmap
    still said it after `CLAUDE.md` was corrected.

Those were found one at a time, by reading. That does not scale, and the next one is
already being written. So the class gets a gate rather than the instances getting fixes:

  1. **Every repository path a canonical document references must exist.** This is what
     catches a citation to a file nobody filed — `A-06`, twice.
  2. **Every commit-shaped hex string must resolve to a real commit.** This is what catches
     a head that has gone stale, invented or rebased away.
  3. **Every ticket id must exist where tickets live.** A `T-nnn` in prose and not in
     `TASKS.md` or the archive is a pointer to nothing.
  4. **Every toolchain version claim must match the machine.** This is what catches
     "cargo 1.96" on a box running 1.97.1.

What this deliberately does NOT do: judge prose. It cannot tell whether a sentence
describing a design is still true — only a reader can. It checks the claims that have a
machine-checkable referent, which is the class that produced every defect above.

Stdlib plus `git`. Offline. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_REL = "config/canonical-read-manifest.json"

# A markdown link target that looks like a repository path: not a URL, not an anchor.
LINK = re.compile(r"\]\(\s*(?!https?:|mailto:|#)([^)\s]+)")
# Inline code that looks like a path: a slash and a file extension. The extension must be
# a known source/text one — `brops.sign-request/result.v1` is a protocol name, and a rule
# loose enough to call it a path is a rule that gets switched off.
SOURCE_EXT = ("py","rs","ts","tsx","js","json","md","yml","yaml","toml","sql","css","html","sh","ico")
INLINE_PATH = re.compile(
    r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_.-]+\.(?:" + "|".join(SOURCE_EXT) + r"))`")
# 7-40 hex in backticks — the shape a commit is always written in here.
SHA = re.compile(r"`([0-9a-f]{7,40})`")
TICKET = re.compile(r"`?\b([TOAIHBFG]-\d{2,3})\b`?")
# "cargo 1.97.1", "node 20.20.2", "npm 10.8.2"
VERSION = re.compile(r"\b(cargo|node|npm|python3?)\s+v?(\d+\.\d+(?:\.\d+)?)\b", re.I)

# Hex words that are not commits. Kept explicit and short: a broad rule here would
# silently exempt the very thing this checks.
NOT_A_SHA = {"deadbee", "abcdefa", "1234567", "0000000", "fffffff", "accepted", "deface"}

# Commit ids from menqstudio/BroPS BEFORE the subtree import. They do not resolve here and
# never will; they are the historical record of which design revision an Architect reviewed.
# Listed BY NAME, never by a rule that would exempt a whole class -- a broad exemption here
# would hand back exactly the guarantee this gate provides, and the ledger has been bitten by
# a prefix rule before.
PRE_IMPORT_SHAS = {"6a6882e", "fa1b8cb", "5be8d95"}


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return 1, ""


def installed_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for tool, args, pat in (
        ("cargo", ["cargo", "--version"], r"cargo (\d+\.\d+\.\d+)"),
        ("node", ["node", "-v"], r"v?(\d+\.\d+\.\d+)"),
        ("npm", ["npm", "-v"], r"(\d+\.\d+\.\d+)"),
    ):
        if not shutil.which(args[0]):
            continue
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        except Exception:  # noqa: BLE001
            continue
        m = re.search(pat, (r.stdout or "") + (r.stderr or ""))
        if m:
            out[tool] = m.group(1)
    return out


def known_tickets() -> set[str]:
    ids: set[str] = set()
    for rel in ("TASKS.md", "apps/desktop/AUDIT/AUDIT_LEDGER.md",
                "apps/desktop/AUDIT/AUDIT_LEDGER_ARCHIVE.md",
                "docs/archive/TASKS_ARCHIVE_2026-08.md",
                "docs/PHASE_10_PRODUCTION_ITEMS.md", "docs/OWNER_ACTION_REQUIRED.md"):
        path = ROOT / rel
        if path.is_file():
            ids |= set(TICKET.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return ids


def main(root: pathlib.Path = ROOT) -> int:
    try:
        paths = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))["paths"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"RED: cannot read {MANIFEST_REL}: {exc}")
        return 1

    tickets = known_tickets()
    versions = installed_versions()
    problems: list[str] = []
    checked = {"paths": 0, "shas": 0, "tickets": 0, "versions": 0}

    for rel in paths:
        doc = root / rel
        if not doc.is_file():
            problems.append(f"{rel}: in the read manifest and not on disk")
            continue
        text = doc.read_text(encoding="utf-8", errors="ignore")

        # 1 — referenced repository paths exist.
        for raw in set(LINK.findall(text)) | set(INLINE_PATH.findall(text)):
            target = raw.split("#", 1)[0].strip()
            if not target or target.startswith(("http", "mailto")):
                continue
            # `lstrip("./")` strips CHARACTERS, not a prefix, so `.claude/x` became
            # `claude/x` and every reference to a dotfile directory was a false RED. Found
            # by this gate's own first run, on the file that documents this gate.
            # "`x.rs` (deleted 2026-08-10)" is a document being accurate about a file that
            # no longer exists. Requiring the word immediately after the path keeps this from
            # becoming a way to cite anything at all.
            if re.search(re.escape("`" + raw + "` (deleted"), text):
                continue
            clean = target[2:] if target.startswith("./") else target
            candidates = [doc.parent / clean, root / clean]
            # Documents legitimately cite a path relative to the subtree they describe
            # (`broker/src/main.rs` under apps/desktop/src-tauri/). Accept a unique
            # suffix match, and only a unique one: two matches is an ambiguous citation.
            checked["paths"] += 1
            if not any(c.exists() for c in candidates):
                hits = [q for q in root.rglob("*" + pathlib.Path(clean).name)
                        if q.is_file() and q.as_posix().endswith("/" + clean)
                        and ".git/" not in q.as_posix() and "node_modules" not in q.as_posix()]
                if len(hits) == 1:
                    continue
            if not any(c.exists() for c in candidates):
                problems.append(
                    f"{rel}: references `{target}`, which does not exist. A citation to a "
                    f"file nobody filed is how `A-06` happened — twice")

        # 2 — commit-shaped strings resolve.
        for sha in set(SHA.findall(text)):
            if sha in NOT_A_SHA or sha in PRE_IMPORT_SHAS or not re.fullmatch(r"[0-9a-f]{7,40}", sha):
                continue
            if len(sha) == 7 and not re.search(r"[a-f]", sha):
                continue  # a bare 7-digit number is not a commit
            checked["shas"] += 1
            code, _ = git("cat-file", "-e", sha)
            if code != 0:
                problems.append(
                    f"{rel}: names `{sha}`, which is not an object in this repository. "
                    f"START_HERE.md sat seven merges behind on exactly this")

        # 3 — ticket ids exist somewhere tickets live.
        for tid in set(TICKET.findall(text)):
            checked["tickets"] += 1
            if tid not in tickets:
                problems.append(
                    f"{rel}: names `{tid}`, which is in no task board, ledger or archive")

        # 4 — toolchain claims match the machine.
        for tool, claimed in set(VERSION.findall(text)):
            tool = tool.lower().rstrip("3")
            actual = versions.get(tool)
            if not actual:
                continue
            checked["versions"] += 1
            if not actual.startswith(claimed) and not claimed.startswith(actual.split(".")[0]):
                problems.append(
                    f"{rel}: claims {tool} {claimed}; this machine has {actual}. Five "
                    f"canonical documents said PowerShell-only cargo on a Debian box")

    if problems:
        print("RED: canonical documents make claims that are not true\n")
        for p in sorted(set(problems)):
            print(f"  - {p}")
        print("\nEach of these is checkable, so none of them has to be found by reading.")
        return 1

    print("GREEN: canonical claims check out; "
          + ", ".join(f"{v} {k}" for k, v in checked.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
