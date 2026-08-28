from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import stock_tool.dashboard.app as dashboard_app
from stock_tool.application.daily_brief import DailyBriefService
from stock_tool.dashboard.home_data import load_home_summary
from stock_tool.data.storage import SQLitePriceStorage


class _FakeSessionState(dict[str, object]):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = _FakeSessionState()


def _app_path() -> Path:
    return Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"


def _market_qualified_prices() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, market, provider_symbol, close in (
        ("2330", "TWSE", "2330.TW", 600.0),
        ("6488", "TPEX", "6488.TWO", 700.0),
        ("AAPL", "US", "AAPL", 190.0),
    ):
        for offset, date in enumerate(("2024-01-02", "2024-01-03")):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "market": market,
                    "open": close - 1 + offset,
                    "high": close + 2 + offset,
                    "low": close - 2 + offset,
                    "close": close + offset,
                    "volume": 1_000 + offset,
                    "adjusted_close": close + offset,
                    "provider": "fixture",
                    "provider_symbol": provider_symbol,
                    "source_type": "cache",
                    "last_data_date": "2024-01-03",
                    "checked_at": "2024-01-12T08:00:00+00:00",
                }
            )
    return pd.DataFrame(rows)


def test_daily_home_reloads_market_qualified_prices_after_new_session(
    tmp_path, monkeypatch
) -> None:
    """A fresh session must retain persisted TWSE, TPEX, and US price identities."""

    runtime = tmp_path / "isolated-runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    portfolio_path = data_dir / "portfolio.csv"
    pd.DataFrame(
        {
            "symbol": ["2330", "6488", "AAPL"],
            "market": ["TWSE", "TPEX", "US"],
            "quantity": [1.0, 1.0, 1.0],
            "average_cost": [500.0, 650.0, 180.0],
            "currency": ["TWD", "TWD", "USD"],
            "note": ["", "", ""],
        }
    ).to_csv(portfolio_path, index=False, encoding="utf-8")
    database = data_dir / "stock_data.sqlite"
    persisted = _market_qualified_prices()

    dashboard_app._persist_price_data(persisted, database)

    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)
    monkeypatch.setattr(dashboard_app, "PORTFOLIO_FILE", portfolio_path)
    monkeypatch.setattr(dashboard_app, "WATCHLIST_FILE", data_dir / "watchlist.csv")
    fresh_session = _FakeStreamlit()
    dashboard_app._init_state(fresh_session)

    loaded = fresh_session.session_state.price_data
    assert isinstance(loaded, pd.DataFrame)
    assert set(zip(loaded["symbol"], loaded["market"], strict=True)) == {
        ("2330", "TWSE"),
        ("6488", "TPEX"),
        ("AAPL", "US"),
    }
    assert set(loaded["last_data_date"].dropna()) == {"2024-01-03"}
    assert set(loaded["checked_at"].dropna()) == {"2024-01-12T08:00:00+00:00"}
    assert set(loaded["provider"].dropna()) == {"fixture"}
    assert set(loaded["source_type"].dropna()) == {"cache"}

    brief = dashboard_app._build_daily_brief(fresh_session)

    assert brief.portfolio.position_count == 3
    assert brief.portfolio.priced_position_count == 3
    assert brief.portfolio.price_coverage == 1.0
    assert any(item.code == "stale_price" for item in brief.attention_items)


def test_streamlit_restart_home_shows_persisted_price_coverage(tmp_path, monkeypatch) -> None:
    """A new app process reads the isolated sidecar instead of losing market identities."""

    runtime = tmp_path / "app-runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["2330", "6488", "AAPL"],
            "market": ["TWSE", "TPEX", "US"],
            "quantity": [1.0, 1.0, 1.0],
            "average_cost": [500.0, 650.0, 180.0],
            "currency": ["TWD", "TWD", "USD"],
            "note": ["", "", ""],
        }
    ).to_csv(data_dir / "portfolio.csv", index=False, encoding="utf-8")
    processed_dir = data_dir / "processed"
    processed_dir.mkdir()
    dashboard_app._persist_price_data(
        _market_qualified_prices(), processed_dir / "stock_data.sqlite"
    )
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))

    app = AppTest.from_file(str(_app_path())).run(timeout=20)

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["持股筆數"] == "3"
    assert metrics["已有價格資料"] == "3/3"
    assert metrics["價格覆蓋率"] == "100.0%"


