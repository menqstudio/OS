# M-8 — App-command FS surface bypasses the capability model; files root is env-widenable

- **Severity:** Medium
- **Confidence:** High (mechanism); config-dependent (impact)
- **Type:** Tauri attack surface / access control
- **Files:** `src-tauri/src/lib.rs:123-125` (handler registration), `src-tauri/src/files.rs:53-66` (`files_root`), `src-tauri/build.rs`, `src-tauri/capabilities/default.json`
- **Status:** Proposed patch (read-only audit)

## Problem
`capabilities/default.json` advertises a "minimal capability set", but **Tauri v2 capabilities only gate plugin commands** — application commands (`list_dir`, `read_file`, `write_file`) registered in `generate_handler!` are invokable by the webview with **no permission entry at all**. So a renderer compromise gets read/write over the confined root.

Worse, `files_root()` honors `BROPS_FILES_ROOT`:
```rust
Ok(v) if !v.trim().is_empty() => PathBuf::from(v)
```
Setting `BROPS_FILES_ROOT=/` (or `C:\`) widens the surface to the whole disk, leaving only the incomplete `is_sensitive()` denylist as a guard. (See L-2: the Windows `HOME`-vs-`USERPROFILE` bug pushes users toward setting a broad root.)

## Fix
1. Declare app-command permissions so the ACL is real. In `build.rs`:
```rust
tauri_build::try_build(
    tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["list_dir", "read_file", "write_file", /* ... */]),
    ),
).expect("failed to run tauri-build");
```
then list the corresponding `allow-*` permissions explicitly in `capabilities/default.json`.
2. Refuse dangerous roots in `files_root()`:
```rust
// reject a root that resolves to a filesystem root or to $HOME itself
if canon.parent().is_none() || canon == home { return Err("unsafe files root".into()); }
```
3. Keep the default narrow (`~/BroPS`).

## Acceptance criteria
- [ ] `BROPS_FILES_ROOT` set to `/`, `C:\`, or the home dir itself is rejected at startup.
- [ ] App file commands are governed by an explicit capability entry (removing it disables them).
- [ ] Default workspace still resolves to `~/BroPS` on both Unix and Windows (coordinate with L-2's `USERPROFILE` fix).
