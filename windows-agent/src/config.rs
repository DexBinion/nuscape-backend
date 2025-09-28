use std::fs;
use std::path::PathBuf;

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::models::UploadConfig;
use crate::storage::StoragePaths;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct ConfigRecord {
    api_base: Option<String>,
}

pub struct UsageConfigStore {
    path: PathBuf,
    cache: Mutex<ConfigRecord>,
}

impl UsageConfigStore {
    pub fn new(paths: &StoragePaths) -> Result<Self> {
        let path = paths.config_path();
        let cache = if path.exists() {
            let data = fs::read_to_string(&path)?;
            serde_json::from_str(&data).unwrap_or_default()
        } else {
            ConfigRecord::default()
        };
        Ok(Self {
            path,
            cache: Mutex::new(cache),
        })
    }

    pub fn set_api_base(&self, url: &str) -> Result<()> {
        let mut record = self.cache.lock();
        record.api_base = Some(url.to_string());
        let serialized = serde_json::to_string_pretty(&*record)?;
        fs::write(&self.path, serialized)?;
        Ok(())
    }

    pub fn get_api_base(&self) -> Option<String> {
        self.cache.lock().api_base.clone()
    }

    pub fn resolve_upload_config(&self) -> Result<UploadConfig> {
        let base = self
            .get_api_base()
            .context("api base url not configured")?;
        let mut base_url = reqwest::Url::parse(&base)
            .or_else(|_| reqwest::Url::parse(&(base.clone() + "/")))?;
        if !base_url.path().ends_with('/') {
            base_url.set_path(&(base_url.path().to_string() + "/"));
        }
        let mut batch_url = base_url.clone();
        batch_url
            .path_segments_mut()
            .map_err(|_| anyhow!("invalid base url"))?
            .extend(["api", "v1", "usage", "batch"]);
        Ok(UploadConfig {
            base_url,
            batch_url,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DeviceRecord {
    device_id: Uuid,
    last_seen: DateTime<Utc>,
}

pub struct DeviceIdStore {
    path: PathBuf,
    cache: Mutex<Option<DeviceRecord>>,
}

impl DeviceIdStore {
    pub fn new(paths: &StoragePaths) -> Result<Self> {
        let path = paths.device_path();
        let cache = if path.exists() {
            let data = fs::read_to_string(&path)?;
            serde_json::from_str(&data).ok()
        } else {
            None
        };
        Ok(Self {
            path,
            cache: Mutex::new(cache),
        })
    }

    pub fn get_or_create(&self) -> Result<Uuid> {
        let mut guard = self.cache.lock();
        if let Some(record) = guard.as_mut() {
            record.last_seen = Utc::now();
            let serialized = serde_json::to_string_pretty(record)?;
            fs::write(&self.path, serialized)?;
            return Ok(record.device_id);
        }
        let record = DeviceRecord {
            device_id: Uuid::new_v4(),
            last_seen: Utc::now(),
        };
        let device_id = record.device_id;
        *guard = Some(record.clone());
        let serialized = serde_json::to_string_pretty(&record)?;
        fs::write(&self.path, serialized)?;
        Ok(device_id)
    }
}
