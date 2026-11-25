# Persistent in-memory series query caching

## Plan

Investigate cache lifetimes and query arguments, then propose the smallest change supporting repeated Station creation without expiration. The proposal was approved and implemented in this same iteration.

## Findings

- Hidro.get_series and Telemetria.get_series currently use functools.cache. Their keys contain provider identity (self), so newly created providers miss. They also retain provider instances and return the same mutable DataFrame.
- SqlConnector.read_sql_with_retries no longer has the failing decorator. A direct decorator cannot accept its dictionary/list arguments.
- Stations borrow a caller-owned connector, allowing notebook stations to share one connector cache.
- Series SQL parameters include integers and Python datetime values. Source tables and measurement columns are present in the SQL itself.
- UserSqlConnector already caches SQL results in an application-owned cache and copies DataFrames. web.app configures SimpleCache with default_timeout=0 and threshold=512. It survives request connector creation but may prune at its size threshold.
- Web cache keys include the exact access token and database; token renewal creates a different scope. Date windows also affect keys. The deployed configuration uses one worker.

## Implementation plan

1. Remove the provider get_series decorators and unused imports.
2. Add a plain per-connector dictionary for notebook SQL reads, without TTL or automatic size eviction. Do not add a global cache or new dependency.
3. Form an immutable key from SQL, sorted parameter items, parse_dates converted to a tuple, and sorted dtype items. Current parameters are scalar/hashable, including datetime. Preserve parameter types; do not stringify all values indiscriminately. Retry controls do not affect result identity.
4. Look up before connecting. Store only successful results, including empty frames. Store an independent DataFrame copy and return independent frames on hits, preventing downstream edits from corrupting the cache.
5. Add clear_query_cache() for explicit notebook refresh. Cache lifetime is the connector lifetime; preserve it through engine reconnection, clear on full close. Reuse the same connector across Station objects.
6. Keep the web application cache as its single cache layer: explicitly disable base connector caching for UserSqlConnector. Its initializer bypasses the base initializer, so implementation must handle that deliberately. Existing web refresh bypass must continue to force SQL and replace the cached entry.
7. If permanent retention is also required on the website, adjust its size-eviction policy separately. Current token scope intentionally prevents cross-credential reuse; sharing across token renewal requires a deliberately chosen authenticated user scope and is not necessary for the notebook fix.

## Semantics and limits

- Exact SQL, parameters, and output conversion options must match. Different date windows are distinct entries; no superset-window lookup is proposed.
- This caches raw query results, so daily aggregation and consistency filtering still run.
- No TTL means results remain the first fetched snapshot until explicit clearing or process/connector termination, even after the daily database update.
- In-memory caches do not survive kernel/process restarts and are not shared between worker processes.
- With no automatic size eviction, memory grows with distinct query results, especially raw telemetry.

## Implementation and verification record

- Implemented the per-connector dictionary directly in read_sql_with_retries; the short key construction stays inline rather than adding a helper used once. Parameter types are included in the key.
- Added clear_query_cache(), clearing on full connector close, and explicitly disabled the base cache for UserSqlConnector to preserve its application cache and refresh semantics.
- Removed get_series cache decorators from both providers; this restores those files to their committed form.
- Inspected data.py: its provider close method already respects borrowed-connector ownership. The invalid self.close() call was in Station.__init__; removed the exception handler so the original error propagates.
- Temporary checks passed for recreated Station instances sharing all historical, telemetry, and inventory queries, date parameters, insertion-order independence, changed parameter/output-option keys, independent DataFrame copies, empty results, independent connector clearing, retries, uncached failures, original Station exception propagation, borrowed connector ownership, web cache reuse/refresh, and cache clearing on close.
- Checks used local SQLite plus simulated SQL responses. No live Azure query was performed and no test files were added.
- An initial verification call incorrectly passed the measurement as the source positional argument to Station.get_series; corrected it to the existing series_type keyword and reran successfully.
- Full ruff check and ruff format --check passed on all five Python files modified during this iteration.
- Changed Python files pass git diff --check. The repository-wide diff check reports pre-existing trailing whitespace on the modified pyproject.toml line 45, which this iteration did not edit.
- No new dependencies, classes, or cache framework were introduced.

## Method-call examples

```python
conn = SqlConnector()
first = Station(STATION_CODE, connector=conn)
first.load_series(source="hidro", series_type="vazao", start="2020-01-01", end="2025-12-31")

# New providers, same connector and query: reuse cached SQL results.
second = Station(STATION_CODE, connector=conn)
second.load_series(source="hidro", series_type="vazao", start="2020-01-01", end="2025-12-31")

# Explicitly fetch a new snapshot on subsequent reads.
conn.clear_query_cache()
second.load_series(source="hidro", series_type="vazao", start="2020-01-01", end="2025-12-31")
```
