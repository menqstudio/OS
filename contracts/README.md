# contracts/ 📜

**Placeholder — Phase 3.** The single source of truth for the schemas both halves must agree on.

## English
When the cockpit (Rust) and the engine (Python) exchange security-relevant objects, they must validate against **one** definition — not two drifting copies. This directory will hold the canonical schemas:

- `execution-lease` · `mode-grant` · `approval` · `task-contract` · `verifier-receipt`

Today these live in [`../engine/schemas/`](../engine/schemas/) (Python side) and are mirrored informally in the desktop's Rust `domain`. Phase 3 extracts them here so both sides consume the same files.

## Հայերեն
Երբ cockpit-ը (Rust) ու engine-ը (Python) փոխանակում են security-relevant object-եր, պիտի validate անեն **մեկ** սահմանման դեմ — ոչ երկու drift-վող պատճենի։ Այս պանակը կպահի canonical schema-ները (lease · mode-grant · approval · task-contract · verifier-receipt)։ Հիմա դրանք [`../engine/schemas/`](../engine/schemas/)-ում են; Phase 3-ը կհանի սրանք էստեղ, որ երկու կողմն էլ նույն ֆայլերը օգտագործեն։
