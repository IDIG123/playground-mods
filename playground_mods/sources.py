from __future__ import annotations

import logging
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlparse

import requests
from lxml import html as lxml_html
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import (
    Idea,
    Mod,
    ModComment,
    ModDependency,
    ModDetail,
    ModVersion,
    Post,
    ResolvedDownload,
    SiteConfig,
    SiteMeta,
)

log = logging.getLogger(__name__)

SWITCH_BASE = "https://deswitchstudio.com"
SWITCH_API = f"{SWITCH_BASE}/api/mods"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 PlaygroundMods/1.0"
)


class SourceError(RuntimeError):
    pass


def _normalise_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_count(value: str) -> int:
    match = re.search(r"([\d.,]+)\s*([KkMm])?", value or "")
    if not match:
        return 0
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return 0
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def _clean_title(title: str) -> str:
    title = _normalise_space(title)
    return re.sub(r"\s+for People Playground\s*$", "", title, flags=re.I)


def _iso_date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value[:32]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _badge(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    text = str(value.get("text") or "").strip()
    color = str(value.get("color") or "").strip()
    return {"text": text, "color": color} if text else {}


def _unique_urls(values: list[Any]) -> list[str]:
    urls: list[str] = []
    for value in values:
        if not value:
            continue
        resolved = urljoin(SWITCH_BASE, str(value))
        if resolved not in urls:
            urls.append(resolved)
    return urls


class CatalogueService:
    """Fetches and normalises the two People Playground catalogues."""

    def __init__(self) -> None:
        self._thread_local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                backoff_factor=0.45,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "HEAD"}),
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            self._thread_local.session = session
        return session

    def _get(self, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", 25)
        try:
            response = self._session().get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise SourceError(str(exc)) from exc

    def _get_json(self, url: str, **kwargs) -> dict[str, Any]:
        response = self._get(url, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceError("The site returned invalid data") from exc
        if not isinstance(payload, dict):
            raise SourceError("The site returned an unexpected response")
        return payload

    # ------------------------------------------------------------------
    # Switch Studio catalogue
    # ------------------------------------------------------------------
    def _switch_mod(self, item: dict[str, Any]) -> Mod | None:
        slug = str(item.get("slug") or "")
        if not slug:
            return None
        cover = str(item.get("cover") or "")
        gallery = _unique_urls([cover, *(item.get("images") or [])])
        tier = str(item.get("tier") or "")
        has_file = bool(item.get("hasFile", True))
        can_download = bool(item.get("canDownload", False))
        free = can_download and has_file and not tier
        videos = [str(video) for video in item.get("videos") or [] if video]
        video = str(item.get("video") or "")
        if video and video not in videos:
            videos.insert(0, video)
        tags = [str(tag).lower() for tag in item.get("tags") or [] if tag]
        locked = bool(item.get("locked"))
        if free:
            locked_reason = ""
        elif not has_file:
            locked_reason = "No file is attached to this mod yet"
        elif item.get("broken"):
            locked_reason = "This mod is marked as broken by the site team"
        elif tier:
            locked_reason = "Needs a Switch Studio Basic or Pro subscription"
        elif locked:
            locked_reason = "Requires a Switch Studio account or license"
        else:
            locked_reason = "This mod is not available for direct download"
        return Mod(
            uid=f"switch:{slug}",
            source="Switch Studio",
            title=_normalise_space(str(item.get("title") or slug)),
            summary=_normalise_space(str(item.get("summary") or "")),
            url=f"{SWITCH_BASE}/mod/{slug}",
            image_url=gallery[0] if gallery else "",
            images=gallery,
            tags=tags or ["mod"],
            version=str(item.get("version") or ""),
            game_version=str(item.get("gameVersion") or ""),
            author=_normalise_space(
                str(item.get("modAuthor") or item.get("author") or "")
            ),
            metric=_int(item.get("downloads")),
            metric_label="downloads",
            published=_iso_date(str(item.get("releasedAt") or "")),
            install_mode="direct" if free else "external",
            download_url=f"{SWITCH_API}/{slug}/download" if free else "",
            slug=slug,
            locked_reason=locked_reason,
            site_id=_int(item.get("id")),
            no=_int(item.get("no")),
            video=video,
            videos=videos,
            updated=bool(item.get("updated")),
            latest_ver=_int(item.get("latestVer")),
            file_size=_int(item.get("fileSize")),
            has_file=has_file,
            status=str(item.get("status") or "published"),
            tier=tier,
            licensed=bool(item.get("licensed")),
            likes=_int(item.get("likes")),
            comments_count=_int(item.get("comments")),
            author_badge=_badge(item.get("authorBadge")),
            mod_author=_normalise_space(str(item.get("modAuthor") or "")),
            idea_author=_normalise_space(str(item.get("ideaAuthor") or "")),
            studio=_int(item.get("studio")),
            pinned=bool(item.get("pinned")),
            broken=bool(item.get("broken")),
            created_at=_iso_date(str(item.get("createdAt") or "")),
            updated_at=_iso_date(str(item.get("updatedAt") or "")),
            locked=locked,
            can_download=can_download,
            can_manage=bool(item.get("canManage")),
            following=bool(item.get("following")),
        )

    def _fetch_switch_page(self, page: int) -> tuple[list[Mod], int]:
        payload = self._get_json(f"{SWITCH_API}?page={page}&limit=100")
        mods: list[Mod] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            mod = self._switch_mod(item)
            if mod is not None:
                mods.append(mod)
        return mods, _int(payload.get("pages"), 1)

    def fetch_switch(
        self, status: Callable[[str], None] | None = None
    ) -> list[Mod]:
        if status:
            status("Loading Switch Studio catalogue…")
        first, pages = self._fetch_switch_page(1)
        by_uid = {mod.uid: mod for mod in first}
        if pages > 1:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self._fetch_switch_page, page): page
                    for page in range(2, pages + 1)
                }
                for index, future in enumerate(as_completed(futures), start=1):
                    try:
                        items, _ = future.result()
                    except Exception as exc:  # one broken page should not kill the rest
                        log.warning("Switch page failed: %s", exc)
                        continue
                    for mod in items:
                        by_uid[mod.uid] = mod
                    if status:
                        status(f"Switch Studio · {index + 1}/{pages} pages")
        return list(by_uid.values())

    # ------------------------------------------------------------------
    # Site metadata
    # ------------------------------------------------------------------
    def fetch_site_meta(self) -> SiteMeta:
        meta = SiteMeta()
        requests = {
            "config": f"{SWITCH_BASE}/api/config",
            "stats": f"{SWITCH_BASE}/api/stats",
            "tags": f"{SWITCH_BASE}/api/tags",
            "free": f"{SWITCH_BASE}/api/mods?access=free&limit=1",
            "featured": f"{SWITCH_BASE}/api/featured",
            "trending": f"{SWITCH_BASE}/api/trending",
        }
        payloads: dict[str, dict[str, Any]] = {}
        # These endpoints are independent; fetching them together keeps the
        # catalogue refresh from waiting on six sequential round trips.
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(self._get_json, url): key
                for key, url in requests.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    payloads[key] = future.result()
                except Exception as exc:  # noqa: BLE001 - optional metadata
                    log.info("Could not load site %s: %s", key, exc)
        if "config" in payloads:
            meta.config = SiteConfig.from_dict(payloads["config"])
        if "stats" in payloads:
            meta.stats = payloads["stats"]
        if "tags" in payloads:
            meta.tags = [
                item
                for item in payloads["tags"].get("items") or []
                if isinstance(item, dict)
            ]
        if "free" in payloads:
            meta.free_total = _int(payloads["free"].get("total"))
        if "featured" in payloads:
            meta.featured = [
                mod
                for item in payloads["featured"].get("mods") or []
                if isinstance(item, dict) and (mod := self._switch_mod(item))
            ]
        if "trending" in payloads:
            meta.trending = [
                mod
                for item in payloads["trending"].get("items") or []
                if isinstance(item, dict) and (mod := self._switch_mod(item))
            ]
        return meta

    # ------------------------------------------------------------------
    # Rich mod details
    # ------------------------------------------------------------------
    def fetch_mod_detail(self, mod: Mod) -> ModDetail:
        if mod.source == "Switch Studio" and mod.slug:
            payload = self._get_json(f"{SWITCH_API}/{quote(mod.slug)}")
            return self._switch_detail(payload)
        return ModDetail(
            description=mod.summary,
            gallery=[mod.image_url] if mod.image_url else [],
            source_page=mod.url,
        )

    @staticmethod
    def _switch_detail(payload: dict[str, Any]) -> ModDetail:
        versions: list[ModVersion] = []
        for item in payload.get("versions") or []:
            if not isinstance(item, dict):
                continue
            scan = item.get("scan") if isinstance(item.get("scan"), dict) else {}
            versions.append(
                ModVersion(
                    version=str(item.get("version") or ""),
                    changelog=str(item.get("changelog") or ""),
                    size=_int(item.get("size")),
                    sha256=str(item.get("sha256") or ""),
                    created_at=_iso_date(str(item.get("createdAt") or "")),
                    av=str(scan.get("av") or ""),
                )
            )
        deps: list[ModDependency] = []
        for item in payload.get("deps") or []:
            if not isinstance(item, dict):
                continue
            deps.append(
                ModDependency(
                    slug=str(item.get("slug") or ""),
                    title=str(item.get("title") or ""),
                    tier=str(item.get("tier") or ""),
                    locked=bool(item.get("locked")),
                    draft=bool(item.get("draft")),
                )
            )
        editions = (
            payload.get("editions") if isinstance(payload.get("editions"), dict) else {}
        )
        gallery = _unique_urls(
            [str(payload.get("cover") or ""), *(payload.get("images") or [])]
        )
        return ModDetail(
            description=str(payload.get("description") or ""),
            versions=versions,
            deps=deps,
            editions=editions,
            featured=bool(payload.get("featured")),
            following=bool(payload.get("following")),
            gallery=gallery,
            source_page=f"{SWITCH_BASE}/mod/{payload.get('slug') or ''}",
        )

    # ------------------------------------------------------------------
    # Comments, related mods, news and ideas
    # ------------------------------------------------------------------
    def fetch_comments(self, item_type: str, item_id: int) -> list[ModComment]:
        if not item_id:
            return []
        payload = self._get_json(
            f"{SWITCH_BASE}/api/comments?type={quote(item_type)}&id={item_id}"
        )
        comments: list[ModComment] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            parent = item.get("parentId")
            comments.append(
                ModComment(
                    id=_int(item.get("id")),
                    body=str(item.get("body") or ""),
                    author=str(item.get("author") or "Someone"),
                    author_role=str(item.get("authorRole") or "user"),
                    author_badge=_badge(item.get("authorBadge")),
                    created_at=_iso_date(str(item.get("createdAt") or "")),
                    parent_id=_int(parent) if parent not in (None, "") else None,
                    reply_to_author=str(item.get("replyToAuthor") or ""),
                    likes=_int(item.get("likes")),
                    edited_at=_iso_date(str(item.get("editedAt") or "")),
                )
            )
        return comments

    def fetch_related(self, slug: str) -> list[Mod]:
        if not slug:
            return []
        payload = self._get_json(f"{SWITCH_API}/{quote(slug)}/related")
        mods: list[Mod] = []
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                mod = self._switch_mod(item)
                if mod is not None:
                    mods.append(mod)
        return mods

    def fetch_posts(self, page: int = 1) -> tuple[list[Post], int]:
        payload = self._get_json(f"{SWITCH_BASE}/api/posts?page={max(1, page)}")
        posts: list[Post] = []
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            posts.append(self._post(item))
        return posts, _int(payload.get("pages"), 1)

    def fetch_post(self, slug: str) -> Post:
        payload = self._get_json(f"{SWITCH_BASE}/api/posts/{quote(slug)}")
        return self._post(payload)

    @staticmethod
    def _post(item: dict[str, Any]) -> Post:
        cover = str(item.get("cover") or "")
        return Post(
            id=_int(item.get("id")),
            slug=str(item.get("slug") or ""),
            title=str(item.get("title") or ""),
            summary=str(item.get("summary") or ""),
            body=str(item.get("body") or ""),
            cover=urljoin(SWITCH_BASE, cover) if cover else "",
            video=str(item.get("video") or ""),
            author=str(item.get("author") or ""),
            author_badge=_badge(item.get("authorBadge")),
            created_at=_iso_date(str(item.get("createdAt") or "")),
            views=_int(item.get("views")),
            likes=_int(item.get("likes")),
            comments=_int(item.get("comments")),
        )

    def fetch_ideas(self, tab: str = "top") -> list[Idea]:
        if tab not in {"top", "new", "planned", "done"}:
            tab = "top"
        payload = self._get_json(f"{SWITCH_BASE}/api/ideas?tab={tab}")
        ideas: list[Idea] = []
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                ideas.append(self._idea(item))
        return ideas

    def fetch_idea(self, idea_id: int) -> Idea:
        payload = self._get_json(f"{SWITCH_BASE}/api/ideas/{int(idea_id)}")
        return self._idea(payload)

    @staticmethod
    def _idea(item: dict[str, Any]) -> Idea:
        mod = item.get("mod") if isinstance(item.get("mod"), dict) else {}
        return Idea(
            id=_int(item.get("id")),
            title=str(item.get("title") or ""),
            body=str(item.get("body") or ""),
            status=str(item.get("status") or "open"),
            author=str(item.get("author") or ""),
            author_badge=_badge(item.get("authorBadge")),
            votes=_int(item.get("votes")),
            comments=_int(item.get("comments")),
            mod_slug=str(mod.get("slug") or ""),
            mod_title=str(mod.get("title") or ""),
            created_at=_iso_date(str(item.get("createdAt") or "")),
        )
