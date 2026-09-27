"""Online concept-stock lookup for Taiwan and US research workflows."""

from __future__ import annotations

from stock_tool.yfinance_runtime import configure_yfinance_cache

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
import yfinance as yf
from yfinance.screener import EquityQuery

DEFAULT_CONCEPT_STOCK_PATH = Path("data") / "sample" / "concept_stocks.csv"
TWSE_COMPANY_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
CONCEPT_COLUMNS = (
    "symbol",
    "name",
    "market",
    "exchange",
    "industry",
    "concept",
    "relation_type",
    "price_reaction_stage",
    "stage_note",
    "keywords",
    "source",
    "note",
)
MARKET_LABELS = {
    "TWSE": "台股上市",
    "TPEX": "台股上櫃",
    "US": "美股",
}
TW_INDUSTRY_CODES = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "20": "其他",
    "21": "化學工業",
    "22": "生技醫療",
    "23": "油電燃氣",
    "24": "半導體",
    "25": "電腦及週邊設備",
    "26": "光電業",
    "27": "通信網路",
    "28": "電子零組件",
    "29": "電子通路",
    "30": "資訊服務",
    "31": "其他電子",
    "32": "文化創意",
    "33": "農業科技",
    "34": "電子商務",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
}
QUERY_ALIASES = {
    "ai": ("ai", "人工智慧", "生成式ai", "gpu", "ai伺服器", "伺服器"),
    "人工智慧": ("ai", "人工智慧", "生成式ai", "gpu", "ai伺服器", "伺服器"),
    "ai伺服器": ("ai伺服器", "伺服器", "server", "gpu", "hpc"),
    "半導體": ("半導體", "晶圓", "ic設計", "封測", "晶片", "gpu"),
    "hbm供應鏈": ("hbm供應鏈", "hbm台股", "hbm概念股", "hbm相關", "ai記憶體供應鏈"),
    "hbm": ("hbm", "高頻寬記憶體", "high bandwidth memory", "hbm3e", "hbm4", "ai記憶體"),
    "矽電容": ("矽電容", "矽電容器", "si-cap", "sicap", "silicon capacitor", "silicon capacitors", "ipd", "integrated passive device"),
    "先進封裝": ("先進封裝", "advanced packaging", "2.5d", "3d封裝", "chiplet", "異質整合", "封裝"),
    "cowos": ("cowos", "co-wos", "cowos-s", "cowos-l", "cowos-r", "chip on wafer on substrate", "chip-on-wafer-on-substrate"),
    "copos": ("copos", "co-pos", "chip on panel on substrate", "chip-on-panel-on-substrate", "panel level packaging", "panel-level packaging", "foplp"),
    "tgv": ("tgv", "through glass via", "through-glass via", "through glass vias", "glass via", "glass substrate", "玻璃基板", "玻璃通孔"),
    "cpo": ("cpo", "co-packaged optics", "co packaged optics", "silicon photonics", "矽光子", "共同封裝光學"),
    "pcb": ("pcb", "印刷電路板", "電路板", "載板", "abf", "銅箔基板", "ccl"),
    "記憶體": ("記憶體", "memory", "dram", "nand", "nor", "儲存", "模組"),
    "電源": ("電源", "電源供應器", "power supply", "psu", "充電器", "變壓器", "電源管理"),
    "低軌衛星": ("低軌衛星", "衛星", "leo", "satellite", "通訊", "射頻", "天線"),
    "人形機器人": ("人形機器人", "機器人", "robotics", "robot", "自動化", "伺服", "感測"),
    "電動車": ("電動車", "ev", "車用電子", "充電", "電池"),
    "綠能": ("綠能", "太陽能", "儲能", "電網", "風電"),
    "資安": ("資安", "cybersecurity", "網路安全", "雲端安全"),
    "雲端": ("雲端", "cloud", "saas", "資料中心"),
    "生技": ("生技", "醫療", "製藥", "biotech", "healthcare"),
    "金融": ("金融", "銀行", "保險", "金控", "fintech"),
    "航運": ("航運", "海運", "空運", "航空"),
}

