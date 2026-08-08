"""The evidence store holds more than one kind of evidence-recorder statement.

`artifact_type` names the AUTHORITY that may sign a document, not its shape:
`bro_signature.ARTIFACT_AUTHORITY` maps `evidence-event` to the evidence-recorder, and
the recorder signs two different true statements under it — a chain event, and an
execution receipt (`tools/bro_run_receipt.run_and_sign`, verified by
`bro_receipt.verify_receipt` as an `evidence-event` deliberately, because that is the
authority a receipt must carry).

The durable runtime keeps both in the same flat store. `bro_evidence._scan_events` read
the artifact type as if it were a shape, so the governance read surface
(`read_chain` / `read_chains`) raised "unexpected shape" on the first receipt it met and
was unusable on any real store. The receipt was not mislabelled; the reader was too
narrow. These tests hold the reader to that.

The receipts here are produced by the REAL producer against a real git worktree, not by
a hand-written dict: a fixture that invents the shape would keep passing on the day the
producer changed it.

`StoreCustodyTests` at the foot of this file covers the other thing the store has to get
right about being shared: WHO may reach it. `brops_evidence_store._harden_dir` kept both
halves of that — the 0700 creation and the world-accessible refusal — inside
`if os.name == "posix"`, so on Windows the store was created with whatever it inherited from
its parent and nothing checked it afterwards. Those tests give the same verdict on both
platforms, because a rule that is enforced on one is not a rule.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_evidence import EvidenceError, read_chain, read_chains
import brops_evidence_store as store_module
from brops_evidence_store import EvidenceStore, EvidenceStoreError
from bro_run_receipt import run_and_sign
from bro_signature import load_trusted_keys
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin
from test_orchestration_runtime import AGENT, build_evidence

AUTHORITIES = ["operator-root", "issuer", "evidence-recorder", "builder",
               "verifier", "release"]
RUN_CMD = [sys.executable, "-c", "print('ok')"]


class SharedEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = pathlib.Path(self.temporary.name)
        self.store = base / "evidence"
        self.store.mkdir()
        self.keys = {a: generate_key(a, f"dev-{a}", False) for a in AUTHORITIES}
        use_operator_pin(self, self.keys["operator-root"]["public_key"])
        registry_root = base / "registry"
        (registry_root / "config").mkdir(parents=True)
        self.now = int(time.time())
        (registry_root / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), self.now - 60, 86400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(registry_root)

    def clean_repository(self) -> pathlib.Path:
        """A committed, clean worktree — `run_and_sign` refuses to attest a dirty one."""
        clean = pathlib.Path(self.temporary.name) / f"repo-{len(list(pathlib.Path(self.temporary.name).iterdir()))}"
        (clean / "tests").mkdir(parents=True)
        shutil.copy(ROOT / "tests" / "catalog.json", clean / "tests" / "catalog.json")
        for args in (["init", "-q"], ["config", "user.email", "t@e.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(clean), *args], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clean), "commit", "-qm", "init"],
                       check=True, capture_output=True)
        return clean

    def drop_receipt(self, task_id: str) -> str:
        """One real execution receipt, in the same store as the chain."""
        document, _ = run_and_sign(RUN_CMD, key=self.keys["evidence-recorder"],
                                   task_id=task_id, root=self.clean_repository(),
                                   runner_id="runner", now=self.now)
        receipt_id = document["payload"]["receipt_id"]
        (self.store / f"{receipt_id}.json").write_text(json.dumps(document), encoding="utf-8")
        return receipt_id

    # --- the reader must see past a receipt, and only past a receipt ----------------

    def test_a_receipt_sharing_the_store_does_not_break_the_chain_read(self) -> None:
        ids = build_evidence(self.store, self.keys, "task-shared", 2)
        self.drop_receipt("task-shared")
        chain = read_chain(self.store, "task-shared", self.trusted)
        self.assertEqual([event["event_id"] for event in chain], ids)

    def test_the_receipt_is_not_smuggled_into_the_chain_as_an_event(self) -> None:
        """Skipping it must mean skipping it: a receipt is not a chain event, and a
        reader that counted it would break the head anchor it is checked against."""
        build_evidence(self.store, self.keys, "task-notevent", 2)
        receipt_id = self.drop_receipt("task-notevent")
        chain = read_chain(self.store, "task-notevent", self.trusted)
        self.assertEqual(len(chain), 2)
        self.assertNotIn(receipt_id, [event["event_id"] for event in chain])

    def test_many_chains_read_in_one_pass_survive_receipts_for_each(self) -> None:
        expected = {}
        for task_id in ("task-multi-a", "task-multi-b"):
            expected[task_id] = build_evidence(self.store, self.keys, task_id, 2)
            self.drop_receipt(task_id)
        chains = read_chains(self.store, list(expected), self.trusted)
        self.assertEqual({task: [event["event_id"] for event in events]
                          for task, events in chains.items()}, expected)

    def test_a_receipt_for_an_unread_task_is_still_ignored(self) -> None:
        build_evidence(self.store, self.keys, "task-only", 2)
        self.drop_receipt("task-other")
        self.assertEqual(len(read_chain(self.store, "task-only", self.trusted)), 2)

    # --- everything that is NOT a receipt is still a hard error ---------------------

    def test_a_document_claiming_to_be_an_event_in_neither_shape_is_refused(self) -> None:
        """Widening the reader must not become "skip anything unfamiliar": that is the
        silent truncation the anchor exists to prevent.

        This document has no `sequence` at all, which is what makes the field-set gate
        load-bearing rather than merely early: without it the scan reaches straight past
        the shape it never checked and dies indexing a field that is not there — an
        unhandled KeyError where a refusal belongs.
        """
        build_evidence(self.store, self.keys, "task-odd", 2)
        payload = {
            "artifact_type": "evidence-event",
            "key_id": self.keys["evidence-recorder"]["key_id"],
            "task_id": "task-odd", "event_id": "task-odd-x1",
            "surprise": "a field neither shape has",
        }
        (self.store / "task-odd-x1.json").write_text(
            json.dumps(sign_payload(self.keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            read_chain(self.store, "task-odd", self.trusted)
        self.assertIn("unexpected shape", str(caught.exception))

    def test_an_event_disguised_as_a_receipt_cannot_shorten_the_chain(self) -> None:
        """The shape is read before the signature, so rewriting an event into receipt
        shape does make the scan step over it. It cannot forge a shorter history: the
        chain still has to reproduce the signed head's count and final hash."""
        ids = build_evidence(self.store, self.keys, "task-hide", 2)
        receipt_shape = json.loads(
            (self.store / f"{self.drop_receipt('task-hide')}.json").read_text(encoding="utf-8"))
        receipt_shape["payload"]["task_id"] = "task-hide"
        (self.store / f"{ids[-1]}.json").write_text(json.dumps(receipt_shape), encoding="utf-8")
        with self.assertRaises(EvidenceError) as caught:
            read_chain(self.store, "task-hide", self.trusted)
        self.assertIn("incomplete", str(caught.exception))

    def test_a_receipt_shaped_document_that_is_not_signed_is_not_a_way_in(self) -> None:
        """A receipt is skipped because it is another statement, not because skipping is
        safe: it never becomes part of the chain, signed or not."""
        ids = build_evidence(self.store, self.keys, "task-unsigned", 2)
        document = json.loads(
            (self.store / f"{self.drop_receipt('task-unsigned')}.json").read_text(encoding="utf-8"))
        document["signature"] = "00" * 64
        (self.store / "rcpt-unsigned.json").write_text(json.dumps(document), encoding="utf-8")
        chain = read_chain(self.store, "task-unsigned", self.trusted)
        self.assertEqual([event["event_id"] for event in chain], ids)


