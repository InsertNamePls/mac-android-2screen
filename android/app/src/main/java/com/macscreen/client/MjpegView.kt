package com.macscreen.client

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.util.AttributeSet
import android.view.SurfaceHolder
import android.view.SurfaceView

/**
 * A [SurfaceView] that connects to an MJPEG stream and renders each decoded
 * frame as fast as the decoder delivers them.  The surface is drawn on a
 * dedicated background thread to avoid blocking the main thread.
 *
 * Call [setStreamUrl] to configure the URL before the surface is created, or
 * at any time to reconnect to a new address.
 */
class MjpegView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : SurfaceView(context, attrs), SurfaceHolder.Callback {

    private var decoder: MjpegDecoder? = null
    private var pendingUrl: String? = null

    /** Callbacks invoked on the decoder thread; post to the main thread before using in UI. */
    var onConnected: (() -> Unit)? = null
    var onError: ((String) -> Unit)? = null

    private val destRect = Rect()
    private val clearPaint = Paint().apply { color = Color.BLACK }

    init {
        holder.addCallback(this)
    }

    /**
     * Set the MJPEG stream URL.  If the surface is already ready the decoder
     * is (re)started immediately; otherwise the URL is stored and applied when
     * [surfaceCreated] fires.
     */
    fun setStreamUrl(url: String) {
        pendingUrl = url
        if (holder.surface.isValid) {
            restartDecoder(url)
        }
    }

    // ------------------------------------------------------------------
    // SurfaceHolder.Callback
    // ------------------------------------------------------------------

    override fun surfaceCreated(holder: SurfaceHolder) {
        pendingUrl?.let { restartDecoder(it) }
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {
        destRect.set(0, 0, width, height)
    }

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        decoder?.stop()
        decoder = null
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    private fun restartDecoder(url: String) {
        decoder?.stop()
        decoder = MjpegDecoder(
            streamUrl = url,
            onFrame = ::renderFrame,
            onConnected = { onConnected?.invoke() },
            onError = { msg -> onError?.invoke(msg) },
        ).also { it.start() }
    }

    private fun renderFrame(bitmap: Bitmap) {
        val canvas: Canvas = holder.lockCanvas() ?: run {
            bitmap.recycle()
            return
        }
        try {
            canvas.drawRect(destRect, clearPaint)
            canvas.drawBitmap(bitmap, null, destRect, null)
        } finally {
            holder.unlockCanvasAndPost(canvas)
            bitmap.recycle()
        }
    }
}
