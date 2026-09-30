-- The icon an administrator's save fetched from the website, re-encoded and stored in the public site
-- asset tree. Only such local assets may be referenced; '' means none (the page shows a monogram).
ALTER TABLE recommended_websites
    ADD COLUMN icon_url VARCHAR(64) NOT NULL DEFAULT ''
    CHECK (icon_url = '' OR icon_url ~ '^/api/media/site/[0-9a-f]{32}\.webp$');
