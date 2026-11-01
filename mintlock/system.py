"""What the designs get to know about the machine: user, wallpaper, theme, battery."""

import glob
import os
import re
import pwd
import socket
from urllib.parse import unquote, urlparse

from gi.repository import Gio, GLib

from . import config


def _settings(schema):
    src = Gio.SettingsSchemaSource.get_default()
    if src is None or src.lookup(schema, True) is None:
        return None
    return Gio.Settings.new(schema)


def _file_url(path):
    return GLib.filename_to_uri(path, None) if path and os.path.isfile(path) else ""


def user_info():
    name = GLib.get_user_name()
    try:
        gecos = pwd.getpwnam(name).pw_gecos.split(",")[0].strip()
    except KeyError:
        gecos = ""
    real = gecos or name
    avatar = ""
    for cand in (os.path.expanduser("~/.face"),
                 "/var/lib/AccountsService/icons/" + name):
        if os.path.isfile(cand) and os.access(cand, os.R_OK):
            avatar = _file_url(cand)
            break
    return {"user": name, "realName": real, "initial": real[:1].upper(),
            "avatar": avatar, "host": socket.gethostname()}


def wallpaper():
    s = _settings("org.cinnamon.desktop.background")
    if s is None:
        return ""
    uri = s.get_string("picture-uri")
    if not uri:
        return ""
    path = unquote(urlparse(uri).path) if uri.startswith("file://") else uri
    return _file_url(path)


def _theme_dir(name):
    for base in (os.path.expanduser("~/.themes"),
                 os.path.join(GLib.get_user_data_dir(), "themes"),
                 "/usr/share/themes"):
        d = os.path.join(base, name)
        if os.path.isdir(d):
            return d
    return None


_MINT_ACCENTS = {
    "aqua": "#1f9ede", "blue": "#0c75de", "brown": "#b5834a", "grey": "#70737a",
    "orange": "#ff7139", "pink": "#e54980", "purple": "#8c5dd9", "red": "#e82127",
    "sand": "#c5a07c", "teal": "#199ca8",
}


def theme_colors():
    """accent / bg / fg from the GTK theme, falling back to Mint green on dark."""
    out = {"accent": "#35a854", "bg": "#1e1e1e", "fg": "#f0f0f0", "dark": True}
    s = _settings("org.cinnamon.desktop.interface")
    name = s.get_string("gtk-theme") if s else ""
    low = name.lower()
    for key, col in _MINT_ACCENTS.items():
        if low.endswith("-" + key):
            out["accent"] = col
    d = _theme_dir(name) if name else None
    if d:
        css = ""
        for f in ("gtk-3.0/gtk-dark.css", "gtk-3.0/gtk.css"):
            try:
                with open(os.path.join(d, f), encoding="utf-8", errors="replace") as fh:
                    css = fh.read(400_000)
                break
            except OSError:
                continue

        def color(*names):
            for n in names:
                m = re.search(r"@define-color\s+%s\s+(#[0-9a-fA-F]{6})\s*;" % n, css)
                if m:
                    return m.group(1)
            return None

        out["accent"] = color("accent_bg_color", "accent_color", "theme_selected_bg_color",
                              "selected_bg_color") or out["accent"]
        out["bg"] = color("theme_bg_color", "bg_color", "window_bg_color") or out["bg"]
        out["fg"] = color("theme_fg_color", "fg_color", "window_fg_color") or out["fg"]
    try:
        r, g, b = (int(out["bg"][i:i + 2], 16) for i in (1, 3, 5))
        out["dark"] = (0.299 * r + 0.587 * g + 0.114 * b) < 140
    except ValueError:
        pass
    return out


def battery():
    """{"present": bool, "percent": int, "charging": bool} for the first battery."""
    for d in sorted(glob.glob("/sys/class/power_supply/*")):
        try:
            with open(os.path.join(d, "type")) as f:
                if f.read().strip() != "Battery":
                    continue
            with open(os.path.join(d, "capacity")) as f:
                pct = int(f.read().strip())
            with open(os.path.join(d, "status")) as f:
                status = f.read().strip()
        except (OSError, ValueError):
            continue
        return {"present": True, "percent": pct,
                "charging": status in ("Charging", "Full", "Not charging")}
    return {"present": False, "percent": 100, "charging": False}


def environment(cfg=None, preview=False):
    """The object exposed to designs as window.MINTLOCK.env."""
    cfg = cfg or config.load()
    theme = theme_colors()
    env = dict(user_info())
    env.update({
        "wallpaper": wallpaper(),
        "theme": theme,
        "accent": cfg["accent"] or theme["accent"],
        "clock24": cfg["clock24"],
        "showSeconds": cfg["showSeconds"],
        "blur": cfg["blur"],
        "dim": cfg["dim"],
        "reduceMotion": cfg["reduceMotion"],
        "showUser": cfg["showUser"],
        "message": cfg["message"],
        "battery": battery(),
        "preview": preview,
    })
    if os.environ.get("MINTLOCK_DEMO"):
        # Neutral identity for screenshots and demos.
        demo_wall = os.path.join(config.ROOT, "docs", "demo-wallpaper.jpg")
        env.update({"user": "alex", "realName": "Alex Rivera", "initial": "A", "avatar": "",
                    "host": "mint", "wallpaper": _file_url(demo_wall), "message": "",
                    "theme": {"accent": "#35a854", "bg": "#1e1e1e", "fg": "#f0f0f0", "dark": True},
                    "accent": cfg["accent"] or "#35a854"})
    return env
