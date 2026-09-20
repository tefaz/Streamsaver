#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 1; }
command -v yt-dlp >/dev/null || { echo "yt-dlp is required (CachyOS: sudo pacman -S yt-dlp)." >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "FFmpeg is required (CachyOS: sudo pacman -S ffmpeg)." >&2; exit 1; }
python3 -c 'import PyQt6' 2>/dev/null || { echo "PyQt6 is required (CachyOS: sudo pacman -S python-pyqt6)." >&2; exit 1; }

mkdir -p "$BIN_DIR" "$APPLICATIONS_DIR" "$ICON_DIR"
ln -sfn "$APP_DIR/streamsaver" "$BIN_DIR/streamsaver"
ln -sfn "$APP_DIR/streamsaver.svg" "$ICON_DIR/streamsaver.svg"
sed "s|@APP_DIR@|$APP_DIR|g" "$APP_DIR/streamsaver.desktop.in" > "$APPLICATIONS_DIR/streamsaver.desktop"
chmod +x "$APP_DIR/streamsaver" "$APPLICATIONS_DIR/streamsaver.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS_DIR" || true
echo "StreamSaver is installed. Find it in the Plasma application launcher."
