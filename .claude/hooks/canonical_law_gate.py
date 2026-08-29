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

THE THREE HONEST LIMITS -- do not read this gate as more than it is
  * SHELL IS NOT GATED. Only Edit/Write/MultiEdit/NotebookEdit are checked. A
    session can write any file through Bash (`>`, `sed -i`, a python one-liner) and
    this hook will not see it. Closing that needs shell-command classification,
    which the engine's own wall documents as unsound (`cat $(rm -rf x)` classifies
    as a read), and which would block the read-only greps other agents live on.
    The backstop is deliberate and elsewhere: check_canonical_sync runs at commit
    and in CI over whatever landed, however it was written.
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
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Update"}
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

    LIMIT, stated rather than hidden: this sees the Edit/Write tools. A shell
    redirect appends without passing through here -- the same "SHELL IS NOT GATED"
    hole this file's own header names -- and `tools/check_canon_budget.py` in CI is
    the backstop for whatever lands.
    """
    if rel is None:
        return None
    try:
        import check_canon_budget as budget
    except Exception:  # noqa: BLE001 - a missing gate must not wedge the session
        return None
    try:
        ceilings = budget.load_json(ROOT, budget.BUDGET_REL).get("per_file_bytes") or {}
    except SystemExit:
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

    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    if isinstance(old, str) and isinstance(new, str):
        delta = len(new.encode("utf-8")) - len(old.encode("utf-8"))
        if delta < 0:
            return None
        return (f"{rel} is {current:,} bytes against a ceiling of {cap:,}, and this edit "
                f"adds {delta:,} more. While a canonical document is over budget the only "
                f"edit that is accepted is one that makes it smaller -- that is the whole "
                f"point of the ceiling: this repository has never lacked a rule that says "
                f"write something, only one that says remove something. Archive the history "
                f"first. `python tools/check_canon_budget.py` names every file and its overage.")
    return None


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

    import check_prior_art as prior_art
    import check_read_receipt as receipt_store
    import check_roadmap_order as roadmap

    sid = receipt_store.session_id(str(data.get("session_id") or "") or None)

    if event in {"session-start", "subagent-start"}:
        hook = "SessionStart" if event == "session-start" else "SubagentStart"
        receipt = receipt_store.record(ROOT, sid)
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
        context("UserPromptSubmit", session_status(receipt_store, roadmap, sid))
        return 0

    if event == "pre-tool":
        handle_pre_tool(data, receipt_store, roadmap, prior_art, sid)
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
        hook = {"pre-tool": "PreToolUse", "prompt": "UserPromptSubmit"}.get(event_name, "SessionStart")
        try:
            context(hook, f"CANONICAL LAW GATE FAILED OPEN: {detail}. The wall did not run for "
                          "this call. Fix .claude/hooks/canonical_law_gate.py before trusting any "
                          "of its guarantees.")
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(0)
