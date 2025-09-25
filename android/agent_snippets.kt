/*
Kotlin agent snippets: UsageStats delta collection, sessionization, Retrofit interface, WorkManager worker,
and server guardrails (SQL + FastAPI validation) included at bottom as text snippets.

Place the Kotlin code into your Android app module (adjust package names / imports as needed).
This file is intended as drop-in reference pieces — integrate into your existing Retrofit / WorkManager setup.
*/

package com.example.nuscape_mobile.agent

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.annotation.RequiresApi
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import java.time.Duration
import java.time.Instant
import java.util.Collections
import kotlin.math.max
import kotlin.math.min
import com.google.gson.annotations.SerializedName

// ---------------------------
// CursorStore - persist last cursor timestamp
// ---------------------------
object CursorStore {
    private const val PREF = "collector_prefs"
    private const val KEY  = "last_cursor_ms"

    fun get(ctx: Context): Long =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).getLong(KEY, 0L)

    fun set(ctx: Context, v: Long) =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit().putLong(KEY, v).apply()
}

// ---------------------------
// ScreenStateTracker - keep screen-on windows
// ---------------------------
class ScreenStateTracker(private val ctx: Context) {
    private val windows = Collections.synchronizedList(mutableListOf<LongRange>())
    @Volatile private var currentStart: Long? = null

    fun receiver(): BroadcastReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, i: Intent?) {
            when (i?.action) {
                Intent.ACTION_SCREEN_ON  -> currentStart = System.currentTimeMillis()
                Intent.ACTION_SCREEN_OFF -> {
                    currentStart?.let {
                        windows += LongRange(it, System.currentTimeMillis())
                    }
                    currentStart = null
                }
            }
        }
    }

    // Return screen windows overlapping the requested interval
    fun windowsBetween(start: Long, end: Long): List<LongRange> =
        synchronized(windows) { windows.filter { it.first < end && it.last > start } }
}

// ---------------------------
// Session types & helpers
// ---------------------------
data class Session(val pkg: String, val start: Long, val end: Long)

@RequiresApi(Build.VERSION_CODES.LOLLIPOP)
fun sessionsFromEvents(events: UsageEvents): List<Session> {
    val fg = mutableMapOf<String, Long>()
    val out = mutableListOf<Session>()
    val e = UsageEvents.Event()
    while (events.hasNextEvent()) {
        events.getNextEvent(e)
        when (e.eventType) {
            UsageEvents.Event.MOVE_TO_FOREGROUND -> fg[e.packageName] = e.timeStamp
            UsageEvents.Event.MOVE_TO_BACKGROUND -> {
                val s = fg.remove(e.packageName) ?: continue
                if (e.timeStamp > s) out += Session(e.packageName, s, e.timeStamp)
            }
        }
    }
    return out
}

fun mergeGaps(input: List<Session>, gapMs: Long = 30_000): List<Session> =
    input.groupBy { it.pkg }.values.flatMap { perPkg ->
        val sorted = perPkg.sortedBy { it.start }
        val merged = mutableListOf<Session>()
        for (s in sorted) {
            if (merged.isEmpty()) merged += s
            else {
                val last = merged.last()
                if (s.start - last.end <= gapMs) {
                    merged[merged.lastIndex] = last.copy(end = max(last.end, s.end))
                } else merged += s
            }
        }
        merged
    }

fun clampToWindows(sess: Session, win: List<LongRange>): Session? {
    var total = 0L
    var start = Long.MAX_VALUE
    var end = 0L
    for (w in win) {
        val s = max(sess.start, w.first)
        val e = min(sess.end,   w.last)
        if (e > s) {
            total += (e - s)
            start = min(start, s)
            end = max(end, e)
        }
    }
    return if (total > 0L) Session(sess.pkg, start, end) else null
}

val NOISE = setOf(
    "com.android.systemui", "com.google.android.inputmethod.latin",
    "com.sec.android.app.launcher"
)

private const val TAG = "UsageUploadWorker"
private const val MAX_SESSION_MS = 8 * 60 * 60 * 1000L
private const val CLOCK_SKEW_GRACE_SECONDS = 5 * 60L

