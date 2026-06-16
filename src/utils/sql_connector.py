"""SqlAlchemy connector."""

from __future__ import annotations

import logging
import struct
import time
from typing import TYPE_CHECKING, Any

import pandas as pd
import pyodbc
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DeviceCodeCredential
from sqlalchemy import create_engine, inspect, text

if TYPE_CHECKING:
    from sqlalchemy.engine.base import Engine

logger = logging.getLogger(__name__)

type Param = dict[str, str]


class SqlConnector:
    """
    A SQLAlchemy connector for Azure SQL-like databases.

    e.g., Azure Synapse On-Demand)
    using Azure Active Directory token-based authentication with pyodbc.

    It handles token acquisition and refresh through a provided Azure Identity credential
    object and manages SQLAlchemy engine and connection pooling.
    """

    SERVER = "synanaprod001-ondemand.sql.azuresynapse.net"
    SQL_COPT_SS_ACCESS_TOKEN = 1256
    DEFAULT_POOL_RECYCLE_SECONDS = 1800  # 30 minutes
    DEFAULT_POOL_SIZE = 5
    DEFAULT_MAX_OVERFLOW = 10
    DEFAULT_POOL_TIMEOUT_SECONDS = 60
    # Azure SQL/Synapse token scope
    TOKEN_SCOPE = "https://database.windows.net/.default"  # noqa: S105

    CONNECTION_STRING = """Driver={ODBC Driver 18 for SQL Server};
    Server=synanaprod001-ondemand.sql.azuresynapse.net;
    Database=syndb_hidro;Encrypt=yes;TrustServerCertificate=no;
    Connection Timeout=30;ConnectRetryCount=10;ConnectRetryInterval=10;
    Pooling=no;MARS_Connection=no;"""

    def __init__(
        self,
        pool_recycle: int = DEFAULT_POOL_RECYCLE_SECONDS,
        pool_size: int = DEFAULT_POOL_SIZE,
        max_overflow: int = DEFAULT_MAX_OVERFLOW,
        pool_timeout: int = DEFAULT_POOL_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initialize the SqlConnector.

        Args:
            odbc_connection_string (str): The DSN-less ODBC connection string.
                Example: "Driver={ODBC Driver 18 for SQL Server};
                Server=your-synapse-ondemand.sql.azuresynapse.net;Database=your_db;Encrypt=yes;TrustServerCertificate=no;"
                Ensure it does NOT contain UID/PWD or AccessToken parameters.
            credential (TokenCredential): An Azure Identity credential object
                (e.g., DeviceCodeCredential, ClientSecretCredential, ManagedIdentityCredential).
            pool_recycle (int): Number of seconds after which a connection is recycled.
                Should be less than the access token lifetime. Defaults to 1800 (30 mins).
            pool_size (int): Number of connections to keep open in the connection pool.
            Defaults to 5.
            max_overflow (int): Number of extra connections allowed beyond pool_size.
            Defaults to 10.
            pool_timeout (int): Seconds to wait before giving up on getting a connection from the
            pool. Defaults to 30.
            sqlalchemy_echo (bool): If True, SQLAlchemy engine will log all statements.
            Defaults to False.
            sqlalchemy_echo_pool (Union[bool, str]): If True or "debug", SQLAlchemy pool will log
            checkouts/checkins. Defaults to False.

        """
        self.odbc_connection_string = SqlConnector.CONNECTION_STRING
        self.credential = DeviceCodeCredential()
        self.pool_recycle = pool_recycle
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout

        logger.info("Initializing SqlConnector.")
        self.engine: Engine = self._create_sqlalchemy_engine()

        # Just ping the database to start the connection
        self.execute_query("SELECT 1")

    def _get_azure_token_struct(self) -> bytes:
        """
        Acquire an Azure AD access token using the provided credential.

        Additionally, packs it into the structure expected by pyodbc for SQL_COPT_SS_ACCESS_TOKEN.

        Returns:
            bytes: The packed token structure.

        Raises:
            ClientAuthenticationError: If token acquisition fails.
            Exception: For other errors during token acquisition or packing.

        """
        try:
            logger.debug("Attempting to get Azure AD token for scope: %s", self.TOKEN_SCOPE)
            token_object = self.credential.get_token(self.TOKEN_SCOPE)
            token_bytes = token_object.token.encode("UTF-16-LE")
            # The token structure for pyodbc:
            #   ULONG   cbAccessToken; // Length of AccessToken in bytes
            #   BYTE    rgbAccessToken[]; // AccessToken string
            token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        except ClientAuthenticationError:
            logger.exception("Azure AD token acquisition failed")
            raise  # Re-raise to signal failure to connect

        except Exception:
            logger.exception("An unexpected error occurred during token acquisition or packing")
            raise

        else:
            logger.debug("Successfully obtained and packed Azure AD token.")
            return token_struct

    def _creator_pyodbc(self) -> pyodbc.Connection:
        """
        Create a pyodbc connection.

        Creator function for SQLAlchemy engine. Establishes a pyodbc connection
        using Azure AD token authentication.
        """
        try:
            token_struct = self._get_azure_token_struct()
            # Ensure autocommit is False by default for DBAPI, SQLAlchemy manages transactions.
            # If autocommit is desired, it should be an explicit choice.
            conn = pyodbc.connect(
                self.odbc_connection_string,
                attrs_before={SqlConnector.SQL_COPT_SS_ACCESS_TOKEN: token_struct},
                autocommit=False,
            )

        except Exception:
            logger.exception("Failed to create pyodbc connection in creator function")
            raise  # Propagate error to SQLAlchemy to handle connection failure

        else:
            logger.debug("pyodbc connection established successfully.")
            return conn

    def _create_sqlalchemy_engine(self) -> Engine:
        """
        Create a SQLAlchemy engine.

        Configured for pyodbc and Azure AD token authentication.
        """
        logger.debug(
            "Creating SQLAlchemy engine with pool_recycle=%ds, pool_size=%d, max_overflow=%d",
            self.pool_recycle,
            self.pool_size,
            self.max_overflow,
        )

        try:
            engine = create_engine(
                "mssql+pyodbc://",  # Dialect and driver; connection details handled by creator
                creator=self._creator_pyodbc,
                pool_pre_ping=True,
                pool_recycle=self.pool_recycle,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                echo=False,
                echo_pool=False,
            )

        except Exception:
            logger.exception("Failed to create SQLAlchemy engine")
            raise

        else:
            logger.debug("SQLAlchemy engine created successfully.")
            return engine

    def execute_query(
        self,
        query: str,
        params: Param | list[Param] | None = None,
        *,
        is_dml: bool = False,
    ) -> list[tuple[Any, ...]] | int:
        """
        Execute a SQL query using a connection from the engine's pool.

        Args:
            query (str): The SQL query string to execute.
            Use sqlalchemy.text() for safety if constructing queries.

            params (Optional[Union[dict, List[dict]]]): Parameters for the query
            (for bind parameters).
            is_dml (bool): Set to True if the query is a Data Modification Language (DML)
            statement
            (e.g., INSERT, UPDATE, DELETE, CREATE) that requires a commit.
            Defaults to False (assuming a SELECT query).

        Returns:
            Union[List[Tuple[Any, ...]], int]:
                - For SELECT queries (or queries that return rows): A list of tuples representing
                the fetched rows.
                - For DML queries (when is_dml=True): The rowcount affected by the operation.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: For errors during query execution.
            pyodbc.Error: For underlying database errors.

        """
        if params:
            logger.debug("Query parameters: %s", params)

        with self.engine.connect() as connection:
            try:
                result_proxy = connection.execute(text(query), params or {})

                if is_dml:
                    connection.commit()
                    return int(result_proxy.rowcount)
                if result_proxy.returns_rows:
                    fetched_results = result_proxy.fetchall()
                    return [tuple(row) for row in fetched_results]

                # Should not happen if not DML and returns_rows is False, but handle gracefully.
                return int(result_proxy.rowcount)

            except (
                pyodbc.Error,
                Exception,
            ):  # Catch generic Exception as SQLAlchemy might wrap pyodbc errors
                logger.exception("Error executing query: %s...", query[:100])
                if is_dml and "connection" in locals() and connection.in_transaction():
                    try:
                        connection.rollback()
                        logger.warning("Transaction rolled back due to error.")
                    except Exception:
                        logger.exception("Error during rollback")
                        raise
                raise

    def read_sql_with_retries(
        self,
        query: str,
        *,
        parse_dates: list[str] | None = None,
        dtype: dict[str, str] | None = None,
        max_attempts: int = 5,
        retry_sleep_seconds: int = 10,
        stream_results: bool = True,
        failure_message: str | None = None,
    ) -> pd.DataFrame:
        """
        Read a SQL query into a pandas dataframe, retrying failed attempts.

        Args:
            query (str): SQL query to execute.
            parse_dates (list[str] | None): Columns to parse as dates.
            dtype (dict[str, str] | None): Column dtype mapping for pandas.
            max_attempts (int): Maximum number of read attempts.
            retry_sleep_seconds (int): Base sleep time between attempts.
            stream_results (bool): Whether to stream results from SQLAlchemy.
            failure_message (str | None): Message used if all attempts fail.

        Returns:
            pd.DataFrame: Dataframe returned by pandas.read_sql.

        """
        data = None
        last_exception = None

        for attempt in range(max_attempts):
            connection = self.engine.connect()
            if stream_results:
                connection = connection.execution_options(stream_results=True)

            try:
                data = pd.read_sql(
                    query,
                    connection,
                    parse_dates=parse_dates,
                    dtype=dtype,
                )
                break

            except Exception as e:
                last_exception = e
                print(
                    f"Failed to retrieve data (attempt {attempt + 1}/{max_attempts}): {e}",
                )

                if attempt == max_attempts - 1:
                    break

                connection.invalidate()
                time.sleep(retry_sleep_seconds * (attempt + 1))

            finally:
                connection.close()

        if data is None:
            msg = failure_message or f"Failed to retrieve data after {max_attempts} attempts"
            raise ConnectionError(msg) from last_exception

        return data

    def list_tables(self, schema: str | None = None) -> list[str]:
        """
        List all tables in the connected database.

        Args:
            schema: Optional schema name to filter tables. If None, returns tables from
                all schemas or the default schema depending on the database.

        Returns:
            List of table names in the database.

        Raises:
            sqlalchemy.exc.SQLAlchemyError: For errors during table inspection.

        """
        try:
            inspector = inspect(self.engine)
            table_names = inspector.get_table_names(schema=schema)
            logger.debug("Found %d tables in the database", len(table_names))
            return table_names  # type: ignore[no-any-return]

        except Exception:
            logger.exception("Error listing tables")
            raise

    def dispose_engine(self) -> None:
        """
        Dispose of the underlying SQLAlchemy engine and its connection pool.

        Note: We keep the Azure Identity credential alive to avoid re-authentication.
        """
        if self.engine:
            logger.info("Disposing SQLAlchemy engine.")
            self.engine.dispose()
            self.engine = None  # pyright: ignore[reportAttributeAccessIssue]

        logger.info("SqlConnector engine disposed (credential kept alive).")

    def close(self) -> None:
        """
        Fully close the connector including credentials.

        Use this when you're completely done with the connector.
        Use dispose_engine() for temporary engine recreation.
        """
        self.dispose_engine()

        if hasattr(self.credential, "close") and callable(self.credential.close):
            try:
                logger.info("Closing Azure Identity credential.")
                self.credential.close()
            except Exception:
                logger.exception("Error closing Azure Identity credential")

        logger.info("SqlConnector fully closed.")

    def reconnect(self) -> None:
        """
        Recreate the database engine and connection.

        Useful when connection issues persist and a fresh engine is needed.
        Note: Keeps the existing credential to avoid re-authentication.

        """
        logger.info("Recreating database engine...")
        try:
            # Dispose of the current engine (but keep credential)
            self.dispose_engine()

            # Create a new engine (reusing existing credential)
            self.engine = self._create_sqlalchemy_engine()

            # Test the connection
            self.execute_query("SELECT 1")
            logger.info("Database engine recreated successfully")
        except Exception:
            logger.exception("Failed to recreate database engine")
            raise
