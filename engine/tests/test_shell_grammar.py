"""The shell command language, held against three things that are not the code under test.

`bro_security.parse_simple_command` accepts one small language and refuses everything else
(docs/design/SHELL_CLASSIFIER_DESIGN.md, Appendix A). A test that asked the function what it
accepts and then agreed with it would prove nothing, so every acceptance here is compared with
something written independently of it:

  1. a MODEL: the language written a second time, as one regular expression, in this file;
  2. real `bash`: an accepted command is run with a probe as its executable, and the argument
     list Bash hands the probe must be the one the gate derived -- one invocation, no more;
  3. a pinned Bash PARSER (tree-sitter-bash): test-only, never imported by the wall, and required
     where CI declares it, so its absence fails there instead of skipping.

What is run under Bash is only what the gate ACCEPTED, plus a short list of forms whose whole
point is that Bash makes two commands of them. Everything is built from the words `probe`, `a`,
`b`, `x` and `INJECTED`, in an empty directory, with a PATH that holds the probe and nothing else.
"""
import importlib.metadata
import itertools
import os
import pathlib
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_authorization import classify_tool_action
from bro_security import SecurityError, analyze_command, parse_simple_command, validate_exact_push

# ---- 1. the model: the language, written a second time ------------------------------------

BARE_CHARS = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ" "abcdefghijklmnopqrstuvwxyz" "0123456789" "_./:=@%+^-")
_CONTROL = "\\x00-\\x1f\\x7f-\\x9f\\ud800-\\udfff\\u2028\\u2029"
_SINGLE = f"'[^'\"{_CONTROL}]*'"
_DOUBLE = f"\"[^\"'$`\\\\!{_CONTROL}]*\""
_BARE = "[" + re.escape(BARE_CHARS) + "]"
# `~` is a literal only after the word has begun and not straight after a bare `=` or `:`. The
# lookbehind sees the character before it: a closing quote there is fine, `=` and `:` are not.
_WORD = f"(?:{_SINGLE}|{_DOUBLE}|{_BARE})(?:{_SINGLE}|{_DOUBLE}|{_BARE}|(?<![=:])~)*"
MODEL = re.compile(f"[ \\t]*{_WORD}(?:[ \\t]+{_WORD})*[ \\t]*")
MODEL_WORD = re.compile(_WORD)


def model_argv(command: str):
    """What the model says the argument list is, or None when it refuses."""
    if not MODEL.fullmatch(command):
        return None
    # A quoted part cannot contain either quote character, so removing them all is exact.
    argv = tuple(re.sub("['\"]", "", word) for word in MODEL_WORD.findall(command))
    return None if "=" in argv[0] else argv


def gate_argv(command: str):
    try:
        return parse_simple_command(command)
    except SecurityError:
        return None


# ---- 2. the Bash oracle ---------------------------------------------------------------------

BASH = shutil.which("bash") if os.name == "posix" else None


class BashOracle:
    """Runs a command line under real Bash and reports what Bash actually executed."""

    def __init__(self):
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="bro-shell-oracle-"))
        self.bin = self.base / "bin"
        self.work = self.base / "work"
        self.home = self.base / "home"
        for path in (self.bin, self.work, self.home):
            path.mkdir()
        self.log = self.base / "probe.log"
        self.count = self.base / "commands.count"
        # Files a pathname expansion would match, so a glob that slipped through shows up as
        # an argument list the gate did not derive rather than as the unmatched pattern.
        for name in ("a", "b", "x", "ab", "aXb", "a.b", "a-b"):
            (self.work / name).write_text("", encoding="utf-8")
        probe = self.bin / "probe"
        probe.write_text(f"#!{BASH}\nprintf '%s\\0' \"$#\" \"$@\" >> \"$PROBE_LOG\"\n", encoding="utf-8")
        probe.chmod(probe.stat().st_mode | stat.S_IXUSR)
        # Read by a non-interactive bash before the command: counts every simple command Bash
        # is about to run, including ones that are not the probe. The probe is itself a bash
        # script and inherits BASH_ENV, so the trap is installed in the outermost shell only.
        self.env_file = self.base / "bash_env"
        self.env_file.write_text(
            "if [ -z \"$PROBE_INNER\" ]; then export PROBE_INNER=1; set -T; "
            "trap 'printf x >> \"$PROBE_COUNT\"' DEBUG; fi\n", encoding="utf-8")

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def run(self, command: str):
        """(every probe invocation's argument list, how many simple commands Bash ran)."""
        for path in (self.log, self.count):
            path.write_bytes(b"")
        subprocess.run(
            [BASH, "--norc", "--noprofile", "-c", command],
            cwd=self.work, capture_output=True, timeout=20, stdin=subprocess.DEVNULL,
            env={"PATH": str(self.bin), "HOME": str(self.home), "PROBE_LOG": str(self.log),
                 "PROBE_COUNT": str(self.count), "BASH_ENV": str(self.env_file),
                 "LC_ALL": "C.UTF-8"},
        )
        fields = self.log.read_bytes().split(b"\0")[:-1]
        calls, i = [], 0
        while i < len(fields):
            n = int(fields[i])
            calls.append(tuple(f.decode("utf-8", "surrogateescape") for f in fields[i + 1:i + 1 + n]))
            i += 1 + n
        return calls, len(self.count.read_bytes())


