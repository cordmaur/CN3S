"""File-backed basin overview tests with a small synthetic network."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import geopandas as gpd
import matplotlib as mpl
import pandas as pd

mpl.use("Agg")

import matplotlib.pyplot as plt
import pytest
from matplotlib.collections import LineCollection
from shapely.geometry import LineString, Point, Polygon, box

from hydrography import BasinOverview, Hydrography, Stations

if TYPE_CHECKING:
    from pathlib import Path

SOURCE_COUNT = 9
FILTERED_COUNT = 7
GROUPED_COUNT = 6
OVERVIEW_COUNT = 4
ASSIGNED_OVERVIEW_COUNT = 3
SELECTED_RECORD = 2
WORKING_EPSG = 4674
VISIBLE_REACH_COUNT = 3


@pytest.fixture
def network(tmp_path: Path) -> Hydrography:
    """Provide two adjacent watersheds and one without a matching reach."""
    reaches = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121"],
            "cocursodag": ["12", "12"],
            "nuareamont": [2.0, 3.0],
            "dsversao": ["v1", "v1"],
        },
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 0), (2, 1)])],
        crs="EPSG:4674",
    )
    watersheds = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121", "140"],
            "dsversao": ["v1", "v1", "v1"],
            "nuareacont": [1.0, 1.0, 1.0],
        },
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(4, 0, 5, 1)],
        crs="EPSG:4674",
    )
    reach_path = tmp_path / "reaches.parquet"
    watershed_path = tmp_path / "watersheds.parquet"
    reaches.to_parquet(reach_path)
    watersheds.to_parquet(watershed_path)
    return Hydrography(watershed_path, reach_path)


@pytest.fixture
def station_path(tmp_path: Path) -> Path:
    """Include filter exclusions, duplicate keys, boundaries, and missing watersheds."""
    rows = [
        (1, "0001", 1, "RHN", Point(0.2, 0.2)),
        (2, "0001", 1, "RHN", Point(0.3, 0.3)),
        (99, "0001", 2, "RHN", Point(9, 9)),
        (3, "1", 1, "RHN", Point(1.5, 0.5)),
        (4, "edge", 1, "RHN", Point(0, 0.5)),
        (5, "ambiguous", 1, "RHN", Point(1, 0.5)),
        (6, "missing", 1, "RHN", Point(6, 6)),
        (7, "no-reach", 1, "RHN", Point(4.5, 0.5)),
        (8, "excluded", 1, "CotaOnline", Point(0.5, 0.5)),
    ]
    frame = gpd.GeoDataFrame(
        {
            "ESTCODIGO": [Decimal(code) for code, *_ in rows],
            "ESTCODIGOADICIONAL": [key for _, key, *_ in rows],
            "ESTRESPONSAVEL": [Decimal(responsible) for _, _, responsible, *_ in rows],
            "OGMORGAO": [organization for _, _, _, organization, _ in rows],
            "ESTNOME": [f"Station {code}" for code, *_ in rows],
            "ESTSTATUS": [Decimal(0)] * len(rows),
            "ESTLATITUDE": [str(point.y) for *_, point in rows],
            "ESTLONGITUDE": [str(point.x) for *_, point in rows],
        },
        geometry=[point for *_, point in rows],
        crs=None,
    )
    path = tmp_path / "telemetric.parquet"
    frame.to_parquet(path)
    return path


def test_filter_group_and_assign_cobacia(station_path: Path, network: Hydrography) -> None:
    """Filter before deduplication and report distinct spatial assignment outcomes."""
    stations = Stations(station_path, network)
    assert stations.source_count == SOURCE_COUNT
    assert stations.filtered_count == FILTERED_COUNT
    assert len(stations.stations) == GROUPED_COUNT
    assert set(stations.stations.index) == {
        "0001",
        "1",
        "edge",
        "ambiguous",
        "missing",
        "no-reach",
    }
    assert stations.stations.loc["0001", "ESTCODIGO"] == Decimal(2)
    assert stations.stations.crs.to_epsg() == WORKING_EPSG

    assigned = stations.assign_cobacia()
    assert assigned.loc["0001", "cobacia"] == "120"
    assert assigned.loc["1", "cobacia"] == "121"
    assert assigned.loc["edge", "assignment_status"] == "assigned"
    assert assigned.loc["ambiguous", "assignment_status"] == "ambiguous"
    assert assigned.loc["missing", "assignment_status"] == "unmatched"
    assert assigned.loc["no-reach", "assignment_status"] == "reach_missing"
    stations.select_upstream(station_code="0001")
    assert stations.selected is not None
    assert set(stations.selected.index) == {"0001", "1", "edge"}
    with pytest.raises(ValueError, match="no usable cobacia"):
        stations.select_upstream(station_code="ambiguous")


def test_projected_basin_overview_and_map(
    station_path: Path, network: Hydrography, tmp_path: Path
) -> None:
    """Reproject a basin, include boundary stations, and show all selected labels."""
    basin = gpd.GeoDataFrame(geometry=[box(0, 0, 2, 1)], crs="EPSG:4674").to_crs(3857)
    basin_path = tmp_path / "projected-basin.parquet"
    basin.to_parquet(basin_path)
    overview = BasinOverview(basin_path, station_path, network)
    assert overview.station_count == OVERVIEW_COUNT
    assert overview.basin.crs.to_epsg() == WORKING_EPSG
    table = overview.station_table()
    assert set(table["ESTCODIGOADICIONAL"]) == {"0001", "1", "edge", "ambiguous"}
    assert table["ESTCODIGOADICIONAL"].is_unique
    assert table.loc[table["ESTCODIGOADICIONAL"] == "0001", "ESTCODIGO"].iloc[0] == SELECTED_RECORD
    assert overview.summary().set_index("measure")["count"].to_dict() == {
        "Source records": SOURCE_COUNT,
        "Records after RHN/responsible/status filter": FILTERED_COUNT,
        "Unique station keys after grouping": GROUPED_COUNT,
        "Stations inside basin": OVERVIEW_COUNT,
        "Stations assigned to a watershed": ASSIGNED_OVERVIEW_COUNT,
    }

    nearby_outside = network.reaches.iloc[[0]].copy()
    nearby_outside.geometry = [LineString([(-0.03, 0.2), (-0.03, 0.8)])]
    far_away = network.reaches.iloc[[0]].copy()
    far_away.geometry = [LineString([(5, 0.2), (5, 0.8)])]
    network.reaches = gpd.GeoDataFrame(
        pd.concat([network.reaches, nearby_outside, far_away], ignore_index=True),
        geometry="geometry",
        crs=network.reaches.crs,
    )
    fig, ax = plt.subplots()
    try:
        assert overview.plot(ax) is ax
        assert {item.get_text() for item in ax.texts} == set(table["ESTCODIGOADICIONAL"])
        reach_lines = [item for item in ax.collections if isinstance(item, LineCollection)]
        assert len(reach_lines) == 1
        assert len(reach_lines[0].get_segments()) == VISIBLE_REACH_COUNT
        assert len(set(reach_lines[0].get_linewidths())) > 1
        fig.canvas.draw()
    finally:
        plt.close(fig)


def test_invalid_basin_is_repaired(
    station_path: Path, network: Hydrography, tmp_path: Path
) -> None:
    """Repair a crossed polygon in memory without changing its GeoParquet source."""
    crossed = Polygon([(0, 0), (2, 1), (0, 1), (2, 0), (0, 0)])
    assert not crossed.is_valid
    basin = gpd.GeoDataFrame(geometry=[crossed], crs="EPSG:4674")
    path = tmp_path / "crossed.parquet"
    basin.to_parquet(path)
    overview = BasinOverview(path, station_path, network)
    assert overview.basin.is_valid.all()
    assert not gpd.read_parquet(path).is_valid.all()


def test_empty_basin_has_an_empty_table_and_map(
    station_path: Path, network: Hydrography, tmp_path: Path
) -> None:
    """A basin without qualifying stations still produces a usable overview."""
    basin = gpd.GeoDataFrame(geometry=[box(10, 10, 11, 11)], crs="EPSG:4674")
    path = tmp_path / "empty-basin.parquet"
    basin.to_parquet(path)
    overview = BasinOverview(path, station_path, network)
    assert overview.station_count == 0
    assert overview.station_table().empty
    summary = overview.summary().set_index("measure")["count"]
    assert summary["Stations inside basin"] == 0
    assert summary["Stations assigned to a watershed"] == 0
    fig, ax = plt.subplots()
    try:
        assert overview.plot(ax) is ax
        assert not ax.texts
    finally:
        plt.close(fig)
