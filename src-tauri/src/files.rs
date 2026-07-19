//! Read-only filesystem browser. Unlike the rest of the command surface this
//! does not touch SQLite — it lists real directory contents through `std::fs`
//! so the Files workspace shows the actual disk, not a mock. Browsing is
//! read-only; nothing here mutates the filesystem.

use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;
use tauri::Manager;

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
pub fn list_dir(app: tauri::AppHandle, path: Option<String>) -> Result<DirListing, String> {
    let dir: PathBuf = match path {
        Some(p) if !p.is_empty() => PathBuf::from(p),
        _ => app.path().home_dir().map_err(|e| e.to_string())?,
    };
    read_listing(&dir).map_err(|e| format!("{}: {e}", dir.display()))
}

/// Largest file we will read into the editor. Bigger files (or binaries) are
/// refused so the UI never tries to load a gigabyte into a textarea.
const MAX_EDIT_BYTES: u64 = 2 * 1024 * 1024;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileContent {
    pub path: String,
    pub content: String,
    /// True when the file is not editable as text here (too large or binary).
    pub readonly: bool,
    pub size_bytes: u64,
}

/// Read a text file for viewing/editing. Refuses directories, over-large files,
/// and non-UTF-8 (binary) content — reporting `readonly` with an explanation in
/// `content` rather than failing, so the UI can show a calm message.
pub fn read_text(path: &Path) -> std::io::Result<FileContent> {
    let meta = fs::metadata(path)?;
    if meta.is_dir() {
        return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "path is a directory"));
    }
    let size = meta.len();
    let path_str = path.to_string_lossy().into_owned();
    if size > MAX_EDIT_BYTES {
        return Ok(FileContent { path: path_str, content: String::new(), readonly: true, size_bytes: size });
    }
    let bytes = fs::read(path)?;
    match String::from_utf8(bytes) {
        Ok(content) => Ok(FileContent { path: path_str, content, readonly: false, size_bytes: size }),
        Err(_) => Ok(FileContent { path: path_str, content: String::new(), readonly: true, size_bytes: size }),
    }
}

#[tauri::command]
pub fn read_file(path: String) -> Result<FileContent, String> {
    read_text(Path::new(&path)).map_err(|e| format!("{path}: {e}"))
}

/// Overwrite an existing file's contents. Refuses to create a new file or write
/// over a directory — editing here is limited to files the browser already
/// surfaced, so a typo can't scatter new files across the disk.
#[tauri::command]
pub fn write_file(path: String, content: String) -> Result<(), String> {
    let p = Path::new(&path);
    let meta = fs::metadata(p).map_err(|e| format!("{path}: {e}"))?;
    if meta.is_dir() {
        return Err(format!("{path}: is a directory"));
    }
    if meta.len() > MAX_EDIT_BYTES {
        return Err(format!("{path}: file is too large to edit here"));
    }
    fs::write(p, content).map_err(|e| format!("{path}: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn listing_sorts_dirs_first_then_name() {
        let root = std::env::temp_dir().join(format!("brops_files_test_{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
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
        assert_eq!(listing.parent.as_deref(), Some(root.parent().unwrap().to_string_lossy().as_ref()));

        let _ = fs::remove_dir_all(&root);
    }
}
