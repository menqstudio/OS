fn main() {
    // M-8: declare the app's own IPC commands in the application manifest so the
    // capability system actually governs them. Tauri v2 capabilities only gate
    // PLUGIN commands by default — app commands registered in
    // `generate_handler!` would otherwise be invokable by the webview with no
    // permission entry at all. Listing a command here makes tauri-build generate
    // `allow-<command>` / `deny-<command>` permissions for it, which
    // `capabilities/default.json` must then grant explicitly; removing the grant
    // disables the command for the window.
    //
    // Only the filesystem surface (the highest-risk commands — direct disk
    // read/write from the webview) is declared for now.
    // TODO(M-8): extend the manifest to the SQLite-backed `commands::*` surface
    // once per-command capability grouping (read-only vs. mutating) is decided.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["list_dir", "read_file", "write_file"]),
        ),
    )
    .expect("failed to run tauri-build");
}
