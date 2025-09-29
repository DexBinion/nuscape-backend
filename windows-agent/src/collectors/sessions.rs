use std::sync::Arc;
use std::time::Duration as StdDuration;

use anyhow::Result;
use chrono::{DateTime, Duration, Utc};
use parking_lot::Mutex;
use tauri::async_runtime;
use tauri::async_runtime::JoinHandle;
use tokio::time;
use windows::Win32::Foundation::{CloseHandle, HWND};
use windows::Win32::System::ProcessStatus::K32GetModuleBaseNameW;
use windows::Win32::System::Threading::{
    OpenProcess, PROCESS_QUERY_INFORMATION, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};

use crate::models::UsageSession;

const MIN_SESSION_MS: i64 = 5_000;
const MERGE_GAP_MS: i64 = 10_000;
const MAX_SESSION_MS: i64 = 8 * 60 * 60 * 1_000;
const SAMPLE_INTERVAL_MS: u64 = 5_000;

#[derive(Clone, Debug)]
struct RawSession {
    package: String,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
}

#[derive(Clone, Debug)]
struct ActiveSession {
    package: String,
    started_at: DateTime<Utc>,
    last_seen: DateTime<Utc>,
}

struct TrackerState {
    current: Option<ActiveSession>,
    completed: Vec<RawSession>,
}

impl TrackerState {
    fn new() -> Self {
        Self {
            current: None,
            completed: Vec::new(),
        }
    }

    fn finalize_current(&mut self) {
        if let Some(active) = self.current.take() {
            let mut end = active.last_seen;
            if end < active.started_at {
                end = active.started_at;
            }
            let total_ms = (end - active.started_at).num_milliseconds();
            if total_ms >= MIN_SESSION_MS {
                self.completed.push(RawSession {
                    package: active.package,
                    start: active.started_at,
                    end,
                });
            }
        }
    }

    fn observe(&mut self, package: Option<String>, now: DateTime<Utc>) {
        match (self.current.as_mut(), package) {
            (Some(active), Some(pkg)) if active.package == pkg => {
                active.last_seen = now;
            }
            (Some(_), Some(pkg)) => {
                self.finalize_current();
                self.current = Some(ActiveSession {
                    package: pkg,
                    started_at: now,
                    last_seen: now,
                });
            }
            (None, Some(pkg)) => {
                self.current = Some(ActiveSession {
                    package: pkg,
                    started_at: now,
                    last_seen: now,
                });
            }
            (Some(_), None) => {
                self.finalize_current();
            }
            (None, None) => {}
        }
    }

    fn drain(&mut self, now: DateTime<Utc>, window: Duration) -> Vec<RawSession> {
        let cutoff = now - window;
        let mut sessions = Vec::new();
        self.completed.retain(|raw| {
            if raw.end < cutoff {
                false
            } else {
                sessions.push(raw.clone());
                true
            }
        });
        if let Some(active) = self.current.as_ref() {
            if now - active.last_seen > Duration::milliseconds(MERGE_GAP_MS) {
                self.finalize_current();
                if let Some(last) = self.completed.last() {
                    if last.end >= cutoff {
                        sessions.push(last.clone());
                    }
                }
            }
        }
        sessions
    }
}

#[derive(Clone)]
pub struct SessionCollector {
    state: Arc<Mutex<TrackerState>>,
}

impl SessionCollector {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(TrackerState::new())),
        }
    }

    pub fn spawn_sampler(&self) -> JoinHandle<()> {
        let collector = self.clone();
        async_runtime::spawn(async move {
            let mut interval = time::interval(StdDuration::from_millis(SAMPLE_INTERVAL_MS));
            loop {
                interval.tick().await;
                if let Err(err) = collector.sample_once() {
                    log::warn!("session sample failed: {err:?}");
                }
            }
        })
    }

    fn sample_once(&self) -> Result<()> {
        let now = Utc::now();
        let package = foreground_package()?;
        let mut state = self.state.lock();
        state.observe(package, now);
        Ok(())
    }

    pub fn drain_sessions(&self, window: Duration) -> Vec<UsageSession> {
        let now = Utc::now();
        let mut state = self.state.lock();
        let raw = state.drain(now, window);
        merge_and_convert(raw)
    }
}

fn merge_and_convert(raw: Vec<RawSession>) -> Vec<UsageSession> {
    if raw.is_empty() {
        return Vec::new();
    }
    let mut sorted = raw;
    sorted.sort_by_key(|r| r.start);
    let mut merged: Vec<RawSession> = Vec::new();
    for session in sorted {
        if let Some(last) = merged.last_mut() {
            if last.package == session.package
                && (session.start - last.end).num_milliseconds() <= MERGE_GAP_MS
            {
                if session.end > last.end {
                    last.end = session.end;
                }
                continue;
            }
        }
        merged.push(session);
    }

    merged
        .into_iter()
        .filter_map(|mut s| {
            let total_ms = (s.end - s.start).num_milliseconds();
            if total_ms < MIN_SESSION_MS {
                return None;
            }
            if total_ms > MAX_SESSION_MS {
                s.end = s.start + Duration::milliseconds(MAX_SESSION_MS);
            }
            let total = (s.end - s.start).num_milliseconds().max(0) as u64;
            Some(UsageSession {
                package: s.package,
                window_start: s.start,
                window_end: s.end,
                total_ms: total,
                foreground: true,
            })
        })
        .collect()
}

fn foreground_package() -> Result<Option<String>> {
    let hwnd = unsafe { GetForegroundWindow() };
    if hwnd.0 == 0 {
        return Ok(None);
    }
    let pid = unsafe { window_process_id(hwnd) };
    if pid == 0 {
        return Ok(None);
    }
    let package = query_process_image(pid)?;
    Ok(package.filter(|pkg| should_track(pkg)))
}

unsafe fn window_process_id(hwnd: HWND) -> u32 {
    let mut pid = 0u32;
    GetWindowThreadProcessId(hwnd, Some(&mut pid));
    pid
}

fn query_process_image(pid: u32) -> Result<Option<String>> {
    let handle = unsafe {
        match OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
            false,
            pid,
        ) {
            Ok(handle) => handle,
            Err(_) => return Ok(None),
        }
    };
    let mut buffer = [0u16; 260];
    let len = unsafe { K32GetModuleBaseNameW(handle, None, &mut buffer) };
    unsafe {
        let _ = CloseHandle(handle);
    }
    if len == 0 {
        return Ok(None);
    }
    let name = String::from_utf16_lossy(&buffer[..len as usize]).to_lowercase();
    Ok(Some(name))
}

fn should_track(package: &str) -> bool {
    if package.is_empty() {
        return false;
    }
    let blacklist = [
        "explorer.exe",
        "systemsettings.exe",
        "taskmgr.exe",
        "searchui.exe",
        "sihost.exe",
    ];
    if blacklist.contains(&package) {
        return false;
    }
    let prefixes = [
        "fontdrvhost",
        "applicationframehost",
        "shellexperiencehost",
        "startmenuexperiencehost",
    ];
    if prefixes.iter().any(|p| package.starts_with(p)) {
        return false;
    }
    true
}
