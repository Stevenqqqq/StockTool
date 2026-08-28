"""Generate sample Excel and HTML stock research reports."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.reports import ReportData, generate_excel_report, generate_html_report
from stock_tool.risk import RiskConfig, RiskManager
from stock_tool.strategies import MACDTrendStrategy


def build_sample_report_data() -> ReportData:
    """Build a complete report input from local sample data."""

    prices = pd.read_csv(
        PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv",
        dtype={"symbol": str},
    )
    indicators = pd.read_csv(
        PROJECT_ROOT / "data" / "sample" / "sample_tw_indicators.csv",
        dtype={"symbol": str},
    )
    fundamental_scores = pd.read_csv(
        PROJECT_ROOT / "data" / "sample" / "sample_fundamental_scores.csv",
        dtype={"symbol": str},
    )

    strategy = MACDTrendStrategy(target_percent=0.5)
    signals = strategy.generate_signals(prices)
    engine = BacktestEngine(
        initial_cash=1_000_000,
        broker_config=BrokerConfig(
            commission_rate=0.001425,
            tax_rate=0.003,
            slippage_rate=0.001,
            execution_price_col="open",
        ),
        max_position_pct=0.5,
    )
    benchmark = prices[["date", "close"]].copy()
    result = engine.run(prices, signals, benchmark=benchmark)

    risk_manager = RiskManager(RiskConfig(max_drawdown_pct=0.005, max_volatility=0.08))
    returns = result.equity_curve["total_equity"].pct_change().dropna()
    risk_alerts = risk_manager.check_portfolio_alerts(
        equity_curve=result.equity_curve,
        returns=returns,
        trades=result.trades,
        portfolio=result.portfolio,
    )

    return ReportData(
        symbol="2330",
        price_data=prices,
        technical_indicators=indicators,
        fundamental_scores=fundamental_scores,
        backtest_result=result,
        risk_alerts=risk_alerts,
        parameters={
            "strategy": strategy.name,
            "strategy_parameters": strategy.parameters,
            "initial_cash": 1_000_000,
            "commission_rate": 0.001425,
            "tax_rate": 0.003,
            "slippage_rate": 0.001,
            "execution_price_col": "open",
        },
    )


def generate_sample_reports() -> tuple[Path, Path]:
    """Generate sample Excel and HTML reports under the reports directory."""

    report_data = build_sample_report_data()
    output_dir = PROJECT_ROOT / "reports"
    excel_path = generate_excel_report(report_data, output_dir / "sample_stock_report.xlsx")
    html_path = generate_html_report(report_data, output_dir / "sample_stock_report.html")
    return excel_path, html_path


if __name__ == "__main__":
    excel, html_report = generate_sample_reports()
    print(excel)
    print(html_report)
