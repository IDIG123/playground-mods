from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..installer import (
    PreparedInstall,
    extract_prepared,
    prepare_download,
    prepare_local_archive,
    sanitize_folder_name,
)
from ..models import (
    KIND_CONTRAPTION,
    KIND_MOD,
    Mod,
    ModComment,
    ModDetail,
    ResolvedDownload,
    kind_folder_name,
    kind_label,
)
from ..images import ImageLoader
from ..paths import contraptions_directory
from ..sources import CatalogueService
from ..store import Store
from ..workers import Task
from .widgets import (
    CoverLabel,
    MiniModCard,
    format_date,
    format_metric,
    format_size,
    markdown_to_html,
    time_ago,
)


def open_external(url: str) -> None:
    if url:
        QDesktopServices.openUrl(QUrl(url))


class ModDetailsDialog(QDialog):
    install_requested = Signal(object)
    mod_requested = Signal(object)
    library_changed = Signal()

    def __init__(
        self,
        mod: Mod,
        loader: ImageLoader,
        service: CatalogueService | None = None,
        store: Store | None = None,
        library: dict | None = None,
        installed: bool = False,
        mod_lookup=None,
        load_rich: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mod = mod
        self.loader = loader
        self.service = service or CatalogueService()
        self.store = store
        self.library = library if library is not None else {
            "version": 1,
            "likes": [],
            "follows": {},
            "seen": {},
            "dismissed_notice": "",
            "onboarding_seen": False,
        }
        self.mod_lookup = mod_lookup
        self._installed = installed
        self._load_rich = load_rich
        self._pixmaps: dict[str, QPixmap] = {}
        self._thumbs: dict[str, CoverLabel] = {}
        self._current = ""
        self._detail: ModDetail | None = None
        self._comments: list[ModComment] = []
        self._related: list[Mod] = []
        self._task: Task | None = None
        self._closed = False
        self._gallery_layout: QHBoxLayout | None = None
        self._spec_grid: QGridLayout | None = None
        self._versions_layout: QVBoxLayout | None = None
        self._deps_layout: QVBoxLayout | None = None
        self._related_grid: QGridLayout | None = None
        self._comments_layout: QVBoxLayout | None = None

        self.setObjectName("DetailsDialog")
        self.setWindowTitle(f"{mod.title} — details")
        self.setModal(True)
        self.resize(860, 760)
        self.setMinimumSize(700, 580)
        self._build_ui()
        self._update_like_button()
        self._update_follow_button()
        self._fill_spec(None)

        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        for url in dict.fromkeys([mod.image_url, *mod.images]):
            if url:
                loader.load(url)
        if not mod.image_url:
            self.cover.set_placeholder(mod.title)
        if self._load_rich:
            QTimer.singleShot(0, self._start_rich_load)
        else:
            self.loading_label.hide()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("DetailsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 14)
        header_layout.setSpacing(22)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(7)
        kicker_parts = [self.mod.source.upper(), f"#{self.mod.tag.upper()}"]
        if self.mod.kind_label:
            kicker_parts.append(self.mod.kind_label.upper())
        kicker = QLabel("  /  ".join(kicker_parts), header)
        kicker.setObjectName("DialogKicker")
        left.addWidget(kicker)

        title = QLabel(self.mod.title, header)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        left.addWidget(title)

        meta_bits = [
            bit
            for bit in (
                self.mod.creator,
                f"PP {self.mod.game_version}" if self.mod.game_version else "",
                f"v{self.mod.version}" if self.mod.version else "",
                f"{format_metric(self.mod.metric)} {self.mod.metric_label}",
            )
            if bit
        ]
        meta = QLabel("  ·  ".join(meta_bits), header)
        meta.setObjectName("DialogSmall")
        meta.setWordWrap(True)
        left.addWidget(meta)

        if self.mod.tags:
            tags = QHBoxLayout()
            tags.setContentsMargins(0, 2, 0, 0)
            tags.setSpacing(5)
            for tag in self.mod.tags[:8]:
                pill = QLabel(f"#{tag}", header)
                pill.setObjectName("TagPill")
                tags.addWidget(pill)
            tags.addStretch(1)
            left.addLayout(tags)

        if self._installed:
            installed_note = QLabel(
                "✓ Installed — installing again replaces the existing folder.",
                header,
            )
            installed_note.setObjectName("InstalledNote")
            installed_note.setWordWrap(True)
            left.addWidget(installed_note)
        left.addStretch(1)
        header_layout.addLayout(left, 1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        self.cover = CoverLabel(self.mod.title, radius=9, parent=header)
        self.cover.setFixedSize(304, 174)
        self.cover.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        right.addWidget(self.cover)
        self._gallery_layout = QHBoxLayout()
        self._gallery_layout.setContentsMargins(0, 0, 0, 0)
        self._gallery_layout.setSpacing(5)
        self._gallery_layout.addStretch(1)
        right.addLayout(self._gallery_layout)
        header_layout.addLayout(right, 0)
        outer.addWidget(header)

        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        action_bar = QWidget(self)
        action_bar.setObjectName("DetailsActionBar")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(26, 10, 26, 10)
        actions.setSpacing(8)
        self.like_button = QPushButton(action_bar)
        self.like_button.setObjectName("LikeButton")
        self.like_button.setCheckable(True)
        self.like_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.like_button.clicked.connect(self._toggle_like)
        actions.addWidget(self.like_button)
        self.follow_button = QPushButton(action_bar)
        self.follow_button.setObjectName("FollowButton")
        self.follow_button.setCheckable(True)
        self.follow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.follow_button.setToolTip(
            "Follow this mod to get a local notice when its version changes."
        )
        self.follow_button.clicked.connect(self._toggle_follow)
        actions.addWidget(self.follow_button)
        page = QPushButton("Open source page", action_bar)
        page.setObjectName("SecondaryButton")
        page.setCursor(Qt.CursorShape.PointingHandCursor)
        page.clicked.connect(lambda: open_external(self.mod.url))
        actions.addWidget(page)
        actions.addStretch(1)
        close = QPushButton("Close", action_bar)
        close.setObjectName("SecondaryButton")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        noun = "contraption" if self.mod.kind == KIND_CONTRAPTION else "mod"
        if self.mod.install_mode == "external":
            install_label = f"Get {noun}"
        elif self._installed:
            install_label = f"Reinstall {noun}"
        else:
            install_label = f"Install {noun}"
        install = QPushButton(install_label, action_bar)
        install.setObjectName("PrimaryButton")
        install.setCursor(Qt.CursorShape.PointingHandCursor)
        install.clicked.connect(self._install)
        actions.addWidget(install)
        outer.addWidget(action_bar)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        body = QVBoxLayout(content)
        body.setContentsMargins(26, 16, 26, 24)
        body.setSpacing(14)

        self.loading_label = QLabel(
            "Loading full details, versions and comments from the source…",
            content,
        )
        self.loading_label.setObjectName("LoadingNote")
        self.loading_label.setWordWrap(True)
        body.addWidget(self.loading_label)

        _description_section, description_layout = self._add_section(
            body, "About this mod", "Description from the original source."
        )
        self.description_label = QLabel(content)
        self.description_label.setObjectName("DetailText")
        self.description_label.setWordWrap(True)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        self.description_label.setOpenExternalLinks(True)
        self.description_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        description_layout.addWidget(self.description_label)

        self.spec_section, spec_layout = self._add_section(
            body, "Spec sheet", "Everything the source publishes about this file."
        )
        self._spec_grid = QGridLayout()
        self._spec_grid.setContentsMargins(0, 0, 0, 0)
        self._spec_grid.setHorizontalSpacing(18)
        self._spec_grid.setVerticalSpacing(5)
        self._spec_grid.setColumnStretch(1, 1)
        spec_layout.addLayout(self._spec_grid)

        self.versions_section, self._versions_layout = self._add_section(
            body, "Changelog", "Recent versions published by the author."
        )
        self.versions_section.hide()

        self.deps_section, self._deps_layout = self._add_section(
            body, "Dependencies", "Install these first if the mod asks for them."
        )
        self.deps_section.hide()

        self.related_section, related_layout = self._add_section(
            body, "Related mods", "More from the same catalogue."
        )
        self._related_grid = QGridLayout()
        self._related_grid.setContentsMargins(0, 0, 0, 0)
        self._related_grid.setHorizontalSpacing(8)
        self._related_grid.setVerticalSpacing(8)
        related_layout.addLayout(self._related_grid)
        self.related_section.hide()

        self.comments_section, self._comments_layout = self._add_section(
            body,
            "Comments",
            "A read-only mirror of the public discussion on the source site.",
        )
        self.comments_section.hide()

        body.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self._update_description()
        self._rebuild_gallery(
            list(dict.fromkeys([self.mod.image_url, *self.mod.images]))
        )

    def _add_section(
        self, parent_layout: QVBoxLayout, title: str, caption: str = ""
    ) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(self)
        frame.setObjectName("DetailSection")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title, frame)
        heading.setObjectName("DetailSectionTitle")
        layout.addWidget(heading)
        if caption:
            note = QLabel(caption, frame)
            note.setObjectName("DetailSectionCaption")
            note.setWordWrap(True)
            layout.addWidget(note)
        parent_layout.addWidget(frame)
        return frame, layout

    # ------------------------------------------------------------------
    # Async detail loading
    # ------------------------------------------------------------------
    def _start_rich_load(self) -> None:
        task = Task(self._fetch_rich)
        task.signals.done.connect(self._rich_ready)
        task.signals.error.connect(self._rich_failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _fetch_rich(self) -> tuple:
        errors: list[str] = []
        detail: ModDetail | None = None
        comments: list[ModComment] = []
        related: list[Mod] = []
        try:
            detail = self.service.fetch_mod_detail(self.mod)
        except Exception as exc:  # noqa: BLE001 - show a partial page
            errors.append(str(exc))
        if self.mod.source == "Switch Studio":
            if self.mod.site_id:
                try:
                    comments = self.service.fetch_comments("mod", self.mod.site_id)
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
            if self.mod.slug:
                try:
                    related = self.service.fetch_related(self.mod.slug)
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
        return detail, comments, related, errors

    def _rich_ready(self, result: tuple) -> None:
        self._task = None
        if self._closed:
            return
        detail, comments, related, errors = result
        self._detail = detail
        self._comments = list(comments or [])
        self._related = list(related or [])
        self.loading_label.hide()
        if detail is not None:
            self._update_description()
            self._fill_spec(detail)
            if detail.gallery:
                self._rebuild_gallery(detail.gallery)
        self._fill_versions()
        self._fill_dependencies()
        self._fill_related()
        self._fill_comments()
        if errors and detail is None:
            self.description_label.setText(
                markdown_to_html(self.mod.summary or "No description provided.")
            )
            self.comments_section.hide()
            self.loading_label.setText(
                "The full description could not be loaded. Showing the catalogue "
                "summary instead. Open the source page to read everything."
            )
            self.loading_label.show()

    def _rich_failed(self, message: str) -> None:
        self._task = None
        if self._closed:
            return
        self.loading_label.setText(
            f"Could not load full details: {message}. Showing the catalogue summary."
        )
        self.loading_label.show()
        self._update_description()
        self._fill_spec(None)
        self._fill_comments()

    def _update_description(self) -> None:
        text = ""
        if self._detail is not None and self._detail.description.strip():
            text = self._detail.description
        elif self.mod.summary.strip():
            text = self.mod.summary
        if not text:
            text = "No description provided."
        self.description_label.setText(markdown_to_html(text))

    # ------------------------------------------------------------------
    # Spec sheet, versions, dependencies, related
    # ------------------------------------------------------------------
    def _fill_spec(self, detail: ModDetail | None) -> None:
        if self._spec_grid is None:
            return
        while self._spec_grid.count():
            item = self._spec_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        latest_size = self.mod.file_size
        if detail is not None and detail.versions:
            latest_size = detail.versions[0].size or latest_size
        access = "Free"
        if self.mod.tier:
            access = f"Paid · {self.mod.tier.title()}"
        elif self.mod.install_mode == "external":
            access = "External / account required"
        if self.mod.licensed:
            access += " · licensed"

        rows: list[tuple[str, str]] = [
            ("Source", self.mod.source),
            ("Author", self.mod.creator),
            ("Version", f"v{self.mod.version}" if self.mod.version else ""),
            ("Game version", self.mod.game_version),
            ("Released", format_date(self.mod.published)),
            ("Updated", format_date(self.mod.updated_at)),
            ("File size", format_size(latest_size)),
            ("Downloads", f"{self.mod.metric:,}" if self.mod.metric else ""),
            ("Likes", f"{self.mod.likes:,}" if self.mod.likes else ""),
            ("Comments", f"{self.mod.comments_count:,}" if self.mod.comments_count else ""),
            ("Access", access),
            (
                "Installs to",
                kind_folder_name(self.mod.kind)
                if self.mod.kind
                else "Detected from the archive contents",
            ),
            ("Status", self.mod.status if self.mod.status != "published" else ""),
        ]
        if detail is not None and detail.featured:
            rows.append(("Featured", "Yes"))
        if self.mod.pinned:
            rows.append(("Pinned", "Yes, by the site team"))
        if self.mod.broken:
            rows.append(("Broken", "Marked as broken by the site team"))
        seen = {key.lower() for key, _ in rows if key}
        if detail is not None:
            for key, value in detail.file_info:
                if key and value and key.lower() not in seen:
                    rows.append((key, value))
                    seen.add(key.lower())
        rows = [(key, value) for key, value in rows if value]

        for row, (key, value) in enumerate(rows):
            key_label = QLabel(key.upper(), self)
            key_label.setObjectName("DialogMetaKey")
            value_label = QLabel(value, self)
            value_label.setObjectName("DialogMetaValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._spec_grid.addWidget(key_label, row, 0)
            self._spec_grid.addWidget(value_label, row, 1)

    def _fill_versions(self) -> None:
        if self._versions_layout is None:
            return
        while self._versions_layout.count():
            item = self._versions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        versions = self._detail.versions if self._detail is not None else []
        if not versions:
            self.versions_section.hide()
            return
        for version in versions[:6]:
            row = QFrame(self.versions_section)
            row.setObjectName("VersionRow")
            layout = QVBoxLayout(row)
            layout.setContentsMargins(12, 9, 12, 9)
            layout.setSpacing(4)
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(8)
            tag = QLabel(f"v{version.version or '—'}", row)
            tag.setObjectName("VersionTag")
            top.addWidget(tag)
            when = format_date(version.created_at)
            if when:
                date_label = QLabel(when, row)
                date_label.setObjectName("VersionDate")
                top.addWidget(date_label)
            size = format_size(version.size)
            if size != "—":
                size_label = QLabel(size, row)
                size_label.setObjectName("VersionDate")
                top.addWidget(size_label)
            top.addStretch(1)
            layout.addLayout(top)
            changelog = version.changelog.strip()
            text = QLabel(row)
            text.setObjectName("DetailText")
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setOpenExternalLinks(True)
            text.setText(
                markdown_to_html(changelog)
                if changelog
                else "<p>No changelog was provided for this version.</p>"
            )
            layout.addWidget(text)
            self._versions_layout.addWidget(row)
        if len(versions) > 6:
            more = QLabel(
                f"{len(versions) - 6} older versions are listed on the source page.",
                self.versions_section,
            )
            more.setObjectName("DetailSectionCaption")
            self._versions_layout.addWidget(more)
        self.versions_section.show()

    def _fill_dependencies(self) -> None:
        if self._deps_layout is None:
            return
        while self._deps_layout.count():
            item = self._deps_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        deps = self._detail.deps if self._detail is not None else []
        if not deps:
            self.deps_section.hide()
            return
        for dep in deps:
            row = QFrame(self.deps_section)
            row.setObjectName("DependencyRow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(11, 8, 11, 8)
            layout.setSpacing(8)
            title = QLabel(dep.title or dep.slug, row)
            title.setObjectName("DependencyTitle")
            title.setWordWrap(True)
            layout.addWidget(title, 1)
            if dep.tier:
                pill = QLabel(dep.tier.upper(), row)
                pill.setObjectName("TierBadge")
                layout.addWidget(pill)
            if dep.draft:
                pill = QLabel("DRAFT", row)
                pill.setObjectName("BrokenBadge")
                layout.addWidget(pill)
            if dep.locked:
                pill = QLabel("LOCKED", row)
                pill.setObjectName("BrokenBadge")
                layout.addWidget(pill)
            target = self.mod_lookup(dep.slug) if self.mod_lookup else None
            button = QPushButton("Open" if target else "Source", row)
            button.setObjectName("InstalledAction")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if target is not None:
                button.clicked.connect(
                    lambda _=False, target=target: self._request_mod(target)
                )
            else:
                button.clicked.connect(
                    lambda _=False, slug=dep.slug: open_external(
                        f"https://deswitchstudio.com/mod/{slug}"
                    )
                )
            layout.addWidget(button)
            self._deps_layout.addWidget(row)
        self.deps_section.show()

    def _fill_related(self) -> None:
        if self._related_grid is None:
            return
        while self._related_grid.count():
            item = self._related_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._related:
            self.related_section.hide()
            return
        for index, mod in enumerate(self._related[:6]):
            card = MiniModCard(mod, self.loader, self.related_section)
            card.clicked.connect(self._request_mod)
            self._related_grid.addWidget(card, index // 2, index % 2)
        self._related_grid.setColumnStretch(0, 1)
        self._related_grid.setColumnStretch(1, 1)
        self.related_section.show()

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    def _fill_comments(self) -> None:
        if self._comments_layout is None:
            return
        while self._comments_layout.count():
            item = self._comments_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        comments = self._comments
        if not comments:
            if self.mod.source == "Switch Studio" and self.mod.comments_count:
                note = QLabel(
                    "Comments could not be loaded. Open the mod page to read "
                    f"all {self.mod.comments_count} comments.",
                    self.comments_section,
                )
                note.setObjectName("DetailSectionCaption")
                note.setWordWrap(True)
                self._comments_layout.addWidget(note)
                self.comments_section.show()
            else:
                self.comments_section.hide()
            return

        by_id = {comment.id: comment for comment in comments}
        depth_cache: dict[int, int] = {}

        def depth(comment: ModComment, seen: set[int] | None = None) -> int:
            if comment.id in depth_cache:
                return depth_cache[comment.id]
            seen = seen or set()
            if comment.id in seen or not comment.parent_id:
                depth_cache[comment.id] = 0
                return 0
            seen.add(comment.id)
            parent = by_id.get(comment.parent_id)
            value = min(3, depth(parent, seen) + 1) if parent else 0
            depth_cache[comment.id] = value
            return value

        for comment in comments[:12]:
            row = QFrame(self.comments_section)
            row.setObjectName("CommentRow")
            row.setContentsMargins(depth(comment) * 18, 0, 0, 0)
            layout = QVBoxLayout(row)
            layout.setContentsMargins(11, 9, 11, 9)
            layout.setSpacing(4)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(6)
            author = QLabel(comment.author or "Someone", row)
            author.setObjectName("CommentAuthor")
            head.addWidget(author)
            badge = comment.author_badge or {}
            if badge.get("text"):
                pill = QLabel(str(badge["text"]), row)
                pill.setObjectName("CommentBadge")
                pill.setProperty("color", str(badge.get("color") or "yellow"))
                head.addWidget(pill)
            if comment.author_role and comment.author_role != "user":
                role = QLabel(comment.author_role.upper(), row)
                role.setObjectName("CommentBadge")
                role.setProperty("color", "green")
                head.addWidget(role)
            when = time_ago(comment.created_at)
            if when:
                time_label = QLabel(when, row)
                time_label.setObjectName("CommentMeta")
                head.addWidget(time_label)
            if comment.likes:
                likes = QLabel(f"♥ {comment.likes}", row)
                likes.setObjectName("CommentMeta")
                head.addWidget(likes)
            head.addStretch(1)
            layout.addLayout(head)
            body = QLabel(comment.body, row)
            body.setObjectName("CommentBody")
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(body)
            if comment.edited_at:
                edited = QLabel("edited", row)
                edited.setObjectName("CommentMeta")
                layout.addWidget(edited)
            self._comments_layout.addWidget(row)

        if len(comments) > 12:
            more = QLabel(
                f"Showing 12 of {len(comments)} comments. Open the source page "
                "to read the rest.",
                self.comments_section,
            )
            more.setObjectName("DetailSectionCaption")
            self._comments_layout.addWidget(more)
        read = QPushButton("Read all comments on the site", self.comments_section)
        read.setObjectName("SecondaryButton")
        read.setCursor(Qt.CursorShape.PointingHandCursor)
        read.clicked.connect(lambda: open_external(self.mod.url))
        self._comments_layout.addWidget(read)
        self.comments_section.show()

    # ------------------------------------------------------------------
    # Gallery
    # ------------------------------------------------------------------
    def _rebuild_gallery(self, urls: list[str]) -> None:
        if self._gallery_layout is None:
            return
        while self._gallery_layout.count():
            item = self._gallery_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._thumbs.clear()
        unique = [url for url in dict.fromkeys(urls) if url]
        if len(unique) > 1:
            for url in unique[:6]:
                thumb = CoverLabel("", radius=5, parent=self)
                thumb.setFixedSize(46, 29)
                thumb.setSizePolicy(
                    QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
                )
                thumb.setCursor(Qt.CursorShape.PointingHandCursor)
                thumb.clicked.connect(lambda url=url: self._select_image(url))
                self._thumbs[url] = thumb
                self._gallery_layout.addWidget(thumb)
                self.loader.load(url)
        self._gallery_layout.addStretch(1)
        first = unique[0] if unique else ""
        if first and not self._current:
            self._select_image(first)

    def _select_image(self, url: str) -> None:
        self._current = url
        pixmap = self._pixmaps.get(url)
        if pixmap is not None:
            self.cover.set_cover(pixmap)
        else:
            self.cover.set_placeholder(self.mod.title)
            self.loader.load(url)

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        self._pixmaps[url] = pixmap
        thumb = self._thumbs.get(url)
        if thumb is not None:
            thumb.set_cover(pixmap)
        if url == self.mod.image_url and not self._current:
            self._current = url
        if url == self._current:
            self.cover.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if url == self._current:
            self.cover.set_cover(None)
            self.cover.set_placeholder(self.mod.title)

    # ------------------------------------------------------------------
    # Local like / follow
    # ------------------------------------------------------------------
    def _liked(self) -> bool:
        return self.mod.uid in set(self.library.get("likes") or [])

    def _following(self) -> bool:
        return self.mod.uid in (self.library.get("follows") or {})

    def _update_like_button(self) -> None:
        liked = self._liked()
        count = self.mod.likes + (1 if liked else 0)
        self.like_button.setChecked(liked)
        self.like_button.setText(f"♥  {format_metric(count)}")
        self.like_button.setToolTip(
            "You liked this mod locally. Likes are kept on this computer."
            if liked
            else "Like this mod locally. The count on the site is not changed."
        )

    def _update_follow_button(self) -> None:
        following = self._following()
        self.follow_button.setChecked(following)
        self.follow_button.setText("★  Following" if following else "☆  Follow")
        self.follow_button.setToolTip(
            "Following. The app will tell you when a new version appears."
            if following
            else "Follow this mod to get a local notice when its version changes."
        )

    def _toggle_like(self, checked: bool) -> None:
        likes = [uid for uid in self.library.get("likes") or [] if uid != self.mod.uid]
        if checked:
            likes.append(self.mod.uid)
        self.library["likes"] = likes
        self._update_like_button()
        self._save_library()

    def _toggle_follow(self, checked: bool) -> None:
        follows = dict(self.library.get("follows") or {})
        if checked:
            follows[self.mod.uid] = {
                "title": self.mod.title,
                "version": self.mod.version,
                "latest_ver": self.mod.latest_ver,
                "url": self.mod.url,
                "source": self.mod.source,
                "slug": self.mod.slug,
                "followed_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            follows.pop(self.mod.uid, None)
        self.library["follows"] = follows
        self._update_follow_button()
        self._save_library()

    def _save_library(self) -> None:
        if self.store is not None:
            self.store.save_library(self.library)
        self.library_changed.emit()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _install(self) -> None:
        self.install_requested.emit(self.mod)
        self.accept()

    def _request_mod(self, mod: Mod) -> None:
        self.accept()
        self.mod_requested.emit(mod)

    def done(self, result: int) -> None:  # type: ignore[override]
        self._closed = True
        super().done(result)


class InstallDialog(QDialog):
    installed_changed = Signal()

    def __init__(
        self,
        service: CatalogueService,
        store: Store,
        records: dict,
        mods_root: Path,
        mod: Mod | None = None,
        local_zip: Path | None = None,
        contraptions_root: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.store = store
        self.records = records
        self.mods_root = Path(mods_root)
        self.contraptions_root = (
            Path(contraptions_root)
            if contraptions_root is not None
            else contraptions_directory(self.mods_root)
        )
        self.mod = mod
        self.local_zip = local_zip
        self._cancel_event = threading.Event()
        self._task: Task | None = None
        self._task_kind = ""
        self._prepared: PreparedInstall | None = None
        self._page_urls: list[str] = []
        self._busy = False
        self._destination_kind = KIND_MOD

        self.setWindowTitle(
            "Install from ZIP"
            if mod is None
            else ("Install contraption" if mod.kind == KIND_CONTRAPTION else "Install mod")
        )
        self.setModal(True)
        self.resize(580, 360)
        self.setMinimumSize(500, 320)
        self._build_ui()

        if local_zip is not None:
            QTimer.singleShot(0, lambda: self._begin_local(local_zip))
        elif mod is None:
            self._show_local_prompt()
        elif mod.install_mode == "direct":
            self._show_direct_ready()
        elif mod.install_mode == "resolve":
            self._show_resolving()
            QTimer.singleShot(0, self._resolve_top)
        else:
            self._show_external()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        self.kicker = QLabel(self)
        self.kicker.setObjectName("DialogKicker")
        layout.addWidget(self.kicker)

        self.title = QLabel(self)
        self.title.setObjectName("DialogTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.meta = QLabel(self)
        self.meta.setObjectName("DialogSmall")
        layout.addWidget(self.meta)

        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        layout.addWidget(divider)

        self.body = QLabel(self)
        self.body.setObjectName("DialogText")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.body)

        self.target = QLabel(
            f"Destination  ·  {self.mods_root}", self
        )
        self.target.setObjectName("DialogSmall")
        self.target.setWordWrap(True)
        self.target.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.target)

        self.destination_row = QWidget(self)
        destination_layout = QHBoxLayout(self.destination_row)
        destination_layout.setContentsMargins(0, 0, 0, 0)
        destination_layout.setSpacing(6)
        choose = QLabel("INSTALL AS", self.destination_row)
        choose.setObjectName("DialogSmall")
        destination_layout.addWidget(choose)
        self.destination_group = QButtonGroup(self)
        self.destination_group.setExclusive(True)
        self.mods_choice = QPushButton("Mod  →  Mods", self.destination_row)
        self.contraptions_choice = QPushButton(
            "Contraption  →  Contraptions", self.destination_row
        )
        for button, kind in (
            (self.mods_choice, KIND_MOD),
            (self.contraptions_choice, KIND_CONTRAPTION),
        ):
            button.setObjectName("SourceFilter")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, kind=kind: self._set_destination_kind(kind)
            )
            self.destination_group.addButton(button)
            destination_layout.addWidget(button)
        destination_layout.addStretch(1)
        self.destination_row.hide()
        layout.addWidget(self.destination_row)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.status = QLabel("", self)
        self.status.setObjectName("DialogSmall")
        self.status.hide()
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 4, 0, 0)
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def _clear_actions(self) -> None:
        while self.actions.count():
            item = self.actions.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_actions(
        self,
        primary: str | None = None,
        primary_slot=None,
        secondary: str | None = None,
        secondary_slot=None,
        cancel_text: str = "Cancel",
        cancel_slot=None,
        danger: bool = False,
    ) -> None:
        self._clear_actions()
        self.actions.addStretch(1)
        if secondary:
            button = QPushButton(secondary, self)
            button.setObjectName("SecondaryButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if secondary_slot:
                button.clicked.connect(secondary_slot)
            self.actions.addWidget(button)
        if cancel_text:
            cancel = QPushButton(cancel_text, self)
            cancel.setObjectName("SecondaryButton")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.clicked.connect(cancel_slot or self.reject)
            self.actions.addWidget(cancel)
        if primary:
            button = QPushButton(primary, self)
            button.setObjectName("DangerButton" if danger else "PrimaryButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if primary_slot:
                button.clicked.connect(primary_slot)
            self.actions.addWidget(button)

    def _set_busy(self, busy: bool, indeterminate: bool = False) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.status.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0 if indeterminate else 100)

    def _on_progress(self, value: int, text: str) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, value)))
        self.status.setText(text)
        self.status.show()

    def _on_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.show()

    def _destination_root(self) -> Path:
        if self._destination_kind == KIND_CONTRAPTION:
            return self.contraptions_root
        return self.mods_root

    def _set_destination_kind(self, kind: str) -> None:
        self._destination_kind = kind
        self._update_destination_label()

    def _update_destination_label(self) -> None:
        root = self._destination_root()
        self.target.setText(f"Destination  ·  {kind_folder_name(self._destination_kind)}  ·  {root}")
        self.mods_choice.setChecked(self._destination_kind == KIND_MOD)
        self.contraptions_choice.setChecked(self._destination_kind == KIND_CONTRAPTION)

    def _start(self, kind: str, function) -> None:
        self._cancel_event.clear()
        self._task_kind = kind
        task = Task(function)
        self._task = task
        task.signals.progress.connect(self._on_progress)
        task.signals.status.connect(self._on_status)
        task.signals.done.connect(self._on_task_done)
        task.signals.error.connect(self._on_task_error)
        self._set_busy(True, indeterminate=kind == "resolve")
        QThreadPool.globalInstance().start(task)

    def _on_task_done(self, result) -> None:
        self._task = None
        kind = self._task_kind
        self._task_kind = ""
        if kind == "resolve":
            self._resolved(result)
        elif kind == "prepare":
            self._prepared_ready(result)
        elif kind == "extract":
            self._installed(result)

    def _on_task_error(self, message: str) -> None:
        self._task = None
        kind = self._task_kind
        self._task_kind = ""
        self._set_busy(False)
        if kind == "prepare" and self._prepared and self._prepared.cleanup:
            try:
                self._prepared.archive.unlink()
            except OSError:
                pass
            self._prepared = None
        if "cancel" in message.lower():
            self._show_cancelled()
            return
        if kind == "prepare":
            lowered = message.lower()
            self._show_error(
                message,
                not_a_mod=(
                    "not a mods-folder" in lowered
                    or "not a people playground mod" in lowered
                ),
            )
        elif kind == "extract":
            self._show_error(message)
        else:
            self._show_resolution_failed(message)

    # ------------------------------------------------------------------
    # States
    # ------------------------------------------------------------------
    def _header(self, kicker: str, title: str, meta: str = "") -> None:
        self.kicker.setText(kicker)
        self.title.setText(title)
        self.meta.setText(meta)
        self.meta.setVisible(bool(meta))
        self.destination_row.hide()

    def _show_direct_ready(self) -> None:
        mod = self.mod
        if mod is None:
            return
        self._header(
            "READY TO INSTALL",
            mod.title,
            "  ·  ".join(
                bit
                for bit in (
                    mod.author,
                    f"PP {mod.game_version}" if mod.game_version else "",
                    f"v{mod.version}" if mod.version else "",
                )
                if bit
            ),
        )
        self.body.setText(
            "The app will download the original ZIP, check its contents, and "
            "extract it into the right People Playground folder. Mods go to "
            "Mods and contraptions go to Contraptions. Existing files outside "
            "those two folders are never touched."
        )
        self.progress.hide()
        self.status.hide()
        self._set_actions(
            "Install", self._begin_download,
            "Open page", lambda: open_external(mod.url),
        )

    def _show_external(self, message: str = "") -> None:
        mod = self.mod
        url = self._page_urls[0] if self._page_urls else (mod.url if mod else "")
        title = mod.title if mod else "Install a downloaded ZIP"
        self._header(
            "ORIGINAL SOURCE",
            title,
            (mod.author if mod else "") or "",
        )
        if not message:
            if mod and mod.install_mode == "external":
                message = (
                    "This mod is downloaded from Switch Studio and may require "
                    "their account or license. Open the source page in your "
                    "browser, or import the ZIP after downloading it."
                )
            else:
                message = (
                    "The original host protects its download page with a browser "
                    "check. Open the download page, then use “Install from ZIP…” "
                    "to place the archive in the correct folder."
                )
        self.body.setText(message)
        self.progress.hide()
        self.status.hide()
        self._set_actions(
            "Open download page" if url else None,
            (lambda: open_external(url)) if url else None,
            "Install from ZIP…", self._choose_zip,
        )

    def _show_local_prompt(self) -> None:
        self._header(
            "LOCAL ARCHIVE",
            "Install a downloaded ZIP",
            "The archive stays on your computer.",
        )
        self.body.setText(
            "Choose a People Playground ZIP. The app checks the archive for "
            "unsafe paths and works out whether it is a mod or a contraption "
            "before extracting it into the matching folder."
        )
        self.progress.hide()
        self.status.hide()
        self._set_actions(
            "Choose ZIP…", self._choose_zip,
        )

    def _show_resolving(self) -> None:
        mod = self.mod
        self._header(
            "CHECKING SOURCE",
            mod.title if mod else "Resolving download",
            (mod.author if mod else "") or "",
        )
        self.body.setText(
            "Looking for a direct archive on the original source page. Some "
            "download hosts require a browser check; in that case the app will "
            "offer the original page and ZIP import instead."
        )
        self._set_actions()

    def _show_cancelled(self) -> None:
        self._header("INSTALLATION", "Cancelled", "")
        self.body.setText("Nothing was changed.")
        self._set_actions(
            "Close", self.reject, "Open source page",
            (lambda: open_external(self.mod.url)) if self.mod else None,
            cancel_text="",
        )

    def _show_error(self, message: str, not_a_mod: bool = False) -> None:
        self._header("INSTALLATION", "Could not install", "")
        if not_a_mod:
            message = (
                message
                + "\n\nContent that replaces files in the game folder must be "
                "installed manually from its own page. Playground Mods only "
                "writes inside the Mods and Contraptions folders."
            )
        self.body.setText(message)
        self._set_actions(
            "Open source page" if self.mod else None,
            (lambda: open_external(self.mod.url)) if self.mod else None,
            "Try another ZIP", self._choose_zip,
            cancel_text="Close",
        )

    def _show_resolution_failed(self, message: str) -> None:
        self._header("DOWNLOAD SOURCE", "Browser required", "")
        self.body.setText(message)
        self._set_actions(
            "Open download page",
            lambda: open_external(self._page_urls[0] if self._page_urls else (self.mod.url if self.mod else "")),
            "Install from ZIP…", self._choose_zip,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _resolve_top(self) -> None:
        if self.mod is None:
            return
        self._start(
            "resolve",
            lambda: self.service.resolve_top_download(self.mod),
        )

    def _resolved(self, result: ResolvedDownload) -> None:
        self._set_busy(False)
        self._page_urls = result.page_urls
        if result.direct_url:
            self.body.setText(
                "A direct ZIP link is available. The app will verify the archive "
                "and extract it into the matching folder — Mods or Contraptions."
            )
            self._set_actions(
                "Install", lambda: self._begin_download(result.direct_url),
                "Open page", lambda: open_external(self.mod.url if self.mod else ""),
            )
        else:
            self._show_external(result.message)

    def _begin_download(self, direct_url: str | None = None) -> None:
        if self.mod is None:
            self._choose_zip()
            return
        url = direct_url or self.mod.download_url
        if not url:
            self._show_external()
            return
        self._header(
            "INSTALLING",
            self.mod.title,
            self.mod.source,
        )
        self.body.setText("Downloading the original archive from the source.")
        self.status.setText("Starting download…")
        self.status.show()
        self._set_actions(cancel_text="Cancel", cancel_slot=self._cancel)
        self._start(
            "prepare",
            lambda progress=None: prepare_download(
                url,
                self.mod.title,
                cancelled=self._cancel_event.is_set,
                progress=progress,
            ),
        )

    def _choose_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a People Playground mod ZIP",
            str(Path.home() / "Downloads"),
            "ZIP archives (*.zip);;All files (*)",
        )
        if path:
            self._begin_local(Path(path))

    def _begin_local(self, path: Path) -> None:
        self._header(
            "CHECKING ARCHIVE",
            path.name,
            "Local file",
        )
        self.body.setText("Checking the archive contents…")
        self._set_actions(cancel_text="Cancel", cancel_slot=self._cancel)
        self._start(
            "prepare",
            lambda progress=None: prepare_local_archive(
                path,
                self.mod.title if self.mod else path.stem,
                progress=progress,
            ),
        )

    def _prepared_ready(self, prepared: PreparedInstall) -> None:
        self._prepared = prepared
        self._set_busy(False)
        self._set_destination_kind(prepared.kind)
        size_text = f"{prepared.total_size / (1024 * 1024):.1f} MB"
        self._header(
            f"READY TO INSTALL  ·  {prepared.kind_label.upper()}",
            prepared.folder_name,
            size_text,
        )
        self.destination_row.show()
        self.body.setText(
            f"The archive contains {prepared.file_count} files and looks like a "
            f"{prepared.kind_label.lower()}. It will be installed as "
            f"“{prepared.folder_name}” inside the {prepared.folder_kind_name} "
            "folder. Use the buttons above to send it to the other folder if "
            "the detection is wrong."
        )
        self._set_actions(
            "Install now", self._extract,
            "Cancel", self._cancel_discard,
        )

    def _extract(self) -> None:
        if not self._prepared:
            return
        prepared = self._prepared
        destination = self._destination_root()
        final = destination / sanitize_folder_name(prepared.folder_name)
        overwrite = False
        if final.exists():
            answer = QMessageBox.question(
                self,
                "Replace existing folder?",
                f"A folder named “{prepared.folder_name}” already exists in the "
                f"{kind_folder_name(self._destination_kind)} folder.\n\nReplace "
                "it with this version? The old folder will be backed up until "
                "the new copy is complete.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self._header("INSTALLING", prepared.folder_name, "")
        self.body.setText(
            "Extracting the verified files into the "
            f"{kind_folder_name(self._destination_kind)} folder."
        )
        self._set_actions(cancel_text="Cancel", cancel_slot=self._cancel)
        self._start(
            "extract",
            lambda progress=None: extract_prepared(
                prepared,
                self.mods_root,
                overwrite=overwrite,
                cancelled=self._cancel_event.is_set,
                destination_root=destination,
                progress=progress,
            ),
        )

    def _installed(self, folder: Path) -> None:
        self._set_busy(False)
        folder = Path(folder)
        mod = self.mod
        prepared = self._prepared
        kind = self._destination_kind
        uid = mod.uid if mod else f"local:{folder.name}"
        title = mod.title if mod else (prepared.title_hint if prepared else folder.name)
        self.records[uid] = {
            "folder": folder.name,
            "title": title,
            "source": mod.source if mod else "Local ZIP",
            "url": mod.url if mod else "",
            "kind": kind,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.save_installed(self.records)
        if prepared and prepared.cleanup:
            try:
                prepared.archive.unlink()
            except OSError:
                pass
        self.installed_changed.emit()

        folder_name = kind_folder_name(kind)
        self._header(
            "INSTALLED",
            "Ready to spawn.",
            f"{kind_label(kind)} · {folder.name}",
        )
        self.body.setText(
            f"{title} is now inside the People Playground {folder_name} folder."
            "\n\nNo game settings were changed. Restart or refresh the game's "
            f"{'mods' if kind == KIND_MOD else 'contraptions'} list to load it."
        )
        self.target.setText(f"Installed to  ·  {folder}")
        self.destination_row.hide()
        self.progress.hide()
        self.status.hide()
        self._set_actions(
            f"Open {folder_name} folder",
            lambda: open_external(QUrl.fromLocalFile(str(folder.parent)).toString()),
            "Done", self.accept,
            cancel_text="",
        )

    def _cancel(self) -> None:
        if self._busy:
            self._cancel_event.set()
            self.status.setText("Cancelling…")
            self.progress.setRange(0, 0)
        else:
            self.reject()

    def _cancel_discard(self) -> None:
        if self._prepared and self._prepared.cleanup:
            try:
                self._prepared.archive.unlink()
            except OSError:
                pass
        self._prepared = None
        self.reject()

    def reject(self) -> None:  # type: ignore[override]
        if self._busy:
            self._cancel_event.set()
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._busy:
            self._cancel_event.set()
        super().closeEvent(event)
