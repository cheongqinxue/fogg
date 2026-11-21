-- Pre-release FOGG baseline. LangGraph manages its own checkpoint tables.

CREATE TABLE agent_chat_messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX agent_chat_messages_account_id_id_idx ON agent_chat_messages (account_id, id DESC);

CREATE TABLE agent_chat_migrations (
    migration_key TEXT PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent_chat_migrated_users (
    account_id TEXT PRIMARY KEY,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent_user_layout (
    account_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    layout_hash TEXT NOT NULL,
    layout JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE agent_user_tool_preferences (
    account_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    active BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, tool_name)
);

CREATE TABLE agent_user_provider_credentials (
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    ciphertext TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    legacy_encryption_owner TEXT,
    PRIMARY KEY (account_id, provider)
);

CREATE TABLE users (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    legacy_subject TEXT UNIQUE CHECK (btrim(legacy_subject) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_bio_details (
    account_id UUID PRIMARY KEY REFERENCES users(account_id) ON DELETE CASCADE,
    name TEXT CHECK (btrim(name) <> ''),
    gender TEXT CHECK (btrim(gender) <> ''),
    home_formatted_address TEXT CHECK (btrim(home_formatted_address) <> ''),
    home_country_code TEXT CHECK (home_country_code ~ '^[A-Z]{2}$'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE immigration_statuses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES users(account_id) ON DELETE CASCADE,
    country_code TEXT NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    kind TEXT NOT NULL CHECK (kind IN ('citizenship', 'permanent_resident', 'visa')),
    valid_from DATE,
    valid_until DATE,
    label TEXT,
    CHECK (valid_until >= valid_from)
);

CREATE INDEX immigration_statuses_account_id_idx ON immigration_statuses (account_id);

CREATE TABLE user_summaries (
    account_id UUID PRIMARY KEY REFERENCES users(account_id) ON DELETE CASCADE,
    preference_summary TEXT CHECK (btrim(preference_summary) <> ''),
    trip_summary TEXT CHECK (btrim(trip_summary) <> ''),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_password_credentials (
    account_id UUID PRIMARY KEY REFERENCES users(account_id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(btrim(email)) AND email <> ''),
    password_salt BYTEA NOT NULL CHECK (octet_length(password_salt) = 16),
    password_hash BYTEA NOT NULL CHECK (octet_length(password_hash) = 32)
);

CREATE TABLE user_sessions (
    token_hash BYTEA PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    account_id UUID NOT NULL REFERENCES users(account_id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX user_sessions_account_id_idx ON user_sessions (account_id);

CREATE TABLE account_identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    account_id UUID NOT NULL REFERENCES users(account_id) ON DELETE CASCADE,
    PRIMARY KEY (provider, subject)
);

CREATE INDEX account_identities_account_id_idx ON account_identities (account_id);
