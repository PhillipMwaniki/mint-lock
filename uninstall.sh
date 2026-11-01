#!/bin/bash
# Remove mint-lock and hand locking back to Cinnamon. Your settings in
# ~/.config/mint-lock and designs in ~/.local/share/mint-lock/designs are kept
# unless you pass --purge.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

if gsettings get org.cinnamon.desktop.screensaver custom-screensaver-command 2>/dev/null | grep -q mint-lock; then
  gsettings reset org.cinnamon.desktop.screensaver custom-screensaver-command
  echo "Cinnamon is back on its own lock screen."
fi
rm -rf "$DATA/mint-lock/app"
rm -f "$DATA/mint-lock/lib"
rm -f "$HOME/.local/bin/mint-lock" "$DATA/applications/mint-lock-explorer.desktop"
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$DATA/mint-lock" "${XDG_CONFIG_HOME:-$HOME/.config}/mint-lock"
  echo "Settings and your designs removed."
fi
echo "mint-lock removed."