class StoreCustodyTests(unittest.TestCase):
    """Design §4.0: shared with a second dedicated principal, never with a login identity.

    Every test here asserts the SAME property on Windows and POSIX. That is the finding: the
    creation mode and the world-accessible refusal both sat inside `if os.name == "posix"`, so
    on Windows the store inherited its parent's ACL — under a volume root or `C:\\ProgramData`
    that includes `BUILTIN\\Users` — and no later check ever looked. A check that returns early
    on a platform is indistinguishable from no check.

    Where a configuration cannot be built on this host, the test SKIPS with the reason. None of
    them may pass because the ambient account happens to be configured favourably: the Windows
    cases stamp the descriptor they need onto a directory this process owns, and report the
    Win32 error if that is refused.
    """

    def setUp(self) -> None:
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="bro-store-custody-")).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    # ---- creation ---------------------------------------------------------------------

    def test_a_created_store_is_private_to_its_owner(self) -> None:
        """`mkdir` states who may reach the store, on both platforms.

        POSIX has always said 0700. Windows said nothing at all: `mkdir` there takes no mode
        and the new directory simply inherits its parent's ACL. The Windows assertion is made
        by reading the descriptor back as SDDL — a different route than the ACE walk in the
        code under test, so the test cannot be fooled by the same mistake twice.
        """
        store = EvidenceStore(self.base / "created")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(store.root).st_mode), 0o700)
            return
        sddl = _dacl_sddl(self, store.root)
        self.assertTrue(sddl.startswith("D:P"),
                        f"the store DACL is not protected from inheritance: {sddl}")
        for text, name in _WORLD_SIDS:
            self.assertNotIn(f";;;{_SDDL_ALIASES[text]})", sddl,
                             f"the created store grants access to {name}: {sddl}")

    # ---- validation of a store that already exists --------------------------------------

    def test_a_store_reachable_by_every_login_identity_is_refused(self) -> None:
        """READ access is enough to refuse — the contents are the evidence.

        POSIX asks `mode & S_IRWXO`, so 0704 (other: read+execute, no write) must refuse.
        Windows is given the same thing: FILE_GENERIC_READ for Everyone. Same verdict, and
        for the same stated reason, on both.
        """
        directory = self.base / "worldly"
        directory.mkdir()
        if os.name == "posix":
            os.chmod(directory, 0o704)
        else:
            _apply_dacl(self, directory,
                        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)"
                        "(A;OICI;0x1200a9;;;WD)", expect="Everyone")
        with self.assertRaises(EvidenceStoreError) as caught:
            EvidenceStore(directory)
        message = str(caught.exception)
        self.assertIn(str(directory), message)
        if os.name == "nt":
            self.assertIn("Everyone", message)
            self.assertIn("S-1-1-0", message)
        else:
            self.assertIn("world-accessible", message)

    def test_a_store_shared_with_a_second_named_principal_is_still_admitted(self) -> None:
        """The store is SUPPOSED to be shared — the supervisor writes it, the signer reads it.

        A refusal that fired on any second principal would be a different rule from the one
        design §4.0 asks for, and would push every real deployment back to one identity. POSIX
        says that with a group (0770); Windows says it with an ACE for a named principal. The
        SID used here is a real, well-formed, non-well-known account SID that resolves to
        nothing on this host — which is the point: it stands for "some named account", and the
        rule must let it through without the test depending on which accounts exist.
        """
        directory = self.base / "shared"
        directory.mkdir()
        if os.name == "posix":
            os.chmod(directory, 0o770)
        else:
            _apply_dacl(self, directory,
                        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)"
                        "(A;OICI;FA;;;S-1-5-21-1111111111-2222222222-3333333333-1099)")
        EvidenceStore(directory)  # must NOT raise

    def test_a_store_private_to_this_account_is_admitted(self) -> None:
        """...and the rule must not be a blanket ban either.

        An ordinary directory this process just created is the common case; if it refused,
        the check would be noise rather than a custody statement.
        """
        directory = self.base / "private"
        directory.mkdir()
        if os.name == "posix":
            os.chmod(directory, 0o700)
        EvidenceStore(directory)  # must NOT raise

    # ---- no platform is exempt ----------------------------------------------------------

    def test_an_uninterrogable_platform_refuses_on_creation(self) -> None:
        """The dispatch is patched at `brops_evidence_store.platform_name`, not at `os.name`:
        patching the latter also re-points `pathlib.Path` at the wrong flavour, so the test
        would fail for a reason that is not the one under test."""
        with unittest.mock.patch.object(store_module, "platform_name",
                                        lambda: "themythicalos"):
            with self.assertRaises(EvidenceStoreError) as caught:
                EvidenceStore(self.base / "elsewhere")
        self.assertIn("custody cannot be established on themythicalos",
                      str(caught.exception))

    def test_an_uninterrogable_platform_refuses_on_validation(self) -> None:
        """The defect was a silent return, so both arms of the branch are pinned.

        Fixing only the creation arm would leave an existing store — the case a deployment is
        actually in after its first run — validated by nothing at all.
        """
        directory = self.base / "already-there"
        directory.mkdir()
        with unittest.mock.patch.object(store_module, "platform_name",
                                        lambda: "themythicalos"):
            with self.assertRaises(EvidenceStoreError) as caught:
                EvidenceStore(directory)
        self.assertIn("an unchecked store is not a protected store", str(caught.exception))


