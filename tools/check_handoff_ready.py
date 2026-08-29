"""Could a brand-new session take over right now, from this repository alone?

`CLAUDE.md`'s continuous-documentation law already says the answer must always be yes:

    At every moment the repository must be sufficient for a brand-new Claude/GPT
    session told only "Go to menqstudio/OS, read NEXT_CHAT.md and every file in
    config/canonical-read-manifest.json, verify the exact GitHub HEAD/CI, and
    continue" -- and then continue correctly FROM GITHUB ALONE.

That law has been in the brain for weeks and nothing ever checked it. It is a
sentence, and this repository's own first rule is that a documented claim is not
evidence. So this is the same sentence as a program.

It exists because of a specific moment: the one where a session is nearly out of
context and the work has to move to a fresh one. That is exactly when the temptation
is to write a hasty paragraph and say "continue from here" -- and exactly when a
wrong answer costs the most, because the next session starts from whatever is on
disk and has no memory of what was meant. Nobody should have to take an assistant's
word for "everything is ready". This prints the answer, and names what is missing.

Six questions, each satisfiable, each naming its own remedy:

  1. Is the canonical read set inside its budget?  (tools/check_canon_budget.py)
  2. Is the working tree clean?      An uncommitted file does not exist for the next session.
  3. Is the branch pushed?           Neither does an unpushed commit. Inside GitHub
                                     Actions this becomes "does this checkout contain
                                     the head CI says it is testing" -- see ci_checkout.
  4. Does NEXT_CHAT.md name THIS branch and THIS head, and a next action?
  5. Does config/current_state.json point at a commit that exists?
  6. If a session id is given: is the roadmap phase declared?

RED names every gap. GREEN prints the one sentence that may then be said out loud.

Stdlib only. Exit 0 GREEN, 1 RED. Network failure is RED-with-a-reason, never a
silent pass: "I could not check" and "it is fine" are different answers, and this
gate exists because they were being conflated.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

# How far into NEXT_CHAT.md the live handoff block is expected to be. Beyond this the
# file is history -- its own line 9 says "Earlier prose below is HISTORY" -- and a head
# named 3000 lines down is a record, not a handoff.
LIVE_BLOCK_LINES = 40


#: On a `pull_request` run, `actions/checkout` leaves a DETACHED merge commit whose first
#: parent is the base branch and whose second is the PR head. Asked naively, git then answers
#: three questions wrong at once: the branch is "HEAD", there is no upstream, and HEAD^ is
#: `main` rather than the commit the handoff is describing. This gate was added by `T-045`,
#: wired into CI in the same commit, and had NEVER been green there -- it reported "nothing of
#: it is on GitHub" about a checkout that GitHub had just performed. A gate that is red for a
#: reason having nothing to do with its subject teaches everyone to ignore it, which is worse
#: than not having it: `check_repo_state.py` was ignored the same way when #84 merged red.
def ci_checkout(root: pathlib.Path, env: dict[str, str] | None = None) -> dict[str, str] | None:
    """What GitHub Actions actually checked out, or None when this is not a CI run.

    Returns `{"head": sha, "branch": name}` describing the commit a next session would clone
    -- for a pull request that is the PR head, never the throwaway merge commit, because the
    merge commit exists only inside this run and no session can ever start from it.
    """
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") != "true":
        return None
    event = env.get("GITHUB_EVENT_NAME") or ""
    if event.startswith("pull_request"):
        head = _pr_head_from_event(env) or ""
        if not head:
            # No payload: the PR head is the merge commit's second parent.
            code, second = git(root, "rev-parse", "HEAD^2")
            head = second if code == 0 else ""
        return {"head": head or (env.get("GITHUB_SHA") or ""),
                "branch": env.get("GITHUB_HEAD_REF") or ""}
    return {"head": env.get("GITHUB_SHA") or "", "branch": env.get("GITHUB_REF_NAME") or ""}


def _pr_head_from_event(env: dict[str, str]) -> str | None:
    """`pull_request.head.sha` from the event payload, or None if it cannot be read."""
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    try:
        payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sha = (payload.get("pull_request") or {}).get("head", {}).get("sha")
    return sha if isinstance(sha, str) and sha else None


class Result:
    def __init__(self) -> None:
        self.problems: list[tuple[str, str]] = []

    def bad(self, what: str, remedy: str) -> None:
        self.problems.append((what, remedy))


def git(root: pathlib.Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 - an unusable git is RED, not GREEN
        return 1, str(exc)


def check_canon(root: pathlib.Path, res: Result) -> None:
    try:
        import check_canon_budget
    except Exception as exc:  # noqa: BLE001
        res.bad(f"the canon budget gate could not be imported: {exc}",
                "restore tools/check_canon_budget.py")
        return
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = check_canon_budget.main(root)
        except SystemExit as exc:
            code = int(exc.code or 1)
    if code != 0:
        res.bad("the canonical read set is over budget, so the next session cannot be "
                "handed what it is required to read",
                "python tools/check_canon_budget.py   (it names every file and its overage)")


def check_tree_clean(root: pathlib.Path, res: Result) -> None:
    code, out = git(root, "status", "--porcelain")
    if code != 0:
        res.bad(f"git status failed: {out}", "run this inside the repository")
        return
    if out:
        n = len(out.splitlines())
        res.bad(f"{n} file(s) are uncommitted -- they do not exist for the next session",
                "commit them, or revert them; either is an answer, leaving them is not")


def check_pushed(root: pathlib.Path, res: Result, ci: dict[str, str] | None = None) -> None:
    if ci is not None:
        # GitHub Actions cloned this from the remote a moment ago, so "is it pushed" is
        # answered by the checkout itself. What is still worth asking is whether the commit
        # CI names as the head is one this clone actually has -- a shallow or misconfigured
        # checkout is a real failure and must not read as GREEN.
        head = ci.get("head") or ""
        if not head:
            res.bad("this is a CI run and the head under test could not be resolved",
                    "check the workflow's checkout step; the gate must know what it is testing")
            return
        code, _ = git(root, "cat-file", "-e", f"{head}^{{commit}}")
        if code != 0:
            res.bad(f"CI names {head[:7]} as the head under test and this checkout does not "
                    f"have that commit",
                    "give actions/checkout fetch-depth: 0, or enough depth to contain the head")
        return
    code, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        res.bad("the current branch could not be resolved", "run this inside the repository")
        return
    code, upstream = git(root, "rev-parse", "--abbrev-ref", "@{upstream}")
    if code != 0:
        res.bad(f"branch {branch} has no upstream -- nothing of it is on GitHub",
                f"git push -u origin {branch}")
        return
    code, local = git(root, "rev-parse", "HEAD")
    code2, remote = git(root, "rev-parse", upstream)
    if code != 0 or code2 != 0:
        res.bad("local and remote heads could not be compared",
                "git fetch, then run this again")
        return
    if local != remote:
        res.bad(f"HEAD {local[:7]} is not what {upstream} has ({remote[:7]}) -- the next "
                f"session clones the remote, not this disk",
                f"git push")


def check_handoff_names_reality(root: pathlib.Path, res: Result,
                                ci: dict[str, str] | None = None) -> None:
    path = root / "NEXT_CHAT.md"
    try:
        head_lines = path.read_text(encoding="utf-8").splitlines()[:LIVE_BLOCK_LINES]
    except OSError as exc:
        res.bad(f"NEXT_CHAT.md is unreadable: {exc}", "restore it")
        return
    live = "\n".join(head_lines)

    code, sha = git(root, "rev-parse", "HEAD")
    code2, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or code2 != 0:
        res.bad("HEAD could not be resolved to compare against NEXT_CHAT.md", "run inside the repo")
        return
    if ci is not None:
        # Compare against what a next session would clone, not against the merge commit this
        # run invented. Left alone, the gate demanded that NEXT_CHAT.md name a commit that
        # exists nowhere but inside one CI job -- unsatisfiable by construction.
        sha = ci.get("head") or sha
        branch = ci.get("branch") or "HEAD"

    # A document cannot name the commit that contains it: the hash exists only after
    # the write. So the handoff may name HEAD or HEAD's first parent -- the settling
    # commit describes the state its parent left, and after the push HEAD is what the
    # next session clones. Anything older is the drift this checks for: START_HERE.md
    # sat at a head SEVEN merges stale, and nothing checked it.
    accepted = [sha]
    code3, parent = git(root, "rev-parse", f"{sha}^")
    if code3 == 0:
        accepted.append(parent)
    if not any(re.search(re.escape(c[:7]), live) for c in accepted):
        res.bad(f"NEXT_CHAT.md's first {LIVE_BLOCK_LINES} lines name neither the current "
                f"head {sha[:7]} nor its parent "
                f"{parent[:7] if code3 == 0 else '(none)'}",
                "put the current head in the live block -- a head named further down is a "
                "record, not a handoff")
    if branch != "HEAD" and branch not in live:
        res.bad(f"NEXT_CHAT.md's live block does not name the current branch {branch!r}",
                f"say which branch the next session continues on")
    if not re.search(r"(?im)^\s*>?\s*\*{0,2}next\b", live):
        res.bad("NEXT_CHAT.md's live block states no next action",
                "write one line beginning 'Next:' -- what the next session does first")


def check_machine_mirror(root: pathlib.Path, res: Result) -> None:
    path = root / "config" / "current_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        res.bad(f"config/current_state.json is unusable: {exc}", "restore or repair it")
        return
    settled = state.get("settled_at_main_head")
    if not isinstance(settled, str) or not settled:
        res.bad("config/current_state.json carries no settled_at_main_head",
                "set it to the commit a new session should start from")
        return
    code, _ = git(root, "cat-file", "-e", f"{settled}^{{commit}}")
    if code != 0:
        res.bad(f"config/current_state.json.settled_at_main_head ({settled[:12]}) is not a "
                f"commit in this repository",
                "point it at a real commit")


def check_phase_declared(root: pathlib.Path, session: str | None, res: Result) -> None:
    if not session:
        return
    try:
        import check_roadmap_order as roadmap
    except Exception:  # noqa: BLE001
        return
    ok, why = roadmap.verify_declaration(root, session)
    if not ok:
        res.bad(f"this session has not declared its roadmap phase: {why}",
                'python tools/check_roadmap_order.py --declare <n|meta> --note "..."')


def main(root: pathlib.Path = ROOT, session: str | None = None,
         env: dict[str, str] | None = None) -> int:
    ci = ci_checkout(root, env)
    res = Result()
    check_canon(root, res)
    check_tree_clean(root, res)
    check_pushed(root, res, ci)
    check_handoff_names_reality(root, res, ci)
    check_machine_mirror(root, res)
    check_phase_declared(root, session, res)

    if res.problems:
        print("RED: this work is NOT ready to hand to a new session\n")
        for i, (what, remedy) in enumerate(res.problems, 1):
            print(f"  {i}. {what}")
            print(f"     -> {remedy}\n")
        print("Do these, then run this again. Until it is GREEN, telling anyone to open a\n"
              "fresh session is telling them to start from a repository that cannot carry\n"
              "the work -- which is the failure this gate exists to make impossible.")
        return 1

    code, sha = git(root, "rev-parse", "HEAD")
    code2, branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if ci is not None:
        sha = ci.get("head") or sha
        branch = ci.get("branch") or branch
    print("GREEN: a new session can take over from this repository alone.\n")
    print(f"  branch : {branch}")
    print(f"  head   : {sha}")
    print("\nIt is now true, and may be said out loud:")
    print("  \"Open a fresh session. Everything it needs is committed and pushed.\"")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--session", default=None)
    args = ap.parse_args()
    raise SystemExit(main(pathlib.Path(args.root), args.session))
