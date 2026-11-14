from __future__ import annotations

import logging
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..images import ImageLoader
from ..installer import (
    clean_old_downloads,
    remove_managed_mod,
    scan_installed,
)
from ..models import (
    KIND_CONTRAPTION,
    KIND_MOD,
    CatalogueResult,
    InstalledMod,
    Mod,
    Post,
    SiteMeta,
    kind_folder_name,
)
from ..paths import (
    contraptions_directory,
    detect_game_path,
    mods_directory,
)
from ..sources import CatalogueService
from ..store import Store
from ..workers import Task
from .community import (
    AboutDialog,
    GettingStartedDialog,
    IdeasDialog,
    PostDetailDialog,
    PostStripCard,
    PostsDialog,
    ReportDialog,
    SubscriptionsDialog,
)
from .dialogs import InstallDialog, ModDetailsDialog
from .widgets import (
    ChevronComboBox,
    FlowGrid,
    FreshCard,
    InstalledCard,
    ModCard,
    clear_thumbnail_queue,
    format_metric,
)

log = logging.getLogger(__name__)

PAGE_SIZE = 24
INSTALLED_PAGE_SIZE = 60

CONTENT_MAX_WIDTH = 1280

CATALOGUE_PLACEHOLDER = "⌕  Search mods, contraptions…"
INSTALLED_PLACEHOLDER = "⌕  Search installed content…"

# Neither source exposes a real mod/contraption field, so the catalogue filter
# uses these category names as a best-effort hint. The archive itself is always
# checked during install, and installed records override the guess.
_CONTRAPTION_TAGS = frozenset(
    {
        "contraption",
        "contraptions",
        "buildings",
        "building",
        "cars",
        "car",
        "military-vehicle",
        "vehicle",
        "vehicles",
        "map",
        "maps",
        "machine",
        "machines",
    }
)
_CONTRAPTION_TITLE = re.compile(
    r"\b(?:contraption|building|house|tower|skyscraper|facility|car|cars|"
    r"tank|vehicle|helicopter|aircraft|plane|ship|boat|map|machine|coaster|"
    r"cart|carts|base|city)\b",
    re.IGNORECASE,
)


def _format_index(value: int) -> str:
    return format_metric(value)


