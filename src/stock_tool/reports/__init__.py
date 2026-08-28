"""Excel and HTML report generation."""

from stock_tool.reports.excel import generate_excel_report
from stock_tool.reports.html import generate_html_report, render_html_report
from stock_tool.reports.models import (
    DISCLAIMER,
    INSUFFICIENT_DATA,
    SURVIVORSHIP_BIAS_WARNING,
    TRAILING_STOP_DAILY_MODEL_NOTICE,
    BenchmarkMetadata,
    ReportData,
    ReportPackage,
    ReproducibilityManifest,
    localize_display_frame,
)

__all__ = [
    "DISCLAIMER",
    "INSUFFICIENT_DATA",
    "SURVIVORSHIP_BIAS_WARNING",
    "TRAILING_STOP_DAILY_MODEL_NOTICE",
    "BenchmarkMetadata",
    "ReportData",
    "ReportPackage",
    "ReproducibilityManifest",
    "generate_excel_report",
    "generate_html_report",
    "localize_display_frame",
    "render_html_report",
]
