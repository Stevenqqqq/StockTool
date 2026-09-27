"""Beginner-facing Chinese explanations, with facts separated from mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
import re

from stock_tool.company_dossier import CompanyDossier


@dataclass(frozen=True)
class CompanyExplanation:
    heading: str
    text: str
    kind: str
    evidence_indices: tuple[int, ...] = ()


def explain_company(dossier: CompanyDossier) -> tuple[CompanyExplanation, ...]:
    """Explain confirmed exposures without inventing revenue mix or realized risks."""
    facts = dossier.facts
    product_ids = tuple(i for i, f in enumerate(facts) if f.section == "產品與技術")
    product_text = " ".join(facts[i].excerpt for i in product_ids)
    role_ids = tuple(i for i, f in enumerate(facts) if f.section == "公司角色")
    role_text = " ".join(facts[i].excerpt for i in role_ids)
    items: list[CompanyExplanation] = []
    if re.search(r"DDR|DRAM|NAND|NOR.?Flash", product_text, re.I):
        names = tuple(
            dict.fromkeys(
                re.findall(r"(?:LP)?DDR\s*[1-6]|DRAM|NAND|NOR\s*Flash", product_text, re.I)
            )
        )
        items.append(
            CompanyExplanation(
                "這家公司靠什麼做生意",
                "官網列出的產品包括「"
                + "、".join(names)
                + "」。這些是電子設備儲存或暫存資料的記憶體產品，不是完整電腦。"
                + (
                    "公司自述從事 IC 設計，表示它的角色是設計晶片；不能因此假定它擁有晶圓廠。"
                    if re.search(r"IC\s*設計|fabless", role_text, re.I)
                    else ""
                )
                + "產品資料能確認它賣什麼，但目前不能確認哪項產品貢獻最多營收、客戶占比或代工安排。",
                "公司事實與資料缺口",
                (*role_ids, *product_ids)[:6],
            )
        )
        items.append(
            CompanyExplanation(
                "規格怎麼看",
                "DDR 後面的數字代表技術世代；DDR4 與 DDR5 是不同世代，不是獲利排名。Gb 是單顆容量，Mbps 是傳輸速率。"
                "DRAM 用於工作中的暫存資料；Flash 用於斷電後仍要保留的資料。官網提到量產只證明該來源當時的說法；日期未知就不能當成最新進度。",
                "名詞解釋",
            )
        )
        items.append(
            CompanyExplanation(
                "營運結構與循環要怎麼理解",
                "閱讀這類公司的營運，可先拆成『賣出多少顆 × 平均售價』，再看製造、封裝測試等成本如何影響毛利。"
                "下游客戶補庫存時訂單可能增加，去庫存時可能減少；這是產業機制，尚未證明這家公司目前處於哪一段循環。"
                "本次尚未確認各產品營收占比、近期售價／出貨、存貨及毛利趨勢。",
                "理解框架，非本期營運結論",
            )
        )
        items.append(
            CompanyExplanation(
                "針對這些產品，最需要追問的風險",
                "公司既然列有不同記憶體產品，就要查客戶是否轉向新世代、原有產品價格是否下跌，以及庫存是否難以出售。"
                "產品世代多不代表收入分散；也不能把 DDR4 當成 HBM 或直接認定受惠 AI。"
                "目前缺近期營收結構與庫存證據，這些是待驗證風險，不是已發生虧損的判斷。",
                "依已確認產品提出的研究判斷",
                product_ids[:3],
            )
        )
    elif re.search(
        r"Consumer\s*(?:&|and)\s*Community Banking|Commercial\s*(?:&|and)\s*Investment Bank|Asset\s*(?:&|and)\s*Wealth Management",
        product_text,
        re.I,
    ):
        divisions = (
            (
                r"Consumer\s*(?:&|and)\s*Community Banking",
                "消費與社區銀行：面向個人及小型企業，銀行業通常透過存放款利差與服務費賺錢",
            ),
            (
                r"Commercial\s*(?:&|and)\s*Investment Bank",
                "商業與投資銀行：服務企業及機構，業務可能涉及融資、交易與顧問服務",
            ),
            (
                r"Asset\s*(?:&|and)\s*Wealth Management",
                "資產與財富管理：替客戶管理或配置資產，通常收取管理及相關服務費",
            ),
        )
        found = [
            description
            for pattern, description in divisions
            if re.search(pattern, product_text, re.I)
        ]
        items.append(
            CompanyExplanation(
                "這家公司靠什麼做生意",
                "官網確認的業務部門包括："
                + "；".join(found)
                + "。以上收益方式是業務名詞的解釋；各項實際收入與占比仍須核對分部財報。",
                "公司業務與名詞解釋",
                product_ids[:4],
            )
        )
        items.append(
            CompanyExplanation(
                "營運結構要看什麼",
                "不能用晶片世代衡量銀行。要分開看利息收入減去資金成本、手續費收入，以及貸款收不回來所提列的信用成本。資產管理規模也不等於公司自己的收入；本次尚未完整核對分部占比。",
                "理解框架，非本期營運結論",
            )
        )
        items.append(
            CompanyExplanation(
                "循環與優先研究風險",
                "利率變動同時影響放款收益與存款成本，升息不一定增加獲利。經濟轉弱可能提高違約與信用成本；市場下跌可能影響交易與資產管理收入。這些對已列銀行業務有關，但是否已惡化，需要逾放、提存、淨利差及資本資料確認。管理層對監管或壓力測試的抱怨不能代替這些數據。",
                "依已確認業務提出的研究判斷",
                product_ids[:3],
            )
        )
    elif re.search(
        r"Azure|Microsoft\s*365|Dynamics\s*365|Copilot|cloud platform|SaaS", product_text, re.I
    ):
        items.append(
            CompanyExplanation(
                "這家公司靠什麼做生意",
                "官網列有軟體或雲端產品。這類業務通常向客戶收取授權、訂閱或使用量費用；這是收費模式解釋，尚不能確認各模式在本公司的收入占比。Azure 是雲端運算平台，Microsoft 365 是辦公與協作服務；只適用於下方確實列出的產品。",
                "公司產品與名詞解釋",
                product_ids[:4],
            )
        )
        items.append(
            CompanyExplanation(
                "營運與優先研究風險",
                "先查客戶是否續約、使用量是否成長，以及伺服器與研發投入是否侵蝕毛利。AI 產品推出不等於已產生重要收入；資安產品的廣告也不是公司自身資安風險的證據。以上是依產品提出的研究問題，尚未確認本期收入、續約率、資本支出或事故。",
                "依已確認產品提出的研究判斷",
                product_ids[:3],
            )
        )
    else:
        items.append(
            CompanyExplanation(
                "先理解這家公司",
                "本次尚未取得足以可靠整理成中文的業務結構，不能只靠產業標籤猜它怎麼賺錢。下方保留可核對的產品原文；收入結構、主要客戶及公司特有風險仍待補證據。",
                "資料缺口",
            )
        )
    items.append(
        CompanyExplanation(
            "現在能下什麼結論",
            "這份整理能幫助辨認產品與提出研究問題，還不足以判斷公司便宜、值得買或風險低。先核對最新年報／法說的分部收入、獲利與風險，再把未知事項補齊。",
            "研究限制",
        )
    )
    return tuple(items)
