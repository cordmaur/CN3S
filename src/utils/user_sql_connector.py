"""Request-scoped SQL access using a website visitor's delegated token."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from .sql_connector import SqlConnector

if TYPE_CHECKING:
    import pandas as pd
    from cachelib import BaseCache
    from sqlalchemy.engine import Engine


class UserSqlConnector(SqlConnector):
    """Reuse SQL operations without the notebook's shared account or token cache."""

    def __init__(
        self, access_token: str, *, cache: BaseCache | None = None, use_cache: bool = True
    ) -> None:
        """
        Open a connector authenticated as one signed-in website user.

        Args:
            access_token: Microsoft Entra access token issued for Azure SQL.
                Obtain a current token before constructing this request-scoped connector.
            cache: Optional shared web query cache, bounded by entry count without time expiry.
            use_cache: Read cached results when available. False forces fresh SQL
                queries while still updating the cache for subsequent requests.

        """
        # Do not call the notebook initializer: it creates a shared device-login cache.
        self._access_token = access_token
        self.cache = cache
        self.use_cache = use_cache
        # Scope cached data to the exact credential and database, never across users.
        self.cache_scope = hashlib.sha256(
            (access_token + self.CONNECTION_STRING).encode(),
        ).hexdigest()
        self.odbc_connection_string = self.CONNECTION_STRING
        # Connections are never pooled across requests or users.
        self.engine = self._create_sqlalchemy_engine()
        # SQL authenticates on a cache miss; avoid an extra round trip on every chart.

    def _create_sqlalchemy_engine(self) -> Engine:
        """
        Build an engine that never pools connections across user requests.

        Returns:
            SQLAlchemy engine using this user's ODBC token.

        """
        return create_engine(
            "mssql+pyodbc://",
            creator=self._creator_pyodbc,
            poolclass=NullPool,
        )

    def _get_azure_token_struct(self) -> bytes:
        """
        Pack this user's SQL token for the ODBC access-token attribute.

        Returns:
            Token encoded as a byte count followed by UTF-16-LE bytes.

        """
        token_bytes = self._access_token.encode("UTF-16-LE")
        return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

    def read_sql_with_retries(self, query: str, **kwargs: Any) -> pd.DataFrame:
        """
        Read SQL with credential-scoped caching and one attempt by default.

        Args:
            query: SQL statement, using bound parameters for user input.
            **kwargs: Options accepted by SqlConnector.read_sql_with_retries.

        Returns:
            Independent DataFrame; caller edits never change the cached result.

        """
        # A failed query should reach the browser promptly rather than retry for minutes.
        kwargs.setdefault("max_attempts", 1)
        options = json.dumps(kwargs, sort_keys=True, default=str)
        key = (
            "sql:"
            + hashlib.sha256(
                (self.cache_scope + query + options).encode(),
            ).hexdigest()
        )
        if self.cache is not None and self.use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return cached.copy(deep=True)
        result = super().read_sql_with_retries(query, **kwargs)
        # Only successful results are stored; failed queries remain visible to users.
        if self.cache is not None:
            self.cache.set(key, result.copy(deep=True))
        return result

    def close(self) -> None:
        """Dispose SQL resources without modifying any notebook login cache."""
        self.dispose_engine()