// ---------------------------
// Mobile payload types for server (matches backend expected mobile format)
// ---------------------------
data class UsageItemDTO(
    @SerializedName("package") val pkg: String,
    @SerializedName("windowStart") val windowStart: String,
    @SerializedName("windowEnd") val windowEnd: String,
    @SerializedName("totalMs") val totalMs: Long,
    @SerializedName("fg") val fg: Boolean? = null
)

data class UsageBatchDTO(
    @SerializedName("items") val items: List<UsageItemDTO>
)

data class BatchErrorDTO(
    @SerializedName("index") val index: Int,
    @SerializedName("error") val error: String,
    @SerializedName("code") val code: String?
)

data class BatchUploadResponse(
    @SerializedName("accepted") val accepted: Int,
    @SerializedName("duplicates") val duplicates: Int = 0,
    @SerializedName("rejected") val rejected: Int = 0,
    @SerializedName("errors") val errors: List<BatchErrorDTO> = emptyList()
)

private fun UsageItemDTO.isValid(now: Instant, index: Int): Boolean {
    if (totalMs <= 0) {
        Log.w(TAG, "drop[$index]: non-positive duration $totalMs for $pkg")
        return false
    }

    val start = runCatching { Instant.parse(windowStart) }.getOrElse {
        Log.w(TAG, "drop[$index]: invalid start $windowStart for $pkg")
        return false
    }
    val end = runCatching { Instant.parse(windowEnd) }.getOrElse {
        Log.w(TAG, "drop[$index]: invalid end $windowEnd for $pkg")
        return false
    }

    if (!windowStart.endsWith("Z") || !windowEnd.endsWith("Z")) {
        Log.w(TAG, "drop[$index]: timestamps must be UTC Z for $pkg")
        return false
    }

    if (end <= start) {
        Log.w(TAG, "drop[$index]: end <= start for $pkg ($windowStart -> $windowEnd)")
        return false
    }

    val durationMs = Duration.between(start, end).toMillis()
    if (durationMs > MAX_SESSION_MS) {
        Log.w(TAG, "drop[$index]: duration ${durationMs}ms exceeds cap for $pkg")
        return false
    }

    val maxAllowedEnd = now.plusSeconds(CLOCK_SKEW_GRACE_SECONDS)
    if (end.isAfter(maxAllowedEnd)) {
        Log.w(TAG, "drop[$index]: window in future for $pkg ($windowEnd)")
        return false
    }

    return true
}

// ---------------------------
// Retrofit interface (assumes Moshi/Gson converter already configured)
// Adjust baseUrl / converters to your project's setup.
// ---------------------------
interface BackendApi {
    @POST("/api/v1/usage/batch")
    suspend fun postUsageBatch(
        @Header("Authorization") bearer: String,
        @Body batch: UsageBatchDTO
    ): Response<BatchUploadResponse>
}

// ---------------------------
// Simple token provider placeholder - persist tokens securely in EncryptedSharedPreferences
// ---------------------------
object TokenStore {
    private const val PREF = "token_prefs"
    private const val KEY_TOKEN = "access_token"
    fun token(ctx: Context): String? =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).getString(KEY_TOKEN, null)
    fun setToken(ctx: Context, t: String) =
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit().putString(KEY_TOKEN, t).apply()
}