class _WithBash(unittest.TestCase):
    oracle = None

    # Skipped per TEST, not per class: a class-level skip removes its tests from the count
    # unittest prints, and this suite's size is a number the repository states and checks.
    def setUp(self):
        if BASH is None:
            if sys.platform.startswith("linux"):
                self.fail("no bash on a Linux runner: the oracle cannot be skipped here")
            self.skipTest("the Bash oracle needs a POSIX bash; CI's Linux jobs run it")
        cls = type(self)
        if cls.oracle is None:
            cls.oracle = BashOracle()
            cls.addClassCleanup(cls.oracle.close)

    def assert_bash_agrees(self, command: str, argv):
        """Bash ran ONE command, it was the probe, and it got the gate's arguments."""
        calls, ran = self.oracle.run(command)
        self.assertEqual(calls, [tuple(argv[1:])], f"bash disagrees with the gate on {command!r}")
        self.assertEqual(ran, 1, f"bash ran {ran} commands for {command!r}")


# ---- inputs -----------------------------------------------------------------------------------

#: Every refusal the classifier already made, the two findings, and the design's list. Each must
#: raise; none may be classified at all.
REFUSED = (
    # R2-0001: a comment, and a quote inside it that swallowed the newline for the old lexer.
    "echo hi # ' \n echo INJECTED", "echo hi # ' \n rm -rf src #'", "echo hi # rm -rf src",
    "echo hi #", "#", "echo a#b",
    # R2-0002: ANSI-C and locale quoting.
    "echo $'\\'' ; echo INJECTED-RAN ; echo \\'", "echo $'x'", 'echo $"x" ; echo y', 'echo $"x"',
    # Expansion: parameter, pathname, brace, tilde, arithmetic, command, process.
    'cat "$FILE"', "cat $FILE", "cat ${FILE}", "cat *.json", "cat x?", "cat [ab].txt",
    "cat {a,b}.json", "cat a,b", "cat ~/x", "cat ~", "cat x=~/y", "cat x:~/y", "echo $((1+1))",
    "cat $(rm -rf x)", 'cat "$(rm -rf x)"', "echo `whoami`", 'echo "`whoami`"', "cat <(ls)",
    # Newline, CR and continuation, bare and inside either quote.
    "echo hi\necho two", "echo hi\r\necho two", "echo hi\r", "cat a\\\nb", "echo 'a\nb'",
    'echo "a\nb"', "echo hi\n",
    # Redirection, here-document, here-string.
    "echo hacked > file.txt", "cat x < y", "cat x >> y", "cat x 2>&1", "cat <<EOF", "cat <<< x",
    # Lists, pipelines, background.
    "echo hi & rm -rf src", "echo hi &rm -rf src", "ls& git push origin main", "sleep 5 &",
    "echo a |& tee b", "echo hi && rm -rf src", "cat x || cat y", "cat x ; cat y", "cat x;",
    "git log | git show",
    # Grouping and compound commands.
    "(cat x)", "{ cat x; }", "! cat x", "f() { cat x; }", "if true; then cat x; fi",
    "for i in a; do cat x; done", "case x in x) cat y;; esac",
    # Escapes, assignment prefixes, unterminated quotes, nothing at all.
    "echo a\\ b", "echo a \\& b", 'echo "a\\"b"', "FOO=1 cat x", "'FOO=1' cat x",
    "echo 'unterminated", 'echo "unterminated', "", "   ", "\t",
    # Control characters and what is not ASCII outside quotes.
    "echo \x00", "echo \x7f", "echo '\x1b[0m'", 'echo "\x07"', "echo 'a\tb'", "echo \u00e9",
    "echo '\udc80'", "echo '\u2028'", "echo \u00a0x", "echo '\x85'", "echo \x0b", "echo \x0c",
    # History, and a quote of the other kind inside a quote.
    'echo "a!b"', "echo '\"'", "echo \"'\"",
)

