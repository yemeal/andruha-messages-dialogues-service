# Andruha Messages and Dialogues Service

## Purpose and current status

This repository contains domain models for direct, group, and saved dialogues,
messages with text and attachment object IDs, receipts, and operational HTTP
infrastructure. Six concrete application command handlers cover direct/saved
creation and group membership, message acceptance, and receipt ACKs. Persistence,
external clients, and business endpoints are not connected yet.

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
- `infrastructure`: future adapters implementing application ports.
- `entrypoints`: transport translation that will call application command handlers.
- `core`: configuration and cross-cutting logging only.

The dependency direction is `entrypoints -> application -> domain` and `infrastructure -> application ports -> domain`.

## Entrypoints

- `app.entrypoints.http.main:create_app` - FastAPI factory
- `GET /health/live` - process liveness
- `GET /health/ready` - initialized application readiness
- `app.entrypoints.messaging` - empty future messaging transport boundary

No business API or transport contract is available yet.

## Configuration variables

- `SERVICE_NAME`, `APP_VERSION`, `APP_ENVIRONMENT`
- `HOST`, `PORT`
- `DEV_LOGS`, `LOG_LEVEL`, `MUTE_LOGGERS`

## Liveness and readiness

`GET /health/live` reports that the process is running. `GET /health/ready` reports readiness after application lifespan initialization. It intentionally performs no fake dependency probes.

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

`.github/workflows/ci.yml` runs prek quality hooks, ty type checking, unit and
integration tests, branch coverage >= 80%, runtime dependency audit, secret
scanning, and a Docker smoke test. `.github/workflows/release.yml` publishes a
verified image to GHCR only for a version tag. Business APIs and persistence
remain deferred.

## Canonical project material

- [Documentation](https://github.com/yemeal/andruha-messenger/tree/main/docs)
- [Contracts](https://github.com/yemeal/andruha-messenger/tree/main/contracts)
