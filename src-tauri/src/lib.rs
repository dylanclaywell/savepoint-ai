mod sidecar;

use sidecar::SidecarState;
use tauri::{Manager, RunEvent, State};

/// Frontend calls this to learn which localhost port the sidecar is on, then
/// talks to it directly over HTTP. Returns null until the sidecar is healthy.
#[tauri::command]
fn sidecar_port(state: State<SidecarState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let data_dir = app
                .path()
                .app_data_dir()
                .expect("could not resolve app data dir");
            // Start the sidecar off the main thread; the UI shows a
            // "starting…" state until sidecar_port() returns a value.
            tauri::async_runtime::spawn(async move {
                let state = handle.state::<SidecarState>();
                match sidecar::start(&state, &data_dir).await {
                    Ok(port) => eprintln!("[sidecar] healthy on port {port}"),
                    Err(e) => eprintln!("[sidecar] failed to start: {e}"),
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar_port])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<SidecarState>();
                sidecar::stop(&state);
            }
        });
}
