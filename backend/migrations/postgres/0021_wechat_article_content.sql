ALTER TABLE wechat_articles ADD COLUMN content_html TEXT NOT NULL DEFAULT '';
ALTER TABLE wechat_articles ADD COLUMN content_fetched_at TIMESTAMPTZ;
