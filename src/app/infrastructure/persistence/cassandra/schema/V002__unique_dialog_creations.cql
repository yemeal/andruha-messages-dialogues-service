CREATE TABLE IF NOT EXISTS dialog_creations (
    creation_key text PRIMARY KEY,
    dialog_id uuid,
    dialog_kind text,
    payload text
);

-- @down
DROP TABLE IF EXISTS dialog_creations;
