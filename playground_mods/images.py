from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict, deque
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .paths import IMAGE_DIR, ensure_dirs
from .sources import USER_AGENT

log = logging.getLogger(__name__)

# Covers are never displayed larger than a details dialog, so keeping the full
# original in memory just wastes RAM (a 4K cover is ~33 MB as a QPixmap).
_MAX_MEMORY_DIMENSION = 720
_MAX_MEMORY_ITEMS = 160


class ImageLoader(QObject):
    """Asynchronous, disk-cached cover image loader with bounded concurrency."""

    ready = Signal(str, QPixmap)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None, limit: int = 5) -> None:
        super().__init__(parent)
        ensure_dirs()
        self._manager = QNetworkAccessManager(self)
        self._manager.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )
        self._limit = limit
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self._active: dict[str, QNetworkReply] = {}
        self._memory: OrderedDict[str, QPixmap] = OrderedDict()

    def load(self, url: str) -> None:
        if not url:
            self.failed.emit(url)
            return
        cached = self._memory.get(url)
        if cached is not None:
            self._memory.move_to_end(url)
            QTimer.singleShot(0, lambda: self.ready.emit(url, cached))
            return
        disk = self._disk_path(url)
        if disk.is_file():
            pixmap = QPixmap()
            if pixmap.loadFromData(disk.read_bytes()) and not pixmap.isNull():
                pixmap = self._remember(url, pixmap)
                QTimer.singleShot(0, lambda: self.ready.emit(url, pixmap))
                return
            try:
                disk.unlink()
            except OSError:
                pass
        if url in self._queued:
            return
        self._queued.add(url)
        self._queue.append(url)
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._active) < self._limit:
            url = self._queue.popleft()
            request = QNetworkRequest(QUrl(url))
            request.setHeader(
                QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT
            )
            request.setAttribute(
                QNetworkRequest.Attribute.CacheLoadControlAttribute,
                QNetworkRequest.CacheLoadControl.PreferCache,
            )
            reply = self._manager.get(request)
            reply.setParent(self)
            self._active[url] = reply
            reply.finished.connect(lambda url=url, reply=reply: self._done(url, reply))

    def _done(self, url: str, reply: QNetworkReply) -> None:
        self._active.pop(url, None)
        self._queued.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                log.info("Image failed (%s): %s", reply.errorString(), url)
                self.failed.emit(url)
                return
            data = bytes(reply.readAll())
            pixmap = QPixmap()
            if not data or not pixmap.loadFromData(data) or pixmap.isNull():
                self.failed.emit(url)
                return
            pixmap = self._remember(url, pixmap)
            try:
                # Keep the original bytes on disk so a future run can decode at
                # full quality; only the in-memory copy is downscaled.
                self._disk_path(url).write_bytes(data)
            except OSError as exc:
                log.info("Could not cache image: %s", exc)
            self.ready.emit(url, pixmap)
        finally:
            reply.deleteLater()
            self._pump()

    def _remember(self, url: str, pixmap: QPixmap) -> QPixmap:
        if max(pixmap.width(), pixmap.height()) > _MAX_MEMORY_DIMENSION:
            pixmap = pixmap.scaled(
                _MAX_MEMORY_DIMENSION,
                _MAX_MEMORY_DIMENSION,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._memory[url] = pixmap
        self._memory.move_to_end(url)
        while len(self._memory) > _MAX_MEMORY_ITEMS:
            self._memory.popitem(last=False)
        return pixmap

    @staticmethod
    def _disk_path(url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return IMAGE_DIR / f"{digest}.img"
