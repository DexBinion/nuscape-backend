use std::collections::{HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use directories::ProjectDirs;
use parking_lot::Mutex;

use crate::models::{NetworkCounters, UsageBatch};

const APP_QUALIFIER: (&str, &str, &str) = ("com", "NuScape", "NuScapeAgent");
const QUEUE_FILE: &str = "usage_queue.json";
const COUNTERS_FILE: &str = "network_counters.json";
const DEVICE_FILE: &str = "device.json";
const TOKENS_FILE: &str = "tokens.json";
const CONFIG_FILE: &str = "config.json";

pub struct StoragePaths {
    root: PathBuf,
}

impl StoragePaths {
    pub fn new() -> Result<Self> {
        let dirs = ProjectDirs::from(APP_QUALIFIER.0, APP_QUALIFIER.1, APP_QUALIFIER.2)
            .context("unable to resolve storage directory")?;
        let root = dirs.data_dir().to_path_buf();
        fs::create_dir_all(&root)?;
        Ok(Self { root })
    }

    fn join(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }

    pub fn queue_path(&self) -> PathBuf {
        self.join(QUEUE_FILE)
    }

    pub fn counters_path(&self) -> PathBuf {
        self.join(COUNTERS_FILE)
    }

    pub fn device_path(&self) -> PathBuf {
        self.join(DEVICE_FILE)
    }

    pub fn tokens_path(&self) -> PathBuf {
        self.join(TOKENS_FILE)
    }

    pub fn config_path(&self) -> PathBuf {
        self.join(CONFIG_FILE)
    }
}

pub struct UsageBatchStore {
    queue: Mutex<VecDeque<UsageBatch>>,
    path: PathBuf,
}

impl UsageBatchStore {
    pub fn new(paths: &StoragePaths) -> Result<Self> {
        let path = paths.queue_path();
        let queue = if path.exists() {
            let data = fs::read_to_string(&path)?;
            let parsed: Vec<UsageBatch> = serde_json::from_str(&data)?;
            VecDeque::from(parsed)
        } else {
            VecDeque::new()
        };
        Ok(Self {
            queue: Mutex::new(queue),
            path,
        })
    }

    fn persist_locked(queue: &VecDeque<UsageBatch>, path: &Path) -> Result<()> {
        let serialized = serde_json::to_string_pretty(queue)?;
        fs::write(path, serialized)?;
        Ok(())
    }

    pub fn enqueue(&self, batch: UsageBatch) -> Result<()> {
        if !batch.size_fits() {
            log::warn!("skipping oversized batch ({} sessions)", batch.sessions.len());
            return Ok(());
        }
        let mut guard = self.queue.lock();
        guard.push_back(batch);
        Self::persist_locked(&guard, &self.path)
    }

    pub fn peek(&self) -> Option<UsageBatch> {
        self.queue.lock().front().cloned()
    }

    pub fn pop(&self) -> Result<Option<UsageBatch>> {
        let mut guard = self.queue.lock();
        let popped = guard.pop_front();
        Self::persist_locked(&guard, &self.path)?;
        Ok(popped)
    }

    pub fn has_pending(&self) -> bool {
        !self.queue.lock().is_empty()
    }

    pub fn queue_size(&self) -> usize {
        self.queue.lock().len()
    }

    pub fn clear_queue(&self) -> Result<()> {
        let mut guard = self.queue.lock();
        guard.clear();
        Self::persist_locked(&guard, &self.path)
    }

    pub fn queue_preview(&self, limit: usize) -> Vec<UsageBatch> {
        let guard = self.queue.lock();
        guard.iter().take(limit).cloned().collect()
    }
}

pub struct NetworkCounterStore {
    path: PathBuf,
    cache: Mutex<HashMap<String, NetworkCounters>>,
}

impl NetworkCounterStore {
    pub fn new(paths: &StoragePaths) -> Result<Self> {
        let path = paths.counters_path();
        let cache = if path.exists() {
            let data = fs::read_to_string(&path)?;
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            HashMap::new()
        };
        Ok(Self {
            path,
            cache: Mutex::new(cache),
        })
    }

    pub fn load(&self) -> HashMap<String, NetworkCounters> {
        self.cache.lock().clone()
    }

    pub fn save(&self, counters: HashMap<String, NetworkCounters>) -> Result<()> {
        let mut guard = self.cache.lock();
        *guard = counters;
        let serialized = serde_json::to_string_pretty(&*guard)?;
        fs::write(&self.path, serialized)?;
        Ok(())
    }
}
