package com.macscreen.client

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Forwards touch events to the Mac server's `/touch` endpoint as JSON
 * HTTP POST requests.  Requests are dispatched on a single-threaded background
 * executor so they never block the UI thread, and individual send failures are
 * silently discarded to keep the interaction fluid.
 *
 * Coordinates [x] and [y] must be **normalised** (0.0 – 1.0) relative to the
 * size of the displayed stream area so the server can correctly map them onto
 * the captured display region regardless of tablet resolution.
 */
class TouchEventSender(private var baseUrl: String) {

    private val mediaType = "application/json; charset=utf-8".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .writeTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    private val executor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "touch-sender").also { it.isDaemon = true }
    }

    /** Update the target server URL without recreating the sender. */
    fun updateBaseUrl(url: String) {
        baseUrl = url
    }

    /**
     * Enqueue a touch event for delivery.
     *
     * @param type  One of `"down"`, `"up"`, `"move"`, `"click"`, `"rightclick"`.
     * @param x     Normalised X coordinate (0.0 = left edge, 1.0 = right edge).
     * @param y     Normalised Y coordinate (0.0 = top edge, 1.0 = bottom edge).
     */
    fun send(type: String, x: Float, y: Float) {
        if (executor.isShutdown) return
        // Sanitise type to ensure only ASCII word characters reach the JSON payload,
        // preventing any injection even though callers are internal.
        val safeType = type.replace(Regex("[^a-zA-Z]"), "")
        executor.execute {
            try {
                val json = """{"type":"$safeType","x":$x,"y":$y}"""
                val body = json.toRequestBody(mediaType)
                val request = Request.Builder()
                    .url("$baseUrl/touch")
                    .post(body)
                    .build()
                client.newCall(request).execute().use { /* consume and close */ }
            } catch (_: IOException) {
                // Silently ignore — a missed touch event is not critical.
            }
        }
    }

    /**
     * Enqueue a scroll event for delivery.
     *
     * @param x       Normalised X coordinate of the scroll position (0.0 – 1.0).
     * @param y       Normalised Y coordinate of the scroll position (0.0 – 1.0).
     * @param amount  Scroll wheel clicks: positive = scroll up, negative = scroll down.
     *                Should be a non-zero integer value.
     */
    fun sendScroll(x: Float, y: Float, amount: Int) {
        if (executor.isShutdown || amount == 0) return
        executor.execute {
            try {
                val json = """{"type":"scroll","x":$x,"y":$y,"amount":$amount}"""
                val body = json.toRequestBody(mediaType)
                val request = Request.Builder()
                    .url("$baseUrl/touch")
                    .post(body)
                    .build()
                client.newCall(request).execute().use { /* consume and close */ }
            } catch (_: IOException) {
                // Silently ignore — a missed scroll event is not critical.
            }
        }
    }

    /** Release resources.  The sender must not be used after this call. */
    fun shutdown() {
        executor.shutdownNow()
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }
}
