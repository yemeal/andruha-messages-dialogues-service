# Cassandra: взаимодействие с БД

Область: адаптеры Messages, Direct/Saved text HTTP и runner миграций.
Group send/edit/delete/receipt и Kafka delivery остаются следующими этапами.

## Подключение и запросы

- Владелец соединения — `cassandra_connection(config)`. Один Cluster/Session на
  scope роли; репозитории получают общий `AsyncCassandraSession`.
- Согласованное исключение: native `Cluster.connect()/shutdown()` работают в
  отдельном lifecycle executor с **одним потоком**, вместе с внутренним bootstrap
  драйвера. Явные CQL приложения туда не передаются.
  Выбор keyspace — асинхронный `USE` после подключения.
- Каждый CQL: `await adapter.execute(...)` → `Session.execute_async()` → callback
  драйвера → `loop.call_soon_threadsafe` → asyncio Future. В этих путях нет
  `Session.execute()`, `ResponseFuture.result()` и query-offload через `to_thread`.
- По умолчанию максимум 128 незавершённых запросов на общий adapter. Таймаут 5 с
  включает ожидание допуска; отправленному запросу передаётся оставшийся срок.
- Отмена caller не отменяет принятую Cassandra операцию. In-flight slot остаётся
  занят до ответа драйвера. Закрытие запрещает новые запросы, дожидается текущих,
  затем закрывает Cluster. Отмена подключения освобождает поздно полученный ресурс.
- `QueryPage` содержит одну страницу. Следующая запрашивается отдельным await с
  `paging_state`; синхронной автопагинации нет. `fetch_all` требует лимит строк и
  общий timeout. Raw paging state не является публичным cursor API.

## Реализованные операции

| Операция | Таблицы и атомарная граница | Подтверждение результата |
|---|---|---|
| Direct / Saved create | `dialog_creations`: одна запись на нормализованную пару / owner; затем idempotent materialization `canonical_rows.state` | LWT IF NOT EXISTS; ID/time победителя сохраняются, незавершённая materialization чинится повтором. |
| Group create | `canonical_rows`, partition = operation UUIDv7 = dialog ID | Initial state + immutable intent/result сохраняются одним LWT. |
| Group membership | State/revision + immutable command acceptance в одном partition `canonical_rows` | Conditional batch проверяет revision; serial чтения до/после защищают результат и достоверность отсутствия. |
| Send reservation | `message_sends`, один partition на `(sender_id, client_message_id)` | LWT сохраняет одного кандидата между Direct/Saved. Другой dialog/content с тем же ключом отклоняется. |
| Принятие текста | State/revision/position и `send:*` в одном partition `canonical_rows` | Один conditional batch сохраняет Message и первоначальные event envelopes. Позиция назначается заново при подтверждённом конфликте CAS. |
| Обнаружение repair | `work_rows`, известные kind/shard, отдельные head/task | Conditional admission ограничивает каждый из 16 shards 256 задачами. Hint записан до принятия send; незавершённое восстановление не имеет TTL. |
| History / point | `message_history` по position bucket, `message_lookup` по `(dialog_id, message_id)` | Проекции записываются до успеха send. History объединяет bounded рабочие строки с проекцией, подтверждая неизменную revision до/после чтения. |
| Карточки / sync | `user_projection_state`, `user_projection_results`, `user_dialogs`, `user_sync` | User CAS назначает sequence один раз. Сначала записываются карточка/журнал/result, затем продвигается published boundary. Старый repair не уменьшает activity position. |
| Durable outbox | Envelopes внутри canonical acceptance, затем `message_outbox` и work hints | ID/envelope не меняются при repair. Claim/reclaim/complete используют CAS revision и claim token/expiry. Broker publisher ещё не включён. |
| Миграции | `andruha_schema_lock`, `cqltrack_history`, versioned CQL, системные schema tables | Persistent LWT lock, checksum, последовательный DDL, await schema agreement. |

Canonical writes: **QUORUM + SERIAL**. Revision-bound/acceptance reads: **SERIAL**.
Timeout не означает отклонённую запись: сохранённый результат читается повторно;
отсутствие подтверждения даёт StorageUnavailable, не успех. Working journal группы
ограничен 256 командами; group archive/drain ещё не реализован. Для Direct/Saved
send подтверждённый результат архивируется в `message_sends.acceptance` до
условного удаления рабочей строки. Удаление увеличивает revision, поэтому
устаревший writer с прочитанным отсутствием не принимает send заново.

