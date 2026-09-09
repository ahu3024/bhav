/**
 * Stale-while-revalidate over localStorage.
 *
 * The signal changes when the pipeline runs — daily at most. The site was
 * refetching it on every mount: opening the landing page, clicking through to
 * today's call and coming back cost six requests for three answers that had not
 * moved, and on a cold free instance the first of those is a spin-up the reader
 * watches as a spinner.
 *
 * So: render from the last known answer immediately, then revalidate behind it.
 *
 *   1. `read` pulls the previous body out of localStorage synchronously, so
 *      first paint has real content instead of a loading state.
 *   2. Inside `ttl` nothing is requested at all.
 *   3. Past it, one background request goes out; the page only changes if the
 *      answer did. The backend's ETag makes that a 304 with no body unless the
 *      pipeline has actually run since (see backend/bhav/cache.py).
 *   4. A failed revalidation is not an error — the cached answer stays on
 *      screen. Losing the network should not blank a page that already loaded.
 *
 * Every component asking for the same path shares one request and one entry, so
 * the three panels on the landing page cost a single call between them.
 *
 * Nothing here pins a value indefinitely: revalidation runs on an interval and
 * when the tab regains focus, so a page left open picks up a new signal on its
 * own.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const PREFIX = 'bhav:v1:'
/** Matches the backend's default Cache-Control max-age. */
export const DEFAULT_TTL = 5 * 60 * 1000
/** How often an open tab re-checks. Cheap: usually a 304. */
export const DEFAULT_POLL = 15 * 60 * 1000

export type Entry<T> = {
  body: T
  /** Epoch ms this body was received. */
  at: number
  /** The backend's data version, when it told us one. */
  version: string | null
}

type Listener<T> = (entry: Entry<T>) => void

const inflight = new Map<string, Promise<Entry<unknown>>>()
const listeners = new Map<string, Set<Listener<never>>>()
/** Mirrors localStorage so private-mode browsers still share within a session. */
const memory = new Map<string, Entry<unknown>>()

function keyOf(path: string): string {
  return PREFIX + path
}

export function read<T>(path: string): Entry<T> | null {
  const hit = memory.get(keyOf(path))
  if (hit) return hit as Entry<T>
  try {
    const raw = localStorage.getItem(keyOf(path))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Entry<T>
    if (!parsed || typeof parsed.at !== 'number') return null
    memory.set(keyOf(path), parsed)
    return parsed
  } catch {
    // Private mode, quota, or a body written by an older shape of this file.
    return null
  }
}

function write<T>(path: string, entry: Entry<T>): void {
  memory.set(keyOf(path), entry)
  try {
    localStorage.setItem(keyOf(path), JSON.stringify(entry))
  } catch {
    /* over quota or private mode — the in-memory copy still serves this tab */
  }
}

/** Drop everything we have stored. Used when the backend reports new data. */
export function clearAll(): void {
  memory.clear()
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(PREFIX))
      .forEach((k) => localStorage.removeItem(k))
  } catch {
    /* nothing to clear */
  }
}

function emit<T>(path: string, entry: Entry<T>): void {
  listeners.get(path)?.forEach((fn) => (fn as Listener<T>)(entry))
}

/**
 * Fetch, store, notify. Concurrent callers for the same path share one request
 * rather than racing — which is what stops three panels mounting at once from
 * opening three connections to a backend that may still be waking up.
 */
export function revalidate<T>(path: string, base: string): Promise<Entry<T>> {
  const existing = inflight.get(path)
  if (existing) return existing as Promise<Entry<T>>

  const run = (async () => {
    const res = await fetch(`${base}${path}`, { headers: { accept: 'application/json' } })
    if (!res.ok) {
      let detail = `${path} -> ${res.status}`
      try {
        const j = await res.json()
        if (j?.detail) detail = String(j.detail)
      } catch {
        /* non-JSON error body — keep the status line */
      }
      throw new Error(detail)
    }
    const entry: Entry<T> = {
      body: (await res.json()) as T,
      at: Date.now(),
      version: res.headers.get('X-Bhav-Data-Version'),
    }
    write(path, entry)
    emit(path, entry)
    return entry
  })()
    .finally(() => inflight.delete(path))

  inflight.set(path, run as Promise<Entry<unknown>>)
  return run
}

