"""`engine/install/brops_install.sh accounts` — the installer's ACCOUNTS step, held to its sources.

The installer's account table is a third copy of two things that already exist: the names in the
`*_USER=` block of `engine/ci/live/run_ladder_turn.sh`, and the uids in `DEFAULT_UIDS` in
`engine/ci/live/provision_keys.py`. A third copy drifts. So nothing here states a name or a uid
that one of those two files states: the tests READ them, and compare.

The one value neither file carries is `brops-sidecar`'s uid. `provision_keys.py` has no sidecar
entry — the ladder kit hands `provision_ladder.py` the uid on argv from `id -u` — so 5003 is pinned
here as a literal, and `test_the_sidecar_is_the_only_account_provision_keys_does_not_number` says
out loud that it is the only one.

No test needs root and none creates anything. The refusal and idempotence paths run under
`--dry-run` against a passwd/group FILE, and one test reads the real databases through `getent`.
Nothing here runs `groupadd`/`useradd` or the read-back after them: that is CI's ladder job, as
root, and it is the only place those lines have ever executed.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ENGINE = pathlib.Path(__file__).resolve().parents[1]
REPO = ENGINE.parent
SCRIPT = ENGINE / "install" / "brops_install.sh"
KIT = ENGINE / "ci" / "live" / "run_ladder_turn.sh"
PROVISION_KEYS = ENGINE / "ci" / "live" / "provision_keys.py"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"

SHELL = "/usr/sbin/nologin"
#: The one uid no source file states. See the module docstring.
SIDECAR = ("brops-sidecar", 5003)

_USER_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)_USER=([A-Za-z0-9_-]+)\s*$", re.M)
_ACCOUNTS_BLOCK = re.compile(r"^ACCOUNTS=\(\n(?P<body>.*?)^\)", re.M | re.S)
_ACCOUNT_ENTRY = re.compile(r'^\s*"([A-Za-z0-9_-]+):(\d+)"\s*$')


def kit_users() -> dict[str, str]:
    """role -> account name, from the kit's own `*_USER=` lines (`BROKER_USER=…` -> `broker`)."""
    pairs = _USER_LINE.findall(KIT.read_text(encoding="utf-8"))
    roles = [role.lower() for role, _ in pairs]
    assert len(roles) == len(set(roles)), "the kit assigns a *_USER twice: %r" % (roles,)
    return {role.lower(): name for role, name in pairs}


def provision_uids() -> dict[str, int]:
    """`DEFAULT_UIDS`, read from the source rather than imported (the module needs `cryptography`)."""
    tree = ast.parse(PROVISION_KEYS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "DEFAULT_UIDS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("provision_keys.py no longer assigns DEFAULT_UIDS at module scope")


def script_table() -> list[tuple[str, int]]:
    """The installer's `ACCOUNTS=( … )` array, from the script's own text."""
    match = _ACCOUNTS_BLOCK.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, "brops_install.sh no longer carries an ACCOUNTS=( … ) block"
    table = []
    for line in match.group("body").splitlines():
        if not line.strip():
            continue
        entry = _ACCOUNT_ENTRY.match(line)
        assert entry, "unreadable ACCOUNTS entry: %r" % line
        table.append((entry.group(1), int(entry.group(2))))
    return table


def passwd_line(name: str, uid: int, gid: int | None = None, shell: str = SHELL) -> str:
    return "%s:x:%d:%d::/home/%s:%s" % (name, uid, uid if gid is None else gid, name, shell)


def group_line(name: str, gid: int) -> str:
    return "%s:x:%d:" % (name, gid)


class InstallerCase(unittest.TestCase):
    def setUp(self) -> None:
        # A Debian installer: `getent`, passwd-shaped databases and `id -u` are what it reads, and
        # the engine suite also runs on windows-latest, where 12 of these failed in T-136's first
        # CI run. Skipped BY NAME there; the workflow-text tests below still run on every platform.
        if os.name != "posix":
            self.skipTest("brops_install.sh is a Debian installer; its behaviour is only defined on POSIX")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              timeout=60, check=False)

    def dry_run(self, passwd: list[str] | None = None,
                group: list[str] | None = None) -> subprocess.CompletedProcess:
        """`--dry-run accounts` against a box described by two files, never by this machine."""
        pfile, gfile = self.tmp / "passwd", self.tmp / "group"
        pfile.write_text("".join(l + "\n" for l in ["root:x:0:0:root:/root:/bin/bash"] + (passwd or [])))
        gfile.write_text("".join(l + "\n" for l in ["root:x:0:"] + (group or [])))
        return self.run_script("--dry-run", "--passwd-file", str(pfile), "--group-file", str(gfile),
                               "accounts")

    def whole_box(self) -> tuple[list[str], list[str]]:
        table = script_table()
        return ([passwd_line(n, u) for n, u in table], [group_line(n, u) for n, u in table])


