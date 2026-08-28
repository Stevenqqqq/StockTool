from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import nullcontext
from dataclasses import replace

import pytest

from stock_tool.application.market_monitor import (
    EvidenceFixtureMarketFetcher,
    OFFICIAL_ENDPOINTS,
    MarketMonitorApplicationService,
    MarketQuoteRow,
    MarketSnapshotCache,
    OfficialPayload,
    build_industry_heat,
    build_rankings,
    build_snapshot,
    compare_official_breadth,
    compute_breadth,
    parse_number,
    parse_official_quotes,
    parse_official_universe,
    parse_tpex_quotes,
)
from stock_tool.dashboard.pages.discovery import _render_market_overview


def _payload(
    market: str, rows: list[dict[str, object]], date: str = "2026-08-05"
) -> OfficialPayload:
    return OfficialPayload(
        market=market,
        payload=rows,
        endpoint=OFFICIAL_ENDPOINTS[market],
        payload_sha256=f"hash-{market}",
        data_date=date,
    )


def test_number_parser_preserves_missing_and_formats() -> None:
    assert parse_number("+1,234.50") == 1234.5
    assert parse_number("-0.25", percent=True) == -0.25
    assert parse_number("--") is None
    assert parse_number(1.0e309) is None
    assert parse_number(True) is None


def test_official_roc_date_is_normalized_to_gregorian() -> None:
    payload = [{"Date": "1150805", "Code": "2330", "ClosingPrice": "1000"}]
    official = OfficialPayload(
        market="TWSE",
        payload=payload,
        endpoint="twse",
        payload_sha256="payload",
    )
    assert build_snapshot([official]).metadata.data_date == "2026-08-05"


def test_twse_parser_handles_duplicates_invalid_and_no_trade() -> None:
    rows, excluded, warnings = parse_official_quotes(
        [
            {
                "Code": "2330",
                "Name": "TSMC",
                "ClosingPrice": "1,000.0",
                "PriceChange": "+10",
                "TradeVolume": "2,000",
                "TradeValue": "3,000",
            },
            {"Code": "2330", "ClosingPrice": "999", "PriceChange": "-1"},
            {"Code": "6488", "ClosingPrice": "--", "PriceChange": "--"},
            {"Code": "bad", "ClosingPrice": "-1", "PriceChange": "0"},
            {"Code": "9999", "Market": "TPEX", "ClosingPrice": "10"},
        ],
        market="TWSE",
    )
    assert [row.identity for row in rows] == ["TWSE:2330", "TWSE:6488"]
    assert rows[0].close == 1000
    assert rows[1].status == "no_trade"
    assert excluded == 3
    assert any("duplicate" in warning for warning in warnings)
    assert any("market-mismatch" in warning for warning in warnings)


def test_tpex_parser_accepts_wrapped_data_and_market_identity() -> None:
    rows, excluded, _ = parse_official_quotes(
        {
            "data": [
                {"SecuritiesCompanyCode": "6488", "CompanyName": "GlobalWafers", "Close": "95.5"}
            ]
        },
        market="TPEX",
    )
    assert excluded == 0
    assert rows[0].identity == "TPEX:6488"
    with pytest.raises(ValueError):
        parse_official_quotes([], market="US")


def test_tpex_real_shape_fields_and_universe_excludes_warrant() -> None:
    quote_payload = [
        {
            "Date": "1150805",
            "SecuritiesCompanyCode": "6488",
            "CompanyName": "GlobalWafers",
            "Close": "95.5",
            "Change": "+1.5",
            "TradingShares": "1,200",
            "TransactionAmount": "114,600",
        },
        {
            "Date": "1150805",
            "SecuritiesCompanyCode": "030001",
            "CompanyName": "6488C牛",
            "Close": "0.5",
            "Change": "0.1",
            "TradingShares": "100",
            "TransactionAmount": "50",
        },
        {
            "Date": "1150805",
            "SecuritiesCompanyCode": "2330",
            "CompanyName": "missing close",
            "Close": "--",
            "Change": "--",
        },
        {
            "Date": "1150805",
            "SecuritiesCompanyCode": "bad",
            "CompanyName": "invalid",
            "Close": "NaN",
        },
    ]
    universe = parse_official_universe(
        [{"SecuritiesCompanyCode": "6488", "CompanyName": "GlobalWafers"}],
        market="TPEX",
    )
    rows, excluded, warnings = parse_tpex_quotes(
        quote_payload,
        data_date="2026-08-05",
        universe_codes=universe.codes,
        universe_available=universe.available,
    )
    assert [row.identity for row in rows] == ["TPEX:6488"]
    assert rows[0].volume == 1200
    assert rows[0].value == 114600
    assert excluded == 3
    assert any("non-stock product" in warning for warning in warnings)


