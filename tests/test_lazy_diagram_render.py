"""Lazy mermaid/katex render — renderMermaidBlocks/renderKatexBlocks must
defer the heavy mermaid.render() / katex.render() call until the block
actually scrolls into view.

Long sessions can have 50+ mermaid diagrams.  Rendering all of them on
session-switch (or first paint) blocks the main thread for hundreds of
milliseconds and is wasted work for blocks the user never scrolls to.

These tests assert the *mechanism* (IntersectionObserver gating) is
present in static/ui.js so a refactor can't silently regress to the
eager loop.  Functional behaviour (correct SVG output) is covered by
the existing mermaid tests.
"""
from pathlib import Path

import pytest

UI_JS = (Path(__file__).parent.parent / "static" / "ui.js").read_text(encoding="utf-8")


def _slice_function(name: str) -> str:
    """Return the source text of a top-level function by name (brace-balanced)."""
    needle = f"function {name}("
    start = UI_JS.find(needle)
    assert start != -1, f"function {name} not found in ui.js"
    i = UI_JS.index("{", start) + 1
    depth = 1
    while depth and i < len(UI_JS):
        c = UI_JS[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return UI_JS[start:i]


class TestMermaidLazy:
    def test_renderMermaidBlocks_uses_intersection_observer(self):
        body = _slice_function("renderMermaidBlocks")
        assert "IntersectionObserver" in body, (
            "renderMermaidBlocks must gate mermaid.render() behind an "
            "IntersectionObserver so off-screen diagrams don't block the "
            "main thread on session switch / first paint."
        )

    def test_mermaid_observer_uses_root_margin_for_pre_render(self):
        """We want diagrams to start rendering ~200px before they enter
        the viewport so the user doesn't see the <pre><code> placeholder
        flash to SVG mid-scroll."""
        body = _slice_function("renderMermaidBlocks")
        assert "rootMargin" in body, (
            "Observer should use rootMargin so diagrams render slightly "
            "before they scroll into view (avoid placeholder→SVG flash)."
        )

    def test_mermaid_unobserves_after_render_to_prevent_double_render(self):
        body = _slice_function("renderMermaidBlocks")
        assert "unobserve" in body, (
            "Once a diagram has been rendered, the observer must unobserve "
            "it so re-entering the viewport doesn't trigger another render."
        )

    def test_mermaid_falls_back_when_observer_unavailable(self):
        """Very old browsers (or jsdom) lack IntersectionObserver — the
        function must still render diagrams eagerly in that case."""
        body = _slice_function("renderMermaidBlocks")
        assert "typeof IntersectionObserver" in body or "'IntersectionObserver' in window" in body, (
            "Must feature-detect IntersectionObserver and fall back to "
            "eager render when it's missing."
        )


class TestKatexLazy:
    def test_renderKatexBlocks_uses_intersection_observer(self):
        body = _slice_function("renderKatexBlocks")
        assert "IntersectionObserver" in body, (
            "renderKatexBlocks must gate katex.render() behind an "
            "IntersectionObserver — same reasoning as mermaid."
        )

    def test_katex_unobserves_after_render(self):
        body = _slice_function("renderKatexBlocks")
        assert "unobserve" in body

    def test_katex_falls_back_when_observer_unavailable(self):
        body = _slice_function("renderKatexBlocks")
        assert "typeof IntersectionObserver" in body or "'IntersectionObserver' in window" in body


def test_eager_foreach_render_path_removed_from_mermaid():
    """The original code did `blocks.forEach(async block => mermaid.render(...))`
    unconditionally.  After the lazy refactor, the synchronous render call
    must only run inside the observer callback (or the no-IO fallback), not
    in the top-level forEach over all blocks."""
    body = _slice_function("renderMermaidBlocks")
    # Find every `mermaid.render(` call site and confirm none of them
    # appear in a top-level forEach loop that is reached on every call.
    # Heuristic: the only forEach on `blocks` should be one that calls
    # `observer.observe(block)` (or the eager fallback path).
    foreach_blocks = body.count("blocks.forEach")
    # We expect 1 (observer registration) or 2 (registration + fallback)
    # iterations, never an eager-render-everything loop.
    assert foreach_blocks <= 2, (
        f"Expected ≤2 blocks.forEach loops (observer-register + optional "
        f"fallback). Found {foreach_blocks} — looks like an eager loop "
        f"slipped back in."
    )
