# Application: конкретные use cases

Структура следует `application/commands` User Profile Service: неизменяемая
`BaseCommand[ResultT]`, отдельный `command.py`, `handler.py` с асинхронным
`__call__` и типизированный результат. Handler получает репозитории и внешние
порты через конструктор; часы и генератор UUIDv7 передаются как callables.
Бизнес-инварианты остаются в существующих доменных агрегатах и policies.

| Каталог commands | Команда / Handler | Результат |
| --- | --- | --- |
| `dialogues/create_direct` | `CreateDirectDialogCommand` / `CreateDirectDialogHandler` | `CreateDirectDialogResult` |
| `dialogues/create_saved` | `CreateSavedDialogCommand` / `CreateSavedDialogHandler` | `CreateSavedDialogResult` |
| `groups/add_member` | `AddGroupMemberCommand` / `AddGroupMemberHandler` | `GroupDialogDTO` |
| `groups/remove_member` | `RemoveGroupMemberCommand` / `RemoveGroupMemberHandler` | `GroupDialogDTO` |
| `groups/send_message` | `SendGroupMessageCommand` / `SendGroupMessageHandler` | `SendGroupMessageResult` |
| `groups/advance_receipt` | `AdvanceGroupReceiptCommand` / `AdvanceGroupReceiptHandler` | `AdvanceGroupReceiptResult` |

Например, после сборки зависимостей вызывающий код выполняет:

```python
result = await handler(CreateDirectDialogCommand(actor_id=actor_id, peer_id=peer_id))
```

`actor_id` поступает из проверенного principal. Handler не проверяет JWT,
не выбирает HTTP-статус и не подтверждает Kafka offset.

## Каноническое создание

Создание Direct сначала строит `DirectParticipants`: self-dialog отклоняется,
A–B и B–A обозначают один ключ. Для нового диалога handler проверяет завершённую
регистрацию обоих пользователей через `RegisteredUsersProtocol`. Создание Saved
проверяет владельца. Отрицательный ответ Identity и недоступность Identity —
разные application exceptions; Profile existence не заменяет подтверждение.

`create_or_get(candidate)` — атомарный контракт репозитория, возвращающий
сохранённого победителя и признак создания. Application не обеспечивает
распределённую уникальность предварительным чтением. При конкуренции в проекции
и результат попадают ID и время победителя, а не проигравшего кандидата.

Успех возвращается после `ensure_for_user` для обоих участников Direct или
владельца Saved. Ошибка проекции даёт `DialogProjectionsIncompleteError` с
каноническим dialog ID, user ID и исходной причиной. Повтор команды использует
каноническую запись и восстанавливает обязательные представления, даже если
Identity временно недоступен. Первоначальные значения activity/preview/unread
не должны заменять более свежие значения: это гарантия порта проекций.

## Согласованность групп

Каждый групповой handler сам выполняет цикл: загрузить `GroupSnapshot`, вызвать
доменную операцию, попытаться условно сохранить результат. Отдельного dispatch
или универсального исполнителя команд в этой итерации нет.

`GroupSnapshot` содержит доменный `GroupDialog`, техническую `revision` и
последнюю принятую позицию сообщения. Доменные `version` и `updated_at`
изменяются по существующим правилам агрегата. `revision` увеличивается при
каждом успешно принятом действии и связывает состав с записью сообщения/ACK.

`try_commit(expected, mutation, command_id=...)` обязан атомарно проверить
ревизию, записать результат и подтверждение command ID, затем продвинуть
ревизию. Для сообщения в эту же операцию входит новая позиция истории.
Последовательные «проверить версию → записать сообщение» не подходят.

`False` означает подтверждённый конфликт без частичных эффектов. Handler снова
читает актуальный состав и заново выполняет доменную проверку. Исключённый
actor получает отказ; второй кандидат на последнее место получает
`GroupMemberLimitExceededError`. Для остающегося участника повтор пересчитывает
позицию сообщения и ACK по свежему состоянию. По умолчанию разрешено восемь
попыток; после их исчерпания возвращается `ConcurrentModificationError`.

Повторное сообщение и no-op ACK тоже проходят условную запись (`mutation=None`).
Это подтверждает актуальность прав перед успешным результатом, сохраняя
идентичность сообщения, watermark version и доменное время.

Если запись сообщения/ACK победила до исключения, она сохраняется: протокол
задаёт порядок успешных действий. После сохранённого исключения новый успех
по старому составу недопустим. READ по-прежнему подразумевает DELIVERED;
ACK допускается только для сохранённого входящего сообщения.

Неизвестный исход commit разрешает адаптер по durable подтверждению command ID.
Если исход не установлен, `StorageUnavailableError` выходит из handler без
успеха и без трактовки timeout как конфликта. Подтверждённые результаты,
репозитории и DTO не содержат деталей Cassandra или транспортных библиотек.

## Порты и следующие адаптеры

- `ports/identity`: факт завершённой регистрации;
- `ports/persistence/repositories`: каноническое создание и условное принятие
  групповых команд;
- `ports/projections`: необходимые карточки и списки пользователя;
- `ports/objects`: готовность объектов и право автора прикрепить их.

Групповая отправка проверяет непустой текст/вложения в домене и запрашивает
внешнюю проверку вложений до записи. Повтор ключа с другим содержимым даёт
`MessageSendConflictError`. Поиск принятой отправки здесь ограничен группой;
глобальную reservation sender/clientMessageId между диалогами нужно соединить
с будущим полным message-send pipeline.

Реальные Identity/Object Storage клиенты, Cassandra, схемы БД, HTTP/Kafka
адаптеры и публикация sync/events остаются следующим этапом. Для будущего
Cassandra adapter выбран [протокол одной условной записи](../../../docs/adr/0001-conditional-group-command-writes.md).
Он должен атомарно оставлять и материал для восстановления обязательных
последующих эффектов; успешный вызов Python handler сам по себе этого не доказывает.

## Проверки

Application unit tests находятся в `tests/unit/application`. Они проверяют
public command/handler, реальные доменные модели и fakes внешних портов.
Конкурентные сценарии используют явные барьеры и события вместо задержек:
исключение против сообщения/ACK, no-op ACK против исключения, два кандидата
на последнее место, две отправки и конкурирующие границы прочтения.

Эти проверки подтверждают координацию handlers при соблюдении контрактов портов.
Распределённую уникальность, LWT и восстановление после отказа настоящей БД
нужно отдельно доказать интеграционными тестами будущих адаптеров.
