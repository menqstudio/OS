#!/usr/bin/env python3
"""The repository-root wall: read the canon, work the open phase, look before you build.

CLAUDE.md called the hook "the enforcement wall" and said "a textual claim such as
'I read it' is not evidence". That wall existed only under `engine/` -- the engine's
own `runtime/bro_hook.py`, wired at `engine/.claude/settings.json`, with its own
manifest rooted at `engine/`. A session opened at the REPOSITORY root got one
Stop-hook and nothing else, so the startup contract at the root was, in fact, prose.
This is the missing wall.

WHAT IT ENFORCES, PER EVENT
  SessionStart / SubagentStart -- reads every path in the canonical read manifest,
    puts their TEXT into the session's context, and records the content-bound
    receipt. The read is done, not asked for.
  UserPromptSubmit -- restates the receipt state, the first open phase, and this
    session's declaration, every turn. Cheap, and it removes "I forgot the roadmap
    existed" as a possibility.
  PreToolUse (edit tools only) -- refuses the edit unless, in order:
      1. the full-read receipt matches the canonical bytes on disk (auto-refreshed,
         with the changed files' text handed over -- see AUTO-REFRESH below);
      2. the session has declared a roadmap phase, and it is the first open one;
      3. a `meta` session stays inside the governance/tooling scope;
      4. a NEW file has a recorded prior-art search.
  PreToolUse (shell tools) -- TWO commands, recognised by NAME, are refused before they
    run: `gh pr merge`, unless it pins `--match-head-commit` and
    tools/check_merge_ready.py is GREEN; and a `git push` that is not a delete, unless
    tools/check_push_ready.py is GREEN. And one SHAPE of command line: a gate
    (`tools/check_*.py`) whose verdict is thrown away on the way to a commit, a push or a
    pull request. Every other shell command returns before anything is imported or
    spawned. See THE TWO NAMED COMMANDS and A DISCARDED VERDICT below.
  PostToolUse (shell tools only) -- DETECTION, NOT CONTAINMENT. See below.

SHELL: WHY THIS IS A PostToolUse CHECK AND NOT A MATCHER CHANGE
  Until T-053 the shell was not looked at here at all, and the paragraph in this
  place said so. The obvious repair -- add `Bash` to the PreToolUse matcher in
  `.claude/settings.json` and read the command TO DECIDE WHAT IT WRITES -- was designed
  first and rejected, for a reason that is a property of shells and not of this
  implementation:

      A RELIABLE PreToolUse SHELL PATH-CHECK IS NOT POSSIBLE.

  Deciding which paths a shell command writes is undecidable in general. It is not
  a matter of a better regex. `sh -c "$(printf ...)"` builds the command at run
  time; `python3 -c "open(p,'w')"` hides it in another language; `./deploy.sh` and
  `make install` put it behind a file the hook would have to interpret; `eval
  "$CMD"` puts it behind the environment. `tools/test_wall_bash_gap.py` runs twelve
  such spellings of one write as a live corpus. And the same classifier would have
  to wave through the read-only greps every agent here lives on, so its false
  positives cost as much as its false negatives.

  So the check is CONTENT-BASED rather than intent-based: it does not ask what the
  command said it would do, it asks what changed on disk. That question is decidable,
  and it is the same shape the engine's own wall already uses on
  `Bash|PowerShell|Shell` at PostToolUse.

  WHAT IT COSTS. One `git status --porcelain -uall` plus a hash of each already-dirty
  file, per shell call: 24 ms measured on this tree. And it runs AFTER the write.

  WHAT IT IS NOT. It cannot undo the write, and it does not try to: an automatic
  revert of an agent's uncommitted work is data loss with a governance excuse. The
  engine's PostToolUse path is the same -- the `post-tool` branch of `bro_hook.py`
  settles a lease and hands a red settlement to `_observe_or_block`, which emits
  `{"decision":"block"}` (or, in shadow mode, only a `[SHADOW] would block` note);
  there is no revert, no unlink, no restore anywhere in it. So state it exactly:
  SHELL COVERAGE HERE, AND IN THE ENGINE, IS DETECTION PLUS
  HALTING THE TURN -- NOT CONTAINMENT. The bytes that landed stay landed. What it
  buys is that the violation cannot be silently ridden past: the turn fails, the path
  is named, and it keeps failing while the violation stands.

  WHAT IT DOES NOT COVER, listed rather than implied:
    - a write outside the repository, or to a git-ignored path (git does not report it);
    - a write that is made and reverted inside one shell call (transient tamper);
    - which of several shell calls in a turn did it -- only that it happened;
    - a write made AND COMMITTED inside one shell call: the settlement walks the dirty
      set, and a committed path is clean again. HEAD is not compared, on purpose -- a
      `git pull` moves HEAD over hundreds of paths the session never wrote, and a
      report nobody can clear by reverting is a gate that gets switched off;
    - a write made before the session HAS a baseline. The baseline is taken at
      SessionStart / SubagentStart; a session whose start hook did not run is baselined
      by its first shell call instead, so whatever that call wrote is not judged. That
      call says so in the context -- it is announced, not silent;
    - a shell call that removes this session's baseline file from the temp directory:
      the next call re-baselines, with the same announcement and the same blind spot;
    - `CANONICAL_LAW=off`, which disables this exactly as it disables the rest;
    - anything at all in a session whose project root is not this checkout.

THE TWO NAMED COMMANDS (T-150) -- and why this does not contradict the paragraph above
  `Bash|PowerShell|Shell` IS in a PreToolUse matcher now. Not for the question above --
  which PATHS does this command write, still undecidable, still answered after the fact
  -- but for a different and much smaller one: IS THIS COMMAND LINE `gh pr merge` OR
  `git push`? That is a question about the words typed, and it has an answer.

  Both had a written rule and both were broken in one day. #314 was squash-merged a few
  minutes after midnight with 39 of 39 checks green; the squash is a new commit dated at
  the merge, PROJECT_STATE.md still said the day before, and `main` went RED. #317 was
  pushed without the bundle gate ever having been run to a verdict, and CI refused it.
  The remedy on file each time was a memory note. A memory is not a mechanism.

  HOW A COMMAND IS RECOGNISED. First, on the raw string and before anything is imported
  or spawned: does it contain `gh` and `merge`, or `git` and `push`? If not, the arm
  returns -- that is the whole cost for every other command, and it is why no bug below
  that line can reach them. Otherwise the line is split into simple commands at the
  UNQUOTED separators `;` `&` `|` newline `(` `)`; a quoted string is one word, a heredoc
  body is skipped, and a `$(...)` or backtick substitution is its own command even inside
  double quotes, because the shell runs it. Leading `NAME=value` words and wrappers
  (`sudo`, `env`, `time`, `command`, ...) are dropped, and then the FIRST word must be
  `gh` with positionals `pr merge`, or `git` with first non-option word `push`. So
  `echo "gh pr merge 5"` and `git commit -m "then git push"` are not what is asked about.

  HOW IT FAILS, which is two answers on purpose. Once a command IS one of the two, any
  failure to get a GREEN -- the gate RED, crashed, timed out, missing, or printing no
  verdict -- refuses it. For every other command a failure in this arm allows. If the
  splitter itself raises, the command is refused only when the raw string still reads
  `gh ... pr ... merge` or `git ... push` word for word; anything else passes. A wall
  that blocks every shell command cannot be repaired from inside the session it blocks.

  WHAT IT DOES NOT COVER, listed rather than implied:
    - a person merging in the GitHub web UI, or pushing from their own terminal;
    - a session whose project root is not this checkout: none of this loads;
    - `git push` or `gh pr merge` inside a script, a Makefile target, an alias, `eval`,
      `sh -c "..."`, or a heredoc fed to a shell -- the arm reads the command line, not
      what the command line runs. That is the same wall the paragraph above describes;
    - a push or a merge in a DIFFERENT repository: recognised, said out loud, and allowed;
    - the heavy tools/check_produced_artifact.py and the three suites: neither gate runs
      them;
    - `CANONICAL_LAW=off`, which disables this exactly as it disables the rest.

  A PUSH IS JUDGED ON THE TREE IT SENDS (T-160). This hook fires before the command line
  starts, so the push gate reads the tree as it is THEN. A line that edits, commits and
  pushes hands the gate a tree the push does not send: on 2026-10-02 `sync && commit &&
  push` sent a banner 47 bytes over its budget and the gate, asked first, had said GREEN.
  So a `git push` that is not a delete is refused when the line runs anything before it
  except `cd`, `export`, `unset`, `set`, `true`, `:` and `gh auth token`. What follows the
  push is not restricted.

A DISCARDED VERDICT (T-157) -- the third thing the shell arm refuses, and it is a shape
  Six times in this repository a gate printed RED and the commit, the push or the write
  after it ran anyway. Never because the gate was wrong: because the command line never
  asked the shell to connect the two. `gate | tail -3 && git commit` -- `&&` tests the
  last command of a pipeline, which is `tail`, and `tail` succeeded. `gate; git commit` --
  `;` does not test anything. A memory note recorded it after the second time, and the
  count went on to six, the sixth on the day this was written.

  WHAT IS REFUSED. Reading the same split command line as above, with the operator that
  ended each simple command:
    - a gate piped into anything, when `&&` follows that pipeline -- unless
      `set -o pipefail` came first on the line;
    - `git commit`, `git push`, `git merge`, `gh pr create|merge|ready|edit|comment|
      close|reopen`, `tools/sync_active_pr.py` or `tools/stamp_pr_head.py`, when a gate
      runs earlier in the line and anything but `&&` stands between them.
  A gate the shell itself is asking -- `if gate; then`, `elif`, `while`, `until` -- is not
  judged; neither is a gate nothing leans on (`gate | tail -3` alone, `gate; echo $?`).

  HOW IT FAILS. Open, like everything here that is not one of the two named commands: if
  this rule raises, the command runs.

  WHAT IT DOES NOT COVER, listed rather than implied:
    - a gate the line does not name by file: `for g in tools/check_*.py; do python3 "$g";
      done; git commit` is not seen, and neither is a gate inside a script or `sh -c`;
    - any follower outside the list above. `gate | tail && python3 write_things.py` is
      refused for its `&&`; `gate; python3 write_things.py` is not, because what a
      command writes cannot be decided from its words (see the SHELL paragraph);
    - a gate inside `( ... )`: a subshell's status is not followed, so no claim is made;
    - a verdict discarded ACROSS two tool calls. Reading the output is still the job.

THE THREE HONEST LIMITS -- do not read this gate as more than it is
  * SHELL IS NOT GATED BEFORE THE FACT -- for what it WRITES. Only
    Edit/Write/MultiEdit/NotebookEdit are refused in advance for a path; the two named
    commands above are refused for what they ARE, which says nothing about paths. A
    session can still write any file through Bash (`>`,
    `sed -i`, a python one-liner) and the write WILL LAND; what changed in T-053 is
    that it is detected afterwards and the turn is failed. Closing it in advance
    needs shell-command classification, which the engine's own wall documents as
    unsound (`cat $(rm -rf x)` classifies as a read). The durable backstop is still
    elsewhere: check_canonical_sync runs at commit and in CI over whatever landed,
    however it was written -- though note that it judges a DIFFERENT property, whether
    code and canon moved together, and cannot ask whether the session had the right
    to write that path.
  * THE GATE FAILS OPEN ON ITS OWN BUGS. A policy verdict is fail-closed -- no
    declaration means denied. But an unexpected exception inside this file allows
    the tool and shouts in the context instead. A wall that bricks the repository
    when it malfunctions cannot be repaired, because repairing it requires editing
    it. The durable enforcement is the CI gates, which fail closed.
  * `CANONICAL_LAW=off` DISABLES IT. That is the recovery path, and it is a real
    bypass: a session that can set an environment variable can turn the wall off.
    It is written here rather than hidden, because a rule that documents its own
    bypass is worth more than one that pretends it has none.

AUTO-REFRESH, and why it is not a loophole
  When a canonical file changes mid-session, the receipt stops verifying. The hook
  then re-reads, hands the CHANGED files' text to the session, and allows the tool.
  It does not silently re-stamp: the new bytes go into the context. A hard deny was
  the first design and was rejected -- the update law REQUIRES the session to edit
  the canonical documents, so a deny-on-change rule would refuse every second edit
  of the work it demands.

Wired at .claude/settings.json. stdlib only. Never writes inside the repository.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(os.getenv("CLAUDE_PROJECT_DIR")
                    or pathlib.Path(__file__).resolve().parents[2]).resolve()
sys.path.insert(0, str(ROOT / "tools"))

# Tools that write files through the harness. Bash is deliberately absent -- see the
# module docstring's first honest limit.
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Tools that run a shell. These are NOT added to EDIT_TOOLS: they are not refused in
# advance for the PATHS they write (see the docstring -- a reliable PreToolUse shell
# path-check is not possible), they are settled afterwards against what actually changed
# on disk. Two commands are refused in advance by NAME, and one shape of command line:
# see `handle_pre_shell`.
SHELL_TOOLS = {"Bash", "PowerShell", "Shell"}
# How long a merge/push gate may take before the command it guards is refused. Kept under
# a minute on purpose: a hook the harness has to kill has given no verdict, and no verdict
# from the harness's side is an allow.
GATE_TIMEOUT = 50
# A dirty file larger than this is compared on (size, mtime_ns) instead of its hash, so
# one big artifact cannot make every shell call slow. Weaker, and said so rather than
# quietly hashing 400 MB on every `ls`.
MAX_HASH_BYTES = 8 * 1024 * 1024
# How much canonical text is pasted into a session before the rest is merely NAMED.
# The canonical set here is ~810 KB (~200k tokens); the default budget delivers about
# 437 KB of it at SessionStart and lists the remainder with sizes. This is the one
# number in the wall worth arguing about: raise it and sessions start closer to
# context exhaustion, lower it and more of the "mandatory read" becomes an instruction
# rather than a delivery. It is deliberately NOT silent either way -- whatever is not
# pasted is named, with its size, under a "NOT PASTED" banner.
MAX_INJECT_BYTES = int(os.getenv("CANONICAL_LAW_INJECT_BYTES", "500000"))
MAX_DELTA_INJECT_BYTES = 200_000
OFF_VALUES = {"off", "0", "false", "no", "disabled"}


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=True))


def context(hook: str, text: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": hook, "additionalContext": text}})


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                 "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def payload() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def disabled() -> bool:
    return str(os.getenv("CANONICAL_LAW", "")).strip().lower() in OFF_VALUES


def canonical_text(receipt_store, changed_only: list[str] | None = None) -> str:
    """Paste as much of the canonical set as a session can actually take, and be
    explicit about the rest.

    The canonical set in this repository is ~810 KB -- roughly 200k tokens. Pasting
    all of it would not deliver a read; it would blow the context and be truncated by
    the harness, which is a read that silently did not happen. So: fill the budget in
    manifest order (the manifest puts the current-state documents first, deliberately),
    then NAME the remainder with sizes and instruct the session to open them.

    The receipt is recorded either way, and it does NOT claim the remainder was read
    -- it claims the session was handed, or told exactly where to find, the bytes that
    are on disk right now. Overstating that would be the same lie one level up.
    """
    paths = changed_only if changed_only is not None else receipt_store.manifest_paths(ROOT)
    budget = MAX_DELTA_INJECT_BYTES if changed_only is not None else MAX_INJECT_BYTES
    blocks: list[str] = []
    deferred: list[tuple[str, int]] = []
    used = 0
    for rel in paths:
        try:
            size = (ROOT / rel).stat().st_size
        except OSError:
            size = 0
        if used + size > budget and blocks:
            deferred.append((rel, size))
            continue
        try:
            blocks.append(f"\n===== {rel} =====\n{(ROOT / rel).read_text(encoding='utf-8')}")
            used += size
        except OSError as exc:
            blocks.append(f"\n===== {rel} =====\n<<UNREADABLE: {exc}>>")
    text = "".join(blocks)
    if deferred:
        listing = "\n".join(f"  - {rel} ({size} bytes)" for rel, size in deferred)
        text += (f"\n\n===== NOT PASTED ({len(deferred)} canonical files, "
                 f"{sum(size for _, size in deferred)} bytes) =====\n"
                 "These are canonical and they were NOT delivered above -- the set is larger than "
                 f"one context ({budget} byte budget). The receipt covers their hashes, not your "
                 "having read them. Open every one of them with Read before you act:\n" + listing)
    return text


# --- per-turn enforcement -----------------------------------------------------------
# Session start is one moment and a session is hundreds. Everything injected once
# competes with everything that arrives afterwards and loses -- which is why the Owner
# had to say "you forget" about a rule that WAS in CLAUDE.md. So the cheap gates run on
# every message, and their verdict is restated every message.
#
# Only gates that are pure file arithmetic run here. check_doc_claims and
# check_handoff_ready shell out to git and walk the tree; per-turn they would tax every
# message to catch something that changes on commit, so they stay in CI and in the
# handoff. A gate that makes the session slow is a gate somebody removes.
FAST_GATES = ("check_canon_budget", "check_state_fields")

# How many consecutive turns may pass with the repository unchanged before the session is
# told to stop and say what is blocking it. Not a limit on thinking: reading, searching and
# planning legitimately change nothing. It is a limit on how long a session may believe it
# is progressing while nothing lands. Two full working stretches, then escalation.
STALL_TURNS = 25
STALL_AGAIN = 15


def _turn_state_path(sid: str) -> pathlib.Path:
    import hashlib
    import tempfile
    safe = hashlib.sha256((sid or "unknown").encode()).hexdigest()[:20]
    d = pathlib.Path(tempfile.gettempdir()) / "os-canonical-law" / "turns"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def fast_gate_line() -> str:
    """Run the file-arithmetic gates and report them in one line, every turn."""
    import contextlib
    import io
    verdicts = []
    for name in FAST_GATES:
        try:
            mod = __import__(name)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = mod.main(ROOT)
            verdicts.append((name, code, buf.getvalue().strip()))
        except SystemExit as exc:
            verdicts.append((name, int(exc.code or 1), ""))
        except Exception as exc:  # noqa: BLE001 - a broken gate must not wedge the turn
            verdicts.append((name, -1, f"could not run: {exc}"))
    red = [(n, out) for n, c, out in verdicts if c != 0]
    if not red:
        return "GATES: canon budget GREEN, machine mirror GREEN."
    lines = ["GATES RED -- fix these before adding anything to a canonical document:"]
    for name, out in red:
        first = next((ln for ln in out.splitlines() if ln.strip().startswith("-")), "")
        lines.append(f"  {name}: {first.strip() or 'RED'}")
        lines.append(f"    run: python3 tools/{name}.py")
    return "\n".join(lines)


def stall_line(sid: str) -> str:
    """Notice, out loud, when many turns have passed and the repository has not moved.

    A session that has misunderstood the task does not feel stuck; it feels busy. The
    only signal available from here that does not require judgement is whether anything
    has LANDED, so that is the signal used -- and its limit is stated rather than hidden:
    reading and planning legitimately move nothing, so this cannot distinguish careful
    work from a loop. It does not block. It asks a question the session cannot answer
    from inside the loop, which is the point.
    """
    import json as _json
    code, head = 0, ""
    try:
        import subprocess
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        code, head = r.returncode, (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""
    if code != 0:
        return ""
    path = _turn_state_path(sid)
    try:
        state = _json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    if state.get("head") != head:
        state = {"head": head, "turns": 0, "warned": 0}
    state["turns"] = int(state.get("turns", 0)) + 1
    turns, warned = state["turns"], int(state.get("warned", 0))

    due = STALL_TURNS if warned == 0 else STALL_TURNS + STALL_AGAIN * warned
    note = ""
    if turns >= due:
        state["warned"] = warned + 1
        note = (
            f"\n\nSTALL CHECK: {turns} turns on this session and HEAD has not moved from "
            f"{head[:7]}. That is fine if you are reading, searching or planning. It is not "
            f"fine if you are looping.\n"
            f"  Stop and answer three questions IN THE REPLY, not silently:\n"
            f"    1. What exactly are you trying to make true?\n"
            f"    2. What have you tried, and what did each attempt actually print?\n"
            f"    3. What would tell you that you are on the wrong track?\n"
            f"  If you cannot answer 2 with output you have SEEN, you are guessing -- say so "
            f"to the Owner and ask, rather than continuing. Three days of a confident wrong "
            f"direction costs more than one question.")
    try:
        path.write_text(_json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return note


OWNER_CONTRACT_REL = "config/owner-contract.md"


def owner_contract() -> str:
    """The Owner's working contract, restated on EVERY message.

    Not at session start alone. A rule stated once competes with everything that arrives
    after it and loses: the session that added this file drifted out of Armenian for
    several turns and the Owner had to say so. Restating it each turn costs a couple of
    hundred tokens and removes the failure mode entirely.

    Fail-closed and LOUD if it is missing: a silently absent contract is exactly the
    condition it exists to prevent, and this repository has already been bitten once by a
    wall that was off without announcing it (T-019).
    """
    path = ROOT / OWNER_CONTRACT_REL
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return (f"OWNER CONTRACT MISSING ({OWNER_CONTRACT_REL}: {exc}). Nothing is telling "
                f"you how the Owner wants to be worked with. Restore it from git before "
                f"answering; do not improvise it.")


def session_status(receipt_store, roadmap, sid: str) -> str:
    ok, why = receipt_store.verify(ROOT, sid)
    try:
        open_phase = roadmap.first_open_phase(ROOT)
    except Exception as exc:  # noqa: BLE001 - a broken roadmap must still produce a line
        return f"receipt: {why}; roadmap unreadable: {exc}"
    declared_ok, declared_why = roadmap.verify_declaration(ROOT, sid)
    return (f"CANONICAL LAW | receipt: {'OK' if ok else 'STALE'} ({why}) | "
            f"first open roadmap phase: {open_phase} | "
            f"phase declaration: {'OK' if declared_ok else 'MISSING/REFUSED'} - {declared_why}")


def target_path(tool_input: dict) -> str | None:
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def relative(path_str: str) -> str | None:
    try:
        return pathlib.Path(path_str).resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return None


def _budget_ceilings() -> dict | None:
    """The per-file ceilings, or None when the budget gate cannot be asked.

    One loader for the pre-tool and the post-tool arm. They were two, and they did not
    catch the same thing: `check_canon_budget.load_json` raises SystemExit on a missing
    or invalid budget file, the pre-tool arm caught it, and the post-tool arm caught only
    Exception -- so the hook died with exit 1 past the FAILED OPEN shout.
    """
    import contextlib
    import io
    try:
        import check_canon_budget as budget
        # load_json PRINTS its `RED:` line before it raises, and a hook's stdout is its
        # verdict channel -- so the line is swallowed along with the exit.
        with contextlib.redirect_stdout(io.StringIO()):
            ceilings = budget.load_json(ROOT, budget.BUDGET_REL).get("per_file_bytes") or {}
    except (Exception, SystemExit):  # noqa: BLE001 - a missing gate must not wedge the session
        return None
    return ceilings if isinstance(ceilings, dict) else None


def _edit_delta(tool_input: dict) -> int | None:
    """Bytes an Edit or a MultiEdit adds (negative: removes), or None if unmeasurable.

    `Edit` carries one `old_string`/`new_string` pair at the top level; `MultiEdit`
    carries a list of them under `edits`. A shape this cannot read is None, never 0:
    "could not measure" and "adds nothing" are different answers.
    """
    edits = tool_input.get("edits")
    pairs = edits if isinstance(edits, list) and edits else [tool_input]
    delta = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            return None
        old, new = pair.get("old_string"), pair.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        delta += len(new.encode("utf-8")) - len(old.encode("utf-8"))
    return delta


def canon_budget_problem(rel: str | None, tool: str, tool_input: dict) -> str | None:
    """While a canonical document is over its ceiling, only an edit that SHRINKS it
    is allowed through.

    Every other gate in this repository can be satisfied by adding: a check to write,
    a row to append, a document to update. That is why the read manifest reached
    1917 KB -- a session that appends is compliant and a session that deletes is not
    rewarded, so nothing ever deleted. NEXT_CHAT.md got to 4034 lines one honest
    paragraph at a time, and PROJECT_STATE.md is 95% the same file.

    So the refusal is deliberately asymmetric. Over budget, `NEXT_CHAT.md` accepts a
    write that is smaller than what is there and refuses one that is not. Under
    budget, nothing here fires at all.

    LIMIT, stated rather than hidden: this sees the harness edit tools. A shell
    redirect appends without passing through here -- the same "SHELL IS NOT GATED"
    hole this file's own header names; `shell_path_problem` asks the same question
    after the fact, and `tools/check_canon_budget.py` in CI is the backstop for
    whatever lands.
    """
    if rel is None:
        return None
    ceilings = _budget_ceilings()
    if ceilings is None:
        return None
    cap = ceilings.get(rel)
    if not isinstance(cap, int):
        return None
    try:
        current = (ROOT / rel).stat().st_size
    except OSError:
        return None
    if current <= cap:
        return None

    if tool == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            return None
        after = len(content.encode("utf-8"))
        if after < current:
            return None
        return (f"{rel} is {current:,} bytes against a ceiling of {cap:,}, and this write "
                f"would leave it at {after:,}. While a canonical document is over budget "
                f"the only edit that is accepted is one that makes it smaller. Move the "
                f"history to docs/archive/ and leave the live statement behind, then write "
                f"again. Run `python tools/check_canon_budget.py` to see the whole set.")

    delta = _edit_delta(tool_input)
    if delta is None:
        # A payload whose size cannot be read (a NotebookEdit, a shape nobody has met yet)
        # used to fall through to an allow -- and so did MultiEdit, which the matcher has
        # always named. Over its ceiling a file accepts a SHRINKING edit; one that cannot
        # be shown to shrink it is not one.
        return (f"{rel} is {current:,} bytes against a ceiling of {cap:,}, and this {tool} "
                f"call carries nothing its size can be measured from. While a canonical "
                f"document is over budget the only edit that is accepted is one that makes "
                f"it smaller: use Edit or Write, so the change can be measured.")
    if delta < 0:
        return None
    return (f"{rel} is {current:,} bytes against a ceiling of {cap:,}, and this edit "
            f"adds {delta:,} more. While a canonical document is over budget the only "
            f"edit that is accepted is one that makes it smaller -- that is the whole "
            f"point of the ceiling: this repository has never lacked a rule that says "
            f"write something, only one that says remove something. Archive the history "
            f"first. `python tools/check_canon_budget.py` names every file and its overage.")


def _shell_state_path(sid: str) -> pathlib.Path:
    """Where a session's dirty-tree fingerprint lives -- outside the repository.

    Same reasoning as the read receipt: a fingerprint committed into the tree would be
    a reusable one, and this file never writes inside the repository.
    """
    import hashlib
    import tempfile
    safe = hashlib.sha256(f"{ROOT}|{sid or 'unknown'}".encode()).hexdigest()[:24]
    directory = pathlib.Path(tempfile.gettempdir()) / "os-canonical-law" / "shell"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe}.json"


#: Where the baseline keeps each dirty path's SIZE. Repo-relative paths never start with
#: a slash, so this key cannot collide with one. The sizes are a second map rather than a
#: new field inside the fingerprint on purpose: changing the fingerprint's shape would make
#: every already-dirty path of every live session look changed on its next shell call.
SIZES_KEY = "/sizes"


def _size(rel: str) -> int | None:
    try:
        return (ROOT / rel).stat().st_size
    except OSError:
        return None


def _committed_size(rel: str) -> int | None:
    """The size of `rel` at HEAD, or None when HEAD has no such blob or git cannot say."""
    import subprocess
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-s", f"HEAD:{rel}"],
                                capture_output=True, text=True, timeout=10)
        return int(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:  # noqa: BLE001 - no git, no answer
        return None


def _load_shell_state(path: pathlib.Path) -> tuple[dict[str, str], dict[str, int]] | None:
    """`(fingerprints, sizes)` from a baseline file, or None when there is no baseline."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return {}, {}
    sizes = raw.pop(SIZES_KEY, None)
    sizes = ({k: v for k, v in sizes.items() if isinstance(v, int)}
             if isinstance(sizes, dict) else {})
    return {k: v for k, v in raw.items() if isinstance(v, str)}, sizes