#: Forms Bash makes MORE than one command of. Listed so the corpus cannot be vacuous: the oracle
#: must really report two (or three) runs, and the gate must refuse.
BASH_FORMS_SEVERAL = (
    ("probe hi # ' \n probe INJECTED", 2),          # R2-0001
    ("probe $'\\'' ; probe INJECTED ; probe \\'", 3),  # R2-0002
    ("probe a ; probe b", 2), ("probe a && probe b", 2), ("probe a & probe b", 2),
    ("probe a\nprobe b", 2), ("probe a | probe b", 2),
)

#: Forms where Bash runs ONE command with arguments that are not the characters typed.
BASH_CHANGES_ARGUMENTS = (
    "probe a*b", "probe a?b", "probe ~", "probe x=~", "probe x=a:~", "probe {a,b}", "probe $HOME",
    "probe a\\ b", "probe $'a'", "probe a\\\nb",
)

ACCEPTED = (
    ("probe", ("probe",)), ("  probe  a\tb ", ("probe", "a", "b")),
    ("probe 'a b' \"c d\" e", ("probe", "a b", "c d", "e")),
    ("probe --format=\"%H %s\" -n 5", ("probe", "--format=%H %s", "-n", "5")),
    ("probe '*.py' 'x?' '[ab]' '{a,b}' '~' '$HOME' '`x`' 'a;b' 'a|b' 'a&b' '#x' 'a\\b'",
     ("probe", "*.py", "x?", "[ab]", "{a,b}", "~", "$HOME", "`x`", "a;b", "a|b", "a&b", "#x", "a\\b")),
    ("probe \"a;b\" \"a|b\" \"a&b\" \"#x\" \"*\" \"~\" \"(x)\" \"{a,b}\" \"<>\"",
     ("probe", "a;b", "a|b", "a&b", "#x", "*", "~", "(x)", "{a,b}", "<>")),
    ("probe HEAD~1 a~ a~b 'x='~ \"x:\"~", ("probe", "HEAD~1", "a~", "a~b", "x=~", "x:~")),
    ("probe a=b --x=y :: @ % + ^ - . /", ("probe", "a=b", "--x=y", "::", "@", "%", "+", "^", "-", ".", "/")),
    ("probe '' \"\" a''b", ("probe", "", "", "ab")),
    ("probe '\u0570\u0561\u0575' \"\u00e9 \U0001f600\"", ("probe", "\u0570\u0561\u0575", "\u00e9 \U0001f600")),
    ("'probe' x", ("probe", "x")), ("pr\"ob\"e x", ("probe", "x")),
)


def generated(seed: int = 159, cases: int = 4000):
    """Deterministic combinations of quote, comment, newline, CRLF, escape, expansion,
    redirection and compound-command fragments, each led by the probe."""
    pieces = ("probe", "a", "b", "x", " ", " ", "\t", "'", '"', "#", "\n", "\r\n", "\\", "$'",
              '$"', "$x", "$(", ")", "`", ";", "&", "&&", "||", "|", ">", "<", "*", "?", "[", "]",
              "{", "}", ",", "~", "=", ":", "!", "-", ".", "/", "'a b'", '"a b"', "\u00e9", "''")
    rng = random.Random(seed)
    for _ in range(cases):
        yield "probe " + "".join(rng.choice(pieces) for _ in range(rng.randint(1, 9)))


def byte_table():
    """Every ASCII byte in each place a character can stand: (context, command)."""
    for code in range(128):
        ch = chr(code)
        yield "bare-inside", ch, f"probe a{ch}b"
        yield "bare-first", ch, f"probe {ch}b"
        yield "single", ch, f"probe 'a{ch}b'"
        yield "double", ch, f"probe \"a{ch}b\""


