"""Render a design to PNG without showing anything on screen (for thumbnails and checks)."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402

from . import config, system, webview  # noqa: E402


def snapshot(design_id, out_path, width=1920, height=1080, delay_ms=1500, query="mode=thumb"):
    env = system.environment(preview=True)
    win = Gtk.OffscreenWindow()
    win.set_default_size(width, height)
    view = webview.make_view(env, lambda *a: None)
    view.set_size_request(width, height)
    win.add(view)
    win.show_all()
    result = {"ok": False}

    def save(_view, res):
        try:
            surface = view.get_snapshot_finish(res)
            surface.write_to_png(out_path)
            result["ok"] = True
        except GLib.Error as e:
            print("snapshot failed:", e.message)
        Gtk.main_quit()

    def shoot():
        view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, save)
        return False

    def on_load(_v, ev):
        if ev == WebKit2.LoadEvent.FINISHED:
            GLib.timeout_add(delay_ms, shoot)

    view.connect("load-changed", on_load)
    webview.load(view, config.design_path(design_id), query)
    GLib.timeout_add_seconds(20, lambda: Gtk.main_quit() or False)
    Gtk.main()
    return result["ok"]
