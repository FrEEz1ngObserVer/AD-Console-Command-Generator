from __future__ import annotations

"""Offline icon loading and normalization helpers.

The updater downloads hero icons into cache/icons/.
This module does not fetch from the network. It only:
- resolves alias keys to canonical icon files;
- loads images from disk;
- normalizes them to a fixed display size;
- caches PhotoImage objects in memory for reuse.
"""

import json
import tkinter as tk
from pathlib import Path
from typing import Dict, Iterable

from PIL import Image, ImageOps, ImageTk


class IconManager:
    """Read hero icons from the local cache and return Tk-compatible images."""

    def __init__(self, cache_dir: Path, size: tuple[int, int] = (96, 54)):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.size = size

        # Tk PhotoImage objects must be kept referenced in Python, otherwise they
        # can disappear from buttons after garbage collection.
        self._images: Dict[str, tk.PhotoImage] = {}

        # Aliases map alternate keys such as legacy hero names onto one canonical
        # icon filename, avoiding duplicate icon files on disk.
        self.alias_map = self._load_alias_map()

    def _load_alias_map(self) -> Dict[str, str]:
        """Load cache/icons/aliases.json if present."""
        alias_path = self.cache_dir / 'aliases.json'
        if not alias_path.exists():
            return {}
        try:
            data = json.loads(alias_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}

        result: Dict[str, str] = {}
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                result[key.strip().lower()] = value.strip().lower()
        return result

    def path_for(self, icon_key: str) -> Path:
        """Return the on-disk PNG path for one icon key."""
        return self.cache_dir / f"{icon_key}.png"

    def _resolve_key(self, key: str) -> str:
        """Follow alias chains until a canonical icon key is reached."""
        candidate = key.strip().lower()
        seen: set[str] = set()
        while candidate and candidate not in seen:
            seen.add(candidate)
            target = self.alias_map.get(candidate)
            if not target or target == candidate:
                return candidate
            candidate = target
        return candidate

    def _find_existing_path(self, candidate_keys: Iterable[str]) -> Path | None:
        """Try all candidate keys and return the first icon file that exists."""
        for key in candidate_keys:
            resolved = self._resolve_key(key)
            for probe in dict.fromkeys([resolved, key.strip().lower()]):
                if not probe:
                    continue
                path = self.path_for(probe)
                if path.exists():
                    return path
        return None

    def _load_and_normalize(self, path: Path) -> tk.PhotoImage | None:
        """Load one image file and fit it into a fixed transparent canvas."""
        try:
            with Image.open(path) as raw:
                image = raw.convert('RGBA')
                normalized = ImageOps.contain(image, self.size, Image.Resampling.LANCZOS)
                canvas = Image.new('RGBA', self.size, (0, 0, 0, 0))
                offset = (
                    (self.size[0] - normalized.width) // 2,
                    (self.size[1] - normalized.height) // 2,
                )
                canvas.paste(normalized, offset, normalized)
        except OSError:
            return None

        return ImageTk.PhotoImage(canvas)

    def get(self, candidate_keys: Iterable[str]) -> tk.PhotoImage | None:
        """Return a normalized PhotoImage for any of the given candidate keys.

        This is the main UI entry point. The caller can pass multiple possible keys
        (for example, site slug and internal hero name), and the icon manager will
        use whichever local file exists.
        """
        normalized_input = [k.strip().lower() for k in candidate_keys if k and k.strip()]
        keys = tuple(dict.fromkeys(self._resolve_key(k) for k in normalized_input))
        if not keys:
            return None

        cache_key = '|'.join(keys)
        if cache_key in self._images:
            return self._images[cache_key]

        path = self._find_existing_path(normalized_input)
        if path is None:
            return None

        image = self._load_and_normalize(path)
        if image is None:
            return None

        self._images[cache_key] = image
        return image
