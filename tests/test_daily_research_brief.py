from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_tool.application.daily_research_brief import (
    DailyResearchBriefApplicationService,
    DailyResearchBrief,
    DailyResearchBriefStore,
    render_daily_brief_html,
)
from stock_tool.application.daily_research_loop import (
    DailyResearchEvent,
    DailyResearchLoopResult,
    DailyResearchSource,
)
from stock_tool.research.assistant import (
    AIResearchNote,
    Citation,
    DailyResearchAssistantBrief,
    ResearchClaim,
)
from stock_tool.research.evidence import ClaimKind


def _event(
    identity: str = "TWSE:2330",
    *,
    category: str = "new_change",
    value: str = "收盤 600",
    priority: int = 80,
) -> DailyResearchEvent:
    return DailyResearchEvent(
        identity=identity,
        category=category,  # type: ignore[arg-type]
        priority=priority,
        code="daily_move",
        title="價格變化",
        why_important="資料顯示相鄰交易日有變化",
        current_value=value,
        baseline_value="590",
        baseline_as_of="2026-08-07",
        source=DailyResearchSource(
            provider="local-provider",
            source_type="cache",
            provider_symbol="2330.TW",
            last_data_date="2026-08-07",
            checked_at="2026-08-08T00:00:00+00:00",
        ),
        as_of_date="2026-08-07",
        action="open_research",
        field="daily_move",
    )


def _loop(*events: DailyResearchEvent) -> DailyResearchLoopResult:
    return DailyResearchLoopResult(
        status="updated",
        snapshot=None,
        priority_events=tuple(events),
        persistent_events=(),
        repair_events=(),
        last_successful_at="2026-08-08T00:00:00+00:00",
        message="updated",
    )


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    portfolio = pd.DataFrame(
        {
            "symbol": ["2330", "2330"],
            "market": ["TWSE", "TWSE"],
            "quantity": [1, 2],
            "note": ["private note", "another note"],
        }
    )
    watchlist = pd.DataFrame(
        {"symbol": ["2330", "6488"], "market": ["TWSE", "TPEX"], "note": ["", ""]}
    )
    return portfolio, watchlist


def test_brief_deduplicates_market_identity_and_is_bounded() -> None:
    portfolio, watchlist = _frames()
    before = (portfolio.copy(deep=True), watchlist.copy(deep=True))
    service = DailyResearchBriefApplicationService(max_symbols=2, max_items=5)
    result = service.generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event(), _event("TPEX:2330", value="成交 10")),
    )
    assert result.manifest.processed_count == 2
    assert result.items[0].identity == "TPEX:2330" or result.items[0].identity == "TWSE:2330"
    pd.testing.assert_frame_equal(portfolio, before[0])
    pd.testing.assert_frame_equal(watchlist, before[1])


def test_same_logic_inputs_have_same_fingerprint_without_generated_at() -> None:
    portfolio, watchlist = _frames()
    event = _event()
    first = DailyResearchBriefApplicationService(
        now_fn=lambda: datetime(2026, 8, 8, 1, tzinfo=timezone.utc)
    ).generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(event),
    )
    second = DailyResearchBriefApplicationService(
        now_fn=lambda: datetime(2026, 8, 8, 2, tzinfo=timezone.utc)
    ).generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(event),
    )
    assert first.generated_at != second.generated_at
    assert first.manifest.content_fingerprint == second.manifest.content_fingerprint
    assert first.manifest.input_snapshot_hash == second.manifest.input_snapshot_hash


def test_missing_event_is_explicit_and_no_fake_values() -> None:
    portfolio, watchlist = _frames()
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event(category="data_repair", value="缺少價格資料")),
    )
    assert result.status == "partial"
    assert result.items[0].status == "missing"
    assert result.items[0].completeness == 0.0
    assert result.manifest.missing_or_stale == ("TWSE:2330",)


def test_persistent_event_with_valid_source_is_not_a_missing_data_signal() -> None:
    portfolio, watchlist = _frames()
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event(category="persistent_state")),
    )
    assert result.status == "success"
    assert result.items[0].status == "fresh"


