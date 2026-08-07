#!/usr/bin/env python3
"""Fail-closed CI gate: release signing + updater configuration can never be half-wired.

**Why this exists.** Phase 10's "signed, updatable build" has two halves that must move
together, and the failure mode when they do not is SILENT:

  * The Owner sets `TAURI_SIGNING_PRIVATE_KEY` in CI but `tauri.conf.json` carries no
    `plugins.updater.pubkey` and no `bundle.createUpdaterArtifacts` — Tauri then produces
    **no updater artifacts at all**, never touches the key, and the release looks
    successful. Every user is on a build that can never update.
  * The Owner sets `bundle.windows.certificateThumbprint` but the certificate is not in the
    runner's store — Tauri emits an unsigned binary and the job stays green.
  * A `pubkey` placeholder ("REPLACE_ME", a docs example key) is committed to unblock a
    build. Now the app trusts a key nobody controls, or trusts nothing while claiming to.

None of those are visible in a diff review, because each half is individually plausible.
This gate encodes the COUPLING, with no network access and no secret material:

  1. `apps/desktop/src-tauri/tauri.conf.json` must be in exactly ONE coherent updater state —
     fully UNPROVISIONED or fully PROVISIONED. Any mixture is RED, and the RED names the
     exact half that is missing.
  2. A committed updater `pubkey` must be a real minisign/Tauri public key (base64 that
     decodes to a `minisign public key` block) and must not be a placeholder token.
  3. No private key material may appear in the Tauri config.
  4. `bundle.windows.certificateThumbprint`, if committed, must be a real 40-hex thumbprint.
     Authenticode timestamping (`timestampUrl`) and `digestAlgorithm` must be configured, so
     a signature outlives the certificate that made it.
  5. `.github/workflows/release.yml` must run THIS gate in `--require-release-ready` mode
     before it can build, must name every Owner secret, and its build job must depend on
     that preflight. A release workflow that can publish without the preflight is RED.
  6. `docs/RELEASE_SETUP.md` must name every Owner secret this gate requires, so the
     "what must the Owner provide" list cannot drift away from what CI enforces.

Modes
-----
`python tools/check_release_signing.py`
    Repository-consistency mode (runs on every PR). Verifies 1-6.

`python tools/check_release_signing.py --require-release-ready`
    Release preflight (runs inside `release.yml`, before any build step). Additionally
    requires the updater to be PROVISIONED and every Owner secret to be present and
    non-empty in the environment. Prints a LOUD, NAMED refusal listing exactly what is
    missing. Secret NAMES only are printed — never a value, never a prefix of a value.

`python tools/check_release_signing.py --verify-updater-signatures <bundle-dir>`
    Post-build verification. Every updater artifact must have a non-empty sibling `.sig`.
    An unsigned build fails here; it never warns.

Exit 0 = pass. Exit 1 = a violation. No other outcome.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys

# --------------------------------------------------------------------------------------
# The Owner-provided material. This tuple is the single source of truth for "what must the
# Owner provide"; release.yml and docs/RELEASE_SETUP.md are both checked against it, so the
# three can never drift apart.
# --------------------------------------------------------------------------------------
#: name -> what it is / where the Owner gets it. Printed verbatim in the refusal.
REQUIRED_OWNER_SECRETS: dict[str, str] = {
    "TAURI_SIGNING_PRIVATE_KEY": (
        "Tauri updater private key — `npm run tauri signer generate`. The matching PUBLIC "
        "key goes into tauri.conf.json `plugins.updater.pubkey`."
    ),
    "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": (
        "Password protecting the updater private key. Generate the key WITH a password; an "
        "empty password is refused here on purpose."
    ),
    "WINDOWS_CERTIFICATE": (
        "Base64 of the Windows Authenticode code-signing .pfx (OV or EV). Owner purchases "
        "from a CA (DigiCert/Sectigo/...); EV requires hardware token handling."
    ),
    "WINDOWS_CERTIFICATE_PASSWORD": "Password for the .pfx above.",
    "APPLE_CERTIFICATE": (
        "Base64 of the Apple 'Developer ID Application' .p12 (needs a paid Apple Developer "
        "Program membership)."
    ),
    "APPLE_CERTIFICATE_PASSWORD": "Password for the .p12 above.",
    "APPLE_SIGNING_IDENTITY": (
        "The identity string, e.g. 'Developer ID Application: <name> (<TEAMID>)'."
    ),
    "APPLE_ID": "Apple ID used for notarization.",
    "APPLE_PASSWORD": "App-specific password for that Apple ID (notarytool).",
    "APPLE_TEAM_ID": "Apple Developer team id.",
}

#: Tokens that betray a placeholder rather than real key material.
_PLACEHOLDER_TOKENS = (
    "replace",
    "todo",
    "placeholder",
    "changeme",
    "change_me",
    "example",
    "fixme",
    "your-",
    "yourkey",
    "xxxx",
    "dummy",
    "fake",
    "sample",
)

#: Anything that looks like a PRIVATE key must never appear in a committed config.
_PRIVATE_KEY_MARKERS = (
    "-----begin",
    "private key",
    "minisign encrypted secret key",
    "untrusted comment: rsign encrypted secret key",
)

_THUMBPRINT_RE = re.compile(r"^[0-9A-Fa-f]{40}$")

#: Extensions Tauri emits as UPDATER payloads. Each must be accompanied by `<name>.sig`.
_UPDATER_SUFFIXES = (
    ".app.tar.gz",
    ".AppImage.tar.gz",
    ".nsis.zip",
    ".msi.zip",
    ".tar.gz",
    ".zip",
)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _load_json(path: pathlib.Path, problems: list[str]) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        problems.append(f"{path}: unreadable ({exc})")
    except json.JSONDecodeError as exc:
        problems.append(f"{path}: is not valid JSON ({exc})")
    return None


def _read_text(path: pathlib.Path, problems: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(f"{path}: unreadable ({exc})")
        return ""


def pubkey_problem(pubkey: str) -> str | None:
    """Return why `pubkey` is not a usable Tauri updater public key, or None if it is.

    A Tauri updater pubkey is base64 of a minisign public-key block:
        untrusted comment: minisign public key <ID>
        RW<base64...>
    A placeholder decodes to something else (or to nothing), which is precisely what we
    must refuse — a placeholder here silently disables update verification.
    """
    if not isinstance(pubkey, str) or not pubkey.strip():
        return "is empty"
    lowered = pubkey.lower()
    for token in _PLACEHOLDER_TOKENS:
        if token in lowered:
            return f"contains the placeholder token {token!r}"
    try:
        decoded = base64.b64decode(pubkey, validate=True).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same verdict
        return f"is not valid base64 ({exc})"
    if "minisign public key" not in decoded.lower():
        return (
            "does not decode to a minisign public-key block — a Tauri updater pubkey is "
            "base64 of the `untrusted comment: minisign public key ...` file"
        )
    body = [ln.strip() for ln in decoded.splitlines() if ln.strip()]
    if len(body) < 2 or not body[1].startswith("RW"):
        return "decodes to a minisign block whose key line does not start with 'RW'"
    return None


# --------------------------------------------------------------------------------------
# rule 1-4: the Tauri config
# --------------------------------------------------------------------------------------
def check_tauri_config(root: pathlib.Path, problems: list[str]) -> str:
    """Verify the config's coupling rules. Returns 'PROVISIONED' | 'UNPROVISIONED' | 'BROKEN'."""
    path = root / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
    raw = _read_text(path, problems)
    conf = _load_json(path, problems) if raw else None
    if conf is None:
        return "BROKEN"

    rel = path.relative_to(root).as_posix()

    # rule 3 — no private key material, ever.
    lowered_raw = raw.lower()
    for marker in _PRIVATE_KEY_MARKERS:
        if marker in lowered_raw:
            problems.append(
                f"{rel}: contains {marker!r} — private key material must NEVER be committed; "
                f"it belongs in the CI secret TAURI_SIGNING_PRIVATE_KEY"
            )

    bundle = conf.get("bundle") or {}
    updater = ((conf.get("plugins") or {}).get("updater")) or {}
    artifacts = bundle.get("createUpdaterArtifacts")
    pubkey = updater.get("pubkey")
    endpoints = updater.get("endpoints")

    has_updater_block = bool(updater)
    has_artifacts = bool(artifacts)
    has_pubkey = bool(pubkey)

    # rule 4 — Windows Authenticode settings.
    windows = bundle.get("windows") or {}
    thumb = windows.get("certificateThumbprint")
    if thumb is not None and not _THUMBPRINT_RE.match(str(thumb)):
        problems.append(
            f"{rel}: bundle.windows.certificateThumbprint {str(thumb)[:8]!r}… is not a 40-hex "
            f"SHA-1 thumbprint — a malformed thumbprint makes Tauri emit an unsigned binary"
        )
    if windows.get("digestAlgorithm") != "sha256":
        problems.append(
            f"{rel}: bundle.windows.digestAlgorithm must be \"sha256\" — SHA-1 Authenticode "
            f"signatures are rejected by current Windows trust policy"
        )
    timestamp_url = str(windows.get("timestampUrl") or "")
    if not timestamp_url:
        problems.append(
            f"{rel}: bundle.windows.timestampUrl is not set — without an RFC-3161 timestamp "
            f"every signature stops validating the day the certificate expires"
        )

    # rule 1/2 — the updater halves must move together.
    if not has_updater_block and not has_artifacts:
        return "UNPROVISIONED"

    state_ok = True
    if has_pubkey:
        why = pubkey_problem(str(pubkey))
        if why:
            problems.append(
                f"{rel}: plugins.updater.pubkey {why} — a placeholder or malformed pubkey "
                f"silently disables update signature verification"
            )
            state_ok = False
    else:
        problems.append(
            f"{rel}: plugins.updater is configured but `pubkey` is missing/empty — the app "
            f"would install updates without verifying a signature"
        )
        state_ok = False

    if not has_artifacts:
        problems.append(
            f"{rel}: plugins.updater is configured but bundle.createUpdaterArtifacts is not "
            f"true — Tauri would produce NO updater payloads, so the signing key is never "
            f"used and no user can ever receive an update (the silent half-wired release)"
        )
        state_ok = False
    if has_artifacts and not has_updater_block:
        problems.append(
            f"{rel}: bundle.createUpdaterArtifacts is true but plugins.updater is absent — "
            f"updater payloads would ship with no pubkey to verify them against"
        )
        state_ok = False

    if not isinstance(endpoints, list) or not endpoints:
        problems.append(
            f"{rel}: plugins.updater.endpoints must be a non-empty list (the release manifest "
            f"URL, e.g. the GitHub Releases latest.json)"
        )
        state_ok = False
    else:
        for endpoint in endpoints:
            if not str(endpoint).lower().startswith("https://"):
                problems.append(
                    f"{rel}: plugins.updater endpoint {endpoint!r} is not https:// — an "
                    f"update manifest fetched over plaintext is attacker-controlled"
                )
                state_ok = False

    # The runtime half: the plugin must actually be linked in, or the config is decoration.
    cargo = _read_text(root / "apps" / "desktop" / "src-tauri" / "Cargo.toml", problems)
    if "tauri-plugin-updater" not in cargo:
        problems.append(
            "apps/desktop/src-tauri/Cargo.toml: plugins.updater is configured but the "
            "`tauri-plugin-updater` crate is not a dependency — nothing in the app can "
            "check for or verify an update"
        )
        state_ok = False

    return "PROVISIONED" if state_ok else "BROKEN"