def _save_shell_state(path: pathlib.Path, fingerprints: dict[str, str],
                      sizes: dict[str, int]) -> None:
    try:
        path.write_text(json.dumps({**fingerprints, SIZES_KEY: sizes}), encoding="utf-8")
    except OSError:
        pass


def _sizes_of(rels) -> dict[str, int]:
    out: dict[str, int] = {}
    for rel in rels:
        size = _size(rel)
        if size is not None:
            out[rel] = size
    return out


def baseline_shell_state(sid: str) -> None:
    """Record the session's baseline at its START, unless it already has one.

    The first shell call used to be the baseline, so whatever that call wrote was never
    judged -- a session could do its out-of-scope write first and be clean ever after.
    "Unless it already has one" is load-bearing: SubagentStart fires with the parent's
    session id, and SessionStart fires again on resume and after a compaction; each would
    otherwise forgive everything written since the real start.
    """
    path = _shell_state_path(sid)
    if path.exists():
        return
    now = dirty_fingerprints()
    if now is not None:
        _save_shell_state(path, now, _sizes_of(now))


def _fingerprint(rel: str) -> str:
    """A content fingerprint for one already-dirty path, or a marker for a gone one."""
    import hashlib
    path = ROOT / rel
    try:
        stat = path.stat()
    except OSError:
        return "<absent>"
    if not path.is_file():
        return f"<not-a-file:{stat.st_mode}>"
    if stat.st_size > MAX_HASH_BYTES:
        return f"<big:{stat.st_size}:{stat.st_mtime_ns}>"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return f"<unreadable:{exc.errno}>"


