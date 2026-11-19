from cassandra import ConsistencyLevel, DriverException, RequestExecutionException
from cassandra.cluster import NoHostAvailable
from cassandra.query import SimpleStatement

DRIVER_ERRORS = (
    DriverException,
    RequestExecutionException,
    NoHostAvailable,
    OSError,
    TimeoutError,
)


def serial_read(query: str) -> SimpleStatement:
    return SimpleStatement(query, consistency_level=ConsistencyLevel.SERIAL)


def conditional_write(query: str) -> SimpleStatement:
    return SimpleStatement(
        query,
        consistency_level=ConsistencyLevel.QUORUM,
        serial_consistency_level=ConsistencyLevel.SERIAL,
    )
