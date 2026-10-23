"""Fixed-scope official calendar regression, not security qualification."""

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from stock_tool.application.prediction_lab import MarketTradingCalendar


def test_official_raw_and_fixed_period_calendar():
    raw = (Path(__file__).parent / "fixtures/qualification/twse-calendar-2025.json").read_bytes()
    payload = json.loads(raw)
    calendar = MarketTradingCalendar.default_for("TWSE", year=2025)
    assert hashlib.sha256(raw).hexdigest() == calendar.raw_payload_sha256
    assert len(raw) == calendar.raw_payload_size_bytes
    assert payload["queryYear"] == 2025
    assert payload["stat"] == "ok"
    assert payload["total"] == len(payload["data"]) == 24
    closed = {
        row[0] for row in payload["data"] if "開始交易" not in row[1] and "最後交易" not in row[1]
    }
    day = date(2025, 2, 24)
    expected = []
    while day <= date(2025, 6, 30):
        if day.weekday() < 5 and day.isoformat() not in closed:
            expected.append(day.isoformat())
        day += timedelta(days=1)
    actual = [d for d in calendar.dates if "2025-02-24" <= d <= "2025-06-30"]
    assert actual == expected
    assert len(actual) == 86
    assert sum(d < "2025-04-01" for d in actual) == 25
    assert sum(d >= "2025-04-01" for d in actual) == 61
    assert calendar.target_date("2025-04-02", 1) == "2025-04-07"
    assert calendar.target_date("2025-04-07", 1) == "2025-04-08"


def test_repaired_calendar_serialization_and_market_isolation():
    calendar = MarketTradingCalendar.default_for("TWSE", year=2025)
    assert MarketTradingCalendar.from_dict(calendar.to_dict()) == calendar
    other = MarketTradingCalendar.default_for("TWSE", year=2026)
    assert (
        other.raw_payload_sha256
        == "7fefe785ea7155a5004a2eb74486ad865ea5c4b5f02ee0cffbbdacb1ca2ea390"
    )
    assert calendar.market == "TWSE"
