"""Safe, reusable data-evidence presentation helpers for the Library workspace."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from stock_tool.data.contracts import sanitize_provider_text

_SOURCE_LABELS = {
    "online": "線上下載",
    "cache": "本機快取",
    "local_file": "本機匯入資料",
    "user_upload": "使用者上傳",
    "sample": "範例資料",
    "unknown": "來源未確認",
}


def build_data_evidence(
    source: Mapping[str, Any] | None,
    *,
    health: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build user-safe provenance, quality, attempts, and next-step evidence."""

    metadata = dict(source or {})
    source_type = str(metadata.get("source_type") or "unknown").strip().lower()
    if source_type not in _SOURCE_LABELS:
        source_type = "unknown"
    warnings = _safe_texts(metadata.get("warnings") or ())
    attempts = _safe_attempts(metadata.get("attempts") or ())
    cache_state = _safe_text(metadata.get("cache_state"))
    quality = _quality_state(metadata, warnings)
    return {
        "identity": {
            "user_symbol": _safe_text(metadata.get("user_symbol")),
            "market": _safe_text(metadata.get("market")),
            "query_symbol": _safe_text(metadata.get("query_symbol")),
        },
        "provenance": {
            "provider": _safe_text(metadata.get("provider")),
            "source_type": source_type,
            "source_label": _SOURCE_LABELS[source_type],
            "fetched_at": _safe_text(metadata.get("fetched_at") or metadata.get("updated_at")),
            "last_data_date": _safe_text(
                metadata.get("last_data_date") or metadata.get("end_date")
            ),
            "row_count": _safe_integer(metadata.get("row_count")),
            "cache_state": cache_state,
            "cache_age_seconds": _safe_number(metadata.get("cache_age_seconds")),
            "cache_file": _safe_text(metadata.get("cache_file")),
        },
        "quality": quality,
        "warnings": warnings,
        "attempts": attempts,
        "health": [_safe_health(item) for item in health],
        "next_step": _next_step(source_type, cache_state, quality, warnings),
    }


def render_data_quality(st: Any, evidence: Mapping[str, Any]) -> bool:
    """Render a compact data-evidence centre and return a refresh click state."""

    st.subheader("資料與證據中心")
    identity = evidence["identity"]
    provenance = evidence["provenance"]
    st.caption(
        "輸入代號："
        f"{identity['user_symbol'] or '資料不足'}；市場：{identity['market'] or '資料不足'}；"
        f"實際查詢代號：{identity['query_symbol'] or '資料不足'}"
    )
    columns = st.columns(4)
    columns[0].metric("資料來源", provenance["source_label"])
    columns[1].metric("提供者", provenance["provider"] or "資料不足")
    columns[2].metric(
        "資料列數", provenance["row_count"] if provenance["row_count"] is not None else "資料不足"
    )
    columns[3].metric("品質狀態", evidence["quality"]["label"])
    st.caption(
        f"取得時間：{provenance['fetched_at'] or '資料不足'}；最後資料日："
        f"{provenance['last_data_date'] or '資料不足'}；快取狀態："
        f"{provenance['cache_state'] or '未使用'}。"
    )
    if evidence["warnings"]:
        for warning in evidence["warnings"]:
            st.warning(warning)
    if evidence["attempts"]:
        st.caption("Provider 嘗試與備援紀錄")
        st.dataframe(evidence["attempts"], use_container_width=True, hide_index=True)
    if evidence["health"]:
        st.caption("Provider Health（僅本次執行期間；重新啟動後會重設）")
        st.dataframe(evidence["health"], use_container_width=True, hide_index=True)
    st.info(f"下一步：{evidence['next_step']}")
    return bool(
        st.button(
            "強制重新整理",
            key="library_force_refresh",
            disabled=not bool(identity["user_symbol"] and identity["market"]),
        )
    )


def _quality_state(metadata: Mapping[str, Any], warnings: tuple[str, ...]) -> dict[str, str]:
    state = _safe_text(metadata.get("quality_status"))
    if state:
        return {"value": state, "label": state}
    if any("過期" in warning or "快取" in warning for warning in warnings):
        return {"value": "stale", "label": "過期備援"}
    if metadata.get("row_count") is None:
        return {"value": "insufficient", "label": "資料不足"}
    return {"value": "available", "label": "可用"}


def _next_step(
    source_type: str,
    cache_state: str | None,
    quality: Mapping[str, str],
    warnings: tuple[str, ...],
) -> str:
    if source_type == "cache" and cache_state in {"stale", "expired"}:
        return "目前為過期快取備援；網路可用時請使用強制重新整理確認資料。"
    if quality.get("value") == "insufficient":
        return "請確認代號與市場，重新整理資料，或使用資料匯入提供可驗證資料。"
    if warnings:
        return "請閱讀資料警示後再進行研究；系統不會以缺失資料補造結論。"
    return "資料可用於研究；請留意資料日期與來源限制。"


def _safe_attempts(value: Iterable[object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in value:
        raw = item if isinstance(item, Mapping) else getattr(item, "__dict__", {})
        if not isinstance(raw, Mapping):
            continue
        items.append(
            {
                "provider": _safe_text(raw.get("provider")) or "資料不足",
                "結果": "成功" if raw.get("success") else "失敗",
                "原因": _safe_text(raw.get("reason")) or "未提供原因",
            }
        )
    return items


def _safe_health(value: Mapping[str, Any]) -> dict[str, object]:
    return {
        "provider": _safe_text(value.get("provider")) or "資料不足",
        "enabled": bool(value.get("enabled")),
        "last_success_at": _safe_text(value.get("last_success_at")) or "資料不足",
        "last_failure_at": _safe_text(value.get("last_failure_at")) or "資料不足",
        "consecutive_failures": _safe_integer(value.get("consecutive_failures")) or 0,
        "last_error_category": _safe_text(value.get("last_error_category")) or "無",
        "recent_source_type": _safe_text(value.get("recent_source_type")) or "無",
        "recent_cache_state": _safe_text(value.get("recent_cache_state")) or "無",
    }


def _safe_text(value: object) -> str | None:
    text = sanitize_provider_text(value).strip() if value is not None else ""
    return text or None


def _safe_texts(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(text for value in values if (text := _safe_text(value)))


def _safe_integer(value: object) -> int | None:
    return int(value) if isinstance(value, int) and value >= 0 else None


def _safe_number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None
