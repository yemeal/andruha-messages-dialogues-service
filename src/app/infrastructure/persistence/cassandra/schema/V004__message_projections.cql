ALTER TABLE message_sends ADD acceptance text;

CREATE TABLE IF NOT EXISTS work_rows (
    kind text,
    shard int,
    row_key text,
    revision bigint,
    pending_count int,
    payload text,
    PRIMARY KEY ((kind, shard), row_key)
);

CREATE TABLE IF NOT EXISTS message_history (
    dialog_id uuid,
    bucket bigint,
    position bigint,
    payload text,
    PRIMARY KEY ((dialog_id, bucket), position)
);

CREATE TABLE IF NOT EXISTS message_lookup (
    dialog_id uuid,
    message_id uuid,
    payload text,
    PRIMARY KEY ((dialog_id, message_id))
);

CREATE TABLE IF NOT EXISTS user_projection_state (
    user_id uuid PRIMARY KEY,
    revision bigint,
    payload text
);

CREATE TABLE IF NOT EXISTS user_projection_results (
    user_id uuid,
    event_key text,
    sequence bigint,
    PRIMARY KEY ((user_id, event_key))
);

CREATE TABLE IF NOT EXISTS user_sync (
    user_id uuid,
    bucket bigint,
    sequence bigint,
    payload text,
    PRIMARY KEY ((user_id, bucket), sequence)
);

CREATE TABLE IF NOT EXISTS user_dialogs (
    user_id uuid,
    bucket bigint,
    ordinal bigint,
    last_position bigint,
    payload text,
    PRIMARY KEY ((user_id, bucket), ordinal)
);

CREATE TABLE IF NOT EXISTS message_outbox (
    event_id uuid PRIMARY KEY,
    revision bigint,
    payload text
);

-- @down
DROP TABLE IF EXISTS message_outbox;
DROP TABLE IF EXISTS user_dialogs;
DROP TABLE IF EXISTS user_sync;
DROP TABLE IF EXISTS user_projection_results;
DROP TABLE IF EXISTS user_projection_state;
DROP TABLE IF EXISTS message_lookup;
DROP TABLE IF EXISTS message_history;
DROP TABLE IF EXISTS work_rows;
ALTER TABLE message_sends DROP acceptance;
