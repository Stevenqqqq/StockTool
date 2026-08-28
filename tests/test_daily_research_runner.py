from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import stock_tool.application.daily_research_runner as runner_module
from stock_tool.application.daily_research_runner import (
    DailyResearchRunManifest,
    DailyResearchRunner,
)
from stock_tool.application.daily_research_scheduler import (
    DailyResearchRunOutcome,
    DailyResearchStageResult,
    ScheduledRunRecord,
)
from stock_tool.runtime_paths import RuntimePaths


def _record(*, status: str = "success", exit_code: int = 0) -> ScheduledRunRecord:
    return ScheduledRunRecord(
        run_id="run-fixture",
        trigger="manual",
        scheduled_for=None,
        started_at="2026-08-24T10:00:00+00:00",
        completed_at="2026-08-24T10:00:01+00:00",
        status=status,
        exit_code=exit_code,
        input_snapshot_hash="a" * 64,
        output_brief_fingerprint="b" * 64 if status == "success" else None,
        data_as_of="2026-08-23" if status == "success" else None,
        deterministic_fallback_used=True,
        reason=None if status == "success" else "資料不足",
        duration_seconds=1.0,
    )


def _stages(*statuses: str, reason: str | None = None) -> tuple[DailyResearchStageResult, ...]:
    names = (
        "target_refresh",
        "market_refresh",
        "brief",
        "change",
        "prediction_registration",
        "notification",
    )
    return tuple(
        DailyResearchStageResult(
            name=name,
            status=status,
            input_snapshot_hash="a" * 64,
            output_fingerprint=("b" * 64 if name == "brief" and status == "success" else None),
            data_as_of="2026-08-23" if status == "success" else None,
            reason=None if status == "success" else reason,
        )
        for name, status in zip(names, statuses)
    )


def test_daily_research_runner_persists_ordered_stage_manifest(monkeypatch, tmp_path: Path) -> None:
    class FakeCore:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, *, trigger, dry_run):
            assert trigger == "manual"
            assert dry_run is False
            record = _record()
            return DailyResearchRunOutcome(
                "success", 0, None, record, stages=_stages(*(["success"] * 6))
            )

    monkeypatch.setattr(runner_module, "HeadlessDailyResearchRunner", FakeCore)
    paths = RuntimePaths(tmp_path).ensure_directories()
    result = DailyResearchRunner(paths).run()

    assert result.status == "success"
    manifest = DailyResearchRunner(paths).latest_manifest()
    assert manifest is not None
    assert [stage.name for stage in manifest.stages] == [
        "target_refresh",
        "market_refresh",
        "brief",
        "change",
        "prediction_registration",
        "notification",
    ]
    assert [stage.status for stage in manifest.stages[:5]] == ["success"] * 5
    assert (paths.daily_research_run_manifests_dir / "run-fixture.json").is_file()