def dirty_fingerprints() -> dict[str, str] | None:
    """`{repo-relative path: fingerprint}` for everything git reports as changed.

    None when git could not be asked -- the caller then allows and says so, because a
    gate that cannot run has not failed, and this file's law is that only POLICY
    verdicts are fail-closed.

    Only already-dirty paths are hashed, which is what keeps this to milliseconds: the
    set is normally single digits and `git status` has done the walking.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001 - no git, no verdict
        return None
    if result.returncode != 0:
        return None
    out: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if len(line) < 4:
            continue
        code, payload = line[:2], line[3:]
        # `R  old -> new` -- both sides matter: one path gained content, one lost it.
        for piece in (payload.split(" -> ") if " -> " in payload else [payload]):
            rel = piece.strip().strip('"')
            if rel:
                # The porcelain CODE is kept in the value, not just the content hash,
                # because `??` (untracked) is what makes a path NEW. The first cut of
                # this used "absent from the previous dirty set" for that, which called
                # every ordinary edit of a clean tracked file a new file and demanded a
                # prior-art search for it -- caught by the live probe, not by reasoning.
                out[rel] = f"{code}:{_fingerprint(rel)}"
    return out


def shell_path_problem(rel: str, roadmap, prior_art, sid: str,
                       before: dict[str, str], now: dict[str, str],
                       before_sizes: dict[str, int] | None = None) -> str | None:
    """The same questions PreToolUse asks about a path, asked after the write.

    Deliberately the SAME predicates, not a second weaker copy of them: if the two ever
    disagreed, which tool wrote the file would decide whether the rule applied, which is
    the whole defect being closed.

    `before_sizes` is what makes that true of the budget rule. Until it was passed, this
    arm said "over its ceiling AND bigger than it was" in a comment and tested only the
    first half -- so a shell edit that SHRANK an over-budget file was blocked while the
    same shrink through Edit was accepted, and the stated remedy (revert the path) made
    the file larger.
    """
    scope = roadmap.scope_problem(ROOT, sid, rel)
    if scope:
        return scope

    # New file: at PreToolUse "new" means "does not exist yet". After the fact the file
    # exists either way, so the question becomes whether git TRACKS it -- porcelain `??`.
    # Not "was it dirty a moment ago": that made every edit of a clean tracked file look
    # like a new file.
    if now.get(rel, "").startswith("??") and (ROOT / rel).exists():
        art_ok, art_why = prior_art.verify(ROOT, sid, rel)
        if not art_ok:
            return art_why

    # Canon budget: over its ceiling AND not smaller than it was. "Was" is the size the
    # baseline recorded for a path that was already dirty, and the committed size for one
    # that was clean -- which is what a clean tracked file's size WAS.
    ceilings = _budget_ceilings()
    if ceilings is None:
        return None
    cap = ceilings.get(rel)
    if not isinstance(cap, int):
        return None
    size = _size(rel)
    if size is None or size <= cap:
        return None
    was = (before_sizes or {}).get(rel)
    if was is None:
        was = _committed_size(rel)
    if was is not None and size < was:
        return None
    grew = (f"it was {was:,} before this shell call" if was is not None
            else "its previous size could not be established")
    return (f"{rel} is {size:,} bytes against a ceiling of {cap:,}, and {grew}. While a "
            f"canonical document is over budget the only accepted edit is one that makes "
            f"it smaller. Archive the history to docs/archive/ and leave the live statement.")


def handle_post_tool(data: dict, roadmap, prior_art, sid: str) -> None:
    """Settle a shell call against what changed on disk. See the docstring: this is
    detection plus halting the turn, and the write has already landed."""
    if str(data.get("tool_name") or "") not in SHELL_TOOLS:
        return

    now = dirty_fingerprints()
    if now is None:
        context("PostToolUse", "CANONICAL LAW: could not read `git status`, so this shell "
                               "call was NOT settled against the tree. Not a pass.")
        return

    state_path = _shell_state_path(sid)
    loaded = _load_shell_state(state_path)

    if loaded is None:
        # Nothing to compare against: baseline whatever is already dirty and allow. A
        # session that starts on a dirty tree must not be blamed for it. But say so --
        # the baseline is normally taken at session start, so arriving here means the
        # start hook did not run for this session or its baseline file is gone, and
        # either way whatever THIS call wrote is being forgiven unseen.
        _save_shell_state(state_path, now, _sizes_of(now))
        context("PostToolUse", "CANONICAL LAW: this session had no shell baseline, so this "
                               "call was used as one and was NOT settled against the tree. "
                               "Anything it wrote is unjudged. Not a pass.")
        return
    before, before_sizes = loaded

    changed = sorted(rel for rel, fp in now.items() if before.get(rel) != fp)
    if not changed:
        return

    declared_ok, declared_why = roadmap.verify_declaration(ROOT, sid)
    if not declared_ok:
        problems = [f"{rel}: {declared_why}" for rel in changed[:1]]
        violating = set(changed)
    else:
        problems, violating = [], set()
        for rel in changed:
            problem = shell_path_problem(rel, roadmap, prior_art, sid, before, now,
                                         before_sizes)
            if problem:
                problems.append(f"{rel}: {problem}")
                violating.add(rel)

    # Advance the baseline for everything that was allowed. A violating path is left OUT
    # of the baseline on purpose, so it keeps being reported until it is reverted or the
    # session declares a phase that permits it -- both real, satisfiable actions. A gate
    # that reports a violation once and then forgets it is a notification, not a gate.
    # Its SIZE record is kept as it was, though: "smaller than it was" must go on meaning
    # smaller than before the violation, not smaller than the violation.
    sizes = _sizes_of(rel for rel in now if rel not in violating)
    sizes.update({rel: before_sizes[rel] for rel in violating if rel in before_sizes})
    _save_shell_state(state_path,
                      {rel: fp for rel, fp in now.items() if rel not in violating}, sizes)

    if not problems:
        return
    listed = "\n".join(f"  - {p}" for p in problems[:8])
    more = f"\n  ... and {len(problems) - 8} more" if len(problems) > 8 else ""
    emit({"decision": "block", "reason":
          "CANONICAL LAW: a shell command changed paths this session may not write.\n"
          + listed + more +
          "\n\nTHE WRITE HAS ALREADY LANDED -- this check runs after the tool and cannot "
          "undo it. Revert the path, or declare the roadmap phase that owns it, and the "
          "report clears. It will keep firing until one of those is true."})


# --- the pre-tool SHELL arm: two commands, refused before they run (T-150) -------------
# Read THE TWO NAMED COMMANDS in the module docstring first. Everything from here to
# `handle_pre_shell` is pure string work except `run_gate` and the two `_git` questions,
# and those are reached only after a command has been recognised as one of the two.

MERGE_GATE = "check_merge_ready.py"
PUSH_GATE = "check_push_ready.py"
RECOVERY = ("If this refusal is itself the bug, `CANONICAL_LAW=off` is the recovery path, "
            "and it is a real bypass -- say so when you use it.")

#: Words that may stand in front of a command without being it.
_WRAPPERS = frozenset({"sudo", "env", "command", "builtin", "exec", "time", "nohup", "nice",
                       "then", "do", "else", "elif", "if", "while", "until", "!", "{"})
#: `gh` options that take a value, so the value is not mistaken for a positional.
_GH_VALUE_FLAGS = frozenset({"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t",
                             "--subject", "-A", "--author-email", "--match-head-commit"})
#: `git` options, before the subcommand, that take a value.
_GIT_VALUE_FLAGS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                              "--exec-path", "--super-prefix", "--config-env"})


def mentions_guarded(command: str) -> bool:
    """Could this string possibly be `gh pr merge` or `git push`? String tests only.

    This is the line that keeps every other command free: nothing is imported, parsed or
    spawned for a command that fails it, so no bug below can refuse or delay one.
    """
    return ("merge" in command and "gh" in command) or ("push" in command and "git" in command)


def reads_as_guarded(command: str) -> bool:
    """The crude reading, used ONLY when `guarded_invocations` has itself raised.

    Whitespace words, no quoting, and deliberately sharing no code with the parser that
    just failed: `gh` whose first words past its options are `pr merge`, or `git` whose
    first word past its options is `push`. It over-reads an unquoted mention
    (`echo git push`), and that is accepted here: the alternative when the parser is
    broken is to wave through the two commands this arm exists for.
    """
    words = command.split()
    for i, word in enumerate(words):
        name = word.rsplit("/", 1)[-1]
        if name not in ("gh", "git"):
            continue
        j = i + 1
        while j < len(words) and words[j].startswith("-"):
            j += 2 if words[j] in ("-C", "-c", "-R", "--repo") else 1
        if name == "gh" and words[j:j + 2] == ["pr", "merge"]:
            return True
        if name == "git" and words[j:j + 1] == ["push"]:
            return True
    return False


def _scan(command: str) -> tuple[list[list[str]], list[str]]:
    """The simple commands in a command line, and the operator that ENDED each.

    The second list is parallel to the first: `&&`, `||`, `|`, `|&`, `;`, `;;`, `&`, a
    newline, `)`, or the empty string for the end of the line. `shell_segments` drops it;
    `discarded_verdict` is what reads it.

    Split at the UNQUOTED separators `;` `&` `|` newline `(` `)`. A single- or
    double-quoted string is one word. A heredoc body is skipped. A `$(...)` or backtick
    substitution is a command of its own -- including inside double quotes, where the shell
    still runs it -- and the word around it carries on afterwards.

    This is not a shell. It does not expand variables, aliases or globs, and it does not
    follow `eval`, `sh -c` or a script: the docstring lists those as not covered.
    """
    segments: list[list[str]] = []
    ops: list[str] = []
    words: list[str] = []
    word: str | None = None
    stack: list[tuple[str, list[str], str | None]] = []   # (kind, outer words, outer word)
    heredocs: list[tuple[str, bool]] = []
    i, n = 0, len(command)

    def end_word() -> None:
        nonlocal word
        if word is not None:
            words.append(word)
            word = None

    def end_segment(op: str = "") -> None:
        nonlocal words
        end_word()
        if words:
            segments.append(words)
            ops.append(op)
        words = []

    def open_sub(kind: str) -> None:
        nonlocal words, word
        stack.append((kind, words, word))
        words, word = [], None

    def close_sub() -> None:
        nonlocal words, word
        end_segment(")")
        _, words, word = stack.pop()

    while i < n:
        c = command[i]
        if stack and stack[-1][0] == "dq":
            if c == "\\" and i + 1 < n:
                word = (word or "") + command[i + 1]
                i += 2
            elif c == '"':
                stack.pop()
                i += 1
            elif c == "$" and command[i + 1:i + 2] == "(":
                open_sub("sub")
                i += 2
            elif c == "`":
                open_sub("bt")
                i += 1
            else:
                word = (word or "") + c
                i += 1
            continue
        if c == "\\":
            if command[i + 1:i + 2] != "\n":                 # a line continuation is nothing
                word = (word or "") + command[i + 1:i + 2]
            i += 2
        elif c == "'":
            end = command.find("'", i + 1)
            end = n if end < 0 else end
            word = (word or "") + command[i + 1:end]
            i = end + 1
        elif c == '"':
            word = word or ""
            stack.append(("dq", words, word))               # nothing to restore; a marker
            i += 1
        elif c == "`":
            if stack and stack[-1][0] == "bt":
                close_sub()
            else:
                open_sub("bt")
            i += 1
        elif c == "$" and command[i + 1:i + 2] == "(":
            open_sub("sub")
            i += 2
        elif c == "(":
            open_sub("sub")
            i += 1
        elif c == ")":
            if stack and stack[-1][0] == "sub":
                close_sub()
            else:
                end_segment(")")
            i += 1
        elif c == "&" and (command[i + 1:i + 2] == ">" or (word and word[-1] in "<>")):
            word = (word or "") + c                          # `2>&1`, `&>file`: a redirection
            i += 1
        elif c in ";&|":
            op = command[i:i + 2] if command[i:i + 2] in ("&&", "||", "|&", ";;") else c
            end_segment(op)
            i += len(op)
        elif c == "\n":
            end_segment("\n")
            i += 1
            for delimiter, strip_tabs in heredocs:           # skip each pending body
                while i < n:
                    end = command.find("\n", i)
                    end = n if end < 0 else end
                    line = command[i:end]
                    i = min(end + 1, n)
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
            heredocs = []
        elif c in " \t\r":
            end_word()
            i += 1
        elif c == "#" and word is None:
            end = command.find("\n", i)
            i = n if end < 0 else end
        elif command.startswith("<<<", i):
            word = (word or "") + "<<<"
            i += 3
        elif command.startswith("<<", i):
            end_word()
            i += 2
            strip_tabs = command[i:i + 1] == "-"
            i += 1 if strip_tabs else 0
            while i < n and command[i] in " \t":
                i += 1
            delimiter = ""
            while i < n and command[i] not in " \t\n;&|()<>":
                if command[i] in "'\"":
                    quote = command[i]
                    end = command.find(quote, i + 1)
                    end = n if end < 0 else end
                    delimiter += command[i + 1:end]
                    i = end + 1
                else:
                    delimiter += command[i + 1:i + 2] if command[i] == "\\" else command[i]
                    i += 2 if command[i] == "\\" else 1
            if delimiter:
                heredocs.append((delimiter, strip_tabs))
        else:
            word = (word or "") + c
            i += 1
    end_segment()
    while stack:                                             # an unclosed quote or paren
        kind, outer_words, outer_word = stack.pop()
        if kind != "dq":                                     # a quote opened no new command
            words, word = outer_words, outer_word
            end_segment()
    return segments, ops


def shell_segments(command: str) -> list[list[str]]:
    """The simple commands in a command line, each as its list of words. See `_scan`."""
    return _scan(command)[0]


def _command_words(words: list[str]) -> list[str]:
    """`words` without what may legally stand in front of the command name."""
    i = 0
    while i < len(words):
        w = words[i]
        name, eq, _ = w.partition("=")
        if w in _WRAPPERS:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 1                                       # `env -i`, `sudo -E`
        elif eq and name and (name[0].isalpha() or name[0] == "_") \
                and name.replace("_", "a").isalnum():
            i += 1                                           # NAME=value
        elif w == "timeout":
            i += 1
            while i < len(words) and (words[i].startswith("-") or words[i][:1].isdigit()):
                i += 1
        else:
            break
    return words[i:]


def _program(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _gh_merge(words: list[str]) -> dict | None:
    positional: list[str] = []
    flags: dict[str, str] = {}
    i = 1
    while i < len(words):
        w = words[i]
        if w.startswith("-"):
            name, eq, value = w.partition("=")
            if eq:
                flags[name] = value
            elif name in _GH_VALUE_FLAGS and i + 1 < len(words):
                flags[name] = words[i + 1]
                i += 1
            else:
                flags[name] = ""
        else:
            positional.append(w)
        i += 1
    if positional[:2] != ["pr", "merge"]:
        return None
    return {"kind": "merge",
            "target": positional[2] if len(positional) > 2 else None,
            "pinned": "--match-head-commit" in flags,
            "pin": flags.get("--match-head-commit", ""),
            "repo": flags.get("--repo") or flags.get("-R") or None}


def _git_push(words: list[str]) -> dict | None:
    i, directory = 1, None
    while i < len(words) and words[i].startswith("-"):
        if words[i] in _GIT_VALUE_FLAGS and i + 1 < len(words):
            if words[i] == "-C":
                directory = words[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(words) or words[i] != "push":
        return None
    args = words[i + 1:]
    refs = [a for a in args if not a.startswith("-")][1:]    # after the remote
    delete = (any(a in ("--delete", "-d") for a in args)
              or (bool(refs) and all(r.startswith(":") for r in refs)))
    return {"kind": "push", "delete": delete, "directory": directory}


#: Commands that may stand before a `git push` in one command line, because they change
#: nothing the push gate reads: they move, or they set the environment.
_BEFORE_A_PUSH = frozenset({"cd", "export", "unset", "set", "true", ":"})


def _changes_nothing(words: list[str]) -> bool:
    program = _program(words[0])
    return program in _BEFORE_A_PUSH or (program == "gh" and words[1:3] == ["auth", "token"])


def guarded_invocations(command: str) -> list[dict]:
    """Every `gh pr merge` and every `git push` this command line itself runs.

    A push also carries `after`: the commands the line runs BEFORE it that could change the
    tree. The push gate is run when the hook fires, which is before the line starts.
    """
    found: list[dict] = []
    moved_to: str | None = None
    earlier: list[str] = []
    for segment in shell_segments(command):
        words = _command_words(segment)
        if not words:
            continue
        program = _program(words[0])
        if program == "cd" and len(words) > 1:
            moved_to = words[1]
        elif program == "gh":
            merge = _gh_merge(words)
            if merge:
                found.append(merge)
        elif program == "git":
            push = _git_push(words)
            if push:
                push["cd"] = moved_to
                push["after"] = list(earlier)
                found.append(push)
        if not _changes_nothing(words):
            earlier.append(" ".join(words[:2]))
    return found


# --- a gate's verdict, discarded on the way to something that depends on it (T-157) -----
# See A DISCARDED VERDICT in the module docstring. String work only: nothing is spawned.

#: Operators that carry a failure forward: what follows runs only if what came before passed.
_KEEPS = ("&&",)
_PIPES = ("|", "|&")
#: Operators after which the next command runs whatever the last one answered.
_DROPS = (";", "\n", "&", "||")
#: A command in one of these positions is being ASKED, and the shell reads its answer.
_CONDITIONS = frozenset({"if", "elif", "while", "until"})
_PY_VALUE_FLAGS = frozenset({"-X", "-W"})
#: Outward `git` subcommands, `gh pr` subcommands, and the two tools that write the canon
#: and the pull request body. A deliberately short list: see the docstring for why.
_GIT_ACTIONS = frozenset({"commit", "push", "merge"})
_GH_PR_ACTIONS = frozenset({"create", "merge", "ready", "edit", "comment", "close", "reopen"})
_CANON_WRITERS = frozenset({"sync_active_pr.py", "stamp_pr_head.py"})


def mentions_discard(command: str) -> bool:
    """Could this line run a gate AND then something that leans on it? String tests only."""
    if "check_" not in command:
        return False
    return (("|" in command and "&&" in command)
            or any(word in command for word in ("commit", "push", "gh ", "git merge",
                                                "sync_active_pr", "stamp_pr_head")))


def _script(words: list[str]) -> str | None:
    """The script file a command runs: `python3 -B tools/x.py` and `tools/x.py` are `x.py`."""
    program = _program(words[0])
    if program.endswith(".py"):
        return program
    if program != "py" and not program.startswith("python"):
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] in ("-c", "-m", "-"):
            return None                                      # no script file is being run
        i += 2 if words[i] in _PY_VALUE_FLAGS else 1
    return _program(words[i]) if i < len(words) else None


def _gate_run(words: list[str]) -> str | None:
    """`check_x.py` when this simple command RUNS that gate, else None."""
    script = _script(words)
    if script and script.startswith("check_") and script.endswith(".py"):
        return script
    return None


def _outward_action(words: list[str]) -> str | None:
    """What this simple command sends out or records, in words, or None."""
    program = _program(words[0])
    if program == "git":
        i = 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in _GIT_VALUE_FLAGS else 1
        if i < len(words) and words[i] in _GIT_ACTIONS:
            return f"git {words[i]}"
        return None
    if program == "gh":
        positional, i = [], 1
        while i < len(words):
            if words[i].startswith("-"):
                i += 2 if (words[i] in _GH_VALUE_FLAGS and "=" not in words[i]) else 1
            else:
                positional.append(words[i])
                i += 1
        if positional[:1] == ["pr"] and positional[1:2] and positional[1] in _GH_PR_ACTIONS:
            return f"gh pr {positional[1]}"
        return None
    script = _script(words)
    return f"tools/{script}" if script in _CANON_WRITERS else None


def discarded_verdict(command: str) -> str | None:
    """The refusal for a line that runs a gate and then does not let its verdict decide.

    Two shapes, both of which ran in this repository and both of which committed or wrote
    on a RED:

      `gate | tail -3 && next`   -- `&&` tests the LAST command of a pipeline, so `next`
                                    runs when the gate failed (unless `pipefail` is set);
      `gate ; git commit`        -- or a newline, `||`, `&`, a pipe: the commit runs
                                    whatever the gate said.

    A gate whose answer the shell itself reads (`if gate; then ...`) is not judged.
    """
    segments, ops = _scan(command)
    pipefail = False
    held: list[str] = []          # gates whose verdict still decides what comes next
    loose: list[str] = []         # gates whose verdict no longer does
    feeding: str | None = None    # a gate upstream in the pipeline being read now
    for raw, op in zip(segments, ops):
        words = _command_words(raw)                          # empty for a bare `FOO=1`
        if words and _program(words[0]) == "set" and "pipefail" in words and "+o" not in words:
            pipefail = True
        action = _outward_action(words) if words else None
        if action and loose:
            return (f"CANONICAL LAW: `{action}` is refused in this command line -- "
                    f"tools/{loose[0]} runs earlier in it, and its verdict does not decide "
                    f"whether `{action}` runs: between the two there is a `;`, a newline, "
                    f"`||`, `&` or a pipe, so `{action}` runs on a RED exactly as on a "
                    f"GREEN.\n\nJoin them with `&&` and nothing else -- "
                    f"`python3 tools/{loose[0]} ... && {action} ...` -- or run the gate in "
                    f"its own call and read what it printed.\n\n{RECOVERY}")
        if feeding and op in _KEEPS:
            return (f"CANONICAL LAW: this command line is refused -- tools/{feeding} is piped "
                    f"into another command and `&&` follows the pipeline. `&&` tests the "
                    f"LAST command of a pipeline (`tail`, `grep`, `tee`), not the gate, so "
                    f"what follows runs when the gate is RED.\n\nRun the gate bare -- "
                    f"`python3 tools/{feeding} ... && next` -- or put `set -o pipefail;` in "
                    f"front of the line.\n\n{RECOVERY}")
        gate = _gate_run(words) if words and raw[0] not in _CONDITIONS else None
        if gate:
            held.append(gate)
        piped = op in _PIPES and not pipefail
        if piped:
            feeding = feeding or gate
            if gate:                                         # only ITS verdict is lost: a
                held.remove(gate)                            # gate held from before still
                loose.append(gate)                           # decides whether this runs
            continue
        feeding = None
        if op in _KEEPS or op in _PIPES:
            continue
        if op in _DROPS:
            loose, held = loose + held, []
        else:                                                # `)`, `;;`: no claim is made
            held = []                                        # about a subshell's status
    return None


def pr_number(target: str | None) -> int | None:
    """The pull request a `gh pr merge` names: `5`, `#5`, or a `.../pull/5` URL."""
    if not target:
        return None
    text = target.strip().rstrip("/")
    if "/pull/" in text:
        text = text.rsplit("/pull/", 1)[1].split("/", 1)[0]
    text = text.lstrip("#")
    return int(text) if text.isdigit() and int(text) > 0 else None


def run_gate(script: str, args: list[str]) -> tuple[int, str]:
    """Run one gate from THIS checkout's tools/ and return `(exit code, what it printed)`.

    Raises on a timeout or a gate that cannot be started; the caller turns that into a
    refusal. Replaced in the tests, which is why it is a module-level name.
    """
    import subprocess
    done = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools" / script), *args],
                          cwd=str(ROOT), capture_output=True, timeout=GATE_TIMEOUT)
    text = ((done.stdout or b"") + (done.stderr or b"")).decode("utf-8", errors="replace")
    return done.returncode, text.strip()


def _git_answer(directory: pathlib.Path, *args: str) -> str | None:
    import subprocess
    try:
        done = subprocess.run(["git", "-C", str(directory), *args],
                              capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001 - no answer is an answer the caller handles
        return None
    return (done.stdout or "").strip() if done.returncode == 0 else None


def _common_dir(directory: pathlib.Path) -> pathlib.Path | None:
    """The git directory a checkout shares with its worktrees, or None."""
    out = _git_answer(directory, "rev-parse", "--git-common-dir")
    if not out:
        return None
    try:
        return (directory / out).resolve()
    except OSError:
        return None


def push_checkout(inv: dict, data: dict) -> pathlib.Path | None:
    """The checkout a `git push` sends from; None when it is a DIFFERENT repository.

    A worktree of this repository shares its git directory and is judged, as the tree it
    is. A directory that cannot be resolved -- `cd "$DIR"`, a path that is not a
    repository -- falls back to this checkout: not being able to tell is not being told
    it is somebody else's.
    """
    here = pathlib.Path(str(data.get("cwd") or ROOT))
    for step in (inv.get("cd"), inv.get("directory")):
        if step:
            here = here / pathlib.Path(step).expanduser()
    top = _git_answer(here, "rev-parse", "--show-toplevel")
    theirs, ours = _common_dir(here), _common_dir(ROOT)
    if not top or theirs is None or ours is None:
        return ROOT
    return pathlib.Path(top) if theirs == ours else None


def is_this_repository(slug: str | None) -> bool:
    """Whether `-R owner/name` names this clone's origin. Unknown counts as yes."""
    if not slug:
        return True
    url = _git_answer(ROOT, "remote", "get-url", "origin")
    if not url:
        return True
    ours = url.strip().removesuffix(".git").replace(":", "/").split("/")[-2:]
    theirs = slug.strip().removesuffix(".git").replace(":", "/").split("/")[-2:]
    return [p.lower() for p in ours] == [p.lower() for p in theirs]


