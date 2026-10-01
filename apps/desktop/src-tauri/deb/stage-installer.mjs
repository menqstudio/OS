#!/usr/bin/env node
// stage-installer.mjs — `build.beforeBundleCommand` of tauri.conf.json.
//
// WHY THIS EXISTS
// ---------------
// The .deb's `postinst` runs `/usr/lib/brops/brops-install`, and the package ships the root
// anchor installer beside it as `/usr/lib/brops/brops_install_anchor`. That binary is a bin of
// the `brops-provision` crate, and `tauri build` does NOT build it: measured 2026-10-01 with
// tauri-cli 2.11.4, a full `tauri build --debug --bundles deb` left exactly one executable in
// `target/debug/` — `brops`. So something has to build it before the bundler looks for it.
//
// `bundle.linux.deb.files` takes one fixed source path per destination, and cargo's output path
// is not fixed: it moves with the profile (`debug`/`release`), with `--target <triple>` and with
// `CARGO_TARGET_DIR`. This script builds the bin with the profile and target the Tauri CLI
// reports through `TAURI_ENV_DEBUG` / `TAURI_ENV_TARGET_TRIPLE`, asks cargo where the executable
// landed (`--message-format=json`, never a guessed path), and copies it to the one fixed path
// the config names: `src-tauri/target/deb-stage/brops_install_anchor`, mode 0755.
//
// Measured with the same CLI: the hook runs with cwd `apps/desktop`, after the application is
// built and before any bundle is assembled, and a file it creates is picked up by `deb.files`.
// The bundler writes a 0775 source into the package as 0755 and a 0664 one as 0644.
//
// WHAT IT REFUSES
// ---------------
// The stage directory is deleted before anything else on Linux, so a failed build can never
// leave a previous run's binary for the bundler to ship. Any failure — cargo, no executable
// reported, an empty file — is a non-zero exit.
//
// Off Linux there is no .deb and nothing to stage: exit 0, touching nothing. The release
// workflow runs this same hook on Windows and macOS.
//
//   node src-tauri/deb/stage-installer.mjs                 # what the hook runs
//   node src-tauri/deb/stage-installer.mjs --print-stage   # the staged path, relative to src-tauri

import { spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, mkdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PACKAGE = 'brops-provision';
const BIN = 'brops_install_anchor';
// Relative to src-tauri, and `/`-separated: this is the string tauri.conf.json carries.
const STAGE_REL = `target/deb-stage/${BIN}`;

const SRC_TAURI = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const STAGED = join(SRC_TAURI, ...STAGE_REL.split('/'));

function fail(why) {
  console.error(`stage-installer: FAILED — ${why}`);
  process.exit(1);
}

if (process.argv.includes('--print-stage')) {
  console.log(STAGE_REL);
  process.exit(0);
}

const platform = process.env.TAURI_ENV_PLATFORM ?? process.platform;
if (platform !== 'linux') {
  console.error(`stage-installer: platform is ${platform}, not linux — no .deb, nothing staged`);
  process.exit(0);
}

// First, so nothing stale survives a failure below.
rmSync(dirname(STAGED), { recursive: true, force: true });

const debug = process.env.TAURI_ENV_DEBUG === 'true';

// `--target` only when the CLI is building for something other than this host: for a host
// build cargo then shares the dependency artifacts `tauri build` just produced.
const rustc = spawnSync('rustc', ['-vV'], { encoding: 'utf8' });
if (rustc.status !== 0) fail(`rustc -vV did not run: ${rustc.error ?? rustc.stderr}`);
const host = /^host:\s*(\S+)$/m.exec(rustc.stdout)?.[1];
if (!host) fail('rustc -vV printed no host triple');
const target = process.env.TAURI_ENV_TARGET_TRIPLE;

const args = [
  'build',
  '--manifest-path', join(SRC_TAURI, 'Cargo.toml'),
  '-p', PACKAGE,
  '--bin', BIN,
  '--message-format=json-render-diagnostics',
];
if (!debug) args.push('--release');
if (target && target !== host) args.push('--target', target);

console.error(`stage-installer: cargo ${args.join(' ')}`);
const cargo = spawnSync('cargo', args, {
  cwd: SRC_TAURI,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'inherit'],
  maxBuffer: 256 * 1024 * 1024,
});
if (cargo.status !== 0) {
  fail(`cargo exited ${cargo.status ?? cargo.signal}${cargo.error ? `: ${cargo.error}` : ''}`);
}

let executable = null;
for (const line of cargo.stdout.split('\n')) {
  if (!line.startsWith('{')) continue;
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    continue;
  }
  if (
    message.reason === 'compiler-artifact' &&
    message.target?.name === BIN &&
    message.target?.kind?.includes('bin') &&
    message.executable
  ) {
    executable = message.executable;
  }
}
if (!executable) fail(`cargo reported no executable for the bin ${BIN} of ${PACKAGE}`);

mkdirSync(dirname(STAGED), { recursive: true });
copyFileSync(executable, STAGED);
chmodSync(STAGED, 0o755);

const staged = statSync(STAGED);
if (!staged.isFile() || staged.size === 0) fail(`${STAGED} is not a non-empty file after the copy`);
if ((staged.mode & 0o777) !== 0o755) {
  fail(`${STAGED} is mode ${(staged.mode & 0o777).toString(8)}, not 755`);
}
console.error(
  `stage-installer: staged ${executable} -> ${STAGED} (${staged.size} bytes, ${debug ? 'debug' : 'release'})`,
);
