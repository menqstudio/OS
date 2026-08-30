#!/usr/bin/env python3
"""The root wall does not see Bash. This file proves it, and is the regression guard.

Run: python -m unittest test_wall_bash_gap   (from tools/)

WHAT IS ACTUALLY TRUE, measured -- and the distinction matters more than the headline
-----------------------------------------------------------------------------------
There are two `.claude/settings.json` files in this repository and only one of them is
the ROOT wall:

    .claude/settings.json         PreToolUse  matcher='Edit|Write|MultiEdit|NotebookEdit'
                                  SessionStart / SubagentStart / UserPromptSubmit / Stop
                                  (no matcher, so no tool filter applies to them)
    engine/.claude/settings.json  PreToolUse  matcher='*'          <- DOES see Bash
                                  PostToolUse / PostToolUseFailure matcher='Bash|PowerShell|Shell'
                                  SessionStart / UserPromptSubmit / SubagentStart /
                                  SubagentStop / Stop / InstructionsLoaded (no matcher)

So the honest claim is NOT "the wall is bypassable through Bash". The ENGINE's
enforcement wall matches `*` and does see every Bash call. What is bypassable is the
ROOT COORDINATION GATE -- `.claude/hooks/canonical_law_gate.py` -- and precisely these
four protections it provides, each of which this file demonstrates is simply not
consulted for a shell command:

  1. phase declaration      (has this session declared a roadmap phase at all?)
  2. meta scope             (may a `meta` session write THIS path?)
  3. prior art              (does a NEW file have a recorded prior-art search?)
  4. canon budget           (while a canonical document is over its ceiling, only a
                             shrinking edit is accepted)

and the read-receipt refresh that runs beside them.

The gap is not a discovery. `canonical_law_gate.py`'s own module docstring names it as
the first of "THE THREE HONEST LIMITS" and names its backstop: `check_canonical_sync`
at commit and in CI, over whatever landed, however it was written. What had never been
written down is that the backstop covers a DIFFERENT property -- it asks whether code
and canon moved together, and cannot ask whether the session had the right to write
that path. Scope, prior art and the shrink-only budget rule have no CI equivalent,
because they are properties of the SESSION and CI has no session.

WHY THIS IS A TEST AND NOT A FIX
--------------------------------
Deciding which paths a shell command writes is undecidable in general. `SHELL_WRITE_FORMS`
below is the evidence: every entry writes the same protected path, and a PreToolUse
classifier would have to defeat all of them plus the ones nobody has thought of. The
recommended containment is therefore content-based and after the fact -- see the T-053
report. This file pins the CURRENT boundary so that closing it is a visible, deliberate
edit to a named assertion rather than a silent change in what the wall covers.

`test_the_root_wall_sees_no_bash_call_at_any_event` is the assertion a containment
change is EXPECTED to turn red. That is deliberate: it is what makes the change visible.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import unittest

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
ROOT_SETTINGS = ROOT / ".claude" / "settings.json"
ENGINE_SETTINGS = ROOT / "engine" / ".claude" / "settings.json"
HOOK = ROOT / ".claude" / "hooks" / "canonical_law_gate.py"

#: The four tools the root PreToolUse matcher names, as of the head that added this file.
ROOT_PRE_TOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"

#: A path only a correctly-declared session should be able to write. `apps/desktop/**` is
#: outside `meta` scope and outside every governance prefix.
PROTECTED = "apps/desktop/src/App.tsx"

#: Every one of these writes PROTECTED. None is refused by the root wall, because the
#: wall is never asked. They are listed rather than summarised because they are the
#: specification any future PreToolUse shell classifier would have to satisfy -- and the
#: argument that it cannot: #6 builds the command at runtime, #7 hides it in an
#: interpreter, #8 puts it behind a second file, #9 behind an environment variable, #10
#: behind a target the hook would have to read a Makefile to resolve.
SHELL_WRITE_FORMS = [
    f"cat > {PROTECTED} <<'EOF'\npwned\nEOF",
    f"echo pwned > {PROTECTED}",
    f"echo pwned | tee {PROTECTED}",
    f"sed -i 's/a/b/' {PROTECTED}",
    f"printf pwned > {PROTECTED}",
    f"sh -c \"$(printf 'echo pwned > %s' {PROTECTED})\"",
    f"python3 -c \"open('{PROTECTED}','w').write('pwned')\"",
    f"./scripts/write.sh   # the script writes {PROTECTED}; the command never names it",
    f"eval \"$WRITE_CMD\"  # resolved from the environment at run time",
    "make deploy          # the target writes it; resolving that needs a Makefile parse",
    f"git checkout other -- {PROTECTED}",
    f"cp /tmp/payload {PROTECTED}",
]


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def matchers(settings: dict) -> dict[str, list]:
    """`{event: [matcher, ...]}`; a block with no `matcher` key contributes `None`."""
    out: dict[str, list] = {}
    for event, blocks in (settings.get("hooks") or {}).items():
        out[event] = [block.get("matcher") for block in blocks]
    return out


def run_hook(event: str, payload: dict) -> tuple[int, str]:
    """Invoke the REAL root hook exactly as `.claude/settings.json` does."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", str(HOOK), event],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=120)
    return result.returncode, result.stdout