CONCEPT_SYMBOL_NOTES = {
    "先進封裝": {
        "2330": "台積電：晶圓代工與先進封裝整合平台代表，CoWoS、InFO、SoIC 等封裝能力常被視為 AI 晶片供應鏈的核心環節之一。",
        "3711": "日月光投控：全球主要封測 OSAT 服務商之一，先進封裝、SiP、異質整合與測試服務具代表性；實際市占與技術領先程度仍需以最新產業報告確認。",
        "2449": "京元電子：半導體測試服務商，與高階晶片封裝後測試需求相關；不是封裝代工廠。",
        "3037": "欣興：IC 載板與高階載板供應鏈代表，與先進封裝、AI/HPC 封裝基板需求相關。",
        "3189": "景碩：IC 載板供應商，與高階封裝基板、BT/ABF 載板需求相關。",
        "8046": "南電：IC 載板與高階載板供應鏈代表，受 AI/HPC 與先進封裝基板需求影響。",
        "3443": "創意：ASIC 設計服務商，與先進製程、Chiplet 與 AI/HPC 客製晶片設計需求相關。",
        "3661": "世芯-KY：ASIC 設計服務商，與 AI/HPC 客製晶片、先進製程與封裝協同設計需求相關。",
        "3583": "辛耘：半導體設備與再生晶圓等服務供應商，屬先進製程與封裝產能擴充的周邊設備鏈。",
        "3680": "家登：半導體載具與晶圓傳載解決方案供應商，與先進製程及封裝廠潔淨搬運需求相關。",
        "6196": "帆宣：半導體廠務與設備整合服務商，與先進製程、封裝與擴產工程需求相關。",
        "6510": "精測：測試介面與探針卡供應商，與高階晶片測試、先進製程及封裝後測試需求相關。",
        "TSM": "台積電 ADR：晶圓代工與先進封裝平台供應方，CoWoS、InFO、SoIC 等能力與 AI/HPC 封裝需求高度相關。",
        "ASX": "ASE Technology：全球主要 OSAT 封測服務商之一，提供封裝、測試、SiP 與異質整合相關服務。",
        "AMKR": "Amkor Technology：全球主要 OSAT 封測服務商之一，提供先進封裝與測試服務。",
        "INTC": "Intel：IDM 廠，具 EMIB、Foveros 等先進封裝技術；不是純 OSAT 封裝代工廠。",
        "NVDA": "NVIDIA：AI GPU 與加速器設計公司，會深度參與封裝架構設計並大量使用 CoWoS/HBM 等先進封裝產能；不是封裝代工廠。",
        "AMD": "AMD：CPU/GPU 與加速器設計公司，採用 chiplet、3D V-Cache、2.5D/3D 封裝等架構；不是封裝代工廠。",
        "AVGO": "Broadcom：ASIC、網通與半導體設計公司，與先進封裝需求端及客製晶片供應鏈相關；不是封裝代工廠。",
        "AMAT": "Applied Materials：半導體設備供應商，與先進封裝製程設備需求相關；不是封裝代工廠。",
        "KLAC": "KLA：半導體檢測與量測設備供應商，與先進封裝檢測需求相關；不是封裝代工廠。",
        "LRCX": "Lam Research：半導體設備供應商，與先進製程及部分封裝相關製程設備需求有關；不是封裝代工廠。",
        "ONTO": "Onto Innovation：半導體量測與檢測設備供應商，與先進封裝製程控制需求相關；不是封裝代工廠。",
    },
    "cowos": {
        "2330": "台積電：CoWoS 主要供應平台之一，與 AI GPU、HBM 整合及 2.5D 先進封裝產能高度相關。",
        "3711": "日月光投控：全球主要封測 OSAT 服務商之一，屬先進封裝與測試服務鏈；並非 CoWoS 專屬供應商。",
        "3037": "欣興：高階 IC 載板供應鏈代表，與 CoWoS/HBM 相關封裝基板需求有關。",
        "3189": "景碩：IC 載板供應商，與 AI/HPC 封裝基板需求相關。",
        "8046": "南電：IC 載板與高階載板供應鏈代表，與 AI/HPC 封裝基板需求相關。",
        "TSM": "台積電 ADR：CoWoS 主要供應平台之一。",
        "ASX": "ASE Technology：封測服務商，屬先進封裝與測試鏈；不是 CoWoS 專屬供應商。",
        "AMKR": "Amkor Technology：封測服務商，屬先進封裝與測試鏈；不是 CoWoS 專屬供應商。",
        "NVDA": "NVIDIA：CoWoS/HBM 重要需求端與封裝架構協同設計方；不是 CoWoS 封裝代工廠。",
        "AMD": "AMD：先進封裝與 chiplet 架構重要需求端；不是 CoWoS 封裝代工廠。",
        "AVGO": "Broadcom：客製 ASIC 與網通晶片需求端，與先進封裝產能相關；不是封裝代工廠。",
        "MRVL": "Marvell：資料中心與客製晶片需求端，與先進封裝產能相關；不是封裝代工廠。",
        "AMAT": "Applied Materials：半導體設備供應商，與先進封裝設備需求相關。",
        "KLAC": "KLA：半導體檢測與量測設備供應商，與先進封裝檢測需求相關。",
        "ONTO": "Onto Innovation：半導體量測與檢測設備供應商，與先進封裝製程控制需求相關。",
    },
    "hbm供應鏈": {
        "2330": "台積電：HBM 需求通常連動 AI 加速器與 CoWoS 等先進封裝產能；此為供應鏈關聯，非 HBM 記憶體製造商。",
        "3711": "日月光投控：全球主要封測 OSAT 服務商之一，與先進封裝與測試服務相關；此為 HBM 需求供應鏈關聯，非 HBM 記憶體製造商。",
        "3037": "欣興：IC 載板供應鏈代表，與 AI/HBM 封裝基板需求相關；非 HBM 記憶體製造商。",
        "3189": "景碩：IC 載板供應商，與高階封裝基板需求相關；非 HBM 記憶體製造商。",
        "8046": "南電：IC 載板與高階載板供應鏈代表，與 AI/HBM 封裝基板需求相關；非 HBM 記憶體製造商。",
    },
    "矽電容": {
        "6531": "愛普*：市場常將其視為台股矽電容 / IPD 題材代表之一；需追蹤量產進度、客戶認證、良率與營收占比。",
        "6770": "力積電：與矽電容 / IPD 製造、晶圓代工與集團供應鏈分工相關；需追蹤產能、製程良率與客戶導入進度。",
        "2344": "華邦電：記憶體與相關製程能力受到市場討論；與矽電容題材的直接營收連動需持續確認。",
        "2330": "台積電：先進封裝與高效能運算供應鏈核心之一；此處為矽電容應用場景關聯，非純矽電容標的。",
    },
}

CONCEPT_SYMBOL_RELATION_TYPES = {
    "先進封裝": {
        "2330": "先進封裝平台 / 晶圓代工",
        "3711": "封測服務商（OSAT）",
        "2449": "測試服務供應鏈",
        "3037": "IC 載板供應鏈",
        "3189": "IC 載板供應鏈",
        "8046": "IC 載板供應鏈",
        "3443": "晶片設計服務 / 封裝協同設計",
        "3661": "晶片設計服務 / 封裝協同設計",
        "3583": "設備 / 製程周邊供應鏈",
        "3680": "載具 / 製程周邊供應鏈",
        "6196": "廠務 / 設備整合供應鏈",
        "6510": "測試介面供應鏈",
        "TSM": "先進封裝平台 / 晶圓代工",
        "ASX": "封測服務商（OSAT）",
        "AMKR": "封測服務商（OSAT）",
        "INTC": "IDM / 先進封裝技術",
        "NVDA": "晶片設計 / 先進封裝需求端（非封裝代工）",
        "AMD": "晶片設計 / 先進封裝需求端（非封裝代工）",
        "AVGO": "晶片設計 / 先進封裝需求端（非封裝代工）",
        "AMAT": "設備供應鏈（非封裝代工）",
        "KLAC": "檢測量測設備供應鏈（非封裝代工）",
        "LRCX": "設備供應鏈（非封裝代工）",
        "ONTO": "檢測量測設備供應鏈（非封裝代工）",
    },
    "cowos": {
        "2330": "CoWoS 平台供應方",
        "3711": "封測服務商（非 CoWoS 專屬）",
        "3037": "IC 載板供應鏈",
        "3189": "IC 載板供應鏈",
        "8046": "IC 載板供應鏈",
        "3443": "晶片設計服務 / 封裝協同設計",
        "3661": "晶片設計服務 / 封裝協同設計",
        "3583": "設備 / 製程周邊供應鏈",
        "3680": "載具 / 製程周邊供應鏈",
        "6196": "廠務 / 設備整合供應鏈",
        "6510": "測試介面供應鏈",
        "TSM": "CoWoS 平台供應方",
        "ASX": "封測服務商（非 CoWoS 專屬）",
        "AMKR": "封測服務商（非 CoWoS 專屬）",
        "NVDA": "AI GPU 需求端 / 封裝架構協同設計（非封裝代工）",
        "AMD": "AI 加速器需求端 / chiplet 封裝架構（非封裝代工）",
        "AVGO": "ASIC 需求端 / 先進封裝需求（非封裝代工）",
        "MRVL": "ASIC 需求端 / 先進封裝需求（非封裝代工）",
        "AMAT": "設備供應鏈（非封裝代工）",
        "KLAC": "檢測量測設備供應鏈（非封裝代工）",
        "ONTO": "檢測量測設備供應鏈（非封裝代工）",
    },
    "hbm供應鏈": {
        "NVDA": "AI GPU 需求端 / HBM 封裝整合需求（非 HBM 製造商）",
        "AMD": "AI 加速器需求端 / HBM 封裝整合需求（非 HBM 製造商）",
        "AVGO": "ASIC 需求端 / HBM 封裝整合需求（非 HBM 製造商）",
        "TSM": "先進封裝平台 / HBM 整合供應鏈",
        "ASX": "封測服務供應鏈",
        "AMKR": "封測服務供應鏈",
        "AMAT": "設備供應鏈",
        "KLAC": "檢測量測設備供應鏈",
        "ONTO": "檢測量測設備供應鏈",
    },
}

