"""Offline contracts for the local Hydro SQL providers and station aggregation."""

from __future__ import annotations

# Numeric constants below describe the synthetic station fixtures.
# ruff: noqa: PLR2004
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from hydro import Hidro, Station, Telemetria
from hydro.data import SqlProvider, date_predicate, identifier


class FakeSql:
    """Small source tables with a query log and explicit connection ownership."""

    def __init__(self) -> None:
        """Create synthetic historical and hourly telemetry source tables."""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0
        self.historical = pd.DataFrame(
            {
                "EstacaoCodigo": [10] * 6,
                "NivelConsistencia": [1, 2, 1, 2, 2, 2],
                "MediaDiaria": [1, 1, 1, 1, 0, 1],
                "date": [
                    "2020-01-01",
                    "2020-01-01",
                    "2020-01-02",
                    "2020-01-02",
                    "2020-01-03",
                    "2020-01-04",
                ],
                "value": [1, 4, 3, np.nan, 99, 0],
            }
        )
        self.telemetry = pd.DataFrame(
            {
                "HORDATAHORA": ["2020-01-01 01:00", "2020-01-01 23:00", "2020-01-03 12:00"],
                "value": [10, 20, 30],
            }
        )

    def read_sql_with_retries(self, query: str, **kwargs: Any) -> pd.DataFrame:
        """Return deterministic data for each provider query."""
        params = kwargs.get("params", {})
        self.calls.append((query, params))
        if "INFORMATION_SCHEMA" in query:
            return pd.DataFrame({"TABLE_NAME": ["Estacao", "CurvaDescarga"]})
        if "[hidro].[Estacao]" in query:
            return pd.DataFrame({"Codigo": [10], "Nome": ["Test station"]})
        if "[hidro].[CurvaDescarga]" in query:
            return pd.DataFrame(
                {
                    "NumeroCurva": [1],
                    "TipoEquacao": [1],
                    "CoefA": [1.0],
                    "CoefH0": [0.0],
                    "CoefN": [2.0],
                    "CotaMinima": [0],
                    "CotaMaxima": [1000],
                }
            )
        if "[hidro].[pivot" in query:
            kind = "cota" if "pivotcotas" in query else "vazao"
            frame = self.historical.rename(columns={"date": f"{kind}_data", "value": f"{kind}_val"})
            return self._window(frame, f"{kind}_data", params)
        if "LEFT JOIN" in query:
            codes = [100, 200] if "ESTANEELFLU" in query else [params["code"]]
            return pd.DataFrame(
                {
                    "ESTCODIGO": codes,
                    "ESTNOME": ["Telemetry"] * len(codes),
                    "OGMORGAO": ["RHN" if code == 100 else "Setor Elétrico" for code in codes],
                }
            )
        if "[hidroInfoAna].[cotas]" in query or "[hidroInfoAna].[vazoes]" in query:
            kind = "HORNIVELADOTADO" if "[cotas]" in query else "HORVAZAO"
            frame = self.telemetry.rename(columns={"value": kind}).copy()
            frame["HORESTACAO"] = params["code"]
            if params["code"] == 200:
                frame[kind] *= 10
            return self._window(frame, "HORDATAHORA", params)
        msg = f"Unexpected query: {query}"
        raise AssertionError(msg)

    @staticmethod
    def _window(frame: pd.DataFrame, column: str, params: dict[str, Any]) -> pd.DataFrame:
        dates = pd.to_datetime(frame[column])
        if "start" in params:
            frame = frame.loc[dates >= params["start"]]
        if "end" in params:
            frame = frame.loc[dates.loc[frame.index] < params["end"]]
        return frame.copy()

    def close(self) -> None:
        """Count resource cleanup."""
        self.closed += 1