# --------------------------------------------------------------------------------------
# rule 5-6: the workflow and the doc must agree with this file
# --------------------------------------------------------------------------------------
def check_release_workflow(root: pathlib.Path, problems: list[str]) -> None:
    path = root / ".github" / "workflows" / "release.yml"
    text = _read_text(path, problems)
    if not text:
        problems.append(".github/workflows/release.yml: missing — there is no release path to gate")
        return
    rel = ".github/workflows/release.yml"

    if "check_release_signing.py --require-release-ready" not in text:
        problems.append(
            f"{rel}: no step runs `python tools/check_release_signing.py "
            f"--require-release-ready` — without the preflight the workflow can publish a "
            f"release whose signing material was never checked"
        )
    if not re.search(r"^\s{2}preflight:\s*$", text, re.MULTILINE):
        problems.append(f"{rel}: no `preflight:` job — the refusal must be its own job")
    if not re.search(r"^\s+needs:\s*(\[\s*)?preflight", text, re.MULTILINE):
        problems.append(
            f"{rel}: the build job does not declare `needs: preflight` — a build that does "
            f"not depend on the preflight can run (and publish) when it fails"
        )
    if re.search(r"continue-on-error:\s*true", text):
        problems.append(
            f"{rel}: contains `continue-on-error: true` — a release step that is allowed to "
            f"fail is not a gate"
        )
    for phrase in ("skips signing rather than failing", "unsigned installers"):
        if phrase in text:
            problems.append(
                f"{rel}: still documents the old behaviour {phrase!r}; an unsigned build must "
                f"fail, not warn"
            )
    for name in REQUIRED_OWNER_SECRETS:
        if name not in text:
            problems.append(
                f"{rel}: Owner secret {name} is required by tools/check_release_signing.py but "
                f"never referenced by the workflow"
            )


