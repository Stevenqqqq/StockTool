# Sprint 27.1.1.1.1.1.1.1 Evidence Metadata Hotfix

本輪只修正 evidence metadata 與 verifier；未修改產品 source、候選 EXE、source ZIP、formal EXE、browser capture、真實資料或排程，亦未重跑 browser、performance、pytest、coverage 或 quality gate。

## Exact artifact verification

`artifacts/sprint27.1.1.1.1.1.1/candidate-hash-verifier.json` 已改為 fail-closed schema v2：

- 每個 expected/actual SHA-256 均先驗證為恰好 64 個十六進位字元。
- size 使用完全相等比較。
- hash 使用 exact equality；不使用 prefix、contains 或 truthy 判定。
- top-level `match` 僅在 stable、payload、source ZIP、formal EXE 的 `size_match` 與 `hash_match` 全部為 true 時成立。
- 每項均輸出 expected、actual、size_match、hash_match 與 hash-valid 欄位。

四個實體檔案重新計算結果：

| artifact | size | SHA-256 | exact match |
|---|---:|---|---|
| stable EXE | 7,111,060 | `49D1698C66D24AE7180D18BA79DF91EB6C29F1F073B95CA8F30BA668259C8A19` | true |
| payload EXE | 23,914,976 | `C8837DE556A6868063F2E0BC2D465EB78B564E779E2901C61470CDEC8698B5A0` | true |
| source ZIP | 2,592,188 | `5AAB2B935391F2CC4D5C7FF60484ED0C0155A228D2A4BD614E9FC5009A284EA8` | true |
| formal EXE | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | true |

已修正所有找到的 63 碼 source ZIP expected 值：candidate binding、candidate verifier expected source、browser-result 的 nested source hash 與 top-level source hash、前一份 acceptance 文件。Browser capture bytes 未修改。

## Index verification

`artifacts/sprint27.1.1.1.1.1.1/evidence-hash-index.json` 與 sidecar 已重建；重新讀取實體檔後確認：

- index entries、actual files、missing、extra、mismatch：均為 0。
- evidence index sidecar：exact match。
- capture manifest 與既有 PNG/DOM/console/launch/guard/cleanup bytes：未改動。

未建立 commit、tag、push、發布或下一 Sprint；正式成品與真實資料維持不變。
