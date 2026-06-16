# include necessary imports
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

import pandas as pd
from dateutil.relativedelta import relativedelta

from utils.sql_connector import SqlConnector

if TYPE_CHECKING:
    from datetime import datetime


def months_between_dates(start_datetime: datetime, end_datetime: datetime) -> int:
    """
    Calculate the total number of months between two datetimes.

    Args:
        start_datetime (datetime): start datetime
        end_datetime (datetime): end datetime

    Returns:
        int: total number of months between the two datetimes

    """
    delta = relativedelta(end_datetime, start_datetime)
    months = delta.years * 12 + delta.months

    if delta.days > 0:
        months += 1

    return months


class Hydrology:
    """Hydrology class is used to get discharge data from the Hydrology database."""

    rename_columns = {  # noqa: RUF012
        "vazao_val": "Vazao",
        "vazao_data": "Data",
        "cota_val": "Cota",
        "cota_data": "Data",
    }

    ###### INIT Methods ######
    def __init__(self) -> None:
        """Docstring."""
        self.conn = SqlConnector()

    def close(self) -> None:
        """Close the connection to the database."""
        self.conn.dispose_engine()

    def __del__(self) -> None:
        """Ensure the connection is closed."""
        self.close()

    ###### MAIN PUBLIC METHODS ######
    def get_discharge(
        self,
        station: int,
        _type: Literal["vazao", "cota"] = "vazao",
    ) -> pd.DataFrame:
        """
        Get discharge for a given station.

        Args:
            station (int): station number

        Returns:
            pd.DataFrame: dataframe with discharge

        """
        tablename = "hidro.pivotvazoes" if _type == "vazao" else "hidro.pivotcotas"
        # Query database to retrieve discharge records
        query = f"""SELECT EstacaoCodigo, NivelConsistencia, {_type}_val, {_type}_data
                    FROM {tablename}
                    WHERE EstacaoCodigo = {station}"""

        data = self.conn.read_sql_with_retries(
            query,
            parse_dates=[f"{_type}_data"],
            dtype={
                "EstacaoCodigo": "int32",
                "NivelConsistencia": "uint8",
                f"{_type}_val": "float64",
            },
            failure_message=(
                f"Failed to retrieve {_type} data for station {station} after 5 attempts"
            ),
        )

        # Rename columns for clarity
        data = data.rename(columns=Hydrology.rename_columns)

        # Sort by date and consistency level, keeping the most consistent record for each date
        data = data.sort_values(["Data", "NivelConsistencia"]).groupby("Data").last()

        # Round discharge values
        data[_type.capitalize()] = data[_type.capitalize()].round(2)

        # Drop NA rows
        return data

    @lru_cache(maxsize=512, typed=False)  # noqa: B019
    def get_station_stats(self, station: int) -> dict[str, str | float] | None:
        """
        Get statistics for a given station.

        Args:
            station (int): station number

        Returns:
            dict: station statistics

        """
        # Get discharge data
        q = self.get_discharge(station)

        if len(q) == 0:
            return None

        # Make sure we have a datetime index
        if not isinstance(q.index, pd.DatetimeIndex):
            msg = "Expected a DatetimeIndex to extract year attributes."
            raise TypeError(msg)

        # count values by month
        q_count = q.groupby([q.index.year, q.index.month]).size()
        q_count = q_count[q_count >= 28]  # noqa: PLR2004

        total_months = months_between_dates(
            pd.to_datetime(q.index.min()),
            pd.to_datetime(q.index.max()),
        )

        return {
            "complete_months": len(q_count),
            "years": int(len(q_count) / 12),
            "start_year": q.index.min().strftime("%Y/%m"),
            "end_year": q.index.max().strftime("%Y/%m"),
            "total_months": total_months,
            "missing_perc": f"{(100 * (total_months - len(q_count)) / total_months):.2f}%",
        }
