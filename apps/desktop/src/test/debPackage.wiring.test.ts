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
//
// BELOW THE .deb: two more things that are only a property of the FILES, held the same way —
// what `vite.config.ts` lets into the client bundle, and what the stylesheets say when read as
// text. They live in this file rather than one of their own because the number of test files is
// a counted claim in four canonical documents; the suite is the same either way.

import { describe, it, expect } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ratio, type Rgba } from './contrast';

const HERE = dirname(fileURLToPath(import.meta.url));
const DESKTOP = resolve(HERE, '../..');
const SRC_TAURI = resolve(DESKTOP, 'src-tauri');
const REPO_ROOT = resolve(DESKTOP, '../..');
const SRC = resolve(DESKTOP, 'src');

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

const walk = (dir: string): string[] =>
  readdirSync(dir).flatMap((name) => {
    const path = resolve(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });

const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const rel = (path: string) => relative(SRC, path).split('\\').join('/');

const ALL = walk(SRC);
/** Every stylesheet the app ships, comments removed. */
const CSS = new Map(ALL.filter((f) => f.endsWith('.css')).map((f) => [rel(f), stripComments(readFileSync(f, 'utf8'))]));
/** Every shipped script: pages carry `<style>` blocks of their own, and class names live here. */
const SCRIPTS = new Map(
  ALL.filter((f) => /\.tsx?$/.test(f) && !/\.(test|spec)\.tsx?$/.test(f) && !rel(f).startsWith('test/'))
    .map((f) => [rel(f), readFileSync(f, 'utf8')]),
);
const AIOS = CSS.get('theme/aios.css')!;

const KEYFRAMES = /@keyframes\s+([\w-]+)\s*\{/g;
const token = (name: string) => new RegExp(`(?<![\\w-])${name.replace(/[-]/g, '\\-')}(?![\\w-])`, 'g');

/** `{selector: declarations}` for every plain rule, in file order. At-rule preludes are skipped. */
function rules(css: string): Array<{ selectors: string[]; body: string }> {
  const out: Array<{ selectors: string[]; body: string }> = [];
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const prelude = m[1].trim();
    if (prelude.startsWith('@') || /^(from|to|[\d.,%\s]+)$/.test(prelude)) continue;
    out.push({ selectors: prelude.split(',').map((s) => s.trim()), body: m[2] });
  }
  return out;
}

/** The value of `--name` inside the first block opened by exactly `selector`. */
function declared(css: string, selector: string, name: string): string {
  const at = css.indexOf(`${selector}{`);
  expect(at, `no \`${selector}{\` block`).toBeGreaterThanOrEqual(0);
  const block = css.slice(at, css.indexOf('}', at));
  const m = new RegExp(`${name}\\s*:\\s*([^;]+);`).exec(block);
  expect(m, `${selector} declares no ${name}`).not.toBeNull();
  return m![1].trim();
}

describe('the client bundle carries no variable family that holds a secret', () => {
  // `envPrefix` is the list of process-variable prefixes `import.meta.env` may expose to the
  // renderer. It was ["VITE_", "TAURI_"]; release.yml sets TAURI_SIGNING_PRIVATE_KEY and its
  // password on the step that runs this build.
  const viteConfig = readFileSync(resolve(DESKTOP, 'vite.config.ts'), 'utf8');
  const envPrefix = /^\s*envPrefix:\s*(\[[^\]]*\]|"[^"]*"|'[^']*')/m.exec(viteConfig);
  const prefixes = envPrefix ? [...envPrefix[1].matchAll(/["']([^"']*)["']/g)].map((m) => m[1]) : [];

  it('declares its prefixes explicitly', () => {
    expect(envPrefix, 'vite.config.ts no longer sets envPrefix; this check holds nothing').not.toBeNull();
    expect(prefixes.length).toBeGreaterThan(0);
    // An empty prefix exposes the whole environment.
    expect(prefixes).not.toContain('');
  });

  it('matches no secret the release workflow puts in the build environment', () => {
    const release = readFileSync(resolve(REPO_ROOT, '.github/workflows/release.yml'), 'utf8');
    const secrets = [...new Set([...release.matchAll(/^\s*([A-Z][A-Z0-9_]*):\s*\$\{\{\s*secrets\./gm)].map((m) => m[1]))];
    expect(secrets, 'release.yml names no secret env var; the pattern has stopped matching').toContain('TAURI_SIGNING_PRIVATE_KEY');
    const exposed = secrets.filter((name) => prefixes.some((p) => name.startsWith(p.replace(/\*$/, ''))));
    expect(exposed).toEqual([]);
  });

  it('exposes nothing the renderer does not read', () => {
    // Nothing under src/ reads `import.meta.env`, so the default prefix is the whole list. The day
    // something does, name that variable here and in vite.config.ts — whole, not by family.
    const readers = ALL.filter((f) => /\.tsx?$/.test(f) && !/\.(test|spec)\.tsx?$/.test(f))
      .filter((f) => readFileSync(f, 'utf8').includes('import.meta.env'));
    expect(readers.map(rel)).toEqual([]);
    expect(prefixes).toEqual(['VITE_']);
  });
});

// ── the stylesheets, read as text ──────────────────────────────────────────────────────────────
//
// The unit suite runs with `css: false`, so no jsdom test ever loads a stylesheet, and the browser
// specs measure the pages they visit. Between those two sat a class of mistake that is only a
// property of the files: a name defined twice, a rule that silently replaces another rule's value,
// a token used where its type does not fit. Each check below was written for one that shipped.
// None of them proves what a browser paints.

describe('@keyframes — one namespace per document', () => {
  it('defines no name twice, in any stylesheet or in-component <style>', () => {
    // `global.css` and `aios.css` both defined `shimmer`. styles.css imports aios.css last, so its
    // translate+scale replaced the skeleton's background sweep and every loading bar drifted.
    const seen = new Map<string, string[]>();
    for (const [file, text] of [...CSS, ...SCRIPTS]) {
      for (const m of text.matchAll(KEYFRAMES)) seen.set(m[1], [...(seen.get(m[1]) ?? []), file]);
    }
    const twice = [...seen].filter(([, files]) => files.length > 1).map(([name, files]) => `${name}: ${files.join(', ')}`);
    expect(twice, 'the later @keyframes replaces the earlier one for every rule that names it').toEqual([]);
  });

  it('defines none that nothing animates with', () => {
    // 55 of aios.css's 132 were referenced by nothing — the mockup's, kept after the pages that
    // used them took in-component styles of their own.
    const everything = [...CSS.values(), ...SCRIPTS.values()].join('\n');
    const unused: string[] = [];
    for (const [file, text] of CSS) {
      for (const m of text.matchAll(KEYFRAMES)) {
        // one occurrence is the definition itself
        if ((everything.match(token(m[1])) ?? []).length < 2) unused.push(`${m[1]} (${file})`);
      }
    }
    expect(unused).toEqual([]);
  });
});

describe('the compositor hint leaves every transform where it was', () => {
  it('gives translateZ(0) to no element that has a transform of its own', () => {
    // `transform` does not merge. `.horizon` and `#cursorlight` were in the hint's selector list,
    // and the hint — later, same specificity — replaced the perspective tilt and the cursor follow.
    const all = rules(AIOS);
    const hints = all.filter((r) => /will-change/.test(r.body) && /transform\s*:\s*translateZ\(0\)/.test(r.body));
    expect(hints.length, 'the compositor-hint rule is gone or reworded; this check holds nothing').toBeGreaterThan(0);
    const clobbered: string[] = [];
    for (const hint of hints) {
      for (const selector of hint.selectors) {
        const own = all.find((r) => r !== hint && r.selectors.includes(selector) && /(^|;|\s)transform\s*:/.test(r.body));
        if (own) clobbered.push(selector);
      }
    }
    expect(clobbered).toEqual([]);
  });

  it('still has the two transforms the hint used to replace', () => {
    const transformOf = (selector: string) =>
      rules(AIOS).filter((r) => r.selectors.includes(selector)).map((r) => /transform\s*:\s*([^;]+)/.exec(r.body)?.[1]).filter(Boolean);
    expect(transformOf('.horizon')).toEqual(['perspective(340px) rotateX(62deg)']);
    expect(transformOf('#cursorlight')).toHaveLength(1);
    expect(transformOf('#cursorlight')[0]).toMatch(/^translate3d\(calc\(var\(--cx/);
  });
});

describe('motion tokens are used as the type they are', () => {
  // --fast / --slow / --enter are `<time> <easing>`; --spring is an easing alone.
  const TIMED = ['--fast', '--slow', '--enter'];
  const items = [...CSS].flatMap(([file, text]) =>
    [...text.matchAll(/(?:animation|transition)\s*:\s*([^;}]+)/g)].flatMap((m) =>
      // split the list on commas that are not inside parentheses
      m[1].split(/,(?![^(]*\))/).map((item) => ({ file, item: item.trim() }))));
  const explicitTime = (s: string) => /(?<![\w.-])\d*\.?\d+m?s\b/.exec(s.replace(/var\([^)]*\)/g, (v) => ' '.repeat(v.length)));

  it('declares each token with the shape this file assumes', () => {
    const root = AIOS.slice(AIOS.indexOf(':root{'));
    for (const name of TIMED) expect(new RegExp(`${name}:\\d+ms cubic-bezier\\(`).test(root), name).toBe(true);
    expect(/--spring:cubic-bezier\(/.test(root)).toBe(true);
  });

  it('never puts an explicit time in front of a token that carries one', () => {
    // `animation:sheen .85s var(--enter)` — the second <time> in an item is the DELAY, so every
    // card hover waited 640ms before its sheen.
    const bad = items.filter(({ item }) => TIMED.some((name) => {
      const at = item.indexOf(`var(${name})`);
      const time = explicitTime(item);
      return at >= 0 && time !== null && time.index < at;
    }));
    expect(bad).toEqual([]);
  });

  it('never uses the bare easing as a whole transition', () => {
    // `transition:…,transform var(--spring)` has no duration, so it is 0s: a snap.
    const bad = items.filter(({ item }) =>
      item.includes('var(--spring)') && explicitTime(item) === null && !TIMED.some((name) => item.includes(`var(${name})`)));
    expect(bad).toEqual([]);
  });
});

describe('the responsive sweep only names things that exist', () => {
  it('has no class that neither the markup nor an earlier rule uses', () => {
    const marker = AIOS.indexOf(':root{ --s5:16px');
    expect(marker, 'the sweep block moved; this check holds nothing').toBeGreaterThan(0);
    const start = AIOS.lastIndexOf('@media', AIOS.lastIndexOf('@media', marker) - 1);
    const sweep = AIOS.slice(start);
    const before = AIOS.slice(0, start);
    const scripts = [...SCRIPTS.values()].join('\n');
    const classes = new Set(rules(sweep).flatMap((r) => r.selectors).flatMap((s) => [...s.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((m) => m[1])));
    expect(classes.size).toBeGreaterThan(20);
    const orphans = [...classes].filter((c) => !token(c).test(scripts) && !new RegExp(`\\.${c}(?![\\w-])`).test(before));
    expect(orphans).toEqual([]);
  });
});

describe('colours copied by hand match the token they copy', () => {
  const triplet = (selector: string) => declared(AIOS, selector, '--cyan-rgb').split(/\s+/).join(',');

  it("paints each theme-preview tile's accent in that theme's own cyan", () => {
    // The tiles show a theme that is usually not the active one, so they cannot use `var(--cyan)`.
    // The light tile kept the pre-retune #0EA5E9 after light --cyan moved to #0A71A0.
    const tileRules = (mode: string) => rules(AIOS).filter((r) => r.selectors.some((s) => s.includes(`.tt-${mode} .tt-bar`) || s.includes(`.tt-${mode} .tt-glow`)));
    const dark = triplet(':root');
    const light = triplet(':root[data-theme="light"]');
    // the un-scoped `.tt-glow` rule is the dark tile's
    const glow = rules(AIOS).filter((r) => r.selectors.includes('.v-settings .tt-glow'));
    for (const [mode, want, extra] of [['dark', dark, glow], ['light', light, []]] as const) {
      const found = [...tileRules(mode), ...extra].flatMap((r) => [...r.body.matchAll(/rgba\((\d+,\d+,\d+),/g)].map((m) => m[1]));
      expect(found.length, `${mode} tile has no accent literal`).toBeGreaterThan(0);
      expect([...new Set(found)], `${mode} tile`).toEqual([want]);
    }
  });

  it('keeps the primary button label readable on the colour the button is actually painted', () => {
    // `.btn--primary` paints --brops-accent-text on --brops-accent (= aios --cyan). The manifest's
    // `primary-button-label` pair measures the --menq-* accent pair instead, which no button uses,
    // and this pair once fell to 3.5:1 in the light theme (tokens.css says so).
    const ui = CSS.get('components/ui.css')!;
    expect(ui).toMatch(/\.btn--primary\s*\{\s*background:\s*var\(--brops-accent\);\s*color:\s*var\(--brops-accent-text\)/);
    const tokens = CSS.get('theme/tokens.css')!;
    expect(tokens).toMatch(/--brops-accent:\s*var\(--cyan,/);
    const hex = (h: string): Rgba => {
      const v = /^#([0-9a-f]{6})$/i.exec(h);
      expect(v, `${h} is not a 6-digit hex`).not.toBeNull();
      return [0, 2, 4].map((i) => parseInt(v![1].slice(i, i + 2), 16)).concat(1) as Rgba;
    };
    // tokens.css: the bare `:root` value is the dark one, and `:root:not([data-theme="dark"])` restates it.
    const text = (block: string) => {
      const m = new RegExp(`${block} \\{[^}]*--brops-accent-text:\\s*(#[0-9a-f]{6})`, 'i').exec(tokens);
      expect(m, `tokens.css: no --brops-accent-text under ${block}`).not.toBeNull();
      return m![1];
    };
    const pairs = {
      dark: [text(':root'), declared(AIOS, ':root', '--cyan')],
      light: [text(':root:not\\(\\[data-theme="dark"\\]\\)'), declared(AIOS, ':root[data-theme="light"]', '--cyan')],
    };
    for (const [theme, [fg, bg]] of Object.entries(pairs)) {
      const measured = ratio(hex(fg), hex(bg));
      expect(measured, `${theme}: ${fg} on ${bg} = ${measured.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe('both stylesheet layers start in the same theme', () => {
  it('index.html names the theme the store defaults to', () => {
    // tokens.css is light unless `data-theme="dark"`; aios.css is dark unless `data-theme="light"`.
    // With no attribute the --menq-* layer painted light and the --ink/--bg layer dark until
    // AppProvider's effect ran. The attribute is in the document now, so it must stay the default.
    const html = readFileSync(resolve(DESKTOP, 'index.html'), 'utf8');
    const attr = /<html[^>]*\sdata-theme="(\w+)"/.exec(html);
    expect(attr, 'index.html sets no data-theme on <html>').not.toBeNull();
    const fallback = /LS\.get<Theme>\('brops\.theme',\s*'(\w+)'\)/.exec(SCRIPTS.get('app/store.tsx')!);
    expect(fallback, 'app/store.tsx no longer reads brops.theme with a literal default').not.toBeNull();
    expect(attr![1]).toBe(fallback![1]);
    // and the two layers really do hang off that attribute the opposite way round
    expect(CSS.get('theme/tokens.css')).toMatch(/:root\[data-theme="dark"\]\s*\{/);
    expect(AIOS).toMatch(/:root\[data-theme="light"\]\{/);
  });
});
