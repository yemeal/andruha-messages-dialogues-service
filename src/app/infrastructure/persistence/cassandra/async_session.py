"""Bridge the driver's callback API to asyncio without blocking request threads."""

import asyncio
from collections.abc import Sequence

from cassandra import DriverException
from cassandra.cluster import ResponseFuture, ResultSet, Session
from cassandra.pool import Host
from cassandra.query import Statement
from pydantic import AliasChoices, BaseModel, Field, ValidationError


class CassandraSessionClosedError(DriverException):
    """The connection owner has stopped accepting requests."""


class _ConditionalRow(BaseModel):
    applied: bool = Field(
        validation_alias=AliasChoices("[applied]", "applied"), strict=True
    )


async def await_response(response: ResponseFuture) -> Sequence[object]:
    loop = asyncio.get_running_loop()
    pending: asyncio.Future[Sequence[object]] = loop.create_future()

    def deliver(rows: Sequence[object] | None, error: Exception | None) -> None:
        if pending.done():
            return
        if error is not None:
            pending.set_exception(error)
        else:
            pending.set_result(rows if rows is not None else ())

    def schedule(rows: Sequence[object] | None, error: Exception | None) -> None:
        try:
            loop.call_soon_threadsafe(deliver, rows, error)
        except RuntimeError:
            if not loop.is_closed():
                raise

    response.add_callbacks(
        callback=lambda rows: schedule(rows, None),
        errback=lambda error: schedule(None, error),
    )
    return await pending


class QueryPage:
    """A single page; iteration never triggers synchronous network pagination."""

    def __init__(self, result: ResultSet) -> None:
        self.current_rows: tuple[object, ...] = tuple(result.current_rows)
        self.paging_state: bytes | None = result.paging_state
        self._result = result

    def one(self) -> object | None:
        return self.current_rows[0] if self.current_rows else None

    @property
    def was_applied(self) -> bool:
        # A failed conditional batch may return one row for each failed condition.
        # ResultSet.was_applied rejects that valid response with RuntimeError.
        try:
            outcomes = {
                _ConditionalRow.model_validate(row, from_attributes=True).applied
                for row in self.current_rows
            }
        except ValidationError as error:
            raise DriverException("Conditional outcome is not readable") from error
        if len(outcomes) != 1:
            raise DriverException("Conditional outcome is not confirmed")
        return outcomes.pop()


class AsyncCassandraSession:
    def __init__(self, session: Session, *, max_in_flight: int = 128) -> None:
        if max_in_flight < 1:
            raise ValueError("Cassandra in-flight limit must be positive")
        self._native = session
        self._limit = asyncio.Semaphore(max_in_flight)
        self._requests: set[asyncio.Task[Sequence[object]]] = set()
        self._closing = False

    @property
    def keyspace(self) -> str | None:
        return self._native.keyspace

    @property
    def live_hosts(self) -> tuple[Host, ...]:
        cluster = self._native.cluster
        if cluster is None:
            raise RuntimeError("Cassandra session has no cluster")
        return tuple(host for host in cluster.metadata.all_hosts() if host.is_up)

    async def aclose(self) -> None:
        """Stop admission and drain native requests before the connection owner closes."""
        self._closing = True
        if self._requests:
            await asyncio.shield(
                asyncio.gather(*tuple(self._requests), return_exceptions=True)
            )

    def _finished(self, task: asyncio.Task[Sequence[object]]) -> None:
        self._limit.release()
        self._requests.discard(task)
        if not task.cancelled():
            # A cancelled caller may leave the native request running. Consume
            # its eventual exception while retaining the permit until completion.
            task.exception()

    async def execute(
        self,
        query: str | Statement,
        parameters: Sequence[object] | None = None,
        *,
        timeout: float = 5,
        paging_state: bytes | None = None,
        host: Host | None = None,
    ) -> QueryPage:
        if timeout <= 0:
            raise ValueError("Cassandra request timeout must be positive")
        if self._closing:
            raise CassandraSessionClosedError("Cassandra session is closing")
        started = asyncio.get_running_loop().time()
        async with asyncio.timeout(timeout):
            await self._limit.acquire()
        try:
            if self._closing:
                raise CassandraSessionClosedError("Cassandra session is closing")
            remaining = timeout - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                raise TimeoutError("Cassandra admission timed out")
            response = self._native.execute_async(
                query,
                parameters,
                timeout=remaining,
                paging_state=paging_state,
                host=host,
            )
            pending = asyncio.create_task(await_response(response))
        except BaseException:
            self._limit.release()
            raise
        self._requests.add(pending)
        pending.add_done_callback(self._finished)
        rows = await asyncio.shield(pending)
        return QueryPage(ResultSet(response, rows))

    async def fetch_all(
        self,
        query: str | Statement,
        parameters: Sequence[object] | None = None,
        *,
        max_rows: int,
        timeout: float = 5,
    ) -> tuple[object, ...]:
        """Read explicitly paged, bounded metadata; never invoke ResultSet iteration."""
        if max_rows < 1:
            raise ValueError("Cassandra row limit must be positive")
        rows: list[object] = []
        cursor = None
        seen: set[bytes] = set()
        async with asyncio.timeout(timeout):
            while True:
                page = await self.execute(
                    query, parameters, timeout=timeout, paging_state=cursor
                )
                rows.extend(page.current_rows)
                if len(rows) > max_rows:
                    raise ValueError("Cassandra metadata row limit exceeded")
                cursor = page.paging_state
                if cursor is None:
                    return tuple(rows)
                if cursor in seen:
                    raise ValueError("Cassandra paging state did not advance")
                seen.add(cursor)