def decision(stdout: str) -> str | None:
    """The permission decision in a hook's stdout, or None when it did not render one."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        specific = obj.get("hookSpecificOutput") or {}
        if specific.get("permissionDecision"):
            return specific["permissionDecision"]
        if obj.get("decision"):
            return obj["decision"]
    return None


class RootSettingsWiring(unittest.TestCase):
    """What the ROOT `.claude/settings.json` actually wires. Read it, do not assume it."""

    def setUp(self):
        self.settings = matchers(load(ROOT_SETTINGS))

    def test_pre_tool_use_matcher_is_exactly_the_four_edit_tools(self):
        self.assertEqual(self.settings["PreToolUse"], [ROOT_PRE_TOOL_MATCHER])

    def test_bash_is_absent_from_the_pre_tool_use_matcher(self):
        self.assertNotIn("Bash", ROOT_PRE_TOOL_MATCHER.split("|"))

    def test_the_session_scoped_events_carry_no_matcher(self):
        # No matcher means no tool filter -- these fire once per session/turn, not per tool,
        # so they are not a per-call gate on anything.
        for event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "Stop"):
            with self.subTest(event=event):
                self.assertEqual(self.settings[event], [None])

    def test_the_root_wall_sees_no_bash_call_at_any_event(self):
        """THE GAP, stated as one assertion.

        Every root event either carries a matcher that excludes Bash, or is not a
        per-tool event at all. There is no PostToolUse at the root either, so the root
        has neither containment nor detection for a shell write.

        A containment change is EXPECTED to turn this red. That is the point.
        """
        self.assertNotIn("PostToolUse", self.settings)
        self.assertNotIn("PostToolUseFailure", self.settings)
        per_tool = {e: m for e, m in self.settings.items() if e.endswith("ToolUse")}
        self.assertEqual(list(per_tool), ["PreToolUse"])
        for event, values in per_tool.items():
            for matcher in values:
                with self.subTest(event=event, matcher=matcher):
                    self.assertIsNotNone(matcher)
                    self.assertNotIn("Bash", matcher)
                    self.assertNotEqual(matcher, "*")


class EngineSettingsWiring(unittest.TestCase):
    """The distinction the report must state precisely: the engine's wall DOES see Bash."""

    def setUp(self):
        self.settings = matchers(load(ENGINE_SETTINGS))

    def test_engine_pre_tool_use_matches_everything_including_bash(self):
        self.assertEqual(self.settings["PreToolUse"], ["*"])

    def test_engine_post_tool_use_names_the_shells(self):
        self.assertEqual(self.settings["PostToolUse"], ["Bash|PowerShell|Shell"])
        self.assertEqual(self.settings["PostToolUseFailure"], ["Bash|PowerShell|Shell"])

    def test_engine_session_events_carry_no_matcher(self):
        for event in ("SessionStart", "UserPromptSubmit", "SubagentStart",
                      "SubagentStop", "Stop", "InstructionsLoaded"):
            with self.subTest(event=event):
                self.assertEqual(self.settings[event], [None])

    def test_the_two_walls_are_wired_to_different_programs(self):
        """The engine's settings are addressed to the ENGINE as project root.

        Every engine hook command is `$CLAUDE_PROJECT_DIR/runtime/bro_hook.py`. There is
        no `runtime/` at the repository root, so those commands only resolve for a
        session whose project root IS `engine/`. This is the mechanical half of
        CLAUDE.md §5's "the wall loads from the SESSION's project root": a session opened
        at the repository root cannot be running the engine's wiring, because the file it
        names does not exist there.
        """
        engine_text = ENGINE_SETTINGS.read_text(encoding="utf-8")
        self.assertIn("$CLAUDE_PROJECT_DIR/runtime/bro_hook.py", engine_text)
        self.assertFalse((ROOT / "runtime" / "bro_hook.py").exists())
        self.assertTrue((ROOT / "engine" / "runtime" / "bro_hook.py").exists())

        root_text = ROOT_SETTINGS.read_text(encoding="utf-8")
        self.assertIn("$CLAUDE_PROJECT_DIR/.claude/hooks/canonical_law_gate.py", root_text)
        self.assertNotIn("bro_hook.py", root_text)