def _gate_verdict(script: str, args: list[str]) -> tuple[bool, str]:
    """`(green, text)`. GREEN needs BOTH exit 0 and the word: an empty or half-written
    gate that exits 0 has not said yes."""
    try:
        code, output = run_gate(script, args)
    except Exception as exc:  # noqa: BLE001 - a gate that did not answer has not said yes
        return False, (f"tools/{script} did not give a verdict: {type(exc).__name__}: {exc}. "
                       f"It crashed, timed out or is missing, and that is not a pass.")
    if code == 0 and "GREEN" in output:
        return True, output
    if "RED" not in output:
        output = (f"tools/{script} exited {code} without a verdict -- it crashed, or printed "
                  f"usage. That is not a pass.\n\n{output}")
    return False, output


def merge_problem(inv: dict) -> tuple[str | None, str | None]:
    """`(refusal, note)` for one `gh pr merge`."""
    if not is_this_repository(inv.get("repo")):
        return None, (f"CANONICAL LAW: `gh pr merge` names {inv['repo']}, which is not this "
                      f"repository. It was NOT judged by tools/{MERGE_GATE}.")
    number = pr_number(inv.get("target"))
    if number is None:
        return (f"CANONICAL LAW: `gh pr merge` is refused -- it does not name the pull request "
                f"by number (got {inv.get('target')!r}), so there is nothing to check it "
                f"against.\n\n  python3 tools/{MERGE_GATE} --pr <N>\n\nprints the exact "
                f"command to run when it is GREEN.\n\n{RECOVERY}"), None
    args = ["--pr", str(number)]
    if inv.get("repo"):
        args += ["--repo", str(inv["repo"])]
    if inv.get("pin"):
        args += ["--expect-head", str(inv["pin"])]
    green, output = _gate_verdict(MERGE_GATE, args)
    if not inv.get("pinned") or not inv.get("pin"):
        return (f"CANONICAL LAW: `gh pr merge {number}` is refused -- it carries no "
                f"`--match-head-commit <sha>`, so it would merge whatever head is there when "
                f"GitHub gets to it rather than the head the checks passed on.\n\n"
                f"tools/{MERGE_GATE} --pr {number} says:\n\n{output}\n\n{RECOVERY}"), None
    if not green:
        return (f"CANONICAL LAW: `gh pr merge {number}` is refused until "
                f"tools/{MERGE_GATE} --pr {number} is GREEN.\n\n{output}\n\n{RECOVERY}"), None
    return None, None


