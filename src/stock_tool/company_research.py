"""Rule-based company business and industry research summaries."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Sequence

import yfinance as yf

from stock_tool.concept_repository import legacy_unverified_concept_hints
from stock_tool.data.auto_fetch import Market, normalize_market, yfinance_symbol_candidates
from stock_tool.data.repositories import ConceptRelationRecord
from stock_tool.network_deadline import RemoteCallTimeout, call_with_timeout


@dataclass(frozen=True)
class CompanyResearchProfile:
    """Business context shown on the AI analysis page."""

    symbol: str
    provider_symbol: str | None
    company_name: str
    sector: str
    industry: str
    website: str
    main_business: tuple[str, ...]
    technical_features: tuple[str, ...]
    linked_industries: tuple[str, ...]
    current_applications: tuple[str, ...]
    future_applications: tuple[str, ...]
    bottlenecks: tuple[str, ...]
    additional_checks: tuple[str, ...]
    data_sources: tuple[str, ...]
    limitations: tuple[str, ...]
    fact_fields: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        """Return whether the profile contains usable company context."""

        return any((self.company_name, self.sector, self.industry, self.main_business))


DEFAULT_LIMITATIONS = (
    "公司業務摘要使用公開資料與本機規則推論，可能不完整或延遲。",
    "題材關聯是研究索引，不代表公司營收主要來源或投資結論。",
    "請用公司年報、法說會、產品公告與財報附註交叉驗證。",
)

INDUSTRY_LABELS = {
    "technology": "科技",
    "financial services": "金融服務",
    "healthcare": "醫療保健",
    "industrials": "工業",
    "consumer cyclical": "非必需消費",
    "consumer defensive": "民生消費",
    "communication services": "通訊服務",
    "energy": "能源",
    "utilities": "公用事業",
    "basic materials": "原物料",
    "semiconductors": "半導體",
    "semiconductor equipment & materials": "半導體設備與材料",
    "electronic components": "電子零組件",
    "computer hardware": "電腦硬體",
    "communication equipment": "通訊設備",
    "information technology services": "資訊科技服務",
    "software - infrastructure": "軟體基礎設施",
    "software - application": "應用軟體",
    "electrical equipment & parts": "電氣設備與零組件",
    "specialty industrial machinery": "專用工業機械",
    "scientific & technical instruments": "科學與技術儀器",
    "consumer electronics": "消費性電子",
    "auto manufacturers": "汽車製造",
    "auto parts": "汽車零組件",
    "aerospace & defense": "航太與國防",
    "telecom services": "電信服務",
    "biotechnology": "生物科技",
    "banks - regional": "區域銀行",
    "banks - diversified": "綜合銀行",
    "marine shipping": "海運",
    "tools & accessories": "工具機與配件",
}

DOMAIN_RULES = {
    "半導體": {
        "tokens": ("semiconductor", "foundry", "wafer", "integrated circuit", "晶圓", "半導體"),
        "business": ("半導體製造、IC 設計、晶圓代工、封測或相關供應鏈服務。",),
        "tech": ("製程節點、良率、先進封裝、功耗控制與供應鏈交期是主要技術觀察點。",),
        "current": ("手機、資料中心、車用電子、工業控制與消費性電子。",),
        "future": ("AI 加速運算、高效能運算、車用晶片與邊緣 AI。",),
        "bottlenecks": ("資本支出高、景氣循環明顯、先進製程競爭與地緣供應鏈風險。",),
    },
    "記憶體": {
        "tokens": ("dram", "nand", "flash", "記憶體"),
        "business": ("DRAM、NAND、NOR Flash、記憶體模組或儲存控制相關業務。",),
        "tech": ("容量密度、速度、功耗、可靠度、控制器與先進封裝整合能力是核心觀察點。",),
        "current": ("PC、伺服器、手機、車用電子與工業儲存。",),
        "future": ("AI 伺服器、高頻寬記憶體、邊緣裝置與車用儲存需求。",),
        "bottlenecks": ("價格循環、庫存調整、產能擴張時點與產品世代轉換風險。",),
    },
    "AI / 伺服器": {
        "tokens": (
            "artificial intelligence",
            "server",
            "data center",
            "gpu",
            "hpc",
            "人工智慧",
            "伺服器",
        ),
        "business": ("AI 伺服器、資料中心硬體、散熱、電源、連接器或系統整合相關供應鏈。",),
        "tech": ("高速訊號、散熱設計、電源效率、系統整合與供應鏈交付能力是關鍵。",),
        "current": ("雲端資料中心、企業 AI 訓練與推論、HPC 叢集。",),
        "future": ("邊緣 AI、企業私有雲 AI、AI PC 與自動化系統。",),
        "bottlenecks": ("客戶集中、GPU 供給、規格變動、毛利率壓力與資本支出循環。",),
    },
    "PCB / 載板": {
        "tokens": ("pcb", "printed circuit", "substrate", "abf", "ccl", "電路板", "載板"),
        "business": ("PCB、HDI、軟板、載板、銅箔基板或電子互連材料。",),
        "tech": ("線寬線距、層數、材料穩定度、良率與高頻高速訊號完整性是主要技術特點。",),
        "current": ("手機、伺服器、網通設備、車用電子與消費電子。",),
        "future": ("AI 伺服器、高速交換器、車用電子與先進封裝載板。",),
        "bottlenecks": ("原物料價格、產品認證週期、良率爬坡、客戶砍單與產能利用率。",),
    },
    "電源 / 能源管理": {
        "tokens": (
            "power supply",
            "power management",
            "psu",
            "charger",
            "battery",
            "電源",
            "電源供應",
            "電源管理",
            "電池",
        ),
        "business": ("電源供應器、電源管理、充電、能源轉換或電氣設備零組件。",),
        "tech": ("轉換效率、散熱、安全認證、功率密度與可靠度是主要技術觀察點。",),
        "current": ("伺服器、工業設備、消費電子、通訊設備與電動車充電。",),
        "future": ("AI 資料中心電力基礎設施、儲能、電網升級與高功率快充。",),
        "bottlenecks": ("安規認證、原料成本、客戶規格變更、產能調配與價格競爭。",),
    },
    "通訊 / 低軌衛星": {
        "tokens": (
            "satellite",
            "low earth orbit",
            "communication",
            "telecom",
            "antenna",
            "衛星",
            "通訊",
        ),
        "business": ("通訊設備、射頻模組、天線、網通設備或衛星通訊相關供應鏈。",),
        "tech": ("射頻設計、天線效率、低延遲通訊、耐候可靠度與系統認證是核心觀察點。",),
        "current": ("寬頻網路、企業通訊、航空海事通訊與地面接收設備。",),
        "future": ("低軌衛星網路、偏遠地區通訊、國防通訊與物聯網連線。",),
        "bottlenecks": ("法規頻譜、客戶導入時程、發射與部署成本、供應鏈認證週期。",),
    },
    "機器人 / 自動化": {
        "tokens": ("robot", "robotics", "automation", "servo", "機器人", "自動化", "伺服"),
        "business": ("工業自動化、機器人零組件、伺服控制、感測或系統整合。",),
        "tech": ("精密控制、伺服馬達、感測融合、機構設計與軟硬整合能力是核心。",),
        "current": ("工廠自動化、物流搬運、檢測設備與精密製造。",),
        "future": ("人形機器人、智慧工廠、服務機器人與自動化倉儲。",),
        "bottlenecks": ("商業化速度、成本下降、可靠度、安全認證與客戶導入週期。",),
    },
    "生技醫療": {
        "tokens": (
            "biotech",
            "pharmaceutical",
            "healthcare",
            "drug",
            "生技",
            "製藥",
            "醫療器材",
            "藥品",
        ),
        "business": ("藥品、醫療器材、檢測服務、生技研發或醫療通路。",),
        "tech": ("臨床數據、法規送審、量產一致性與通路覆蓋是核心觀察點。",),
        "current": ("醫療院所、慢性病照護、檢測、藥品與醫材市場。",),
        "future": ("精準醫療、遠距醫療、新藥開發與高齡照護需求。",),
        "bottlenecks": ("臨床與法規不確定性、研發費用、健保給付與市場採用速度。",),
    },
}

FOCUS_RULES = {
    "Semiconductor silicon wafers": {
        "symbols": ("6488",),
        "tokens": ("silicon wafer", "silicon wafers", "semiconductor wafer"),
        "business": (
            "半導體矽晶圓製造與供應；實際產品組合、尺寸與終端用途應以公司公告與年報確認。",
        ),
        "tech": ("矽晶圓的晶體成長、拋光、外延、缺陷密度與規格認證是主要技術觀察點。",),
        "current": ("邏輯、記憶體、功率與特殊製程半導體的矽晶圓供應鏈。",),
        "future": ("先進製程、車用與功率半導體需求變化需以客戶認證與產能利用率交叉驗證。",),
        "bottlenecks": ("晶圓價格循環、產能利用率、客戶認證、規格轉換與能源成本是主要觀察風險。",),
        "checks": ("檢查矽晶圓出貨量、平均售價、產能利用率、客戶結構與資本支出。",),
    },
    "HBM / AI 記憶體": {
        "symbols": ("MU",),
        "tokens": (
            "hbm",
            "hbm3e",
            "hbm4",
            "high bandwidth memory",
            "high-bandwidth memory",
            "高頻寬記憶體",
        ),
        "business": (
            "AI 記憶體與資料中心記憶體供應；重點不是只有一般 DRAM，而是 HBM、DDR5、LPDDR 與資料中心 SSD 等高頻寬/高效能產品組合。",
        ),
        "tech": (
            "HBM 的核心觀察點是堆疊層數、頻寬、功耗、散熱、良率、先進封裝配合度與 AI 加速器平台認證進度。",
            "DRAM 與 NAND 仍有景氣循環，但 HBM 更需要觀察長約、產能配置、客戶認證與每 bit 獲利能力。",
        ),
        "current": ("AI 訓練伺服器、GPU/AI 加速器、資料中心推論、高效能運算與企業伺服器記憶體。",),
        "future": ("HBM3E/HBM4、AI 伺服器記憶體擴容、資料中心儲存與邊緣 AI 裝置記憶體升級。",),
        "bottlenecks": (
            "HBM 產能、先進封裝供給、良率爬坡、客戶集中、價格循環與資本支出節奏是主要瓶頸。",
        ),
        "checks": ("檢查 HBM 相關營收占比、位元出貨成長、平均售價、毛利率與主要客戶認證進度。",),
    },
    "NAND / SSD 儲存": {
        "symbols": ("SNDK",),
        "tokens": (
            "nand",
            "flash storage",
            "solid state drive",
            "ssd",
            "memory card",
            "usb flash",
            "sandisk",
        ),
        "business": ("NAND Flash、SSD、記憶卡、USB 隨身碟、嵌入式儲存與企業/消費儲存產品。",),
        "tech": (
            "NAND 儲存的技術重點是 3D NAND 堆疊層數、控制器、韌體、耐用度、資料保存、讀寫速度與成本/容量曲線。",
            "若連到 AI 題材，核心通常不是 HBM，而是資料中心 SSD、AI 資料管線、邊緣裝置與高耐寫儲存需求。",
        ),
        "current": ("PC、手機周邊、遊戲、影像創作、車用/工業嵌入式儲存、資料中心與企業 SSD。",),
        "future": (
            "AI 資料湖、模型訓練資料儲存、邊緣 AI、車用資料記錄、工業 IoT 與高容量企業 SSD。",
        ),
        "bottlenecks": (
            "NAND 供需循環、價格下跌、控制器/韌體可靠度、產品組合轉換與資料中心客戶導入速度。",
        ),
        "checks": ("檢查 NAND 價格趨勢、enterprise SSD 占比、庫存水位、資本支出與產品毛利率。",),
    },
    "機器人關節 / 減速器": {
        "symbols": ("2049",),
        "tokens": (
            "harmonic reducer",
            "strain wave gear",
            "robot reducer",
            "rv reducer",
            "減速器",
            "諧波",
            "關節",
        ),
        "business": ("機器人關節、諧波/機器人減速器、滾珠螺桿、線性滑軌或精密傳動元件。",),
        "tech": (
            "減速器重點是低背隙、高扭矩密度、高剛性、傳動效率、壽命、噪音、重量與量產一致性。",
            "人形機器人若使用在肩、肘、腕、髖、膝、踝等關節，需要同時檢查精度、耐衝擊、散熱與成本。",
        ),
        "current": ("工具機、半導體設備、自動化產線、工業機器人與精密定位設備。",),
        "future": ("人形機器人關節模組、協作機器人、服務機器人、自動化倉儲與醫療/復健設備。",),
        "bottlenecks": ("量產良率、成本下降、關節壽命、客戶認證、日系/歐系競爭與實際出貨節奏。",),
        "checks": ("檢查減速器或關節模組是否已有量產訂單、占營收比重、毛利率與主要客戶驗證進度。",),
    },
    "伺服控制 / 運動控制": {
        "symbols": ("1590", "2308", "2464", "ROK"),
        "tokens": ("servo", "motion control", "motor drive", "伺服", "運動控制", "馬達驅動"),
        "business": ("伺服馬達、驅動器、控制器、氣動/電動執行元件或自動化系統整合。",),
        "tech": (
            "運動控制重點是控制迴路響應、定位精度、扭矩控制、通訊協定、安全控制與多軸同步能力。",
        ),
        "current": ("工廠自動化、機械手臂、半導體設備、物流設備與智慧製造產線。",),
        "future": ("人形機器人關節控制、協作機器人、AMR/AGV、自動化倉儲與智慧工廠。",),
        "bottlenecks": ("客戶導入週期長、軟硬整合難度、可靠度驗證、國際大廠競爭與價格壓力。",),
        "checks": ("確認公司產品是伺服/控制核心零組件，還是只間接供應自動化設備。",),
    },
    "邊緣控制 / 工業電腦": {
        "symbols": ("6166",),
        "tokens": (
            "industrial computer",
            "edge computing",
            "robot controller",
            "工業電腦",
            "邊緣運算",
            "控制器",
        ),
        "business": ("工業電腦、邊緣運算平台、機器視覺控制、資料擷取或機器人控制器。",),
        "tech": ("重點是工規可靠度、即時控制、I/O 擴充、低延遲、AI 推論加速與工業通訊整合。",),
        "current": ("工廠自動化、機器視覺、交通、醫療設備、半導體設備與邊緣 AI。",),
        "future": ("機器人控制器、智慧工廠邊緣 AI、視覺檢測與多感測器融合。",),
        "bottlenecks": ("專案型訂單波動、客製化成本、客戶驗證週期、零組件供給與毛利率穩定性。",),
        "checks": ("確認 AI/機器人相關產品是否已貢獻營收，而非僅止於展示或概念題材。",),
    },
    "整機 / AI 平台": {
        "symbols": ("TSLA", "NVDA", "ISRG", "SYM", "TER"),
        "tokens": ("humanoid", "robotics platform", "robotics system", "機器人平台", "整機"),
        "business": ("機器人整機、AI 訓練/推論平台、機器人系統、自動化設備或精密機械臂。",),
        "tech": (
            "整機平台重點是感知、運動控制、AI 模型、系統安全、供應鏈整合、成本下降與量產能力。",
        ),
        "current": ("工業自動化、醫療機器人、倉儲物流、AI 模型訓練與仿真平台。",),
        "future": ("人形機器人、服務機器人、自動駕駛工廠、智慧倉儲與具身 AI。",),
        "bottlenecks": ("商業模式、可靠度、安全法規、成本、電池續航、量產良率與終端需求驗證。",),
        "checks": ("區分公司是整機/平台、核心零組件、軟體工具，還是只被題材間接帶動。",),
    },
}


def build_company_research_profile(
    symbol: str,
    *,
    market: Market = "AUTO",
    info: dict[str, Any] | None = None,
    concept_relations: Sequence[ConceptRelationRecord] = (),
    allow_remote_fetch: bool = True,
    fetch_timeout_seconds: float = 5.0,
) -> CompanyResearchProfile:
    """Build a conservative business and industry summary for one company."""

    symbol_text = str(symbol).strip().upper()
    if not symbol_text:
        return _empty_profile("", None, "股票代號空白，無法產生公司研究摘要。")

    provider_symbol = None
    data_sources = ["yfinance 公司基本資料"]
    limitations = list(DEFAULT_LIMITATIONS)
    fetched_info: dict[str, Any] = {}

    if info is not None:
        fetched_info = dict(info)
        provider_symbol = str(fetched_info.get("symbol") or symbol_text)
    elif not allow_remote_fetch:
        provider_symbol = symbol_text
        limitations.append("目前使用本機快取資料；為避免離線等待，已略過公司基本資料的線上查詢。")
    else:
        fetched_info, provider_symbol, fetch_error = _fetch_company_info(
            symbol_text, market=market, timeout_seconds=fetch_timeout_seconds
        )
        if fetch_error:
            limitations.append(fetch_error)

    company_name = _first_text(
        fetched_info.get("longName"),
        fetched_info.get("shortName"),
        fetched_info.get("displayName"),
        symbol_text,
    )
    sector = _label(fetched_info.get("sector") or fetched_info.get("sectorDisp"))
    industry = _label(fetched_info.get("industry") or fetched_info.get("industryDisp"))
    website = str(fetched_info.get("website") or "").strip()
    summary = str(fetched_info.get("longBusinessSummary") or "").strip()

    canonical_concepts = tuple(
        relation.concept_key
        for relation in concept_relations
        if relation.identity.symbol == symbol_text
        and relation.identity.market == normalize_market(market)
        and relation.evidence
    )
    if canonical_concepts:
        data_sources.append("canonical 題材關係證據")
    else:
        data_sources.append("本機規則式題材對照（未驗證相容提示）")
        limitations.append("未使用 canonical 題材證據時，規則式題材對照不代表已驗證供應鏈關係。")
    matched_domains = _matched_domains(
        symbol=symbol_text,
        provider_symbol=provider_symbol,
        text=" ".join((company_name, sector, industry, summary)),
        allow_legacy_fallback=not canonical_concepts,
    )
    matched_focuses = _matched_focus_rules(
        symbol=symbol_text,
        provider_symbol=provider_symbol,
        text=" ".join((company_name, sector, industry, summary)),
    )
    main_business = _dedupe(
        *_business_overview(company_name, sector, industry, summary),
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["business"]),
        *(item for domain in matched_domains for item in DOMAIN_RULES[domain]["business"]),
    )
    technical_features = _dedupe(
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["tech"]),
        *(item for domain in matched_domains for item in DOMAIN_RULES[domain]["tech"]),
        default="缺少足夠產品或製程描述；需查看公司年報、產品頁與法說資料確認技術特點。",
    )
    linked_industries = _dedupe(
        _translated_label(sector),
        _translated_label(industry),
        *matched_domains,
        *matched_focuses,
        *(
            _concept_label(item)
            for item in _matched_concepts(
                symbol_text,
                provider_symbol,
                " ".join((company_name, sector, industry, summary)),
                allow_legacy_hints=not canonical_concepts,
            )
        ),
        *canonical_concepts,
    )
    current_applications = _dedupe(
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["current"]),
        *(item for domain in matched_domains for item in DOMAIN_RULES[domain]["current"]),
        default="目前應用場景需依公司產品線、客戶別與營收拆分進一步確認。",
    )
    future_applications = _dedupe(
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["future"]),
        *(item for domain in matched_domains for item in DOMAIN_RULES[domain]["future"]),
        default="未來應用方向資料不足；不應用題材敘事替代公司實際訂單與財務驗證。",
    )
    bottlenecks = _dedupe(
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["bottlenecks"]),
        *(item for domain in matched_domains for item in DOMAIN_RULES[domain]["bottlenecks"]),
        "需注意需求循環、客戶集中、毛利率變化、匯率、利率與市場競爭。",
    )
    additional_checks = _dedupe(
        *(item for focus in matched_focuses for item in FOCUS_RULES[focus]["checks"]),
        "確認各產品線營收占比，避免把小題材誤當主要業務。",
        "檢查近四季毛利率、營業利益率與現金流是否支持題材敘事。",
        "檢查主要客戶、產能利用率、存貨週轉與資本支出變化。",
    )

    if not summary:
        limitations.append("yfinance 未提供公司長描述，業務摘要主要依產業分類與題材對照推論。")
    if not matched_domains:
        limitations.append("未匹配到明確題材規則，技術與應用摘要會較保守。")

    return CompanyResearchProfile(
        symbol=symbol_text,
        provider_symbol=provider_symbol,
        company_name=company_name,
        sector=sector or "資料不足",
        industry=industry or "資料不足",
        website=website,
        main_business=main_business,
        technical_features=technical_features,
        linked_industries=linked_industries,
        current_applications=current_applications,
        future_applications=future_applications,
        bottlenecks=bottlenecks,
        additional_checks=additional_checks,
        data_sources=tuple(data_sources),
        limitations=tuple(_dedupe(*limitations)),
        fact_fields=tuple(
            field
            for field, value in (
                ("company_name", fetched_info.get("longName") or fetched_info.get("shortName")),
                ("sector", fetched_info.get("sector") or fetched_info.get("sectorDisp")),
                ("industry", fetched_info.get("industry") or fetched_info.get("industryDisp")),
                ("business_summary", fetched_info.get("longBusinessSummary")),
            )
            if value
        ),
    )


def _fetch_company_info(
    symbol: str, *, market: Market, timeout_seconds: float = 5.0
) -> tuple[dict[str, Any], str | None, str | None]:
    market_key = normalize_market(market)
    if market_key == "AUTO" and not symbol.isdigit() and not symbol.endswith((".TW", ".TWO")):
        market_key = "US"
    try:
        candidates = yfinance_symbol_candidates(symbol, market=market_key)
    except Exception as exc:
        return {}, None, f"無法建立 yfinance 查詢代號：{exc}"

    failures: list[str] = []
    deadline = monotonic() + max(0.0, timeout_seconds)
    for candidate in candidates:
        remaining = deadline - monotonic()
        if remaining <= 0:
            failures.append("公司基本資料查詢逾時，已保留可用的本機研究結果。")
            break
        try:
            ticker = yf.Ticker(candidate)
            info = call_with_timeout(
                lambda: (
                    ticker.get_info()
                    if hasattr(ticker, "get_info")
                    else getattr(ticker, "info", {})
                ),
                timeout_seconds=remaining,
            )
            info = dict(info or {})
            useful_count = sum(
                1
                for key in ("longName", "shortName", "sector", "industry", "longBusinessSummary")
                if info.get(key)
            )
            if useful_count:
                return info, candidate, None
            failures.append(f"{candidate}: 沒有公司描述或產業欄位")
        except RemoteCallTimeout:
            failures.append(f"{candidate}: 公司基本資料查詢逾時，已略過。")
            break
        except Exception as exc:
            failures.append(f"{candidate}: {exc}")
    return (
        {},
        candidates[0] if candidates else None,
        "；".join(failures) if failures else "yfinance 沒有回傳公司基本資料。",
    )


def _matched_domains(
    *,
    symbol: str,
    provider_symbol: str | None,
    text: str,
    allow_legacy_fallback: bool = True,
) -> tuple[str, ...]:
    normalized_text = _normalize_text(text)
    provider_base = _base_symbol(provider_symbol)
    is_silicon_wafer_identity = symbol == "6488" or provider_base == "6488"
    text_matches: list[str] = []
    for domain, rule in DOMAIN_RULES.items():
        if is_silicon_wafer_identity and {"dram", "nand", "flash"}.issubset(
            {_normalize_text(token) for token in rule["tokens"]}
        ):
            continue
        if any(_normalize_text(token) in normalized_text for token in rule["tokens"]):
            text_matches.append(domain)
    if text_matches:
        return tuple(dict.fromkeys(text_matches))

    if is_silicon_wafer_identity:
        return ()

    fallback_matches: list[str] = []
    if not allow_legacy_fallback:
        return ()
    for concept in legacy_unverified_concept_hints(
        symbol=symbol, provider_symbol=provider_base, text=text
    ):
        if concept:
            if concept in {"ai", "人工智慧", "ai伺服器"}:
                fallback_matches.append("AI / 伺服器")
            elif concept == "pcb":
                fallback_matches.append("PCB / 載板")
            elif concept == "電源":
                fallback_matches.append("電源 / 能源管理")
            elif concept == "低軌衛星":
                fallback_matches.append("通訊 / 低軌衛星")
            elif concept == "人形機器人":
                fallback_matches.append("機器人 / 自動化")
            elif concept == "記憶體":
                fallback_matches.append("記憶體")
            elif concept in DOMAIN_RULES:
                fallback_matches.append(concept)
    return tuple(dict.fromkeys(fallback_matches))


def _matched_focus_rules(*, symbol: str, provider_symbol: str | None, text: str) -> tuple[str, ...]:
    normalized_text = _normalize_text(text)
    provider_base = _base_symbol(provider_symbol)
    is_silicon_wafer_identity = symbol == "6488" or provider_base == "6488"
    matches: list[str] = []
    for focus, rule in FOCUS_RULES.items():
        if is_silicon_wafer_identity and focus != "Semiconductor silicon wafers":
            continue
        symbols = {str(item).upper() for item in rule["symbols"]}
        if symbol in symbols or provider_base in symbols:
            matches.append(focus)
            continue
        if any(_safe_token_match(token, normalized_text) for token in rule["tokens"]):
            matches.append(focus)
    return tuple(dict.fromkeys(matches))


def _matched_concepts(
    symbol: str,
    provider_symbol: str | None,
    text: str,
    *,
    allow_legacy_hints: bool = True,
) -> tuple[str, ...]:
    """Return legacy hints only during the gradual canonical-dataset transition."""

    if not allow_legacy_hints:
        return ()
    return legacy_unverified_concept_hints(
        symbol=symbol, provider_symbol=provider_symbol, text=text
    )


def _is_safe_concept_text_match(alias: str, normalized_text: str) -> bool:
    """Return whether a concept name is specific enough to match inside company text."""

    return _safe_token_match(alias, normalized_text)


def _safe_token_match(alias: str, normalized_text: str) -> bool:
    """Return whether a token is specific enough to match inside company text."""

    if not alias:
        return False
    alias = _normalize_text(alias)
    if alias.isascii() and len(alias) < 3:
        return False
    return alias in normalized_text


def _concept_label(concept: str) -> str:
    labels = {
        "ai": "AI",
        "人工智慧": "AI",
        "ai伺服器": "AI 伺服器",
        "hbm": "HBM / AI 記憶體",
        "cowos": "CoWoS",
        "copos": "CoPoS",
        "tgv": "TGV / 玻璃通孔",
        "cpo": "CPO / 矽光子",
        "pcb": "PCB",
    }
    return labels.get(concept, concept)


def _business_overview(name: str, sector: str, industry: str, summary: str) -> tuple[str, ...]:
    sector_label = _translated_label(sector)
    industry_label = _translated_label(industry)
    if industry_label != "資料不足":
        return (f"{name} 依公開資料分類屬於「{industry_label}」，上層產業為「{sector_label}」。",)
    if summary:
        return (f"{name} 有公開公司描述，但產業分類不足；需進一步查公司年報確認主要業務。",)
    return (f"{name} 主要業務資料不足；需用年報、官網與財報補充確認。",)


def _translated_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "資料不足"
    return INDUSTRY_LABELS.get(text.lower(), text)


def _label(value: Any) -> str:
    text = str(value or "").strip()
    return _translated_label(text) if text else ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _base_symbol(symbol: str | None) -> str:
    return str(symbol or "").upper().replace(".TW", "").replace(".TWO", "")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _dedupe(*items: str, default: str | None = None) -> tuple[str, ...]:
    output: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text != "資料不足" and text not in output:
            output.append(text)
    if not output and default:
        output.append(default)
    return tuple(output)


def _empty_profile(symbol: str, provider_symbol: str | None, reason: str) -> CompanyResearchProfile:
    return CompanyResearchProfile(
        symbol=symbol,
        provider_symbol=provider_symbol,
        company_name=symbol,
        sector="資料不足",
        industry="資料不足",
        website="",
        main_business=(),
        technical_features=(),
        linked_industries=(),
        current_applications=(),
        future_applications=(),
        bottlenecks=(),
        additional_checks=(),
        data_sources=("yfinance 公司基本資料", "本機規則式題材對照"),
        limitations=(*DEFAULT_LIMITATIONS, reason),
        fact_fields=(),
    )
