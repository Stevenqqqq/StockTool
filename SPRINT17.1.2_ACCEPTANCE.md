# StockTool Sprint 17.1.2 Correction Acceptance Record

## 狀態

本次只修正 Sprint 17.1.1 驗收問題。實作、測試、staging build 與
HTTP smoke 已完成；本文件不是正式驗收宣告。因隔離 EXE 的瀏覽器自動化
未能取得可操作的 Streamlit DOM，完整 UI click smoke 保留給 CTO 獨立驗收。
未開始 Sprint 18、twstock、promotion 或正式發布。

## 修改檔案

- `src/stock_tool/application/research_library.py`
- `src/stock_tool/research/document_store.py`
- `src/stock_tool/research/library.py`
- `src/stock_tool/dashboard/pages/research.py`
- `src/stock_tool/dashboard/pages/library.py`
- `src/stock_tool/release_assets.py`
- `build_exe.bat`
- `tests/test_research_library.py`
- `tests/test_research_library_application.py`
- `tests/test_research_document_workspace.py`
- `tests/test_release_assets.py`
- `SPRINT17.1.2_ACCEPTANCE.md`

## 文件引用正式流程

- 新增 `ResearchLibraryApplicationService`，供 Research Workspace UI 使用；
  UI 不直接操作 `DocumentStore` 或 `ResearchDocumentLink`。
- 使用者輸入原始文件的**絕對本機路徑**與可選標題，透過
  `DocumentStore.register()` 登錄。沒有使用 `file_uploader`，不會把上傳
  暫存檔誤存成永久 reference。
- UI 顯示已登錄文件及其可用／遺失／已變更狀態；使用者可勾選可用文件、
  選取 evidence IDs 與輸入可選頁碼。
- `儲存至研究庫` 由 application service 建立 `ResearchDocumentLink`，
  並傳入 `ResearchLibrary.save()`。
- service/UI end-to-end regression 使用合成 PDF 原始路徑，驗證：登錄、
  帶頁碼引用保存、重新開啟後可用、刪除後遺失、改寫後已變更。metadata JSON
  不包含 PDF bytes；沒有 OCR 或文件副本。

## 引用完整性與舊資料策略

- 新 entry schema 為 `2`。`content_hash` 包含正規化後的 document ID、
  排序後 citation IDs、頁碼及 reference 順序。
- 正規化政策：每個 link 的 citation IDs 依字典序排序；links 依
  `document_id` 排序。非正規順序直接 fail closed。
- hostile JSON tests 覆蓋：document ID、citation IDs、page、增加、刪除、
  link 重排及 citation ID 重排；全部無法載入/顯示。
- 外部文件內容不納入 entry hash；`DocumentStore` 的保存 SHA-256 持續負責
  available/missing/changed 判定。
- schema 1 無 document references 的舊 entry 可載入，標示
  `legacy_no_references`。Sprint 17.1.1 含未受 hash 保護 references 的
  schema 1 entry 載入為 `legacy_unverified`，引用會安全略過並在保存版本 UI
  顯示中文警告；不會被視為已驗證，也不會原地修改使用者資料。
- backup/restore regression 驗證 entry hash、verified references 與
  `documents/documents.json` metadata 一致；既有 duplicate/file_count/schema/
  size/hash/path traversal 防護仍通過。

## 測試與品質

- Research Library/DocumentStore/backup/UI/application targeted suite：
  **65 passed**，另有 1 個預期的 hostile duplicate-ZIP fixture warning。
- 完整 pytest：**861 collected tests，全部通過**。
- Branch coverage：**82.53%**（門檻 82.45%）。
- Black、Ruff、mypy（6 個變更 production modules）、`compileall -q src tests`
  全部通過。
- 維持回歸：保存版本 provider/`ensure_symbol_data` 零呼叫、目前資料動作才
  進入 provider workflow、中文保存畫面、available/missing/changed、derived
  metadata/snapshot/evidence/citation integrity、`None` 不顯示為字串、以及
  無 OCR/私人文件內容副本。

## 可重現 staging build

- `build_exe.bat` 改為 `python -m stock_tool.release_assets` module entry
  point；source root 由 module 檔案位置解析，不再在 batch inline Python 中
  傳遞 Unicode 資產名稱。
- 修正 `STAGING_PARENT` delayed expansion：自訂
  `release\\staging-sprint17.1.2` 不再錯誤回退到 `release\\staging`。
- 標準命令：
  `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint17.1.2 build_exe.bat`
  已完成 PyInstaller、allowlisted public asset copy、`validate_release_assets`
  並 **exit 0**；沒有人工補拷貝。
- Candidate：`release\\staging-sprint17.1.2\\StockTool\\StockTool.exe`
- Candidate `--version`：`1.2.2`，通過。
- Candidate SHA-256：
  `E9B273FE20FE74EFFA38F9CA71F7191FF9E4421EB4B276D25AE2F714403E9D8D`。
- 正式 release EXE 未覆寫，SHA-256 仍為：
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## EXE smoke 與資料保護

- 候選以全新
  `artifacts\\sprint17.1.2-exe-smoke\\user-data` 啟動；
  `http://127.0.0.1:8501/_stcore/health` 回傳 `200 / ok`，首頁回傳 `200`
  （1,522 bytes）。
- 候選關閉後：`StockTool` process **0**；8501/8502 listener **0**。
- 隔離 browser surface 對該 localhost Streamlit app 僅回傳空白 banner，
  沒有可可靠 click 的 DOM；因此 EXE 層的登錄 PDF、保存頁碼、重啟、
  missing/changed、provider-zero/current-provider、backup/tamper click smoke
  尚待 CTO 在一般桌面瀏覽器完成。對應實際 render/application service tests
  已通過，並非 model API-only fixture。
- 真實資料預先基線（Sprint 17.1.1）與本次 smoke 後目前檢查一致：
  portfolio 存在、131 bytes、SHA-256
  `a4d05d021c6fff6ec4c561a6b4186d53782722f5244b702f3b507f953e285bf6`；
  watchlist、ledger SQLite、settings 均不存在。候選啟動繼承隔離資料根目錄，
  未開啟或寫入真實資料。

## Privacy 與 source archive

- Project privacy scan：**0 violations**。
- Candidate forbidden-file scan：**0 forbidden files**（2,803 files）。
- Source archive：
  `artifacts\\sprint17.1.2-source-verify\\stocktool-source.zip`
- Archive entries：**287**。
- Archive SHA-256：
  `693FD1767D16903C0701DBE1585E2CEB74DFB02604D7FDB20F49A580ECEEA836`。
- Archive verification：0 missing required inputs、0 forbidden entries、
  0 content mismatches。

## 已知限制與 rollback

- CTO 仍需在一般桌面 browser 對候選完成隔離 UI click smoke，尤其是文件
  登錄/頁碼保存/重啟、broken-document 顯示、保存版本 provider-zero、目前資料
  provider flow 與 backup tamper rejection。
- 未進行 OCR、雲端同步、新 provider、installer、正式發布或 promotion。
- rollback 是未變更的 `release\\StockTool\\StockTool.exe` 與 Sprint 12/v1.2.2
  正式基線。
