//! Provider-agnostic AI layer for BroPS.
//!
//! Default provider is the **local `claude` CLI** (Claude Code) — it uses the
//! user's own Claude login, so replies cost nothing beyond their existing
//! subscription and no API key is stored anywhere. If `ANTHROPIC_API_KEY` is
//! set, the metered Anthropic API is used instead. A local Ollama model is
//! available as a third option. When nothing is reachable the caller gets an
//! honest error string that the UI surfaces rather than faking a reply.
//!
//! Configuration (all optional; secrets come from the environment, never SQLite):
//!   BROPS_AI_PROVIDER    – force one of: claude-cli | anthropic | ollama
//!   BROPS_CLAUDE_BIN     – path to the `claude` binary (default: claude)
//!   BROPS_CLAUDE_MODEL   – model for the CLI (optional; CLI default otherwise)
//!   ANTHROPIC_API_KEY    – if set (and provider not forced), use Anthropic
//!   BROPS_ANTHROPIC_MODEL– Anthropic model id (default: claude-sonnet-5)
//!   BROPS_OLLAMA_MODEL   – Ollama model tag  (default: llama3.2)
//!   BROPS_OLLAMA_URL     – Ollama base url   (default: http://localhost:11434)

use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::io::AsyncBufReadExt;

const DEFAULT_ANTHROPIC_MODEL: &str = "claude-sonnet-5";
const DEFAULT_OLLAMA_MODEL: &str = "llama3.2";
const DEFAULT_OLLAMA_URL: &str = "http://localhost:11434";
const DEFAULT_CLAUDE_BIN: &str = "claude";
const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION: &str = "2023-06-01";

/// One turn of a conversation. `role` is "user" or "assistant".
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMsg {
    pub role: String,
    pub content: String,
}

/// Which provider is active and whether it looks usable — surfaced to the UI.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AiStatus {
    pub provider: String,
    pub model: String,
    pub ready: bool,
    pub detail: String,
}

enum Provider {
    ClaudeCli { bin: String },
    Anthropic { key: String, model: String },
    Ollama { model: String, url: String },
}

fn env_nonempty(key: &str) -> Option<String> {
    std::env::var(key).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty())
}

fn resolve() -> Provider {
    let forced = env_nonempty("BROPS_AI_PROVIDER").map(|v| v.to_lowercase());
    let claude_bin = env_nonempty("BROPS_CLAUDE_BIN").unwrap_or_else(|| DEFAULT_CLAUDE_BIN.to_string());
    match forced.as_deref() {
        Some("anthropic") => {
            let key = env_nonempty("ANTHROPIC_API_KEY").unwrap_or_default();
            return Provider::Anthropic {
                key,
                model: env_nonempty("BROPS_ANTHROPIC_MODEL").unwrap_or_else(|| DEFAULT_ANTHROPIC_MODEL.to_string()),
            };
        }
        Some("ollama") => {
            return Provider::Ollama {
                model: env_nonempty("BROPS_OLLAMA_MODEL").unwrap_or_else(|| DEFAULT_OLLAMA_MODEL.to_string()),
                url: env_nonempty("BROPS_OLLAMA_URL").unwrap_or_else(|| DEFAULT_OLLAMA_URL.to_string()),
            };
        }
        Some("claude-cli") => return Provider::ClaudeCli { bin: claude_bin },
        _ => {}
    }
    // Auto: a metered key means the user opted into Anthropic; otherwise default
    // to the local claude CLI (free via the user's own login).
    if let Some(key) = env_nonempty("ANTHROPIC_API_KEY") {
        return Provider::Anthropic {
            key,
            model: env_nonempty("BROPS_ANTHROPIC_MODEL").unwrap_or_else(|| DEFAULT_ANTHROPIC_MODEL.to_string()),
        };
    }
    Provider::ClaudeCli { bin: claude_bin }
}

