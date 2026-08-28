# Sprint 30.1.1 驗收報告：StockTool 個人正式發佈候選與安裝生命週期硬化 (Correction)

## 1. 執行摘要與範圍界定

- **Sprint 目標**：完成 StockTool 個人正式發佈候選版本（`1.3.0-rc1`）之發佈加固、完整安裝生命週期驗證、瀏覽器無障礙鍵盤導航與原生縮放驗證。
- **發佈候選版本**：`1.3.0-rc1`
- **正式基線版本**：`1.2.2` (正式不可變基線)
- **範圍承諾**：
  - 本 Sprint 僅處理 release hardening 與驗收證據加固。
  - 不新增投資策略、provider、Pine Script、Cloudflare、Remotion、public-apis、QTrader、交易機器人或重大 UI 改動。
  - 嚴格保護真實使用者資料（`%LOCALAPPDATA%\StockTool`），保持零差異（zero-diff）。
  - 正式 `release/StockTool/StockTool.exe` 保持不可變。

---

## 2. 候選製品與正式基線雜湊對照

| 成品角色 | 檔案路徑 | 版本 | SHA-256 雜湊 |
| :--- | :--- | :--- | :--- |
| **Formal Baseline** | `release/StockTool/StockTool.exe` | `1.2.2` | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |
| **Stable Launcher** | `release/staging-sprint30.1/StockTool/StockTool.exe` | `1.3.0-rc1` | `4AC2B490998058D40BAF58D6B0310D7A4B4018DF82CCB2D227E0D24929C5ECDD` |
| **Payload Candidate**| `release/staging-sprint30.1/StockTool/versions/1.3.0-rc1/StockToolPayload.exe` | `1.3.0-rc1` | `023BF237589FCC4F3EEB90B704CD659DD02D9DB556A9FD63504AA8256E570E82` |
| **Source Archive**  | `release/staging-sprint30.1-source.zip` | `1.3.0-rc1` | `0C5BC02BD1812E6B4F817B6D83F72B57B0A26A4D948AEAECEFE42BCDF88D6F2C` |
| **Internal Installer**| `artifacts/sprint30.1.1/installer/StockTool-Setup-1.3.0-rc1-internal-test.exe` | `1.3.0-rc1` | `DC290B4B5EC92854F4B8E4FE577668D3A01D951F898FA8B7E047FFADA305C921` |

---

## 3. 驗收核心項目與驗證結果

### 3.1 Chrome 原生縮放（100%、125%、150%）驗證
- **驗證方式**：透過 Chrome CDP 控制 PageScaleFactor 與 DeviceScaleFactor，維持固定實體視窗尺寸（1400x900）。
- **驗證記錄**：輸出 `zoom-metadata.json`，完整記錄 `innerWidth`、`innerHeight`、`devicePixelRatio`、`visualViewport` 與實體視窗尺寸。
- **證據產出**：
  - `zoom_100.png`、`zoom_100.dom.txt`、`zoom_100.console.json` (`devicePixelRatio: 1.0`)
  - `zoom_125.png`、`zoom_125.dom.txt`、`zoom_125.console.json` (`devicePixelRatio: 1.25`)
  - `zoom_150.png`、`zoom_150.dom.txt`、`zoom_150.console.json` (`devicePixelRatio: 1.5`)
  - 均由相同 session 生成、雜湊鎖定、無 console 錯誤。

### 3.2 鍵盤 E2E 無障礙互動驗證
- **驗證方式**：以 Tab、ArrowDown、Enter 於瀏覽器中操作市場選擇下拉選單（Streamlit Selectbox），DOM 必須證明選項實際改變。
- **操作歷程**：
  1. `keyboard_initial`：市場初始為「`請選擇市場`」。
  2. Tab 鍵聚焦、ArrowDown 開啟下拉選單。
  3. `keyboard_opened`：擷取下拉選單展開畫面。
  4. ArrowDown 移動至「`台股上市 TWSE`」，Enter 確認選取。
  5. `keyboard_changed`：DOM 與畫面確認更新為「`台股上市 TWSE`」。
