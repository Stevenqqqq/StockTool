"""Pure next-step guidance for incomplete portfolio-health inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stock_tool.domain.models import MissingData

PORTFOLIO_RISK_INDEPENDENCE_NOTICE = "投資組合風險不需要先執行策略回測。"


@dataclass(frozen=True, slots=True)
class PortfolioGuidance:
    """A user-facing action with the underlying technical reason kept separate."""

    field: str
    next_step: str
    technical_reason: str


def portfolio_missing_data_guidance(
    missing_data: Iterable[MissingData],
) -> tuple[PortfolioGuidance, ...]:
    """Map canonical missing-data fields to non-destructive Chinese next steps."""

    output: list[PortfolioGuidance] = []
    seen: set[str] = set()
    for item in missing_data:
        if item.field in seen:
            continue
        seen.add(item.field)
        output.append(
            PortfolioGuidance(
                field=item.field,
                next_step=_next_step(item.field),
                technical_reason=item.reason,
            )
        )
    return tuple(output)


def _next_step(field: str) -> str:
    actions = {
        "latest_price": "請更新持股價格後再查看估值與健康度。",
        "portfolio_prices": "請補齊持股的歷史股價資料後再查看風險指標。",
        "fx_rate_to_base": "請更新匯率，或輸入明確的手動 USD/TWD 匯率。",
        "portfolio_fx": "請更新匯率，或輸入明確的手動 USD/TWD 匯率。",
        "portfolio_fundamentals": "請補齊各持股基本面資料，才能評估投資組合的基本面覆蓋度。",
        "portfolio_indicators": "請取得各持股足夠歷史價格，並建立技術指標後再評估風險。",
        "portfolio_composite_scores": "請先為各持股完成 Research Workspace 研究快照與綜合評分。",
        "technical_indicators": "請補齊持股的歷史股價資料，以計算波動率與回撤。",
        "fundamental_scores": "請補齊基本面資料後再重新整理投資組合健康度。",
        "composite_score": "請先在 Research Workspace 建立該股票的完整研究快照。",
        "portfolio.identity": "請確認股票代號與市場是否正確。",
        "portfolio.market": "請確認股票代號與市場是否正確。",
    }
    return actions.get(field, "請補齊對應資料後重新整理投資組合健康度。")
