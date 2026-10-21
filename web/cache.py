"""Directory listing cache manager for high-performance multi-cloud browsing with disk persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import DEFAULT_CONFIG_DIR
from domain.models import FileItem

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    remote: str
    path: str
    items: list[FileItem]
    timestamp: float
    ttl: float

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl


class DirectoryCacheManager:
    """Multi-level directory listing cache with in-memory L1 and persistent SQLite L2."""

    def __init__(
        self,
        default_ttl: int = 300,
        max_entries: int = 1000,
        persist_to_disk: bool = False,
        db_path: Path | str | None = None,
    ) -> None:
        self.enabled: bool = True
        self.default_ttl: int = default_ttl
        self.max_entries: int = max_entries
        self.persist_to_disk: bool = persist_to_disk
        self.db_path: Path | str | None = Path(db_path) if (db_path and db_path != ":memory:") else db_path

        self._cache: dict[tuple[str, str], CacheEntry] = {}
        self._thumb_cache: dict[tuple[str, str], tuple[str, float, float]] = {}  # url, timestamp, ttl
        self._hits: int = 0
        self._misses: int = 0
        self._lock = threading.Lock()
        self._db_conn: sqlite3.Connection | None = None

        if self.persist_to_disk and self.db_path is not None:
            with self._lock:
                self._init_db_locked()
                self._warmup_cache_locked()

    @staticmethod
    def _norm(path: str) -> str:
        p = path.strip()
        if not p or p == ".":
            return "/"
        norm = "/" + p.strip("/")
        return norm if norm != "" else "/"

    def set_db_path(self, db_path: Path | str | None, persist_to_disk: bool | None = None) -> None:
        """Update SQLite database path and reload/warmup persistent cache."""
        with self._lock:
            if persist_to_disk is not None:
                self.persist_to_disk = persist_to_disk
            if self._db_conn is not None:
                try:
                    self._db_conn.close()
                except Exception:
                    pass
                self._db_conn = None

            self.db_path = Path(db_path) if (db_path and db_path != ":memory:") else db_path
            if self.persist_to_disk and self.db_path is not None:
                self._init_db_locked()
                self._warmup_cache_locked()

    def _init_db_locked(self) -> None:
        """Initialize SQLite database connection, PRAGMAs, and tables."""
        if not self.db_path:
            return
        try:
            if self.db_path != ":memory:" and isinstance(self.db_path, Path):
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10.0)
            self._db_conn.execute("PRAGMA journal_mode = WAL;")
            self._db_conn.execute("PRAGMA synchronous = NORMAL;")
            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS directory_cache (
                    remote TEXT NOT NULL,
                    path TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    ttl REAL NOT NULL,
                    PRIMARY KEY (remote, path)
                );
                """
            )
            self._db_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dir_cache_remote ON directory_cache(remote);"
            )
            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thumbnail_cache (
                    remote TEXT NOT NULL,
                    path TEXT NOT NULL,
                    thumbnail_url TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    ttl REAL NOT NULL,
                    PRIMARY KEY (remote, path)
                );
                """
            )
            self._db_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thumb_cache_remote ON thumbnail_cache(remote);"
            )
            self._db_conn.commit()

            # Clean expired rows on startup
            now = time.time()
            self._db_conn.execute("DELETE FROM directory_cache WHERE (? - timestamp) > ttl;", (now,))
            self._db_conn.execute("DELETE FROM thumbnail_cache WHERE (? - timestamp) > ttl;", (now,))
            self._db_conn.commit()
        except Exception as exc:
            logger.warning("初始化 SQLite 持久化快取資料庫失敗 (%s): %s", self.db_path, exc)
            self._db_conn = None

    def _warmup_cache_locked(self) -> None:
        """Warm up in-memory cache from persistent SQLite database."""
        if not self._db_conn:
            return
        try:
            now = time.time()
            cursor = self._db_conn.cursor()
            cursor.execute(
                "SELECT remote, path, items_json, timestamp, ttl FROM directory_cache ORDER BY timestamp DESC LIMIT ?",
                (self.max_entries,),
            )
            for row in cursor.fetchall():
                remote, path, items_json, ts, ttl = row
                if (now - ts) <= ttl:
                    try:
                        raw = json.loads(items_json)
                        items = [FileItem.model_validate(x) for x in raw]
                        self._cache[(remote, path)] = CacheEntry(
                            remote=remote,
                            path=path,
                            items=items,
                            timestamp=ts,
                            ttl=ttl,
                        )
                    except Exception as err:
                        logger.debug("反序列化快取項目失敗 (%s:%s): %s", remote, path, err)

            # Warmup thumbnail cache (most recent 2000)
            cursor.execute(
                "SELECT remote, path, thumbnail_url, timestamp, ttl FROM thumbnail_cache ORDER BY timestamp DESC LIMIT 2000"
            )
            for row in cursor.fetchall():
                r, p, url, ts, ttl = row
                if (now - ts) <= ttl:
                    self._thumb_cache[(r, p)] = (url, ts, ttl)
        except Exception as exc:
            logger.warning("從磁碟快取預熱資料失敗: %s", exc)

    def get(self, remote: str, path: str) -> list[FileItem] | None:
        """Retrieve cached items for remote and path if not expired."""
        if not self.enabled:
            return None
        norm_p = self._norm(path)
        key = (remote, norm_p)
        with self._lock:
            # Check L1 memory cache
            entry = self._cache.get(key)
            if entry:
                if not entry.is_expired():
                    self._hits += 1
                    return list(entry.items)
                else:
                    del self._cache[key]
                    if self.persist_to_disk and self._db_conn:
                        try:
                            self._db_conn.execute(
                                "DELETE FROM directory_cache WHERE remote = ? AND path = ?",
                                (remote, norm_p),
                            )
                            self._db_conn.commit()
                        except Exception:
                            pass

            # Check L2 persistent store on L1 miss
            if self.persist_to_disk and self._db_conn:
                try:
                    cursor = self._db_conn.cursor()
                    cursor.execute(
                        "SELECT items_json, timestamp, ttl FROM directory_cache WHERE remote = ? AND path = ?",
                        (remote, norm_p),
                    )
                    row = cursor.fetchone()
                    if row:
                        items_json, ts, ttl = row
                        now = time.time()
                        if (now - ts) <= ttl:
                            raw = json.loads(items_json)
                            items = [FileItem.model_validate(x) for x in raw]
                            self._cache[key] = CacheEntry(
                                remote=remote,
                                path=norm_p,
                                items=items,
                                timestamp=ts,
                                ttl=ttl,
                            )
                            self._hits += 1
                            return list(items)
                        else:
                            self._db_conn.execute(
                                "DELETE FROM directory_cache WHERE remote = ? AND path = ?",
                                (remote, norm_p),
                            )
                            self._db_conn.commit()
                except Exception as exc:
                    logger.debug("讀取持久化快取失敗 (%s:%s): %s", remote, norm_p, exc)

            self._misses += 1
        return None

    def put(
        self,
        remote: str,
        path: str,
        items: list[FileItem],
        ttl: int | None = None,
    ) -> None:
        """Store directory items in memory and persistent cache."""
        if not self.enabled:
            return
        norm_p = self._norm(path)
        key = (remote, norm_p)
        entry_ttl = ttl if ttl is not None else self.default_ttl
        now = time.time()

        with self._lock:
            if len(self._cache) >= self.max_entries:
                self._prune_expired_locked()
                if len(self._cache) >= self.max_entries:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
                    del self._cache[oldest_key]

            self._cache[key] = CacheEntry(
                remote=remote,
                path=norm_p,
                items=list(items),
                timestamp=now,
                ttl=float(entry_ttl),
            )

            # Persist to L2 SQLite
            if self.persist_to_disk and self._db_conn:
                try:
                    dumped = [it.model_dump(mode="json") for it in items]
                    items_json = json.dumps(dumped, ensure_ascii=False)
                    self._db_conn.execute(
                        """
                        INSERT OR REPLACE INTO directory_cache (remote, path, items_json, timestamp, ttl)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (remote, norm_p, items_json, now, float(entry_ttl)),
                    )
                    self._db_conn.commit()
                except Exception as exc:
                    logger.warning("寫入持久化目錄快取失敗 (%s:%s): %s", remote, norm_p, exc)

    def _prune_expired_locked(self) -> None:
        """Prune expired entries from memory and SQLite."""
        now = time.time()
        expired = [k for k, v in self._cache.items() if (now - v.timestamp) > v.ttl]
        for k in expired:
            del self._cache[k]

        expired_thumbs = [k for k, v in self._thumb_cache.items() if (now - v[1]) > v[2]]
        for k in expired_thumbs:
            del self._thumb_cache[k]

        if self.persist_to_disk and self._db_conn:
            try:
                self._db_conn.execute("DELETE FROM directory_cache WHERE (? - timestamp) > ttl;", (now,))
                self._db_conn.execute("DELETE FROM thumbnail_cache WHERE (? - timestamp) > ttl;", (now,))
                self._db_conn.commit()
            except Exception:
                pass

    def invalidate(self, remote: str, path: str | None = None) -> int:
        """Invalidate cache for a remote or specific directory subtree."""
        count = 0
        norm_p = self._norm(path) if path else "/"

        with self._lock:
            if path is None or norm_p == "/":
                keys_to_del = [k for k in self._cache if k[0] == remote]
                thumb_keys = [k for k in self._thumb_cache if k[0] == remote]
            else:
                prefix = norm_p.rstrip("/") + "/"
                parent = norm_p.rsplit("/", 1)[0] or "/"
                keys_to_del = [
                    k for k in self._cache
                    if k[0] == remote and (k[1] == norm_p or k[1].startswith(prefix) or k[1] == parent)
                ]
                thumb_keys = [
                    k for k in self._thumb_cache
                    if k[0] == remote and (k[1] == norm_p or k[1].startswith(prefix))
                ]

            for k in keys_to_del:
                del self._cache[k]
                count += 1
            for k in thumb_keys:
                del self._thumb_cache[k]

            if self.persist_to_disk and self._db_conn:
                try:
                    if path is None or norm_p == "/":
                        self._db_conn.execute("DELETE FROM directory_cache WHERE remote = ?", (remote,))
                        self._db_conn.execute("DELETE FROM thumbnail_cache WHERE remote = ?", (remote,))
                    else:
                        prefix_like = norm_p.rstrip("/") + "/%"
                        parent = norm_p.rsplit("/", 1)[0] or "/"
                        self._db_conn.execute(
                            "DELETE FROM directory_cache WHERE remote = ? AND (path = ? OR path LIKE ? OR path = ?)",
                            (remote, norm_p, prefix_like, parent),
                        )
                        self._db_conn.execute(
                            "DELETE FROM thumbnail_cache WHERE remote = ? AND (path = ? OR path LIKE ?)",
                            (remote, norm_p, prefix_like),
                        )
                    self._db_conn.commit()
                except Exception as exc:
                    logger.warning("清除持久化快取失敗 (%s): %s", remote, exc)

        return count

    def clear(self) -> int:
        """Flush the entire directory and thumbnail cache (memory and disk)."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._thumb_cache.clear()

            if self.persist_to_disk and self._db_conn:
                try:
                    self._db_conn.execute("DELETE FROM directory_cache;")
                    self._db_conn.execute("DELETE FROM thumbnail_cache;")
                    self._db_conn.commit()
                except Exception as exc:
                    logger.warning("清空持久化快取失敗: %s", exc)

            return count

    def reset_stats(self) -> None:
        """Reset hit and miss counters."""
        with self._lock:
            self._hits = 0
            self._misses = 0

    def get_thumbnail(self, remote: str, path: str) -> str | None:
        """Retrieve cached thumbnail URL for remote and path if not expired."""
        if not self.enabled:
            return None
        norm_p = self._norm(path)
        key = (remote, norm_p)
        now = time.time()

        with self._lock:
            thumb_val = self._thumb_cache.get(key)
            if thumb_val:
                url, ts, ttl = thumb_val
                if (now - ts) <= ttl:
                    return url
                else:
                    del self._thumb_cache[key]

            if self.persist_to_disk and self._db_conn:
                try:
                    cursor = self._db_conn.cursor()
                    cursor.execute(
                        "SELECT thumbnail_url, timestamp, ttl FROM thumbnail_cache WHERE remote = ? AND path = ?",
                        (remote, norm_p),
                    )
                    row = cursor.fetchone()
                    if row:
                        url, ts, ttl = row
                        if (now - ts) <= ttl:
                            self._thumb_cache[key] = (str(url), float(ts), float(ttl))
                            return str(url)
                        else:
                            self._db_conn.execute(
                                "DELETE FROM thumbnail_cache WHERE remote = ? AND path = ?",
                                (remote, norm_p),
                            )
                            self._db_conn.commit()
                except Exception:
                    pass

        return None

    def put_thumbnail(self, remote: str, path: str, url: str, ttl: float | None = None) -> None:
        """Store thumbnail URL in memory and persistent cache."""
        if not self.enabled or not url:
            return
        norm_p = self._norm(path)
        key = (remote, norm_p)
        entry_ttl = ttl if ttl is not None else max(1800.0, float(self.default_ttl * 6))
        now = time.time()

        with self._lock:
            self._thumb_cache[key] = (url, now, float(entry_ttl))
            if self.persist_to_disk and self._db_conn:
                try:
                    self._db_conn.execute(
                        """
                        INSERT OR REPLACE INTO thumbnail_cache (remote, path, thumbnail_url, timestamp, ttl)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (remote, norm_p, url, now, float(entry_ttl)),
                    )
                    self._db_conn.commit()
                except Exception as exc:
                    logger.debug("儲存縮圖快取失敗: %s", exc)

    def get_stats(self) -> dict[str, Any]:
        """Return cache health metrics, active entries, and persistence indicators."""
        with self._lock:
            self._prune_expired_locked()
            total_req = self._hits + self._misses
            ratio = round((self._hits / total_req) * 100, 1) if total_req > 0 else 0.0
            remotes_cached = sorted({k[0] for k in self._cache})

            persisted_dirs = 0
            persisted_thumbs = 0
            if self.persist_to_disk and self._db_conn:
                try:
                    cur = self._db_conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM directory_cache;")
                    persisted_dirs = cur.fetchone()[0]
                    cur.execute("SELECT COUNT(*) FROM thumbnail_cache;")
                    persisted_thumbs = cur.fetchone()[0]
                except Exception:
                    pass

            return {
                "enabled": self.enabled,
                "ttl_seconds": self.default_ttl,
                "max_entries": self.max_entries,
                "current_entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": ratio,
                "cached_remotes": remotes_cached,
                "persist_to_disk": self.persist_to_disk,
                "persisted_dirs": persisted_dirs,
                "persisted_thumbs": persisted_thumbs,
                "db_path": str(self.db_path) if self.db_path else None,
            }

    def close(self) -> None:
        """Close SQLite connection cleanly."""
        with self._lock:
            if self._db_conn:
                try:
                    self._db_conn.close()
                except Exception:
                    pass
                self._db_conn = None


# Singleton directory cache instance
directory_cache = DirectoryCacheManager(
    persist_to_disk=True,
    db_path=DEFAULT_CONFIG_DIR / "cache.db",
)
