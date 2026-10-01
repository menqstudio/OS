"""The .deb `postinst` hands provisioning to `brops-install` and reports ITS verdict.

`apps/desktop/src-tauri/deb/postinst` is what dpkg runs as root after unpacking the
package (docs/design/DEBIAN_INSTALL_PROVISIONING.md, slice A). It is a few lines of
shell, and every one of them decides whether a box that failed to provision trust
looks installed. So the contract is held here, by running the real script against a
fake installer -- no root, no build, no dpkg:

  * installer absent            -> exit 0, and one line saying trust is NOT provisioned
  * installer present, exits 0  -> exit 0
  * installer present, exits 7  -> exit 7 (design section 4.5: a failed provision
                                   must fail the package install)
  * present but not runnable    -> exit 1, never a silent success
  * any dpkg action other than `configure` never reaches the installer
  * the script itself creates no account and no key

The installer path is overridable through `BROPS_INSTALL_BIN`; every run here sets
it, so a test can never reach a real `/usr/lib/brops/brops-install`.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _prerequisites import REPO_ROOT, Prerequisite, requires  # noqa: E402

SCRIPT = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "deb" / "postinst"
REAL_INSTALLER = "/usr/lib/brops/brops-install"

DEB_POSTINST = Prerequisite(
    "apps/desktop deb postinst",
    SCRIPT.is_file,
    "apps/desktop/src-tauri/deb/postinst is not present beside the engine tree "
    "(deployment Step 6 copies engine/ only)",
)

#: Commands that would mean the script had started provisioning for itself.
_FORBIDDEN_COMMANDS = (
    "useradd", "adduser", "groupadd", "addgroup", "usermod", "openssl", "ssh-keygen",
    "gpg", "chown", "chmod", "mkdir", "systemctl", "visudo",
)


@unittest.skipUnless(os.name == "posix", "a Debian maintainer script; needs a POSIX sh")
@requires(DEB_POSTINST)
class DebPostinst(unittest.TestCase):
    def setUp(self):
        self.sh = shutil.which("sh")
        self.assertIsNotNone(self.sh, "no `sh` on PATH")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.installer = self.tmp / "brops-install"
        self.argv_log = self.tmp / "argv.log"

    # -- helpers ---------------------------------------------------------------------------

    def fake_installer(self, status: int, mode: int = 0o755) -> None:
        """An installer that records each argument on its own line, then exits `status`."""
        self.installer.write_text(
            "#!/bin/sh\n"
            f"for arg in \"$@\"; do printf '%s\\n' \"$arg\"; done > '{self.argv_log}'\n"
            f"exit {status}\n",
            encoding="utf-8",
        )
        self.installer.chmod(mode)

    def run_postinst(self, *args: str, sudo_user: str | None = "alice"):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "BROPS_INSTALL_BIN": str(self.installer)}
        if sudo_user is not None:
            env["SUDO_USER"] = sudo_user
        return subprocess.run([self.sh, str(SCRIPT), *args], env=env, capture_output=True,
                              text=True, timeout=30)

    def recorded_argv(self) -> list[str]:
        return self.argv_log.read_text(encoding="utf-8").split("\n")[:-1]

    def assert_installer_never_ran(self) -> None:
        self.assertFalse(self.argv_log.exists(), "the installer was run")

    # -- the script as a file --------------------------------------------------------------

    def test_it_is_valid_posix_sh(self):
        result = subprocess.run([self.sh, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_it_is_an_executable_sh_script_under_set_eu(self):
        lines = SCRIPT.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertIn("set -eu", lines)
        self.assertTrue(os.access(SCRIPT, os.X_OK),
                        "dpkg refuses a maintainer script that is not executable")

    def test_the_default_installer_is_the_packaged_path(self):
        self.assertIn('BROPS_INSTALL_BIN="${BROPS_INSTALL_BIN:-' + REAL_INSTALLER + '}"',
                      SCRIPT.read_text(encoding="utf-8"))

    def test_it_creates_no_account_and_no_key_itself(self):
        code = [line.split("#", 1)[0] for line in SCRIPT.read_text(encoding="utf-8").splitlines()]
        words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", "\n".join(code)))
        self.assertEqual(sorted(words.intersection(_FORBIDDEN_COMMANDS)), [])

    # -- the three cases the design names --------------------------------------------------

    def test_absent_installer_says_not_provisioned_and_exits_zero(self):
        self.assertFalse(self.installer.exists())
        result = self.run_postinst("configure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("\n"), 1, result.stderr)
        self.assertIn("trust is NOT provisioned", result.stderr)
        self.assertIn("governed path stays refused", result.stderr)
        self.assertIn(str(self.installer), result.stderr)

    def test_successful_installer_exits_zero_and_is_given_the_sudo_user(self):
        self.fake_installer(0)
        result = self.run_postinst("configure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_argv(), ["--user", "alice"])
        self.assertNotIn("NOT provisioned", result.stderr)

    def test_failing_installer_fails_the_install_with_its_own_status(self):
        self.fake_installer(7)
        result = self.run_postinst("configure")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.recorded_argv(), ["--user", "alice"])
        self.assertIn("trust is NOT provisioned", result.stderr)

    # -- the edges around them -------------------------------------------------------------

    def test_without_sudo_user_the_installer_is_given_an_empty_user_to_refuse(self):
        self.fake_installer(0)
        result = self.run_postinst("configure", sudo_user=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_argv(), ["--user", ""])

    def test_an_upgrade_configure_runs_the_installer_again(self):
        self.fake_installer(0)
        result = self.run_postinst("configure", "0.1.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_argv(), ["--user", "alice"])

    def test_installer_present_but_not_executable_fails_the_install(self):
        self.fake_installer(0, mode=0o644)
        result = self.run_postinst("configure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("trust is NOT provisioned", result.stderr)
        self.assert_installer_never_ran()

    def test_installer_path_that_is_a_directory_fails_the_install(self):
        self.installer.mkdir()
        result = self.run_postinst("configure")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("trust is NOT provisioned", result.stderr)

    def test_dpkg_unwind_actions_never_reach_the_installer(self):
        for action in ("abort-upgrade", "abort-remove", "abort-deconfigure", "triggered"):
            with self.subTest(action=action):
                self.fake_installer(7)
                result = self.run_postinst(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_installer_never_ran()

    def test_an_unknown_or_missing_action_is_refused_without_running_the_installer(self):
        for args in ((), ("install",), ("",)):
            with self.subTest(args=args):
                self.fake_installer(0)
                result = self.run_postinst(*args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("unknown argument", result.stderr)
                self.assert_installer_never_ran()


if __name__ == "__main__":
    unittest.main()
