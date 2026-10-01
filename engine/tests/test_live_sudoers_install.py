"""How the two live kits put a fragment into /etc/sudoers.d — EXECUTED, not read.

`run_live_turn.sh` and `run_ladder_turn.sh` are root scripts, and one file sudo cannot parse in
/etc/sudoers.d makes sudo refuse every command for every account on the machine. Until T-141 both
kits wrote the fragment straight into that directory, validated it afterwards, skipped the
validation when `visudo` was not on PATH, and armed the trap that removes it hundreds of lines
later. On a CI runner none of that matters. It was found by running the kit on a real box.

The `sudoers-install` block is lifted out of BOTH scripts verbatim and run in bash against a
directory standing in for /etc/sudoers.d, a `visudo` that answers what the test tells it to, and a
`chown` that records instead of changing ownership (this suite does not run as root). So what is
checked is behaviour: a fragment that fails validation never has a name in the target directory, a
missing visudo refuses, a valid one lands 0440 as the very inode that was validated, and the kit's
own `cleanup` — also lifted, also run — removes fragment and staging directory on every exit.

WHAT THIS CANNOT CHECK: that root's `chown 0:0` succeeds on a real /etc, that the real
/etc/sudoers.d and its sibling staging directory share a filesystem on a given machine (the block
refuses if they do not), and that either kit still completes its turn. Only the CI ladder and live
jobs run the kits.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(ENGINE_ROOT, "ci", "live")
KITS = ("run_live_turn.sh", "run_ladder_turn.sh")

BLOCK_OPEN = "# >>> sudoers-install >>>"
BLOCK_CLOSE = "# <<< sudoers-install <<<"

# kit -> [(the variable naming the fragment's final path, the heredoc that builds it)]
FRAGMENTS = {
    "run_live_turn.sh": [("SUDOERS", "PYSUDO")],
    "run_ladder_turn.sh": [("SUDOERS", "PYSUDO"), ("DRIVER_SUDOERS", "PYDRVSUDO")],
}

# What each fragment says for the fixture below. Generated from the heredocs as they stood BEFORE
# T-141 moved the write, and unchanged by it: that change is about how the file gets there.
RECORDER_ARGS = (
    "/opt/brops-live/bin/governed_recorder --store /opt/brops-live/store"
    " --launcher /opt/brops-live/tcb/privileged-launcher.bin"
    " --executor /opt/brops-live/bin/proof_executor --lease /opt/brops-live/tcb/executor.lease"
    " --cgroup brops-live --out /opt/brops-live/report/%(kit)s-*.out"
    " --containment-out /opt/brops-live/report/%(kit)s-*.out.containment.json"
    " --evidence-out /opt/brops-live/evidence-state/*.evidence.json"
    " --evidence-state /opt/brops-live/evidence-state\n")
EXPECTED_FRAGMENT = {
    ("run_live_turn.sh", "PYSUDO"):
        "brops-verifier_broker ALL=(brops-recorder) NOPASSWD: " + RECORDER_ARGS % {"kit": "live"},
    ("run_ladder_turn.sh", "PYSUDO"):
        "brops-supervisor ALL=(brops-recorder) NOPASSWD: " + RECORDER_ARGS % {"kit": "ladder"},
    ("run_ladder_turn.sh", "PYDRVSUDO"):
        "brops-verifier_broker ALL=(brops-sidecar) NOPASSWD: /usr/bin/env "
        "BROPS_SUPERVISOR_SOCKET\\=/opt/brops-live/sock/supervisor.sock /usr/bin/python3 "
        "/opt/brops-live/bridge/engine_sidecar.py\n",
}
FIXTURE_CONFIG = {"execution": {
    "recorder_command": ["sudo", "-n", "-u", "brops-recorder", "/opt/brops-live/bin/governed_recorder"],
    "report_dir": "/opt/brops-live/report",
    "evidence_state_dir": "/opt/brops-live/evidence-state",
    "recorder_store_dir": "/opt/brops-live/store",
    "launcher_path": "/opt/brops-live/tcb/privileged-launcher.bin",
    "executor_path": "/opt/brops-live/bin/proof_executor",
    "lease_file": "/opt/brops-live/tcb/executor.lease",
    "cgroup_arg": "brops-live",
}}


def _script(name: str) -> str:
    with open(os.path.join(LIVE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _block(script: str) -> str:
    """The `sudoers-install` block, markers included."""
    lines = script.split("\n")
    opens = [i for i, line in enumerate(lines) if line == BLOCK_OPEN]
    closes = [i for i, line in enumerate(lines) if line == BLOCK_CLOSE]
    if len(opens) != 1 or len(closes) != 1 or closes[0] < opens[0]:
        raise AssertionError("sudoers-install markers: %d open, %d close" % (len(opens), len(closes)))
    return "\n".join(lines[opens[0]:closes[0] + 1]) + "\n"


def _outside_block(script: str) -> list[tuple[int, str]]:
    """(line index, line) for every line of the script that is not inside the block."""
    lines = script.split("\n")
    a, b = lines.index(BLOCK_OPEN), lines.index(BLOCK_CLOSE)
    return [(i, line) for i, line in enumerate(lines) if not a <= i <= b]


def _shell_function(script: str, name: str) -> str:
    """The text of the top-level shell function `name() { ... }` in `script`."""
    lines = script.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith(name + "() {")]
    if len(starts) != 1:
        raise AssertionError("%d definitions of %s" % (len(starts), name))
    end = starts[0]
    while lines[end] != "}":
        end += 1
    return "\n".join(lines[starts[0]:end + 1]) + "\n"


def _heredoc(script: str, marker: str) -> tuple[int, str]:
    """(index of the line carrying `<<'MARKER'`, the heredoc's body)."""
    lines = script.split("\n")
    starts = [i for i, line in enumerate(lines) if "<<'%s'" % marker in line]
    if len(starts) != 1:
        raise AssertionError("%d heredocs named %s" % (len(starts), marker))
    end = starts[0] + 1
    while lines[end] != marker:
        end += 1
    return starts[0], "\n".join(lines[starts[0] + 1:end]) + "\n"


class KitSudoersTextTests(unittest.TestCase):
    """What the scripts SAY: read on every platform, Windows included."""

    def test_both_kits_carry_the_same_block(self):
        live, ladder = (_block(_script(name)) for name in KITS)
        self.assertEqual(live, ladder)
        for function in ("sudoers_find_visudo", "sudoers_stage_begin", "sudoers_stage_end",
                         "sudoers_install"):
            self.assertIn("\n%s() {" % function, live)

    def test_the_block_is_aimed_at_the_real_directory_and_the_absolute_visudo_first(self):
        """The executed tests below substitute these three; the kits must not."""
        for name in KITS:
            assigned = [line for _, line in _outside_block(_script(name))
                        if re.match(r"SUDOERS_(DIR|VISUDO_CANDIDATES|STAGE_DIR)=", line)]
            with self.subTest(kit=name):
                self.assertEqual(assigned, [
                    "SUDOERS_DIR=/etc/sudoers.d",
                    "SUDOERS_VISUDO_CANDIDATES=(/usr/sbin/visudo /sbin/visudo)",
                    'SUDOERS_STAGE_DIR=""',
                ])

    def test_the_trap_is_armed_before_anything_can_be_staged_or_installed(self):
        for name in KITS:
            lines = _script(name).split("\n")
            with self.subTest(kit=name):
                traps = [i for i, line in enumerate(lines) if line.startswith("trap ")]
                self.assertEqual([lines[i] for i in traps], ["trap cleanup EXIT"])
                stage = [i for i, line in enumerate(lines) if line.startswith("sudoers_stage_begin ")]
                install = [i for i, line in enumerate(lines) if line.startswith("sudoers_install ")]
                self.assertEqual(len(stage), 1, stage)
                self.assertEqual(len(install), len(FRAGMENTS[name]), install)
                self.assertLess(traps[0], stage[0], "the staging directory is created before the trap")
                self.assertLess(stage[0], min(install))
                # ...and `cleanup` is DEFINED before the trap names it.
                defined = [i for i, line in enumerate(lines) if line.startswith("cleanup() {")]
                self.assertEqual(len(defined), 1, defined)
                self.assertLess(defined[0], traps[0])

    def test_every_fragment_is_built_in_the_staging_directory_and_installed_once(self):
        for name, fragments in FRAGMENTS.items():
            script = _script(name)
            lines = script.split("\n")
            for variable, marker in fragments:
                with self.subTest(kit=name, fragment=variable):
                    at, _ = _heredoc(script, marker)
                    start = at
                    while not lines[start].startswith("python3 - "):
                        start -= 1
                    invocation = " ".join(lines[start:at + 1])
                    self.assertIn('"$%s_STAGED"' % variable, invocation)
                    self.assertNotIn('"$%s"' % variable, invocation,
                                     "the builder is handed the path inside /etc/sudoers.d")
                    staged = [l for l in lines if l.startswith("%s_STAGED=" % variable)]
                    self.assertEqual(len(staged), 1, staged)
                    self.assertTrue(staged[0].startswith('%s_STAGED="$SUDOERS_STAGE_DIR/' % variable),
                                    staged[0])
                    calls = [i for i, l in enumerate(lines) if l.startswith(
                        'sudoers_install "$%s_STAGED" "$%s" ' % (variable, variable))]
                    self.assertEqual(len(calls), 1, calls)
                    # A refusal is an EXIT: the kit must not carry on without its fragment.
                    call = lines[calls[0]]
                    if call.endswith("\\"):
                        call = call[:-1] + lines[calls[0] + 1].strip()
                    self.assertRegex(call, r' \|\| \{ echo "FAIL: [^"]*"; exit 1; \}$')

    def test_the_ladder_kit_revalidates_in_place_after_the_acl_and_fails_closed(self):
        """The one validation left outside the block: the broker's read ACL is applied to the
        installed file, so it is checked again where it lies — after the trap is armed, through the
        same lookup, and with a missing visudo an exit rather than a skip."""
        lines = _script("run_ladder_turn.sh").split("\n")

        def only(pattern: str) -> int:
            hits = [i for i, line in enumerate(lines) if re.search(pattern, line)]
            self.assertEqual(len(hits), 1, "%r matches %d lines" % (pattern, len(hits)))
            return hits[0]

        fail = r' \|\| \{ echo "FAIL: [^"]*"; exit 1; \}$'
        trap = only(r"^trap cleanup EXIT$")
        acl = only(r'^setfacl -m "u:\$BROKER_USER:r" "\$SUDOERS" ')
        find = only(r'^VISUDO="\$\(sudoers_find_visudo\)"' + fail)
        check = only(r'^"\$VISUDO" -cf "\$SUDOERS" >/dev/null' + fail)
        floor = only(r'^"\$BIN/ladder_turn" --config "\$DRIVER_CONFIG" --verify-tcb')
        self.assertEqual([trap, acl, find, check, floor], sorted([trap, acl, find, check, floor]))

    def test_nothing_outside_the_block_writes_a_fragment_or_finds_visudo_on_its_own(self):
        for name, fragments in FRAGMENTS.items():
            outside = [line for _, line in _outside_block(_script(name))
                       if not line.lstrip().startswith("#")]
            with self.subTest(kit=name):
                self.assertEqual([l for l in outside if "command -v visudo" in l], [])
                # The one visudo call left outside the block re-validates in place, through the lookup.
                bare = [l for l in outside if re.search(r"\bvisudo\"?\s+-", l)]
                self.assertEqual(bare, [])
                for variable, _ in fragments:
                    writes = [l for l in outside if re.search(
                        r'\b(chmod|chown|install|cp|mv|tee)\b[^|;]*"\$%s"\s*($|[;|&])' % variable, l)
                        or re.search(r'>\s*"\$%s"' % variable, l)]
                    self.assertEqual(writes, [], "a write to $%s outside sudoers_install" % variable)


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        # Root Debian scripts. The engine suite also runs on windows-latest; skipped BY NAME there.
        if os.name != "posix":
            self.skipTest("the live kits are Debian root scripts; a sudoers install is only defined on POSIX")
        if not sys.platform.startswith("linux"):
            self.skipTest("the block uses GNU `stat -c` and `mv -T`; the kits only run on Linux")
        self.bash = shutil.which("bash")
        if not self.bash:
            self.skipTest("no bash on this host")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.etc = os.path.join(self.tmp, "etc")
        self.sudoers_d = os.path.join(self.etc, "sudoers.d")
        os.makedirs(self.sudoers_d)
        os.chmod(self.sudoers_d, 0o750)
        self.log = os.path.join(self.tmp, "log.jsonl")
        # The ONLY directory on the driver's PATH: the real tools the block uses, by symlink, and
        # recording stand-ins for the two that would need root or would touch the real /etc.
        self.toolbin = os.path.join(self.tmp, "toolbin")
        os.mkdir(self.toolbin)
        for tool in ("mktemp", "dirname", "rm", "chmod", "stat", "mv", "sleep"):
            real = shutil.which(tool)
            self.assertTrue(real, "no %s on this host" % tool)
            os.symlink(real, os.path.join(self.toolbin, tool))
        self.fake(os.path.join(self.toolbin, "chown"), "chown")
        self.fake(os.path.join(self.toolbin, "setfacl"), "setfacl")
        self.sbin = os.path.join(self.tmp, "usr-sbin", "visudo")      # an absolute candidate
        self.sbin2 = os.path.join(self.tmp, "sbin", "visudo")         # the second absolute candidate
        self.pathbin = os.path.join(self.tmp, "pathbin")              # visudo found through PATH
        for d in (os.path.dirname(self.sbin), os.path.dirname(self.sbin2), self.pathbin):
            os.mkdir(d)

    def fake(self, path: str, who: str, rc: int = 0) -> str:
        """A stand-in that records who it is, its argv and what it could see, then exits `rc`."""
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!%s\n" % sys.executable)
            f.write(
                "import json, os, stat, sys\n"
                "record = {'who': %r, 'argv': sys.argv[1:], 'listing': sorted(os.listdir(%r))}\n"
                "path = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
                "if %r.startswith('visudo') and os.path.isfile(path):\n"
                "    st = os.stat(path)\n"
                "    record.update(inode=st.st_ino, mode=stat.S_IMODE(st.st_mode),\n"
                "                  text=open(path, encoding='utf-8').read())\n"
                "with open(%r, 'a', encoding='utf-8') as log:\n"
                "    log.write(json.dumps(record) + '\\n')\n"
                "sys.exit(%d)\n" % (who, self.sudoers_d, who, self.log, rc))
        os.chmod(path, 0o755)
        return path

    def records(self, who_prefix: str = "") -> list[dict]:
        if not os.path.exists(self.log):
            return []
        with open(self.log, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f]
        return [r for r in rows if r["who"].startswith(who_prefix)]

    def run_block(self, kit: str, body: str, *, candidates: list[str] | None = None,
                  path_visudo: bool = False, preamble: str = "") -> subprocess.CompletedProcess:
        path = self.toolbin + (":" + self.pathbin if path_visudo else "")
        candidates = [self.sbin, self.sbin2] if candidates is None else candidates
        driver = os.path.join(self.tmp, "driver.sh")
        with open(driver, "w", encoding="utf-8") as f:
            f.write("set -u\numask 022\n")
            f.write("SUDOERS_DIR=%s\n" % self.sudoers_d)
            f.write("SUDOERS_VISUDO_CANDIDATES=(%s)\n" % " ".join(candidates))
            f.write('SUDOERS_STAGE_DIR=""\n')
            f.write(_block(_script(kit)))
            f.write(preamble)
            f.write(body)
        return subprocess.run([self.bash, driver], capture_output=True, text=True, timeout=60,
                              check=False, env={"PATH": path, "LC_ALL": "C"})

    FRAGMENT_FILE = "fragment-text"
    INSTALL_ONE = (
        'sudoers_stage_begin || { echo "STAGE-FAILED"; exit 9; }\n'
        'echo "STAGE=$SUDOERS_STAGE_DIR"\n'
        'while IFS= read -r line; do printf "%%s\\n" "$line"; done < %s > "$SUDOERS_STAGE_DIR/brops-x"\n'
        'sudoers_install "$SUDOERS_STAGE_DIR/brops-x" "$SUDOERS_DIR/brops-x"\n'
        'echo "RC=$?"\n')

    def install_one(self, text: str = "alice ALL=(bob) NOPASSWD: /bin/true\n") -> str:
        """A driver body that stages `text` (whole lines) as `brops-x` and installs it."""
        source = os.path.join(self.tmp, self.FRAGMENT_FILE)
        with open(source, "w", encoding="utf-8") as f:
            f.write(text)
        return self.INSTALL_ONE % source

    def rc_of(self, done: subprocess.CompletedProcess) -> int:
        self.assertIn("RC=", done.stdout, done.stdout + done.stderr)
        return int(done.stdout.rsplit("RC=", 1)[1].split()[0])

    def stage_of(self, done: subprocess.CompletedProcess) -> str:
        return done.stdout.split("STAGE=", 1)[1].split("\n", 1)[0]

    def installed(self) -> list[str]:
        return sorted(os.listdir(self.sudoers_d))


class SudoersInstallTests(_Harness):
    """`sudoers_install`, run from each kit's own copy of the block."""

    def test_a_valid_fragment_lands_0440_and_is_the_inode_that_was_validated(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                self.fake(self.sbin, "visudo-absolute")
                done = self.run_block(kit, self.install_one())
                self.assertEqual(self.rc_of(done), 0, done.stderr)
                self.assertEqual(self.installed(), ["brops-x"])
                target = os.path.join(self.sudoers_d, "brops-x")
                st = os.stat(target)
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o440)
                with open(target, encoding="utf-8") as f:
                    self.assertEqual(f.read(), "alice ALL=(bob) NOPASSWD: /bin/true\n")
                stage = self.stage_of(done)
                # Staged BESIDE the target directory, never in it, and private.
                self.assertEqual(os.path.dirname(stage), self.etc)
                self.assertTrue(os.path.basename(stage).startswith(".brops-sudoers-stage."), stage)
                self.assertEqual(stat.S_IMODE(os.stat(stage).st_mode), 0o700)
                seen = self.records("visudo")[-1]
                self.assertEqual(seen["argv"], ["-cf", os.path.join(stage, "brops-x")])
                # When visudo judged it the target directory was still EMPTY ...
                self.assertEqual(seen["listing"], [])
                # ... it was already 0440 ...
                self.assertEqual(seen["mode"], 0o440)
                # ... and what was installed is that inode, renamed: not a copy made afterwards.
                self.assertEqual(seen["inode"], st.st_ino)
                self.assertEqual(os.listdir(stage), [])
                os.unlink(target)

    def test_a_fragment_visudo_rejects_never_appears_in_the_directory(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                self.fake(self.sbin, "visudo-absolute", rc=1)
                done = self.run_block(kit, self.install_one())
                self.assertNotEqual(self.rc_of(done), 0)
                self.assertEqual(self.installed(), [])
                self.assertIn("rejected", done.stderr)
                self.assertIn("was NOT installed", done.stderr)
                # It was asked, and at that moment too the directory held nothing.
                seen = self.records("visudo")[-1]
                self.assertEqual(seen["listing"], [])
                # The rejected text stays where sudo does not read, for whoever debugs it.
                self.assertEqual(os.listdir(self.stage_of(done)), ["brops-x"])

    def test_a_missing_visudo_refuses_rather_than_installing_unvalidated(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                done = self.run_block(kit, self.install_one())     # no stand-in created anywhere
                self.assertNotEqual(self.rc_of(done), 0)
                self.assertEqual(self.installed(), [])
                self.assertIn("no visudo at", done.stderr)
                self.assertIn("refusing to install", done.stderr)
                self.assertEqual(self.records("visudo"), [])

    def test_visudo_is_found_by_absolute_path_before_path(self):
        kit = KITS[1]
        find = 'sudoers_find_visudo; echo "RC=$?"\n'
        self.fake(os.path.join(self.pathbin, "visudo"), "visudo-path")
        # PATH alone: found there, and reported as an absolute path.
        done = self.run_block(kit, find, path_visudo=True)
        self.assertEqual(done.stdout, "%s\nRC=0\n" % os.path.join(self.pathbin, "visudo"), done.stderr)
        # The second absolute candidate beats PATH; the first beats the second.
        self.fake(self.sbin2, "visudo-second")
        done = self.run_block(kit, find, path_visudo=True)
        self.assertEqual(done.stdout, "%s\nRC=0\n" % self.sbin2)
        self.fake(self.sbin, "visudo-absolute")
        done = self.run_block(kit, find, path_visudo=True)
        self.assertEqual(done.stdout, "%s\nRC=0\n" % self.sbin)
        # And the install really runs the one that was found.
        done = self.run_block(kit, self.install_one(), path_visudo=True)
        self.assertEqual(self.rc_of(done), 0, done.stderr)
        self.assertEqual([r["who"] for r in self.records("visudo")], ["visudo-absolute"])

    def test_a_candidate_that_is_not_executable_is_not_a_visudo(self):
        kit = KITS[1]
        self.fake(self.sbin, "visudo-absolute")
        os.chmod(self.sbin, 0o644)
        done = self.run_block(kit, 'sudoers_find_visudo; echo "RC=$?"\n')
        self.assertEqual(done.stdout, "RC=1\n", done.stderr)

    def test_a_candidate_that_is_a_directory_is_not_a_visudo(self):
        kit = KITS[1]
        os.mkdir(self.sbin)                      # searchable, so `-x` alone would take it
        done = self.run_block(kit, 'sudoers_find_visudo; echo "RC=$?"\n')
        self.assertEqual(done.stdout, "RC=1\n", done.stderr)

    def test_a_visudo_that_is_not_a_path_is_not_a_visudo(self):
        """`command -v` also answers for a function or an alias, with a bare name."""
        kit = KITS[1]
        done = self.run_block(kit, 'visudo() { return 0; }\nsudoers_find_visudo; echo "RC=$?"\n')
        self.assertEqual(done.stdout, "RC=1\n", done.stderr)

    def test_a_staging_directory_that_cannot_be_created_is_a_failure_and_names_nothing(self):
        kit = KITS[1]
        done = self.run_block(kit, 'SUDOERS_DIR=%s/absent/sudoers.d\nsudoers_stage_begin\n'
                                   'echo "RC=$? DIR=[$SUDOERS_STAGE_DIR]"\n' % self.tmp)
        self.assertEqual(done.stdout, "RC=1 DIR=[]\n", done.stderr)
        # ...and each kit turns that status into an exit, on the line that calls it.
        for name in KITS:
            calls = [l for l in _script(name).split("\n") if l.startswith("sudoers_stage_begin ")]
            self.assertEqual(len(calls), 1, calls)
            self.assertRegex(calls[0], r'^sudoers_stage_begin \|\| \{ echo "FAIL: [^"]*"; exit 1; \}$')

    def test_it_is_made_root_owned_before_it_is_validated(self):
        kit = KITS[1]
        self.fake(self.sbin, "visudo-absolute")
        done = self.run_block(kit, self.install_one())
        self.assertEqual(self.rc_of(done), 0, done.stderr)
        staged = os.path.join(self.stage_of(done), "brops-x")
        self.assertEqual([r["who"] for r in self.records()], ["chown", "visudo-absolute"])
        self.assertEqual(self.records("chown")[0]["argv"], ["0:0", staged])

    def test_a_chown_that_fails_refuses(self):
        kit = KITS[1]
        self.fake(self.sbin, "visudo-absolute")
        self.fake(os.path.join(self.toolbin, "chown"), "chown", rc=1)
        done = self.run_block(kit, self.install_one())
        self.assertNotEqual(self.rc_of(done), 0)
        self.assertEqual(self.installed(), [])
        self.assertIn("root-owned 0440", done.stderr)
        self.assertEqual(self.records("visudo"), [])

    def test_a_file_that_was_not_staged_is_refused(self):
        """The helper's whole point is the order, so it will not validate a file IN the directory —
        which is the old shape — nor one from anywhere else."""
        kit = KITS[1]
        self.fake(self.sbin, "visudo-absolute")
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        for where in (self.sudoers_d, elsewhere):
            with self.subTest(where=where):
                body = ('sudoers_stage_begin || exit 9\n'
                        'printf "x\\n" > "%s/brops-y"\n'
                        'sudoers_install "%s/brops-y" "$SUDOERS_DIR/brops-x"\n'
                        'echo "RC=$?"\n' % (where, where))
                done = self.run_block(kit, body)
                self.assertNotEqual(self.rc_of(done), 0)
                self.assertIn("is not in the staging directory", done.stderr)
                self.assertNotIn("brops-x", self.installed())
                self.assertEqual(self.records("visudo"), [])
        # Before any staging directory exists, nothing is "in" it either.
        done = self.run_block(kit, 'sudoers_install "/brops-y" "$SUDOERS_DIR/brops-x"; echo "RC=$?"\n')
        self.assertNotEqual(self.rc_of(done), 0)
        self.assertIn("is not in the staging directory", done.stderr)

    def test_a_target_outside_the_sudoers_directory_is_refused(self):
        kit = KITS[1]
        self.fake(self.sbin, "visudo-absolute")
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.mkdir(elsewhere)
        body = self.install_one().replace('"$SUDOERS_DIR/brops-x"', '"%s/brops-x"' % elsewhere)
        done = self.run_block(kit, body)
        self.assertNotEqual(self.rc_of(done), 0)
        self.assertIn("is not directly inside", done.stderr)
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertEqual(self.records("visudo"), [])

    def test_a_staging_directory_on_another_filesystem_refuses(self):
        """`mv` across filesystems is copy-then-unlink — the non-atomic write this replaces."""
        kit = KITS[1]
        other = "/dev/shm"
        if not (os.path.isdir(other) and os.access(other, os.W_OK)
                and os.stat(other).st_dev != os.stat(self.tmp).st_dev):
            self.skipTest("needs a second writable filesystem; /dev/shm is not one on this host")
        real = tempfile.mkdtemp(prefix="brops-sudoers-test.", dir=other)
        self.addCleanup(shutil.rmtree, real, True)
        os.rmdir(self.sudoers_d)
        os.symlink(real, self.sudoers_d)       # the directory's NAME is here, its inodes are there
        self.fake(self.sbin, "visudo-absolute")
        done = self.run_block(kit, self.install_one())
        self.assertNotEqual(self.rc_of(done), 0)
        self.assertIn("a rename would be a copy", done.stderr)
        self.assertEqual(os.listdir(real), [])

    def test_staging_twice_is_one_directory(self):
        kit = KITS[1]
        done = self.run_block(kit, 'sudoers_stage_begin; a="$SUDOERS_STAGE_DIR"\n'
                                   'sudoers_stage_begin; [ "$a" = "$SUDOERS_STAGE_DIR" ]; echo "RC=$?"\n')
        self.assertEqual(self.rc_of(done), 0, done.stderr)
        self.assertEqual(len([n for n in os.listdir(self.etc) if n != "sudoers.d"]), 1)


class KitCleanupTests(_Harness):
    """Each kit's own `cleanup`, armed the way the kit arms it, on the exits a real run can take."""

    def arm(self, kit: str) -> str:
        script = _script(kit)
        names = "".join('%s="$SUDOERS_DIR/%s"\n' % (variable, variable.lower())
                        for variable, _ in FRAGMENTS[kit])
        return ("BROKER_USER=brops-verifier_broker\n" + names + "PIDS=()\n"
                + _shell_function(script, "cleanup") + "trap cleanup EXIT\n")

    def install_all(self, kit: str) -> str:
        body = 'sudoers_stage_begin || exit 9\necho "STAGE=$SUDOERS_STAGE_DIR"\n'
        for variable, _ in FRAGMENTS[kit]:
            body += ('printf "x\\n" > "$SUDOERS_STAGE_DIR/%(n)s"\n'
                     'sudoers_install "$SUDOERS_STAGE_DIR/%(n)s" "$%(v)s" || exit 8\n'
                     % {"n": variable.lower(), "v": variable})
        return body + 'echo "INSTALLED=$(echo "$SUDOERS_DIR"/*)"\n'

    def assert_nothing_left(self, done: subprocess.CompletedProcess) -> None:
        self.assertEqual(self.installed(), [], done.stdout + done.stderr)
        self.assertEqual(os.listdir(self.etc), ["sudoers.d"], "the staging directory survived")
        self.assertNotIn("unbound variable", done.stderr)

    def test_the_trap_removes_every_installed_fragment_and_the_staging_directory(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                self.fake(self.sbin, "visudo-absolute")
                done = self.run_block(kit, self.install_all(kit) + "exit 3\n", preamble=self.arm(kit))
                self.assertEqual(done.returncode, 3, done.stderr)
                # They WERE there: the trap removed something, rather than finding nothing.
                for variable, _ in FRAGMENTS[kit]:
                    self.assertIn(os.path.join(self.sudoers_d, variable.lower()),
                                  done.stdout.split("INSTALLED=", 1)[1])
                self.assert_nothing_left(done)

    def test_the_trap_runs_when_the_kit_is_terminated(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                self.fake(self.sbin, "visudo-absolute")
                done = self.run_block(kit, self.install_all(kit) + "kill -TERM $$\nsleep 30\n",
                                      preamble=self.arm(kit))
                self.assertEqual(done.returncode, -15, done.stdout + done.stderr)
                self.assertIn("INSTALLED=", done.stdout)
                self.assert_nothing_left(done)

    def test_a_rejected_fragment_leaves_nothing_behind_when_the_kit_exits(self):
        for kit in KITS:
            with self.subTest(kit=kit):
                self.fake(self.sbin, "visudo-absolute", rc=1)
                done = self.run_block(kit, self.install_all(kit), preamble=self.arm(kit))
                self.assertEqual(done.returncode, 8, done.stderr)
                self.assertTrue(os.path.basename(self.stage_of(done)).startswith(".brops-sudoers-stage."))
                self.assert_nothing_left(done)

    def test_the_trap_is_safe_before_anything_was_staged(self):
        """The trap is now armed early, so it also runs on exits that staged nothing."""
        for kit in KITS:
            with self.subTest(kit=kit):
                done = self.run_block(kit, "exit 4\n", preamble=self.arm(kit))
                self.assertEqual(done.returncode, 4, done.stderr)
                self.assertEqual(done.stderr, "")
                self.assert_nothing_left(done)

    def test_the_ladder_kit_still_withdraws_the_brokers_acl(self):
        done = self.run_block("run_ladder_turn.sh", "exit 0\n", preamble=self.arm("run_ladder_turn.sh"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([r["argv"] for r in self.records("setfacl")],
                         [["-x", "u:brops-verifier_broker", "/etc/sudoers.d"]])


class FragmentTextTests(_Harness):
    """WHAT a fragment says did not change: each builder is run, and its bytes compared."""

    def build(self, kit: str, marker: str) -> str:
        _, body = _heredoc(_script(kit), marker)
        out = os.path.join(self.tmp, "fragment")
        if marker == "PYDRVSUDO":
            argv = ["brops-verifier_broker", "brops-sidecar", "/usr/bin/env",
                    "/opt/brops-live/sock/supervisor.sock", "/usr/bin/python3",
                    "/opt/brops-live/bridge/engine_sidecar.py", out]
        else:
            config = os.path.join(self.tmp, "config.json")
            with open(config, "w", encoding="utf-8") as f:
                json.dump(FIXTURE_CONFIG, f)
            invoker = "brops-verifier_broker" if kit == "run_live_turn.sh" else "brops-supervisor"
            argv = [config, invoker, "brops-recorder", out]
        done = subprocess.run([sys.executable, "-c", body, *argv], capture_output=True, text=True,
                              timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(out, "rb") as f:
            return f.read().decode("utf-8")

    def test_each_fragment_is_the_line_it_was_before_the_write_moved(self):
        for kit, fragments in FRAGMENTS.items():
            for _, marker in fragments:
                with self.subTest(kit=kit, heredoc=marker):
                    self.assertEqual(self.build(kit, marker), EXPECTED_FRAGMENT[(kit, marker)])

    def test_the_real_visudo_accepts_all_three_and_rejects_a_broken_one_through_the_block(self):
        """The stand-in answers what it is told. Where a real visudo is installed, ask it too."""
        real = next((p for p in ("/usr/sbin/visudo", "/sbin/visudo") if os.access(p, os.X_OK)), None)
        if real is None:
            self.skipTest("no visudo at /usr/sbin or /sbin on this host")
        for (kit, marker), text in sorted(EXPECTED_FRAGMENT.items()):
            with self.subTest(kit=kit, heredoc=marker):
                done = self.run_block(kit, self.install_one(self.build(kit, marker)), candidates=[real])
                self.assertEqual(self.rc_of(done), 0, done.stderr)
                target = os.path.join(self.sudoers_d, "brops-x")
                with open(target, encoding="utf-8") as f:
                    self.assertEqual(f.read(), text)
                os.unlink(target)
        done = self.run_block(KITS[1], self.install_one("alice ALL=(bob NOPASSWD /bin/true\n"),
                              candidates=[real])
        self.assertNotEqual(self.rc_of(done), 0)
        self.assertIn("rejected", done.stderr)
        self.assertEqual(self.installed(), [])


if __name__ == "__main__":
    unittest.main()
