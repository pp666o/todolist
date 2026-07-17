BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS posts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    source varchar(64) NOT NULL,
    source_id text NOT NULL,

    title text NOT NULL,
    content text NOT NULL DEFAULT '',
    category varchar(16) NOT NULL,
    tags text[] NOT NULL DEFAULT ARRAY[]::text[],

    latitude double precision,
    longitude double precision,
    country varchar(100),
    province varchar(100),
    city varchar(100),
    district varchar(100),
    address text,

    likes bigint NOT NULL DEFAULT 0,
    views bigint NOT NULL DEFAULT 0,
    marks bigint NOT NULL DEFAULT 0,
    dislikes bigint NOT NULL DEFAULT 0,
    ratescore double precision,
    visible_status varchar(32),
    owner_id text,

    created_at timestamptz,
    updated_at timestamptz,

    embedding vector(384),
    embedding_updated_at timestamptz,

    synced_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT posts_source_source_id_key
        UNIQUE (source, source_id),

    CONSTRAINT posts_category_check
        CHECK (category IN ('求助', '问答', '吐槽')),

    CONSTRAINT posts_latitude_check
        CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),

    CONSTRAINT posts_longitude_check
        CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),

    CONSTRAINT posts_likes_check
        CHECK (likes >= 0),

    CONSTRAINT posts_views_check
        CHECK (views >= 0),

    CONSTRAINT posts_marks_check
        CHECK (marks >= 0),

    CONSTRAINT posts_dislikes_check
        CHECK (dislikes >= 0)
);

CREATE INDEX IF NOT EXISTS idx_posts_category
    ON posts (category);

CREATE INDEX IF NOT EXISTS idx_posts_visible_status
    ON posts (visible_status);

CREATE INDEX IF NOT EXISTS idx_posts_city_district
    ON posts (city, district);

CREATE INDEX IF NOT EXISTS idx_posts_updated_at
    ON posts (updated_at DESC);

COMMIT;