# --- Windows helpers, written against the Win32 API directly -----------------------------
# Deliberately NOT routed through `bro_custody`: a test that establishes and reads back its
# premise using the code under test cannot detect that code answering the wrong question.

#: The SDDL alias each world SID is printed as, so the created-store assertion can look for
#: it in the descriptor string. Keyed by SID text to stay aligned with `bro_custody`.
_SDDL_ALIASES = {
    "S-1-1-0": "WD",
    "S-1-5-11": "AU",
    "S-1-5-4": "IU",
    "S-1-5-2": "NU",
    "S-1-5-7": "AN",
    "S-1-5-32-545": "BU",
    "S-1-5-32-546": "BG",
    "S-1-5-32-547": "PU",
}
_WORLD_SIDS = (
    ("S-1-1-0", "Everyone"),
    ("S-1-5-11", "Authenticated Users"),
    ("S-1-5-4", "INTERACTIVE"),
    ("S-1-5-2", "NETWORK"),
    ("S-1-5-7", "ANONYMOUS LOGON"),
    ("S-1-5-32-545", "BUILTIN\\Users"),
    ("S-1-5-32-546", "BUILTIN\\Guests"),
    ("S-1-5-32-547", "BUILTIN\\Power Users"),
)


def _advapi():
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    return advapi32