def test_persisted_same_ticker_in_different_markets_does_not_collide(tmp_path) -> None:
    """The sidecar must preserve both market identities even though legacy SQLite cannot."""

    database = tmp_path / "stock_data.sqlite"
    prices = pd.DataFrame(
        {
            "date": ["2024-01-03", "2024-01-03"],
            "symbol": ["TEST", "TEST"],
            "market": ["TWSE", "US"],
            "open": [100.0, 200.0],
            "high": [101.0, 201.0],
            "low": [99.0, 199.0],
            "close": [100.0, 200.0],
            "volume": [1_000.0, 2_000.0],
            "adjusted_close": [100.0, 200.0],
            "provider": ["fixture-tw", "fixture-us"],
            "provider_symbol": ["TEST.TW", "TEST"],
            "source_type": ["online", "cache"],
            "last_data_date": ["2024-01-03", "2024-01-03"],
            "checked_at": ["2024-01-04T00:00:00+00:00"] * 2,
        }
    )
    before = prices.copy(deep=True)

    dashboard_app._persist_price_data(prices, database)
    loaded = dashboard_app._load_default_database_prices(database)

    assert loaded is not None
    assert set(zip(loaded["symbol"], loaded["market"], strict=True)) == {
        ("TEST", "TWSE"),
        ("TEST", "US"),
    }
    values = {
        (row.symbol, row.market): row.close
        for row in loaded[["symbol", "market", "close"]].itertuples(index=False)
    }
    assert values == {("TEST", "TWSE"): 100.0, ("TEST", "US"): 200.0}
    pd.testing.assert_frame_equal(prices, before)


def test_corrupt_price_identity_metadata_is_not_silently_used(tmp_path) -> None:
    """Malformed sidecar metadata must leave only UNKNOWN legacy rows available."""

    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_price_data(
        [
            {
                "date": "2024-01-03",
                "symbol": "2330",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000.0,
                "adjusted_close": 100.0,
            }
        ]
    )
    SQLitePriceStorage(database).price_identity_sidecar_path.write_text(
        "{not valid json", encoding="utf-8"
    )

    loaded = dashboard_app._load_default_database_prices(database)

    assert loaded is not None
    assert loaded["market"].tolist() == ["UNKNOWN"]
    assert loaded.attrs["price_identity_warnings"]


def test_unknown_market_price_is_not_used_for_portfolio_coverage(tmp_path, monkeypatch) -> None:
    """A legacy price row cannot be silently assigned to a known portfolio market."""

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "stock_data.sqlite"
    SQLitePriceStorage(database).save_price_data(
        [
            {
                "date": "2024-01-03",
                "symbol": "2330",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000.0,
                "adjusted_close": 100.0,
            }
        ]
    )
    portfolio_path = data_dir / "portfolio.csv"
    pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "quantity": [1.0],
            "average_cost": [90.0],
            "currency": ["TWD"],
            "note": [""],
        }
    ).to_csv(portfolio_path, index=False, encoding="utf-8")
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)
    monkeypatch.setattr(dashboard_app, "PORTFOLIO_FILE", portfolio_path)
    monkeypatch.setattr(dashboard_app, "WATCHLIST_FILE", data_dir / "watchlist.csv")

    fresh_session = _FakeStreamlit()
    dashboard_app._init_state(fresh_session)
    brief = dashboard_app._build_daily_brief(fresh_session)

    assert brief.portfolio.position_count == 1
    assert brief.portfolio.priced_position_count == 0
    assert brief.portfolio.price_coverage == 0.0
    assert any(item.code == "missing_price" for item in brief.attention_items)


