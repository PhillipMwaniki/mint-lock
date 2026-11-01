"""Keeps the screen locked no matter what happens to the lock screen UI.

`mint-lock lock` runs this. It is deliberately small and uses only python-xlib
(no GTK, no WebKit), so there is little in it that can crash:

  1. Map a black override-redirect "shield" over the whole screen and grab the
     keyboard and pointer on it.
  2. Start Cinnamon's cs-backup-locker watching the shield, in case this
     process itself is killed.
  3. Start the UI (locker.py) as a child. When the child reports its windows
     are up, release the grab so the child can take it.
  4. If the child exits without reporting a successful unlock, grab again
     straight away and start a new child. After repeated crashes the child is
     started in safe mode (plain GTK password box, no WebKit).
  5. Only when the child reports "unlocked" and exits: stop the backup
     locker, unmap the shield and exit.

Cinnamon's power daemon (csd-power) runs the lock command itself on idle and
before suspend. Before suspend it passes XSS_SLEEP_LOCK_FD, a descriptor it
waits on: closing it says "the screen is covered, go ahead and sleep". That is
closed as soon as the UI reports ready (or right away if already locked).

SIGUSR1 ends the lock without a password. Only the same user can send it, and
that user could kill the session anyway; it is the way out from a text console
if the lock screen is ever stuck: `pkill -USR1 -f "mint-lock lock"`.
"""

import fcntl
import os
import select
import signal
import subprocess
import sys
import time

from Xlib import X, display, error

from . import config

BACKUP_LOCKER = "/usr/libexec/cinnamon-screensaver/cs-backup-locker"
BIN = os.path.join(config.ROOT, "bin", "mint-lock")
SAFE_AFTER = 3          # crashes within CRASH_WINDOW before using safe mode
CRASH_WINDOW = 60


def log(*a):
    print("mint-lock[supervisor]:", *a, file=sys.stderr, flush=True)


def release_sleep_fd():
    """Tell csd-power the screen is locked so suspend can go ahead."""
    fd = os.environ.pop("XSS_SLEEP_LOCK_FD", None)
    if fd and fd.isdigit():
        try:
            os.close(int(fd))
        except OSError:
            pass


class InstanceLock:
    """Only one lock at a time; a second `mint-lock lock` does nothing."""

    path = os.path.join(config.RUNTIME_DIR, "locked")

    def __init__(self):
        os.makedirs(config.RUNTIME_DIR, mode=0o700, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)

    def acquire(self):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())
        return True

    @classmethod
    def holder(cls):
        """pid of the running lock, or 0."""
        try:
            fd = os.open(cls.path, os.O_RDONLY | os.O_CLOEXEC)
        except OSError:
            return 0
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                return 0
            except BlockingIOError:
                data = os.read(fd, 32).decode(errors="ignore").strip()
                return int(data) if data.isdigit() else -1
        finally:
            os.close(fd)


