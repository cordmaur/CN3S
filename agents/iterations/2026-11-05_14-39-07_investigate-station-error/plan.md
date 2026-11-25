# Investigate station initialization error

## Plan

- Trace the saved notebook traceback through station initialization and SQL access.
- Identify the original failure and the subsequent cleanup error, preserving existing work.
- Report a minimal correction and any verification limits.

## Session record

- The notebook records `TypeError: unhashable type: 'dict'` at the SQL reader call.
- `functools.cache` on `SqlConnector.read_sql_with_retries` attempts to hash the `params` dictionary before the method runs. The decorator is an existing uncommitted change.
- The exception handler invokes `Station.close()`, which does not exist, masking the original error. The station borrows its connector, so it should not close it on construction failure.
- Recommended correction: remove the cache decorator and its import, and replace the constructor's try/except with the direct inventory call. This investigation leaves application code unchanged.
- No live database query was performed.

## Method-call example

```python
conn = SqlConnector()
station = Station(STATION_CODE, connector=conn)
```
