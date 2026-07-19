"""Integrity-checked backup and restore for machine-local runtime state.

The runtime keeps its durable state OUTSIDE Git, by contract: the execution-lease
ledger, the recovery/transaction store, the task-lock ledger, and the append-only
audit / shadow ledgers all live on operator-controlled paths. Operational rollout
needs those to survive a host move or disk loss without silently losing — or
silently corrupting — the audit history.

This tool snapshots a named set of those stores into an archive with a per-file
SHA-256 manifest, and restores them back with the manifest re-verified. It is
fail-closed on integrity: every append-only ledger (``*.jsonl``, verified through
bro_audit_log's hash chain + head anchor) is chain-verified at BOTH backup and
restore time, so a tampered or truncated ledger is never archived and never
restored. Whether a file IS a ledger is derived from its archived ``*.jsonl``
suffix, never from the attacker-supplied manifest — a crafted manifest cannot opt
a ledger out of chain verification by declaring ``audit_chain: null``.

The manifest itself may be signed by the offline operator (an Ed25519 detached
signature over the canonical payload, verified through bro_signature's key
registry). When trusted keys are supplied — or the archive carries a signed
manifest at all — verification is authoritative: a tampered or unsigned manifest
is refused, so an adversary who rewrites both a state file and its manifest entry
no longer verifies GREEN. An unsigned manifest without keys remains a structural
check only (corruption/truncation, plus the ledgers' own cryptographic chains).

Pure standard library plus bro_audit_log; bro_signature only when signatures are
in play. No repository writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_audit_log import AuditError, verify as verify_audit_chain, verify_signed_payload

MANIFEST_NAME = "backup-manifest.json"
# Like bro_audit_log's audit-head, this artifact type is deliberately unknown to
# bro_signature.ARTIFACT_AUTHORITY, so a signed backup manifest can never be
# replayed as a registry artifact (or vice versa).
MANIFEST_ARTIFACT_TYPE = "backup-manifest"
# Only the offline operator may sign a backup manifest; the builder that writes
# the runtime state it snapshots holds no operator key.
MANIFEST_AUTHORITIES = ("operator-root",)


class BackupError(ValueError):
    pass


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(source: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """Return (relpath, absolute) for every regular file under a source.

    A source may be a single file (e.g. an audit ledger) or a directory (e.g. the
    recovery store). Relative paths are taken from the source's parent for a file
    and from the source itself for a directory, so restore is uniform: everything
    lands under a single target directory.
    """
    source = source.expanduser()
    if source.is_file():
        files = [(source.name, source)]
        # An audit ledger's head anchor (.jsonl.head) is required for chain
        # verification; carry it alongside a single-file ledger source, together
        # with the signed head anchor (.jsonl.head.sig) when one exists so a
        # restored ledger stays verifiable against its recorder signature.
        if source.suffix == ".jsonl":
            for sidecar_suffix in (".head", ".head.sig"):
                sidecar = source.with_name(source.name + sidecar_suffix)
                if sidecar.is_file():
                    files.append((sidecar.name, sidecar))
        return files
    if source.is_dir():
        out = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise BackupError(f"refusing to back up a symlink: {path}")
            if path.is_file():
                out.append((path.relative_to(source).as_posix(), path))
        return out
    raise BackupError(f"backup source does not exist: {source}")


def _is_ledger(name: str) -> bool:
    """Ledger-ness is a property of the file's ``*.jsonl`` suffix, decided here and
    nowhere else — never from a manifest entry an attacker controls. Case-folded so
    a crafted ``*.JSONL`` cannot dodge chain verification on any host."""
    return pathlib.PurePosixPath(name).suffix.lower() == ".jsonl"


def _verify_ledger(path: pathlib.Path) -> int:
    """Chain-verify an append-only ledger; return its record count. A broken chain
    fails closed."""
    try:
        return verify_audit_chain(path)
    except AuditError as exc:
        raise BackupError(f"append-only ledger failed chain verification: {path}: {exc}") from exc


def _chain_count(path: pathlib.Path) -> int | None:
    """Record count for a ``*.jsonl`` ledger, None for any other file."""
    if not _is_ledger(path.name):
        return None
    return _verify_ledger(path)


def backup(sources: dict[str, pathlib.Path], dest: pathlib.Path, *, now: int) -> dict:
    """Archive each named source under ``dest/<name>/`` with an integrity manifest."""
    dest = dest.expanduser()
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"backup destination is not empty: {dest}")
    # artifact_type is carried in the payload from the start so the offline
    # operator's signing step only adds its key_id and wraps {payload, signature};
    # verify_signed_payload then binds the signature to this artifact type.
    manifest: dict = {"schema": 1, "artifact_type": MANIFEST_ARTIFACT_TYPE,
                      "created_at_epoch": int(now), "sources": {}}
    for name, source in sources.items():
        if "/" in name or "\\" in name or name in {"", ".", ".."}:
            raise BackupError(f"invalid source name: {name!r}")
        files = _iter_files(pathlib.Path(source))
        entries = []
        for rel, absolute in files:
            target = dest / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(absolute, target)
            entries.append({
                "rel": rel,
                "sha256": _sha256(absolute),
                "bytes": absolute.stat().st_size,
                "audit_chain": (lambda c: {"count": c} if c is not None else None)(_chain_count(absolute)),
            })
        manifest["sources"][name] = {
            "kind": "file" if pathlib.Path(source).expanduser().is_file() else "dir",
            "files": entries,
        }
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


# A restore must never trust the manifest's paths. A crafted archive can name a
# source "../x" or an entry rel "../../etc/evil", or slip a symlink into the
# archive, and drive a write outside the target. Names and rels are validated as
# strictly-relative, ..-free, backslash-free, non-symlink, and every resolved path
# is required to stay within its base.
def _reject_windows_anchor(value: str, label: str) -> None:
    """Reject any Windows drive letter, drive-relative, or root anchor in a single
    path component. `_safe_rel`'s POSIX parsing treats `C:` as an ordinary name and
    `is_absolute()` stays False, but on a Windows *restore* host `target / "C:" /
    ...` resets to the `C:` drive and escapes the target — regardless of the OS the
    archive was crafted on. A bare `:` is also refused (drive syntax and NTFS
    alternate-data-stream syntax both use it; runtime ledger names never do)."""
    if ":" in value:
        raise BackupError(f"unsafe {label} (drive/stream colon): {value!r}")
    win = pathlib.PureWindowsPath(value)
    if win.drive or win.root:
        raise BackupError(f"unsafe {label} (drive/root anchor): {value!r}")


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise BackupError(f"invalid source name in manifest: {name!r}")
    _reject_windows_anchor(name, "source name")
    return name


def _safe_rel(rel: str) -> pathlib.PurePosixPath:
    if not isinstance(rel, str) or not rel or rel != rel.strip() or "\\" in rel:
        raise BackupError(f"invalid archived path: {rel!r}")
    pure = pathlib.PurePosixPath(rel)
    if pure.is_absolute() or any(part == ".." for part in pure.parts):
        raise BackupError(f"unsafe archived path (traversal): {rel!r}")
    for part in pure.parts:
        _reject_windows_anchor(part, "archived path component")
    return pure


def _walk_no_symlink(root: pathlib.Path, parts: tuple[str, ...], label: str) -> pathlib.Path:
    """Descend `parts` from `root`, rejecting a symlink at any component so no
    component — including a source directory — can redirect a read or write
    outside `root`. `root` itself is not required to be symlink-free (a target may
    legitimately be one). Containment is enforced both by construction (names and
    rels carry no `..`, absolute, or drive parts) and by a final lexical check that
    the built path stays under `root` — the latter catches a Windows drive-letter
    component that would otherwise reset the anchor on a Windows host."""
    cur = root
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            raise BackupError(f"{label} path component is a symlink: {cur}")
    try:
        cur.relative_to(root)
    except ValueError:
        raise BackupError(f"{label} path escapes the target: {cur}") from None
    return cur


def _archived_source(archive: pathlib.Path, name: str, rel: str) -> pathlib.Path:
    return _walk_no_symlink(archive, (_safe_name(name), *_safe_rel(rel).parts), "archived")


def _restore_target(target: pathlib.Path, rel: str) -> pathlib.Path:
    return _walk_no_symlink(target, _safe_rel(rel).parts, "restore")


def _rel_key(rel: str) -> str:
    """Normalised identity of an archived path, so `a.txt` and `./a.txt` collide."""
    return _safe_rel(rel).as_posix()


def _load_manifest(archive: pathlib.Path, keys: dict | None, now: int | None) -> dict:
    """Read the archive manifest, verifying the operator signature when present.

    Fail-closed in both directions: a signed manifest without trusted keys is
    refused (skipping the signature would silently downgrade the check), and an
    unsigned manifest is refused whenever the caller supplied keys (an attacker
    must not be able to strip the signature to reach the weaker path)."""
    manifest_path = archive / MANIFEST_NAME
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"unreadable backup manifest: {exc}") from exc
    if isinstance(document, dict) and set(document) == {"payload", "signature"}:
        if keys is None:
            raise BackupError(
                "archive manifest is signed but no trusted keys were supplied; "
                "refusing to verify without the operator signature")
        try:
            manifest = verify_signed_payload(document, MANIFEST_ARTIFACT_TYPE, keys,
                                             authorities=MANIFEST_AUTHORITIES, now=now)
        except AuditError as exc:
            raise BackupError(f"backup manifest signature RED: {exc}") from exc
    else:
        if keys is not None:
            raise BackupError(
                "trusted keys supplied but the archive manifest is unsigned; "
                "refusing the downgrade")
        manifest = document
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise BackupError("unsupported backup manifest schema")
    return manifest


def verify_archive(archive: pathlib.Path, *, keys: dict | None = None,
                   now: int | None = None) -> dict:
    """Re-verify an archive against its manifest without restoring. Raises on any
    checksum mismatch, missing file, broken ledger chain, unsafe/duplicate path,
    or (with ``keys``) a missing/invalid operator signature on the manifest."""
    archive = archive.expanduser()
    manifest = _load_manifest(archive, keys, now)
    for name, spec in manifest.get("sources", {}).items():
        seen: set[str] = set()
        for entry in spec.get("files", []):
            rel = entry["rel"]
            key = _rel_key(rel)
            if key in seen:
                raise BackupError(f"duplicate archived path: {name}/{rel}")
            seen.add(key)
            archived = _archived_source(archive, name, rel)
            if not archived.is_file():
                raise BackupError(f"archived file is missing: {name}/{rel}")
            if _sha256(archived) != entry["sha256"]:
                raise BackupError(f"archived file checksum mismatch: {name}/{rel}")
            # Ledger-ness comes from the *.jsonl suffix, never from the manifest:
            # every archived ledger is chain-verified, and its manifest entry MUST
            # declare the chain — "audit_chain": null on a ledger is a forged or
            # downgraded manifest, not an opt-out.
            if _is_ledger(archived.name):
                declared = entry.get("audit_chain")
                if not isinstance(declared, dict) or not isinstance(declared.get("count"), int):
                    raise BackupError(
                        f"manifest does not declare a ledger chain for {name}/{rel}")
                if _verify_ledger(archived) != declared["count"]:
                    raise BackupError(f"archived ledger chain length changed: {name}/{rel}")
            elif entry.get("audit_chain") is not None:
                raise BackupError(
                    f"manifest claims a ledger chain for a non-ledger file: {name}/{rel}")
    return manifest


def restore(archive: pathlib.Path, targets: dict[str, pathlib.Path], *, force: bool = False,
            keys: dict | None = None, now: int | None = None) -> dict:
    """Restore named sources from a verified archive into their target directories.

    Every file is checksum-verified, every ledger chain re-verified, and (with
    ``keys``) the manifest's operator signature verified before any write. Existing
    target files are not clobbered unless ``force`` is set.
    """
    archive = archive.expanduser()
    manifest = verify_archive(archive, keys=keys, now=now)
    restored: dict[str, int] = {}
    for name, target in targets.items():
        spec = manifest.get("sources", {}).get(name)
        if spec is None:
            raise BackupError(f"archive has no source named {name!r}")
        target = pathlib.Path(target).expanduser()
        for entry in spec["files"]:
            out = _restore_target(target, entry["rel"])
            if out.exists() and not force:
                raise BackupError(f"refusing to overwrite existing file (use force): {out}")
        for entry in spec["files"]:
            out = _restore_target(target, entry["rel"])
            src = _archived_source(archive, name, entry["rel"])
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out)
        restored[name] = len(spec["files"])
    return restored


def _registry_keys_if_signed(archive: pathlib.Path) -> dict | None:
    """CLI helper: when the archive carries a signed manifest, load the trusted key
    registry (anchored to the external operator pin) so the signature is actually
    checked. An unsigned manifest keeps the keyless structural path; a signed one
    with no resolvable registry fails closed inside verify/restore."""
    try:
        document = json.loads((pathlib.Path(archive).expanduser() / MANIFEST_NAME)
                              .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"unreadable backup manifest: {exc}") from exc
    if not (isinstance(document, dict) and set(document) == {"payload", "signature"}):
        return None
    from bro_signature import SignatureError, load_trusted_keys
    try:
        return load_trusted_keys()
    except SignatureError as exc:
        raise BackupError(
            f"archive manifest is signed but the trusted key registry cannot be "
            f"loaded: {exc}") from exc


def _parse_named(pairs: list[str]) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise BackupError(f"expected name=path, got: {pair!r}")
        name, path = pair.split("=", 1)
        out[name] = pathlib.Path(path)
    return out


def main(argv: list[str] | None = None) -> int:
    import time
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="archive named runtime-state sources")
    b.add_argument("--dest", required=True)
    b.add_argument("--source", action="append", metavar="name=path", help="repeatable")

    v = sub.add_parser("verify", help="re-verify an archive against its manifest")
    v.add_argument("--archive", required=True)

    r = sub.add_parser("restore", help="restore named sources from an archive")
    r.add_argument("--archive", required=True)
    r.add_argument("--target", action="append", metavar="name=path", help="repeatable")
    r.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            manifest = backup(_parse_named(args.source), pathlib.Path(args.dest), now=int(time.time()))
            print(f"GREEN: backed up sources={len(manifest['sources'])} to {args.dest}")
        elif args.command == "verify":
            archive = pathlib.Path(args.archive)
            manifest = verify_archive(archive, keys=_registry_keys_if_signed(archive))
            print(f"GREEN: archive verified sources={len(manifest['sources'])}")
        elif args.command == "restore":
            archive = pathlib.Path(args.archive)
            restored = restore(archive, _parse_named(args.target), force=args.force,
                               keys=_registry_keys_if_signed(archive))
            print(f"GREEN: restored {restored}")
    except BackupError as exc:
        print(f"RED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
