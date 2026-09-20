import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from downloader import DownloadError, build_command, clean_media_filename, validate_url


class DownloaderTests(unittest.TestCase):
    def test_url_validation(self):
        self.assertEqual(validate_url(" https://example.com/v/1 "), "https://example.com/v/1")
        for value in ("", "example.com/video", "file:///tmp/video"):
            with self.assertRaises(DownloadError): validate_url(value)

    @patch("downloader.find_program", side_effect=lambda name: f"/usr/bin/{name}")
    def test_video_command_limits_height_and_mp4(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = build_command("https://example.com/v", Path(tmp), "video", 1080)
        selector = cmd[cmd.index("-f") + 1]
        self.assertTrue(selector.startswith(
            "bestvideo[height<=1080][vcodec^=avc1][ext=mp4][protocol=https]"
            "+bestaudio[ext=m4a][protocol=https]/"
        ))
        self.assertIn("bestvideo[height<=1080]+bestaudio", selector)
        self.assertNotIn("--embed-thumbnail", cmd)
        self.assertIn("--no-quiet", cmd)
        self.assertEqual(cmd[-1], "https://example.com/v")
        self.assertIn("mp4", cmd)
        template = cmd[cmd.index("-o") + 1]
        self.assertIn("%(title).180B.%(ext)s", template)
        self.assertNotIn("%(id)s", template)

    @patch("downloader.find_program", side_effect=lambda name: f"/usr/bin/{name}")
    def test_audio_command_extracts_mp3(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = build_command("https://example.com/v", Path(tmp), "audio")
        self.assertIn("--audio-format", cmd); self.assertIn("mp3", cmd)
        self.assertNotIn("--merge-output-format", cmd)

    @patch("downloader.find_program", side_effect=lambda name: f"/usr/bin/{name}")
    def test_default_video_quality_is_capped_at_1080p(self, _):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = build_command("https://example.com/v", Path(tmp), "video")
        selector = cmd[cmd.index("-f") + 1]
        self.assertTrue(selector.startswith(
            "bestvideo[height<=1080][vcodec^=avc1][ext=mp4][protocol=https]"
            "+bestaudio[ext=m4a][protocol=https]/"
        ))
        self.assertTrue(selector.endswith("best[height<=1080]"))

    def test_filename_cleanup_removes_video_decorations(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Artist - Song (Lyrics) [HD] [1080p].mp4"
            source.touch()
            result = clean_media_filename(source)
            self.assertEqual(result.name, "Artist - Song.mp4")
            self.assertTrue(result.exists())

    def test_filename_cleanup_keeps_meaningful_qualifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Song (Live) [2024 Remaster].mp3"
            source.touch()
            result = clean_media_filename(source)
            self.assertEqual(result, source)

    def test_filename_cleanup_avoids_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Song [HD].mp4"
            existing = Path(tmp) / "Song.mp4"
            source.touch(); existing.touch()
            result = clean_media_filename(source)
            self.assertEqual(result.name, "Song (2).mp4")


if __name__ == "__main__": unittest.main()
