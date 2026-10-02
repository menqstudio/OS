"""Tests for the push-readiness gate.

Every input comes through `check_push_ready.Inputs`, so `Fake` below replaces git, the two
gates it runs, and the `cryptography` probe: no build, no package and no repository is
needed. Two tests at the bottom drive the REAL `Inputs` against a repository on disk,
because a fake proves nothing about what `git diff` counts as "changed on this branch".

Every test names the mutation that turns it red. `unittest.main()` is the last statement
(ninth audit `I-05`).
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import check_push_ready
from check_push_ready import BUNDLE, SNIPPETS, GateError

GREEN = (0, "GREEN: within budget.")
STALE = (1, "RED: the build is stale —\n  - the build is stale: 3 bundled source(s) are newer "
            "than apps/desktop/dist/.vite/manifest.json — apps/desktop/src/App.tsx. Run "
            "`npm run build` in apps/desktop and re-run this gate\n\n1 problem(s). rebuild "
            "before trusting any number this gate prints.")
MISSING = (1, "RED: no Vite build manifest found (looked for "
              "apps/desktop/dist/.vite/manifest.json, apps/desktop/dist/manifest.json). Run "
              "`npm run build` with `build.manifest: true` in vite.config.ts.")
OVER = (1, "RED: bundle-size budget exceeded —\n  - route 'Approvals' navigation payload "
           "12.1 KB gzip exceeds budget 11.5 KB by 0.6 KB")

#: A population with one gate of every kind the report distinguishes.
GATES = ["check_action_pins.py", BUNDLE, "check_canonical_sync.py", "check_coordination.py",
         "check_merge_ready.py", "check_prior_art.py", "check_produced_artifact.py",
         "check_push_ready.py", "check_read_receipt.py", SNIPPETS]


class Fake(check_push_ready.Inputs):
    def __init__(self, changed=(), *, bundle=GREEN, snippets=GREEN, blocker=None,
                 gates=GATES) -> None:
        super().__init__(ROOT)
        self._changed = changed
        self.results = {BUNDLE: bundle, SNIPPETS: snippets}
        self.blocker = blocker
        self._gates = gates
        self.calls: list[tuple[str, list[str]]] = []

    def changed(self):
        if isinstance(self._changed, BaseException):
            raise self._changed
        return "0123456789abcdef0123456789abcdef01234567", sorted(self._changed)

    def run_gate(self, name, args):
        self.calls.append((name, list(args)))
        result = self.results[name]
        if isinstance(result, BaseException):
            raise result
        return result

    def snippets_blocker(self):
        return self.blocker

    def gates(self):
        if isinstance(self._gates, BaseException):
            raise self._gates
        return list(self._gates)


def gate(inputs: Fake) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = check_push_ready.main([], inputs)
    return code, out.getvalue()


def not_run_section(out: str) -> str:
    """The NOT RUN block alone -- the verdict line after it names what DID run."""
    return out.split("NOT RUN by this gate")[1].split("\n\n")[0]


FRONTEND = ["apps/desktop/src/pages/Approvals.tsx"]
BACKEND = ["engine/runtime/bro_hook.py", "tools/check_push_ready.py", "docs/ARCHITECTURE.md"]


class PushReady(unittest.TestCase):
    def ran(self, inputs: Fake) -> list[str]:
        return [name for name, _ in inputs.calls]

    # --- which gates run -------------------------------------------------------------

    def test_without_frontend_changes_the_bundle_gate_is_not_run_and_is_named(self):
        """Mutant: run the bundle gate always ⇒ every backend push demands a frontend
        build. The first cut of the gate also CRASHED on exactly this input -- an index
        into an empty list -- which is why it is the first test."""
        inputs = Fake(BACKEND)
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran(inputs), [SNIPPETS])
        self.assertIn(f"tools/{BUNDLE} -- no bundled frontend path changed", out)
        self.assertNotIn("Traceback", out)

    def test_a_branch_that_changes_nothing_at_all_is_green(self):
        inputs = Fake([])
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran(inputs), [SNIPPETS])

    def test_with_frontend_changes_the_bundle_gate_runs_on_the_tree_being_pushed(self):
        """Mutant: never run the bundle gate ⇒ #317 again."""
        inputs = Fake(BACKEND + FRONTEND)
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertEqual(inputs.calls, [(BUNDLE, ["--root", str(ROOT)]), (SNIPPETS, [])])
        self.assertIn(f"GREEN tools/{BUNDLE}", out)
        self.assertIn("apps/desktop/src/pages/Approvals.tsx", out)

    def test_every_path_the_bundle_is_built_from_triggers_it(self):
        """Mutant: drop any one of the six ⇒ its subTest is red."""
        for path in ("apps/desktop/src/main.tsx", "apps/desktop/src/styles/tokens.css",
                     "apps/desktop/package.json", "apps/desktop/package-lock.json",
                     "apps/desktop/vite.config.ts", "apps/desktop/perf-budget.json",
                     "apps/desktop/index.html", "apps\\desktop\\src\\main.tsx"):
            with self.subTest(path=path):
                inputs = Fake([path])
                gate(inputs)
                self.assertIn(BUNDLE, self.ran(inputs))

    def test_a_path_the_bundle_is_NOT_built_from_does_not(self):
        """The other direction. A gate that fires on every path is one somebody turns off."""
        for path in ("package.json", "apps/desktop/src-tauri/src/main.rs",
                     "apps/desktop/README.md", "apps/desktop/src-tauri/tauri.conf.json",
                     "engine/package.json", "docs/apps/desktop/src/notes.md",
                     "apps/desktop/srcs/x.ts"):
            with self.subTest(path=path):
                inputs = Fake([path])
                gate(inputs)
                self.assertNotIn(BUNDLE, self.ran(inputs))

    def test_when_what_changed_is_unknown_the_bundle_gate_RUNS(self):
        """Mutant: treat an unreadable diff as an empty one ⇒ the gate is skipped on no
        information. Not knowing what changed is not knowing that nothing did."""
        inputs = Fake(GateError("no merge base with origin/main or main could be found"))
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran(inputs), [BUNDLE, SNIPPETS])
        self.assertIn("could NOT be established", out)

    # --- the bundle gate's verdict, passed through -------------------------------------

    def test_a_stale_build_is_red_and_names_the_command(self):
        """Mutant: drop the remedy ⇒ red without `npm run build`. Mutant: ignore the exit
        code ⇒ green, which is #317."""
        code, out = gate(Fake(FRONTEND, bundle=STALE))
        self.assertEqual(code, 1, out)
        self.assertIn("3 bundled source(s) are newer", out, "the gate's own verdict was not "
                                                            "passed through")
        self.assertIn("cd apps/desktop && npm run build", out)
        self.assertIn("RED: do NOT push", out)

    def test_a_missing_build_is_red_and_names_the_command(self):
        code, out = gate(Fake(FRONTEND, bundle=MISSING))
        self.assertEqual(code, 1, out)
        self.assertIn("no Vite build manifest found", out)
        self.assertIn("cd apps/desktop && npm run build", out)

    def test_a_budget_that_is_exceeded_is_red_and_is_not_called_a_stale_build(self):
        """A fresh build that is too big is not repaired by building again."""
        code, out = gate(Fake(FRONTEND, bundle=OVER))
        self.assertEqual(code, 1, out)
        self.assertIn("exceeds budget 11.5 KB", out)
        self.assertNotIn("npm run build", out)

    # --- the snippets gate ---------------------------------------------------------------

    def test_the_snippets_gate_runs_whatever_changed(self):
        for changed in ([], BACKEND, FRONTEND):
            with self.subTest(changed=changed):
                inputs = Fake(changed)
                gate(inputs)
                self.assertIn(SNIPPETS, self.ran(inputs))

    def test_a_red_snippets_gate_is_red(self):
        """Mutant: ignore its exit code ⇒ green."""
        code, out = gate(Fake(BACKEND, snippets=(1, "RED: runbook snippets disagree with the "
                                                    "code they call:\n  bro_supervisor.run(2 args)")))
        self.assertEqual(code, 1, out)
        self.assertIn("bro_supervisor.run(2 args)", out)

    def test_an_unrunnable_snippets_gate_is_named_NOT_RUN_and_never_counted(self):
        """Mutant: count a gate that could not run among the passes ⇒ '1 gate(s) ran'.
        Mutant: run it anyway ⇒ it is called. It is not RED either: nothing here can show
        what CI will say, and refusing every push on a box without the package is a wedge."""
        inputs = Fake(BACKEND, blocker="`cryptography` does not import here")
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran(inputs), [])
        self.assertIn(f"tools/{SNIPPETS} -- COULD NOT RUN: `cryptography` does not import", out)
        self.assertIn("GREEN: 0 gate(s) ran and passed (none)", out)

    # --- what was not run ------------------------------------------------------------------

    def test_every_gate_it_did_not_run_is_named_with_its_reason(self):
        """Mutant: summarise instead of naming ⇒ a name is missing. Mutant: claim the rest
        passed ⇒ the last assertion."""
        inputs = Fake(BACKEND)
        code, out = gate(inputs)
        self.assertEqual(code, 0, out)
        for name in GATES:
            if name in (SNIPPETS, "check_push_ready.py"):
                continue
            with self.subTest(name=name):
                self.assertIn(name, not_run_section(out))
        self.assertIn("tools/check_canonical_sync.py -- needs --staged", out)
        self.assertIn("tools/check_merge_ready.py -- needs --pr N", out)
        self.assertIn("tools/check_produced_artifact.py -- needs the evidence", out)
        self.assertIn("2 argument-free gate(s)", out)
        self.assertIn("check_action_pins.py, check_coordination.py", out)
        self.assertIn("This is not every gate.", out)
        self.assertIn("8 named above were not run", out)
        self.assertNotIn("every gate passed", out.lower())
        self.assertNotIn("all gates", out.lower())

    def test_a_gate_that_ran_is_not_also_listed_as_not_run(self):
        inputs = Fake(FRONTEND)
        _, out = gate(inputs)
        not_run = not_run_section(out)
        self.assertNotIn(BUNDLE, not_run)
        self.assertNotIn(SNIPPETS, not_run)

    def test_the_reason_tables_name_gates_that_exist(self):
        """A table naming a gate that was renamed away would file the real one under
        'argument-free' and the dead name nowhere."""
        for name in (*check_push_ready.NEEDS_ARGUMENTS, *check_push_ready.NEEDS_ARTIFACT,
                     BUNDLE, SNIPPETS, check_push_ready.SELF):
            with self.subTest(name=name):
                self.assertTrue((TOOLS / name).is_file(), name)

    # --- failing inputs ---------------------------------------------------------------------

    def test_a_gate_that_crashes_or_times_out_is_red_with_that_fact(self):
        """Mutant: swallow the failure ⇒ green, with a gate that never answered."""
        for name, kwargs in ((BUNDLE, {"bundle": GateError(f"tools/{BUNDLE} did not finish "
                                                           f"within 40s")}),
                             (SNIPPETS, {"snippets": GateError("could not be started")})):
            with self.subTest(name=name):
                code, out = gate(Fake(FRONTEND, **kwargs))
                self.assertEqual(code, 1, out)
                self.assertIn(f"tools/{name} could not be run to a verdict", out)
                self.assertNotIn("Traceback", out)

    def test_an_unexpected_exception_is_red_and_never_a_traceback(self):
        """Mutant: drop the outer except ⇒ a traceback, which the hook reads as no verdict."""
        code, out = gate(Fake(BACKEND, gates=RuntimeError("the unexpected")))
        self.assertEqual(code, 1, out)
        self.assertIn("RED: do NOT push -- the gate itself failed: RuntimeError", out)
        self.assertNotIn("Traceback", out)


