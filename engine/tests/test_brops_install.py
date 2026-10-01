"""`engine/install/brops_install.sh` — the installer's ACCOUNTS and ANCHOR steps, held to their sources.

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

THE ANCHOR STEP (T-138). Who the desktop account is, and where its application data directory is,
are decided under `--dry-run` against a passwd FILE, one test per rule and per refusal. The step's
REAL run — it executes a tool and passes on its status — is exercised without root too, because
the step creates nothing itself: `BROPS_INSTALL_ANCHOR_BIN` names a fake tool that records its
argv and exits as told. Those runs resolve the account through the machine's own database, so
they name the account running the tests. The REAL `brops_install_anchor` is never run here, and
neither is `all` as root: the one real `all` run below is a non-root one, which the accounts step
refuses, and what it proves is that the tool did not run first.

The bundle identifier is the third thing this file refuses to restate: it is read from
`apps/desktop/src-tauri/tauri.conf.json` and the script's literal is held to it.
"""

from __future__ import annotations

import ast
import json
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
TAURI_CONF = REPO / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
POSTINST = REPO / "apps" / "desktop" / "src-tauri" / "deb" / "postinst"
#: The variable the script reads the anchor tool's path from.
ANCHOR_ENV = "BROPS_INSTALL_ANCHOR_BIN"
#: Variables the script reads. Scrubbed from every run, so a suite started under `sudo` or with
#: a real tool installed decides nothing here.
_READ_BY_THE_SCRIPT = ("SUDO_USER", "PKEXEC_UID", ANCHOR_ENV)

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

    def run_script(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        full = {k: v for k, v in os.environ.items() if k not in _READ_BY_THE_SCRIPT}
        full.update(env or {})
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              timeout=60, check=False, env=full)

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


def human(name: str, uid: int, shell: str = "/bin/bash", home: str | None = None) -> str:
    return "%s:x:%d:%d:,,,:%s:%s" % (name, uid, uid, "/home/" + name if home is None else home, shell)


def identifier() -> str:
    return json.loads(TAURI_CONF.read_text(encoding="utf-8"))["identifier"]


class AnchorCase(InstallerCase):
    """The anchor step against a box described by a passwd FILE, under `--dry-run`."""

    def anchor(self, passwd: list[str], *args: str, env: dict[str, str] | None = None,
               group: list[str] | None = None, step: str | None = "anchor") -> subprocess.CompletedProcess:
        pfile, gfile = self.tmp / "passwd", self.tmp / "group"
        pfile.write_text("".join(l + "\n" for l in ["root:x:0:0:root:/root:/bin/bash"] + passwd))
        gfile.write_text("".join(l + "\n" for l in ["root:x:0:"] + (group or [])))
        tail = [step] if step else []
        return self.run_script("--dry-run", "--passwd-file", str(pfile), "--group-file", str(gfile),
                               *args, *tail, env=env)

    def plan(self, done: subprocess.CompletedProcess) -> dict[str, str]:
        self.assertEqual(done.returncode, 0, done.stderr)
        found = {}
        for line in done.stdout.splitlines():
            if line.startswith("anchor "):
                _, key, rest = line.split(" ", 2)
                self.assertNotIn(key, found)
                found[key] = rest
        self.assertEqual(sorted(found), ["app-data", "command", "user"], done.stdout)
        return found

    def resolved(self, done: subprocess.CompletedProcess) -> str:
        return self.plan(done)["user"].split(" ")[0]

    def refused(self, done: subprocess.CompletedProcess, *needles: str) -> None:
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("REFUSED", done.stderr)
        for needle in needles:
            self.assertIn(needle, done.stderr)
        self.assertEqual(done.stdout, "", "a refusal prints no plan")

    def fake_tool(self, status: int = 0, name: str = "fake_anchor") -> tuple[pathlib.Path, pathlib.Path]:
        """A tool that writes its argv, one per line, to a marker file and exits `status`."""
        tool, mark = self.tmp / name, self.tmp / (name + ".argv")
        tool.write_text("#!/bin/sh\nprintf '%%s\\n' \"$@\" > '%s'\necho tool-stdout\nexit %d\n" % (mark, status))
        tool.chmod(0o755)
        return tool, mark


