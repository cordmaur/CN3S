# Microsoft user sign-in and station inventory test

## Plan

- Keep SqlConnector unchanged and add UserSqlConnector for a current visitor's
  delegated Azure SQL token; reuse existing SQL operations with no shared pool.
- Use Microsoft device-code login, a server-side per-visitor token cache,
  and a station-code form under /cn3s-test.
- Query only Station(code, connector=conn).name and close the connector afterward.
- Add the ODBC driver, runtime dependencies and IIS prefix-forwarding instructions.

## Session record

- User authorized a separate connector and clarified that each visitor should
  enter a device code on Microsoft's site, as in the notebooks.
- Existing SqlConnector uses device login plus a shared disk account cache; the
  new connector bypasses that initialization and never opens the notebook cache.
- Use Azure Identity's default development application for this prototype, as
  the notebook does. No callback URL, client secret or new registration is
  required for the device-code test, subject to tenant policy.
- The SDK waits for login in a background thread. The browser polls a status
  endpoint that never returns tokens. Per-visitor tokens expire without refresh;
  users sign in again when needed. Notebook caches are never accessed.
- Sessions stay in the container and reset when it is recreated. HTTP remains
  enabled for the existing internal test; production HTTPS remains separate.
- Live Microsoft login and database access require user verification.
- Temporary checks passed for two separate visitors, independent tokens, CSRF,
  login/status/logout, escaped station names using the real Station constructor
  with a simulated SQL reader, failed lookup responses, ODBC token packing,
  resource disposal and bypass of the notebook credential initializer.
- Python compilation, TOML and Compose parsing passed. Confirmed the original
  SqlConnector file is unchanged. No formal test suite was added.
- Docker is unavailable in this devcontainer, so the ODBC image build and real
  Azure authentication/SQL access remain unverified until the user rebuilds.

## Method-call examples

```python
conn = UserSqlConnector(access_token)
try:
    station = Station(14558000, connector=conn)
    print(station.name)
finally:
    conn.close()
```
