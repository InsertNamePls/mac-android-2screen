#!/usr/bin/env python3
"""
MacScreen Launcher
------------------
One-click setup for mac-android-2screen.

• Optionally creates a virtual display (requires `displayplacer` from Homebrew).
• Sets up USB ADB port-forwarding when using wired mode.
• Discovers the Mac's LAN IP when using Wi-Fi mode.
• Starts (and stops) the MJPEG streaming server.

Run with:
    python mac/launcher.py
"""

import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, scrolledtext, ttk

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER_PY = os.path.join(_HERE, "server.py")
_SCRIPTS = os.path.join(os.path.dirname(_HERE), "scripts")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _get_local_ips() -> list[str]:
    """Return non-loopback IPv4 addresses for this machine."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        results = socket.getaddrinfo(hostname, None)
        for item in results:
            addr = item[4][0]
            if "." in addr and not addr.startswith("127."):
                if addr not in ips:
                    ips.append(addr)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return ips


def _count_displays() -> int:
    """Return the number of connected displays (macOS only)."""
    if platform.system() != "Darwin":
        return 1
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=5
        )
        # Each display entry has a "Resolution:" line
        count = len(re.findall(r"Resolution:", result.stdout))
        return max(count, 1)
    except Exception:
        return 1


def _displayplacer_available() -> bool:
    return _which("displayplacer") is not None


def _adb_available() -> bool:
    return _which("adb") is not None


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MacScreen Launcher")
        self.resizable(False, False)
        self.configure(bg="#1e1e1e")

        self._server_proc: subprocess.Popen | None = None
        self._adb_proc: subprocess.Popen | None = None
        self._log_lock = threading.Lock()

        self._build_ui()
        self._refresh_display_count()
        self._on_mode_change()  # initialise mode-dependent UI state
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        pad = {"padx": 12, "pady": 6}

        # ---------- fonts ----------
        title_font = tkfont.Font(family="Helvetica", size=18, weight="bold")
        label_font = tkfont.Font(family="Helvetica", size=11)
        mono_font  = tkfont.Font(family="Menlo",     size=10)

        FG   = "#eeeeee"
        BG   = "#1e1e1e"
        CARD = "#2d2d2d"
        ACC  = "#0a84ff"  # macOS blue

        def card(parent: tk.Widget) -> tk.Frame:
            f = tk.Frame(parent, bg=CARD, bd=0, relief="flat")
            return f

        def lbl(parent: tk.Widget, text: str, **kw) -> tk.Label:
            return tk.Label(parent, text=text, bg=CARD, fg=FG, font=label_font, **kw)

        # ---------- title ----------
        tk.Label(
            self, text="MacScreen Launcher", font=title_font,
            bg=BG, fg=FG
        ).grid(row=0, column=0, columnspan=2, pady=(16, 4))

        tk.Label(
            self, text="Stream your Mac display to an Android tablet",
            font=tkfont.Font(family="Helvetica", size=11),
            bg=BG, fg="#888888"
        ).grid(row=1, column=0, columnspan=2, pady=(0, 12))

        # ---------- virtual display card ----------
        vd_card = card(self)
        vd_card.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        lbl(vd_card, "Virtual Display", font=tkfont.Font(family="Helvetica", size=12, weight="bold"),
            anchor="w").grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 2))
        lbl(vd_card, "Create a virtual second display that macOS treats as a real monitor.",
            fg="#aaaaaa", anchor="w").grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 8))

        lbl(vd_card, "Resolution:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self._vd_res = tk.StringVar(value="1920x1200")
        res_box = ttk.Combobox(
            vd_card, textvariable=self._vd_res, width=12, state="readonly",
            values=["1280x800", "1920x1080", "1920x1200", "2560x1600", "2732x2048"]
        )
        res_box.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        self._vd_btn = tk.Button(
            vd_card, text="Create Virtual Display",
            command=self._create_virtual_display,
            bg=ACC, fg="white", font=label_font,
            activebackground="#0060cc", activeforeground="white",
            relief="flat", padx=10, pady=4, cursor="hand2"
        )
        self._vd_btn.grid(row=2, column=2, padx=10, pady=4)

        if not _displayplacer_available():
            lbl(vd_card,
                "⚠  displayplacer not found — install via:  brew install displayplacer",
                fg="#ffcc00", anchor="w"
                ).grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 8))
            self._vd_btn.configure(state="disabled")
        else:
            tk.Label(vd_card, bg=CARD).grid(row=3, pady=4)  # spacer

        # ---------- connection card ----------
        conn_card = card(self)
        conn_card.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)

        lbl(conn_card, "Connection Mode", font=tkfont.Font(family="Helvetica", size=12, weight="bold"),
            anchor="w").grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))

        self._mode = tk.StringVar(value="usb")
        for col, (val, txt) in enumerate([("usb", "USB (ADB)"), ("wifi", "Wi-Fi")]):
            rb = tk.Radiobutton(
                conn_card, text=txt, variable=self._mode, value=val,
                command=self._on_mode_change,
                bg=CARD, fg=FG, selectcolor="#444444",
                activebackground=CARD, activeforeground=FG,
                font=label_font
            )
            rb.grid(row=1, column=col, sticky="w", padx=(10 if col == 0 else 2), pady=4)

        self._wifi_ip_label = lbl(conn_card, "Mac IP:")
        self._wifi_ip_label.grid(row=2, column=0, sticky="w", padx=10, pady=(4, 8))
        self._wifi_ip_var = tk.StringVar(value="Detecting…")
        self._wifi_ip_entry = tk.Label(
            conn_card, textvariable=self._wifi_ip_var,
            bg=CARD, fg="#aaffaa", font=mono_font, anchor="w"
        )
        self._wifi_ip_entry.grid(row=2, column=1, columnspan=3, sticky="w", padx=4, pady=(4, 8))

        # ADB status
        self._adb_label = lbl(conn_card, "")
        self._adb_label.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 8))

        # ---------- server settings card ----------
        srv_card = card(self)
        srv_card.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)

        lbl(srv_card, "Server Settings", font=tkfont.Font(family="Helvetica", size=12, weight="bold"),
            anchor="w").grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))

        settings: list[tuple[str, tk.Variable, list[str]]] = [
            ("Display #",  tk.StringVar(value="1"),  ["1", "2", "3", "4"]),
            ("Port",       tk.StringVar(value="8080"), []),
            ("FPS",        tk.StringVar(value="30"),  ["15", "20", "24", "30", "60"]),
            ("Quality",    tk.StringVar(value="75"),  ["50", "65", "75", "85", "95"]),
        ]
        self._display_var, self._port_var, self._fps_var, self._quality_var = [s[1] for s in settings]

        for col, (label, var, choices) in enumerate(settings):
            lbl(srv_card, label).grid(row=1, column=col * 2, sticky="e", padx=(10 if col == 0 else 6, 2), pady=4)
            if choices:
                w = ttk.Combobox(srv_card, textvariable=var, values=choices, width=5, state="readonly")
            else:
                w = tk.Entry(srv_card, textvariable=var, width=7, bg="#3a3a3a", fg=FG,
                             insertbackground=FG, relief="flat", font=label_font)
            w.grid(row=1, column=col * 2 + 1, sticky="w", padx=(0, 6), pady=4)

        lbl(srv_card, "").grid(row=2, pady=4)  # spacer

        # ---------- start / stop buttons ----------
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=8)

        self._start_btn = tk.Button(
            btn_frame, text="▶  Start",
            command=self._start,
            bg="#30d158", fg="white",
            font=tkfont.Font(family="Helvetica", size=13, weight="bold"),
            activebackground="#28a745", activeforeground="white",
            relief="flat", padx=20, pady=8, width=12, cursor="hand2"
        )
        self._start_btn.grid(row=0, column=0, padx=8)

        self._stop_btn = tk.Button(
            btn_frame, text="■  Stop",
            command=self._stop,
            bg="#ff453a", fg="white",
            font=tkfont.Font(family="Helvetica", size=13, weight="bold"),
            activebackground="#cc2222", activeforeground="white",
            relief="flat", padx=20, pady=8, width=12, cursor="hand2",
            state="disabled"
        )
        self._stop_btn.grid(row=0, column=1, padx=8)

        # ---------- log area ----------
        log_frame = tk.Frame(self, bg=BG)
        log_frame.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))

        tk.Label(log_frame, text="Log", bg=BG, fg="#888888",
                 font=tkfont.Font(family="Helvetica", size=10)).pack(anchor="w")
        self._log = scrolledtext.ScrolledText(
            log_frame, height=10, width=68,
            bg="#111111", fg="#cccccc", font=mono_font,
            relief="flat", state="disabled", wrap="word"
        )
        self._log.pack(fill="both", expand=True)

        # Detect IPs in background
        threading.Thread(target=self._detect_ips, daemon=True).start()

    # ------------------------------------------------------------------
    # Mode helpers
    # ------------------------------------------------------------------

    def _on_mode_change(self) -> None:
        is_wifi = self._mode.get() == "wifi"
        self._wifi_ip_label.configure(fg="#eeeeee" if is_wifi else "#555555")
        self._wifi_ip_entry.configure(fg="#aaffaa" if is_wifi else "#555555")

        if is_wifi:
            adb_msg = ""
        else:
            if _adb_available():
                adb_msg = "✓  adb found — USB port forwarding will be set up automatically."
                color = "#aaffaa"
            else:
                adb_msg = "⚠  adb not found — install via:  brew install android-platform-tools"
                color = "#ffcc00"
            self._adb_label.configure(text=adb_msg, fg=color if not is_wifi else "#555555")
            return
        self._adb_label.configure(text=adb_msg)

    def _detect_ips(self) -> None:
        ips = _get_local_ips()
        display = ", ".join(ips) if ips else "Not detected"
        self.after(0, lambda: self._wifi_ip_var.set(display))

    def _refresh_display_count(self) -> None:
        count = _count_displays()
        self._log_write(f"Detected {count} connected display(s).\n")

    # ------------------------------------------------------------------
    # Virtual display
    # ------------------------------------------------------------------

    def _create_virtual_display(self) -> None:
        """Use displayplacer to create a virtual display."""
        res = self._vd_res.get()  # e.g. "1920x1200"
        w, h = res.split("x")
        self._log_write(f"Creating virtual display {w}×{h} via displayplacer…\n")
        threading.Thread(target=self._run_displayplacer, args=(w, h), daemon=True).start()

    def _run_displayplacer(self, width: str, height: str) -> None:
        try:
            # List current screens so we know what already exists.
            list_result = subprocess.run(
                ["displayplacer", "list"],
                capture_output=True, text=True, timeout=10
            )
            self._log_write(list_result.stdout)

            # Build a dummy resolution string that macOS will create as a virtual display.
            # displayplacer uses "res:WxH hz:60 color_depth:8 scaling:off origin:(0,0) degree:0"
            cmd = [
                "displayplacer",
                f"res:{width}x{height}",
                "hz:60",
                "color_depth:8",
                "scaling:off",
                "origin:(0,0)",
                "degree:0",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            out = result.stdout + result.stderr
            self.after(0, lambda: self._log_write(out or "displayplacer command finished.\n"))
        except FileNotFoundError:
            self.after(0, lambda: self._log_write("displayplacer not found.\n"))
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self._log_write("displayplacer timed out.\n"))
        except Exception as exc:
            self.after(0, lambda: self._log_write(f"Error: {exc}\n"))

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def _start(self) -> None:
        self._log_write("─" * 50 + "\n")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        threading.Thread(target=self._start_sequence, daemon=True).start()

    def _start_sequence(self) -> None:
        mode = self._mode.get()

        # 1. USB: ADB reverse forwarding
        if mode == "usb":
            port = self._port_var.get().strip() or "8080"
            if _adb_available():
                self._log_write("Setting up ADB reverse port forwarding…\n")
                try:
                    result = subprocess.run(
                        ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
                        capture_output=True, text=True, timeout=10
                    )
                    out = result.stdout + result.stderr
                    if result.returncode == 0:
                        self._log_write(f"✓  adb reverse tcp:{port} tcp:{port}\n")
                    else:
                        self._log_write(f"⚠  adb: {out.strip()}\n")
                except subprocess.TimeoutExpired:
                    self._log_write("⚠  adb timed out — is a device connected?\n")
                except Exception as exc:
                    self._log_write(f"⚠  adb error: {exc}\n")
            else:
                self._log_write("⚠  adb not found — skipping USB forwarding.\n")

        # 2. Start the Python server
        display  = self._display_var.get().strip() or "1"
        port     = self._port_var.get().strip()    or "8080"
        fps      = self._fps_var.get().strip()     or "30"
        quality  = self._quality_var.get().strip() or "75"

        cmd = [
            sys.executable, _SERVER_PY,
            "--display", display,
            "--port",    port,
            "--fps",     fps,
            "--quality", quality,
        ]
        self._log_write(f"Starting server:  {' '.join(cmd)}\n")
        try:
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._log_write(f"Failed to start server: {exc}\n")
            self.after(0, self._reset_buttons)
            return

        self._log_write(f"✓  Server started (PID {self._server_proc.pid})\n")
        if mode == "wifi":
            ips = _get_local_ips()
            if ips:
                self._log_write(f"   Open MacScreen app → Wi-Fi mode → IP: {ips[0]}, port: {port}\n")
        else:
            self._log_write(f"   Open MacScreen app → USB (ADB) mode, port: {port}\n")

        # Stream server output into the log
        assert self._server_proc.stdout is not None
        for line in self._server_proc.stdout:
            self._log_write(line)
        self._server_proc.wait()
        self._log_write(f"Server exited (code {self._server_proc.returncode}).\n")
        self.after(0, self._reset_buttons)

    def _stop(self) -> None:
        if self._server_proc and self._server_proc.poll() is None:
            self._log_write("Stopping server…\n")
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
        self._reset_buttons()

    def _reset_buttons(self) -> None:
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_write(self, text: str) -> None:
        def _append():
            self._log.configure(state="normal")
            self._log.insert("end", text)
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _append)

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._server_proc and self._server_proc.poll() is None:
            if messagebox.askyesno(
                "MacScreen",
                "The server is still running.\nStop it and quit?"
            ):
                self._stop()
            else:
                return
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if platform.system() != "Darwin":
        print("Warning: MacScreen is designed for macOS. Some features may not work.")
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
