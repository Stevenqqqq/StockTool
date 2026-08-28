CREATE TABLE IF NOT EXISTS research_fundamentals (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    fiscal_period TEXT NOT NULL,
    period_type TEXT NOT NULL,
    as_of_date TEXT NOT NULL DEFAULT '',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    provider_symbol TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (symbol, market, fiscal_period, period_type, as_of_date)
);

CREATE TABLE IF NOT EXISTS research_company_profiles (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    company_name TEXT NOT NULL,
    business_summary TEXT NOT NULL DEFAULT '',
    technology_summary TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    as_of_date TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    provider_symbol TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (symbol, market)
);

CREATE TABLE IF NOT EXISTS research_concepts (
    concept_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    as_of_date TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    provider_symbol TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS research_concept_relations (
    concept_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    as_of_date TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    provider_symbol TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (concept_key, symbol, market, relation_type)
);

CREATE TABLE IF NOT EXISTS research_documents (
    document_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    as_of_date TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    provider_symbol TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_research_fundamentals_identity
    ON research_fundamentals(symbol, market, fiscal_period DESC);

CREATE INDEX IF NOT EXISTS idx_research_concept_relations_identity
    ON research_concept_relations(symbol, market, concept_key);

CREATE INDEX IF NOT EXISTS idx_research_documents_identity
    ON research_documents(symbol, market, as_of_date DESC);