def _dacl_sddl(test_case, path) -> str:
    """The directory's DACL as an SDDL string, read independently of `bro_custody`."""
    import ctypes
    from ctypes import wintypes

    advapi32 = _advapi()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), 1, 0x4, None, None, None, None, ctypes.byref(descriptor))
    if status != 0:
        test_case.skipTest(
            f"cannot read the DACL of {path} (GetNamedSecurityInfo error {status}), so the "
            "Windows custody of a created store is NOT covered on this host")
    printed = wintypes.LPWSTR()
    if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 0x4, ctypes.byref(printed), None):
        test_case.skipTest(
            f"cannot render the DACL of {path} as SDDL (error {ctypes.get_last_error()}), so "
            "the Windows custody of a created store is NOT covered on this host")
    return printed.value


def _apply_dacl(test_case, path, sddl: str, expect: str | None = None) -> None:
    """Stamp an explicit protected DACL on a directory this process owns, or skip saying why.

    ``expect`` is a principal name that must appear in the directory's ACL afterwards,
    read back independently. Pass it whenever the test's premise IS the ACE — otherwise
    a host that quietly declines the change produces a failure that reads like a defect
    in the rule.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = _advapi()
    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        raise AssertionError(
            f"cannot build a descriptor from {sddl!r} (error {ctypes.get_last_error()})")
    dacl = ctypes.c_void_p()
    present = wintypes.BOOL()
    defaulted = wintypes.BOOL()
    if not advapi32.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
        raise AssertionError(f"no DACL in the descriptor built from {sddl!r}")
    status = advapi32.SetNamedSecurityInfoW(
        str(path), 1, 0x4 | 0x80000000, None, None, dacl, None)
    if status != 0:
        test_case.skipTest(
            f"cannot set the DACL of {path} to {sddl!r} (SetNamedSecurityInfo error "
            f"{status}); this host cannot construct the configuration under test, so it is "
            "NOT covered here")
    if expect is not None:
        # Read it back with a tool that is not the code under test, and not the call that
        # wrote it. A zero status is the API saying it accepted the request, not the
        # filesystem saying the request survived — and a test whose premise is unverified
        # reports "the rule did not fire" when the truth may be "the rule was never given
        # anything to fire on". That distinction is the whole subject of this module.
        landed = subprocess.run(["icacls", str(path)], capture_output=True, text=True).stdout
        if expect not in landed:
            test_case.skipTest(
                f"the DACL did not survive on this host: {expect!r} is absent from icacls "
                f"output after setting {sddl!r}. The configuration under test could not be "
                f"constructed, so it is NOT covered here.\n{landed.strip()[:600]}")


if __name__ == "__main__":
    unittest.main()
