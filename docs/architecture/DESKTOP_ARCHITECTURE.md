# BroPS Desktop Architecture

## Stack
Tauri 2 + Rust host, React + TypeScript + Vite frontend, SQLite local database.

## Boundaries
- UI layer: rendering, navigation, local interaction state.
- Application layer: commands, queries, validation, orchestration.
- Domain layer: entities, policies and state machines.
- Infrastructure layer: SQLite, filesystem, secrets, providers, notifications and OS integration.
- Tauri boundary: minimal typed commands and events; no arbitrary shell execution.

## Local storage
SQLite uses migrations, foreign keys, WAL mode and transactional writes. User files remain in managed workspace directories; metadata and content hashes are stored in SQLite. Every external file path is normalized and access checked.

## Secrets
Provider keys and sensitive tokens MUST use the OS credential vault/keychain. Secrets are never stored in plaintext configuration, logs, analytics or exports.

## Files
File operations support import, copy, move, rename, preview, version metadata and trash-before-delete. Destructive actions require approval and audit records.

## Backup and restore
Backups include database, managed files, settings and manifest checksums. Secrets are excluded unless explicitly exported through an encrypted flow. Restore validates schema version, checksums and available disk space before atomic replacement.

## Security
CSP enabled, Tauri capabilities allowlisted, updater signatures required, URLs validated, plugin boundaries explicit and audit logging append-only.