class TestWhoTheDesktopAccountIs(AnchorCase):
    BOX = [human("alice", 1000), human("bob", 1001), human("carol", 1002)]

    def test_an_explicit_user_wins_over_everything(self) -> None:
        done = self.anchor(self.BOX, "--user", "carol", env={"SUDO_USER": "alice", "PKEXEC_UID": "1001"})
        self.assertEqual(self.plan(done)["user"], "carol (uid 1002; from --user)")

    def test_an_empty_user_falls_to_sudo_user(self) -> None:
        # Exactly what `postinst` passes: `--user "${SUDO_USER:-}"` may be the empty string.
        done = self.anchor(self.BOX, "--user", "", env={"SUDO_USER": "alice", "PKEXEC_UID": "1001"})
        self.assertEqual(self.plan(done)["user"], "alice (uid 1000; from SUDO_USER)")

    def test_no_user_flag_at_all_falls_to_sudo_user(self) -> None:
        done = self.anchor(self.BOX, env={"SUDO_USER": "bob"})
        self.assertEqual(self.plan(done)["user"], "bob (uid 1001; from SUDO_USER)")

    def test_pkexec_uid_is_resolved_to_a_name_when_sudo_user_is_empty(self) -> None:
        done = self.anchor(self.BOX, "--user", "", env={"SUDO_USER": "", "PKEXEC_UID": "1002"})
        self.assertEqual(self.plan(done)["user"], "carol (uid 1002; from PKEXEC_UID)")

    def test_the_only_human_account_is_used_when_nothing_names_one(self) -> None:
        done = self.anchor([human("alice", 1000)], "--user", "")
        self.assertEqual(self.plan(done)["user"],
                         "alice (uid 1000; from the only human account in the passwd database)")

    def test_one_account_listed_twice_is_still_one_account(self) -> None:
        # Two sources answering for the same account (files and a directory) enumerate it twice.
        done = self.anchor([human("alice", 1000), human("alice", 1000)], "--user", "")
        self.assertEqual(self.resolved(done), "alice")

    def test_several_human_accounts_are_refused_and_named_never_guessed(self) -> None:
        done = self.anchor(self.BOX, "--user", "")
        self.refused(done, "3 human accounts", "alice (uid 1000), bob (uid 1001), carol (uid 1002)",
                     "would be a guess")

    def test_no_human_account_is_refused(self) -> None:
        self.refused(self.anchor([], "--user", ""), "holds no human account")

    def test_both_ends_of_the_human_range_are_inside_it(self) -> None:
        self.assertEqual(self.resolved(self.anchor([human("first", 1000)])), "first")
        self.assertEqual(self.resolved(self.anchor([human("last", 59999)])), "last")

    def test_an_account_below_the_range_is_not_a_human(self) -> None:
        self.refused(self.anchor([human("daemonish", 999)]), "holds no human account")

    def test_an_account_above_the_range_is_not_a_human(self) -> None:
        self.refused(self.anchor([human("nobodyish", 60000)]), "holds no human account")

    def test_a_nologin_shell_is_not_a_human(self) -> None:
        for shell in ("/usr/sbin/nologin", "/sbin/nologin", "nologin"):
            with self.subTest(shell=shell):
                self.refused(self.anchor([human("svc", 1001, shell=shell)]), "holds no human account")

    def test_a_false_shell_is_not_a_human(self) -> None:
        for shell in ("/bin/false", "/usr/bin/false"):
            with self.subTest(shell=shell):
                self.refused(self.anchor([human("svc", 1001, shell=shell)]), "holds no human account")

    def test_non_humans_do_not_stop_the_one_human_being_the_only_one(self) -> None:
        box = [human("alice", 1000), human("svc1", 1001, shell="/usr/sbin/nologin"),
               human("svc2", 1002, shell="/bin/false"), human("low", 999), human("high", 60000)]
        self.assertEqual(self.resolved(self.anchor(box)), "alice")

    def test_the_installers_own_accounts_are_never_the_only_human(self) -> None:
        # Given a login shell on purpose: the shell rule must not be what excludes them.
        name, uid = script_table()[0]
        self.assertTrue(1000 <= uid <= 59999, "the table left the human uid range; rewrite this test")
        self.refused(self.anchor([human(name, uid)]), "holds no human account")
        self.assertEqual(self.resolved(self.anchor([human(name, uid), human("alice", 1000)])), "alice")

    def test_a_name_on_a_service_uid_is_never_the_only_human(self) -> None:
        _, uid = script_table()[0]
        self.refused(self.anchor([human("alias", uid)]), "holds no human account")