History/sync buckets ограничены 256 позициями; user head — 256 pending changes
и 1 MiB. Outbox owner token назначают заново для каждой claim-попытки; это не
постоянный идентификатор worker. Истечение lease запрещает старому owner
финализировать результат. Данные журнала и terminal outbox пока без очистки;
retention/GC относятся к эксплуатационному этапу.

При недоступной Cassandra адаптер переводит и `NoHostAvailable` (он не наследник
`DriverException`) в StorageUnavailable. HTTP даёт 503, а не SENT/500. Failed
conditional batch может вернуть несколько строк; `QueryPage.was_applied`
проверяет согласованный `[applied]` в этих строках без sync driver helper.

`get_by_participants/get_by_owner` ремонтируют materialization уже принятого
создания и используются create-командами. Публичные queries используют отдельные
read paths; `get_by_id` не создаёт состояние. Membership проверяется до истории
и point reads; list/sync адресуются проверенному actor. Подписанные cursors
связывают actor/resource/order/upper boundary и срок, raw driver paging state
наружу не передаётся.

## Миграции

Runner наш, асинхронный. Из `cql-track 1.1.0` используются CQL parser/checksum,
конфигурация и DTO diff; синхронный Migrator не вызывается. Формат:
`V001__name.cql`, UP CQL и необязательная секция `-- @down`.
Для изменения схемы используется только CLI ниже: upstream `cqltrack migrate`
не учитывает наши lock/recovery состояния.

Из каталога сервиса (PowerShell):

```powershell
$env:PYTHONPATH = "src"
$env:CQLTRACK_CONTACT_POINTS = "127.0.0.1"
$env:CQLTRACK_KEYSPACE = "messages"
uv run python -m app.entrypoints.migrations migrate
uv run python -m app.entrypoints.migrations status
uv run python -m app.entrypoints.migrations history
uv run python -m app.entrypoints.migrations diff --target-keyspace messages_reference
uv run python -m app.entrypoints.migrations rollback --steps 1
```

Keyspace и DC/replication создаются отдельно. В локальном Compose это задача
`messages-keyspace` (RF=1), за ней `messages-migrate`; business HTTP стартует
после успешных миграций. Connection settings: `cqltrack.yml`,
`CQLTRACK_PORT/USERNAME/PASSWORD/CONSISTENCY`; TLS — в private YAML. Зависимости
закреплены в lockfile, загрузка через Tsinghua с проверкой TLS.

- Lock не истекает по TTL; release условен по owner UUID. После аварии сначала
  остановить старую job, проверить исход её CQL и схему, прочитать owner, удалить только его:
  `DELETE FROM andruha_schema_lock WHERE lock_id='schema' IF owner=<UUID>`.
- История содержит applying/applied/failed/rolling_back/rollback_failed.
  Частичный сбой блокирует обычный запуск. После проверки состояния
  `migrate --resume` или `rollback --resume` повторяет **всю** затронутую миграцию;
  скрипт должен допускать такой повтор. Автоматического отката DDL нет.
  `--resume` не обходит checksum: исправление файла с уже записанной checksum
  требует отдельного операторского восстановления; автоматического repair нет.
- Успешный rollback выполняет DOWN CQL и удаляет запись применения версии.
  `history` показывает состояние версий, а не append-only аудит попыток.
  DOWN может удалять данные; это не транзакционный rollback и не backup.
- После каждого DDL сравниваются schema_version всех известных живых hosts.
  Deadline без согласования останавливает выполнение. Diff читает свежие
  system_schema через async pagination; изменение schema_version во время
  сравнения требует повторного запуска.
- Diff охватывает таблицы, колонки/ключи/порядок, indexes, UDT,
  TTL/gc/compaction/compression; остальные schema options в этом этапе не сравниваются.
- История ограничена 1000 версиями, schema inspection — 10000 строк на запрос.
  Превышение даёт ошибку, не усечение. Checksum обнаруживает дрейф файла и не
  является криптографической защитой схемы.

## Проверки и границы этапа

Integration использует настоящую Cassandra, уникальные keyspaces и teardown.
Native sync API остаётся в тестовой harness для setup и контрольных чтений;
regression tests запрещают его в runtime/migration paths. Многонодовый кластер и
TLS/auth-enabled Cassandra отдельно ещё не проверялись. Direct/Saved text send,
projections/outbox recovery и HTTP history/sync проверены реальными адаптерами;
E2E с Identity/Profile/Gateway проверяет concurrent replay, restart и остановку/
запуск Cassandra. Group messages, receipts, edit/delete, broker delivery и media
остаются backlog. Итоговые counts и evidence — в parent implementation report.
