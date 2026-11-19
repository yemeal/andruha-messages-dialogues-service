CREATE TABLE IF NOT EXISTS message_sends (
    sender_id uuid,
    client_message_id uuid,
    payload text,
    PRIMARY KEY ((sender_id, client_message_id))
);

-- @down
DROP TABLE IF EXISTS message_sends;