def test_universe_unavailable_fails_closed_instead_of_defaulting_all_products() -> None:
    rows, excluded, warnings = parse_official_quotes(
        [{"Code": "2330", "ClosingPrice": "100"}, {"Code": "006201", "ClosingPrice": "10"}],
        market="TWSE",
        universe_available=False,
    )
    assert rows == ()
    assert excluded == 2
    assert any("universe unavailable" in warning for warning in warnings)


def test_universe_rules_exclude_explicit_etf_even_when_code_is_four_digits() -> None:
    universe = parse_official_universe(
        [
            {"Code": "2330", "CompanyName": "TSMC", "ProductType": "common stock"},
            {"Code": "0050", "CompanyName": "Taiwan 50", "ProductType": "ETF"},
            {"Code": "030001", "CompanyName": "warrant", "ProductType": "warrant"},
        ],
        market="TWSE",
    )
    assert universe.codes == ("2330",)
    assert universe.excluded_non_stock == 2


def test_each_market_recomputes_independent_contiguous_rankings() -> None:
    twse = _payload(
        "TWSE",
        [
            {
                "Code": "2330",
                "ClosingPrice": "100",
                "PriceChange": "5",
                "TradeVolume": "20",
                "TradeValue": "200",
            },
            {
                "Code": "1101",
                "ClosingPrice": "50",
                "PriceChange": "2",
                "TradeVolume": "10",
                "TradeValue": "100",
            },
        ],
    )
    twse = replace(twse, universe_codes=("1101", "2330"), universe_available=True)
    tpex = _payload(
        "TPEX",
        [
            {
                "Code": "6488",
                "ClosingPrice": "100",
                "PriceChange": "10",
                "TradeVolume": "30",
                "TradeValue": "300",
            },
            {
                "Code": "3105",
                "ClosingPrice": "50",
                "PriceChange": "1",
                "TradeVolume": "5",
                "TradeValue": "50",
            },
        ],
    )
    tpex = replace(tpex, universe_codes=("3105", "6488"), universe_available=True)
    snapshot = build_snapshot([twse, tpex])
    for market in ("TWSE", "TPEX"):
        rows = [row for row in snapshot.quotes if row.market == market]
        rankings = build_rankings(rows)
        for category in ("gainers", "losers", "volume", "value"):
            ranks = [entry.rank for entry in rankings if entry.category == category]
            assert ranks == list(range(1, len(ranks) + 1))


def test_source_dates_are_preserved_and_mismatch_is_explicit() -> None:
    twse = replace(
        _payload("TWSE", [{"Code": "2330", "ClosingPrice": "100"}], "2026-08-05"),
        universe_codes=("2330",),
        universe_available=True,
    )
    tpex = replace(
        _payload("TPEX", [{"Code": "6488", "ClosingPrice": "100"}], "2026-08-04"),
        universe_codes=("6488",),
        universe_available=True,
    )
    snapshot = build_snapshot([twse, tpex])
    assert snapshot.metadata.data_date is None
    assert [(item.market, item.data_date) for item in snapshot.source_metadata] == [
        ("TWSE", "2026-08-05"),
        ("TPEX", "2026-08-04"),
    ]
    assert any("source data dates differ" in warning for warning in snapshot.warnings)


def test_tpex_without_official_breadth_is_explicitly_derived_only() -> None:
    payload = replace(
        _payload("TPEX", [{"Code": "6488", "ClosingPrice": "100"}]),
        universe_codes=("6488",),
        universe_available=True,
    )
    snapshot = build_snapshot([payload])
    assert snapshot.source_metadata[0].breadth_status == "derived_only"
    assert any("derived only" in warning for warning in snapshot.warnings)