def push_problem(inv: dict, data: dict) -> tuple[str | None, str | None]:
    """`(refusal, note)` for one `git push`."""
    if inv.get("delete"):
        return None, None
    if inv.get("after"):
        shown = ", ".join(f"`{name}`" for name in inv["after"][:4])
        return (f"CANONICAL LAW: `git push` is refused in this command line -- it runs after "
                f"{shown}. tools/{PUSH_GATE} is run when this hook fires, which is BEFORE the "
                f"line starts, so it would judge the tree as it is now and not the one the "
                f"push sends. On 2026-10-02 a banner was written, committed and pushed in one "
                f"line and went out 47 bytes over its budget with the gate GREEN.\n\n"
                f"Run what comes before the push in one call, and `git push` first in the "
                f"next (`cd`, `export` and `gh auth token` may stand before it).\n\n"
                f"{RECOVERY}"), None
    checkout = push_checkout(inv, data)
    if checkout is None:
        return None, ("CANONICAL LAW: this `git push` is in a different repository. It was "
                      f"NOT judged by tools/{PUSH_GATE}.")
    green, output = _gate_verdict(PUSH_GATE, ["--root", str(checkout)])
    if not green:
        return (f"CANONICAL LAW: `git push` is refused until tools/{PUSH_GATE} is GREEN for "
                f"{checkout}.\n\n{output}\n\n{RECOVERY}"), None
    unrun = [line.strip() for line in output.splitlines() if "COULD NOT RUN" in line]
    if unrun:
        return None, ("CANONICAL LAW: the push is allowed, and one gate CI runs could not be "
                      "run here -- it is NOT a pass:\n  " + "\n  ".join(unrun))
    return None, None


