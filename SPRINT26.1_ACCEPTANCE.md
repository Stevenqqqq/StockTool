# Sprint 26.1 implementation evidence

狀態：implementation evidence complete，等待獨立 CTO 驗收。未宣稱 CTO acceptance、發布或下一 Sprint。

## 修正範圍

- `src/stock_tool/application/daily_research_brief.py`
  - fingerprint 現在涵蓋 status、message、manifest 語意欄位、items、sources、references 與所有可見內容；只排除 generated-at 與暫存/絕對路徑。
  - 新增嚴格 `EvidenceReference` contract；每項 fact/inference/risk 都保存 reference IDs，未解析、重複或不一致引用 fail closed；AI citation IDs 保留於 manifest。
  - 事件只接受目前 portfolio/watchlist 的 market-qualified identities，避免舊 loop snapshot 洩漏。
  - JSON 為權威版本，HTML 以 content-fingerprint marker 綁定；雙檔寫入採暫存、fsync、replace 與失敗復原，上一版保持完整。
- `tests/test_daily_research_brief.py`
  - 新增 status/message/item/source/reference tamper、引用 contract、identity isolation、兩階段 replace fault-injection 回歸。
- `PRODUCT_EXECUTION_PLAN.md`
  - Sprint 26.1 改列 evidence-contract correction；Windows 排程/通知移至 Sprint 26.2。

## 自動化驗證

| 檢查 | 結果 |
|---|---|
| Sprint 26.1 targeted (`tests/test_daily_research_brief.py`) | 16 passed |
| Full pytest | 1124 passed, 2 skipped |
| Branch coverage | 83.12%（gate 78.5%） |
| `cmd /c quality_gate.bat` | exit 0；pytest、coverage、Black、Ruff、focused mypy、compile、privacy、release layout、regression 全部通過 |
| `pip check` | exit 0 |
| official `pip-audit --format json` | exit 0；0 vulnerabilities；UTF-8 JSON 可直接 parse（`artifacts/sprint26.1/pip-audit.json`；result `artifacts/sprint26.1/pip-audit-result.json`） |
| Performance hard gate | passed；`artifacts/sprint26.1/performance-final.json` |
| Source archive verify | missing/forbidden/mismatch/duplicate 全為 0 |

Quality log：`artifacts/sprint26.1/quality-gate-final.log`（SHA-256 `84EFDAF86EEC2822270646D90DC8AC15FC569ACAB2FF86CA389173BFE61D9FE2`；本次 final rebuild quality gate，exit 0）。

## 候選與安全證據

- Stable EXE：`release/staging-sprint26.1/StockTool/StockTool.exe` — `B36C7896CC4F76E4353B5EED5B41CF98BACC2730E0D47961FF8404CE33710559`
- Payload：`release/staging-sprint26.1/StockTool/versions/1.2.2/StockToolPayload.exe` — `9A03ED305EAD3A04008C651D535CDAB6EF21C122A3BF941BF27064BF23332D9F`
- Source ZIP：`artifacts/sprint26.1/sprint26.1-source.zip` — `0C75E7D12617B3CE2DBB9354A0624C221DBD2BB888F60394CA8F487EEDF4497A`（`2544074` bytes）
- Formal EXE 未變更：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`
- Candidate `--version`/health：v1.2.2、health ready；online/offline/partial 三次 guard smoke 均 passed，cleanup 與 8501/8502 listener 均為 0。摘要：`artifacts/sprint26.1/exe-smoke-summary.json`。

## Browser 與歷史證據

- 最新 hash-bound browser evidence：`artifacts/sprint26.1/browser-result.json`（SHA-256 `C8E7B0C742EA4EF78FF97F406BF2CBF739A62A70DC8FC8E72F391A19EC431A0E`）。線上研究首頁與「產生今日研究簡報」畫面各有 screenshot、DOM、active console（error 0）及 transport/guard 證據；offline/partial 明確標為 guarded EXE/transport smoke，不冒充瀏覽器畫面。
- 歷史失敗 guard 保留且未引用為成功：`artifacts/sprint26/browser-run-online/guard-result.json`；索引：`artifacts/sprint26.1/browser-history-index.json`。
- 原生 Chrome 100%/125%/150% 仍為 `deferred_to_formal_release`，未以 viewport resize 冒充。
- Performance JSON SHA-256：`B5689C4F3C6AAF67E3553E046B7DB4B14C74F8D1577EDD16FF64056CB68D2FB5`；pip-audit JSON SHA-256：`14BA763B074F49C21B076A1A851DC119160BB453CDCBC8913D4C4FF345E29773`。

## 資料保全與限制

- 每次候選啟動均經 `scripts/evidence_launcher.py`，使用全新 temporary `STOCK_TOOL_USER_DATA_DIR`；real-data manifest 為 191 → 191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 未修改、移動或覆寫正式 EXE、正式 installer 或真實使用者資料；未發布、簽章、push、commit 或 tag。
- 仍待獨立 CTO 驗收；Windows 原生縮放及更廣泛人工瀏覽器流程是已揭露限制。
