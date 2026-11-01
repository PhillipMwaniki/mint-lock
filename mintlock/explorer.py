"""The explorer: browse, preview and pick designs, and change settings."""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import config, system, webview  # noqa: E402

EXPLORER_PAGE = os.path.join(config.WEB, "explorer", "index.html")
BIN = os.path.join(config.ROOT, "bin", "mint-lock")
GSCHEMA = "org.cinnamon.desktop.screensaver"
GKEY = "custom-screensaver-command"


def _hook_settings():
    src = Gio.SettingsSchemaSource.get_default()
    if src is None or src.lookup(GSCHEMA, True) is None:
        return None
    return Gio.Settings.new(GSCHEMA)


def hooked():
    s = _hook_settings()
    return bool(s and "mint-lock" in s.get_string(GKEY))


def set_hooked(on):
    s = _hook_settings()
    if s is None:
        return False
    if on:
        s.set_string(GKEY, BIN + " lock")
    else:
        s.reset(GKEY)
    Gio.Settings.sync()
    return True


def _design_list():
    out = []
    for d in config.designs():
        item = {k: d[k] for k in ("id", "name", "description", "tags", "category", "builtin")}
        item["url"] = GLib.filename_to_uri(d["path"], None)
        out.append(item)
    return out


class PreviewWindow(Gtk.Window):
    """Full screen, nothing locked; Esc or a click on the close hint ends it."""

    def __init__(self, design_id, on_close=None):
        super().__init__(title="mint-lock preview")
        self.on_close = on_close
        env = system.environment(preview=True)
        self.view = webview.make_view(env, lambda *a: None)
        self.add(self.view)
        webview.load(self.view, config.design_path(design_id), "mode=preview")
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", lambda *a: on_close and on_close())
        self.fullscreen()
        self.show_all()
        self.view.grab_focus()

    def on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if ev.keyval == Gdk.KEY_u and ev.state & Gdk.ModifierType.CONTROL_MASK:
            webview.send(self.view, {"t": "unlock"})
            GLib.timeout_add(700, lambda: self.destroy() or False)
            return True
        return False


class Explorer(Gtk.Window):
    def __init__(self, debug=False):
        super().__init__(title="Lock Screen Explorer")
        self.set_default_size(1280, 800)
        self.set_icon_name("system-lock-screen")
        self.preview = None
        env = system.environment(preview=True)
        self.view = webview.make_view(env, self.on_message, debug=debug)
        self.add(self.view)
        webview.load(self.view, EXPLORER_PAGE)
        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def reply(self, msg):
        webview.send(self.view, msg)

    def state(self):
        cfg = config.load()
        return {"t": "state", "designs": _design_list(), "config": cfg, "hooked": hooked(),
                "env": system.environment(cfg, preview=True),
                "userDesignsDir": config.USER_DESIGNS_DIR}

    def on_message(self, _view, msg):
        t = msg.get("t")
        if t == "init":
            self.reply(self.state())
        elif t == "set":
            ids = {d["id"] for d in config.designs()}
            if msg.get("id") in ids:
                config.update(design=msg["id"])
            self.reply(self.state())
        elif t == "config":
            key, value = msg.get("key"), msg.get("value")
            if key != "favorites" and config.valid(key, value):
                config.update(**{key: value})
            self.reply(self.state())
        elif t == "favorite":
            cfg = config.load()
            favs = list(cfg["favorites"])
            did = msg.get("id")
            if did in favs:
                favs.remove(did)
            elif isinstance(did, str):
                favs.append(did)
            config.update(favorites=favs)
            self.reply(self.state())
        elif t == "hook":
            set_hooked(bool(msg.get("on")))
            self.reply(self.state())
        elif t == "preview":
            if self.preview is None:
                self.preview = PreviewWindow(msg.get("id") or config.load()["design"],
                                             on_close=self._preview_closed)
        elif t == "lock":
            subprocess.Popen([sys.executable, BIN, "lock"], start_new_session=True,
                             stdin=subprocess.DEVNULL)
        elif t == "open-folder":
            os.makedirs(config.USER_DESIGNS_DIR, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(config.USER_DESIGNS_DIR, None), None)
        elif t == "close":
            self.destroy()

    def _preview_closed(self):
        self.preview = None
        self.present()
        self.view.grab_focus()


def run(debug=False):
    Explorer(debug=debug)
    Gtk.main()
    return 0


def run_preview(design_id):
    PreviewWindow(design_id, on_close=Gtk.main_quit)
    Gtk.main()
    return 0