// ---------------------------
// WorkManager worker to collect deltas and upload
// ---------------------------
class UsageUploadWorker(
    appContext: Context,
    workerParams: WorkerParameters,
    private val retrofit: Retrofit, // Injected when creating the worker (Factory)
    private val screenTracker: ScreenStateTracker
) : CoroutineWorker(appContext, workerParams) {

    private val api by lazy { retrofit.create(BackendApi::class.java) }
    private val ctx = appContext

    @RequiresApi(Build.VERSION_CODES.LOLLIPOP)
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
            val end = System.currentTimeMillis()
            val lastCursor = CursorStore.get(ctx)
            val lookbackCap = 60 * 60 * 1000L // 1 hour safety cap
            val start = max(lastCursor, end - lookbackCap)

            // Prefer events-based sessionization when available
            val events = usm.queryEvents(start, end)
            val raw = sessionsFromEvents(events)
            val merged = mergeGaps(raw, 30_000)
                .filter { it.pkg !in NOISE }

            val clamped = merged.mapNotNull { clampToWindows(it, screenTracker.windowsBetween(start, end)) }

            val nowInstant = Instant.ofEpochMilli(end)
            val items = clamped.map {
                val startIso = Instant.ofEpochMilli(it.start).toString()
                val endIso = Instant.ofEpochMilli(it.end).toString()
                val totalMs = (it.end - it.start).coerceAtLeast(0L)
                UsageItemDTO(
                    pkg = it.pkg,
                    windowStart = startIso,
                    windowEnd = endIso,
                    totalMs = totalMs,
                    fg = true
                )
            }

            val filtered = items.filter { it.totalMs >= 5_000 }
            val validated = filtered.mapIndexedNotNull { index, item ->
                if (item.isValid(nowInstant, index)) item else null
            }

            if (validated.isNotEmpty()) {
                val token = TokenStore.token(ctx) ?: return@withContext Result.retry()
                val bearer = "Bearer $token"
                val batch = UsageBatchDTO(validated)
                val resp = api.postUsageBatch(bearer, batch)

                if (resp.isSuccessful) {
                    val body = resp.body()
                    body?.errors?.forEach { err ->
                        Log.w(TAG, "server rejected item ${err.index}: ${err.code ?: "unknown"} -> ${err.error}")
                    }

                    if ((body?.accepted ?: 0) > 0) {
                        CursorStore.set(ctx, end)
                    }
                    return@withContext Result.success()
                }

                when (resp.code()) {
                    401 -> {
                        Log.w(TAG, "auth failure 401; trigger refresh before retry")
                        return@withContext Result.retry()
                    }
                    in 500..599 -> {
                        Log.w(TAG, "server ${resp.code()} - retry later")
                        return@withContext Result.retry()
                    }
                    else -> {
                        Log.w(
                            TAG,
                            "permanent failure ${resp.code()} body=${resp.errorBody()?.string()}"
                        )
                        return@withContext Result.retry()
                    }
                }
            } else {
                if (items.isNotEmpty()) {
                    Log.w(TAG, "all ${items.size} items filtered out locally; advancing cursor")
                }
                CursorStore.set(ctx, end)
                return@withContext Result.success()
            }
        } catch (e: Exception) {
            e.printStackTrace()
            return@withContext Result.retry()
        }
    }
}

fun enqueueUsageUpload(ctx: Context) {
    val constraints = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    val work = OneTimeWorkRequestBuilder<UsageUploadWorker>()
        .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
        .setConstraints(constraints)
        .build()

    WorkManager.getInstance(ctx).enqueueUniqueWork(
        "usage-upload",
        ExistingWorkPolicy.APPEND_OR_REPLACE,
        work
    )
}

// ---------------------------
// Notes on integration:
// - Register BroadcastReceiver for screen on/off in your ForegroundService and pass ScreenStateTracker into the worker
// - Create a WorkerFactory to inject Retrofit and ScreenStateTracker into UsageUploadWorker
// - Use WorkManager periodic work (e.g., 15 minutes) and also trigger one-off uploads when app goes to background or on network available
// - Persist tokens securely using EncryptedSharedPreferences (not plain SharedPreferences in production)
// - Add proper telemetry/logging of items[] payloads (logcat) for quick verification
// ---------------------------

// ---------------------------
// Server guardrails (SQL + FastAPI validation)
// Place the SQL in your migration (alembic) and add the FastAPI validation patch to backend/main.py's create_usage_batch_tolerant()
// ---------------------------

/*
Server-side pairing:
 - backend/main.py now enforces per-item validation with ±5 minute skew grace and 8 hour max windows.
 - /api/v1/usage/batch returns {accepted, duplicates, rejected, errors[]} so the Android agent can log granular feedback.
 - /api/v1/usage/validate accepts the same payload for dry-run checks.
 - backend/crud.create_usage_logs() performs ON CONFLICT upserts (and falls back cleanly on SQLite for tests).

Keep the agent logging enabled until you confirm accepted>0 and rejected==0 in the field; the server log will mirror any rejections.
*/
