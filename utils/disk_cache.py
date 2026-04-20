"""
utils/disk_cache.py — Picklable disk-backed cache for expensive computations.

Purpose
-------
Streamlit's @st.cache_data is per-session and in-memory. When Streamlit Cloud
evicts an idle session (~10 min of inactivity), every cached value is lost and
the next interaction pays the full rebuild cost. This module provides a second
tier: a persistent disk cache that survives session eviction, process restart,
and most redeploys.

Architecture
------------
    Memory cache  (@st.cache_data)     — fastest, per-session
         ↓ miss
    Disk cache    (this module)        — fast, survives session eviction
         ↓ miss
    Rebuild from source                — slow, network + computation

Usage
-----
As a decorator — works nicely on top of @st.cache_data:

    import streamlit as st
    from utils.disk_cache import disk_cached

    @st.cache_data(ttl=1800)
    @disk_cached(namespace="perf", ttl=3600, version=1)
    def expensive_compute(strategy, as_of):
        ...

On a cache miss the disk cache runs the underlying function, pickles the
result to `data/cache/disk/<namespace>/<key>.pkl`, and returns it. Subsequent
calls read from disk and deserialize (~1-10ms for typical DataFrames).

Keys
----
Cache keys are derived from the function's positional and keyword arguments
via repr() + hashlib.blake2b. Only arguments that are picklable / stable
across processes should be used as cache keys — DataFrames, dicts, custom
classes with non-deterministic repr() won't work. Stick to str, int, float,
tuple, and datetime-ish values.

Failure modes
-------------
- Corrupted pickle files are silently deleted and treated as cache misses
- Write failures (disk full, permission errors) log once and fall through to
  computing the value (so the app never breaks because of disk issues)
- The cache directory is created on first use if it doesn't exist
"""

from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

# ── Configuration ──────────────────────────────────────────────────────────

# Resolve to <repo>/data/cache/disk  regardless of where this module is imported
# from. utils/ and data/ are siblings, so go up one level from utils/.
_UTILS_DIR = Path(__file__).resolve().parent
_REPO_DIR = _UTILS_DIR.parent
_CACHE_ROOT = _REPO_DIR / "data" / "cache" / "disk"

# Hard cap on total cache size. On Streamlit Cloud the ephemeral disk is
# limited but generous — 100 MB is plenty for our scale and leaves headroom.
_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


def _key_to_path(namespace: str, key: str) -> Path:
    """Build the filesystem path for a cache entry."""
    ns_dir = _CACHE_ROOT / namespace
    return ns_dir / f"{key}.pkl"


def _hash_args(args: tuple, kwargs: dict, version: int) -> str:
    """Stable hash of function arguments. Used as the cache filename."""
    # repr() is stable for str, int, float, tuple, frozenset, None, bool,
    # datetime — which covers everything we use as a cache key.
    # We include the version number so bumping it invalidates the cache.
    raw = repr((version, args, sorted(kwargs.items())))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()


