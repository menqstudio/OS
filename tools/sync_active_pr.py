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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check_coordination import PR_ROLES  # the closed enum, imported so it cannot drift  # noqa: E402

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
    "**The last independent audit returned RED -- now for one platform rather than one mechanism.** "
    "The FOURTH round -- `apps/desktop/AUDIT/2026-08-15-zero-trust-reaudit-0a9a1af.md`, a re-audit "
    "of the third round's five fixes against a **pinned snapshot** of `main` @ `0a9a1af` (the "
    "auditor proved the pin: `rev-parse 0a9a1af^{tree}` == its own `write-tree`, because main moved "
    "three times mid-run) -- could **not reopen four of the five**. `B-01`: the fifth, `A-01`, was "
    "fixed on Python/Linux only while this ledger's row claimed **both platforms** -- the F-02 "
    "pattern the ledger exists to catch. Closed on Windows 2026-08-15. `B-02` (the pin sits in the "
    "authority, not the supervisor that owns the floor) stays **OPEN** as a topology question beside "
    "the 1b decision. Superseding: the THIRD "
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


def carrier_merge_commit(number: int) -> str | None:
    """The 40-hex merge commit of a pull request, or None if it is not merged / cannot be read.

    Fail-soft on purpose: the caller uses this only to AVOID moving a field that is already right,
    and a `gh` outage must not turn a settle into a refusal. What it must never do is answer
    confidently and wrongly, so anything that is not a 40-hex sha is None.
    """
    out = subprocess.run(["gh", "pr", "view", str(number), "--json", "mergeCommit"],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    if out.returncode != 0:
        return None
    try:
        commit = (json.loads(out.stdout or "{}").get("mergeCommit") or {}).get("oid") or ""
    except json.JSONDecodeError:
        return None
    return commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None


def settled_head_for(head: str, carrier_no: int | None) -> str:
    """What `settled_at_main_head` must be, computed the way its VERIFIER computes it.

    `check_repo_state.verify_settled_snapshot` pins the field to the first parent of the carrier's
    merge commit — *"the main that carrier #N merged into"*. `--settled` wrote the live main head
    instead, which is the same commit only while the carrier is still open. Run the documented
    ritual in the documented order — merge, pull, settle — and the generator produces a snapshot its
    own gate refuses, naming the merge commit where the pin wants that commit's parent.

    That happened on 2026-08-17 and is recorded rather than quietly patched, because it is the
    SECOND time a generator and a gate have disagreed about this one field. The first was the
    unsatisfiable floor the fifth audit's `A-07` fix shipped, which turned main red within the hour.
    **A generator that can emit a state its own verifier rejects is a defect even when the verifier
    is right**, because what it teaches whoever hits it is that the gate is noise.

    So the rule is DERIVED from the fact the gate reads rather than restated beside it: if the
    carrier has merged and its merge commit is the head being settled at, the settled head is that
    commit's first parent. Otherwise — carrier still open, `gh` unreadable, someone settling from a
    branch — it is the live main head, which is what the field meant before the carrier existed.
    """
    if carrier_no is None:
        return head
    merged_as = carrier_merge_commit(carrier_no)
    if not merged_as or merged_as != head:
        return head
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{head}^1"],
                         capture_output=True, text=True)
    parent = out.stdout.strip()
    return parent if re.fullmatch(r"[0-9a-f]{40}", parent) else head


