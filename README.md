# Andruha Messages and Dialogues Service

## Purpose and current status

This repository contains the first domain increment for direct dialogues and
operational HTTP infrastructure. `DirectParticipants` and `DirectDialog` enforce
local domain rules; application use cases, persistence, and business endpoints
are not connected yet.

## Domain design

- [Domain vocabulary](CONTEXT.md)
- [DDD and Hexagonal Architecture model proposal, 2026-09-18](docs/domain-model-design-2026-09-18.md)
- [First domain iteration: walkthrough and review points](docs/domain-iteration-1-walkthrough-2026-09-19.md)

The direct-dialogue domain increment is implemented and unit-tested. Message and
receipt models remain design proposals for subsequent iterations.

## Responsibility and explicit non-responsibilities

Own dialogue membership rules now; add durable dialogues, messages, and receipt
state in subsequent iterations.

It does not own credentials, public profiles, media object bytes, connection routing, presence, typing state, or online delivery.

## Hexagonal/DDD layer map

- `domain`: immutable direct-dialogue models and domain errors, using Pydantic for validation.
- `application`: future use cases and owned ports; depends only on domain.
- `infrastructure`: future adapters implementing application ports.
- `entrypoints`: transport translation that will call application services.
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