- **證據產出**：
  - `keyboard_initial.*`、`keyboard_opened.*`、`keyboard_changed.*`
  - `keyboard-navigation-trace.json` 記錄所有鍵盤動作與初始/變更值。

### 3.3 安裝生命週期（7 階段完整自動化驗證）
- **報告產出**：`artifacts/sprint30.1.1/installer-lifecycle-result.json`
- **階段涵蓋**：
  1. **Clean Install**：全新安裝至乾淨路徑，確認安裝 2804 個檔案、`current-version.json` 指向 `1.3.0-rc1`。
  2. **First Launch & Health**：首次啟動候選 EXE，確認健康檢查 `http://127.0.0.1:8501/_stcore/health` 回應 HTTP 200。
  3. **Reinstall / Repair**：重疊安裝/修復，確認版本權威正常維持。
  4. **Failed-Install Rollback**：模擬更新中斷，確認舊版權威與可用性不受損（fail-closed）。
  5. **Uninstall & User Data Preservation**：執行 `unins000.exe` 靜默解除安裝，應用程式主目錄完全移除，但使用者資料目錄（含 sentinel 測試檔）完全保留。
  6. **Upgrade from formal v1.2.2 baseline**：從正式 v1.2.2 基線進行升級安裝，確認 v1.2.2 歷史版本保留且 v1.3.0-rc1 成功啟用並運作。
  7. **Task Scheduler Lifecycle**：建立、查詢、停用、啟用、刪除排程工作，確認系統無殘留。

### 3.4 嚴格驗證器驗證（`verify_evidence_bundle.py`）
- 執行指令：
  ```bash
  python scripts/verify_evidence_bundle.py artifacts/sprint30.1.1/evidence-bundle --stable-candidate release/staging-sprint30.1/StockTool/StockTool.exe --payload-candidate release/staging-sprint30.1/StockTool/versions/1.3.0-rc1/StockToolPayload.exe --source-zip release/staging-sprint30.1-source.zip --formal-exe release/StockTool/StockTool.exe
  ```
- **結果**：`passed=True, errors=[]`（共驗證 46 個規範證據檔案，包括 zoom 與 keyboard 完整規格）。

---

## 4. 品質門禁與測試統計

- **Targeted Tests**：通過（涵蓋 verifier、installer_build、version_resource、stable_entry 等）
- **Full Pytest**：全部通過（1364 passed, 2 skipped, 0 failed）
- **Branch Coverage**：>= 82.47%
- **靜態品質檢查**：
  - `python -m compileall src tests scripts`：通過（無語法錯誤）
  - `ruff check src tests scripts`：通過（零警告、零錯誤）
  - `black --check src tests scripts`：通過（格式完全合規）
  - `mypy src`：通過（類型檢查零錯誤）
  - `pip check`：通過（無衝突相依性）
  - `pip-audit`：通過（無已知套件安全性漏洞）
- **冷啟動效能**：<= 5.0 秒
- **真實使用者資料保護**：`zero_diff=True`（無任何檔案新增、刪除或修改）
- **環境殘留程序**：0 個殘留程序、0 個殘留排程。

---

## 5. 已知限制與發布前提

1. **未簽署安裝檔（SmartScreen 提示）**：
   - 目前安裝檔 `StockTool-Setup-1.3.0-rc1-internal-test.exe` 為未簽署之內部測試版（unsigned internal test installer），在未載入 Windows Authenticode 憑證前，Windows SmartScreen 會顯示發行者未知的警告提示。
2. **自動更新機制需伺服器端支援**：
   - 本地已具備 stable launcher 與多版本 authority 結構，但正式線上自動更新仍需搭配 HTTPS 靜態檔案伺服器與發布 manifest。
3. **使用者權限範圍**：
   - 安裝檔預設為 Per-User 安裝（安裝於 `%LOCALAPPDATA%\Programs\StockTool`），不需系統管理員（UAC）提升權限，捷徑建立於當前使用者之桌面與開始功能表。
