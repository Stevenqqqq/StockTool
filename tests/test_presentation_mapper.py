"""Sprint 34 Presentation Mapper comprehensive test suite."""

from __future__ import annotations


from stock_tool.dashboard.presentation_mapper import (
    aggregate_fold_warnings,
    deduplicate_warnings,
    format_currency,
    format_iso_datetime,
    format_market_label,
    format_number,
    format_parameters_zh,
    format_percentage,
    format_source_state_label,
    format_status_label,
    format_taiwan_company_display,
    format_turnover_value,
    format_volume,
    get_next_trading_date,
    translate_health_category,
    translate_health_reason,
)


def test_status_label_translations() -> None:
    assert format_status_label("healthy") == "健康"
    assert format_status_label("ready") == "資料已就緒"
    assert format_status_label("fresh") == "最新"
    assert format_status_label("stale") == "離線快取（已過期）"
    assert format_status_label("partial") == "部分可用"
    assert format_status_label("missing") == "資料不足"
    assert format_status_label("complete") == "已完成"
    assert format_status_label("not_run") == "尚未執行"
    assert format_status_label("blocked") == "條件未達成（已阻擋）"
    assert format_status_label("error") == "錯誤"
    assert format_status_label("unknown_status") == "unknown_status"


def test_source_state_label_translations() -> None:
    assert format_source_state_label("offline_cache") == "離線／本機快取"
    assert format_source_state_label("local_index") == "本機探索索引"
    assert format_source_state_label("provider") == "線上來源"
    assert format_source_state_label("missing") == "資料不足"


def test_market_label_translations() -> None:
    assert format_market_label("TWSE") == "台股上市"
    assert format_market_label("TPEX") == "台股上櫃"
    assert format_market_label("US") == "美股"
    assert format_market_label("CUSTOM") == "自訂市場"


def test_format_percentage() -> None:
    assert format_percentage(None) == "資料不足"
    assert format_percentage(float("nan")) == "資料不足"
    assert format_percentage(float("inf")) == "資料不足"
    assert format_percentage(0.1234, is_ratio=True) == "12.34%"
    assert format_percentage(0.1234, is_ratio=True, with_sign=True) == "+12.34%"
    assert format_percentage(0.5667, is_ratio=True) == "56.67%"
    assert format_percentage(0.5667, is_ratio=True, with_sign=True) == "+56.67%"
    assert format_percentage(-0.052, is_ratio=True, with_sign=True) == "-5.20%"
    assert format_percentage(12.34, is_ratio=False) == "12.34%"
    assert format_percentage(12.34, is_ratio=False, with_sign=True) == "+12.34%"
    assert format_percentage(-5.2, is_ratio=False, with_sign=True) == "-5.20%"
    assert format_percentage(0.0, with_sign=True) == "0.00%"


def test_format_number() -> None:
    assert format_number(None) == "資料不足"
    assert format_number(float("nan")) == "資料不足"
    assert format_number(1234567.89, decimals=2) == "1,234,567.89"
    assert format_number(1234567.0) == "1,234,567"
    assert format_number(500, with_sign=True) == "+500"


def test_format_volume() -> None:
    assert format_volume(None) == "資料不足"
    assert format_volume(500) == "500 股"
    assert format_volume(3500) == "3.5 千股"
    assert format_volume(250000) == "25.0 萬股"
    assert format_volume(350000000) == "3.50 億股"


def test_format_turnover_value() -> None:
    assert format_turnover_value(None) == "資料不足"
    assert format_turnover_value(5000) == "5,000 元"
    assert format_turnover_value(54000000) == "5,400.0 萬元"
    assert format_turnover_value(12540000000) == "125.40 億元"
    assert format_turnover_value(1000000, currency="USD") == "USD 100.0 萬元"


def test_format_currency() -> None:
    assert format_currency(None) == "資料不足"
    assert format_currency(1234.5, currency="TWD") == "TWD 1,234.50"
    assert format_currency(210.75, currency="USD") == "USD 210.75"


def test_format_iso_datetime() -> None:
    assert format_iso_datetime(None) == "資料不足"
    assert format_iso_datetime("") == "資料不足"
    assert format_iso_datetime("2026-08-29") == "2026-08-29"
    # ISO timestamp with microseconds
    assert format_iso_datetime("2026-08-29T14:30:15.123456Z") == "2026-08-29 14:30"
    assert format_iso_datetime("2026-08-29T08:15:00+00:00") == "2026-08-29 08:15"