class TheRealInputs(unittest.TestCase):
    """`Inputs` itself, against a repository on disk."""

    def _git(self, cwd: pathlib.Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t",
             "-c", "commit.gpgsign=false", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    def _repo(self, tmp: pathlib.Path) -> pathlib.Path:
        self._git(tmp, "init", "-q", "-b", "main")
        (tmp / "apps" / "desktop" / "src").mkdir(parents=True)
        (tmp / "README.md").write_text("one\n", encoding="utf-8")
        (tmp / "apps" / "desktop" / "src" / "old.ts").write_text("export {}\n", encoding="utf-8")
        self._git(tmp, "add", "-A")
        self._git(tmp, "commit", "-qm", "main")
        self._git(tmp, "checkout", "-q", "-b", "feature")
        return tmp

    def test_changed_is_the_committed_range_plus_what_is_staged(self):
        """Mutant: drop the staged half ⇒ `staged.ts` is missing. Mutant: diff the working
        tree ⇒ `unstaged.ts` appears, and it is not in the push."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(pathlib.Path(tmp))
            src = root / "apps" / "desktop" / "src"
            (src / "committed.ts").write_text("export {}\n", encoding="utf-8")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "feature")
            (src / "staged.ts").write_text("export {}\n", encoding="utf-8")
            self._git(root, "add", "apps/desktop/src/staged.ts")
            (src / "unstaged.ts").write_text("export {}\n", encoding="utf-8")
            (root / "README.md").write_text("two, not staged\n", encoding="utf-8")

            base, changed = check_push_ready.Inputs(root).changed()
        self.assertRegex(base, r"^[0-9a-f]{40}$")
        self.assertEqual(changed, ["apps/desktop/src/committed.ts", "apps/desktop/src/staged.ts"])

    def test_a_repository_with_no_main_is_a_GateError_not_an_empty_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._git(root, "init", "-q", "-b", "elsewhere")
            (root / "a.txt").write_text("a\n", encoding="utf-8")
            self._git(root, "add", "-A")
            self._git(root, "commit", "-qm", "only")
            with self.assertRaises(GateError):
                check_push_ready.Inputs(root).changed()

    def test_run_gate_runs_the_gate_of_the_tree_it_was_given(self):
        """Mutant: run this checkout's copy ⇒ the verdict is about the wrong tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "tools").mkdir()
            (root / "tools" / "check_x.py").write_text(
                "import sys\nprint('GREEN from', sys.argv[1])\nsys.stderr.write('and stderr')\n"
                "sys.exit(3)\n", encoding="utf-8")
            inputs = check_push_ready.Inputs(root)
            code, text = inputs.run_gate("check_x.py", ["the-tree"])
            self.assertEqual(code, 3)
            self.assertIn("GREEN from the-tree", text)
            self.assertIn("and stderr", text)
            self.assertEqual(inputs.gates(), ["check_x.py"])

    def test_the_two_gates_it_runs_take_the_arguments_it_passes(self):
        """`check_bundle_budget.py --root` and a bare `check_runbook_snippets.py`: if either
        stopped accepting that, this gate would report a usage error as a RED bundle."""
        import check_bundle_budget
        import inspect
        self.assertIn('"--root"', inspect.getsource(check_bundle_budget.main))
        for marker in check_push_ready.NO_BUILD:
            self.assertIn(marker, inspect.getsource(check_bundle_budget))


if __name__ == "__main__":
    unittest.main()
