#!/usr/bin/env python3
"""The desktop app's version is written out five times in four files, and nothing held them equal.

**What this refuses, and why.** `apps/desktop` states one product version in five declarations
across four files, and no tool reconciles them:

  * `apps/desktop/package.json` -> `.version`            (what npm and the frontend report)
  * `apps/desktop/src-tauri/tauri.conf.json` -> `.version` (what the INSTALLER carries: CFBundle-
    ShortVersionString on macOS, the NSIS/MSI product version on Windows, the `.deb` version)
  * `apps/desktop/src-tauri/Cargo.toml` -> `[package] version` (what `CARGO_PKG_VERSION` compiles
    into the host binary)
  * `apps/desktop/package-lock.json` -> `.version` AND `.packages[""].version` (two of them)

At the head this gate was written all five say `0.1.0`, so the drift has never happened. It also
could not have been caught: no workflow, script or hook reads any of these fields
(`grep -n version tools/check_release_signing.py` prints nothing, and that is the one gate that
opens `tauri.conf.json` at all), and **`npm ci` does not care** -- measured, not assumed: a probe
package with `package.json` at `9.9.9` and its lock at `0.1.0` printed `up to date, audited 1
package` and exited 0. So the first bump that touches three files out of four ships an installer
whose version disagrees with the binary inside it, and every check in this repository stays green.

Tauri offers two ways not to have this problem, and the repository uses neither. `tauri-utils`
documents the field as *"a semver version number **or a path to a `package.json` file** containing
the `version` field. If removed the version number from `Cargo.toml` is used."* Adopting either is
a build-behaviour change to the shipped bundle; holding the copies equal is not. This gate does the
second and names the first as the real remedy.

WHAT IS CHECKED
  1. all five declarations parse and carry a version string                          -> else RED
  2. the declared strings are BYTE-IDENTICAL to each other                           -> else RED,
     naming every file that disagrees, the string it carries, and the majority it disagrees with
  3. the string is a bare `MAJOR.MINOR.PATCH` semver core -- what every one of the four
     consumers above accepts without translation                                     -> else RED

WHAT IS **NOT** CHECKED, AND WHY NOT -- THE GIT-TAG QUESTION
  `.github/workflows/release.yml` triggers on `push: tags: v*`. This gate does **not** require a
  `v*` tag to equal these strings, because answering that needs a release policy the Owner
  has not stated anywhere in this repository, and guessing it would put a rule in CI that nobody
  decided.

  The facts, measured at this head:
    * `git tag -l` prints exactly one tag, `brops-desktop-v0.1.0` (commit `fb304a2`, 2026-08-04),
      which came in with the BroPS subtree. `git tag -l 'v*'` prints nothing, so `release.yml`
      has never been triggered by a tag and its `preflight` refusal has never run.
    * `OWNERS.md`: *"Release and tagging stay the Owner's alone"* -- the 2026-08-14 §B.5
      delegation covers push and merge and nothing further.
    * `docs/RELEASE_SETUP.md` §5 puts the release gate on human/audit judgement, *"enforced
      before tagging, not by this file"*.
    * There is no CHANGELOG, no versioning policy document, and no script that bumps anything
      (`grep -rn 'npm version|cargo set-version' .github/workflows/` finds no bumper).

  The undecided question is what these four files MEAN BETWEEN TAGS, and the two answers give
  opposite gates:
    (a) they hold the LAST RELEASED version -- then `v1.2.3` must equal them at the tagged commit,
        and any commit that bumps them without a tag is RED;
    (b) they hold the NEXT, UNRELEASED version -- then they are *ahead* of the newest tag for the
        whole of normal development, and requiring equality would be RED on almost every commit.
  Nothing in the repository distinguishes (a) from (b). Until the Owner states one, the honest
  gate is the one that checks what is settled: the copies agree with each other. This
  paragraph is the handoff -- when the policy exists, the tag arm goes here.

WHAT IS DELIBERATELY OUT OF SCOPE
  The nine workspace members under `apps/desktop/src-tauri/` (`brops-core`, `brops-broker`, ...)
  each declare `version = "0.1.0"` of their own, and `Cargo.lock` mirrors all ten. Whether a
  library crate's version is the PRODUCT's version is a second unstated policy -- crates version
  independently by default in Cargo -- and binding them here would enforce a coupling nobody
  decided. The host package `brops` is in scope because `tauri.conf.json` sits beside it and
  Tauri falls back to exactly that `[package] version`.

Usage:  python tools/check_version_parity.py [--root DIR]
Exit 0 + "GREEN: ..." / exit 1 + the disagreement, naming names.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

PACKAGE_JSON = "apps/desktop/package.json"
TAURI_CONF = "apps/desktop/src-tauri/tauri.conf.json"
CARGO_TOML = "apps/desktop/src-tauri/Cargo.toml"
PACKAGE_LOCK = "apps/desktop/package-lock.json"

#: A bare semver core. Deliberately no pre-release/build suffix: the Windows MSI product version
#: and the macOS CFBundleShortVersionString are both numeric-triples, so `0.2.0-rc.1` would be
#: silently rewritten by the bundler and the four sources would stop meaning one thing again.
_SEMVER_CORE = re.compile(r"^\d+\.\d+\.\d+$")

#: `version = "0.1.0"` in the FIRST `[package]` table of a Cargo manifest. Anchored to the table
#: because `[workspace.package]`, `[dependencies]` and `[build-dependencies]` all carry a key
#: spelled `version`, and matching the first one in the file would read tauri-build's.
_CARGO_PACKAGE_VERSION = re.compile(
    r"^\[package\][^\[]*?^version\s*=\s*[\"'](?P<v>[^\"']+)[\"']",
    re.MULTILINE | re.DOTALL,
)


def _read_json(root: pathlib.Path, rel: str, problems: list[str]) -> dict | None:
    path = root / rel
    if not path.exists():
        problems.append(f"{rel} is missing — one of the four places the app version is written")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{rel} does not parse: {exc}")
        return None


def declared_versions(root: pathlib.Path, problems: list[str]) -> dict[str, str]:
    """{source label: version string} for every source that could be read.

    A source that cannot be read appends a problem and is absent from the result — it is not
    defaulted to anything. A missing file and an agreeing file are different statements.
    """
    found: dict[str, str] = {}

    pkg = _read_json(root, PACKAGE_JSON, problems)
    if pkg is not None:
        value = pkg.get("version")
        if not isinstance(value, str) or not value:
            problems.append(f'{PACKAGE_JSON}: no string "version" field — npm reports nothing')
        else:
            found[f"{PACKAGE_JSON} .version"] = value

    conf = _read_json(root, TAURI_CONF, problems)
    if conf is not None:
        value = conf.get("version")
        if not isinstance(value, str) or not value:
            # Tauri's own fallback is legal, but it is not what this repository does, and a
            # gate that accepted silence here would accept the field being deleted by accident.
            problems.append(
                f'{TAURI_CONF}: no string "version" field. Tauri would then fall back to '
                f'{CARGO_TOML}, which is a real de-duplication — but adopting it changes what '
                f"the bundler reads, so it is a decision to make on purpose, not by omission"
            )
        else:
            found[f"{TAURI_CONF} .version"] = value

    cargo = root / CARGO_TOML
    if not cargo.exists():
        problems.append(f"{CARGO_TOML} is missing — the host crate the bundle is built from")
    else:
        match = _CARGO_PACKAGE_VERSION.search(cargo.read_text(encoding="utf-8"))
        if match is None:
            problems.append(
                f"{CARGO_TOML}: no `version` key in the [package] table — CARGO_PKG_VERSION "
                f"would not compile the product version into the host binary"
            )
        else:
            found[f"{CARGO_TOML} [package] version"] = match.group("v")

    lock = _read_json(root, PACKAGE_LOCK, problems)
    if lock is not None:
        for label, node in (
            (f"{PACKAGE_LOCK} .version", lock),
            (f'{PACKAGE_LOCK} .packages[""].version', lock.get("packages", {}).get("", {})),
        ):
            value = node.get("version") if isinstance(node, dict) else None
            if not isinstance(value, str) or not value:
                problems.append(f"{label}: absent — npm writes it and npm never checks it back")
            else:
                found[label] = value

    return found


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []
    found = declared_versions(root, problems)

    if len(found) < 2:
        problems.append(
            "fewer than two versions could be read, so there is nothing to compare — "
            "treat every line above as the failure, not this one"
        )
        return problems

    distinct = set(found.values())
    if len(distinct) > 1:
        counts = Counter(found.values())
        # The most common string is the one the disagreement is reported AGAINST. On a tie the
        # lexicographically lowest wins, so the message is deterministic rather than
        # dict-ordering-dependent -- a gate whose text changes between runs on the same tree
        # teaches a reader to skim it.
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        agreeing = sorted(k for k, v in found.items() if v == top)
        for label in sorted(found):
            if found[label] != top:
                problems.append(
                    f"{label} says {found[label]!r}, but {len(agreeing)} of the other sources say "
                    f"{top!r} ({', '.join(agreeing)}). One product, one version: change it in all "
                    f"{len(found)} places in one commit, or adopt Tauri's `version` -> "
                    f"{PACKAGE_JSON} pointer so there is one place to change"
                )

    for label in sorted(found):
        if not _SEMVER_CORE.match(found[label]):
            problems.append(
                f"{label} says {found[label]!r}, which is not a bare MAJOR.MINOR.PATCH. The MSI "
                f"product version and CFBundleShortVersionString are numeric triples, so a suffix "
                f"is rewritten by the bundler and the sources stop meaning one thing"
            )

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail CI when the four declarations of the desktop app version disagree."
    )
    ap.add_argument("--root", default=None, help="repository root (default: this file's repo)")
    args = ap.parse_args(argv)
    root = (
        pathlib.Path(args.root)
        if args.root is not None
        else pathlib.Path(__file__).resolve().parents[1]
    )

    problems = check(root)
    if problems:
        print("RED: the desktop app version does not agree with itself —", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). The four files are {PACKAGE_JSON}, {TAURI_CONF}, "
            f"{CARGO_TOML} and {PACKAGE_LOCK}; see this gate's docstring for why a `v*` git tag "
            f"is NOT one of them.",
            file=sys.stderr,
        )
        return 1

    found = declared_versions(root, [])
    version = next(iter(set(found.values())))
    print(
        f"GREEN: {len(found)} declaration(s) of the desktop app version all say {version!r} "
        f"({', '.join(sorted(found))}); no `v*` git tag is compared, by decision — see the "
        f"docstring."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