def handle_pre_shell(data: dict) -> None:
    """Refuse `gh pr merge` and `git push` unless their gate is GREEN, and a line that
    throws a gate's verdict away on the way to an outward action; touch nothing else."""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return
    if mentions_discard(command):
        try:
            refusal = discarded_verdict(command)
        except Exception:  # noqa: BLE001 - this rule never refuses on its own bug
            refusal = None
        if refusal:
            deny(refusal)
            return
    if not mentions_guarded(command):
        return                                   # every other command ends here, untouched

    try:
        found = guarded_invocations(command)
    except Exception as exc:  # noqa: BLE001 - see HOW IT FAILS in the module docstring
        if reads_as_guarded(command):
            deny("CANONICAL LAW: this command reads as `gh pr merge` or `git push`, and the "
                 f"hook could not parse it to be sure ({type(exc).__name__}: {exc}). It is "
                 f"refused rather than waved through. Run the gate by hand -- "
                 f"tools/{MERGE_GATE} --pr <N> or tools/{PUSH_GATE} -- and fix "
                 f".claude/hooks/canonical_law_gate.py.\n\n{RECOVERY}")
        return

    notes: list[str] = []
    for inv in found:
        try:
            refusal, note = (merge_problem(inv) if inv["kind"] == "merge"
                             else push_problem(inv, data))
        except Exception as exc:  # noqa: BLE001 - it IS one of the two, so no answer refuses
            what = "gh pr merge" if inv.get("kind") == "merge" else "git push"
            refusal, note = (f"CANONICAL LAW: `{what}` is refused -- the hook failed while "
                             f"judging it ({type(exc).__name__}: {exc}), and a command of "
                             f"this kind is not allowed on no answer.\n\n{RECOVERY}"), None
        if refusal:
            deny(refusal)
            return
        if note:
            notes.append(note)
    if notes:
        context("PreToolUse", "\n\n".join(notes))


