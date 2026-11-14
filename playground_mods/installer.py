from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import requests

from .models import (
    KIND_CONTRAPTION,
    KIND_MOD,
    InstalledMod,
    kind_folder_name,
    kind_label,
)
from .paths import DOWNLOAD_DIR, contraptions_directory, ensure_dirs
from .sources import USER_AGENT

log = logging.getLogger(__name__)

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 10_000

# Content roots that say nothing about the mod itself. When an archive is
# packed as ``mod/mod.json`` or ``files/mod.json`` the title is a better folder
# name than the generic wrapper directory.
_GENERIC_ROOTS = {
    "mod",
    "mods",
    "files",
    "content",
    "people playground mod",
    "people-playground-mod",
}
_STAGING_PREFIX = ".pgm-staging-"
_BACKUP_PREFIX = ".pgm-backup-"


class InstallError(RuntimeError):
    pass


class NotAModError(InstallError):
    pass


class ExistingModError(InstallError):
    def __init__(self, folder: Path) -> None:
        super().__init__(f"The folder “{folder.name}” already exists.")
        self.folder = folder


class CancelledError(InstallError):
    pass


@dataclass(slots=True)
class PreparedInstall:
    archive: Path
    folder_name: str
    content_root: str
    file_count: int
    total_size: int
    cleanup: bool
    title_hint: str
    kind: str = KIND_MOD

    @property
    def kind_label(self) -> str:
        return kind_label(self.kind)

    @property
    def folder_kind_name(self) -> str:
        return kind_folder_name(self.kind)


Progress = Callable[[int, str], None]
IsCancelled = Callable[[], bool]


def sanitize_folder_name(name: str, fallback: str = "People Playground Mod") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    if not name:
        name = fallback
    if len(name) > 96:
        name = name[:96].rstrip()
    return name


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        name = info.filename.replace("\\", "/").lstrip("/")
        if not name:
            continue
        parts = PurePosixPath(name).parts
        if any(part in ("..", "") for part in parts) or re.match(
            r"^[A-Za-z]:", name
        ):
            raise InstallError("The ZIP contains an unsafe file path.")
        if info.flag_bits & 0x1:
            raise InstallError("The ZIP is password protected.")
        members.append(info)
    if len(members) > MAX_ENTRIES:
        raise InstallError("The ZIP contains too many files.")
    return members


def _member_path(info: zipfile.ZipInfo) -> str:
    return info.filename.replace("\\", "/").lstrip("/")


def _basename(path: str) -> str:
    """Lower-case final path component (``Foo/Mod.json`` -> ``mod.json``)."""
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()


def _is_mod_config(path: str) -> bool:
    # Compare the whole basename: ``endswith("mod.json")`` would also accept
    # unrelated files such as ``custommod.json`` or ``notmod.json``.
    return _basename(path) == "mod.json"


def _detect_kind(members: list[zipfile.ZipInfo]) -> str:
    """Decide whether an archive is a mod or a contraption from its contents.

    A ``mod.json`` anywhere in the archive marks a mod (this is the same file
    the game looks for inside ``Mods``). A ``.jaap`` file without any
    ``mod.json`` marks a contraption, which the game reads from
    ``Contraptions``.
    """
    paths = [_member_path(info) for info in members if not info.is_dir()]
    if any(_is_mod_config(path) for path in paths):
        return KIND_MOD
    if any(path.lower().endswith(".jaap") for path in paths):
        return KIND_CONTRAPTION
    return KIND_MOD


