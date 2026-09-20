#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import base64
import re
import signal
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QObject, QPointF, QRunnable, QRectF, QSettings, Qt, QThreadPool, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QDockWidget, QMainWindow, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from downloader import (
    DownloadError, MAX_MP4_HEIGHT, VideoInfo, build_command, clean_media_filename, probe,
    read_download_process, validate_url,
)


class Signals(QObject):
    info = pyqtSignal(object)
    error = pyqtSignal(str)
    line = pyqtSignal(str)
    done = pyqtSignal(bool, str)


class ProbeTask(QRunnable):
    def __init__(self, url: str):
        super().__init__(); self.url = url; self.signals = Signals()

    def run(self):
        try: self.signals.info.emit(probe(self.url))
        except Exception as exc: self.signals.error.emit(str(exc))


class DownloadTask(QRunnable):
    def __init__(self, command: list[str]):
        super().__init__(); self.command = command; self.signals = Signals(); self.process = None; self.filepath = None

    def run(self):
        try:
            self.process = subprocess.Popen(self.command, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True,
                                            bufsize=1, start_new_session=True)
            def handle_line(line):
                if line.startswith("filepath:"):
                    self.filepath = line.removeprefix("filepath:")
                else:
                    self.signals.line.emit(line)

            code, error = read_download_process(self.process, handle_line)
            cleanup_warning = ""
            if code == 0 and self.filepath:
                try:
                    clean_media_filename(Path(self.filepath))
                except OSError as exc:
                    # The media was downloaded successfully. A failed optional rename
                    # must never turn that into a reported download failure.
                    cleanup_warning = f"Downloaded, but its filename could not be cleaned: {exc}"
            self.signals.done.emit(code == 0, error or cleanup_warning)
        except Exception as exc: self.signals.done.emit(False, str(exc))

    def cancel(self):
        if self.process and self.process.poll() is None:
            try: os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except ProcessLookupError: pass


class DropLineEdit(QLineEdit):
    def __init__(self):
        super().__init__(); self.setAcceptDrops(True)
        self.setPlaceholderText("Paste a video URL here…")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText(): event.acceptProposedAction()

    def dropEvent(self, event):
        text = event.mimeData().urls()[0].toString() if event.mimeData().hasUrls() else event.mimeData().text()
        self.setText(text.strip()); event.acceptProposedAction()


