# Andruha Messages and Dialogues Service

## Purpose and current status

This repository contains domain models for direct, group, and saved dialogues,
messages with text and attachment object IDs, receipts, and operational HTTP
infrastructure. Application command handlers cover direct/saved/group creation,
group management, message acceptance, text editing and receipt ACKs. Group
creation and editing now use immutable command acceptance for retry recovery.
A bounded private Identity lookup adapter is implemented and tested against
real Identity/Profile. Direct/Saved text sends, HTTP history/list/sync and JWT
authentication are connected to real Cassandra. Group sends, media, edit/delete,
receipts and Kafka/WebSocket delivery remain follow-up slices.

## Domain design

- [Domain vocabulary](CONTEXT.md)
- [DDD and Hexagonal Architecture model proposal, 2026-09-18](docs/domain-model-design-2026-09-18.md)
- [First domain iteration: walkthrough and review points](docs/domain-iteration-1-walkthrough-2026-09-19.md)
- [Domain hardening: Message, groups, media, SOLID, and verification](docs/domain-hardening-walkthrough-2026-09-29.md)
- [Message text editing and frontend edit metadata](docs/message-text-editing-2026-09-30.md)
- [Application use cases and conditional group writes](src/app/application/README.md)

The domain includes dialogue aggregates, messages with text and/or attachment
object IDs, sender-scoped send keys, dialog-scoped message positions,
message checkpoints, receipt watermarks, and posting/delivery policies.
Message contains no dialogue type or recipient field. Policies depend on narrow
dialogue protocols. Groups support up to 1000 members, full history for current
members, membership changes, ownership transfer, renaming, and avatar references.
Attachments and avatars use ObjectId values serialized as UUIDs; S3 keys and
expiring download URLs are not part of the domain state.
The author can edit message text through `Message.edit_text`. Real edits advance
the message version and edit time; equivalent normalized text leaves both unchanged.
`is_edited` and `edited_at` expose edit metadata for a future application DTO.
These properties do not add fields to the existing public messaging schemas.
The domain does not verify attachment ownership or readiness; an application
scenario must validate object IDs with Object Storage before acceptance.
Attachment size, media type, checksum, and S3 object keys belong to Object Storage.
Domain limits are collected in [`src/app/domain/limits.py`](src/app/domain/limits.py).
Runtime defaults are at the top of `src/app/core/settings.py`; the request ID
length default is at the top of its HTTP policy file.
Message acceptance and receipt ACKs require a durable adapter implementing the
conditional repository contract. Application concurrency tests simulate that port.

## Responsibility and explicit non-responsibilities

Own dialogue, message, and receipt rules and their application command handlers;
add durable storage and transport integration in subsequent iterations.

It does not own credentials, public profiles, media object bytes, connection routing, presence, typing state, or online delivery.

## Hexagonal/DDD layer map

- `domain`: dialogue, message, and receipt models, value objects, policies, and domain errors, using Pydantic for validation.
- `application`: concrete command/handler use cases, typed results, and owned ports; depends only on domain.
- `infrastructure`: the bounded Identity eligibility client; durable persistence
  and other runtime adapters are being added in separate verified slices.
- `entrypoints`: transport translation that will call application command handlers.
- `core`: configuration and cross-cutting logging only.

The dependency direction is `entrypoints -> application -> domain` and `infrastructure -> application ports -> domain`.

## Entrypoints

- `app.entrypoints.http.main:create_app` - FastAPI factory
- `GET /health/live` - process liveness
- `GET /health/ready` - initialized application readiness
- `app.entrypoints.messaging` - empty future messaging transport boundary

The business role exposes `/api/v1/dialogues/direct`, `/saved`, `/`, `/sync`,
`/{dialogId}`, `/{dialogId}/messages` and message point reads. Actor IDs come
only from verified Identity JWTs. Create returns 201/200; text send returns 200
after required storage effects. HTTP schemas are published by `/openapi.json`.
The parent `docs/contracts/messages-http-v1.md` describes pagination and errors.
Kafka publisher/consumer and WebSocket delivery are not connected yet.

## Configuration variables