def _ensure_dir(path: Path) -> bool:
    """Create the parent directory if it doesn't exist. Returns False on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _is_fresh(path: Path, ttl: Optional[float]) -> bool:
    """True if the file exists and is within TTL (or TTL is None = no expiry)."""
    if not path.exists():
        return False
    if ttl is None:
        return True
    try:
        age = time.time() - path.stat().st_mtime
        return age < ttl
    except OSError:
        return False


def _read(path: Path) -> Optional[Any]:
    """Read a cache entry. Returns None on any error (treated as a miss)."""
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except (pickle.PickleError, EOFError, OSError, AttributeError, ImportError):
        # Corrupted or incompatible pickle — delete and treat as miss
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _write(path: Path, value: Any) -> bool:
    """Write a cache entry atomically. Returns True on success."""
    if not _ensure_dir(path):
        return False
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("wb") as f:
            pickle.dump(value, f, protocol=pickle.HIGHEST_PROTOCOL)
        # Atomic rename — prevents half-written files from being read as valid
        os.replace(tmp, path)
        return True
    except (pickle.PickleError, OSError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _enforce_size_cap() -> None:
    """If the cache exceeds _MAX_BYTES, delete oldest files until under cap.
    Called opportunistically; not every write (too expensive)."""
    if not _CACHE_ROOT.exists():
        return
    try:
        files = []
        total = 0
        for p in _CACHE_ROOT.rglob("*.pkl"):
            try:
                stat = p.stat()
                files.append((stat.st_mtime, stat.st_size, p))
                total += stat.st_size
            except OSError:
                continue
        if total <= _MAX_BYTES:
            return
        # Delete oldest-first until we're under the cap
        files.sort(key=lambda t: t[0])
        for _, size, p in files:
            if total <= _MAX_BYTES:
                break
            try:
                p.unlink()
                total -= size
            except OSError:
                continue
    except OSError:
        pass


# Opportunistic size-cap enforcement: once per process, on first import.
# Running on every write would add disk I/O to the fast path.
_enforce_size_cap()


# ── Public API ─────────────────────────────────────────────────────────────

def disk_cached(
    namespace: str,
    ttl: Optional[float] = 3600,
    version: int = 1,
) -> Callable:
    """
    Decorator: persist function results to disk keyed on arguments.

    Parameters
    ----------
    namespace : str
        Directory name under data/cache/disk/ — groups related cache entries
        so clearing one feature doesn't blow away others.
    ttl : float | None
        Seconds before a cached entry is considered stale. None = no expiry
        (useful for data that only invalidates via version bumps).
    version : int
        Bump to invalidate all entries in this namespace — useful after
        changing the function's return shape or computation logic.

    The decorated function's arguments must be stable, hashable-via-repr
    values (str, int, float, tuple, bool, None, datetime). Pass large
    unhashable objects (DataFrames, dicts-of-DataFrames) via underscore-
    prefixed kwargs — they'll be available to the function but won't
    participate in the cache key.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build the cache key from non-underscore kwargs only, mirroring
            # Streamlit's own cache-key convention.
            hashable_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
            hashable_args = args  # positional args are always hashed
            try:
                key = _hash_args(hashable_args, hashable_kwargs, version)
            except Exception:
                # If argument repr fails, skip disk cache and just compute
                return func(*args, **kwargs)

            path = _key_to_path(namespace, key)

            # Try disk cache first
            if _is_fresh(path, ttl):
                cached = _read(path)
                if cached is not None:
                    return cached

            # Miss: compute and persist
            result = func(*args, **kwargs)
            if result is not None:
                _write(path, result)
            return result

        # Expose a way to clear a specific namespace — useful for admin /
        # cache-bust operations from the Streamlit UI.
        wrapper.clear_namespace = lambda: clear_namespace(namespace)  # type: ignore[attr-defined]
        return wrapper

    return decorator


def clear_namespace(namespace: str) -> int:
    """Delete all cache entries in a namespace. Returns count of files removed."""
    ns_dir = _CACHE_ROOT / namespace
    if not ns_dir.exists():
        return 0
    count = 0
    try:
        for p in ns_dir.glob("*.pkl"):
            try:
                p.unlink()
                count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count


def clear_all() -> int:
    """Delete every disk-cached entry across all namespaces."""
    if not _CACHE_ROOT.exists():
        return 0
    try:
        count = sum(1 for _ in _CACHE_ROOT.rglob("*.pkl"))
        shutil.rmtree(_CACHE_ROOT, ignore_errors=True)
        return count
    except OSError:
        return 0


def stats() -> dict:
    """Return a dict with cache size / entry counts — useful for diagnostics."""
    if not _CACHE_ROOT.exists():
        return {"entries": 0, "bytes": 0, "namespaces": []}
    try:
        entries = 0
        total = 0
        namespaces: dict[str, int] = {}
        for p in _CACHE_ROOT.rglob("*.pkl"):
            try:
                size = p.stat().st_size
                entries += 1
                total += size
                ns = p.parent.name
                namespaces[ns] = namespaces.get(ns, 0) + 1
            except OSError:
                continue
        return {
            "entries": entries,
            "bytes": total,
            "mb": round(total / (1024 * 1024), 2),
            "namespaces": sorted(namespaces.items()),
        }
    except OSError:
        return {"entries": 0, "bytes": 0, "namespaces": []}