CONCEPT_SYMBOL_RELATION_RANKS = {
    "先進封裝": {
        "2330": 0,
        "TSM": 0,
        "3711": 1,
        "ASX": 1,
        "AMKR": 1,
        "INTC": 1,
        "2449": 2,
        "3037": 2,
        "3189": 2,
        "8046": 2,
        "3443": 2,
        "3661": 2,
        "3583": 2,
        "3680": 2,
        "6196": 2,
        "6510": 2,
        "AMAT": 2,
        "KLAC": 2,
        "LRCX": 2,
        "ONTO": 2,
        "NVDA": 3,
        "AMD": 3,
        "AVGO": 3,
    },
    "cowos": {
        "2330": 0,
        "TSM": 0,
        "3711": 1,
        "ASX": 1,
        "AMKR": 1,
        "3037": 2,
        "3189": 2,
        "8046": 2,
        "3443": 2,
        "3661": 2,
        "3583": 2,
        "3680": 2,
        "6196": 2,
        "6510": 2,
        "AMAT": 2,
        "KLAC": 2,
        "ONTO": 2,
        "NVDA": 3,
        "AMD": 3,
        "AVGO": 3,
        "MRVL": 3,
    },
}

CONCEPT_STAGE_DEFAULT = ("未標註", "此題材尚未設定股價反應階段；請搭配股價、成交量、基本面與新聞時點自行判斷。")

