from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..images import ImageLoader
from ..models import Idea, Mod, Post, SiteConfig, SiteMeta
from ..sources import CatalogueService
from ..workers import Task
from .dialogs import open_external
from .widgets import (
    CoverLabel,
    format_metric,
    markdown_to_html,
    strip_markdown,
    time_ago,
)

SITE_BASE = "https://deswitchstudio.com"
IDEA_STATUS = {
    "open": "Open",
    "planned": "Planned",
    "in-progress": "In progress",
    "done": "Done",
    "rejected": "Rejected",
}


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)


def _add_section(
    parent_layout: QVBoxLayout,
    parent: QWidget,
    title: str,
    caption: str = "",
) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(parent)
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


def _bullet(text: str, parent: QWidget) -> QLabel:
    label = QLabel(f"•  {text}", parent)
    label.setObjectName("BulletText")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _scroll_body(dialog: QDialog, outer: QVBoxLayout) -> QVBoxLayout:
    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget(scroll)
    body = QVBoxLayout(content)
    body.setContentsMargins(26, 16, 26, 24)
    body.setSpacing(14)
    scroll.setWidget(content)
    outer.addWidget(scroll, 1)
    return body


def _footer(dialog: QDialog, outer: QVBoxLayout) -> QHBoxLayout:
    bar = QWidget(dialog)
    bar.setObjectName("CommunityFooter")
    row = QHBoxLayout(bar)
    row.setContentsMargins(26, 10, 26, 12)
    row.setSpacing(8)
    row.addStretch(1)
    close = QPushButton("Close", bar)
    close.setObjectName("SecondaryButton")
    close.setCursor(Qt.CursorShape.PointingHandCursor)
    close.clicked.connect(dialog.reject)
    row.addWidget(close)
    outer.addWidget(bar)
    return row


def _button(
    text: str,
    url: str,
    parent: QWidget,
    object_name: str = "SecondaryButton",
) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda: open_external(url))
    return button


class GettingStartedDialog(QDialog):
    install_patch = Signal()
    browse_requested = Signal()
    import_requested = Signal()

    def __init__(
        self,
        config: SiteConfig,
        patch_mod: Mod | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.patch_mod = patch_mod
        self.setWindowTitle("How to start")
        self.setModal(True)
        self.resize(760, 640)
        self.setMinimumSize(620, 500)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 12)
        header_layout.setSpacing(5)
        kicker = QLabel("HOW TO START", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel("Mods in three steps", header)
        title.setObjectName("DialogTitle")
        header_layout.addWidget(title)
        sub = QLabel(
            "People Playground needs one patch mod before community content "
            "shows up. After that, installs are handled by this app.",
            header,
        )
        sub.setObjectName("DialogText")
        sub.setWordWrap(True)
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)

        step_one, one_layout = self._step(
            body,
            "1",
            f"Install {config.patch_title or 'deSwitcher'}",
            "The patch mod restores the in-game mods list after a People "
            "Playground update. Install it once, then keep it updated.",
        )
        one_actions = QHBoxLayout()
        one_actions.setContentsMargins(0, 0, 0, 0)
        one_actions.setSpacing(8)
        if patch_mod is not None:
            install = QPushButton(f"Install {config.patch_title or 'deSwitcher'}", step_one)
            install.setObjectName("PrimaryButton")
            install.setCursor(Qt.CursorShape.PointingHandCursor)
            install.clicked.connect(self._install_patch)
            one_actions.addWidget(install)
        elif config.patch_url:
            one_actions.addWidget(
                _button(
                    f"Open {config.patch_title or 'deSwitcher'} page",
                    config.patch_url,
                    step_one,
                    "PrimaryButton",
                )
            )
        if config.patch_guide:
            one_actions.addWidget(
                _button("Watch the guide", config.patch_guide, step_one)
            )
        one_actions.addStretch(1)
        one_layout.addLayout(one_actions)

        step_two, two_layout = self._step(
            body,
            "2",
            "Pick a mod or contraption",
            "Browse both catalogues, filter by tags, access or source, and open "
            "a card to read the description, changelog and comments. Not sure "
            "what to play? Use Random mod.",
        )
        browse = QPushButton("Browse catalogue", step_two)
        browse.setObjectName("SecondaryButton")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)
        two_layout.addWidget(browse, 0, Qt.AlignmentFlag.AlignLeft)

        step_three, three_layout = self._step(
            body,
            "3",
            "Install and restart the game",
            "The app checks the archive and places mods in Mods and "
            "contraptions in Contraptions. Restart People Playground or refresh "
            "its content list. No game settings are changed.",
        )
        zip_button = QPushButton("Install from ZIP…", step_three)
        zip_button.setObjectName("SecondaryButton")
        zip_button.setCursor(Qt.CursorShape.PointingHandCursor)
        zip_button.clicked.connect(self._import)
        three_layout.addWidget(zip_button, 0, Qt.AlignmentFlag.AlignLeft)

        safety, safety_layout = _add_section(
            body,
            self,
            "Only two folders are touched",
            "Playground Mods never edits game settings, saves or the rest of "
            "the install.",
        )
        safety_layout.addWidget(
            _bullet(
                "Mods go to the game's Mods folder; contraptions go to Contraptions.",
                safety,
            )
        )
        safety_layout.addWidget(
            _bullet(
                "The archive is inspected before extraction, so a mislabelled "
                "download still lands in the right place.",
                safety,
            )
        )
        safety_layout.addWidget(
            _bullet(
                "Mods can run C# code. Only install content from authors you trust.",
                safety,
            )
        )
        body.addStretch(1)
        _footer(self, outer)

    def _step(
        self, body: QVBoxLayout, number: str, title: str, text: str
    ) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(self)
        frame.setObjectName("StepCard")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        mark = QLabel(number, frame)
        mark.setObjectName("StepNumber")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        heading = QLabel(title, frame)
        heading.setObjectName("StepTitle")
        heading.setWordWrap(True)
        content.addWidget(heading)
        note = QLabel(text, frame)
        note.setObjectName("StepText")
        note.setWordWrap(True)
        content.addWidget(note)
        row.addLayout(content, 1)
        body.addWidget(frame)
        return frame, content

    def _install_patch(self) -> None:
        self.accept()
        self.install_patch.emit()

    def _browse(self) -> None:
        self.accept()
        self.browse_requested.emit()

    def _import(self) -> None:
        self.accept()
        self.import_requested.emit()


