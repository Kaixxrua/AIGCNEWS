ALTER TABLE github_repo_enrichments
    ADD COLUMN tags_zh_json TEXT,
    ADD COLUMN tags_en_json TEXT;

ALTER TABLE tool_website_enrichments
    ADD COLUMN tags_zh_json TEXT,
    ADD COLUMN tags_en_json TEXT;

UPDATE github_repo_enrichments
SET tags_zh_json = tags_json
WHERE tags_zh_json IS NULL;

UPDATE tool_website_enrichments
SET tags_zh_json = tags_json
WHERE tags_zh_json IS NULL;
