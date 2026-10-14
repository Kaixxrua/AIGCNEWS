-- Additive: legacy projects remain visible and unassessed until a bounded refresh.
ALTER TABLE github_repo_enrichments
    ADD COLUMN assessment_json JSONB;
