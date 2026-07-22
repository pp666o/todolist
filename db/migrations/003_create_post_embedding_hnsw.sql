BEGIN;

DO $migration$
DECLARE
    current_embedding_type text;
BEGIN
    SELECT
        format_type(
            attribute.atttypid,
            attribute.atttypmod
        )
    INTO current_embedding_type
    FROM pg_attribute AS attribute
    WHERE attribute.attrelid = 'public.posts'::regclass
      AND attribute.attname = 'embedding'
      AND NOT attribute.attisdropped;

    IF current_embedding_type IS NULL THEN
        RAISE EXCEPTION
            'posts.embedding column does not exist';

    ELSIF current_embedding_type <> 'vector(512)' THEN
        RAISE EXCEPTION
            'Expected posts.embedding to be vector(512), got %',
            current_embedding_type;
    END IF;
END
$migration$;

CREATE INDEX IF NOT EXISTS idx_posts_embedding_hnsw
    ON public.posts
    USING hnsw (
        embedding vector_cosine_ops
    )
    WITH (
        m = 16,
        ef_construction = 64
    );

ANALYZE public.posts;

COMMIT;
