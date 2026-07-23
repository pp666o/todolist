BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_posts_title_trgm
ON posts
USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_posts_content_trgm
ON posts
USING gin (content gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_posts_tags_gin
ON posts
USING gin (tags);

COMMIT;