def test_schema_one_cache_is_rejected_after_universe_schema_bump(tmp_path: Path) -> None:
    cache = MarketSnapshotCache(tmp_path / "cache.json")
    cache.path.write_text(
        json.dumps({"schema_version": 1, "snapshot": {}, "content_sha256": "x"}),
        encoding="utf-8",
    )
    result = cache.load()
    assert result.status == "corrupt"


def test_breadth_and_rankings_are_deterministic() -> None:
    rows = (
        MarketQuoteRow("2", "TWSE", close=10, change=1, change_pct=2, volume=10, value=100),
        MarketQuoteRow("1", "TWSE", close=10, change=1, change_pct=2, volume=10, value=100),
        MarketQuoteRow("3", "TWSE", close=10, change=-1, change_pct=-1, volume=30, value=50),
        MarketQuoteRow("4", "TWSE", close=None, change=None),
    )
    breadth = compute_breadth(rows)
    assert (breadth.up, breadth.down, breadth.flat, breadth.unknown, breadth.valid_total) == (
        2,
        1,
        0,
        1,
        3,
    )
    gainers = [row.symbol for row in build_rankings(rows) if row.category == "gainers"]
    assert gainers[:2] == ["1", "2"]


def test_industry_heat_discloses_unclassified_subset() -> None:
    rows = (
        MarketQuoteRow("2330", "TWSE", change_pct=1),
        MarketQuoteRow("6488", "TPEX", change_pct=-1),
    )
    heat = build_industry_heat(rows, {("TWSE", "2330"): "半導體"})
    assert [item.industry for item in heat] == ["半導體", "未分類"]
    assert heat[0].coverage == 1
    assert heat[1].valid_samples == 1


def test_official_summary_mismatch_is_warning() -> None:
    warnings = compare_official_breadth(
        compute_breadth([MarketQuoteRow("1", "TWSE", change=1)]), {"up": 9}
    )
    assert warnings and "mismatch" in warnings[0]


def test_official_summary_is_retained_alongside_derived_breadth() -> None:
    base = _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])
    payload = OfficialPayload(
        market=base.market,
        payload=base.payload,
        endpoint=base.endpoint,
        payload_sha256=base.payload_sha256,
        data_date=base.data_date,
        official_breadth={"up": 9, "down": 0, "flat": 0},
    )
    snapshot = build_snapshot([payload])
    assert snapshot.official_breadth == ({"up": 9, "down": 0, "flat": 0},)
    assert snapshot.source_metadata[0].breadth_status == "derived_only"
    assert not any("mismatch" in warning for warning in snapshot.warnings)
    assert snapshot.from_dict(snapshot.to_dict()).official_breadth == snapshot.official_breadth


def test_official_breadth_compared_only_when_dates_match() -> None:
    base = _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])
    payload = replace(
        base,
        official_breadth={
            "up": 9,
            "down": 0,
            "flat": 0,
            "data_date": base.data_date,
            "source": "twse",
        },
    )
    snapshot = build_snapshot([payload])
    assert snapshot.source_metadata[0].breadth_status == "compared"
    assert any("mismatch" in warning for warning in snapshot.warnings)


def test_stale_official_breadth_keeps_provenance_without_comparison() -> None:
    base = _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])
    payload = replace(
        base,
        official_breadth={
            "up": 9,
            "down": 0,
            "flat": 0,
            "data_date": "2026-08-04",
            "source": "twse-breadth",
            "payload_sha256": "breadth-hash",
        },
    )
    snapshot = build_snapshot([payload])
    source = snapshot.source_metadata[0]
    assert source.breadth_status == "official_stale"
    assert source.official_breadth_date == "2026-08-04"
    assert snapshot.official_breadth[0]["payload_sha256"] == "breadth-hash"
    assert not any("mismatch" in warning for warning in snapshot.warnings)


def test_missing_official_breadth_date_is_not_compared() -> None:
    base = _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])
    payload = replace(base, official_breadth={"up": 9, "down": 0, "flat": 0})
    snapshot = build_snapshot([payload])
    assert snapshot.source_metadata[0].breadth_status == "derived_only"
    assert not any("mismatch" in warning for warning in snapshot.warnings)


