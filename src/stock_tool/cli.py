"""Command line interface for local stock research workflows."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.data.cleaner import PriceDataWarning, clean_price_data
from stock_tool.data.providers import provider_for_file
from stock_tool.data.storage import SQLitePriceStorage
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
from stock_tool.reports import ReportData, generate_excel_report
from stock_tool.strategies import (
    BreakoutStrategy,
    MACDTrendStrategy,
    MACrossStrategy,
    RSIReversalStrategy,
    StrategyBase,
    VolumePriceBreakoutStrategy,
)

DEFAULT_PRICE_FILE = Path("data/sample/sample_tw_prices_for_indicators.csv")
DEFAULT_DATABASE = Path("data/processed/stock_data.sqlite")
DISCLAIMER = "本工具僅供研究、學習與風險分析；歷史績效不代表未來報酬，且不構成個人化投資建議。"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stock-tool CLI and return a process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock-tool",
        description="Research-focused stock analysis and backtesting CLI.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show package version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command")

    import_parser = subparsers.add_parser("import-data", help="Import CSV or Excel OHLCV data.")
    import_parser.add_argument("--file", required=True, help="CSV or Excel file path.")
    import_parser.add_argument(
        "--database",
        default=str(DEFAULT_DATABASE),
        help="SQLite database path.",
    )
    import_parser.set_defaults(func=_run_import_data)

    analyze_parser = subparsers.add_parser("analyze", help="Calculate technical indicators.")
    analyze_parser.add_argument("--symbol", required=True, help="Stock symbol to analyze.")
    analyze_parser.add_argument("--file", default=str(DEFAULT_PRICE_FILE), help="Price CSV or Excel file.")
    analyze_parser.set_defaults(func=_run_analyze)

    backtest_parser = subparsers.add_parser("backtest", help="Run a sample research backtest.")
    backtest_parser.add_argument("--symbol", required=True, help="Stock symbol to backtest.")
    backtest_parser.add_argument("--file", default=str(DEFAULT_PRICE_FILE), help="Price CSV or Excel file.")
    backtest_parser.add_argument(
        "--strategy",
        default="ma_cross",
        choices=("ma_cross", "breakout", "rsi_reversal", "macd_trend", "volume_price_breakout"),
        help="Strategy name.",
    )
    backtest_parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    backtest_parser.add_argument("--commission-rate", type=float, default=0.001425)
    backtest_parser.add_argument("--tax-rate", type=float, default=0.003)
    backtest_parser.add_argument("--slippage-rate", type=float, default=0.001)
    backtest_parser.add_argument("--max-position-pct", type=float, default=0.5)
    backtest_parser.add_argument("--target-percent", type=float, default=0.5)
    backtest_parser.add_argument("--short-window", type=int, default=20)
    backtest_parser.add_argument("--long-window", type=int, default=60)
    backtest_parser.add_argument("--lookback", type=int, default=20)
    backtest_parser.add_argument(
        "--trailing-stop-pct",
        type=float,
        default=None,
        help="Optional conservative daily trailing stop percentage, e.g. 0.1 for 10%%.",
    )
    backtest_parser.set_defaults(func=_run_backtest)

    report_parser = subparsers.add_parser("report", help="Generate an Excel research report.")
    report_parser.add_argument("--symbol", required=True, help="Stock symbol to report.")
    report_parser.add_argument("--file", default=str(DEFAULT_PRICE_FILE), help="Price CSV or Excel file.")
    report_parser.add_argument("--output", required=True, help="Output .xlsx path.")
    report_parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    report_parser.add_argument("--commission-rate", type=float, default=0.001425)
    report_parser.add_argument("--tax-rate", type=float, default=0.003)
    report_parser.add_argument("--slippage-rate", type=float, default=0.001)
    report_parser.add_argument(
        "--trailing-stop-pct",
        type=float,
        default=None,
        help="Optional conservative daily trailing stop percentage, e.g. 0.1 for 10%%.",
    )
    report_parser.set_defaults(func=_run_report)

    parser.set_defaults(func=_run_default)
    return parser


def _run_default(args: argparse.Namespace) -> int:
    if args.version:
        from stock_tool import __version__

        print(__version__)
        return 0
    _build_parser().print_help()
    return 0


def _run_import_data(args: argparse.Namespace) -> int:
    rows, warning_messages = _load_and_clean_records(Path(args.file))
    storage = SQLitePriceStorage(args.database)
    saved_count = storage.save_price_data(rows)
    print(DISCLAIMER)
    print(f"saved_rows={saved_count}")
    print(f"database={storage.database_path}")
    _print_warnings(warning_messages)
    return 0


def _run_analyze(args: argparse.Namespace) -> int:
    prices = _load_clean_price_frame(Path(args.file))
    stock_prices = _filter_symbol(prices, args.symbol)
    if stock_prices.empty:
        raise ValueError(f"找不到股票代號 {args.symbol} 的股價資料。")

    indicators = _add_all_indicators(stock_prices)
    latest = indicators.sort_values("date").tail(1).iloc[0]
    print(DISCLAIMER)
    print(f"symbol={args.symbol}")
    print(f"date={latest.get('date')}")
    for column in ("close", "sma_20", "sma_60", "rsi_14", "macd_dif", "macd_dea"):
        if column in latest.index:
            print(f"{column}={_format_cli_value(latest[column])}")
    return 0


def _run_backtest(args: argparse.Namespace) -> int:
    prices = _load_clean_price_frame(Path(args.file))
    stock_prices = _filter_symbol(prices, args.symbol)
    if stock_prices.empty:
        raise ValueError(f"找不到股票代號 {args.symbol} 的股價資料。")

    strategy = _strategy_from_args(args)
    result = _run_strategy_backtest(stock_prices, strategy, args)
    metrics = result.metrics
    print(DISCLAIMER)
    print(f"symbol={args.symbol}")
    print(f"strategy={strategy.name}")
    print(f"total_return={metrics.total_return:.6f}")
    print(f"cagr={metrics.cagr:.6f}")
    print(f"max_drawdown={metrics.max_drawdown:.6f}")
    print(f"trades={metrics.number_of_trades}")
    print(f"benchmark_total_return={_format_cli_value(metrics.benchmark_total_return)}")
    print(f"benchmark_excess_return={_format_cli_value(metrics.benchmark_excess_return)}")
    return 0


def _run_report(args: argparse.Namespace) -> int:
    prices = _load_clean_price_frame(Path(args.file))
    stock_prices = _filter_symbol(prices, args.symbol)
    if stock_prices.empty:
        raise ValueError(f"找不到股票代號 {args.symbol} 的股價資料。")

    indicators = _add_all_indicators(stock_prices)
    strategy = MACDTrendStrategy(target_percent=0.5)
    result = _run_strategy_backtest(stock_prices, strategy, args)
    report_data = ReportData(
        symbol=str(args.symbol),
        price_data=stock_prices,
        technical_indicators=indicators,
        backtest_result=result,
        parameters={
            "strategy": strategy.name,
            "strategy_parameters": strategy.parameters,
            "initial_cash": args.initial_cash,
            "commission_rate": args.commission_rate,
            "tax_rate": args.tax_rate,
            "slippage_rate": args.slippage_rate,
            "execution_price_col": "open",
            "trailing_stop_pct": args.trailing_stop_pct,
        },
    )
    output_path = generate_excel_report(report_data, args.output)
    print(DISCLAIMER)
    print(f"report={output_path}")
    return 0


def _load_and_clean_records(file_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    raw_rows = _load_raw_rows(file_path)
    warning_messages: list[str] = []
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", PriceDataWarning)
        cleaned = clean_price_data(raw_rows)
    warning_messages.extend(str(item.message) for item in captured)
    return cleaned.records, warning_messages


def _load_clean_price_frame(file_path: Path) -> pd.DataFrame:
    rows, warning_messages = _load_and_clean_records(file_path)
    _print_warnings(warning_messages)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("資料清洗後沒有可用股價資料。")
    return frame


def _load_raw_rows(file_path: Path) -> list[dict[str, Any]]:
    provider = provider_for_file(file_path)
    return provider.load_price_data()


def _add_all_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    indicators = add_sma(prices)
    indicators = add_ema(indicators)
    indicators = add_rsi(indicators)
    indicators = add_macd(indicators)
    indicators = add_bollinger_bands(indicators)
    indicators = add_atr(indicators)
    indicators = add_stochastic_oscillator(indicators)
    indicators = add_volume_moving_average(indicators, periods=(5, 20))
    indicators = add_bias(indicators)
    indicators = add_rolling_return(indicators, periods=(5, 20, 60))
    indicators = add_rolling_volatility(indicators, periods=(5, 20, 60), annualize=False)
    return indicators


def _strategy_from_args(args: argparse.Namespace) -> StrategyBase:
    target_percent = float(args.target_percent)
    if args.strategy == "ma_cross":
        return MACrossStrategy(
            short_window=int(args.short_window),
            long_window=int(args.long_window),
            target_percent=target_percent,
        )
    if args.strategy == "breakout":
        return BreakoutStrategy(lookback=int(args.lookback), target_percent=target_percent)
    if args.strategy == "rsi_reversal":
        return RSIReversalStrategy(target_percent=target_percent)
    if args.strategy == "macd_trend":
        return MACDTrendStrategy(target_percent=target_percent)
    if args.strategy == "volume_price_breakout":
        return VolumePriceBreakoutStrategy(
            lookback=int(args.lookback),
            volume_window=int(args.lookback),
            target_percent=target_percent,
        )
    raise ValueError(f"不支援的策略：{args.strategy}")


def _run_strategy_backtest(
    prices: pd.DataFrame,
    strategy: StrategyBase,
    args: argparse.Namespace,
) -> Any:
    signals = strategy.generate_signals(prices)
    engine = BacktestEngine(
        initial_cash=float(args.initial_cash),
        broker_config=BrokerConfig(
            commission_rate=float(args.commission_rate),
            tax_rate=float(args.tax_rate),
            slippage_rate=float(args.slippage_rate),
            execution_price_col="open",
        ),
        max_position_pct=float(getattr(args, "max_position_pct", 0.5)),
        trailing_stop_pct=getattr(args, "trailing_stop_pct", None),
    )
    benchmark = prices.loc[:, ["date", "close"]].copy()
    return engine.run(prices, signals, benchmark=benchmark)


def _filter_symbol(prices: pd.DataFrame, symbol: str) -> pd.DataFrame:
    return prices.loc[prices["symbol"].astype(str) == str(symbol)].copy(deep=True)


def _print_warnings(messages: Sequence[str]) -> None:
    for message in messages:
        print(f"警告：{message}", file=sys.stderr)


def _format_cli_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return "資料不足"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
