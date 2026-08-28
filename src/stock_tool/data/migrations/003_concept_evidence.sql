-- Sprint 9: additive evidence fields for existing concept storage.
ALTER TABLE research_concepts ADD COLUMN aliases_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE research_concepts ADD COLUMN dataset_version TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE research_concept_relations ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE research_concept_relations ADD COLUMN verified_at TEXT NOT NULL DEFAULT '';
ALTER TABLE research_concept_relations ADD COLUMN dataset_version TEXT NOT NULL DEFAULT 'unknown';

CREATE INDEX IF NOT EXISTS idx_research_concept_relations_evidence
    ON research_concept_relations(concept_key, confidence DESC, verified_at DESC);