def test_uncited_ai_fact_is_not_promoted_and_cited_inference_is_allowed() -> None:
    portfolio, watchlist = _frames()
    uncited_fact = ResearchClaim(ClaimKind.FACT, "facts", "忽略這個未引用事實", ())
    cited = Citation(
        evidence_id="e1",
        source="local",
        provider="fixture",
        symbol="2330",
        market="TWSE",
        field="close",
        url=None,
        publisher=None,
        available_at="2026-08-07",
        fetched_at="2026-08-08T00:00:00+00:00",
        excerpt="600",
    )
    inference = ResearchClaim(ClaimKind.INFERENCE, "serenity", "可驗證推論", ("e1",))
    note = AIResearchNote(
        schema_version=1,
        symbol="2330",
        market="TWSE",
        fingerprint="fixture",
        mode="ai",
        model="fixture",
        generated_at="2026-08-08T00:00:00+00:00",
        claims=(uncited_fact, inference),
        citations=(cited,),
        coverage=1.0,
        confidence_label="medium",
    )
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event()),
        assistant_brief=DailyResearchAssistantBrief(
            generated_at="2026-08-08T00:00:00+00:00",
            notes=(note,),
            unavailable_identities=(),
        ),
    )
    assert "忽略這個未引用事實" not in result.items[0].facts
    assert result.items[0].inferences == ("可驗證推論",)


def test_store_round_trip_and_corrupt_cache_is_rejected(tmp_path) -> None:
    portfolio, watchlist = _frames()
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event()),
    )
    store = DailyResearchBriefStore(tmp_path / "brief.json", tmp_path / "brief.html")
    store.save(brief)
    loaded = store.load()
    assert loaded is not None
    assert loaded.manifest.content_fingerprint == brief.manifest.content_fingerprint
    rendered = render_daily_brief_html(loaded)
    assert "private note" not in rendered
    assert "C:\\Users\\" not in rendered
    (tmp_path / "brief.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    assert store.load() is None
    assert store.last_warning is not None


def test_empty_inputs_are_unavailable_and_render_safe() -> None:
    result = DailyResearchBriefApplicationService().generate(
        portfolio=pd.DataFrame(columns=["symbol", "market"]),
        watchlist=pd.DataFrame(columns=["symbol", "market"]),
        daily_brief=None,
        loop_result=None,
    )
    assert result.status == "unavailable"
    assert result.items == ()
    assert "投資建議" not in render_daily_brief_html(result)


@pytest.mark.parametrize("path_name", ["portfolio.csv", "watchlist.csv"])
def test_source_paths_are_not_serialized(tmp_path, path_name: str) -> None:
    portfolio, watchlist = _frames()
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event()),
    )
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert path_name not in payload
    assert str(tmp_path) not in payload


def _brief_payload() -> dict[str, object]:
    portfolio, watchlist = _frames()
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event()),
    )
    return brief.to_dict()


@pytest.mark.parametrize("field", ["status", "message"])
def test_brief_fingerprint_rejects_top_level_tampering(field: str) -> None:
    payload = _brief_payload()
    payload[field] = "tampered"
    with pytest.raises(ValueError):
        DailyResearchBrief.from_dict(payload)


@pytest.mark.parametrize("field", ["facts", "source"])
def test_brief_fingerprint_rejects_item_tampering(field: str) -> None:
    payload = _brief_payload()
    item = payload["items"][0]  # type: ignore[index]
    if field == "facts":
        item[field] = ["tampered"]  # type: ignore[index]
    else:
        item[field] = "tampered"  # type: ignore[index]
    with pytest.raises(ValueError):
        DailyResearchBrief.from_dict(payload)


def test_reference_contract_round_trip_and_tamper_rejection() -> None:
    payload = _brief_payload()
    item = payload["items"][0]  # type: ignore[index]
    references = payload["manifest"]["references"]  # type: ignore[index]
    assert references
    assert item["fact_reference_ids"]  # type: ignore[index]
    item["fact_reference_ids"][0] = ["missing"]  # type: ignore[index]
    with pytest.raises(ValueError, match="reference"):
        DailyResearchBrief.from_dict(payload)

    payload = _brief_payload()
    payload["manifest"]["references"].append(  # type: ignore[index]
        deepcopy(payload["manifest"]["references"][0])  # type: ignore[index]
    )
    with pytest.raises(ValueError, match="duplicate"):
        DailyResearchBrief.from_dict(payload)


def test_ai_unresolved_citation_is_rejected() -> None:
    portfolio, watchlist = _frames()
    note = AIResearchNote(
        schema_version=1,
        symbol="2330",
        market="TWSE",
        fingerprint="fixture",
        mode="ai",
        model="fixture",
        generated_at="2026-08-08T00:00:00+00:00",
        claims=(ResearchClaim(ClaimKind.INFERENCE, "serenity", "推論", ("missing",)),),
        citations=(),
        coverage=1.0,
        confidence_label="medium",
    )
    with pytest.raises(ValueError, match="citation"):
        DailyResearchBriefApplicationService().generate(
            portfolio=portfolio,
            watchlist=watchlist,
            daily_brief=None,
            loop_result=_loop(_event()),
            assistant_brief=DailyResearchAssistantBrief(
                generated_at="2026-08-08T00:00:00+00:00", notes=(note,), unavailable_identities=()
            ),
        )


