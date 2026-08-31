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

WHY THE PreToolUse GAP IS PINNED RATHER THAN CLOSED
---------------------------------------------------
Deciding which paths a shell command writes is undecidable in general. `SHELL_WRITE_FORMS`
below is the evidence: every entry writes the same protected path, and a PreToolUse
classifier would have to defeat all of them plus the ones nobody has thought of, while
still waving through the read-only greps every agent here lives on. So `Bash` is NOT added
to the PreToolUse matcher, and `TheGapDemonstrated` pins that: those assertions stay true.

WHAT T-053 ADDED INSTEAD
------------------------
A root `PostToolUse` hook matched on `Bash|PowerShell|Shell` that asks the decidable
question -- what changed on disk -- and fails the turn when a changed path is one the
session may not write. `TheContainment` below tests it.

Say what it is: DETECTION PLUS HALTING THE TURN, NOT CONTAINMENT. The write has already
landed and nothing undoes it. The engine's PostToolUse path is the same shape and the same
limit: `bro_hook.py:148-177` settles a lease and emits `{"decision":"block"}`; there is no
revert, unlink or restore anywhere in it. A security model that claims containment from
either one is claiming something neither does.
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

    def test_bash_is_seen_AFTER_the_fact_and_never_before_it(self):
        """The shape of the root wall in one assertion, both halves.

        Before T-053 this asserted that no root event saw Bash at all, and named itself
        as the assertion a containment change would turn red. It did. What replaces it is
        the same claim made precisely: Bash is absent from PreToolUse ON PURPOSE, because
        a reliable pre-execution shell path-check is not possible, and present at
        PostToolUse, where the decidable question can be asked.

        Adding Bash to PreToolUse turns this red, which is still the point.
        """
        self.assertNotIn("Bash", self.settings["PreToolUse"][0])
        self.assertNotEqual(self.settings["PreToolUse"], ["*"])
        self.assertEqual(self.settings["PostToolUse"], ["Bash|PowerShell|Shell"])
        # There is still no PostToolUseFailure at the root: a shell command that FAILED
        # may still have written before it failed. Named as a known hole rather than
        # implied to be covered.
        self.assertNotIn("PostToolUseFailure", self.settings)

    def test_the_post_tool_hook_is_the_same_program_as_the_pre_tool_one(self):
        """One file, one set of predicates. Two copies would let the tool that wrote a
        file decide whether the rule applied, which is the defect being closed."""
        settings = load(ROOT_SETTINGS)["hooks"]
        commands = {event: settings[event][0]["hooks"][0]["command"]
                    for event in ("PreToolUse", "PostToolUse")}
        for event, argument in (("PreToolUse", "pre-tool"), ("PostToolUse", "post-tool")):
            with self.subTest(event=event):
                self.assertIn("canonical_law_gate.py", commands[event])
                self.assertTrue(commands[event].rstrip().endswith(argument), commands[event])
        self.assertNotIn("bro_hook.py", " ".join(commands.values()))


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


