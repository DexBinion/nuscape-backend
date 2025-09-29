use std::fs;
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use chrono::{DateTime, Duration, Utc};
use log;
use parking_lot::Mutex;
use reqwest;
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use crate::config::{DeviceIdStore, UsageConfigStore};
use crate::storage::StoragePaths;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TokenRecord {
    access_token: String,
    refresh_token: String,
    issued_at: DateTime<Utc>,
    expires_in_seconds: i64,
}

pub struct TokenStore {
    path: PathBuf,
    cache: Mutex<Option<TokenRecord>>,
}

impl TokenStore {
    pub fn new(paths: &StoragePaths) -> Result<Self> {
        let path = paths.tokens_path();
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

    fn load(&self) -> Option<TokenRecord> {
        self.cache.lock().clone()
    }

    pub fn access_token(&self) -> Option<String> {
        self.load().map(|t| t.access_token)
    }

    pub fn refresh_token(&self) -> Option<String> {
        self.load().map(|t| t.refresh_token)
    }

    pub fn is_access_token_expired(&self, now: DateTime<Utc>) -> bool {
        self.load()
            .map(|t| {
                let expiry =
                    t.issued_at + Duration::seconds(t.expires_in_seconds) - Duration::seconds(120);
                expiry <= now
            })
            .unwrap_or(false)
    }

    pub fn save_tokens(
        &self,
        access_token: String,
        refresh_token: String,
        expires_in_seconds: i64,
        issued_at: DateTime<Utc>,
    ) -> Result<()> {
        let record = TokenRecord {
            access_token,
            refresh_token,
            issued_at,
            expires_in_seconds,
        };
        let mut guard = self.cache.lock();
        *guard = Some(record);
        let serialized = serde_json::to_string_pretty(&*guard)?;
        fs::write(&self.path, serialized)?;
        Ok(())
    }

    pub fn has_tokens(&self) -> bool {
        self.access_token().is_some() && self.refresh_token().is_some()
    }

    pub fn clear(&self) -> Result<()> {
        {
            let mut guard = self.cache.lock();
            *guard = None;
        }
        if self.path.exists() {
            let _ = fs::remove_file(&self.path);
        }
        Ok(())
    }

    pub fn ensure_refreshable(&self) -> Result<()> {
        if self.refresh_token().is_some() {
            Ok(())
        } else {
            Err(anyhow!("refresh token missing"))
        }
    }
}
#[derive(Debug, Deserialize)]
struct RegisterResponsePayload {
    device_id: String,
    access_token: String,
    refresh_token: String,
    #[serde(default)]
    expires_in: Option<i64>,
}

pub async fn ensure_registered(
    config_store: &UsageConfigStore,
    token_store: &TokenStore,
    device_store: &DeviceIdStore,
) -> Result<()> {
    if token_store.has_tokens() {
        return Ok(());
    }

    let upload_cfg = config_store.resolve_upload_config()?;
    let register_url = upload_cfg.base_url.join("api/v1/devices/register")?;

    let computer_name =
        std::env::var("COMPUTERNAME").unwrap_or_else(|_| "windows-device".to_string());
    let user_name = std::env::var("USERNAME").unwrap_or_default();
    let hardware = json!({
        "hostname": computer_name,
        "username": user_name,
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH
    });

    let body = json!({
        "platform": "windows",
        "name": computer_name,
        "hardware": hardware
    });

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    log::info!("registering device at {}", register_url);
    let response = client.post(register_url).json(&body).send().await?;
    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        return Err(anyhow!("device registration failed: {status} {text}"));
    }

    let payload: RegisterResponsePayload = response.json().await?;
    let expires = payload.expires_in.unwrap_or(86_400) as i64;
    token_store.save_tokens(
        payload.access_token.clone(),
        payload.refresh_token.clone(),
        expires,
        Utc::now(),
    )?;

    if let Ok(device_id) = Uuid::parse_str(&payload.device_id) {
        device_store.save(device_id)?;
    }

    Ok(())
}