def test_daily_research_runner_persists_phase1_outcome_evaluation_stage(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeCore:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            record = _record()
            names = (
                "target_refresh",
                "market_refresh",
                "brief",
                "change",
                "prediction_registration",
                "prediction_outcome_evaluation",
                "notification",
            )
            stages = tuple(
                DailyResearchStageResult(
                    name=name,
                    status="success" if name != "prediction_outcome_evaluation" else "partial",
                    input_snapshot_hash="a" * 64,
                    output_fingerprint=(
                        "b" * 64 if name == "prediction_outcome_evaluation" else None
                    ),
                    data_as_of="2026-08-23",
                    reason="仍有待結算樣本" if name == "prediction_outcome_evaluation" else None,
                )
                for name in names
            )
            return DailyResearchRunOutcome("partial", 10, "仍有待結算樣本", record, stages=stages)

    monkeypatch.setattr(runner_module, "HeadlessDailyResearchRunner", FakeCore)
    paths = RuntimePaths(tmp_path).ensure_directories()
    DailyResearchRunner(paths).run()
    manifest = DailyResearchRunner(paths).latest_manifest()
    assert manifest is not None
    assert manifest.schema_version == 3
    assert [stage.name for stage in manifest.stages] == [
        "target_refresh",
        "market_refresh",
        "brief",
        "change",
        "prediction_registration",
        "prediction_outcome_evaluation",
        "notification",
    ]
    assert manifest.stages[5].status == "partial"


def test_daily_research_runner_partial_does_not_claim_downstream_success(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeCore:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            record = _record(status="partial", exit_code=10)
            return DailyResearchRunOutcome(
                "partial",
                10,
                "資料不足",
                record,
                stages=_stages(
                    "success",
                    "partial",
                    "skipped",
                    "skipped",
                    "skipped",
                    "skipped",
                    reason="資料不足",
                ),
            )

    monkeypatch.setattr(runner_module, "HeadlessDailyResearchRunner", FakeCore)
    paths = RuntimePaths(tmp_path).ensure_directories()
    DailyResearchRunner(paths).run()
    manifest = DailyResearchRunner(paths).latest_manifest()
    assert manifest is not None
    assert [stage.status for stage in manifest.stages] == [
        "success",
        "partial",
        "skipped",
        "skipped",
        "skipped",
        "skipped",
    ]


def test_daily_research_manifest_rejects_missing_or_extra_fields() -> None:
    payload = {
        "schema_version": 2,
        "run_id": "run",
        "trigger": "manual",
        "status": "success",
        "exit_code": 0,
        "started_at": "2026-08-24T10:00:00+00:00",
        "completed_at": "2026-08-24T10:00:01+00:00",
        "stages": [
            {
                "name": name,
                "status": "success",
                "input_snapshot_hash": None,
                "output_fingerprint": None,
                "data_as_of": None,
                "output_reference": None,
                "reason": None,
            }
            for name in (
                "target_refresh",
                "market_refresh",
                "brief",
                "change",
                "prediction_registration",
                "notification",
            )
        ],
        "input_snapshot_hash": None,
        "output_brief_fingerprint": None,
        "market_snapshot_hash": None,
        "market_status": None,
        "market_source_state": None,
        "market_data_as_of": None,
        "data_as_of": None,
        "deterministic_fallback_used": True,
        "reason": None,
    }
    parsed = DailyResearchRunManifest.from_dict(payload)
    assert parsed.schema_version == 2
    payload["unexpected"] = True
    with pytest.raises(ValueError):
        DailyResearchRunManifest.from_dict(payload)


def test_manifest_uses_typed_stage_results_and_market_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeMarketResult:
        status = "fresh"
        source_state = "official"
        snapshot = type(
            "FakeSnapshot",
            (),
            {"metadata": type("Meta", (), {"data_date": "2026-08-23"})()},
        )()

    stages = tuple(
        DailyResearchStageResult(
            name=name,
            status=status,
            input_snapshot_hash="a" * 64,
            output_fingerprint=("b" * 64 if name == "brief" else None),
            data_as_of="2026-08-23",
            reason=reason,
        )
        for name, status, reason in (
            ("target_refresh", "success", None),
            ("market_refresh", "success", None),
            ("brief", "success", None),
            ("change", "failure", "change 保存失敗"),
            ("prediction_registration", "skipped", "樣本已存在"),
            ("notification", "unavailable", "通知未啟用"),
        )
    )

    class FakeCore:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            return DailyResearchRunOutcome(
                "partial",
                10,
                "change 保存失敗",
                _record(status="partial", exit_code=10),
                stages=stages,
                market_result=FakeMarketResult(),
                market_snapshot_hash="c" * 64,
            )

    monkeypatch.setattr(runner_module, "HeadlessDailyResearchRunner", FakeCore)
    paths = RuntimePaths(tmp_path).ensure_directories()
    result = DailyResearchRunner(paths).run()
    assert result.status == "partial"
    manifest = DailyResearchRunner(paths).latest_manifest()
    assert manifest is not None
    assert [stage.status for stage in manifest.stages] == [
        "success",
        "success",
        "success",
        "failure",
        "skipped",
        "unavailable",
    ]
    assert manifest.market_snapshot_hash == "c" * 64
    assert manifest.market_status == "fresh"
    assert manifest.market_source_state == "official"


def test_manifest_publish_exception_preserves_core_stage_trace(monkeypatch, tmp_path: Path) -> None:
    """A façade publish failure must not erase the six real core stages."""

    class FakeCore:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            record = _record(status="partial", exit_code=10)
            return DailyResearchRunOutcome(
                "partial",
                10,
                "change 保存失敗",
                record,
                stages=_stages(
                    "success",
                    "success",
                    "success",
                    "failure",
                    "skipped",
                    "skipped",
                    reason="前一階段未完成",
                ),
            )

    monkeypatch.setattr(runner_module, "HeadlessDailyResearchRunner", FakeCore)
    monkeypatch.setattr(
        runner_module.DailyResearchRunner,
        "_persist_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("manifest")),
    )
    paths = RuntimePaths(tmp_path).ensure_directories()
    result = DailyResearchRunner(paths).run()

    assert result.status == "failed"
    assert result.exit_code == 40
    assert [stage.status for stage in result.stages] == [
        "success",
        "success",
        "success",
        "failure",
        "skipped",
        "skipped",
    ]


def test_headless_refreshes_official_markets_once_and_reuses_same_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    import pandas as pd
    from types import SimpleNamespace

    import stock_tool.application.daily_research_scheduler as scheduler_module

    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    frame = pd.DataFrame([{"symbol": "2330", "market": "TWSE"}])
    paths.portfolio_file.write_text(
        "symbol,market,quantity,average_cost\n2330,TWSE,1,600\n", encoding="utf-8"
    )
    monkeypatch.setattr(scheduler_module, "load_portfolio", lambda _path: frame)
    monkeypatch.setattr(scheduler_module, "load_watchlist", lambda _path: frame.iloc[0:0])
    monkeypatch.setattr(scheduler_module, "build_effective_watchlist", lambda _w, _p: frame)
    monkeypatch.setattr(
        scheduler_module,
        "_load_price_context",
        lambda _paths: (
            pd.DataFrame(
                [{"symbol": "2330", "market": "TWSE", "date": "2026-08-23", "close": 600.0}]
            ),
            {"TWSE:2330": "2026-08-23T10:00:00+00:00"},
        ),
    )
    monkeypatch.setattr(scheduler_module, "_load_local_valuation", lambda *_args: None)
    monkeypatch.setattr(
        scheduler_module, "_load_local_research_continuations", lambda *_args, **_kwargs: ()
    )
    monkeypatch.setattr(scheduler_module, "_load_local_fundamental_scores", lambda *_args: None)
    monkeypatch.setattr(
        scheduler_module.DailyBriefService, "build", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        scheduler_module.DailyResearchLoopService,
        "complete_success",
        lambda *_args, **_kwargs: SimpleNamespace(snapshot=None),
    )
    brief = _record(status="success").output_brief_fingerprint
    assert brief is not None
    captured: dict[str, object] = {}
    fake_brief = SimpleNamespace(
        status="success",
        manifest=SimpleNamespace(
            content_fingerprint=brief,
            as_of_date="2026-08-23",
            brief_date="2026-08-24",
        ),
    )

    def generate(_self, **kwargs):
        captured["brief_market"] = kwargs["market_result"]
        return fake_brief

    monkeypatch.setattr(scheduler_module.DailyResearchBriefApplicationService, "generate", generate)

    class FakeBriefStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def history(self):
            return ()

        def save(self, _brief):
            return None

    class FakeChangeStore:
        def __init__(self, *_args, **_kwargs):
            pass

        def save(self, _change):
            return None

    monkeypatch.setattr(scheduler_module, "DailyResearchBriefStore", FakeBriefStore)
    monkeypatch.setattr(scheduler_module, "DailyResearchChangeStore", FakeChangeStore)
    monkeypatch.setattr(
        scheduler_module.DailyResearchChangeApplicationService,
        "compare",
        lambda *_args, **_kwargs: object(),
    )

    fake_snapshot = SimpleNamespace(
        metadata=SimpleNamespace(
            status="ready",
            freshness="fresh",
            market="TWSE",
            data_date="2026-08-23",
            payload_sha256="a" * 64,
            valid_rows=1,
            coverage=1.0,
        ),
        quotes=(
            SimpleNamespace(
                market="TWSE",
                symbol="2330",
                close=600.0,
                change=1.0,
                change_pct=1.0,
                volume=1000.0,
                value=600000.0,
                status="valid",
                product_type="stock",
            ),
        ),
        source_metadata=(SimpleNamespace(data_date="2026-08-23"),),
        to_dict=lambda: {"quotes": [{"market": "TWSE", "symbol": "2330", "change_pct": 1.0}]},
    )
    fake_market_result = SimpleNamespace(
        status="fresh", source_state="official", snapshot=fake_snapshot, warnings=()
    )
    market_calls: list[tuple[str, ...]] = []

    class FakeMarketService:
        def __init__(self, *_args, **_kwargs):
            pass

        def refresh(self, *, markets):
            market_calls.append(tuple(markets))
            return fake_market_result

    monkeypatch.setattr(scheduler_module, "MarketMonitorApplicationService", FakeMarketService)

    class FakePredictionService:
        def __init__(self, *_args, **_kwargs):
            pass

        def register_from_market_snapshot(self, snapshot, **_kwargs):
            captured["prediction_snapshot"] = snapshot
            return SimpleNamespace(status="success", records=(), created_count=1, skipped_count=0)

    monkeypatch.setattr(scheduler_module, "PredictionLabApplicationService", FakePredictionService)
    monkeypatch.setattr(
        scheduler_module.PredictionLabStore,
        "from_runtime_paths",
        lambda _paths: SimpleNamespace(ensure=lambda: object()),
    )
    monkeypatch.setattr(
        scheduler_module,
        "economic_input_fingerprint",
        lambda *_args, **_kwargs: "d" * 64,
    )
    runner = scheduler_module.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: datetime(2026, 8, 24, 10, tzinfo=timezone.utc),
        refresh_callback=lambda *_args: (),
        on_success=lambda *_args, **_kwargs: SimpleNamespace(status="sent", reason=None),
    )
    outcome = runner.run(trigger="manual")
    assert outcome.status == "success"
    assert market_calls == [("TWSE", "TPEX")]
    assert captured["brief_market"] is fake_market_result
    assert captured["prediction_snapshot"] is fake_snapshot


def test_market_snapshot_date_mismatch_blocks_prediction_samples() -> None:
    from types import SimpleNamespace

    import stock_tool.application.daily_research_scheduler as scheduler_module

    metadata = SimpleNamespace(status="ready", freshness="fresh")
    mismatched = SimpleNamespace(
        status="fresh",
        snapshot=SimpleNamespace(
            metadata=metadata,
            source_metadata=(
                SimpleNamespace(data_date="2026-08-23"),
                SimpleNamespace(data_date="2026-08-24"),
            ),
        ),
    )
    matching = SimpleNamespace(
        status="fresh",
        snapshot=SimpleNamespace(
            metadata=metadata,
            source_metadata=(
                SimpleNamespace(data_date="2026-08-24"),
                SimpleNamespace(data_date="2026-08-24"),
            ),
        ),
    )

    assert not scheduler_module._market_result_is_sample_eligible(mismatched)
    assert scheduler_module._market_result_is_sample_eligible(matching)
