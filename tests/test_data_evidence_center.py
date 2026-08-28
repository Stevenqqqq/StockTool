from __future__ import annotations

from stock_tool.dashboard.components.data_quality import build_data_evidence


def test_evidence_center_renders_actual_cache_provenance_and_redacts_attempts() -> None:
    evidence = build_data_evidence(
        {
            "user_symbol": "2330",
            "market": "TWSE",
            "query_symbol": "2330.TW",
            "provider": "yfinance",
            "source_type": "cache",
            "cache_file": "data/cache/example.csv",
            "cache_state": "stale",
            "cache_age_seconds": 7200,
            "fetched_at": "2026-07-14T00:00:00+00:00",
            "last_data_date": "2026-07-13",
            "row_count": 500,
            "warnings": ("cache fallback",),
            "attempts": (
                {"provider": "finmind", "success": False, "reason": "token=secret-value"},
                {"provider": "cache:yfinance", "success": True, "reason": "loaded"},
            ),
        },
        health=(
            {
                "provider": "yfinance",
                "enabled": True,
                "consecutive_failures": 0,
                "last_success_at": "2026-07-14T00:00:00+00:00",
            },
        ),
    )

    assert evidence["provenance"]["source_label"] == "本機快取"
    assert evidence["identity"]["query_symbol"] == "2330.TW"
    assert evidence["attempts"][0]["原因"] == "token=[REDACTED]"
    assert "過期快取" in evidence["next_step"]


def test_evidence_center_does_not_promote_sample_or_upload_to_online() -> None:
    for source_type, label in (("sample", "範例資料"), ("user_upload", "使用者上傳")):
        evidence = build_data_evidence({"source_type": source_type, "row_count": 1})
        assert evidence["provenance"]["source_label"] == label
        assert evidence["provenance"]["source_type"] != "online"


def test_evidence_center_uses_insufficient_data_not_internal_sentinels() -> None:
    evidence = build_data_evidence({"source_type": "unknown", "warnings": ("API key: secret",)})
    assert evidence["quality"]["label"] == "資料不足"
    assert evidence["warnings"] == ("API key: [REDACTED]",)
    assert "secret" not in str(evidence)
