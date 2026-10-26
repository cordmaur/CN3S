# Shared SQL login at notebook startup

## Plan
- Add shared project-local disk caching and account-record restoration to SqlConnector.
- Add an explicit check_login class method that verifies database access and closes its
  temporary connection; imports remain free of authentication side effects.
- Check login in the early setup of Workflow notebooks 01, 02, 04, and 05. For notebook
  02, check immediately after configuration only when PREPARE_INPUTS is true, preserving
  the documented offline calibration workflow. Notebook 03 does not use SqlConnector.
- Preserve existing notebook outputs and unrelated local changes. Ignore .azure-auth/.
- Use temporary offline checks for cache reuse, reauthentication, cleanup, and notebook
  placement. Run relevant lint/type/syntax checks without initiating a real device login.

## Decisions
Use the existing Azure Identity public API with TokenCachePersistenceOptions and an
AuthenticationRecord. The cache prefix is an absolute path in the project .azure-auth
folder, independent of notebook working directory. Encryption is attempted by the SDK;
allow its documented unencrypted fallback for the headless container. Restrict the folder
to the current OS user and exclude it from Git. Never store the user's password. Missing
or expired authentication prompts through the existing device flow; network and SQL
errors propagate rather than being treated as a reason to discard credentials.

## Session record
Implemented in src/utils/sql_connector.py, .gitignore, and Workflow notebooks 01, 02,
04, and 05. Startup checks execute SELECT 1 and close the temporary connector. Other
connectors restore the same account record and token cache. AuthenticationRequiredError
triggers device authentication and saves its returned account record; other failures
propagate. Failed startup queries also close the connector. No dependencies added.

Verification completed:
- Ruff lint and format checks passed for sql_connector.py.
- Changed notebook cells compiled successfully after IPython magic transformation.
- Compared every Workflow notebook with its captured pre-edit state: only the intended
  setup/configuration source arrays changed; all outputs, metadata, and other cells
  were preserved. Notebook 03 is unchanged.
- Executed notebook 02's configuration with PREPARE_INPUTS=False and confirmed the
  login check is skipped.
- Used the installed Azure/MSAL disk-cache backend with synthetic account/token data.
  A separate Python process restored the login and packed the cached SQL token without
  invoking device authentication or making a token request. Only authority metadata was
  supplied by an offline stub; no real credentials or network requests were used.
- Temporary checks verified reauthentication saves the account record with mode 0600,
  the cache folder has mode 0700, unrelated authentication errors propagate, and startup
  checks release the engine and credential on both success and query failure.
- git check-ignore confirmed account and token-cache paths are excluded.
- Mypy reported one pre-existing pandas read_sql dtype mismatch. Running it against
  the original connector via --shadow-file reproduced the same error (original line
  296; updated line 352). It also reports the existing unsupported configuration option
  strict_equality_for_none. These unrelated issues were left unchanged.

No real login or live database query was attempted. The first real notebook run still
requires the user to sign in and verifies actual tenant/database access. Disk caching
survives kernel restarts; container rebuild survival depends on retaining the project
folder and, when encryption is used, the platform keyring. Headless Linux file fallback
is unencrypted, restricted to the OS user, and excluded from Git.

References:
- https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.devicecodecredential?view=azure-python
- https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.tokencachepersistenceoptions?view=azure-python

## Follow-up inspection
The user reported the check was absent in notebook 05. Inspection confirmed its saved
first code cell no longer contained the added import or call. Restored both in place,
then re-read the notebook and verified that only that cell's source changed. Compiled
the modified cell after IPython transformation. The connector method and startup calls
in Workflow notebooks 01, 02, and 04 were still present. No live login attempted.

## Proposed method-call examples
```python
from utils.sql_connector import SqlConnector

SqlConnector.check_login()

# Later calls reuse the persisted account and tokens.
conn = SqlConnector()
```

For optional SQL preparation in notebook 02:
```python
if PREPARE_INPUTS:
    SqlConnector.check_login()
```