class Supervisor:
    def __init__(self, design=None, debug=False):
        self.design = design
        self.debug = debug
        self.d = display.Display()
        self.screen = self.d.screen()
        self.root = self.screen.root
        self.shield = None
        self.grabbed = False
        self.child = None
        self.report = None
        self.buf = b""
        self.unlocked = False
        self.crashes = []
        self.backup = None
        self.stop_requested = False

    # -- X ------------------------------------------------------------------

    def make_shield(self):
        geo = self.root.get_geometry()
        self.shield = self.root.create_window(
            0, 0, geo.width, geo.height, 0, self.screen.root_depth,
            X.InputOutput, X.CopyFromParent,
            background_pixel=self.screen.black_pixel,
            override_redirect=True,
            event_mask=X.StructureNotifyMask)
        self.shield.set_wm_name("mint-lock-shield")
        self.shield.set_wm_class("mint-lock", "MintLock")
        self.shield.map()
        self.shield.raise_window()
        self.root.change_attributes(event_mask=X.StructureNotifyMask)
        self.d.sync()

    def fit_shield(self):
        geo = self.root.get_geometry()
        self.shield.configure(x=0, y=0, width=geo.width, height=geo.height)
        self.d.sync()

    def grab(self, tries=200):
        """Grab keyboard and pointer on the shield, retrying for up to tries*50ms."""
        if self.grabbed:
            return True
        for _ in range(tries):
            try:
                self.shield.raise_window()
                kb = self.shield.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
                if kb == X.GrabSuccess:
                    ptr = self.shield.grab_pointer(
                        False, X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask,
                        X.GrabModeAsync, X.GrabModeAsync, self.shield, X.NONE, X.CurrentTime)
                    self.grabbed = True
                    if ptr != X.GrabSuccess:
                        log("pointer grab failed (%s); keyboard is held" % ptr)
                    self.d.sync()
                    return True
            except error.XError as e:
                log("grab error:", e)
            time.sleep(0.05)
        log("could not grab the keyboard; another client is holding it")
        return False

    def ungrab(self):
        if self.grabbed:
            self.d.ungrab_keyboard(X.CurrentTime)
            self.d.ungrab_pointer(X.CurrentTime)
            self.d.sync()
            self.grabbed = False

    def drain_x(self):
        while self.d.pending_events():
            ev = self.d.next_event()
            if ev.type == X.ConfigureNotify and ev.window == self.root:
                self.fit_shield()

    # -- backup locker --------------------------------------------------------

    def start_backup(self):
        if not os.path.exists(BACKUP_LOCKER):
            return
        session_tty = os.environ.get("XDG_VTNR", "7")
        term_tty = "2" if session_tty != "2" else "1"
        try:
            self.backup = subprocess.Popen(
                [BACKUP_LOCKER, "--xid", str(self.shield.id), "--term", term_tty,
                 "--session", session_tty],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            log("backup locker not started:", e)

    def stop_backup(self):
        if self.backup and self.backup.poll() is None:
            self.backup.terminate()
            try:
                self.backup.wait(2)
            except subprocess.TimeoutExpired:
                self.backup.kill()
        self.backup = None

    # -- child ----------------------------------------------------------------

    def safe_mode(self):
        now = time.monotonic()
        self.crashes = [t for t in self.crashes if now - t < CRASH_WINDOW]
        return len(self.crashes) >= SAFE_AFTER

    def start_child(self):
        r, w = os.pipe()
        os.set_inheritable(w, True)
        args = [sys.executable, BIN, "lock", "--child", str(w)]
        if self.design:
            args += ["--design", self.design]
        if self.debug:
            args.append("--debug")
        if self.safe_mode():
            args.append("--safe")
            log("starting the lock screen in safe mode after repeated crashes")
        self.child = subprocess.Popen(args, pass_fds=(w,), stdin=subprocess.DEVNULL)
        os.close(w)
        self.report = r
        self.buf = b""

    def read_report(self):
        try:
            data = os.read(self.report, 4096)
        except OSError:
            data = b""
        if not data:
            os.close(self.report)
            self.report = None
            return
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if line == b"ready":
                self.ungrab()
                release_sleep_fd()
            elif line == b"unlocked":
                self.unlocked = True

    def child_exited(self, code):
        self.child = None
        if self.report is not None:
            os.close(self.report)
            self.report = None
        if self.unlocked and code == 0:
            return True
        self.unlocked = False
        self.crashes.append(time.monotonic())
        log("lock screen UI exited (%s) without unlocking; restarting" % code)
        self.grab()
        if len(self.crashes) > 20:
            time.sleep(1)  # something is badly wrong; don't spin
        self.start_child()
        return False

    # -- main ---------------------------------------------------------------------

    def run(self):
        signal.signal(signal.SIGUSR1, lambda *a: setattr(self, "stop_requested", True))
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)  # being told to quit is not an unlock

        self.make_shield()
        self.grab()
        self.start_backup()
        self.start_child()
        xfd = self.d.fileno()

        while True:
            if self.stop_requested:
                log("unlock requested by the session")
                if self.child and self.child.poll() is None:
                    self.child.kill()
                    self.child.wait()
                break
            fds = [xfd] + ([self.report] if self.report is not None else [])
            try:
                ready, _, _ = select.select(fds, [], [], 0.25)
            except InterruptedError:
                continue
            if xfd in ready:
                self.drain_x()
            if self.report is not None and self.report in ready:
                self.read_report()
            if self.child is not None:
                code = self.child.poll()
                if code is not None and self.child_exited(code):
                    break

        self.stop_backup()
        self.ungrab()
        self.shield.destroy()
        self.d.sync()
        self.d.close()
        return 0


def lock(design=None, debug=False):
    inst = InstanceLock()
    if not inst.acquire():
        log("already locked")
        release_sleep_fd()
        return 0
    return Supervisor(design=design, debug=debug).run()
