# Sprint 25.1.1.1 implementation evidence

狀態：implementation evidence complete，等待獨立驗收；原生 Chrome zoom 仍 pending CTO verification。本文件不是 CTO acceptance，也不是發布核准。

## 依賴安全

- 只在專案 `.venv` 執行：GitPython **3.1.58**、pypdf **6.15.0**。
- `requirements/stocktool-runtime-constraints.txt` 更新為 GitPython `>=3.1.58,<4`、pypdf `>=6.15.0,<7`；`pyproject.toml` 的 pypdf 下限同步為 6.15.0。
- `pip check` exit 0；官方 `pip-audit --format=json` exit 0、**0 vulnerabilities**。證據：`artifacts/sprint25.1.1.1/pip-audit-final.json`、`pip-check.txt`、`pip-audit.log`。
- runtime SBOM：`artifacts/sprint25.1.1.1/sbom.json`，SHA-256 `69D4D6359941CDFA23F2BED2D0689F5E8015A7E9B93EE7B49153A3430004AB80`。

## 證據不可變綁定

- 每次 browser run 使用獨立 provider metadata：
  - `browser/twse-provider-metadata.json` SHA-256 `0FE0D3AF10631A8031D19FB7B161444A27BEA61437A6F9EB4C7BD5D9BD645663`，1058 bytes。
  - `browser/tpex-provider-metadata.json` SHA-256 `64C3EFC1790260773AB51B6DB9E13B2E5B0546435BE35788D5BD2737F893AE21`，803 bytes。
  - `browser/combined-provider-metadata.json` SHA-256 `B8682F3F26A97739CD69DE5D8245120BD2BB9AF2EA7E16AF9A7ECFAD918E2E01`，1913 bytes。
- `browser/provider-metadata-manifest.json` 記錄相對路徑、hash、size、fetched_at、coverage 與 source metadata；browser-result 另綁定 manifest hash。
- `browser/browser-consistency.json` 驗證 TWSE、TPEX、COMBINED 的 DOM 日期、breadth status、coverage 與 provider metadata 一致，三項 `consistent=true`。
- 官方資料：TWSE quote date 2026-08-07、breadth date 2026-06-05 → `official_stale`；TPEx quote date 2026-08-07、無可靠官方 breadth → `derived_only`。沒有將舊快取冒充 fresh online evidence。

## 測試與品質

- targeted：market/roadmap/evidence-launcher/portfolio workspace **64 passed**。
- full pytest：**1106 passed, 2 skipped**。
- quality gate：`cmd /c quality_gate.bat` exit 0；branch coverage **83.00%**；Black、Ruff、focused mypy、compileall、privacy、release layout、regression baseline 全部通過。日誌：`artifacts/sprint25.1.1.1/quality-gate.log`。
- Portfolio workspace 狀態優先序修改保留：既有 `test_missing_prices_and_fx_never_create_fake_base_weights` 已鎖定「缺 FX 且價格 stale 仍為 partial」的必要 regression；完整回歸因果已在 Sprint 25.1.1 evidence 說明，未新增無關產品行為。

## 候選與成品

- stable：`release/staging-sprint25.1.1.1/StockTool/StockTool.exe`，SHA-256 `2F6B4577563EB865ADE82F9D176419DD4E161E7159F944109C72A15D0D1B147F`，`--version` 1.2.2。
- payload：`release/staging-sprint25.1.1.1/StockTool/versions/1.2.2/StockToolPayload.exe`，SHA-256 `FBCDCD9C87F96819EA84622B577B2712E8E3BDC316C87FD6E190AB3A54910356`，`--version` 1.2.2。
- source ZIP：`artifacts/sprint25.1.1.1/sprint25.1.1.1-source.zip`，SHA-256 `55256818E92538DEC2BEC4231E754D4CAF1477DE812E4CD1D41C5DC38C0CCC3B`；獨立驗證 missing/forbidden/mismatch/duplicate 全為 0。
- binding：`artifacts/sprint25.1.1.1/candidate-hash-binding.json`。
- formal EXE SHA-256 維持 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## Performance / smoke / data preservation

- `performance-current.json` 三次量測通過既有門檻；`performance-canonical.json` 的 `canonical_current` 指向 `sprint25.1.1.1-final-candidate`，並保留歷史 Excel max 6.444 秒失敗紀錄。
- evidence launcher online、offline、partial smoke 均通過，所有結果 `zero_diff=true`；候選程序、8501/8502 listener 清理為 0。
- 真實 user-data before/after：`artifacts/sprint25.1.1.1/real-data-comparison.json`，191 檔，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。

## Browser

- `artifacts/sprint25.1.1.1/browser/browser-result.json` 綁定 final stable/payload/source hashes；TWSE、TPEx、COMBINED 各保存 screenshot、DOM、active console 與 provider metadata。active console error count 0。
- Chrome 原生 100%／125%／150% 未以 viewport resize 冒充，維持 `pending_cto_verification`，交由 Sol 最終驗收操作。

## 限制與治理

- 未修改 formal EXE、既有 installer、正式發布內容或真實使用者資料；未 commit/tag/push，未開始 Sprint 26。
- 根目錄 `artifacts_sprint25_1_1_quality.log` 為前一 correction 產生的舊 evidence copy；本次正式 quality evidence 已放於 `artifacts/sprint25.1.1.1/quality-gate.log`，未將私人絕對路徑寫入 release/source archive。
