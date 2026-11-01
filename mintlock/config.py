"""Settings, design discovery and paths."""

import json
import os

from gi.repository import GLib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
DESIGNS_DIR = os.path.join(WEB, "designs")
USER_DESIGNS_DIR = os.path.join(GLib.get_user_data_dir(), "mint-lock", "designs")
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "mint-lock")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
RUNTIME_DIR = os.path.join(GLib.get_user_runtime_dir(), "mint-lock")

DEFAULTS = {
    "design": "classic",
    "clock24": True,
    "showSeconds": False,
    "accent": "",          # empty: follow the Cinnamon theme
    "blur": 18,            # wallpaper blur in px, for designs that show it
    "dim": 0.35,           # 0..1 darkening over the wallpaper
    "reduceMotion": False,
    "showUser": True,
    "favorites": [],
    "message": "",         # shown under the clock, e.g. "Back in 10"
}


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if k not in DEFAULTS:
                    continue
                want = DEFAULTS[k]
                if isinstance(want, bool):
                    ok = isinstance(v, bool)
                elif isinstance(want, (int, float)):
                    ok = isinstance(v, (int, float)) and not isinstance(v, bool)
                else:
                    ok = isinstance(v, type(want))
                if ok:
                    cfg[k] = v
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    clean = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def update(**changes):
    cfg = load()
    cfg.update({k: v for k, v in changes.items() if k in DEFAULTS})
    save(cfg)
    return cfg


def _read_meta(path):
    """Designs carry their metadata in a <script type="application/json" id="meta"> block."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(64 * 1024)
    except OSError:
        return None
    start = text.find('id="meta"')
    if start < 0:
        return {}
    start = text.find(">", start) + 1
    end = text.find("</script>", start)
    try:
        meta = json.loads(text[start:end])
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        return {}


def designs():
    """All designs, built-in first, as a list of dicts with id/name/path/..."""
    found = {}
    for base, builtin in ((DESIGNS_DIR, True), (USER_DESIGNS_DIR, False)):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".html") or name.startswith("_"):
                continue
            path = os.path.join(base, name)
            meta = _read_meta(path)
            if meta is None:
                continue
            did = name[:-5]
            found[did] = {
                "id": did,
                "name": meta.get("name", did.replace("-", " ").title()),
                "description": meta.get("description", ""),
                "tags": meta.get("tags", []),
                "category": meta.get("category", "Styling"),
                "order": meta.get("order", 100),
                "builtin": builtin,
                "path": path,
            }
    return sorted(found.values(), key=lambda d: (not d["builtin"], d["order"], d["name"]))


def design_path(design_id):
    for d in designs():
        if d["id"] == design_id:
            return d["path"]
    return os.path.join(DESIGNS_DIR, "classic.html")
