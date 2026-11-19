# Cassandra: canonical command journal and bounded projections

**Status:** Direct/Saved text acceptance and bounded projections are implemented;
group creation/membership proof is implemented. Full acceptance remains open for
group sends, edit/delete, receipts and broker delivery.
**Date:** 2026-11-16.

ADR-0001 and the approved backlog require one conditional table/partition for
group authorization, revision, mutation and command acceptance. Cassandra remains
the selected Messages store. PostgreSQL UoW semantics are not assumed across
Cassandra, Kafka or HTTP peers.

## Selected base

`canonical_rows` is partitioned by dialog ID. The `state` row contains the
current group snapshot, common revision, last accepted message position, immutable
creation intent/result and a working-command count. A client-supplied creation
UUIDv7 is also the group ID, allowing the initial state and creation acceptance
to be inserted atomically with `IF NOT EXISTS` without a cross-partition lookup.
Membership commits update state/revision and insert immutable command intent/result
in one conditional batch. Existing creation identity/time and old command results
survive a new adapter instance and retries.

Writes use QUORUM + SERIAL. Revision-bound reads use SERIAL before/after the
requested row, including absence. A changed revision raises GroupReadConflictError.
Timeout is not CAS rejection: re-read the durable acceptance; only a matching
saved result confirms success. Missing/unreadable acceptance remains unavailable.

The adapters use cassandra-driver 3.30.1 and pyasyncore 1.0.4 for Python 3.14
on Windows/Linux. Every runtime and migration CQL request uses execute_async,
bridged to an asyncio Future. Only native connect/shutdown use the explicitly
approved single-worker lifecycle executor. One shared async session bounds
in-flight requests, preserves unknown outcomes on cancellation, drains before
shutdown and exposes explicit asynchronous pagination.

The async migration runner owns apply/rollback/history/status/diff, strict schema
agreement and a persistent LWT lock. cql-track 1.1.0 supplies the CQL parser,
checksum format, configuration and diff DTO; its synchronous Migrator is unused.
Partial upgrade/rollback is recorded and requires inspection plus explicit resume.
The outer lock has no TTL; recovery after a killed job requires stopping the old
job and checking its outcome before releasing its exact owner. Applied files are
not rewritten. See [Database interactions](../database-interactions.md).

## Access patterns to complete in MD-N05/06/08/09

| Data / request | Partition and continuation |
|---|---|
| Direct A–B / B–A creation | Normalized pair reservation; stable winning UUIDv7/time; repair canonical-by-ID and required projections before success. |
| Saved creation | Owner reservation with the same repair requirements. |
| Group command | `canonical_rows(dialog_id)`; shared revision for membership/send/edit/delete/receipt and immutable acceptance. |
| Global send identity | One bounded row keyed by `(sender_id, client_message_id)`, independent of dialog/type/date; no TTL that permits key reuse while message retention lasts. |
| Archived command result | One bounded row keyed by `(dialog_id, command_id)`; immutable acceptance retained for the associated business lifetime. |
| History | Deterministic integer-position buckets with a fixed row cap; an opaque signed cursor captures its upper position. Month changes cannot reorder integer positions. |
| Message point read | `(dialog_id, message_id)` locator/current snapshot; overlay a newer working canonical mutation before returning content. |
| Receipt | Dialog/user watermark and per-reader version, bounded batch reads for history status. Reader-detail indexing follows MD-N13. |
| User list/sync | Bounded journal/index buckets, idempotent target event identity and version guards; cursor binds actor/query/order and distinguishes expired retention from an empty page. |
| Recovery discovery | Durable bounded work hints created before canonical acceptance; unfinished hints/results do not expire. Admission and completion need a tested fencing protocol. |

Every hot request must have a known partition key. No ALLOW FILTERING or full
cluster scan is permitted. A reservation is not SENT: message/position acceptance
and recovery material must commit inside the canonical boundary before success.

## Working-set retention and admission

The canonical working set defaults to 256 accepted commands and fails closed
when full. Direct/Saved sends now archive confirmed results and project effects
before conditionally retiring working rows/counts. Group command archive/drain
remains open. Unfinished work has no TTL.
Readers must prefer newer working rows over archived projections. Retiring a row
must prove that its exact version is durable in projections and that no newer
mutation is being discarded. Old repair must not overwrite newer message,
membership, receipt, activity or sync versions.

The archive and global send-key partitions contain bounded individual records.
History/journal buckets are bounded by position/count rather than an unbounded
dialog partition. The configurable command cap is admission/backpressure, not
an invitation to discard old acceptance rows when the partition fills.

## Alternatives and consequences

Separate CAS of group state followed by ordinary message INSERT was rejected:
it permits success against removed membership and loses recovery material on
crash. A PostgreSQL rewrite contradicts the approved storage choice. A single
owner/actor per dialog would require a new ownership/rebalance protocol and does
not remove global send-key/recovery requirements.

The common revision serializes writes to a hot group. LWT and snapshot costs are
accepted for the current service; no production HA/throughput guarantee follows.
Cross-partition projections require explicit recovery. Event ID/envelope is
allocated once at canonical acceptance and reused for publishing; this is
at-least-once delivery, not an exactly-once Cassandra/Kafka transaction.

## Acceptance gates

- Creation/membership, last-place race, changed-revision absence and loss of a
  real conditional-commit response: real isolated Cassandra tests.
- Send-key cross-dialog uniqueness, position races, send/edit/ACK versus removal,
  archive/retire fencing and partial projections: required before full MD-N06/08.
- No-op/replay must fence fresh rights without replacing the old result.
- Deletion follows the approved author/current-group-owner, no-window,
  no-restore policy; versioned tombstones prevent old repair from resurrection.
- Migrations/checksum, bounded admission, deterministic replay and dependencies
  are verified separately from the existing HTTP bootstrap suite.

Sources: [CQL conditional batches](https://cassandra.apache.org/doc/latest/cassandra/developing/cql/dml.html),
[driver serial consistency](https://github.com/apache/cassandra-python-driver/blob/trunk/cassandra/query.py),
[driver event-loop support](https://github.com/apache/cassandra-python-driver/blob/trunk/docs/installation.rst).
Migration format helpers: [cql-track](https://github.com/ereshzealous/cql-track),
[PyPI release](https://pypi.org/project/cql-track/1.1.0/).