def _analyse_archive(archive_path: Path, title_hint: str) -> PreparedInstall:
    if not zipfile.is_zipfile(archive_path):
        raise InstallError("The downloaded file is not a valid ZIP archive.")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_members(archive)
            total_size = sum(max(0, info.file_size) for info in members)
            if total_size > MAX_EXTRACTED_BYTES:
                raise InstallError("The ZIP is too large to install safely.")

            configs = [info for info in members if _is_mod_config(_member_path(info))]
            if not configs:
                # Older People Playground mods use a root-level .json config,
                # while contraptions ship a root-level .jaap plus metadata.
                configs = [
                    info
                    for info in members
                    if _member_path(info).lower().endswith((".json", ".jaap"))
                    and "/" not in _member_path(info).strip("/")
                ]
            if not configs:
                # A contraption packed inside its own sub-folder has no root
                # config; fall back to the shallowest .jaap in the archive.
                configs = [
                    info
                    for info in members
                    if _member_path(info).lower().endswith(".jaap")
                    and not info.is_dir()
                ]
            if not configs:
                raise NotAModError(
                    "This ZIP is not a People Playground mod or contraption. "
                    "Tools such as deSwitcher install into the game folder "
                    "itself, so the app will not place them in the Mods or "
                    "Contraptions directories."
                )

            kind = _detect_kind(members)

            config = min(
                configs,
                key=lambda info: len(PurePosixPath(_member_path(info)).parts),
            )
            config_path = PurePosixPath(_member_path(config))
            content_root = (
                str(config_path.parent) if str(config_path.parent) != "." else ""
            )
            root_name = content_root.split("/")[-1].strip() if content_root else ""
            if root_name and root_name.lower() not in _GENERIC_ROOTS:
                folder_name = sanitize_folder_name(root_name, title_hint)
            else:
                folder_name = sanitize_folder_name(title_hint, root_name or "PPG Mod")
            if not folder_name:
                folder_name = f"PPG_Mod_{uuid.uuid4().hex[:6]}"
            return PreparedInstall(
                archive=archive_path,
                folder_name=folder_name,
                content_root=content_root,
                file_count=sum(1 for info in members if not info.is_dir()),
                total_size=total_size,
                cleanup=False,
                title_hint=title_hint,
                kind=kind,
            )
    except zipfile.BadZipFile as exc:
        raise InstallError("The ZIP archive is damaged or incomplete.") from exc
    except OSError as exc:
        raise InstallError(f"Could not read the ZIP archive: {exc}") from exc


def prepare_local_archive(
    path: Path, title_hint: str = "", progress: Progress | None = None
) -> PreparedInstall:
    if not path.is_file():
        raise InstallError("That file no longer exists.")
    hint = title_hint or path.stem
    if progress:
        progress(20, "Checking archive…")
    prepared = _analyse_archive(path, hint)
    prepared.cleanup = False
    if progress:
        progress(100, "Ready to install")
    return prepared