/// Report the configured provider and a best-effort readiness check.
pub async fn status() -> AiStatus {
    match resolve() {
        Provider::ClaudeCli { bin } => {
            let ok = tokio::time::timeout(
                Duration::from_secs(4),
                tokio::process::Command::new(&bin).arg("--version").output(),
            )
            .await
            .ok()
            .and_then(|r| r.ok())
            .map(|o| o.status.success())
            .unwrap_or(false);
            AiStatus {
                provider: "claude-cli".into(),
                model: env_nonempty("BROPS_CLAUDE_MODEL").unwrap_or_else(|| "claude (subscription)".into()),
                ready: ok,
                detail: if ok {
                    format!("Local Claude Code (`{bin}`) is available — replies use your own login, no API key.")
                } else {
                    format!("`{bin}` not found or not logged in. Install/login to Claude Code, set BROPS_CLAUDE_BIN, or set ANTHROPIC_API_KEY.")
                },
            }
        }
        Provider::Anthropic { model, .. } => AiStatus {
            provider: "anthropic".into(),
            model,
            ready: true,
            detail: "Anthropic API key detected (ANTHROPIC_API_KEY) — metered usage.".into(),
        },
        Provider::Ollama { model, url } => {
            let reachable = reqwest::Client::new()
                .get(format!("{url}/api/tags"))
                .timeout(Duration::from_millis(1500))
                .send()
                .await
                .map(|r| r.status().is_success())
                .unwrap_or(false);
            AiStatus {
                provider: "ollama".into(),
                model,
                ready: reachable,
                detail: if reachable {
                    format!("Local Ollama is running at {url}.")
                } else {
                    format!("Local Ollama not reachable at {url}.")
                },
            }
        }
    }
}

/// Generate a single reply given a system prompt and prior turns.
pub async fn generate(system: &str, messages: &[ChatMsg]) -> Result<String, String> {
    match resolve() {
        Provider::ClaudeCli { bin } => claude_cli(&bin, system, messages).await,
        Provider::Anthropic { key, model } => anthropic(&key, &model, system, messages).await,
        Provider::Ollama { model, url } => ollama(&url, &model, system, messages).await,
    }
}

/// Streaming generation: `on_delta` is called with each incremental text chunk
/// as it arrives; the full text is returned at the end. Only the local `claude`
/// CLI streams token-by-token today; the Anthropic and Ollama providers fall
/// back to a single final chunk (still correct, just not incremental).
pub async fn generate_stream<F: FnMut(&str)>(
    system: &str,
    messages: &[ChatMsg],
    mut on_delta: F,
) -> Result<String, String> {
    match resolve() {
        Provider::ClaudeCli { bin } => claude_cli_stream(&bin, system, messages, &mut on_delta).await,
        Provider::Anthropic { key, model } => {
            let full = anthropic(&key, &model, system, messages).await?;
            on_delta(&full);
            Ok(full)
        }
        Provider::Ollama { model, url } => {
            let full = ollama(&url, &model, system, messages).await?;
            on_delta(&full);
            Ok(full)
        }
    }
}

static AI_SANDBOX: std::sync::OnceLock<std::path::PathBuf> = std::sync::OnceLock::new();

/// A unique, owner-only (0700) empty directory created fresh for this process's
/// `claude` subprocesses, so the CLI can't pick up a nearby project's
/// `.claude/settings.json`, `.mcp.json`, or source files. `create_dir` (not
/// `_all`) fails if the name already exists, so a pre-planted `/tmp` directory or
/// symlink can never be reused to smuggle in config. Cached for the process.
fn ai_sandbox_dir() -> Result<std::path::PathBuf, String> {
    if let Some(p) = AI_SANDBOX.get() {
        return Ok(p.clone());
    }
    let base = std::env::temp_dir();
    let pid = std::process::id();
    for attempt in 0..16u32 {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = base.join(format!("brops-ai-{pid}-{nanos}-{attempt}"));
        match std::fs::create_dir(&dir) {
            Ok(()) => {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))
                        .map_err(|e| format!("AI sandbox perms: {e}"))?;
                }
                let _ = AI_SANDBOX.set(dir.clone());
                return Ok(AI_SANDBOX.get().cloned().unwrap_or(dir));
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("AI sandbox: {e}")),
        }
    }
    Err("could not create a private AI sandbox directory".to_string())
}