PRINTABLE = {chr(c) for c in range(0x20, 0x7F)}
#: What each place accepts, typed out here and not read from the code under test.
TABLE_ACCEPTS = {
    "bare-inside": set(BARE_CHARS) | {"~", " ", "\t"},
    "bare-first": set(BARE_CHARS) | {" ", "\t"},
    "single": PRINTABLE - {"'", '"'},
    "double": PRINTABLE - {'"', "'", "$", "`", "\\", "!"},
}


# ---- tests ------------------------------------------------------------------------------------

class RefusalCorpusTests(unittest.TestCase):
    def test_every_listed_form_is_refused_and_never_classified(self):
        for command in REFUSED:
            with self.assertRaises(SecurityError, msg=repr(command)):
                analyze_command(command)
            self.assertIsNone(model_argv(command), f"the model accepts {command!r}")

    def test_the_two_findings_are_refused_through_the_tool_classifier(self):
        for command in ("echo hi # ' \n rm -rf src #'", "echo $'\\'' ; rm -rf src ; echo \\'"):
            with self.assertRaises(SecurityError, msg=repr(command)):
                classify_tool_action("Bash", {"command": command})

    def test_what_bash_makes_several_commands_of_is_refused(self):
        for command, _runs in BASH_FORMS_SEVERAL + tuple((c, 1) for c in BASH_CHANGES_ARGUMENTS):
            self.assertIsNone(gate_argv(command), repr(command))

    def test_a_refusal_says_what_it_refused(self):
        with self.assertRaises(SecurityError) as caught:
            parse_simple_command("echo hi ; rm x")
        self.assertIn("';' outside quotes", str(caught.exception))

    def test_keywords_and_wrappers_are_one_command_that_is_never_a_read(self):
        """Made of letters, so the language accepts them as ONE command; what refuses them is
        the executable allowlist, which is unchanged. None may come out READ_LOCAL."""
        for command in ("time cat x", "eval cat x", "exec cat x", "source x", ". x", "env cat x",
                        "command cat x", "builtin echo x", "nohup cat x", "coproc cat x",
                        "bash -c 'cat x'", "sh -c 'cat x'", "if x", "while x", ": x"):
            classified = classify_tool_action("Bash", {"command": command})
            self.assertNotIn("READ_LOCAL", classified.capabilities, command)
            self.assertTrue(classified.unknown or classified.mutating, command)


class AcceptedLanguageTests(unittest.TestCase):
    def test_the_gate_derives_the_argument_list_the_model_does(self):
        for command, argv in ACCEPTED:
            self.assertEqual(gate_argv(command), argv, repr(command))
            self.assertEqual(model_argv(command), argv, repr(command))

    def test_every_ascii_byte_in_every_place_is_accepted_or_refused_as_the_table_says(self):
        checked = 0
        for context, ch, command in byte_table():
            expected = ch in TABLE_ACCEPTS[context]
            self.assertEqual(gate_argv(command) is not None, expected,
                             f"{context}: {ch!r} in {command!r}")
            self.assertEqual(model_argv(command) is not None, expected,
                             f"model, {context}: {ch!r}")
            checked += 1
        self.assertEqual(checked, 4 * 128)

    def test_gate_and_model_agree_on_every_generated_input(self):
        accepted = 0
        for command in generated():
            got = gate_argv(command)
            self.assertEqual(got, model_argv(command), repr(command))
            accepted += got is not None
        # Not vacuous in either direction: the generator must reach both verdicts.
        self.assertGreater(accepted, 100)
        self.assertLess(accepted, 3000)

    def test_tilde_is_a_literal_only_where_bash_leaves_it_alone(self):
        for command in ("probe ~", "probe ~a", "probe a=~", "probe a=~/x", "probe a:~", "probe --x=~"):
            self.assertIsNone(gate_argv(command), command)
        for command in ("probe a~", "probe HEAD~1", "probe '~'", 'probe "a="~', "probe a='~'"):
            self.assertIsNotNone(gate_argv(command), command)

    def test_unicode_is_data_inside_quotes_and_nothing_outside_them(self):
        self.assertEqual(gate_argv("echo '\u0562\u0561\u0580\u0565\u0582'"), ("echo", "\u0562\u0561\u0580\u0565\u0582"))
        self.assertIsNone(gate_argv("echo \u0562\u0561\u0580\u0565\u0582"))
        for code in itertools.chain(range(0x00, 0x20), range(0x7F, 0xA0), (0xD800, 0xDFFF, 0x2028, 0x2029)):
            for quote in "'\"":
                self.assertIsNone(gate_argv(f"echo {quote}a{chr(code)}b{quote}"), hex(code))

    def test_the_command_name_cannot_be_an_assignment(self):
        for command in ("A=1 cat x", "'A=1' cat x", "a=b"):
            self.assertIsNone(gate_argv(command), command)
        self.assertEqual(gate_argv("cat A=1"), ("cat", "A=1"))


