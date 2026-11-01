"""The lock screen itself.

One override-redirect window per monitor. The primary monitor shows the chosen
design and takes the keyboard and pointer grab; the others show a clock.

This runs as a child of supervisor.py, which keeps a black shield and the
grab whenever this process is not up, and restarts it if it dies. It reports
"ready" once its windows cover the screen and "unlocked" after PAM says yes,
on the file descriptor the supervisor passes in.

--test runs it alone in an ordinary window with no grabs, for trying designs.
"""

import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, system, webview  # noqa: E402
from .auth import Authenticator  # noqa: E402

CLOCK_PAGE = os.path.join(config.DESIGNS_DIR, "_clock.html")
SLEEP_AFTER = 45          # seconds without input before the design rests
OUTRO_MAX_MS = 900        # longest an unlock animation may hold the screen


def log(*args):
    print("mint-lock:", *args, file=sys.stderr, flush=True)


class MonitorWindow(Gtk.Window):
    def __init__(self, locker, monitor, primary, windowed=False):
        super().__init__(type=Gtk.WindowType.TOPLEVEL if windowed else Gtk.WindowType.POPUP)
        self.locker = locker
        self.monitor = monitor
        self.primary = primary
        self.crashes = 0
        self.native = None
        self.page_ready = False

        geo = monitor.get_geometry()
        if windowed:
            self.set_default_size(min(geo.width, 1280), min(geo.height, 720))
            self.set_title("mint-lock (test)")
        else:
            self.set_decorated(False)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_keep_above(True)
            self.move(geo.x, geo.y)
            self.set_default_size(geo.width, geo.height)
            self.resize(geo.width, geo.height)

        self.view = webview.make_view(locker.env, self.on_message, debug=locker.debug)
        self.view.connect("web-process-terminated", self.on_web_crash)
        self.add(self.view)
        self.load_page()

        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("key-press-event", locker.on_activity)
        self.connect("motion-notify-event", locker.on_activity)
        self.connect("button-press-event", locker.on_activity)
        self.connect("grab-broken-event", lambda *a: locker.schedule_grab())
        # Real lock windows cannot be closed; the windowed test one can.
        self.connect("delete-event", lambda *a: (Gtk.main_quit() if windowed else None) or True)

    def load_page(self):
        self.page_ready = False
        if self.primary:
            webview.load(self.view, self.locker.design_path, "mode=lock")
        else:
            webview.load(self.view, CLOCK_PAGE, "mode=lock")

    def on_message(self, _view, msg):
        t = msg.get("t")
        if t == "ready":
            self.page_ready = True
            if self.primary:
                self.locker.push_auth_state()
        elif self.primary:
            self.locker.on_page_message(msg)

    def on_web_crash(self, _view, reason):
        self.crashes += 1
        log("design web process ended (%s), crash %d" % (reason, self.crashes))
        if self.primary and self.crashes >= 3:
            self.use_native_fallback()
        else:
            GLib.timeout_add(200, lambda: (self.load_page(), False)[1])

    def use_native_fallback(self):
        """Plain GTK password box, for when the design cannot be rendered."""
        if self.native:
            return
        self.remove(self.view)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large'>Locked</span>")
        self.native_msg = Gtk.Label(label="The lock screen design failed; enter your password.")
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_width_chars(28)
        entry.connect("activate", lambda e: (self.locker.auth.submit(e.get_text()), e.set_text("")))
        for w in (title, self.native_msg, entry):
            box.pack_start(w, False, False, 0)
        self.add(box)
        box.show_all()
        entry.grab_focus()
        self.native = entry
        self.locker.schedule_grab()

    def focus_input(self):
        if self.native:
            self.native.grab_focus()
        else:
            self.view.grab_focus()