class TestScript(InstallerCase):
    def test_bash_syntax(self) -> None:
        done = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_it_is_strict(self) -> None:
        self.assertRegex(SCRIPT.read_text(encoding="utf-8"), r"(?m)^set -euo pipefail$")


class TestThePlan(InstallerCase):
    def test_dry_run_prints_exactly_the_kits_accounts_at_provision_keys_uids(self) -> None:
        users, uids = kit_users(), provision_uids()
        expected = {}
        for role, name in users.items():
            if role in uids:
                expected[name] = uids[role]
        expected[SIDECAR[0]] = SIDECAR[1]

        done = self.dry_run()
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        seen = {}
        for line in lines:
            fields = line.split(" ")
            self.assertEqual(len(fields), 4, "a plan line is `name uid gid shell`: %r" % line)
            name, uid, gid, shell = fields
            self.assertNotIn(name, seen, "an account is planned twice")
            self.assertEqual(gid, uid, "%s: the gid is the uid" % name)
            self.assertEqual(shell, SHELL, name)
            seen[name] = int(uid)
        self.assertEqual(seen, expected)
        # Every account the kit names is planned — none was dropped for want of a uid.
        self.assertEqual(sorted(seen), sorted(users.values()))
        self.assertEqual(len(lines), len(users))

    def test_every_provision_keys_role_is_an_account_at_that_uid(self) -> None:
        users, uids = kit_users(), provision_uids()
        planned = dict(script_table())
        self.assertTrue(uids, "DEFAULT_UIDS is empty")
        for role, uid in uids.items():
            self.assertIn(role, users, "provision_keys.py numbers %r and the kit has no %s_USER"
                          % (role, role.upper()))
            self.assertEqual(planned.get(users[role]), uid,
                             "%s (%s) must be uid %d — provision_keys.py writes that literal into "
                             "the peer allowlists" % (users[role], role, uid))

    def test_the_sidecar_is_the_only_account_provision_keys_does_not_number(self) -> None:
        users, uids = kit_users(), provision_uids()
        unnumbered = sorted(name for role, name in users.items() if role not in uids)
        self.assertEqual(unnumbered, [SIDECAR[0]])
        planned = dict(script_table())
        self.assertEqual(planned[SIDECAR[0]], SIDECAR[1])
        self.assertNotIn(SIDECAR[1], uids.values(), "§2.6: the sidecar must not share a uid")

    def test_the_scripts_account_list_is_the_kits_user_block(self) -> None:
        table = script_table()
        names = [name for name, _ in table]
        self.assertEqual(len(names), len(set(names)), "a name appears twice in ACCOUNTS")
        self.assertEqual(sorted(names), sorted(kit_users().values()))
        uids = [uid for _, uid in table]
        self.assertEqual(len(uids), len(set(uids)), "§2.6: the uids are not pairwise distinct")
        # And the array is what runs: the plan is the array, in order.
        done = self.dry_run()
        self.assertEqual([line.split(" ")[0] for line in done.stdout.splitlines()], names)

    def test_a_table_with_two_accounts_on_one_uid_is_refused_by_the_script_itself(self) -> None:
        # The script's own §2.6 check cannot be reached through the shipped table, so it is run
        # against a copy whose table has been collapsed. Without it the failure would be
        # `useradd`'s, as root, after the first accounts already exist.
        table = script_table()
        text = SCRIPT.read_text(encoding="utf-8")
        victim = '"%s:%d"' % table[1]
        self.assertEqual(text.count(victim), 1)
        copy = self.tmp / "collapsed.sh"
        copy.write_text(text.replace(victim, '"%s:%d"' % (table[1][0], table[0][1])), encoding="utf-8")
        pfile, gfile = self.tmp / "passwd", self.tmp / "group"
        pfile.write_text("root:x:0:0:root:/root:/bin/bash\n")
        gfile.write_text("root:x:0:\n")
        done = subprocess.run(["bash", str(copy), "--dry-run", "--passwd-file", str(pfile),
                               "--group-file", str(gfile), "accounts"],
                              capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("pairwise-distinct", done.stderr)
        self.assertEqual(done.stdout, "")


class TestRoot(InstallerCase):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "this refusal is for a non-root caller")
    def test_refuses_without_root_when_not_a_dry_run(self) -> None:
        done = self.run_script("accounts")
        self.assertEqual(done.returncode, 1)
        self.assertIn("must run as root", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_the_alternate_databases_are_refused_outside_a_dry_run(self) -> None:
        pfile, gfile = self.tmp / "passwd", self.tmp / "group"
        pfile.write_text("")
        gfile.write_text("")
        done = self.run_script("--passwd-file", str(pfile), "--group-file", str(gfile), "accounts")
        self.assertEqual(done.returncode, 2)
        self.assertIn("only with --dry-run", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_no_step_and_an_unknown_step_are_usage_errors(self) -> None:
        self.assertEqual(self.run_script("--dry-run").returncode, 2)
        done = self.run_script("--dry-run", "everything")
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown argument", done.stderr)


class TestIdempotenceAndRefusal(InstallerCase):
    def test_an_empty_box_needs_every_account(self) -> None:
        n = len(script_table())
        done = self.dry_run()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("%d group(s) and %d account(s) would be created" % (n, n), done.stderr)

    def test_a_box_that_already_holds_them_needs_nothing(self) -> None:
        passwd, group = self.whole_box()
        done = self.dry_run(passwd, group)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("0 group(s) and 0 account(s) would be created", done.stderr)
        self.assertEqual(len(done.stdout.splitlines()), len(script_table()))

    def test_a_half_provisioned_box_needs_only_the_rest(self) -> None:
        passwd, group = self.whole_box()
        done = self.dry_run(passwd[:3], group[:5])
        self.assertEqual(done.returncode, 0, done.stderr)
        n = len(script_table())
        self.assertIn("%d group(s) and %d account(s) would be created" % (n - 5, n - 3), done.stderr)

    def refused(self, passwd: list[str], group: list[str], *needles: str) -> None:
        done = self.dry_run(passwd, group)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("REFUSED", done.stderr)
        for needle in needles:
            self.assertIn(needle, done.stderr)
        self.assertEqual(done.stdout, "", "a refusal prints no plan")

    def test_refuses_an_account_with_a_different_uid_and_names_it(self) -> None:
        passwd, group = self.whole_box()
        name, uid = script_table()[2]
        passwd[2] = passwd_line(name, 998, gid=uid)
        self.refused(passwd, group, "account %s exists with uid 998, not %d" % (name, uid))

    def test_refuses_an_account_with_a_different_shell_and_names_it(self) -> None:
        passwd, group = self.whole_box()
        name, uid = script_table()[4]
        passwd[4] = passwd_line(name, uid, shell="/bin/bash")
        self.refused(passwd, group, "account %s exists with shell /bin/bash" % name)

    def test_refuses_an_account_with_a_different_primary_gid(self) -> None:
        passwd, group = self.whole_box()
        name, uid = script_table()[1]
        passwd[1] = passwd_line(name, uid, gid=100)
        self.refused(passwd, group, "account %s exists with primary gid 100, not %d" % (name, uid))

    def test_refuses_a_uid_already_held_by_another_account(self) -> None:
        name, uid = script_table()[0]
        self.refused([passwd_line("alice", uid, gid=1000)], [],
                     "uid %d, wanted for account %s, is already held by account alice" % (uid, name))

    def test_refuses_a_group_with_a_different_gid_or_a_gid_held_by_another_group(self) -> None:
        name, uid = script_table()[0]
        self.refused([], [group_line(name, 997)], "group %s exists with gid 997, not %d" % (name, uid))
        self.refused([], [group_line("staff2", uid)],
                     "gid %d, wanted for group %s, is already held by group staff2" % (uid, name))

    def test_every_conflict_is_reported_not_only_the_first(self) -> None:
        passwd, group = self.whole_box()
        table = script_table()
        passwd[0] = passwd_line(table[0][0], 990, gid=table[0][1])
        passwd[6] = passwd_line(table[6][0], table[6][1], shell="/bin/sh")
        self.refused(passwd, group, table[0][0], table[6][0])


class TestTheSystemDatabase(InstallerCase):
    """Everything above describes a box with two files. This asks the machine the test runs on,
    through `getent` — the path the real, root run takes. What the machine holds is not this
    test's to decide, so the expected answer is worked out from Python's own view of the same
    databases (`pwd`/`grp`), and the script must reach it: the same count to create, or a refusal
    exactly when Python sees a conflict. A lookup that reads "absent" out of a failed `getent`
    would create a duplicate as root; here it shows up as a count that is too high."""

    def test_a_dry_run_reads_the_real_account_database_as_python_does(self) -> None:
        import grp
        import pwd

        def lookup(fn, key):
            try:
                return fn(key)
            except KeyError:
                return None

        need_groups = need_users = conflicts = 0
        for name, uid in script_table():
            group = lookup(grp.getgrnam, name)
            if group is not None:
                conflicts += group.gr_gid != uid
            elif lookup(grp.getgrgid, uid) is not None:
                conflicts += 1
            else:
                need_groups += 1
            user = lookup(pwd.getpwnam, name)
            if user is not None:
                conflicts += (user.pw_uid, user.pw_gid, user.pw_shell) != (uid, uid, SHELL)
            elif lookup(pwd.getpwuid, uid) is not None:
                conflicts += 1
            else:
                need_users += 1

        done = self.run_script("--dry-run", "accounts")
        self.assertNotIn("unreadable", done.stderr)
        if conflicts:
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertIn("REFUSED", done.stderr)
            self.assertEqual(done.stdout, "")
        else:
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(len(done.stdout.splitlines()), len(script_table()))
            self.assertIn("%d group(s) and %d account(s) would be created" % (need_groups, need_users),
                          done.stderr)


class TestCiRunsTheInstaller(unittest.TestCase):
    """CI's accounts are the installer's. An inline `useradd` beside it would be the parallel copy
    this file was written to end: green in CI, and absent from every install."""

    def setUp(self) -> None:
        self.code = [line for line in CI_YML.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#")]

    def test_no_workflow_step_creates_an_account_itself(self) -> None:
        inline = [line.strip() for line in self.code if re.search(r"\b(useradd|groupadd|adduser)\b", line)]
        self.assertEqual(inline, [])

    def test_both_kit_jobs_call_the_accounts_step(self) -> None:
        call = "sudo bash engine/install/brops_install.sh accounts"
        text = "\n".join(self.code)
        for kit in ("run_live_turn.sh", "run_ladder_turn.sh"):
            run = text.index("bash engine/ci/live/" + kit)
            job_start = text.rfind("\n    runs-on:", 0, run)
            self.assertNotEqual(job_start, -1)
            self.assertIn(call, text[job_start:run],
                          "the job that runs %s must create its accounts through the installer" % kit)


if __name__ == "__main__":
    unittest.main()
