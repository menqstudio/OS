# BroPS — release / installer / updater setup

> What is CONFIGURED in the repo vs what the **Owner must provide** (secrets) to cut a signed, auto-updating
> v1 release. Nothing here weakens the security chain: a release is gated on the same fail-closed rules
> (`NoTrustedManifest` until the governed chain is code-audit GREEN + running).

## 1. Installer bundle — CONFIGURED (`apps/desktop/src-tauri/tauri.conf.json`)
- `productName` BroPS · `version` 0.1.0 · `identifier` `studio.menq.brops`
- `bundle`: `targets: "all"` (Windows NSIS/MSI, macOS `.app`/`.dmg`, Linux `.deb`/`.AppImage`), icons,
  publisher, category, short/long description, copyright, homepage.
- Build: `cd apps/desktop && npm ci && npm run tauri build` → installers in `src-tauri/target/release/bundle/`.

## 2. Code signing — OWNER PROVIDES (secrets)
Unsigned installers trip OS SmartScreen/Gatekeeper. To ship trusted binaries:
- **Windows** — an Authenticode code-signing certificate (`.pfx` + password) → set
  `bundle.windows.certificateThumbprint` (or sign in CI with `signtool`). Owner provides the cert.
- **macOS** — an Apple Developer ID Application cert + notarization (`APPLE_CERTIFICATE`,
  `APPLE_ID`, `APPLE_PASSWORD`, team id) → CI secrets. Owner provides the Apple account.
- **Linux** — no OS signing required (optionally GPG-sign the repo/AppImage).

## 3. Auto-updater — OWNER PROVIDES the signing keypair, then CONFIGURED
Tauri's updater signs each release so the app only installs Owner-signed updates:
1. `npm run tauri signer generate -- -w ~/.tauri/brops.key` → prints a **public key** + writes the private key.
2. **Public key** → `tauri.conf.json` `plugins.updater.pubkey` (safe to commit).
3. **Private key** → CI secret `TAURI_SIGNING_PRIVATE_KEY` (+ `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). NEVER commit it.
4. Set `bundle.createUpdaterArtifacts: true` and `plugins.updater.endpoints` to the release manifest URL
   (e.g. a GitHub Releases `latest.json`). Add the `@tauri-apps/plugin-updater` dep + the Rust
   `tauri-plugin-updater` init.
> Deferred here because it requires the Owner's private key — the config slot is documented, not stubbed
> with a fake key (a bad pubkey would break the build).

## 4. Release CI (to add once signing secrets exist)
A `release.yml` (tag-triggered) matrix building on windows/macos/linux runners, signing, and publishing the
installers + `latest.json` to GitHub Releases. Gated on the full CI suite green.

## 5. Release GATE (fail-closed — do NOT ship until all hold)
- The full CI suite is green (supply-chain, a11y, perf, ai-surface, coordination, repo-state, cargo, frontend).
- The **3b-1B implementation is Architect CODE-audit GREEN** and the governed chain runs end-to-end on Linux
  (the isolation proof passes) — see `WAVE_3B1B_IMPL_CODE_AUDIT_REQUEST.md`.
- **3b-2/3b-3** landed → the app can render a real production `trusted_verified` (until then `NoTrustedManifest`
  stays fail-closed and no "Verified" is production).
- Installers are code-signed + the updater is Owner-key-signed.

A release that skips the security gate would ship an app that can display "Verified" it cannot honestly back —
that is exactly the fail-closed condition this whole design prevents.
