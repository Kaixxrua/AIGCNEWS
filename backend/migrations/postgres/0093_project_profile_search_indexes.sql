-- Keep the v1 indexes for legacy/shadow and rollback. These expressions must
-- match both v2 repository adapters, including the bounded raw description.
CREATE INDEX idx_gh_candidates_profile_v2_trgm
    ON github_repo_candidates
    USING GIN (
        (LOWER(
            COALESCE(full_name, '') || ' ' ||
            COALESCE(title, '') || ' ' ||
            LEFT(COALESCE(description, ''), 1024) || ' ' ||
            COALESCE(language, '') || ' ' ||
            COALESCE(topics_json, '')
        )) public.gin_trgm_ops
    );

CREATE INDEX idx_gh_enrichments_profile_v2_trgm
    ON github_repo_enrichments
    USING GIN (
        (LOWER(
            COALESCE(description_zh, '') || ' ' ||
            COALESCE(description_en, '') || ' ' ||
            COALESCE(tags_json::text, '') || ' ' ||
            COALESCE(tags_zh_json::text, '') || ' ' ||
            COALESCE(tags_en_json::text, '')
        )) public.gin_trgm_ops
    );
