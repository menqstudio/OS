#!/usr/bin/env python3
"""Self-tests for tools/check_crypto_surface.py.

Each test builds a throwaway repository root on disk and runs the gate's own functions over
it, so nothing here asserts against the real tree: a test that passes only because this
repository happens to be clean would go green on a repository that is not.

The tests that matter are the ones that reconstruct the two defects the gate was written for:
`test_patch_level_fix_is_refused` is 2026-09-19's actual state (pin 46.0.3, three advisories
fixed in 46.0.5/6/7 waived under a major-bump excuse), and `test_pem_loader_is_refused` is the
future edit that would silently make four accepted HIGHs reachable.
"""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import tempfile
import unittest

import check_crypto_surface as gate


PIN = """\
jsonschema==4.25.1 \\
    --hash=sha256:aaaa
cryptography=={version} \\
    --hash=sha256:bbbb \\
    --hash=sha256:cccc
attrs==26.1.0 \\
    --hash=sha256:dddd
"""


class Fixture:
    """A minimal repository root: the pin, the waiver file, and any Python sources."""

    def __init__(self, stack: unittest.TestCase, version: str = "46.0.7"):
        self.root = pathlib.Path(tempfile.mkdtemp())
        stack.addCleanup(self._clean)
        (self.root / "engine").mkdir(parents=True)
        (self.root / ".github/supply-chain").mkdir(parents=True)
        self.pin(version)
        self.waivers([])
        self.rustsec(["RUSTSEC-2024-0413"], ["RUSTSEC-2024-0413"])
        # One file of the permitted surface, so the scan has something to read: a root with
        # no Python in it is RED now, and these fixtures are about the other rules.
        self.source("engine/runtime/sign.py", "from cryptography.hazmat.primitives.asymmetric "
                                              "import ed25519\n")

    def _clean(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def pin(self, version: str | None) -> None:
        text = "" if version is None else PIN.format(version=version)
        (self.root / gate.REQUIREMENTS).write_text(text, encoding="utf-8")

    def waivers(self, lines: list[str]) -> None:
        body = "# a comment line, ignored\n" + "".join(line + "\n" for line in lines)
        (self.root / gate.IGNORE_FILE).write_text(body, encoding="utf-8")

    def rustsec(self, audit: list[str], deny: list[str]) -> None:
        """The two homes of the RustSec waiver list."""
        (self.root / gate.CARGO_AUDIT_IGNORE).write_text(
            "# RustSec ids, one per line\n"
            + "".join(f"{identifier}  # a crate\n" for identifier in audit), encoding="utf-8")
        (self.root / gate.CARGO_DENY).write_text(
            "[advisories]\nyanked = \"deny\"\nignore = [\n"
            + "".join(f'    "{identifier}", # a crate\n' for identifier in deny) + "]\n",
            encoding="utf-8")

    def source(self, relative: str, body: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


class VersionKeyTests(unittest.TestCase):
    def test_compares_numerically_not_as_text(self):
        self.assertLess(gate.version_key("46.0.9"), gate.version_key("46.0.10"))
        self.assertLess(gate.version_key("46.0.7"), gate.version_key("48.0.1"))
        self.assertEqual(gate.version_key("46.0.7")[:2], gate.version_key("46.0.3")[:2])


class PinReadingTests(unittest.TestCase):
    def test_reads_the_pinned_version_past_the_hash_continuations(self):
        fixture = Fixture(self)
        self.assertEqual(gate.pinned_cryptography(fixture.root), "46.0.7")

    def test_no_pin_reads_as_none(self):
        fixture = Fixture(self)
        fixture.pin(None)
        self.assertIsNone(gate.pinned_cryptography(fixture.root))

    def test_an_unpinned_requirements_file_refuses_rather_than_passing(self):
        fixture = Fixture(self)
        fixture.pin(None)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused surface"])
        problems, pinned, count = gate.scan_waivers(fixture.root)
        self.assertIsNone(pinned)
        self.assertEqual(count, 1)
        self.assertTrue(any("names no `cryptography==` pin" in p for p in problems))


class WaiverParsingTests(unittest.TestCase):
    def test_reads_ids_the_way_the_workflow_does(self):
        fixture = Fixture(self)
        fixture.waivers(
            [
                "GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — bundled OpenSSL",
                "# a whole-line comment carrying fixed=1.0.0 is not an entry",
                "",
                "GHSA-g6cj-pr64-35w5  # fixed=50.0.0 — PKCS#7",
            ]
        )
        entries = gate.waived_entries(fixture.root)
        self.assertEqual(
            [(identifier, fixed) for _, identifier, fixed in entries],
            [("GHSA-537c-gmf6-5ccf", "48.0.1"), ("GHSA-g6cj-pr64-35w5", "50.0.0")],
        )

    def test_a_missing_ignore_file_is_no_waiver_rather_than_a_crash(self):
        fixture = Fixture(self)
        (fixture.root / gate.IGNORE_FILE).unlink()
        self.assertEqual(gate.waived_entries(fixture.root), [])


class WaiverFreshnessTests(unittest.TestCase):
    def test_a_fix_above_the_pin_is_the_legitimate_case(self):
        fixture = Fixture(self, version="46.0.7")
        fixture.waivers(
            [
                "GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — bundled OpenSSL, unused",
                "GHSA-m2h6-j472-rp4c  # fixed=49.0.0 — X.509, unused",
                "GHSA-g6cj-pr64-35w5  # fixed=50.0.0 — PKCS#7, unused",
            ]
        )
        problems, pinned, count = gate.scan_waivers(fixture.root)
        self.assertEqual((pinned, count), ("46.0.7", 3))
        self.assertEqual(problems, [])

    def test_patch_level_fix_is_refused(self):
        """2026-09-19's real state: pin 46.0.3, three fixes inside the same 46.0 line."""
        fixture = Fixture(self, version="46.0.3")
        fixture.waivers(
            [
                "PYSEC-2026-2141  # fixed=46.0.5 — HIGH",
                "PYSEC-2026-35  # fixed=46.0.6",
                "PYSEC-2026-36  # fixed=46.0.7",
            ]
        )
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 3, problems)
        for problem in problems:
            self.assertIn("PATCH release of the pinned 46.0.3", problem)

    def test_a_pin_that_reached_the_fix_kills_the_waiver(self):
        fixture = Fixture(self, version="49.0.0")
        fixture.waivers(["GHSA-m2h6-j472-rp4c  # fixed=49.0.0 — X.509, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("the waiver is dead", problems[0])

    def test_a_waiver_with_no_fixed_marker_is_refused(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-g6cj-pr64-35w5  # PKCS#7 EnvelopedData, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("records no `fixed=<version>`", problems[0])

    def test_a_bare_package_name_is_refused_because_pip_audit_would_waive_nothing(self):
        fixture = Fixture(self)
        fixture.waivers(["cryptography  # fixed=99.0.0 — waive the package"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("is not a GHSA / PYSEC / CVE id", problems[0])

    def test_a_cve_id_is_a_valid_advisory_id(self):
        fixture = Fixture(self)
        fixture.waivers(["CVE-2026-45447  # fixed=48.0.1 — PKCS7_verify, unused"])
        problems, _, _ = gate.scan_waivers(fixture.root)
        self.assertEqual(problems, [])


class SurfaceTests(unittest.TestCase):
    def test_the_ed25519_raw_surface_passes(self):
        fixture = Fixture(self)
        fixture.source(
            "engine/runtime/signing.py",
            "from cryptography.hazmat.primitives import serialization\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n"
            "def mint():\n"
            "    key = Ed25519PrivateKey.generate()\n"
            "    return key.private_bytes(\n"
            "        serialization.Encoding.Raw,\n"
            "        serialization.PrivateFormat.Raw,\n"
            "        serialization.NoEncryption(),\n"
            "    )\n",
        )
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_pem_loader_is_refused(self):
        fixture = Fixture(self)
        fixture.source(
            "bridge/sidecar.py",
            "from cryptography.hazmat.primitives.serialization import load_pem_private_key\n",
        )
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("load_pem_private_key", problems[0])
        self.assertIn("bridge/sidecar.py:1", problems[0])

    def test_an_x509_import_is_refused_and_names_the_advisories(self):
        fixture = Fixture(self)
        fixture.source("engine/verify.py", "from cryptography import x509\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("GHSA-m2h6-j472-rp4c", problems[0])

    def test_a_submodule_import_is_refused(self):
        fixture = Fixture(self)
        fixture.source("engine/p7.py", "import cryptography.hazmat.primitives.serialization.pkcs7\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("PKCS#7", problems[0])

    def test_a_loader_called_as_an_attribute_is_refused_without_any_import(self):
        fixture = Fixture(self)
        fixture.source(
            "engine/attr.py",
            "def read(serialization, blob):\n    return serialization.load_der_public_key(blob)\n",
        )
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("load_der_public_key", problems[0])

    def test_writing_pem_is_not_parsing_pem(self):
        """Encoding OUT touches no ASN.1 parser, so it is deliberately allowed."""
        fixture = Fixture(self)
        fixture.source(
            "engine/out.py",
            "from cryptography.hazmat.primitives import serialization\n"
            "def dump(key):\n"
            "    return key.public_bytes(\n"
            "        serialization.Encoding.PEM,\n"
            "        serialization.PublicFormat.SubjectPublicKeyInfo,\n"
            "    )\n",
        )
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_skipped_directories_are_not_scanned(self):
        fixture = Fixture(self)
        fixture.source(
            "node_modules/vendor/thing.py",
            "from cryptography import x509\n",
        )
        fixture.source(".venv/lib/other.py", "from cryptography import x509\n")
        self.assertEqual(gate.scan_surface(fixture.root), [])

    def test_a_file_that_will_not_parse_is_reported_rather_than_skipped(self):
        fixture = Fixture(self)
        fixture.source("engine/broken.py", "from cryptography import x509\ndef (:\n")
        problems = gate.scan_surface(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("will not parse", problems[0])


def run_gate(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = gate.main(list(argv))
    return code, out.getvalue()


class RustSecWaiverTests(unittest.TestCase):
    """Rule 3. The RustSec waivers are written in two files, each with a comment saying "keep
    in sync" with the other, and nothing read either."""

    IDS = ["RUSTSEC-2024-0413", "RUSTSEC-2024-0429"]

    def test_the_two_lists_as_one_set_is_green(self):
        fixture = Fixture(self)
        fixture.rustsec(self.IDS, list(reversed(self.IDS)))
        self.assertEqual(gate.scan_rustsec_waivers(fixture.root), ([], 2))

    def test_an_id_only_cargo_audit_waives_is_refused(self):
        fixture = Fixture(self)
        fixture.rustsec(self.IDS + ["RUSTSEC-2025-0081"], self.IDS)
        problems, _ = gate.scan_rustsec_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("cargo-audit-ignore.txt waives RUSTSEC-2025-0081 and "
                      ".github/supply-chain/deny.toml does not", problems[0])

    def test_an_id_only_cargo_deny_waives_is_refused(self):
        fixture = Fixture(self)
        fixture.rustsec(self.IDS, self.IDS + ["RUSTSEC-2025-0081"])
        problems, _ = gate.scan_rustsec_waivers(fixture.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("deny.toml waives RUSTSEC-2025-0081 and "
                      ".github/supply-chain/cargo-audit-ignore.txt does not", problems[0])

    def test_the_table_form_of_a_deny_entry_is_read(self):
        fixture = Fixture(self)
        fixture.rustsec(self.IDS, [])
        (fixture.root / gate.CARGO_DENY).write_text(
            '[advisories]\nignore = [\n  "RUSTSEC-2024-0413",\n'
            '  { id = "RUSTSEC-2024-0429", reason = "glib, unsound" },\n]\n', encoding="utf-8")
        self.assertEqual(gate.scan_rustsec_waivers(fixture.root), ([], 2))

    def test_the_ignore_file_is_read_the_way_the_workflow_reads_it(self):
        fixture = Fixture(self)
        (fixture.root / gate.CARGO_AUDIT_IGNORE).write_text(
            "# RUSTSEC-0000-0000 in a comment is not an entry\n\n"
            "  RUSTSEC-2024-0413   # atk\nRUSTSEC-2024-0429#glib\n", encoding="utf-8")
        self.assertEqual(gate.cargo_audit_waivers(fixture.root),
                         {"RUSTSEC-2024-0413", "RUSTSEC-2024-0429"})

    def test_a_missing_or_unparseable_copy_is_refused(self):
        for label, damage, needle in (
            ("no ignore file", lambda r: (r / gate.CARGO_AUDIT_IGNORE).unlink(),
             "cargo-audit-ignore.txt is missing"),
            ("no deny.toml", lambda r: (r / gate.CARGO_DENY).unlink(), "deny.toml is missing"),
            ("broken deny.toml", lambda r: (r / gate.CARGO_DENY).write_text(
                "[advisories\n", encoding="utf-8"), "deny.toml is not valid TOML"),
        ):
            with self.subTest(case=label):
                fixture = Fixture(self)
                damage(fixture.root)
                problems, _ = gate.scan_rustsec_waivers(fixture.root)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(needle, problems[0])

    def test_a_drifted_list_exits_one_and_says_which_rule(self):
        fixture = Fixture(self)
        fixture.rustsec(self.IDS, self.IDS[:1])
        code, said = run_gate("--root", str(fixture.root))
        self.assertEqual(code, 1)
        self.assertIn("RED: the RustSec waiver list is written twice and the two copies differ",
                      said)
        self.assertIn("Rule 3", said)

    def test_this_repositorys_two_lists_are_one_set(self):
        repo = pathlib.Path(gate.__file__).resolve().parents[1]
        problems, count = gate.scan_rustsec_waivers(repo)
        self.assertEqual(problems, [])
        self.assertEqual(count, len(gate.cargo_deny_waivers(repo)))


class NothingToCheckIsNotGreen(unittest.TestCase):
    """Rule 0. From an empty directory the gate printed "GREEN: ... 0 waived advisories each
    record a fix above the pinned (unpinned)" and exited 0; so did a renamed waiver file."""

    def test_an_empty_directory_is_red(self):
        with tempfile.TemporaryDirectory() as empty:
            code, said = run_gate("--root", empty)
        self.assertEqual(code, 1)
        self.assertIn("RED: this gate had nothing to check", said)
        for needle in ("pip-audit-ignore.txt is missing", "requirements-ci.txt is missing",
                       "no Python source was found"):
            self.assertIn(needle, said)
        self.assertNotIn("GREEN", said)

    def test_each_missing_input_is_red_on_its_own(self):
        for label, damage, needle in (
            ("waiver file renamed", lambda f: (f.root / gate.IGNORE_FILE).rename(
                f.root / ".github/supply-chain/pip-audit-ignore.txt.bak"),
             "pip-audit-ignore.txt is missing"),
            ("requirements gone", lambda f: (f.root / gate.REQUIREMENTS).unlink(),
             "requirements-ci.txt is missing"),
            ("no cryptography pin", lambda f: f.pin(None), "names no `cryptography==` pin"),
            ("no python at all", lambda f: (f.root / "engine/runtime/sign.py").unlink(),
             "no Python source was found"),
        ):
            with self.subTest(case=label):
                fixture = Fixture(self)
                code, _ = run_gate("--root", str(fixture.root))
                self.assertEqual(code, 0, "the fixture must be green before it is damaged")
                damage(fixture)
                code, said = run_gate("--root", str(fixture.root))
                self.assertEqual(code, 1, said)
                self.assertIn(needle, said)
                self.assertEqual(said.count("    - "), 1, said)

    def test_the_default_root_is_this_repository_whatever_the_cwd(self):
        """`--root` defaulted to the current directory, so where the shell stood decided
        which tree was judged -- and an empty one was judged clean."""
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as elsewhere:
            os.chdir(elsewhere)
            try:
                code, said = run_gate()
            finally:
                os.chdir(here)
        self.assertEqual(code, 0, said)
        # Proof that THIS repository was judged and not an empty directory: the gate names the
        # real pin and finds the real RustSec lists. It used to be "at least one cryptography
        # waiver", which stopped being true when T-165 took the fix and deleted all four.
        pinned = gate.pinned_cryptography(pathlib.Path(__file__).resolve().parents[1])
        self.assertTrue(pinned)
        self.assertIn(f"above the pinned {pinned};", said)
        self.assertRegex(said, r"; [1-9]\d* RustSec waiver\(s\) identical")


class ExitCodeTests(unittest.TestCase):
    def test_green_exits_zero(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        code, said = run_gate("--root", str(fixture.root))
        self.assertEqual(code, 0, said)
        self.assertIn("1 RustSec waiver(s) identical in cargo-audit-ignore.txt and deny.toml",
                      said)

    def test_a_dead_waiver_exits_one(self):
        fixture = Fixture(self, version="48.0.1")
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        self.assertEqual(gate.main(["--root", str(fixture.root)]), 1)

    def test_a_reached_surface_exits_one(self):
        fixture = Fixture(self)
        fixture.waivers(["GHSA-537c-gmf6-5ccf  # fixed=48.0.1 — unused"])
        fixture.source("engine/v.py", "from cryptography import x509\n")
        self.assertEqual(gate.main(["--root", str(fixture.root)]), 1)


if __name__ == "__main__":
    unittest.main()
