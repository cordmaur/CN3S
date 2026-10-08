"""SQL contracts and connection ownership for the Hydro providers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, TypeAlias

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping

Source: TypeAlias = Literal["hidro", "telemetria", "hidro/telemetria"]
SeriesType: TypeAlias = Literal["cota", "vazao"]
DataStatus: TypeAlias = Literal["raw", "validated", "combined"]


class SqlReader(Protocol):
    """Minimal injectable interface implemented by SqlConnector."""

    def read_sql_with_retries(self, query: str, **kwargs: Any) -> pd.DataFrame:
        """Read a query into a DataFrame."""
        ...

    def close(self) -> None:
        """Close the reader."""
        ...


def identifier(name: str) -> str:
    """Quote a schema-qualified identifier after validating its components."""
    parts = name.split(".")
    if not parts or any(re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", p) is None for p in parts):
        msg = f"Invalid SQL identifier: {name!r}"
        raise ValueError(msg)
    return ".".join(f"[{part}]" for part in parts)


def require_columns(frame: pd.DataFrame, columns: list[str], context: str) -> None:
    """Fail explicitly when a SQL result does not satisfy its data contract."""
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        msg = f"{context}: missing columns {missing}"
        raise ValueError(msg)


def empty_series() -> pd.DataFrame:
    """Return the common empty daily-series shape."""
    return pd.DataFrame(
        {"val": pd.Series(dtype="float64"), "Sistema": pd.Series(dtype="str")},
        index=pd.DatetimeIndex([], name="Data"),
    )


def validate_series_type(series_type: str) -> None:
    """Validate the selected measurement before issuing SQL."""
    if series_type not in ("cota", "vazao"):
        msg = "Series type must be either 'cota' or 'vazao'."
        raise ValueError(msg)


class SqlProvider:
    """Lazily create an owned connector or borrow a caller-supplied reader."""

    def __init__(self, connector: SqlReader | None = None) -> None:
        """Configure an injected reader or a lazily created SQL connector."""
        self._connector = connector
        self._owns_connector = connector is None
        self._closed = False
        self._tables: dict[str, str] = {}

    @property
    def connector(self) -> SqlReader:
        """Return the connector, authenticating only on first data access."""
        if self._closed:
            msg = "This Hydro provider is closed."
            raise RuntimeError(msg)
        if self._connector is None:
            from utils.sql_connector import SqlConnector  # noqa: PLC0415

            self._connector = SqlConnector()
        return self._connector

    def read(self, query: str, params: Mapping[str, Any]) -> pd.DataFrame:
        """Read through the shared retrying SQL interface."""
        return self.connector.read_sql_with_retries(query, params=params)

    def resolve_table(self, schema: str, name: str, override: str | None) -> str:
        """Resolve historical table names using SQL metadata, allowing explicit overrides."""
        if override is not None:
            return identifier(override)
        key = f"{schema}.{name}"
        if key not in self._tables:
            tables = self.read(
                "SELECT DISTINCT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = :schema",
                {"schema": schema},
            )
            require_columns(tables, ["TABLE_NAME"], "SQL metadata")
            candidates = {name.casefold(), f"tb_{name}".casefold()}
            matches = [str(t) for t in tables["TABLE_NAME"] if str(t).casefold() in candidates]
            if len(matches) != 1:
                msg = (
                    f"Cannot uniquely resolve {key}; candidates: {matches}. "
                    "Supply a table override."
                )
                raise ValueError(msg)
            self._tables[key] = identifier(f"{schema}.{matches[0]}")
        return self._tables[key]

    def close(self) -> None:
        """Close owned resources; borrowed connectors remain caller-owned."""
        if not self._closed and self._owns_connector and self._connector is not None:
            self._connector.close()
        self._closed = True

    def __enter__(self) -> Self:
        """Enter a provider context without connecting."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close owned resources on context exit."""
        self.close()


def date_predicate(
    column: str,
    start: str | None,
    end: str | None,
) -> tuple[str, dict[str, Any]]:
    """Build an inclusive calendar-day window using an exclusive next-day upper bound."""
    first = pd.Timestamp(start).normalize() if start is not None else None
    last = pd.Timestamp(end).normalize() if end is not None else None
    if (first is not None and pd.isna(first)) or (last is not None and pd.isna(last)):
        msg = "Date bounds must be valid dates."
        raise ValueError(msg)
    if first is not None and last is not None and first > last:
        msg = "Start date must not be after end date."
        raise ValueError(msg)
    clauses = ""
    params: dict[str, Any] = {}
    if first is not None:
        clauses += f" AND {identifier(column)} >= :start"
        params["start"] = first.to_pydatetime()
    if last is not None:
        clauses += f" AND {identifier(column)} < :end"
        params["end"] = (last + pd.Timedelta(days=1)).to_pydatetime()
    return clauses, params