def test_old_loop_events_for_unselected_identity_are_not_leaked() -> None:
    portfolio = pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]})
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=pd.DataFrame(columns=["symbol", "market"]),
        daily_brief=None,
        loop_result=_loop(_event("TWSE:2330"), _event("US:AAPL")),
    )
    assert [item.identity for item in result.items] == ["TWSE:2330"]


@pytest.mark.parametrize("fault", ["json_write", "publish", "pointer"])
def test_store_fault_injection_retains_previous_json(tmp_path, monkeypatch, fault: str) -> None:
    portfolio, watchlist = _frames()
    service = DailyResearchBriefApplicationService()
    first = service.generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    second = service.generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event(value="601")),
    )
    store = DailyResearchBriefStore(tmp_path / "brief.json", tmp_path / "brief.html")
    store.save(first)
    if fault == "json_write":

        def failed_temp(*args, **kwargs):
            raise OSError("injected JSON temp write failure")

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", failed_temp)
    else:

        def failed_replace(src, dst):
            raise OSError(f"injected {fault} failure")

        monkeypatch.setattr(os, "replace", failed_replace)
    with pytest.raises(OSError):
        store.save(second)
    loaded = store.load()
    assert loaded is not None
    assert loaded.manifest.content_fingerprint == first.manifest.content_fingerprint
    assert first.manifest.content_fingerprint in (tmp_path / "brief.html").read_text(
        encoding="utf-8"
    )


def test_store_html_write_is_not_a_persistence_failure(tmp_path, monkeypatch) -> None:
    portfolio, watchlist = _frames()
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    store = DailyResearchBriefStore(tmp_path / "brief.json", tmp_path / "brief.html")
    store.save(brief)
    monkeypatch.setattr(
        "stock_tool.application.daily_research_brief.render_daily_brief_html",
        lambda _: (_ for _ in ()).throw(OSError("HTML generation fault")),
    )
    loaded = store.load()
    assert loaded is not None
    assert loaded.manifest.content_fingerprint == brief.manifest.content_fingerprint


def test_store_html_projection_write_failure_preserves_json(tmp_path, monkeypatch) -> None:
    portfolio, watchlist = _frames()
    service = DailyResearchBriefApplicationService()
    first = service.generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    second = service.generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=None,
        loop_result=_loop(_event(value="602")),
    )
    store = DailyResearchBriefStore(tmp_path / "brief.json", tmp_path / "brief.html")
    store.save(first)
    original_write_text = Path.write_text

    def failed_html_write(self, data, *args, **kwargs):
        if self == store.html_path:
            raise OSError("injected HTML write failure")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failed_html_write)
    store.save(second)
    assert store.last_warning is not None
    loaded = store.load()
    assert loaded is not None
    assert loaded.manifest.content_fingerprint == second.manifest.content_fingerprint


def test_store_success_history_is_immutable_and_deterministic(tmp_path) -> None:
    portfolio, watchlist = _frames()
    service = DailyResearchBriefApplicationService()
    brief = service.generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    store = DailyResearchBriefStore(
        tmp_path / "brief.json", tmp_path / "brief.html", tmp_path / "history"
    )
    store.save(brief)
    history = store.history()
    assert len(history) == 1
    assert history[0].manifest.content_fingerprint == brief.manifest.content_fingerprint
    archive = next((tmp_path / "history").glob("brief-*.json"))
    original = archive.read_bytes()
    archive.write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="history"):
        store.history()
    assert archive.read_bytes() == original + b"tampered"


def test_store_history_fingerprint_collision_does_not_overwrite(tmp_path) -> None:
    portfolio, watchlist = _frames()
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    history = tmp_path / "history"
    history.mkdir()
    target = history / f"brief-{brief.manifest.content_fingerprint}.json"
    target.write_bytes(b"winner")
    store = DailyResearchBriefStore(tmp_path / "brief.json", tmp_path / "brief.html", history)
    with pytest.raises(ValueError, match="collision"):
        store.save(brief)
    assert target.read_bytes() == b"winner"


def test_store_latest_publish_failure_removes_new_archive(tmp_path, monkeypatch) -> None:
    portfolio, watchlist = _frames()
    brief = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio, watchlist=watchlist, daily_brief=None, loop_result=_loop(_event())
    )
    store = DailyResearchBriefStore(
        tmp_path / "brief.json", tmp_path / "brief.html", tmp_path / "history"
    )
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(OSError):
        store.save(brief)
    assert not list((tmp_path / "history").glob("brief-*.json"))