class Backdrop(QWidget):
    """A lightweight painted background that stays crisp at every window size."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base = QLinearGradient(0, 0, 0, self.height())
        base.setColorAt(0, QColor("#0b1020"))
        base.setColorAt(1, QColor("#090c14"))
        painter.fillRect(self.rect(), base)

        teal = QRadialGradient(QPointF(self.width() * .82, 25), self.width() * .6)
        teal.setColorAt(0, QColor(31, 211, 180, 38))
        teal.setColorAt(.55, QColor(20, 135, 126, 12))
        teal.setColorAt(1, QColor(9, 12, 20, 0))
        painter.fillRect(self.rect(), teal)

        violet = QRadialGradient(QPointF(0, self.height() * .66), self.width() * .55)
        violet.setColorAt(0, QColor(114, 83, 255, 25))
        violet.setColorAt(1, QColor(9, 12, 20, 0))
        painter.fillRect(self.rect(), violet)

        painter.setPen(QPen(QColor(255, 255, 255, 7), 1))
        spacing = 52
        for x in range(0, self.width(), spacing):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), spacing):
            painter.drawLine(0, y, self.width(), y)


class BrandMark(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(34, 34)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(3, 3, 31, 31)
        gradient.setColorAt(0, QColor("#66f3d1"))
        gradient.setColorAt(1, QColor("#37b8ff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(1, 1, 32, 32), 10, 10)
        arrow_pen = QPen(QColor("#07151a"), 2.4)
        arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        arrow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(arrow_pen)
        painter.drawLine(QPointF(17, 8), QPointF(17, 21))
        painter.drawLine(QPointF(11.5, 16), QPointF(17, 21.5))
        painter.drawLine(QPointF(22.5, 16), QPointF(17, 21.5))
        painter.drawLine(QPointF(10, 26), QPointF(24, 26))


class HistoryEntry(QFrame):
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_url()
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonRelease and
                event.button() == Qt.MouseButton.LeftButton):
            self._open_url()
            return True
        return super().eventFilter(watched, event)

    def _open_url(self):
        QDesktopServices.openUrl(QUrl(self.url))


class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("LocalApps", "StreamSaver")
        try:
            entries = json.loads(self.settings.value("download_history", "[]"))
            self.history = [entry for entry in entries if isinstance(entry, dict)
                            and all(isinstance(entry.get(key), str)
                                    for key in ("title", "url", "thumbnail", "image"))] if isinstance(entries, list) else []
        except (ValueError, TypeError):
            self.history = []
        self.download_info = None
        self.pool = QThreadPool.globalInstance(); self.info = None; self.task = None; self.probe_task = None
        self.thumbnail_manager = QNetworkAccessManager(self)
        self.thumbnail_generation = 0
        self.lookup_timer = QTimer(self)
        self.lookup_timer.setSingleShot(True)
        self.lookup_timer.setInterval(350)
        self.lookup_timer.timeout.connect(self.fetch_info)
        self.destination = Path(self.settings.value("destination", str(Path.home() / "Downloads")))
        self.setWindowTitle("StreamSaver")
        self.setMinimumSize(720, 580); self.resize(1240, 860)
        icon = Path(__file__).with_name("streamsaver.svg")
        if icon.exists(): self.setWindowIcon(QIcon(str(icon)))
        self._build(); self._build_history(); self._style()

    def _build(self):
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)

        root = Backdrop()
        root.setObjectName("root")
        root.setMinimumSize(680, 740)
        scroll.setWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(46, 32, 46, 34)
        outer.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(11)
        self.history_toggle = QPushButton("History")
        self.history_toggle.setCheckable(True)
        self.history_toggle.setObjectName("quiet")
        header.addWidget(self.history_toggle)
        header.addWidget(BrandMark())
        brand_stack = QVBoxLayout()
        brand_stack.setSpacing(0)
        brand = QLabel("STREAMSAVER")
        brand.setObjectName("brand")
        brand_note = QLabel("MEDIA, MINUS THE FUSS")
        brand_note.setObjectName("brandNote")
        brand_stack.addWidget(brand)
        brand_stack.addWidget(brand_note)
        header.addLayout(brand_stack)
        header.addStretch()
        privacy = QLabel("●  RUNS LOCALLY")
        privacy.setObjectName("privacy")
        header.addWidget(privacy)
        outer.addLayout(header)

        hero = QVBoxLayout()
        hero.setSpacing(5)
        title = QLabel("Bring your favorites offline.")
        title.setObjectName("title")
        subtitle = QLabel("Drop in a link. Choose your format. StreamSaver handles the rest.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        hero.addWidget(title)
        hero.addWidget(subtitle)
        outer.addLayout(hero)

        link_panel = QFrame()
        link_panel.setObjectName("linkPanel")
        link_layout = QVBoxLayout(link_panel)
        link_layout.setContentsMargins(18, 15, 18, 18)
        link_layout.setSpacing(10)
        link_head = QHBoxLayout()
        link_head.addWidget(self._step_label("01", "PASTE A LINK"))
        link_head.addStretch()
        hint = QLabel("YouTube + hundreds more")
        hint.setObjectName("hint")
        link_head.addWidget(hint)
        link_layout.addLayout(link_head)
        row = QHBoxLayout()
        row.setSpacing(9)
        self.url = DropLineEdit()
        self.url.setClearButtonEnabled(True)
        self.paste = QPushButton("Paste")
        self.paste.setObjectName("quiet")
        self.paste.clicked.connect(self.paste_url)
        self.url.returnPressed.connect(self.fetch_info)
        self.url.textChanged.connect(self._url_changed)
        row.addWidget(self.url, 1)
        row.addWidget(self.paste)
        link_layout.addLayout(row)
        outer.addWidget(link_panel)

        self.card = QFrame()
        self.card.setObjectName("card")
        card = QVBoxLayout(self.card)
        card.setContentsMargins(20, 18, 20, 18)
        card.setSpacing(13)

        media_head = QHBoxLayout()
        media_head.setSpacing(14)
        self.thumbnail = QLabel()
        self.thumbnail.setObjectName("thumbnail")
        self.thumbnail.setFixedSize(160, 90)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.hide()
        media_head.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignTop)
        media_copy = QVBoxLayout()
        media_copy.setSpacing(3)
        self.video_title = QLabel("Ready when you are")
        self.video_title.setObjectName("videoTitle")
        self.video_title.setWordWrap(True)
        self.meta = QLabel("Your video details and available qualities will appear here.")
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        media_copy.addWidget(self.video_title)
        media_copy.addWidget(self.meta)
        media_head.addLayout(media_copy, 1)
        self.ready_badge = QLabel("WAITING")
        self.ready_badge.setObjectName("readyBadge")
        self.ready_badge.setProperty("ready", False)
        media_head.addWidget(self.ready_badge, 0, Qt.AlignmentFlag.AlignTop)
        card.addLayout(media_head)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        card.addWidget(divider)

        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(self._step_label("02", "CHOOSE FORMAT"))
        type_row.addStretch()
        self.mp4 = QRadioButton("MP4  ·  Video")
        self.mp3 = QRadioButton("MP3  ·  Audio")
        for choice in (self.mp4, self.mp3):
            choice.setObjectName("formatChoice")
            choice.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mp4.setChecked(True)
        self.types = QButtonGroup(self)
        self.types.addButton(self.mp4)
        self.types.addButton(self.mp3)
        self.mp4.toggled.connect(self._show_qualities)
        type_row.addWidget(self.mp4)
        type_row.addWidget(self.mp3)
        card.addLayout(type_row)

        self.quality_area = QScrollArea()
        self.quality_area.setObjectName("qualityArea")
        self.quality_area.setWidgetResizable(True)
        self.quality_area.setFrameShape(QFrame.Shape.NoFrame)
        self.quality_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.quality_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.quality_area.setFixedHeight(50)
        self.quality_box = QWidget()
        self.quality_box.setObjectName("qualityBox")
        self.quality_row = QHBoxLayout(self.quality_box)
        self.quality_row.setContentsMargins(0, 3, 0, 5)
        self.quality_row.setSpacing(8)
        self.quality_area.setWidget(self.quality_box)
        self.qualities = QButtonGroup(self)
        self._set_qualities(())
        card.addWidget(self.quality_area)
        outer.addWidget(self.card)

        destination = QFrame()
        destination.setObjectName("destination")
        folder_row = QHBoxLayout(destination)
        folder_row.setContentsMargins(18, 14, 18, 14)
        folder_row.setSpacing(9)
        folder_text = QVBoxLayout()
        folder_text.setSpacing(3)
        folder_text.addWidget(self._step_label("03", "SAVE LOCATION"))
        self.folder = QLabel(str(self.destination))
        self.folder.setObjectName("folder")
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder_text.addWidget(self.folder)
        self.choose = QPushButton("Choose folder")
        self.choose.clicked.connect(self.choose_folder)
        open_btn = QPushButton("Open")
        open_btn.setObjectName("quiet")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.destination))))
        folder_row.addLayout(folder_text, 1)
        folder_row.addWidget(open_btn)
        folder_row.addWidget(self.choose)
        outer.addWidget(destination)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status.hide()
        outer.addWidget(self.progress)
        outer.addWidget(self.status)
        action = QHBoxLayout()
        action.addStretch()
        self.cancel = QPushButton("Cancel")
        self.cancel.hide()
        self.cancel.clicked.connect(self.cancel_download)
        self.download = QPushButton("Download now")
        self.download.setObjectName("downloadButton")
        self.download.setEnabled(False)
        self.download.clicked.connect(self.start_download)
        action.addWidget(self.cancel)
        action.addWidget(self.download)
        outer.addLayout(action)
        outer.addStretch()

        for button in root.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _build_history(self):
        self.history_dock = QDockWidget("Download history", self)
        self.history_dock.setObjectName("historyDock")
        self.history_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.history_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.history_dock.setMinimumWidth(280)
        self.history_dock.setMaximumWidth(350)
        panel = QWidget()
        panel.setObjectName("historyPanel")
        layout = QVBoxLayout(panel)
        self.clear_history_button = QPushButton("Clear history")
        self.clear_history_button.setToolTip("Remove all history entries. Downloaded files are kept.")
        self.clear_history_button.clicked.connect(self.clear_history)
        layout.addWidget(self.clear_history_button)
        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("historyScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        contents = QWidget()
        contents.setObjectName("historyContents")
        self.history_layout = QVBoxLayout(contents)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_scroll.setWidget(contents)
        layout.addWidget(self.history_scroll)
        self.history_dock.setWidget(panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.history_dock)
        self.resizeDocks([self.history_dock], [290], Qt.Orientation.Horizontal)
        self.history_toggle.toggled.connect(self.history_dock.setVisible)
        self.history_dock.visibilityChanged.connect(self.history_toggle.setChecked)
        self.history_toggle.setChecked(True)
        self._render_history()

    def _render_history(self):
        while self.history_layout.count():
            widget = self.history_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        self.clear_history_button.setEnabled(bool(self.history))
        if not self.history:
            empty = QLabel("No downloads yet.\nSuccessful downloads will appear here.")
            empty.setObjectName("historyEmpty")
            empty.setWordWrap(True)
            empty.setMinimumHeight(80)
            self.history_layout.addWidget(empty)
        for entry in self.history:
            card = HistoryEntry(entry["url"])
            layout = QVBoxLayout(card)
            pixmap = QPixmap()
            try:
                pixmap.loadFromData(base64.b64decode(entry["image"]))
            except ValueError:
                pass
            if not pixmap.isNull():
                thumbnail = QLabel()
                thumbnail.setPixmap(pixmap.scaled(220, 124, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
                thumbnail.installEventFilter(card)
                layout.addWidget(thumbnail)
            title = QLabel(entry["title"])
            title.setObjectName("historyTitle")
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            title.installEventFilter(card)
            layout.addWidget(title)
            copy_url = QPushButton("Copy URL")
            copy_url.setObjectName("historyUrl")
            copy_url.setToolTip(entry["url"])
            copy_url.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_url.clicked.connect(lambda checked=False, url=entry["url"]: self._copy_history_url(url))
            layout.addWidget(copy_url)
            self.history_layout.addWidget(card)
        self.history_scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, lambda: self.history_scroll.verticalScrollBar().setValue(0))

    @staticmethod
    def _copy_history_url(url: str):
        QApplication.clipboard().setText(url)

    def _save_history(self):
        self.settings.setValue("download_history", json.dumps(self.history))
        self.settings.sync()
        self._render_history()
        return self.settings.status() == QSettings.Status.NoError

    def clear_history(self):
        self.history.clear()
        if not self._save_history():
            self._set_status("Could not clear saved history. Check your settings folder permissions.", "error")

    def _record_download(self):
        info = self.download_info
        if info is None:
            return True
        image = self._thumbnail_image()
        self.history.insert(0, {"title": info.title, "url": info.webpage_url,
                                "thumbnail": info.thumbnail or "", "image": image})
        return self._save_history()

    def _thumbnail_image(self):
        pixmap = self.thumbnail.pixmap()
        if pixmap is not None and not pixmap.isNull():
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            return base64.b64encode(bytes(data)).decode("ascii")
        return ""

    @staticmethod
    def _step_label(number: str, text: str) -> QWidget:
        widget = QWidget()
        widget.setObjectName("step")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        badge = QLabel(number)
        badge.setObjectName("stepNumber")
        label = QLabel(text)
        label.setObjectName("section")
        layout.addWidget(badge)
        layout.addWidget(label)
        return widget

    def _style(self):
        self.setStyleSheet("""
        QMainWindow { background: #090c14; }
        QWidget { color: #eaf0fa; font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 14px; }
        QDockWidget#historyDock { background: #0b1020; color: #dce6f5; border-right: 1px solid #273249; }
        QDockWidget#historyDock::title { background: #111827; color: #dce6f5; border-bottom: 1px solid #273249; padding: 11px 12px; font-size: 12px; font-weight: 800; }
        QDockWidget#historyDock::close-button { background: #202a3c; border: 1px solid #35435b; border-radius: 6px; }
        QWidget#historyPanel, QScrollArea#historyScroll, QScrollArea#historyScroll > QWidget > QWidget, QWidget#historyContents { background: #0b1020; }
        QScrollArea#historyScroll { border: none; }
        QLabel#historyEmpty { color: #8591a6; padding: 8px; }
        QLabel#historyTitle { color: #f2f6fc; font-weight: 700; }
        QPushButton#historyUrl { color: #9ecdbc; background: #101e28; border-color: #28594d; font-size: 11px; padding: 7px 9px; }
        QPushButton#historyUrl:hover { color: #d2f7e9; background: #15312e; border-color: #3f8d7b; }
        QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget { background: #090c14; }
        QWidget#root { background: transparent; }
        QLabel#brand { color: #f6fbff; font-weight: 800; letter-spacing: 2px; font-size: 13px; }
        QLabel#brandNote { color: #64728a; font-size: 8px; font-weight: 700; letter-spacing: 1px; }
        QLabel#privacy { color: #65e6c8; background: rgba(18, 48, 48, 170); border: 1px solid #244f4c; border-radius: 10px; padding: 6px 9px; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
        QLabel#title { font-size: 31px; font-weight: 750; color: #ffffff; }
        QLabel#subtitle { color: #8d99ad; font-size: 14px; }
        QLabel#hint { color: #6f7b91; font-size: 11px; }
        QLabel#videoTitle { color: #f7f9fd; font-size: 18px; font-weight: 700; }
        QLabel#thumbnail { background: #0b111d; border: 1px solid #2b374b; border-radius: 9px; }
        QLabel#muted { color: #8591a6; font-size: 13px; }
        QLabel#section { color: #a7b3c7; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
        QLabel#stepNumber { color: #5de4c7; background: #16332f; border: 1px solid #25554e; border-radius: 9px; min-width: 18px; min-height: 18px; max-width: 18px; max-height: 18px; qproperty-alignment: AlignCenter; font-size: 8px; font-weight: 900; }
        QLabel#folder { color: #d4dbea; font-size: 12px; }
        QLabel#readyBadge { color: #7c899f; background: #141c2a; border: 1px solid #2a3547; border-radius: 9px; padding: 5px 8px; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
        QLabel#readyBadge[ready="true"] { color: #62e6c8; background: #123029; border-color: #28594d; }
        QLabel#status[statusState="working"] { color: #b7c8df; background: rgba(20, 32, 50, 220); border: 1px solid #31415a; border-radius: 10px; padding: 10px 12px; }
        QLabel#status[statusState="success"] { color: #7ee6c4; background: rgba(15, 43, 35, 230); border: 1px solid #285e4e; border-radius: 10px; padding: 10px 12px; }
        QLabel#status[statusState="error"] { color: #ffabb7; background: rgba(51, 23, 32, 230); border: 1px solid #713344; border-radius: 10px; padding: 10px 12px; }
        QFrame#linkPanel, QFrame#card, QFrame#destination { background: rgba(17, 24, 39, 235); border: 1px solid #273249; border-radius: 14px; }
        QFrame#linkPanel { border-color: #30415b; }
        QFrame#divider { color: #263146; background: #263146; border: none; max-height: 1px; }
        QLineEdit { min-height: 20px; background: #0c1220; border: 1px solid #35435c; border-radius: 9px; padding: 10px 13px; selection-background-color: #32bca4; }
        QLineEdit:hover { border-color: #4a5a75; }
        QLineEdit:focus { border: 1px solid #56dfc2; background: #0d1523; }
        QPushButton { min-height: 20px; background: #202a3c; border: 1px solid #35435b; border-radius: 9px; padding: 9px 15px; font-weight: 650; }
        QPushButton:hover { background: #2a364b; border-color: #50617c; }
        QPushButton:pressed { background: #182131; }
        QPushButton:disabled { color: #5f6b7e; background: #161d2a; border-color: #252e3e; }
        QPushButton#quiet { color: #abb6c8; background: transparent; }
        QPushButton#quiet:hover { color: #eef5ff; background: #202a3a; }
        QPushButton#primary, QPushButton#downloadButton { color: #061916; background: #59e1c3; border: 1px solid #74eed4; font-weight: 800; }
        QPushButton#primary:hover, QPushButton#downloadButton:hover { background: #78edd4; border-color: #9af5e1; }
        QPushButton#primary:pressed, QPushButton#downloadButton:pressed { background: #43c8ab; }
        QPushButton#primary:disabled, QPushButton#downloadButton:disabled { color: #657279; background: #202a32; border-color: #303c48; }
        QPushButton#downloadButton { min-width: 142px; padding: 11px 22px; }
        QRadioButton#formatChoice { color: #a8b3c6; background: #111827; border: 1px solid #2d394e; border-radius: 9px; padding: 8px 12px; font-weight: 650; }
        QRadioButton#formatChoice:hover { color: #eaf1fb; border-color: #4b5b74; }
        QRadioButton#formatChoice:checked { color: #071b17; background: #5de4c7; border-color: #70ecd1; }
        QRadioButton#formatChoice:disabled { color: #687487; background: #151d2a; border-color: #273247; }
        QRadioButton#formatChoice::indicator, QRadioButton#qualityChoice::indicator { width: 0; height: 0; }
        QRadioButton#qualityChoice { color: #94a0b4; background: #101724; border: 1px solid #2b3548; border-radius: 8px; padding: 7px 13px; font-size: 12px; font-weight: 650; }
        QRadioButton#qualityChoice:hover { color: #e6edf8; border-color: #4b5c76; }
        QRadioButton#qualityChoice:checked { color: #76ead0; background: #15312e; border-color: #347264; }
        QRadioButton#qualityChoice:disabled { color: #5e697b; background: #141b27; border-color: #252f40; }
        QProgressBar { background: #1b2433; border: 1px solid #29364a; border-radius: 5px; min-height: 8px; max-height: 8px; text-align: center; color: transparent; }
        QProgressBar::chunk { background: #59e1c3; border-radius: 4px; }
        QScrollArea#qualityArea, QWidget#qualityBox, QScrollArea#qualityArea > QWidget > QWidget { background: transparent; border: none; }
        QScrollBar:horizontal { background: transparent; height: 3px; margin: 0; }
        QScrollBar::handle:horizontal { background: #35445c; border-radius: 1px; min-width: 30px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QScrollBar:vertical { background: #0c111b; width: 8px; }
        QScrollBar::handle:vertical { background: #344057; border-radius: 4px; min-height: 32px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    def fetch_info(self):
        if not self.url.text().strip() or self.probe_task or self.task:
            return
        self.lookup_timer.stop()
        try:
            url = validate_url(self.url.text())
        except DownloadError:
            return
        self.url.setReadOnly(True)
        self.paste.setEnabled(False)
        self.download.setEnabled(False)
        self._clear_thumbnail()
        self._set_ready(False, "CHECKING")
        self.video_title.setText("Reading video page…")
        self.meta.setText("This usually takes only a few seconds.")
        self.probe_task = ProbeTask(url)
        self.probe_task.signals.info.connect(self._info_ready)
        self.probe_task.signals.error.connect(self._probe_error)
        self.pool.start(self.probe_task)

    def _info_ready(self, info: VideoInfo):
        self.probe_task = None
        self.info = info
        self.video_title.setText(info.title)
        duration = f" • {info.duration // 60}:{info.duration % 60:02d}" if info.duration else ""
        self.meta.setText(f"{info.uploader}{duration}")
        self.url.setReadOnly(False)
        self.paste.setEnabled(True)
        self._load_thumbnail(info.thumbnail)
        self._set_qualities(info.heights)
        self._set_ready(True, "READY")
        self.download.setEnabled(True)

    def _probe_error(self, message):
        self.probe_task = None
        self.url.setReadOnly(False)
        self.paste.setEnabled(True)
        self._clear_thumbnail()
        self.video_title.setText("Couldn’t read this video")
        self.meta.setText(message)
        self._set_ready(False, "NOT FOUND")
        self.download.setEnabled(False)

    def _set_qualities(self, heights):
        while self.quality_row.count():
            item = self.quality_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.qualities = QButtonGroup(self)
        self.qualities.setExclusive(True)
        quality_label = QLabel("QUALITY")
        quality_label.setObjectName("section")
        self.quality_row.addWidget(quality_label)
        available_heights = sorted({h for h in heights if h <= MAX_MP4_HEIGHT}, reverse=True)
        for index, h in enumerate(available_heights[:8]):
            radio = QRadioButton(f"{h}p")
            radio.setObjectName("qualityChoice")
            radio.setProperty("qualityHeight", h)
            radio.setChecked(index == 0)
            radio.setCursor(Qt.CursorShape.PointingHandCursor)
            self.qualities.addButton(radio)
            self.quality_row.addWidget(radio)
        self.quality_row.addStretch()

    def _show_qualities(self, video):
        self.quality_area.setVisible(video)

    def _set_ready(self, ready: bool, text: str):
        self.ready_badge.setText(text)
        self.ready_badge.setProperty("ready", ready)
        self.ready_badge.style().unpolish(self.ready_badge)
        self.ready_badge.style().polish(self.ready_badge)

    def _url_changed(self):
        if self.probe_task or self.task:
            return
        self.lookup_timer.stop()
        self.info = None
        self.download.setEnabled(False)
        self._clear_thumbnail()
        self.video_title.setText("Ready when you are")
        self.meta.setText("Your video details and available qualities will appear here.")
        self._set_ready(False, "WAITING")
        self._set_qualities(())
        self.status.hide()
        self.progress.hide()
        try:
            validate_url(self.url.text())
        except DownloadError:
            return
        self.lookup_timer.start()

    def paste_url(self):
        text = QApplication.clipboard().text().strip()
        if text:
            self.url.setText(text)
            self.url.setFocus()
            self.fetch_info()

    def _clear_thumbnail(self):
        self.thumbnail_generation += 1
        self.thumbnail.clear()
        self.thumbnail.hide()

    def _load_thumbnail(self, url: str | None):
        self._clear_thumbnail()
        if not url:
            return
        generation = self.thumbnail_generation
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        reply = self.thumbnail_manager.get(request)
        reply.finished.connect(lambda: self._thumbnail_ready(reply, generation))

    def _thumbnail_ready(self, reply: QNetworkReply, generation: int):
        try:
            if (generation != self.thumbnail_generation or
                    reply.error() != QNetworkReply.NetworkError.NoError):
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                return
            pixmap = pixmap.scaled(
                self.thumbnail.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail.setPixmap(pixmap)
            self.thumbnail.show()
            # A small download can finish before its thumbnail request does.
            changed = False
            if self.info:
                for entry in self.history:
                    if (entry["url"] == self.info.webpage_url and not entry["image"]
                            and entry["thumbnail"] == self.info.thumbnail):
                        entry["image"] = self._thumbnail_image()
                        changed = True
            if changed:
                self._save_history()
        finally:
            reply.deleteLater()

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose download folder", str(self.destination))
        if chosen:
            self.destination = Path(chosen)
            self.folder.setText(chosen)
            self.settings.setValue("destination", chosen)

    def start_download(self):
        try:
            selected = self.qualities.checkedButton()
            value = selected.property("qualityHeight") if selected else MAX_MP4_HEIGHT
            height = int(value) if self.mp4.isChecked() else None
            command = build_command(self.url.text(), self.destination, "video" if self.mp4.isChecked() else "audio", height)
        except DownloadError as exc:
            self._set_status(str(exc), "error"); return
        self.task = DownloadTask(command)
        self.download_info = self.info
        self.task.signals.line.connect(self._progress_line)
        self.task.signals.done.connect(self._download_done)
        self.progress.setValue(0)
        self.progress.show()
        self._set_status("Starting download…", "working")
        self._set_inputs_enabled(False)
        self.download.setEnabled(False)
        self.cancel.show()
        self.pool.start(self.task)

    def _progress_line(self, line):
        if line.startswith("progress:"):
            parts = line[9:].split("|"); match = re.search(r"([\d.]+)%", parts[0])
            if match: self.progress.setValue(int(float(match.group(1))))
            details = " • ".join(x.strip() for x in parts[1:] if x.strip() not in {"N/A", "Unknown"})
            self._set_status("Downloading" + (f" • {details}" if details else "…"), "working")
        elif "Merging formats" in line: self._set_status("Merging audio and video…", "working")
        elif "ExtractAudio" in line: self._set_status("Converting to MP3…", "working")

    def cancel_download(self):
        if self.task: self.task.cancel(); self._set_status("Cancelling…", "working")

    def _download_done(self, success, error):
        self.cancel.hide()
        self._set_inputs_enabled(True)
        self.download.setEnabled(True)
        self.task = None
        if success:
            self.progress.setValue(100)
            message = error or f"Finished — saved to {self.destination}"
            if not self._record_download():
                message += " — History could not be saved."
            self._set_status(message, "success")
        else:
            message = error or "Download cancelled, or the site rejected the request."
            self._set_status(f"Download failed — {message}", "error")
        self.download_info = None

    def _set_inputs_enabled(self, enabled: bool):
        self.url.setReadOnly(not enabled)
        self.paste.setEnabled(enabled)
        self.choose.setEnabled(enabled)
        self.mp4.setEnabled(enabled)
        self.mp3.setEnabled(enabled)
        for button in self.qualities.buttons():
            button.setEnabled(enabled)

    def _set_status(self, message, state):
        self.status.setText(message)
        self.status.setProperty("statusState", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.show()

    def closeEvent(self, event):
        if self.task: self.task.cancel()
        event.accept()


def main():
    app = QApplication(sys.argv); app.setApplicationName("StreamSaver"); app.setStyle("Fusion")
    window = MainWindow(); window.show(); return app.exec()


if __name__ == "__main__": raise SystemExit(main())
