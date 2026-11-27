"""Read HidroInfoAna inventory and daily Datamart telemetry."""

from __future__ import annotations

import pandas as pd

from .data import (
    SeriesType,
    SqlProvider,
    SqlReader,
    date_predicate,
    empty_series,
    identifier,
    require_columns,
    validate_series_type,
)


class Telemetria(SqlProvider):
    """Station inventory and daily means of telemetric stage and discharge."""

    PRECEDENCE = (
        "RHN",
        "Setor Elétrico",
        "Setores Regulados",
        "Inpe/Sivam(desativadas)",
        "Poços",
        "CotaOnline",
        "Açudes Semiárido",
    )

    def __init__(
        self,
        connector: SqlReader | None = None,
        *,
        stations_table: str = "hidroInfoAna.Estacao",
        origins_table: str = "hidroInfoAna.origem",
        stages_table: str = "datamart.hidroinfoana_cotas_media_diaria",
        discharges_table: str = "datamart.hidroinfoana_vazoes_media_diaria",
    ) -> None:
        """
        Configure the inventory and daily mean tables.

        Args:
            connector: Shared SQL reader, if provided.
            stations_table: HidroInfoAna station inventory.
            origins_table: HidroInfoAna list of telemetry origins.
            stages_table: Datamart daily stage table with AVG_HORNIVELADOTADO in cm.
            discharges_table: Datamart daily discharge table with AVG_HORVAZAO in m³/s.

        """
        super().__init__(connector)
        self.stations_table = identifier(stations_table)
        self.origins_table = identifier(origins_table)
        self.stages_table = identifier(stages_table)
        self.discharges_table = identifier(discharges_table)

    def _stations(self, column: str, code: int) -> pd.DataFrame:
        """
        Look up the station inventory, including the telemetry origin.

        Args:
            column: Inventory field to match.
            code: Historical or telemetric station code for that field.

        Returns:
            Matching stations and their origins.

        """
        return self.read(
            f"SELECT s.*, o.OGMORGAO FROM {self.stations_table} AS s "
            f"LEFT JOIN {self.origins_table} AS o ON s.ESTORIGEM = o.OGMCODIGO "
            f"WHERE s.{identifier(column)} = :code",
            {"code": int(code)},
        )

    def get_telemetric_code(self, station: int) -> pd.DataFrame | None:
        """Return the telemetric stations and origins associated with a historical code."""
        frame = self._stations("ESTANEELFLU", station)
        require_columns(frame, ["ESTCODIGO", "OGMORGAO"], "Telemetric inventory")
        if frame.empty:
            return None
        frame = frame[["ESTCODIGO", "OGMORGAO"]].copy()
        frame["ESTCODIGO"] = pd.to_numeric(frame["ESTCODIGO"], errors="raise").astype("int64")
        return frame.drop_duplicates("ESTCODIGO").set_index("ESTCODIGO").sort_index()

    def get_station_info(self, telemetric_code: int) -> pd.DataFrame:
        """Return inventory and origin for a telemetric station."""
        return self._stations("ESTCODIGO", telemetric_code)

    def get_telemetric_name(self, telemetric_code: int) -> str:
        """Return the station name, or the established missing-name label."""
        frame = self.get_station_info(telemetric_code)
        require_columns(frame, ["ESTNOME"], "Telemetric inventory")
        return str(frame["ESTNOME"].iloc[0]) if len(frame) == 1 else "Não encontrado"

    def get_series(
        self,
        telemetric_code: int,
        series_type: SeriesType,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """
        Read the station's daily mean values directly from Datamart.

        Args:
            telemetric_code: Internal HidroInfoAna station code.
            series_type: Stage in cm or discharge in m³/s.
            start: Optional inclusive start date.
            end: Optional inclusive end date.

        Returns:
            Dated daily values with the origin and station code used for source precedence.

        """
        validate_series_type(series_type)
        table = self.stages_table if series_type == "cota" else self.discharges_table
        value_column = "AVG_HORNIVELADOTADO" if series_type == "cota" else "AVG_HORVAZAO"
        window, params = date_predicate("DATE", start, end)
        frame = self.read(
            f"SELECT [DATE], {value_column} FROM {table} WHERE HORESTACAO = :code{window}",
            {"code": int(telemetric_code), **params},
        )
        require_columns(frame, ["DATE", value_column], "Telemetric observations")
        if frame.empty:
            return empty_series()
        dates = pd.to_datetime(frame["DATE"], errors="coerce")
        values = pd.to_numeric(frame[value_column], errors="coerce")
        daily = pd.DataFrame({"Data": dates, "val": values}).dropna()
        if daily.empty:
            return empty_series()
        daily = daily.set_index("Data").sort_index()
        info = self.get_station_info(telemetric_code)
        require_columns(info, ["OGMORGAO"], "Telemetric origin")
        if info.empty:
            msg = f"Telemetric station {telemetric_code} is missing from inventory."
            raise ValueError(msg)
        daily["HORESTACAO"] = int(telemetric_code)
        # Preserve unknown origins as well as the known precedence list.
        origin = info["OGMORGAO"].iloc[0]
        categories = list(self.PRECEDENCE)
        if pd.notna(origin) and origin not in categories:
            categories.append(origin)
        daily["ORIGEM"] = pd.Categorical([origin] * len(daily), categories=categories, ordered=True)
        daily["Sistema"] = "Telemetria"
        return daily
