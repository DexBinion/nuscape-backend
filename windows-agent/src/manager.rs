use std::sync::Arc;

use anyhow::Result;
use chrono::{Duration, Utc};

use crate::collectors::network::NetworkUsageCollector;
use crate::collectors::sessions::SessionCollector;
use crate::collectors::status::DeviceStatusProvider;
use crate::config::DeviceIdStore;
use crate::models::UsageBatch;
use crate::storage::UsageBatchStore;

pub struct UsageCollectionManager {
    sessions: Arc<SessionCollector>,
    network: Arc<NetworkUsageCollector>,
    status: DeviceStatusProvider,
    device_store: Arc<DeviceIdStore>,
    batch_store: Arc<UsageBatchStore>,
}

impl UsageCollectionManager {
    pub fn new(
        sessions: Arc<SessionCollector>,
        network: Arc<NetworkUsageCollector>,
        device_store: Arc<DeviceIdStore>,
        batch_store: Arc<UsageBatchStore>,
    ) -> Self {
        Self {
            sessions,
            network,
            status: DeviceStatusProvider::new(),
            device_store,
            batch_store,
        }
    }

    pub fn collect_batch(&self) -> Result<Option<UsageBatch>> {
        let device_id = self.device_store.get_or_create()?;
        let now = Utc::now();
        let window = Duration::hours(24);
        let sessions = self.sessions.drain_sessions(window);
        let network_deltas = self.network.collect()?;
        let status = self.status.build_status();

        if sessions.is_empty() && network_deltas.is_empty() {
            return Ok(None);
        }

        let batch = UsageBatch {
            device_id,
            sent_at: now,
            sessions,
            network_deltas,
            status: Some(status),
        };
        Ok(Some(batch))
    }

    pub fn collect_and_store(&self) -> Result<bool> {
        if let Some(batch) = self.collect_batch()? {
            self.batch_store.enqueue(batch)?;
            return Ok(true);
        }
        Ok(false)
    }

    pub fn batch_store(&self) -> Arc<UsageBatchStore> {
        Arc::clone(&self.batch_store)
    }
}