def test_format_parameters_zh() -> None:
    assert format_parameters_zh({}) == "無自訂參數"
    params = {"short_window": 5, "long_window": 20, "target_percent": 0.4}
    formatted = format_parameters_zh(params)
    assert "短期均線：5" in formatted
    assert "長期均線：20" in formatted
    assert "投入比例：40%" in formatted


def test_deduplicate_warnings() -> None:
    warnings = ["缺少匯率", "缺少匯率", "資料過期", "", "缺少匯率"]
    deduped = deduplicate_warnings(warnings)
    assert deduped == ("缺少匯率", "資料過期")


def test_aggregate_fold_warnings() -> None:
    raw = [
        "Fold 1: 0 trades executed",
        "Fold 2: 0 trades executed",
        "Fold 3: 0 trades executed",
        "Fold 4: 0 trades executed",
        "Fold 5: 0 trades executed",
        "Fold 6: 0 trades executed",
        "Fold 7: 0 trades executed",
        "Fold 8: 0 trades executed",
        "Fold 9: 0 trades executed",
        "Fold 10: 0 trades executed",
        "資料長度不足",
    ]
    aggregated = aggregate_fold_warnings(raw, total_folds=10)
    assert len(aggregated) == 2
    assert "共 10 個 Walk-forward fold 於樣本期間內無交易紀錄" in aggregated[0]
    assert aggregated[1] == "資料長度不足"


def test_get_next_trading_date() -> None:
    # TWSE calendar query
    # Should safely return string date or None, never raises
    next_date = get_next_trading_date("TWSE", as_of_date="2026-08-01")
    if next_date is not None:
        assert isinstance(next_date, str)
        assert len(next_date) == 10
    # Far future beyond calendar
    assert get_next_trading_date("TWSE", as_of_date="2099-12-31") is None


def test_format_taiwan_company_display() -> None:
    assert format_taiwan_company_display("2330") == "台積電 (2330)"
    assert format_taiwan_company_display("2330", "台積電") == "台積電 (2330)"
    assert (
        format_taiwan_company_display("2330", "Taiwan Semiconductor Manufacturing Company Limited")
        == "台積電 (2330)"
    )
    assert format_taiwan_company_display("2330", "Taiwan Semiconductor") == "台積電 (2330)"
    assert format_taiwan_company_display("2454", "MediaTek Inc.") == "聯發科 (2454)"
    assert format_taiwan_company_display("2317", "Hon Hai Precision Industry") == "鴻海 (2317)"
    assert format_taiwan_company_display("2454", "聯發科") == "聯發科 (2454)"
    assert format_taiwan_company_display("AAPL", "Apple Inc.") == "Apple Inc. (AAPL)"
    assert format_taiwan_company_display("9999", None) == "9999"


def test_translate_health_category_and_reasons() -> None:
    assert translate_health_category("diversification") == "持股分散度"
    assert translate_health_category("valuation") == "估值覆蓋與健康度"
    assert translate_health_category("fundamental_health") == "基本面健康度"

    assert (
        translate_health_reason("Single stock concentration exceeds threshold")
        == "單一持股集中度高於建議門檻"
    )
    assert translate_health_reason("Missing price data for position") == "部分持股缺少最新價格資料"
    assert translate_health_reason("Custom untranslated reason") == "Custom untranslated reason"


def test_presentation_mapper_comprehensive_edge_cases() -> None:
    # Null & invalid inputs
    assert format_status_label(None) == "資料不足"
    assert format_source_state_label(None) == "資料不足"
    assert format_market_label(None) == "未知市場"
    assert format_percentage("invalid") == "資料不足"
    assert format_number("invalid") == "資料不足"
    assert format_number(float("inf")) == "資料不足"
    assert format_volume("invalid") == "資料不足"
    assert format_volume(-100) == "資料不足"
    assert format_volume(float("nan")) == "資料不足"
    assert format_turnover_value("invalid") == "資料不足"
    assert format_turnover_value(-50) == "資料不足"
    assert format_turnover_value(float("nan")) == "資料不足"
    assert format_currency("invalid") == "資料不足"
    assert format_currency(float("nan")) == "資料不足"
    assert format_iso_datetime("not-a-date") == "not-a-date"

    # Aggregation edge cases
    assert aggregate_fold_warnings([]) == ()
    assert aggregate_fold_warnings(["Fold 1: 0 trades executed"]) == ("Fold 1: 0 trades executed",)

    # Calendar exception fallback
    assert get_next_trading_date("NONEXISTENT_MARKET") is None

    # Company name formatting with existing parentheses
    assert format_taiwan_company_display("2330", "台積電 (2330)") == "台積電 (2330)"
    assert format_taiwan_company_display("", None) == ""
    assert translate_health_category("unknown_cat") == "unknown_cat"