/**
 * Read-through cache for a one-shot call — the imperative counterpart to
 * `useCached`, for code that asks for something in an event handler rather than
 * on render.
 *
 * A past date's backtest is a historical fact, so walking back and forth across
 * the preset dates should cost the network nothing after the first visit to
 * each. A stale entry still short-circuits nothing: it revalidates, and the
 * ETag turns that into a 304.
 */
export async function cachedFetch<T>(
  path: string,
  base: string,
  ttl = DEFAULT_TTL,
): Promise<T> {
  const hit = read<T>(path)
  if (hit && Date.now() - hit.at < ttl) return hit.body
  try {
    return (await revalidate<T>(path, base)).body
  } catch (e) {
    // A stored answer beats an error for something that cannot have changed.
    if (hit) return hit.body
    throw e
  }
}

export type Cached<T> = {
  data: T | null
  error: string | null
  /** No body yet — the only state that should show a spinner. */
  loading: boolean
  /** Showing a stored body while a fresher one is on its way. */
  revalidating: boolean
  /** When the body on screen was fetched. */
  at: number | null
  refresh: () => void
}

export type CachedOptions = {
  /** How long a stored body is used without asking the network. */
  ttl?: number
  /** Re-check on this interval while the tab is open. 0 disables. */
  poll?: number
  /** Turn a fetch failure into something a person can act on. */
  describeError?: (e: unknown) => string
}

/**
 * Subscribe to one cached path.
 *
 * The returned `data` is populated on the very first render when anything was
 * stored, so a component using this has content before an effect has run.
 */
export function useCached<T>(
  path: string,
  base: string,
  options: CachedOptions = {},
): Cached<T> {
  const { ttl = DEFAULT_TTL, poll = DEFAULT_POLL, describeError } = options

  const [entry, setEntry] = useState<Entry<T> | null>(() => read<T>(path))
  const [error, setError] = useState<string | null>(null)
  const [revalidating, setRevalidating] = useState(false)
  // Read in callbacks that outlive the render they were made in.
  const entryRef = useRef(entry)
  entryRef.current = entry

  const load = useCallback(
    (force: boolean) => {
      const current = entryRef.current ?? read<T>(path)
      if (!force && current && Date.now() - current.at < ttl) return
      setRevalidating(true)
      revalidate<T>(path, base)
        .then(() => setError(null))
        .catch((e) => {
          // Only surface a failure when there is nothing to show instead.
          if (!entryRef.current) {
            setError(describeError ? describeError(e) : String(e))
          }
        })
        .finally(() => setRevalidating(false))
    },
    [path, base, ttl, describeError],
  )

  useEffect(() => {
    // Adopt whatever is stored for this path, in case it changed identity.
    setEntry(read<T>(path))

    const listener: Listener<T> = (next) => setEntry(next)
    const set = listeners.get(path) ?? new Set()
    set.add(listener as Listener<never>)
    listeners.set(path, set)

    load(false)

    // A tab left open on a phone in a pocket should not go stale silently, and
    // coming back to it is exactly when someone looks at the number again.
    const onFocus = () => load(false)
    window.addEventListener('focus', onFocus)
    const timer = poll > 0 ? window.setInterval(() => load(false), poll) : 0

    return () => {
      set.delete(listener as Listener<never>)
      if (set.size === 0) listeners.delete(path)
      window.removeEventListener('focus', onFocus)
      if (timer) window.clearInterval(timer)
    }
  }, [path, load, poll])

  return {
    data: entry?.body ?? null,
    error: entry ? null : error,
    loading: !entry && !error,
    revalidating,
    at: entry?.at ?? null,
    refresh: () => load(true),
  }
}
