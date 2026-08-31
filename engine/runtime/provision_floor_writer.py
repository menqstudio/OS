#!/usr/bin/env python3
"""Provision the Floor Writer — FW-1, Linux, root. The half of §1.10 that did not exist.

``floor_writer.py`` VALIDATES a provisioning generation and SERVES it with every reply; until
this module there was nothing that **minted** one, so ``config/spec-conformance.json`` recorded
§1.10 as ``partial`` with the words *"the number is one an operator writes into the TCB-owned
config by hand"*. A number a procedure produces is not a mechanism, and B6 is that gap.

What this writes, and why each piece cannot be left to the service or to the caller:

* **The marks store** ``<marks_root>/<install_id>/``, owned by the Floor Writer principal, mode
  ``0700``. The service REFUSES to start unless this is true (``require_private_directory``), and
  it cannot make it true itself: a process cannot give itself a directory whose parent it may not
  write. Provisioning is the only party that can, which is why it is a separate, root-only path.
* **The first authoritative document** ``floor-state.json``, empty roster, empty floors, carrying
  the generation. §4.2: a floor is not client-bootstrappable — and it is not service-bootstrappable
  at start either, so that "no state" is never read as "empty state".
* **The socket directory**, owned by the Floor Writer principal, group the caller group, mode
  ``0750``. §1.7: **the directory IS the server authentication** — a directory no other runtime
  principal may write is one in which no other principal can replace the endpoint. Group execute
  so the caller can traverse; group write withheld, because that is the whole property.
* **The TCB-owned config**, ``root:root`` mode ``0644`` in a root-owned directory. The install
  scope and the per-op allowlist are exactly the values a service account must not be able to
  rewrite; if the Floor Writer could edit its own allowlist, the allowlist would be its opinion.
* **The generation**, minted here and only here: the previous config's value plus one, or 1 when
  there is none. It never decreases — a decreasing generation would make a re-provisioned floor
  look OLDER than the one it replaced, which is the confusion §1.10 exists to remove.

**Re-provisioning discards floors, visibly.** ``--reprovision`` writes a FRESH empty state under a
NEW generation, and the receipt names every task id it dropped. That is §1.10's *"visibly new
rather than silently empty"*: a client that kept a floor from generation N sees generation N+1 in
every reply. It does not close **O-5** — nothing here is signed from outside the machine, so a
restore of the whole store, generation included, is still indistinguishable from a first sighting.
That is stated in §1.10 itself and is not fixed by this module.

**What this does NOT do**, so no reader takes the file for more than it is:

* it does not create OS accounts. The Floor Writer account and the caller group are the machine
  administrator's, made once, outside any tree that a compromise of this repository could reach;
* it does not register a service manager unit. Starting the service is ``run_floor_writer.py``
  under whatever supervises it;
* it is Linux-only, like everything in FW-1. Windows provisioning is FW-2 and mirrors
  ``provision/src/audit_signer.rs``, which does not exist here.

Exit codes: 2 configuration, 3 platform, 4 custody. There is no exit 0 path that has not also
passed the readback below — a provisioner that reports success from its intentions rather than
from the filesystem is how a deployment comes up looking provisioned.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pathlib
import pwd
import stat
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import floor_writer

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_PLATFORM = 3
EXIT_CUSTODY = 4

#: The store directory: the Floor Writer principal and nobody else (§1.2, and what
#: ``require_private_directory`` demands at start).
MARKS_DIR_MODE = 0o700
#: The authoritative document: readable and writable by its owner alone.
STATE_FILE_MODE = 0o600
#: §1.7 / B4. Group execute so the caller can TRAVERSE to the socket; group write withheld,
#: because a directory the caller can write is one in which it can replace the endpoint.
SOCKET_DIR_MODE = floor_writer.SOCKET_DIR_MODE
#: The config is the TCB's statement to the service. World-readable is deliberate — there is
#: nothing secret in it — and not writable by anyone but root is the entire point.
CONFIG_MODE = 0o644
#: A parent that another principal can write lets them rename the whole directory aside, which
#: makes the child's own mode irrelevant. Checked for every parent this module writes into.
_OTHER_WRITE = stat.S_IWGRP | stat.S_IWOTH


class ProvisionError(Exception):
    """A refusal, carrying the exit code it leaves with. Every early return here is an error."""

    def __init__(self, code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def require_linux() -> None:
    if sys.platform != "linux":
        raise ProvisionError(
            EXIT_PLATFORM,
            f"the Floor Writer is Linux-only in FW-1 (SO_PEERCRED peer authentication); this "
            f"platform is {sys.platform!r}. Windows provisioning is FW-2 and is not built")


def require_root(euid: Optional[int] = None) -> None:
    """Root, because everything here is an ownership or a mode that only root can set.

    A non-root provisioner could create the paths and would silently leave them owned by itself,
    which is the deployment the whole task exists to remove: the party that runs the completion
    owning the state that polices it.
    """
    effective = os.geteuid() if euid is None else euid
    if effective != 0:
        raise ProvisionError(
            EXIT_CONFIG,
            f"provisioning must run as root; this process is uid {effective}. The store, the "
            "socket directory and the config are owned by principals this process is not, and a "
            "provisioner that cannot set ownership would leave every path owned by itself")


def resolve_user(name: str) -> Tuple[int, int]:
    """``(uid, gid)`` for a name or a numeric id. An unknown principal is a refusal, not a create."""
    try:
        entry = pwd.getpwuid(int(name)) if name.isdigit() else pwd.getpwnam(name)
    except (KeyError, ValueError) as exc:
        raise ProvisionError(
            EXIT_CONFIG,
            f"no such user {name!r}: the Floor Writer account is the machine administrator's to "
            "create, deliberately outside this tree") from exc
    return entry.pw_uid, entry.pw_gid


def resolve_group(name: str) -> Tuple[int, List[str]]:
    """``(gid, members)``. The members are recorded in the receipt: everyone who can TRAVERSE to
    the endpoint, which is a different and wider set than everyone the allowlist admits."""
    try:
        entry = grp.getgrgid(int(name)) if name.isdigit() else grp.getgrnam(name)
    except (KeyError, ValueError) as exc:
        raise ProvisionError(EXIT_CONFIG, f"no such group {name!r}") from exc
    return entry.gr_gid, sorted(entry.gr_mem)


def group_members(gid: int, members: List[str]) -> set:
    """Every uid in the group, by supplementary membership OR by primary gid.

    ``grp`` lists only the supplementary members; a user whose PRIMARY group is this one does not
    appear there and can still traverse. Reading only the first list is how a reachability check
    reports an unreachable service as fine.
    """
    uids = set()
    for name in members:
        try:
            uids.add(pwd.getpwnam(name).pw_uid)
        except KeyError:
            continue
    for entry in pwd.getpwall():
        if entry.pw_gid == gid:
            uids.add(entry.pw_uid)
    return uids


# ---------------------------------------------------------------------------
# §1.10 — the generation, minted here and only here
# ---------------------------------------------------------------------------


def read_previous_generation(config_path: pathlib.Path) -> int:
    """The generation the existing config carries, or 0 when there is no config yet.

    An unreadable or unparseable existing config is a REFUSAL rather than a 0: overwriting it
    would mint generation 1 over a store that may be at 9, and the whole value of the number is
    that it never goes backwards.
    """
    if not config_path.exists():
        return 0
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProvisionError(
            EXIT_CONFIG,
            f"an existing Floor Writer config {config_path} is present and unreadable: {exc}. "
            "Refusing rather than minting generation 1 over a store whose generation is unknown"
        ) from exc
    previous = document.get("generation") if isinstance(document, dict) else None
    if isinstance(previous, bool) or not isinstance(previous, int) or previous < 1:
        raise ProvisionError(
            EXIT_CONFIG,
            f"the existing Floor Writer config {config_path} carries no usable generation; a new "
            "one cannot be minted above a number that is not there")
    return previous


def mint_generation(config_path: pathlib.Path) -> int:
    """§1.10. Previous + 1, or 1. Monotonic by construction — there is no argument to override it,
    because an operator-supplied generation is exactly the hand-written number B6 removes."""
    return read_previous_generation(config_path) + 1


# ---------------------------------------------------------------------------
# The plan — every fact resolved and checked before a single byte is written
# ---------------------------------------------------------------------------


class ProvisionPlan:
    """What will be written, resolved and validated. Building it touches nothing."""

    def __init__(self, install_id: str, service_uid: int, service_gid: int, caller_gid: int,
                 caller_group_members: set, marks_root: pathlib.Path, socket_path: pathlib.Path,
                 config_path: pathlib.Path, peers: Mapping[str, frozenset], generation: int,
                 reprovision: bool) -> None:
        self.install_id = install_id
        self.service_uid = service_uid
        self.service_gid = service_gid
        self.caller_gid = caller_gid
        self.caller_group_members = set(caller_group_members)
        self.marks_root = marks_root
        self.socket_path = socket_path
        self.config_path = config_path
        self.peers = {op: frozenset(uids) for op, uids in peers.items()}
        self.generation = generation
        self.reprovision = reprovision

    @property
    def marks_dir(self) -> pathlib.Path:
        return self.marks_root / self.install_id

    @property
    def state_path(self) -> pathlib.Path:
        return self.marks_dir / floor_writer.STATE_FILE

    @property
    def socket_dir(self) -> pathlib.Path:
        return self.socket_path.parent

    def config_document(self) -> Dict[str, Any]:
        return {
            "install_id": self.install_id,
            "marks_root": str(self.marks_root),
            "socket_path": str(self.socket_path),
            "generation": self.generation,
            "peers": {op: sorted(uids) for op, uids in sorted(self.peers.items())},
        }


def _parse_peers(pairs: List[str], service_uid: int) -> Dict[str, frozenset]:
    """``--peer <op>=<user|uid>``, repeated. Every refusal here is a boundary, not a typo check."""
    peers: Dict[str, set] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ProvisionError(EXIT_CONFIG, f"--peer expects <op>=<user|uid>, got {pair!r}")
        op, who = pair.split("=", 1)
        if op not in floor_writer.FW1_OPS:
            raise ProvisionError(
                EXIT_CONFIG,
                f"--peer names op {op!r}; FW-1 serves {' and '.join(floor_writer.FW1_OPS)}. "
                f"{floor_writer.OP_SCOPE_PIN} is FW-3 and this service refuses it by name")
        uid, _gid = resolve_user(who)
        if uid == 0:
            raise ProvisionError(
                EXIT_CONFIG,
                "root must not be on a peer allowlist: root can rewrite the store directly, so "
                "admitting it on the wire advertises a boundary that is not there")
        if uid == service_uid:
            raise ProvisionError(
                EXIT_CONFIG,
                f"uid {uid} is the Floor Writer's own principal and must not be its own caller. "
                "A service that may advance its own floor is A-01 restored inside the fix")
        peers.setdefault(op, set()).add(uid)
    for op in floor_writer.FW1_OPS:
        if not peers.get(op):
            raise ProvisionError(
                EXIT_CONFIG,
                f"no --peer given for {op!r}; §1.8 requires a list PER OP, and an empty list "
                "refuses every caller, which is a misconfiguration rather than a posture")
    return {op: frozenset(uids) for op, uids in peers.items()}


def build_plan(args: argparse.Namespace) -> ProvisionPlan:
    if not floor_writer._INSTALL_ID.fullmatch(args.install_id):
        raise ProvisionError(
            EXIT_CONFIG,
            f"install id {args.install_id!r} is not an identifier; it becomes a directory name "
            "under the marks root, so a value carrying a separator addresses another store")
    service_uid, service_gid = resolve_user(args.service_user)
    if service_uid == 0:
        raise ProvisionError(
            EXIT_CONFIG,
            "the Floor Writer must not run as root. A root service can write every path it is "
            "supposed to be constrained by, which makes 'a distinct principal' a word rather "
            "than a boundary")
    caller_gid, members = resolve_group(args.caller_group)
    peers = _parse_peers(args.peer, service_uid)

    reachable = group_members(caller_gid, members)
    admitted = set().union(*peers.values())
    unreachable = sorted(admitted - reachable)
    if unreachable:
        raise ProvisionError(
            EXIT_CONFIG,
            f"uid(s) {unreachable} are on an allowlist but are not in the caller group "
            f"{args.caller_group}: the socket directory is mode {SOCKET_DIR_MODE:04o}, so they "
            "cannot traverse to the endpoint and would be refused by the filesystem before the "
            "allowlist ever ran. A provisioning that produces an unreachable service is a "
            "misconfiguration, not a posture")
    config_path = pathlib.Path(args.config).resolve()
    return ProvisionPlan(
        install_id=args.install_id,
        service_uid=service_uid,
        service_gid=service_gid,
        caller_gid=caller_gid,
        caller_group_members=reachable,
        marks_root=pathlib.Path(args.marks_root).resolve(),
        socket_path=pathlib.Path(args.socket_path).resolve(),
        config_path=config_path,
        peers=peers,
        generation=mint_generation(config_path),
        reprovision=bool(args.reprovision),
    )


# ---------------------------------------------------------------------------
# Custody of the parents — before anything is written into them
# ---------------------------------------------------------------------------


def require_root_owned_parent(directory: pathlib.Path, what: str) -> None:
    """The directory this provisioner writes INTO must be root's and not writable by others.

    ``require_private_directory`` asks the same question of the service's own paths at start; this
    asks it of their parents, at provisioning time, where it can still be fixed. A parent another
    principal can write makes every mode below it advisory: they rename the directory aside and
    put their own in its place.
    """
    try:
        info = directory.lstat()
    except OSError as exc:
        raise ProvisionError(EXIT_CUSTODY, f"cannot stat {what} {directory}: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ProvisionError(EXIT_CUSTODY, f"{what} {directory} is not a directory")
    if info.st_uid != 0:
        raise ProvisionError(
            EXIT_CUSTODY,
            f"{what} {directory} is owned by uid {info.st_uid}, not root. A non-root parent can "
            "be renamed aside by its owner, which makes the mode of everything under it advisory")
    if info.st_mode & _OTHER_WRITE:
        raise ProvisionError(
            EXIT_CUSTODY,
            f"{what} {directory} is group- or world-writable (mode {stat.S_IMODE(info.st_mode):04o})")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def _mkdir_owned(directory: pathlib.Path, uid: int, gid: int, mode: int) -> None:
    directory.mkdir(parents=False, exist_ok=True)
    os.chown(directory, uid, gid)
    os.chmod(directory, mode)


def _write_owned(path: pathlib.Path, payload: bytes, uid: int, gid: int, mode: int) -> None:
    """The same publish the service uses: temp in the same directory, fsync, rename, fsync dir.

    Provisioning writes the document a crash must never truncate, so it is written the way every
    other write to that document is written. A provisioner using a plain ``write_text`` would be
    the one unprotected write to the one file whose integrity the whole service rests on.
    """
    temporary = path.parent / f".{path.name}.provision.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, payload)
        os.fsync(fd)
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def apply(plan: ProvisionPlan) -> Dict[str, Any]:
    """Write everything, then prove it by reading it back. Returns the receipt."""
    require_root_owned_parent(plan.marks_root.parent, "the marks root's parent")
    require_root_owned_parent(plan.socket_dir.parent, "the socket directory's parent")
    require_root_owned_parent(plan.config_path.parent, "the Floor Writer config directory")

    plan.marks_root.mkdir(parents=False, exist_ok=True)
    os.chown(plan.marks_root, 0, 0)
    os.chmod(plan.marks_root, 0o755)

    _mkdir_owned(plan.marks_dir, plan.service_uid, plan.service_gid, MARKS_DIR_MODE)
    _mkdir_owned(plan.socket_dir, plan.service_uid, plan.caller_gid, SOCKET_DIR_MODE)

    discarded: List[str] = []
    if plan.state_path.exists():
        if not plan.reprovision:
            raise ProvisionError(
                EXIT_CONFIG,
                f"{plan.state_path} already exists. Provisioning over a live floor would restart "
                "every task's anti-rollback mark at zero, which is the rollback the floor exists "
                "to refuse. Pass --reprovision to discard it deliberately, under a new generation")
        try:
            existing = json.loads(plan.state_path.read_text(encoding="utf-8"))
            discarded = sorted(existing.get("roster", [])) if isinstance(existing, dict) else []
        except (OSError, ValueError):
            discarded = ["<unreadable>"]

    document = {"install_id": plan.install_id, "generation": plan.generation,
                "roster": [], "floors": {}}
    _write_owned(plan.state_path,
                 json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                 plan.service_uid, plan.service_gid, STATE_FILE_MODE)

    _write_owned(plan.config_path,
                 json.dumps(plan.config_document(), sort_keys=True, indent=2).encode("utf-8") + b"\n",
                 0, 0, CONFIG_MODE)

    receipt = readback(plan)
    receipt["discarded_roster"] = discarded
    return receipt


# ---------------------------------------------------------------------------
# Readback — the receipt describes the filesystem, never the intention
# ---------------------------------------------------------------------------


def _facts(path: pathlib.Path, expect_uid: int, expect_gid: Optional[int],
           expect_mode: int, what: str) -> Dict[str, Any]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ProvisionError(EXIT_CUSTODY, f"{what} {path} is not there after writing it: {exc}")
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid != expect_uid:
        raise ProvisionError(
            EXIT_CUSTODY,
            f"{what} {path} reads back owned by uid {info.st_uid}, not {expect_uid}")
    if expect_gid is not None and info.st_gid != expect_gid:
        raise ProvisionError(
            EXIT_CUSTODY, f"{what} {path} reads back group {info.st_gid}, not {expect_gid}")
    if mode != expect_mode:
        raise ProvisionError(
            EXIT_CUSTODY, f"{what} {path} reads back mode {mode:04o}, not {expect_mode:04o}")
    return {"path": str(path), "uid": info.st_uid, "gid": info.st_gid, "mode": f"{mode:04o}"}


def readback(plan: ProvisionPlan) -> Dict[str, Any]:
    """Re-stat and re-parse everything. A provisioner that reports success from its own intentions
    is how a deployment comes up looking provisioned; this reports from the filesystem."""
    facts = {
        "marks_dir": _facts(plan.marks_dir, plan.service_uid, plan.service_gid,
                            MARKS_DIR_MODE, "the marks store"),
        "state_file": _facts(plan.state_path, plan.service_uid, plan.service_gid,
                             STATE_FILE_MODE, "the authoritative floor state"),
        "socket_dir": _facts(plan.socket_dir, plan.service_uid, plan.caller_gid,
                             SOCKET_DIR_MODE, "the socket directory"),
        "config": _facts(plan.config_path, 0, 0, CONFIG_MODE, "the Floor Writer config"),
    }
    # The config is not "written" until the SERVICE's own loader accepts it. Parsing it here with
    # the same function the service uses is the difference between a file and a configuration.
    config = floor_writer.load_service_config(
        {floor_writer.ENV_SERVICE_CONFIG: str(plan.config_path)})
    if config.generation != plan.generation or config.install_id != plan.install_id:
        raise ProvisionError(EXIT_CUSTODY, "the config reads back as a different provisioning")
    state = json.loads(plan.state_path.read_text(encoding="utf-8"))
    if state.get("generation") != plan.generation:
        raise ProvisionError(
            EXIT_CUSTODY,
            "the authoritative state reads back under a different generation than the config; a "
            "store and a config that disagree about which provisioning they belong to is the "
            "confusion §1.10 exists to remove")
    return {
        "install_id": plan.install_id,
        "generation": plan.generation,
        "service_uid": plan.service_uid,
        "socket_path": str(plan.socket_path),
        "peers": {op: sorted(uids) for op, uids in sorted(plan.peers.items())},
        "caller_group_gid": plan.caller_gid,
        "can_traverse_to_endpoint": sorted(plan.caller_group_members),
        "paths": facts,
        "roster": state.get("roster"),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision the Floor Writer (FW-1, Linux, root).")
    parser.add_argument("--install-id", required=True)
    parser.add_argument("--service-user", required=True,
                        help="the Floor Writer principal; the machine administrator creates it")
    parser.add_argument("--caller-group", required=True,
                        help="the group whose members may TRAVERSE to the endpoint; admission is "
                             "still the per-op allowlist and nothing else")
    parser.add_argument("--marks-root", required=True)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--peer", action="append", default=[], metavar="OP=USER",
                        help="repeatable; one authorized caller for ONE op (§1.8)")
    parser.add_argument("--reprovision", action="store_true",
                        help="discard an existing floor state under a NEW generation")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_linux()
        require_root()
        plan = build_plan(args)
        receipt = apply(plan)
    except ProvisionError as exc:
        print(exc.detail, file=sys.stderr)
        return exc.code
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_CONFIG
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
