# Sprint 21.1 implementation evidence

狀態：implementation evidence，等待獨立驗收；不代表 CTO acceptance、發布或 Sprint 22 核准。

## 本次修正

- `src/stock_tool/application/strategy_workspace.py`
  - 強制策略 `target_percent` 與 `BacktestFormValues.allocation_rate` 完全一致；不一致時 fail closed。
  - 保留投入比例、初始資金、持股上限、commission、tax、slippage、trailing stop 到 engine 與 manifest 的同一組值。
  - 每一標的資料列的 `market` 必須唯一且存在；缺失或衝突時標為 partial，不執行。
- `src/stock_tool/dashboard/pages/strategy_workspace.py`
  - 投入比例直接建立策略參數與 `BacktestFormValues`，不再固定為 0.4。
  - 市場從所選資料列取得，不沿用全域來源市場。
  - 無效策略參數不回退預設值，執行按鈕停用。
  - 顯示樣本內／樣本外、每個 Walk-forward fold、每個敏感度組合及 manifest digest／過期警告。
- `tests/test_strategy_workspace.py`
  - 新增 allocation mismatch、完整成本綁定、投入比例超過持股上限、TWSE/TPEX/US 混合市場與衝突 fail-closed、原生 AppTest 回歸。

## 驗證命令與結果

- targeted：
  `.venv\\Scripts\\python.exe -m pytest tests/test_strategy_workspace.py tests/test_strategy_page.py tests/test_dashboard_navigation.py -q`
  - **28 passed，exit 0**；輸出：`artifacts/sprint21.1/targeted-tests.log`。
- 完整閘門：`cmd /c quality_gate.bat`
  - **993 passed、2 skipped，exit 0**；branch coverage **83.15%**（門檻 78.50%）。
  - Black、Ruff、focused mypy、compileall、project privacy、release layout、regression baseline 全部通過；完整輸出：`artifacts/sprint21.1/quality-gate.log`。
- 變更的兩個 application/UI source 檔另以 `.venv\\Scripts\\python.exe -m mypy --ignore-missing-imports src/stock_tool/application/strategy_workspace.py src/stock_tool/dashboard/pages/strategy_workspace.py` 驗證，**2 files、0 errors、exit 0**；Black/Ruff/compile 對本次三檔也均 exit 0。
- 原生策略工作區 AppTest 包含標準回測、設定變更過期、重新執行恢復、完整健檢詳細 fold／敏感度與超過持股上限停用，均通過。
- `pip check`：exit 0；官方 `.venv` `pip-audit --format=json`：exit 0、零已知漏洞，輸出：`artifacts/sprint21.1/pip-audit.json`。
- 效能 hard gate：3 次固定資料測量全部通過，輸出：`artifacts/sprint21.1/performance-result.json`；indicators/scoring、Excel、cached research、allocation/risk、EXE health 均低於既定門檻。
- `git diff --check`、source layout validation：exit 0。

## 候選與來源封存

以 `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint21.1` 執行 `build_exe.bat`，exit 0；staging trust-boundary validation 通過。

- stable：`release/staging-sprint21.1/StockTool/StockTool.exe`
  SHA-256 `5586ED1F270BDF57B810BBBC8AF6A409A6256DE0BF9F20F6EA3D069DDD23AB28`
- payload：`release/staging-sprint21.1/StockTool/versions/1.2.2/StockToolPayload.exe`
  SHA-256 `19DE863C885A94F9EFEB26883F68F761D3670B930C4F4ED0633338F5ED2CDE33`
- source archive：`artifacts/sprint21.1/staging-sprint21.1-source.zip`
  SHA-256 `14844FFA37443A195A8F76C20D339B9BC53732A5C7A4E9F4AD4C83F926058076`；sidecar 同值。
- source archive extract verification：missing required inputs **0**、forbidden **0**、content mismatches **0**、duplicate **0**；包含 stable launcher 與所有 build inputs。
- candidate hash record：`artifacts/sprint21.1/candidate-hashes.json`。

## EXE smoke 與資料保全

- 隔離 smoke：`artifacts/sprint21.1/exe-smoke-20260801192014/online/`；stable `--version`、payload `--version` 均為 **1.2.2**，health `200/ok`，程序樹與 listener cleanup 已記錄。
- 正式 `release/StockTool/StockTool.exe` before/after SHA-256 均為：
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- 真實 `%LOCALAPPDATA%\\StockTool` 只讀 manifest：185 檔；`real-data-before.json` 與 `real-data-after.json` 比對 `added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 所有本次啟動程序已清理；未留下 8501/8502 listener。

## Browser best-effort

已以 final candidate hashes 建立九情境 machine-readable record：`artifacts/sprint21.1/browser/browser-result.json`。目前瀏覽器控制面不可用，因此九項均誠實標記 `BLOCKED`，沒有以 AppTest、fixture 或假截圖冒充瀏覽器證據；此為 best-effort 限制，不改寫上述自動化品質結果。

## 限制

本文件只提供 implementation evidence。瀏覽器人工／互動驗收仍需具備可用控制面後由獨立驗收者判定；未進行發布、簽章、promotion、正式 release 覆寫或真實資料修改。