def handle_pre_tool(data: dict, receipt_store, roadmap, prior_art, sid: str) -> None:
    tool = str(data.get("tool_name") or "")
    if tool not in EDIT_TOOLS:
        return
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    raw_target = target_path(tool_input)
    rel = relative(raw_target) if raw_target else None

    notes: list[str] = []
    # 1) receipt -- auto-refresh, handing over what changed.
    ok, why = receipt_store.verify(ROOT, sid)
    if not ok:
        previous = receipt_store.load(ROOT, sid) or {}
        before = previous.get("paths") if isinstance(previous.get("paths"), dict) else {}
        try:
            after = receipt_store.canonical_hashes(ROOT)
        except receipt_store.ReceiptError as exc:
            deny(f"CANONICAL LAW: the canonical set itself is broken: {exc}. Fix the manifest or "
                 "restore the missing document before editing anything.")
            return
        changed = sorted(rel_ for rel_ in after if after[rel_] != before.get(rel_))
        receipt_store.record(ROOT, sid)
        notes.append("CANONICAL LAW: your full-read receipt was stale (" + why + "). It has been "
                     "refreshed. These canonical documents are not what you last read -- their "
                     "current text follows, take it before you continue:\n"
                     + canonical_text(receipt_store, changed))

    # 2) roadmap order.
    declared_ok, declared_why = roadmap.verify_declaration(ROOT, sid)
    if not declared_ok:
        deny("CANONICAL LAW: " + declared_why)
        return

    # 3) meta scope.
    if rel:
        scope = roadmap.scope_problem(ROOT, sid, rel)
        if scope:
            deny("CANONICAL LAW: " + scope)
            return

    # 4) prior art, for a file that does not exist yet.
    if rel and not (ROOT / rel).exists():
        art_ok, art_why = prior_art.verify(ROOT, sid, rel)
        if not art_ok:
            deny("CANONICAL LAW: " + art_why)
            return

    # 5) canon budget -- the only refusal in this file that can only be satisfied
    #    by removing text rather than adding it.
    problem = canon_budget_problem(rel, tool, tool_input)
    if problem:
        deny("CANONICAL LAW: " + problem)
        return

    if notes:
        context("PreToolUse", "\n\n".join(notes))


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    data = payload()
    if disabled():
        if event == "session-start":
            context("SessionStart", "CANONICAL LAW is DISABLED for this session "
                                    "(CANONICAL_LAW=off). No read receipt, no phase order, no "
                                    "prior-art check is being enforced.")
        return 0

    # The shell arm goes FIRST, before the imports below: a shell command that is not one
    # of the two named ones must cost nothing, and must not be exposed to anything that can
    # fail on its behalf -- a broken receipt store is not `ls`'s problem.
    if event == "pre-tool" and str(data.get("tool_name") or "") in SHELL_TOOLS:
        handle_pre_shell(data)
        return 0

    import check_prior_art as prior_art
    import check_read_receipt as receipt_store
    import check_roadmap_order as roadmap

    sid = receipt_store.session_id(str(data.get("session_id") or "") or None)

    if event in {"session-start", "subagent-start"}:
        hook = "SessionStart" if event == "session-start" else "SubagentStart"
        receipt = receipt_store.record(ROOT, sid)
        baseline_shell_state(sid)
        open_phase = roadmap.first_open_phase(ROOT)
        structural = roadmap.structural_problems(ROOT)
        header = (
            "CANONICAL STARTUP READ (enforced, not requested). The full text of every path in "
            f"{receipt_store.MANIFEST} follows. A content-bound receipt over "
            f"{len(receipt['paths'])} files / {receipt['canonical_bytes']} bytes "
            f"(digest {receipt['canonical_digest'][:12]}) is recorded for this session; it stops "
            "verifying the moment any of them changes.\n\n"
            f"ROADMAP ORDER: the first phase whose Definition of Done is not fully checked is "
            f"Phase {open_phase}. You may not edit anything until you declare the phase you are "
            "working:\n"
            f"    python tools/check_roadmap_order.py --declare {open_phase} --note \"<what you "
            "are doing>\"\n"
            "    python tools/check_roadmap_order.py --declare meta --note \"<governance/tooling "
            "work>\"\n"
            "Declaring a later phase while this one is open is REFUSED by name.\n\n"
            "BEFORE BUILDING ANYTHING NEW: establish it does not already exist, and record it:\n"
            "    python tools/check_prior_art.py --declare <path> --searched \"...\" "
            "--found \"...\" --decision \"extend:<path>|new:<why>\"\n\n"
            "WHEN YOU COMMIT: code and canon move together --\n"
            "    python tools/check_canonical_sync.py --staged\n")
        if structural:
            header += ("\nWARNING: the roadmap's own completion state is self-inconsistent, so "
                       "phase order cannot be enforced until it is fixed:\n  - "
                       + "\n  - ".join(structural[:5]) + "\n")
        context(hook, header + canonical_text(receipt_store))
        return 0

    if event == "prompt":
        ok, _ = receipt_store.verify(ROOT, sid)
        if not ok:
            receipt_store.record(ROOT, sid)
        context("UserPromptSubmit",
                owner_contract()
                + "\n\n---\n" + session_status(receipt_store, roadmap, sid)
                + "\n" + fast_gate_line()
                + stall_line(sid))
        return 0

    if event == "pre-tool":
        handle_pre_tool(data, receipt_store, roadmap, prior_art, sid)
        return 0

    if event == "post-tool":
        handle_post_tool(data, roadmap, prior_art, sid)
        return 0

    return 0


if __name__ == "__main__":
    event_name = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        # FAIL OPEN, LOUDLY. See the module docstring: a malfunctioning wall that
        # denies every edit cannot be repaired, because repairing it means editing it.
        # Policy denials above are fail-closed; only gate BUGS land here.
        detail = f"{type(exc).__name__}: {exc}".encode("ascii", "backslashreplace").decode("ascii")
        hook = {"pre-tool": "PreToolUse", "post-tool": "PostToolUse",
                "prompt": "UserPromptSubmit"}.get(event_name, "SessionStart")
        try:
            context(hook, f"CANONICAL LAW GATE FAILED OPEN: {detail}. The wall did not run for "
                          "this call. Fix .claude/hooks/canonical_law_gate.py before trusting any "
                          "of its guarantees.")
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(0)
