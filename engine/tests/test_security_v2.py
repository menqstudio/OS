import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_contracts import validate_registered_schemas
from bro_security import (
    SecurityError,
    analyze_command,
    enforce_scope,
    enforce_scope_within_binding,
    finalize_nonce,
    quarantine_nonce,
    release_nonce_reservation,
    reserve_nonce,
    validate_exact_push,
)


class SecurityV2Tests(unittest.TestCase):
    def test_git_global_option_bypasses_are_detected(self):
        cases = [
            "git -C /repo push origin main",
            "git -C . commit -m x",
            "git -c http.extraheader=x push origin main",
            "git -c credential.helper=x push origin main",
            "git --git-dir=.git push origin main",
            "git --work-tree=. commit -am x",
            "git -C . -c user.name=x commit -m x",
            "git -c core.sshCommand=evil push",
            "git -c alias.x=push x origin main",
            "git update-ref refs/heads/x HEAD",
            "git stash",
            "git worktree add ../x",
            "git config user.name x",
            "git remote set-url origin evil",
        ]
        for command in cases:
            info = analyze_command(command)[0]
            self.assertTrue(info.mutating, command)
        self.assertTrue(
            analyze_command("git -c alias.x=push x origin main")[0].dangerous_config
        )

    def test_code_exec_config_on_read_only_git_is_not_read_only(self):
        # `git -c <exec-config> status/log/diff` is an RCE vector — the config runs code
        # while the subcommand looks read-only. Every such injection must be dangerous
        # (so it is not classified read-only, even in review mode), not just the three
        # keys the old denylist happened to name.
        for command in [
            "git -c core.fsmonitor=evil status",
            "git -c core.pager=evil log",
            "git -c core.hooksPath=/tmp/h status",
            "git -c diff.external=evil diff",
            "git -c uploadpack.packObjectsHook=evil status",
            "git -c sequence.editor=evil rebase",
            "git --config-env=core.sshCommand=EVIL status",
        ]:
            info = analyze_command(command)[0]
            self.assertTrue(info.dangerous_config, command)
            self.assertTrue(info.mutating, command)
        # A display-only config keeps a read-only subcommand read-only.
        safe = analyze_command("git -c color.ui=false status")[0]
        self.assertFalse(safe.dangerous_config, "color.ui is display-only")
        self.assertFalse(safe.mutating, "color.ui on status stays read-only")

    def test_git_path_global_options_surface_containment_targets(self):
        # A read-only git subcommand steered by -C/--git-dir/--work-tree reads a filesystem
        # location; that location MUST be a containment target so the workspace/scope gates
        # can deny an out-of-workspace read exactly like `cat /elsewhere` — not sail through
        # with empty targets (audit F-04).
        for command, expected in (
            ("git -C /home/victim/repo show", "/home/victim/repo"),
            ("git --git-dir=/home/v/.git log", "/home/v/.git"),
            ("git --work-tree=/etc status", "/etc"),
            ("git -C .. diff", ".."),
        ):
            info = analyze_command(command)[0]
            self.assertTrue(info.recognized_read_only, command)
            self.assertIn(expected, info.targets, command)
        # A config option (-c) is NOT a filesystem path and must not become a target.
        self.assertEqual(analyze_command("git -c color.ui=false status")[0].targets, ())

    def test_read_only_git_subcommand_with_an_unlisted_flag_is_not_read_only(self):
        # A read-only SUBCOMMAND can still write or execute through its options:
        # `--output` writes a file, `--ext-diff`/`--textconv`/`--filters` run configured
        # programs. The subcommand used to decide alone, so `git diff --output=<path>`
        # classified READ_LOCAL and the read-scope gate then dropped the flag token —
        # the only place the path appeared.
        for command, surfaced in (
            ("git diff --output=runtime/x.py HEAD~1", "runtime/x.py"),
            ("git log --output=runtime/x.py -1", "runtime/x.py"),
            ("git show --outp=runtime/x.py HEAD", "runtime/x.py"),   # git accepts abbreviations
            ("git diff --output runtime/x.py", "runtime/x.py"),
            ("git diff --ext-diff", None),
            ("git show --textconv HEAD:x", None),
            ("git cat-file --filters HEAD:x", None),
            ("git cat-file --textconv HEAD:x", None),
            ("git ls-files --exclude-from=/etc/shadow", "/etc/shadow"),
            ("git status --no-such-flag", None),
        ):
            info = analyze_command(command)[0]
            self.assertTrue(info.mutating, command)
            self.assertFalse(info.recognized_read_only, command)
            if surfaced is not None:
                self.assertIn(surfaced, info.targets, command)

    def test_read_only_git_subcommand_with_listed_flags_stays_read_only(self):
        for command in (
            "git status --short --branch",
            "git diff --stat --cached",
            "git log --oneline -5",
            "git log -n5 --format=%H",
            "git show --name-only HEAD",
            "git rev-parse --abbrev-ref HEAD",
            "git ls-files --others --exclude-standard",
            "git cat-file -p HEAD",
            # After a bare `--` everything is a pathspec, not an option.
            "git diff -- --output=x",
        ):
            info = analyze_command(command)[0]
            self.assertTrue(info.recognized_read_only, command)
            self.assertFalse(info.mutating, command)

    def test_path_qualified_executable_is_never_the_read_only_builtin(self):
        # The basename is what a file is called, not what it is: `./tmp/echo hi` runs
        # whatever sits at ./tmp/echo. A path-qualified executable is therefore never
        # read-only, and the file itself is a target for the scope gate.
        for command, path in (
            ("./tmp/echo hi", "./tmp/echo"),
            ("/tmp/evil/cat x", "/tmp/evil/cat"),
            # A Windows spelling is a path too, and reaches the classifier only inside single
            # quotes: an unquoted backslash is outside the accepted command language (T-159).
            ("'tools\\ls.exe'", "tools\\ls.exe"),
            ('"./my tools/pwd"', "./my tools/pwd"),
            ("/usr/bin/git status", "/usr/bin/git"),
            ("./find . -name x", "./find"),
        ):
            info = analyze_command(command)[0]
            self.assertTrue(info.mutating, command)
            self.assertFalse(info.recognized_read_only, command)
            self.assertEqual(info.targets[0], path, command)
        # The bare names are untouched.
        for command in ("echo hi", "cat x", "git status", "find . -name x"):
            info = analyze_command(command)[0]
            self.assertFalse(info.mutating, command)
            self.assertTrue(info.recognized_read_only, command)
        # A segment that was already mutating with NO determinable target is refused
        # by the scope gate for that reason. Naming its executable by path must not
        # hand it a target that could then match a scope.
        for command in ('./tools/bash -c "rm x"', "/usr/bin/python3 -c pass", "./tools/git commit"):
            info = analyze_command(command)[0]
            self.assertTrue(info.mutating, command)
            self.assertEqual(info.targets, (), command)
        # End to end: the shell verbs leave READ_LOCAL for UNKNOWN, which is denied
        # outright; a path-qualified git becomes a governed mutation, never a read.
        from bro_authorization import classify_tool_action
        for command in ("./tmp/echo hi", "/tmp/evil/cat x"):
            classified = classify_tool_action("Bash", {"command": command})
            self.assertTrue(classified.unknown, command)
            self.assertTrue(classified.mutating, command)
        for command in ("/usr/bin/git status", "git diff --output=runtime/x.py HEAD~1"):
            classified = classify_tool_action("Bash", {"command": command})
            self.assertNotIn("READ_LOCAL", classified.capabilities, command)
            self.assertTrue(classified.mutating, command)

    def test_segments_quotes_windows_and_mixed_case(self):
        # Until T-159 this was ONE command, split on `&&`, `;` and `|` into four segments that
        # were classified one by one. A command that is more than one command is refused whole
        # now (design Appendix A, Q3); each former segment is still classified as it was when it
        # arrives alone.
        whole = ('git status && C:\\Git\\bin\\GIT.EXE -C . commit -m "x y"; '
                 "git log | git show")
        with self.assertRaises(SecurityError):
            analyze_command(whole)
        for command in ("git status", "git log", "git show"):
            (info,) = analyze_command(command)
            self.assertEqual((info.executable, info.mutating), ("git", False), command)
        # Mixed case and `.exe` still fold to `git`; quotes still group an argument.
        (info,) = analyze_command('GIT.EXE -C . commit -m "x y"')
        self.assertEqual((info.executable, info.subcommand, info.mutating), ("git", "commit", True))
        self.assertIn("x y", info.targets)
        # The Windows path is refused bare (a backslash is not in the language) and is a
        # path-qualified executable when quoted.
        with self.assertRaises(SecurityError):
            analyze_command('C:\\Git\\bin\\GIT.EXE -C . commit -m "x y"')
        (info,) = analyze_command("'C:\\Git\\bin\\GIT.EXE' status")
        self.assertTrue(info.mutating)
        self.assertFalse(info.recognized_read_only)

    def test_wrappers_are_fail_closed(self):
        cases = [
            'powershell -Command "Set-Content secret.txt hacked"',
            'pwsh -c "Remove-Item x"',
            "cmd /c del x",
            'bash -c "git push origin main"',
            'sh -c "rm x"',
            "python -c 'pass'",
        ]
        for command in cases:
            self.assertTrue(analyze_command(command)[0].mutating, command)
        # A wrapper whose payload needs an escape does not reach the classifier at all.
        with self.assertRaises(SecurityError):
            analyze_command('python -c "open(\\"x\\",\\"w\\").write(\\"bad\\")"')

    def test_redirection_and_substitution_are_denied(self):
        for command in (
            "echo hacked > file.txt",
            "cat x < y",
            "echo `whoami`",
            "cat $(rm -rf x)",          # unquoted command substitution
            'cat "$(rm -rf x)"',        # substitution inside double quotes still runs
            'echo "`whoami`"',          # backtick inside double quotes still runs
            "echo $((1+1))",            # arithmetic expansion shares the $( opener
        ):
            with self.assertRaises(SecurityError, msg=command):
                analyze_command(command)

    def test_a_bare_ampersand_cannot_hide_a_command_behind_a_read_only_verb(self):
        # `&` separates commands exactly as `;` does. Until 2026-10-01 it was not in the separator
        # list, so `echo hi & rm -rf src` was ONE segment led by `echo`: classified READ_LOCAL,
        # not mutating, no targets -- and the `rm` reached no gate at all.
        for command in (
            "echo hi & rm -rf src",
            "echo hi &rm -rf src",
            "ls& git push origin main",
            "sleep 5 &",
            "echo a |& tee b",
        ):
            with self.assertRaises(SecurityError, msg=command):
                analyze_command(command)

    def test_an_ampersand_that_separates_nothing_is_still_text(self):
        # Quoted, `&` is an argument.
        self.assertEqual(len(analyze_command("echo 'a & b'")), 1)
        self.assertEqual(len(analyze_command('echo "a & b"')), 1)
        # Escaped, it was an argument until T-159; the language has no escape, so it is refused.
        # And `&&` was a separator whose second segment was classified; it is refused whole.
        for command in ("echo a \\& b", "echo hi && rm -rf src"):
            with self.assertRaises(SecurityError, msg=command):
                analyze_command(command)

    def test_single_quoted_substitution_is_literal(self):
        # Single quotes suppress substitution in the shell, so '$(...)' and
        # backticks are literal text, not a bypass, and must not be rejected.
        infos = analyze_command("echo '$(rm -rf x)'")
        self.assertEqual(infos[0].executable, "echo")

    def test_unknown_executable_is_not_read_only(self):
        info = analyze_command("custom-tool --do-anything")[0]
        self.assertTrue(info.mutating)
        self.assertFalse(info.recognized_read_only)

    def test_exact_push_shape(self):
        validate_exact_push(
            "git push origin HEAD:bro-agent-os-v1", "bro-agent-os-v1"
        )
        blocked = [
            "git push origin bro-agent-os-v1",
            "git push upstream HEAD:bro-agent-os-v1",
            "git push --force origin HEAD:bro-agent-os-v1",
            "git -C . push origin HEAD:bro-agent-os-v1",
            "git push origin HEAD:other",
            "git status && git push origin HEAD:bro-agent-os-v1",
            # A path-qualified git is a file somebody named, not the git on PATH.
            "./git push origin HEAD:bro-agent-os-v1",
            "/tmp/evil/git push origin HEAD:bro-agent-os-v1",
        ]
        for command in blocked:
            with self.assertRaises(SecurityError, msg=command):
                validate_exact_push(command, "bro-agent-os-v1")

    def test_scope_enforcement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "ok").mkdir()
            enforce_scope(root, ["ok/a.txt"], ["ok"], ["ok/no"])
            for bad in ("../x", "/tmp/x", "C:/Windows/x"):
                with self.assertRaises(SecurityError):
                    enforce_scope(root, [bad], ["ok"], [])
            with self.assertRaises(SecurityError):
                enforce_scope(root, ["ok/no/x"], ["ok"], ["ok/no"])

    def test_absolute_target_needs_an_absolute_scope_entry(self):
        # An absolute path is not silently reinterpreted as repo-relative, and an
        # absolute spelling of an in-repo path does not inherit a repo grant.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "ok").mkdir()
            with self.assertRaises(SecurityError) as caught:
                enforce_scope(root, [str(root / "ok" / "a.txt")], ["ok"], [])
            self.assertIn("no absolute scope entry", str(caught.exception))

    def test_absolute_scope_entry_grants_an_absolute_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = pathlib.Path(temp_dir) / "desktop-project"
            (outside / "src").mkdir(parents=True)
            grant = outside.as_posix()
            enforce_scope(pathlib.Path(temp_dir), [str(outside / "src" / "a.ts")], [grant], [])
            with self.assertRaises(SecurityError):
                enforce_scope(pathlib.Path(temp_dir),
                              [str(outside.parent / "elsewhere" / "a.ts")], [grant], [])

    def test_absolute_prohibition_beats_an_absolute_grant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = pathlib.Path(temp_dir) / "desktop-project"
            (outside / "secrets").mkdir(parents=True)
            with self.assertRaises(SecurityError):
                enforce_scope(pathlib.Path(temp_dir),
                              [str(outside / "secrets" / "k.pem")],
                              [outside.as_posix()],
                              [(outside / "secrets").as_posix()])

    def test_absolute_target_cannot_walk_out_of_its_grant(self):
        # Containment is decided on resolved paths, so '..' is spent before the
        # comparison. A textual prefix test would accept this.
        with tempfile.TemporaryDirectory() as temp_dir:
            base = pathlib.Path(temp_dir)
            (base / "granted").mkdir()
            (base / "secret").mkdir()
            with self.assertRaises(SecurityError):
                enforce_scope(base, [str(base / "granted" / ".." / "secret" / "k.pem")],
                              [(base / "granted").as_posix()], [])

    def test_absolute_target_cannot_follow_a_symlink_out_of_its_grant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = pathlib.Path(temp_dir)
            (base / "granted").mkdir()
            (base / "secret").mkdir()
            try:
                os.symlink(base / "secret", base / "granted" / "link",
                           target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                # Windows needs Developer Mode or SeCreateSymbolicLink for this.
                self.skipTest(f"symlinks unavailable on this host: {exc}")
            with self.assertRaises(SecurityError):
                enforce_scope(base, [str(base / "granted" / "link" / "k.pem")],
                              [(base / "granted").as_posix()], [])

    def test_repository_prohibition_survives_an_absolute_spelling(self):
        # An absolute grant covering the repository must not become a way around a
        # repo-relative prohibition just by spelling the target differently.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "release").mkdir()
            with self.assertRaises(SecurityError):
                enforce_scope(root, [str(root / "release" / "sign.py")],
                              [root.as_posix()], ["release"])

    def test_device_and_network_targets_are_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            for target in ("\\\\host\\share\\x", "\\\\?\\C:\\x"):
                with self.assertRaises(SecurityError, msg=target):
                    enforce_scope(root, [target], [root.as_posix()], [])

    def test_scope_outside_the_bound_workspace_is_refused_by_name(self):
        # The operator-signed binding is the outer boundary; a task contract cannot
        # widen it. Refused once, naming the cause, rather than denying every
        # target with a message about the target.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir) / "workspace"
            root.mkdir()
            enforce_scope_within_binding(root, ["docs", (root / "sub").as_posix()])
            with self.assertRaises(SecurityError) as caught:
                enforce_scope_within_binding(
                    root, ["docs", (root.parent / "elsewhere").as_posix()])
            self.assertIn("outside the bound workspace root", str(caught.exception))

    # `test_signature_and_tamper` and `test_atomic_nonce_replay_legacy` stood here. They were the
    # only callers of the HMAC `verify_signed_document` and the legacy `consume_nonce`, and went
    # with them (T-153). Their absence is held by
    # `test_release_v3.LegacyReleaseGrantRetiredTests`; nonce replay on the live path is the
    # reserve/finalize tests below.

    def test_nonce_reserve_then_finalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            self.assertEqual(len(list(ledger.glob("*.reserved"))), 1)
            finalize_nonce(payload, ledger, "toolu_1", command)
            self.assertEqual(len(list(ledger.glob("*.reserved"))), 0)
            self.assertEqual(len(list(ledger.glob("*.used"))), 1)
            with self.assertRaises(SecurityError):
                reserve_nonce(payload, ledger, "toolu_2", command)

    def test_failed_push_can_release_only_matching_reservation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            with self.assertRaises(SecurityError):
                release_nonce_reservation(payload, ledger, "toolu_wrong", command)
            release_nonce_reservation(payload, ledger, "toolu_1", command)
            self.assertEqual(list(ledger.glob("*.reserved")), [])
            reserve_nonce(payload, ledger, "toolu_2", command)

    def test_ambiguous_push_quarantines_nonce(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = pathlib.Path(temp_dir)
            payload = {
                "nonce": "abcdefghijklmnop",
                "expected_head_sha": "a" * 40,
                "branch": "main",
            }
            command = "git push origin HEAD:main"
            reserve_nonce(payload, ledger, "toolu_1", command)
            quarantine_nonce(payload, ledger, "toolu_1", command, "network unknown")
            self.assertEqual(len(list(ledger.glob("*.ambiguous"))), 1)
            with self.assertRaises(SecurityError):
                reserve_nonce(payload, ledger, "toolu_2", command)

    def test_registered_schemas_compile(self):
        self.assertGreaterEqual(validate_registered_schemas(ROOT), 10)

    def test_the_schema_registry_drift_check_can_actually_fail(self):
        """It compared a counter with the length of the list the counter had just been run over,
        so "schema registry drift" was a message nothing could produce."""
        import shutil
        from bro_contracts import ContractError

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            shutil.copytree(ROOT / "schemas", root / "schemas")
            registered = validate_registered_schemas(root)          # the control: a copy passes
            self.assertEqual(registered, validate_registered_schemas(ROOT))

            # A schema file the registry does not name is validated by nothing.
            stray = root / "schemas" / "stray.schema.json"
            stray.write_text(json.dumps({"type": "object"}), encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                validate_registered_schemas(root)
            self.assertIn("schema registry drift", str(caught.exception))
            self.assertIn("schemas/stray.schema.json", str(caught.exception))
            stray.unlink()

            # The same path registered twice.
            registry_path = root / "schemas" / "registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["schemas"].append(dict(registry["schemas"][0]))
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                validate_registered_schemas(root)
            self.assertIn("registered more than once", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
