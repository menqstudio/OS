//! Filesystem workspace: browse a directory tree and view/edit text files
//! through `std::fs` (no SQLite). Access is **confined to a single root** (a
//! dedicated `~/BroPS` workspace by default, or `BROPS_FILES_ROOT`) — the
//! security boundary between the untrusted webview and the real disk. Every
//! path is canonicalized (resolving `..` and symlinks) and rejected if it
//! escapes the root, so a compromised renderer cannot read or write arbitrary
//! files. Editing is limited to existing regular files, bounded in size, and
//! written atomically. Error strings that cross the IPC boundary are generic:
//! canonical paths and raw io errors are logged internally only, so a
//! compromised renderer cannot probe file existence or the disk layout.

use serde::Serialize;
use std::fs;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// Largest file we will read into / write from the editor.
const MAX_EDIT_BYTES: u64 = 2 * 1024 * 1024;

/// Most directory entries a single listing will return. A huge directory would
/// otherwise allocate proportional memory and block the IPC thread; past the
/// cap the listing is cut short and flagged `truncated` so the UI can say so.
const MAX_DIR_ENTRIES: usize = 10_000;

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DirEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size_bytes: u64,
    pub modified: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DirListing {
    pub path: String,
    pub parent: Option<String>,
    pub entries: Vec<DirEntry>,
    /// True when the directory held more than [`MAX_DIR_ENTRIES`] children and
    /// the listing was cut short.
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileContent {
    pub path: String,
    pub content: String,
    /// True when the file is not editable as text here (non-regular, too large,
    /// or binary/non-UTF-8).
    pub readonly: bool,
    pub size_bytes: u64,
}

// --- security: confine every path to one canonical root ---------------------

/// The user's home directory: `HOME` where set (Unix, and respected everywhere),
/// falling back to `USERPROFILE` so the default workspace resolves on Windows,
/// where `HOME` is normally unset.
fn home_dir() -> Option<PathBuf> {
    if let Some(h) = std::env::var_os("HOME") {
        if !h.is_empty() {
            return Some(PathBuf::from(h));
        }
    }
    if let Some(h) = std::env::var_os("USERPROFILE") {
        if !h.is_empty() {
            return Some(PathBuf::from(h));
        }
    }
    None
}

/// Refuse a files root that resolves to a filesystem root (`/`, `C:\`) or to the
/// home directory itself — either would put the whole disk/profile (SSH keys,
/// browser data, shell rc) one `confine` check away, leaving only the incomplete
/// `is_sensitive` denylist as a guard. `canon` must already be canonicalized;
/// `home` (if known) is canonicalized here before comparing, so `\\?\`-prefix or
/// symlink differences can't dodge the check. Fails closed: an unsafe root is an
/// error, never silently widened or narrowed.
fn reject_unsafe_root(canon: &Path, home: Option<&Path>) -> Result<(), String> {
    if canon.parent().is_none() {
        eprintln!(
            "[brops] files: BROPS_FILES_ROOT resolves to a filesystem root ({}) — refused",
            canon.display()
        );
        return Err("the configured files root is not allowed".to_string());
    }
    if let Some(home) = home {
        if let Ok(home_canon) = fs::canonicalize(home) {
            if canon == home_canon {
                eprintln!(
                    "[brops] files: BROPS_FILES_ROOT resolves to the home directory ({}) — refused",
                    canon.display()
                );
                return Err("the configured files root is not allowed".to_string());
            }
        }
    }
    Ok(())
}

/// The one directory subtree the file commands may touch. To avoid granting the
/// whole home directory (SSH/AWS keys, shell rc, tool configs) by default, this
/// is a dedicated `~/BroPS` workspace unless `BROPS_FILES_ROOT` points somewhere
/// narrower/specific — and an override is clamped by [`reject_unsafe_root`] so
/// it can never be the filesystem root or the home directory itself. Returned
/// canonicalized so containment compares real paths.
fn files_root() -> Result<PathBuf, String> {
    let raw = match std::env::var("BROPS_FILES_ROOT") {
        Ok(v) if !v.trim().is_empty() => PathBuf::from(v),
        _ => {
            let home = home_dir().ok_or_else(|| {
                eprintln!("[brops] files: no files root (HOME/USERPROFILE unset, BROPS_FILES_ROOT unset)");
                "file workspace is not configured".to_string()
            })?;
            let ws = home.join("BroPS");
            let _ = fs::create_dir_all(&ws); // so the default workspace can be browsed
            ws
        }
    };
    let canon = fs::canonicalize(&raw).map_err(|e| {
        eprintln!("[brops] files: cannot resolve files root {}: {e}", raw.display());
        "file workspace is unavailable".to_string()
    })?;
    // Applied to the default too (harmless — `~/BroPS` can never trip it), so the
    // clamp cannot be bypassed by any code path.
    reject_unsafe_root(&canon, home_dir().as_deref())?;
    Ok(canon)
}

/// Defense-in-depth denylist: even inside the files root, never touch known
/// secret/credential/startup paths. Enforced on top of root confinement so that
/// a broad `BROPS_FILES_ROOT` (e.g. `$HOME`) still can't reach these.
fn is_sensitive(path: &Path) -> bool {
    // Matching is case-insensitive (a `.SSH` or `Credentials.JSON` must not slip
    // through) and covers common variants, not just exact names.
    const DENY_DIRS: &[&str] = &[
        ".ssh", ".aws", ".gnupg", ".gpg", ".kube", ".docker", ".claude", ".azure",
        ".gcloud", ".config", ".password-store", ".mozilla", ".git", ".secrets",
    ];
    for comp in path.components() {
        if let Component::Normal(os) = comp {
            let s = os.to_string_lossy().to_ascii_lowercase();
            if DENY_DIRS.iter().any(|d| *d == s) {
                return true;
            }
        }
    }
    if let Some(raw) = path.file_name().and_then(|n| n.to_str()) {
        let name = raw.to_ascii_lowercase();
        const DENY_FILES: &[&str] = &[
            ".bashrc", ".bash_profile", ".bash_login", ".bash_history", ".profile",
            ".zshrc", ".zprofile", ".zshenv", ".zsh_history", ".netrc", ".pgpass",
            ".git-credentials", ".gitconfig", ".npmrc", ".pypirc", ".htpasswd", ".dockercfg",
            "authorized_keys", "known_hosts", "credentials", "credentials.json",
            "secrets.json", "secrets.yaml", "secrets.yml", "service-account.json",
            "serviceaccount.json", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
            // cloud / infra / app secrets that live as plaintext
            ".my.cnf", ".s3cfg", ".boto", ".databrickscfg", ".vault-token",
            "wp-config.php", "terraform.tfstate", "terraform.tfvars",
        ];
        const DENY_EXT: &[&str] = &[
            ".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".ppk", ".asc", ".kdbx",
            ".ovpn", ".tfstate", ".tfvars",
        ];
        if DENY_FILES.contains(&name.as_str())
            || name.starts_with(".env")            // .env, .env.local, .env.production…
            || name.starts_with("id_")             // ssh private keys
            || name.contains("credential")
            || name.contains(".tfstate")           // terraform.tfstate(.backup)
            || DENY_EXT.iter().any(|e| name.ends_with(e))
        {
            return true;
        }
    }
    false
}

/// Canonicalize `raw` (which must already exist) and confirm it lies inside
/// `root` after resolving `..` and symlinks — rejecting path-traversal and
/// symlink escapes. An empty `raw` resolves to the root itself. Split out from
/// [`confine`] so tests can pass an explicit root without touching env vars.
fn confine_in(root: &Path, raw: &str) -> Result<PathBuf, String> {
    if raw.is_empty() {
        return Ok(root.to_path_buf());
    }
    // One generic error for both "does not exist" and "not accessible" — a
    // renderer must not be able to distinguish them (existence probing), and the
    // raw io error / canonical path is logged internally only.
    let canon = fs::canonicalize(raw).map_err(|e| {
        eprintln!("[brops] files: cannot resolve {raw}: {e}");
        "path not found or not accessible".to_string()
    })?;
    // Component-wise containment (not string-prefix): "/home/gev2" is NOT inside
    // "/home/gev".
    if !canon.starts_with(root) {
        eprintln!("[brops] files: {} is outside the allowed files root", canon.display());
        return Err("path is outside the allowed workspace".to_string());
    }
    Ok(canon)
}

/// Production confinement against the configured [`files_root`], plus the
/// sensitive-path denylist.
fn confine(raw: &str) -> Result<PathBuf, String> {
    let p = confine_in(&files_root()?, raw)?;
    if is_sensitive(&p) {
        eprintln!("[brops] files: sensitive path blocked: {}", p.display());
        return Err("access to this path is blocked".to_string());
    }
    Ok(p)
}

// --- listing ----------------------------------------------------------------

fn modified_ms(meta: &fs::Metadata) -> Option<String> {
    meta.modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis().to_string())
}