class TestWhoIsRefused(AnchorCase):
    BOX = [human("alice", 1000)]

    def test_root_is_refused_from_every_source(self) -> None:
        for args, env in ((("--user", "root"), {}), (("--user", ""), {"SUDO_USER": "root"}),
                          (("--user", ""), {"PKEXEC_UID": "0"})):
            with self.subTest(args=args, env=env):
                self.refused(self.anchor(self.BOX, *args, env=env), "is root")

    def test_a_refused_name_does_not_fall_through_to_a_later_rule(self) -> None:
        # SUDO_USER=root with exactly one human on the box: still a refusal, not alice.
        self.refused(self.anchor(self.BOX, "--user", "", env={"SUDO_USER": "root"}), "from SUDO_USER", "is root")

    def test_uid_zero_under_another_name_is_refused(self) -> None:
        self.refused(self.anchor(self.BOX + ["toor:x:0:0::/root:/bin/bash"], "--user", "toor"),
                     "toor (uid 0)", "is root")
        self.refused(self.anchor(self.BOX + ["toor2:x:00:0::/root:/bin/bash"], "--user", "toor2"), "is root")

    def test_the_name_root_is_refused_whatever_uid_it_holds(self) -> None:
        pfile, gfile = self.tmp / "passwd", self.tmp / "group"
        pfile.write_text("root:x:1234:1234::/root:/bin/bash\n")
        gfile.write_text("")
        done = self.run_script("--dry-run", "--passwd-file", str(pfile), "--group-file", str(gfile),
                               "--user", "root", "anchor")
        self.refused(done, "root (uid 1234)", "is root")

    def test_an_unknown_name_is_refused(self) -> None:
        self.refused(self.anchor(self.BOX, "--user", "mallory"), "mallory, is not in the passwd database")
        self.refused(self.anchor(self.BOX, "--user", "", env={"SUDO_USER": "ghost"}),
                     "from SUDO_USER, ghost, is not in the passwd database")

    def test_a_uid_is_not_accepted_where_a_name_is_asked_for(self) -> None:
        self.refused(self.anchor(self.BOX, "--user", "1000"), "1000, is not in the passwd database")

    def test_a_pkexec_uid_nobody_holds_is_refused(self) -> None:
        self.refused(self.anchor(self.BOX, env={"PKEXEC_UID": "4242"}),
                     "PKEXEC_UID names uid 4242", "no account")

    def test_a_pkexec_uid_that_is_not_a_number_is_refused(self) -> None:
        self.refused(self.anchor(self.BOX, env={"PKEXEC_UID": "alice"}), "which is not a uid")

    def test_a_service_account_is_refused_by_name(self) -> None:
        name, uid = script_table()[3]
        self.refused(self.anchor(self.BOX + [passwd_line(name, uid)], "--user", name),
                     "%s is one of this installer's own service accounts" % name)
        # The table decides, not the box: refused whatever uid the box gave that name.
        self.refused(self.anchor(self.BOX + [human(name, 1500)], "--user", name),
                     "one of this installer's own service accounts")

    def test_an_account_on_a_service_uid_is_refused(self) -> None:
        name, uid = script_table()[3]
        self.refused(self.anchor(self.BOX + [human("alias", uid)], "--user", "alias"),
                     "alias holds uid %d, which is the service account %s's" % (uid, name))

    def test_a_string_that_is_not_an_account_name_is_refused(self) -> None:
        for bad in ("-x", "--dry-run", "a b", "a:b", "a/b", "a\\b", "al*"):
            with self.subTest(name=bad):
                self.refused(self.anchor(self.BOX, "--user", bad), "is not an account name")

    def test_a_passwd_entry_with_a_uid_that_is_not_a_number_is_refused(self) -> None:
        self.refused(self.anchor(["odd:x:abc:1000::/home/odd:/bin/bash"], "--user", "odd"),
                     "a uid that is not a number")


