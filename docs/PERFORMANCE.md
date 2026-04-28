# Hermes Web UI — Performance Notes

> Operational guide for the perf-sensitive code paths.  See
> `docs/plans/PERF_RESULTS.md` for the latest before/after numbers
> and `docs/plans/2026-04-28-session-switch-perf.md` for the design plan.

## Session switch — design overview

Switching between sessions is the most user-visible perf path in the UI.
The current architecture has four collaborating layers, each addressing
a specific cost:

### 1. Backend: pagination + ETag (`api/routes.py`, `api/helpers.py`)

* `/api/session` accepts optional `tail=N`, `since_idx=K`, `limit=M`
  parameters.  Each returned message carries `_idx` (its absolute index)
  and the response includes `pagination: {start_idx, end_idx, total}`.
  The frontend uses `?tail=30` for initial paint of long sessions.
* `/api/session` emits a weak ETag built from `sha1(sid|updated_at|count|params)`.
  When the client sends `If-None-Match` matching the current fingerprint,
  the server returns **304 with empty body** before doing any serialization
  / redact / gzip work.  Sub-millisecond server cost; zero network bytes.
* `Cache-Control: no-cache` is set on `/api/session` (other endpoints keep
  the default `no-store`) so browsers actually send `If-None-Match` —
  `no-store` would make the 304 path dead.

### 2. Client request layer: ETag-aware GET cache (`static/workspace.js`)

The `api()` helper maintains a 32-entry LRU keyed by URL → `{etag, body}`.
When a cached URL is requested again it sends `If-None-Match`; on 304 it
returns the stored body verbatim — no JSON parse.  Scoped narrowly to
`/api/session*` to avoid serving stale data from endpoints whose ETag
semantics weren't designed for it.

### 3. Client render cache: cloned DOM (`static/ui.js` — `_sessionHtmlCache`)

Switching back to a session that's already been rendered restores from a
deep-cloned DOM tree instead of rebuilding from JSON / markdown:

* Cache value: `{node: inner.cloneNode(true), count, lastKey}`.
* Cache key: `sid + (count, lastKey)`.  `lastKey` is a cheap fingerprint
  of the *last* message (`role|len|head32|tail32`) so edits/retries on
  the most recent turn invalidate correctly.
* On hit: `inner.replaceChildren(...cached.node.cloneNode(true).childNodes)`
  — no HTML parse, no markdown re-render.
* LRU 16 sessions; evicts oldest beyond that.
* Skipped while a session is mid-stream (`INFLIGHT[sid]` sentinel).

### 4. Client render path: fragment build + lazy heavy renders (`static/ui.js`)

* `renderMessages()` builds every row, separator, assistant turn, and
  compression card into a detached `DocumentFragment` and commits with
  a single `inner.replaceChildren(_frag)`.  N reflows → 1.
* `renderMermaidBlocks()` / `renderKatexBlocks()` gate `mermaid.render()`
  and `katex.render()` behind shared `IntersectionObserver`s with
  `rootMargin: '300px 0px'`.  Off-screen diagrams don't run until they
  scroll near the viewport; the observer auto-`unobserve`s after first
  intersect to prevent double-render.
* Both functions feature-detect `IntersectionObserver` and fall back to
  eager rendering when it's missing (very old browsers / jsdom).

## Operating principles

1. **Server-side `/api/session` is fast (≤7 ms for 200 msgs).**  Don't
   chase server perf for normal-length sessions; reach for the client
   tools first.
2. **The biggest wins are in DOM construction and lazy heavy renders.**
   Adding a new heavy widget?  Wrap it in `IntersectionObserver` from
   day one — don't render off-screen.
3. **Anything that mutates the existing render cache must update both
   `count` and `lastKey`** or you'll serve stale HTML on session re-switch.
4. **Streaming sessions never use the render cache** — the `INFLIGHT[sid]`
   guard exists because the live `smd` parser writes into a DOM node
   that `cloneNode(true)` would detach.

## Regression tests

| File | Pins |
|---|---|
| `tests/test_session_pagination.py` | `tail / since_idx / limit` correctness + edge cases |
| `tests/test_session_cache_key.py` | `_sessionCacheKey` fingerprint behaviour (8 cases) |
| `tests/test_session_etag.py` | ETag emission, 304 on match, varies-by-query |
| `tests/test_lazy_diagram_render.py` | mermaid/katex `IntersectionObserver` mechanism |
| `tests/test_render_fragment.py` | `renderMessages` uses `DocumentFragment` + `replaceChildren` |
| `tests/test_session_switch_perf.py` | Ongoing baseline measurement (currently soft assertions) |
| `tests/test_perf_results_capture.py` | One-shot perf snapshot for `PERF_RESULTS.md` updates |

## When to revisit

* If 500-msg sessions feel janky despite Tasks 5 + 7, add windowed render
  (Task 3 in the original plan) — only mount the last 30 messages on
  switch, IntersectionObserver sentinel reveals more on scroll-up.
* If streaming feels janky during long-tool-call output, move markdown
  parse to a Web Worker (Task 4 in the original plan).  The render cache
  /switch path don't need it; live streaming might.
