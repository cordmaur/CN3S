"""Historical daily series, station inventory, and rating curves over SQL."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import (
    DataStatus,
    SeriesType,
    Source,
    SqlProvider,
    SqlReader,
    date_predicate,
    empty_series,
    identifier,
    require_columns,
    validate_series_type,
)

__all__ = ["DataStatus", "Hidro", "SeriesType", "Source"]


class Hidro(SqlProvider):
    """Read the same historical pivot views used by utils.hydrology.Hydrology."""

    def __init__(
        self,
        connector: SqlReader | None = None,
        *,
        stations_table: str | None = None,
        curves_table: str | None = None,
        stages_table: str = "hidro.pivotcotas",
        discharges_table: str = "hidro.pivotvazoes",
    ) -> None:
        """Configure historical SQL tables and connection ownership."""
        super().__init__(connector)
        self.stations_table = stations_table
        self.curves_table = curves_table
        self.stages_table = identifier(stages_table)
        self.discharges_table = identifier(discharges_table)

    def get_station_info(self, station: int) -> pd.DataFrame:
        """Read historical station inventory without loading the full table."""
        table = self.resolve_table("hidro", "estacao", self.stations_table)
        frame = self.read(f"SELECT * FROM {table} WHERE Codigo = :code", {"code": int(station)})
        require_columns(frame, ["Codigo", "Nome"], "Historical inventory")
        if frame.empty:
            msg = f"Station {station} not found in Hidro"
            raise ValueError(msg)
        return frame

    def get_series(
        self,
        station: int,
        series_type: SeriesType,
        data_status: DataStatus = "combined",
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Read daily means, selecting raw, validated, or preferred consistency records."""
        validate_series_type(series_type)
        if data_status not in ("raw", "validated", "combined"):
            msg = "Data status must be either 'raw', 'validated', or 'combined'."
            raise ValueError(msg)
        table = self.stages_table if series_type == "cota" else self.discharges_table
        date_column, value_column = f"{series_type}_data", f"{series_type}_val"
        window, params = date_predicate(date_column, start, end)
        frame = self.read(
            f"SELECT EstacaoCodigo, NivelConsistencia, MediaDiaria, "
            f"{date_column}, {value_column} FROM {table} "
            f"WHERE EstacaoCodigo = :code{window}",
            {"code": int(station), **params},
        )
        require_columns(
            frame,
            [date_column, value_column, "NivelConsistencia", "MediaDiaria"],
            "Historical daily series",
        )
        frame = frame.copy()
        frame["NivelConsistencia"] = pd.to_numeric(frame["NivelConsistencia"], errors="coerce")
        frame = frame[pd.to_numeric(frame["MediaDiaria"], errors="coerce") == 1].copy()
        frame["Data"] = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize()
        frame["val"] = pd.to_numeric(frame[value_column], errors="coerce")
        frame = frame.dropna(subset=["Data", "val", "NivelConsistencia"])
        if data_status != "combined":
            level = 1 if data_status == "raw" else 2
            frame = frame[frame["NivelConsistencia"] == level]
        frame = frame.sort_values(["Data", "NivelConsistencia"], kind="stable")
        frame = frame.drop_duplicates("Data", keep="last").set_index("Data")
        if frame.empty:
            result = empty_series()
            result["NivelConsistencia"] = pd.Series(dtype="int64")
            return result
        frame["NivelConsistencia"] = frame["NivelConsistencia"].astype("int64")
        frame = frame.drop(columns=[value_column])
        for part in ("ano", "mes", "dia"):
            legacy_column = f"{series_type}_{part}"
            if legacy_column in frame:
                frame = frame.drop(columns=legacy_column)
        frame["ano"], frame["mes"], frame["dia"] = (
            frame.index.year,
            frame.index.month,
            frame.index.day,
        )
        frame["Sistema"] = "Hidro"
        return frame

    def get_rating_curves(self, station: int) -> pd.DataFrame:
        """Fetch only this station's rating curves when requested."""
        table = self.resolve_table("hidro", "curvadescarga", self.curves_table)
        frame = self.read(
            "SELECT EstacaoCodigo, NumeroCurva, TipoEquacao, CoefA, CoefH0, CoefN, "
            f"CotaMinima, CotaMaxima FROM {table} WHERE EstacaoCodigo = :code",
            {"code": int(station)},
        )
        require_columns(
            frame,
            ["NumeroCurva", "TipoEquacao", "CoefA", "CoefH0", "CoefN", "CotaMinima", "CotaMaxima"],
            "Rating curves",
        )
        return frame

    @staticmethod
    def flow_from_stage(
        h: float | pd.Series,
        a: float,
        h0: float,
        n: float,
    ) -> float | pd.Series:
        """Compute Q = A * (H - H0) ** n with H in metres and Q in m³/s."""
        return a * (h - h0) ** n

    @staticmethod
    def stage_from_flow(
        q: float | pd.Series,
        a: float,
        h0: float,
        n: float,
    ) -> float | pd.Series:
        """Invert a rating curve, returning stage in metres."""
        return h0 + (q / a) ** (1.0 / n)

    def compute_stage_from_flow(
        self,
        q: pd.Series,
        station: int,
        ignore_error: bool = False,  # noqa: FBT001, FBT002
    ) -> pd.Series:
        """
        Convert discharge to centimetres using the copied curve-range policy.

        The lowest and highest stage limits are extended by 20%, as in the
        original package. Overlapping curves are averaged. Unsupported equations
        and incomplete coverage raise errors unless incomplete coverage is allowed.
        """
        if q.empty:
            return pd.Series(index=q.index, dtype="float64", name=q.name)
        curves = self.get_rating_curves(station)
        if curves.empty:
            msg = f"No rating curves for station {station}"
            raise ValueError(msg)
        columns = ["TipoEquacao", "CoefA", "CoefH0", "CoefN", "CotaMinima", "CotaMaxima"]
        curves = curves.copy()
        curves[columns] = curves[columns].apply(pd.to_numeric, errors="raise")
        curves = curves.sort_values("TipoEquacao").groupby("NumeroCurva").last()
        minimum, maximum = curves["CotaMinima"].min(), curves["CotaMaxima"].max()
        stages_list = []
        for _, curve in curves.iterrows():
            if curve["TipoEquacao"] != 1:
                msg = "Only equation type 1 is supported: Q = A * (H - H0) ** n"
                raise ValueError(msg)
            if curve["CoefA"] <= 0 or curve["CoefN"] <= 0:
                msg = "Rating-curve coefficients A and n must be positive."
                raise ValueError(msg)
            lower, upper = curve["CotaMinima"], curve["CotaMaxima"]
            if lower == minimum:
                lower *= 0.8 if lower > 0 else 1.2
            if upper == maximum:
                upper *= 1.2
            stages = 100 * self.stage_from_flow(
                q.where(q >= 0), curve["CoefA"], curve["CoefH0"], curve["CoefN"]
            )
            stages = stages.replace([np.inf, -np.inf], np.nan).dropna()
            stages = stages.astype("int64")
            stages_list.append(stages[(stages >= lower) & (stages <= upper)])
        stages = pd.concat(stages_list).groupby(level=list(range(q.index.nlevels))).mean()
        if not ignore_error and not q.index.isin(stages.index).all():
            msg = f"{station}: rating curves do not cover every supplied discharge value."
            raise ValueError(msg)
        return stages.reindex(q.index) if not ignore_error else stages
