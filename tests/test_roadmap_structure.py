from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fenced_ranges(text: str) -> tuple[tuple[int, int], ...]:
    lines = text.splitlines()
    starts: list[int] = []
    ranges: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not line.strip().startswith("```"):
            continue
        if starts:
            ranges.append((starts.pop(), index))
        else:
            starts.append(index)
    assert not starts, "roadmap has an unclosed code fence"
    return tuple(ranges)


def test_sprint_20_to_23_extension_is_normal_markdown_outside_dependency_fence() -> None:
    text = (PROJECT_ROOT / "PRODUCT_EXECUTION_PLAN.md").read_text(encoding="utf-8")
    extension_start = text.index("## Roadmap extension: Sprint 20–23")
    extension_end = text.index("### 12.2", extension_start)
    assert extension_start < extension_end
    assert not any(start <= extension_start < end for start, end in _fenced_ranges(text))
    extension = text[extension_start:extension_end]
    assert "Sprint 20–22 are locally implemented and independently validated" in extension
    assert "Sprint 23" in extension
    assert "pending independent acceptance" in extension


def test_dependency_diagram_closing_fence_precedes_extension() -> None:
    text = (PROJECT_ROOT / "PRODUCT_EXECUTION_PLAN.md").read_text(encoding="utf-8")
    diagram_start = text.index("### 12.1")
    diagram_end = text.index("## Roadmap extension: Sprint 20–23")
    diagram = text[diagram_start:diagram_end]
    assert diagram.count("```") == 2
    assert diagram.rstrip().endswith("```")


def test_sprint_24_extension_is_explicitly_pending_and_outside_fences() -> None:
    text = (PROJECT_ROOT / "PRODUCT_EXECUTION_PLAN.md").read_text(encoding="utf-8")
    start = text.index("### Sprint 24 — Research Context & Workspace Handoff")
    section = text[start:]
    assert "pending independent CTO acceptance" in section
    assert "no new provider" in section
    assert not any(begin <= start < end for begin, end in _fenced_ranges(text))


def test_sprint_25_market_monitor_scope_is_explicit_and_outside_fences() -> None:
    text = (PROJECT_ROOT / "PRODUCT_EXECUTION_PLAN.md").read_text(encoding="utf-8")
    start = text.index("### Sprint 25 — 台股盤後市場監控 MVP")
    section = text[start:]
    assert "STOCK_DAY_ALL" in section
    assert "tpex_mainboard_daily_close_quotes" in section
    assert "pending independent CTO acceptance" in section
    assert "render-time request" in section
    assert not any(begin <= start < end for begin, end in _fenced_ranges(text))
