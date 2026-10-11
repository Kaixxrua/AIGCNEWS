-- Preserve the scoring input so repairs can retain the same bounded discount.
-- Historical scores and versions remain unchanged; only future computes use v9.
ALTER TABLE github_repo_daily_metrics
    ADD COLUMN previous_top_streak_days SMALLINT NOT NULL DEFAULT 0
    CHECK (previous_top_streak_days BETWEEN 0 AND 5);
