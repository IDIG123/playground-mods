from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import CatalogueResult, Mod, SiteMeta
from .paths import DATA_DIR, ensure_dirs

log = logging.getLogger(__name__)


class Store:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        ensure_dirs()
        self.data_dir = data_dir
        self.catalogue_path = data_dir / "catalogue.json"
        self.installed_path = data_dir / "installed.json"
        self.library_path = data_dir / "library.json"
        self.meta_path = data_dir / "site-meta.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("Could not read %s: %s", path, exc)
            return None

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def load_catalogue(self) -> CatalogueResult | None:
        data = self._read_json(self.catalogue_path)
        if not data:
            return None
        try:
            switch_items = data.get("switch")
            return CatalogueResult(
                switch_mods=[
                    Mod.from_dict(item)
                    for item in (switch_items if isinstance(switch_items, list) else [])
                    if isinstance(item, dict)
                ],
            )
        except (TypeError, ValueError) as exc:
            log.warning("Ignoring invalid catalogue cache: %s", exc)
            return None

    def save_catalogue(self, result: CatalogueResult) -> None:
        self._write_json(
            self.catalogue_path,
            {
                "version": 1,
                "switch": [mod.to_dict() for mod in result.switch_mods],
            },
        )

    def load_installed(self) -> dict[str, dict[str, Any]]:
        data = self._read_json(self.installed_path) or {}
        records = data.get("mods")
        if not isinstance(records, dict):
            return {}
        return {
            str(uid): record
            for uid, record in records.items()
            if isinstance(record, dict)
        }

    def save_installed(self, records: dict[str, dict[str, Any]]) -> None:
        self._write_json(self.installed_path, {"version": 1, "mods": records})

    # ------------------------------------------------------------------
    # Local library (likes, follows, seen versions, onboarding)
    # ------------------------------------------------------------------
    def load_library(self) -> dict[str, Any]:
        data = self._read_json(self.library_path) or {}
        likes = data.get("likes") if isinstance(data.get("likes"), list) else []
        follows = data.get("follows") if isinstance(data.get("follows"), dict) else {}
        seen = data.get("seen") if isinstance(data.get("seen"), dict) else {}
        return {
            "version": 1,
            "likes": [str(uid) for uid in likes if uid],
            "follows": {
                str(uid): record
                for uid, record in follows.items()
                if uid and isinstance(record, dict)
            },
            "seen": {
                str(uid): int(version)
                for uid, version in seen.items()
                if uid and isinstance(version, (int, float, str))
                and str(version).isdigit()
            },
            "dismissed_notice": str(data.get("dismissed_notice") or ""),
            "onboarding_seen": bool(data.get("onboarding_seen")),
            "game_path": str(data.get("game_path") or ""),
        }

    def save_library(self, library: dict[str, Any]) -> None:
        self._write_json(
            self.library_path,
            {
                "version": 1,
                "likes": sorted(set(library.get("likes") or [])),
                "follows": library.get("follows") or {},
                "seen": library.get("seen") or {},
                "dismissed_notice": str(library.get("dismissed_notice") or ""),
                "onboarding_seen": bool(library.get("onboarding_seen")),
                "game_path": str(library.get("game_path") or ""),
            },
        )

    # ------------------------------------------------------------------
    # Site metadata cache
    # ------------------------------------------------------------------
    def load_site_meta(self) -> SiteMeta:
        return SiteMeta.from_dict(self._read_json(self.meta_path))

    def save_site_meta(self, meta: SiteMeta) -> None:
        self._write_json(self.meta_path, meta.to_dict())
