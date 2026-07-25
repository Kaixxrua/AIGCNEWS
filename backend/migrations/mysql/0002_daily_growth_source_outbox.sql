INSERT INTO project_catalog_outbox (
    event_id,
    aggregate_type,
    aggregate_key,
    operation,
    source_method
)
SELECT
    UUID(),
    'github_repo_daily_metrics',
    JSON_OBJECT('metric_date', metric_date, 'repo_id', repo_id),
    'reconcile',
    'mysql_migration_daily_growth_source_backfill'
FROM github_repo_daily_metrics
WHERE daily_growth_available = 1
  AND COALESCE(daily_growth_source, 'unavailable') = 'unavailable'
  AND previous_snapshot_date = DATE_FORMAT(
      DATE_SUB(STR_TO_DATE(metric_date, '%Y-%m-%d'), INTERVAL 1 DAY),
      '%Y-%m-%d'
  );

UPDATE github_repo_daily_metrics
SET daily_growth_source = 'snapshot_delta'
WHERE daily_growth_available = 1
  AND COALESCE(daily_growth_source, 'unavailable') = 'unavailable'
  AND previous_snapshot_date = DATE_FORMAT(
      DATE_SUB(STR_TO_DATE(metric_date, '%Y-%m-%d'), INTERVAL 1 DAY),
      '%Y-%m-%d'
  );
