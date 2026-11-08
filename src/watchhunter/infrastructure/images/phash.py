"""Perceptual hashes of listing photos: spot the same photo in another listing.

The same photo under a different listing means a relist, a cross-post
(eBay + Kleinanzeigen) or a scam reusing someone else's pictures. pHash is
robust to resizing and recompression; distance <= MAX_DISTANCE bits = same photo.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import imagehash
from PIL import Image
from sqlalchemy import select

from watchhunter.config.logging import get_logger
from watchhunter.infrastructure.http.client import HttpClient
from watchhunter.infrastructure.persistence.database import Database
from watchhunter.infrastructure.persistence.models import ImageHashRow

log = get_logger(__name__)

MAX_DISTANCE = 6  # of 64 bits


@dataclass(frozen=True)
class PhotoMatch:
    external_id: str
    listing_url: str
    distance: int


class PhotoIndex:
    def __init__(self, *, database: Database, http: HttpClient) -> None:
        self._db = database
        self._http = http
        self._cache: list[tuple[str, str, imagehash.ImageHash]] | None = None
        self._lock = asyncio.Lock()

    async def _load(self) -> list[tuple[str, str, imagehash.ImageHash]]:
        if self._cache is None:
            async with self._db.session() as s:
                rows = list(await s.scalars(select(ImageHashRow)))
            self._cache = [
                (r.external_id, r.listing_url, imagehash.hex_to_hash(r.phash)) for r in rows
            ]
        return self._cache

    async def _hash(self, url: str) -> imagehash.ImageHash | None:
        try:
            async with self._http.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        except Exception:
            return None
        return await asyncio.to_thread(lambda: imagehash.phash(Image.open(io.BytesIO(data))))

    async def check_and_add(
        self, *, external_id: str, image_url: str, listing_url: str
    ) -> PhotoMatch | None:
        """Hash the photo, return the closest earlier listing with the same photo."""
        h = await self._hash(image_url)
        if h is None:
            return None
        async with self._lock:
            known = await self._load()
            best: PhotoMatch | None = None
            for other_id, other_url, other in known:
                if other_id == external_id:
                    continue
                d = h - other
                if d <= MAX_DISTANCE and (best is None or d < best.distance):
                    best = PhotoMatch(other_id, other_url, d)
            if all(k[0] != external_id for k in known):
                known.append((external_id, listing_url, h))
                async with self._db.session() as s:
                    s.add(
                        ImageHashRow(
                            external_id=external_id,
                            url=image_url,
                            listing_url=listing_url,
                            phash=str(h),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
        if best:
            log.info("photo.duplicate", external_id=external_id, other=best.external_id, distance=best.distance)
        return best
