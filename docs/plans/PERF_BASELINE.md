# Performance Baseline — `/api/session` (Task 0)

> Captured by `tests/test_session_switch_perf.py` against a synthetic
> 200-message session (~82 KB on disk, mixed markdown / code / mermaid /
> katex content). Numbers from the test runner host on `2026-04-28`.

## Findings

| Metric | Value | Note |
|---|---|---|
| 200-message session file size | 81.8 KB | JSON, indent=2 |
| `/api/session` (full payload) median latency | **11.2 ms** | server-side, gzip on |
| `/api/session` (full payload) min/max | 11.0 / 11.3 ms | very stable |
| `/api/session?messages=0` (metadata) median | 0.7 ms | already fast — keep using on cold sidebar clicks |
| `Content-Encoding: gzip` on `/api/session` | ✅ **already on** | Task 6 only needs ETag |
| `ETag` on `/api/session` | ❌ not emitted | Task 6 to add |

## Implications for the plan

- **Server-side `/api/session` is NOT the bottleneck** (~11 ms for 200 msgs).
  Task 1 (`tail/since_idx`) is still useful for *very* long sessions and to
  enable Task 3's windowed render to fetch only what it needs, but it is
  not the highest-leverage change here.
- **Gzip is already enabled** in `j()`. Task 6 reduces to: add ETag + 304
  fast path. Saves the ~82 KB transfer entirely on cache hits.
- **The user's "切换非常差" pain is therefore client-side**: markdown parse +
  DOMPurify + Prism + mermaid/katex on the main thread, plus the full
  `innerHTML=` rebuild. That elevates Tasks 2 (DocumentFragment cache),
  3 (windowed render), 4 (worker), 5 (lazy diagrams), and 7 (frame slicing)
  to top priority.
- Tasks 1 and 6 stay in scope but expectation-managed: they bring net-positive
  improvements (smaller initial payload, instant cached re-fetch) but the
  **headline win** has to come from the client work.

## Reproducing the baseline

```
cd /mnt/disk8t/code/ai/hermes-webui-perf
python3 -m pytest tests/test_session_switch_perf.py -v \
  -o junit_logging=all --junit-xml=/tmp/perf_baseline.xml
python3 -c "import xml.etree.ElementTree as ET; \
  [print(tc.get('name'),[(p.get('name'),p.get('value')) for p in (tc.find('properties') or [])]) \
   for tc in ET.parse('/tmp/perf_baseline.xml').getroot().iter('testcase')]"
```

## Next: Task 1 (backend pagination) and beyond

After every task, append a delta row to `PERF_RESULTS.md` (created in Task 8)
so we can attribute improvement to specific commits.