class Locker:
    def __init__(self, windowed=False, debug=False, design=None, timeout=0,
                 report_fd=None, safe=False):
        self.windowed = windowed
        self.report_fd = report_fd
        self.safe = safe
        self.debug = debug
        self.timeout = timeout
        self.cfg = config.load()
        self.design_path = config.design_path(design or self.cfg["design"])
        self.env = system.environment(self.cfg)
        self.windows = []
        self.grabbed = False
        self._grab_id = 0
        self.unlocking = False
        self.last_activity = time.monotonic()
        self.asleep = False
        self.auth_state = ("ready", "")
        self.auth = Authenticator(self.on_auth)

    # -- windows ------------------------------------------------------------

    def build_windows(self):
        for w in self.windows:
            w.destroy()
        self.windows = []
        display = Gdk.Display.get_default()
        primary = display.get_primary_monitor() or display.get_monitor(0)
        monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        if self.windowed:
            monitors = [primary]
        for m in monitors:
            win = MonitorWindow(self, m, m == primary, self.windowed)
            win.show_all()
            if self.safe and win.primary:
                win.use_native_fallback()
            self.windows.append(win)
        self.primary_window().focus_input()
        self.schedule_grab()

    def report(self, line):
        if self.report_fd is None:
            return
        try:
            os.write(self.report_fd, (line + "\n").encode())
        except OSError:
            pass

    def primary_window(self):
        for w in self.windows:
            if w.primary:
                return w
        return self.windows[0]

    def on_monitors_changed(self, *_a):
        if self.unlocking:
            return
        self.build_windows()

    # -- grabs --------------------------------------------------------------

    def schedule_grab(self):
        if self.windowed or self._grab_id:
            return
        self.grabbed = False
        self._grab_id = GLib.timeout_add(50, self._try_grab)

    def _try_grab(self):
        win = self.primary_window()
        gdkwin = win.get_window()
        if gdkwin is None:
            return True
        seat = Gdk.Display.get_default().get_default_seat()
        status = seat.grab(gdkwin, Gdk.SeatCapabilities.ALL, False,
                           Gdk.Cursor.new_from_name(gdkwin.get_display(), "default"),
                           None, None, None)
        if status == Gdk.GrabStatus.SUCCESS:
            self.grabbed = True
            self._grab_id = 0
            win.focus_input()
            return False
        # Someone else (an open menu, a drag) holds the grab; keep trying. The
        # windows are already covering the screen in the meantime.
        return True

    # -- auth ---------------------------------------------------------------

    def on_auth(self, kind, text):
        self.auth_state = (kind, text)
        self.push_auth_state()
        win = self.primary_window() if self.windows else None
        if win is not None and win.native is not None and kind in ("failed", "info"):
            win.native_msg.set_text(text)
        if kind == "success":
            self.unlock()

    def push_auth_state(self):
        if not self.windows:
            return
        kind, text = self.auth_state
        webview.send(self.primary_window().view, {"t": "auth", "state": kind, "text": text})

    def on_page_message(self, msg):
        t = msg.get("t")
        if t == "submit" and not self.unlocking:
            pw = msg.get("password")
            if isinstance(pw, str):
                self.auth.submit(pw)
        elif t == "outro-done" and self.unlocking:
            self.finish()

    # -- activity / sleep -----------------------------------------------------

    def on_activity(self, *_a):
        self.last_activity = time.monotonic()
        if self.asleep:
            self.asleep = False
            for w in self.windows:
                webview.send(w.view, {"t": "wake"})
        return False

    def tick(self):
        if self.unlocking:
            return False
        if not self.asleep and time.monotonic() - self.last_activity > SLEEP_AFTER:
            self.asleep = True
            for w in self.windows:
                webview.send(w.view, {"t": "sleep"})
        return True

    def refresh_env(self):
        bat = system.battery()
        for w in self.windows:
            webview.send(w.view, {"t": "battery", "battery": bat})
        return not self.unlocking

    # -- lifecycle ------------------------------------------------------------

    def run(self):
        display = Gdk.Display.get_default()
        if display is None:
            log("no display")
            return 1
        display.connect("monitor-added", self.on_monitors_changed)
        display.connect("monitor-removed", self.on_monitors_changed)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            # Being asked to quit is not a reason to unlock. In test mode it is.
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig,
                                 lambda *a: (Gtk.main_quit() if self.windowed else None) or True)

        self.build_windows()
        # Let the windows map before telling the supervisor to hand over the grab.
        GLib.timeout_add(150, lambda: self.report("ready") or False)
        GLib.timeout_add_seconds(5, self.tick)
        GLib.timeout_add_seconds(60, self.refresh_env)
        if self.timeout:
            GLib.timeout_add_seconds(self.timeout, lambda: self.on_auth("success", "") or False)
        self.auth.start()
        Gtk.main()
        return 0

    def unlock(self):
        if self.unlocking:
            return
        self.unlocking = True
        self.auth.stop()
        for w in self.windows:
            webview.send(w.view, {"t": "unlock"})
        GLib.timeout_add(OUTRO_MAX_MS, self.finish)

    def finish(self):
        if not self.unlocking:
            return False
        self.unlocking = None  # finish only once
        self.report("unlocked")
        Gdk.Display.get_default().get_default_seat().ungrab()
        for w in self.windows:
            w.destroy()
        Gtk.main_quit()
        return False


def run(windowed=False, debug=False, design=None, timeout=0, report_fd=None, safe=False):
    return Locker(windowed=windowed, debug=debug, design=design, timeout=timeout,
                  report_fd=report_fd, safe=safe).run()
