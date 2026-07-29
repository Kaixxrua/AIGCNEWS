ALTER TABLE briefings
    ADD COLUMN content_zh TEXT NOT NULL DEFAULT '',
    ADD COLUMN content_en TEXT NOT NULL DEFAULT '';

UPDATE briefings SET content_zh = content WHERE content_zh = '';