/// List a directory's immediate children: directories first, then files, each
/// group sorted case-insensitively by name. Unreadable entries are skipped
/// rather than failing the whole listing. At most `cap` entries are collected;
/// past that the listing stops (bounded memory) and is flagged `truncated`.
/// Split from [`read_listing`] so tests can exercise the cap cheaply.
fn read_listing_capped(dir: &Path, cap: usize) -> std::io::Result<DirListing> {
    let mut entries: Vec<DirEntry> = Vec::new();
    let mut truncated = false;
    for entry in fs::read_dir(dir)? {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        if entries.len() >= cap {
            truncated = true;
            break;
        }
        let path = entry.path();
        // symlink_metadata does NOT follow the link, so a symlink reports its own
        // (small) size/mtime and is_dir=false — it can't leak the target's dir
        // flag / size / mtime, and the UI treats it as a non-navigable file.
        // Opening it still goes through confine(), which resolves + re-checks it.
        let meta = match fs::symlink_metadata(&path) {
            Ok(m) => m,
            Err(_) => continue,
        };
        entries.push(DirEntry {
            name: entry.file_name().to_string_lossy().into_owned(),
            path: path.to_string_lossy().into_owned(),
            is_dir: meta.is_dir(),
            size_bytes: if meta.is_dir() { 0 } else { meta.len() },
            modified: modified_ms(&meta),
        });
    }
    entries.sort_by(|a, b| {
        b.is_dir
            .cmp(&a.is_dir)
            .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    Ok(DirListing {
        path: dir.to_string_lossy().into_owned(),
        parent: dir.parent().map(|p| p.to_string_lossy().into_owned()),
        entries,
        truncated,
    })
}

/// [`read_listing_capped`] with the production [`MAX_DIR_ENTRIES`] cap.
pub fn read_listing(dir: &Path) -> std::io::Result<DirListing> {
    read_listing_capped(dir, MAX_DIR_ENTRIES)
}

#[tauri::command]
pub fn list_dir(path: Option<String>) -> Result<DirListing, String> {
    let root = files_root()?;
    let dir = confine_in(&root, path.as_deref().unwrap_or(""))?;
    // Enforce the sensitive-path denylist on listing too (not just read/write),
    // so a `.ssh`/`.aws` directory can't even be enumerated.
    if is_sensitive(&dir) {
        eprintln!("[brops] files: sensitive path blocked in listing: {}", dir.display());
        return Err("access to this path is blocked".to_string());
    }
    let mut listing = read_listing(&dir).map_err(|e| {
        eprintln!("[brops] files: cannot list {}: {e}", dir.display());
        "cannot list directory".to_string()
    })?;
    // Hide sensitive children so they can't be seen or clicked into.
    listing.entries.retain(|e| !is_sensitive(Path::new(&e.path)));
    // Never offer an "Up" that leaves the confinement root.
    let escapes_root = listing
        .parent
        .as_ref()
        .map(|p| !Path::new(p).starts_with(&root))
        .unwrap_or(false);
    if dir == root || escapes_root {
        listing.parent = None;
    }
    Ok(listing)
}

// --- read / write a text file -----------------------------------------------

/// Read a text file for viewing/editing. Only **regular files** are editable —
/// directories, symlinks, and character/FIFO/socket devices are reported
/// `readonly` (a device like `/dev/zero` has length 0 but never reaches EOF, so
/// we must not `fs::read` it). The read is **bounded** to `MAX_EDIT_BYTES + 1`
/// so a file that lies about (or grows past) its length can't exhaust memory.
/// Over-large or non-UTF-8 content is reported `readonly` rather than failing.
pub fn read_text(path: &Path) -> std::io::Result<FileContent> {
    let meta = fs::symlink_metadata(path)?;
    let path_str = path.to_string_lossy().into_owned();
    if !meta.file_type().is_file() {
        return Ok(FileContent { path: path_str, content: String::new(), readonly: true, size_bytes: 0 });
    }
    let file = fs::File::open(path)?;
    let mut buf = Vec::new();
    file.take(MAX_EDIT_BYTES + 1).read_to_end(&mut buf)?;
    let size = buf.len() as u64;
    if size > MAX_EDIT_BYTES {
        return Ok(FileContent { path: path_str, content: String::new(), readonly: true, size_bytes: size });
    }
    match String::from_utf8(buf) {
        Ok(content) => Ok(FileContent { path: path_str, content, readonly: false, size_bytes: size }),
        Err(_) => Ok(FileContent { path: path_str, content: String::new(), readonly: true, size_bytes: size }),
    }
}

/// Log an io failure with full detail internally and return the generic,
/// probe-proof message the frontend is allowed to see (L-2a).
fn fs_err(generic: &'static str, path: &Path, detail: &dyn std::fmt::Display) -> String {
    eprintln!("[brops] files: {generic} ({}): {detail}", path.display());
    generic.to_string()
}

/// Overwrite an existing regular file's text, atomically. Writes to a uniquely
/// named, **exclusively created** (`O_EXCL`) sibling temp — so it can't follow or
/// clobber a planted temp/symlink — fsyncs it, copies the **original file's
/// permissions** onto it (a 0600 secret stays 0600), then renames it over the
/// target and fsyncs the directory. Refuses new files, non-regular targets, and
/// content over the size cap, so a huge payload can't exhaust the disk and a
/// partial write can never truncate the original.
///
/// Windows note (reduced guarantee): the owner-only `0o600` temp mode and the
/// post-rename directory fsync are Unix-only. On Windows the temp file inherits
/// the parent directory's ACL — private when the workspace lives under the user
/// profile (the default `~/BroPS`), which is per-user by default — and there is
/// no supported way to fsync a directory, so the rename itself is not flushed
/// (the file *content* is still `sync_all`'d before the rename, so the target
/// is never observed half-written; at worst a crash yields the old file).
fn write_text(path: &Path, content: &str) -> Result<(), String> {
    use std::io::Write;
    if content.len() as u64 > MAX_EDIT_BYTES {
        return Err(format!("content exceeds the {MAX_EDIT_BYTES}-byte edit limit"));
    }
    let meta = fs::symlink_metadata(path).map_err(|e| fs_err("cannot write file", path, &e))?;
    if !meta.file_type().is_file() {
        return Err("not an editable file".to_string());
    }
    let parent = path
        .parent()
        .ok_or_else(|| fs_err("cannot write file", path, &"no parent directory"))?;
    let file_name = path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| fs_err("cannot write file", path, &"invalid file name"))?;
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let tmp = parent.join(format!(".{file_name}.{}.{nanos}.brops-tmp", std::process::id()));

    // create_new (O_CREAT|O_EXCL) fails if the name already exists (regular file
    // OR symlink), so a pre-planted temp can't be followed or overwritten. The
    // temp is created owner-only (0600) from the START, so the content is never
    // briefly world-readable under a permissive umask.
    let mut opts = fs::OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut f = opts.open(&tmp).map_err(|e| fs_err("cannot write file", &tmp, &e))?;
    if let Err(e) = f.write_all(content.as_bytes()).and_then(|_| f.sync_all()) {
        drop(f);
        let _ = fs::remove_file(&tmp);
        return Err(fs_err("cannot write file", &tmp, &e));
    }
    // Apply the original file's exact permissions so a 0600 secret stays 0600 (and
    // a 0644 file isn't needlessly tightened). A failure here aborts — never leave
    // the file with the wrong mode.
    if let Err(e) = fs::set_permissions(&tmp, meta.permissions()) {
        drop(f);
        let _ = fs::remove_file(&tmp);
        return Err(fs_err("cannot write file", &tmp, &format!("preserving permissions failed: {e}")));
    }
    drop(f);
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        fs_err("cannot write file", path, &e)
    })?;
    // Best-effort durability: fsync the directory so the rename survives a crash.
    // Unix-only — Windows has no supported directory fsync (see the fn doc note).
    #[cfg(unix)]
    if let Ok(dir) = fs::File::open(parent) {
        let _ = dir.sync_all();
    }
    Ok(())
}