/// Build the argv (after the binary) for a `claude -p` chat call. Centralized so
/// the security lockdown is guaranteed present on every path and unit-testable.
/// The chat is a pure text completion: no built-in tools, no MCP servers, and no
/// user/local settings (hooks/plugins) — so a prompt-injection in a message
/// can't read/write the filesystem or run commands through the coding agent.
///
/// The prompt (which contains the chat transcript) is NOT here — it is written
/// to the child's stdin so it never appears in argv / `/proc/<pid>/cmdline`,
/// where another local user could read it while the process runs.
fn claude_args(system: &str, streaming: bool, model: Option<&str>) -> Vec<String> {
    let mut a: Vec<String> = vec!["-p".into(), "--output-format".into()];
    if streaming {
        a.push("stream-json".into());
        a.push("--verbose".into());
        a.push("--include-partial-messages".into());
    } else {
        a.push("json".into());
    }
    a.push("--append-system-prompt".into());
    a.push(system.into());
    a.push("--tools".into());
    a.push(String::new()); // "" → disable ALL built-in tools
    a.push("--strict-mcp-config".into()); // ignore every MCP config (we pass none)
    a.push("--setting-sources".into());
    a.push("project".into()); // only project settings (empty sandbox) — excludes user hooks/plugins/MCP
    a.push("--no-session-persistence".into());
    if let Some(m) = model {
        a.push("--model".into());
        a.push(m.into());
    }
    a
}

async fn claude_cli_stream<F: FnMut(&str)>(
    bin: &str,
    system: &str,
    messages: &[ChatMsg],
    on_delta: &mut F,
) -> Result<String, String> {
    let prompt = format!("{}\n\nReply to the latest User message.", transcript(messages));
    let mut cmd = tokio::process::Command::new(bin);
    cmd.args(claude_args(system, true, env_nonempty("BROPS_CLAUDE_MODEL").as_deref()))
        .current_dir(ai_sandbox_dir()?)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        // Ensure the child is killed if this future is dropped or returns early
        // (timeout, read error) — never leak a running `claude` process.
        .kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| {
        format!("Could not run `{bin}` ({e}). Install Claude Code and log in, set BROPS_CLAUDE_BIN, or set ANTHROPIC_API_KEY.")
    })?;

    // Feed the transcript over stdin (never argv → not in /proc/<pid>/cmdline) on
    // a background task, so a full pipe (large transcript, child not yet reading)
    // can't block us before the read loop's per-read timeout can fire. If we bail,
    // kill_on_drop reaps the child and this task's write fails harmlessly.
    if let Some(mut stdin) = child.stdin.take() {
        let bytes = prompt.into_bytes();
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            let _ = stdin.write_all(&bytes).await;
            let _ = stdin.shutdown().await;
        });
    }

    // Drain stderr concurrently so a full stderr pipe can never deadlock the
    // stdout read loop.
    let stderr = child.stderr.take();
    let stderr_task = tokio::spawn(async move {
        let mut buf = String::new();
        if let Some(mut e) = stderr {
            use tokio::io::AsyncReadExt;
            let _ = e.read_to_string(&mut buf).await;
        }
        buf
    });

    let stdout = child.stdout.take().ok_or("no stdout from claude")?;
    let mut lines = tokio::io::BufReader::new(stdout).lines();
    let mut acc = String::new();
    let mut result_text: Option<String> = None;

    // stream-json emits one JSON object per line. Token deltas arrive as
    // {type:"stream_event", event:{type:"content_block_delta", delta:{text}}};
    // the final full text arrives as {type:"result", result}. A stalled read
    // (hung `claude`, auth prompt, network stall) is bounded by a per-read
    // timeout so the UI never spins forever; kill_on_drop reaps the child.
    loop {
        let line = match tokio::time::timeout(Duration::from_secs(120), lines.next_line()).await {
            Err(_) => return Err("claude CLI timed out".to_string()),
            Ok(Ok(Some(l))) => l,
            Ok(Ok(None)) => break,
            Ok(Err(e)) => return Err(e.to_string()),
        };
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let v: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        match v.get("type").and_then(|t| t.as_str()) {
            Some("stream_event") => {
                let ev = &v["event"];
                if ev.get("type").and_then(|t| t.as_str()) == Some("content_block_delta") {
                    if let Some(text) = ev.get("delta").and_then(|d| d.get("text")).and_then(|t| t.as_str()) {
                        if !text.is_empty() {
                            acc.push_str(text);
                            on_delta(text);
                        }
                    }
                }
            }
            Some("result") => {
                if let Some(r) = v.get("result").and_then(|r| r.as_str()) {
                    result_text = Some(r.trim().to_string());
                }
            }
            _ => {}
        }
    }

    let status = child.wait().await.map_err(|e| e.to_string())?;
    let errbuf = stderr_task.await.unwrap_or_default();
    if !status.success() {
        let msg = errbuf.trim();
        return Err(if msg.is_empty() {
            "claude CLI failed".to_string()
        } else {
            format!("claude CLI failed: {msg}")
        });
    }

    // Prefer the streamed accumulation; fall back to the result line.
    let full = if !acc.trim().is_empty() {
        acc.trim().to_string()
    } else {
        result_text.unwrap_or_default()
    };
    if full.is_empty() {
        return Err("claude returned no result".to_string());
    }
    Ok(full)
}