def prepare_download(
    url: str,
    title_hint: str,
    progress: Progress | None = None,
    cancelled: IsCancelled | None = None,
) -> PreparedInstall:
    ensure_dirs()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = DOWNLOAD_DIR / f"{uuid.uuid4().hex}.zip"
    temporary = target.with_suffix(".part")
    try:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/zip,*/*"}
        with requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=(15, 90),
            allow_redirects=True,
        ) as response:
            if response.status_code != 200:
                message = f"The download server returned HTTP {response.status_code}."
                try:
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        message = str(payload["error"])
                except ValueError:
                    pass
                raise InstallError(message)
            content_type = response.headers.get("Content-Type", "").lower()
            if "json" in content_type or "text/html" in content_type:
                raise InstallError(
                    "The source returned a web page instead of a ZIP. "
                    "Open the download page and import the archive manually."
                )
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_ARCHIVE_BYTES:
                raise InstallError("The archive is unexpectedly large.")
            downloaded = 0
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if cancelled and cancelled():
                        raise CancelledError("Install cancelled.")
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_ARCHIVE_BYTES:
                        raise InstallError("The archive is unexpectedly large.")
                    if progress:
                        percent = int(downloaded * 100 / total) if total else 0
                        size_mb = downloaded / (1024 * 1024)
                        progress(percent, f"Downloading · {size_mb:.1f} MB")
        temporary.replace(target)
        if progress:
            progress(100, "Checking archive…")
        prepared = _analyse_archive(target, title_hint)
        prepared.cleanup = True
        return prepared
    except Exception:
        for path in (temporary, target):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise


def _find_config_in_tree(root: Path) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in (".json", ".jaap"):
            return True
    return False


def _destination_root(prepared: PreparedInstall, mods_root: Path) -> Path:
    """Where this prepared archive should be installed."""
    if prepared.kind == KIND_CONTRAPTION:
        return contraptions_directory(mods_root)
    return mods_root


def extract_prepared(
    prepared: PreparedInstall,
    mods_root: Path,
    overwrite: bool = False,
    progress: Progress | None = None,
    cancelled: IsCancelled | None = None,
    destination_root: Path | None = None,
) -> Path:
    mods_root = Path(mods_root).expanduser()
    target_root = (
        Path(destination_root).expanduser()
        if destination_root is not None
        else _destination_root(prepared, mods_root)
    )

    if not target_root.exists() and target_root != mods_root:
        # The game creates Contraptions on first launch; recreate it so an
        # install can still land in the right place.
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InstallError(
                f"Could not create the {target_root.name} folder:\n{target_root}"
            ) from exc
    if not target_root.is_dir():
        raise InstallError(f"The {target_root.name} folder does not exist:\n{target_root}")

    final = target_root / sanitize_folder_name(prepared.folder_name)
    try:
        final.resolve().relative_to(target_root.resolve())
    except ValueError as exc:
        raise InstallError(
            f"Refusing to install outside the {target_root.name} folder."
        ) from exc
    if final.exists() and not overwrite:
        raise ExistingModError(final)

    staging = Path(
        tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=str(target_root))
    )
    backup: Path | None = None
    try:
        with zipfile.ZipFile(prepared.archive) as archive:
            root_prefix = (
                prepared.content_root.rstrip("/") + "/"
                if prepared.content_root
                else ""
            )
            files = [
                info
                for info in archive.infolist()
                if not info.is_dir() and _member_path(info).startswith(root_prefix)
            ]
            for index, info in enumerate(files, start=1):
                if cancelled and cancelled():
                    raise CancelledError("Install cancelled.")
                name = _member_path(info)
                relative = name[len(root_prefix) :].lstrip("/")
                if not relative:
                    continue
                parts = PurePosixPath(relative).parts
                if any(part in ("..", "") for part in parts):
                    raise InstallError("The ZIP contains an unsafe file path.")
                destination = staging.joinpath(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=256 * 1024)
                if progress and (index == len(files) or index % 8 == 0):
                    progress(
                        int(index * 100 / max(1, len(files))),
                        f"Installing · {index}/{len(files)} files",
                    )

        if not _find_config_in_tree(staging):
            raise NotAModError(
                "The archive did not contain a People Playground mod or "
                "contraption configuration."
            )

        if final.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=_BACKUP_PREFIX, dir=str(target_root))
            ) / final.name
            shutil.move(str(final), str(backup))
        shutil.move(str(staging), str(final))
        if backup is not None:
            shutil.rmtree(backup.parent, ignore_errors=True)
            backup = None
        if progress:
            progress(100, "Installed")
        return final
    except Exception:
        if backup is not None and backup.exists() and not final.exists():
            shutil.move(str(backup), str(final))
            shutil.rmtree(backup.parent, ignore_errors=True)
            backup = None
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists():
            shutil.rmtree(backup.parent, ignore_errors=True)


def _pick(data: dict[str, Any], key: str) -> str:
    for candidate, value in data.items():
        if candidate.lower() == key.lower() and isinstance(value, str):
            return value.strip()
    return ""


def _folder_entries(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir(), key=lambda path: path.name.lower())
    except OSError as exc:
        log.warning("Could not list %s: %s", folder, exc)
        return []


def _folder_has_mod_config(folder: Path) -> bool:
    return any(
        entry.is_file() and entry.name.lower() == "mod.json"
        for entry in _folder_entries(folder)
    )


def _folder_configs(folder: Path) -> list[Path]:
    return [
        entry
        for entry in _folder_entries(folder)
        if entry.is_file() and entry.suffix.lower() in (".json", ".jaap")
    ]


def read_mod_metadata(folder: Path) -> dict[str, str]:
    configs = [
        entry
        for entry in _folder_entries(folder)
        if entry.is_file() and entry.suffix.lower() == ".json"
    ]
    # Prefer the real ``mod.json`` over any other JSON metadata in the folder.
    configs.sort(key=lambda path: (path.name.lower() != "mod.json", path.name.lower()))
    for config in configs:
        try:
            if config.stat().st_size > 2 * 1024 * 1024:
                continue
            with config.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                continue
            # Contraption metadata stores the numeric folder id in "Name" and
            # the human title in "DisplayName"; mod.json uses "Name" for the
            # title and usually has no DisplayName. Prefer DisplayName when set.
            title = _pick(data, "displayname") or _pick(data, "name")
            if not title:
                continue
            return {
                "title": title,
                "author": _pick(data, "author") or _pick(data, "creator"),
                "description": _pick(data, "description"),
                "thumbnail": _pick(data, "thumbnailpath"),
            }
        except (OSError, ValueError, UnicodeError):
            continue
    return {}


def find_thumbnail(folder: Path, metadata: dict[str, str]) -> Path | None:
    thumb = metadata.get("thumbnail", "")
    if thumb:
        candidate = folder / thumb.replace("\\", "/")
        if candidate.is_file():
            return candidate
        for path in folder.rglob(Path(thumb).name):
            if path.is_file():
                return path
    preferred = ("thumb.png", "thumbnail.png", "modthumb.png")
    for name in preferred:
        matches = [p for p in folder.glob("*") if p.name.lower() == name]
        if matches:
            return matches[0]
    images = [
        path
        for path in folder.glob("*")
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    ]
    return images[0] if images else None


def _detect_folder_kind(folder: Path) -> str:
    if _folder_has_mod_config(folder):
        return KIND_MOD
    if any(
        entry.is_file() and entry.suffix.lower() == ".jaap"
        for entry in _folder_entries(folder)
    ):
        return KIND_CONTRAPTION
    return KIND_MOD


def _scan_root(
    root: Path,
    managed_by_key: dict[tuple[str, str], tuple[str, dict[str, Any]]],
    managed_by_folder: dict[str, tuple[str, dict[str, Any]]],
) -> list[InstalledMod]:
    if not root.is_dir():
        return []
    try:
        folders = sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=lambda path: path.name.lower(),
        )
    except OSError as exc:
        log.warning("Could not scan %s: %s", root, exc)
        return []

    installed: list[InstalledMod] = []
    for folder in folders:
        if folder.name.startswith("."):
            continue
        try:
            has_mod_json = _folder_has_mod_config(folder)
            configs = _folder_configs(folder)
            if not has_mod_json and not configs:
                continue
            kind = _detect_folder_kind(folder)
            metadata = read_mod_metadata(folder)
            title = metadata.get("title") or folder.name
            if not metadata and configs:
                title = configs[0].stem
            thumb = find_thumbnail(folder, metadata)
            record = managed_by_key.get((kind, folder.name)) or managed_by_folder.get(
                folder.name
            )
            installed.append(
                InstalledMod(
                    folder=folder.name,
                    path=str(folder),
                    title=title,
                    author=metadata.get("author", ""),
                    description=metadata.get("description", ""),
                    thumbnail=str(thumb) if thumb else "",
                    has_mod_json=has_mod_json,
                    managed=record is not None,
                    uid=record[0] if record else "",
                    source=str(record[1].get("source", "")) if record else "",
                    url=str(record[1].get("url", "")) if record else "",
                    kind=kind,
                )
            )
        except OSError as exc:
            log.warning("Could not inspect %s: %s", folder, exc)
    return installed


def scan_installed(
    mods_root: Path,
    managed: dict[str, dict[str, Any]] | None = None,
    contraptions_root: Path | None = None,
) -> list[InstalledMod]:
    managed = managed or {}
    managed_by_folder = {
        str(record.get("folder") or ""): (uid, record)
        for uid, record in managed.items()
    }
    managed_by_key = {
        (str(record.get("kind") or KIND_MOD), str(record.get("folder") or "")): (
            uid,
            record,
        )
        for uid, record in managed.items()
    }

    contraptions_root = contraptions_root or contraptions_directory(mods_root)
    for root in (Path(mods_root), Path(contraptions_root)):
        cleanup_stale_workdirs(root)
    installed = _scan_root(Path(mods_root), managed_by_key, managed_by_folder)
    installed += _scan_root(
        Path(contraptions_root), managed_by_key, managed_by_folder
    )
    installed.sort(key=lambda item: (item.kind != KIND_MOD, item.title.lower()))
    return installed


def remove_managed_mod(
    folder: Path, root: Path, managed_record: dict[str, Any]
) -> None:
    if not managed_record:
        raise InstallError("This item was not installed by Playground Mods.")
    recorded_folder = str(managed_record.get("folder") or "")
    if recorded_folder and recorded_folder != folder.name:
        raise InstallError(
            "The install record does not match this folder, so it was left alone."
        )
    root = Path(root).expanduser()
    try:
        resolved = folder.resolve()
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise InstallError(
            f"Refusing to remove a folder outside the {root.name} directory."
        ) from exc
    if not resolved.is_dir():
        raise InstallError("The item folder no longer exists.")
    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        raise InstallError(f"Could not remove the folder: {exc}") from exc


def cleanup_stale_workdirs(root: Path, max_age_hours: int = 6) -> int:
    """Remove abandoned staging/backup directories left by an interrupted install."""
    root = Path(root).expanduser()
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0
    for path in entries:
        if not path.name.startswith((_STAGING_PREFIX, _BACKUP_PREFIX)):
            continue
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def clean_old_downloads(max_age_hours: int = 48) -> int:
    ensure_dirs()
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for path in DOWNLOAD_DIR.glob("*.zip"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed
