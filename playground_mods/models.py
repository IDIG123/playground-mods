from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# People Playground keeps two kinds of content in sibling folders:
#   * mods          -> "<game>/Mods"          (identified by a mod.json config)
#   * contraptions  -> "<game>/Contraptions"  (identified by a .jaap file)
KIND_MOD = "mod"
KIND_CONTRAPTION = "contraption"

KIND_LABELS = {
    KIND_MOD: "Mod",
    KIND_CONTRAPTION: "Contraption",
}
KIND_BADGES = {
    KIND_MOD: "MOD",
    KIND_CONTRAPTION: "CONTRA",
}
KIND_FOLDER_NAMES = {
    KIND_MOD: "Mods",
    KIND_CONTRAPTION: "Contraptions",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, "Mod")


def kind_badge(kind: str) -> str:
    return KIND_BADGES.get(kind, "")


def kind_folder_name(kind: str) -> str:
    return KIND_FOLDER_NAMES.get(kind, "Mods")


@dataclass(slots=True)
class Mod:
    uid: str
    source: str
    title: str
    summary: str
    url: str
    image_url: str = ""
    images: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: str = ""
    game_version: str = ""
    author: str = ""
    metric: int = 0
    metric_label: str = "downloads"
    published: str = ""
    install_mode: str = "external"
    download_url: str = ""
    slug: str = ""
    locked_reason: str = ""
    kind: str = ""  # "" = unknown, otherwise KIND_MOD / KIND_CONTRAPTION

    # Switch Studio catalogue fields. The detail endpoint fills what it can.
    site_id: int = 0
    no: int = 0
    video: str = ""
    videos: list[str] = field(default_factory=list)
    updated: bool = False
    latest_ver: int = 0
    file_size: int = 0
    has_file: bool = True
    status: str = "published"
    tier: str = ""
    licensed: bool = False
    likes: int = 0
    comments_count: int = 0
    author_badge: dict[str, str] = field(default_factory=dict)
    mod_author: str = ""
    idea_author: str = ""
    studio: int = 0
    pinned: bool = False
    broken: bool = False
    created_at: str = ""
    updated_at: str = ""
    locked: bool = False
    can_download: bool = True
    can_manage: bool = False
    following: bool = False

    @property
    def tag(self) -> str:
        return self.tags[0] if self.tags else "mod"

    @property
    def is_free_download(self) -> bool:
        return self.install_mode == "direct" and bool(self.download_url)

    @property
    def is_paid(self) -> bool:
        return bool(self.tier) or self.install_mode == "external"

    @property
    def is_free(self) -> bool:
        return not self.tier and self.install_mode in ("direct", "resolve")

    @property
    def source_short(self) -> str:
        return "SWITCH"

    @property
    def kind_label(self) -> str:
        return kind_label(self.kind) if self.kind else ""

    @property
    def kind_badge(self) -> str:
        return kind_badge(self.kind) if self.kind else ""

    @property
    def creator(self) -> str:
        return self.mod_author or self.author or "Unknown creator"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mod":
        known = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass(slots=True)
class InstalledMod:
    folder: str
    path: str
    title: str
    author: str = ""
    description: str = ""
    thumbnail: str = ""
    has_mod_json: bool = False
    managed: bool = False
    uid: str = ""
    source: str = ""
    url: str = ""
    kind: str = KIND_MOD

    @property
    def kind_label(self) -> str:
        return kind_label(self.kind)

    @property
    def kind_badge(self) -> str:
        return kind_badge(self.kind)


@dataclass(slots=True)
class CatalogueResult:
    switch_mods: list[Mod]


@dataclass(slots=True)
class ResolvedDownload:
    direct_url: str = ""
    page_urls: list[str] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Rich site data
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ModVersion:
    version: str
    changelog: str = ""
    size: int = 0
    sha256: str = ""
    created_at: str = ""
    av: str = ""


@dataclass(slots=True)
class ModDependency:
    slug: str
    title: str = ""
    tier: str = ""
    locked: bool = False
    draft: bool = False


@dataclass(slots=True)
class ModComment:
    id: int
    body: str
    author: str
    author_role: str = "user"
    author_badge: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    parent_id: int | None = None
    reply_to_author: str = ""
    likes: int = 0
    edited_at: str = ""