fn transcript(messages: &[ChatMsg]) -> String {
    messages
        .iter()
        .map(|m| {
            let who = if m.role == "user" { "User" } else { "Assistant" };
            format!("{who}: {}", m.content)
        })
        .collect::<Vec<_>>()
        .join("\n\n")
}

async fn claude_cli(bin: &str, system: &str, messages: &[ChatMsg]) -> Result<String, String> {
    let prompt = format!(
        "{}\n\nReply to the latest User message.",
        transcript(messages)
    );
    let mut cmd = tokio::process::Command::new(bin);
    cmd.args(claude_args(system, false, env_nonempty("BROPS_CLAUDE_MODEL").as_deref()))
        .current_dir(ai_sandbox_dir()?)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true);
    let mut child = cmd.spawn().map_err(|e| {
        format!("Could not run `{bin}` ({e}). Install Claude Code and log in, set BROPS_CLAUDE_BIN to its path, or set ANTHROPIC_API_KEY.")
    })?;
    // Feed the transcript to stdin (never argv → not in /proc/<pid>/cmdline) on a
    // background task that runs concurrently with the timeout-bounded wait — so a
    // stalled stdin write (full pipe, child not reading) can't hang the request
    // forever. On timeout, kill_on_drop reaps the child and this task's write
    // fails harmlessly.
    if let Some(mut stdin) = child.stdin.take() {
        let bytes = prompt.into_bytes();
        tokio::spawn(async move {
            use tokio::io::AsyncWriteExt;
            let _ = stdin.write_all(&bytes).await;
            let _ = stdin.shutdown().await;
        });
    }
    let out = tokio::time::timeout(Duration::from_secs(120), child.wait_with_output())
        .await
        .map_err(|_| "claude CLI timed out".to_string())?
        .map_err(|e| format!("claude CLI error: {e}"))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(format!("claude CLI failed: {}", err.trim()));
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let json: serde_json::Value = serde_json::from_str(stdout.trim())
        .map_err(|e| format!("could not parse claude output ({e})"))?;
    json.get("result")
        .and_then(|r| r.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "claude returned no result".to_string())
}

