"""HTML report generation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd

from stock_tool.reports.charts import drawdown_chart, equity_curve_chart, price_chart
from stock_tool.reports.excel import (
    _backtest_summary,
    _fundamental_summary,
    _risk_summary,
    _technical_summary,
)
from stock_tool.reports.models import (
    DISCLAIMER,
    INSUFFICIENT_DATA,
    ReportData,
    ReportPackage,
    data_period,
    ensure_table,
    localize_display_frame,
    unpack_report_input,
)


def generate_html_report(report_data: ReportData | ReportPackage, output_path: str | Path) -> Path:
    """Generate a self-contained HTML report and return the output path."""

    report_data = unpack_report_input(report_data)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html_text = render_html_report(report_data)
    path.write_text(html_text, encoding="utf-8")
    return path


def render_html_report(report_data: ReportData | ReportPackage) -> str:
    """Render report data into a self-contained HTML document."""

    report_data = unpack_report_input(report_data)
    equity_curve = report_data.resolved_equity_curve()
    trade_log = report_data.resolved_trade_log()
    risk_alerts = report_data.resolved_risk_alerts()
    indicators = ensure_table(report_data.technical_indicators, "技術指標")
    fundamentals = ensure_table(report_data.fundamental_scores, "基本面評分")
    backtest_metrics = report_data.resolved_backtest_metrics()
    benchmark_comparison = report_data.resolved_benchmark_comparison()
    data_sources = report_data.resolved_data_sources()
    data_quality = report_data.resolved_data_quality()
    manifest = report_data.resolved_manifest()
    corporate_action_audit = report_data.resolved_corporate_action_audit()
    daily_reconciliation = report_data.resolved_daily_reconciliation()

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(report_data.symbol)} 股票研究報表</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #111827; background: #f9fafb; }}
    header {{ background: #111827; color: #ffffff; padding: 28px 36px; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 28px 24px 44px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    .subtitle {{ color: #d1d5db; }}
    .notice {{ background: #fff7ed; border: 1px solid #fed7aa; color: #7c2d12; padding: 12px 14px; border-radius: 8px; margin: 16px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }}
    .card {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; }}
    .label {{ color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
    .value {{ margin-top: 5px; font-size: 15px; line-height: 1.5; }}
    .chart {{ width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0 16px; }}
    .chart-title {{ font-size: 15px; font-weight: 700; fill: #111827; }}
    .axis-label, .muted {{ font-size: 11px; fill: #6b7280; color: #6b7280; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 8px 10px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #f3f4f6; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    .section-note {{ color: #6b7280; font-size: 13px; margin: -6px 0 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(report_data.symbol)} 股票研究報表</h1>
    <div class="subtitle">分析日期：{html.escape(report_data.resolved_analysis_date())} ｜ 資料期間：{html.escape(data_period(report_data.price_data))}</div>
  </header>
  <main>
    <div class="notice">{html.escape(DISCLAIMER)}</div>

    <section>
      <h2>摘要</h2>
      <div class="grid">
        {_summary_card("技術面摘要", report_data.technical_summary or _technical_summary(report_data))}
        {_summary_card("基本面摘要", report_data.fundamental_summary or _fundamental_summary(report_data))}
        {_summary_card("風險摘要", report_data.risk_summary or _risk_summary(report_data))}
        {_summary_card("回測績效摘要", report_data.backtest_summary or _backtest_summary(report_data))}
      </div>
    </section>

    <section>
      <h2>圖表</h2>
      <p class="section-note">圖表使用本機資料產生；資料不足時會顯示提示。</p>
      {price_chart(report_data.price_data)}
      {equity_curve_chart(equity_curve)}
      {drawdown_chart(equity_curve)}
    </section>

    <section>
      <h2>指標摘要</h2>
      {_frame_to_html(indicators.tail(10))}
    </section>

    <section>
      <h2>基本面評分</h2>
      {_frame_to_html(fundamentals)}
    </section>

    <section>
      <h2>回測績效</h2>
      {_frame_to_html(backtest_metrics)}
    </section>

    <section>
      <h2>基準比較</h2>
      <p class="section-note">僅在基準與策略資金曲線日期完整一致時顯示；資料不足時不以 0 代替。</p>
      {_frame_to_html(benchmark_comparison)}
    </section>

    <section>
      <h2>資料來源與品質</h2>
      {_frame_to_html(data_sources)}
      <h3>資料缺口與警告</h3>
      {_frame_to_html(data_quality)}
    </section>

    <section>
      <h2>可重現性 Manifest</h2>
      <p class="section-note">Manifest 用於驗證本報表的輸入與設定一致性，不包含原始外部資料或私人內容。</p>
      {_frame_to_html(manifest)}
    </section>

    <section>
      <h2>交易紀錄</h2>
      {_frame_to_html(trade_log)}
    </section>

    <section>
      <h2>公司行動稽核</h2>
      <p class="section-note">僅列出具明確價格政策、可得日期與來源的已套用或拒絕事件。</p>
      {_frame_to_html(corporate_action_audit)}
    </section>

    <section>
      <h2>每日資產對帳</h2>
      <p class="section-note">每日總資產必須等於現金加持股市值；任何差異會保留在表中。</p>
      {_frame_to_html(daily_reconciliation)}
    </section>

    <section>
      <h2>風險提示</h2>
      {_frame_to_html(risk_alerts)}
    </section>
  </main>
</body>
</html>
"""


def _summary_card(label: str, value: Any) -> str:
    return f"""
<div class="card">
  <div class="label">{html.escape(label)}</div>
  <div class="value">{html.escape(str(value or INSUFFICIENT_DATA))}</div>
</div>
"""


def _frame_to_html(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        frame = pd.DataFrame({"訊息": [INSUFFICIENT_DATA]})
    display = localize_display_frame(frame)
    display = display.where(pd.notna(display), INSUFFICIENT_DATA)
    rows = []
    header = "".join(f"<th>{html.escape(str(column))}</th>" for column in display.columns)
    rows.append(f"<tr>{header}</tr>")
    for _, row in display.iterrows():
        cells = "".join(f"<td>{html.escape(_format_cell(value))}</td>" for value in row)
        rows.append(f"<tr>{cells}</tr>")
    return f"<table>{''.join(rows)}</table>"


def _format_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    if isinstance(value, float):
        return f"{value:,.4f}"
    return str(value)
