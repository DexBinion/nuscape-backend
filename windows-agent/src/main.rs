#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod auth;
mod collectors;
mod config;
mod manager;
mod models;
mod runtime;
mod storage;
mod uploader;

use auth::TokenStore;
use collectors::network::NetworkUsageCollector;
use collectors::sessions::SessionCollector;
use config::{DeviceIdStore, UsageConfigStore};
use manager::UsageCollectionManager;
use parking_lot::Mutex;
use runtime::AgentRuntime;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use storage::{NetworkCounterStore, StoragePaths, UsageBatchStore};
use tauri::{AppHandle, CustomMenuItem, Manager, SystemTray, SystemTrayEvent, SystemTrayMenu};
use tokio::task::JoinHandle;
use uploader::UsageUploader;

struct AgentState {
    handles: Mutex<Vec<JoinHandle<()>>>,
}

impl AgentState {
    fn new(handles: Vec<JoinHandle<()>>) -> Self {
        Self {
            handles: Mutex::new(handles),
        }
    }

    fn abort_all(&self) {
        let mut handles = self.handles.lock();
        for handle in handles.drain(..) {
            handle.abort();
        }
    }
}

fn dnscrypt_search_dirs(app: &AppHandle) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            dirs.push(dir.join("dnscrypt"));
        }
    }
    if let Some(res) = app.path_resolver().resource_dir() {
        dirs.push(res.join("dnscrypt"));
    }
    if let Some(app_dir) = app.path_resolver().app_local_data_dir() {
        dirs.push(app_dir.join("dnscrypt"));
    }
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd.join("dnscrypt"));
    }
    dirs
}

fn find_dnscrypt_paths(app: &AppHandle) -> Option<(PathBuf, PathBuf)> {
    for base in dnscrypt_search_dirs(app) {
        let exe = base.join("dnscrypt-proxy.exe");
        let cfg = base.join("dnscrypt-proxy.toml");
        if exe.exists() && cfg.exists() {
            return Some((exe, cfg));
        }
    }
    None
}

fn spawn_dnscrypt(exe: &Path, cfg: &Path) -> io::Result<()> {
    Command::new(exe)
        .args(["-config", &cfg.display().to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    log::info!("dnscrypt-proxy started");
    Ok(())
}

fn get_active_adapter_name() -> io::Result<Option<String>> {
    let output = Command::new("netsh")
        .args(["interface", "show", "interface"])
        .output()?;
    if !output.status.success() {
        return Ok(None);
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines().filter(|l| !l.trim().is_empty()) {
        if line.contains("Connected") && (line.contains("Dedicated") || line.contains("External")) {
            let parts: Vec<&str> = line.trim().split_whitespace().collect();
            if let Some(name) = parts.last() {
                return Ok(Some(name.to_string()));
            }
        }
    }
    Ok(None)
}

fn set_system_dns(adapter_name: &str) -> io::Result<()> {
    let cmd = format!(
        "interface ip set dns name=\"{}\" static 127.0.0.1",
        adapter_name
    );
    let status = Command::new("netsh")
        .args(cmd.split(' '))
        .status()?;
    if status.success() {
        log::info!("DNS set to 127.0.0.1 on \"{}\"", adapter_name);
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::Other,
            "netsh set dns failed (likely needs admin)",
        ))
    }
}

fn setup_background(handle: &AppHandle) {
    match find_dnscrypt_paths(handle) {
        Some((exe, cfg)) => {
            if let Err(e) = spawn_dnscrypt(&exe, &cfg) {
                log::error!("Failed to start dnscrypt-proxy: {e}");
            }
        }
        None => {
            log::warn!("dnscrypt binaries not found. Place dnscrypt-proxy.exe and dnscrypt-proxy.toml under dnscrypt/");
        }
    }

    match get_active_adapter_name() {
        Ok(Some(adapter)) => {
            if let Err(e) = set_system_dns(&adapter) {
                log::error!("Failed to set system DNS: {e}");
            }
        }
        Ok(None) => log::warn!("No connected adapter found"),
        Err(e) => log::error!("Adapter detection error: {e}"),
    }
}

fn build_tray() -> SystemTray {
    let quit = CustomMenuItem::new("quit".to_string(), "Quit NuScape");
    let menu = SystemTrayMenu::new().add_item(quit);
    SystemTray::new().with_menu(menu)
}

fn on_tray_event(app: &AppHandle, event: SystemTrayEvent) {
    match event {
        SystemTrayEvent::MenuItemClick { id, .. } => {
            if id == "quit" {
                if let Some(state) = app.try_state::<AgentState>() {
                    state.abort_all();
                }
                app.exit(0);
            }
        }
        _ => {}
    }
}

fn init_agent() -> anyhow::Result<Vec<JoinHandle<()>>> {
    let paths = StoragePaths::new()?;
    let batch_store = Arc::new(UsageBatchStore::new(&paths)?);
    let counter_store = Arc::new(NetworkCounterStore::new(&paths)?);
    let token_store = Arc::new(TokenStore::new(&paths)?);
    let config_store = Arc::new(UsageConfigStore::new(&paths)?);
    let device_store = Arc::new(DeviceIdStore::new(&paths)?);

    let session_collector = Arc::new(SessionCollector::new());
    let network_collector = Arc::new(NetworkUsageCollector::new(counter_store));

    let manager = Arc::new(UsageCollectionManager::new(
        session_collector.clone(),
        network_collector,
        device_store,
        batch_store.clone(),
    ));

    let uploader = Arc::new(UsageUploader::new(
        config_store,
        token_store,
        batch_store,
    )?);

    let runtime = Arc::new(AgentRuntime::new(
        session_collector,
        manager,
        uploader,
    ));

    Ok(runtime.spawn())
}

fn main() {
    let _ = env_logger::builder()
        .format_timestamp_secs()
        .try_init();

    tauri::Builder::default()
        .system_tray(build_tray())
        .on_system_tray_event(on_tray_event)
        .setup(|app| {
            let handle = app.handle();
            setup_background(&handle);
            match init_agent() {
                Ok(handles) => {
                    app.manage(AgentState::new(handles));
                }
                Err(err) => {
                    log::error!("agent init failed: {err:?}");
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
