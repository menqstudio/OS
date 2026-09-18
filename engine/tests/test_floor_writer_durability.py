"""Crash-consistency for the authoritative floor state — the property B5 did NOT prove.

The Architect's ruling, in his words: *"manual creation of an inconsistent state only proves
corruption detection. That is still not crash-consistency evidence."* ``test_floor_writer.py``'s
§7 negative 11 writes a temp file by hand and shows the service ignores it — a true and different
statement. This file is about the other one.

And the distinction he asked to be kept in view: **one atomic rename is not automatically
crash-safe.** ``rename(2)`` is atomic with respect to other observers of the directory — no reader
ever sees a half-name — and that says nothing about what survives a power loss, which is decided by
whether the data reached the device before the rename did and whether the directory entry itself
was flushed after. Atomicity and durability are two properties and this file measures both:

1. **The syscall order, read from the kernel rather than from the source.** A real child process
   commits one state under ``strace``, and the trace must show, on the SAME file descriptor:
   ``openat`` a private temp in the final directory → ``write`` → ``fsync`` the temp → ``rename``
   over the document → ``fsync`` the DIRECTORY. Deleting either ``fsync`` from ``commit_state``
   makes this test red; that was checked by deleting each one.

2. **Process-level injected interruption.** A child advances the floor as fast as it can and is
   ``SIGKILL``-ed at a random point — a kill the process cannot catch, ordered by the kernel, with
   no cleanup path and no chance to finish a partial write. After every kill the store must read
   back as a COMPLETE document at a floor the writer actually attempted, the roster and the floors
   must agree, and the next advance must succeed from there. Never a torn document, never a
   half-state, and never a repair: the recovery path is that there is none.

A meta-control fails the test if the kills never landed inside a write window, because a suite
that killed the child before it started would be green and would have measured nothing.

``SIGKILL`` is the strongest interruption a process can be given and it is not a power cut. What it
proves is that no code path of this service can leave a partial document behind. What it cannot
prove is the device's write ordering under power loss; that is the ``fsync`` pair's job, and (1) is
the evidence that the pair is issued. Both halves are stated because either alone would be a
smaller claim wearing a bigger name.
"""

import json
import os
import pathlib
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import floor_writer as fw

LINUX_ONLY = "the Floor Writer is Linux-only in FW-1; Windows is FW-2 and is not built"
_LINUX = sys.platform == "linux"
INSTALL = "install-1"
DIGEST = "c" * 64
CALLER = (os.geteuid() + 1) if _LINUX else 0

#: The child does this many advances with nothing between them, so almost all of its wall time is
#: inside `commit_state`. A child that spent its time sleeping would be killed between commits and
#: the interesting window would never be sampled. The number is far more than any budget below can
#: finish, on purpose: the child must always be mid-loop when the kill arrives.
CHILD_ADVANCES = 20000
#: How many kills. Each is a separate process and a separate store state.
KILL_ROUNDS = 12

_CHILD = r'''
import json, pathlib, sys
sys.path.insert(0, {runtime!r})
import floor_writer as fw
config = fw.load_service_config({{fw.ENV_SERVICE_CONFIG: sys.argv[1]}})
task = sys.argv[2]
limit = int(sys.argv[3])
sys.stderr.write("ready\n"); sys.stderr.flush()
for head in range(1, limit + 1):
    fw.do_advance(config, task, head, {digest!r})
'''


def _durable_temp_root():
    """A directory on a REAL filesystem where one exists.

    ``/tmp`` is ``tmpfs`` on this box and on most CI images, and ``fsync`` on ``tmpfs`` is a
    no-op: measuring durability there would be measuring nothing. This prefers the first
    disk-backed candidate and RECORDS which filesystem the store actually sat on, because a
    durability claim that does not name its filesystem is not a measurement.
    """
    types = {}
    try:
        for line in pathlib.Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 3:
                types[parts[1]] = parts[2]
    except OSError:
        return tempfile.gettempdir(), "unknown"

    def fstype(path):
        best, kind = "", "unknown"
        for mount, name in types.items():
            if (path == mount or path.startswith(mount.rstrip("/") + "/")) and len(mount) > len(best):
                best, kind = mount, name
        return kind

    for candidate in ("/var/tmp", tempfile.gettempdir(), "/tmp"):
        if os.path.isdir(candidate) and os.access(candidate, os.W_OK):
            kind = fstype(os.path.realpath(candidate))
            if kind not in ("tmpfs", "ramfs"):
                return candidate, kind
    fallback = tempfile.gettempdir()
    return fallback, fstype(os.path.realpath(fallback))


