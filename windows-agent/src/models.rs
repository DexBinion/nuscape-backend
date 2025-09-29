use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use serde_with::{serde_as, DisplayFromStr};
use uuid::Uuid;

pub const MAX_PAYLOAD_BYTES: usize = 1_000_000;
pub const DEFAULT_CHUNK_SESSION_LIMIT: usize = 100;
pub const DEFAULT_CHUNK_BYTE_LIMIT: usize = 100_000;

#[serde_as]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageSession {
    #[serde(rename = "package")]
    pub package: String,
    #[serde(rename = "windowStart")]
    #[serde_as(as = "DisplayFromStr")]
    pub window_start: DateTime<Utc>,
    #[serde(rename = "windowEnd")]
    #[serde_as(as = "DisplayFromStr")]
    pub window_end: DateTime<Utc>,
    #[serde(rename = "totalMs")]
    pub total_ms: u64,
    #[serde(rename = "fg")]
    pub foreground: bool,
}

impl UsageSession {
    pub fn duration(&self) -> Duration {
        Duration::milliseconds(self.total_ms as i64)
    }
}

#[serde_as]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkDelta {
    #[serde(rename = "package")]
    pub package: String,
    #[serde(rename = "sampled_at")]
    #[serde_as(as = "DisplayFromStr")]
    pub sampled_at: DateTime<Utc>,
    #[serde(rename = "wifi_bytes")]
    pub wifi_bytes: u64,
    #[serde(rename = "cell_bytes")]
    pub cellular_bytes: u64,
}

#[serde_as]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkCounters {
    #[serde(rename = "wifi")]
    pub wifi_total: u64,
    #[serde(rename = "cell")]
    pub cell_total: u64,
    #[serde(rename = "sampled_at")]
    #[serde_as(as = "DisplayFromStr")]
    pub sampled_at: DateTime<Utc>,
}

#[serde_as]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceStatus {
    #[serde(rename = "usage_access")]
    pub usage_access: bool,
    #[serde(rename = "accessibility")]
    pub accessibility: bool,
    #[serde(rename = "overlay")]
    pub overlay: bool,
    #[serde(rename = "vpn")]
    pub vpn: bool,
    #[serde(rename = "battery_pct")]
    pub battery_pct: f64,
    #[serde(rename = "tz")]
    pub time_zone_id: String,
}

#[serde_as]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageBatch {
    #[serde(rename = "device_id")]
    pub device_id: Uuid,
    #[serde(rename = "sent_at")]
    #[serde_as(as = "DisplayFromStr")]
    pub sent_at: DateTime<Utc>,
    #[serde(rename = "sessions")]
    pub sessions: Vec<UsageSession>,
    #[serde(rename = "net_deltas")]
    pub network_deltas: Vec<NetworkDelta>,
    #[serde(rename = "status", skip_serializing_if = "Option::is_none")]
    pub status: Option<DeviceStatus>,
}

impl UsageBatch {
    pub fn to_json_string(&self) -> anyhow::Result<String> {
        Ok(serde_json::to_string(self)?)
    }

    pub fn size_fits(&self) -> bool {
        self.to_json_string()
            .map(|s| s.as_bytes().len() <= MAX_PAYLOAD_BYTES)
            .unwrap_or(false)
    }

    pub fn chunked(
        &self,
        max_sessions: usize,
        max_bytes: usize,
    ) -> anyhow::Result<Vec<UsageBatch>> {
        if self.sessions.is_empty() {
            return Ok(vec![self.clone()]);
        }

        let mut result = Vec::new();
        let mut include_meta = true;
        let mut index = 0usize;

        while index < self.sessions.len() {
            let mut end = (index + max_sessions).min(self.sessions.len());
            let mut slice = &self.sessions[index..end];
            let mut chunk = UsageBatch {
                device_id: self.device_id,
                sent_at: self.sent_at,
                sessions: slice.to_vec(),
                network_deltas: if include_meta {
                    self.network_deltas.clone()
                } else {
                    Vec::new()
                },
                status: if include_meta {
                    self.status.clone()
                } else {
                    None
                },
            };

            let mut payload_bytes = chunk.to_json_string()?.into_bytes().len();
            while payload_bytes > max_bytes && slice.len() > 1 {
                end -= 1;
                slice = &self.sessions[index..end];
                chunk.sessions = slice.to_vec();
                chunk.network_deltas = if include_meta {
                    self.network_deltas.clone()
                } else {
                    Vec::new()
                };
                chunk.status = if include_meta {
                    self.status.clone()
                } else {
                    None
                };
                payload_bytes = chunk.to_json_string()?.into_bytes().len();
            }

            result.push(chunk);
            index = end;
            include_meta = false;
        }

        if result.is_empty() {
            result.push(UsageBatch {
                device_id: self.device_id,
                sent_at: self.sent_at,
                sessions: Vec::new(),
                network_deltas: self.network_deltas.clone(),
                status: self.status.clone(),
            });
        }

        Ok(result)
    }
}

#[derive(Debug, Clone)]
pub struct UploadConfig {
    pub base_url: reqwest::Url,
    pub batch_url: reqwest::Url,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestOutcome {
    pub success: bool,
    pub failure: Option<UploadFailureReason>,
    pub body: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UploadResult {
    pub uploaded_batches: usize,
    pub failure_reason: Option<UploadFailureReason>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum UploadFailureReason {
    MissingConfig,
    MissingToken,
    TokenExpired,
    Unauthorized,
    NetworkError,
    ServerError,
}

impl UploadFailureReason {
    pub fn retryable(&self) -> bool {
        matches!(
            self,
            UploadFailureReason::MissingConfig
                | UploadFailureReason::MissingToken
                | UploadFailureReason::TokenExpired
        )
    }
}
