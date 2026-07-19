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
    cmd.arg("-p")
        .arg(&prompt)
        .arg("--output-format")
        .arg("json")
        .arg("--append-system-prompt")
        .arg(system);
    if let Some(model) = env_nonempty("BROPS_CLAUDE_MODEL") {
        cmd.arg("--model").arg(model);
    }
    let out = tokio::time::timeout(Duration::from_secs(120), cmd.output())
        .await
        .map_err(|_| "claude CLI timed out".to_string())?
        .map_err(|e| {
            format!("Could not run `{bin}` ({e}). Install Claude Code and log in, set BROPS_CLAUDE_BIN to its path, or set ANTHROPIC_API_KEY.")
        })?;
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
