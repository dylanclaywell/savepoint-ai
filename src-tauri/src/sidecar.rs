//! Python sidecar lifecycle: pick a free port, spawn the process, poll
//! `/health` until it answers, and kill it on app exit.
//!
//! Dev builds run the sidecar through `uv` from the `sidecar/` source tree so
//! no frozen binary is needed while iterating. Release builds will spawn the
//! PyInstaller `externalBin` instead (wired at the packaging step).

use std::net::TcpListener;
use std::path::Path;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

/// Shared sidecar state held in Tauri's managed state.
#[derive(Default)]
pub struct SidecarState {
    pub port: Mutex<Option<u16>>,
    pub child: Mutex<Option<Child>>,
}

/// Ask the OS for a free localhost port by binding to :0 and reading it back.
fn pick_free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    // Listener drops here, freeing the port for the sidecar to claim.
    Ok(port)
}

/// Spawn the sidecar process bound to `port`, writing data to `data_dir`.
fn spawn_sidecar(port: u16, data_dir: &Path) -> std::io::Result<Child> {
    let port = port.to_string();
    let data_dir = data_dir.to_string_lossy().to_string();
    if cfg!(debug_assertions) {
        // Dev: run from source via uv. `--directory` points uv at the sidecar
        // project regardless of the launcher's cwd.
        let sidecar_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../sidecar");
        Command::new("uv")
            .args([
                "run",
                "--directory",
                sidecar_dir,
                "savepoint-sidecar",
                "--port",
                &port,
                "--data-dir",
                &data_dir,
            ])
            .spawn()
    } else {
        // Release: the PyInstaller binary is bundled as a Tauri externalBin and
        // lands next to the app executable (triple suffix stripped at runtime).
        let bin = std::env::current_exe()?
            .parent()
            .ok_or_else(|| {
                std::io::Error::new(std::io::ErrorKind::NotFound, "no exe parent dir")
            })?
            .join(SIDECAR_BIN);
        let mut cmd = Command::new(bin);
        cmd.args(["--port", &port, "--data-dir", &data_dir]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        cmd.spawn()
    }
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(windows)]
const SIDECAR_BIN: &str = "savepoint-sidecar.exe";
#[cfg(not(windows))]
const SIDECAR_BIN: &str = "savepoint-sidecar";

/// Poll `/health` until it returns 200 or the timeout elapses.
async fn wait_for_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::Client::new();
    for _ in 0..40 {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    false
}

/// Start the sidecar and store its port/child in state. Returns the port.
pub async fn start(state: &SidecarState, data_dir: &Path) -> Result<u16, String> {
    let port = pick_free_port().map_err(|e| format!("no free port: {e}"))?;
    let child =
        spawn_sidecar(port, data_dir).map_err(|e| format!("spawn failed: {e}"))?;

    *state.child.lock().unwrap() = Some(child);

    if !wait_for_health(port).await {
        return Err(format!("sidecar did not become healthy on port {port}"));
    }

    *state.port.lock().unwrap() = Some(port);
    Ok(port)
}

/// Kill the sidecar process if running. Called on app exit.
///
/// We launch a parent that spawns its own child (uv → python in dev; the
/// PyInstaller one-file bootloader → the real app in release), and Windows does
/// not kill children when the parent dies. So tear down the whole process tree.
pub fn stop(state: &SidecarState) {
    if let Some(mut child) = state.child.lock().unwrap().take() {
        #[cfg(windows)]
        {
            let _ = Command::new("taskkill")
                .args(["/PID", &child.id().to_string(), "/T", "/F"])
                .creation_flags_no_window()
                .output();
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// Small extension so the taskkill helper itself doesn't flash a console window.
#[cfg(windows)]
trait NoWindow {
    fn creation_flags_no_window(&mut self) -> &mut Self;
}
#[cfg(windows)]
impl NoWindow for Command {
    fn creation_flags_no_window(&mut self) -> &mut Self {
        use std::os::windows::process::CommandExt;
        self.creation_flags(CREATE_NO_WINDOW)
    }
}
