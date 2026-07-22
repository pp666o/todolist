BEGIN;

DO $migration$
DECLARE
    current_embedding_type text;
    embedded_post_count bigint;
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

    ELSIF current_embedding_type = 'vector(512)' THEN
        RAISE NOTICE
            'posts.embedding is already vector(512); skipping';

    ELSIF current_embedding_type = 'vector(384)' THEN
        SELECT COUNT(*)
        INTO embedded_post_count
        FROM public.posts
        WHERE embedding IS NOT NULL;

        IF embedded_post_count > 0 THEN
            RAISE EXCEPTION
                'Cannot resize posts.embedding: % rows already contain 384-dimensional vectors',
                embedded_post_count;
        END IF;

        ALTER TABLE public.posts
            ALTER COLUMN embedding
            TYPE vector(512)
            USING NULL::vector(512);

        RAISE NOTICE
            'Resized posts.embedding from vector(384) to vector(512)';

    ELSE
        RAISE EXCEPTION
            'Unexpected posts.embedding type: %',
            current_embedding_type;
    END IF;
END
$migration$;

COMMIT;