CONCEPT_PROFILES = {
    "半導體": {
        "tw_codes": ("24",),
        "tw_symbols": ("2303", "2330", "2379", "2408", "2454", "3034", "3711", "3443", "3529", "3661"),
        "us_symbols": ("NVDA", "AMD", "AVGO", "QCOM", "INTC", "MU", "TSM", "ASML", "ARM"),
        "us_industries": ("Semiconductors",),
        "search_queries": ("semiconductor", "semiconductor equipment", "AI chip"),
    },
    "ai": {
        "tw_codes": ("24", "25", "28", "31", "36"),
        "tw_symbols": ("2330", "2454", "2317", "2382", "3231", "6669", "2356", "2376", "2308", "3661"),
        "us_symbols": ("NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD", "AVGO", "PLTR", "TSM"),
        "us_industries": ("Semiconductors", "Software - Infrastructure", "Information Technology Services"),
        "search_queries": ("artificial intelligence", "AI chip", "AI infrastructure"),
    },
    "人工智慧": {
        "tw_codes": ("24", "25", "28", "31", "36"),
        "tw_symbols": ("2330", "2454", "2317", "2382", "3231", "6669", "2356", "2376", "2308", "3661"),
        "us_symbols": ("NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD", "AVGO", "PLTR", "TSM"),
        "us_industries": ("Semiconductors", "Software - Infrastructure", "Information Technology Services"),
        "search_queries": ("artificial intelligence", "AI chip", "AI infrastructure"),
    },
    "ai伺服器": {
        "tw_codes": ("25", "28", "31", "24"),
        "tw_symbols": ("2382", "3231", "6669", "2356", "2376", "2317", "3017", "3324", "2308", "2404"),
        "us_symbols": ("NVDA", "SMCI", "DELL", "HPE", "AMD", "AVGO", "ANET", "TSM"),
        "us_industries": ("Computer Hardware", "Semiconductors", "Information Technology Services"),
        "search_queries": ("AI server", "data center hardware", "GPU server"),
    },
    "pcb": {
        "tw_codes": (),
        "tw_symbols": (
            "2313",
            "2367",
            "2383",
            "3037",
            "3044",
            "3189",
            "4958",
            "5469",
            "6108",
            "6213",
            "6269",
            "6274",
            "8213",
        ),
        "us_symbols": ("TTMI", "SANM", "JBL", "FLEX"),
        "us_industries": ("Electronic Components",),
        "search_queries": ("printed circuit board", "PCB manufacturing", "electronic components"),
    },
    "記憶體": {
        "tw_codes": (),
        "tw_symbols": ("2337", "2344", "2408", "2451", "3006", "3260", "4967", "6239", "8299"),
        "us_symbols": ("MU", "WDC", "STX", "SNDK", "SIMO"),
        "us_industries": ("Semiconductors", "Computer Hardware"),
        "search_queries": ("memory semiconductor", "DRAM", "NAND flash"),
    },
    "hbm供應鏈": {
        "tw_codes": (),
        "tw_symbols": ("2330", "3711", "3037", "3189", "8046", "3443", "3661", "3583", "3680", "6196", "6510"),
        "us_symbols": ("TSM", "ASX", "AMKR", "NVDA", "AMD", "AVGO", "AMAT", "KLAC", "ONTO"),
        "us_industries": (),
        "search_queries": ("HBM supply chain", "CoWoS HBM", "advanced packaging HBM"),
        "relation_type": ("供應鏈關聯（非直接 HBM 製造商）",),
        "relation_rank": ("1",),
        "note": (
            "此為 HBM 需求相關供應鏈或先進封裝關聯，非 HBM 記憶體製造商清單。",
        ),
    },
    "hbm": {
        "tw_codes": (),
        "tw_symbols": (),
        "us_symbols": ("MU",),
        "us_industries": (),
        "search_queries": ("Micron HBM",),
        "relation_type": ("直接製造商",),
        "relation_rank": ("0",),
        "related_profiles": ("hbm供應鏈",),
        "note": (
            "HBM 直接製造商主要是記憶體大廠；目前台股沒有明確的 HBM 記憶體製造商，台股多屬先進封裝、測試、載板、設備或材料供應鏈。",
        ),
    },
    "矽電容": {
        "tw_codes": (),
        "tw_symbols": ("6531", "6770", "2344", "2330"),
        "us_symbols": (),
        "us_industries": (),
        "search_queries": ("silicon capacitor", "Si-Cap semiconductor", "integrated passive device"),
        "relation_type": ("概念 / 題材關聯",),
        "relation_rank": ("1",),
        "price_reaction_stage": ("初期觀察",),
        "stage_note": (
            "矽電容 / Si-Cap 題材仍偏早期反應階段；市場開始討論供給、客戶導入與量產時程，但需觀察實際營收占比、產能、良率與客戶認證是否落地。",
        ),
        "note": (
            "矽電容題材為早期研究索引；候選股多屬記憶體製程、IPD、先進封裝或晶圓代工關聯，不代表已形成穩定營收貢獻。",
        ),
    },
    "先進封裝": {
        "tw_codes": (),
        "tw_symbols": (
            "2330",
            "3711",
            "2449",
            "3037",
            "3189",
            "8046",
            "3443",
            "3661",
            "3583",
            "3680",
            "6196",
            "6510",
        ),
        "us_symbols": ("TSM", "ASX", "AMKR", "INTC", "NVDA", "AMD", "AVGO", "AMAT", "KLAC", "LRCX", "ONTO"),
        "us_industries": (),
        "search_queries": ("advanced semiconductor packaging", "chiplet packaging", "2.5D packaging", "heterogeneous integration"),
        "relation_type": ("概念 / 題材關聯",),
        "relation_rank": ("1",),
    },
    "cowos": {
        "tw_codes": (),
        "tw_symbols": (
            "2330",
            "3711",
            "3443",
            "3661",
            "3037",
            "3189",
            "8046",
            "3583",
            "3680",
            "6196",
            "6510",
        ),
        "us_symbols": ("TSM", "ASX", "AMKR", "NVDA", "AMD", "AVGO", "MRVL", "AMAT", "KLAC", "ONTO"),
        "us_industries": ("Semiconductors", "Semiconductor Equipment & Materials"),
        "search_queries": ("CoWoS", "Chip on Wafer on Substrate", "advanced packaging CoWoS"),
    },
    "copos": {
        "tw_codes": (),
        "tw_symbols": (
            "2330",
            "3711",
            "2409",
            "3481",
            "3037",
            "3189",
            "8046",
            "3583",
            "3680",
            "6196",
            "6510",
        ),
        "us_symbols": ("TSM", "ASX", "AMKR", "AMAT", "KLAC", "LRCX", "ONTO"),
        "us_industries": ("Semiconductors", "Semiconductor Equipment & Materials", "Electronic Components"),
        "search_queries": ("CoPoS", "Chip on Panel on Substrate", "panel level packaging", "fan out panel level packaging"),
    },
    "tgv": {
        "tw_codes": (),
        "tw_symbols": (
            "2330",
            "3711",
            "2409",
            "3481",
            "3037",
            "3189",
            "8046",
            "3583",
            "3680",
            "6196",
            "6510",
        ),
        "us_symbols": ("GLW", "AMAT", "KLAC", "ONTO", "COHR", "LITE", "AMKR", "TSM"),
        "us_industries": ("Semiconductor Equipment & Materials", "Electronic Components"),
        "search_queries": ("through glass via", "TGV glass substrate", "glass substrate semiconductor packaging"),
    },
    "cpo": {
        "tw_codes": ("27", "24", "28"),
        "tw_symbols": ("2330", "3711", "3105", "3450", "4979", "3081", "2314", "2345", "6285", "6214"),
        "us_symbols": ("AVGO", "MRVL", "COHR", "LITE", "CIEN", "INFN", "INTC", "NVDA", "TSM"),
        "us_industries": ("Communication Equipment", "Semiconductors", "Electronic Components"),
        "search_queries": ("co-packaged optics", "silicon photonics", "optical interconnect"),
    },
    "電源": {
        "tw_codes": (),
        "tw_symbols": ("2301", "2308", "2457", "3015", "3323", "3416", "6282", "6412"),
        "us_symbols": ("VRT", "ETN", "GNRC", "POWI", "MPWR", "ON"),
        "us_industries": ("Electrical Equipment & Parts", "Electronic Components", "Semiconductors"),
        "search_queries": ("power supply", "power management", "electrical equipment"),
    },
    "低軌衛星": {
        "tw_codes": (),
        "tw_symbols": ("2314", "2345", "2419", "2498", "3491", "4906", "4977", "4991", "6285", "6214"),
        "us_symbols": ("ASTS", "RKLB", "IRDM", "VSAT", "GSAT", "LUNR", "BA", "LMT"),
        "us_industries": ("Communication Equipment", "Aerospace & Defense", "Telecom Services"),
        "search_queries": ("low earth orbit satellite", "satellite communication", "space stocks"),
    },
    "人形機器人": {
        "tw_codes": (),
        "tw_symbols": ("1590", "2049", "2308", "2317", "2359", "2360", "2464", "3017", "6166", "4576"),
        "us_symbols": ("TSLA", "NVDA", "ISRG", "ROK", "TER", "SYM", "PATH", "ABBNY"),
        "us_industries": ("Specialty Industrial Machinery", "Scientific & Technical Instruments", "Semiconductors"),
        "search_queries": ("humanoid robot", "robotics automation", "industrial robotics"),
    },
    "雲端": {
        "tw_codes": ("30", "36", "25"),
        "tw_symbols": ("2395", "3029", "3088", "3227", "4953", "8050"),
        "us_symbols": ("MSFT", "AMZN", "GOOGL", "CRM", "SNOW", "NET", "DDOG", "ORCL"),
        "us_industries": ("Software - Infrastructure", "Software - Application", "Information Technology Services"),
        "us_sectors": ("Technology",),
        "search_queries": ("cloud computing", "SaaS", "data center"),
    },
    "電動車": {
        "tw_codes": ("12", "05", "28", "25"),
        "tw_symbols": ("2308", "2317", "2354", "2497", "3019", "3665", "4721", "6271"),
        "us_symbols": ("TSLA", "RIVN", "LCID", "GM", "F", "ON", "ALB", "CHPT"),
        "us_industries": ("Auto Manufacturers", "Auto Parts", "Electrical Equipment & Parts"),
        "search_queries": ("electric vehicle", "EV battery", "autonomous vehicle"),
    },
    "綠能": {
        "tw_codes": ("35", "23", "05", "06"),
        "tw_symbols": ("1303", "1513", "1609", "2308", "2406", "3576", "6443", "6806"),
        "us_symbols": ("FSLR", "ENPH", "SEDG", "NEE", "BE", "RUN", "ARRY"),
        "us_industries": ("Solar", "Utilities - Renewable", "Electrical Equipment & Parts"),
        "search_queries": ("renewable energy", "solar", "energy storage"),
    },
    "資安": {
        "tw_codes": ("30", "36"),
        "tw_symbols": ("3029", "6148", "6214", "6690", "6791", "8050"),
        "us_symbols": ("CRWD", "PANW", "ZS", "FTNT", "OKTA", "S", "NET"),
        "us_industries": ("Software - Infrastructure",),
        "search_queries": ("cybersecurity", "zero trust security", "cloud security"),
    },
    "生技": {
        "tw_codes": ("22",),
        "tw_symbols": ("1701", "1707", "1760", "1783", "1795", "4123", "4142", "4162", "6446", "6547"),
        "us_symbols": ("AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "BMRN"),
        "us_industries": ("Biotechnology", "Drug Manufacturers - General", "Healthcare Plans"),
        "search_queries": ("biotech", "pharmaceutical", "healthcare"),
    },
    "生技醫療": {
        "tw_codes": ("22",),
        "tw_symbols": ("1701", "1707", "1760", "1783", "1795", "4123", "4142", "4162", "6446", "6547"),
        "us_symbols": ("AMGN", "GILD", "VRTX", "REGN", "BIIB", "MRNA", "BMRN"),
        "us_industries": ("Biotechnology", "Drug Manufacturers - General", "Healthcare Plans"),
        "search_queries": ("biotech", "pharmaceutical", "healthcare"),
    },
    "金融": {
        "tw_codes": ("17",),
        "tw_symbols": ("2801", "2880", "2881", "2882", "2883", "2884", "2885", "2886", "2891", "2892"),
        "us_symbols": ("JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "AXP"),
        "us_industries": ("Banks - Diversified", "Banks - Regional", "Capital Markets"),
        "us_sectors": ("Financial Services",),
        "search_queries": ("bank stocks", "financial services"),
    },
    "航運": {
        "tw_codes": ("15",),
        "tw_symbols": ("2603", "2605", "2606", "2607", "2609", "2610", "2615", "2618", "2634", "2637"),
        "us_symbols": ("MATX", "ZIM", "DAC", "UAL", "DAL", "FDX", "UPS"),
        "us_industries": ("Marine Shipping", "Airlines", "Integrated Freight & Logistics"),
        "search_queries": ("shipping stocks", "airline stocks", "logistics"),
    },
}
US_EXCHANGES = {
    "NYQ",
    "NMS",
    "NGM",
    "NCM",
    "ASE",
    "PCX",
    "NAS",
    "BTS",
    "PNK",
    "PNQ",
    "OTC",
    "OQB",
    "OQX",
    "OEM",
}
OTC_EXCHANGES = {"PNK", "PNQ", "OTC", "OQB", "OQX", "OEM"}


@dataclass(frozen=True)
class ConceptLookupResult:
    """Online concept lookup output with source attempts and warnings."""

    query: str
    matches: pd.DataFrame
    warnings: tuple[str, ...] = ()
    attempts: tuple[str, ...] = ()


def load_concept_stocks(path: str | Path = DEFAULT_CONCEPT_STOCK_PATH) -> pd.DataFrame:
    """Load the local concept-stock CSV and normalize its schema."""

    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    frame = pd.read_csv(file_path, dtype=str).fillna("")
    return normalize_concept_stocks(frame)


def normalize_concept_stocks(frame: pd.DataFrame, *, preserve_extra: bool = False) -> pd.DataFrame:
    """Return a normalized concept-stock table without mutating the input."""

    output = frame.copy(deep=True)
    extra_columns = [column for column in output.columns if column not in CONCEPT_COLUMNS]
    for column in CONCEPT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    columns = [*CONCEPT_COLUMNS, *(extra_columns if preserve_extra else ())]
    output = output.loc[:, columns]
    for column in CONCEPT_COLUMNS:
        output[column] = output[column].fillna("").astype(str).str.strip()
    output["market"] = output["market"].str.upper()
    output["market_label"] = output["market"].map(MARKET_LABELS).fillna(output["market"])
    output = output.drop_duplicates(subset=["symbol", "market", "concept"]).reset_index(drop=True)
    return output


def search_concept_stocks(
    query: str,
    concepts: pd.DataFrame,
    *,
    markets: Sequence[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Search concept stocks by industry, concept, keyword, name, or symbol.

    Results are ranked by transparent keyword matching. The function does not
    fetch live market data and does not imply any stock is suitable to buy.
    """

    normalized = normalize_concept_stocks(concepts)
    query_text = str(query or "").strip()
    if not query_text:
        return pd.DataFrame(columns=[*normalized.columns, "match_score", "match_reason"])

    market_filter = {market.strip().upper() for market in markets or () if str(market).strip()}
    if market_filter:
        normalized = normalized.loc[normalized["market"].isin(market_filter)]
    if normalized.empty:
        return pd.DataFrame(columns=[*normalized.columns, "match_score", "match_reason"])

    tokens = _query_tokens(query_text)
    scored_rows: list[dict[str, object]] = []
    for _, row in normalized.iterrows():
        score, reason = _match_score(row, tokens)
        if score <= 0:
            continue
        item = row.to_dict()
        item["match_score"] = score
        item["match_reason"] = reason
        scored_rows.append(item)

    if not scored_rows:
        return pd.DataFrame(columns=[*normalized.columns, "match_score", "match_reason"])

    result = pd.DataFrame(scored_rows)
    result = result.sort_values(
        ["match_score", "market", "symbol"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    if limit is not None:
        result = result.head(int(limit)).reset_index(drop=True)
    return result


def concept_market_summary(matches: pd.DataFrame) -> pd.DataFrame:
    """Return match counts grouped by market label."""

    if matches.empty or "market_label" not in matches.columns:
        return pd.DataFrame(columns=["市場", "檔數"])
    summary = (
        matches.groupby("market_label", dropna=False)["symbol"]
        .nunique()
        .reset_index()
        .rename(columns={"market_label": "市場", "symbol": "檔數"})
    )
    return summary.sort_values("市場").reset_index(drop=True)


def _query_tokens(query: str) -> tuple[str, ...]:
    normalized = _normalize_text(query)
    raw_tokens = {token for token in normalized.replace(",", " ").replace("，", " ").split() if token}
    raw_tokens.add(normalized)
    for alias_key, aliases in QUERY_ALIASES.items():
        if _normalize_text(alias_key) == normalized or normalized in {_normalize_text(item) for item in aliases}:
            raw_tokens.update(_normalize_text(item) for item in aliases)
    return tuple(sorted(raw_tokens, key=len, reverse=True))


def _match_score(row: pd.Series, tokens: Iterable[str]) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []
    symbol = _normalize_text(row.get("symbol", ""))
    name = _normalize_text(row.get("name", ""))
    industry = _normalize_text(row.get("industry", ""))
    concept = _normalize_text(row.get("concept", ""))
    keywords = _normalize_text(row.get("keywords", ""))
    haystack = " ".join((symbol, name, industry, concept, keywords))

    for token in tokens:
        if not token:
            continue
        if token == symbol:
            score += 120
            reasons.append("股票代號相符")
        if token == industry:
            score += 100
            reasons.append("產業完全相符")
        elif token in industry:
            score += 70
            reasons.append("產業包含關鍵字")
        if token == concept:
            score += 90
            reasons.append("概念完全相符")
        elif token in concept:
            score += 65
            reasons.append("概念包含關鍵字")
        if token in keywords:
            score += 45
            reasons.append("關鍵字相符")
        if token in name:
            score += 35
            reasons.append("公司名稱相符")
        elif token in haystack:
            score += 15

    reason_text = "、".join(dict.fromkeys(reasons)) or "文字關聯"
    return score, reason_text


def lookup_concept_stocks_online(
    query: str,
    *,
    markets: Sequence[str] = ("TWSE", "TPEX", "US"),
    max_results_per_source: int = 25,
    timeout_seconds: int = 20,
    include_local_fallback: bool = False,
    local_path: str | Path = DEFAULT_CONCEPT_STOCK_PATH,
) -> ConceptLookupResult:
    """Look up concept stocks from online sources, grouped across Taiwan and US markets."""

    query_text = str(query or "").strip()
    if not query_text:
        return ConceptLookupResult(query="", matches=pd.DataFrame(columns=[*CONCEPT_COLUMNS, "market_label"]))

    market_set = {str(market).upper() for market in markets}
    profiles = _concept_profiles_for_query(query_text)
    frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    attempts: list[str] = []

    if {"TWSE", "TPEX"} & market_set:
        try:
            taiwan_frames = [
                _lookup_taiwan_online(
                    query_text,
                    markets=tuple(market_set),
                    profile=profile,
                    timeout_seconds=timeout_seconds,
                )
                for profile in profiles
            ]
            taiwan = _combine_lookup_frames(taiwan_frames, query_text)
            attempts.append(f"TWSE/TPEx OpenAPI：取得 {len(taiwan)} 檔")
            if not taiwan.empty:
                frames.append(taiwan)
        except Exception as exc:
            warnings.append(f"台股官方 OpenAPI 查詢失敗：{exc}")
            attempts.append("TWSE/TPEx OpenAPI：失敗")

    if "US" in market_set:
        try:
            us_frames = [
                _lookup_us_online(
                    query_text,
                    profile=profile,
                    max_results=max_results_per_source,
                )
                for profile in profiles
            ]
            us = _combine_lookup_frames(us_frames, query_text)
            attempts.append(f"yfinance：取得 {len(us)} 檔")
            if not us.empty:
                frames.append(us)
        except Exception as exc:
            warnings.append(f"美股 yfinance 查詢失敗：{exc}")
            attempts.append("yfinance：失敗")

    if include_local_fallback:
        local_matches = search_concept_stocks(
            query_text,
            load_concept_stocks(local_path),
            markets=tuple(market_set),
            limit=max_results_per_source * max(1, len(market_set)),
        )
        attempts.append(f"本機備援清單：取得 {len(local_matches)} 檔")
        if not local_matches.empty:
            local_matches = local_matches.copy(deep=True)
            local_matches["source"] = local_matches["source"].replace("", "local_fallback")
            frames.append(local_matches)

    if not frames:
        return ConceptLookupResult(
            query=query_text,
            matches=pd.DataFrame(columns=[*CONCEPT_COLUMNS, "market_label", "match_score", "match_reason"]),
            warnings=tuple(warnings or ("沒有找到可用的線上結果；請換一個產業關鍵字或啟用本機備援清單。",)),
            attempts=tuple(attempts),
        )

    combined = normalize_concept_stocks(
        pd.concat(frames, ignore_index=True, sort=False),
        preserve_extra=True,
    )
    combined = _rank_combined_results(combined, query_text, profiles[0])
    return ConceptLookupResult(
        query=query_text,
        matches=combined,
        warnings=tuple(warnings),
        attempts=tuple(attempts),
    )


def _lookup_taiwan_online(
    query: str,
    *,
    markets: Sequence[str],
    profile: dict[str, tuple[str, ...]],
    timeout_seconds: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if "TWSE" in markets:
        frames.append(_fetch_twse_companies(timeout_seconds=timeout_seconds))
    if "TPEX" in markets:
        frames.append(_fetch_tpex_companies(timeout_seconds=timeout_seconds))
    if not frames:
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    companies = pd.concat(frames, ignore_index=True, sort=False)
    if companies.empty:
        return pd.DataFrame(columns=[*CONCEPT_COLUMNS, "industry_code", "match_score", "match_reason"])
    if "industry_code" not in companies.columns:
        companies["industry_code"] = ""
    tokens = _query_tokens(query)
    tw_codes = set(profile.get("tw_codes", ()))
    tw_symbols = set(profile.get("tw_symbols", ()))
    concept_notes = tuple(profile.get("note", ()))
    profile_key = _profile_concept_label(profile, query)
    relation_type = _profile_relation_type(profile)
    relation_rank = _profile_relation_rank(profile)
    stage, stage_note = _profile_stage(profile)
    if tw_symbols:
        symbol_matches = companies.loc[companies["symbol"].isin(tw_symbols)].copy()
    else:
        symbol_matches = pd.DataFrame(columns=companies.columns)
    if tw_codes:
        code_matches = companies.loc[companies["industry_code"].isin(tw_codes)].copy()
    else:
        code_matches = pd.DataFrame(columns=companies.columns)
    text_matches = _filter_by_text(companies, tokens)
    output = pd.concat([symbol_matches, code_matches, text_matches], ignore_index=True, sort=False)
    if output.empty:
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    output = output.drop_duplicates(subset=["symbol", "market"]).copy()
    output["concept"] = profile_key
    output["relation_type"] = output.apply(
        lambda row: _taiwan_relation_type(row, tw_codes, tw_symbols, relation_type, profile_key),
        axis=1,
    )
    output["relation_rank"] = output.apply(
        lambda row: _taiwan_relation_rank(row, tw_codes, tw_symbols, relation_rank, profile_key),
        axis=1,
    )
    output["price_reaction_stage"] = stage
    output["stage_note"] = stage_note
    output["keywords"] = output["industry"]
    output["match_score"] = output.apply(
        lambda row: _taiwan_match_score(row, tokens, tw_codes, tw_symbols),
        axis=1,
    )
    output["match_reason"] = output.apply(
        lambda row: _taiwan_match_reason(row, tw_codes, tw_symbols),
        axis=1,
    )
    output["source"] = output.apply(
        lambda row: _taiwan_source_label(row, tw_symbols),
        axis=1,
    )
    output["note"] = output.apply(
        lambda row: _taiwan_note_text(row, tw_symbols, concept_notes, profile_key),
        axis=1,
    )
    return output


def _lookup_us_online(
    query: str,
    *,
    profile: dict[str, tuple[str, ...]],
    max_results: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in profile.get("us_symbols", ()):
        rows.extend(_search_yfinance_us(symbol, max_results=1))
    for industry in profile.get("us_industries", ()):
        rows.extend(_screen_yfinance_us("industry", industry, max_results=max_results))
    for sector in profile.get("us_sectors", ()):
        rows.extend(_screen_yfinance_us("sector", sector, max_results=max_results))
    search_queries = profile.get("search_queries", ()) or (query,)
    for search_query in search_queries:
        rows.extend(_search_yfinance_us(search_query, max_results=max_results))
    if not rows:
        return pd.DataFrame(columns=CONCEPT_COLUMNS)
    output = pd.DataFrame(rows)
    output = normalize_concept_stocks(output, preserve_extra=True)
    output = output.drop_duplicates(subset=["symbol", "market"]).reset_index(drop=True)
    output["match_score"] = output.get("match_score", 50)
    output["match_reason"] = output.get("match_reason", "線上資料相符")
    profile_key = _profile_concept_label(profile, query)
    concept_notes = tuple(profile.get("note", ()))
    relation_type = _profile_relation_type(profile, default="美股線上搜尋 / 產業關聯")
    relation_rank = _profile_relation_rank(profile, default=4)
    output["concept"] = profile_key
    output["relation_type"] = output["symbol"].map(
        lambda symbol: _symbol_relation_type(profile_key, symbol, relation_type),
    )
    output["relation_rank"] = output["symbol"].map(
        lambda symbol: _symbol_relation_rank(profile_key, symbol, relation_rank),
    )
    output["note"] = output.apply(
        lambda row: _symbol_note_text(
            profile_key,
            row.get("symbol", ""),
            row.get("note", ""),
            concept_notes,
        ),
        axis=1,
    )
    stage, stage_note = _profile_stage(profile)
    output["price_reaction_stage"] = stage
    output["stage_note"] = stage_note
    return output


def _fetch_twse_companies(*, timeout_seconds: int) -> pd.DataFrame:
    rows = _download_json(TWSE_COMPANY_URL, timeout_seconds=timeout_seconds)
    output = []
    for row in rows:
        code = str(row.get("產業別", "")).strip()
        output.append(
            {
                "symbol": str(row.get("公司代號", "")).strip(),
                "name": str(row.get("公司簡稱") or row.get("公司名稱") or "").strip(),
                "market": "TWSE",
                "exchange": "TWSE",
                "industry": TW_INDUSTRY_CODES.get(code, code),
                "industry_code": code,
                "concept": "",
                "keywords": f"{TW_INDUSTRY_CODES.get(code, code)};{row.get('英文簡稱', '')}",
                "source": "TWSE OpenAPI",
                "note": "線上官方公司基本資料；產業為交易所分類，不代表完整概念股清單。",
            }
        )
    return pd.DataFrame(output, columns=[*CONCEPT_COLUMNS, "industry_code"])


def _fetch_tpex_companies(*, timeout_seconds: int) -> pd.DataFrame:
    rows = _download_json(TPEX_COMPANY_URL, timeout_seconds=timeout_seconds)
    output = []
    for row in rows:
        code = str(row.get("SecuritiesIndustryCode", "")).strip()
        output.append(
            {
                "symbol": str(row.get("SecuritiesCompanyCode", "")).strip(),
                "name": str(row.get("CompanyAbbreviation") or row.get("CompanyName") or "").strip(),
                "market": "TPEX",
                "exchange": "TPEx",
                "industry": TW_INDUSTRY_CODES.get(code, code),
                "industry_code": code,
                "concept": "",
                "keywords": f"{TW_INDUSTRY_CODES.get(code, code)};{row.get('Symbol', '')}",
                "source": "TPEx OpenAPI",
                "note": "線上官方公司基本資料；產業為交易所分類，不代表完整概念股清單。",
            }
        )
    return pd.DataFrame(output, columns=[*CONCEPT_COLUMNS, "industry_code"])


def _screen_yfinance_us(field: str, value: str, *, max_results: int) -> list[dict[str, object]]:
    query = EquityQuery("eq", [field, value])
    configure_yfinance_cache()
    response = yf.screen(query, count=max_results, sortField="intradaymarketcap", sortAsc=False)
    quotes = response.get("quotes", []) if isinstance(response, dict) else []
    return [_quote_to_concept_row(quote, source=f"yfinance screen:{field}={value}") for quote in quotes if _is_us_equity(quote)]


def _search_yfinance_us(query: str, *, max_results: int) -> list[dict[str, object]]:
    configure_yfinance_cache()
    search = yf.Search(
        query,
        max_results=max_results,
        news_count=0,
        lists_count=0,
        include_research=False,
        timeout=20,
        raise_errors=False,
    )
    return [_quote_to_concept_row(quote, source=f"yfinance search:{query}") for quote in search.quotes if _is_us_equity(quote)]


def _quote_to_concept_row(quote: dict[str, object], *, source: str) -> dict[str, object]:
    industry = str(quote.get("industryDisp") or quote.get("industry") or "")
    sector = str(quote.get("sectorDisp") or quote.get("sector") or "")
    exchange = str(quote.get("exchange") or quote.get("fullExchangeName") or "")
    note = "yfinance 線上查詢結果；可能包含延遲、缺漏或排序偏差，請再確認。"
    if exchange.strip().upper() in OTC_EXCHANGES:
        note += " 此標的屬於 OTC / 粉單或店頭交易，流動性、揭露品質與成交風險可能較高。"
    return {
        "symbol": str(quote.get("symbol", "")).strip(),
        "name": str(quote.get("longname") or quote.get("shortname") or quote.get("symbol") or "").strip(),
        "market": "US",
        "exchange": exchange,
        "industry": industry or sector,
        "concept": industry or sector,
        "keywords": ";".join(item for item in (sector, industry, str(quote.get("shortname", ""))) if item),
        "source": source,
        "note": note,
        "match_score": 70,
        "match_reason": "yfinance 產業/搜尋結果相符",
    }


def _download_json(url: str, *, timeout_seconds: int, retries: int = 2) -> list[dict[str, object]]:
    request = urllib.request.Request(url, headers={"User-Agent": "StockTool/0.1"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
            data = json.loads(payload.decode("utf-8-sig"))
            break
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                raise
            time.sleep(0.5 * (attempt + 1))
    else:
        raise ValueError(f"線上資料下載失敗：{last_error}")
    if not isinstance(data, list):
        raise ValueError("線上資料格式不是列表。")
    return data


def _concept_profile(query: str) -> dict[str, tuple[str, ...]]:
    return _concept_profiles_for_query(query)[0]


def _concept_profiles_for_query(query: str) -> tuple[dict[str, tuple[str, ...]], ...]:
    keys = _concept_profile_keys(query)
    if keys:
        return tuple(_copy_concept_profile(key) for key in keys)
    normalized = _normalize_text(query)
    matched_codes = tuple(code for code, name in TW_INDUSTRY_CODES.items() if normalized in _normalize_text(name))
    return (
        {
            "_profile_key": (query,),
            "tw_codes": matched_codes,
            "us_industries": (),
            "search_queries": (query,),
            "relation_type": ("交易所產業分類 / 線上搜尋",),
            "relation_rank": ("2",),
        },
    )


def _concept_profile_keys(query: str) -> tuple[str, ...]:
    normalized = _normalize_text(query)
    candidates: list[tuple[int, int, str]] = []
    for key, profile in CONCEPT_PROFILES.items():
        aliases = {_normalize_text(key), *(_normalize_text(item) for item in QUERY_ALIASES.get(key, ()))}
        for alias in aliases:
            if not alias:
                continue
            if normalized == _normalize_text(key):
                candidates.append((3, len(alias), key))
            elif normalized == alias:
                candidates.append((2, len(alias), key))
            elif alias in normalized:
                candidates.append((1, len(alias), key))
    if not candidates:
        return ()
    _, _, key = max(candidates)
    profile = CONCEPT_PROFILES[key]
    return tuple(dict.fromkeys((key, *profile.get("related_profiles", ()))))


def _copy_concept_profile(key: str) -> dict[str, tuple[str, ...]]:
    profile = {name: tuple(values) for name, values in CONCEPT_PROFILES[key].items()}
    profile["_profile_key"] = (key,)
    return profile


def _combine_lookup_frames(frames: Sequence[pd.DataFrame], query: str) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame(columns=[*CONCEPT_COLUMNS, "market_label", "match_score", "match_reason"])
    combined = normalize_concept_stocks(pd.concat(non_empty, ignore_index=True, sort=False), preserve_extra=True)
    return _rank_combined_results(combined, query, {})


def _profile_concept_label(profile: dict[str, tuple[str, ...]], fallback: str) -> str:
    key = next(iter(profile.get("_profile_key", ())), "")
    return key or fallback


def _profile_relation_type(profile: dict[str, tuple[str, ...]], *, default: str = "概念 / 題材關聯") -> str:
    relation = tuple(profile.get("relation_type", ()))
    return str(relation[0]) if relation else default


def _profile_relation_rank(profile: dict[str, tuple[str, ...]], *, default: int = 1) -> int:
    values = tuple(profile.get("relation_rank", ()))
    if not values:
        return int(default)
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return int(default)


def _profile_stage(profile: dict[str, tuple[str, ...]]) -> tuple[str, str]:
    stages = tuple(profile.get("price_reaction_stage", ()))
    notes = tuple(profile.get("stage_note", ()))
    stage, note = CONCEPT_STAGE_DEFAULT
    if stages:
        stage = str(stages[0])
    if notes:
        note = str(notes[0])
    return stage, note


def _symbol_relation_type(profile_key: str, symbol: object, default: str) -> str:
    """Return a symbol-specific concept role when the curated profile defines one."""

    symbol_key = str(symbol or "").strip().upper()
    return CONCEPT_SYMBOL_RELATION_TYPES.get(profile_key, {}).get(symbol_key, default)


def _symbol_relation_rank(profile_key: str, symbol: object, default: int) -> int:
    """Return a symbol-specific sort rank when the curated profile defines one."""

    symbol_key = str(symbol or "").strip().upper()
    return int(CONCEPT_SYMBOL_RELATION_RANKS.get(profile_key, {}).get(symbol_key, default))


def _symbol_note_text(
    profile_key: str,
    symbol: object,
    note: object,
    concept_notes: tuple[str, ...] = (),
) -> str:
    """Return a symbol-specific research note without discarding provider warnings."""

    base_note = str(note or "").strip()
    symbol_key = str(symbol or "").strip().upper()
    role_note = CONCEPT_SYMBOL_NOTES.get(profile_key, {}).get(symbol_key, "")
    if role_note and base_note:
        return f"{role_note} {base_note}"
    if role_note:
        return role_note
    if concept_notes:
        concept_note = str(concept_notes[0])
        if base_note:
            return f"{concept_note} {base_note}"
        return concept_note
    return base_note


def _filter_by_text(frame: pd.DataFrame, tokens: Sequence[str]) -> pd.DataFrame:
    if frame.empty:
        return frame
    haystack = (
        frame["symbol"].astype(str)
        + " "
        + frame["name"].astype(str)
        + " "
        + frame["industry"].astype(str)
        + " "
        + frame["keywords"].astype(str)
    ).map(_normalize_text)
    mask = pd.Series(False, index=frame.index)
    for token in tokens:
        if _use_taiwan_text_token(token):
            mask = mask | haystack.str.contains(token, regex=False)
    return frame.loc[mask].copy()


def _use_taiwan_text_token(token: str) -> bool:
    """Avoid noisy Taiwan company matches from short English abbreviations."""

    if not token or len(token) <= 1:
        return False
    if token.isascii() and len(token) < 4:
        return False
    return True


def _taiwan_match_score(
    row: pd.Series,
    tokens: Sequence[str],
    tw_codes: set[str],
    tw_symbols: set[str],
) -> int:
    score = 140 if str(row.get("symbol", "")).strip() in tw_symbols else 0
    score += 100 if row.get("industry_code") in tw_codes else 0
    text = _normalize_text(" ".join(str(row.get(column, "")) for column in ("symbol", "name", "industry", "keywords")))
    score += sum(20 for token in tokens if token and token in text)
    return score


def _taiwan_match_reason(row: pd.Series, tw_codes: set[str], tw_symbols: set[str]) -> str:
    symbol = str(row.get("symbol", "")).strip()
    if symbol in tw_symbols:
        return "內建概念題材對照 + 官方公司資料確認"
    if row.get("industry_code") in tw_codes:
        return "官方產業分類相符"
    return "公司資料文字相符"


def _taiwan_relation_type(
    row: pd.Series,
    tw_codes: set[str],
    tw_symbols: set[str],
    profile_relation: str,
    profile_key: str,
) -> str:
    symbol = str(row.get("symbol", "")).strip()
    if symbol in tw_symbols:
        return _symbol_relation_type(profile_key, symbol, profile_relation or "內建題材關聯")
    if row.get("industry_code") in tw_codes:
        return "交易所產業分類"
    return "公司資料文字關聯"


def _taiwan_relation_rank(
    row: pd.Series,
    tw_codes: set[str],
    tw_symbols: set[str],
    profile_rank: int,
    profile_key: str,
) -> int:
    symbol = str(row.get("symbol", "")).strip()
    if symbol in tw_symbols:
        return _symbol_relation_rank(profile_key, symbol, int(profile_rank))
    if row.get("industry_code") in tw_codes:
        return 2
    return 3


def _taiwan_source_label(row: pd.Series, tw_symbols: set[str]) -> str:
    source = str(row.get("source", "")).strip() or "官方公司資料"
    symbol = str(row.get("symbol", "")).strip()
    if symbol in tw_symbols:
        return f"內建概念題材對照 + {source}"
    return source


def _taiwan_note_text(
    row: pd.Series,
    tw_symbols: set[str],
    concept_notes: tuple[str, ...] = (),
    profile_key: str = "",
) -> str:
    note = str(row.get("note", "")).strip()
    symbol = str(row.get("symbol", "")).strip()
    if symbol not in tw_symbols:
        return note
    role_note = _symbol_note_text(profile_key, symbol, "", concept_notes)
    if role_note:
        return role_note
    if concept_notes:
        return str(concept_notes[0])
    return (
        "概念關聯為內建題材對照；公司名稱、市場與產業來自線上官方公司資料，"
        "不代表完整概念股清單。"
    )


def _rank_combined_results(frame: pd.DataFrame, query: str, profile: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    output = frame.copy(deep=True)
    if "match_score" not in output.columns:
        output["match_score"] = 0
    output["match_score"] = pd.to_numeric(output["match_score"], errors="coerce").fillna(0).astype(int)
    if "match_reason" not in output.columns:
        output["match_reason"] = ""
    if "relation_type" not in output.columns:
        output["relation_type"] = ""
    market_order = {"TWSE": 0, "TPEX": 1, "US": 2}
    output["_market_order"] = output["market"].map(market_order).fillna(99)
    if "relation_rank" in output.columns:
        output["_relation_order"] = pd.to_numeric(output["relation_rank"], errors="coerce").fillna(4).astype(int)
    else:
        output["_relation_order"] = output["relation_type"].map(_relation_sort_order)
    output = output.sort_values(
        ["_relation_order", "match_score", "_market_order", "symbol"],
        ascending=[True, False, True, True],
    )
    output = output.drop(columns=["_market_order", "_relation_order"]).reset_index(drop=True)
    return output


def _relation_sort_order(value: object) -> int:
    text = str(value or "")
    if "直接" in text:
        return 0
    if "供應鏈" in text or "題材" in text:
        return 1
    if "產業分類" in text:
        return 2
    if "文字" in text:
        return 3
    return 4


def _is_us_equity(quote: dict[str, object]) -> bool:
    symbol = str(quote.get("symbol", "")).strip()
    exchange = str(quote.get("exchange", "")).strip().upper()
    quote_type = str(quote.get("quoteType", "")).strip().upper()
    if not symbol or quote_type != "EQUITY":
        return False
    if "." in symbol or "=" in symbol:
        return False
    return exchange in US_EXCHANGES or str(quote.get("fullExchangeName", "")).lower() in {
        "nasdaq",
        "nyse",
        "nyse arca",
        "american stock exchange",
    }


def _normalize_text(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "")
