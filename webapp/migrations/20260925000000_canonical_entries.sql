BEGIN;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS source_id text;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS label text;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS attachments jsonb;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS created_at timestamptz;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS updated_at timestamptz;

DROP TRIGGER IF EXISTS entries_touch_updated_at_trigger ON public.entries;
DROP TRIGGER IF EXISTS entries_merge_source_id_trigger ON public.entries;
DROP INDEX IF EXISTS public.entries_content_unique_idx;
DROP INDEX IF EXISTS public.entries_content_key_unique_idx;
DROP INDEX IF EXISTS public.entries_source_id_unique_idx;

CREATE OR REPLACE FUNCTION public.entries_attachment_item(value jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    item_url text;
    item_name text;
    item_lower text;
BEGIN
    IF jsonb_typeof(value) = 'string' THEN
        item_url := btrim(value #>> '{}');
    ELSIF jsonb_typeof(value) = 'object' THEN
        item_url := COALESCE(value ->> 'url', value ->> 'href', value ->> 'path');
        item_name := COALESCE(value ->> 'name', value ->> 'filename', '');
    ELSE
        RETURN NULL;
    END IF;

    item_url := btrim(item_url);
    IF item_url IS NULL OR item_url = '' THEN
        RETURN NULL;
    END IF;

    item_lower := lower(item_url);
    IF item_lower LIKE 'javascript:%'
        OR item_lower LIKE 'void%'
        OR item_lower LIKE '#%'
        OR item_lower LIKE 'mailto:%'
        OR item_lower LIKE 'tel:%'
        OR item_lower LIKE 'data:%' THEN
        RETURN NULL;
    END IF;

    IF item_url LIKE '~/%' THEN
        item_url := substr(item_url, 3);
    END IF;
    IF item_url LIKE '//%' THEN
        item_url := 'https:' || item_url;
    ELSIF item_lower NOT LIKE 'http://%' AND item_lower NOT LIKE 'https://%' THEN
        item_url := 'https://rainbow.myclassboard.com/StudentERP/'
            || ltrim(item_url, '/');
    END IF;

    item_name := btrim(COALESCE(item_name, ''));
    IF item_name = '' OR lower(item_name) IN (
        'attachment',
        'attachments',
        'file',
        'download',
        'view file'
    ) THEN
        item_name := COALESCE(
            NULLIF(regexp_replace(item_url, '^.*/', ''), ''),
            'Attachment'
        );
    END IF;

    RETURN jsonb_build_object('name', item_name, 'url', item_url);
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_attachment_url_key(value jsonb)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    item_url text;
    parts text[];
BEGIN
    item_url := btrim(COALESCE(value ->> 'url', ''));
    IF item_url ~* '^https?://' THEN
        parts := regexp_match(
            item_url,
            '^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)(.*)$'
        );
        IF parts IS NOT NULL THEN
            RETURN lower(parts[1]) || '://' || lower(parts[2]) || parts[3];
        END IF;
    END IF;
    RETURN item_url;
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_attachments_valid(value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    item jsonb;
BEGIN
    IF value IS NULL OR jsonb_typeof(value) <> 'array' THEN
        RETURN false;
    END IF;

    FOR item IN
        SELECT element
        FROM jsonb_array_elements(value) AS elements(element)
    LOOP
        IF jsonb_typeof(item) <> 'object' THEN
            RETURN false;
        END IF;
        IF NOT (item ? 'name' AND item ? 'url') THEN
            RETURN false;
        END IF;
        IF (SELECT count(*) FROM jsonb_object_keys(item)) <> 2 THEN
            RETURN false;
        END IF;
        IF jsonb_typeof(item -> 'name') <> 'string'
            OR jsonb_typeof(item -> 'url') <> 'string' THEN
            RETURN false;
        END IF;
        IF btrim(item ->> 'name') = '' OR btrim(item ->> 'url') = '' THEN
            RETURN false;
        END IF;
    END LOOP;

    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_normalize_attachments(value jsonb)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    item jsonb;
    normalized jsonb;
    result jsonb := '[]'::jsonb;
BEGIN
    IF value IS NULL THEN
        RETURN result;
    END IF;
    IF jsonb_typeof(value) = 'object' THEN
        value := jsonb_build_array(value);
    ELSIF jsonb_typeof(value) <> 'array' THEN
        RETURN result;
    END IF;

    FOR item IN
        SELECT element
        FROM jsonb_array_elements(value) AS elements(element)
    LOOP
        normalized := public.entries_attachment_item(item);
        IF normalized IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(result) AS existing(item)
                WHERE public.entries_attachment_url_key(existing.item)
                    = public.entries_attachment_url_key(normalized)
            ) THEN
            result := result || jsonb_build_array(normalized);
        END IF;
    END LOOP;

    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_merge_attachments(left_value jsonb, right_value jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT public.entries_normalize_attachments(
        CASE
            WHEN jsonb_typeof(left_value) = 'array' THEN left_value
            WHEN jsonb_typeof(left_value) = 'object' THEN jsonb_build_array(left_value)
            ELSE '[]'::jsonb
        END ||
        CASE
            WHEN jsonb_typeof(right_value) = 'array' THEN right_value
            WHEN jsonb_typeof(right_value) = 'object' THEN jsonb_build_array(right_value)
            ELSE '[]'::jsonb
        END
    );
$$;

CREATE OR REPLACE FUNCTION public.entries_parse_attachments(value text)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    trimmed text;
    parsed jsonb;
BEGIN
    IF value IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;

    trimmed := btrim(value);
    IF trimmed = '' THEN
        RETURN '[]'::jsonb;
    END IF;

    BEGIN
        parsed := trimmed::jsonb;
    EXCEPTION WHEN others THEN
        IF left(trimmed, 1) IN ('[', '{', '"') THEN
            RETURN '[]'::jsonb;
        END IF;
        RETURN public.entries_normalize_attachments(
            jsonb_build_array(trimmed)
        );
    END;

    IF jsonb_typeof(parsed) IN ('array', 'object', 'string') THEN
        RETURN public.entries_normalize_attachments(parsed);
    END IF;

    RETURN '[]'::jsonb;
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_row_attachments(value jsonb, legacy_url text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT public.entries_merge_attachments(
        public.entries_normalize_attachments(value),
        public.entries_parse_attachments(legacy_url)
    );
$$;

CREATE OR REPLACE FUNCTION public.entries_serialize_attachments(value jsonb)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    result text;
BEGIN
    IF value IS NULL OR jsonb_typeof(value) <> 'array' OR jsonb_array_length(value) = 0 THEN
        RETURN NULL;
    END IF;

    SELECT '[' || string_agg(
        '{"name":' || to_json(item ->> 'name')::text ||
        ',"url":' || to_json(item ->> 'url')::text || '}',
        ',' ORDER BY item_position
    ) || ']'
    INTO result
    FROM jsonb_array_elements(value) WITH ORDINALITY AS elements(item, item_position);

    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.entries_content_key(
    value_entry_type text,
    value_date date,
    value_subject text,
    value_summary text
)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT jsonb_build_array(
        value_entry_type,
        value_date,
        value_subject,
        value_summary
    )::text;
$$;

CREATE OR REPLACE FUNCTION public.entries_content_matches(
    row_entry_type text,
    row_date date,
    row_subject text,
    row_summary text,
    candidate_entry_type text,
    candidate_date date,
    candidate_subject text,
    candidate_summary text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT row_entry_type IS NOT DISTINCT FROM candidate_entry_type
       AND row_date IS NOT DISTINCT FROM candidate_date
       AND row_subject IS NOT DISTINCT FROM candidate_subject
       AND row_summary IS NOT DISTINCT FROM candidate_summary;
$$;

DO $$
DECLARE
    generation text;
BEGIN
    SELECT pg_get_expr(
        entries_attribute.attgenerated_expr,
        entries_attribute.attrelid
    )
    INTO generation
    FROM pg_attribute AS entries_attribute
    WHERE entries_attribute.attrelid = 'public.entries'::regclass
      AND entries_attribute.attname = 'content_key'
      AND entries_attribute.attnum > 0
      AND NOT entries_attribute.attisdropped;

    IF generation IS NULL
        OR generation NOT LIKE '%entries_content_key%' THEN
        ALTER TABLE public.entries
            DROP COLUMN IF EXISTS content_key;
    END IF;
END;
$$;

ALTER TABLE public.entries
    ADD COLUMN IF NOT EXISTS content_key text
    GENERATED ALWAYS AS (
        public.entries_content_key(entry_type, date, subject, summary)
    ) STORED;

UPDATE public.entries
SET label = CASE
    WHEN entry_type = 'DiaryEntry' AND NULLIF(btrim(subject), '') IS NOT NULL
        THEN btrim(subject)
    ELSE 'General'
END
WHERE label IS NULL OR btrim(label) = '';

WITH normalized_attachments AS (
    SELECT
        entries.id,
        public.entries_row_attachments(
            entries.attachments,
            entries.attachment_url
        ) AS attachments
    FROM public.entries AS entries
)
UPDATE public.entries AS entries
SET
    attachments = normalized_attachments.attachments,
    attachment_url = public.entries_serialize_attachments(
        normalized_attachments.attachments
    )
FROM normalized_attachments
WHERE entries.id = normalized_attachments.id
  AND (
      entries.attachments IS DISTINCT FROM normalized_attachments.attachments
      OR entries.attachment_url IS DISTINCT FROM public.entries_serialize_attachments(
          normalized_attachments.attachments
      )
  );

UPDATE public.entries
SET created_at = COALESCE(updated_at, now())
WHERE created_at IS NULL;

UPDATE public.entries
SET updated_at = COALESCE(created_at, now())
WHERE updated_at IS NULL;

ALTER TABLE public.entries
    ALTER COLUMN label SET DEFAULT 'General',
    ALTER COLUMN label SET NOT NULL,
    ALTER COLUMN attachments SET DEFAULT '[]'::jsonb,
    ALTER COLUMN attachments SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.entries'::regclass
          AND conname = 'entries_attachments_shape_check'
          AND contype = 'c'
    ) THEN
        ALTER TABLE public.entries
            ADD CONSTRAINT entries_attachments_shape_check
            CHECK (
                jsonb_typeof(attachments) = 'array'
                AND public.entries_attachments_valid(attachments)
            ) NOT VALID;
    END IF;
END;
$$;

ALTER TABLE public.entries
    VALIDATE CONSTRAINT entries_attachments_shape_check;

WITH ranked AS (
    SELECT
        entries.id,
        entries.source_id,
        row_number() OVER (
            PARTITION BY entries.source_id
            ORDER BY
                entries.updated_at DESC NULLS LAST,
                entries.created_at DESC NULLS LAST,
                jsonb_array_length(entries.attachments) DESC,
                entries.id DESC
        ) AS row_position,
        count(*) OVER (PARTITION BY entries.source_id) AS total
    FROM public.entries AS entries
    WHERE entries.source_id IS NOT NULL
), keepers AS (
    SELECT id, source_id
    FROM ranked
    WHERE row_position = 1 AND total > 1
), merged AS (
    SELECT
        keeper.id,
        public.entries_merge_attachments(
            public.entries_row_attachments(
                keeper.attachments,
                keeper.attachment_url
            ),
            COALESCE(
                (
                    SELECT jsonb_agg(
                        item
                        ORDER BY
                            CASE WHEN duplicate.id = keeper.id THEN 0 ELSE 1 END,
                            duplicate.id,
                            items.item_position
                    )
                    FROM public.entries AS duplicate
                    CROSS JOIN LATERAL jsonb_array_elements(
                        public.entries_row_attachments(
                            duplicate.attachments,
                            duplicate.attachment_url
                        )
                    ) WITH ORDINALITY AS items(item, item_position)
                    WHERE duplicate.source_id = keeper.source_id
                ),
                '[]'::jsonb
            )
        ) AS attachments
    FROM public.entries AS keeper
    JOIN keepers ON keepers.id = keeper.id
)
UPDATE public.entries AS entries
SET
    attachments = merged.attachments,
    attachment_url = public.entries_serialize_attachments(merged.attachments)
FROM merged
WHERE entries.id = merged.id;

WITH ranked AS (
    SELECT
        entries.id,
        row_number() OVER (
            PARTITION BY entries.source_id
            ORDER BY
                entries.updated_at DESC NULLS LAST,
                entries.created_at DESC NULLS LAST,
                jsonb_array_length(entries.attachments) DESC,
                entries.id DESC
        ) AS row_position,
        count(*) OVER (PARTITION BY entries.source_id) AS total
    FROM public.entries AS entries
    WHERE entries.source_id IS NOT NULL
)
DELETE FROM public.entries AS entries
USING ranked
WHERE entries.id = ranked.id
  AND ranked.row_position > 1
  AND ranked.total > 1;

WITH ranked AS (
    SELECT
        entries.id,
        entries.entry_type,
        entries.date,
        entries.subject,
        entries.summary,
        row_number() OVER (
            PARTITION BY entries.entry_type, entries.date, entries.subject, entries.summary
            ORDER BY
                entries.updated_at DESC NULLS LAST,
                entries.created_at DESC NULLS LAST,
                jsonb_array_length(entries.attachments) DESC,
                (entries.source_id IS NOT NULL) DESC,
                entries.source_id ASC NULLS LAST,
                entries.id DESC
        ) AS row_position,
        count(*) OVER (
            PARTITION BY entries.entry_type, entries.date, entries.subject, entries.summary
        ) AS total
    FROM public.entries AS entries
), keepers AS (
    SELECT id, entry_type, date, subject, summary
    FROM ranked
    WHERE row_position = 1 AND total > 1
), merged AS (
    SELECT
        keeper.id,
        public.entries_merge_attachments(
            public.entries_row_attachments(
                keeper.attachments,
                keeper.attachment_url
            ),
            COALESCE(
                (
                    SELECT jsonb_agg(
                        item
                        ORDER BY
                            CASE WHEN duplicate.id = keeper.id THEN 0 ELSE 1 END,
                            duplicate.id,
                            items.item_position
                    )
                    FROM public.entries AS duplicate
                    CROSS JOIN LATERAL jsonb_array_elements(
                        public.entries_row_attachments(
                            duplicate.attachments,
                            duplicate.attachment_url
                        )
                    ) WITH ORDINALITY AS items(item, item_position)
                    WHERE public.entries_content_matches(
                        duplicate.entry_type,
                        duplicate.date,
                        duplicate.subject,
                        duplicate.summary,
                        keeper.entry_type,
                        keeper.date,
                        keeper.subject,
                        keeper.summary
                    )
                ),
                '[]'::jsonb
            )
        ) AS attachments
    FROM public.entries AS keeper
    JOIN keepers ON keepers.id = keeper.id
)
UPDATE public.entries AS entries
SET
    attachments = merged.attachments,
    attachment_url = public.entries_serialize_attachments(merged.attachments)
FROM merged
WHERE entries.id = merged.id;

WITH ranked AS (
    SELECT
        entries.id,
        row_number() OVER (
            PARTITION BY entries.entry_type, entries.date, entries.subject, entries.summary
            ORDER BY
                entries.updated_at DESC NULLS LAST,
                entries.created_at DESC NULLS LAST,
                jsonb_array_length(entries.attachments) DESC,
                (entries.source_id IS NOT NULL) DESC,
                entries.source_id ASC NULLS LAST,
                entries.id DESC
        ) AS row_position,
        count(*) OVER (
            PARTITION BY entries.entry_type, entries.date, entries.subject, entries.summary
        ) AS total
    FROM public.entries AS entries
)
DELETE FROM public.entries AS entries
USING ranked
WHERE entries.id = ranked.id
  AND ranked.row_position > 1
  AND ranked.total > 1;

DROP INDEX IF EXISTS public.entries_content_unique_idx;

CREATE UNIQUE INDEX IF NOT EXISTS entries_content_key_unique_idx
    ON public.entries (content_key);

CREATE UNIQUE INDEX IF NOT EXISTS entries_source_id_unique_idx
    ON public.entries (source_id)
    WHERE source_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS entries_date_updated_idx
    ON public.entries (date DESC, updated_at DESC, created_at DESC, id DESC);

CREATE OR REPLACE FUNCTION public.entries_merge_source_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    existing_id bigint;
BEGIN
    IF NEW.source_id IS NULL THEN
        RETURN NEW;
    END IF;

    NEW.source_id := NULLIF(btrim(NEW.source_id), '');
    IF NEW.source_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT existing.id
    INTO existing_id
    FROM public.entries AS existing
    WHERE existing.source_id = NEW.source_id
      AND existing.id IS DISTINCT FROM NEW.id
    ORDER BY
        existing.updated_at DESC NULLS LAST,
        existing.created_at DESC NULLS LAST,
        existing.id DESC
    LIMIT 1
    FOR UPDATE;

    IF existing_id IS NULL THEN
        SELECT existing.id
        INTO existing_id
        FROM public.entries AS existing
        WHERE existing.content_key = public.entries_content_key(
                NEW.entry_type,
                NEW.date,
                NEW.subject,
                NEW.summary
            )
          AND existing.id IS DISTINCT FROM NEW.id
        ORDER BY
            existing.updated_at DESC NULLS LAST,
            existing.created_at DESC NULLS LAST,
            jsonb_array_length(existing.attachments) DESC,
            existing.id DESC
        LIMIT 1
        FOR UPDATE;
    END IF;

    IF existing_id IS NULL THEN
        RETURN NEW;
    END IF;

    UPDATE public.entries
    SET
        entry_type = NEW.entry_type,
        subject = NEW.subject,
        teacher = NEW.teacher,
        date = NEW.date,
        summary = NEW.summary,
        label = COALESCE(NEW.label, 'General'),
        attachments = COALESCE(NEW.attachments, '[]'::jsonb),
        attachment_url = NEW.attachment_url,
        source_id = NEW.source_id
    WHERE id = existing_id;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS entries_merge_source_id_trigger ON public.entries;

CREATE TRIGGER entries_merge_source_id_trigger
    BEFORE INSERT ON public.entries
    FOR EACH ROW
    EXECUTE FUNCTION public.entries_merge_source_id();

CREATE OR REPLACE FUNCTION public.entries_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS entries_touch_updated_at_trigger ON public.entries;

CREATE TRIGGER entries_touch_updated_at_trigger
    BEFORE UPDATE ON public.entries
    FOR EACH ROW
    EXECUTE FUNCTION public.entries_touch_updated_at();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_publication
        WHERE pubname = 'supabase_realtime'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = 'entries'
    ) THEN
        BEGIN
            ALTER PUBLICATION supabase_realtime ADD TABLE public.entries;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'skipping supabase_realtime publication for public.entries';
        END;
    END IF;
END;
$$;

COMMIT;
