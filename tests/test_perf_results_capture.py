"""One-shot perf measurement printout — run with `pytest -s` to see numbers.

Captures latency for full payload, tail-30 (Task 1), metadata-only,
and ETag-304 fast path (Task 6).  Marked `xfail` so it's not part of
the regular gate; produces output for PERF_RESULTS.md updates.
"""
import json, secrets, statistics, time, urllib.error, urllib.request
import pytest
from tests._pytest_port import BASE
from tests.conftest import TEST_STATE_DIR

SESSION_DIR = TEST_STATE_DIR / "sessions"


def _seed(sid: str, n: int = 200) -> int:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    msgs = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append({"role": "user", "content": f"Q{i}: explain X. " + ("lorem " * 10)})
        else:
            extras = "\n\n```mermaid\ngraph TD;A-->B;\n```\n" if i % 11 == 0 else ""
            msgs.append({"role": "assistant", "content": f"A{i}. " + ("response " * 30) + extras})
    p = {"session_id": sid, "title": "perf", "workspace": "/tmp", "model": "x",
         "created_at": now, "updated_at": now, "last_message_at": now + n,
         "pinned": False, "archived": False, "project_id": None,
         "messages": msgs, "tool_calls": [], "active_stream_id": None,
         "pending_user_message": None, "pending_attachments": [], "pending_started_at": None}
    path = SESSION_DIR / f"{sid}.json"
    path.write_text(json.dumps(p), encoding="utf-8")
    return path.stat().st_size


def _get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers.items()), r.read(), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read(), time.perf_counter() - t0


def _median_ms(fn, n=10):
    return round(statistics.median([fn() for _ in range(n)]) * 1000, 2)


def test_print_perf_results(cleanup_test_sessions, capsys):
    sid = secrets.token_hex(6)
    size = _seed(sid, 200)
    # warm up
    for _ in range(3):
        _get(f"/api/session?session_id={sid}")
    full_ms = _median_ms(lambda: _get(f"/api/session?session_id={sid}")[3])
    meta_ms = _median_ms(lambda: _get(f"/api/session?session_id={sid}&messages=0")[3])
    tail_ms = _median_ms(lambda: _get(f"/api/session?session_id={sid}&tail=30")[3])
    _, h, _, _ = _get(f"/api/session?session_id={sid}")
    etag = h.get("ETag") or h.get("Etag")

    def _etag_hit():
        s, _, b, dt = _get(f"/api/session?session_id={sid}", {"If-None-Match": etag})
        assert s == 304 and b == b""
        return dt

    etag_ms = _median_ms(_etag_hit)
    _, _, full_body, _ = _get(f"/api/session?session_id={sid}")
    _, _, tail_body, _ = _get(f"/api/session?session_id={sid}&tail=30")
    _, _, meta_body, _ = _get(f"/api/session?session_id={sid}&messages=0")
    msg = (
        f"\n=== /api/session perf (200-msg synthetic, {size//1024}KB on disk) ===\n"
        f"Full payload :  {full_ms:>7.2f} ms   {len(full_body):>6} B\n"
        f"Tail 30 (T1) :  {tail_ms:>7.2f} ms   {len(tail_body):>6} B  "
        f"({100*len(tail_body)/max(1,len(full_body)):.0f}% of full)\n"
        f"Metadata only:  {meta_ms:>7.2f} ms   {len(meta_body):>6} B\n"
        f"ETag 304 (T6):  {etag_ms:>7.2f} ms        0 B\n"
    )
    with capsys.disabled():
        print(msg)
