"""Fundamental data loading and scoring."""

from stock_tool.fundamentals.loader import (
    FUNDAMENTAL_COLUMNS,
    FundamentalDataError,
    load_fundamentals_csv,
)
from stock_tool.fundamentals.auto_fetch import (
    FundamentalFetchError,
    FundamentalFetchResult,
    fetch_yfinance_fundamentals,
)
from stock_tool.fundamentals.scoring import (
    IndustryScoringProfile,
    MetricRule,
    score_fundamentals,
)
from stock_tool.fundamentals.models import (
    FundamentalAvailabilityResult,
    FundamentalPointInTimeMode,
    prepare_fundamental_strategy_frame,
    visible_fundamentals_as_of,
)

__all__ = [
    "FUNDAMENTAL_COLUMNS",
    "FundamentalDataError",
    "FundamentalFetchError",
    "FundamentalFetchResult",
    "IndustryScoringProfile",
    "MetricRule",
    "fetch_yfinance_fundamentals",
    "load_fundamentals_csv",
    "score_fundamentals",
    "FundamentalAvailabilityResult",
    "FundamentalPointInTimeMode",
    "prepare_fundamental_strategy_frame",
    "visible_fundamentals_as_of",
]
