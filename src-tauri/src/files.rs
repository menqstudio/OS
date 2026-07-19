//! Filesystem workspace: browse a directory tree and view/edit text files
//! through `std::fs` (no SQLite). Access is **confined to a single root** (the
//! user's home by default, or `BROPS_FILES_ROOT`) — the security boundary
//! between the untrusted webview and the real disk. Every path is canonicalized
//! (resolving `..` and symlinks) and rejected if it escapes the root, so a
//! compromised renderer cannot read or write arbitrary files. Editing is limited
//! to existing regular files, bounded in size, and written atomically.

use serde::Serialize;
use std::fs;
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// Largest file we will read into / write from the editor.
const MAX_EDIT_BYTES: u64 = 2 * 1024 * 1024;

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

/// The one directory subtree the file commands may touch. To avoid granting the
/// whole home directory (SSH/AWS keys, shell rc, tool configs) by default, this
/// is a dedicated `~/BroPS` workspace unless `BROPS_FILES_ROOT` points somewhere
/// narrower/specific. Returned canonicalized so containment compares real paths.
fn files_root() -> Result<PathBuf, String> {
    let raw = match std::env::var("BROPS_FILES_ROOT") {
        Ok(v) if !v.trim().is_empty() => PathBuf::from(v),
        _ => {
            let home = std::env::var_os("HOME")
                .map(PathBuf::from)
                .ok_or_else(|| "no files root (HOME unset, BROPS_FILES_ROOT unset)".to_string())?;
            let ws = home.join("BroPS");
            let _ = fs::create_dir_all(&ws); // so the default workspace can be browsed
            ws
        }
    };
    fs::canonicalize(&raw).map_err(|e| format!("files root {}: {e}", raw.display()))
}

/// Defense-in-depth denylist: even inside the files root, never touch known
/// secret/credential/startup paths. Enforced on top of root confinement so that
/// a broad `BROPS_FILES_ROOT` (e.g. `$HOME`) still can't reach these.
fn is_sensitive(path: &Path) -> bool {
    const DENY_DIRS: &[&str] = &[
        ".ssh", ".aws", ".gnupg", ".gpg", ".kube", ".docker", ".claude", ".azure",
        ".gcloud", ".password-store", ".mozilla", ".git",
    ];
    for comp in path.components() {
        if let Component::Normal(os) = comp {
            let s = os.to_string_lossy();
            if DENY_DIRS.iter().any(|d| *d == s) {
                return true;
            }
        }
    }
    if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
        const DENY_FILES: &[&str] = &[
            ".bashrc", ".bash_profile", ".bash_login", ".bash_history", ".profile",
            ".zshrc", ".zprofile", ".zshenv", ".zsh_history", ".netrc", ".pgpass",
            ".git-credentials", ".npmrc", ".pypirc", ".env", "authorized_keys", "known_hosts",
        ];
        if DENY_FILES.contains(&name)
            || name.ends_with(".pem")
            || name.ends_with(".key")
            || name.ends_with(".p12")
            || name.ends_with(".pfx")
            || name.starts_with("id_")
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
    let canon = fs::canonicalize(raw).map_err(|e| format!("{raw}: {e}"))?;
    // Component-wise containment (not string-prefix): "/home/gev2" is NOT inside
    // "/home/gev".
    if !canon.starts_with(root) {
        return Err(format!("{}: outside the allowed files root", canon.display()));
    }
    Ok(canon)
}

/// Production confinement against the configured [`files_root`], plus the
/// sensitive-path denylist.
fn confine(raw: &str) -> Result<PathBuf, String> {
    let p = confine_in(&files_root()?, raw)?;
    if is_sensitive(&p) {
        return Err(format!("{}: access to this sensitive path is blocked", p.display()));
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
/// rather than failing the whole listing.
pub fn read_listing(dir: &Path) -> std::io::Result<DirListing> {
    let mut entries: Vec<DirEntry> = Vec::new();
    for entry in fs::read_dir(dir)? {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        let path = entry.path();
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
    })
}

#[tauri::command]
pub fn list_dir(path: Option<String>) -> Result<DirListing, String> {
    let root = files_root()?;
    let dir = confine_in(&root, path.as_deref().unwrap_or(""))?;
    let mut listing = read_listing(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
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

/// Overwrite an existing regular file's text, atomically. Writes to a uniquely
/// named, **exclusively created** (`O_EXCL`) sibling temp — so it can't follow or
/// clobber a planted temp/symlink — fsyncs it, copies the **original file's
/// permissions** onto it (a 0600 secret stays 0600), then renames it over the
/// target and fsyncs the directory. Refuses new files, non-regular targets, and
/// content over the size cap, so a huge payload can't exhaust the disk and a
/// partial write can never truncate the original.
fn write_text(path: &Path, content: &str) -> Result<(), String> {
    use std::io::Write;
    if content.len() as u64 > MAX_EDIT_BYTES {
        return Err(format!("content exceeds the {MAX_EDIT_BYTES}-byte edit limit"));
    }
    let meta = fs::symlink_metadata(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if !meta.file_type().is_file() {
        return Err(format!("{}: not a regular file", path.display()));
    }
    let parent = path.parent().ok_or_else(|| format!("{}: no parent directory", path.display()))?;
    let file_name = path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| format!("{}: invalid file name", path.display()))?;
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let tmp = parent.join(format!(".{file_name}.{}.{nanos}.brops-tmp", std::process::id()));

    // create_new (O_CREAT|O_EXCL) fails if the name already exists (regular file
    // OR symlink), so a pre-planted temp can't be followed or overwritten.
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&tmp)
        .map_err(|e| format!("{}: {e}", tmp.display()))?;
    if let Err(e) = f.write_all(content.as_bytes()).and_then(|_| f.sync_all()) {
        drop(f);
        let _ = fs::remove_file(&tmp);
        return Err(format!("{}: {e}", tmp.display()));
    }
    // Preserve the original file's permissions so editing a 0600 secret can't
    // silently widen it to the umask default.
    let _ = fs::set_permissions(&tmp, meta.permissions());
    drop(f);
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        format!("{}: {e}", path.display())
    })?;
    // Best-effort durability: fsync the directory so the rename survives a crash.
    #[cfg(unix)]
    if let Ok(dir) = fs::File::open(parent) {
        let _ = dir.sync_all();
    }
    Ok(())
}

#[tauri::command]
pub fn read_file(path: String) -> Result<FileContent, String> {
    let p = confine(&path)?;
    read_text(&p).map_err(|e| format!("{path}: {e}"))
}

#[tauri::command]
pub fn write_file(path: String, content: String) -> Result<(), String> {
    let p = confine(&path)?;
    write_text(&p, &content).map_err(|e| format!("{path}: {e}"))
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
        ] {
            assert!(is_sensitive(Path::new(p)), "{p} must be denied");
        }
        for p in ["/home/u/project/src/main.rs", "/home/u/notes.txt", "/home/u/BroPS/todo.md"] {
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
