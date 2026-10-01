// @vitest-environment node
//
// What the .deb is configured to carry — held without a build and without root.
//
// The package's `postinst` hands the whole install to `/usr/lib/brops/brops-install`. Whether
// that file is IN the package is decided by three strings in three files: the default path in
// `deb/postinst`, a key of `bundle.linux.deb.files` in tauri.conf.json, and the path the
// `beforeBundleCommand` helper stages the anchor binary at. Any one of them can drift alone and
// nothing fails: the bundler ships whatever the map says, and a `postinst` that finds no
// installer exits 0 saying trust is not provisioned.
//
// This file holds the strings to each other. It does NOT prove the built package: only
// `tauri build --bundles deb` followed by `dpkg-deb -c` / `dpkg-deb -e` does that.

import { describe, it, expect } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const DESKTOP = resolve(HERE, '../..');
const SRC_TAURI = resolve(DESKTOP, 'src-tauri');
const REPO_ROOT = resolve(DESKTOP, '../..');

const INSTALLER_DEST = '/usr/lib/brops/brops-install';
const ANCHOR_DEST = '/usr/lib/brops/brops_install_anchor';
const HELPER = 'src-tauri/deb/stage-installer.mjs';

const config = JSON.parse(readFileSync(resolve(SRC_TAURI, 'tauri.conf.json'), 'utf8'));
const deb = config.bundle?.linux?.deb ?? {};
const files: Record<string, string> = deb.files ?? {};

/** The helper, run the way the hook runs it, with an environment of our choosing. */
const runHelper = (args: string[], env: Record<string, string>) =>
  spawnSync(process.execPath, [resolve(DESKTOP, HELPER), ...args], { encoding: 'utf8', env });

describe('the .deb carries the installer its postinst runs', () => {
  it('names a postinst that exists', () => {
    expect(deb.postInstallScript).toBe('deb/postinst');
    expect(statSync(resolve(SRC_TAURI, deb.postInstallScript)).isFile()).toBe(true);
  });

  it("ships a file at the exact path the postinst's default names", () => {
    const postinst = readFileSync(resolve(SRC_TAURI, 'deb/postinst'), 'utf8');
    const match = /^BROPS_INSTALL_BIN="\$\{BROPS_INSTALL_BIN:-([^}]+)\}"$/m.exec(postinst);
    expect(match, 'deb/postinst no longer declares a default BROPS_INSTALL_BIN').not.toBeNull();
    expect(match![1]).toBe(INSTALLER_DEST);
    expect(Object.keys(files)).toContain(match![1]);
  });

  it('takes that file from the one installer script, which is executable', () => {
    const source = resolve(SRC_TAURI, files[INSTALLER_DEST] ?? 'missing');
    expect(source).toBe(resolve(REPO_ROOT, 'engine/install/brops_install.sh'));
    const stat = statSync(source);
    expect(stat.isFile()).toBe(true);
    // The bundler carries the source's mode into the package (measured: 0775 -> 0755,
    // 0664 -> 0644), and the postinst fails the install on a file it cannot execute.
    // Windows has no execute bit to read.
    if (process.platform !== 'win32') expect(stat.mode & 0o100).toBe(0o100);
  });

  it('ships the anchor installer from the path the build hook stages it at', () => {
    const printed = runHelper(['--print-stage'], { PATH: '' });
    expect(printed.status).toBe(0);
    const staged = printed.stdout.trim();
    expect(staged).toBe('target/deb-stage/brops_install_anchor');
    expect(files[ANCHOR_DEST]).toBe(staged);
    // The name staged is the name of a real bin of the provisioning crate.
    expect(existsSync(resolve(SRC_TAURI, 'provision/src/bin/brops_install_anchor.rs'))).toBe(true);
  });

  it('puts everything it ships under /usr/lib/brops and nothing anywhere else', () => {
    expect(Object.keys(files).sort()).toEqual([INSTALLER_DEST, ANCHOR_DEST].sort());
  });

  it('runs the staging helper before bundling, from the directory the hook runs in', () => {
    // Measured with tauri-cli 2.11.4: the hook's cwd is apps/desktop.
    expect(config.build?.beforeBundleCommand).toBe(`node ${HELPER}`);
    expect(statSync(resolve(DESKTOP, HELPER)).isFile()).toBe(true);
  });

  it('stages nothing, and needs no toolchain, where no .deb is built', () => {
    // The release workflow runs the same hook on Windows and macOS. An empty PATH is the
    // proof it reached for neither rustc nor cargo.
    for (const platform of ['windows', 'darwin']) {
      const run = runHelper([], { PATH: '', TAURI_ENV_PLATFORM: platform });
      expect(run.status, run.stderr).toBe(0);
      expect(run.stderr).toContain('nothing staged');
    }
  });
});
