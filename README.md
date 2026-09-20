# StreamSaver

A native Qt desktop app for downloading the main video at a URL as an MP4 at a chosen quality, or extracting it as a high-quality MP3. Site support is provided by `yt-dlp`; FFmpeg handles merging and conversion.

## Install on CachyOS / Arch

```bash
sudo pacman -S python-pyqt6 yt-dlp ffmpeg
chmod +x install.sh streamsaver
./install.sh
```

Launch **StreamSaver** from Plasma's application launcher, or run `./streamsaver` from this folder.

## Notes

- Open **History** to see successful downloads, newest first, with their titles, URLs, and cached thumbnails when available. History is saved locally between sessions. **Clear history** removes these records and thumbnails without deleting downloaded files. Downloads made before this feature was added are not included.
- StreamSaver intentionally downloads only the main video, not playlists.
- Available resolutions are detected per video. “Best” uses the highest available quality.
- Downloaded filenames are cleaned of common presentation labels such as `[HD]`, `(Lyrics)`, `Official Video`, and resolution tags. Meaningful qualifiers such as live versions and remaster information are preserved.
- Some sites require authentication, DRM, or actively block download tools. DRM-protected media cannot be downloaded by this app.
- Only download media you are legally allowed to save, and respect each site's terms.

## Uninstall launcher

Remove `~/.local/bin/streamsaver`, `~/.local/share/applications/streamsaver.desktop`, and `~/.local/share/icons/hicolor/scalable/apps/streamsaver.svg`. The project folder itself is self-contained.