def test_import_and_construction_have_no_external_side_effects() -> None:
    """Importing and constructing providers must not import Spark or authenticate."""
    script = (
        "import sys; from hydro import Hidro, Telemetria; Hidro(); Telemetria(); "
        "assert 'pyspark' not in sys.modules; "
        "assert 'utils.sql_connector' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603


def test_historical_consistency_daily_filter_and_nulls() -> None:
    """Choose valid daily rows atomically and retain genuine zero discharge."""
    sql = FakeSql()
    hidro = Hidro(sql)
    combined = hidro.get_series(10, "vazao")
    assert combined["val"].tolist() == [4, 3, 0]
    assert combined["NivelConsistencia"].tolist() == [2, 1, 2]
    assert combined.index.name == "Data"
    assert combined["dia"].tolist() == [1, 2, 4]
    assert hidro.get_series(10, "vazao", "raw")["val"].tolist() == [1, 3]
    assert hidro.get_series(10, "cota", "validated")["val"].tolist() == [4, 0]
    hidro.get_series(10, "vazao", start="2020-01-01", end="2020-01-01")
    query, params = sql.calls[-1]
    assert "EstacaoCodigo = :code" in query
    assert params["code"] == 10
    assert params["end"] == pd.Timestamp("2020-01-02")
    assert "SELECT EstacaoCodigo, NivelConsistencia, MediaDiaria" in query
    assert "SELECT *" not in query


def test_telemetry_averages_numeric_values_and_includes_end_day() -> None:
    """Average same-day observations, keeping the entire requested last day."""
    telemetry = Telemetria(FakeSql())
    frame = telemetry.get_series(100, "vazao", start="2020-01-01", end="2020-01-01")
    assert frame["val"].tolist() == [15]
    assert frame["ORIGEM"].iloc[0] == "RHN"
    assert telemetry.get_telemetric_name(100) == "Telemetry"
    assert telemetry.get_telemetric_code(10).index.tolist() == [100, 200]


def test_station_precedence_window_sanitization_and_copy() -> None:
    """Historical data win overlaps; RHN fills gaps ahead of other origins."""
    sql = FakeSql()
    station = Station(
        10,
        {"vazao": {"2020-01-02": 7}},
        hidro=Hidro(sql),
        telemetria=Telemetria(sql),
        start="2020-01-01",
        end="2020-01-03",
    )
    assert station.name == "Test station"
    merged = station.get_series()
    assert merged["val"].tolist() == [4, 7, 30]
    assert merged["Sistema"].tolist() == ["Hidro", "Hidro", "Telemetria"]
    assert station.get_series("telemetria")["val"].tolist() == [15, 30]
    assert len(station.get_series(period=slice("2020-01-02", "2020-01-02"))) == 1
    assert len(station.available_series()) == 6
    merged.loc[:, "val"] = -1
    assert station.get_series()["val"].tolist() == [4, 7, 30]
    ax = station.plot_series()
    assert ax.get_ylabel() == "Vazão (m³/s)"
    import matplotlib.pyplot as plt  # noqa: PLC0415

    plt.close(ax.figure)
    station.close()
    assert sql.closed == 0
    assert not hasattr(station, "stats")


def test_no_telemetry_or_historical_data() -> None:
    """Missing source records remain usable typed empty frames."""
    sql = FakeSql()
    sql.telemetry = sql.telemetry.iloc[:0]
    sql.historical = sql.historical.iloc[:0]
    station = Station(10, hidro=Hidro(sql), telemetria=Telemetria(sql))
    frame = station.get_series()
    assert frame.empty
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert "val" in frame
    with pytest.raises(ValueError, match="No vazao observations"):
        station.plot_series()


def test_rating_curve_is_lazy_and_retains_units_and_index() -> None:
    """Rating conversion uses only station curves and returns centimetres."""
    sql = FakeSql()
    hidro = Hidro(sql)
    assert sql.calls == []
    q = pd.Series([1.0, 4.0], index=pd.date_range("2020-01-01", periods=2), name="val")
    stages = hidro.compute_stage_from_flow(q, 10)
    assert stages.tolist() == [100, 200]
    assert stages.index.equals(q.index)
    assert any("CurvaDescarga" in query for query, _ in sql.calls)
    with pytest.raises(ValueError, match="do not cover"):
        hidro.compute_stage_from_flow(pd.Series([-1.0]), 10)
    assert hidro.compute_stage_from_flow(pd.Series([-1.0]), 10, ignore_error=True).empty


def test_owned_and_borrowed_connector_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default station providers share one owned connection; injected ones stay open."""
    sql = FakeSql()
    monkeypatch.setattr("utils.sql_connector.SqlConnector", lambda: sql)
    with Station(10) as station:
        assert station.hidro.connector is sql
        assert station.telemetria.connector is sql
    station.close()
    assert sql.closed == 1
    borrowed = Hidro(FakeSql())
    borrowed.close()
    assert borrowed._connector.closed == 0  # noqa: SLF001


def test_validation_and_metadata_resolution() -> None:
    """Reject invalid arguments before querying and validate table contracts."""
    sql = FakeSql()
    hidro = Hidro(sql)
    with pytest.raises(ValueError, match="Series type"):
        hidro.get_series(10, "rain")
    with pytest.raises(ValueError, match="Data status"):
        hidro.get_series(10, "vazao", "bad")
    with pytest.raises(ValueError, match="Start date"):
        date_predicate("Data", "2021-01-01", "2020-01-01")
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        identifier("hidro.estacao; DROP TABLE x")
    assert sql.calls == []
    assert hidro.get_station_info(10)["Nome"].iloc[0] == "Test station"
    explicit = Hidro(sql, stations_table="hidro.Estacao")
    previous = len(sql.calls)
    explicit.get_station_info(10)
    assert len(sql.calls) == previous + 1
    sql.historical = sql.historical.drop(columns="MediaDiaria")
    with pytest.raises(ValueError, match="MediaDiaria"):
        hidro.get_series(10, "vazao")


def test_repeated_reads_do_not_mutate_source_frames() -> None:
    """Normalization leaves the injected reader's input data intact."""
    sql = FakeSql()
    before = sql.historical.copy(deep=True)
    hidro = Hidro(sql)
    hidro.get_series(10, "cota")
    hidro.get_series(10, "vazao")
    assert_frame_equal(sql.historical, before)


def test_ambiguous_metadata_and_closed_provider() -> None:
    """Do not guess missing table names or reconnect a closed provider."""
    sql = FakeSql()
    provider = SqlProvider(sql)
    with pytest.raises(ValueError, match="Supply a table override"):
        provider.resolve_table("hidro", "unknown", None)
    provider.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = provider.connector


def test_connector_parameter_binding_and_connection_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real SQLite execution checks binding; a transient acquisition failure is retried."""
    from sqlalchemy import create_engine  # noqa: PLC0415

    from utils.sql_connector import SqlConnector  # noqa: PLC0415

    engine = create_engine("sqlite://")

    class FlakyEngine:
        """Simulate one failed connection before allowing normal SQL execution."""

        def __init__(self) -> None:
            self.attempts = 0

        def connect(self) -> Any:
            """Fail on first attempt."""
            self.attempts += 1
            if self.attempts == 1:
                msg = "Temporary connection failure"
                raise ConnectionError(msg)
            return engine.connect()

    flaky = FlakyEngine()
    connector = SqlConnector.__new__(SqlConnector)
    connector.engine = flaky
    monkeypatch.setattr("utils.sql_connector.time.sleep", lambda _: None)
    payload = "a'; DROP TABLE station; --"
    frame = connector.read_sql_with_retries(
        "SELECT :value AS value",
        params={"value": payload},
        max_attempts=2,
        stream_results=False,
    )
    assert frame["value"].iloc[0] == payload
    assert flaky.attempts == 2
    engine.dispose()