class TheContainment(unittest.TestCase):
    """The PostToolUse settlement, driven against the real hook and the real tree.

    Every case here runs the hook exactly as `.claude/settings.json` runs it, on a session
    id that exists only for the test, and asserts on the verdict it printed.
    """

    def setUp(self):
        self.sid = f"t053-containment-{os.getpid()}-{self._testMethodName}"
        subprocess.run([sys.executable, str(TOOLS / "check_read_receipt.py"),
                        "--session", self.sid, "--record"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
        subprocess.run([sys.executable, str(TOOLS / "check_roadmap_order.py"),
                        "--session", self.sid, "--declare", "meta", "--note",
                        "T-053 self-test of the post-tool shell settlement, driving the "
                        "real hook against a scratch path in the real tree"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)

    def settle(self, command: str = "ls") -> tuple[int, str]:
        return run_hook("post-tool", {"session_id": self.sid, "tool_name": "Bash",
                                      "tool_input": {"command": command}})

    def test_a_non_shell_tool_is_not_this_handlers_business(self):
        """The shell-tool FILTER must be what decides this, so the tree is left in the
        state that WOULD block: dirty at an out-of-scope path. The first version of this
        test probed a clean tree and passed with the filter deleted -- caught by the
        mutation sweep, which is the whole reason the sweep is run.
        """
        self.settle()          # baseline
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            # Same payload, same dirty tree; only the tool name differs.
            _, ignored = run_hook("post-tool", {
                "session_id": self.sid, "tool_name": "Edit",
                "tool_input": {"command": f"echo x >> {PROTECTED}"}})
            _, judged = run_hook("post-tool", {
                "session_id": self.sid, "tool_name": "Bash",
                "tool_input": {"command": f"echo x >> {PROTECTED}"}})
        finally:
            target.write_bytes(original)
        self.assertEqual(ignored, "", "a non-shell tool was settled by the shell handler")
        self.assertEqual(decision(judged), "block", judged)

    def test_a_shell_call_that_changed_nothing_is_allowed(self):
        self.settle()          # baseline
        _, out = self.settle()
        self.assertEqual(out, "", out)

    def test_a_shell_write_to_a_path_outside_scope_blocks_the_turn(self):
        """The bypass, closed after the fact. A `meta` session writes product code
        through a shell redirect; the settlement names the path and the reason."""
        self.settle()          # baseline
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            _, out = self.settle(f"echo x >> {PROTECTED}")
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(out), "block", out)
        self.assertIn(PROTECTED, out)
        self.assertIn("declared `meta`", out)
        self.assertIn("ALREADY LANDED", out)

    def test_it_keeps_reporting_while_the_violation_stands(self):
        """A gate that reports once and forgets is a notification. The violating path is
        deliberately left out of the baseline so it is still there next call."""
        self.settle()
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            self.settle(f"echo x >> {PROTECTED}")
            _, again = self.settle("ls")
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(again), "block", again)

    def test_reverting_the_path_clears_the_report(self):
        """Satisfiable, which is the other half of fail-closed: a gate nobody can clear
        gets switched off."""
        self.settle()
        target = ROOT / PROTECTED
        original = target.read_bytes()
        with target.open("ab") as handle:
            handle.write(b"\n// T-053 self-test\n")
        self.settle(f"echo x >> {PROTECTED}")
        target.write_bytes(original)
        _, out = self.settle("ls")
        self.assertEqual(out, "", out)

    def test_a_path_the_declaration_DOES_own_is_allowed(self):
        """The false-positive control, and it earned its place: the first cut treated any
        edit of a clean TRACKED file as a new file and demanded a prior-art search for it.
        Found by running the thing, not by reading it."""
        self.settle()
        target = TOOLS / "check_no_lstrip_prefix.py"
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n# T-053 self-test\n")
            _, out = self.settle("echo x >> tools/check_no_lstrip_prefix.py")
        finally:
            target.write_bytes(original)
        self.assertEqual(out, "", out)

    def test_a_new_untracked_file_needs_a_prior_art_search(self):
        self.settle()
        target = TOOLS / "t053_selftest_scratch.py"
        try:
            target.write_text("x = 1\n", encoding="utf-8")
            _, out = self.settle("printf x > tools/t053_selftest_scratch.py")
        finally:
            target.unlink(missing_ok=True)
        self.assertEqual(decision(out), "block", out)
        self.assertIn("prior-art search", out)

    def test_an_UNDECLARED_session_is_blocked_for_any_changed_path(self):
        """The branch every other test in this class walks past.

        `setUp` declares `meta`, so the "no declaration at all" arm was reachable by
        nothing until the mutation sweep said so: deleting it left the suite GREEN. An
        undeclared session has no scope to test a path against, so EVERY changed path is
        a violation, including one inside `tools/`.
        """
        sid = f"t053-undeclared-{os.getpid()}"
        first = run_hook("post-tool", {"session_id": sid, "tool_name": "Bash",
                                       "tool_input": {"command": "ls"}})[1]
        self.assertEqual(first, "", "the baseline call should never block")

        target = TOOLS / "check_no_lstrip_prefix.py"
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n# T-053 self-test\n")
            _, out = run_hook("post-tool", {"session_id": sid, "tool_name": "Bash",
                                            "tool_input": {"command": "echo x >> tools/x"}})
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(out), "block", out)
        self.assertIn("phase declaration", out)

    def test_the_first_shell_call_baselines_a_dirty_tree_rather_than_blaming_it(self):
        """A session that starts on a dirty tree did not make it dirty."""
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            _, out = self.settle("ls")       # the FIRST call for this session id
        finally:
            target.write_bytes(original)
        self.assertEqual(out, "", out)


class TheContainmentUnits(unittest.TestCase):
    """The pure parts, without driving a subprocess."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
        try:
            import canonical_law_gate as wall
        finally:
            sys.path.pop(0)
        self.wall = wall

    def test_the_shell_tool_set_matches_what_the_settings_wire(self):
        matcher = json.loads(ROOT_SETTINGS.read_text(encoding="utf-8"))
        block = matcher["hooks"]["PostToolUse"][0]
        self.assertEqual(set(block["matcher"].split("|")), self.wall.SHELL_TOOLS)

    def test_shell_tools_and_edit_tools_are_disjoint(self):
        """A tool refused in advance AND settled afterwards would be judged twice."""
        self.assertEqual(self.wall.SHELL_TOOLS & self.wall.EDIT_TOOLS, set())

    def test_dirty_fingerprints_carries_the_porcelain_code(self):
        """`??` is what makes a path new; without the code in the value the gate called
        every edit of a clean tracked file a new file."""
        state = self.wall.dirty_fingerprints()
        self.assertIsNotNone(state)
        for rel, value in state.items():
            with self.subTest(rel=rel):
                self.assertRegex(value, r"^.{2}:")

    def test_a_tree_git_cannot_be_asked_about_is_not_a_pass(self):
        """The gate says so in the context rather than staying silent."""
        source = (ROOT / ".claude" / "hooks" / "canonical_law_gate.py").read_text(encoding="utf-8")
        self.assertIn("was NOT settled against the tree. Not a pass.", source)

    def test_the_docstring_states_the_limit_in_the_required_words(self):
        """The Owner asked for the honest form of this claim in those words; a security
        model that says 'containment' about either wall is overstating both."""
        source = (ROOT / ".claude" / "hooks" / "canonical_law_gate.py").read_text(encoding="utf-8")
        self.assertIn("A RELIABLE PreToolUse SHELL PATH-CHECK IS NOT POSSIBLE", source)
        self.assertIn("DETECTION PLUS\n  HALTING THE TURN -- NOT CONTAINMENT", source)


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
