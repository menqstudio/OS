import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  envPrefix: ["VITE_", "TAURI_"],
  // Emit dist/.vite/manifest.json so tools/check_bundle_budget.py can resolve each
  // entry's chunks/CSS and enforce the gzip budget (perf-budget.yml). The manifest is
  // an extra sidecar file under dist/; it does not change index.html or the served
  // assets, so it is transparent to the Tauri host that loads frontendDist.
  build: { manifest: true }
});