def check_release_doc(root: pathlib.Path, problems: list[str]) -> None:
    path = root / "docs" / "RELEASE_SETUP.md"
    text = _read_text(path, problems)
    if not text:
        problems.append("docs/RELEASE_SETUP.md: missing — the Owner has nothing to act on")
        return
    for name in REQUIRED_OWNER_SECRETS:
        if name not in text:
            problems.append(
                f"docs/RELEASE_SETUP.md: does not name the Owner secret {name}, which CI "
                f"requires — the 'what the Owner must provide' list has drifted"
            )


# --------------------------------------------------------------------------------------
# preflight mode
# --------------------------------------------------------------------------------------
def missing_secrets(env: dict[str, str] | None = None) -> list[str]:
    """Names (never values) of Owner secrets that are absent or empty in the environment."""
    source = os.environ if env is None else env
    return [name for name in REQUIRED_OWNER_SECRETS if not (source.get(name) or "").strip()]


def render_refusal(missing: list[str], state: str) -> str:
    lines = [
        "",
        "=" * 78,
        "RELEASE REFUSED — the Owner's signing material is not present.",
        "=" * 78,
        "",
        "This is a fail-closed refusal, not a warning. No installer, no draft release, and",
        "no updater payload is produced. An unsigned build must never leave this workflow.",
        "",
    ]
    if state != "PROVISIONED":
        lines += [
            f"CONFIG state: {state} (required: PROVISIONED)",
            "",
            "  apps/desktop/src-tauri/tauri.conf.json must carry, together:",
            "    - plugins.updater.pubkey       = the PUBLIC half of TAURI_SIGNING_PRIVATE_KEY",
            "    - plugins.updater.endpoints    = [ \"https://.../latest.json\" ]",
            "    - bundle.createUpdaterArtifacts = true",
            "    - apps/desktop/src-tauri/Cargo.toml must depend on `tauri-plugin-updater`",
            "",
        ]
    if missing:
        lines += [f"MISSING repository secrets ({len(missing)}):", ""]
        for name in missing:
            lines.append(f"  - {name}")
            lines.append(f"      {REQUIRED_OWNER_SECRETS[name]}")
        lines.append("")
    lines += [
        "Set them under: Settings -> Secrets and variables -> Actions -> New repository secret.",
        "Full instructions, including how to generate each one: docs/RELEASE_SETUP.md.",
        "",
        "Do NOT work around this by disabling the check or committing a placeholder key:",
        "a placeholder pubkey means the app verifies updates against a key nobody controls.",
        "=" * 78,
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# artifact verification mode
# --------------------------------------------------------------------------------------
def unsigned_updater_artifacts(bundle_dir: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (updater_artifacts, unsigned) — an updater payload with no non-empty `.sig`."""
    found: list[str] = []
    unsigned: list[str] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file() or path.suffix == ".sig":
            continue
        name = path.name
        if not any(name.endswith(suffix) for suffix in _UPDATER_SUFFIXES):
            continue
        found.append(name)
        sig = path.with_name(name + ".sig")
        if not sig.is_file() or sig.stat().st_size == 0:
            unsigned.append(name)
    return found, unsigned


# --------------------------------------------------------------------------------------
def check(root: pathlib.Path) -> tuple[list[str], str]:
    problems: list[str] = []
    state = check_tauri_config(root, problems)
    check_release_workflow(root, problems)
    check_release_doc(root, problems)
    return problems, state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-release-ready",
        action="store_true",
        help="release preflight: additionally require PROVISIONED config + every Owner secret",
    )
    parser.add_argument(
        "--verify-updater-signatures",
        metavar="BUNDLE_DIR",
        help="post-build: every updater payload under BUNDLE_DIR must carry a non-empty .sig",
    )
    parser.add_argument("--root", default=None, help="repository root (default: this file's repo)")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parents[1]

    if args.verify_updater_signatures:
        bundle_dir = pathlib.Path(args.verify_updater_signatures)
        if not bundle_dir.is_dir():
            print(f"RED: bundle directory {bundle_dir} does not exist — nothing was built")
            return 1
        found, unsigned = unsigned_updater_artifacts(bundle_dir)
        if not found:
            print(
                f"RED: no updater payloads under {bundle_dir} — the release produced nothing "
                f"an installed app could ever update to (bundle.createUpdaterArtifacts)"
            )
            return 1
        if unsigned:
            print("RED: updater payload(s) shipped WITHOUT a signature:")
            for name in unsigned:
                print(f"  - {name} (expected {name}.sig)")
            return 1
        print(f"GREEN: {len(found)} updater payload(s), each with a non-empty .sig")
        return 0

    problems, state = check(root)

    if args.require_release_ready:
        missing = missing_secrets()
        if missing or state != "PROVISIONED":
            for p in problems:
                print(f"  - {p}")
            print(render_refusal(missing, state))
            return 1

    if problems:
        print("RED: release signing / updater gate failed")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(
        f"GREEN: release signing gate consistent (updater state: {state}; "
        f"{len(REQUIRED_OWNER_SECRETS)} Owner secrets declared, named in release.yml and "
        f"docs/RELEASE_SETUP.md)"
    )
    if state == "UNPROVISIONED":
        print(
            "  note: the updater is deliberately UNPROVISIONED — it needs the Owner's "
            "keypair. release.yml refuses to release until it is PROVISIONED; see "
            "docs/PHASE_10_PRODUCTION_ITEMS.md."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
