BEGIN;

CREATE TABLE IF NOT EXISTS public.user_profiles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    source varchar(64) NOT NULL,
    source_user_id text NOT NULL,

    age_bucket varchar(16),
    job text,
    education text,
    hobby_tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    character_tag text,
    user_level bigint,

    country varchar(100),
    province varchar(100),
    city varchar(100),
    district varchar(100),
    school varchar(255),

    authored_post_count integer NOT NULL DEFAULT 0,

    category_weights jsonb NOT NULL DEFAULT '{}'::jsonb,
    tag_weights jsonb NOT NULL DEFAULT '{}'::jsonb,

    avg_likes double precision NOT NULL DEFAULT 0,
    avg_views double precision NOT NULL DEFAULT 0,
    avg_marks double precision NOT NULL DEFAULT 0,
    avg_dislikes double precision NOT NULL DEFAULT 0,
    avg_rate_score double precision,

    last_authored_at timestamptz,

    profile_version integer NOT NULL DEFAULT 1,
    source_updated_at timestamptz,
    synced_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT user_profiles_source_source_user_id_key
        UNIQUE (source, source_user_id),

    CONSTRAINT user_profiles_age_bucket_check
        CHECK (
            age_bucket IS NULL
            OR age_bucket IN (
                '18-24',
                '25-34',
                '35-44',
                '45-54',
                '55-64',
                '65+',
                'unknown'
            )
        ),

    CONSTRAINT user_profiles_authored_post_count_check
        CHECK (authored_post_count >= 0),

    CONSTRAINT user_profiles_category_weights_check
        CHECK (jsonb_typeof(category_weights) = 'object'),

    CONSTRAINT user_profiles_tag_weights_check
        CHECK (jsonb_typeof(tag_weights) = 'object'),

    CONSTRAINT user_profiles_profile_version_check
        CHECK (profile_version > 0),

    CONSTRAINT user_profiles_avg_likes_check
        CHECK (avg_likes >= 0),

    CONSTRAINT user_profiles_avg_views_check
        CHECK (avg_views >= 0),

    CONSTRAINT user_profiles_avg_marks_check
        CHECK (avg_marks >= 0),

    CONSTRAINT user_profiles_avg_dislikes_check
        CHECK (avg_dislikes >= 0),

    CONSTRAINT user_profiles_avg_rate_score_check
        CHECK (
            avg_rate_score IS NULL
            OR avg_rate_score >= 0
        )
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_source_city_district
    ON public.user_profiles (
        source,
        city,
        district
    );

CREATE INDEX IF NOT EXISTS idx_user_profiles_source_authored_posts
    ON public.user_profiles (
        source,
        authored_post_count DESC
    );

CREATE INDEX IF NOT EXISTS idx_user_profiles_hobby_tags_gin
    ON public.user_profiles
    USING gin (hobby_tags);

COMMIT;
