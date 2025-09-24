/*
Quick Kotlin standalone test snippet to POST a single valid mobile-format usage item
to /api/v1/usage/debug (or /api/v1/usage/batch). Drop into an Android module (debug-only),
or run as a small function from your debug UI.

This uses OkHttp directly for simplicity and prints server response.
Adjust BASE_URL and TOKEN retrieval to suit your environment.
*/

package com.example.nuscape_mobile.debug

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.logging.HttpLoggingInterceptor
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

fun isoNowMinus(minutes: Long): String {
    return Instant.now().minusSeconds(minutes * 60)
        .atOffset(ZoneOffset.UTC)
        .format(DateTimeFormatter.ISO_INSTANT)
}

fun buildTestPayload(): String {
    val start = isoNowMinus(6) // 6 minutes ago
    val end = Instant.now().atOffset(ZoneOffset.UTC).format(DateTimeFormatter.ISO_INSTANT)
    // Ensure fields and casing match server expectations exactly
    return """
    {
      "items": [
        {
          "package": "com.google.android.youtube",
          "totalMs": 360000,
          "windowStart": "$start",
          "windowEnd": "$end"
        }
      ]
    }
    """.trimIndent()
}

fun postTestUsage(baseUrl: String, bearerToken: String) {
    val log = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BODY }
    val client = OkHttpClient.Builder()
        .addInterceptor(log)
        .build()

    val json = buildTestPayload()
    val mediaType = "application/json; charset=utf-8".toMediaType()
    val body = RequestBody.create(mediaType, json)

    val req = Request.Builder()
        .url("$baseUrl/api/v1/usage/debug") // debug endpoint; swap to /api/v1/usage/batch for real ingestion
        .addHeader("Authorization", "Bearer $bearerToken")
        .addHeader("Content-Type", "application/json")
        .post(body)
        .build()

    client.newCall(req).execute().use { resp ->
        val code = resp.code
        val text = resp.body?.string()
        println("Response code: $code")
        println("Response body: $text")
    }
}

// Example usage (replace values and call from an appropriate debug context)
fun main() {
    val BASE_URL = "https://9614bb61-b6e4-4778-bde5-79a776306cc3-00-22nqhbvlkbzbc.janeway.replit.dev"
    val TOKEN = "<PASTE_ACCESS_TOKEN_HERE>"
    postTestUsage(BASE_URL, TOKEN)
}