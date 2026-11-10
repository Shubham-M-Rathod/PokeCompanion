"""Shared Asynchronous Sprite & Badge Asset Loader for PokeCompanion UI."""

import threading
import urllib.request
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

KANTO_BADGE_URLS = [
    "https://archives.bulbagarden.net/media/upload/d/dd/Boulder_Badge.png",
    "https://archives.bulbagarden.net/media/upload/9/9c/Cascade_Badge.png",
    "https://archives.bulbagarden.net/media/upload/a/a6/Thunder_Badge.png",
    "https://archives.bulbagarden.net/media/upload/b/b5/Rainbow_Badge.png",
    "https://archives.bulbagarden.net/media/upload/7/7d/Soul_Badge.png",
    "https://archives.bulbagarden.net/media/upload/6/62/Marsh_Badge.png",
    "https://archives.bulbagarden.net/media/upload/c/cc/Volcano_Badge.png",
    "https://archives.bulbagarden.net/media/upload/7/78/Earth_Badge.png",
]


def pokemon_front_urls(species_id: int) -> List[str]:
    """Returns FRLG front sprite URL with standard PokeAPI fallback."""
    return [
        f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/firered-leafgreen/{species_id}.png",
        f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{species_id}.png",
    ]


def pokemon_back_urls(species_id: int) -> List[str]:
    """Returns FRLG back sprite URL with standard PokeAPI fallback."""
    return [
        f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-iii/firered-leafgreen/back/{species_id}.png",
        f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/back/{species_id}.png",
        f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{species_id}.png",
    ]


class AsyncImageLoader(QObject):
    """Fetches remote sprites/icons on daemon threads with in-memory caching and fallback URLs."""

    image_loaded = Signal(str, QPixmap)
    _cache: Dict[str, QPixmap] = {}
    _pending: set = set()

    def fetch(self, url: str, fallback_urls: Optional[Sequence[str]] = None) -> None:
        if not url:
            return
        if url in self._cache:
            self.image_loaded.emit(url, self._cache[url])
            return
        if url in self._pending:
            return

        self._pending.add(url)
        candidates = [url] + list(fallback_urls or [])

        def _worker():
            try:
                for candidate in candidates:
                    if candidate in self._cache:
                        self._cache[url] = self._cache[candidate]
                        self.image_loaded.emit(url, self._cache[url])
                        return
                    try:
                        req = urllib.request.Request(
                            candidate,
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PokeCompanion/1.0"},
                        )
                        with urllib.request.urlopen(req, timeout=4.0) as resp:
                            raw_data = resp.read()
                            img = QImage.fromData(raw_data)
                            if not img.isNull():
                                pix = QPixmap.fromImage(img)
                                self._cache[url] = pix
                                self._cache[candidate] = pix
                                self.image_loaded.emit(url, pix)
                                return
                    except Exception:
                        continue
            finally:
                self._pending.discard(url)

        threading.Thread(target=_worker, daemon=True).start()

