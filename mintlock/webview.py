"""WebKit views that host designs, plus the JS bridge (window.MintLock)."""

import json
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, WebKit2  # noqa: E402

from . import config  # noqa: E402

_LIB = os.path.join(config.WEB, "lib")


def _allowed_uri(uri):
    """Designs are local files; nothing in them may navigate the view elsewhere."""
    if not uri.startswith("file://"):
        return uri in ("about:blank",)
    path = GLib.filename_from_uri(uri)[0]
    path = os.path.realpath(path)
    return any(path.startswith(os.path.realpath(base) + os.sep)
               for base in (config.WEB, config.USER_DESIGNS_DIR))


def make_view(env, on_message, debug=False, extra_handlers=None):
    """A WebView with window.MINTLOCK_ENV set before any page script runs.

    on_message(view, dict) receives everything the page posts through
    MintLock.post(); extra_handlers maps additional handler names to callbacks.
    """
    ucm = WebKit2.UserContentManager()
    ucm.add_script(WebKit2.UserScript.new(
        "window.MINTLOCK_ENV = %s;" % json.dumps(env),
        WebKit2.UserContentInjectedFrames.ALL_FRAMES,
        WebKit2.UserScriptInjectionTime.START, None, None))

    view = WebKit2.WebView.new_with_user_content_manager(ucm)

    def handler(_ucm, result, cb=on_message):
        try:
            value = result.get_js_value().to_string()
            msg = json.loads(value)
        except Exception:
            return
        if isinstance(msg, dict):
            cb(view, msg)

    ucm.register_script_message_handler("mintlock")
    ucm.connect("script-message-received::mintlock", handler)
    for name, cb in (extra_handlers or {}).items():
        ucm.register_script_message_handler(name)
        ucm.connect("script-message-received::" + name,
                    lambda u, r, cb=cb: handler(u, r, cb))

    s = view.get_settings()
    s.set_enable_javascript(True)
    s.set_allow_file_access_from_file_urls(True)
    s.set_allow_universal_access_from_file_urls(False)
    s.set_enable_developer_extras(debug)
    s.set_enable_write_console_messages_to_stdout(debug)
    s.set_enable_back_forward_navigation_gestures(False)
    s.set_javascript_can_open_windows_automatically(False)
    s.set_enable_webaudio(True)
    s.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
    s.set_enable_page_cache(False)

    view.set_background_color(Gdk.RGBA(0, 0, 0, 1))

    def on_policy(_v, decision, kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                    WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION or not _allowed_uri(uri):
                decision.ignore()
                return True
        return False

    view.connect("decide-policy", on_policy)
    if not debug:
        view.connect("context-menu", lambda *a: True)
    return view


def send(view, msg):
    """Deliver msg to MintLock._recv() in the page (no-op before the lib loads)."""
    js = "window.MintLock && window.MintLock._recv(%s);" % json.dumps(msg)
    try:
        view.evaluate_javascript(js, -1, None, None, None, None, None)
    except Exception:
        pass


def load(view, path, query=""):
    uri = GLib.filename_to_uri(path, None)
    view.load_uri(uri + (("?" + query) if query else ""))
