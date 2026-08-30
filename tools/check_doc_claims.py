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
  4. **Every toolchain version claim must match `config/toolchain.json`**, which records the
     DEVELOPMENT machine, and that file must match the real machine wherever a real one is
     present. This is what catches "cargo 1.96" on a box running 1.97.1.

     It compared the documents straight against `platform.node()`'s machine until
     2026-08-30 -- and it runs in CI, where the machine is a GitHub runner carrying a
     different node. So it reported four canonical files as making an untrue claim about
     node when all four were CORRECT about the box they describe, and it could not have
     been green in CI and on the box at the same time. Two different machines were being
     compared through one number. The claim gets one source of record instead: the
     documents are checked against the file everywhere, and the file is checked against the
     machine only where a development machine is what is running it. In CI that half prints
     SKIPPED and says why -- "I could not check" and "it is fine" are different answers.

What this deliberately does NOT do: judge prose. It cannot tell whether a sentence
describing a design is still true — only a reader can. It checks the claims that have a
machine-checkable referent, which is the class that produced every defect above.

Stdlib plus `git`. Offline. Exit 0 GREEN, 1 RED.
"""
from __future__ import annotations

import json
import os
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
#: The same claim without backticks, for the canonical JSON. `config/current_state.json` is in
#: the read manifest and this gate has always read it -- but every commit id in it is written
#: as plain text inside a JSON string, and the backticked pattern above could not see one.
#: `38d5d71504ba68b70b015b958cb09109c80e595a` sat in `design_gate.candidate_head_note` naming a
#: branch head that a squash merge had erased, invisible to a gate that was reading the file it
#: was written in.
#:
#: Applied to `.json` only, deliberately: in prose, a bare hex word is as likely to be an
#: example, a digest or an id, and the backtick is the author saying "this is a commit". In the
#: machine mirror there is no such convention to lean on.
BARE_SHA = re.compile(r"(?<![0-9a-zA-Z_/-])([0-9a-f]{7,40})(?![0-9a-zA-Z_/-])")
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

# Versions a canonical document QUOTES in order to say it was wrong. `CLAUDE.md` and the
# roadmap both carry "*(The documents said cargo 1.96 ...)*" beside the corrected number,
# which is the record of the correction and worth keeping -- but it is version-shaped, so a
# gate reading shapes cannot tell it from a claim.
#
# Listed as (file, tool, version) triples, BY NAME, exactly like PRE_IMPORT_SHAS and for the
# same reason: a rule general enough to recognise a quotation -- "a version after the word
# said" -- would hand back the guarantee this check provides, and every stale number in the
# repository is one sentence away from qualifying. Three named exceptions can be read; a
# heuristic cannot be audited. If one of these lines is ever rewritten, its entry goes RED as
# an unused exemption is not caught here -- the entry simply stops matching and the quotation
# is checked as a claim, which is the safe direction to fail.
QUOTED_STALE_VERSIONS = {
    ("CLAUDE.md", "cargo", "1.96"),
    ("MASTER_EXECUTION_ROADMAP.md", "cargo", "1.96"),
}


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args],
                           capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return 1, ""


TOOLCHAIN_REL = "config/toolchain.json"


def declared_versions(root: pathlib.Path) -> tuple[dict[str, str], str | None]:
    """The development machine's toolchain as recorded, plus a problem string if unusable.

    Fail-closed: an unreadable or malformed record is RED, not an empty dict that quietly
    checks nothing. A gate that skips when its input is missing is a gate that passes on the
    day the input goes missing.
    """
    path = root / TOOLCHAIN_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"{TOOLCHAIN_REL}: unreadable, so no version claim can be checked ({exc})"
    versions = data.get("versions")
    if not isinstance(versions, dict) or not versions:
        return {}, f"{TOOLCHAIN_REL}: carries no `versions` object"
    out: dict[str, str] = {}
    for tool, value in versions.items():
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
            return {}, f"{TOOLCHAIN_REL}: {tool} version {value!r} is not an x.y.z version"
        out[tool.lower()] = value
    return out, None


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


def _version_prefix(claimed: str, actual: str) -> bool:
    """Is `claimed` the same version as `actual`, allowing a document to name fewer parts?

    Compared COMPONENT-WISE. The first rule here was

        actual.startswith(claimed) or claimed.startswith(actual.split(".")[0])

    and the second half of it made the whole check a formality: with `actual` = `1.97.1`,
    every claim beginning `1` passed — `cargo 1.96`, the exact string this gate was written
    to catch, among them. It only ever fired on `node` because 20 and 22 differ in the major.
    A check that passes the case it was written for is not a check; it was found by its own
    first test, which is what tests are for.
    """
    want = claimed.split(".")
    have = actual.split(".")
    return len(want) <= len(have) and have[:len(want)] == want


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
    versions, toolchain_problem = declared_versions(root)
    problems: list[str] = [] if toolchain_problem is None else [toolchain_problem]
    checked = {"paths": 0, "shas": 0, "tickets": 0, "versions": 0}

    # The record against the machine — only where the machine is the one the record is about.
    in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    machine_note = ("SKIPPED: config/toolchain.json describes the development box and this is a "
                    "CI runner, which is a different machine; the documents are still checked "
                    "against the file")
    if versions and not in_ci:
        installed = installed_versions()
        compared = 0
        for tool, declared in sorted(versions.items()):
            actual = installed.get(tool)
            if not actual:
                continue
            compared += 1
            if actual != declared:
                problems.append(
                    f"{TOOLCHAIN_REL}: records {tool} {declared}; this machine has {actual}. "
                    f"The direction is machine -> this file -> documents, so update the file "
                    f"and every document that repeats the number, in one commit")
        machine_note = f"config/toolchain.json agrees with this machine on {compared} tool(s)"

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
            #
            # `.claude/worktrees/` is excluded for the same reason as `.git/`: the Agent tool
            # checks a whole second copy of this repository out there so a subagent cannot
            # collide with the session, and that copy made EVERY subtree-relative citation
            # ambiguous. This gate went RED on a clean tree with five such findings while CI,
            # which has no worktree, was green -- a verdict that depended on the machine, not
            # the code, which is the failure T-045 fixed in this same file once already.
            checked["paths"] += 1
            if not any(c.exists() for c in candidates):
                # Every exclusion is matched on the path RELATIVE to `root`, never the
                # absolute one. With `q.as_posix()` the gate was GREEN in CI and RED for any
                # agent whose checkout IS a worktree: `root` itself contained
                # `/.claude/worktrees/`, so EVERY candidate matched the exclusion, `hits` was
                # empty, and the same five citations were reported as files that do not exist.
                # That is the machine-dependent verdict this exclusion was added to prevent,
                # arriving from the other side -- and it is the same character-vs-path defect
                # family as `lstrip("./")` (T-053).
                hits = []
                for q in root.rglob("*" + pathlib.Path(clean).name):
                    if not q.is_file():
                        continue
                    rel_q = q.relative_to(root).as_posix()
                    if not rel_q.endswith("/" + clean) and rel_q != clean:
                        continue
                    if rel_q.startswith(".git/") or "/.git/" in rel_q:
                        continue
                    if "node_modules" in rel_q:
                        continue
                    if rel_q.startswith(".claude/worktrees/"):
                        continue
                    hits.append(q)
                if len(hits) == 1:
                    continue
            if not any(c.exists() for c in candidates):
                problems.append(
                    f"{rel}: references `{target}`, which does not exist. A citation to a "
                    f"file nobody filed is how `A-06` happened — twice")

        # 2 — commit-shaped strings resolve.
        found_shas = set(SHA.findall(text))
        if rel.endswith(".json"):
            found_shas |= set(BARE_SHA.findall(text))
        for sha in found_shas:
            if sha in NOT_A_SHA or sha in PRE_IMPORT_SHAS or not re.fullmatch(r"[0-9a-f]{7,40}", sha):
                continue
            # A hex word with no letter in it is a NUMBER -- a run id, a timestamp, a count --
            # and not a commit. This was `len(sha) == 7` and had to widen with BARE_SHA: an
            # 11-digit GitHub run id sits in the mirror and matched. A 40-character all-digit
            # commit id is possible in principle and has never existed; the check is on the
            # length that is actually written.
            if len(sha) < 40 and not re.search(r"[a-f]", sha):
                continue
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
            if (rel, tool, claimed) in QUOTED_STALE_VERSIONS:
                continue
            if not _version_prefix(claimed, actual):
                problems.append(
                    f"{rel}: claims {tool} {claimed}; {TOOLCHAIN_REL} records {actual}. Five "
                    f"canonical documents said PowerShell-only cargo on a Debian box")

    if problems:
        print("RED: canonical documents make claims that are not true\n")
        for p in sorted(set(problems)):
            print(f"  - {p}")
        print("\nEach of these is checkable, so none of them has to be found by reading.")
        return 1

    print("GREEN: canonical claims check out; "
          + ", ".join(f"{v} {k}" for k, v in checked.items()))
    print(f"  ({machine_note})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