class PostStripCard(QFrame):
    """Compact lab-log card used on the catalogue home page."""

    clicked = Signal(object)

    def __init__(self, post: Post, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.post = post
        self.setObjectName("PostCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(116)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(4)
        kicker = QLabel("LAB LOG", self)
        kicker.setObjectName("PostCardKicker")
        layout.addWidget(kicker)
        title = QLabel(post.title, self)
        title.setObjectName("PostCardTitle")
        title.setWordWrap(True)
        title.setFixedHeight(34)
        layout.addWidget(title)
        summary = QLabel(post.summary or "Read the latest update.", self)
        summary.setObjectName("PostCardSummary")
        summary.setWordWrap(True)
        summary.setFixedHeight(32)
        layout.addWidget(summary)
        meta_bits = [post.author, time_ago(post.created_at)]
        if post.views:
            meta_bits.append(f"{format_metric(post.views)} views")
        meta = QLabel("  ·  ".join(bit for bit in meta_bits if bit), self)
        meta.setObjectName("PostCardMeta")
        layout.addWidget(meta)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.post)
        super().mouseReleaseEvent(event)


class PostRow(QFrame):
    clicked = Signal(object)

    def __init__(
        self, post: Post, loader: ImageLoader, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.post = post
        self.setObjectName("PostRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 12, 10)
        layout.setSpacing(12)
        self.image = CoverLabel(post.title, radius=7, parent=self, max_source=300)
        self.image.setFixedSize(142, 84)
        self.image.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.image)
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        title = QLabel(post.title, self)
        title.setObjectName("PostTitle")
        title.setWordWrap(True)
        body.addWidget(title)
        summary = QLabel(post.summary or "Read the full post.", self)
        summary.setObjectName("PostSummary")
        summary.setWordWrap(True)
        summary.setFixedHeight(30)
        body.addWidget(summary)
        meta_bits = [post.author, time_ago(post.created_at)]
        if post.views:
            meta_bits.append(f"{format_metric(post.views)} views")
        if post.comments:
            meta_bits.append(f"{format_metric(post.comments)} comments")
        meta = QLabel("  ·  ".join(bit for bit in meta_bits if bit), self)
        meta.setObjectName("PostMeta")
        body.addWidget(meta)
        body.addStretch(1)
        layout.addLayout(body, 1)
        read = QPushButton("Read", self)
        read.setObjectName("SecondaryButton")
        read.setCursor(Qt.CursorShape.PointingHandCursor)
        read.clicked.connect(lambda: self.clicked.emit(self.post))
        layout.addWidget(read, 0, Qt.AlignmentFlag.AlignVCenter)
        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        if post.cover:
            loader.load(post.cover)
        else:
            self._image_failed(post.cover)

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self.post.cover:
            self.image.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if url == self.post.cover:
            self.image.set_cover(None)
            self.image.set_placeholder(self.post.title)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.post)
        super().mouseReleaseEvent(event)


class PostsDialog(QDialog):
    def __init__(
        self,
        service: CatalogueService,
        loader: ImageLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.loader = loader
        self._task: Task | None = None
        self._closed = False
        self.setWindowTitle("Lab log")
        self.setModal(True)
        self.resize(800, 680)
        self.setMinimumSize(640, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(4)
        kicker = QLabel("LAB LOG", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel("News from the lab", header)
        title.setObjectName("DialogTitle")
        header_layout.addWidget(title)
        sub = QLabel(
            "Devlogs, releases and site updates from Switch Studio.",
            header,
        )
        sub.setObjectName("DialogText")
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        self.status = QLabel("Loading the lab log…", self)
        self.status.setObjectName("LoadingNote")
        body.addWidget(self.status)
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        body.addLayout(self.list_layout)
        body.addStretch(1)

        footer = _footer(self, outer)
        open_button = _button("Open lab log on the site", f"{SITE_BASE}/", footer.parentWidget())
        footer.insertWidget(0, open_button)
        QTimer.singleShot(0, self._load)

    def _load(self) -> None:
        task = Task(lambda: self.service.fetch_posts(1))
        task.signals.done.connect(self._loaded)
        task.signals.error.connect(self._failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _loaded(self, result: tuple) -> None:
        self._task = None
        if self._closed:
            return
        posts, pages = result
        self.status.hide()
        _clear_layout(self.list_layout)
        if not posts:
            empty = QLabel("No lab log posts were published yet.", self)
            empty.setObjectName("EmptyState")
            self.list_layout.addWidget(empty)
            return
        for post in posts:
            row = PostRow(post, self.loader, self)
            row.clicked.connect(self._open_post)
            self.list_layout.addWidget(row)
        if pages > 1:
            more = _button("Read older posts on the site", f"{SITE_BASE}/", self)
            self.list_layout.addWidget(more)

    def _failed(self, message: str) -> None:
        self._task = None
        if self._closed:
            return
        self.status.setText(
            f"Could not load the lab log: {message}. Open the site to read it."
        )
        self.status.show()

    def _open_post(self, post: Post) -> None:
        dialog = PostDetailDialog(post, self.service, self.loader, self)
        dialog.exec()

    def done(self, result: int) -> None:  # type: ignore[override]
        self._closed = True
        super().done(result)


class PostDetailDialog(QDialog):
    def __init__(
        self,
        post: Post,
        service: CatalogueService,
        loader: ImageLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.post = post
        self.service = service
        self.loader = loader
        self._task: Task | None = None
        self._closed = False
        self.setWindowTitle(post.title)
        self.setModal(True)
        self.resize(780, 700)
        self.setMinimumSize(620, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 20, 26, 10)
        header_layout.setSpacing(5)
        self.cover = CoverLabel(post.title, radius=9, parent=header, max_source=900)
        self.cover.setFixedHeight(190)
        header_layout.addWidget(self.cover)
        kicker = QLabel("LAB LOG", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel(post.title, header)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        header_layout.addWidget(title)
        meta_bits = [post.author, time_ago(post.created_at)]
        if post.views:
            meta_bits.append(f"{format_metric(post.views)} views")
        if post.comments:
            meta_bits.append(f"{format_metric(post.comments)} comments")
        meta = QLabel("  ·  ".join(bit for bit in meta_bits if bit), header)
        meta.setObjectName("DialogSmall")
        header_layout.addWidget(meta)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        self.body_label = QLabel(self)
        self.body_label.setObjectName("DetailText")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(Qt.TextFormat.RichText)
        self.body_label.setOpenExternalLinks(True)
        self.body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.body_label.setText(markdown_to_html(post.body or post.summary))
        body.addWidget(self.body_label)
        self.status = QLabel("", self)
        self.status.setObjectName("LoadingNote")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        body.addStretch(1)

        footer = _footer(self, outer)
        footer.insertWidget(
            0,
            _button("Open post on the site", f"{SITE_BASE}/", footer.parentWidget()),
        )
        loader.ready.connect(self._image_ready)
        loader.failed.connect(self._image_failed)
        if post.cover:
            loader.load(post.cover)
        else:
            self._image_failed(post.cover)
        if not post.body and post.slug:
            self.status.setText("Loading the full post…")
            QTimer.singleShot(0, self._load)

    def _load(self) -> None:
        task = Task(lambda: self.service.fetch_post(self.post.slug))
        task.signals.done.connect(self._loaded)
        task.signals.error.connect(self._failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _loaded(self, post: Post) -> None:
        self._task = None
        if self._closed:
            return
        self.post = post
        self.status.hide()
        self.body_label.setText(markdown_to_html(post.body or post.summary))
        if post.cover and not self.cover._source:
            self.loader.load(post.cover)

    def _failed(self, message: str) -> None:
        self._task = None
        if self._closed:
            return
        self.status.setText(
            f"Could not load the full post: {message}. Open the site to read it."
        )

    def _image_ready(self, url: str, pixmap: QPixmap) -> None:
        if url == self.post.cover:
            self.cover.set_cover(pixmap)

    def _image_failed(self, url: str) -> None:
        if url == self.post.cover:
            self.cover.set_cover(None)
            self.cover.set_placeholder(self.post.title)

    def done(self, result: int) -> None:  # type: ignore[override]
        self._closed = True
        super().done(result)


class IdeaRow(QFrame):
    clicked = Signal(object)

    def __init__(self, idea: Idea, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.idea = idea
        self.setObjectName("IdeaRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        votes = QWidget(self)
        votes_layout = QVBoxLayout(votes)
        votes_layout.setContentsMargins(0, 0, 0, 0)
        votes_layout.setSpacing(0)
        count = QLabel(str(idea.votes), votes)
        count.setObjectName("IdeaVotes")
        count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption = QLabel("votes", votes)
        caption.setObjectName("IdeaVotesCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        votes_layout.addWidget(count)
        votes_layout.addWidget(caption)
        votes.setFixedWidth(48)
        layout.addWidget(votes, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(7)
        title = QLabel(idea.title, self)
        title.setObjectName("IdeaTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        status = QLabel(IDEA_STATUS.get(idea.status, idea.status.title()), self)
        status.setObjectName("StatusBadge")
        status.setProperty("status", idea.status)
        top.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)
        snippet = strip_markdown(idea.body)
        if snippet:
            text = QLabel(snippet[:180] + ("…" if len(snippet) > 180 else ""), self)
            text.setObjectName("IdeaBody")
            text.setWordWrap(True)
            text.setFixedHeight(34)
            body.addWidget(text)
        meta_bits = [idea.author, time_ago(idea.created_at)]
        if idea.comments:
            noun = "comment" if idea.comments == 1 else "comments"
            meta_bits.append(f"{format_metric(idea.comments)} {noun}")
        meta = QLabel("  ·  ".join(bit for bit in meta_bits if bit), self)
        meta.setObjectName("IdeaMeta")
        body.addWidget(meta)
        layout.addLayout(body, 1)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.idea)
        super().mouseReleaseEvent(event)


class IdeasDialog(QDialog):
    mod_requested = Signal(object)

    def __init__(
        self,
        service: CatalogueService,
        mod_lookup: Callable[[str], Mod | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.mod_lookup = mod_lookup
        self.tab = "top"
        self._cache: dict[str, list[Idea]] = {}
        self._task: Task | None = None
        self._task_tab = ""
        self._closed = False
        self.setWindowTitle("Ideas")
        self.setModal(True)
        self.resize(820, 700)
        self.setMinimumSize(660, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(4)
        kicker = QLabel("COMMUNITY IDEAS", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel("What should the lab build next?", header)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        header_layout.addWidget(title)
        sub = QLabel(
            "The most requested ideas from the Switch Studio community. Voting "
            "and new suggestions happen on the site.",
            header,
        )
        sub.setObjectName("DialogText")
        sub.setWordWrap(True)
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        tabs = QWidget(self)
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(26, 10, 26, 4)
        tabs_layout.setSpacing(7)
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("top", "Top"),
            ("new", "New"),
            ("planned", "Planned"),
            ("done", "Done"),
        ):
            button = QPushButton(label, tabs)
            button.setObjectName("KindPill")
            button.setCheckable(True)
            button.setChecked(key == self.tab)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, key=key: self._set_tab(key))
            self.tab_buttons[key] = button
            tabs_layout.addWidget(button)
        tabs_layout.addStretch(1)
        outer.addWidget(tabs)

        body = _scroll_body(self, outer)
        self.status = QLabel("Loading ideas…", self)
        self.status.setObjectName("LoadingNote")
        body.addWidget(self.status)
        self.list_layout = QVBoxLayout()
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        body.addLayout(self.list_layout)
        body.addStretch(1)

        footer = _footer(self, outer)
        footer.insertWidget(
            0, _button("Open ideas on the site", f"{SITE_BASE}/ideas", footer.parentWidget())
        )
        QTimer.singleShot(0, self._load)

    def _set_tab(self, tab: str) -> None:
        if tab == self.tab and self._cache.get(tab):
            return
        self.tab = tab
        for key, button in self.tab_buttons.items():
            button.setChecked(key == tab)
        if tab in self._cache:
            self.status.hide()
            self._render(self._cache[tab])
            return
        self.status.setText("Loading ideas…")
        self.status.show()
        _clear_layout(self.list_layout)
        self._load()

    def _load(self) -> None:
        tab = self.tab
        self._task_tab = tab
        task = Task(lambda: self.service.fetch_ideas(tab))
        task.signals.done.connect(lambda ideas, tab=tab: self._loaded(tab, ideas))
        task.signals.error.connect(self._failed)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _loaded(self, tab: str, ideas: list[Idea]) -> None:
        self._task = None
        if self._closed:
            return
        self._cache[tab] = list(ideas)
        if tab != self.tab:
            return
        self.status.hide()
        self._render(ideas)

    def _render(self, ideas: list[Idea]) -> None:
        _clear_layout(self.list_layout)
        if not ideas:
            empty = QLabel("No ideas in this tab yet.", self)
            empty.setObjectName("EmptyState")
            self.list_layout.addWidget(empty)
            return
        for idea in ideas:
            row = IdeaRow(idea, self)
            row.clicked.connect(self._open_idea)
            self.list_layout.addWidget(row)

    def _failed(self, message: str) -> None:
        self._task = None
        if self._closed:
            return
        self.status.setText(
            f"Could not load ideas: {message}. Open the site to browse them."
        )
        self.status.show()

    def _open_idea(self, idea: Idea) -> None:
        dialog = IdeaDetailDialog(
            idea, self.service, self.mod_lookup, self
        )
        dialog.mod_requested.connect(self._mod_requested)
        dialog.exec()

    def _mod_requested(self, mod: Mod) -> None:
        self.accept()
        self.mod_requested.emit(mod)

    def done(self, result: int) -> None:  # type: ignore[override]
        self._closed = True
        super().done(result)


class IdeaDetailDialog(QDialog):
    mod_requested = Signal(object)

    def __init__(
        self,
        idea: Idea,
        service: CatalogueService,
        mod_lookup: Callable[[str], Mod | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.idea = idea
        self.service = service
        self.mod_lookup = mod_lookup
        self._task: Task | None = None
        self._closed = False
        self.setWindowTitle(idea.title)
        self.setModal(True)
        self.resize(680, 620)
        self.setMinimumSize(560, 460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(5)
        kicker = QLabel("COMMUNITY IDEA", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel(idea.title, header)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        header_layout.addWidget(title)
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(7)
        status = QLabel(IDEA_STATUS.get(idea.status, idea.status.title()), header)
        status.setObjectName("StatusBadge")
        status.setProperty("status", idea.status)
        meta_row.addWidget(status)
        votes = QLabel(f"▲  {idea.votes} votes", header)
        votes.setObjectName("DialogSmall")
        meta_row.addWidget(votes)
        author = QLabel(
            "  ·  ".join(
                bit for bit in (idea.author, time_ago(idea.created_at)) if bit
            ),
            header,
        )
        author.setObjectName("DialogSmall")
        meta_row.addWidget(author)
        meta_row.addStretch(1)
        header_layout.addLayout(meta_row)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        body_label = QLabel(self)
        body_label.setObjectName("DetailText")
        body_label.setWordWrap(True)
        body_label.setTextFormat(Qt.TextFormat.RichText)
        body_label.setOpenExternalLinks(True)
        body_label.setText(markdown_to_html(idea.body or "No description provided."))
        body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        body.addWidget(body_label)
        if idea.mod_slug:
            made, made_layout = _add_section(
                body, self, "This idea became a mod", idea.mod_title or idea.mod_slug
            )
            target = self.mod_lookup(idea.mod_slug) if self.mod_lookup else None
            if target is not None:
                open_mod = QPushButton(f"Open {target.title}", made)
                open_mod.setObjectName("PrimaryButton")
                open_mod.setCursor(Qt.CursorShape.PointingHandCursor)
                open_mod.clicked.connect(lambda: self._request_mod(target))
                made_layout.addWidget(open_mod, 0, Qt.AlignmentFlag.AlignLeft)
            else:
                made_layout.addWidget(
                    _button(
                        "Open the mod page",
                        f"{SITE_BASE}/mod/{idea.mod_slug}",
                        made,
                    ),
                    0,
                    Qt.AlignmentFlag.AlignLeft,
                )
        note, note_layout = _add_section(
            body,
            self,
            "Voting and replies",
            "Voting and new suggestions require a Switch Studio account, so they "
            "are handled on the site.",
        )
        if idea.comments:
            note_layout.addWidget(
                QLabel(f"{idea.comments} comments on the site.", note)
            )
        body.addStretch(1)

        footer = _footer(self, outer)
        footer.insertWidget(
            0,
            _button(
                "Open idea on the site",
                f"{SITE_BASE}/ideas",
                footer.parentWidget(),
            ),
        )

    def _request_mod(self, mod: Mod) -> None:
        self.accept()
        self.mod_requested.emit(mod)

    def done(self, result: int) -> None:  # type: ignore[override]
        self._closed = True
        super().done(result)


class AboutDialog(QDialog):
    def __init__(self, meta: SiteMeta, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.meta = meta
        config = meta.config
        self.setWindowTitle("About and safety")
        self.setModal(True)
        self.resize(800, 720)
        self.setMinimumSize(640, 540)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(4)
        kicker = QLabel("ABOUT", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel(config.site_name, header)
        title.setObjectName("DialogTitle")
        header_layout.addWidget(title)
        sub = QLabel(
            f"{config.tagline} · game version {config.current_game_version}",
            header,
        )
        sub.setObjectName("DialogText")
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        intro, intro_layout = _add_section(
            body,
            self,
            "A mod hub for People Playground",
            "The Steam Workshop is back, but the game does not officially "
            "support mods there yet, so community mods are collected here.",
        )
        intro_layout.addWidget(
            _bullet(
                f"{config.site_name} publishes free and paid mods, devlogs and "
                "community ideas.",
                intro,
            )
        )
        intro_layout.addWidget(
            _bullet(
                "This desktop app reads the public catalogue and installs "
                "archives into your game folders.",
                intro,
            )
        )

        if config.team:
            team, team_layout = _add_section(
                body, self, "Who made it", "The people behind the site."
            )
            for person in config.team:
                row = QFrame(team)
                row.setObjectName("TeamRow")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(10)
                name = QLabel(str(person.get("name") or "Unknown"), row)
                name.setObjectName("TeamName")
                row_layout.addWidget(name)
                roles = QLabel(
                    " · ".join(str(role) for role in person.get("roles") or []),
                    row,
                )
                roles.setObjectName("TeamRoles")
                row_layout.addWidget(roles, 1)
                url = str(person.get("url") or "")
                if url:
                    row_layout.addWidget(_button("Channel", url, row))
                team_layout.addWidget(row)

        patch, patch_layout = _add_section(
            body,
            self,
            f"The {config.patch_title or 'deSwitcher'} patch",
            "Restores the in-game mods list after a People Playground update. "
            "Install it once and keep it updated.",
        )
        patch_actions = QHBoxLayout()
        patch_actions.setContentsMargins(0, 0, 0, 0)
        patch_actions.setSpacing(8)
        if config.patch_url:
            patch_actions.addWidget(
                _button(
                    f"Open {config.patch_title or 'deSwitcher'} page",
                    config.patch_url,
                    patch,
                    "PrimaryButton",
                )
            )
        if config.patch_guide:
            patch_actions.addWidget(
                _button("Watch the guide", config.patch_guide, patch)
            )
        patch_actions.addStretch(1)
        patch_layout.addLayout(patch_actions)

        safety, safety_layout = _add_section(
            body,
            self,
            "Safety",
            "A short checklist before installing anything.",
        )
        safety_layout.addWidget(
            _bullet(
                "Playground Mods only writes inside the game's Mods and "
                "Contraptions folders. It never changes settings or saves.",
                safety,
            )
        )
        safety_layout.addWidget(
            _bullet(
                "Mods can run C# code. Install from authors and sources you trust.",
                safety,
            )
        )
        safety_layout.addWidget(
            _bullet(
                "If a download looks wrong, report it to the site team instead "
                "of installing it.",
                safety,
            )
        )
        safety_layout.addWidget(
            _bullet(
                "Paid mods need a Switch Studio subscription or license. This "
                "app does not handle accounts or payments.",
                safety,
            )
        )

        links = config.links
        if links:
            link_section, link_layout = _add_section(
                body, self, "Links", "Official Switch Studio pages."
            )
            link_row = QHBoxLayout()
            link_row.setContentsMargins(0, 0, 0, 0)
            link_row.setSpacing(8)
            labels = {
                "discord": "Discord",
                "boosty": "Boosty",
                "patreon": "Patreon",
                "contact": "Contact",
            }
            for key, label in labels.items():
                url = str(links.get(key) or "")
                if url:
                    link_row.addWidget(_button(label, url, link_section))
            creator_url = str(config.creator.get("url") or "")
            if creator_url:
                link_row.addWidget(
                    _button(
                        f"{config.creator.get('name') or 'Creator'} on YouTube",
                        creator_url,
                        link_section,
                    )
                )
            link_row.addStretch(1)
            link_layout.addLayout(link_row)

        app_section, app_layout = _add_section(
            body,
            self,
            "About this desktop app",
            f"Playground Mods {__version__} · an unofficial companion for "
            f"{config.site_name}.",
        )
        app_layout.addWidget(
            _bullet(
                "The catalogue is cached locally, so the app opens instantly "
                "and still works offline.",
                app_section,
            )
        )
        app_layout.addWidget(
            _bullet(
                "Likes, follows and dismissed notices are stored on this "
                "computer only.",
                app_section,
            )
        )
        body.addStretch(1)
        _footer(self, outer)


class SubscriptionsDialog(QDialog):
    def __init__(self, meta: SiteMeta, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.meta = meta
        config = meta.config
        self.setWindowTitle("Subscriptions")
        self.setModal(True)
        self.resize(760, 660)
        self.setMinimumSize(620, 500)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(4)
        kicker = QLabel("SUPPORT THE LAB", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel("Subscriptions and paid mods", header)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        header_layout.addWidget(title)
        sub = QLabel(
            "Paid mods support the authors. Accounts, checkout and licenses "
            "are handled on the official site.",
            header,
        )
        sub.setObjectName("DialogText")
        sub.setWordWrap(True)
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        if config.tiers:
            tiers_layout = QHBoxLayout()
            tiers_layout.setContentsMargins(0, 0, 0, 0)
            tiers_layout.setSpacing(10)
            for tier in config.tiers:
                card = QFrame(self)
                card.setObjectName("TierCard")
                card.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
                )
                layout = QVBoxLayout(card)
                layout.setContentsMargins(15, 14, 15, 14)
                layout.setSpacing(6)
                name = QLabel(str(tier.get("name") or tier.get("id") or "Tier"), card)
                name.setObjectName("TierName")
                layout.addWidget(name)
                label = QLabel(
                    str(tier.get("modLabel") or "Paid mods"), card
                )
                label.setObjectName("TierPrice")
                layout.addWidget(label)
                for perk in tier.get("perks") or []:
                    layout.addWidget(_bullet(str(perk), card))
                layout.addStretch(1)
                tiers_layout.addWidget(card, 1)
            body.addLayout(tiers_layout)
        else:
            note, note_layout = _add_section(
                body,
                self,
                "Paid mods",
                "Some Switch Studio mods need a Basic or Pro subscription.",
            )
            note_layout.addWidget(
                _bullet(
                    "The catalogue marks paid mods and links to their source page.",
                    note,
                )
            )

        support, support_layout = _add_section(
            body,
            self,
            "Where to subscribe",
            "Subscriptions and one-off support are handled by the official pages.",
        )
        support_row = QHBoxLayout()
        support_row.setContentsMargins(0, 0, 0, 0)
        support_row.setSpacing(8)
        for key, label in (("boosty", "Boosty"), ("patreon", "Patreon")):
            url = str(config.links.get(key) or "")
            if url:
                support_row.addWidget(
                    _button(label, url, support, "PrimaryButton")
                )
        support_row.addStretch(1)
        support_layout.addLayout(support_row)

        if config.studios:
            studios, studios_layout = _add_section(
                body,
                self,
                "Partner studios",
                "Some catalogue entries come from partner studios with their "
                "own subscription pages.",
            )
            for studio in config.studios:
                row = QFrame(studios)
                row.setObjectName("TeamRow")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(10)
                name = QLabel(str(studio.get("name") or studio.get("slug") or "Studio"), row)
                name.setObjectName("TeamName")
                row_layout.addWidget(name)
                tiers = studio.get("tiers") if isinstance(studio.get("tiers"), list) else []
                if tiers:
                    names = ", ".join(
                        str(tier.get("name") or tier.get("id") or "")
                        for tier in tiers
                        if isinstance(tier, dict)
                    )
                    if names:
                        tier_label = QLabel(names, row)
                        tier_label.setObjectName("TeamRoles")
                        row_layout.addWidget(tier_label, 1)
                if studio.get("discordInvite"):
                    row_layout.addWidget(
                        _button("Discord", str(studio["discordInvite"]), row)
                    )
                if studio.get("patreon"):
                    row_layout.addWidget(
                        _button("Patreon", str(studio["patreon"]), row)
                    )
                studios_layout.addWidget(row)

        body.addStretch(1)
        footer = _footer(self, outer)
        footer.insertWidget(
            0,
            _button(
                "Open the site",
                SITE_BASE,
                footer.parentWidget(),
            ),
        )


class ReportDialog(QDialog):
    def __init__(
        self,
        links: dict[str, str],
        diagnostics: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.links = links
        self.diagnostics = diagnostics
        self.setWindowTitle("Report a problem")
        self.setModal(True)
        self.resize(700, 620)
        self.setMinimumSize(580, 480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(26, 22, 26, 10)
        header_layout.setSpacing(4)
        kicker = QLabel("REPORT", header)
        kicker.setObjectName("DialogKicker")
        header_layout.addWidget(kicker)
        title = QLabel("Report a problem", header)
        title.setObjectName("DialogTitle")
        header_layout.addWidget(title)
        sub = QLabel(
            "Broken mods, stolen content, unsafe files and site bugs all go to "
            "the Switch Studio team.",
            header,
        )
        sub.setObjectName("DialogText")
        sub.setWordWrap(True)
        header_layout.addWidget(sub)
        outer.addWidget(header)
        divider = QFrame(self)
        divider.setObjectName("DialogDivider")
        outer.addWidget(divider)

        body = _scroll_body(self, outer)
        report, report_layout = _add_section(
            body,
            self,
            "What to include",
            "A clear report gets fixed faster.",
        )
        report_layout.addWidget(
            _bullet("The mod or post link, and what went wrong.", report)
        )
        report_layout.addWidget(
            _bullet(
                "For unsafe files: the download source and why you think it is "
                "unsafe. Do not run it again.",
                report,
            )
        )
        report_layout.addWidget(
            _bullet(
                "For site bugs: what you clicked, what you expected and what "
                "happened.",
                report,
            )
        )
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        contact = str(links.get("contact") or "")
        if contact:
            actions.addWidget(
                _button("Message the team", contact, report, "PrimaryButton")
            )
        discord = str(links.get("discord") or "")
        if discord:
            actions.addWidget(_button("Join Discord", discord, report))
        actions.addWidget(
            _button("Open the report page", f"{SITE_BASE}/report", report)
        )
        actions.addStretch(1)
        report_layout.addLayout(actions)

        diagnostics_section, diagnostics_layout = _add_section(
            body,
            self,
            "App diagnostics",
            "Useful when the problem is in this desktop app. No personal data "
            "is included.",
        )
        box = QLabel(diagnostics, diagnostics_section)
        box.setObjectName("DiagnosticsBox")
        box.setWordWrap(True)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        diagnostics_layout.addWidget(box)
        copy_row = QHBoxLayout()
        copy_row.setContentsMargins(0, 0, 0, 0)
        copy_row.setSpacing(8)
        copy = QPushButton("Copy diagnostics", diagnostics_section)
        copy.setObjectName("SecondaryButton")
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.clicked.connect(self._copy)
        copy_row.addWidget(copy)
        self.copied = QLabel("", diagnostics_section)
        self.copied.setObjectName("DetailSectionCaption")
        copy_row.addWidget(self.copied)
        copy_row.addStretch(1)
        diagnostics_layout.addLayout(copy_row)
        body.addStretch(1)
        _footer(self, outer)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.diagnostics)
        self.copied.setText("Copied to the clipboard.")
