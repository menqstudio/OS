#!/usr/bin/env python3
"""The root wall does not see Bash BEFORE it runs, and settles it after. This file proves
both halves, and is the regression guard.

Run: python -m unittest test_wall_bash_gap   (from tools/)

WHAT IS ACTUALLY TRUE, measured -- and the distinction matters more than the headline
-----------------------------------------------------------------------------------
There are two `.claude/settings.json` files in this repository and only one of them is
the ROOT wall:

    .claude/settings.json         PreToolUse  matcher='Edit|Write|MultiEdit|NotebookEdit'
                                  PreToolUse  matcher='Bash|PowerShell|Shell'   (T-150, two
                                              named commands only -- see below)
                                  PostToolUse matcher='Bash|PowerShell|Shell'   (T-053)
                                  SessionStart / SubagentStart / UserPromptSubmit / Stop
                                  (no matcher, so no tool filter applies to them)
    engine/.claude/settings.json  PreToolUse  matcher='*'          <- DOES see Bash
                                  PostToolUse / PostToolUseFailure matcher='Bash|PowerShell|Shell'
                                  SessionStart / UserPromptSubmit / SubagentStart /
                                  SubagentStop / Stop / InstructionsLoaded (no matcher)

So the honest claim is NOT "the wall is bypassable through Bash". The ENGINE's
enforcement wall matches `*` and does see every Bash call. What is bypassable IN ADVANCE
is the ROOT COORDINATION GATE -- `.claude/hooks/canonical_law_gate.py` -- and precisely
these four protections it provides, each of which this file demonstrates is not consulted
BEFORE a shell command runs (`TheGapDemonstrated`), and is asked afterwards about what the
command left on disk (`TheContainment`):

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
because they are properties of the SESSION and CI has no session. So for a shell write
they are: not refused before the fact, detected after it, and backed by nothing in CI.

WHY THE PreToolUse GAP IS PINNED RATHER THAN CLOSED
---------------------------------------------------
Deciding which paths a shell command writes is undecidable in general. `SHELL_WRITE_FORMS`
below is the evidence: every entry writes the same protected path, and a PreToolUse
classifier would have to defeat all of them plus the ones nobody has thought of, while
still waving through the read-only greps every agent here lives on. So no PreToolUse block
asks what a shell command WRITES, and `TheGapDemonstrated` pins that: those assertions stay
true, and since T-150 they run THROUGH the shell matcher rather than around it.

WHAT T-150 ADDED, WHICH IS A DIFFERENT QUESTION
-----------------------------------------------
A second PreToolUse block, matched on `Bash|PowerShell|Shell`, that refuses exactly two
commands by NAME: `gh pr merge` and a `git push` that is not a delete, each unless its gate
(`tools/check_merge_ready.py`, `tools/check_push_ready.py`) is GREEN. "Is this command line
one of those two" is decidable where "what does it write" is not. `TheTwoNamedCommands`
tests the recogniser in both directions, and `TheTwoNamedCommandsRefused` the refusals --
including that nothing else can be refused by it, whatever breaks inside it.

WHAT T-053 ADDED INSTEAD
------------------------
A root `PostToolUse` hook matched on `Bash|PowerShell|Shell` that asks the decidable
question -- what changed on disk -- and fails the turn when a changed path is one the
session may not write. `TheContainment` below tests it.

Say what it is: DETECTION PLUS HALTING THE TURN, NOT CONTAINMENT. The write has already
landed and nothing undoes it. The engine's PostToolUse path is the same shape and the same
limit: the `post-tool` branch of `bro_hook.py` settles a lease and hands a red settlement to
`_observe_or_block`, which emits `{"decision":"block"}` -- or, in shadow mode, only a
`[SHADOW] would block` note. There is no revert, unlink or restore anywhere in it. A
security model that claims containment from either one is claiming something neither does.
(Cited by name: the line numbers this sentence used to carry were right on the day and
checked by nothing.)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

TOOLS = pathlib.Path(__file__).resolve().parent
ROOT = TOOLS.parent
ROOT_SETTINGS = ROOT / ".claude" / "settings.json"
ENGINE_SETTINGS = ROOT / "engine" / ".claude" / "settings.json"
HOOK = ROOT / ".claude" / "hooks" / "canonical_law_gate.py"

#: The four tools the root PreToolUse EDIT block names, as of the head that added this file.
ROOT_PRE_TOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
#: The second PreToolUse block (T-150): the shells, for two named commands and nothing else.
ROOT_PRE_SHELL_MATCHER = "Bash|PowerShell|Shell"

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


def import_wall():
    """The root hook as a module, for the tests that call its functions directly."""
    sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
    try:
        import canonical_law_gate as wall
    finally:
        sys.path.pop(0)
    return wall


def git(root: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True, text=True, timeout=60)


class _AnySession:
    """A roadmap and a prior-art store that object to nothing, so a test of the budget
    arm is a test of the budget arm."""

    @staticmethod
    def verify_declaration(root, sid):
        return True, "declared"

    @staticmethod
    def scope_problem(root, sid, rel):
        return None

    @staticmethod
    def verify(root, sid, rel):
        return True, "searched"


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

    def test_pre_tool_use_is_the_four_edit_tools_and_then_the_shells(self):
        """Two blocks, in this order, and no third. Until T-150 there was one."""
        self.assertEqual(self.settings["PreToolUse"],
                         [ROOT_PRE_TOOL_MATCHER, ROOT_PRE_SHELL_MATCHER])

    def test_bash_is_absent_from_the_EDIT_block(self):
        # Read from the settings file. This split the constant defined at the top of
        # THIS file, so it could not fail whatever `.claude/settings.json` said.
        self.assertNotIn("Bash", self.settings["PreToolUse"][0].split("|"))

    def test_every_pre_tool_block_runs_the_same_command_line(self):
        """One program, one argument. A shell block wired to a different script, or to
        `post-tool`, would be a second wall with its own idea of the rules."""
        blocks = load(ROOT_SETTINGS)["hooks"]["PreToolUse"]
        commands = {hook["command"] for block in blocks for hook in block["hooks"]}
        self.assertEqual(len(commands), 1, commands)
        self.assertEqual([len(block["hooks"]) for block in blocks], [1, 1])
        self.assertTrue(next(iter(commands)).rstrip().endswith("pre-tool"))

    def test_the_session_scoped_events_carry_no_matcher(self):
        # No matcher means no tool filter -- these fire once per session/turn, not per tool,
        # so they are not a per-call gate on anything.
        for event in ("SessionStart", "SubagentStart", "UserPromptSubmit", "Stop"):
            with self.subTest(event=event):
                self.assertEqual(self.settings[event], [None])

    def test_bash_is_judged_for_what_it_WROTE_only_after_the_fact(self):
        """The shape of the root wall in one assertion, both halves.

        Before T-053 this asserted that no root event saw Bash at all, and named itself
        as the assertion a containment change would turn red. It did. T-053's version
        said "Adding Bash to PreToolUse turns this red, which is still the point" -- and
        T-150 added Bash to PreToolUse and it stayed GREEN, because it read block 0 and
        the shells arrived as block 1. A test that names the change it would catch and
        then does not catch it; recorded here rather than quietly rewritten.

        What is true now, and asserted over EVERY block: the edit block names no shell;
        the only block that does is exactly the three shells; nothing matches `*`. What a
        shell command WROTE is still asked only at PostToolUse. That the shell block
        refuses two named commands and never a path is `TheGapDemonstrated`'s business,
        which runs every write form through it and gets no verdict.
        """
        self.assertNotIn("Bash", self.settings["PreToolUse"][0])
        self.assertNotIn("*", self.settings["PreToolUse"])
        self.assertEqual([m for m in self.settings["PreToolUse"] if "Bash" in m],
                         [ROOT_PRE_SHELL_MATCHER])
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
    """It IS wired for Bash since T-150, and for a shell it never reaches the path
    predicates: `EDIT_TOOLS` is what admits a tool to them, and no shell is in it."""

    def test_the_hooks_own_tool_set_excludes_every_shell(self):
        source = HOOK.read_text(encoding="utf-8")
        wall = import_wall()
        for shell in ("Bash", "PowerShell", "Shell", "BashOutput"):
            with self.subTest(tool=shell):
                self.assertNotIn(shell, wall.EDIT_TOOLS)
        self.assertIn("SHELL IS NOT GATED", source,
                      "the hook no longer documents its own first honest limit")

    def test_the_hooks_edit_tools_are_exactly_what_the_settings_matcher_names(self):
        """Both directions. The hook must handle what it is wired for, and it must not
        carry a tool the matcher never delivers: `EDIT_TOOLS` held `Update` for months,
        an entry no event could reach, recorded here as dead instead of removed.
        """
        wall = import_wall()
        wired = matchers(load(ROOT_SETTINGS))["PreToolUse"][0].split("|")
        self.assertEqual(set(wired), wall.EDIT_TOOLS)

    def test_the_hooks_shell_tools_are_exactly_what_the_pre_tool_shell_block_names(self):
        """The same, for the T-150 block: a shell the matcher delivers and the hook does
        not know falls through to the EDIT arm, which returns for it -- silently unguarded."""
        wall = import_wall()
        wired = matchers(load(ROOT_SETTINGS))["PreToolUse"][1].split("|")
        self.assertEqual(set(wired), wall.SHELL_TOOLS)


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
        # A uuid, not the pid: the hook keeps a baseline file per session id in the temp
        # directory, and a REUSED pid inherited the last run's -- which turned the "first
        # call" below into a second one.
        self.sid = f"t053-containment-{uuid.uuid4().hex}-{self._testMethodName}"
        self.sessions = [self.sid]
        recorded = subprocess.run([sys.executable, str(TOOLS / "check_read_receipt.py"),
                                   "--session", self.sid, "--record"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        declared = subprocess.run(
            [sys.executable, str(TOOLS / "check_roadmap_order.py"),
             "--session", self.sid, "--declare", "meta", "--note",
             "T-053 self-test of the post-tool shell settlement, driving the "
             "real hook against a scratch path in the real tree"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(declared.returncode, 0, declared.stdout + declared.stderr)

    def tearDown(self):
        wall = import_wall()
        with mock.patch.object(wall, "ROOT", ROOT):
            for sid in self.sessions:
                wall._shell_state_path(sid).unlink(missing_ok=True)

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
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            _, reported = self.settle(f"echo x >> {PROTECTED}")
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(reported), "block", reported)
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
        sid = f"t053-undeclared-{uuid.uuid4().hex}"
        self.sessions.append(sid)
        first = run_hook("post-tool", {"session_id": sid, "tool_name": "Bash",
                                       "tool_input": {"command": "ls"}})[1]
        self.assertIsNone(decision(first), "the baseline call should never block")

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
        """A session that starts on a dirty tree did not make it dirty -- and a call
        that was used as the baseline says it judged nothing, rather than passing in
        silence: whatever that call itself wrote has just been forgiven unseen."""
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            _, out = self.settle("ls")       # the FIRST call for this session id
        finally:
            target.write_bytes(original)
        self.assertIsNone(decision(out), out)
        self.assertIn("had no shell baseline", out)
        self.assertIn("Not a pass.", out)

    def test_a_session_baselined_at_its_START_is_judged_on_its_first_shell_call(self):
        """The hole the first-call baseline left: write first, be clean ever after.

        The start hook now records the baseline, so the first shell call is compared
        against the tree the session STARTED on. Driven through the real `subagent-start`
        event, the same program `.claude/settings.json` wires.
        """
        code, _ = run_hook("subagent-start", {"session_id": self.sid})
        self.assertEqual(code, 0)
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            _, out = self.settle(f"echo x >> {PROTECTED}")   # the FIRST shell call
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(out), "block", out)
        self.assertIn(PROTECTED, out)

    def test_a_second_start_event_does_not_forgive_what_was_written_since(self):
        """SubagentStart carries the PARENT's session id, and SessionStart fires again on
        resume: a start hook that re-baselined would launder every write before it."""
        run_hook("subagent-start", {"session_id": self.sid})
        target = ROOT / PROTECTED
        original = target.read_bytes()
        try:
            with target.open("ab") as handle:
                handle.write(b"\n// T-053 self-test\n")
            run_hook("subagent-start", {"session_id": self.sid})
            _, out = self.settle("ls")
        finally:
            target.write_bytes(original)
        self.assertEqual(decision(out), "block", out)


class TheContainmentUnits(unittest.TestCase):
    """The pure parts, without driving a subprocess."""

    def setUp(self):
        self.wall = import_wall()

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
        # A tree KNOWN to be dirty. This looped over the live checkout's dirty set, which
        # is empty on a clean tree -- CI's state -- so it asserted nothing where it ran.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            git(root, "init", "-q")
            (root / "tracked.txt").write_bytes(b"one\n")
            git(root, "add", "tracked.txt")
            git(root, "commit", "-q", "-m", "seed")
            (root / "tracked.txt").write_bytes(b"two\n")
            (root / "fresh.txt").write_bytes(b"new\n")
            with mock.patch.object(self.wall, "ROOT", root):
                state = self.wall.dirty_fingerprints()
        self.assertEqual(set(state), {"tracked.txt", "fresh.txt"})
        self.assertRegex(state["tracked.txt"], r"^ M:[0-9a-f]{64}$")
        self.assertRegex(state["fresh.txt"], r"^\?\?:[0-9a-f]{64}$")

    def test_a_tree_git_cannot_be_asked_about_is_not_a_pass(self):
        """The gate says so in the context rather than staying silent.

        Driven, not grepped: this used to search the hook's SOURCE for the sentence, so
        deleting the branch and leaving the words in a comment kept it green.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(self.wall, "ROOT", pathlib.Path(tmp)):
                self.assertIsNone(self.wall.dirty_fingerprints(),
                                  "a directory that is not a repository produced a dirty set")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.wall.handle_post_tool(
                        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
                        _AnySession, _AnySession, f"t053-no-git-{uuid.uuid4().hex}")
        self.assertIsNone(decision(out.getvalue()))
        self.assertIn("was NOT settled against the tree. Not a pass.", out.getvalue())

    def test_the_docstring_states_the_limit_in_the_required_words(self):
        """The Owner asked for the honest form of this claim in those words; a security
        model that says 'containment' about either wall is overstating both."""
        source = (ROOT / ".claude" / "hooks" / "canonical_law_gate.py").read_text(encoding="utf-8")
        self.assertIn("A RELIABLE PreToolUse SHELL PATH-CHECK IS NOT POSSIBLE", source)
        self.assertIn("DETECTION PLUS\n  HALTING THE TURN -- NOT CONTAINMENT", source)


