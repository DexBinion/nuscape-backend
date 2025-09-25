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
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
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

// ---------------------------
// Retrofit interface (assumes Moshi/Gson converter already configured)
// Adjust baseUrl / converters to your project's setup.
// ---------------------------
interface BackendApi {
    @POST("/api/v1/usage/batch")
    suspend fun postUsageBatch(
        @Header("Authorization") bearer: String,
        @Body batch: UsageBatchDTO
    ): Response<Any>
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

            val items = clamped.map {
                MobileItem(
                    `package` = it.pkg,
                    totalMs = (it.end - it.start),
                    windowStart = Instant.ofEpochMilli(it.start).toString(),
                    windowEnd   = Instant.ofEpochMilli(it.end).toString()
                )
            }.filter { it.totalMs >= 5_000 } // drop <5s blips

            if (items.isNotEmpty()) {
                val token = TokenStore.token(ctx) ?: return@withContext Result.retry()
                val bearer = "Bearer $token"
                val batch = UsageBatch(items)
                val resp = api.postUsageBatch(bearer, batch)
                if (resp.isSuccessful) {
                    CursorStore.set(ctx, end) // advance only on success
                    return@withContext Result.success()
                } else {
                    // Server may reject unbounded totals — handle 400/422/429 accordingly
                    return@withContext Result.retry()
                }
            } else {
                // Nothing to send; still advance cursor to avoid repeated empty scans
                CursorStore.set(ctx, end)
                return@withContext Result.success()
            }
        } catch (e: Exception) {
            e.printStackTrace()
            return@withContext Result.retry()
        }
    }
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
SQL migration snippet (alembic - create index to prevent duplicate session double-counting):

-- alembic revision: add unique index to usage_logs for dedupe
CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_session
ON usage_logs (device_id, app_package, start, "end");

Reason: prevents accidental inserts of identical session rows. If you want strict dedupe,
consider ON CONFLICT DO NOTHING semantics in an INSERT ... ON CONFLICT clause at the ORM level.
*/

/*
FastAPI validation patch (Python) - validate incoming mobile-format items in create_usage_batch_tolerant()

Insert near the top of the handler (after parsing body_data):
    raw_items = body_data.get('items') or body_data.get('entries') or body_data.get('sessions') or []
    # Guardrail: reject "totals only" style payloads with no bounded windows
    for i, item in enumerate(raw_items):
        # require windowStart and windowEnd or server-bounded window keys
        if not item.get('windowStart') or not item.get('windowEnd') or 'totalMs' not in item:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid item at index {i}: require windowStart, windowEnd and totalMs"
            )
        # Cap item length to 8 hours (safety)
        try:
            from datetime import datetime
            s = datetime.fromisoformat(item['windowStart'].replace('Z', '+00:00'))
            e = datetime.fromisoformat(item['windowEnd'].replace('Z', '+00:00'))
            if (e - s).total_seconds() > 8 * 3600:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Item at index {i} exceeds maximum allowed session length"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid ISO timestamps in item at index {i}"
            )

Later, when inserting usage rows via SQLAlchemy you can catch unique constraint violations
and ignore duplicates (so agent retries are idempotent):

    try:
        accepted_count = await crud.create_usage_logs(db, device, usage_entries)
    except sqlalchemy.exc.IntegrityError as ie:
        # detect duplicate key violation (unique index) and treat as accepted=0 or partial
        db.rollback()
        logging.warning("Duplicate session insert detected; ignoring duplicates")
        accepted_count = 0

This combination ensures:
- Clients must send bounded deltas (windowStart/windowEnd).
- Server prevents double counting via unique index and handles retry/idempotency gracefully.
*/

/*
If you'd like, I can:
 - Create an Alembic revision file containing the CREATE INDEX statement (and a down() to drop it), or
 - Open and patch the Python create_usage_batch_tolerant handler in-place to add the validation guardrail.

Tell me which server-side change you'd like me to apply now.
*/