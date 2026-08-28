# StockTool Privacy Notice

## Local-first processing

StockTool stores research and optional portfolio/watchlist data locally. It
does not upload that data as part of normal local operation. A market-data
provider may receive the symbol, market, requested date range, interval, and
the query parameters necessary to retrieve the user-requested market data.

An external AI provider is contacted only when a user has explicitly configured
an AI endpoint and API key and then triggers AI research. That request contains
a bounded EvidenceBundle, which may include symbol/market, prices and dates,
composite score and coverage, company/industry summary, provider/source
metadata, warnings, missing-data records, and citation excerpts. It never
includes portfolio data, watchlists, private-document contents or paths, API
keys, logs, caches, or other personal data. Local-rules mode does not call an
external AI provider. External endpoints have their own privacy terms.

## What is not packaged

Release candidates, installers, and source archives must exclude API keys,
`.env` files other than `.env.example`, private documents, OCR output,
portfolio/watchlist files, SQLite runtime data, caches, logs, reports, and
backups. The release checks fail closed when these categories are found.

## User control

Use `STOCK_TOOL_USER_DATA_DIR` to select an isolated test directory. Do not use
the real user-data directory for automated tests. Uninstalling the application
does not delete the separate user-data directory.

## Limits

External market-data providers have their own privacy terms. StockTool does not
make investment recommendations and users should avoid putting credentials or
personal information in research notes or source documents.
