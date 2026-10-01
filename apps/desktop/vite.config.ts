import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  // strictPort: fail loudly if 1420 is taken instead of silently hopping ports (Tauri's devUrl
  // is pinned to 1420). watch.ignored: never watch the Rust side — otherwise vite's file watcher
  // trips over src-tauri/target/debug/deps/*.dll while `cargo build` is (re)writing/locking it,
  // which on Windows surfaces as an EPERM that crashes node and reads as
  // "beforeDevCommand terminated with a non-zero status code". This mirrors the canonical Tauri v2 template.
  server: { port: 1420, strictPort: true, watch: { ignored: ["**/src-tauri/**"] } },
  // envPrefix decides which process variables `import.meta.env` may carry into the CLIENT bundle.
  // It was ["VITE_", "TAURI_"], copied from the Tauri v1 template, and `TAURI_` is also the prefix
  // of TAURI_SIGNING_PRIVATE_KEY and TAURI_SIGNING_PRIVATE_KEY_PASSWORD, which release.yml sets on
  // the very step that runs this build. Nothing under src/ reads `import.meta.env` at all, so the
  // list is Vite's own default and no more. If a build-time fact from the Tauri CLI is ever
  // needed, name the variable whole (the v2 template's form is "TAURI_ENV_*") — never the family.
  envPrefix: ["VITE_"],
  // Emit dist/.vite/manifest.json so tools/check_bundle_budget.py can resolve each
  // entry's chunks/CSS and enforce the gzip budget (perf-budget.yml). The manifest is
  // an extra sidecar file under dist/; it does not change index.html or the served
  // assets, so it is transparent to the Tauri host that loads frontendDist.
  build: { manifest: true }
});
