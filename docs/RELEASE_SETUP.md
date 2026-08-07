# BroPS — release / installer / updater setup

> What is CONFIGURED in the repo vs what the **Owner must provide** (secrets) to cut a signed, auto-updating
> v1 release. Nothing here weakens the security chain: a release is gated on the same fail-closed rules
> (`NoTrustedManifest` until the governed chain is code-audit GREEN + running).
>
> **The list of Owner secrets below is machine-enforced.** `tools/check_release_signing.py` holds
> `REQUIRED_OWNER_SECRETS` (the code), `.github/workflows/release.yml` (the workflow), and this document to
> the *same* list — if one drifts, the `Release signing + updater` job in `supply-chain.yml` goes RED. So
> this page can never quietly become out of date about what the Owner has to supply.

## 1. Installer bundle — CONFIGURED (`apps/desktop/src-tauri/tauri.conf.json`)
- `productName` BroPS · `version` 0.1.0 · `identifier` `studio.menq.brops`
- `bundle`: `targets: "all"` (Windows NSIS/MSI, macOS `.app`/`.dmg`, Linux `.deb`/`.AppImage`), icons,
  publisher, category, short/long description, copyright, homepage.
- `bundle.windows`: `digestAlgorithm: "sha256"` and an RFC-3161 `timestampUrl`. These are the two
  Authenticode settings that need **no** Owner secret, and without the timestamp every signature stops
  validating the day the certificate expires. `certificateThumbprint` is deliberately **not** committed —
  see §2.
- Build: `cd apps/desktop && npm ci && npm run tauri build` → installers in `src-tauri/target/release/bundle/`.
  This local build is also how you smoke-test the bundle without secrets; CI no longer produces unsigned
  output (§4).

## 2. Code signing — OWNER PROVIDES (secrets)
Unsigned binaries trip OS SmartScreen/Gatekeeper. To ship trusted binaries:

| Secret | What it is |
|---|---|
| `WINDOWS_CERTIFICATE` | Base64 of the Authenticode code-signing `.pfx` (OV or EV) from a CA — DigiCert, Sectigo, … |
| `WINDOWS_CERTIFICATE_PASSWORD` | Password for that `.pfx`. |
| `APPLE_CERTIFICATE` | Base64 of the *Developer ID Application* `.p12` (needs a paid Apple Developer Program membership). |
| `APPLE_CERTIFICATE_PASSWORD` | Password for that `.p12`. |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: menq studio (TEAMID)`. |
| `APPLE_ID` | Apple ID used for notarization. |
| `APPLE_PASSWORD` | App-specific password for that Apple ID (`notarytool`). |
| `APPLE_TEAM_ID` | Apple Developer team id. |

- **Windows** — the release job imports `WINDOWS_CERTIFICATE` into the runner's store and derives the real
  thumbprint from the certificate the Owner actually supplied, merging it into the Tauri config at build
  time (`--config`). A thumbprint is **not** committed: a thumbprint in the repo names a certificate the
  runner may not hold, and Tauri then emits an unsigned binary while the job stays green.
- **macOS** — `tauri-action` signs and notarizes from the Apple secrets above; the job then runs
  `codesign --verify --strict --deep` and `spctl --assess` on the produced `.app`, so Gatekeeper's own
  verdict — not the build's exit code — is the evidence.
- **Linux** — no OS signing required (optionally GPG-sign the repo/AppImage).

## 3. Auto-updater — OWNER PROVIDES the keypair; the repo enforces the wiring
Tauri's updater signs each release so the app only installs Owner-signed updates.

| Secret | What it is |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | The updater private key (`npm run tauri signer generate -- -w ~/.tauri/brops.key`). |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Password protecting it. Generate the key **with** a password — an empty one is refused. |

Steps once the Owner has the keypair:
1. `cd apps/desktop && npm run tauri signer generate -- -w ~/.tauri/brops.key` → prints a **public key**,
   writes the private key.
2. **Public key** → `tauri.conf.json` `plugins.updater.pubkey` (safe to commit — it is the public half).
3. **Private key** → repository secret `TAURI_SIGNING_PRIVATE_KEY` (+ `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`).
   NEVER commit it.
4. Set `bundle.createUpdaterArtifacts: true` and `plugins.updater.endpoints` to the release-manifest URL
   (an `https://` GitHub Releases `latest.json`).
5. Add `@tauri-apps/plugin-updater` (npm) and `tauri-plugin-updater` (Cargo) and initialise the plugin in
   the Rust entrypoint.

**Today the updater is deliberately UNPROVISIONED** — no `pubkey`, no `createUpdaterArtifacts`, no plugin
dependency. It is not stubbed with a fake key: a placeholder pubkey means the app verifies updates against
a key nobody controls, which is strictly worse than having no updater.

**The half-wired state is what the gate exists to prevent.** `tools/check_release_signing.py` requires the
config to be in exactly one coherent state — *all* of {pubkey, https endpoints, `createUpdaterArtifacts`,
plugin dependency} or *none* of them. Setting only the CI secret, or only the config flag, produces a
release that looks successful and can never update anybody; that combination is RED.

## 4. Release CI — CONFIGURED and FAIL-CLOSED (`.github/workflows/release.yml`)
Tag-triggered (`v*`) matrix build on windows/macos/linux.

- A `preflight` job runs `python tools/check_release_signing.py --require-release-ready` **before anything
  builds**. If any secret in §2/§3 is absent, or the updater config is not fully provisioned, it prints a
  named refusal listing exactly what is missing and exits 1. `build` declares `needs: preflight`, so the
  release stops there.
- **An unsigned build fails; it does not warn.** The previous version of this workflow skipped signing when
  the key was absent and still published a draft release — a green check over a build nobody could trust or
  update. That path is gone.
- After bundling, the job verifies the produced **bytes**: every updater payload must carry a non-empty
  `.sig`; every Windows installer must return `Valid` from `Get-AuthenticodeSignature`; the macOS `.app`
  must pass `codesign --verify` and `spctl --assess`.
- Set the secrets under **Settings → Secrets and variables → Actions → New repository secret**.

## 5. Release GATE (fail-closed — do NOT ship until all hold)
- The full CI suite is green (supply-chain, a11y, perf, ai-surface, coordination, repo-state, cargo, frontend).
- The **3b-1B implementation is Architect CODE-audit GREEN** and the governed chain runs end-to-end on Linux
  (the isolation proof passes) — see `WAVE_3B1B_IMPL_CODE_AUDIT_REQUEST.md`.
- **3b-2/3b-3** landed → the app can render a real production `trusted_verified` (until then `NoTrustedManifest`
  stays fail-closed and no "Verified" is production).
- Installers are code-signed + the updater is Owner-key-signed (§2–§4 — now enforced by CI, not by discipline).
- The residual engine items **O-1 … O-5** are closed or owner-signed-deferred — see
  [`PHASE_10_PRODUCTION_ITEMS.md`](./PHASE_10_PRODUCTION_ITEMS.md).

A release that skips the security gate would ship an app that can display "Verified" it cannot honestly back —
that is exactly the fail-closed condition this whole design prevents.
