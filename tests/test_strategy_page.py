from __future__ import annotations

import pandas as pd

from stock_tool.backtest import BacktestEngine
from stock_tool.dashboard.pages.strategy import build_strategy_health_preflight
from stock_tool.dashboard.pages.strategy import render_strategy_health
from stock_tool.strategies.registry import create_strategy, get_strategy_definition


class _FakeSt:
    def __init__(self, *, run_health: bool) -> None:
        self.run_health = run_health
        self.session_state: dict[str, object] = {}
        self.events: list[tuple[str, str]] = []

    def __enter__(self) -> _FakeSt:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def divider(self) -> None:
        self.events.append(("divider", ""))

    def subheader(self, text: str) -> None:
        self.events.append(("subheader", text))

    def caption(self, text: str) -> None:
        self.events.append(("caption", text))

    def markdown(self, text: str) -> None:
        self.events.append(("markdown", text))

    def write(self, text: str) -> None:
        self.events.append(("write", text))

    def info(self, text: str) -> None:
        self.events.append(("info", text))

    def warning(self, text: str) -> None:
        self.events.append(("warning", text))

    def expander(self, _label: str, **_kwargs: object) -> _FakeSt:
        return self

    def button(self, _label: str, **_kwargs: object) -> bool:
        return self.run_health

    def spinner(self, _text: str) -> _FakeSt:
        return self

    def dataframe(self, _frame: pd.DataFrame, **_kwargs: object) -> None:
        self.events.append(("dataframe", ""))


def _render_prices(rows: int = 90) -> pd.DataFrame:
    closes = [100.0 + ((index % 9) - 4) * 2.0 + index * 0.15 for index in range(rows)]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "symbol": "2330",
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000.0] * rows,
        }
    )


def test_strategy_health_preflight_reports_period_and_bounded_defaults() -> None:
    dates = pd.date_range("2024-01-01", periods=120, freq="D")
    preflight = build_strategy_health_preflight(
        price_data=pd.DataFrame({"date": dates, "symbol": "2330", "open": 1.0, "close": 1.0}),
        definition=get_strategy_definition("ma_cross"),
    )

    assert preflight.can_run
    assert preflight.train_period is not None
    assert preflight.test_period is not None
    assert preflight.walk_forward is not None
    assert preflight.train_period.end < preflight.test_period.start
    assert preflight.expected_sensitivity_combinations <= 25
    assert preflight.walk_forward.max_folds <= 10


def test_strategy_health_preflight_declares_insufficient_data_without_creating_a_result() -> None:
    preflight = build_strategy_health_preflight(
        price_data=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4),
                "symbol": "2330",
                "open": 1.0,
                "close": 1.0,
            }
        ),
        definition=get_strategy_definition("ma_cross"),
    )

    assert not preflight.can_run
    assert "資料不足" in preflight.message


def test_strategy_health_page_renders_existing_single_backtest_adjacent_health_sections() -> None:
    st = _FakeSt(run_health=True)
    prices = _render_prices()

    render_strategy_health(
        st,
        strategy=create_strategy("breakout", {"lookback": 3, "quantity": 1}),
        price_data=prices,
        fundamentals=None,
        engine_factory=lambda: BacktestEngine(initial_cash=10_000.0),
    )

    assert "strategy_validation_result" in st.session_state
    assert ("subheader", "策略健檢") in st.events
    assert sum(kind == "dataframe" for kind, _message in st.events) == 3
    assert any("不推薦任何策略" in message for _kind, message in st.events)
