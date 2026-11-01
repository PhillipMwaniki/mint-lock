"""Drives PAM through authhelper.py processes.

There is always one helper running while the screen is locked, so a module like
pam_fprintd can listen for a finger as soon as the lock comes up. If a password
is submitted while that helper is still busy with the fingerprint reader (and
so has not asked for a password yet), a second helper is started for the
password. The reader is claimed by the first one, so pam_fprintd in the second
gives up straight away and pam_unix asks for the password. Whichever helper
succeeds first unlocks; the rest are killed.
"""

import json
import os
import signal
import sys

from gi.repository import Gio, GLib

HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "authhelper.py")
PAM_SERVICE = "cinnamon-screensaver"


class _Helper:
    def __init__(self, auth, password=None):
        self.auth = auth
        self.pending = password       # answer to send at the first prompt
        self.waiting = False          # sitting at a password prompt
        self.checking = password is not None
        self.done = False
        self.proc = Gio.Subprocess.new(
            [sys.executable, "-I", HELPER, auth.service, auth.user],
            Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
            | Gio.SubprocessFlags.STDERR_SILENCE)
        self.stdin = self.proc.get_stdin_pipe()
        self.stdout = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.cancel = Gio.Cancellable()
        self._read()

    def _read(self):
        self.stdout.read_line_async(GLib.PRIORITY_DEFAULT, self.cancel, self._on_line)

    def _on_line(self, stream, res):
        try:
            line, _len = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            if not self.done:
                self.done = True
                self.auth._helper_gone(self)
            return
        try:
            msg = json.loads(line)
        except ValueError:
            msg = {}
        self.auth._message(self, msg)
        if not self.done:
            self._read()

    def answer(self, password):
        self.waiting = False
        self.checking = True
        data = (json.dumps(password) + "\n").encode()
        try:
            self.stdin.write_all(data, None)
            self.stdin.flush(None)
        except GLib.Error:
            pass

    def kill(self):
        self.done = True
        self.cancel.cancel()
        try:
            self.proc.send_signal(signal.SIGKILL)
        except Exception:
            pass


class Authenticator:
    """Events sent to on_event(kind, text):
        "info"    a message from PAM (e.g. "Place your finger on the reader")
        "ready"   a password can be typed and submitted
        "busy"    a password is being checked
        "failed"  the password (or finger) was rejected; text is PAM's message
        "success" unlock
    """

    def __init__(self, on_event, user=None, service=PAM_SERVICE):
        self.on_event = on_event
        self.user = user or GLib.get_user_name()
        self.service = service
        self.helpers = []
        self.finished = False
        self._respawn_id = 0

    def start(self):
        self._ensure_listener()

    def stop(self):
        self.finished = True
        if self._respawn_id:
            GLib.source_remove(self._respawn_id)
            self._respawn_id = 0
        for h in self.helpers:
            h.kill()
        self.helpers = []

    def submit(self, password):
        if self.finished:
            return
        if any(h.checking for h in self.helpers):
            return  # one check at a time
        self.on_event("busy", "")
        for h in self.helpers:
            if h.waiting:
                h.answer(password)
                return
        if len(self.helpers) < 2:
            self.helpers.append(_Helper(self, password))

    # -- helper callbacks -------------------------------------------------

    def _message(self, helper, msg):
        if self.finished:
            return
        kind = msg.get("t")
        text = msg.get("msg", "")
        if kind == "prompt":
            if helper.pending is not None:
                pw, helper.pending = helper.pending, None
                helper.answer(pw)
            else:
                helper.waiting = True
                self.on_event("ready", "")
        elif kind in ("info", "error"):
            if text:
                self.on_event("info", text)
        elif kind == "result":
            helper.done = True
            if msg.get("ok"):
                self.on_event("success", "")
                self.stop()
                return
            was_checking = helper.checking
            self._drop(helper)
            if was_checking:
                self.on_event("failed", text or "Authentication failed")
            self._ensure_listener()

    def _helper_gone(self, helper):
        if self.finished:
            return
        was_checking = helper.checking
        self._drop(helper)
        if was_checking:
            self.on_event("failed", "Authentication failed")
        self._ensure_listener(delay=1000)

    def _drop(self, helper):
        helper.kill()
        if helper in self.helpers:
            self.helpers.remove(helper)

    def _ensure_listener(self, delay=0):
        if self.finished or self.helpers or self._respawn_id:
            if not self.finished and any(h.waiting for h in self.helpers):
                self.on_event("ready", "")
            return

        def spawn():
            self._respawn_id = 0
            if not self.finished and not self.helpers:
                self.helpers.append(_Helper(self))
            return False

        if delay:
            self._respawn_id = GLib.timeout_add(delay, spawn)
        else:
            spawn()
