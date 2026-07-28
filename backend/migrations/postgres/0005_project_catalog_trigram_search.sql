CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_gh_candidates_lexical_document_trgm
    ON github_repo_candidates
    USING GIN (
        (LOWER(
            COALESCE(full_name, '') || ' ' ||
            COALESCE(title, '') || ' ' ||
            COALESCE(description, '') || ' ' ||
            COALESCE(language, '') || ' ' ||
            COALESCE(topics_json, '')
        )) public.gin_trgm_ops
    );

CREATE INDEX idx_gh_enrichments_lexical_document_trgm
    ON github_repo_enrichments
    USING GIN (
        (LOWER(
            COALESCE(description_zh, '') || ' ' ||
            COALESCE(tags_json::text, '')
        )) public.gin_trgm_ops
    );
