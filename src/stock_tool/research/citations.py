"""Citation validation at the boundary between model output and the UI."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Mapping

from stock_tool.research.evidence import ClaimKind, EvidenceBundle

if TYPE_CHECKING:
    from stock_tool.research.assistant import ResearchClaim


_INJECTION_TERMS = (
    "ignore previous",
    "ignore all",
    "system prompt",
    "api key",
    "execute shell",
    "run powershell",
    "modify watchlist",
    "modify portfolio",
    "<script",
    "javascript:",
    "忽略先前指示",
    "忽略之前指示",
    "忽略所有指示",
    "忽略上述指示",
    "忽略先前指令",
    "忽略之前指令",
    "忽略所有指令",
    "忽略上述指令",
    "忽略之前说明",
    "忽略所有说明",
    "系统提示",
    "系統提示",
    "api 金鑰",
    "api 金钥",
    "api 密鑰",
    "api 密钥",
    "顯示金鑰",
    "顯示金钥",
    "显示密钥",
    "顯示密鑰",
    "显示 secret",
    "顯示 secret",
    "show secret",
    "顯示系統提示",
    "显示系统提示",
    "執行 shell",
    "执行 shell",
    "執行 powershell",
    "执行 powershell",
    "修改持股",
    "修改自選股",
    "修改自选股",
)
_ADVICE_TERMS = (
    "立即買進",
    "立即买进",
    "立即買入",
    "立即买入",
    "現在買進",
    "现在买进",
    "現在買入",
    "现在买入",
    "保證獲利",
    "保证获利",
    "保證盈利",
    "保证盈利",
    "穩賺",
    "稳赚",
    "必漲",
    "必涨",
    "歐印",
    "梭哈",
)
_CHINESE_TRADE_ACTION = (
    r"(?:\u8cb7\u9032|\u8cb7\u5165|\u8ce3\u51fa|\u51fa\u6e05|\u52a0\u78bc|\u6e1b\u78bc|"
    r"\u4e70\u8fdb|\u4e70\u5165|\u5356\u51fa|\u6e05\u4ed3|\u52a0\u7801|\u51cf\u7801)"
)
_GENERIC_ENGLISH_TRADE_TARGET = r"(?:this\s+stock|the\s+stock|the\s+position|(?:the\s+)?shares)"
_GENERIC_CHINESE_TRADE_TARGET = (
    r"(?:\u9019\u6a94\u80a1\u7968|\u8fd9\u53ea\u80a1\u7968|\u6301\u80a1|\u5009\u4f4d|\u4ed3\u4f4d)"
)
_ADVICE_PATTERNS = (
    re.compile(r"\b(?:buy|sell)\s+(?:now|immediately|this stock|all[- ]in)\b"),
    re.compile(r"\bstrong\s+(?:buy|sell)\b"),
    re.compile(r"\b(?:guaranteed?|risk[- ]free)\s+(?:profit|return|gain|money)\b"),
    re.compile(r"\b(?:recommend|recommends|recommended)\s+(?:buy|buying|sell|selling)\b"),
    re.compile(r"\b(?:buy|sell)\s+(?:now|today|immediately)\b"),
    re.compile(
        r"(?:\u5efa\u8b70|\u5efa\u8bae|\u63a8\u85a6|\u63a8\u8350|\u61c9\u8a72|\u5e94\u8be5)"
        r".{0,8}(?:\u8cb7\u9032|\u8cb7\u5165|\u8ce3\u51fa|\u51fa\u6e05|\u52a0\u78bc|\u6e1b\u78bc|"
        r"\u4e70\u8fdb|\u4e70\u5165|\u5356\u51fa|\u6e05\u4ed3|\u52a0\u7801|\u51cf\u7801)"
    ),
    re.compile(
        r"(?:\u73fe\u5728|\u73b0\u5728|\u7acb\u5373|\u7acb\u523b|\u99ac\u4e0a|\u9a6c\u4e0a|\u4eca\u5929)"
        r".{0,8}(?:\u8cb7\u9032|\u8cb7\u5165|\u8ce3\u51fa|\u51fa\u6e05|\u52a0\u78bc|\u6e1b\u78bc|"
        r"\u4e70\u8fdb|\u4e70\u5165|\u5356\u51fa|\u6e05\u4ed3|\u52a0\u7801|\u51cf\u7801)"
    ),
    re.compile(
        r"(?:\u8cb7\u9032|\u8cb7\u5165|\u8ce3\u51fa|\u51fa\u6e05|\u52a0\u78bc|\u6e1b\u78bc|"
        r"\u4e70\u8fdb|\u4e70\u5165|\u5356\u51fa|\u6e05\u4ed3|\u52a0\u7801|\u51cf\u7801)"
        r".{0,8}(?:\u73fe\u5728|\u73b0\u5728|\u7acb\u5373|\u7acb\u523b|\u99ac\u4e0a|\u9a6c\u4e0a|\u4eca\u5929)"
    ),
    re.compile(
        r"(?:\u4fdd\u8b49|\u4fdd\u8bc1).{0,6}(?:\u7372\u5229|\u83b7\u5229|\u76c8\u5229|\u8cfa\u9322|\u8d5a\u94b1)"
    ),
)


class ResearchClaimValidationError(ValueError):
    """Raised when an untrusted output violates the all-or-nothing contract."""


def validate_research_claims(
    claims: tuple[ResearchClaim, ...],
    bundle: EvidenceBundle,
    *,
    fail_closed: bool = False,
) -> tuple[tuple[ResearchClaim, ...], tuple[str, ...]]:
    """Validate claims against immutable evidence.

    The default preserves the existing inspection API by returning accepted
    claims and warnings. Callers consuming model or cache output must pass
    ``fail_closed=True`` so that any invalid claim rejects the complete note.
    """

    registry = bundle.evidence_by_id()
    validated: list[ResearchClaim] = []
    warnings: list[str] = []
    for claim in claims:
        violation = _claim_violation(claim, registry, bundle)
        if violation is not None:
            warnings.append(violation)
            if fail_closed:
                raise ResearchClaimValidationError("AI research claims failed validation.")
            continue
        validated.append(claim)
    return tuple(validated), tuple(dict.fromkeys(warnings))


def _claim_violation(
    claim: ResearchClaim,
    registry: Mapping[str, object],
    bundle: EvidenceBundle,
) -> str | None:
    text = _security_normalized(claim.text)
    if any(term in text for term in _INJECTION_TERMS):
        return "AI 研究輸出包含不可信指令。"
    if (
        any(term in text for term in _ADVICE_TERMS)
        or _is_direct_trade_instruction(claim.text, bundle)
        or any(pattern.search(text) for pattern in _ADVICE_PATTERNS)
    ):
        return "Rejected trading instruction or guarantee in AI research output."
    if any(identifier not in registry for identifier in claim.citation_ids):
        return "AI 研究輸出引用不存在的證據。"
    requires_exact_evidence = claim.kind in {ClaimKind.FACT, ClaimKind.CALCULATION}
    if requires_exact_evidence and not claim.citation_ids:
        return "事實或計算結果必須附上引用。"
    if requires_exact_evidence and not any(
        _normalized_text(claim.text) == _normalized_text(getattr(registry[identifier], "text"))
        for identifier in claim.citation_ids
    ):
        return "AI 研究輸出改寫已引用的確定性證據。"
    if requires_exact_evidence and any(
        getattr(registry[identifier], "kind") is ClaimKind.MISSING
        for identifier in claim.citation_ids
    ):
        return "Rejected missing evidence presented as a fact or calculation."
    if claim.kind is ClaimKind.INFERENCE and (
        not claim.citation_ids
        or not any(
            getattr(registry[identifier], "kind") is not ClaimKind.MISSING
            for identifier in claim.citation_ids
        )
    ):
        return "AI inference requires at least one non-missing evidence citation."
    return None


def _is_direct_trade_instruction(text: str, bundle: EvidenceBundle) -> bool:
    """Reject narrow trade commands aimed at this research identity.

    A model may not make a trade recommendation.  The target must be either a
    short list of explicit generic references or a symbol obtained from the
    active evidence bundle; ordinary English words are never treated as a
    ticker.  Unknown ticker-shaped commands are rejected separately so that a
    model cannot introduce an unrelated symbol as an apparent safe target.
    """

    normalized = _security_normalized(text)
    symbol_forms = _bundle_symbol_forms(bundle)
    symbol_target = "|".join(re.escape(symbol) for symbol in symbol_forms)
    english_target = _GENERIC_ENGLISH_TRADE_TARGET
    chinese_target = _GENERIC_CHINESE_TRADE_TARGET
    if symbol_target:
        english_target = rf"(?:{english_target}|{symbol_target})"
        chinese_target = rf"(?:{chinese_target}|{symbol_target})"

    known_target_patterns = (
        re.compile(
            rf"(?:^|[.!?]\s*)(?:please\s+)?(?:buy|sell)\s+{english_target}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])"
        ),
        re.compile(
            rf"(?:^|[\u3002\uff01\uff1f]\s*)(?:\u8acb|\u8bf7)?{_CHINESE_TRADE_ACTION}\s*"
            rf"{chinese_target}(?=$|[\u3002\uff01\uff1f.!?])"
        ),
        re.compile(
            rf"\b(?:you|we)\s+should(?:\s+consider)?\s+"
            rf"(?:buy|buying|sell|selling)\s+{english_target}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])"
        ),
        re.compile(
            rf"\b(?:i|we)\s+recommend(?:\s+(?:that\s+)?(?:you|investors))?\s+"
            rf"(?:buy|buying|sell|selling)\s+{english_target}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])"
        ),
    )
    if any(pattern.search(normalized) for pattern in known_target_patterns):
        return True

    # This is rejection-only: an imperative or recommendation with a complete
    # direct-object phrase is unsafe unless the object was already accepted
    # above. It does not infer that an arbitrary English word is a ticker;
    # instead, it rejects an otherwise unambiguous trade command. Phrases such
    # as "Buy signals are historically noisy" remain descriptive because the
    # object is not followed by a sentence boundary.
    unknown_english_object = r"[a-z0-9.$_-]+"
    unknown_chinese_object = r"(?:[a-z0-9.$_-]+|[\u4e00-\u9fff]{1,12})"
    return bool(
        re.search(
            rf"(?:^|[.!?]\s*)(?:please\s+)?(?:buy|sell)\s+{unknown_english_object}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])",
            normalized,
        )
        or re.search(
            rf"\b(?:you|we)\s+should(?:\s+consider)?\s+"
            rf"(?:buy|buying|sell|selling)\s+{unknown_english_object}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])",
            normalized,
        )
        or re.search(
            rf"\b(?:i|we)\s+recommend(?:\s+(?:that\s+)?(?:you|investors))?\s+"
            rf"(?:buy|buying|sell|selling)\s+{unknown_english_object}"
            rf"(?:\s+(?:now|today|immediately))?(?=$|[.!?])",
            normalized,
        )
        or re.search(
            rf"(?:^|[\u3002\uff01\uff1f]\s*)(?:\u8acb|\u8bf7)?{_CHINESE_TRADE_ACTION}\s*"
            rf"{unknown_chinese_object}(?=$|[\u3002\uff01\uff1f.!?])",
            normalized,
        )
    )


def _bundle_symbol_forms(bundle: EvidenceBundle) -> tuple[str, ...]:
    """Return only canonical symbol forms evidenced by the active bundle."""

    symbol = _security_normalized(bundle.symbol).strip()
    if not symbol:
        return ()
    forms = {symbol}
    market = _security_normalized(bundle.market).strip()
    if symbol.endswith(".tw"):
        forms.add(symbol.removesuffix(".tw"))
    elif symbol.endswith(".two"):
        forms.add(symbol.removesuffix(".two"))
    elif re.fullmatch(r"\d{3,6}", symbol):
        if market == "twse":
            forms.add(f"{symbol}.tw")
        elif market == "tpex":
            forms.add(f"{symbol}.two")
    return tuple(sorted(forms, key=lambda value: (-len(value), value)))


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _security_normalized(value: str) -> str:
    """Normalize untrusted claim text before applying narrow safety policies."""

    normalized = _security_normalized_preserving_case(value).casefold()
    return normalized


def _security_normalized_preserving_case(value: str) -> str:
    """Normalize Unicode before the case-insensitive safety comparison."""
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(character for character in normalized if unicodedata.category(character) != "Cf")