@unittest.skipUnless(_LINUX, LINUX_ONLY)
class DurabilityFixture(unittest.TestCase):
    def setUp(self):
        base, self.fstype = _durable_temp_root()
        self._tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.marks_root = self.root / "marks"
        # `mkdir(parents=True, mode=...)` applies the mode to the LAST component only; the
        # intermediates take the process umask, which is 0o002 on this box and produces a
        # group-writable `marks/`. The ancestry rule refuses that — correctly — so the fixture
        # builds the chain the way a provisioned deployment has it.
        self.marks_root.mkdir(mode=0o755)
        (self.marks_root / INSTALL).mkdir(mode=0o700)
        self.config_path = self.root / "fw-config.json"
        self.config_path.write_text(json.dumps({
            "install_id": INSTALL, "marks_root": str(self.marks_root),
            "socket_path": str(self.root / "fw.sock"), "generation": 3,
            "peers": {fw.OP_GET: [CALLER], fw.OP_ADVANCE: [CALLER]}}), encoding="utf-8")
        self.config = fw.load_service_config({fw.ENV_SERVICE_CONFIG: str(self.config_path)})
        # Provisioning's first document, written the way provisioning writes it.
        fw.commit_state(self.config, {"install_id": INSTALL, "generation": 3,
                                      "roster": [], "floors": {}})

    def child_source(self):
        return _CHILD.format(runtime=str(ROOT / "runtime"), digest=DIGEST)


class SyscallOrder(DurabilityFixture):
    """(1) — the commit's durability barriers, read out of the kernel."""

    def setUp(self):
        super().setUp()
        if shutil.which("strace") is None:
            self.skipTest("strace is not installed, so the syscall order cannot be measured; "
                          "asserting it from the source would be reading, not measuring")

    def trace_one_commit(self):
        script = self.root / "commit_once.py"
        script.write_text(self.child_source(), encoding="utf-8")
        trace = self.root / "commit.trace"
        result = subprocess.run(
            ["strace", "-f", "-y", "-e", "trace=openat,write,fsync,rename,renameat,renameat2",
             "-o", str(trace), sys.executable, str(script), str(self.config_path),
             "task-1", "1"],
            capture_output=True, text=True, timeout=120)
        if result.returncode != 0 and not trace.exists():
            self.skipTest(f"strace could not attach (ptrace may be restricted): {result.stderr[:200]}")
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        return trace.read_text(encoding="utf-8", errors="replace")

    def test_the_commit_is_temp_write_fsync_rename_then_directory_fsync(self):
        lines = [line for line in self.trace_one_commit().splitlines()
                 if fw.STATE_FILE in line or "fsync(" in line]
        temp_name = f".{fw.STATE_FILE}.tmp"
        # The one file descriptor the temp file was opened on; `-y` prints the path it points at,
        # which is what lets the fsync be attributed rather than assumed.
        opened = [i for i, line in enumerate(lines)
                  if "openat(" in line and temp_name in line and "O_CREAT" in line]
        self.assertTrue(opened, f"no temp file was created in the marks directory:\n" +
                        "\n".join(lines[:40]))
        start = opened[0]
        wrote = [i for i in range(start, len(lines))
                 if lines[i].startswith(tuple("0123456789")) and "write(" in lines[i]
                 and temp_name in lines[i]]
        synced = [i for i in range(start, len(lines))
                  if "fsync(" in lines[i] and temp_name in lines[i]]
        renamed = [i for i in range(start, len(lines))
                   if re.search(r"rename(at2?)?\(", lines[i]) and temp_name in lines[i]
                   and fw.STATE_FILE in lines[i]]
        dir_synced = [i for i in range(start, len(lines))
                      if "fsync(" in lines[i] and temp_name not in lines[i]
                      and f"/{INSTALL}>" in lines[i]]
        self.assertTrue(wrote, "the payload was never written to the temp file")
        self.assertTrue(synced, "the temp file was never fsynced: the rename could then publish a "
                                "name whose data has not reached the device")
        self.assertTrue(renamed, "the document was never published by rename")
        self.assertTrue(dir_synced, "the marks DIRECTORY was never fsynced: after a power loss the "
                                    "new name itself can be the thing that is missing")
        self.assertLess(wrote[0], synced[0], "fsync must follow the write it is flushing")
        self.assertLess(synced[0], renamed[0],
                        "the data must be on the device BEFORE the name that publishes it")
        self.assertLess(renamed[0], dir_synced[0],
                        "the directory fsync must follow the rename it is making durable")

    def test_the_temp_file_is_created_in_the_final_directory(self):
        # A temp elsewhere could not be renamed atomically onto the document: rename across
        # filesystems is EXDEV, and a copy is not a publish.
        for line in self.trace_one_commit().splitlines():
            if f".{fw.STATE_FILE}.tmp" in line and "openat(" in line:
                self.assertIn(f"{INSTALL}/.{fw.STATE_FILE}.tmp", line)
                return
        self.fail("no temp file open was traced")


