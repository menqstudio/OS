# bridge/ 🔗

**Placeholder — Phase 1.** No integration code yet (Phase 0 assembles; it does not wire).

## English
The **bridge** is where the cockpit's backend (`apps/desktop/src-tauri`, Rust) will call into the governance **engine** (`engine/`, Python). It replaces the desktop's current direct `claude` spawn (`apps/desktop/src-tauri/src/ai.rs`) with a governed call:

```
Tauri command (Rust) → bridge → engine: bro_supervisor
   → execution lease → 🧱 hook wall → sandboxed AI → signed receipt → back
```

**Boundary:** subprocess/sidecar (matches the engine's CLI/hook model), not PyO3 embedding.
**Contract:** requests and receipts are validated against the shared schemas in [`../contracts/`](../contracts/).

## Հայերեն
**bridge**-ը էն տեղն ա, որտեղ cockpit-ի backend-ը (`apps/desktop/src-tauri`, Rust) կկանչի governance **engine**-ը (`engine/`, Python)։ Փոխարինում ա desktop-ի հիմիկվա ուղիղ `claude` spawn-ը (`ai.rs`) governed call-ով (տես վերևի flow-ը)։ Boundary-ն subprocess/sidecar ա; request/receipt-ները validate են [`../contracts/`](../contracts/)-ի schema-ների դեմ։
