-- schema.sql

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    timezone TEXT DEFAULT 'UTC',
    jlpt_focus_level TEXT DEFAULT 'N5',
    notification_time TIME DEFAULT '06:00',
    daily_new_word_target INT DEFAULT 10,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    original_filename TEXT,
    storage_path TEXT,
    status TEXT DEFAULT 'processing', -- processing | ready | failed
    is_active BOOLEAN DEFAULT true,
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    item_count INT DEFAULT 0,
    detected_jlpt_levels TEXT[] DEFAULT '{}'
);

CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL, -- vocabulary | kanji | sentence | grammar
    text_ja TEXT NOT NULL,
    reading TEXT,
    romaji TEXT,
    meaning_en TEXT,
    part_of_speech TEXT,
    example_sentence_ja TEXT,
    example_sentence_en TEXT,
    jlpt_level TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE item_sources (
    item_id UUID REFERENCES items(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, document_id)
);

CREATE TABLE memory_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    item_id UUID REFERENCES items(id) ON DELETE CASCADE,
    ease_factor REAL DEFAULT 2.5,
    interval_days REAL DEFAULT 0,
    repetitions INT DEFAULT 0,
    next_due_date DATE DEFAULT CURRENT_DATE,
    last_result TEXT,
    mastery_state TEXT DEFAULT 'new', -- new | learning | review | mastered
    total_reviews INT DEFAULT 0,
    total_correct INT DEFAULT 0,
    last_reviewed_at TIMESTAMPTZ,
    UNIQUE(user_id, item_id)
);

-- schema.sql (add this table for the archive referenced above, Section 6.2)
CREATE TABLE memory_records_archive (LIKE memory_records INCLUDING ALL);


CREATE TABLE daily_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    plan_date DATE NOT NULL,
    word_of_day_item_id UUID REFERENCES items(id),
    study_set_item_ids UUID[] DEFAULT '{}',
    quiz_item_ids UUID[] DEFAULT '{}',
    generated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, plan_date)
);

CREATE TABLE review_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    item_id UUID REFERENCES items(id) ON DELETE CASCADE,
    event_type TEXT, -- flashcard | quiz
    result TEXT,     -- again | hard | good | easy
    created_at TIMESTAMPTZ DEFAULT now()
);

-- schema.sql (add to users table, or new settings table)
ALTER TABLE users ADD COLUMN quiet_hours_start TIME DEFAULT '22:00';
ALTER TABLE users ADD COLUMN quiet_hours_end TIME DEFAULT '07:00';
ALTER TABLE users ADD COLUMN reminder_times TIME[] DEFAULT ARRAY['06:00'::TIME];

-- schema.sql (add)
CREATE TABLE speaking_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    item_id UUID REFERENCES items(id) ON DELETE CASCADE,
    transcript TEXT,
    score INT,
    text_similarity REAL,
    stt_confidence REAL,
    created_at TIMESTAMPTZ DEFAULT now()
);