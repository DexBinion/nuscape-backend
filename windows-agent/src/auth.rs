use std::fs;
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use chrono::{DateTime, Duration, Utc};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

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
                let expiry = t.issued_at + Duration::seconds(t.expires_in_seconds) - Duration::seconds(120);
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
