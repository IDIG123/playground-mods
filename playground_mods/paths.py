from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

APP_NAME = "Playground Mods"
APP_SLUG = "playground-mods"

# Derive the Steam library from the current user instead of hard-coding a
# username, so the app keeps working when the home directory differs.
_STEAM_COMMON = Path.home() / ".local/share/Steam/steamapps/common"
DEFAULT_GAME_PATH = _STEAM_COMMON / "People Playground"
DEFAULT_MODS_PATH = DEFAULT_GAME_PATH / "Mods"
DEFAULT_CONTRAPTIONS_PATH = DEFAULT_GAME_PATH / "Contraptions"


def _data_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def _cache_home() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library/Caches"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


DATA_DIR = _data_home() / APP_SLUG
CACHE_DIR = _cache_home() / APP_SLUG
IMAGE_DIR = CACHE_DIR / "images"
DOWNLOAD_DIR = CACHE_DIR / "downloads"
LOG_FILE = DATA_DIR / "app.log"


def ensure_dirs() -> None:
    for path in (DATA_DIR, CACHE_DIR, IMAGE_DIR, DOWNLOAD_DIR):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    ensure_dirs()
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    # Third-party request logs are noisy at INFO level.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def mods_directory() -> Path:
    override = os.environ.get("PLAYGROUND_MODS_DIR")
    path = Path(override).expanduser() if override else DEFAULT_MODS_PATH
    return path


def contraptions_directory(mods_root: Path | None = None) -> Path:
    """The Contraptions folder that sits next to the Mods folder.

    ``Contraptions`` is a sibling of ``Mods`` inside the game install. When a
    custom ``mods_root`` is supplied (for example during tests) the sibling of
    that folder is used so the two always stay together.
    """
    override = os.environ.get("PLAYGROUND_CONTRAPTIONS_DIR")
    if override:
        return Path(override).expanduser()
    if mods_root is not None:
        return Path(mods_root).expanduser().parent / "Contraptions"
    return DEFAULT_CONTRAPTIONS_PATH


# ------------------------------------------------------------------
# Auto-detection of the People Playground install folder
# ------------------------------------------------------------------
def _steam_root_candidates() -> list[Path]:
    """Likely Steam installation roots on the current platform."""
    roots: list[Path] = []
    if sys.platform == "win32":
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(var)
            if base:
                roots.append(Path(base) / "Steam")
        # Common SteamCMD / custom installs.
        roots.append(Path("C:/Steam"))
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library/Application Support/Steam")
    else:
        roots.extend(
            [
                Path.home() / ".local/share/Steam",
                Path.home() / ".steam/steam",
                Path.home() / ".steam/root",
                Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
                Path("/usr/share/steam"),
            ]
        )
    env = os.environ.get("STEAM_ROOT")
    if env:
        roots.insert(0, Path(env).expanduser())
    return [root for root in roots if root.exists()]


def _parse_library_folders(vdf_path: Path) -> list[Path]:
    """Read the 'path' entries from a Steam libraryfolders.vdf file."""
    libraries: list[Path] = []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s*"([^"]+)"', text):
        raw = match.group(1).replace("\\\\", "\\")
        path = Path(raw).expanduser()
        if path.exists():
            libraries.append(path)
    return libraries


def detect_steam_libraries() -> list[Path]:
    """Return every Steam ``steamapps/common`` folder that exists on disk."""
    common_dirs: set[Path] = set()
    for root in _steam_root_candidates():
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for library in _parse_library_folders(vdf):
                common = library / "steamapps" / "common"
                if common.exists():
                    common_dirs.add(common)
        common = root / "steamapps" / "common"
        if common.exists():
            common_dirs.add(common)
    return sorted(common_dirs)


def detect_game_path() -> Path | None:
    """Find the People Playground install folder automatically.

    Checks, in order: an explicit environment override, every Steam library
    detected on disk, and finally the platform default location.
    """
    env = os.environ.get("PLAYGROUND_GAME_DIR")
    if env:
        path = Path(env).expanduser()
        if path.name.lower() == "people playground" and path.exists():
            return path
        if (path / "People Playground").exists():
            return path / "People Playground"
        if path.exists():
            return path

    for common in detect_steam_libraries():
        candidate = common / "People Playground"
        if candidate.exists():
            return candidate

    if DEFAULT_GAME_PATH.exists():
        return DEFAULT_GAME_PATH
    return None


def game_directory() -> Path | None:
    """Convenience wrapper used by the UI at startup."""
    return detect_game_path()
