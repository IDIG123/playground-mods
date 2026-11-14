from __future__ import annotations

import html
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..images import ImageLoader
from ..models import (
    KIND_CONTRAPTION,
    InstalledMod,
    Mod,
    kind_badge,
    kind_folder_name,
    kind_label,
)
from ..installer import find_thumbnail


def format_metric(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_date(value: str) -> str:
    """Turn an ISO date from either source into a short, readable label."""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    return parsed.strftime("%b %d, %Y")


def time_ago(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return format_date(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 86400 * 7:
        return f"{int(seconds // 86400)}d ago"
    return format_date(text)


def format_size(value: int) -> str:
    if value <= 0:
        return "—"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


def version_compare(left: str, right: str) -> int:
    def parts(value: str) -> list[int]:
        return [int(part) if part.isdigit() else 0 for part in str(value or "").split(".")]

    a, b = parts(left), parts(right)
    for index in range(max(len(a), len(b))):
        delta = (a[index] if index < len(a) else 0) - (
            b[index] if index < len(b) else 0
        )
        if delta:
            return -1 if delta < 0 else 1
    return 0


def strip_markdown(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`~#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _inline_markdown(text: str) -> str:
    # Escape first, then re-introduce only the small markup subset the site
    # actually uses in descriptions and changelogs.
    text = html.escape(text, quote=False)

    def link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = html.unescape(match.group(2))
        if not url.startswith(("http://", "https://")):
            return label
        return f'<a href="{html.escape(url, quote=True)}">{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def markdown_to_html(value: str) -> str:
    """A compact Markdown renderer for QLabel rich text."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    blocks: list[str] = []
    list_items: list[str] = []
    ordered_items: list[str] = []

    def flush_lists() -> None:
        nonlocal list_items, ordered_items
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items = []
        if ordered_items:
            blocks.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered_items) + "</ol>")
            ordered_items = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_lists()
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            flush_lists()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*+]\s+(.*)$", line)
        if bullet:
            if ordered_items:
                flush_lists()
            list_items.append(_inline_markdown(bullet.group(1)))
            continue
        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if numbered:
            if list_items:
                flush_lists()
            ordered_items.append(_inline_markdown(numbered.group(1)))
            continue
        flush_lists()
        blocks.append(f"<p>{_inline_markdown(line)}</p>")
    flush_lists()
    return "".join(blocks)


_THUMBNAIL_CACHE: dict[str, QPixmap] = {}
_THUMBNAIL_CACHE_LIMIT = 320


def _cached_thumbnail(path: Path) -> QPixmap | None:
    """Load a thumbnail once and reuse it across installed-card rebuilds."""
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        return None
    cached = _THUMBNAIL_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    if len(_THUMBNAIL_CACHE) >= _THUMBNAIL_CACHE_LIMIT:
        _THUMBNAIL_CACHE.clear()
    _THUMBNAIL_CACHE[key] = pixmap
    return pixmap


# Installed thumbnails are decoded in small batches so opening the installed
# page or changing its filter never blocks on a hundred PNG decodes at once.
_PENDING_THUMBNAILS: deque[tuple["CoverLabel", Path]] = deque()
_THUMBNAIL_TIMER: QTimer | None = None
_THUMBNAIL_BATCH = 4


def _thumbnail_timer() -> QTimer:
    global _THUMBNAIL_TIMER
    if _THUMBNAIL_TIMER is None:
        _THUMBNAIL_TIMER = QTimer(QCoreApplication.instance())
        _THUMBNAIL_TIMER.setInterval(0)
        _THUMBNAIL_TIMER.timeout.connect(_load_thumbnail_batch)
    return _THUMBNAIL_TIMER


def request_thumbnail(cover: "CoverLabel", path: Path) -> None:
    """Show a cached thumbnail now, or queue it for the next idle batch."""
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        return
    cached = _THUMBNAIL_CACHE.get(key)
    if cached is not None:
        cover.set_cover(cached)
        return
    _PENDING_THUMBNAILS.append((cover, path))
    timer = _thumbnail_timer()
    if not timer.isActive():
        timer.start()


def clear_thumbnail_queue() -> None:
    _PENDING_THUMBNAILS.clear()


def _load_thumbnail_batch() -> None:
    for _ in range(_THUMBNAIL_BATCH):
        if not _PENDING_THUMBNAILS:
            if _THUMBNAIL_TIMER is not None:
                _THUMBNAIL_TIMER.stop()
            return
        cover, path = _PENDING_THUMBNAILS.popleft()
        if not shiboken6.isValid(cover):
            continue
        pixmap = _cached_thumbnail(path)
        if pixmap is not None:
            cover.set_cover(pixmap)


class CoverLabel(QLabel):
    resized = Signal()
    clicked = Signal()

    def __init__(
        self,
        placeholder: str = "",
        radius: int = 7,
        parent: QWidget | None = None,
        max_source: int = 720,
    ) -> None:
        super().__init__(parent)
        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._placeholder = placeholder
        self._radius = radius
        self._max_source = max(64, max_source)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Do not use Ignored here: inside a box layout Qt then reserves zero
        # space for the cover and draws the following widgets on top of it.
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )

    def set_cover(self, pixmap: QPixmap | None) -> None:
        if pixmap is not None and not pixmap.isNull():
            # Keep only as much source resolution as this widget can show.
            if max(pixmap.width(), pixmap.height()) > self._max_source:
                pixmap = pixmap.scaled(
                    self._max_source,
                    self._max_source,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._source = pixmap
        else:
            self._source = None
        self._scaled = None
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._scaled = None
        self.resized.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not shiboken6.isValid(self):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _cover_pixmap(self) -> QPixmap | None:
        if self._source is None or self.width() <= 0 or self.height() <= 0:
            return None
        if self._scaled is None:
            self._scaled = self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        return self._scaled

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        cover = self._cover_pixmap()
        if cover is not None:
            x = (cover.width() - self.width()) // 2
            y = (cover.height() - self.height()) // 2
            painter.drawPixmap(-x, -y, cover)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor("#2a2a2a"))
            gradient.setColorAt(0.55, QColor("#1e1e1e"))
            gradient.setColorAt(1.0, QColor("#161616"))
            painter.fillRect(rect, gradient)
            if self._placeholder:
                font = QFont("Noto Sans")
                font.setPixelSize(max(11, min(18, self.height() // 7)))
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor("#6f6f6f"))
                text = self._placeholder[:40]
                painter.drawText(
                    self.rect().adjusted(14, 10, -14, -10),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    text,
                )
        painter.end()


class ChevronComboBox(QComboBox):
    """Combo box with a visible chevron that survives the dark stylesheet."""

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#9a9a9a"), 1.6))
        x = self.width() - 15
        y = self.height() // 2 - 2
        painter.drawLine(x - 3, y, x, y + 3)
        painter.drawLine(x, y + 3, x + 3, y)
        painter.end()


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text or ""
        self._apply()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        available = max(10, self.width() - 2)
        self.setText(
            metrics.elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, available
            )
        )


class ModCard(QFrame):
    install_clicked = Signal(object)
    details_clicked = Signal(object)

    def __init__(
        self,
        mod: Mod,
        loader: ImageLoader,
        installed: bool = False,
        kind: str = "",
        kind_guess: bool = False,
        liked: bool = False,
        following: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mod = mod
        # ``kind`` is authoritative only for content already on disk. The
        # catalogue guess is flagged separately so the tooltip can say so.
        self.kind = kind or ""
        self.kind_guess = bool(kind_guess) and not installed
        self.liked = liked
        self.following = following
        self.image: CoverLabel | None = None
        self.title: QLabel | None = None
        self._installed = False
        self.setObjectName("ModCard")
        self.setFixedHeight(318)
        self.setMinimumWidth(228)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("installed", installed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.image = CoverLabel(mod.title, radius=10, parent=self, max_source=640)
        self.image.setFixedHeight(164)
        category = QLabel(self._category_text(), self.image)
        category.setObjectName("CategoryBadge")
        category.adjustSize()
        category.move(10, 10)
        category.raise_()
        self.category_badge = category
        outer.addWidget(self.image)

        self.kind_badge: QLabel | None = None
        if self.kind:
            self.kind_badge = QLabel(kind_badge(self.kind), self.image)
            self.kind_badge.setObjectName("KindBadge")
            self.kind_badge.setProperty("kind", self.kind)
            self.kind_badge.adjustSize()
            self.kind_badge.raise_()

        self.badge_row = QWidget(self.image)
        self.badge_row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge_layout = QHBoxLayout(self.badge_row)
        self.badge_layout.setContentsMargins(0, 0, 0, 0)
        self.badge_layout.setSpacing(4)
        self._build_badges()
        self.badge_layout.addStretch(1)
        self.badge_row.raise_()

        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(13, 9, 13, 10)
        body_layout.setSpacing(4)

        self.title = QLabel(mod.title, body)
        self.title.setObjectName("CardTitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.title.setFixedHeight(38)
        body_layout.addWidget(self.title)

        meta_bits = [mod.creator]
        published = time_ago(mod.published)
        if published:
            meta_bits.append(published)
        meta_text = "  ·  ".join(meta_bits)
        meta = ElidedLabel(meta_text, body)
        meta.setObjectName("CardMeta")
        meta.setFixedHeight(15)
        meta.setToolTip(meta_text)
        body_layout.addWidget(meta)

        summary = QLabel(mod.summary or "No description provided.", body)
        summary.setObjectName("CardSummary")
        summary.setWordWrap(True)
        summary.setFixedHeight(32)
        summary.setToolTip(mod.summary)
        body_layout.addWidget(summary)
        body_layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 1, 0, 0)
        footer.setSpacing(7)
        metric = QLabel(f"↓ {format_metric(mod.metric)}", body)
        metric.setObjectName("CardMetric")
        metric.setToolTip(f"{mod.metric:,} {mod.metric_label}")
        footer.addWidget(metric)
        if mod.likes or self.liked:
            likes = QLabel(f"♥ {format_metric(mod.likes + (1 if self.liked else 0))}", body)
            likes.setObjectName("CardMetric")
            likes.setToolTip(
                f"{mod.likes + (1 if self.liked else 0):,} likes"
                + (" · liked locally" if self.liked else "")
            )
            footer.addWidget(likes)
        if mod.comments_count:
            comments = QLabel(f"{format_metric(mod.comments_count)} comments", body)
            comments.setObjectName("CardMetric")
            footer.addWidget(comments)
        footer.addStretch(1)
        if mod.version:
            version = QLabel(f"v{mod.version}", body)
            version.setObjectName("CardVersion")
            footer.addWidget(version)
        details = QPushButton("Details", body)
        details.setObjectName("DetailsLink")
        details.setCursor(Qt.CursorShape.PointingHandCursor)
        details.clicked.connect(lambda: self.details_clicked.emit(self.mod))
        footer.addWidget(details)
        self.install_button = QPushButton(body)
        self.install_button.setObjectName("InstallButton")
        self.install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_button.clicked.connect(lambda: self.install_clicked.emit(self.mod))
        footer.addWidget(self.install_button)
        body_layout.addLayout(footer)
        outer.addWidget(body, 1)

        self.set_installed(installed)
        self._apply_image_state()
        self._update_kind_tooltip()
        self._place_badges()
        self.image.installEventFilter(self)
        self.title.installEventFilter(self)
        self.image.resized.connect(self._place_badges)
        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        if mod.image_url:
            loader.load(mod.image_url)
        else:
            self._image_failed(mod.image_url)

    def _category_text(self) -> str:
        label = (self.mod.tag or "mod").replace("-", " ").strip()
        if len(label) > 18:
            label = label[:17].rstrip() + "…"
        return label.upper()

    def _build_badges(self) -> None:
        mod = self.mod
        badges: list[tuple[str, str]] = []
        if mod.pinned:
            badges.append(("PINNED", "PinnedBadge"))
        if mod.broken:
            badges.append(("BROKEN", "BrokenBadge"))
        elif mod.updated:
            badges.append(("UPDATED", "UpdateBadge"))
        if mod.tier:
            badges.append((mod.tier.upper(), "TierBadge"))
        if self.following:
            badges.append(("FOLLOWING", "FollowingBadge"))
        if mod.status and mod.status != "published":
            badges.append((mod.status.upper(), "BrokenBadge"))
        for text, object_name in badges[:3]:
            label = QLabel(text, self.badge_row)
            label.setObjectName(object_name)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.adjustSize()
            self.badge_layout.addWidget(label)

    def _update_kind_tooltip(self) -> None:
        if self.kind_badge is None or not self.kind:
            return
        if self._installed:
            text = (
                f"Installed as a {kind_label(self.kind).lower()} in the "
                f"{kind_folder_name(self.kind)} folder."
            )
        elif self.kind_guess:
            text = (
                f"Likely a {kind_label(self.kind).lower()} based on its listing. "
                "The archive contents are verified when you install it."
            )
        else:
            text = (
                f"{kind_label(self.kind)} — installs into the "
                f"{kind_folder_name(self.kind)} folder."
            )
        self.kind_badge.setToolTip(text)

    def _place_badges(self) -> None:
        if self.kind_badge is not None:
            width = max(0, self.image.width() - self.kind_badge.width() - 10)
            self.kind_badge.move(width, 10)
            self.kind_badge.raise_()
        if self.image.width() > 0:
            self.badge_row.setGeometry(
                10, max(10, self.image.height() - 30), self.image.width() - 20, 22
            )
            self.badge_row.raise_()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._place_badges()

    def _apply_image_state(self) -> None:
        external = self.mod.install_mode == "external"
        self.install_button.setText(
            "Get" if external else ("Reinstall" if self._installed else "Install")
        )
        self.install_button.setProperty("external", external)
        self.install_button.setProperty("installed", self._installed)
        self.install_button.style().unpolish(self.install_button)
        self.install_button.style().polish(self.install_button)
        noun = "contraption" if self.kind == KIND_CONTRAPTION else "mod"
        if self.mod.locked_reason:
            self.install_button.setToolTip(self.mod.locked_reason)
        elif external:
            self.install_button.setToolTip("Open the original source page")
        elif self._installed:
            self.install_button.setToolTip(f"Install again or update this {noun}")
        else:
            self.install_button.setToolTip(f"Install {self.mod.title}")

    def set_installed(self, installed: bool) -> None:
        self._installed = installed
        self.setProperty("installed", installed)
        self.style().unpolish(self)
        self.style().polish(self)
        self._apply_image_state()
        self._update_kind_tooltip()

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(None)
            self.image.set_placeholder(self.mod.title)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if not shiboken6.isValid(self):
            return False
        if (
            watched is not None
            and (watched is self.image or watched is self.title)
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                self.details_clicked.emit(self.mod)
                return True
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not shiboken6.isValid(self):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.details_clicked.emit(self.mod)
        super().mouseReleaseEvent(event)


class FreshCard(QFrame):
    """Compact card used by the home discovery rail."""

    clicked = Signal(object)

    def __init__(
        self,
        mod: Mod,
        loader: ImageLoader,
        is_new: bool = False,
        badge_text: str = "",
        badge_fresh: bool | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mod = mod
        self.setObjectName("FreshCard")
        self.setFixedSize(194, 174)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image = CoverLabel(mod.title, radius=9, parent=self, max_source=420)
        self.image.setFixedHeight(106)
        layout.addWidget(self.image)
        if badge_text:
            text = badge_text
            fresh = is_new if badge_fresh is None else badge_fresh
        else:
            text = "New" if is_new else f"Updated · v{mod.version or '—'}"
            fresh = is_new
        badge = QLabel(text, self.image)
        badge.setObjectName("FreshBadge")
        badge.setProperty("fresh", fresh)
        badge.adjustSize()
        badge.move(8, 8)
        badge.raise_()

        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(9, 7, 9, 7)
        body_layout.setSpacing(2)
        title = QLabel(mod.title, body)
        title.setObjectName("FreshTitle")
        title.setWordWrap(True)
        title.setFixedHeight(32)
        body_layout.addWidget(title)
        meta = QLabel(
            f"{mod.creator}  ·  {time_ago(mod.published)}", body
        )
        meta.setObjectName("FreshMeta")
        meta.setToolTip(f"{mod.creator} · {format_date(mod.published)}")
        body_layout.addWidget(meta)
        layout.addWidget(body, 1)

        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        if mod.image_url:
            loader.load(mod.image_url)
        else:
            self._image_failed(mod.image_url)

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(None)
            self.image.set_placeholder(self.mod.title)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not shiboken6.isValid(self):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod)
        super().mouseReleaseEvent(event)


class MiniModCard(QFrame):
    """Small horizontal card used for related mods inside details dialogs."""

    clicked = Signal(object)

    def __init__(
        self,
        mod: Mod,
        loader: ImageLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mod = mod
        self.setObjectName("MiniModCard")
        self.setFixedHeight(76)
        self.setMinimumWidth(250)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 7, 9, 7)
        layout.setSpacing(9)
        self.image = CoverLabel(mod.title, radius=6, parent=self, max_source=220)
        self.image.setFixedSize(96, 62)
        self.image.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.image)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        title = QLabel(mod.title, self)
        title.setObjectName("MiniTitle")
        title.setWordWrap(True)
        title.setFixedHeight(32)
        body.addWidget(title)
        meta = QLabel(
            f"↓ {format_metric(mod.metric)}  ·  v{mod.version or '—'}", self
        )
        meta.setObjectName("MiniMeta")
        body.addWidget(meta)
        layout.addLayout(body, 1)
        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        if mod.image_url:
            loader.load(mod.image_url)
        else:
            self._image_failed(mod.image_url)

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if not shiboken6.isValid(self):
            return
        if url == self.mod.image_url:
            self.image.set_cover(None)
            self.image.set_placeholder(self.mod.title)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if not shiboken6.isValid(self):
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mod)
        super().mouseReleaseEvent(event)


class FlowGrid(QWidget):
    """A responsive card grid that keeps all cards on the main thread."""

    def __init__(
        self, min_card_width: int = 238, spacing: int = 12, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._min_card_width = min_card_width
        self._spacing = spacing
        self._cards: list[QWidget] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(16)
        self._reflow_timer.timeout.connect(self._reflow)

    def set_cards(self, cards: list[QWidget]) -> None:
        self._take_all()
        for widget in self._cards:
            widget.setParent(None)
            widget.deleteLater()
        self._cards = cards
        for card in cards:
            card.setParent(self)
        self._columns = 0
        self._reflow()

    def _take_all(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)

    def _reflow(self) -> None:
        available = max(1, self.width())
        columns = max(
            1, (available + self._spacing) // (self._min_card_width + self._spacing)
        )
        columns = min(columns, max(1, len(self._cards)))
        if columns == self._columns:
            return
        self._columns = columns
        self._take_all()
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        # Clear stretch on columns that are no longer used; a stale stretch
        # would keep sharing the row width and leave empty space on the right.
        for column in range(max(self._grid.columnCount(), columns, 12)):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        # Adding/removing rows leaves the grid's size hint stale until it is
        # invalidated; without this the rows get compressed and overlap.
        self._grid.invalidate()
        self._grid.activate()
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
            parent.layout().activate()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Coalesce rapid resize events while the window is being dragged.
        self._reflow_timer.start()


class InstalledCard(QFrame):
    open_clicked = Signal(object)
    remove_clicked = Signal(object)

    def __init__(
        self, mod: InstalledMod, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.mod = mod
        self.setObjectName("InstalledCard")
        self.setFixedHeight(92)
        self.setMinimumWidth(300)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(10)

        self.image = CoverLabel(mod.title, radius=7, parent=self, max_source=256)
        self.image.setFixedSize(112, 64)
        # Pin the cover so the text never overlaps it in a horizontal layout.
        self.image.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        thumb = Path(mod.thumbnail) if mod.thumbnail else None
        if thumb is None or not thumb.is_file():
            try:
                thumb = find_thumbnail(Path(mod.path), {})
            except OSError:
                thumb = None
        if thumb is not None and thumb.is_file():
            request_thumbnail(self.image, thumb)
        layout.addWidget(self.image)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        title = ElidedLabel(mod.title, self)
        title.setObjectName("InstalledTitle")
        top.addWidget(title, 1)
        body.addLayout(top)

        meta_text = (
            f"{mod.author or 'Unknown author'}  ·  {kind_folder_name(mod.kind)}"
            f"  ·  {mod.folder}"
        )
        meta = ElidedLabel(meta_text, self)
        meta.setObjectName("InstalledMeta")
        meta.setToolTip(meta_text)
        body.addWidget(meta)
        body.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        open_button = QPushButton("Open folder", self)
        open_button.setObjectName("InstalledAction")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(lambda: self.open_clicked.emit(self.mod))
        actions.addWidget(open_button)
        remove_button = QPushButton("Remove", self)
        remove_button.setObjectName("InstalledAction")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.setEnabled(mod.managed)
        remove_button.setToolTip(
            "Only items installed by this app can be removed here."
            if not mod.managed
            else f"Remove {mod.title} from the {kind_folder_name(mod.kind)} folder"
        )
        remove_button.clicked.connect(lambda: self.remove_clicked.emit(self.mod))
        actions.addWidget(remove_button)
        actions.addStretch(1)
        body.addLayout(actions)
        layout.addLayout(body, 1)
