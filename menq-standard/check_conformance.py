#!/usr/bin/env python3
"""Does this repository follow MenQ Standard at the version its pin names? (decision D-029)

A repository that follows the standard keeps a PIN, `.menq-standard.json`, and an unchanged copy
of the consumer KIT in one directory. This file is part of the kit. It needs Python and git, no
package and no network.

    check        is the repository conformant?                          exit 0 GREEN, 1 RED
    status       is the pin behind a checkout of the standard?          exit 0 CURRENT, 10 BEHIND, 1 RED
    install      copy the kit from a checkout of the standard and write the pin (adoption and update)
    changelog    print the standard's changelog entries newer than a version
    pin-commit   print the commit the pin names, once it is proven to be on the standard's ref

WHAT `check` CHECKS WITH NO NETWORK AND NO STANDARD:
    the pin is well-formed; every kit file it lists exists and has the recorded hash; nothing else
    sits in the kit directory; every workflow it lists exists and has the recorded hash; the
    session-read manifest exists and the budget gate is GREEN on it; and, when
    config/doc-facts.json exists, `sync_facts.py --check` is GREEN.

WHAT IT CHECKS ONLY WITH `--standard DIR` (a git checkout of the standard):
    the pin's commit exists there and is an ancestor of `--standard-ref`; the pin's version and
    every recorded hash equal the standard's own VERSION and consumer/KIT_MANIFEST.json at that
    commit; every recorded workflow is the standard's template rendered at its recorded commit.
    Without `--standard` a pin can name a commit and hashes of its own invention and stay GREEN;
    the output says so on every run.

THE HASH of a kit file is the sha256 of its bytes after CRLF is folded to LF, so a checkout that
converts line endings does not make an unmodified kit file look edited. An edit that changes
nothing but line endings is therefore not detected.

The gate and sync_facts that `check` runs are the copies NEXT TO THIS FILE. Run from the
standard's checkout (the reusable workflow does), a repository cannot pass by editing its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent

STANDARD_REPOSITORY = "menqstudio/MenQ-Standard"
PIN_REL = ".menq-standard.json"
PIN_SCHEMA_VERSION = 1
KIT_MANIFEST_SCHEMA_VERSION = 1
STANDARD_KIT_DIR = "consumer"
KIT_MANIFEST_REL = STANDARD_KIT_DIR + "/KIT_MANIFEST.json"
VERSION_REL = "VERSION"
CHANGELOG_REL = "CHANGELOG.md"
DEFAULT_KIT_DIR = "menq-standard"
DEFAULT_MANIFEST_REL = "SESSION_READ_MANIFEST.json"
SYNC_FACTS_CONFIG = "config/doc-facts.json"
HASH_RULE = "sha256 of the file's bytes after CRLF is folded to LF"
SELF = "check_conformance.py"
BUDGET_GATE = "check_session_read_budget.py"
SYNC_FACTS = "sync_facts.py"
CONFORMANCE_WORKFLOW = ".github/workflows/menq-standard-conformance.yml"
UPDATE_WORKFLOW = ".github/workflows/menq-standard-update.yml"
# Where a kit template is rendered in a repository.  The first is required; the second is not.
WORKFLOW_TEMPLATES = {
    CONFORMANCE_WORKFLOW: "templates/menq-standard-conformance.yml",
    UPDATE_WORKFLOW: "templates/menq-standard-update.yml",
}
REQUIRED_WORKFLOWS = (CONFORMANCE_WORKFLOW,)
# The kit files this checker itself runs or renders: a pin that omits one cannot be checked.
REQUIRED_KIT_FILES = (SELF, BUDGET_GATE, SYNC_FACTS, *WORKFLOW_TEMPLATES.values())
COMMIT_PLACEHOLDER = "__MENQ_STANDARD_COMMIT__"
KIT_DIR_PLACEHOLDER = "__MENQ_KIT_DIR__"
EXIT_BEHIND = 10

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# One directory name that starts with a letter or a digit: no "/", and so never "." or "..".
KIT_DIR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION_HEADING = re.compile(r"^## .*\bMenQ Standard v(\d+\.\d+\.\d+)(?![\w.])")
IGNORED_IN_KIT_DIR = ("__pycache__",)
VERDICT_NAME = {"check": "CONFORMANCE", "pin-commit": "CONFORMANCE", "status": "STATUS", "install": "INSTALL", "changelog": "CHANGELOG"}


class Refusal(Exception):
    """The command cannot continue; the message is the RED line."""


# ================================================================================================
# Small helpers
# ================================================================================================


def normalised(data: bytes) -> bytes:
    """Fold CRLF to LF, so a hash does not depend on the checkout."""
    return data.replace(b"\r\n", b"\n")


def kit_hash(data: bytes) -> str:
    return hashlib.sha256(normalised(data)).hexdigest()


def parse_version(text: object) -> tuple[int, int, int] | None:
    if not isinstance(text, str):
        return None
    match = SEMVER.match(text)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def path_problem(value: object) -> str | None:
    """Why a recorded path is not a clean relative path, or None."""
    if not isinstance(value, str) or not value:
        return "is not a non-empty string"
    if "\\" in value:
        return "uses a backslash"
    if value.startswith("/"):
        return "is absolute"
    if any(part in ("", ".", "..") for part in value.split("/")):
        return "is not normalised (empty, '.' or '..' segment)"
    return None


def render(template: bytes, commit: str, kit_dir: str) -> bytes:
    """A kit template with its two placeholders filled in.  LF line endings."""
    text = normalised(template)
    return text.replace(COMMIT_PLACEHOLDER.encode(), commit.encode()).replace(KIT_DIR_PLACEHOLDER.encode(), kit_dir.encode())


def run_git(repo: Path, *args: str) -> tuple[int, bytes]:
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    except OSError as exc:
        raise Refusal(f"git could not be run in {repo}: {exc}") from exc
    return result.returncode, result.stdout


# ================================================================================================
# The pin
# ================================================================================================


def pin_errors(pin: object) -> list[str]:
    """Every structural fault of a pin.  An empty list means the pin is well-formed."""
    if not isinstance(pin, dict):
        return ["pin is malformed: top level must be an object"]
    errors: list[str] = []
    expected = {"schema_version", "standard", "kit_dir", "session_read_manifest", "hash", "files", "workflows"}
    for key in sorted(set(pin) - expected):
        errors.append(f"pin is malformed: unknown field {key!r}")
    for key in sorted(expected - set(pin)):
        errors.append(f"pin is malformed: field {key!r} is missing")
    if "schema_version" in pin and pin["schema_version"] != PIN_SCHEMA_VERSION:
        errors.append(f"pin is malformed: schema_version is {pin['schema_version']!r}, expected {PIN_SCHEMA_VERSION}")

    standard = pin.get("standard")
    if "standard" in pin:
        if not isinstance(standard, dict) or set(standard) != {"repository", "version", "commit"}:
            errors.append("pin is malformed: standard must be an object with exactly repository, version and commit")
        else:
            if standard["repository"] != STANDARD_REPOSITORY:
                errors.append(
                    f"pin is malformed: standard.repository is {standard['repository']!r}, expected {STANDARD_REPOSITORY!r}"
                )
            if parse_version(standard["version"]) is None:
                errors.append(f"pin is malformed: standard.version {standard['version']!r} is not MAJOR.MINOR.PATCH")
            if not isinstance(standard["commit"], str) or not COMMIT.match(standard["commit"]):
                errors.append(f"pin is malformed: standard.commit {standard['commit']!r} is not a full 40-character commit SHA")

    kit_dir = pin.get("kit_dir")
    if "kit_dir" in pin and (not isinstance(kit_dir, str) or not KIT_DIR_NAME.match(kit_dir)):
        errors.append(f"pin is malformed: kit_dir {kit_dir!r} must be one directory name at the repository root")
    if "session_read_manifest" in pin:
        problem = path_problem(pin["session_read_manifest"])
        if problem:
            errors.append(f"pin is malformed: session_read_manifest {pin['session_read_manifest']!r} {problem}")
    if "hash" in pin and pin["hash"] != HASH_RULE:
        errors.append(f"pin is malformed: hash is {pin['hash']!r}, expected {HASH_RULE!r}")

    files = pin.get("files")
    if "files" in pin:
        if not isinstance(files, dict) or not files:
            errors.append("pin is malformed: files must be a non-empty object mapping a kit file to its sha256")
        else:
            for rel, digest in files.items():
                problem = path_problem(rel)
                if problem:
                    errors.append(f"pin is malformed: files path {rel!r} {problem}")
                if not isinstance(digest, str) or not SHA256.match(digest):
                    errors.append(f"pin is malformed: files[{rel!r}] is not a sha256 (64 lower-case hex characters)")
            for rel in REQUIRED_KIT_FILES:
                if rel not in files:
                    errors.append(f"pin is malformed: files does not list {rel!r}, which the checker itself needs")

    workflows = pin.get("workflows")
    if "workflows" in pin:
        if not isinstance(workflows, dict):
            errors.append("pin is malformed: workflows must be an object")
        else:
            for dest, record in workflows.items():
                if dest not in WORKFLOW_TEMPLATES:
                    errors.append(f"pin is malformed: workflows names {dest!r}, which is not a workflow the kit renders")
                    continue
                if not isinstance(record, dict) or set(record) != {"template", "commit", "sha256"}:
                    errors.append(f"pin is malformed: workflows[{dest!r}] must have exactly template, commit and sha256")
                    continue
                if record["template"] != WORKFLOW_TEMPLATES[dest]:
                    errors.append(
                        f"pin is malformed: workflows[{dest!r}].template is {record['template']!r}, "
                        f"expected {WORKFLOW_TEMPLATES[dest]!r}"
                    )
                if not isinstance(record["commit"], str) or not COMMIT.match(record["commit"]):
                    errors.append(f"pin is malformed: workflows[{dest!r}].commit is not a full 40-character commit SHA")
                if not isinstance(record["sha256"], str) or not SHA256.match(record["sha256"]):
                    errors.append(f"pin is malformed: workflows[{dest!r}].sha256 is not a sha256")
            for dest in REQUIRED_WORKFLOWS:
                if dest not in workflows:
                    errors.append(f"pin is malformed: workflows does not list {dest!r}; conformance must run in CI")
    return errors


def load_pin(consumer: Path) -> tuple[dict | None, list[str]]:
    path = consumer / PIN_REL
    if not path.is_file():
        return None, [f"pin is missing: {PIN_REL}"]
    try:
        pin = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"pin is malformed: {PIN_REL}: {exc}"]
    errors = pin_errors(pin)
    return (None, errors) if errors else (pin, [])


def pin_bytes(version: str, commit: str, kit_dir: str, manifest_rel: str, files: dict, workflows: dict) -> bytes:
    document = {
        "schema_version": PIN_SCHEMA_VERSION,
        "standard": {"repository": STANDARD_REPOSITORY, "version": version, "commit": commit},
        "kit_dir": kit_dir,
        "session_read_manifest": manifest_rel,
        "hash": HASH_RULE,
        "files": {rel: files[rel] for rel in sorted(files)},
        "workflows": {dest: workflows[dest] for dest in sorted(workflows)},
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ================================================================================================
# A checkout of the standard, read through git objects (never through its working tree)
# ================================================================================================


class Standard:
    def __init__(self, path: Path, ref: str) -> None:
        self.path = path
        self.ref = ref
        if not path.is_dir() or run_git(path, "rev-parse", "--git-dir")[0] != 0:
            raise Refusal(f"--standard is not a git checkout: {path}")
        resolved = self.commit_of(ref)
        if resolved is None:
            raise Refusal(f"the standard at {path} has no ref {ref!r}")
        self.ref_commit = resolved

    def commit_of(self, revision: str) -> str | None:
        code, out = run_git(self.path, "rev-parse", "--verify", "--quiet", revision + "^{commit}")
        return out.decode("ascii", "replace").strip() if code == 0 else None

    def has_commit(self, commit: str) -> bool:
        return self.commit_of(commit) == commit

    def is_ancestor(self, commit: str, of: str) -> bool:
        return run_git(self.path, "merge-base", "--is-ancestor", commit, of)[0] == 0

    def blob(self, commit: str, rel: str) -> bytes | None:
        code, out = run_git(self.path, "cat-file", "blob", f"{commit}:{rel}")
        return out if code == 0 else None

    def state(self, commit: str) -> tuple[str, dict[str, str]]:
        """(version, {kit file: hash}) the standard declares at a commit."""
        short = commit[:12]
        version_blob = self.blob(commit, VERSION_REL)
        if version_blob is None:
            raise Refusal(f"the standard at {short} has no {VERSION_REL} file: it predates the consumer kit")
        version = normalised(version_blob).decode("utf-8", "replace").strip()
        if parse_version(version) is None:
            raise Refusal(f"the standard at {short} has a {VERSION_REL} that is not MAJOR.MINOR.PATCH: {version!r}")
        manifest_blob = self.blob(commit, KIT_MANIFEST_REL)
        if manifest_blob is None:
            raise Refusal(f"the standard at {short} carries no consumer kit ({KIT_MANIFEST_REL} is absent)")
        try:
            manifest = json.loads(manifest_blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Refusal(f"the standard at {short} has a malformed {KIT_MANIFEST_REL}: {exc}") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != KIT_MANIFEST_SCHEMA_VERSION:
            found = manifest.get("schema_version") if isinstance(manifest, dict) else None
            raise Refusal(
                f"the standard at {short} has kit manifest schema_version {found!r}; this checker knows "
                f"{KIT_MANIFEST_SCHEMA_VERSION}. Update by hand, following consumer/ADOPTION.md at that commit"
            )
        files = manifest.get("files")
        if (
            not isinstance(files, dict)
            or not files
            or any(path_problem(rel) or not isinstance(digest, str) or not SHA256.match(digest) for rel, digest in files.items())
        ):
            raise Refusal(f"the standard at {short} has a malformed {KIT_MANIFEST_REL}: files is not a path-to-sha256 object")
        return version, files


def pin_against_standard(pin: dict, standard: Standard) -> list[str]:
    """Is what the pin says about the standard true of the standard?"""
    errors: list[str] = []
    commit = pin["standard"]["commit"]
    if not standard.has_commit(commit):
        return [f"pin names a commit that does not exist in the standard: {commit}"]
    if not standard.is_ancestor(commit, standard.ref_commit):
        return [f"pin names a commit that is not on the standard's {standard.ref}: {commit}"]
    try:
        version, files = standard.state(commit)
    except Refusal as refusal:
        return [str(refusal)]
    short = commit[:12]
    if pin["standard"]["version"] != version:
        errors.append(f"pin names version {pin['standard']['version']}, but the standard at {short} is version {version}")
    for rel in sorted(set(files) | set(pin["files"])):
        if rel not in pin["files"]:
            errors.append(f"pin does not list kit file {rel}, which the standard has at {short}")
        elif rel not in files:
            errors.append(f"pin lists {rel}, which is not a kit file of the standard at {short}")
        elif pin["files"][rel] != files[rel]:
            errors.append(f"pin records {pin['files'][rel]} for {rel}; the standard at {short} has {files[rel]}")
    for dest, record in sorted(pin["workflows"].items()):
        if not standard.has_commit(record["commit"]):
            errors.append(f"pin names a workflow commit that does not exist in the standard: {dest} at {record['commit']}")
            continue
        if not standard.is_ancestor(record["commit"], standard.ref_commit):
            errors.append(f"pin names a workflow commit that is not on the standard's {standard.ref}: {dest} at {record['commit']}")
            continue
        template = standard.blob(record["commit"], f"{STANDARD_KIT_DIR}/{record['template']}")
        if template is None:
            errors.append(f"the standard at {record['commit'][:12]} has no template {record['template']} for {dest}")
        elif kit_hash(render(template, record["commit"], pin["kit_dir"])) != record["sha256"]:
            errors.append(
                f"pin records a hash for {dest} that is not the standard's template rendered at {record['commit'][:12]}"
            )
    return errors


# ================================================================================================
# check
# ================================================================================================


def kit_file_errors(consumer: Path, pin: dict) -> list[str]:
    errors: list[str] = []
    kit_dir = pin["kit_dir"]
    for rel, recorded in sorted(pin["files"].items()):
        path = consumer / kit_dir / rel
        if not path.is_file():
            errors.append(f"kit file is missing: {kit_dir}/{rel}")
            continue
        found = kit_hash(path.read_bytes())
        if found != recorded:
            errors.append(
                f"kit file does not match its pin: {kit_dir}/{rel} (pinned {recorded}, found {found}); "
                "a kit file is never edited in a repository that follows the standard"
            )
    root = consumer / kit_dir
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or any(part in IGNORED_IN_KIT_DIR for part in rel.split("/")):
                continue
            if rel not in pin["files"]:
                errors.append(f"file in the kit directory is not listed in the pin: {kit_dir}/{rel}")
    return errors


def workflow_errors(consumer: Path, pin: dict) -> list[str]:
    errors: list[str] = []
    for dest, record in sorted(pin["workflows"].items()):
        path = consumer / dest
        if not path.is_file():
            errors.append(f"workflow file is missing: {dest}")
            continue
        found = kit_hash(path.read_bytes())
        if found != record["sha256"]:
            errors.append(
                f"workflow file does not match its pin: {dest} (pinned {record['sha256']}, found {found}); "
                "it is rendered by `install --render-workflows`, never edited"
            )
    return errors


def run_sibling(script: str, *args: str) -> tuple[int, str]:
    """Run a kit script that sits next to this file, never one named by the repository being checked."""
    path = KIT / script
    if not path.is_file():
        raise Refusal(f"the checker's own kit is incomplete: {script} is not next to {SELF}")
    try:
        result = subprocess.run(
            [sys.executable, str(path), *args], capture_output=True, text=True, encoding="utf-8", errors="backslashreplace"
        )
    except OSError as exc:
        raise Refusal(f"{script} could not be run: {exc}") from exc
    return result.returncode, result.stdout + result.stderr


def budget_errors(consumer: Path, pin: dict, report: list[str]) -> list[str]:
    manifest_rel = pin["session_read_manifest"]
    if not (consumer / manifest_rel).is_file():
        return [f"session-read manifest is missing: {manifest_rel} (D-028 requires one in every repository that follows the standard)"]
    code, output = run_sibling(BUDGET_GATE, "--root", str(consumer), "--manifest", manifest_rel)
    lines = [line for line in output.splitlines() if line.strip()]
    if code != 0:
        reasons = [line[2:] for line in lines if line.startswith("- ")] or lines[-1:] or [f"exit {code}"]
        return [f"session-read budget gate is RED: {reason}" for reason in reasons]
    summary = next((line for line in lines if line.startswith("core: ")), "GREEN")
    report.append(f"session read: {manifest_rel}: {summary}")
    return []


def facts_errors(consumer: Path, report: list[str]) -> list[str]:
    if not (consumer / SYNC_FACTS_CONFIG).is_file():
        report.append(f"sync_facts: NOT CONFIGURED ({SYNC_FACTS_CONFIG} is absent), so no repeated fact is checked")
        return []
    code, output = run_sibling(SYNC_FACTS, "--check", "--root", str(consumer))
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if code != 0:
        return [f"sync_facts --check is RED: {line}" for line in lines] or [f"sync_facts --check is RED: exit {code}"]
    report.append(f"sync_facts: {lines[-1] if lines else 'GREEN'}")
    return []


def check(consumer: Path, standard: Standard | None) -> tuple[list[str], list[str]]:
    """Return (errors, report lines).  No errors means GREEN."""
    report: list[str] = []
    pin, errors = load_pin(consumer)
    if pin is None:
        return errors, report
    report.append(f"pin: {STANDARD_REPOSITORY} {pin['standard']['version']} @ {pin['standard']['commit']}")
    found = kit_file_errors(consumer, pin)
    errors += found
    if not found:
        report.append(f"kit: {len(pin['files'])} files in {pin['kit_dir']}/ match the pin, and nothing else is there")
    found = workflow_errors(consumer, pin)
    errors += found
    if not found:
        report.append(f"workflows: {', '.join(sorted(pin['workflows']))} match the pin")
    try:
        errors += budget_errors(consumer, pin, report)
        errors += facts_errors(consumer, report)
    except Refusal as refusal:
        errors.append(str(refusal))
    if standard is None:
        report.append(
            "standard: NOT CHECKED. Without --standard nothing proved that the pin's commit, version and hashes "
            "are the standard's own; the reusable workflow checks that"
        )
    else:
        found = pin_against_standard(pin, standard)
        errors += found
        if not found:
            report.append(
                f"standard: the pin's commit is on {standard.ref}, and its version, {len(pin['files'])} kit hashes "
                f"and {len(pin['workflows'])} workflow hash(es) are the standard's own"
            )
    return errors, report


# ================================================================================================
# status
# ================================================================================================


def status(consumer: Path, standard: Standard) -> tuple[int, list[str]]:
    """(exit code, lines).  0 current, EXIT_BEHIND behind, 1 RED."""
    pin, errors = load_pin(consumer)
    if pin is not None:
        errors = pin_against_standard(pin, standard)
    if pin is None or errors:
        return 1, ["MENQ STANDARD STATUS: RED", *(f"- {error}" for error in errors)]
    try:
        version, files = standard.state(standard.ref_commit)
    except Refusal as refusal:
        return 1, ["MENQ STANDARD STATUS: RED", f"- {refusal}"]
    pinned = pin["standard"]["version"]
    differing: list[str] = []
    for rel in sorted(set(files) | set(pin["files"])):
        if rel not in pin["files"]:
            differing.append(f"  added    {rel}")
        elif rel not in files:
            differing.append(f"  removed  {rel}")
        elif files[rel] != pin["files"][rel]:
            differing.append(f"  changed  {rel}")
    lines = [
        f"pin:      {pinned} @ {pin['standard']['commit']}",
        f"standard: {version} @ {standard.ref_commit} ({standard.ref})",
    ]
    if parse_version(version) < parse_version(pinned):
        return 1, ["MENQ STANDARD STATUS: RED", f"- pin names version {pinned}, newer than {version} at {standard.ref}", *lines]
    if version == pinned:
        if differing:
            return 1, [
                "MENQ STANDARD STATUS: RED",
                f"- the standard changed kit files between the pin and {standard.ref} without changing VERSION; "
                "that is a defect in the standard, not in this repository",
                *lines,
                *differing,
            ]
        return 0, ["MENQ STANDARD STATUS: CURRENT", *lines, "kit files that differ: none"]
    lines.append(f"kit files that differ ({len(differing)}):" if differing else "kit files that differ: none (the version moved, the kit did not)")
    lines += differing
    stale = [
        f"  {dest}  (template {record['template']} changed since {record['commit'][:12]})"
        for dest, record in sorted(pin["workflows"].items())
        if standard.blob(record["commit"], f"{STANDARD_KIT_DIR}/{record['template']}")
        != standard.blob(standard.ref_commit, f"{STANDARD_KIT_DIR}/{record['template']}")
    ]
    if stale:
        lines.append("workflows a person must re-render and push (an Actions token may not write workflow files):")
        lines += stale
    return EXIT_BEHIND, ["MENQ STANDARD STATUS: BEHIND", *lines]


# ================================================================================================
# install
# ================================================================================================


def install(
    consumer: Path,
    standard: Standard,
    kit_dir: str | None,
    manifest_rel: str | None,
    with_update_workflow: bool,
    render_workflows: bool,
) -> list[str]:
    """Copy the kit at the standard's ref into the repository and write the pin.  Raises Refusal."""
    if not consumer.is_dir():
        raise Refusal(f"--consumer is not a directory: {consumer}")
    commit = standard.ref_commit
    version, files = standard.state(commit)

    old: dict | None = None
    if (consumer / PIN_REL).exists():
        old, errors = load_pin(consumer)
        if old is None:
            raise Refusal(f"the existing pin cannot be read, so nothing was written: {errors[0]}")
        if parse_version(version) < parse_version(old["standard"]["version"]):
            raise Refusal(
                f"the standard at {standard.ref} is version {version}, older than the pinned "
                f"{old['standard']['version']}; an update is undone by reverting its commit, not by installing backwards"
            )
        if kit_dir is not None and kit_dir != old["kit_dir"]:
            raise Refusal(f"the kit lives in {old['kit_dir']}/; moving it to {kit_dir}/ is a change a person makes by hand")
    kit_dir = kit_dir or (old["kit_dir"] if old else DEFAULT_KIT_DIR)
    manifest_rel = manifest_rel or (old["session_read_manifest"] if old else DEFAULT_MANIFEST_REL)
    if not KIT_DIR_NAME.match(kit_dir):
        raise Refusal(f"kit directory {kit_dir!r} must be one directory name at the repository root")
    if path_problem(manifest_rel):
        raise Refusal(f"session-read manifest path {manifest_rel!r} {path_problem(manifest_rel)}")

    # Everything is read and verified before the first byte is written.
    blobs: dict[str, bytes] = {}
    for rel, recorded in sorted(files.items()):
        blob = standard.blob(commit, f"{STANDARD_KIT_DIR}/{rel}")
        if blob is None or kit_hash(blob) != recorded:
            raise Refusal(
                f"the standard at {commit[:12]} is inconsistent: {STANDARD_KIT_DIR}/{rel} does not match "
                f"{KIT_MANIFEST_REL}; nothing was written"
            )
        blobs[rel] = blob
    for rel in REQUIRED_KIT_FILES:
        if rel not in blobs:
            raise Refusal(f"the standard at {commit[:12]} has no kit file {rel}; nothing was written")

    workflows: dict[str, dict] = dict(old["workflows"]) if old else {}
    rendered: dict[str, bytes] = {}
    wanted = set(REQUIRED_WORKFLOWS) if old is None else set()
    if render_workflows:
        wanted |= set(REQUIRED_WORKFLOWS) | set(workflows)
    if with_update_workflow:
        wanted.add(UPDATE_WORKFLOW)
    for dest in sorted(wanted):
        rendered[dest] = render(blobs[WORKFLOW_TEMPLATES[dest]], commit, kit_dir)
        workflows[dest] = {"template": WORKFLOW_TEMPLATES[dest], "commit": commit, "sha256": kit_hash(rendered[dest])}

    for rel, blob in blobs.items():
        path = consumer / kit_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    removed = sorted(set(old["files"]) - set(blobs)) if old else []
    for rel in removed:
        path = consumer / kit_dir / rel
        if path.is_file():
            path.unlink()
    for dest, content in rendered.items():
        path = consumer / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (consumer / PIN_REL).write_bytes(pin_bytes(version, commit, kit_dir, manifest_rel, files, workflows))

    before = f"{old['standard']['version']} -> " if old else ""
    lines = [
        f"INSTALLED: MenQ Standard {before}{version} @ {commit}",
        f"kit: {len(blobs)} files written to {kit_dir}/" + (f", {len(removed)} removed ({', '.join(removed)})" if removed else ""),
        f"pin: {PIN_REL}",
    ]
    lines += [f"workflow rendered: {dest}" for dest in sorted(rendered)]
    kept = sorted(set(workflows) - set(rendered))
    if kept:
        lines.append(f"workflows left as they were: {', '.join(kept)} (re-render with --render-workflows and push as a person)")
    if not (consumer / manifest_rel).is_file():
        lines.append(f"NOT DONE: {manifest_rel} does not exist; `check` is RED until the repository writes its session-read manifest")
    return lines


