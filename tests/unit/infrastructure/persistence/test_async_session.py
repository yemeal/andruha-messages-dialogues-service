import asyncio
from threading import Thread

import pytest
from cassandra import OperationTimedOut

from app.infrastructure.persistence.cassandra.async_session import (
    AsyncCassandraSession,
    CassandraSessionClosedError,
    await_response,
)


class ManualResponse:
    def __init__(self):
        self.attached = asyncio.Event()
        self.callback = None
        self.errback = None

    def add_callbacks(self, callback, errback):
        self.callback = callback
        self.errback = errback
        self.attached.set()


@pytest.mark.asyncio
async def test_driver_io_thread_completes_await_without_blocking_or_executor():
    response = ManualResponse()
    pending = asyncio.create_task(await_response(response))
    await response.attached.wait()
    rows = [{"value": 42}]
    driver_thread = Thread(target=lambda: response.callback(rows))
    driver_thread.start()
    assert await pending == rows
    driver_thread.join(timeout=1)
    assert not driver_thread.is_alive()


@pytest.mark.asyncio
async def test_driver_timeout_is_preserved_as_unknown_write_outcome():
    response = ManualResponse()
    pending = asyncio.create_task(await_response(response))
    await response.attached.wait()
    failure = OperationTimedOut()
    driver_thread = Thread(target=lambda: response.errback(failure))
    driver_thread.start()
    with pytest.raises(OperationTimedOut) as raised:
        await pending
    driver_thread.join(timeout=1)
    assert raised.value is failure
    assert not driver_thread.is_alive()


@pytest.mark.asyncio
async def test_late_driver_callback_after_cancellation_does_not_corrupt_loop():
    response = ManualResponse()
    pending = asyncio.create_task(await_response(response))
    await response.attached.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    loop = asyncio.get_running_loop()
    errors = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _, context: errors.append(context))
    try:
        driver_thread = Thread(target=lambda: response.callback([{"late": True}]))
        driver_thread.start()
        driver_thread.join(timeout=1)
        assert not driver_thread.is_alive()
        barrier = asyncio.Event()
        loop.call_soon(barrier.set)
        await barrier.wait()
        assert errors == []
    finally:
        loop.set_exception_handler(previous)


class ManualSession:
    def __init__(self):
        self.requests = asyncio.Queue()

    def execute_async(self, query, parameters=None, **kwargs):
        response = ManualResponse()
        self.requests.put_nowait(response)
        return response


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_inflight_slot_until_native_response_arrives():
    native = ManualSession()
    session = AsyncCassandraSession(native, max_in_flight=1)
    first = asyncio.create_task(session.execute("first conditional write"))
    first_response = await native.requests.get()
    await first_response.attached.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    second = asyncio.create_task(session.execute("second conditional write"))
    barrier = asyncio.Event()
    asyncio.get_running_loop().call_soon(barrier.set)
    await barrier.wait()
    assert native.requests.empty()
    first_response.callback([])
    second_response = await native.requests.get()
    await second_response.attached.wait()
    failure = OperationTimedOut()
    second_response.errback(failure)
    with pytest.raises(OperationTimedOut) as raised:
        await second
    assert raised.value is failure


@pytest.mark.asyncio
async def test_closing_rejects_new_queries_and_drains_cancelled_callers_native_work():
    native = ManualSession()
    session = AsyncCassandraSession(native)
    request = asyncio.create_task(session.execute("conditional write"))
    response = await native.requests.get()
    await response.attached.wait()
    closing = asyncio.create_task(session.aclose())
    barrier = asyncio.Event()
    asyncio.get_running_loop().call_soon(barrier.set)
    await barrier.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not closing.done()
    with pytest.raises(CassandraSessionClosedError):
        await session.execute("must not start")
    assert native.requests.empty()
    response.errback(OperationTimedOut())
    await closing
    assert native.requests.empty()


@pytest.mark.asyncio
async def test_inflight_admission_has_a_deadline(monkeypatch):
    native = ManualSession()
    session = AsyncCassandraSession(native, max_in_flight=1)
    first = asyncio.create_task(session.execute("first"))
    response = await native.requests.get()
    await response.attached.wait()
    loop = asyncio.get_running_loop()
    now = loop.time()
    monkeypatch.setattr(loop, "time", lambda: now)
    second = asyncio.create_task(session.execute("second", timeout=0.1))
    barrier = asyncio.Event()
    loop.call_soon(barrier.set)
    await barrier.wait()
    now += 1
    with pytest.raises(TimeoutError):
        await second
    assert native.requests.empty()
    response.errback(OperationTimedOut())
    with pytest.raises(OperationTimedOut):
        await first
