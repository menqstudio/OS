#!/usr/bin/env python3
"""Point the state anchor and the three banners at the PR that is actually active.

`tools/check_repo_state.py` compares `config/current_state.json` against live GitHub, so opening a
PR without updating it turns the build red. That has happened three times in one day — not because
the rule is unclear, but because it is the last step of a long task and the cost of forgetting is
paid two minutes later by CI rather than immediately by the person forgetting.

So: one command, run right after `gh pr create`.

    python tools/sync_active_pr.py --pr 71 --branch fix/step6-readonly-deadlock \\
        --summary "One line on what this PR does and why."

It edits `config/current_state.json` and rewrites line 3 of NEXT_CHAT.md, PROJECT_STATE.md and
TASKS.md — the banner all three share. It does NOT commit or push: the state change belongs in the
same commit as the work, and a tool that pushed for you would be one more thing to trust.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANNER_FILES = ("NEXT_CHAT.md", "PROJECT_STATE.md", "TASKS.md")
STATE = ROOT / "config" / "current_state.json"

#: The one sentence every banner ends with. It states the SHIPPED fail-closed posture, so it is
#: load-bearing and has to stay true of the code.
#:
#: It used to say "the broker hands out `UpstreamBlockedExecutor`", flatly. That is false, and this
#: file is where the falsehood was manufactured and stamped into three canonical documents at a
#: time. `build_governed_executor` (`broker/src/main.rs:228`) returns a real `ChainExecutor` over a
#: `LinuxGovernedTurnChain` whose `ProductionResolver` can reach `TrustState::Production`; the
#: fail-closed `UpstreamBlockedExecutor` is the FALLBACK, taken at `:240` when `$BROPS_BROKER_CONFIG`
#: is unset or empty, and again when the file is unreadable/malformed, carries no TCB-root-signed
#: manifest, or the durable acceptance ledger will not open. The posture is real because nothing in
#: the shipped app sets that variable -- which is the condition a reader needs, and which the old
#: wording hid. Say what refuses AND under what condition it would stop refusing.
#: The audit POSITION, in the banner because the banner is the first thing a cold reader meets.
#: Two cold reads in a row concluded the audit had come back clean: NEXT_CHAT.md led with the FIRST
#: audit's "all code facts CONFIRMED, none refuted" and the SECOND audit's RED verdict appeared in
#: no canonical file at all. A verdict that lives only in a report nobody is routed to is not a
#: verdict the repository has. Change this string when -- and only when -- an independent audit
#: actually returns a different one.
AUDIT_POSITION_SENTENCE = (
    "**The last independent audit returned RED -- for materially fewer reasons.** The THIRD "
    "independent audit -- `apps/desktop/AUDIT/2026-08-14-zero-trust-audit-e0dd969.md`, of `main` @ "
    "`e0dd969`, auditor-role-only and READ-ONLY on the tree -- raised **5 new findings** "
    "(A-01..A-05, P2 1 / P3 4), **could not reopen the previous round's P0** on either platform, and "
    "**confirmed all three of the gate's refusals closed** at that head. It attacked 14 Builder "
    "claims and could not refute **9**, which it recommends for the independently-confirmed mark; it "
    "also found **4 ledger rows stale** and **2 false**. Its headline is **A-01**: the anti-rollback "
    "floor is scoped by `install_id`, which the broker chooses -- the R-07/R-10 bootstrap defect "
    "surviving one level up rather than closing, on both platforms, demonstrated against the "
    "repository's own ledger code. **RED is the standing verdict of record and the gate stays "
    "shut.** The index is `apps/desktop/AUDIT/AUDIT_LEDGER.md`; the superseded round is "
    "`2026-08-06-remediation-audit.md` (45 findings, 1 P0, at `219c763`)."
)
#: This constant said "122 surviving findings (1 P0, 7 P1, 32 P2, 82 P3) across its three rounds"
#: until 2026-08-14. That figure is in NEITHER audit report. The remediation audit's own verdict
#: table says 45 (P0 1 / P1 5 / P2 13 / P3 26) and the document carries exactly 45 R-numbered
#: rows, R-01..R-45, whose priorities sum to the same split. Every occurrence of "122" in that
#: report is a line number or a line count. "across its three rounds" was invented with it.
#:
#: It mattered because THIS constant is what stamps the audit position into NEXT_CHAT.md,
#: PROJECT_STATE.md and TASKS.md at once -- the same generator that stamped the false
#: "the broker hands out UpstreamBlockedExecutor" sentence into three canonical files before
#: 2026-08-09. The one file that had it right was apps/desktop/AUDIT/AUDIT_LEDGER.md, which is
#: the file every reader is sent to for the audit position, and which said 45 while six other
#: documents said 122. Where this sentence and the report disagree, the report wins: read it.

FAIL_CLOSED_SENTENCE = (
    "**The governed surfaces stay fail-closed.** `governed_verification_unconfigured()` returns "
    "Some(...) unconditionally before the model is invoked, `connect_broker()` refuses off Linux, "
    "and the broker serves `UpstreamBlockedExecutor` unless `$BROPS_BROKER_CONFIG` names a "
    "deployment config with a TCB-root-signed manifest -- which nothing in the shipped app sets."
)


def live_main_head() -> str:
    """The 40-hex sha the gate compares against. Read from the REMOTE, never typed.

    This used to run ``git rev-parse origin/main``, which reads a local ref and therefore returns
    whatever the last ``git fetch`` happened to leave behind. On 2026-08-10 that wrote a
    ``baseline_main_head_at_sync`` of ``6bd3027`` into the snapshot while main had already moved to
    ``5a72258``, and the Repo-state gate — which compares the field against the PR's live base sha —
    went RED. The function was named ``live_main_head`` the whole time.

    ``git ls-remote`` asks the remote and needs no fetch, so a stale local ref cannot produce a
    confident wrong answer. ``tools/stamp_pr_head.py`` already reads the remote this way; this is the
    same rule applied to the other end of the same comparison.
    """
    out = subprocess.run(["git", "-C", str(ROOT), "ls-remote", "origin", "refs/heads/main"],
                         capture_output=True, text=True, check=True)
    line = out.stdout.strip()
    sha = line.split("\t")[0] if line else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit(f"RED: origin refs/heads/main did not resolve to a 40-hex sha: {line!r}")
    return sha


def rewrite_state(pr: int, branch: str, summary: str, head: str) -> list[str]:
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)              # parse first: refuse to touch a file we cannot read back
    changed = []

    def swap(old: str, new: str, label: str) -> None:
        nonlocal text
        if old != new and old in text:
            text = text.replace(old, new, 1)
            changed.append(label)

    swap(f'"baseline_main_head_at_sync": "{data["sync"]["baseline_main_head_at_sync"]}"',
         f'"baseline_main_head_at_sync": "{head}"', "baseline head")
    swap(f'"snapshot_branch": "{data["sync"]["snapshot_branch"]}"',
         f'"snapshot_branch": "{branch}"', "snapshot branch")
    swap(f'    "branch": "{data["active"]["branch"]}"\n  }},',
         f'    "branch": "{branch}"\n  }},', "active branch")

    current = data["current_workflow_pr"]
    swap(f'    "number": {current["number"]},\n    "branch": "{current["branch"]}",',
         f'    "number": {pr},\n    "branch": "{branch}",', "workflow pr")
    swap(f"marker in the PR #{current['number']} body.",
         f"marker in the PR #{pr} body.", "candidate-head marker")
    swap(f"self-carrier is PR #{current['number']}). PR #{current['number']}'s own exact-head",
         f"self-carrier is PR #{pr}). PR #{pr}'s own exact-head", "self-carrier")

    # The note is prose; replace it wholesale rather than patching around the old text.
    start = text.index('"note": "', text.index('"current_workflow_pr"'))
    end = text.index('"\n  },', start) + 1
    text = text[:start] + '"note": ' + json.dumps(summary) + text[end:]
    changed.append("note")

    json.loads(text)                     # and parse again: never leave it unreadable
    STATE.write_text(text, encoding="utf-8")
    return changed


def rewrite_banners(banner: str) -> None:
    """Replace the WHOLE banner block, not just its first line.

    The banner is multi-line, and the first version of this replaced `lines[2]` alone. A second run
    therefore left the previous banner's continuation lines sitting under the new one, so the file
    accumulated fragments: a fresh first line above a stale tail, which is precisely the shape of
    staleness this tool exists to remove. It was caught by reading the output rather than by any
    check — the coordination gate saw a banner that did not name the active branch, which is a
    symptom two steps downstream of the cause.

    The block is every consecutive blockquote line from line 3 down. All of it is replaced.
    """
    for name in BANNER_FILES:
        p = ROOT / name
        lines = p.read_text(encoding="utf-8").split(chr(10))
        if not lines[2].startswith("> **"):
            raise SystemExit(f"RED: {name} line 3 is not the shared banner; refusing to overwrite it")
        end = 2
        while end + 1 < len(lines) and lines[end + 1].startswith(">"):
            end += 1
        rebuilt = lines[:2] + banner.split(chr(10)) + lines[end + 1:]
        p.write_text(chr(10).join(rebuilt), encoding="utf-8")

def rewrite_carrier_block(pr: int, branch: str) -> bool:
    """Point `next_action_by_carrier` at the PR that is actually carrying the snapshot.

    `check_coordination` refuses a block naming a PR other than `current_workflow_pr`, because this
    one modelled a merged PR as the open carrier for three days. The tool that moves the carrier has
    to move this too — otherwise the rule fires on every pull request and gets satisfied by hand,
    which is the drift it exists to prevent.
    """
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)
    block = data.get("next_action_by_carrier")
    if not isinstance(block, dict):
        return False
    note = ("The carrier is current_workflow_pr (#" + str(pr) + " on " + branch + "). This block is "
            "rewritten by tools/sync_active_pr.py whenever the carrier moves: it modelled PR #48 as "
            "the open carrier for three days after #48 merged, because nothing updated it. No "
            "merge-transition is modeled (there is no carrier_transition block), so the branches "
            "below are advisory prose, not gate inputs.")
    replaced = {
        "_note": note,
        "open": "merge #" + str(pr) + " so main records this state; see next_action for what follows",
        "merged": "re-run tools/sync_active_pr.py --settled --pr <next> --branch <next> so the "
                  "snapshot stops naming a carrier that has merged",
    }
    for key, value in replaced.items():
        old = json.dumps(block.get(key, ""), ensure_ascii=False)
        new = json.dumps(value, ensure_ascii=False)
        if old != new and old in text:
            text = text.replace(old, new, 1)
    json.loads(text)                     # never leave it unreadable
    STATE.write_text(text, encoding="utf-8")
    return True

def settle(head: str, next_up: str | None, pr: int | None, branch: str | None,
           banner: str | None = None) -> int:
    """Record that nothing is open, and point the reader at main rather than at a dead branch.

    `check_repo_state` refuses a snapshot that still names a merged carrier, because the reader it
    misleads is a person or an agent arriving at the repository cold — and CI never noticed, since
    the PR-event checks only run on a `pull_request` and after the merge nothing asked.
    """
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)
    line = '  "settled_at_main_head": "' + head + '",\n'
    existing = re.search(r'^\s*"settled_at_main_head":.*\n', text, re.M)
    if existing:
        text = text[: existing.start()] + line + text[existing.end() :]
    else:
        insert = text.index('  "sync":')
        text = text[:insert] + line + text[insert:]
    # The ACTIVE branch moves to main too. `check_coordination` requires the human docs to name
    # `active.branch`; leaving a deleted branch there asks every canonical document to point at
    # something that no longer exists -- the same staleness this mode exists to remove, one level
    # down, and it would have been caught only by whoever tried to check the branch out.
    for field, was in (("branch", (data.get("active") or {}).get("branch")),):
        if was and was != "main":
            text = text.replace('    "' + field + '": "' + was + '"\n  },',
                                '    "' + field + '": "main"\n  },', 1)
    snapshot_branch = (data.get("sync") or {}).get("snapshot_branch")
    if snapshot_branch and snapshot_branch != "main":
        text = text.replace('"snapshot_branch": "' + snapshot_branch + '"',
                            '"snapshot_branch": "main"', 1)
    json.loads(text)                     # never leave it unreadable
    STATE.write_text(text, encoding="utf-8")

    # And the settle commit's OWN pull request becomes the carrier. While it is open, it is the one
    # thing that is open, and the exact-head anchor has to point at it -- otherwise the snapshot
    # names a merged PR's dead branch and the gate refuses the very commit that resolves it.
    if pr and branch:
        rewrite_state(pr, branch,
                      "Settling the state anchor at main " + head[:7] + ". Nothing else is open; "
                      "this pull request is the commit that records it.", head)
        rewrite_carrier_block(pr, branch)

    last = (data.get("current_workflow_pr") or {}).get("number")
    tail = ("\n>\n> **Next:** " + next_up) if next_up else ""
    # The lead clause and the carrier reference are BOTH conditional, and `--banner` is honoured
    # here as the flag has always promised. Until 2026-08-14 the clause "and the only thing open is
    # the pull request that records it" was hard-coded and the literal "PR #" was emitted before
    # the conditional, so `--settled` with no carrier rendered:
    #     "...the only thing open is the pull request that records it.** PR #nothing is open at all."
    # -- a sentence contradicted by its own second half, stamped into all three canonical documents
    # at once. `--banner` could not be used to work around it either: main() parsed the flag and
    # never passed it to this function. A banner that reads as nonsense is not a smaller failure
    # than one that reads as a lie; it is the first thing a cold reader meets in every state file.
    carrier = ((" The only thing open is PR #" + str(pr) + " on `" + branch
                + "`, the pull request that records it.") if pr and branch
               else " Nothing is open.")
    rewrite_banners(banner or (
        "> **\u2705 SETTLED \u2014 `main` is at `" + head[:7] + "`.**" + carrier
        + " Start from "
        "`docs/OWNER_ACTION_REQUIRED.md`, the one page that says what is blocked and on whom."
        + tail + "\n>\n> " + AUDIT_POSITION_SENTENCE + chr(10) + ">" + chr(10) + "> " + FAIL_CLOSED_SENTENCE + " Earlier prose below is HISTORY."))
    print("settled at main " + head[:7] + "; banners point at main, not at a deleted branch")
    print("  verify:  python tools/check_coordination.py && python tools/check_repo_state.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, help="required unless --settled")
    ap.add_argument("--branch", help="required unless --settled")
    ap.add_argument("--summary", help="required unless --settled")
    ap.add_argument("--settled", action="store_true",
                    help="nothing is open: record the main everything merged into, and say so in "
                         "the banner. Without this the docs keep naming a PR that no longer "
                         "exists, and a reader goes looking for a branch that was deleted.")
    ap.add_argument("--next", dest="next_up",
                    help="with --settled: one line on what happens next, for whoever reads this "
                         "repository cold")
    ap.add_argument("--banner", help="the human banner; defaults to a line built from --summary")
    args = ap.parse_args()

    head = live_main_head()
    if args.settled:
        return settle(head, args.next_up, args.pr, args.branch, args.banner)
    if not (args.pr and args.branch and args.summary):
        raise SystemExit("RED: --pr, --branch and --summary are required unless --settled")
    changed = rewrite_state(args.pr, args.branch, args.summary, head)
    rewrite_carrier_block(args.pr, args.branch)
    banner = args.banner or (
        f"> **⏭️ CURRENT ACTIVE: PR #{args.pr} · branch `{args.branch}`** (base `main`, tip "
        f"`{head[:7]}`, task T-017).\n>\n> {args.summary}\n>\n> "
        + AUDIT_POSITION_SENTENCE + chr(10) + ">" + chr(10) + "> " + FAIL_CLOSED_SENTENCE + " Earlier prose below is HISTORY.")

    # This call went missing in an edit, and the line below kept announcing it. A message that
    # reports work it did not do is worse than silence: the banner stayed stale while the tool
    # said it had been rewritten, and the only thing that caught it was reading the file.
    rewrite_banners(banner)

    print(f"state anchor → PR #{args.pr} on {args.branch}, main {head[:7]}")
    print(f"  fields changed: {', '.join(changed)}")
    print(f"  banners rewritten: {', '.join(BANNER_FILES)}")
    print("\nNot committed. Run the two gates, then commit with the work:")
    print("  python tools/check_coordination.py && python tools/check_repo_state.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
