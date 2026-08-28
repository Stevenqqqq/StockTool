# Sprint 27.1.1.1.1.1.1 Evidence Correction

狀態：implementation evidence ready for CTO review；本輪未修改產品 source、候選程式、installer、正式 EXE 或正式排程。

## Fresh same-session settings evidence

- Candidate：`release/staging-sprint27.1.1.1.1.1-final/StockTool/StockTool.exe`
- Stable SHA-256：`49D1698C66D24AE7180D18BA79DF91EB6C29F1F073B95CA8F30BA668259C8A19`（size 7,111,060）
- Payload SHA-256：`C8837DE556A6868063F2E0BC2D465EB78B564E779E2901C61470CDEC8698B5A0`
- Source ZIP SHA-256：`5AAB2B935391F2CC4D5C7FF60484ED0C0155A228D2A4BD614E9FC5009A284EA8`（size 2,592,188）
- Formal EXE SHA-256：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`（unchanged）
- Session：`sprint27.1.1.1.1.1.1-settings-1786467862884`
- Capture manifest：`artifacts/sprint27.1.1.1.1.1.1/capture-session-manifest.json`，SHA-256 `308CE0D62D1A75CF7B2AE83E2235E492AE06D5722DB7662D32C11EDAFCC2B279`，size 3,289 bytes。
- Settings PNG：`artifacts/sprint27.1.1.1.1.1.1/browser-session-final/captures/settings.png`，SHA-256 `A00B29C0800664F96B0074BBA97A1AAAEABBA44F917B1A07A3249923D01D2832`；畫面實際顯示「目前狀態：未安裝」、週一至週五 18:30（Asia/Taipei）與操作按鈕。
- Home PNG：`artifacts/sprint27.1.1.1.1.1.1/browser-session-final/captures/home.png`，SHA-256 `127D5823C01F75F2B86B56B8743BA74DE29E06582A8EAA4D90EFD4840302F082`。
- DOM semantic：未安裝為 true、錯誤狀態為 false、平日排程為 true；active console error count = 0。

所有 PNG、DOM、console、launch、guard、cleanup 檔案均以原始 bytes 固定後才建立 capture manifest；`raw-hash-verifier.json` 證明 manifest 對 capture files、browser-result 對 manifest 均一致。`evidence-hash-index.json`（SHA-256 `4801D940BB40EC39073D58DF856002CFAC4E2B40BBD2DDE13272B50D73B63D58`）與 sidecar 的 missing/extra/mismatch 均為 0。

## Guard、資料與清理

- `browser-session-final/guard-result.json`：status `passed`、harness exit code `0`、cleanup verified、candidate processes remaining `[]`、listeners remaining `0`。
- 真實資料：before 191、after 191、added/removed/changed 均為空，`zero_diff=true`；正式排程 absent。
- 最終 cleanup：StockTool/StockToolPayload = 0、8501/8502 listeners = 0、temporary/production task = 0。
- 原驗收工具誤建的唯一指定暫存目錄已在解析並確認 workspace 直屬、basename 完全相同後移除；未使用廣泛 glob，其他資料未觸碰。

## Historical performance evidence

原始失敗檔案已以 binary-safe bytes 保存於 `artifacts/sprint27.1.1.1.1.1.1/historical-performance/`：

- `performance-independent.json` SHA-256 `5E890410CEE16EA0BE99E9757949F7E61FA58CD12869F2B82A0FDF6FE0754BD1`；保留 `exe_health_ready.max_seconds=5.53254330001073`、`passed=false`，沒有改寫成新測量。
- `performance-independent.log` SHA-256 `A95E14CE4782EDC83CD9D196FB26160AE77C4F4E66C2ACAE38B502E4AC4B70A0`。

上一版 browser evidence 因 capture 後被 CRLF rewrite，標記為 `superseded_invalid`；本 acceptance 只引用上述 fresh same-session evidence。Native Chrome 100%/125%/150% 仍為 `deferred_to_formal_release`。

## Scope and limitations

- 本輪只做 evidence capture、raw-byte/hash verification、semantic check、candidate/data/cleanup quick checks；未重跑 full pytest、coverage、quality gate，因 source 與 candidate hash 均未變。
- 未修改 formal release、installer、registry、Start Menu、正式排程、真實使用者資料；未 commit、tag、push、發布或開始下一 Sprint。
