/// Manages the persistent Python sidecar process.
///
/// Stage 4 redesign: a background reader task reads stdout continuously and
/// routes each NDJSON line to a per-request channel keyed by the `id` field.
/// This lets multiple concurrent `send_streaming` callers coexist on the same
/// sidecar process without stealing each other's lines.
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout};
use tokio::sync::{mpsc, Mutex};
use tokio::task::JoinHandle;

type Router = Arc<Mutex<HashMap<String, mpsc::UnboundedSender<Value>>>>;

/// Ring buffer of the sidecar's recent stderr lines, surfaced in error messages
/// when the sidecar exits unexpectedly. Without this a startup crash is invisible.
type StderrTail = Arc<Mutex<Vec<String>>>;

const STDERR_TAIL_LINES: usize = 40;

struct SidecarInner {
    child: Child,
    stdin: Arc<Mutex<ChildStdin>>,
    router: Router,
    reader_task: JoinHandle<()>,
    stderr_task: JoinHandle<()>,
    stderr_tail: StderrTail,
}

pub struct SidecarManager {
    inner: Mutex<Option<SidecarInner>>,
}

impl SidecarManager {
    pub fn new() -> Self {
        SidecarManager {
            inner: Mutex::new(None),
        }
    }

    /// Spawn the sidecar if not alive. Detects dead processes and respawns.
    pub async fn ensure_alive(&self, python: &PathBuf, script: &PathBuf) -> Result<(), String> {
        let mut guard = self.inner.lock().await;

        let needs_spawn = match guard.as_mut() {
            None => true,
            Some(inner) => match inner.child.try_wait() {
                Ok(None) => false, // still running
                _ => true,         // exited or check failed
            },
        };

        if needs_spawn {
            if let Some(mut old) = guard.take() {
                // Explicitly kill the child before dropping — tokio's Child does NOT
                // kill on drop by default, so without this the python.exe would orphan.
                let _ = old.child.start_kill();
                old.reader_task.abort();
                old.stderr_task.abort();
            }
            *guard = Some(spawn(python, script)?);
        }

        Ok(())
    }

    /// Send one v1 request and stream back the response.
    ///
    /// Registers a per-id channel in the router before writing to stdin so no
    /// lines can be lost. Progress lines are forwarded to `on_progress`; the
    /// first non-progress line is the final response.
    ///
    /// A 150 s IDLE backstop guards against a silent/dead sidecar: it trips only if
    /// no line (heartbeat or response) arrives for 150 s. Long operations (e.g. AI
    /// cleanup) stream heartbeats to stay under it; the sidecar enforces its own
    /// per-operation caps.
    pub async fn send_streaming(
        &self,
        request: &Value,
        on_progress: impl Fn(Value) + Send,
    ) -> Result<Value, String> {
        let id = request["id"]
            .as_str()
            .unwrap_or("")
            .to_string();

        // Clone Arcs without holding the inner lock during the whole call.
        let (stdin_arc, router_arc, stderr_tail) = {
            let guard = self.inner.lock().await;
            let inner = guard
                .as_ref()
                .ok_or_else(|| "Sidecar is not running. Run the health check first.".to_string())?;
            (
                Arc::clone(&inner.stdin),
                Arc::clone(&inner.router),
                Arc::clone(&inner.stderr_tail),
            )
        };

        // Register channel BEFORE writing to stdin — eliminates the race where
        // the sidecar responds before we start listening.
        let (tx, mut rx) = mpsc::unbounded_channel::<Value>();
        {
            let mut router = router_arc.lock().await;
            router.insert(id.clone(), tx);
        }

        // Write request.
        {
            let mut stdin = stdin_arc.lock().await;
            let mut line = serde_json::to_string(request)
                .map_err(|e| format!("Could not serialise request: {e}"))?;
            line.push('\n');
            if let Err(e) = stdin.write_all(line.as_bytes()).await {
                let mut router = router_arc.lock().await;
                router.remove(&id);
                return Err(format!("Could not write to sidecar: {e}"));
            }
        }

        // IDLE timeout: the sidecar must send *something* (progress heartbeat or the
        // final response) within this window. Long operations like AI cleanup stay
        // alive by streaming heartbeats; only a genuinely silent/dead sidecar trips it.
        let idle = Duration::from_secs(150);
        let result: Result<Value, String> = loop {
            match tokio::time::timeout(idle, rx.recv()).await {
                Err(_) => {
                    break Err(
                        "Sidecar went silent for 150 seconds. Restart the app.".to_string(),
                    )
                }
                Ok(None) => {
                    let tail = stderr_tail.lock().await;
                    let detail = if tail.is_empty() {
                        "Sidecar exited unexpectedly. Restart the app.".to_string()
                    } else {
                        format!(
                            "Sidecar exited unexpectedly. Recent output:\n{}",
                            tail.join("\n")
                        )
                    };
                    break Err(detail)
                }
                Ok(Some(val)) => {
                    if val.get("type").and_then(|v| v.as_str()) == Some("progress") {
                        on_progress(val);
                    } else {
                        break Ok(val);
                    }
                }
            }
        };

        // Always deregister, even on timeout or error.
        {
            let mut router = router_arc.lock().await;
            router.remove(&id);
        }

        // On timeout, send a targeted cancel so the sidecar stops the orphaned
        // request instead of processing it for up to 600 s (OCR/audio timeout).
        if result.is_err() {
            let cancel_req = serde_json::json!({
                "v": 1, "id": "cancel-timeout", "method": "cancel",
                "params": { "id": id }
            });
            if let Ok(line) = serde_json::to_string(&cancel_req) {
                let mut stdin = stdin_arc.lock().await;
                let mut buf = line;
                buf.push('\n');
                let _ = stdin.write_all(buf.as_bytes()).await;
            }
        }

        result
    }

