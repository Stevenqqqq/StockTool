"""Example usage for technical indicator functions."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_tool.indicators import (
    add_atr,
    add_bias,
    add_bollinger_bands,
    add_ema,
    add_macd,
    add_rolling_return,
    add_rolling_volatility,
    add_rsi,
    add_sma,
    add_stochastic_oscillator,
    add_volume_moving_average,
)


def build_indicator_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Build a DataFrame with the first-stage technical indicators."""

    indicators = add_sma(prices)
    indicators = add_ema(indicators)
    indicators = add_rsi(indicators)
    indicators = add_macd(indicators)
    indicators = add_bollinger_bands(indicators)
    indicators = add_atr(indicators)
    indicators = add_stochastic_oscillator(indicators)
    indicators = add_volume_moving_average(indicators, periods=(5, 20))
    indicators = add_bias(indicators)
    indicators = add_rolling_return(indicators, periods=(5, 20))
    indicators = add_rolling_volatility(indicators, periods=(5, 20), annualize=False)
    return indicators


if __name__ == "__main__":
    source = "data/sample/sample_tw_prices.csv"
    prices_df = pd.read_csv(source, dtype={"symbol": str})
    output_df = build_indicator_frame(prices_df)
    print(output_df.tail())
