use std::sync::Arc;
use std::time::Duration as StdDuration;

use anyhow::{anyhow, Context, Result};
use chrono::Utc;
use reqwest::Client;
use serde_json::Value;
use tokio::time::sleep;

use crate::auth::TokenStore;
use crate::config::UsageConfigStore;
use crate::models::{
    RequestOutcome, UploadFailureReason, UploadResult, DEFAULT_CHUNK_BYTE_LIMIT,
    DEFAULT_CHUNK_SESSION_LIMIT,
};
use crate::storage::UsageBatchStore;

const USER_AGENT: &str = "NuScape-Windows-Agent/1.0";

pub struct UsageUploader {
    client: Client,
    config_store: Arc<UsageConfigStore>,
    token_store: Arc<TokenStore>,
    batch_store: Arc<UsageBatchStore>,
}

impl UsageUploader {
    pub fn new(
        config_store: Arc<UsageConfigStore>,
        token_store: Arc<TokenStore>,
        batch_store: Arc<UsageBatchStore>,
    ) -> Result<Self> {
        let client = Client::builder().user_agent(USER_AGENT).build()?;
        Ok(Self {
            client,
            config_store,
            token_store,
            batch_store,
        })
    }

    pub async fn upload_pending(&self) -> Result<UploadResult> {
        let config = match self.config_store.resolve_upload_config() {
            Ok(cfg) => cfg,
            Err(err) => {
                log::warn!("upload blocked: {err:?}");
                return Ok(UploadResult {
                    uploaded_batches: 0,
                    failure_reason: Some(UploadFailureReason::MissingConfig),
                });
            }
        };

        let mut uploaded = 0usize;
        loop {
            let maybe_batch = self.batch_store.peek();
            let batch = match maybe_batch {
                Some(b) => b,
                None => break,
            };
            let chunks = batch
                .chunked(DEFAULT_CHUNK_SESSION_LIMIT, DEFAULT_CHUNK_BYTE_LIMIT)
                .context("failed to chunk batch")?;
            let mut chunk_index = 0usize;
            let mut refreshed = false;
            let mut failure: Option<UploadFailureReason> = None;

            while chunk_index < chunks.len() {
                let token = match self.token_store.access_token() {
                    Some(t) => t,
                    None => {
                        return Ok(UploadResult {
                            uploaded_batches: uploaded,
                            failure_reason: Some(UploadFailureReason::MissingToken),
                        });
                    }
                };
                if self.token_store.is_access_token_expired(Utc::now()) {
                    if !refreshed && self.try_refresh(&config).await? {
                        refreshed = true;
                        continue;
                    }
                    return Ok(UploadResult {
                        uploaded_batches: uploaded,
                        failure_reason: Some(UploadFailureReason::TokenExpired),
                    });
                }

                let chunk_json = chunks[chunk_index]
                    .to_json_string()
                    .context("serialize chunk")?;
                let request = self
                    .client
                    .post(config.batch_url.clone())
                    .bearer_auth(&token)
                    .header("Content-Type", "application/json")
                    .body(chunk_json)
                    .build()?;
                let outcome = self.execute_request(request).await?;
                if outcome.success {
                    chunk_index += 1;
                    refreshed = false;
                    continue;
                }

                let reason = outcome.failure.unwrap_or(UploadFailureReason::ServerError);
                if matches!(reason, UploadFailureReason::Unauthorized) && !refreshed {
                    if self.try_refresh(&config).await? {
                        refreshed = true;
                        continue;
                    }
                }
                if matches!(reason, UploadFailureReason::Unauthorized) {
                    let _ = self.token_store.clear();
                }
                failure = Some(reason);
                break;
            }

            if let Some(reason) = failure {
                return Ok(UploadResult {
                    uploaded_batches: uploaded,
                    failure_reason: Some(reason),
                });
            }

            if chunk_index == chunks.len() {
                self.batch_store
                    .pop()
                    .context("pop batch after success")?
                    .ok_or_else(|| anyhow!("batch disappeared before removal"))?;
                uploaded += chunks.len();
                continue;
            }
        }

        Ok(UploadResult {
            uploaded_batches: uploaded,
            failure_reason: None,
        })
    }

    async fn execute_request(&self, request: reqwest::Request) -> Result<RequestOutcome> {
        let mut attempt = 0;
        let mut backoff = StdDuration::from_millis(1_000);
        let max_attempts = 3;
        loop {
            attempt += 1;
            match self
                .client
                .execute(request.try_clone().context("failed to clone request")?)
                .await
            {
                Ok(response) => {
                    let status = response.status();
                    let body = response.text().await.ok();
                    if status.is_success() {
                        return Ok(RequestOutcome {
                            success: true,
                            failure: None,
                            body,
                        });
                    }
                    let failure = if status.as_u16() == 401 {
                        UploadFailureReason::Unauthorized
                    } else if status.as_u16() == 408 || (500..=504).contains(&status.as_u16()) {
                        UploadFailureReason::NetworkError
                    } else {
                        UploadFailureReason::ServerError
                    };
                    if attempt < max_attempts
                        && matches!(failure, UploadFailureReason::NetworkError)
                    {
                        sleep(backoff).await;
                        backoff = (backoff * 2).min(StdDuration::from_millis(10_000));
                        continue;
                    }
                    return Ok(RequestOutcome {
                        success: false,
                        failure: Some(failure),
                        body,
                    });
                }
                Err(err) => {
                    log::warn!("upload attempt {attempt} failed: {err:?}");
                    if attempt >= max_attempts {
                        return Ok(RequestOutcome {
                            success: false,
                            failure: Some(UploadFailureReason::NetworkError),
                            body: None,
                        });
                    }
                    sleep(backoff).await;
                    backoff = (backoff * 2).min(StdDuration::from_millis(10_000));
                }
            }
        }
    }

    async fn try_refresh(&self, config: &crate::models::UploadConfig) -> Result<bool> {
        let refresh = match self.token_store.refresh_token() {
            Some(token) => token,
            None => return Ok(false),
        };
        let refresh_url = config
            .base_url
            .clone()
            .join("api/v1/devices/refresh")
            .context("refresh url")?;
        let request = self
            .client
            .post(refresh_url)
            .bearer_auth(&refresh)
            .header("Content-Type", "application/json")
            .body("{}")
            .build()?;
        let response = self.client.execute(request).await?;
        if !response.status().is_success() {
            log::warn!("refresh failed: {}", response.status());
            if response.status() == reqwest::StatusCode::UNAUTHORIZED {
                let _ = self.token_store.clear();
            }
            return Ok(false);
        }
        let body = response.text().await.unwrap_or_default();
        let json: Value = serde_json::from_str(&body)?;
        let access = json
            .get("access_token")
            .and_then(|v| v.as_str())
            .ok_or_else(|| anyhow!("access_token missing"))?;
        let refresh_token = json
            .get("refresh_token")
            .and_then(|v| v.as_str())
            .unwrap_or(&refresh)
            .to_string();
        let expires = json
            .get("expires_in")
            .and_then(|v| v.as_i64())
            .unwrap_or(86_400);
        self.token_store
            .save_tokens(access.to_string(), refresh_token, expires, Utc::now())?;
        Ok(true)
    }
}