    /// Kill the running sidecar (if any) so the next `ensure_alive` spawns a fresh
    /// process. Used after installing new Python packages — the existing process
    /// cannot hot-reload imports.
    pub async fn kill_sidecar(&self) {
        let mut guard = self.inner.lock().await;
        if let Some(mut old) = guard.take() {
            // Explicitly kill — without this the child process would orphan on Windows
            // (tokio's Child does not kill on drop by default). kill_on_drop(true) on the
            // spawn is a belt-and-suspenders backstop; this is the deterministic path.
            let _ = old.child.start_kill();
            old.reader_task.abort();
            old.stderr_task.abort();
        }
    }

    /// Write a cancel request to the sidecar. With empty params the sidecar
    /// cancels ALL active conversions (correct for both single-file and batch).
    pub async fn cancel(&self) -> Result<(), String> {
        let stdin_arc = {
            let guard = self.inner.lock().await;
            guard.as_ref().map(|inner| Arc::clone(&inner.stdin))
        };
        if let Some(stdin_arc) = stdin_arc {
            let cancel_req = serde_json::json!({
                "v": 1,
                "id": "cancel",
                "method": "cancel",
                "params": {}
            });
            let mut line = serde_json::to_string(&cancel_req).unwrap();
            line.push('\n');
            let mut stdin = stdin_arc.lock().await;
            stdin
                .write_all(line.as_bytes())
                .await
                .map_err(|e| format!("Could not write cancel request: {e}"))?;
        }
        Ok(())
    }
}

fn spawn(python: &PathBuf, script: &PathBuf) -> Result<SidecarInner, String> {
    // Build via std::process::Command so we can apply the Windows no-console flag,
    // then hand it to tokio for async pipes. Force UTF-8 everywhere (Python UTF-8
    // Mode): without it the sidecar and its worker default to the OS locale codec
    // (ascii/cp1252 on Windows) and choke on non-ASCII content. The worker inherits env.
    let mut std_cmd = std::process::Command::new(python);
    std_cmd
        .arg(script)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    crate::hide_console(&mut std_cmd);
    let mut child = tokio::process::Command::from(std_cmd)
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("Could not start background process: {e}"))?;

    let stdin = child.stdin.take().ok_or("Could not get sidecar stdin")?;
    let stdout = child.stdout.take().ok_or("Could not get sidecar stdout")?;
    let stderr = child.stderr.take().ok_or("Could not get sidecar stderr")?;

    let router: Router = Arc::new(Mutex::new(HashMap::new()));
    let router_clone = Arc::clone(&router);

    let stderr_tail: StderrTail = Arc::new(Mutex::new(Vec::new()));
    let stderr_tail_clone = Arc::clone(&stderr_tail);

    let reader_task = tokio::spawn(reader_loop(BufReader::new(stdout), router_clone));
    let stderr_task = tokio::spawn(stderr_loop(BufReader::new(stderr), stderr_tail_clone));

    Ok(SidecarInner {
        child,
        stdin: Arc::new(Mutex::new(stdin)),
        router,
        reader_task,
        stderr_task,
        stderr_tail,
    })
}

/// Reads stdout lines from the sidecar and routes each to the matching channel.
/// When the sidecar exits (Ok(0) / Err), clears all channels so waiting
/// `send_streaming` callers receive `None` and return an error.
async fn reader_loop(mut reader: BufReader<ChildStdout>, router: Router) {
    let mut buf = String::new();
    loop {
        buf.clear();
        match reader.read_line(&mut buf).await {
            Ok(0) | Err(_) => {
                // Sidecar closed stdout — drop all senders so receivers get None.
                let mut r = router.lock().await;
                r.clear();
                break;
            }
            Ok(_) => {
                let trimmed = buf.trim();
                if trimmed.is_empty() {
                    continue;
                }
                if let Ok(val) = serde_json::from_str::<Value>(trimmed) {
                    if let Some(id) = val.get("id").and_then(|v| v.as_str()) {
                        let r = router.lock().await;
                        if let Some(tx) = r.get(id) {
                            let _ = tx.send(val);
                        }
                        // Lines with unknown ids (e.g. startup noise) are silently dropped.
                    }
                }
            }
        }
    }
}

/// Drains the sidecar's stderr into a small ring buffer so a startup crash or
/// unexpected exit can be diagnosed instead of showing a bare "exited unexpectedly".
async fn stderr_loop(mut reader: BufReader<tokio::process::ChildStderr>, tail: StderrTail) {
    let mut buf = String::new();
    loop {
        buf.clear();
        match reader.read_line(&mut buf).await {
            Ok(0) | Err(_) => break,
            Ok(_) => {
                let line = buf.trim_end().to_string();
                if line.is_empty() {
                    continue;
                }
                let mut t = tail.lock().await;
                if t.len() >= STDERR_TAIL_LINES {
                    t.remove(0);
                }
                t.push(line);
            }
        }
    }
}