class TestWhereTheApplicationDataIs(AnchorCase):
    def test_the_default_is_the_passwd_home_then_local_share_then_the_bundle_identifier(self) -> None:
        done = self.anchor([human("alice", 1000, home="/srv/people/alice")], "--user", "alice")
        plan = self.plan(done)
        expected = "/srv/people/alice/.local/share/" + identifier()
        self.assertEqual(plan["app-data"].split(" ")[0], expected)
        self.assertIn("XDG_DATA_HOME", plan["app-data"], "the limitation is said where the path is printed")
        self.assertTrue(plan["command"].endswith(" --user alice --app-data " + expected), plan["command"])

    def test_the_session_environment_of_the_caller_decides_nothing(self) -> None:
        # Root's own XDG_DATA_HOME / HOME are not the desktop account's.
        done = self.anchor([human("alice", 1000)], "--user", "alice",
                           env={"XDG_DATA_HOME": "/root/xdg", "HOME": "/root"})
        self.assertEqual(self.plan(done)["app-data"].split(" ")[0],
                         "/home/alice/.local/share/" + identifier())

    def test_an_explicit_app_data_overrides_the_default(self) -> None:
        plan = self.plan(self.anchor([human("alice", 1000)], "--user", "alice", "--app-data", "/xdg/alice/brops"))
        self.assertEqual(plan["app-data"], "/xdg/alice/brops (from --app-data)")
        self.assertTrue(plan["command"].endswith(" --user alice --app-data /xdg/alice/brops"))

    def test_an_explicit_app_data_does_not_need_a_usable_home(self) -> None:
        plan = self.plan(self.anchor([human("alice", 1000, home="")], "--user", "alice", "--app-data", "/xdg/a"))
        self.assertEqual(plan["app-data"], "/xdg/a (from --app-data)")

    def test_an_app_data_with_more_than_one_spelling_is_refused(self) -> None:
        for bad in ("relative/dir", "/", "/a/", "/a//b", "/a/./b", "/a/../b", "/a/.."):
            with self.subTest(path=bad):
                self.refused(self.anchor([human("alice", 1000)], "--user", "alice", "--app-data", bad),
                             "--app-data", "binds it as a string")

    def test_a_home_that_cannot_be_built_on_is_refused_and_names_the_override(self) -> None:
        for bad in ("", "home/alice", "/", "/home/alice/", "/home//alice", "/home/./alice", "/home/../alice"):
            with self.subTest(home=bad):
                self.refused(self.anchor([human("alice", 1000, home=bad)], "--user", "alice"),
                             "the passwd home of alice", "--app-data <dir>")