@dataclass(slots=True)
class ModDetail:
    description: str = ""
    versions: list[ModVersion] = field(default_factory=list)
    deps: list[ModDependency] = field(default_factory=list)
    editions: dict[str, Any] = field(default_factory=dict)
    featured: bool = False
    following: bool = False
    gallery: list[str] = field(default_factory=list)
    file_info: list[tuple[str, str]] = field(default_factory=list)
    source_page: str = ""


@dataclass(slots=True)
class Post:
    id: int
    slug: str
    title: str
    summary: str = ""
    body: str = ""
    cover: str = ""
    video: str = ""
    author: str = ""
    author_badge: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0


@dataclass(slots=True)
class Idea:
    id: int
    title: str
    body: str = ""
    status: str = "open"
    author: str = ""
    author_badge: dict[str, str] = field(default_factory=dict)
    votes: int = 0
    comments: int = 0
    mod_slug: str = ""
    mod_title: str = ""
    created_at: str = ""


@dataclass(slots=True)
class SiteConfig:
    current_game_version: str = "1.28"
    site_name: str = "Switch Studio"
    tagline: str = "Mods for People Playground"
    patch_slug: str = "restore-mods"
    patch_title: str = "deSwitcher"
    patch_guide: str = ""
    notice_id: str = ""
    notice_title: str = ""
    notice_text: str = ""
    links: dict[str, str] = field(default_factory=dict)
    creator: dict[str, str] = field(default_factory=dict)
    team: list[dict[str, Any]] = field(default_factory=list)
    tiers: list[dict[str, Any]] = field(default_factory=list)
    studios: list[dict[str, Any]] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    max_images: int = 5
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def patch_url(self) -> str:
        return f"https://deswitchstudio.com/mod/{self.patch_slug}" if self.patch_slug else ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SiteConfig":
        if not isinstance(data, dict):
            return cls()
        patch = data.get("patchMod") if isinstance(data.get("patchMod"), dict) else {}
        notice = data.get("notice") if isinstance(data.get("notice"), dict) else {}
        links = data.get("links") if isinstance(data.get("links"), dict) else {}
        creator = data.get("creator") if isinstance(data.get("creator"), dict) else {}
        team = data.get("team") if isinstance(data.get("team"), list) else []
        tiers = data.get("tiers") if isinstance(data.get("tiers"), list) else []
        studios = data.get("studios") if isinstance(data.get("studios"), list) else []
        features = data.get("features") if isinstance(data.get("features"), dict) else {}
        return cls(
            current_game_version=str(data.get("currentGameVersion") or "1.28"),
            site_name=str(data.get("siteName") or "Switch Studio"),
            tagline=str(data.get("tagline") or "Mods for People Playground"),
            patch_slug=str(patch.get("slug") or "restore-mods"),
            patch_title=str(patch.get("title") or "deSwitcher"),
            patch_guide=str(patch.get("guide") or ""),
            notice_id=str(notice.get("id") or ""),
            notice_title=str(notice.get("title") or ""),
            notice_text=str(notice.get("text") or ""),
            links={str(k): str(v) for k, v in links.items()},
            creator={str(k): str(v) for k, v in creator.items()},
            team=[item for item in team if isinstance(item, dict)],
            tiers=[item for item in tiers if isinstance(item, dict)],
            studios=[item for item in studios if isinstance(item, dict)],
            features=features,
            max_images=int(data.get("maxImages") or 5),
            raw=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw or {})


@dataclass(slots=True)
class SiteMeta:
    config: SiteConfig = field(default_factory=SiteConfig)
    stats: dict[str, Any] = field(default_factory=dict)
    tags: list[dict[str, Any]] = field(default_factory=list)
    free_total: int = 0
    featured: list[Mod] = field(default_factory=list)
    trending: list[Mod] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "stats": dict(self.stats),
            "tags": list(self.tags),
            "free_total": self.free_total,
            "featured": [mod.to_dict() for mod in self.featured],
            "trending": [mod.to_dict() for mod in self.trending],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SiteMeta":
        if not isinstance(data, dict):
            return cls()
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        featured = data.get("featured") if isinstance(data.get("featured"), list) else []
        trending = data.get("trending") if isinstance(data.get("trending"), list) else []
        return cls(
            config=SiteConfig.from_dict(data.get("config")),
            stats=dict(stats),
            tags=[item for item in tags if isinstance(item, dict)],
            free_total=int(data.get("free_total") or 0),
            featured=[
                Mod.from_dict(item) for item in featured if isinstance(item, dict)
            ],
            trending=[
                Mod.from_dict(item) for item in trending if isinstance(item, dict)
            ],
        )
