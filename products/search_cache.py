"""Short-lived cache for the product search endpoints, invalidated on every stock or price change.

The cache lives in the ``search`` cache alias (a file-based cache in production), not the default
in-memory one: gunicorn runs several workers, and a per-process cache would let a sale handled by
one worker leave the other workers serving the old stock.

Every cached entry is keyed by a per-retailer version. Anything that changes what a search shows
(stock, price, name, active flag) calls ``bump_search_cache``; the next search then misses and
rebuilds. ``SEARCH_CACHE_TTL`` is only a backstop for edits that do not bump (category or brand
renames, offers).
"""
import hashlib
import logging
import time

from django.core.cache import caches
from django.db import transaction

logger = logging.getLogger(__name__)

SEARCH_CACHE_TTL = 30


def _store():
    return caches['search']


def _version_key(retailer_id):
    return f'search_ver_{retailer_id}'


def _version(retailer_id):
    store = _store()
    key = _version_key(retailer_id)
    version = store.get(key)
    if version is None:
        version = time.time_ns()
        store.add(key, version, None)
        version = store.get(key, version)
    return version


def search_cache_key(scope, retailer_id, search, **parts):
    """``scope`` separates the retailer and public endpoints; ``parts`` is every input that changes the payload."""
    query_hash = hashlib.sha1(' '.join(search.lower().split()).encode('utf-8')).hexdigest()[:16]
    tail = '_'.join(f'{name}={parts[name]}' for name in sorted(parts))
    return f'{scope}_{retailer_id}_{_version(retailer_id)}_{query_hash}_{tail}'


def get_cached_search(key):
    try:
        return _store().get(key)
    except Exception:
        logger.warning('Search cache read failed', exc_info=True)
        return None


def set_cached_search(key, value):
    try:
        _store().set(key, value, SEARCH_CACHE_TTL)
    except Exception:
        logger.warning('Search cache write failed', exc_info=True)


def bump_search_cache(retailer_id):
    """Drop every cached search for this retailer, once the surrounding transaction commits.

    Bumping before the commit would let a concurrent search cache the old rows under the new version.
    """
    if not retailer_id:
        return

    def _bump():
        try:
            _store().set(_version_key(retailer_id), time.time_ns(), None)
        except Exception:
            logger.warning('Search cache bump failed', exc_info=True)

    transaction.on_commit(_bump)
