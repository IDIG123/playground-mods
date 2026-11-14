from __future__ import annotations

COLORS = {
    "bg": "#121212",
    "bg_alt": "#161616",
    "panel": "#1a1a1a",
    "panel_2": "#1f1f1f",
    "panel_3": "#262626",
    "border": "#2a2a2a",
    "border_light": "#3a3a3a",
    "text": "#f2f2f2",
    "muted": "#8a8a8a",
    "muted_2": "#666666",
    "lime": "#b6f24b",
    "lime_dark": "#8fca2e",
    "orange": "#f0a43a",
    "danger": "#f87171",
    "success": "#b6f24b",
}


STYLESHEET = f"""
* {{
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    outline: 0;
}}
QMainWindow, QWidget#AppRoot {{
    background: {COLORS["bg"]};
    color: {COLORS["text"]};
}}
QWidget {{
    color: {COLORS["text"]};
    font-size: 12px;
}}
QToolTip {{
    background: {COLORS["panel_3"]};
    color: {COLORS["text"]};
    border: 1px solid {COLORS["border_light"]};
    padding: 6px 8px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #343434;
    min-height: 32px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: #4a4a4a;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: #343434;
    min-width: 28px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #4a4a4a;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QWidget#TopBar {{
    background: {COLORS["bg_alt"]};
    border-bottom: 1px solid #232323;
}}
QLabel#BrandMark {{
    background: {COLORS["lime"]};
    color: #11160a;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 800;
}}
QLabel#BrandName {{
    color: {COLORS["text"]};
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {COLORS["muted"]};
    font-size: 13px;
    font-weight: 600;
    padding: 20px 10px 18px 10px;
}}
QPushButton#NavButton:hover {{
    color: {COLORS["text"]};
}}
QPushButton#NavButton:checked {{
    color: {COLORS["text"]};
    border-bottom: 2px solid {COLORS["lime"]};
}}
QLineEdit#SearchInput {{
    background: #1c1c1c;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
    color: {COLORS["text"]};
    font-size: 12px;
    padding: 8px 12px;
    selection-background-color: {COLORS["lime"]};
    selection-color: #11160a;
}}
QLineEdit#SearchInput:focus {{
    border-color: #4c4c4c;
    background: #1e1e1e;
}}
QPushButton#IconButton {{
    background: #1a1a1a;
    border: 1px solid #2c2c2c;
    border-radius: 8px;
    color: #bdbdbd;
    font-size: 16px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
QPushButton#IconButton:hover {{
    background: #202020;
    border-color: #464646;
    color: {COLORS["lime"]};
}}

QLabel#Eyebrow {{
    color: {COLORS["lime"]};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#HeroTitle {{
    color: {COLORS["text"]};
    font-size: 36px;
    font-weight: 800;
}}
QLabel#HeroSub {{
    color: {COLORS["muted"]};
    font-size: 13px;
}}
QFrame#StatsPanel {{
    background: #181818;
    border: 1px solid #292929;
    border-radius: 12px;
}}
QLabel#StatValue {{
    color: {COLORS["text"]};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#StatValue[accent="true"] {{
    color: {COLORS["lime"]};
}}
QLabel#StatCaption {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QFrame#StatDivider {{
    background: #2b2b2b;
    border: none;
}}

QPushButton#PrimaryButton {{
    background: {COLORS["lime"]};
    border: 1px solid {COLORS["lime"]};
    border-radius: 8px;
    color: #11160a;
    font-size: 12px;
    font-weight: 700;
    padding: 9px 16px;
}}
QPushButton#PrimaryButton:hover {{
    background: #c6ff5c;
    border-color: #c6ff5c;
}}
QPushButton#PrimaryButton:disabled {{
    background: #2c3a18;
    border-color: #3a4a20;
    color: #7e8a6a;
}}
QPushButton#SecondaryButton {{
    background: transparent;
    border: 1px solid #333333;
    border-radius: 8px;
    color: #d6d6d6;
    font-size: 12px;
    padding: 8px 14px;
}}
QPushButton#SecondaryButton:hover {{
    background: #1b1b1b;
    border-color: #555555;
    color: {COLORS["text"]};
}}
QPushButton#DangerButton {{
    background: #35201d;
    border: 1px solid #6e3d36;
    border-radius: 8px;
    color: #ffb4a8;
    font-size: 12px;
    padding: 8px 14px;
}}
QPushButton#DangerButton:hover {{
    background: #452722;
    border-color: #8a4c42;
}}

QFrame#FilterBar {{
    background: #181818;
    border: 1px solid #292929;
    border-radius: 10px;
}}
QPushButton#KindPill {{
    background: transparent;
    border: 1px solid #303030;
    border-radius: 8px;
    color: #b0b0b0;
    font-size: 11px;
    font-weight: 600;
    padding: 6px 12px;
}}
QPushButton#KindPill:hover {{
    border-color: #4a4a4a;
    color: {COLORS["text"]};
}}
QPushButton#KindPill:checked {{
    background: {COLORS["lime"]};
    border-color: {COLORS["lime"]};
    color: #11160a;
}}
QPushButton#TagPill {{
    background: #202020;
    border: 1px solid transparent;
    border-radius: 7px;
    color: #9a9a9a;
    font-size: 11px;
    padding: 5px 9px;
}}
QPushButton#TagPill:hover {{
    background: #262626;
    color: #d6d6d6;
}}
QPushButton#TagPill:checked {{
    background: #263014;
    border-color: #4c5f20;
    color: #c9f57d;
}}
QPushButton#ClearFilters {{
    background: transparent;
    border: 1px solid #3a3324;
    border-radius: 7px;
    color: #d9b36a;
    font-size: 11px;
    padding: 5px 10px;
}}
QPushButton#ClearFilters:hover {{
    border-color: #6b5a2f;
    color: #ffd98a;
}}
QComboBox#SortCombo, QComboBox#SourceCombo {{
    background: #1e1e1e;
    border: 1px solid #303030;
    border-radius: 7px;
    color: #c8c8c8;
    font-size: 11px;
    padding: 5px 22px 5px 9px;
    min-height: 22px;
}}
QComboBox#SortCombo:hover, QComboBox#SourceCombo:hover {{
    border-color: #4a4a4a;
}}
QComboBox#SortCombo::drop-down, QComboBox#SourceCombo::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox#SortCombo QAbstractItemView, QComboBox#SourceCombo QAbstractItemView {{
    background: #202020;
    border: 1px solid #3a3a3a;
    color: {COLORS["text"]};
    selection-background-color: #2f3d1a;
    selection-color: #d7ffa1;
}}
QPushButton#SourceFilter {{
    background: transparent;
    border: 1px solid #333333;
    border-radius: 7px;
    color: #b0b0b0;
    font-size: 11px;
    padding: 5px 10px;
}}
QPushButton#SourceFilter:hover {{
    border-color: #4a4a4a;
}}
QPushButton#SourceFilter:checked {{
    background: #263014;
    border-color: #4c5f20;
    color: #c9f57d;
}}

QLabel#ResultsTitle {{
    color: {COLORS["text"]};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#ResultsCaption {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}

QFrame#ModCard {{
    background: {COLORS["panel"]};
    border: 1px solid #272727;
    border-radius: 12px;
}}
QFrame#ModCard:hover {{
    background: #1d1d1d;
    border-color: #3f3f3f;
}}
QFrame#ModCard[installed="true"] {{
    border-color: #3a4a22;
}}
QFrame#ModCard[installed="true"]:hover {{
    border-color: #55702e;
}}
QLabel#CategoryBadge {{
    background: rgba(12, 12, 12, 220);
    border: 1px solid #353535;
    border-radius: 5px;
    color: #dcdcdc;
    font-size: 9px;
    font-weight: 700;
    padding: 3px 6px;
}}
QLabel#KindBadge {{
    background: rgba(12, 12, 12, 220);
    border: 1px solid #4c5f20;
    border-radius: 5px;
    color: #c9f57d;
    font-size: 9px;
    font-weight: 700;
    padding: 3px 6px;
}}
QLabel#KindBadge[kind="contraption"] {{
    border-color: #6b5320;
    color: #f0b95a;
}}
QLabel#CardTitle {{
    color: {COLORS["text"]};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#CardMeta {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}
QLabel#CardMetric {{
    color: #9a9a9a;
    font-size: 11px;
}}
QPushButton#DetailsLink {{
    background: transparent;
    border: none;
    color: #9a9a9a;
    font-size: 11px;
    padding: 0 3px;
}}
QPushButton#DetailsLink:hover {{
    color: {COLORS["lime"]};
}}
QPushButton#InstallButton {{
    background: {COLORS["lime"]};
    border: 1px solid {COLORS["lime"]};
    border-radius: 6px;
    color: #11160a;
    font-size: 11px;
    font-weight: 700;
    padding: 5px 10px;
}}
QPushButton#InstallButton:hover {{
    background: #c6ff5c;
    border-color: #c6ff5c;
}}
QPushButton#InstallButton[external="true"] {{
    background: #232323;
    border-color: #3a3a3a;
    color: #d6d6d6;
}}
QPushButton#InstallButton[external="true"]:hover {{
    background: #2a2a2a;
    border-color: #4a4a4a;
}}
QPushButton#InstallButton[installed="true"] {{
    background: #263014;
    border-color: #4c5f20;
    color: #c9f57d;
}}
QLabel#EmptyState {{
    color: #777777;
    font-size: 13px;
    padding: 48px 20px;
}}
QPushButton#LoadMoreButton {{
    background: #1c1c1c;
    border: 1px solid #333333;
    border-radius: 8px;
    color: #d6d6d6;
    font-size: 12px;
    padding: 9px 16px;
}}
QPushButton#LoadMoreButton:hover {{
    border-color: {COLORS["lime_dark"]};
    color: {COLORS["lime"]};
}}
QPushButton#LoadMoreButton:disabled {{
    color: #666666;
    border-color: #2a2a2a;
}}

QFrame#InstalledCard {{
    background: {COLORS["panel"]};
    border: 1px solid #272727;
    border-radius: 10px;
}}
QFrame#InstalledCard:hover {{
    background: #1d1d1d;
    border-color: #3d3d3d;
}}
QLabel#InstalledTitle {{
    color: {COLORS["text"]};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#InstalledMeta {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}
QPushButton#InstalledAction {{
    background: transparent;
    border: 1px solid #343434;
    border-radius: 6px;
    color: #b4b4b4;
    font-size: 11px;
    padding: 4px 9px;
}}
QPushButton#InstalledAction:hover {{
    border-color: #5a6b2c;
    color: {COLORS["lime"]};
}}
QPushButton#InstalledAction:disabled {{
    color: #555555;
    border-color: #292929;
}}
QLabel#InstalledNote {{
    background: #202a12;
    border: 1px solid #3f5120;
    border-radius: 6px;
    color: #c9f57d;
    font-size: 11px;
    padding: 7px 10px;
}}

QLabel#Toast {{
    background: {COLORS["lime"]};
    border-radius: 8px;
    color: #11160a;
    font-size: 11px;
    font-weight: 700;
    padding: 10px 14px;
}}
QProgressBar {{
    background: #1b1b1b;
    border: 1px solid #2e2e2e;
    border-radius: 4px;
    color: #cccccc;
    font-size: 9px;
    text-align: center;
    min-height: 14px;
}}
QProgressBar::chunk {{
    background: {COLORS["lime"]};
    border-radius: 3px;
}}
QStatusBar {{
    background: {COLORS["bg_alt"]};
    border-top: 1px solid #232323;
    color: #7d7d7d;
    font-size: 10px;
}}
QStatusBar QLabel {{
    color: #7d7d7d;
    font-size: 10px;
}}

QDialog {{
    background: #1c1c1c;
    color: {COLORS["text"]};
}}
QLabel#DialogKicker {{
    color: {COLORS["lime"]};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#DialogTitle {{
    color: {COLORS["text"]};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#DialogText {{
    color: #b5b5b5;
    font-size: 12px;
}}
QLabel#DialogSmall {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QLabel#DialogMetaKey {{
    color: #777777;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#DialogMetaValue {{
    color: #d6d6d6;
    font-size: 12px;
}}
QFrame#DialogDivider {{
    background: #303030;
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QLabel#TagPill {{
    background: #242424;
    border: 1px solid #333333;
    border-radius: 5px;
    color: #a8a8a8;
    font-size: 9px;
    padding: 3px 6px;
}}
QLabel#Banner {{
    background: #2a2416;
    border: 1px solid #5c4a24;
    border-radius: 6px;
    color: #e7c987;
    font-size: 11px;
    padding: 7px 10px;
}}
QMessageBox {{
    background: #1f1f1f;
}}
QMessageBox QLabel {{
    color: {COLORS["text"]};
    font-size: 12px;
}}
QFileDialog {{
    background: #1f1f1f;
}}

QPushButton#CommunityButton {{
    background: transparent;
    border: 1px solid #303030;
    border-radius: 7px;
    color: #b8b8b8;
    font-size: 11px;
    font-weight: 600;
    padding: 6px 11px;
}}
QPushButton#CommunityButton:hover {{
    background: #1d1d1d;
    border-color: #4a4a4a;
    color: {COLORS["text"]};
}}
QPushButton#CommunityButton::menu-indicator {{
    image: none;
    width: 0px;
}}
QMenu {{
    background: #1d1d1d;
    border: 1px solid #383838;
    border-radius: 8px;
    color: {COLORS["text"]};
    padding: 6px;
}}
QMenu::item {{
    background: transparent;
    border-radius: 5px;
    font-size: 12px;
    padding: 7px 24px 7px 12px;
}}
QMenu::item:selected {{
    background: #2b3718;
    color: #d7ffa1;
}}
QMenu::separator {{
    background: #333333;
    height: 1px;
    margin: 5px 8px;
}}

QLabel#HeroMeta {{
    color: #9a9a9a;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#SiteMetaLine {{
    color: #8f8f8f;
    font-size: 10px;
}}

QFrame#NoticeBanner {{
    background: #1c2213;
    border: 1px solid #3d4a24;
    border-radius: 9px;
}}
QFrame#NoticeAccent {{
    background: {COLORS["lime"]};
    border-radius: 1px;
}}
QLabel#NoticeKicker {{
    color: {COLORS["lime"]};
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
}}
QLabel#NoticeTitle {{
    color: #e6f3cf;
    font-size: 13px;
    font-weight: 700;
}}
QLabel#NoticeText {{
    color: #aebd94;
    font-size: 11px;
}}
QPushButton#NoticeClose {{
    background: transparent;
    border: 1px solid #3f4b2a;
    border-radius: 6px;
    color: #a9b88e;
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#NoticeClose:hover {{
    background: #2a331b;
    border-color: #5e7138;
    color: {COLORS["text"]};
}}

QLabel#SectionTitle {{
    color: {COLORS["text"]};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#SectionCaption {{
    color: {COLORS["muted"]};
    font-size: 11px;
}}
QPushButton#RailArrow {{
    background: #1c1c1c;
    border: 1px solid #333333;
    border-radius: 6px;
    color: #bdbdbd;
    font-size: 16px;
    font-weight: 700;
    min-width: 26px;
    max-width: 26px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
}}
QPushButton#RailArrow:hover {{
    background: #242424;
    border-color: #4c5f20;
    color: {COLORS["lime"]};
}}

QFrame#FreshCard {{
    background: #191919;
    border: 1px solid #292929;
    border-radius: 10px;
}}
QFrame#FreshCard:hover {{
    background: #1e1e1e;
    border-color: #46512c;
}}
QLabel#FreshTitle {{
    color: {COLORS["text"]};
    font-size: 12px;
    font-weight: 600;
}}
QLabel#FreshMeta {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QLabel#FreshBadge {{
    background: rgba(12, 12, 12, 225);
    border: 1px solid #4a4a4a;
    border-radius: 5px;
    color: #d8d8d8;
    font-size: 9px;
    font-weight: 700;
    padding: 3px 6px;
}}
QLabel#FreshBadge[fresh="true"] {{
    background: rgba(26, 38, 12, 235);
    border-color: #4c5f20;
    color: #c9f57d;
}}

QFrame#MiniModCard {{
    background: #1a1a1a;
    border: 1px solid #2b2b2b;
    border-radius: 8px;
}}
QFrame#MiniModCard:hover {{
    background: #1f1f1f;
    border-color: #4a5a2b;
}}
QLabel#MiniTitle {{
    color: #e8e8e8;
    font-size: 12px;
    font-weight: 600;
}}
QLabel#MiniMeta {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}

QPushButton#RandomButton {{
    background: #20261a;
    border: 1px solid #3d4a24;
    border-radius: 7px;
    color: #c9f57d;
    font-size: 11px;
    font-weight: 700;
    padding: 5px 10px;
}}
QPushButton#RandomButton:hover {{
    background: #29331d;
    border-color: #5e7138;
    color: #e0ffad;
}}
QPushButton#HowToStart {{
    background: transparent;
    border: 1px solid #343434;
    border-radius: 8px;
    color: #cfcfcf;
    font-size: 12px;
    padding: 8px 13px;
}}
QPushButton#HowToStart:hover {{
    background: #1c1c1c;
    border-color: #555555;
    color: {COLORS["text"]};
}}
QPushButton#HowToStart[fresh="true"] {{
    border-color: #5e7138;
    color: #d7ffa1;
    background: #1d2414;
}}

QLabel#PinnedBadge, QLabel#UpdateBadge, QLabel#BrokenBadge,
QLabel#TierBadge, QLabel#FollowingBadge {{
    border-radius: 5px;
    font-size: 9px;
    font-weight: 700;
    padding: 3px 6px;
}}
QLabel#PinnedBadge {{
    background: rgba(30, 40, 16, 235);
    border: 1px solid #5a702c;
    color: #d7ffa1;
}}
QLabel#UpdateBadge {{
    background: rgba(34, 34, 14, 235);
    border: 1px solid #6e642c;
    color: #f0dc86;
}}
QLabel#BrokenBadge {{
    background: rgba(42, 20, 18, 235);
    border: 1px solid #6e3d36;
    color: #ffb4a8;
}}
QLabel#TierBadge {{
    background: rgba(20, 30, 44, 235);
    border: 1px solid #3d5a78;
    color: #a9d0f5;
}}
QLabel#FollowingBadge {{
    background: rgba(28, 24, 40, 235);
    border: 1px solid #5a4a7a;
    color: #d4c4ff;
}}

QWidget#DetailsHeader {{
    background: #1c1c1c;
}}
QWidget#DetailsActionBar {{
    background: #1c1c1c;
}}
QPushButton#LikeButton {{
    background: #231a1c;
    border: 1px solid #4a3036;
    border-radius: 7px;
    color: #e8a6b0;
    font-size: 12px;
    font-weight: 700;
    padding: 7px 12px;
}}
QPushButton#LikeButton:hover {{
    background: #2d2023;
    border-color: #6e4048;
}}
QPushButton#LikeButton:checked {{
    background: #3a1c22;
    border-color: #8a4a56;
    color: #ffb3c0;
}}
QPushButton#FollowButton {{
    background: #1b1b24;
    border: 1px solid #38384e;
    border-radius: 7px;
    color: #b9b9d6;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 12px;
}}
QPushButton#FollowButton:hover {{
    background: #22222e;
    border-color: #55557a;
}}
QPushButton#FollowButton:checked {{
    background: #26203a;
    border-color: #6a5a9a;
    color: #d4c4ff;
}}

QFrame#DetailSection {{
    background: #191919;
    border: 1px solid #292929;
    border-radius: 10px;
}}
QLabel#DetailSectionTitle {{
    color: {COLORS["text"]};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#DetailSectionCaption {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QLabel#DetailText {{
    color: #bcbcbc;
    font-size: 12px;
}}
QLabel#LoadingNote {{
    background: #1d2414;
    border: 1px solid #3d4a24;
    border-radius: 7px;
    color: #c9d8ad;
    font-size: 11px;
    padding: 8px 11px;
}}
QFrame#VersionRow {{
    background: #1e1e1e;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
}}
QLabel#VersionTag {{
    background: #263014;
    border: 1px solid #4c5f20;
    border-radius: 5px;
    color: #c9f57d;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
}}
QLabel#VersionDate {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QFrame#DependencyRow {{
    background: #1e1e1e;
    border: 1px solid #2e2e2e;
    border-radius: 7px;
}}
QLabel#DependencyTitle {{
    color: #dedede;
    font-size: 12px;
    font-weight: 600;
}}

QFrame#CommentRow {{
    background: #1e1e1e;
    border: 1px solid #2d2d2d;
    border-radius: 8px;
}}
QLabel#CommentAuthor {{
    color: #e6e6e6;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#CommentBadge {{
    border-radius: 4px;
    font-size: 8px;
    font-weight: 700;
    padding: 2px 5px;
    background: #2a2414;
    border: 1px solid #5c4a24;
    color: #e7c987;
}}
QLabel#CommentBadge[color="blue"] {{
    background: #16222e;
    border-color: #33506b;
    color: #a9d0f5;
}}
QLabel#CommentBadge[color="green"] {{
    background: #182614;
    border-color: #3d5a2c;
    color: #b7e79a;
}}
QLabel#CommentBadge[color="red"] {{
    background: #2a1716;
    border-color: #633832;
    color: #f0a49a;
}}
QLabel#CommentBadge[color="purple"] {{
    background: #211a2e;
    border-color: #4e3d6b;
    color: #d4c4ff;
}}
QLabel#CommentMeta {{
    color: {COLORS["muted"]};
    font-size: 9px;
}}
QLabel#CommentBody {{
    color: #bdbdbd;
    font-size: 11px;
}}

QFrame#PostCard {{
    background: #191919;
    border: 1px solid #292929;
    border-radius: 9px;
}}
QFrame#PostCard:hover {{
    background: #1e1e1e;
    border-color: #46512c;
}}
QLabel#PostCardKicker {{
    color: {COLORS["lime"]};
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
}}
QLabel#PostCardTitle {{
    color: {COLORS["text"]};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#PostCardSummary {{
    color: #9c9c9c;
    font-size: 10px;
}}
QLabel#PostCardMeta {{
    color: {COLORS["muted"]};
    font-size: 9px;
}}
QFrame#PostRow {{
    background: #191919;
    border: 1px solid #292929;
    border-radius: 9px;
}}
QFrame#PostRow:hover {{
    background: #1e1e1e;
    border-color: #46512c;
}}
QLabel#PostTitle {{
    color: {COLORS["text"]};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#PostSummary {{
    color: #9f9f9f;
    font-size: 11px;
}}
QLabel#PostMeta {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}

QFrame#IdeaRow {{
    background: #191919;
    border: 1px solid #292929;
    border-radius: 9px;
}}
QFrame#IdeaRow:hover {{
    background: #1e1e1e;
    border-color: #46512c;
}}
QLabel#IdeaVotes {{
    color: {COLORS["lime"]};
    font-size: 16px;
    font-weight: 800;
}}
QLabel#IdeaVotesCaption {{
    color: {COLORS["muted"]};
    font-size: 8px;
}}
QLabel#IdeaTitle {{
    color: {COLORS["text"]};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#IdeaBody {{
    color: #9f9f9f;
    font-size: 10px;
}}
QLabel#IdeaMeta {{
    color: {COLORS["muted"]};
    font-size: 9px;
}}
QLabel#StatusBadge {{
    border-radius: 5px;
    font-size: 9px;
    font-weight: 700;
    padding: 3px 7px;
    background: #242424;
    border: 1px solid #3a3a3a;
    color: #c0c0c0;
}}
QLabel#StatusBadge[status="open"] {{
    background: #1d2414;
    border-color: #4c5f20;
    color: #c9f57d;
}}
QLabel#StatusBadge[status="planned"] {{
    background: #241f12;
    border-color: #5c4a24;
    color: #e7c987;
}}
QLabel#StatusBadge[status="done"] {{
    background: #16222e;
    border-color: #33506b;
    color: #a9d0f5;
}}
QLabel#StatusBadge[status="in-progress"] {{
    background: #1b2230;
    border-color: #36506b;
    color: #b7d4f0;
}}
QLabel#StatusBadge[status="rejected"] {{
    background: #2a1716;
    border-color: #633832;
    color: #f0a49a;
}}

QFrame#StepCard {{
    background: #191919;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
}}
QLabel#StepNumber {{
    background: #263014;
    border: 1px solid #4c5f20;
    border-radius: 17px;
    color: #c9f57d;
    font-size: 14px;
    font-weight: 800;
}}
QLabel#StepTitle {{
    color: {COLORS["text"]};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#StepText {{
    color: #a8a8a8;
    font-size: 11px;
}}
QLabel#BulletText {{
    color: #b0b0b0;
    font-size: 11px;
}}

QFrame#TeamRow {{
    background: #1e1e1e;
    border: 1px solid #2e2e2e;
    border-radius: 7px;
}}
QLabel#TeamName {{
    color: #ededed;
    font-size: 12px;
    font-weight: 700;
}}
QLabel#TeamRoles {{
    color: {COLORS["muted"]};
    font-size: 10px;
}}
QFrame#TierCard {{
    background: #1a1a1a;
    border: 1px solid #333333;
    border-radius: 10px;
}}
QLabel#TierName {{
    color: {COLORS["lime"]};
    font-size: 17px;
    font-weight: 800;
}}
QLabel#TierPrice {{
    color: #d8d8d8;
    font-size: 11px;
    font-weight: 600;
}}
QWidget#CommunityFooter {{
    background: #1c1c1c;
    border-top: 1px solid #2a2a2a;
}}
QLabel#DiagnosticsBox {{
    background: #141414;
    border: 1px solid #2e2e2e;
    border-radius: 7px;
    color: #b8c8a0;
    font-family: "Noto Sans Mono", "DejaVu Sans Mono", monospace;
    font-size: 10px;
    padding: 9px 11px;
}}
"""
