# SPRINT 29.1 implementation evidence

本文件只記錄本輪實作證據，等待獨立 CTO 驗收，不代表正式發布或驗收通過。

## 本輪修正

- `src/stock_tool/application/macro_snapshot.py`
  - 修訂身分改為系列、觀測期間與標準化數值。
  - 重新抓取時間與完整 payload 雜湊只保留為 provenance，不再單獨建立 revised 記錄。
  - 相同數值 replay 不寫回 ledger，保留原始 bytes。
  - 非最新期間的數值變更仍會追加該期間修訂。
- `tests/test_macro_snapshot.py`
  - 新增相同數值改變抓取時間、改變 payload 雜湊、非最新期間修訂、重啟冪等與 atomic fault 測試。
- `tests/test_daily_home.py`
  - 新增首頁重要修訂不顯示 provenance-only refetch 的回歸測試。

## 主要測試與品質

- focused macro and home tests：51 passed。
- full quality gate：exit 0。
- full pytest：1324 passed、2 skipped、2 warnings。
- branch coverage：82.43 percent。
- Black：pass。
- Ruff：pass，58 source files。
- focused mypy：pass。
- compileall：pass。
- project privacy、release layout、regression baseline：pass。
- pip check：exit 0。
- official pip-audit：exit 0，98 dependencies，0 known vulnerabilities；JSON 可直接解析且為 UTF-8 無 BOM。
- git diff --check：pass。

品質輸出：

- `artifacts/sprint29.1/quality-gate-r2-final.log`
- `artifacts/sprint29.1/pip-check-r2.log`
- `artifacts/sprint29.1/pip-audit-r2.json`
- `artifacts/sprint29.1/verifier-r2-final.json`

## 最終候選與雜湊

本輪 source 修改後只建立一組 r2 staging 候選：

- stable EXE：`release/staging-sprint29.1-final-r2/StockTool/StockTool.exe`
  - size 7110952
  - SHA-256 `80F5101D352859A6A4D9CB1376F7B7448CBCD08052544F8F886348765EE5D4FB`
- payload EXE：`release/staging-sprint29.1-final-r2/StockTool/versions/1.2.2/StockToolPayload.exe`
  - size 23979723
  - SHA-256 `C8138AEFD13B8BA200B6CA2FEC76EB9AA18F08BC5574D300C16F8F49503D8A11`
- source ZIP：`release/staging-sprint29.1-r2-source.zip`
  - size 2644263
  - SHA-256 `6F3D4C5CAA2F3B0CB679F30EE6A1AA4F0AAF50E4632DF008178F85A54814B76B`
- formal EXE：`release/StockTool/StockTool.exe`
  - size 24145141
  - SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

候選 binding：`artifacts/sprint29.1/r2-final-candidate-hashes.json`。

## Performance

canonical measurement：`artifacts/sprint29.1/r2-performance/performance-canonical-r2-bound.json`。

固定資料各執行三次，`exe_health_ready` 為 3.050104、3.030002、3.025157 秒，max 3.050104 秒，小於 5 秒門檻。其他測量亦通過各自既有門檻。每次使用新的隔離資料根，所有 guard cleanup 均完成。

歷史失敗結果保留於既有 artifacts，不以本輪結果覆寫。

## Browser 與 canonical verifier

最終同 session 證據目錄：

`artifacts/sprint29.1/final-bundle-correction-live10/`

- session：`sprint29.1-correction-live10`
- candidate：上述 r2 stable、payload、source ZIP 與 formal 雜湊
- live session 先啟動並完成 health，再擷取首頁、總經背景、每日簡報、變化與設定畫面，之後才 cleanup。
- 總經 DOM 含 FRED official、六個系列、各自觀測期間與最新期間說明。
- 簡報 PNG 顯示本輪每日證據鏈簡報。
- 所有 active console errors：0。
- guard：`status=passed`、`harness_exit_code=0`、`cleanup_verified=true`。
- cleanup 後 candidate process：0，8501／8502 listener：0。
- real-data diff：191 到 191，added、removed、changed 均為空。
- production task：before 與 after 均 absent。
- strict verifier：`passed=true`、`errors=[]`。

Verifier 輸出：`artifacts/sprint29.1/verifier-r2-final.json`。
Bundle 內的 capture manifest、candidate binding、evidence index 與 sidecar 均以原始 bytes 綁定，未做換行正規化。

## 歷史證據與限制

- `final-bundle-correction-live7`、`live8`、`live9` 等舊證據完整保留；timeout 或錯誤證據未被改寫成成功。
- 既有 6.444 秒與其他 performance failure artifacts 保留。
- 原生 Chrome 100、125、150 percent 尚未在本輪取得自動化證據，維持 deferred to formal release。
- 未修改 formal EXE、正式排程、installer 或真實使用者資料。
- 未 commit、tag、push、發布或開始下一個 Sprint。

## 結論

本輪實作與可重播證據已整理完成，狀態為 implementation evidence ready for independent CTO acceptance。