class TestTheIdentifierIsTaurisNotOurs(unittest.TestCase):
    """Text only, so it runs on every platform."""

    def test_the_scripts_identifier_is_tauri_conf_jsons(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        literals = re.findall(r'(?m)^APP_IDENTIFIER="([^"]+)"$', text)
        self.assertEqual(literals, [identifier()])
        # The usage text states the default too, and must state the same one.
        self.assertIn("/.local/share/%s " % identifier(), text)

    def test_postinst_calls_the_stepless_form(self) -> None:
        # The form `all` was defined to serve. If postinst changes how it calls the installer,
        # this is where that is noticed.
        self.assertIn('"$BROPS_INSTALL_BIN" --user "${SUDO_USER:-}"', POSTINST.read_text(encoding="utf-8"))


class TestTheDryRun(AnchorCase):
    def test_it_prints_the_exact_command_and_runs_nothing(self) -> None:
        tool, mark = self.fake_tool()
        done = self.anchor([human("alice", 1000)], "--user", "alice", env={ANCHOR_ENV: str(tool)})
        plan = self.plan(done)
        self.assertEqual(plan["command"], "%s --user alice --app-data /home/alice/.local/share/%s"
                         % (tool, identifier()))
        self.assertFalse(mark.exists(), "a dry run ran the anchor tool")
        self.assertNotIn("tool-stdout", done.stdout)
        self.assertIn("the anchor tool was not run", done.stderr)

    def test_the_command_is_quoted_so_it_is_the_command(self) -> None:
        plan = self.plan(self.anchor([human("alice", 1000)], "--user", "alice", "--app-data", "/x/my data"))
        self.assertTrue(plan["command"].endswith(" --app-data /x/my\\ data"), plan["command"])

    def test_the_default_tool_is_the_packaged_one(self) -> None:
        plan = self.plan(self.anchor([human("alice", 1000)], "--user", "alice"))
        self.assertTrue(plan["command"].startswith("/usr/lib/brops/brops_install_anchor --user "), plan["command"])

    def test_an_absent_tool_is_said_but_does_not_fail_a_dry_run(self) -> None:
        done = self.anchor([human("alice", 1000)], "--user", "alice", env={ANCHOR_ENV: str(self.tmp / "no-such")})
        self.plan(done)
        self.assertIn("is not installed; a real run would REFUSE", done.stderr)


class TestAll(AnchorCase):
    def test_the_stepless_form_is_accounts_then_anchor(self) -> None:
        table = script_table()
        done = self.anchor([human("alice", 1000)], "--user", "alice", step=None)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual([l.split(" ")[0] for l in lines[:len(table)]], [name for name, _ in table])
        self.assertEqual([" ".join(l.split(" ")[:2]) for l in lines[len(table):]],
                         ["anchor user", "anchor app-data", "anchor command"])
        self.assertEqual(self.plan(done)["user"], "alice (uid 1000; from --user)")

    def test_the_stepless_form_with_an_empty_user_is_what_postinst_sends(self) -> None:
        done = self.anchor([human("alice", 1000)], "--user", "", step=None, env={"SUDO_USER": "alice"})
        self.assertEqual(self.plan(done)["user"], "alice (uid 1000; from SUDO_USER)")
        self.assertEqual(len(done.stdout.splitlines()), len(script_table()) + 3)

    def test_naming_all_is_the_stepless_form(self) -> None:
        box = [human("alice", 1000)]
        stepless = self.anchor(box, "--user", "alice", step=None)
        named = self.anchor(box, "--user", "alice", step="all")
        self.assertEqual(named.returncode, 0, named.stderr)
        self.assertEqual(named.stdout, stepless.stdout)

    def test_no_step_and_no_user_is_a_usage_error_not_all(self) -> None:
        done = self.anchor([human("alice", 1000)], step=None)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")

    def test_when_accounts_refuses_the_anchor_step_plans_nothing(self) -> None:
        name, uid = script_table()[0]
        done = self.anchor([human("alice", 1000), passwd_line(name, 998, gid=uid)], "--user", "alice",
                           step=None, group=[group_line(name, uid)])
        self.refused(done, "account %s exists with uid 998" % name)

    def test_an_unresolvable_user_is_refused_before_any_account_is_planned(self) -> None:
        self.refused(self.anchor([human("alice", 1000)], "--user", "root", step=None), "is root")

    def test_the_accounts_step_alone_takes_no_user_and_no_app_data(self) -> None:
        for extra in (("--user", "alice"), ("--app-data", "/x")):
            with self.subTest(extra=extra):
                done = self.anchor([human("alice", 1000)], *extra, step="accounts")
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("takes neither", done.stderr)
                self.assertEqual(done.stdout, "")

    def test_flag_shapes_that_are_usage_errors(self) -> None:
        box = [human("alice", 1000)]
        for args, needle in ((("--user", "alice", "--user", "bob"), "--user was given more than once"),
                             (("--app-data", "/a", "--app-data", "/b"), "--app-data was given more than once"),
                             (("--app-data", ""), "--app-data needs a directory")):
            with self.subTest(args=args):
                done = self.anchor(box, *args)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn(needle, done.stderr)
                self.assertEqual(done.stdout, "")
        done = self.anchor(box, "--user", "alice", "anchor", step="all")
        self.assertEqual(done.returncode, 2)
        self.assertIn("more than one step named", done.stderr)
        # `--user` as the last word has no value at all — which is not the same as an empty one.
        done = self.run_script("--dry-run", "anchor", "--user")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("--user needs a value", done.stderr)


@unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                 "these run the installer for real and must never do so as root")
class TestTheRealRun(AnchorCase):
    """No `--dry-run`, no file seam: the machine's own database, and a FAKE anchor tool."""

    def setUp(self) -> None:
        super().setUp()
        import pwd
        try:
            me = pwd.getpwuid(os.getuid())
        except KeyError:
            self.skipTest("the account running the tests is not in the passwd database")
        table = dict(script_table())
        if (not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.@-]*", me.pw_name) or me.pw_name in table
                or me.pw_uid in table.values()):
            self.skipTest("the account running the tests is not one the installer would accept")
        self.me = me
        self.app_data = str(self.tmp / "app-data")

    def real(self, tool: pathlib.Path | str, *args: str) -> subprocess.CompletedProcess:
        return self.run_script(*args, env={ANCHOR_ENV: str(tool)})

    def test_it_runs_the_tool_with_exactly_user_and_app_data(self) -> None:
        tool, mark = self.fake_tool(0)
        done = self.real(tool, "--user", self.me.pw_name, "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(mark.read_text().splitlines(),
                         ["--user", self.me.pw_name, "--app-data", self.app_data])
        self.assertIn("tool-stdout", done.stdout, "the tool's own report is passed through")
        self.assertIn("succeeded for %s" % self.me.pw_name, done.stderr)
        self.assertFalse(pathlib.Path(self.app_data).exists(), "the script itself created something")

    def test_a_failing_tool_is_the_installers_exit_status(self) -> None:
        tool, mark = self.fake_tool(7)
        done = self.real(tool, "--user", self.me.pw_name, "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 7, done.stderr)
        self.assertTrue(mark.exists())
        self.assertIn("exited 7: trust is NOT provisioned", done.stderr)
        self.assertNotIn("succeeded", done.stderr)

    def test_an_absent_tool_is_a_refusal_never_a_success(self) -> None:
        done = self.real(self.tmp / "no-such-tool", "--user", self.me.pw_name, "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("REFUSED", done.stderr)
        self.assertIn("is not installed", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_a_tool_that_is_not_runnable_is_a_refusal(self) -> None:
        plain = self.tmp / "plain"
        plain.write_text("#!/bin/sh\nexit 0\n")
        plain.chmod(0o644)
        done = self.real(plain, "--user", self.me.pw_name, "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("REFUSED", done.stderr)
        self.assertIn("not an executable file", done.stderr)

    def test_a_tool_that_is_a_directory_is_a_refusal(self) -> None:
        folder = self.tmp / "folder"
        folder.mkdir()
        done = self.real(folder, "--user", self.me.pw_name, "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("REFUSED", done.stderr)
        self.assertIn("not an executable file", done.stderr)

    def test_a_refused_user_never_reaches_the_tool(self) -> None:
        tool, mark = self.fake_tool(0)
        done = self.real(tool, "--user", "root", "--app-data", self.app_data, "anchor")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("is root", done.stderr)
        self.assertFalse(mark.exists(), "the tool ran for a refused account")

    def test_all_runs_accounts_first_and_a_refusal_there_stops_before_the_tool(self) -> None:
        # Not root, so the accounts step refuses. The stepless form, as postinst calls it.
        tool, mark = self.fake_tool(0)
        done = self.real(tool, "--user", self.me.pw_name, "--app-data", self.app_data)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("must run as root", done.stderr)
        self.assertFalse(mark.exists(), "the anchor tool ran although the accounts step refused")
        self.assertEqual(done.stdout, "")

    def test_the_real_database_resolves_this_account_as_python_does(self) -> None:
        tool, _ = self.fake_tool(0)
        done = self.real(tool, "--dry-run", "--user", self.me.pw_name, "anchor")
        home = self.me.pw_dir
        if not home.startswith("/") or home == "/" or re.search(r"/(\.{0,2})(/|$)", home):
            self.assertEqual(done.returncode, 1, done.stderr)
            return
        plan = self.plan(done)
        self.assertEqual(plan["user"], "%s (uid %d; from --user)" % (self.me.pw_name, self.me.pw_uid))
        self.assertEqual(plan["app-data"].split(" ")[0], "%s/.local/share/%s" % (home, identifier()))

    def test_the_only_human_rule_enumerates_the_real_database_as_python_does(self) -> None:
        import pwd
        table = dict(script_table())
        humans = sorted({p.pw_name for p in pwd.getpwall()
                         if 1000 <= p.pw_uid <= 59999 and p.pw_name not in table
                         and p.pw_uid not in table.values()
                         and not re.search(r"(^|/)(nologin|false)$", p.pw_shell)})
        tool, _ = self.fake_tool(0)
        done = self.real(tool, "--dry-run", "--app-data", self.app_data, "anchor")
        self.assertNotIn("unreadable", done.stderr)
        if len(humans) == 1:
            self.assertEqual(self.plan(done)["user"],
                             "%s (uid %d; from the only human account in the passwd database)"
                             % (humans[0], pwd.getpwnam(humans[0]).pw_uid))
        else:
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertIn("no human account" if not humans else "%d human accounts" % len(humans), done.stderr)
            for name in humans:
                self.assertIn(name, done.stderr)


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
