from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


class DownloadError(RuntimeError):
    pass


MAX_MP4_HEIGHT = 1080


@dataclass(frozen=True)
class VideoInfo:
    title: str
    uploader: str
    duration: int | None
    thumbnail: str | None
    heights: tuple[int, ...]
    webpage_url: str


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DownloadError("Enter a complete http:// or https:// video URL.")
    return value


def find_program(name: str) -> str:
    program = shutil.which(name)
    if not program:
        raise DownloadError(f"Required program '{name}' was not found in PATH.")
    return program


def probe(url: str, timeout: int = 90) -> VideoInfo:
    url = validate_url(url)
    command = [
        find_program("yt-dlp"), "--dump-single-json", "--no-playlist",
        "--no-warnings", "--socket-timeout", "20", url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DownloadError("The site took too long to respond.") from exc
    if result.returncode:
        message = _last_error(result.stderr) or "Could not read this video page."
        raise DownloadError(message)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DownloadError("The site returned video information in an unexpected format.") from exc

    heights = sorted({
        int(f["height"]) for f in data.get("formats", [])
        if f.get("vcodec", "none") != "none" and f.get("height")
    }, reverse=True)
    return VideoInfo(
        title=data.get("title") or "Untitled video",
        uploader=data.get("uploader") or data.get("channel") or "Unknown creator",
        duration=int(data["duration"]) if data.get("duration") is not None else None,
        thumbnail=data.get("thumbnail"),
        heights=tuple(heights),
        webpage_url=data.get("webpage_url") or url,
    )


def build_command(url: str, destination: Path, mode: str, height: int | None = None) -> list[str]:
    url = validate_url(url)
    destination.mkdir(parents=True, exist_ok=True)
    output = str(destination / "%(title).180B.%(ext)s")
    base = [
        find_program("yt-dlp"), "--newline", "--no-quiet", "--no-playlist", "--no-overwrites",
        "--windows-filenames", "--progress-template",
        "download:progress:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--print", "after_move:filepath:%(filepath)s",
        "-o", output,
    ]
    if mode == "audio":
        find_program("ffmpeg")
        base += ["-x", "--audio-format", "mp3", "--audio-quality", "0",
                 "--embed-thumbnail", "--add-metadata"]
    else:
        find_program("ffmpeg")
        height = min(height or MAX_MP4_HEIGHT, MAX_MP4_HEIGHT)
        selector = (
            f"bestvideo[height<={height}][vcodec^=avc1][ext=mp4][protocol=https]"
            f"+bestaudio[ext=m4a][protocol=https]/"
            f"bestvideo[height<={height}][ext=mp4][protocol=https]"
            f"+bestaudio[ext=m4a][protocol=https]/"
            f"bestvideo[height<={height}][protocol=https]+bestaudio[protocol=https]/"
            f"bestvideo[height<={height}][protocol=https]+bestaudio/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]"
        )
        base += ["-f", selector, "--merge-output-format", "mp4", "--remux-video", "mp4",
                 "--embed-metadata"]
    return base + [url]


_DECORATION = re.compile(
    r"(?ix)"
    r"(?:\s*[-–—|:]?\s*)"
    r"(?:"
    r"[\[(]\s*(?:"
    r"official(?:\s+music)?\s+video|official\s+audio|"
    r"lyrics?|lyric\s+video|audio|music\s+video|video|visuali[sz]er|"
    r"(?:full\s+)?hd|uhd|[248]k|(?:720|1080|1440|2160|4320)p|"
    r"hq|high\s+quality"
    r")\s*[\])]"
    r"|(?:official(?:\s+music)?\s+video|official\s+audio|lyric\s+video|"
    r"official\s+lyrics?|official\s+visuali[sz]er)"
    r")"
)


def clean_media_filename(path: Path) -> Path:
    """Remove common non-title video labels without touching meaningful qualifiers."""
    cleaned = _DECORATION.sub(" ", path.stem)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ._-–—|")
    if not cleaned or cleaned == path.stem:
        return path

    target = path.with_name(cleaned + path.suffix)
    if target.exists():
        number = 2
        while target.with_name(f"{cleaned} ({number}){path.suffix}").exists():
            number += 1
        target = target.with_name(f"{cleaned} ({number}){path.suffix}")
    os.rename(path, target)
    return target


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _last_error(stderr: str) -> str:
    lines = [_ANSI.sub("", line).strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    line = next((x for x in reversed(lines) if "ERROR:" in x), lines[-1])
    return line.removeprefix("ERROR:").strip()


def read_download_process(
    process: subprocess.Popen[str],
    on_line: Callable[[str], None],
) -> tuple[int, str]:
    output_tail: list[str] = []
    assert process.stdout is not None
    for raw in process.stdout:
        line = _ANSI.sub("", raw).strip()
        if line:
            output_tail.append(line)
            output_tail = output_tail[-12:]
            on_line(line)
    code = process.wait()
    if not code:
        return code, ""
    error = _last_error("\n".join(x for x in output_tail if "ERROR:" in x))
    return code, error or (output_tail[-1] if output_tail else "yt-dlp exited without an error message.")
