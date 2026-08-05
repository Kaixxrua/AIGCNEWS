ALTER TABLE documents ADD COLUMN published_at VARCHAR(64);
ALTER TABLE documents ADD COLUMN author_avatar_url TEXT;
CREATE INDEX idx_documents_published_at ON documents(source, published_at);
CREATE INDEX idx_documents_author_avatar ON documents(source, author_avatar_url) WHERE author_avatar_url IS NOT NULL;