class Toast(QLabel):
    """Small transient message pinned to the bottom-right of the window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, milliseconds: int = 2800) -> None:
        self.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start(milliseconds)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            max(12, parent.width() - self.width() - 26),
            max(12, parent.height() - self.height() - 44),
        )


class PageScroll(QScrollArea):
    """Vertical page scroll with a centred, fixed-width content column."""

    def __init__(
        self,
        parent: QWidget | None = None,
        max_width: int = CONTENT_MAX_WIDTH,
    ) -> None:
        super().__init__(parent)
        self._max_width = max_width
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(self)
        self.body = QVBoxLayout(content)
        self.body.setSpacing(22)
        self.setWidget(content)
        self._apply_margins()

    def _apply_margins(self) -> None:
        width = self.viewport().width()
        side = max(24, (width - self._max_width) // 2)
        self.body.setContentsMargins(side, 26, side, 32)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_margins()


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: CatalogueService | None = None,
        store: Store | None = None,
    ) -> None:
        super().__init__()
        self.service = service or CatalogueService()
        self.store = store or Store()
        self.library = self.store.load_library()
        saved_game = str(self.library.get("game_path") or "").strip()
        if saved_game:
            game = Path(saved_game).expanduser()
            if game.exists():
                self.mods_root = game / "Mods"
                self.contraptions_root = game / "Contraptions"
            else:
                self.mods_root = mods_directory()
                self.contraptions_root = contraptions_directory(self.mods_root)
        else:
            detected = detect_game_path()
            if detected is not None:
                self.mods_root = detected / "Mods"
                self.contraptions_root = detected / "Contraptions"
                self.library["game_path"] = str(detected)
                try:
                    self.store.save_library(self.library)
                except Exception:  # noqa: BLE001 - non-fatal
                    pass
                log.info("Auto-detected People Playground at %s", detected)
            else:
                self.mods_root = mods_directory()
                self.contraptions_root = contraptions_directory(self.mods_root)
        self.records = self.store.load_installed()
        self.site_meta = self.store.load_site_meta()
        self.posts: list[Post] = []
        self.installed: list[InstalledMod] = []
        self._installed_by_uid: dict[str, str] = {}
        self.catalogue = CatalogueResult([])
        self.all_mods: list[Mod] = []
        self.filtered: list[Mod] = []
        self.visible_count = PAGE_SIZE
        self.installed_visible_count = INSTALLED_PAGE_SIZE
        self.active_tags: set[str] = set()
        self.source_filter = "all"
        self.access_filter = "all"
        self.library_filter = "all"
        self.catalogue_kind_filter = "all"
        self.installed_kind_filter = "all"
        self.sort_mode = "newest"
        self._queries = {0: "", 1: ""}
        self._catalogue_dirty = True
        self._installed_dirty = True
        self._installed_rendered = False
        self._loading_catalogue = False
        self._loading_installed = False
        self._tasks: list[Task] = []
        self.discovery_mode = "featured"
        self._weekly_cards: list[QWidget] = []
        self._lab_cards: list[QWidget] = []

        self.loader = ImageLoader(self)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(170)
        self._search_timer.timeout.connect(self._apply_search)

        self.setWindowTitle("Playground Mods")
        self.resize(1360, 900)
        self.setMinimumSize(1040, 680)

        self._build_ui()
        self._apply_site_meta()
        self._install_shortcuts()
        self._restore_cached_catalogue()
        self._refresh_installed()
        QTimer.singleShot(350, self.refresh_catalogue)
        QTimer.singleShot(1200, self._clean_downloads)
        if not self.mods_root.parent.exists():
            QTimer.singleShot(800, self._prompt_game_folder)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget(root)
        self.catalogue_page = self._build_catalogue_page()
        self.installed_page = self._build_installed_page()
        self.stack.addWidget(self.catalogue_page)
        self.stack.addWidget(self.installed_page)
        layout.addWidget(self.stack, 1)

        self.toast = Toast(root)

        status = QStatusBar(self)
        status.setSizeGripEnabled(False)
        self.status_label = QLabel("Starting…", status)
        self.status_progress = QProgressBar(status)
        self.status_progress.setFixedWidth(180)
        self.status_progress.setRange(0, 100)
        self.status_progress.hide()
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.status_progress)
        self.setStatusBar(status)

    def _build_topbar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("TopBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 8, 24, 8)
        row.setSpacing(12)

        mark = QLabel("P", bar)
        mark.setObjectName("BrandMark")
        mark.setFixedSize(32, 32)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand = QLabel("playground/mods", bar)
        brand.setObjectName("BrandName")
        row.addWidget(mark)
        row.addWidget(brand)
        row.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.catalogue_nav = self._nav_button("Catalogue", bar)
        self.installed_nav = self._nav_button("Installed", bar)
        self.catalogue_nav.setChecked(True)
        self.catalogue_nav.clicked.connect(lambda: self._show_page(0))
        self.installed_nav.clicked.connect(lambda: self._show_page(1))
        row.addWidget(self.catalogue_nav)
        row.addWidget(self.installed_nav)
        row.addSpacing(6)
        self.community_button = QPushButton("Community", bar)
        self.community_button.setObjectName("CommunityButton")
        self.community_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.community_button.setMenu(self._build_community_menu(self.community_button))
        self.community_button.setToolTip(
            "How to start, lab log, ideas, about, subscriptions and reports"
        )
        row.addWidget(self.community_button)
        row.addStretch(1)

        self.search_input = QLineEdit(bar)
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText(CATALOGUE_PLACEHOLDER)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedWidth(300)
        self.search_input.textChanged.connect(self._on_search_changed)
        row.addWidget(self.search_input)

        folder_button = QPushButton("⌂", bar)
        folder_button.setObjectName("IconButton")
        folder_button.setToolTip(
            f"Open the game folder\nMods: {self.mods_root}\n"
            f"Contraptions: {self.contraptions_root}"
        )
        folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_button.clicked.connect(self._open_mods_folder)
        row.addWidget(folder_button)

        import_button = QPushButton("⤓", bar)
        import_button.setObjectName("IconButton")
        import_button.setToolTip("Install a downloaded ZIP")
        import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_button.clicked.connect(self._import_zip)
        row.addWidget(import_button)

        self.refresh_button = QPushButton("↻", bar)
        self.refresh_button.setObjectName("IconButton")
        self.refresh_button.setToolTip("Refresh the Switch Studio catalogue")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_catalogue)
        row.addWidget(self.refresh_button)
        return bar

    def _nav_button(self, text: str, parent: QWidget) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.nav_group.addButton(button)
        return button

    def _build_catalogue_page(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = PageScroll(page)
        self.catalogue_scroll = scroll
        layout = scroll.body

        self.notice_banner = self._build_notice_banner(scroll)
        layout.addWidget(self.notice_banner)
        layout.addWidget(self._build_hero(scroll))
        layout.addWidget(self._build_discovery_rail(scroll))
        layout.addWidget(self._build_lab_log(scroll))
        layout.addWidget(self._build_filter_bar(scroll))

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        self.results_title = QLabel("All content", scroll)
        self.results_title.setObjectName("ResultsTitle")
        self.results_caption = QLabel("", scroll)
        self.results_caption.setObjectName("ResultsCaption")
        titles.addWidget(self.results_title)
        titles.addWidget(self.results_caption)
        head.addLayout(titles)
        head.addStretch(1)
        layout.addLayout(head)

        self.grid = FlowGrid(236, 14, scroll)
        layout.addWidget(self.grid)

        self.empty_state = QLabel(
            "No mods match that search.\nTry clearing the filters.", scroll
        )
        self.empty_state.setObjectName("EmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(10)
        self.show_more_button = QPushButton("Show more", scroll)
        self.show_more_button.setObjectName("LoadMoreButton")
        self.show_more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_more_button.clicked.connect(self._show_more)
        self.show_more_button.hide()
        footer.addWidget(self.show_more_button)
        footer.addStretch(1)
        layout.addLayout(footer)
        layout.addStretch(1)

        outer.addWidget(scroll)
        return page

    def _build_hero(self, parent: QWidget) -> QWidget:
        hero = QWidget(parent)
        row = QHBoxLayout(hero)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        eyebrow = QLabel("PEOPLE PLAYGROUND  ·  MOD MANAGER", hero)
        eyebrow.setObjectName("Eyebrow")
        title = QLabel("Mods for People Playground", hero)
        title.setObjectName("HeroTitle")
        sub = QLabel(
            "Download community mods and contraptions, or install your own "
            "archives. Everything lands in the right game folder — nothing "
            "else is touched.",
            hero,
        )
        sub.setObjectName("HeroSub")
        sub.setWordWrap(True)
        left.addWidget(eyebrow)
        left.addWidget(title)
        left.addWidget(sub)
        self.hero_meta = QLabel(
            "Game v1.28  ·  Switch Studio catalogue", hero
        )
        self.hero_meta.setObjectName("HeroMeta")
        self.hero_meta.setWordWrap(True)
        left.addWidget(self.hero_meta)
        left.addSpacing(4)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        browse = QPushButton("Browse catalogue", hero)
        browse.setObjectName("PrimaryButton")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse_catalogue)
        actions.addWidget(browse)
        zip_button = QPushButton("Install from ZIP…", hero)
        zip_button.setObjectName("SecondaryButton")
        zip_button.setCursor(Qt.CursorShape.PointingHandCursor)
        zip_button.clicked.connect(self._import_zip)
        actions.addWidget(zip_button)
        self.start_button = QPushButton("?  How to start", hero)
        self.start_button.setObjectName("HowToStart")
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.setToolTip(
            "The three steps to get community mods running in People Playground"
        )
        self.start_button.clicked.connect(self._show_getting_started)
        actions.addWidget(self.start_button)
        actions.addStretch(1)
        left.addLayout(actions)
        row.addLayout(left, 1)

        panel = QFrame(hero)
        panel.setObjectName("StatsPanel")
        panel.setFixedWidth(350)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 10)
        panel_layout.setSpacing(7)
        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(0)
        self.stat_sources = self._add_stat(stats, "2", "sources", panel)
        self._add_divider(stats, panel)
        self.stat_indexed = self._add_stat(stats, "0", "indexed", panel)
        self._add_divider(stats, panel)
        self.stat_installed = self._add_stat(stats, "0", "on disk", panel)
        panel_layout.addLayout(stats)
        line = QFrame(panel)
        line.setObjectName("StatDivider")
        line.setFixedHeight(1)
        panel_layout.addWidget(line)
        self.site_line = QLabel("Switch Studio  ·  game v1.28", panel)
        self.site_line.setObjectName("SiteMetaLine")
        self.site_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.site_line.setWordWrap(True)
        panel_layout.addWidget(self.site_line)
        row.addWidget(panel, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    def _add_stat(
        self,
        layout: QHBoxLayout,
        value: str,
        caption: str,
        parent: QWidget,
        accent: bool = False,
    ) -> QLabel:
        holder = QWidget(parent)
        block = QVBoxLayout(holder)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(3)
        value_label = QLabel(value, holder)
        value_label.setObjectName("StatValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if accent:
            value_label.setProperty("accent", True)
        caption_label = QLabel(caption, holder)
        caption_label.setObjectName("StatCaption")
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        block.addWidget(value_label)
        block.addWidget(caption_label)
        layout.addWidget(holder, 1)
        return value_label

    def _add_divider(self, layout: QHBoxLayout, parent: QWidget) -> None:
        divider = QFrame(parent)
        divider.setObjectName("StatDivider")
        divider.setFixedWidth(1)
        divider.setMinimumHeight(34)
        layout.addWidget(divider)

    def _build_notice_banner(self, parent: QWidget) -> QWidget:
        frame = QFrame(parent)
        frame.setObjectName("NoticeBanner")
        row = QHBoxLayout(frame)
        row.setContentsMargins(13, 10, 9, 10)
        row.setSpacing(11)
        accent = QFrame(frame)
        accent.setObjectName("NoticeAccent")
        accent.setFixedWidth(3)
        row.addWidget(accent)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        kicker = QLabel("SITE NOTICE", frame)
        kicker.setObjectName("NoticeKicker")
        text.addWidget(kicker)
        self.notice_title = QLabel("", frame)
        self.notice_title.setObjectName("NoticeTitle")
        self.notice_title.setWordWrap(True)
        text.addWidget(self.notice_title)
        self.notice_text = QLabel("", frame)
        self.notice_text.setObjectName("NoticeText")
        self.notice_text.setWordWrap(True)
        text.addWidget(self.notice_text)
        row.addLayout(text, 1)
        close = QPushButton("×", frame)
        close.setObjectName("NoticeClose")
        close.setFixedSize(26, 26)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Dismiss this notice")
        close.clicked.connect(self._dismiss_notice)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        frame.hide()
        return frame

    def _build_discovery_rail(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        self.discovery_title = QLabel("Featured", section)
        self.discovery_title.setObjectName("SectionTitle")
        head.addWidget(self.discovery_title)
        self.discovery_caption = QLabel("", section)
        self.discovery_caption.setObjectName("SectionCaption")
        head.addWidget(self.discovery_caption)
        head.addStretch(1)

        self.discovery_group = QButtonGroup(self)
        self.discovery_group.setExclusive(True)
        self.discovery_buttons: dict[str, QPushButton] = {}
        for key, text, tip in (
            ("featured", "Featured", "Pinned and paid picks from Switch Studio."),
            ("weekly", "This week", "New and updated entries from the last 7 days."),
            ("trending", "Trending", "The most active entries on Switch Studio."),
        ):
            button = QPushButton(text, section)
            button.setObjectName("KindPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, key=key: self._set_discovery_mode(key))
            self.discovery_group.addButton(button)
            self.discovery_buttons[key] = button
            head.addWidget(button)
        self.discovery_buttons[self.discovery_mode].setChecked(True)

        self.discovery_count = QLabel("", section)
        self.discovery_count.setObjectName("SectionCaption")
        head.addWidget(self.discovery_count)

        self.rail_prev = QPushButton("‹", section)
        self.rail_prev.setObjectName("RailArrow")
        self.rail_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rail_prev.setToolTip("Scroll back")
        self.rail_prev.clicked.connect(lambda: self._scroll_discovery(-1))
        head.addWidget(self.rail_prev)
        self.rail_next = QPushButton("›", section)
        self.rail_next.setObjectName("RailArrow")
        self.rail_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rail_next.setToolTip("Scroll forward")
        self.rail_next.clicked.connect(lambda: self._scroll_discovery(1))
        head.addWidget(self.rail_next)
        layout.addLayout(head)

        self.discovery_scroll = QScrollArea(section)
        self.discovery_scroll.setWidgetResizable(True)
        self.discovery_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.discovery_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.discovery_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.discovery_scroll.setFixedHeight(188)
        self.discovery_container = QWidget(self.discovery_scroll)
        self.discovery_row = QHBoxLayout(self.discovery_container)
        self.discovery_row.setContentsMargins(0, 0, 0, 0)
        self.discovery_row.setSpacing(10)
        self.discovery_row.addStretch(1)
        self.discovery_scroll.setWidget(self.discovery_container)
        layout.addWidget(self.discovery_scroll)
        self.discovery_section = section

        # Compatibility aliases used by the smoke test and older callers.
        self.weekly_section = section
        self.weekly_count = self.discovery_count
        self.weekly_scroll = self.discovery_scroll
        self.weekly_container = self.discovery_container
        self.weekly_row = self.discovery_row
        section.hide()
        return section

    def _scroll_discovery(self, direction: int) -> None:
        bar = self.discovery_scroll.horizontalScrollBar()
        step = max(220, bar.pageStep() * 2 // 3)
        bar.setValue(bar.value() + direction * step)

    def _build_lab_log(self, parent: QWidget) -> QWidget:
        section = QWidget(parent)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        title = QLabel("Lab log", section)
        title.setObjectName("SectionTitle")
        head.addWidget(title)
        caption = QLabel("Devlogs and release notes from Switch Studio", section)
        caption.setObjectName("SectionCaption")
        head.addWidget(caption)
        head.addStretch(1)
        self.lab_view_all = QPushButton("View all", section)
        self.lab_view_all.setObjectName("DetailsLink")
        self.lab_view_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lab_view_all.clicked.connect(self._show_news)
        head.addWidget(self.lab_view_all)
        layout.addLayout(head)
        self.lab_row = QHBoxLayout()
        self.lab_row.setContentsMargins(0, 0, 0, 0)
        self.lab_row.setSpacing(8)
        self.lab_row.addStretch(1)
        layout.addLayout(self.lab_row)
        self.lab_section = section
        section.hide()
        return section

    def _build_community_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        menu.addAction("How to start", self._show_getting_started)
        menu.addSeparator()
        menu.addAction("Set game folder…", self._choose_game_folder)
        menu.addAction("Lab log", self._show_news)
        menu.addAction("Ideas", self._show_ideas)
        menu.addSeparator()
        menu.addAction("About & safety", self._show_about)
        menu.addAction("Subscriptions", self._show_subscriptions)
        menu.addAction("Report a problem", self._show_report)
        return menu

    def _build_filter_bar(self, parent: QWidget) -> QWidget:
        bar = QFrame(parent)
        bar.setObjectName("FilterBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(8)

        self.catalogue_kind_group = QButtonGroup(self)
        self.catalogue_kind_group.setExclusive(True)
        self.catalogue_kind_buttons: dict[str, QPushButton] = {}
        for key, text, tip in (
            ("all", "All", "Everything in the Switch Studio catalogue."),
            (
                KIND_MOD,
                "Mods",
                "Catalogue entries not detected as contraptions. The archive "
                "contents are verified when you install.",
            ),
            (
                KIND_CONTRAPTION,
                "Contraptions",
                "Entries likely to be contraptions based on their listing. The "
                "archive contents are verified when you install.",
            ),
        ):
            button = QPushButton(text, bar)
            button.setObjectName("KindPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(tip)
            button.setChecked(key == "all")
            button.clicked.connect(
                lambda _=False, key=key: self._set_catalogue_kind(key)
            )
            self.catalogue_kind_group.addButton(button)
            self.catalogue_kind_buttons[key] = button
            row.addWidget(button)

        divider = QFrame(bar)
        divider.setObjectName("StatDivider")
        divider.setFixedWidth(1)
        divider.setMinimumHeight(26)
        row.addWidget(divider)

        self.tag_scroll = QScrollArea(bar)
        self.tag_scroll.setWidgetResizable(True)
        self.tag_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tag_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tag_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.tag_scroll.setFixedHeight(40)
        self.tag_container = QWidget(self.tag_scroll)
        self.tag_layout = QHBoxLayout(self.tag_container)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.addStretch(1)
        self.tag_scroll.setWidget(self.tag_container)
        row.addWidget(self.tag_scroll, 1)

        self.source_combo = ChevronComboBox(bar)
        self.source_combo.setObjectName("SourceCombo")
        self.source_combo.addItem("All sources", "all")
        self.source_combo.addItem("Switch Studio", "Switch Studio")
        self.source_combo.setFixedWidth(112)
        self.source_combo.setToolTip("Show catalogue entries from one source")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        row.addWidget(self.source_combo)

        self.access_combo = ChevronComboBox(bar)
        self.access_combo.setObjectName("SourceCombo")
        self.access_combo.addItem("All access", "all")
        self.access_combo.addItem("Free", "free")
        self.access_combo.addItem("Paid / licensed", "paid")
        self.access_combo.setFixedWidth(112)
        self.access_combo.setToolTip(
            "Free downloads install directly; paid or licensed mods open their "
            "source page"
        )
        self.access_combo.currentIndexChanged.connect(self._on_access_changed)
        row.addWidget(self.access_combo)

        self.library_combo = ChevronComboBox(bar)
        self.library_combo.setObjectName("SourceCombo")
        self.library_combo.addItem("All content", "all")
        self.library_combo.addItem("Liked", "liked")
        self.library_combo.addItem("Following", "following")
        self.library_combo.addItem("Installed", "installed")
        self.library_combo.setFixedWidth(116)
        self.library_combo.setToolTip(
            "Filter by your local likes, follows and installed content"
        )
        self.library_combo.currentIndexChanged.connect(self._on_library_filter_changed)
        row.addWidget(self.library_combo)

        self.sort_combo = ChevronComboBox(bar)
        self.sort_combo.setObjectName("SortCombo")
        self.sort_combo.addItem("Newest", "newest")
        self.sort_combo.addItem("Most downloaded", "downloads")
        self.sort_combo.addItem("Most liked", "likes")
        self.sort_combo.addItem("A — Z", "az")
        self.sort_combo.setFixedWidth(136)
        self.sort_combo.setToolTip("Change the catalogue order")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row.addWidget(self.sort_combo)

        self.random_button = QPushButton("Random", bar)
        self.random_button.setObjectName("RandomButton")
        self.random_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.random_button.setToolTip(
            "Open a random mod from the current filters"
        )
        self.random_button.clicked.connect(self._random_mod)
        row.addWidget(self.random_button)

        self.clear_filters_button = QPushButton("Clear ×", bar)
        self.clear_filters_button.setObjectName("ClearFilters")
        self.clear_filters_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_filters_button.setToolTip(
            "Reset search, kind, source, access, library and tags"
        )
        self.clear_filters_button.clicked.connect(self._clear_filters)
        self.clear_filters_button.hide()
        row.addWidget(self.clear_filters_button)
        return bar

    def _build_installed_page(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = PageScroll(page)
        self.installed_scroll = scroll
        layout = scroll.body

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        self.installed_title = QLabel("Installed content", scroll)
        self.installed_title.setObjectName("ResultsTitle")
        self.installed_caption = QLabel("", scroll)
        self.installed_caption.setObjectName("ResultsCaption")
        titles.addWidget(self.installed_title)
        titles.addWidget(self.installed_caption)
        head.addLayout(titles)
        head.addStretch(1)
        rescan = QPushButton("Rescan", scroll)
        rescan.setObjectName("SecondaryButton")
        rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan.setToolTip("Scan the Mods and Contraptions folders again")
        rescan.clicked.connect(self._refresh_installed)
        head.addWidget(rescan)
        import_button = QPushButton("Install from ZIP…", scroll)
        import_button.setObjectName("PrimaryButton")
        import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_button.clicked.connect(self._import_zip)
        head.addWidget(import_button)
        layout.addLayout(head)

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self.installed_kind_group = QButtonGroup(self)
        self.installed_kind_group.setExclusive(True)
        self.installed_kind_buttons: dict[str, QPushButton] = {}
        for key, text in (
            ("all", "All"),
            (KIND_MOD, "Mods"),
            (KIND_CONTRAPTION, "Contraptions"),
        ):
            button = QPushButton(text, scroll)
            button.setObjectName("KindPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(key == "all")
            button.clicked.connect(
                lambda _=False, key=key: self._set_installed_kind(key)
            )
            self.installed_kind_group.addButton(button)
            self.installed_kind_buttons[key] = button
            filters.addWidget(button)
        filters.addStretch(1)
        self.installed_clear_button = QPushButton("Clear ×", scroll)
        self.installed_clear_button.setObjectName("ClearFilters")
        self.installed_clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.installed_clear_button.setToolTip("Reset search and kind filter")
        self.installed_clear_button.clicked.connect(self._clear_filters)
        self.installed_clear_button.hide()
        filters.addWidget(self.installed_clear_button)
        layout.addLayout(filters)

        self.installed_grid = FlowGrid(300, 12, scroll)
        layout.addWidget(self.installed_grid)

        self.installed_empty = QLabel(
            "No mods or contraptions found in the game folders yet.", scroll
        )
        self.installed_empty.setObjectName("EmptyState")
        self.installed_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.installed_empty.hide()
        layout.addWidget(self.installed_empty)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(10)
        self.installed_more_button = QPushButton("Show more", scroll)
        self.installed_more_button.setObjectName("LoadMoreButton")
        self.installed_more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.installed_more_button.clicked.connect(self._show_more_installed)
        self.installed_more_button.hide()
        footer.addWidget(self.installed_more_button)
        footer.addStretch(1)
        layout.addLayout(footer)
        layout.addStretch(1)

        outer.addWidget(scroll)
        return page

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _install_shortcuts(self) -> None:
        for sequence, slot in (
            (QKeySequence.StandardKey.Find, self._focus_search),
            (QKeySequence("Ctrl+R"), self.refresh_catalogue),
            (QKeySequence("Ctrl+I"), self._import_zip),
            (QKeySequence("Escape"), self._clear_filters),
        ):
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(slot)

    def _focus_search(self) -> None:
        self.search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_input.selectAll()

    def _choose_game_folder(self) -> None:
        start = str(
            self.mods_root.parent if self.mods_root.parent.exists() else Path.home()
        )
        chosen = QFileDialog.getExistingDirectory(
            self, "Select the People Playground folder", start
        )
        if not chosen:
            return
        game = Path(chosen)
        if game.name.lower() in {"mods", "contraptions"}:
            game = game.parent
        if (game / "People Playground").exists():
            game = game / "People Playground"
        if not game.exists():
            QMessageBox.warning(
                self, "Folder not found", "That folder does not exist."
            )
            return
        self.mods_root = game / "Mods"
        self.contraptions_root = game / "Contraptions"
        self.library["game_path"] = str(game)
        try:
            self.store.save_library(self.library)
        except Exception:  # noqa: BLE001
            pass
        self._refresh_installed()
        self._toast(f"Game folder set to {game}")

    def _prompt_game_folder(self) -> None:
        if self.mods_root.parent.exists():
            return
        reply = QMessageBox.question(
            self,
            "Find People Playground",
            "People Playground was not found automatically.\\n"
            "Would you like to select the game folder now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._choose_game_folder()

    def _browse_catalogue(self) -> None:
        self._show_page(0)
        self._focus_search()

    def _show_page(self, index: int) -> None:
        if index == self.stack.currentIndex():
            return
        # Keep the nav indicator in sync even when the page is changed from
        # code (tests, shortcuts) rather than by clicking the nav button.
        self.catalogue_nav.setChecked(index == 0)
        self.installed_nav.setChecked(index == 1)
        # A pending debounced search belongs to the page we are leaving. Its
        # query is already stored, so just mark that page for a refresh.
        if self._search_timer.isActive():
            self._search_timer.stop()
            if self.stack.currentIndex() == 0:
                self._catalogue_dirty = True
            else:
                self._installed_dirty = True
        self.stack.setCurrentIndex(index)
        self._sync_search()
        if index == 0:
            if self._catalogue_dirty:
                self._refresh_results()
        elif not self._installed_rendered or self._installed_dirty:
            self._render_installed_cards()

    def _sync_search(self) -> None:
        index = self.stack.currentIndex()
        self.search_input.blockSignals(True)
        self.search_input.setText(self._queries.get(index, ""))
        self.search_input.blockSignals(False)
        self.search_input.setPlaceholderText(
            CATALOGUE_PLACEHOLDER if index == 0 else INSTALLED_PLACEHOLDER
        )
        self._update_clear_buttons()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _toast(self, text: str) -> None:
        self.toast.show_message(text)

    # ------------------------------------------------------------------
    # Site metadata, home rails and community
    # ------------------------------------------------------------------
    def _apply_site_meta(self) -> None:
        meta = self.site_meta
        config = meta.config
        stats = meta.stats or {}

        def number(key: str) -> int:
            try:
                return int(stats.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        parts = []
        if number("mods"):
            parts.append(f"{number('mods'):,} mods")
        if number("downloads"):
            parts.append(f"{format_metric(number('downloads'))} downloads")
        if number("authors"):
            parts.append(f"{number('authors')} authors")
        game = config.current_game_version
        hero_bits = [f"Game v{game}" if game else ""]
        if config.patch_title:
            hero_bits.append(f"{config.patch_title} patch")
        hero_bits.extend(parts[:2])
        self.hero_meta.setText(
            "  ·  ".join(bit for bit in hero_bits if bit)
            or "Community mods and contraptions for People Playground"
        )
        site_bits = [config.site_name]
        if number("authors"):
            site_bits.append(f"{number('authors')} authors")
        if meta.free_total:
            site_bits.append(f"{meta.free_total:,} free mods")
        self.site_line.setText("  ·  ".join(bit for bit in site_bits if bit))
        self._update_start_button()
        self._update_notice()

    def _update_notice(self) -> None:
        config = self.site_meta.config
        visible = bool(
            config.notice_id
            and config.notice_id != self.library.get("dismissed_notice")
            and (config.notice_title or config.notice_text)
        )
        if visible:
            self.notice_title.setText(config.notice_title or "Site notice")
            self.notice_text.setText(config.notice_text)
        self.notice_banner.setVisible(visible)

    def _dismiss_notice(self) -> None:
        notice_id = self.site_meta.config.notice_id
        if not notice_id:
            self.notice_banner.hide()
            return
        self.library["dismissed_notice"] = notice_id
        self.store.save_library(self.library)
        self.notice_banner.hide()
        self._toast("Notice dismissed")

    def _update_start_button(self) -> None:
        if not hasattr(self, "start_button"):
            return
        fresh = not bool(self.library.get("onboarding_seen"))
        self.start_button.setProperty("fresh", fresh)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def _mark_onboarding_seen(self) -> None:
        if self.library.get("onboarding_seen"):
            return
        self.library["onboarding_seen"] = True
        self.store.save_library(self.library)
        self._update_start_button()

    def _find_patch_mod(self) -> Mod | None:
        slug = self.site_meta.config.patch_slug
        if not slug:
            return None
        return next((mod for mod in self.all_mods if mod.slug == slug), None)

    def _lookup_mod(self, slug: str) -> Mod | None:
        if not slug:
            return None
        return next((mod for mod in self.all_mods if mod.slug == slug), None)

    @staticmethod
    def _parse_date(value: str) -> datetime | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _weekly_mods(self) -> list[Mod]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        dated: list[tuple[datetime, Mod]] = []
        for mod in self.all_mods:
            when = self._parse_date(
                mod.updated_at or mod.published or mod.created_at
            )
            if when is None or when < cutoff:
                continue
            dated.append((when, mod))
        dated.sort(key=lambda pair: pair[0], reverse=True)
        return [mod for _, mod in dated[:14]]

    def _resolve_mods(self, mods: list[Mod]) -> list[Mod]:
        by_uid = {mod.uid: mod for mod in self.all_mods}
        return [by_uid.get(mod.uid, mod) for mod in mods]

    def _discovery_mods(self) -> list[Mod]:
        if self.discovery_mode == "featured":
            mods = self._resolve_mods(self.site_meta.featured)
            if not mods:
                mods = self._weekly_mods()
        elif self.discovery_mode == "trending":
            mods = self._resolve_mods(self.site_meta.trending)
            if not mods:
                mods = sorted(
                    self.all_mods, key=lambda mod: mod.metric, reverse=True
                )
        else:
            mods = self._weekly_mods()
        return mods[:14]

    def _set_discovery_mode(self, mode: str) -> None:
        if mode not in self.discovery_buttons:
            return
        self.discovery_mode = mode
        for key, button in self.discovery_buttons.items():
            button.setChecked(key == mode)
        self._rebuild_discovery()
        self.discovery_scroll.horizontalScrollBar().setValue(0)

    def _rebuild_discovery(self) -> None:
        if not hasattr(self, "discovery_row"):
            return
        while self.discovery_row.count():
            item = self.discovery_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._weekly_cards = []
        mods = self._discovery_mods()
        titles = {
            "featured": (
                "Featured",
                "Pinned and paid picks from Switch Studio",
            ),
            "weekly": (
                "This week",
                "New and updated catalogue entries from the last 7 days",
            ),
            "trending": (
                "Trending",
                "The most active entries on Switch Studio right now",
            ),
        }
        title, caption = titles.get(
            self.discovery_mode, titles["weekly"]
        )
        fallback = (
            self.discovery_mode == "featured"
            and not self.site_meta.featured
            or self.discovery_mode == "trending"
            and not self.site_meta.trending
        )
        card_mode = self.discovery_mode
        if fallback:
            if self.discovery_mode == "trending":
                caption = "No live picks cached yet · showing the most downloaded"
            else:
                caption = "No live picks cached yet · showing this week instead"
                card_mode = "weekly"
        self.discovery_title.setText(title)
        self.discovery_caption.setText(caption)
        for mod in mods:
            if card_mode == "featured":
                if mod.pinned:
                    badge_text, badge_fresh = "Pinned", True
                elif mod.tier:
                    badge_text = f"{mod.tier.title()} subscription"
                    badge_fresh = False
                else:
                    badge_text, badge_fresh = "Featured", True
                card = FreshCard(
                    mod,
                    self.loader,
                    badge_text=badge_text,
                    badge_fresh=badge_fresh,
                    parent=self.discovery_container,
                )
            elif card_mode == "trending":
                card = FreshCard(
                    mod,
                    self.loader,
                    badge_text="Trending",
                    badge_fresh=True,
                    parent=self.discovery_container,
                )
            else:
                card = FreshCard(
                    mod,
                    self.loader,
                    is_new=not mod.updated,
                    parent=self.discovery_container,
                )
            card.clicked.connect(self._show_details)
            self.discovery_row.addWidget(card)
            self._weekly_cards.append(card)
        self.discovery_row.addStretch(1)
        self.discovery_count.setText(
            f"{len(mods)} pick{'s' if len(mods) != 1 else ''}" if mods else ""
        )
        self.discovery_section.setVisible(bool(mods))

    def _rebuild_lab_log(self) -> None:
        if not hasattr(self, "lab_row"):
            return
        while self.lab_row.count():
            item = self.lab_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._lab_cards = []
        posts = self.posts[:3]
        for post in posts:
            card = PostStripCard(post, self.lab_section)
            card.clicked.connect(self._show_post)
            self.lab_row.addWidget(card, 1)
            self._lab_cards.append(card)
        self.lab_row.addStretch(1)
        self.lab_section.setVisible(bool(posts))

    def _show_getting_started(self) -> None:
        patch = self._find_patch_mod()
        dialog = GettingStartedDialog(self.site_meta.config, patch, self)
        if patch is not None:
            dialog.install_patch.connect(lambda: self._install_mod(patch))
        dialog.browse_requested.connect(self._browse_catalogue)
        dialog.import_requested.connect(self._import_zip)
        self._mark_onboarding_seen()
        dialog.exec()

    def _show_news(self) -> None:
        dialog = PostsDialog(self.service, self.loader, self)
        dialog.exec()

    def _show_post(self, post: Post) -> None:
        dialog = PostDetailDialog(post, self.service, self.loader, self)
        dialog.exec()

    def _show_ideas(self) -> None:
        dialog = IdeasDialog(self.service, self._lookup_mod, self)
        dialog.mod_requested.connect(self._details_from_dialog)
        dialog.exec()

    def _show_about(self) -> None:
        dialog = AboutDialog(self.site_meta, self)
        dialog.exec()

    def _show_subscriptions(self) -> None:
        dialog = SubscriptionsDialog(self.site_meta, self)
        dialog.exec()

    def _show_report(self) -> None:
        dialog = ReportDialog(
            self.site_meta.config.links, self._diagnostics(), self
        )
        dialog.exec()

    def _details_from_dialog(self, mod: Mod) -> None:
        QTimer.singleShot(0, lambda: self._show_details(mod))

    def _diagnostics(self) -> str:
        mods = sum(1 for item in self.installed if item.kind == KIND_MOD)
        contraptions = sum(
            1 for item in self.installed if item.kind == KIND_CONTRAPTION
        )
        return "\n".join(
            (
                f"Playground Mods {__version__}",
                f"Qt {qVersion()} · Python {sys.version.split()[0]} · {sys.platform}",
                f"Game folder: {self.mods_root.parent}",
                f"Catalogue: {len(self.all_mods)} entries "
                f"({len(self.catalogue.switch_mods)} Switch Studio)",
                f"Installed: {len(self.installed)} "
                f"({mods} mods, {contraptions} contraptions)",
                f"Local library: {len(self.library.get('likes') or [])} likes, "
                f"{len(self.library.get('follows') or {})} follows",
            )
        )

    def _check_follow_updates(self) -> None:
        follows = self.library.get("follows") or {}
        if not follows:
            return
        by_uid = {mod.uid: mod for mod in self.all_mods}
        changed: list[str] = []
        touched = False
        for uid, record in list(follows.items()):
            mod = by_uid.get(uid)
            if mod is None or not isinstance(record, dict):
                continue
            current = int(mod.latest_ver or 0)
            try:
                stored = int(record.get("latest_ver") or 0)
            except (TypeError, ValueError):
                stored = 0
            if not current:
                continue
            if not stored:
                record["latest_ver"] = current
                touched = True
                continue
            if current > stored:
                changed.append(mod.title)
                record["latest_ver"] = current
                record["version"] = mod.version
                record["title"] = mod.title
                touched = True
        if touched:
            self.store.save_library(self.library)
        if changed:
            label = changed[0] if len(changed) == 1 else f"{len(changed)} followed mods"
            self._toast(f"Update available · {label}")

    def _on_library_changed(self) -> None:
        self._catalogue_dirty = True
        self._update_start_button()
        if self.stack.currentIndex() == 0:
            self._refresh_results()

    def _random_mod(self) -> None:
        mods = self.filtered or self._sorted_mods()
        if not mods:
            self._toast("No mods match the current filters")
            return
        self._show_details(random.choice(mods))

    def _clean_downloads(self) -> None:
        """Drop old downloaded archives without blocking the window."""
        self._run(
            clean_old_downloads,
            lambda removed: log.info("Removed %s old download(s)", removed),
            lambda _message: None,
        )

    def _open_folder(self, root: Path) -> None:
        if not root.is_dir():
            QMessageBox.warning(
                self,
                f"{root.name} folder missing",
                f"The People Playground {root.name} folder was not found:\n{root}",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def _open_mods_folder(self) -> None:
        self._open_folder(self.mods_root)

    def _run(self, function, on_done, on_error=None, on_progress=None, on_status=None):
        task = Task(function)
        task.signals.done.connect(on_done)
        task.signals.error.connect(on_error or self._on_task_error)
        if on_progress is not None:
            task.signals.progress.connect(on_progress)
        if on_status is not None:
            task.signals.status.connect(on_status)
        self._tasks.append(task)
        task.signals.done.connect(lambda _=None, task=task: self._forget(task))
        task.signals.error.connect(lambda _=None, task=task: self._forget(task))
        QThreadPool.globalInstance().start(task)
        return task

    def _forget(self, task: Task) -> None:
        try:
            self._tasks.remove(task)
        except ValueError:
            pass

    def _on_task_error(self, message: str) -> None:
        self._set_status(f"Error · {message}")
        self.status_progress.hide()
        self._toast(message)

    def _set_busy(self, busy: bool, indeterminate: bool = False) -> None:
        self.refresh_button.setEnabled(not busy)
        self.status_progress.setVisible(busy)
        if busy:
            self.status_progress.setRange(0, 0 if indeterminate else 100)

    # ------------------------------------------------------------------
    # Catalogue loading
    # ------------------------------------------------------------------
    def _restore_cached_catalogue(self) -> None:
        cached = self.store.load_catalogue()
        if cached is None:
            return
        self._apply_catalogue(cached, from_cache=True)

    def _load_catalogue(self, status=None) -> tuple:
        from concurrent.futures import ThreadPoolExecutor

        # Fetch the catalogue, site metadata and the latest lab-log posts at
        # the same time. Each block degrades gracefully if its endpoint is down.
        with ThreadPoolExecutor(max_workers=2) as executor:
            meta_future = executor.submit(self.service.fetch_site_meta)
            posts_future = executor.submit(self.service.fetch_posts, 1)
            switch_mods = self.service.fetch_switch(status=status)
            try:
                meta = meta_future.result()
            except Exception as exc:  # noqa: BLE001
                log.info("Could not refresh site metadata: %s", exc)
                meta = self.site_meta
            else:
                # A partial outage should not wipe metadata that is already
                # cached; fill any missing block from the previous snapshot.
                cached = self.site_meta
                if not meta.config.raw:
                    meta.config = cached.config
                if not meta.stats:
                    meta.stats = cached.stats
                if not meta.tags:
                    meta.tags = cached.tags
                if not meta.free_total:
                    meta.free_total = cached.free_total
                if not meta.featured:
                    meta.featured = cached.featured
                if not meta.trending:
                    meta.trending = cached.trending
            try:
                posts, _pages = posts_future.result()
            except Exception as exc:  # noqa: BLE001
                log.info("Could not refresh lab log: %s", exc)
                posts = []
        return switch_mods, meta, posts

    def refresh_catalogue(self) -> None:
        if self._loading_catalogue:
            return
        self._loading_catalogue = True
        self._set_busy(True)
        self._set_status("Refreshing the Switch Studio catalogue…")
        self._run(
            self._load_catalogue,
            self._catalogue_loaded,
            self._catalogue_failed,
            on_status=self._set_status,
        )

    def _catalogue_loaded(self, result: tuple) -> None:
        self._loading_catalogue = False
        self._set_busy(False)
        switch_mods, meta, posts = result
        catalogue = CatalogueResult(switch_mods=switch_mods)
        self.store.save_catalogue(catalogue)
        self.site_meta = meta
        self.posts = list(posts or [])
        self.store.save_site_meta(meta)
        self._apply_site_meta()
        self._apply_catalogue(catalogue)
        self._rebuild_lab_log()
        self._set_status(f"Loaded {len(switch_mods)} Switch Studio mods")
        self._toast("Catalogue refreshed")

    def _catalogue_failed(self, message: str) -> None:
        self._loading_catalogue = False
        self._set_busy(False)
        if self.all_mods:
            self._set_status(f"Using cached catalogue · {message}")
            self._toast("Refresh failed · showing cached mods")
        else:
            self._set_status(f"Could not load catalogue · {message}")
            self._toast(message)

    def _apply_catalogue(
        self, catalogue: CatalogueResult, from_cache: bool = False
    ) -> None:
        self.catalogue = catalogue
        self.all_mods = list(catalogue.switch_mods)
        self.stat_indexed.setText(_format_index(len(self.all_mods)))
        self._rebuild_tags()
        self._rebuild_discovery()
        self.visible_count = PAGE_SIZE
        self._catalogue_dirty = True
        if self.stack.currentIndex() == 0:
            self._refresh_results()
        self._check_follow_updates()
        if from_cache:
            self._set_status(
                f"Cached catalogue · {len(catalogue.switch_mods)} Switch Studio mods"
            )

    # ------------------------------------------------------------------
    # Filtering and rendering
    # ------------------------------------------------------------------
    def _on_search_changed(self, _text: str) -> None:
        index = self.stack.currentIndex()
        self._queries[index] = self.search_input.text()
        if index == 0:
            self._catalogue_dirty = True
        else:
            self._installed_dirty = True
        self._update_clear_buttons()
        # Debounce so typing does not rebuild every card on each keystroke.
        self._search_timer.start()

    def _apply_search(self) -> None:
        if self.stack.currentIndex() == 0:
            self.visible_count = PAGE_SIZE
            self._refresh_results()
        else:
            self.installed_visible_count = INSTALLED_PAGE_SIZE
            self._render_installed_cards()

    def _on_sort_changed(self, _index: int) -> None:
        self.sort_mode = self.sort_combo.currentData() or "newest"
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _on_source_changed(self, _index: int) -> None:
        self.source_filter = self.source_combo.currentData() or "all"
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _on_access_changed(self, _index: int) -> None:
        self.access_filter = self.access_combo.currentData() or "all"
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _on_library_filter_changed(self, _index: int) -> None:
        self.library_filter = self.library_combo.currentData() or "all"
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _set_catalogue_kind(self, key: str) -> None:
        self.catalogue_kind_filter = key
        for name, button in self.catalogue_kind_buttons.items():
            button.setChecked(name == key)
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _toggle_tag(self, tag: str, checked: bool) -> None:
        if checked:
            self.active_tags.add(tag)
        else:
            self.active_tags.discard(tag)
        self.visible_count = PAGE_SIZE
        self._refresh_results()

    def _clear_filters(self) -> None:
        if self.stack.currentIndex() == 0:
            self._clear_catalogue_filters()
        else:
            self._clear_installed_filters()

    def _clear_catalogue_filters(self) -> None:
        changed = bool(
            self._queries[0].strip()
            or self.active_tags
            or self.source_filter != "all"
            or self.access_filter != "all"
            or self.library_filter != "all"
            or self.catalogue_kind_filter != "all"
        )
        self._queries[0] = ""
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.active_tags.clear()
        self.source_filter = "all"
        self.access_filter = "all"
        self.library_filter = "all"
        self.catalogue_kind_filter = "all"
        for combo in (self.source_combo, self.access_combo, self.library_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        for name, button in self.catalogue_kind_buttons.items():
            button.setChecked(name == "all")
        self.visible_count = PAGE_SIZE
        self._rebuild_tags()
        self._refresh_results()
        self._toast("Filters cleared" if changed else "No filters active")

    def _clear_installed_filters(self) -> None:
        changed = bool(
            self._queries[1].strip() or self.installed_kind_filter != "all"
        )
        self._queries[1] = ""
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.installed_kind_filter = "all"
        for name, button in self.installed_kind_buttons.items():
            button.setChecked(name == "all")
        self.installed_visible_count = INSTALLED_PAGE_SIZE
        self._render_installed_cards()
        self._toast("Filters cleared" if changed else "No filters active")

    def _update_clear_buttons(self) -> None:
        catalogue_active = bool(
            self._queries[0].strip()
            or self.active_tags
            or self.source_filter != "all"
            or self.access_filter != "all"
            or self.library_filter != "all"
            or self.catalogue_kind_filter != "all"
        )
        installed_active = bool(
            self._queries[1].strip() or self.installed_kind_filter != "all"
        )
        self.clear_filters_button.setVisible(catalogue_active)
        self.installed_clear_button.setVisible(installed_active)

    def _rebuild_tags(self) -> None:
        while self.tag_layout.count():
            item = self.tag_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        counts: dict[str, int] = {}
        for mod in self.all_mods:
            for tag in mod.tags:
                key = tag.lower()
                counts[key] = counts.get(key, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        self.active_tags &= {tag for tag, _ in ordered}
        for tag, count in ordered:
            button = QPushButton(f"#{tag}  {count}", self.tag_container)
            button.setObjectName("TagPill")
            button.setCheckable(True)
            button.setChecked(tag in self.active_tags)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked, tag=tag: self._toggle_tag(tag, checked)
            )
            self.tag_layout.addWidget(button)
        self.tag_layout.addStretch(1)

    def _catalogue_kind(self, mod: Mod) -> tuple[str, bool]:
        """Return (kind, guessed) using verified install data first."""
        record = self.records.get(mod.uid)
        if record:
            kind = str(record.get("kind") or "")
            if kind:
                return kind, False
        kind = self._installed_by_uid.get(mod.uid, "")
        if kind:
            return kind, False
        if _CONTRAPTION_TAGS & {tag.lower() for tag in mod.tags}:
            return KIND_CONTRAPTION, True
        if _CONTRAPTION_TITLE.search(mod.title):
            return KIND_CONTRAPTION, True
        return "", False

    def _sorted_mods(self) -> list[Mod]:
        query = self._queries[0].strip().lower()
        mods = self.all_mods
        if self.source_filter != "all":
            mods = [mod for mod in mods if mod.source == self.source_filter]
        if self.access_filter == "free":
            mods = [mod for mod in mods if mod.is_free]
        elif self.access_filter == "paid":
            mods = [mod for mod in mods if mod.is_paid]
        if self.library_filter == "liked":
            liked = set(self.library.get("likes") or [])
            mods = [mod for mod in mods if mod.uid in liked]
        elif self.library_filter == "following":
            follows = self.library.get("follows") or {}
            mods = [mod for mod in mods if mod.uid in follows]
        elif self.library_filter == "installed":
            installed = set(self.records) | set(self._installed_by_uid)
            mods = [mod for mod in mods if mod.uid in installed]
        if self.catalogue_kind_filter == KIND_CONTRAPTION:
            mods = [
                mod
                for mod in mods
                if self._catalogue_kind(mod)[0] == KIND_CONTRAPTION
            ]
        elif self.catalogue_kind_filter == KIND_MOD:
            mods = [
                mod
                for mod in mods
                if self._catalogue_kind(mod)[0] != KIND_CONTRAPTION
            ]
        if query:
            mods = [
                mod
                for mod in mods
                if query in mod.title.lower()
                or query in mod.summary.lower()
                or query in mod.author.lower()
                or any(query in tag.lower() for tag in mod.tags)
            ]
        if self.active_tags:
            mods = [
                mod
                for mod in mods
                if self.active_tags & {tag.lower() for tag in mod.tags}
            ]
        if self.sort_mode == "downloads":
            return sorted(mods, key=lambda mod: mod.metric, reverse=True)
        if self.sort_mode == "likes":
            return sorted(mods, key=lambda mod: mod.likes, reverse=True)
        if self.sort_mode == "az":
            return sorted(mods, key=lambda mod: mod.title.lower())
        return sorted(mods, key=lambda mod: mod.published or "", reverse=True)

    def _refresh_results(self) -> None:
        mods = self._sorted_mods()
        self.filtered = mods
        self._catalogue_dirty = False
        self._update_clear_buttons()
        self.visible_count = max(
            PAGE_SIZE, min(self.visible_count, len(mods) or PAGE_SIZE)
        )
        visible = mods[: self.visible_count]

        cards: list[QWidget] = []
        liked = set(self.library.get("likes") or [])
        follows = self.library.get("follows") or {}
        for mod in visible:
            kind, guessed = self._catalogue_kind(mod)
            record = self.records.get(mod.uid)
            card = ModCard(
                mod,
                self.loader,
                installed=record is not None,
                kind=kind,
                kind_guess=guessed,
                liked=mod.uid in liked,
                following=mod.uid in follows,
            )
            card.install_clicked.connect(self._install_mod)
            card.details_clicked.connect(self._show_details)
            cards.append(card)
        self.grid.set_cards(cards)

        self.results_title.setText(self._results_title())
        self.results_caption.setText(self._caption(len(mods)))

        self.empty_state.setVisible(not mods)
        remaining = len(mods) - len(visible)
        self.show_more_button.setVisible(remaining > 0)
        if remaining > 0:
            self.show_more_button.setText(
                f"Show {min(PAGE_SIZE, remaining)} more · {remaining} left"
            )

        pass

    def _results_title(self) -> str:
        if self._queries[0].strip():
            return "Search results"
        if self.library_filter == "liked":
            return "Liked mods"
        if self.library_filter == "following":
            return "Followed mods"
        if self.library_filter == "installed":
            return "Installed from the catalogue"
        if self.access_filter == "free":
            return "Free downloads"
        if self.access_filter == "paid":
            return "Paid & licensed"
        if self.catalogue_kind_filter == KIND_MOD:
            return "Mods"
        if self.catalogue_kind_filter == KIND_CONTRAPTION:
            return "Contraptions"
        if self.source_filter != "all":
            return self.source_filter
        return "All content"

    def _caption(self, count: int) -> str:
        parts = [f"{count} entr{'y' if count == 1 else 'ies'}"]
        if self.catalogue_kind_filter != "all":
            parts.append(
                "excluding likely contraptions"
                if self.catalogue_kind_filter == KIND_MOD
                else "likely contraptions"
            )
        if self.source_filter != "all":
            parts.append(f"from {self.source_filter}")
        if self.access_filter == "free":
            parts.append("free downloads")
        elif self.access_filter == "paid":
            parts.append("paid or account-locked")
        if self.library_filter != "all":
            parts.append(
                {
                    "liked": "liked locally",
                    "following": "followed locally",
                    "installed": "already installed",
                }.get(self.library_filter, self.library_filter)
            )
        if self.active_tags:
            parts.append(
                "tags " + ", ".join(f"#{tag}" for tag in sorted(self.active_tags))
            )
        if (
            not self._queries[0].strip()
            and not self.active_tags
            and self.source_filter == "all"
            and self.access_filter == "all"
            and self.library_filter == "all"
            and self.catalogue_kind_filter == "all"
        ):
            parts.append("newest additions from Switch Studio")
        return "  ·  ".join(parts)

    def _show_more(self) -> None:
        self.visible_count += PAGE_SIZE
        self._refresh_results()

    # ------------------------------------------------------------------
    # Mod actions
    # ------------------------------------------------------------------
    def _show_details(self, mod: Mod) -> None:
        dialog = ModDetailsDialog(
            mod,
            self.loader,
            self.service,
            self.store,
            self.library,
            installed=mod.uid in self.records,
            mod_lookup=self._lookup_mod,
            parent=self,
        )
        dialog.install_requested.connect(self._install_mod)
        dialog.library_changed.connect(self._on_library_changed)
        dialog.mod_requested.connect(self._details_from_dialog)
        dialog.exec()

    def _install_mod(self, mod: Mod) -> None:
        dialog = InstallDialog(
            self.service,
            self.store,
            self.records,
            self.mods_root,
            mod=mod,
            contraptions_root=self.contraptions_root,
            parent=self,
        )
        dialog.installed_changed.connect(self._on_installed_changed)
        dialog.exec()

    def _import_zip(self) -> None:
        dialog = InstallDialog(
            self.service,
            self.store,
            self.records,
            self.mods_root,
            contraptions_root=self.contraptions_root,
            parent=self,
        )
        dialog.installed_changed.connect(self._on_installed_changed)
        dialog.exec()

    def _on_installed_changed(self) -> None:
        self.records = self.store.load_installed()
        self._catalogue_dirty = True
        self._installed_dirty = True
        self._refresh_results()
        self._refresh_installed()
        self._toast("Game folders updated")

    # ------------------------------------------------------------------
    # Installed view
    # ------------------------------------------------------------------
    def _refresh_installed(self) -> None:
        if self._loading_installed:
            return
        self._loading_installed = True
        self._installed_dirty = True
        self._set_status("Scanning installed content…")
        self._run(
            lambda: scan_installed(
                self.mods_root, self.records, self.contraptions_root
            ),
            self._installed_loaded,
            self._installed_failed,
        )

    def _installed_loaded(self, installed: list[InstalledMod]) -> None:
        self._loading_installed = False
        self.installed = installed
        self._installed_by_uid = {
            item.uid: item.kind for item in installed if item.uid
        }
        self.stat_installed.setText(_format_index(len(installed)))
        managed = sum(1 for mod in installed if mod.managed)
        mods_count = sum(1 for mod in installed if mod.kind == KIND_MOD)
        contraptions_count = sum(
            1 for mod in installed if mod.kind == KIND_CONTRAPTION
        )
        self.installed_title.setText("Installed content")
        self.installed_caption.setText(
            f"{mods_count} mods  ·  {contraptions_count} contraptions  ·  "
            f"{managed} installed by this app"
        )
        self.installed_nav.setText(f"Installed  ({len(installed)})")
        self._update_installed_pills()
        self._installed_dirty = True
        if self.stack.currentIndex() == 1:
            self._render_installed_cards()
        else:
            # Verified kinds and installed badges are now available for the
            # catalogue; rebuild once rather than on every page switch.
            self._refresh_results()
        self._set_status(f"{len(installed)} items on disk")

    def _update_installed_pills(self) -> None:
        counts = {
            "all": len(self.installed),
            KIND_MOD: sum(1 for mod in self.installed if mod.kind == KIND_MOD),
            KIND_CONTRAPTION: sum(
                1 for mod in self.installed if mod.kind == KIND_CONTRAPTION
            ),
        }
        labels = {"all": "All", KIND_MOD: "Mods", KIND_CONTRAPTION: "Contraptions"}
        for key, button in self.installed_kind_buttons.items():
            button.setText(f"{labels[key]}  {counts[key]}")

    def _render_installed_cards(self) -> None:
        query = self._queries[1].strip().lower()
        items = self.installed
        if self.installed_kind_filter != "all":
            items = [
                item for item in items if item.kind == self.installed_kind_filter
            ]
        if query:
            items = [
                item
                for item in items
                if query in item.title.lower()
                or query in item.author.lower()
                or query in item.folder.lower()
                or query in item.description.lower()
            ]
        self.installed_visible_count = max(
            INSTALLED_PAGE_SIZE,
            min(self.installed_visible_count, len(items) or INSTALLED_PAGE_SIZE),
        )
        visible = items[: self.installed_visible_count]
        clear_thumbnail_queue()
        cards: list[QWidget] = []
        for mod in visible:
            card = InstalledCard(mod, self.installed_page)
            card.open_clicked.connect(self._open_installed)
            card.remove_clicked.connect(self._remove_installed)
            cards.append(card)
        self.installed_grid.set_cards(cards)
        self.installed_empty.setText(
            "No installed content matches those filters."
            if self.installed
            else "No mods or contraptions found in the game folders yet."
        )
        self.installed_empty.setVisible(not items)
        remaining = len(items) - len(visible)
        self.installed_more_button.setVisible(remaining > 0)
        if remaining > 0:
            self.installed_more_button.setText(
                f"Show {min(INSTALLED_PAGE_SIZE, remaining)} more · {remaining} left"
            )
        self._installed_rendered = True
        self._installed_dirty = False
        self._update_clear_buttons()

    def _show_more_installed(self) -> None:
        self.installed_visible_count += INSTALLED_PAGE_SIZE
        self._render_installed_cards()

    def _set_installed_kind(self, key: str) -> None:
        self.installed_kind_filter = key
        for name, button in self.installed_kind_buttons.items():
            button.setChecked(name == key)
        self.installed_visible_count = INSTALLED_PAGE_SIZE
        self._render_installed_cards()

    def _installed_failed(self, message: str) -> None:
        self._loading_installed = False
        self._on_task_error(message)

    def _open_installed(self, mod: InstalledMod) -> None:
        path = Path(mod.path)
        if not path.is_dir():
            self._toast("That folder no longer exists")
            self._refresh_installed()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _remove_installed(self, mod: InstalledMod) -> None:
        record = self.records.get(mod.uid) if mod.uid else None
        if not record:
            QMessageBox.information(
                self,
                "Not managed by this app",
                "This folder was not installed by Playground Mods, so the app will "
                "not delete it. Remove it manually if you no longer need it.",
            )
            return
        folder = Path(mod.path)
        folder_name = kind_folder_name(mod.kind)
        answer = QMessageBox.question(
            self,
            f"Remove {mod.kind_label.lower()}?",
            f"Delete “{mod.title}” from the {folder_name} folder?\n\n{mod.path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        root = (
            self.contraptions_root
            if mod.kind == KIND_CONTRAPTION
            else self.mods_root
        )
        try:
            remove_managed_mod(folder, root, record)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Could not remove item", str(exc))
            return
        self.records.pop(mod.uid, None)
        self.store.save_installed(self.records)
        self._toast(f"Removed {mod.title}")
        self._catalogue_dirty = True
        self._installed_dirty = True
        self._refresh_installed()
        self._refresh_results()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast.reposition()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        QThreadPool.globalInstance().waitForDone(6000)
        super().closeEvent(event)