- `SERVICE_NAME`, `APP_VERSION`, `APP_ENVIRONMENT`
- `HOST`, `PORT`
- `DEV_LOGS`, `LOG_LEVEL`, `MUTE_LOGGERS`

Настройки валидируются через `pydantic-settings`; сервис читает их из переменных
окружения и UTF-8-файла `.env`.

## Liveness and readiness

`GET /health/live` reports that the process is running. Operational-only mode
reports readiness after lifespan initialization. With `MESSAGING_ENABLED=true`,
startup requires real Cassandra schema, JWT public keys, an Identity service
credential and a persistent cursor key. Readiness follows Cassandra/schema:
an outage returns 503 while live remains 200. Ordinary sends/reads use local
JWT verification and do not require Identity or Kafka to be available.

## Local build and run status

Runtime and test dependencies are declared and locked for Python 3.14 with `uv`. The
service can be verified from this repository with:

```powershell
uv sync
uv run prek install
uv run prek run --all-files
uv run pytest
docker build --target runtime --tag andruha/messages-dialogues-service:local .
```

### Cassandra storage and migrations

All runtime and migration CQL uses the async driver API. Native connect/shutdown
are isolated in the approved lifecycle executor; migrations run as a separate CLI.
The adapters implement Direct/Saved creation, text acceptance/recovery,
history/point/card/sync projections and durable event envelopes with fenced
outbox claims. Group creation/membership is implemented separately; group sends,
receipt/edit/delete adapters and Kafka delivery remain open.

Business configuration:

- `MESSAGING_ENABLED=true`, `MESSAGING_CASSANDRA_CONFIG=cqltrack.yml`;
- `CQLTRACK_CONTACT_POINTS`, `CQLTRACK_PORT`, `CQLTRACK_KEYSPACE` and existing
  cql-track connection settings;
- `MESSAGING_IDENTITY_URL`, `MESSAGING_IDENTITY_SERVICE_TOKEN`;
- `JWT_PUBLIC_KEYS` (JSON key ID to PEM path), `JWT_ISSUER`, `JWT_AUDIENCE`;
- `MESSAGING_CURSOR_KEY_FILE`: at least 32 persistent random bytes;
- `MESSAGING_REPAIR_INTERVAL_SECONDS` (default 1): bounded recovery polling.

V003/V004 add global send keys and read/work/outbox tables. The dialog CAS
allocates a position and saves message plus event envelopes together. A durable
work hint precedes acceptance. Completion archives the result before retiring
the working row. SERIAL reads and revision advancement during retirement fence
stale absence. No unfinished recovery material has a TTL. Storage limits are
collected in `src/app/infrastructure/persistence/cassandra/limits.py`.

History and user journal buckets hold at most 256 rows. Canonical working sets
hold at most 256 sends; recovery/outbox discovery has 16 shards capped at 256
tasks each. Full queues return 503 and retain accepted work. User journal heads
hold at most 256 pending changes and 1 MiB. Dialog lists use stable creation
order; activity updates are guarded by message position. Lifetime cleanup,
sync retention, publisher retry policy and capacity metrics remain open.

Connection flow, consistency, unknown outcomes, paging, migration commands and
recovery are documented in [Database interactions](docs/database-interactions.md).

From the parent checkout, real isolated Cassandra checks run with:

```powershell
python scripts/verification/run_messages_checks.py
```

Standalone integration runs require MESSAGES_TEST_CASSANDRA_HOST and
MESSAGES_TEST_CASSANDRA_PORT; fixtures create/drop only their unique keyspaces.

`.github/workflows/ci.yml` runs prek quality hooks, ty type checking, unit and
integration tests, branch coverage >= 80%, runtime dependency audit, secret
scanning, and a Docker smoke test. `.github/workflows/release.yml` publishes a
verified image to GHCR only for a version tag. The parent
`scripts/e2e/run_messages.py` verifies real registered A/B users through Gateway,
Identity/Profile and Messages, using an exclusively owned Docker project.

## Canonical project material

- [Documentation](https://github.com/yemeal/andruha-messenger/tree/main/docs)
- [Contracts](https://github.com/yemeal/andruha-messenger/tree/main/contracts)