class BashAgreesTests(_WithBash):
    """An accepted command is ONE command to Bash, with the gate's arguments."""

    def test_the_oracle_can_see_a_second_command(self):
        """The control: on the forms that matter, Bash really does run more than one."""
        for command, runs in BASH_FORMS_SEVERAL:
            calls, _ = self.oracle.run(command)
            self.assertEqual(len(calls), runs, repr(command))

    def test_the_oracle_can_see_an_argument_bash_rewrote(self):
        for command in BASH_CHANGES_ARGUMENTS:
            calls, _ = self.oracle.run(command)
            typed = tuple(command.split(" ", 1)[1].split(" "))
            self.assertNotEqual(calls, [typed], f"bash left {command!r} as typed")

    def test_bash_agrees_on_the_accepted_examples(self):
        for command, argv in ACCEPTED:
            self.assert_bash_agrees(command, argv)

    def test_bash_agrees_wherever_the_gate_accepts_a_tilde(self):
        """Bash expands `~` first in a word and after `=` or `:` in a word shaped like an
        assignment. Whatever the gate accepts among these, Bash must leave exactly as typed."""
        accepted = 0
        for command in ("probe ~", "probe ~a", "probe x=~", "probe x=~/a", "probe x=a:~",
                        "probe x:~", "probe --x=~", "probe a~", "probe HEAD~1", "probe a~b~",
                        "probe 'x='~", "probe x='~'", "probe \"~\""):
            argv = gate_argv(command)
            if argv is not None:
                self.assert_bash_agrees(command, argv)
                accepted += 1
        self.assertEqual(accepted, 6)

    def test_bash_agrees_on_every_accepted_byte_of_the_table(self):
        ran = 0
        for _context, _ch, command in byte_table():
            argv = gate_argv(command)
            if argv is not None:
                self.assert_bash_agrees(command, argv)
                ran += 1
        self.assertGreater(ran, 200)

    def test_bash_agrees_on_every_generated_input_the_gate_accepts(self):
        ran = 0
        for command in generated():
            argv = gate_argv(command)
            if argv is not None:
                self.assert_bash_agrees(command, argv)
                ran += 1
        self.assertGreater(ran, 100)


# ---- 3. the pinned parser: test-only, and required where CI says so ---------------------------

PARSER_PINS = {"tree-sitter": "0.26.0", "tree-sitter-bash": "0.25.1"}
ORACLE_REQUIRED = os.environ.get("BRO_SHELL_PARSER_ORACLE") == "required"
#: Leaf kinds a command made only of literal words may contain.
LITERAL_LEAVES = {"word", "number", "raw_string", "string_content", '"'}


def _load_parser():
    import tree_sitter
    import tree_sitter_bash
    return tree_sitter.Parser(tree_sitter.Language(tree_sitter_bash.language()))


def _leaves(node, out):
    if node.child_count == 0:
        out.append(node)
    for child in node.children:
        _leaves(child, out)
    return out