class TheHookItself(unittest.TestCase):
    """Even if it WERE wired for Bash, the hook returns before deciding anything."""

    def test_the_hooks_own_tool_set_excludes_every_shell(self):
        source = HOOK.read_text(encoding="utf-8")
        sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
        try:
            import canonical_law_gate as wall
        finally:
            sys.path.pop(0)
        for shell in ("Bash", "PowerShell", "Shell", "BashOutput"):
            with self.subTest(tool=shell):
                self.assertNotIn(shell, wall.EDIT_TOOLS)
        self.assertIn("SHELL IS NOT GATED", source,
                      "the hook no longer documents its own first honest limit")

    def test_every_tool_the_settings_matcher_names_is_one_the_hook_understands(self):
        """The direction that must hold: the hook must handle what it is wired for.

        The reverse does NOT hold and is recorded rather than asserted -- `EDIT_TOOLS`
        also contains `Update`, which the matcher never names, so that entry is dead.
        """
        sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
        try:
            import canonical_law_gate as wall
        finally:
            sys.path.pop(0)
        for tool in ROOT_PRE_TOOL_MATCHER.split("|"):
            with self.subTest(tool=tool):
                self.assertIn(tool, wall.EDIT_TOOLS)


class TheGapDemonstrated(unittest.TestCase):
    """Run the real hook. Same session, same target, two spellings, two answers."""

    SESSION = "t053-proving-test-undeclared-session"

    def payload(self, tool: str, tool_input: dict) -> dict:
        return {"session_id": self.SESSION, "tool_name": tool, "tool_input": tool_input}

    def test_an_edit_by_an_undeclared_session_is_DENIED(self):
        """The positive control. Without this, the Bash result below proves nothing."""
        code, out = run_hook("pre-tool", self.payload(
            "Edit", {"file_path": str(ROOT / PROTECTED),
                     "old_string": "a", "new_string": "b"}))
        self.assertEqual(code, 0)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("has not declared which roadmap phase", out)

    def test_a_write_by_an_undeclared_session_is_DENIED(self):
        code, out = run_hook("pre-tool", self.payload(
            "Write", {"file_path": str(ROOT / PROTECTED), "content": "pwned"}))
        self.assertEqual(decision(out), "deny", out)

    def test_the_same_write_spelled_as_Bash_is_NOT_denied(self):
        """The gap. Identical session, identical target, no verdict at all."""
        code, out = run_hook("pre-tool", self.payload(
            "Bash", {"command": SHELL_WRITE_FORMS[0]}))
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "the hook rendered a verdict for Bash; the gap may be closed")
        self.assertIsNone(decision(out))

    def test_no_shell_form_of_the_same_write_is_denied(self):
        """The undecidability evidence, run rather than argued."""
        for command in SHELL_WRITE_FORMS:
            with self.subTest(command=command):
                _, out = run_hook("pre-tool", self.payload("Bash", {"command": command}))
                self.assertIsNone(decision(out), f"unexpectedly judged: {command}")

    def test_a_read_only_shell_command_is_also_not_judged(self):
        """Stated so the fix is not mistaken for cheap.

        The hook cannot tell this apart from the writes above, which is exactly why
        adding `Bash` to the matcher and classifying the command is the wrong shape: the
        same classifier that must catch every form above must also wave this through, and
        agents in this repository live on read-only greps.
        """
        _, out = run_hook("pre-tool", self.payload(
            "Bash", {"command": "grep -rn lstrip tools/"}))
        self.assertIsNone(decision(out))


class TheNamedBackstop(unittest.TestCase):
    """What the hook's docstring points at, and what it does NOT cover."""

    def test_the_backstop_gate_exists(self):
        self.assertTrue((TOOLS / "check_canonical_sync.py").is_file())

    def test_the_backstop_judges_what_landed_not_which_tool_wrote_it(self):
        """It reads git, so the writing tool is invisible to it -- that is its strength."""
        source = (TOOLS / "check_canonical_sync.py").read_text(encoding="utf-8")
        self.assertNotIn("tool_name", source)
        self.assertIn("git", source)

    def test_the_session_scoped_protections_have_no_CI_equivalent(self):
        """The honest half: three of the four protections cannot be reconstructed in CI.

        `check_roadmap_order.scope_problem` and `check_prior_art.verify` both take a
        session id, and CI has no session -- so a path written outside a session's
        declared scope, or a new file with no prior-art search, is caught by nothing once
        the write goes through Bash. This is asserted on the signatures rather than
        described, so it goes red if either gate ever stops being session-scoped.
        """
        import inspect

        sys.path.insert(0, str(TOOLS))
        try:
            import check_prior_art
            import check_roadmap_order
        finally:
            sys.path.pop(0)
        self.assertIn("sid", inspect.signature(check_roadmap_order.scope_problem).parameters)
        self.assertIn("sid", inspect.signature(check_prior_art.verify).parameters)


if __name__ == "__main__":
    unittest.main()
