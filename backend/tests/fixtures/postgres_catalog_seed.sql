INSERT INTO github_repo_candidates (
    repo_id, full_name, title, url, description, language, topics_json,
    created_at, pushed_at, stars, forks, watchers, source_channels,
    first_seen_at, last_seen_at, last_snapshot_at
) VALUES
    ('acme/alpha', 'acme/alpha', 'Alpha', 'https://github.com/acme/alpha',
     'Local RAG workspace', 'Python', '["rag", "knowledge-base"]',
     '2025-01-01T00:00:00Z', '2026-07-20T08:00:00Z', 1200, 80, 25, 'fixture',
     '2026-07-01T00:00:00Z', '2026-07-20T08:00:00Z', '2026-07-23T09:00:00Z'),
    ('acme/beta', 'acme/beta', 'Beta', 'https://github.com/acme/beta',
     'Agent workflow runtime', 'TypeScript', '["agents", "mcp"]',
     '2025-02-01T00:00:00Z', '2026-07-19T08:00:00Z', 800, 60, 20, 'fixture',
     '2026-07-02T00:00:00Z', '2026-07-19T08:00:00Z', '2026-07-23T09:00:00Z'),
    ('acme/draft', 'acme/draft', 'Draft', 'https://github.com/acme/draft',
     'Not enriched yet', 'Go', '[]',
     '2025-03-01T00:00:00Z', '2026-07-18T08:00:00Z', 1500, 10, 5, 'fixture',
     '2026-07-03T00:00:00Z', '2026-07-18T08:00:00Z', '2026-07-23T09:00:00Z');

INSERT INTO github_repo_enrichments (
    repo_id, category_slug, category_name, subcategory_slug, subcategory_name,
    description_zh, tags_json, confidence, source_fingerprint, prompt_version,
    model_provider, model_name, status, enriched_at, updated_at
) VALUES
    ('acme/alpha', 'rag_knowledge', 'RAG 与知识库', 'rag_framework', 'RAG 框架',
     '本地知识库', '["RAG", "local"]', 0.98, repeat('a', 64), 'fixture-v1',
     'fixture', 'fixture', 'succeeded', '2026-07-23T08:00:00Z', '2026-07-23T08:00:00Z'),
    ('acme/beta', 'agents_automation', '智能体与自动化', 'agent_framework', '智能体框架',
     '智能体工作流', '["Agent", "MCP"]', 0.95, repeat('b', 64), 'fixture-v1',
     'fixture', 'fixture', 'succeeded', '2026-07-23T08:00:00Z', '2026-07-23T08:00:00Z');

INSERT INTO github_repo_daily_metrics (
    repo_id, metric_date, stars, forks, watchers, open_issues,
    previous_snapshot_date, previous_stars, daily_star_growth,
    daily_growth_available, daily_growth_source, daily_growth_observed_at,
    hot_score, updated_at
) VALUES
    ('acme/alpha', CURRENT_DATE, 1200, 80, 25, 4,
     CURRENT_DATE - 1, 1158, 42, TRUE, 'snapshot_delta', CURRENT_TIMESTAMP, 91.5, CURRENT_TIMESTAMP),
    ('acme/beta', CURRENT_DATE, 800, 60, 20, 2,
     CURRENT_DATE - 1, 788, 12, TRUE, 'snapshot_delta', CURRENT_TIMESTAMP, 70.0, CURRENT_TIMESTAMP);

INSERT INTO github_repo_recommendations (repo_id, active, recommended_by_user_id, recommended_at)
VALUES ('acme/alpha', TRUE, 7, '2026-07-23T08:30:00Z');

INSERT INTO project_favorites (user_id, project_source, project_id, created_at)
VALUES (42, 'github', 'acme/beta', '2026-07-23T08:45:00Z');
