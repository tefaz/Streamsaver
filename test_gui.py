import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt, QSettings, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
from PyQt6.QtTest import QTest

from main import HistoryEntry, MainWindow
from downloader import VideoInfo


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_quality_buttons_keep_their_resolution_values(self):
        window = MainWindow()
        window._set_qualities((2160, 1080, 720, 480, 240, 144))
        values = {button.text(): button.property("qualityHeight")
                  for button in window.qualities.buttons()}
        self.assertNotIn("Best", values)
        self.assertNotIn("2160p", values)
        self.assertEqual(values["1080p"], 1080)
        self.assertEqual(values["240p"], 240)
        self.assertEqual(window.qualities.checkedButton().text(), "1080p")

    def test_status_text_can_be_selected_and_copied(self):
        window = MainWindow()
        flags = window.status.textInteractionFlags()
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByMouse)
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByKeyboard)

    def test_valid_url_schedules_automatic_lookup_without_find_button(self):
        window = MainWindow()
        button_texts = {button.text() for button in window.findChildren(QPushButton)}
        self.assertNotIn("Find video", button_texts)

        window.url.setText("not a url")
        self.assertFalse(window.lookup_timer.isActive())
        window.url.setText("https://example.com/video")
        self.assertTrue(window.lookup_timer.isActive())
        window.lookup_timer.stop()

    def test_success_history_persists_thumbnail_and_clear_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = str(Path(tmp) / "settings.ini")
            settings = QSettings(settings_path, QSettings.Format.IniFormat)
            window = MainWindow(settings)
            info = VideoInfo("Example title", "Creator", 60,
                             "https://example.com/thumb.png", (720,), "https://example.com/video")
            window.info = info
            window.download_info = info
            pixmap = QPixmap(160, 90)
            pixmap.fill(Qt.GlobalColor.green)
            window.thumbnail.setPixmap(pixmap)
            window._download_done(True, "")
            self.assertEqual(len(window.history), 1)
            self.assertTrue(window.history[0]["image"])
            window.download_info = info
            window._download_done(False, "Cancelled")
            self.assertEqual(len(window.history), 1)
            reopened = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
            self.assertEqual(reopened.history, window.history)
            self.assertEqual(reopened.history[0]["title"], info.title)
            self.assertEqual(reopened.history[0]["url"], info.webpage_url)
            media = Path(tmp) / "video.mp4"
            media.touch()
            reopened.clear_history()
            QTest.qWait(1)
            self.assertTrue(media.exists())
            fresh = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
            self.assertEqual(fresh.history, [])
            self.assertFalse(fresh.clear_history_button.isEnabled())
            self.assertEqual(reopened.history_scroll.verticalScrollBar().value(), 0)
            for item in (window, reopened, fresh):
                item.close()

    def test_history_copy_button_copies_the_full_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            window = MainWindow(settings)
            url = "https://example.com/a-video?with=the-full-url"
            window.history = [{"title": "Example", "url": url, "thumbnail": "", "image": ""}]
            window._render_history()
            copy_button = next(button for button in window.findChildren(QPushButton)
                               if button.objectName() == "historyUrl")
            copy_button.click()
            self.assertEqual(QApplication.clipboard().text(), url)
            window.close()

    def test_clicking_a_history_entry_opens_its_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            window = MainWindow(settings)
            url = "https://example.com/a-video"
            window.history = [{"title": "Example", "url": url, "thumbnail": "", "image": ""}]
            window._render_history()
            card = window.findChild(HistoryEntry)
            title = window.findChild(QLabel, "historyTitle")
            with patch("main.QDesktopServices.openUrl") as open_url:
                QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
                QTest.mouseClick(title, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
            self.assertEqual(open_url.call_count, 2)
            open_url.assert_called_with(QUrl(url))
            window.close()


if __name__ == "__main__":
    unittest.main()