class TheBudgetRule(unittest.TestCase):
    """The fourth protection -- the shrink-only rule on an over-budget canonical file --
    on both sides of the tool call. It had no test on either: `budget` appeared in this
    file only in the docstring.

    Each case runs in a scratch repository with its own budget file, with the hook's
    `ROOT` pointed at it, so nothing here depends on the live canon being over budget.
    """

    DOC = "DOC.md"
    CAP = 100

    def setUp(self):
        self.wall = import_wall()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        (self.root / "config").mkdir()
        (self.root / "config" / "canon-budget.json").write_text(
            json.dumps({"per_file_bytes": {self.DOC: self.CAP}}), encoding="utf-8")
        git(self.root, "init", "-q")
        self.write(300)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "seed: the document is over its ceiling")
        patcher = mock.patch.object(self.wall, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sid = f"t145-budget-{uuid.uuid4().hex}"
        self.addCleanup(lambda: self.wall._shell_state_path(self.sid).unlink(missing_ok=True))

    def write(self, size: int) -> None:
        (self.root / self.DOC).write_bytes(b"x" * size)

    def shell(self, before_sizes=None):
        now = self.wall.dirty_fingerprints()
        return self.wall.shell_path_problem(self.DOC, _AnySession, _AnySession, self.sid,
                                            {}, now, before_sizes)

    def post_tool(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.wall.handle_post_tool({"tool_name": "Bash", "tool_input": {"command": "x"}},
                                       _AnySession, _AnySession, self.sid)
        return out.getvalue()

    # --- after the fact: a shell edit -------------------------------------------------

    def test_a_shell_edit_that_SHRINKS_an_over_budget_file_is_accepted(self):
        """The defect. The comment said "over its ceiling AND bigger than it was" and the
        code tested the first half, so the only edit the rule exists to invite was
        blocked -- and its stated remedy, reverting, made the file larger."""
        self.write(200)                       # still over the ceiling, smaller than HEAD
        self.assertIsNone(self.shell())

    def test_a_shell_edit_that_GROWS_an_over_budget_file_is_reported(self):
        self.write(400)
        problem = self.shell()
        self.assertIsNotNone(problem)
        self.assertIn("it was 300 before this shell call", problem)

    def test_a_shell_rewrite_at_the_same_size_is_not_a_shrink(self):
        (self.root / self.DOC).write_bytes(b"y" * 300)
        self.assertIsNotNone(self.shell())

    def test_the_baselines_size_wins_over_the_committed_one(self):
        """For a path that was ALREADY dirty, "what it was" is what the baseline saw."""
        self.write(200)
        self.assertIsNotNone(self.shell({self.DOC: 150}))   # grew from 150, under HEAD's 300
        self.assertIsNone(self.shell({self.DOC: 250}))

    def test_a_file_whose_previous_size_is_unknown_is_not_waved_through(self):
        (self.root / "config" / "canon-budget.json").write_text(
            json.dumps({"per_file_bytes": {"NEW.md": self.CAP}}), encoding="utf-8")
        (self.root / "NEW.md").write_bytes(b"x" * 200)       # untracked: HEAD has no size
        now = self.wall.dirty_fingerprints()
        problem = self.wall.shell_path_problem("NEW.md", _AnySession, _AnySession, self.sid,
                                               {}, now, {})
        self.assertIn("previous size could not be established", problem)

    def test_a_file_under_its_ceiling_is_nobodys_business(self):
        self.write(self.CAP)
        self.assertIsNone(self.shell())

    def test_a_missing_or_broken_budget_file_does_not_kill_the_hook(self):
        """`load_json` raises SystemExit, which `except Exception` does not catch: the
        post-tool arm let it through and the hook exited 1 past its FAILED OPEN shout."""
        self.write(400)
        budget = self.root / "config" / "canon-budget.json"
        for label, damage in (("invalid", lambda: budget.write_text("{", encoding="utf-8")),
                              ("missing", budget.unlink)):
            damage()
            with self.subTest(budget=label):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertIsNone(self.shell())
                    self.assertIsNone(self.wall.canon_budget_problem(
                        self.DOC, "Write", {"content": "x" * 500}))
                self.assertEqual(out.getvalue(), "",
                                 "the budget loader printed into the hook's verdict channel")

    def test_the_settlement_shrink_then_grow_then_stand(self):
        """End to end through `handle_post_tool`, including the part the baseline plays:
        a violating path keeps the size it had BEFORE the violation, so "smaller than it
        was" cannot be satisfied by shrinking back to just under the violation."""
        self.wall.baseline_shell_state(self.sid)
        self.write(200)
        self.assertEqual(self.post_tool(), "", "a shrinking shell edit was reported")
        self.write(250)
        self.assertEqual(decision(self.post_tool()), "block")
        self.assertEqual(decision(self.post_tool()), "block", "reported once, then forgotten")
        self.write(220)                       # smaller than the violation, not than before it
        self.assertEqual(decision(self.post_tool()), "block")
        self.write(150)
        self.assertEqual(self.post_tool(), "")

    def test_a_baseline_is_recorded_once_and_never_overwritten(self):
        self.wall.baseline_shell_state(self.sid)
        path = self.wall._shell_state_path(self.sid)
        first = path.read_text(encoding="utf-8")
        self.write(400)
        self.wall.baseline_shell_state(self.sid)
        self.assertEqual(path.read_text(encoding="utf-8"), first)

    # --- before the fact: the harness edit tools --------------------------------------

    def pre(self, tool: str, tool_input: dict):
        return self.wall.canon_budget_problem(self.DOC, tool, tool_input)

    def test_write_and_edit_are_judged_by_what_they_leave(self):
        self.assertIsNone(self.pre("Write", {"content": "x" * 250}))
        self.assertIsNotNone(self.pre("Write", {"content": "x" * 300}))
        self.assertIsNone(self.pre("Edit", {"old_string": "xxxx", "new_string": "x"}))
        self.assertIsNotNone(self.pre("Edit", {"old_string": "x", "new_string": "xxxx"}))

    def test_a_MultiEdit_is_summed_over_its_edits(self):
        """`MultiEdit` is named by the matcher and carries `edits: [...]`, not a top-level
        pair -- so it fell through to an allow and could grow an over-budget file."""
        grow = {"edits": [{"old_string": "x", "new_string": "x" * 50},
                          {"old_string": "xxxxx", "new_string": "x"}]}
        shrink = {"edits": [{"old_string": "x", "new_string": "xx"},
                            {"old_string": "x" * 40, "new_string": "x"}]}
        self.assertIn("adds 45 more", self.pre("MultiEdit", grow))
        self.assertIsNone(self.pre("MultiEdit", shrink))

    def test_a_payload_that_cannot_be_measured_is_refused_over_budget(self):
        for tool, tool_input in (("NotebookEdit", {"new_source": "x"}),
                                 ("MultiEdit", {"edits": [{"old_string": "x"}]}),
                                 ("MultiEdit", {"edits": ["x"]})):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assertIn("nothing its size can be measured from",
                              self.pre(tool, tool_input))

    def test_under_budget_nothing_fires_whatever_the_shape(self):
        self.write(self.CAP)
        self.assertIsNone(self.pre("NotebookEdit", {"new_source": "x" * 999}))
        self.assertIsNone(self.pre("MultiEdit", {"edits": [{"old_string": "", "new_string": "x" * 999}]}))


SHA = "0123456789abcdef0123456789abcdef01234567"

#: Command lines that RUN `gh pr merge`. Each must be recognised.
RUNS_A_MERGE = [
    "gh pr merge 5 --squash",
    f"gh pr merge 5 --squash --match-head-commit {SHA}",
    "cd /somewhere && gh pr merge 5",
    "git status; gh pr merge 5",
    "git add -A\ngh pr merge 5 --squash",
    "FOO=1 gh pr merge 5",
    "sudo -E gh pr merge 5",
    "/usr/bin/gh pr merge 5",
    "gh -R menqstudio/OS pr merge 5",
    "gh pr merge --squash 5",
    "x=$(gh pr merge 5)",
    'echo "$(gh pr merge 5)"',            # inside double quotes the shell still runs it
    "echo `gh pr merge 5`",
    "(gh pr merge 5)",
    "true || gh pr merge 5",
    "ls | gh pr merge 5",
]

#: Command lines that RUN `git push`. Each must be recognised.
RUNS_A_PUSH = [
    "git push",
    "git push origin HEAD",
    "git -C /some/where push origin HEAD",
    "git -c user.name=x push",
    "git --no-pager push -u origin branch",
    "git status && git push",
    "git push \\\n  origin main",
    "GIT_TRACE=1 git push",
    'git commit -m "message" && git push',
    "timeout 30 git push",
]

#: Command lines that only MENTION the words. None may be recognised.
ONLY_MENTIONS = [
    'echo "gh pr merge 5"',
    "echo 'git push origin main'",
    'git commit -m "T-150: gh pr merge and git push are refused"',
    "git commit -m 'never git push before the gate'",
    "git commit -m \"$(cat <<'EOF'\nT-150: a merge and a push\n\ngh pr merge 5\ngit push\nEOF\n)\"",
    "cat <<EOF\ngit push origin main\ngh pr merge 5\nEOF",
    "cat <<-'END' > notes.txt\n\tgit push\n\tEND",
    "grep -rn 'gh pr merge' docs/",
    'grep -rn "git push" tools/',
    "git stash push -m wip",
    "git log --grep push",
    "git log --oneline | grep merge && gh pr view 5",
    "gh pr view 5 --json mergeStateStatus",
    "gh pr list --search merge",
    "gh pr checks 5   # then gh pr merge 5",
    "# git push",
    "ls   # ; git push",                               # a separator inside a comment
    'echo "done; gh pr merge 5"',                      # ...inside double quotes
    'git commit -m "build && git push later"',
    "echo 'a | git push origin main'",                 # ...inside single quotes
    "echo gh pr merge 5",                              # unquoted, and still only an echo:
    "echo git push origin main",                       # the FIRST word is the command
    "man git push",
    "printf 'gh pr merge 5\\n' > notes.txt",
    "python3 tools/check_merge_ready.py --pr 5 && git status && echo gh-merge",
    "ls push-git/ merge-gh/",
]


class TheTwoNamedCommands(unittest.TestCase):
    """The recogniser, both directions. Pure string work: nothing here spawns anything."""

    def setUp(self):
        self.wall = import_wall()

    def kinds(self, command: str) -> list[str]:
        return [inv["kind"] for inv in self.wall.guarded_invocations(command)]

    def test_every_form_that_runs_a_merge_is_recognised(self):
        for command in RUNS_A_MERGE:
            with self.subTest(command=command):
                self.assertTrue(self.wall.mentions_guarded(command))
                self.assertEqual(self.kinds(command), ["merge"])

    def test_every_form_that_runs_a_push_is_recognised(self):
        for command in RUNS_A_PUSH:
            with self.subTest(command=command):
                self.assertTrue(self.wall.mentions_guarded(command))
                self.assertEqual(self.kinds(command), ["push"])

    def test_a_command_that_only_MENTIONS_them_is_not(self):
        """Mutant: split on separators without honouring quotes ⇒ red here. A commit
        message, an `echo`, a `grep` pattern, a heredoc body and a comment all contain
        the words and run neither command."""
        for command in ONLY_MENTIONS:
            with self.subTest(command=command):
                self.assertEqual(self.kinds(command), [])

    def test_both_in_one_line_are_both_found(self):
        self.assertEqual(self.kinds(f"git push && gh pr merge 5 --match-head-commit {SHA}"),
                         ["push", "merge"])

    def test_the_cheap_test_comes_first_and_is_string_only(self):
        """What keeps every other command free. Mutant: make `mentions_guarded` return
        True always ⇒ the `ls` case in `TheTwoNamedCommandsRefused` reaches the parser."""
        for command in ("ls", "grep -rn lstrip tools/", "git status", "gh pr view 5",
                        "cargo test --workspace", "npm run build", ""):
            with self.subTest(command=command):
                self.assertFalse(self.wall.mentions_guarded(command))

    def test_what_a_merge_carries(self):
        merge = self.wall.guarded_invocations(
            f"gh pr merge 5 --squash --match-head-commit {SHA} -R a/b")[0]
        self.assertEqual((merge["target"], merge["pinned"], merge["pin"], merge["repo"]),
                         ("5", True, SHA, "a/b"))
        equals = self.wall.guarded_invocations(f"gh pr merge 5 --match-head-commit={SHA}")[0]
        self.assertEqual((equals["pinned"], equals["pin"]), (True, SHA))
        bare = self.wall.guarded_invocations("gh pr merge --squash")[0]
        self.assertEqual((bare["target"], bare["pinned"]), (None, False))

    def test_the_pull_request_number(self):
        for target, number in (("5", 5), ("#5", 5), ("https://github.com/a/b/pull/12", 12),
                               ("https://github.com/a/b/pull/12/files", 12),
                               ("t150/branch", None), ("0", None), ("", None), (None, None)):
            with self.subTest(target=target):
                self.assertEqual(self.wall.pr_number(target), number)

    def test_a_delete_is_a_push_that_is_not_gated(self):
        for command, delete in (("git push --delete origin old", True),
                                ("git push origin --delete old", True),
                                ("git push -d origin old", True),
                                ("git push origin :old", True),
                                ("git push origin :old new", False),
                                ("git push origin HEAD", False),
                                ("git push", False)):
            with self.subTest(command=command):
                self.assertEqual(self.wall.guarded_invocations(command)[0]["delete"], delete)

    def test_where_a_push_is_sent_from(self):
        push = self.wall.guarded_invocations("cd sub/dir && git -C ../other push")[0]
        self.assertEqual((push["cd"], push["directory"]), ("sub/dir", "../other"))

    def test_the_crude_reading_is_command_shaped(self):
        """Used only when the parser itself raised. It must still tell `git push` from
        `git log --grep push`, or a parser bug would refuse half of what agents type."""
        for command in ("git push origin x", "git -C /x push", "gh pr merge 5",
                        "gh -R a/b pr merge 5", "ls && git push"):
            with self.subTest(command=command):
                self.assertTrue(self.wall.reads_as_guarded(command))
        for command in ("git log --grep push", "git stash push", "gh pr view 5 # merge",
                        "ls", 'echo "git push"', "grep -rn 'gh pr merge' docs/"):
            with self.subTest(command=command):
                self.assertFalse(self.wall.reads_as_guarded(command))


class TheTwoNamedCommandsRefused(unittest.TestCase):
    """`handle_pre_shell` with the gate replaced, so no test here needs GitHub or a build.

    The gate is replaced at `run_gate`, the one place the arm spawns anything; every
    decision above that line is the real code.
    """

    GREEN = (0, "GREEN: it may be done.")
    RED = (1, "RED: it must NOT be done now\n\n  1. the reason, in the gate's own words")

    def setUp(self):
        self.wall = import_wall()
        self.calls: list[tuple[str, list[str]]] = []

    def shell(self, command: str, gate=None, *, tool: str = "Bash", cwd=None) -> str:
        def fake(script, args):
            self.calls.append((script, list(args)))
            if isinstance(gate, BaseException):
                raise gate
            return gate

        # `wall.ROOT` is CLAUDE_PROJECT_DIR when a session set it, which is the session's
        # checkout and not necessarily the one under test.
        out = io.StringIO()
        with mock.patch.object(self.wall, "ROOT", ROOT), \
                mock.patch.object(self.wall, "run_gate", fake), contextlib.redirect_stdout(out):
            self.wall.handle_pre_shell({"tool_name": tool, "cwd": str(cwd or ROOT),
                                        "tool_input": {"command": command}})
        return out.getvalue()

    def assert_asked_about_this_checkout(self):
        """One call, to the push gate, about ROOT -- compared as paths, not as spellings."""
        self.assertEqual(len(self.calls), 1, self.calls)
        script, args = self.calls[0]
        self.assertEqual((script, args[0]), ("check_push_ready.py", "--root"))
        self.assertEqual(pathlib.Path(args[1]).resolve(), ROOT.resolve())

    # --- gh pr merge ---------------------------------------------------------------

    def test_a_merge_without_match_head_commit_is_refused_even_when_the_gate_is_GREEN(self):
        """Mutant: drop the pin requirement ⇒ this is allowed. The gate being GREEN is
        about the head it read; an unpinned merge takes whatever head is there later."""
        out = self.shell("gh pr merge 5 --squash", self.GREEN)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("--match-head-commit", out)
        self.assertIn("GREEN: it may be done.", out, "the gate's output, which carries the "
                                                     "exact command, was not handed over")

    def test_a_pin_with_no_value_is_not_a_pin(self):
        out = self.shell("gh pr merge 5 --squash --match-head-commit", self.GREEN)
        self.assertEqual(decision(out), "deny", out)

    def test_a_pinned_merge_is_refused_while_the_gate_is_RED(self):
        """Mutant: ignore the gate's verdict ⇒ allowed. The refusal IS the gate's text."""
        out = self.shell(f"gh pr merge 5 --squash --match-head-commit {SHA}", self.RED)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("the reason, in the gate's own words", out)

    def test_a_pinned_merge_is_allowed_when_the_gate_is_GREEN(self):
        """The positive control, and what the gate was asked: THIS pull request, THIS head."""
        out = self.shell(f"gh pr merge 5 --squash --match-head-commit {SHA}", self.GREEN)
        self.assertEqual(out, "", out)
        self.assertEqual(self.calls, [("check_merge_ready.py",
                                       ["--pr", "5", "--expect-head", SHA])])

    def test_a_merge_that_names_no_number_is_refused_without_asking_the_gate(self):
        for command in ("gh pr merge --squash", "gh pr merge t150/branch --squash"):
            with self.subTest(command=command):
                self.calls.clear()
                out = self.shell(command, self.GREEN)
                self.assertEqual(decision(out), "deny", out)
                self.assertIn("by number", out)
                self.assertEqual(self.calls, [])

    def test_a_merge_in_another_repository_is_said_and_allowed(self):
        with mock.patch.object(self.wall, "_git_answer",
                               lambda directory, *args: "git@github.com:menqstudio/OS.git"):
            other = self.shell(f"gh pr merge 5 -R someone/else --match-head-commit {SHA}",
                               self.RED)
            self.assertIsNone(decision(other), other)
            self.assertIn("NOT judged", other)
            self.assertEqual(self.calls, [])
            ours = self.shell(f"gh pr merge 5 -R MenQStudio/os --match-head-commit {SHA}",
                              self.RED)
        self.assertEqual(decision(ours), "deny", ours)
        self.assertEqual(self.calls[0][1], ["--pr", "5", "--repo", "MenQStudio/os",
                                            "--expect-head", SHA])

    # --- git push ------------------------------------------------------------------

    def test_a_push_is_refused_while_the_gate_is_RED(self):
        """Mutant: skip the push arm ⇒ allowed."""
        out = self.shell("git push origin HEAD", self.RED)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("the reason, in the gate's own words", out)

    def test_a_push_is_allowed_when_the_gate_is_GREEN_and_the_gate_judged_THIS_tree(self):
        out = self.shell("git push origin HEAD", self.GREEN)
        self.assertEqual(out, "", out)
        self.assert_asked_about_this_checkout()

    def test_a_delete_is_not_gated(self):
        """Mutant: drop the delete exemption ⇒ the gate is asked. Deleting a branch sends
        no commit, so there is nothing for CI to refuse."""
        for command in ("git push --delete origin old", "git push origin :old"):
            with self.subTest(command=command):
                self.calls.clear()
                self.assertEqual(self.shell(command, self.RED), "")
                self.assertEqual(self.calls, [])

    def test_a_push_in_a_different_repository_is_said_and_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            git(pathlib.Path(tmp), "init", "-q")
            # posix spelling: an unquoted backslash is an escape to a shell, and to the hook.
            out = self.shell(f"git -C {pathlib.Path(tmp).as_posix()} push origin HEAD", self.RED)
            moved = self.shell("git push origin HEAD", self.RED, cwd=tmp)
        for text in (out, moved):
            self.assertIsNone(decision(text), text)
            self.assertIn("different repository", text)
        self.assertEqual(self.calls, [])

    def test_a_directory_that_cannot_be_resolved_is_judged_as_this_checkout(self):
        """Not being able to tell is not being told it is somebody else's."""
        out = self.shell('cd "$NOWHERE/nothing" && git push', self.RED)
        self.assertEqual(decision(out), "deny", out)
        self.assert_asked_about_this_checkout()

    def test_a_gate_that_could_not_run_one_of_its_gates_is_said_on_the_way_through(self):
        out = self.shell("git push", (0, "  tools/check_runbook_snippets.py -- COULD NOT RUN: "
                                         "`cryptography` does not import here\n\nGREEN: 0 ran"))
        self.assertIsNone(decision(out), out)
        self.assertIn("COULD NOT RUN", out)
        self.assertIn("NOT a pass", out)

    # --- what only mentions them -----------------------------------------------------

    def test_an_echo_and_a_commit_message_trigger_nothing(self):
        """The other direction, end to end: no verdict and the gate never asked."""
        for command in ('echo "gh pr merge 5"',
                        'git commit -m "T-150: git push is refused before CI refuses it"',
                        "git commit -m \"$(cat <<'EOF'\nthen git push\ngh pr merge 5\nEOF\n)\""):
            with self.subTest(command=command):
                self.assertEqual(self.shell(command, self.RED), "")
        self.assertEqual(self.calls, [])

    # --- how it fails ----------------------------------------------------------------

    def test_a_gate_that_crashes_refuses_the_merge_and_the_push(self):
        """Fail closed, for these two only. Mutant: catch the exception and allow ⇒ red."""
        for command in (f"gh pr merge 5 --squash --match-head-commit {SHA}", "git push"):
            with self.subTest(command=command):
                out = self.shell(command, RuntimeError("the gate blew up"))
                self.assertEqual(decision(out), "deny", out)
                self.assertIn("did not give a verdict", out)
                self.assertIn("the gate blew up", out)

    def test_a_gate_that_times_out_refuses(self):
        out = self.shell("git push", subprocess.TimeoutExpired(["python3"], 50))
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("did not give a verdict", out)

    def test_a_traceback_is_not_a_verdict(self):
        out = self.shell("git push", (1, "Traceback (most recent call last):\n  ...\nKeyError: 'x'"))
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("without a verdict", out)

    def test_exit_zero_without_the_word_GREEN_is_not_a_pass(self):
        """Mutant: accept exit 0 alone ⇒ allowed. A truncated or empty gate script exits 0
        and has said nothing."""
        for output in ("", "usage: check_push_ready.py [--root ROOT]"):
            with self.subTest(output=output):
                out = self.shell("git push", (0, output))
                self.assertEqual(decision(out), "deny", out)

    def test_a_nonzero_exit_is_not_a_pass_whatever_it_printed(self):
        """Mutant: accept the word alone ⇒ allowed. The merge gate's own RED text says
        "a head that is not GREEN here", so the word is in every refusal it prints."""
        out = self.shell(f"gh pr merge 5 --squash --match-head-commit {SHA}",
                         (1, "RED: must NOT be merged now\n  1. a head that is not GREEN here"))
        self.assertEqual(decision(out), "deny", out)

    def test_a_missing_gate_script_refuses(self):
        """Not replaced: the REAL `run_gate`, pointed at a tools/ with no gate in it."""
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch.object(self.wall, "ROOT", pathlib.Path(tmp)), \
                    contextlib.redirect_stdout(out):
                self.wall.handle_pre_shell({"tool_name": "Bash", "cwd": tmp, "tool_input": {
                    "command": f"gh pr merge 5 --squash --match-head-commit {SHA}"}})
        self.assertEqual(decision(out.getvalue()), "deny", out.getvalue())
        self.assertIn("without a verdict", out.getvalue())

    def test_an_exception_while_judging_one_of_the_two_refuses_it(self):
        with mock.patch.object(self.wall, "push_problem",
                               mock.Mock(side_effect=KeyError("boom"))):
            out = self.shell("git push", self.GREEN)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("KeyError", out)

    def test_nothing_else_can_be_refused_whatever_breaks_inside_the_arm(self):
        """The wedge, made structurally impossible. EVERY helper below the cheap string
        test raises -- the parser, the crude reading, both judges, the gate -- and a
        command that carries neither word pair still gets no verdict and no exception.

        Mutant: drop the `mentions_guarded` early return ⇒ `ls` reaches the parser, and
        the exception leaves `handle_pre_shell`.
        """
        boom = mock.Mock(side_effect=RuntimeError("the arm is broken"))
        with mock.patch.object(self.wall, "guarded_invocations", boom), \
                mock.patch.object(self.wall, "shell_segments", boom), \
                mock.patch.object(self.wall, "reads_as_guarded", boom), \
                mock.patch.object(self.wall, "merge_problem", boom), \
                mock.patch.object(self.wall, "push_problem", boom):
            for command in ("ls", "grep -rn lstrip tools/", "git status", "cargo test",
                            "gh pr view 5", "npm run build", "git commit -m 'a merge'",
                            "python3 tools/check_merge_ready.py --pr 5"):
                with self.subTest(command=command):
                    self.assertEqual(self.shell(command, RuntimeError("no gate either")), "")
        boom.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_a_parser_crash_refuses_nothing_that_merely_carries_the_words(self):
        """One step further in: these PASS the cheap test, the parser raises on them, and
        the crude reading is what lets them through."""
        boom = mock.Mock(side_effect=RuntimeError("the parser is broken"))
        with mock.patch.object(self.wall, "guarded_invocations", boom):
            for command in ("git log --grep push", "git stash push", "gh pr view 5 # merge",
                            'echo "git push"', "grep -rn 'gh pr merge' docs/"):
                with self.subTest(command=command):
                    self.assertEqual(self.shell(command, RuntimeError("no gate either")), "")
        self.assertEqual(self.calls, [])

    def test_a_parser_crash_still_refuses_what_reads_as_one_of_the_two(self):
        """The other half of the same rule: a broken parser must not wave a merge through."""
        boom = mock.Mock(side_effect=RuntimeError("the parser is broken"))
        with mock.patch.object(self.wall, "guarded_invocations", boom):
            for command in ("git push origin HEAD", "gh pr merge 5 --squash"):
                with self.subTest(command=command):
                    out = self.shell(command, self.GREEN)
                    self.assertEqual(decision(out), "deny", out)
                    self.assertIn("could not parse it", out)

    def test_a_payload_with_no_command_is_nobodys_business(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for payload in ({}, {"tool_input": None}, {"tool_input": {"command": 5}},
                            {"tool_input": {"command": None}}):
                self.wall.handle_pre_shell(payload)
        self.assertEqual(out.getvalue(), "")


#: Lines where a gate is piped and `&&` follows the pipeline. Each must be refused.
BROKEN_GUARDS = [
    "python3 tools/check_prior_art.py --declare x | tail -2 && python3 - <<EOF\nprint(1)\nEOF",
    "python3 tools/check_canonical_sync.py --staged 2>&1 | tail -3 && git commit -m x",
    "python3 -B tools/check_repo_state.py | grep -v ok | tail -1 && echo fine",
    "cd /r && python3 -X utf8 tools/check_x.py |& tee log && ls",
    "tools/check_x.py | tail && ls",
    "BRO_ENV=ci timeout 50 python3 tools/check_x.py | tail -1 && ls",
    "echo pipefail; python3 tools/check_x.py | tail -3 && ls",   # the word, not the option
]

#: Lines where an outward action follows a gate whose verdict does not decide it.
UNGUARDED_ACTIONS = [
    ("python3 tools/check_canonical_sync.py --staged; git commit -m x", "git commit"),
    ("python3 tools/check_canonical_sync.py --staged\ngit commit -m x", "git commit"),
    ("python3 tools/check_x.py | tail -3; git push", "git push"),
    ("python3 tools/check_x.py || true; git push origin HEAD", "git push"),
    ("python3 tools/check_x.py && git commit -m x; git push", "git push"),
    ("python3 tools/check_x.py & git commit -m x", "git commit"),
    ("python3 tools/check_x.py > out.txt; git -C /r commit -m x", "git commit"),
    ("python3 tools/check_x.py; git merge other", "git merge"),
    ("python3 tools/check_x.py; gh pr create --body-file b.md", "gh pr create"),
    ("python3 tools/check_x.py; gh -R a/b pr edit 5 --body x", "gh pr edit"),
    ("python3 tools/check_x.py; python3 tools/stamp_pr_head.py --pr 5", "tools/stamp_pr_head.py"),
    ("python3 tools/check_x.py; python3 -B tools/sync_active_pr.py --settled",
     "tools/sync_active_pr.py"),
    ("if true; then python3 tools/check_x.py; git commit -m x; fi", "git commit"),
    ("python3 tools/check_x.py; FOO=1; git commit -m x", "git commit"),
    ("! python3 tools/check_x.py; git commit -m x", "git commit"),   # negated, not asked
    ("python3 tools/check_x.py; (ls); git commit -m x", "git commit"),
    ("(python3 tools/check_x.py | tail -3); git commit -m x", "git commit"),   # lost in the pipe
    ("set -o pipefail; python3 tools/check_x.py | tail -3; git commit -m x", "git commit"),
]

#: Lines that run a gate and are fine: its verdict decides, or nothing leans on it.
VERDICT_KEPT = [
    "python3 tools/check_x.py && git commit -m x && git push",
    "python3 tools/check_x.py && git add -A && git commit -m x",
    # a pipe on a LATER command loses that command's status, not the gate's: if the gate
    # failed, nothing after its `&&` ran at all
    "python3 tools/check_x.py && git push 2>&1 | tail -1 && python3 tools/stamp_pr_head.py --pr 5",
    "set -o pipefail; python3 tools/check_x.py | tail -3 && git commit -m x",
    "set -euo pipefail\npython3 tools/check_x.py | tail -3 && git commit -m x",
    "python3 tools/check_x.py | tail -3",
    "python3 tools/check_x.py; echo rc=$?",
    "python3 tools/check_x.py; git status; git diff --stat",
    "if python3 tools/check_x.py; then git commit -m x; fi",
    "if python3 tools/check_x.py | grep -q GREEN; then git commit -m x; fi",
    "! python3 tools/check_x.py && git commit -m x",
    "while python3 tools/check_x.py; do git commit -m x; done",
    "until python3 tools/check_x.py; do git commit -m x; done",
    "if false; then ls; elif python3 tools/check_x.py; then git commit -m x; fi",
    "python3 tools/check_x.py | tail -3; git status && git diff --stat",
    "(python3 tools/check_x.py) && ls; git commit -m x",   # a subshell: no claim either way
    "python3 tools/check_a.py | tail -1; python3 tools/check_b.py | tail -1",
    "git commit -m x && python3 tools/check_x.py",
    "git commit -m 'python3 tools/check_x.py; git push'",
    "echo 'python3 tools/check_x.py | tail && git commit'",
    "grep -n foo tools/check_x.py | tail -2 && git commit -m x",
    "cat tools/check_x.py | head && git push",
    "python3 -m unittest tools.test_check_x | tail -3 && git commit -m x",
    "python3 -c 'import check_x' | tail && git commit -m x",
    'for g in tools/check_*.py; do python3 "$g"; done; git status',
    "python3 tools/sync_active_pr.py --pr 5 && python3 tools/check_x.py && git commit -m x",
    "(python3 tools/check_x.py); git commit -m x",        # a subshell: no claim either way
    "python3 tools/check_x.py; gh pr view 5; git log --oneline -1; git stash push",
]


class TheDiscardedVerdict(unittest.TestCase):
    """T-157. A gate that printed RED and a commit that ran anyway, six times in this
    repository, each time because the shell was never asked to connect the two."""

    def setUp(self):
        self.wall = import_wall()
        self.calls: list = []

    def shell(self, command: str) -> str:
        def fake(script, args):
            self.calls.append((script, list(args)))
            return (0, "GREEN: it may be done.")
        out = io.StringIO()
        with mock.patch.object(self.wall, "ROOT", ROOT), \
                mock.patch.object(self.wall, "run_gate", fake), contextlib.redirect_stdout(out):
            self.wall.handle_pre_shell({"tool_name": "Bash", "cwd": str(ROOT),
                                        "tool_input": {"command": command}})
        return out.getvalue()

    def test_a_piped_gate_followed_by_and_and_is_refused(self):
        """Mutant: drop the `feeding` refusal ⇒ every line here is allowed. `&&` after a
        pipeline tests `tail`."""
        for command in BROKEN_GUARDS:
            with self.subTest(command=command):
                self.assertTrue(self.wall.mentions_discard(command))
                problem = self.wall.discarded_verdict(command)
                self.assertIsNotNone(problem)
                self.assertIn("LAST command of a pipeline", problem)
                self.assertIn("pipefail", problem)

    def test_an_outward_action_after_a_loose_gate_is_refused_and_named(self):
        """Mutant: treat `;` as keeping the verdict ⇒ the first case is allowed."""
        for command, action in UNGUARDED_ACTIONS:
            with self.subTest(command=command):
                self.assertTrue(self.wall.mentions_discard(command))
                problem = self.wall.discarded_verdict(command)
                self.assertIsNotNone(problem)
                self.assertIn(f"`{action}` is refused", problem)
                self.assertIn("tools/check_", problem)

    def test_a_verdict_that_decides_or_that_nothing_leans_on_is_left_alone(self):
        """The other direction. Mutant: count `&&` as dropping the verdict ⇒ the first
        line is refused, and that line is how every commit here is made."""
        for command in VERDICT_KEPT:
            with self.subTest(command=command):
                self.assertIsNone(self.wall.discarded_verdict(command))
                self.assertEqual(self.shell(command.replace("git push", "git status")
                                            .replace("gh pr", "gh issue")), "")

    def test_the_refusal_names_the_gate_that_was_let_go(self):
        problem = self.wall.discarded_verdict(
            "python3 tools/check_a.py && python3 tools/check_b.py; git commit -m x")
        self.assertIn("tools/check_a.py runs earlier", problem)

    def test_pipefail_switched_off_again_is_not_pipefail(self):
        problem = self.wall.discarded_verdict(
            "set +o pipefail; python3 tools/check_x.py | tail -3 && git commit -m x")
        self.assertIsNotNone(problem)

    def test_the_hook_denies_it_before_any_gate_is_asked(self):
        """End to end through `handle_pre_shell`. Mutant: compute the refusal and not
        `deny` it ⇒ no verdict. The push gate is never spawned: the line is refused for
        its shape, before the push is judged."""
        for command in ("python3 tools/check_canonical_sync.py --staged | tail -2 && git commit -m x",
                        "python3 tools/check_canonical_sync.py --staged; git push"):
            with self.subTest(command=command):
                out = self.shell(command)
                self.assertEqual(decision(out), "deny", out)
                self.assertIn("CANONICAL_LAW=off", out)
        self.assertEqual(self.calls, [])

    def test_a_guarded_push_still_meets_the_push_gate(self):
        """The new rule returning nothing must not return from the arm."""
        self.shell("python3 tools/check_canonical_sync.py --staged && git commit -m x && git push")
        self.assertEqual([script for script, _ in self.calls], ["check_push_ready.py"])

    def test_the_cheap_test_keeps_every_other_command_out_of_it(self):
        """Mutant: make `mentions_discard` return True always ⇒ `ls` reaches the scanner."""
        for command in ("ls", "git commit -m x", "git push", "python3 tools/check_x.py",
                        "python3 tools/check_merge_ready.py --pr 5",
                        "python3 tools/check_x.py | tail -3", "gh pr create --fill", ""):
            with self.subTest(command=command):
                self.assertFalse(self.wall.mentions_discard(command))
        boom = mock.Mock(side_effect=RuntimeError("the rule is broken"))
        with mock.patch.object(self.wall, "discarded_verdict", boom):
            self.assertEqual(self.shell("ls"), "")
            self.assertEqual(self.shell("python3 tools/check_x.py | tail -3"), "")
        boom.assert_not_called()

    def test_this_rule_never_refuses_on_its_own_bug(self):
        """It allows, as the docstring says of every command that is not one of the two.
        Mutant: let the exception out ⇒ `handle_pre_shell` raises."""
        boom = mock.Mock(side_effect=RuntimeError("the rule is broken"))
        with mock.patch.object(self.wall, "discarded_verdict", boom):
            self.assertEqual(self.shell("python3 tools/check_x.py | tail -3 && ls"), "")
        boom.assert_called_once()

    def test_the_scanner_reports_the_operator_that_ended_each_command(self):
        segments, ops = self.wall._scan("a && b | c |& d; e || f & g\nh")
        self.assertEqual([words[0] for words in segments], list("abcdefgh"))
        self.assertEqual(ops, ["&&", "|", "|&", ";", "||", "&", "\n", ""])
        self.assertEqual(self.wall._scan("(a) && b")[1], [")", ""])

    def test_a_redirection_is_a_word_and_not_a_separator(self):
        """Mutant: drop the redirection branch ⇒ `2>&1` splits at `&`, the gate's segment
        ends in `&`, and `gate 2>&1 | tail && next` is no longer seen as a piped gate."""
        self.assertEqual(self.wall.shell_segments("a 2>&1 | b &>log"),
                         [["a", "2>&1"], ["b", "&>log"]])
        self.assertEqual(self.wall._scan("a 2>&1 | b")[1], ["|", ""])
        self.assertEqual(self.wall.shell_segments("a & b"), [["a"], ["b"]])

    def test_what_counts_as_running_a_gate(self):
        for words, gate in ((["python3", "tools/check_x.py"], "check_x.py"),
                            (["python3", "-X", "utf8", "-B", "tools/check_x.py", "--pr", "5"],
                             "check_x.py"),
                            (["/usr/bin/python3.13", "/r/tools/check_x.py"], "check_x.py"),
                            (["py", "-3", "tools\\check_x.py"], "check_x.py"),
                            (["tools/check_x.py"], "check_x.py"),
                            (["python3", "-m", "check_x.py"], None),
                            (["python3", "-c", "check_x.py"], None),
                            (["python3", "tools/test_check_x.py"], None),
                            (["python3", "tools/sync_active_pr.py"], None),
                            (["cat", "tools/check_x.py"], None),
                            (["python3"], None)):
            with self.subTest(words=words):
                self.assertEqual(self.wall._gate_run(words), gate)

    def test_what_counts_as_an_outward_action(self):
        for words, action in ((["git", "commit", "-m", "x"], "git commit"),
                              (["git", "-C", "/r", "-c", "a=b", "push"], "git push"),
                              (["git", "status"], None),
                              (["git", "log", "--grep", "commit"], None),
                              (["git", "stash", "push"], None),
                              (["gh", "pr", "create", "--fill"], "gh pr create"),
                              (["gh", "-R", "a/b", "pr", "merge", "5"], "gh pr merge"),
                              (["gh", "pr", "view", "5"], None),
                              (["gh", "pr", "ready", "5"], "gh pr ready"),
                              (["gh", "pr", "edit", "5", "--body", "x"], "gh pr edit"),
                              (["gh", "pr", "comment", "5"], "gh pr comment"),
                              (["gh", "pr", "close", "5"], "gh pr close"),
                              (["gh", "pr", "reopen", "5"], "gh pr reopen"),
                              (["git", "merge", "other"], "git merge"),
                              (["python3", "tools/sync_active_pr.py"], "tools/sync_active_pr.py"),
                              (["gh", "issue", "create"], None),
                              (["python3", "tools/stamp_pr_head.py"], "tools/stamp_pr_head.py"),
                              (["python3", "tools/check_x.py"], None),
                              (["echo", "git", "commit"], None)):
            with self.subTest(words=words):
                self.assertEqual(self.wall._outward_action(words), action)

    def test_the_docstring_says_what_this_rule_cannot_see(self):
        doc = self.wall.__doc__
        self.assertIn("A DISCARDED VERDICT", doc)
        self.assertIn('"$g"', doc)


class TheTwoNamedCommandsLive(unittest.TestCase):
    """The REAL hook, run as `.claude/settings.json` runs it. No network: every case
    here is decided before a gate would be asked."""

    def run_pre(self, command: str, tool: str = "Bash", env: dict | None = None) -> tuple[int, str]:
        merged = dict(os.environ)
        merged.update({"CLAUDE_PROJECT_DIR": str(ROOT), "PYTHONUTF8": "1"})
        merged.pop("CANONICAL_LAW", None)
        merged.update(env or {})
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(HOOK), "pre-tool"],
            input=json.dumps({"session_id": "t150-live", "tool_name": tool, "cwd": str(ROOT),
                              "tool_input": {"command": command}}),
            capture_output=True, text=True, env=merged, timeout=120)
        return result.returncode, result.stdout

    def test_ls_exits_zero_and_says_nothing(self):
        self.assertEqual(self.run_pre("ls"), (0, ""))

    def test_a_merge_with_no_number_is_denied_by_the_real_hook(self):
        """Mutant: do not route shell tools to the arm in `main` ⇒ no verdict at all."""
        for tool in ("Bash", "PowerShell", "Shell"):
            with self.subTest(tool=tool):
                code, out = self.run_pre("gh pr merge --squash", tool)
                self.assertEqual(code, 0)
                self.assertEqual(decision(out), "deny", out)

    def test_a_discarded_verdict_is_denied_by_the_real_hook(self):
        """T-157, as the settings run it. Decided on the words: no gate is spawned."""
        code, out = self.run_pre("python3 tools/check_canonical_sync.py --staged | tail -2 "
                                 "&& git commit -m x")
        self.assertEqual(code, 0)
        self.assertEqual(decision(out), "deny", out)
        self.assertIn("LAST command of a pipeline", out)
        self.assertEqual(self.run_pre("python3 tools/check_canon_budget.py | tail -2"), (0, ""))

    def test_a_tool_that_is_not_a_shell_never_reaches_the_arm(self):
        """`BashOutput` carries a command-shaped field and is not a shell."""
        self.assertEqual(self.run_pre("gh pr merge --squash", "BashOutput"), (0, ""))

    def test_the_disabled_switch_disables_this_arm_exactly_as_the_others(self):
        """Mutant: put the shell arm above the `disabled()` return ⇒ still denied."""
        self.assertEqual(self.run_pre("gh pr merge --squash", env={"CANONICAL_LAW": "off"}),
                         (0, ""))

    def test_the_arm_runs_before_the_session_imports(self):
        """A broken receipt store is not `ls`'s problem, and not a merge's alibi either:
        the arm must not depend on check_read_receipt / check_roadmap_order importing.

        Driven with a project root that has no tools/ at all. `ls` still exits 0 in
        silence, and the merge is still refused rather than failed open.
        """
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CLAUDE_PROJECT_DIR": tmp}
            self.assertEqual(self.run_pre("ls", env=env), (0, ""))
            code, out = self.run_pre(f"gh pr merge 5 --squash --match-head-commit {SHA}", env=env)
        self.assertEqual(code, 0)
        self.assertEqual(decision(out), "deny", out)
        self.assertNotIn("FAILED OPEN", out)


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
        declared scope, or a new file with no prior-art search, is not refused before a
        shell write, is detected after it (`TheContainment`), and is backed by nothing in
        CI: if the session ignores the failed turn, no later gate asks again. This is
        asserted on the signatures rather than described, so it goes red if either gate
        ever stops being session-scoped.
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
