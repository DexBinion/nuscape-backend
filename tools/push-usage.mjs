/**
 * tools/push-usage.mjs
 *
 * Simulator that registers / uses a dev token and posts mobile-format usage batches
 * matching Android's UsageStatsManager format (items -> package, totalMs, windowStart, windowEnd).
 *
 * Usage (Windows CMD):
 *   set "REGISTER=1" && set "DEVICE_NAME=sim-android-1" && node tools/push-usage.mjs
 *
 * Usage (PowerShell / Unix):
 *   REGISTER=1 DEVICE_NAME=sim-android-1 node tools/push-usage.mjs
 *
 * Behavior:
 *  - If REGISTER=1 it will POST /api/v1/devices/register and use the returned access_token/device_id.
 *  - Otherwise it will POST /api/v1/dev/token to obtain a dev token.
 *  - It will then POST a mobile-format batch (key: "items") to /api/v1/usage/batch so the tolerant parser
 *    converts mobile items into internal UsageEntry objects and stores them in usage_logs.
 */
const BACKEND = process.env.VITE_API_BASE || "http://127.0.0.1:5001";

function nowIso() {
  return new Date().toISOString();
}

async function fetchJson(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : null;
  } catch (e) {
    throw new Error(`Invalid JSON from ${url}: ${text}`);
  }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} ${res.statusText} from ${url}`);
    err.status = res.status;
    err.body = json;
    throw err;
  }
  return json;
}

async function getTokenAndDevice() {
  if (process.env.REGISTER === "1") {
    const registerUrl = `${BACKEND}/api/v1/devices/register`;
    const deviceName = process.env.DEVICE_NAME || `sim-android-${Date.now()}`;
    const hardware = {
      android_id: process.env.ANDROID_ID || `sim-android-id-${Math.random().toString(36).slice(2,8)}`,
      model: process.env.MODEL || "Pixel",
      brand: process.env.BRAND || "Google"
    };
    const body = {
      platform: "android",
      name: deviceName,
      hardware
    };
    console.log(`Registering device at ${registerUrl} with name=${deviceName}`);
    const json = await fetchJson(registerUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body)
    });
    console.log("Register response:", json);
    // RegisterResponse includes access_token and device_id
    return { token: json.access_token, device_id: json.device_id };
  } else {
    const url = `${BACKEND}/api/v1/dev/token`;
    console.log(`Requesting dev token from ${url}`);
    const json = await fetchJson(url, {
      method: "POST",
      headers: { "Accept": "application/json" },
    });
    console.log("Dev token response:", json);
    return { token: json.token, device_id: json.device_id };
  }
}

async function pushUsage(token, tokenDeviceId = null) {
  const deviceIdEnv = process.env.DEVICE_ID || null;
  const deviceId = deviceIdEnv || tokenDeviceId || undefined;

  const now = new Date();
  const start = new Date(now.getTime() - 60 * 1000); // 60s ago to be safe
  const item = {
    package: process.env.PACKAGE || "com.example.usageapp",
    totalMs: 60000,
    windowStart: start.toISOString(),
    windowEnd: now.toISOString()
  };

  // Build mobile-format batch (key "items") expected by the tolerant endpoint
  const payload = {
    device_id: deviceId,
    client_version: "sim-android-usage",
    items: [item]
  };

  if (!payload.device_id) {
    delete payload.device_id;
  }

  const url = `${BACKEND}/api/v1/usage/batch`;
  console.log(`Posting mobile-format usage batch to ${url}`);
  console.log("Payload:", JSON.stringify(payload, null, 2));

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });

  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch(e) {
    body = text;
  }

  console.log(`Response ${res.status} ${res.statusText}:`, body);
  return { status: res.status, body };
}

(async () => {
  try {
    const info = await getTokenAndDevice();
    const token = info.token;
    const deviceId = info.device_id;
    await pushUsage(token, deviceId);
    console.log("Done.");
  } catch (err) {
    console.error("Error:", err.message || err);
    if (err.body) {
      console.error("Error body:", err.body);
    }
    process.exitCode = 1;
  }
})();