class KillInjection(DurabilityFixture):
    """(2) — a real process, killed by the kernel, mid-write, twelve times."""

    def run_until_killed(self, task, budget):
        script = self.root / "advance_loop.py"
        script.write_text(self.child_source(), encoding="utf-8")
        child = subprocess.Popen(
            [sys.executable, str(script), str(self.config_path), task, str(CHILD_ADVANCES)],
            stderr=subprocess.PIPE)
        try:
            child.stderr.readline()          # "ready": the config is loaded, the loop is running
            time.sleep(budget)
            child.send_signal(signal.SIGKILL)
        finally:
            child.wait(timeout=30)
            child.stderr.close()
        self.assertEqual(child.returncode, -signal.SIGKILL,
                         "the child finished on its own; the kill never landed in a write window")

    def test_every_kill_leaves_a_complete_document_at_a_head_the_writer_attempted(self):
        random.seed(20260831)
        interrupted = 0
        for round_number in range(KILL_ROUNDS):
            # A FRESH task each round: replaying head 1 against a floor already at N is a
            # `stale_floor` refusal, so a reused id would kill a child that had already died of
            # its own accord and the round would measure a crash that never happened.
            task = f"task-{round_number}"
            with self.subTest(round=round_number):
                before, _ = fw.read_floor(self.config, task)
                self.run_until_killed(task, random.uniform(0.02, 0.20))

                # The document must PARSE and validate under the service's own loader. A torn
                # write shows up here, as mark_corrupt, and nothing else in this file would need
                # to be true for that to be the finding.
                document = fw.load_state(self.config)
                head, digest = fw.read_floor(self.config, task)

                self.assertEqual(sorted(document["roster"]), sorted(document["floors"]),
                                 "roster and floors disagree after a kill: a half-state")
                self.assertEqual(document["generation"], self.config.generation)
                self.assertGreaterEqual(head, before, "the floor went BACKWARDS across a crash")
                self.assertLessEqual(head, CHILD_ADVANCES,
                                     "the floor is above anything the writer attempted")
                if head:
                    self.assertEqual(digest, DIGEST)
                if head < CHILD_ADVANCES:
                    interrupted += 1

                # Usable, not merely readable: the next advance must succeed from exactly here.
                reply = fw.handle(
                    {"op": fw.OP_ADVANCE, "protocol": fw.FLOOR_PROTOCOL, "task_id": task,
                     "head_sequence": head + 1, "evidence_head_sha256": DIGEST},
                    config=self.config, peer_uid=CALLER)
                self.assertEqual(reply.get("outcome"), fw.OUTCOME_ADVANCED, reply)
                self.assertEqual(reply["head_sequence"], head + 1)

        self.assertEqual(interrupted, KILL_ROUNDS,
                         "no kill landed before the child finished its whole loop; the window "
                         f"this test exists to sample was never sampled (store filesystem: "
                         f"{self.fstype})")

    def test_a_temp_file_left_by_a_kill_is_never_merged_into_the_document(self):
        # The no-auto-heal rule, on debris a real kill produced rather than debris written by
        # hand. Whatever the killed child left behind, the authoritative document is the one the
        # last completed rename published, and a later advance builds on THAT.
        self.run_until_killed("task-debris", 0.05)
        head, _ = fw.read_floor(self.config, "task-debris")
        debris = self.config.marks_dir / f".{fw.STATE_FILE}.tmp"
        if debris.exists():
            # Poison it: if anything ever read it, the roster below would carry the ghost.
            debris.write_text(json.dumps({
                "install_id": INSTALL, "generation": 3, "roster": ["task-debris", "ghost"],
                "floors": {"task-debris": {"head_sequence": 10 ** 9,
                                           "evidence_head_sha256": "d" * 64}}}), encoding="utf-8")
        self.assertEqual(fw.read_floor(self.config, "task-debris")[0], head)
        self.assertNotIn("ghost", fw.known_tasks(self.config))
        self.assertTrue(fw.NEVER_HEAL_FROM_DIRECTORY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
