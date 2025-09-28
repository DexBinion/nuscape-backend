use std::collections::HashMap;
use std::ptr;
use std::sync::Arc;

use anyhow::{anyhow, Result};
use chrono::{DateTime, Utc};
use windows::Win32::Foundation::WIN32_ERROR;
use windows::Win32::NetworkManagement::IpHelper::{FreeMibTable, GetIfTable2, MIB_IF_ROW2, MIB_IF_TABLE2};
use windows::Win32::NetworkManagement::Ndis::IF_OPER_STATUS;

use crate::models::{NetworkCounters, NetworkDelta};
use crate::storage::NetworkCounterStore;

const WIFI_TYPE: u32 = 71;
const CELLULAR_TYPES: [u32; 2] = [243, 244];

pub struct NetworkUsageCollector {
    store: Arc<NetworkCounterStore>,
}

impl NetworkUsageCollector {
    pub fn new(store: Arc<NetworkCounterStore>) -> Self {
        Self { store }
    }

    pub fn collect(&self) -> Result<Vec<NetworkDelta>> {
        let now = Utc::now();
        let totals = unsafe { snapshot_interfaces(now)? };
        let previous = self.store.load();
        let mut outputs = Vec::new();

        for (iface, total) in totals.iter() {
            let last = previous.get(iface);
            let delta_wifi = last
                .map(|c| total.wifi_total.saturating_sub(c.wifi_total))
                .unwrap_or(total.wifi_total);
            let delta_cell = last
                .map(|c| total.cell_total.saturating_sub(c.cell_total))
                .unwrap_or(total.cell_total);
            if delta_wifi == 0 && delta_cell == 0 {
                continue;
            }
            outputs.push(NetworkDelta {
                package: format!("iface::{iface}"),
                sampled_at: now,
                wifi_bytes: delta_wifi,
                cellular_bytes: delta_cell,
            });
        }

        self.store.save(totals)?;
        Ok(outputs)
    }
}

unsafe fn snapshot_interfaces(now: DateTime<Utc>) -> Result<HashMap<String, NetworkCounters>> {
    let mut table_ptr: *mut MIB_IF_TABLE2 = ptr::null_mut();
    let status = GetIfTable2(&mut table_ptr);
    if status != WIN32_ERROR(0) {
        return Err(anyhow!("GetIfTable2 failed: {:?}", status));
    }
    let table = &*table_ptr;
    let rows = std::slice::from_raw_parts(table.Table.as_ptr(), table.NumEntries as usize);
    let mut map = HashMap::new();
    for row in rows {
        if row.OperStatus != IF_OPER_STATUS(1) {
            continue;
        }
        let desc = wide_to_string(&row.Description);
        if desc.is_empty() {
            continue;
        }
        let (wifi, cell) = categorize_bytes(row);
        map.insert(
            desc,
            NetworkCounters {
                wifi_total: wifi,
                cell_total: cell,
                sampled_at: now,
            },
        );
    }
    FreeMibTable(table_ptr as _);
    Ok(map)
}

fn wide_to_string(buf: &[u16]) -> String {
    let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..len]).trim().to_string()
}

fn categorize_bytes(row: &MIB_IF_ROW2) -> (u64, u64) {
    let total = row.InOctets + row.OutOctets;
    if row.Type == WIFI_TYPE {
        (total, 0)
    } else if CELLULAR_TYPES.contains(&row.Type) {
        (0, total)
    } else {
        (total, 0)
    }
}
