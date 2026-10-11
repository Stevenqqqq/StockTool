"""Isolated calendar repair EXE smoke, no UI or real-data strategy execution."""
import json
from stock_tool.application.prediction_lab import MarketTradingCalendar

calendar = MarketTradingCalendar.default_for("TWSE", year=2025)
dates = [d for d in calendar.dates if "2025-02-24" <= d <= "2025-06-30"]
assert len(dates) == 86
assert calendar.target_date("2025-04-02", 1) == "2025-04-07"
assert MarketTradingCalendar.from_dict(calendar.to_dict()) == calendar
print(json.dumps({"calendar_smoke": "PASS", "fixed_period_days": len(dates), "security_qualification": "incomplete"}))
