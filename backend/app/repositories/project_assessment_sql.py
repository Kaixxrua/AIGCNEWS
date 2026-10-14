"""Shared freshness and selection predicates for catalog rows and refreshes."""

# Aliases c/ge match the catalog. Check current source content before promoting a
# project: a stale README/description must not retain an earlier trial verdict.
CURRENT_ASSESSMENT_SQL = """
    ge.assessment_json ->> 'version' = '1'
    AND ge.assessment_json ->> 'source_description' = COALESCE(c.description, '')
    AND COALESCE(ge.assessment_json ->> 'license_spdx_id', '') = COALESCE(c.license_spdx_id, '')
    AND LEFT(ge.assessment_json ->> 'assessed_at', 10) >=
        ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - 30)::text
    AND COALESCE(ge.assessment_json ->> 'readme_sha256', '') = COALESCE((
        SELECT ss.readme_sha256 FROM github_project_semantic_sources ss
        WHERE ss.repo_id = c.repo_id AND ss.readme_status = 'succeeded'
    ), '')
"""

SCREENED_ASSESSMENT_SQL = f"""
    ({CURRENT_ASSESSMENT_SQL})
    AND ge.assessment_json ->> 'decision' = 'evaluate'
    AND c.availability_status = 'active'
"""
