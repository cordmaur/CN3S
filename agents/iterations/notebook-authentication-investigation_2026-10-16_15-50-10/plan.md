# Notebook authentication investigation

## Scope and plan
Investigate the Microsoft device sign-in requested by notebook cell 18. Trace the
local call chain, inspect installed Azure Identity behavior, and compare supported
authentication methods using Microsoft documentation. Do not modify code or notebooks,
attempt a database login, or provision credentials.

## Session record
- Identified cell 18 of `nbs/Workflow/05-Inference_Organized.ipynb`:
  `observed_discharge = inference.load_discharge()`.
- `src/hydro/inference.py:302` creates a new `SqlConnector` for each call and
  closes it in a finally block after loading daily observations.
- `src/utils/sql_connector.py:86` creates `DeviceCodeCredential()` without persistent
  caching or an authentication record. Construction immediately executes SELECT 1.
- The target is Synapse serverless SQL, database `syndb_hidro`, with the token scope
  `https://database.windows.net/.default`. This is a SQL connection, not an API-key API.
- Installed azure-identity is 1.23.1; msal is 1.32.3; msal-extensions is 1.3.1.
  Inspected installed interactive credential source: silent account lookup requires
  an authentication record. Persistent token caching alone is insufficient for a
  newly constructed DeviceCodeCredential to select the previously authenticated user.
- The constructor docstring mentions an injectable credential, but its actual signature
  does not accept one. Environment variables alone cannot override the hardcoded credential.

## Findings and proposal
1. No direct API-key replacement is available for this SQL endpoint. Synapse supports
   Microsoft Entra authentication and SQL username/password authentication.
2. For repeated interactive notebook runs, propose persistent DeviceCodeCredential token
   caching plus a saved/restored AuthenticationRecord, with first-run sign-in and later
   silent refresh. Conditional Access, revocation, or session policies can still require
   reauthentication. In this Linux dev container, verify encrypted cache support and keep
   the cache outside Git and on persistent storage if container rebuilds must preserve it.
   Reusing the existing credential would help same-kernel runs only.
3. For fully unattended runs, propose a service principal and ClientSecretCredential
   using tenant ID, application client ID, and client secret provided outside the notebook.
   An administrator must provision the identity and grant database read permissions;
   external storage access must also be verified because Synapse can use identity pass-through.
   Secrets expire and need rotation. The current token packing and SQL connection mechanism
   can remain; the credential creation would change in a future authorized implementation.
4. Managed identity is an alternative on a supported Azure host, not automatically provided
   by this local development container. SQL username/password is technically supported by
   Synapse, but availability here depends on administrator configuration and storage access.

No code or notebooks changed. No authentication attempts or live alternative-credential
verification performed. Tenant policy, app-registration permission, and database/storage
permissions remain unverified. This record is the only new file for this investigation.

## Sources
- https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/sql-authentication
- https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.devicecodecredential?view=azure-python
- https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.tokencachepersistenceoptions?view=azure-python
- https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.clientsecretcredential?view=azure-python
- https://learn.microsoft.com/en-us/azure/synapse-analytics/sql/develop-storage-files-storage-access-control

## Proposed method-call examples
Illustrative only; not implemented or executed. The first example assumes a restored
AuthenticationRecord and platform-supported secure persistent cache. The second assumes
an administrator-provisioned identity and externally supplied credentials.

```python
credential = DeviceCodeCredential(
    authentication_record=authentication_record,
    cache_persistence_options=TokenCachePersistenceOptions(name="cn3s"),
)

credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)
credential.get_token("https://database.windows.net/.default")
```
