# Sprint 11 Release Promotion

## Promotion

The verified Sprint 11.1 staging package was promoted without modifying Python source, tests, core logic, or real runtime user data.

| Item | Value |
| --- | --- |
| Formal EXE | `release/StockTool/StockTool.exe` |
| Version | `1.2.2` |
| Size | 24,022,677 bytes |
| Modified | `2026-07-18T12:48:33.8092803+08:00` |
| SHA-256 | `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C` |

The staging hash matched the approved value before promotion. Required public release assets were validated before and after promotion.

## Rollback

The complete prior formal package was preserved before promotion.

| Item | Value |
| --- | --- |
| Rollback directory | `release/rollback/StockTool-pre-sprint11-20260718-130000` |
| Rollback EXE | `release/rollback/StockTool-pre-sprint11-20260718-130000/StockTool.exe` |
| Size | 24,010,824 bytes |
| SHA-256 | `7EE0351ABB217B8E5ADBF2CC09A067F02EF7B721DB2FB06A556CA3B980E5F1D7` |

The existing `release/previous/StockTool` was left untouched. Rollback requires stopping StockTool, moving the current `release/StockTool` aside, and restoring the preserved rollback directory as `release/StockTool`.

## Formal EXE Smoke

The formal EXE launched with an isolated `STOCK_TOOL_USER_DATA_DIR`.

- `http://127.0.0.1:8501/_stcore/health` returned HTTP 200 with body `ok`.
- Isolated `reports`, `logs`, and `data/cache` paths were each writable.
- Smoke-test StockTool processes were stopped.
- No 8501 or 8502 listener remained.
- The isolated smoke runtime directory was removed after verification.

## Release Privacy

The post-promotion filename scan found `0` prohibited entries. The project-owned public release assets contain no real `.env`, Streamlit secrets, provisioned token/API-key/private-key value, `portfolio.csv`, `watchlist.csv`, runtime SQLite, cache, logs, or reports. The public `.env.example` is an allowed release asset. One bundled third-party Streamlit performance-reference document contains a non-secret `st.secrets["openai_key"]` code example; it is not a provisioned credential or a user-data file.

## Real User Data Integrity

`%LOCALAPPDATA%\\StockTool` was read only before and after promotion. Values were identical:

| Path | State | SHA-256 |
| --- | --- | --- |
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | 4 rows | `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent | N/A |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | present | `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E` |

## Desktop Shortcut

The existing desktop shortcut `股票分析工具.lnk` was retained and updated; no duplicate shortcut was created. Its target is `release/StockTool/StockTool.exe` and its working directory is `release/StockTool`.
