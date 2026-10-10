"""The engine-test environment probe goes RED for each fact the audit's sandbox lacked."""

import contextlib
import io
import os
import pathlib
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import check_engine_test_env as probe  # noqa: E402

POSIX = os.name == "posix"


def _run_main() -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = probe.main()
    return code, out.getvalue()


@unittest.skipUnless(POSIX, "the probe judges POSIX environments only")
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.euid = os.geteuid()

    def test_this_environment_passes_all_three(self):
        self.assertEqual(probe.problems(), [])
        code, text = _run_main()
        self.assertEqual(code, 0, text)
        self.assertIn("GREEN", text)
        self.assertIn(f"uid {self.euid}", text)

    def test_a_refused_bind_is_named(self):
        with tempfile.TemporaryDirectory() as fresh:
            with mock.patch.object(socket.socket, "bind", side_effect=PermissionError(1, "Operation not permitted")):
                problem = probe.probe_unix_socket(fresh)
        self.assertIsNotNone(problem)
        self.assertIn("AF_UNIX", problem)
        self.assertIn("PermissionError", problem)

    def test_a_socket_nobody_listens_on_is_named(self):
        with tempfile.TemporaryDirectory() as fresh:
            with mock.patch.object(socket.socket, "listen", side_effect=OSError("no listen")):
                self.assertIn("no listen", probe.probe_unix_socket(fresh) or "")

    def test_a_working_socket_is_not_a_problem(self):
        with tempfile.TemporaryDirectory() as fresh:
            self.assertIsNone(probe.probe_unix_socket(fresh))

    def test_a_directory_owned_by_someone_else_is_named(self):
        with tempfile.TemporaryDirectory() as fresh:
            self.assertIsNone(probe.probe_owned_directory(fresh, self.euid))
            problem = probe.probe_owned_directory(fresh, self.euid + 1)
        self.assertIn(f"owned by uid {self.euid}", problem or "")

    def test_a_mode_that_does_not_take_is_named(self):
        with tempfile.TemporaryDirectory() as fresh:
            real = os.stat(fresh)
            fake = os.stat_result((real.st_mode | 0o077,) + tuple(real)[1:])
            # A filesystem that ignores the chmod: the call succeeds and the mode reads back wide.
            with mock.patch.object(os, "chmod"), mock.patch.object(os, "stat", return_value=fake):
                problem = probe.probe_owned_directory(fresh, self.euid)
        self.assertIn("not 0700", problem or "")

    def test_a_temp_directory_owned_by_a_foreign_uid_is_named(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(probe.probe_temp_owner(root, self.euid))
            # Seen from a uid that is neither the owner nor root, the same directory is foreign.
            other = self.euid + 1
            if self.euid == 0:
                self.skipTest("root owns the directory, and a root-owned temp directory is accepted")
            problem = probe.probe_temp_owner(root, other)
        self.assertIn(f"owned by uid {self.euid}", problem or "")
        self.assertIn("neither root nor", problem or "")

    def test_a_root_owned_temp_directory_is_accepted(self):
        real = os.stat(tempfile.gettempdir())
        fake = os.stat_result(tuple(real)[:4] + (0,) + tuple(real)[5:])
        with mock.patch.object(os, "stat", return_value=fake):
            self.assertIsNone(probe.probe_temp_owner("/anything", 1000))

    def test_main_is_red_and_names_every_fact_when_the_environment_lacks_them(self):
        with mock.patch.object(probe, "problems", return_value=["first fact", "second fact"]):
            code, text = _run_main()
        self.assertEqual(code, 1)
        self.assertIn("RED", text)
        self.assertIn("first fact", text)
        self.assertIn("second fact", text)
        self.assertIn("NOT expected here", text)

    def test_no_temporary_directory_at_all_is_red_not_a_crash(self):
        """The reviewer's read-only sandbox: `tempfile.gettempdir()` raises FileNotFoundError."""
        with mock.patch.object(tempfile, "gettempdir", side_effect=FileNotFoundError(2, "No usable temporary directory")):
            self.assertEqual(len(probe.problems()), 1)
            self.assertIn("no usable temporary directory", probe.problems()[0])
            code, text = _run_main()
        self.assertEqual(code, 1)
        self.assertIn("temp none", text)

    def test_an_unwritable_temp_root_is_a_problem_not_a_crash(self):
        found = probe.problems(temp_root="/nonexistent-root-for-this-test")
        self.assertTrue(any("cannot create a directory" in line for line in found), found)


class NonPosixTests(unittest.TestCase):
    def test_off_posix_it_says_it_does_not_judge(self):
        with mock.patch.object(os, "name", "nt"):
            code, text = _run_main()
        self.assertEqual(code, 0)
        self.assertIn("NOT JUDGED", text)
        self.assertNotIn("GREEN", text)


if __name__ == "__main__":
    unittest.main()
