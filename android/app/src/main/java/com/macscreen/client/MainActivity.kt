package com.macscreen.client

import android.app.AlertDialog
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import androidx.appcompat.app.AppCompatActivity
import com.macscreen.client.databinding.ActivityMainBinding

/**
 * Main (and only) activity.  Occupies the full screen in landscape to maximise
 * the usable display area for the streamed Mac screen content.
 *
 * Connection modes
 * ────────────────
 * • **USB (ADB)** — run `adb reverse tcp:8080 tcp:8080` on the Mac, then the
 *   tablet connects to `localhost:8080`.  No LAN required.
 * • **Wi-Fi** — enter the Mac's LAN IP address; both devices must be on the
 *   same network.
 *
 * Touch gestures
 * ──────────────
 * • **Single tap / drag** — forwarded as left mouse button press/move/release.
 * • **Long press** — sends a right-click at the pressed position.
 * • **Two-finger vertical drag** — forwarded as scroll-wheel events.
 *
 * Touch events are forwarded as normalised coordinates so the Mac server can
 * translate them to the correct position within the captured display region.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var touchSender: TouchEventSender? = null

    private val prefs by lazy { getSharedPreferences("macscreen_prefs", MODE_PRIVATE) }

    // ------------------------------------------------------------------
    // Auto-reconnect state
    // ------------------------------------------------------------------

    private val reconnectHandler = Handler(Looper.getMainLooper())
    /** Delay before the next automatic reconnect attempt; doubles on each failure. */
    private var reconnectDelayMs = 1_000L

    // ------------------------------------------------------------------
    // Touch-gesture state
    // ------------------------------------------------------------------

    /** Set to true once a long-press has been detected; suppresses the following UP. */
    private var longPressConsumed = false
    /** True while a two-finger scroll gesture is in progress. */
    private var isScrolling = false
    /** Y-coordinate of the primary pointer at the last MOVE sample (for scroll delta). */
    private var prevScrollY = 0f
    /** Fractional scroll accumulator; keeps sub-click movements and applies them later. */
    private var scrollAccumulator = 0f

    companion object {
        /** Tablet pixels of two-finger vertical movement that equal one Mac scroll-wheel click. */
        private const val PIXELS_PER_SCROLL_CLICK = 60f
    }

    /** Detects long-press gestures and maps them to right-click events. */
    private val gestureDetector by lazy {
        GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onLongPress(e: MotionEvent) {
                longPressConsumed = true
                val x = (e.x / binding.mjpegView.width).coerceIn(0f, 1f)
                val y = (e.y / binding.mjpegView.height).coerceIn(0f, 1f)
                // Cancel the initial mouse-down that was already sent, then right-click.
                touchSender?.send("up", x, y)
                touchSender?.send("rightclick", x, y)
            }
        })
    }

    // ------------------------------------------------------------------
    // System UI
    // ------------------------------------------------------------------

    /** Hide status bar and navigation bar; use the modern API on API 30+. */
    private fun hideSystemUI() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                )
        }
    }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Keep the screen on and go full-screen so the tablet acts like a monitor.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemUI()

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.settingsButton.setOnClickListener { showSettingsDialog() }
        binding.retryButton.setOnClickListener {
            reconnectDelayMs = 1_000L  // manual retry resets the backoff
            connect()
        }

        connect()
    }

    override fun onDestroy() {
        super.onDestroy()
        reconnectHandler.removeCallbacksAndMessages(null)
        touchSender?.shutdown()
    }

    // ------------------------------------------------------------------
    // Touch forwarding
    // ------------------------------------------------------------------

    override fun onTouchEvent(event: MotionEvent): Boolean {
        gestureDetector.onTouchEvent(event)
        val sender = touchSender ?: return super.onTouchEvent(event)

        // Reset gesture state at the start of every new touch sequence.
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            longPressConsumed = false
            isScrolling = false
            scrollAccumulator = 0f
        }

        // Cancel any active gesture on system cancellation.
        if (event.actionMasked == MotionEvent.ACTION_CANCEL) {
            longPressConsumed = false
            isScrolling = false
            scrollAccumulator = 0f
            return true
        }

        // ── Two-finger scroll ──────────────────────────────────────────
        if (event.pointerCount >= 2) {
            when (event.actionMasked) {
                MotionEvent.ACTION_POINTER_DOWN -> {
                    // A second finger joined — cancel the pending single-touch press
                    // so the Mac doesn't see a dangling mouse-down.
                    if (!longPressConsumed) {
                        val cx = (event.getX(0) / binding.mjpegView.width).coerceIn(0f, 1f)
                        val cy = (event.getY(0) / binding.mjpegView.height).coerceIn(0f, 1f)
                        sender.send("up", cx, cy)
                        longPressConsumed = true  // suppress further single-touch events
                    }
                    isScrolling = true
                    prevScrollY = event.getY(0)
                    scrollAccumulator = 0f
                }
                MotionEvent.ACTION_MOVE -> if (isScrolling) {
                    val dy = prevScrollY - event.getY(0)
                    prevScrollY = event.getY(0)
                    // Accumulate sub-click movements; only send whole-click amounts.
                    scrollAccumulator += dy / PIXELS_PER_SCROLL_CLICK
                    val clicks = scrollAccumulator.toInt()
                    if (clicks != 0) {
                        scrollAccumulator -= clicks.toFloat()
                        val x = (event.getX(0) / binding.mjpegView.width).coerceIn(0f, 1f)
                        val y = (event.getY(0) / binding.mjpegView.height).coerceIn(0f, 1f)
                        sender.sendScroll(x, y, clicks)
                    }
                }
            }
            return true
        }

        // ── Suppress single-touch events after long-press or scroll ───
        if (longPressConsumed || isScrolling) {
            if (event.actionMasked == MotionEvent.ACTION_UP) {
                isScrolling = false
            }
            return true
        }

        // ── Single-finger forwarding ───────────────────────────────────
        // Normalise to 0.0–1.0 relative to the stream view dimensions.
        val x = (event.x / binding.mjpegView.width).coerceIn(0f, 1f)
        val y = (event.y / binding.mjpegView.height).coerceIn(0f, 1f)

        val type = when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> "down"
            MotionEvent.ACTION_UP   -> "up"
            MotionEvent.ACTION_MOVE -> "move"
            else -> return super.onTouchEvent(event)
        }
        sender.send(type, x, y)
        return true
    }

    // ------------------------------------------------------------------
    // Connection
    // ------------------------------------------------------------------

    private fun buildBaseUrl(): String {
        val mode = prefs.getString("mode", "usb")
        val host = if (mode == "wifi") {
            prefs.getString("host", "192.168.1.1") ?: "192.168.1.1"
        } else {
            "localhost"
        }
        val port = prefs.getInt("port", 8080)
        return "http://$host:$port"
    }

    private fun connect() {
        reconnectHandler.removeCallbacksAndMessages(null)

        val baseUrl = buildBaseUrl()
        setStatus("Connecting to $baseUrl …")
        binding.retryButton.visibility = View.GONE

        touchSender?.shutdown()
        touchSender = TouchEventSender(baseUrl)

        binding.mjpegView.onConnected = {
            runOnUiThread {
                reconnectDelayMs = 1_000L  // reset backoff on a successful connection
                setStatus("Connected")
            }
        }
        binding.mjpegView.onError = { msg ->
            runOnUiThread {
                setStatus("Error: $msg")
                binding.retryButton.visibility = View.VISIBLE
                scheduleReconnect()
            }
        }
        binding.mjpegView.setStreamUrl("$baseUrl/stream")
    }

    /**
     * Schedule an automatic reconnect attempt after [reconnectDelayMs] milliseconds,
     * then double the delay (capped at 30 s) for the next potential failure.
     */
    private fun scheduleReconnect() {
        reconnectHandler.postDelayed({
            if (!isFinishing && !isDestroyed) connect()
        }, reconnectDelayMs)
        reconnectDelayMs = (reconnectDelayMs * 2).coerceAtMost(30_000L)
    }

    private fun setStatus(msg: String) {
        binding.statusText.text = msg
    }

    // ------------------------------------------------------------------
    // Settings dialog
    // ------------------------------------------------------------------

    private fun showSettingsDialog() {
        val currentMode = prefs.getString("mode", "usb") ?: "usb"
        val currentHost = prefs.getString("host", "192.168.1.1") ?: "192.168.1.1"
        val currentPort = prefs.getInt("port", 8080)

        // Build a simple vertical layout programmatically to avoid needing a
        // second XML layout file for the dialog.
        val padding = (16 * resources.displayMetrics.density).toInt()
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding, padding, padding)
        }

        val modeGroup = RadioGroup(this).apply {
            orientation = RadioGroup.HORIZONTAL
        }
        val radioUsb = RadioButton(this).apply {
            text = "USB (ADB)"
            id = View.generateViewId()
        }
        val radioWifi = RadioButton(this).apply {
            text = "Wi-Fi"
            id = View.generateViewId()
        }
        modeGroup.addView(radioUsb)
        modeGroup.addView(radioWifi)
        if (currentMode == "wifi") modeGroup.check(radioWifi.id) else modeGroup.check(radioUsb.id)
        layout.addView(modeGroup)

        val hostField = EditText(this).apply {
            hint = "Mac IP address (Wi-Fi only)"
            setText(currentHost)
            inputType = android.text.InputType.TYPE_CLASS_TEXT
        }
        layout.addView(hostField)

        val portField = EditText(this).apply {
            hint = "Port"
            setText(currentPort.toString())
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
        }
        layout.addView(portField)

        AlertDialog.Builder(this)
            .setTitle("Connection settings")
            .setView(layout)
            .setPositiveButton("Connect") { _, _ ->
                val mode = if (modeGroup.checkedRadioButtonId == radioWifi.id) "wifi" else "usb"
                val host = hostField.text.toString().trim().ifEmpty { "192.168.1.1" }
                val port = portField.text.toString().toIntOrNull()?.coerceIn(1, 65535) ?: 8080
                prefs.edit()
                    .putString("mode", mode)
                    .putString("host", host)
                    .putInt("port", port)
                    .apply()
                reconnectDelayMs = 1_000L  // reset backoff on deliberate settings change
                connect()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