async fn ollama(url: &str, model: &str, system: &str, messages: &[ChatMsg]) -> Result<String, String> {
    let mut msgs = vec![serde_json::json!({ "role": "system", "content": system })];
    for m in messages {
        msgs.push(serde_json::json!({ "role": m.role, "content": m.content }));
    }
    let body = serde_json::json!({ "model": model, "messages": msgs, "stream": false });
    let resp = reqwest::Client::new()
        .post(format!("{url}/api/chat"))
        .timeout(Duration::from_secs(120))
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Local Ollama not reachable ({e})."))?;
    if !resp.status().is_success() {
        let code = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Ollama error {code}: {text}"));
    }
    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    json.get("message")
        .and_then(|m| m.get("content"))
        .and_then(|c| c.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| "Ollama returned no content".to_string())
}

async fn anthropic(key: &str, model: &str, system: &str, messages: &[ChatMsg]) -> Result<String, String> {
    if key.is_empty() {
        return Err("ANTHROPIC_API_KEY is empty".to_string());
    }
    let body = serde_json::json!({
        "model": model,
        "max_tokens": 1024,
        "system": system,
        "messages": messages.iter().map(|m| serde_json::json!({ "role": m.role, "content": m.content })).collect::<Vec<_>>(),
    });
    let resp = reqwest::Client::new()
        .post(ANTHROPIC_URL)
        .timeout(Duration::from_secs(120))
        .header("x-api-key", key)
        .header("anthropic-version", ANTHROPIC_VERSION)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Anthropic request failed: {e}"))?;
    if !resp.status().is_success() {
        let code = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Anthropic error {code}: {text}"));
    }
    let json: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    let text: String = json
        .get("content")
        .and_then(|c| c.as_array())
        .map(|blocks| {
            blocks
                .iter()
                .filter_map(|b| b.get("text").and_then(|t| t.as_str()))
                .collect::<Vec<_>>()
                .join("")
        })
        .unwrap_or_default()
        .trim()
        .to_string();
    if text.is_empty() {
        return Err("Anthropic returned no text content".to_string());
    }
    Ok(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    // Security regression: chat calls must disable ALL Claude tools so a
    // prompt-injection can't read/write files or run commands via the agent.
    #[test]
    fn claude_args_lock_down_tools_mcp_and_settings_on_every_path() {
        let secret = "User: my password is hunter2";
        for streaming in [true, false] {
            let args = claude_args("be nice", streaming, None);
            // The transcript/prompt must NOT be in argv (it goes via stdin) — no
            // arg may carry chat content, and there's no bare prompt positional.
            assert!(!args.iter().any(|a| a.contains(secret) || a.contains("hunter2")));
            assert!(!args.iter().any(|a| a == secret));
            // `--tools ""` present as an adjacent pair → all built-in tools off.
            let pos = args.iter().position(|a| a == "--tools").expect("--tools flag present");
            assert_eq!(args.get(pos + 1), Some(&String::new()), "--tools must be followed by \"\"");
            // MCP fully locked to the (absent) --mcp-config → no MCP servers load.
            assert!(args.iter().any(|a| a == "--strict-mcp-config"), "must pass --strict-mcp-config");
            // only project settings load (from the empty sandbox) → no user hooks/plugins/MCP.
            let sp = args.iter().position(|a| a == "--setting-sources").expect("--setting-sources present");
            assert_eq!(args.get(sp + 1), Some(&"project".to_string()));
            assert!(args.iter().any(|a| a == "--no-session-persistence"));
            // never bypass permissions / re-enable tools.
            assert!(!args.iter().any(|a| a == "--dangerously-skip-permissions"
                || a == "--allow-dangerously-skip-permissions"
                || a == "--allowedTools" || a == "--allowed-tools"));
            assert!(!args.iter().any(|a| a == "default"), "must not pass --tools default");
        }
    }

    #[test]
    fn claude_args_model_is_optional_and_appended() {
        let none = claude_args("s", false, None);
        assert!(!none.iter().any(|a| a == "--model"));
        let some = claude_args("s", true, Some("claude-x"));
        let pos = some.iter().position(|a| a == "--model").expect("--model present");
        assert_eq!(some.get(pos + 1), Some(&"claude-x".to_string()));
    }
}