# ================================================================================================
# changelog
# ================================================================================================


def changelog_since(text: str, since: str) -> str:
    """The entries of a newest-first changelog above the first heading naming a version <= since."""
    floor = parse_version(since)
    if floor is None:
        raise Refusal(f"--since {since!r} is not MAJOR.MINOR.PATCH")
    lines = text.replace("\r\n", "\n").split("\n")
    start = next((index for index, line in enumerate(lines) if line.startswith("## ")), None)
    if start is None:
        raise Refusal(f"{CHANGELOG_REL} has no '## ' entry")
    for index in range(start, len(lines)):
        match = VERSION_HEADING.match(lines[index])
        if match and parse_version(match.group(1)) <= floor:
            return "\n".join(lines[start:index]).strip("\n") + "\n" if index > start else ""
    raise Refusal(
        f"{CHANGELOG_REL} has no heading naming MenQ Standard v{since} or older, so the entries newer than it cannot be cut"
    )


# ================================================================================================
# Command line
# ================================================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, summary: str, consumer: bool = True, standard: str = "optional") -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=summary, description=summary)
        if consumer:
            sub.add_argument("--consumer", type=Path, default=Path.cwd(), help="the repository (default: the current directory)")
        if standard != "none":
            sub.add_argument("--standard", type=Path, required=standard == "required", help="a git checkout of MenQ Standard")
            sub.add_argument("--standard-ref", default="HEAD", help="the ref of the standard to judge against (default: HEAD)")
        return sub

    add("check", "is the repository conformant?")
    add("status", "is the pin behind the standard?", standard="required")
    installer = add("install", "copy the kit and write the pin", standard="required")
    installer.add_argument("--kit-dir", help=f"directory for the kit (default: {DEFAULT_KIT_DIR}, or the pinned one)")
    installer.add_argument("--manifest", help=f"session-read manifest path (default: {DEFAULT_MANIFEST_REL}, or the pinned one)")
    installer.add_argument("--with-update-workflow", action="store_true", help=f"also render {UPDATE_WORKFLOW}")
    installer.add_argument("--render-workflows", action="store_true", help="re-render the workflows at the new commit")
    log = add("changelog", "print the standard's changelog entries newer than a version", consumer=False, standard="required")
    log.add_argument("--since", required=True, help="the version the repository is pinned to")
    add("pin-commit", "print the pinned commit once it is proven to be on the standard's ref", standard="required")

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    try:
        consumer = args.consumer.resolve() if hasattr(args, "consumer") else None
        standard = Standard(args.standard.resolve(), args.standard_ref) if getattr(args, "standard", None) else None

        if args.command == "check":
            errors, report = check(consumer, standard)
            if errors:
                print("MENQ STANDARD CONFORMANCE: RED")
                for error in errors:
                    print(f"- {error}")
                return 1
            print("MENQ STANDARD CONFORMANCE: GREEN")
            for line in report:
                print(line)
            return 0

        if args.command == "status":
            code, lines = status(consumer, standard)
            print("\n".join(lines))
            return code

        if args.command == "install":
            lines = install(consumer, standard, args.kit_dir, args.manifest, args.with_update_workflow, args.render_workflows)
            print("\n".join(lines))
            return 0

        if args.command == "changelog":
            blob = standard.blob(standard.ref_commit, CHANGELOG_REL)
            if blob is None:
                raise Refusal(f"the standard at {standard.ref} has no {CHANGELOG_REL}")
            sys.stdout.write(changelog_since(blob.decode("utf-8", "replace"), args.since))
            return 0

        # pin-commit: stdout carries the commit and nothing else, so every reason goes to stderr.
        pin, errors = load_pin(consumer)
        if pin is not None:
            commit = pin["standard"]["commit"]
            if not standard.has_commit(commit):
                errors = [f"pin names a commit that does not exist in the standard: {commit}"]
            elif not standard.is_ancestor(commit, standard.ref_commit):
                errors = [f"pin names a commit that is not on the standard's {standard.ref}: {commit}"]
        if errors:
            print("MENQ STANDARD CONFORMANCE: RED", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print(pin["standard"]["commit"])
        return 0
    except (Refusal, OSError) as refusal:
        # stdout of these two commands is data another program reads, so the reason goes to stderr.
        stream = sys.stderr if args.command in ("pin-commit", "changelog") else sys.stdout
        print(f"MENQ STANDARD {VERDICT_NAME[args.command]}: RED", file=stream)
        print(f"- {refusal}", file=stream)
        return 1


if __name__ == "__main__":
    sys.exit(main())
