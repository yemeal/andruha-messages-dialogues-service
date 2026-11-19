CREATE TABLE IF NOT EXISTS canonical_rows (
    dialog_id uuid,
    row_key text,
    revision bigint,
    last_position bigint,
    pending_count int,
    payload text,
    intent text,
    result text,
    command_kind text,
    PRIMARY KEY ((dialog_id), row_key)
);

-- @down
DROP TABLE IF EXISTS canonical_rows;