def test_snapshot_cache_atomic_round_trip_and_corruption_rejection(tmp_path: Path) -> None:
    snapshot = build_snapshot(
        [_payload("TWSE", [{"Code": "2330", "ClosingPrice": "100", "PriceChange": "1"}])],
        fetched_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )
    cache = MarketSnapshotCache(tmp_path / "cache" / "market.json")
    cache.save(snapshot)
    loaded = cache.load(now=datetime(2026, 8, 5, 1, tzinfo=timezone.utc))
    assert loaded.status == "fresh"
    assert loaded.snapshot is not None
    assert loaded.snapshot.quotes[0].identity == "TWSE:2330"
    payload = json.loads(cache.path.read_text(encoding="utf-8"))
    payload["snapshot"]["quotes"][0]["symbol"] = "6488"
    cache.path.write_text(json.dumps(payload), encoding="utf-8")
    assert cache.load().status == "corrupt"


def test_cache_stale_fallback_is_explicit(tmp_path: Path) -> None:
    snapshot = build_snapshot(
        [_payload("TPEX", [{"Code": "6488", "ClosingPrice": "100", "PriceChange": "0"}])],
        fetched_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    cache = MarketSnapshotCache(tmp_path / "cache.json", max_age=timedelta(days=2))
    cache.save(snapshot)
    result = cache.load(now=datetime(2026, 8, 5, tzinfo=timezone.utc))
    assert result.status == "stale"
    assert result.snapshot is not None
    assert result.snapshot.metadata.freshness == "stale"


def test_service_refresh_saves_only_complete_official_snapshot(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(market: str) -> OfficialPayload:
        calls.append(market)
        return _payload(
            market, [{"Code": "2330" if market == "TWSE" else "6488", "ClosingPrice": "10"}]
        )

    service = MarketMonitorApplicationService(tmp_path / "snapshot.json", fetcher=fetch)
    result = service.refresh()
    assert result.status == "fresh"
    assert calls == ["TWSE", "TPEX"]
    assert service.cache.path.is_file()


def test_evidence_fixture_mode_replays_both_official_markets_through_parser(
    tmp_path: Path, monkeypatch
) -> None:
    fixture_dir = tmp_path / "fixtures"
    data_root = tmp_path / "isolated-runtime"
    fixture_dir.mkdir()
    data_root.mkdir()
    for market, code in (("TWSE", "2330"), ("TPEX", "6488")):
        (fixture_dir / f"{market}.json").write_text(
            json.dumps(
                {
                    "data_date": "2026-08-23",
                    "universe_codes": [code],
                    "official_breadth": {
                        "data_date": "2026-08-23",
                        "up": 1,
                        "down": 0,
                        "flat": 0,
                        "source": "evidence-fixture",
                    },
                    "payload": [
                        {
                            "Code": code,
                            "Name": "fixture company",
                            "ClosingPrice": "100",
                            "PriceChange": "1",
                            "TradeVolume": "1000",
                            "TradeValue": "100000",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
    monkeypatch.setenv("STOCK_TOOL_EVIDENCE_MODE", "sprint32.1.1")
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(data_root))
    monkeypatch.setenv("STOCK_TOOL_EVIDENCE_FIXTURE_DIR", str(fixture_dir))

    service = MarketMonitorApplicationService(tmp_path / "snapshot.json")
    assert isinstance(service.fetcher, EvidenceFixtureMarketFetcher)
    result = service.refresh()

    assert result.status == "fresh"
    assert result.snapshot is not None
    assert result.snapshot.metadata.status == "ready"
    assert {row.identity for row in result.snapshot.quotes} == {"TWSE:2330", "TPEX:6488"}
    assert {item.data_date for item in result.snapshot.source_metadata} == {"2026-08-23"}
    assert {item.breadth_status for item in result.snapshot.source_metadata} == {"compared"}
    assert result.warnings == ()


def test_evidence_fixture_mode_rejects_non_temp_data_root(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    monkeypatch.setenv("STOCK_TOOL_EVIDENCE_MODE", "sprint32.1.1")
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(Path.cwd()))
    monkeypatch.setenv("STOCK_TOOL_EVIDENCE_FIXTURE_DIR", str(fixture_dir))

    with pytest.raises(ValueError, match="system temp"):
        MarketMonitorApplicationService(tmp_path / "snapshot.json")


def test_service_partial_failure_is_honest_and_does_not_overwrite_cache(tmp_path: Path) -> None:
    def fetch(market: str) -> OfficialPayload:
        if market == "TPEX":
            raise OSError("blocked")
        return _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10"}])

    service = MarketMonitorApplicationService(tmp_path / "snapshot.json", fetcher=fetch)
    result = service.refresh()
    assert result.status == "partial"
    assert result.snapshot is not None
    assert "TPEX official source unavailable" in result.warnings
    assert not service.cache.path.exists()


def test_service_offline_failure_without_cache_is_unavailable(tmp_path: Path) -> None:
    service = MarketMonitorApplicationService(
        tmp_path / "snapshot.json", fetcher=lambda _market: (_ for _ in ()).throw(OSError())
    )
    result = service.refresh()
    assert result.status == "unavailable"
    assert result.snapshot is None


def test_render_path_can_read_cache_without_fetching(tmp_path: Path) -> None:
    calls: list[str] = []
    snapshot = build_snapshot(
        [_payload("TWSE", [{"Code": "2330", "ClosingPrice": "10"}])],
        fetched_at=datetime.now(timezone.utc),
    )

    def fetch(market: str) -> OfficialPayload:
        calls.append(market)
        return _payload(market, [])

    service = MarketMonitorApplicationService(tmp_path / "snapshot.json", fetcher=fetch)
    service.cache.save(snapshot)
    result = service.load_cached()
    assert result.snapshot is not None
    assert calls == []


class _RenderFake:
    def __init__(self, service: MarketMonitorApplicationService) -> None:
        self.session_state: dict[str, object] = {}
        self.service = service
        self.messages: list[str] = []

    def subheader(self, value: str) -> None:
        self.messages.append(value)

    def caption(self, value: str) -> None:
        self.messages.append(value)

    def button(self, *_args, **_kwargs) -> bool:
        return False

    def selectbox(self, _label: str, *, options, format_func, key: str) -> str:
        del format_func, key
        return options[0]

    def write(self, value: str) -> None:
        self.messages.append(value)

    def warning(self, value: str) -> None:
        self.messages.append(value)

    def info(self, value: str) -> None:
        self.messages.append(value)

    def markdown(self, value: str) -> None:
        self.messages.append(value)

    def columns(self, _spec):
        return (nullcontext(), nullcontext())

    def error(self, value: str) -> None:
        self.messages.append(value)

    def expander(self, _label: str):
        return nullcontext()


def test_render_stale_breadth_uses_traditional_chinese_warning(tmp_path: Path) -> None:
    base = _payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])
    snapshot = build_snapshot(
        [replace(base, official_breadth={"up": 9, "down": 0, "flat": 0, "data_date": "2026-08-04"})]
    )
    cache = MarketSnapshotCache(tmp_path / "snapshot.json")
    cache.save(snapshot)
    service = MarketMonitorApplicationService(cache.path, fetcher=lambda _market: pytest.fail())
    fake = _RenderFake(service)
    _render_market_overview(fake, service, on_research=lambda _symbol: None)
    assert any("官方廣度日期過期，目前僅為自行推導" in message for message in fake.messages)
    assert not any("已與官方數字比對" in message for message in fake.messages)


def test_render_market_overview_never_refreshes_without_explicit_button(tmp_path: Path) -> None:
    snapshot = build_snapshot(
        [_payload("TWSE", [{"Code": "2330", "ClosingPrice": "10", "PriceChange": "1"}])],
        fetched_at=datetime.now(timezone.utc),
    )
    cache = MarketSnapshotCache(tmp_path / "snapshot.json")
    cache.save(snapshot)
    service = MarketMonitorApplicationService(
        cache.path,
        fetcher=lambda _market: pytest.fail("render must not call provider"),
    )
    fake = _RenderFake(service)
    _render_market_overview(fake, service, on_research=lambda _symbol: None)
    assert any("市場總覽" in message for message in fake.messages)