def test_price_without_check_metadata_states_freshness_is_unknown() -> None:
    """Known market prices without a provider check time must not claim to be current."""

    prices = pd.DataFrame(
        {
            "date": ["2024-01-03"],
            "symbol": ["2330"],
            "market": ["TWSE"],
            "close": [100.0],
            "volume": [1_000.0],
        }
    )
    portfolio = pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]})

    brief = DailyBriefService().build(
        portfolio=portfolio,
        watchlist=None,
        prices=prices,
        valuation=None,
        continuations=(),
        reference_at=None,
    )

    assert any(item.field == "price_freshness" for item in brief.action_required)
    assert not any(item.code == "stale_price" for item in brief.attention_items)


def test_home_summary_normalizes_tw_and_us_without_contradictory_warning(tmp_path) -> None:
    """Legacy TW and US market codes remain countable and do not produce a read-failure warning."""

    portfolio_path = tmp_path / "portfolio.csv"
    pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TW", "US"],
            "quantity": [1.0, 1.0],
            "average_cost": [500.0, 190.0],
            "currency": ["TWD", "USD"],
            "note": ["", ""],
        }
    ).to_csv(portfolio_path, index=False, encoding="utf-8")

    summary = load_home_summary(
        {}, portfolio_path=portfolio_path, watchlist_path=tmp_path / "x.csv"
    )

    assert summary.portfolio_count == 2
    assert not any("無法安全讀取持股檔" in warning for warning in summary.warnings)


def test_home_summary_names_the_unresolved_market_row_without_counting_it(tmp_path) -> None:
    """A truly invalid market is explicit instead of contradicting the usable holding count."""

    portfolio_path = tmp_path / "portfolio.csv"
    pd.DataFrame(
        {
            "symbol": ["2330", "BAD"],
            "market": ["TW", "NOT_A_MARKET"],
            "quantity": [1.0, 1.0],
            "average_cost": [500.0, 1.0],
            "currency": ["TWD", "USD"],
            "note": ["", ""],
        }
    ).to_csv(portfolio_path, index=False, encoding="utf-8")

    summary = load_home_summary(
        {}, portfolio_path=portfolio_path, watchlist_path=tmp_path / "x.csv"
    )

    assert summary.portfolio_count == 1
    assert (
        "持股摘要資料不足：無法解析 第 3 筆 BAD（市場代碼 NOT_A_MARKET）；未納入價格覆蓋率。"
        in summary.warnings
    )


def test_home_summary_and_daily_brief_use_the_same_resolved_portfolio_count(
    tmp_path, monkeypatch
) -> None:
    """The count shown on home and the Daily Brief cannot disagree over an invalid market row."""

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    portfolio_path = data_dir / "portfolio.csv"
    pd.DataFrame(
        {
            "symbol": ["2330", "BAD"],
            "market": ["TW", "NOT_A_MARKET"],
            "quantity": [1.0, 1.0],
            "average_cost": [500.0, 1.0],
            "currency": ["TWD", "USD"],
            "note": ["", ""],
        }
    ).to_csv(portfolio_path, index=False, encoding="utf-8")
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", data_dir / "missing.sqlite")
    monkeypatch.setattr(dashboard_app, "PORTFOLIO_FILE", portfolio_path)
    monkeypatch.setattr(dashboard_app, "WATCHLIST_FILE", data_dir / "watchlist.csv")
    fresh_session = _FakeStreamlit()
    dashboard_app._init_state(fresh_session)

    summary = load_home_summary(
        {}, portfolio_path=portfolio_path, watchlist_path=data_dir / "watchlist.csv"
    )
    brief = dashboard_app._build_daily_brief(fresh_session)

    assert summary.portfolio_count == 1
    assert brief.portfolio.position_count == 1
