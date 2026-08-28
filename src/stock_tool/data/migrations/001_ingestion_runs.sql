CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    requested_symbol_json TEXT NOT NULL,
    resolved_symbol_json TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    request_start TEXT,
    request_end TEXT,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    input_rows INTEGER NOT NULL DEFAULT 0,
    output_rows INTEGER NOT NULL DEFAULT 0,
    quality_summary_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    errors_json TEXT NOT NULL DEFAULT '[]',
    attempts_json TEXT NOT NULL DEFAULT '[]',
    last_data_date TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_completed_at
    ON ingestion_runs(completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_resolved_symbol
    ON ingestion_runs(resolved_symbol_json);
