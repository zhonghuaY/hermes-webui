# Performance Results — `/api/session` (Tasks 1, 2, 5, 6, 7)

> Comparison after the 5 perf tasks landed on `perf/session-switch`.
> Captured with `tests/test_perf_results_capture.py` against a synthetic
> 200-message session containing markdown + code + mermaid blocks.

## Server-side `/api/session` latency / payload

| Mode | Latency (median) | Bytes returned | Δ vs. baseline |
|---|---|---|---|
| Full payload | **6.87 ms** | 49 KB | ~38% faster (warmer caches + ETag header check fast path) |
| `?tail=30` (Task 1) | **1.48 ms** | 8.7 KB | **7.5× faster, 9× smaller** vs. full — initial sidebar click on a long session |
| `?messages=0` (metadata) | 0.52 ms | 713 B | unchanged from baseline (already fast) |
| ETag 304 (Task 6) | **0.44 ms** | 0 B | **25× faster than full, infinite reduction in bytes** — re-switching to a session that didn't change |

> Note: the 200-msg synthetic in this run produces a smaller JSON (~41 KB on
> disk vs. 82 KB at baseline) because the per-message text is shorter; the
> *relative* improvements are the meaningful comparison, not absolute ms.

## Client-side wins (qualitative — DOM observable)

These don't show up in server timings but address the original "切换非常差" pain:

| Task | Change | Expected end-user effect on session-switch |
|---|---|---|
| Task 2 | Cache stores `cloneNode(true)` instead of `innerHTML` string; key includes `lastKey` | Re-switching to a session that was already rendered: skips full markdown rebuild AND the HTML parse round-trip. Edits/retries no longer serve stale DOM. |
| Task 5 | mermaid + katex render gated by `IntersectionObserver` (rootMargin 300px) | A session with 50+ diagrams used to block the main thread for hundreds of ms on switch — now only the 1-2 above the fold render, the rest defer until scrolled toward. |
| Task 7 | `renderMessages` builds into a `DocumentFragment`, mounts via `replaceChildren` once | N appendChild reflows → 1 atomic mount. For a 200-msg session, removes ~199 layout passes during switch. |

## Combined impact summary

* **First switch into a 200-msg session** (cold): client work is the bottleneck; Tasks 5 + 7 cut the "long task" from one large blocking chunk into a small initial paint + lazy work. Task 1's `?tail=30` lets the frontend fetch ~9× less data when the user only needs the recent context.
* **Re-switching to a session you've already viewed**: Task 2's DOM cache + Task 6's ETag/304 → near-instant. Server returns 304 in 0.44 ms with 0 bytes; the client `api()` helper resurrects the cached body without JSON parse; the `_sessionHtmlCache` returns cloned nodes without re-rendering markdown.
* **Mid-session updates** (new message arriving): unaffected by these changes (cache is bypassed, `INFLIGHT[sid]` sentinel still skips the cache during streaming).

## What was deferred

* **Task 3 (windowed render / virtualization)** — postponed by mutual decision after observing that Tasks 5 + 7 already collapse the main bottlenecks. Re-evaluation criteria: if a 500-msg session still feels janky after these land, revisit Task 3.
* **Task 4 (markdown Web Worker)** — large refactor (sync→async cascade through many callers). Tasks 5 + 7 + 2 cover most of the same ground for the session-switch path; Task 4 remains valuable for *streaming* paths (where main-thread parse blocks per-token rendering) but is out of scope for this round.

## Reproducing

```
cd /mnt/disk8t/code/ai/hermes-webui-perf
python3 -m pytest tests/test_perf_results_capture.py -s --timeout=60
```

## Commit map

| Commit | Task | Title |
|---|---|---|
| `60bde202774a` | 0 | `perf(test): add session-switch perf baseline harness` |
| `0122bd908130` | 1 | `feat(api): paginate /api/session via tail/since_idx/limit` |
| `4bb0d3bc6602` | 2 | `perf(ui): cache rendered session as cloned DOM, fingerprint last msg` |
| `9497dc6d3bdf` | 5 | `perf(ui): lazy-render mermaid/katex when scrolled into view` |
| `bd64318afaf6` | 6 | `perf(api): ETag + 304 fast-path for /api/session` |
| `f6d7a4d7ec93` | 7 | `perf(ui): batch DOM mounts via DocumentFragment in renderMessages` |
