"""HTTP caching for the read endpoints.

The signal changes when the pipeline runs — once a day at most, often less. Yet
every page load used to re-slice the feature matrix, re-serialise four hundred
days of NDVI and hand back a fresh copy of bytes the browser already had. On a
small instance that is the whole latency budget, spent on work whose answer was
known.

Three layers, cheapest first:

1. **ETag / 304.** Every response carries an ETag derived from `data_version()`
   — the token only an ingest moves. A revalidating browser gets 304 and no
   body until the pipeline has actually run.
2. **Cache-Control with stale-while-revalidate.** Inside `max-age` the browser
   or CDN answers from its own copy without asking. After it, the stale copy is
   shown *immediately* and refreshed in the background, so a cold instance never
   shows a spinner to someone who has been here before.
3. **A server-side memo of the encoded bytes**, keyed on (route, params, data
   version). A hit skips the dataframe work and the JSON encoding both. Bounded
   in entries and in bytes, because the instances this runs on have 512 MB.

The site stays live throughout: nothing here pins a value beyond the data
version it was computed from, so the moment an ingest bumps that version every
key misses and the next request rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder

from .config import CACHE_MAX_AGE, CACHE_SWR
from .db import data_version

# Bounded twice over: an entry count so a parameter someone can vary freely
# (/backtest?date=) cannot grow the map without limit, and a byte budget so a
# handful of 400-day series cannot eat the instance.
MAX_ENTRIES = 128
MAX_BYTES = 24 * 1024 * 1024

_lock = threading.Lock()
_store: OrderedDict[str, bytes] = OrderedDict()
_bytes = 0


def stats() -> dict:
    with _lock:
        return {"entries": len(_store), "bytes": _bytes,
                "max_entries": MAX_ENTRIES, "max_bytes": MAX_BYTES}


def clear() -> None:
    global _bytes
    with _lock:
        _store.clear()
        _bytes = 0


def _get(key: str) -> bytes | None:
    with _lock:
        hit = _store.get(key)
        if hit is not None:
            _store.move_to_end(key)
        return hit


def _put(key: str, body: bytes) -> None:
    global _bytes
    if len(body) > MAX_BYTES:
        return  # one response bigger than the whole budget: don't hold it
    with _lock:
        if key in _store:
            _bytes -= len(_store.pop(key))
        _store[key] = body
        _bytes += len(body)
        while _store and (len(_store) > MAX_ENTRIES or _bytes > MAX_BYTES):
            _, evicted = _store.popitem(last=False)
            _bytes -= len(evicted)


def _key(route: str, params: dict[str, Any], version: str) -> str:
    canonical = json.dumps(params, sort_keys=True, default=str)
    return f"{route}|{canonical}|{version}"


def _etag(key: str) -> str:
    # Weak: these are semantically-equivalent representations, and nothing here
    # is byte-range fetched.
    return 'W/"' + hashlib.sha256(key.encode()).hexdigest()[:24] + '"'


def headers_for(etag: str, version: str, max_age: int | None = None) -> dict:
    age = CACHE_MAX_AGE if max_age is None else max_age
    if age <= 0:
        control = "no-cache"
    else:
        control = f"public, max-age={age}, stale-while-revalidate={CACHE_SWR}"
    return {
        "ETag": etag,
        "Cache-Control": control,
        "X-Bhav-Data-Version": version,
        # The API is called from a browser on another origin, so the caching
        # headers have to be readable there for a client to act on them.
        "Access-Control-Expose-Headers": "ETag, X-Bhav-Data-Version, X-Bhav-Cache",
    }


def serve(
    request: Request,
    route: str,
    build: Callable[[], Any],
    params: dict[str, Any] | None = None,
    max_age: int | None = None,
    bucket_s: int = 0,
) -> Response:
    """Answer a GET from the cheapest layer that can, and record which one.

    `build` is only called on a genuine miss, so it can be as expensive as the
    honest answer requires.

    `bucket_s` is for answers the data version does not describe — whether the
    WhatsApp session is linked, say. Those are keyed on a coarse clock instead,
    so the entry ages out by itself; without it a value that has nothing to do
    with the pipeline would be pinned until the next ingest.
    """
    version = data_version()
    if bucket_s > 0:
        version = f"{version}@{int(time.time() // bucket_s)}"
    key = _key(route, params or {}, version)
    etag = _etag(key)
    head = headers_for(etag, version, max_age)

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={**head, "X-Bhav-Cache": "revalidated"})

    body = _get(key)
    if body is None:
        body = json.dumps(jsonable_encoder(build()), separators=(",", ":")).encode()
        _put(key, body)
        source = "miss"
    else:
        source = "hit"

    return Response(
        content=body,
        media_type="application/json",
        headers={**head, "X-Bhav-Cache": source},
    )
