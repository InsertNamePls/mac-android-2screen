package com.macscreen.client

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.TimeUnit

/**
 * Connects to the MJPEG stream exposed by the Mac server and delivers decoded
 * [Bitmap] frames via [onFrame].  Parsing relies on the standard JPEG SOI
 * (0xFF 0xD8) and EOI (0xFF 0xD9) markers so it is independent of the
 * multipart boundary string used by the server.
 */
class MjpegDecoder(
    private val streamUrl: String,
    private val onFrame: (Bitmap) -> Unit,
    private val onConnected: () -> Unit,
    private val onError: (String) -> Unit,
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS) // no timeout — it's a live stream
        .build()

    @Volatile private var running = false
    private var activeCall: Call? = null
    private var thread: Thread? = null

    private companion object {
        /** Initial capacity for the per-frame JPEG byte buffer (128 KB). */
        const val INITIAL_BUFFER_SIZE_BYTES = 128 * 1024
        /** Size of the read buffer used for stream I/O. */
        const val IO_BUFFER_SIZE_BYTES = 16 * 1024
    }

    fun start() {
        running = true
        thread = Thread(::streamLoop, "mjpeg-decoder").also { it.start() }
    }

    fun stop() {
        running = false
        activeCall?.cancel()
        thread?.interrupt()
        thread = null
    }

    private fun streamLoop() {
        val request = Request.Builder().url(streamUrl).build()
        val call = client.newCall(request)
        activeCall = call
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    onError("HTTP ${response.code}")
                    return
                }
                onConnected()
                val body = response.body ?: run { onError("Empty response"); return }
                // Wrap in a BufferedInputStream to avoid per-byte syscalls.
                BufferedInputStream(body.byteStream(), IO_BUFFER_SIZE_BYTES)
                    .use { parseJpegStream(it) }
            }
        } catch (e: IOException) {
            if (running) onError(e.message ?: "Stream error")
        }
    }

    private fun parseJpegStream(stream: InputStream) {
        // Find JPEG start (0xFF 0xD8) and end (0xFF 0xD9) markers.  Each
        // complete JPEG image between markers is decoded into a [Bitmap] and
        // delivered to [onFrame].  This approach is more robust than multipart
        // boundary parsing because it works regardless of the exact boundary
        // string and header formatting used by the server.
        val jpegBuf = ByteArrayOutputStream(INITIAL_BUFFER_SIZE_BYTES)
        var prev = -1
        var inJpeg = false

        while (running) {
            val b = stream.read()
            if (b == -1) break  // server closed connection

            if (!inJpeg) {
                if (prev == 0xFF && b == 0xD8) {
                    // JPEG Start Of Image
                    inJpeg = true
                    jpegBuf.reset()
                    jpegBuf.write(0xFF)
                    jpegBuf.write(0xD8)
                }
            } else {
                jpegBuf.write(b)
                if (prev == 0xFF && b == 0xD9) {
                    // JPEG End Of Image — decode and deliver
                    val bytes = jpegBuf.toByteArray()
                    val bm = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    if (bm != null) onFrame(bm)
                    inJpeg = false
                    jpegBuf.reset()
                }
            }
            prev = b
        }
    }
}