class ParserOracleTests(unittest.TestCase):
    parser = None

    def setUp(self):  # per test, for the reason given on _WithBash
        cls = type(self)
        if cls.parser is None:
            try:
                cls.parser = _load_parser()
            except Exception as exc:  # an import that fails for ANY reason is an unusable oracle
                if ORACLE_REQUIRED:
                    self.fail(f"this job declares the Bash parser oracle and it cannot be "
                              f"loaded: {exc!r}")
                self.skipTest("tree-sitter-bash is not installed here; the CI job that sets "
                              "BRO_SHELL_PARSER_ORACLE=required fails without it")

    def _assert_parser_agrees(self, command, argv):
        tree = self.parser.parse(command.encode("utf-8"))
        root = tree.root_node
        self.assertFalse(root.has_error, repr(command))
        self.assertEqual([child.type for child in root.children], ["command"], repr(command))
        leaves = _leaves(root, [])
        self.assertLessEqual({leaf.type for leaf in leaves}, LITERAL_LEAVES, repr(command))
        # Every byte that is not a blank between words is inside some leaf.
        covered = b"".join(leaf.text for leaf in leaves)
        self.assertEqual(covered, "".join(MODEL_WORD.findall(command)).encode("utf-8"), repr(command))
        words = [re.sub("['\"]", "", child.text.decode("utf-8")) for child in root.children[0].children]
        self.assertEqual(tuple(words), argv, repr(command))

    def test_the_installed_parser_is_the_pinned_one(self):
        for package, version in PARSER_PINS.items():
            self.assertEqual(importlib.metadata.version(package), version, package)

    def test_the_parser_sees_both_findings_as_more_than_one_command(self):
        for command, runs in BASH_FORMS_SEVERAL[:2]:
            root = self.parser.parse(command.encode("utf-8")).root_node
            self.assertEqual(sum(child.type == "command" for child in root.children), runs)

    def test_the_parser_agrees_on_the_accepted_examples(self):
        for command, argv in ACCEPTED:
            self._assert_parser_agrees(command, argv)

    def test_the_parser_agrees_on_every_accepted_byte_and_generated_input(self):
        ran = 0
        for command in itertools.chain((c for _a, _b, c in byte_table()), generated()):
            argv = gate_argv(command)
            if argv is not None:
                self._assert_parser_agrees(command, argv)
                ran += 1
        self.assertGreater(ran, 300)


