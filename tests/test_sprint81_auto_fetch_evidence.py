"""Sprint 8.1 regression tests for the retained automatic-fetch Dashboard page."""

from __future__ import annotations

import pandas as pd
import pytest

import stock_tool.dashboard.app as dashboard_app
from stock_tool.dashboard.components.data_quality import build_data_evidence
from stock_tool.data.auto_fetch import FetchResult, ProviderAttempt
from stock_tool.data.policies import ProviderErrorCategory, ProviderHealthTracker


class _SessionState(dict[str, object]):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _AutoFetchStreamlit:
    """Small Streamlit double that executes only the retained auto-fetch page."""

    def __init__(self, tracker: ProviderHealthTracker) -> None:
        self.session_state = _SessionState(
            {
                "price_data": None,
                "technical_indicators": None,
                "price_data_source": None,
                "provider_health_tracker": tracker,
            }
        )
        self.events: list[tuple[str, object]] = []

    def title(self, value: str) -> None:
        self.events.append(("title", value))

    def caption(self, value: str) -> None:
        self.events.append(("caption", value))

    def info(self, value: str) -> None:
        self.events.append(("info", value))

    def warning(self, value: str) -> None:
        self.events.append(("warning", value))

    def success(self, value: str) -> None:
        self.events.append(("success", value))

    def subheader(self, value: str) -> None:
        self.events.append(("subheader", value))

    def text(self, value: str) -> None:
        self.events.append(("text", value))

    def dataframe(self, value: object, **_: object) -> None:
        self.events.append(("dataframe", value))

    def metric(self, label: str, value: object) -> None:
        self.events.append(("metric", (label, value)))

    def columns(self, count: int) -> list[_AutoFetchStreamlit]:
        return [self] * count

    def text_input(self, _label: str, *, value: str, **_: object) -> str:
        return value

    def selectbox(self, _label: str, options: list[str], **_: object) -> str:
        return options[0]

    def checkbox(self, _label: str, **_: object) -> bool:
        return False

    def button(self, label: str, **_: object) -> bool:
        return label == "抓取股價資料"


def _price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-07-10", "2026-07-11"],
            "symbol": ["2330", "2330"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1_000.0, 1_100.0],
            "adjusted_close": [101.0, 102.0],
        }
    )


def test_auto_fetch_page_preserves_full_evidence_and_health_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ProviderHealthTracker()
    fake_st = _AutoFetchStreamlit(tracker)
    captured: dict[str, object] = {}
    result = FetchResult(
        data=_price_frame(),
        source="yfinance",
        symbol="2330",
        provider_symbol="2330.TW",
        from_cache=False,
        cache_file=None,
        market="TWSE",
        start_date="2026-07-10",
        end_date="2026-07-11",
        source_type="online",
        warnings=("API key: secret-value",),
        attempts=(ProviderAttempt("yfinance", False, "token=secret-value"),),
        fetched_at="2026-07-14T12:00:00+00:00",
        last_data_date="2026-07-11",
        cache_state="fresh",
        cache_age_seconds=30.0,
    )

    def fake_fetch(*_: object, **kwargs: object) -> FetchResult:
        captured.update(kwargs)
        return result

    monkeypatch.setattr(dashboard_app, "fetch_prices", fake_fetch)
    monkeypatch.setattr(dashboard_app, "_persist_price_data", lambda *_: 2)

    dashboard_app._page_auto_fetch(fake_st)

    assert captured["health_tracker"] is tracker
    metadata = fake_st.session_state.price_data_source
    assert metadata == {
        "source_type": "online",
        "provider": "yfinance",
        "user_symbol": "2330",
        "query_symbol": "2330.TW",
        "market": "TWSE",
        "start_date": "2026-07-10",
        "end_date": "2026-07-11",
        "cache_file": None,
        "fetched_at": "2026-07-14T12:00:00+00:00",
        "last_data_date": "2026-07-11",
        "cache_state": "fresh",
        "cache_age_seconds": 30.0,
        "attempts": result.attempts,
        "row_count": 2,
    }
    rendered_text = "\n".join(str(value) for _, value in fake_st.events)
    assert "secret-value" not in rendered_text
    assert "[REDACTED]" in rendered_text


def test_auto_fetch_evidence_center_preserves_metadata_and_health_states() -> None:
    tracker = ProviderHealthTracker()
    tracker.record(
        provider="yfinance",
        enabled=True,
        capabilities=("TWSE",),
        success=True,
        latency_ms=12.0,
        source_type="online",
    )
    tracker.record(
        provider="finmind",
        enabled=True,
        capabilities=("TWSE",),
        success=False,
        latency_ms=10.0,
        category=ProviderErrorCategory.TIMEOUT,
    )
    tracker.record(
        provider="cache",
        enabled=True,
        capabilities=("TWSE",),
        success=False,
        latency_ms=None,
    )
    evidence = build_data_evidence(
        {
            "source_type": "online",
            "provider": "yfinance",
            "user_symbol": "2330",
            "query_symbol": "2330.TW",
            "market": "TWSE",
            "fetched_at": "2026-07-14T12:00:00+00:00",
            "last_data_date": "2026-07-11",
            "cache_state": "fresh",
            "row_count": 2,
            "attempts": (ProviderAttempt("finmind", False, "token=secret-value"),),
        },
        health=(snapshot.to_dict() for snapshot in tracker.snapshots()),
    )

    assert evidence["provenance"] == {
        "provider": "yfinance",
        "source_type": "online",
        "source_label": "線上下載",
        "fetched_at": "2026-07-14T12:00:00+00:00",
        "last_data_date": "2026-07-11",
        "row_count": 2,
        "cache_state": "fresh",
        "cache_age_seconds": None,
        "cache_file": None,
    }
    assert evidence["attempts"][0]["原因"] == "token=[REDACTED]"
    categories = {row["provider"]: row["last_error_category"] for row in evidence["health"]}
    assert categories == {"cache": "unknown", "finmind": "timeout", "yfinance": "無"}