#[tauri::command]
pub fn read_file(path: String) -> Result<FileContent, String> {
    let p = confine(&path)?;
    read_text(&p).map_err(|e| fs_err("cannot read file", &p, &e))
}

#[tauri::command]
pub fn write_file(path: String, content: String) -> Result<(), String> {
    let p = confine(&path)?;
    // write_text already returns generic, path-free messages (L-2a).
    write_text(&p, &content)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(tag: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!("brops_files_{}_{}", tag, std::process::id()));
        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn listing_sorts_dirs_first_then_name() {
        let root = scratch("listing");
        fs::create_dir_all(root.join("zeta_dir")).unwrap();
        fs::create_dir_all(root.join("alpha_dir")).unwrap();
        fs::write(root.join("mid.txt"), b"hello").unwrap();
        fs::write(root.join("Aaa.txt"), b"x").unwrap();

        let listing = read_listing(&root).unwrap();
        let names: Vec<&str> = listing.entries.iter().map(|e| e.name.as_str()).collect();
        assert_eq!(names, vec!["alpha_dir", "zeta_dir", "Aaa.txt", "mid.txt"]);

        let mid = listing.entries.iter().find(|e| e.name == "mid.txt").unwrap();
        assert_eq!(mid.size_bytes, 5);
        assert!(!mid.is_dir);
        assert!(listing.entries[0].is_dir);

        let _ = fs::remove_dir_all(&root);
    }

    #[cfg(unix)]
    #[test]
    fn listing_does_not_follow_symlinks() {
        let base = scratch("listsym");
        fs::create_dir_all(base.join("realdir")).unwrap();
        fs::write(base.join("realdir/big"), vec![b'a'; 5000]).unwrap();
        std::os::unix::fs::symlink(base.join("realdir"), base.join("linkdir")).unwrap();

        let listing = read_listing(&base).unwrap();
        let link = listing.entries.iter().find(|e| e.name == "linkdir").unwrap();
        // the symlink must NOT report the target's directory flag / size.
        assert!(!link.is_dir, "a symlink to a dir must not be listed as a dir");
        assert!(link.size_bytes < 5000, "symlink must report its own size, not the target's");

        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn listing_caps_entries_and_flags_truncation() {
        let root = scratch("cap");
        for i in 0..5 {
            fs::write(root.join(format!("f{i}.txt")), b"x").unwrap();
        }
        // under the cap → complete listing, not truncated
        let full = read_listing_capped(&root, 10).unwrap();
        assert_eq!(full.entries.len(), 5);
        assert!(!full.truncated);
        // over the cap → cut short and flagged
        let cut = read_listing_capped(&root, 3).unwrap();
        assert_eq!(cut.entries.len(), 3);
        assert!(cut.truncated, "an over-cap listing must be flagged truncated");
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn files_root_clamp_rejects_fs_root_and_home() {
        let base = scratch("rootclamp");
        let canon = fs::canonicalize(&base).unwrap();
        // a filesystem root ("/", "C:\") is refused
        let fs_root = fs::canonicalize(if cfg!(windows) { "C:\\" } else { "/" }).unwrap();
        assert!(reject_unsafe_root(&fs_root, None).is_err(), "a filesystem root must be refused");
        // the home directory itself is refused (base standing in for $HOME)
        assert!(reject_unsafe_root(&canon, Some(&base)).is_err(), "the home dir itself must be refused");
        // a normal subdirectory is fine
        assert!(reject_unsafe_root(&canon, None).is_ok());
        let sub = base.join("ws");
        fs::create_dir_all(&sub).unwrap();
        assert!(reject_unsafe_root(&fs::canonicalize(&sub).unwrap(), Some(&base)).is_ok());
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn confine_allows_inside_and_rejects_escape() {
        let base = scratch("confine");
        fs::create_dir_all(base.join("inside")).unwrap();
        fs::write(base.join("inside/f.txt"), b"hi").unwrap();
        let root = fs::canonicalize(&base).unwrap();

        // inside the root → allowed
        let ok = confine_in(&root, base.join("inside/f.txt").to_str().unwrap()).unwrap();
        assert!(ok.starts_with(&root));
        // empty → the root itself
        assert_eq!(confine_in(&root, "").unwrap(), root);
        // absolute path outside the root → rejected (exists but escapes)
        assert!(confine_in(&root, "/").is_err());
        // `..` traversal that climbs out of the root → rejected
        let climb = base.join("inside/../..");
        assert!(confine_in(&root, climb.to_str().unwrap()).is_err());
        // a non-existent path → rejected (canonicalize fails)
        assert!(confine_in(&root, base.join("nope").to_str().unwrap()).is_err());

        let _ = fs::remove_dir_all(&base);
    }

    #[cfg(unix)]
    #[test]
    fn confine_rejects_symlink_escape() {
        let base = scratch("symlink");
        fs::create_dir_all(base.join("inside")).unwrap();
        let root = fs::canonicalize(&base).unwrap();
        // a secret outside the root, and a symlink inside the root pointing at it
        let outside = std::env::temp_dir().join(format!("brops_secret_{}.txt", std::process::id()));
        fs::write(&outside, b"secret").unwrap();
        let link = base.join("inside/escape");
        std::os::unix::fs::symlink(&outside, &link).unwrap();

        // following the symlink lands outside the root → rejected
        assert!(confine_in(&root, link.to_str().unwrap()).is_err());

        let _ = fs::remove_file(&outside);
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn sensitive_paths_are_denied() {
        for p in [
            "/home/u/.ssh/id_ed25519",
            "/home/u/.ssh/authorized_keys",
            "/home/u/.aws/credentials",
            "/home/u/.gnupg/secring.gpg",
            "/home/u/.bashrc",
            "/home/u/.zshrc",
            "/home/u/.netrc",
            "/home/u/.git-credentials",
            "/home/u/project/.git/hooks/pre-commit",
            "/home/u/secret.pem",
            "/home/u/cert.key",
            "/home/u/app/.env",
            // variants the round-3 audit flagged
            "/home/u/app/.env.local",
            "/home/u/app/.env.production",
            "/home/u/svc/credentials.json",
            "/home/u/svc/my-credential.txt",
            "/home/u/secrets.yaml",
            "/home/u/vault.kdbx",
            // case-insensitive
            "/home/u/.SSH/id_rsa",
            "/home/u/Credentials.JSON",
            "/home/u/.config/gcloud/access_tokens.db",
            "/home/u/infra/terraform.tfstate",
            "/home/u/infra/terraform.tfstate.backup",
            "/home/u/infra/prod.tfvars",
            "/home/u/.gitconfig",
            "/home/u/.my.cnf",
            "/home/u/.vault-token",
            "/home/u/site/wp-config.php",
        ] {
            assert!(is_sensitive(Path::new(p)), "{p} must be denied");
        }
        for p in ["/home/u/project/src/main.rs", "/home/u/notes.txt", "/home/u/BroPS/todo.md", "/home/u/env.md"] {
            assert!(!is_sensitive(Path::new(p)), "{p} must be allowed");
        }
    }

    #[test]
    fn read_text_regular_file_bounds_and_types() {
        let base = scratch("read");
        fs::write(base.join("f.txt"), b"hi there").unwrap();

        // a directory is not editable
        assert!(read_text(&base).unwrap().readonly);

        // a small utf-8 file reads back exactly
        let fc = read_text(&base.join("f.txt")).unwrap();
        assert_eq!(fc.content, "hi there");
        assert!(!fc.readonly);

        // an over-large file is reported readonly, not loaded
        let big = base.join("big.bin");
        fs::write(&big, vec![b'a'; MAX_EDIT_BYTES as usize + 16]).unwrap();
        let fc = read_text(&big).unwrap();
        assert!(fc.readonly);
        assert!(fc.size_bytes > MAX_EDIT_BYTES);

        // binary / non-utf8 → readonly
        fs::write(base.join("b.bin"), [0xff_u8, 0xfe, 0x00, 0x01]).unwrap();
        assert!(read_text(&base.join("b.bin")).unwrap().readonly);

        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn write_text_enforces_limits_and_persists_atomically() {
        let base = scratch("write");
        let f = base.join("f.txt");
        fs::write(&f, b"orig").unwrap();

        // oversize new content is rejected before any write
        let huge = "a".repeat(MAX_EDIT_BYTES as usize + 1);
        assert!(write_text(&f, &huge).is_err());
        assert_eq!(fs::read_to_string(&f).unwrap(), "orig"); // original untouched

        // writing over a directory is rejected
        assert!(write_text(&base, "x").is_err());

        // happy path persists the new content
        write_text(&f, "updated").unwrap();
        assert_eq!(fs::read_to_string(&f).unwrap(), "updated");
        // no stray temp files left behind
        let leftovers = fs::read_dir(&base)
            .unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().contains("brops-tmp"))
            .count();
        assert_eq!(leftovers, 0);

        let _ = fs::remove_dir_all(&base);
    }
}
