#!/bin/bash
# Install mint-lock for the current user (no root needed, except for missing packages).
#   ./install.sh            install, then ask whether Cinnamon should use it
#   ./install.sh --enable   install and switch Cinnamon over straight away
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/mint-lock/app"
BIN_DIR="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENABLE="${1:-}"

need=()
python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null || need+=(python3-gi gir1.2-gtk-3.0)
python3 -c 'import gi; gi.require_version("WebKit2", "4.1")' 2>/dev/null || need+=(gir1.2-webkit2-4.1)
python3 -c 'import PAM' 2>/dev/null || need+=(python3-pam)
python3 -c 'import Xlib' 2>/dev/null || need+=(python3-xlib)
if ((${#need[@]})); then
  echo "mint-lock needs: ${need[*]}"
  echo "Installing them with apt (asks for your password)..."
  sudo apt-get install -y "${need[@]}"
fi

if [[ "${XDG_SESSION_TYPE:-x11}" != "x11" ]]; then
  echo "Warning: this is a ${XDG_SESSION_TYPE} session. mint-lock is built for Cinnamon on X11." >&2
fi

echo "Installing to $DEST"
rm -rf "$DEST"
mkdir -p "$DEST" "$BIN_DIR" "$APPS"
cp -r "$SRC/bin" "$SRC/mintlock" "$SRC/web" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
chmod +x "$DEST/bin/mint-lock" "$DEST/mintlock/authhelper.py"
ln -sfn "$DEST/bin/mint-lock" "$BIN_DIR/mint-lock"
sed "s|@BIN@|$DEST/bin/mint-lock|" "$SRC/extras/mint-lock-explorer.desktop" > "$APPS/mint-lock-explorer.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo
echo "Installed. Try a design safely first (a normal window, nothing is locked):"
echo "    mint-lock lock --test"
echo "Pick a design:  mint-lock explore   (or 'Lock Screen Explorer' in the menu)"
echo

if [[ "$ENABLE" == "--enable" ]]; then
  "$DEST/bin/mint-lock" enable
elif [[ -t 0 ]]; then
  read -r -p "Make Cinnamon lock with mint-lock now? [y/N] " ans
  if [[ "$ans" =~ ^[Yy] ]]; then "$DEST/bin/mint-lock" enable; else echo "Later: mint-lock enable"; fi
fi
