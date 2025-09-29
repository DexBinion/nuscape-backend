use std::sync::Arc;

use tauri::async_runtime::{self, JoinHandle};
use tokio::time::{interval, sleep, Duration};

use crate::collectors::sessions::SessionCollector;
use crate::manager::UsageCollectionManager;
use crate::uploader::UsageUploader;

const COLLECT_INTERVAL_MINUTES: u64 = 15;
const UPLOAD_INTERVAL_SECONDS: u64 = 60;

pub struct AgentRuntime {
    sessions: Arc<SessionCollector>,
    manager: Arc<UsageCollectionManager>,
    uploader: Arc<UsageUploader>,
}

impl AgentRuntime {
    pub fn new(
        sessions: Arc<SessionCollector>,
        manager: Arc<UsageCollectionManager>,
        uploader: Arc<UsageUploader>,
    ) -> Self {
        Self {
            sessions,
            manager,
            uploader,
        }
    }

    pub fn spawn(self: Arc<Self>) -> Vec<JoinHandle<()>> {
        let sampler = self.sessions.clone().spawn_sampler();
        let manager = self.manager.clone();
        let collect_handle = async_runtime::spawn(async move {
            if let Err(err) = manager.collect_and_store() {
                log::error!("usage collection failed: {err:?}");
            }
            let mut ticker = interval(Duration::from_secs(COLLECT_INTERVAL_MINUTES * 60));
            loop {
                ticker.tick().await;
                if let Err(err) = manager.collect_and_store() {
                    log::error!("usage collection failed: {err:?}");
                }
            }
        });

        let uploader = self.uploader.clone();
        let upload_handle = async_runtime::spawn(async move {
            if let Err(err) = uploader.upload_pending().await {
                log::error!("usage upload failed: {err:?}");
            }
            loop {
                sleep(Duration::from_secs(UPLOAD_INTERVAL_SECONDS)).await;
                if let Err(err) = uploader.upload_pending().await {
                    log::error!("usage upload failed: {err:?}");
                }
            }
        });

        vec![sampler, collect_handle, upload_handle]
    }
}