def live_open_prs() -> list[dict]:
    """Every pull request GitHub says is open right now, with the fields prs[] is anchored on.

    Read live, never assumed. `--settled` used to hard-code "Nothing else is open" into the snapshot
    note and "The only thing open is PR #N" into all three banners, without ever asking. On
    2026-08-15 that stamped both sentences while PR #112 -- a parked design proposal -- was open, so
    the settle that removed three stale claims manufactured a fourth in the same commit. A generator
    that asserts a fact it never measured is the mechanism behind most of this repository's stale
    canon; the fix belongs here, not in the file it writes.
    """
    out = subprocess.run(
        ["gh", "pr", "list", "--state", "open", "--json",
         "number,headRefName,headRefOid,baseRefName,isDraft,title"],
        # encoding is EXPLICIT: `text=True` decodes with the process locale, which on this Windows
        # host is cp1252, and a PR title containing an em-dash came back as "â€”" and was written
        # into the snapshot that way. gh emits UTF-8 on every platform; say so rather than inherit
        # whatever the console happens to be.
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    if out.returncode != 0:
        raise SystemExit("RED: `gh pr list` failed, so this tool cannot know what is open and will "
                         "not guess: " + (out.stderr or "").strip())
    try:
        return sorted(json.loads(out.stdout or "[]"), key=lambda p: p["number"])
    except (ValueError, KeyError) as exc:
        raise SystemExit(f"RED: could not parse `gh pr list` output: {exc}")


def parked_roles(parked: list[dict], pairs: list[str] | None) -> dict[int, str]:
    """Resolve each parked PR's role from --parked-role, or refuse. Never guessed.

    `check_coordination` holds prs[] to a closed enum of roles, and the role is a claim about what a
    pull request IS -- a design proposal is not an implementation, and the difference decides who is
    allowed to merge it. Inferring it from a title or a branch name would be this tool asserting
    something it cannot measure, which is the failure live_open_prs() exists to stop. So: refuse, and
    print the exact command. Checked BEFORE anything is written, so a refusal leaves no half-settled
    file behind.
    """
    roles: dict[int, str] = {}
    for pair in pairs or []:
        num, _, role = pair.partition("=")
        try:
            roles[int(num.strip().lstrip("#"))] = role.strip()
        except ValueError:
            raise SystemExit(f"RED: --parked-role expects NUMBER=ROLE, got {pair!r}")
    known = {p.get("number") for p in (json.loads(STATE.read_text(encoding="utf-8")).get("prs") or [])
             if isinstance(p, dict)}
    missing, bad = [], []
    for p in parked:
        n = p["number"]
        if n in known:
            continue                     # already recorded; its role is whatever the file says
        if n not in roles:
            missing.append(p)
        elif roles[n] not in PR_ROLES:
            bad.append((n, roles[n]))
    if bad:
        raise SystemExit("RED: --parked-role value not in " + repr(PR_ROLES) + ": "
                         + ", ".join(f"#{n}={r!r}" for n, r in bad))
    if missing:
        raise SystemExit(
            "RED: these pull requests are open, are not the carrier, and have no role yet:\n"
            + "".join(f"    #{p['number']}  {p.get('title') or ''}\n" for p in missing)
            + "A settled snapshot has to NAME every open pull request (check_repo_state), and every\n"
              "prs[] entry has to declare a role from " + repr(PR_ROLES) + " (check_coordination).\n"
              "Re-run with, for example:  --parked-role "
            + " --parked-role ".join(f"{p['number']}=design" for p in missing))
    return roles


def record_parked_prs(parked: list[dict], roles: dict[int, str]) -> list[int]:
    """Put every open pull request that is NOT the carrier into prs[], with its exact live head.

    `check_repo_state.verify_settled_snapshot` refuses a settled snapshot that names no open pull
    request, and `compare_external_prs` then anchors each prs[] entry to an exact live head, branch,
    base and draft flag. So this is not bookkeeping: an entry written here is a live claim that goes
    RED the moment the parked PR moves. Every value comes from GitHub, so the entry cannot be a
    guess. Insertion is targeted text surgery -- re-dumping this 109 KB file through json.dumps
    would reformat all of it and bury the change.
    """
    if not parked:
        return []
    text = STATE.read_text(encoding="utf-8")
    have = {p.get("number") for p in (json.loads(text).get("prs") or []) if isinstance(p, dict)}
    new = [p for p in parked if p["number"] not in have]
    if not new:
        return []
    rows = "".join(
        '    {"number": %d, "branch": %s, "base": %s, "draft": %s, "merge_state": "open", '
        '"role": %s, "head": %s, "why_listed": %s},\n'
        % (p["number"], json.dumps(p["headRefName"]), json.dumps(p["baseRefName"]),
           "true" if p["isDraft"] else "false", json.dumps(roles[p["number"]]),
           json.dumps(p["headRefOid"]),
           json.dumps("Open and NOT the carrier: " + str(p.get("title") or "").strip()
                      + ". Listed so the settled snapshot names it; its exact head is anchored."))
        for p in new)
    if '"prs": [],' in text:
        text = text.replace('"prs": [],', '"prs": [\n' + rows.rstrip(",\n") + "\n  ],", 1)
    elif '"prs": [\n' in text:
        text = text.replace('"prs": [\n', '"prs": [\n' + rows, 1)
    else:
        raise SystemExit("RED: could not locate the prs[] array to record the parked pull requests")
    json.loads(text)                     # never leave it unreadable
    STATE.write_text(text, encoding="utf-8")
    return [p["number"] for p in new]


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
    # `settled_at_main_head` moves WITH the baseline. Only `--settled` used to touch it, so three
    # ordinary syncs in a row left it three merges behind while the gate stayed green -- the check
    # could not see it, because an ancestor-of-main test can never go stale (A-07, fifth audit).
    # The field means "the main this carrier merged into", which is the same live head the baseline
    # is being set to, so writing one and not the other was never coherent.
    if data.get("settled_at_main_head"):
        swap(f'"settled_at_main_head": "{data["settled_at_main_head"]}"',
             f'"settled_at_main_head": "{head}"', "settled head")
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

    after = json.loads(text)             # and parse again: never leave it unreadable
    # THE SLICE ABOVE IS POSITIONAL. It runs from `"note": "` to the block's closing `"\n  },`,
    # which is correct only while `note` is the LAST key of current_workflow_pr. Add a key after it
    # and the slice swallows everything in between — and `json.loads` still succeeds, because
    # deleting whole key/value pairs leaves valid JSON (A-10, fifth audit). A parse guard that
    # cannot see the damage it was placed to catch is not a guard, so compare the key set instead:
    # this function is allowed to change the VALUES of current_workflow_pr, never its shape.
    before_keys = set((data.get("current_workflow_pr") or {}).keys())
    after_keys = set((after.get("current_workflow_pr") or {}).keys())
    if before_keys != after_keys:
        raise SystemExit(
            "RED: rewriting the note changed the SHAPE of current_workflow_pr — lost "
            + ", ".join(sorted(before_keys - after_keys) or ["nothing"])
            + "; gained " + ", ".join(sorted(after_keys - before_keys) or ["nothing"])
            + ". The note slice assumes `note` is the last key of the block. Nothing was written.")
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
           banner: str | None = None, role_pairs: list[str] | None = None) -> int:
    """Record that nothing is open, and point the reader at main rather than at a dead branch.

    `check_repo_state` refuses a snapshot that still names a merged carrier, because the reader it
    misleads is a person or an agent arriving at the repository cold — and CI never noticed, since
    the PR-event checks only run on a `pull_request` and after the merge nothing asked.
    """
    # Measure and validate FIRST. parked_roles() refuses when an open pull request has no declared
    # role, and a refusal has to leave the tree untouched -- a half-settled snapshot (new
    # settled_at_main_head, no prs[] entry) is precisely the RED state this whole change is about.
    parked = [p for p in live_open_prs() if p["number"] != pr]
    roles = parked_roles(parked, role_pairs)
    text = STATE.read_text(encoding="utf-8")
    data = json.loads(text)
    # Computed the way the GATE computes it, not assumed to be the live head — see
    # settled_head_for(). The carrier is whichever PR the snapshot currently names, because that is
    # the one whose merge this settle is recording.
    carrier_no = pr or ((data.get("current_workflow_pr") or {}).get("number"))
    settled = settled_head_for(head, carrier_no)
    line = '  "settled_at_main_head": "' + settled + '",\n'
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
    parked_phrase = ("Nothing else is open" if not parked else
                     "Also open, and NOT the carrier: "
                     + ", ".join("#" + str(p["number"]) for p in parked)
                     + " (recorded in prs[], exact-head anchored)")
    if pr and branch:
        rewrite_state(pr, branch,
                      "Settling the state anchor at main " + head[:7] + ". " + parked_phrase
                      + "; this pull request is the commit that records it.", head)
        rewrite_carrier_block(pr, branch)
    added = record_parked_prs(parked, roles)
    if added:
        print("  recorded in prs[]: " + ", ".join("#" + str(n) for n in added))

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
    # "The only thing open" is a measurement, not a phrase. See live_open_prs(): it was hard-coded
    # and it was wrong the day a design proposal was parked open for review.
    others = ("" if not parked else
              " Also open, and deliberately not merged here: "
              + ", ".join("PR #" + str(p["number"]) + " (`" + p["headRefName"] + "`)"
                          for p in parked) + ".")
    carrier = (((" The pull request that records it is PR #" + str(pr) + " on `" + branch + "`."
                 if parked else
                 " The only thing open is PR #" + str(pr) + " on `" + branch
                 + "`, the pull request that records it.") + others) if pr and branch
               else ((" Nothing is open." if not parked else " Open:" + others)))
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
    ap.add_argument("--parked-role", action="append", metavar="NUMBER=ROLE",
                    help="with --settled: the role of an open pull request that is NOT the "
                         "carrier, e.g. 112=design. Never inferred; see parked_roles().")
    args = ap.parse_args()

    head = live_main_head()
    if args.settled:
        return settle(head, args.next_up, args.pr, args.branch, args.banner, args.parked_role)
    if not (args.pr and args.branch and args.summary):
        raise SystemExit("RED: --pr, --branch and --summary are required unless --settled")
    changed = rewrite_state(args.pr, args.branch, args.summary, head)
    rewrite_carrier_block(args.pr, args.branch)
    # A pull request parked open while another one carries the snapshot has to be named in the
    # banner too, not only in --settled's. `check_coordination` requires every OPEN prs[] entry's
    # branch to appear in all three banner documents, and it is right to: a reader who is told
    # "CURRENT ACTIVE: PR #115" and nothing else will not discover that #112 is sitting there
    # waiting on them. Same omission as the hard-coded "Nothing else is open", one mode over.
    parked = [p for p in live_open_prs() if p["number"] != args.pr]
    also = ("" if not parked else
            " Also open, and not this PR's work: "
            + ", ".join("PR #" + str(p["number"]) + " on `" + p["headRefName"] + "`"
                        for p in parked) + ".")
    banner = args.banner or (
        f"> **⏭️ CURRENT ACTIVE: PR #{args.pr} · branch `{args.branch}`** (base `main`, tip "
        f"`{head[:7]}`, task T-017).{also}\n>\n> {args.summary}\n>\n> "
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
