#!/usr/bin/env bash
# Registers dosview in the desktop application menu (Linux only).
#
# Not run automatically by `pip install` — desktop integration needs to
# write outside the Python environment (/usr/local/share/...), which pip
# installs should not do implicitly. Run this manually, after installing
# dosview, if you want a menu entry and icon:
#
#   sudo ./tools/install_desktop_entry.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
applications_dir="/usr/local/share/applications"
icons_dir="/usr/local/share/icons"

install -Dm644 "$repo_root/dosview.desktop" "$applications_dir/dosview.desktop"
install -Dm644 "$repo_root/media/icon_ust.png" "$icons_dir/icon_ust.png"

echo "Installed $applications_dir/dosview.desktop and $icons_dir/icon_ust.png"