class ParserStaysOutOfTheWallTests(unittest.TestCase):
    def test_the_oracle_lock_pins_the_versions_this_module_names(self):
        text = (ROOT / "requirements-test-oracle.txt").read_text(encoding="utf-8")
        for package, version in PARSER_PINS.items():
            self.assertRegex(text, rf"(?m)^{re.escape(package)}=={re.escape(version)} \\$")
        pinned = re.findall(r"(?m)^([A-Za-z0-9_.-]+)==", text)
        self.assertEqual(sorted(pinned), sorted(PARSER_PINS), "the oracle lock pins something else")

    def test_the_deployment_lock_carries_no_parser(self):
        """requirements-ci.txt is what the production install reads. The Architect's audit of
        #333 was RED on exactly this: the parser was pinned there and labelled test-only."""
        text = (ROOT / "requirements-ci.txt").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?im)^\s*tree[-_]sitter")

    def test_the_deployment_runbook_does_not_install_the_oracle_lock(self):
        runbook = ROOT.parent / "docs" / "DEBIAN_DEPLOYMENT.md"
        if not runbook.is_file():
            self.skipTest("the deployment runbook lives in the monorepo, not in the engine tree")
        text = runbook.read_text(encoding="utf-8")
        self.assertIn("requirements-ci.txt", text)
        self.assertNotIn("requirements-test-oracle", text)

    def test_no_runtime_or_tool_module_imports_a_parser(self):
        """The acceptance decision must be reproducible without the parser package: a wall that
        imported it would refuse every shell command wherever it is not installed."""
        offenders = [str(path.relative_to(ROOT))
                     for folder in ("runtime", "tools")
                     for path in sorted((ROOT / folder).rglob("*.py"))
                     if re.search(r"tree_sitter|tree-sitter", path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


# ---- what the classifier does with an accepted command ----------------------------------------

class ClassificationIsStableTests(unittest.TestCase):
    READS = (
        ("cat README.md", ("README.md",)),
        ("ls -la src", ("src",)),
        ("git status", ()),
        ("git diff --stat HEAD~1", ("--stat", "HEAD~1")),
        ('git log --format="%H %s" -n 5', ("--format=%H %s", "-n", "5")),
        ("find . -name '*.py'", (".",)),
        ("echo 'a & b'", ()),
    )

    def test_safe_commands_keep_their_capability_and_targets(self):
        for command, targets in self.READS:
            classified = classify_tool_action("Bash", {"command": command})
            self.assertEqual(classified.capabilities, ("READ_LOCAL",), command)
            self.assertEqual(classified.targets, targets, command)
            self.assertFalse(classified.mutating, command)
            self.assertEqual(len(classified.command_infos), 1, command)

    def test_a_write_is_still_a_governed_mutation_with_its_target(self):
        classified = classify_tool_action("Bash", {"command": "rm docs/x.md"})
        self.assertTrue(classified.mutating and classified.requires_scope and classified.requires_work_grant)
        self.assertEqual(classified.targets, ("docs/x.md",))
        self.assertIn("DELETE", classified.capabilities)
        commit = classify_tool_action("Bash", {"command": 'git commit -m "x y"'})
        self.assertIn("WRITE_REPOSITORY", commit.capabilities)
        self.assertTrue(commit.mutating)

    def test_a_path_qualified_executable_is_still_never_a_read(self):
        for command in ("./tmp/echo hi", "/usr/bin/git status", "'./my tools/pwd'"):
            classified = classify_tool_action("Bash", {"command": command})
            self.assertNotIn("READ_LOCAL", classified.capabilities, command)
            self.assertTrue(classified.mutating, command)

    def test_the_release_push_is_the_exact_four_words(self):
        validate_exact_push("git push origin HEAD:t-1", "t-1")
        validate_exact_push('git push origin "HEAD:t-1"', "t-1")
        for command in ("git push origin HEAD:t-1 # ' \n git push origin HEAD:main",
                        "git push origin HEAD:t-1 ; git push origin HEAD:main",
                        "git push origin $'HEAD:t-1'", "git push origin HEAD:t-1\n",
                        "git push origin HEAD:*",
                        # A fifth word. Nothing tested the length check before T-159: with it
                        # removed, a trailing `--force` passed every other condition.
                        "git push origin HEAD:t-1 --force", "git push origin HEAD:t-1 extra",
                        "git push origin"):
            with self.assertRaises(SecurityError, msg=repr(command)):
                validate_exact_push(command, "t-1")


class OnlyBashIsVouchedForTests(unittest.TestCase):
    """Appendix A, Q2: the gate runs for all three shell tools; a READ is granted only to Bash."""

    def test_a_read_is_read_local_under_bash_and_unknown_under_the_others(self):
        for command, _targets in ClassificationIsStableTests.READS:
            self.assertEqual(classify_tool_action("Bash", {"command": command}).capabilities,
                             ("READ_LOCAL",), command)
            for tool in ("PowerShell", "Shell"):
                classified = classify_tool_action(tool, {"command": command})
                self.assertEqual(classified.capabilities, ("UNKNOWN",), f"{tool}: {command}")
                self.assertTrue(classified.unknown and classified.mutating, f"{tool}: {command}")
                self.assertTrue(classified.requires_task and classified.requires_work_grant)

    def test_a_powershell_read_verb_is_unknown_too(self):
        for command in ("Get-Content x", "gci", "Test-Path x", "Select-String a b"):
            for tool in ("PowerShell", "Shell"):
                self.assertTrue(classify_tool_action(tool, {"command": command}).unknown, command)

    def test_a_mutation_is_classified_the_same_under_every_shell_tool(self):
        for command in ("rm docs/x.md", "git update-ref refs/heads/x HEAD", "Remove-Item x",
                        "git push origin HEAD:t-1"):
            expected = classify_tool_action("Bash", {"command": command})
            for tool in ("PowerShell", "Shell"):
                got = classify_tool_action(tool, {"command": command})
                self.assertEqual((got.capabilities, got.targets, got.mutating, got.push),
                                 (expected.capabilities, expected.targets, expected.mutating,
                                  expected.push), f"{tool}: {command}")

    def test_no_tool_name_carries_a_refused_command_past_the_gate(self):
        for tool in ("Bash", "PowerShell", "Shell"):
            for command in ("echo hi ; rm -rf src", "echo hi # ' \n rm -rf src #'", "cat $x"):
                with self.assertRaises(SecurityError, msg=f"{tool}: {command!r}"):
                    classify_tool_action(tool, {"command": command})


if __name__ == "__main__":
    unittest.main()
