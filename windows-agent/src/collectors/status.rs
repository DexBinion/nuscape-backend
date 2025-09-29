use std::ptr;

use windows::Win32::Foundation::WIN32_ERROR;
use windows::Win32::NetworkManagement::IpHelper::{FreeMibTable, GetIfTable2, MIB_IF_TABLE2};
use windows::Win32::NetworkManagement::Ndis::IF_OPER_STATUS;
use windows::Win32::System::Power::{GetSystemPowerStatus, SYSTEM_POWER_STATUS};
use windows::Win32::System::Time::{GetTimeZoneInformation, TIME_ZONE_INFORMATION};
use windows::Win32::UI::Shell::IsUserAnAdmin;

use crate::models::DeviceStatus;

const VPN_TYPES: [u32; 3] = [23, 131, 166];

pub struct DeviceStatusProvider;

impl DeviceStatusProvider {
    pub fn new() -> Self {
        Self
    }

    pub fn build_status(&self) -> DeviceStatus {
        DeviceStatus {
            usage_access: is_running_as_admin().unwrap_or(false),
            accessibility: false,
            overlay: true,
            vpn: detect_vpn().unwrap_or(false),
            battery_pct: battery_percentage().unwrap_or(-1.0),
            time_zone_id: timezone_identifier().unwrap_or_else(|_| "UTC".to_string()),
        }
    }
}

fn is_running_as_admin() -> windows::core::Result<bool> {
    unsafe { Ok(IsUserAnAdmin().as_bool()) }
}

fn detect_vpn() -> windows::core::Result<bool> {
    unsafe {
        let mut table_ptr: *mut MIB_IF_TABLE2 = ptr::null_mut();
        let status = GetIfTable2(&mut table_ptr);
        if status != WIN32_ERROR(0) {
            return Ok(false);
        }
        let table = &*table_ptr;
        let rows = std::slice::from_raw_parts(table.Table.as_ptr(), table.NumEntries as usize);
        let mut vpn = false;
        for row in rows {
            if VPN_TYPES.contains(&row.Type) && row.OperStatus == IF_OPER_STATUS(1) {
                vpn = true;
                break;
            }
        }
        FreeMibTable(table_ptr as _);
        Ok(vpn)
    }
}

fn battery_percentage() -> windows::core::Result<f64> {
    unsafe {
        let mut status = SYSTEM_POWER_STATUS::default();
        GetSystemPowerStatus(&mut status)?;
        if status.BatteryLifePercent == u8::MAX {
            return Ok(-1.0);
        }
        Ok(status.BatteryLifePercent as f64 / 100.0)
    }
}

fn timezone_identifier() -> windows::core::Result<String> {
    unsafe {
        let mut info = TIME_ZONE_INFORMATION::default();
        let state = GetTimeZoneInformation(&mut info);
        if state == u32::MAX {
            return Ok("UTC".to_string());
        }
        let len = info
            .StandardName
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(info.StandardName.len());
        Ok(String::from_utf16_lossy(&info.StandardName[..len])
            .trim()
            .to_string())
    }
}
