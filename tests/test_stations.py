"""Tests for the small station selection and plotting interface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib as mpl

mpl.use("Agg")

import geopandas as gpd
import matplotlib.pyplot as plt
import pytest
from shapely.geometry import LineString, Point, box

from hydrography import Hydrography, Stations

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def hydrography(tmp_path: Path) -> Hydrography:
    """Build a short network with two river prefixes."""
    reaches = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121", "130", "140"],
            "cocursodag": ["12", "12", "13", "14"],
            "nuareamont": [10.0, 12.0, 8.0, 4.0],
            "dsversao": ["v1"] * 4,
        },
        geometry=[LineString([(i, 0), (i, 1)]) for i in range(4)],
        crs="EPSG:4674",
    )
    watersheds = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121", "130", "140", "122"],
            "dsversao": ["v1", "v1", "v1", "v1", "v2"],
            "nuareacont": [1.25, 2.75, 3.0, 4.0, 100.0],
        },
        geometry=[*[box(i, 0, i + 1, 1) for i in range(4)], box(100, 0, 101, 1)],
        crs="EPSG:4674",
    )
    reaches_path = tmp_path / "reaches.parquet"
    watersheds_path = tmp_path / "watersheds.parquet"
    reaches.to_parquet(reaches_path)
    watersheds.to_parquet(watersheds_path)
    return Hydrography(watersheds_path, reaches_path)


@pytest.fixture
def stations(hydrography: Hydrography, tmp_path: Path) -> Stations:
    """Make stations using the supplied geometry_st column."""
    data = gpd.GeoDataFrame(
        {
            "CÓDIGO": [101, 102, 103, 104],
            "cobacia": ["120", "121", "130", "140"],
        },
        geometry=gpd.GeoSeries(
            [Point(0, 0), Point(1, 1), Point(2, 2), Point(5, 5)],
            name="geometry_st",
            crs="EPSG:4674",
        ),
    )
    stations_path = tmp_path / "stations.parquet"
    data.to_parquet(stations_path)
    result = Stations(stations_path, hydrography)
    assert "CÓDIGO" in data.columns
    return result


def test_select_upstream_uses_either_code(stations: Stations) -> None:
    """Both input routes find the same stations using the reach network."""
    assert stations.select_upstream(cobacia="120") is None
    assert stations.selected is not None
    assert stations.selected.index.name == "CÓDIGO"
    assert stations.selected.index.tolist() == [101, 102]

    stations.select_upstream(station_code="101")
    assert stations.selected is not None
    assert stations.selected.index.tolist() == [101, 102]
    assert stations.stations.index.tolist() == [101, 102, 103, 104]

    with pytest.raises(ValueError, match="exactly one"):
        stations.select_upstream()
    with pytest.raises(ValueError, match="exactly one"):
        stations.select_upstream(cobacia="120", station_code=101)
    with pytest.raises(ValueError, match="Station code"):
        stations.select_upstream(station_code=999)
    with pytest.raises(ValueError, match="not found"):
        stations.select_upstream(cobacia="999")


def test_plot_labels_all_visible_stations(stations: Stations) -> None:
    """Selection does not restrict plotting, while axis bounds do."""
    stations.select_upstream(cobacia="120")
    fig, ax = plt.subplots()
    try:
        ax.set_xlim(-1, 3)
        ax.set_ylim(-1, 3)
        assert stations.plot(ax) is ax
        assert {item.get_text() for item in ax.texts} == {"101", "102", "103"}
        assert ax.get_xlim() == (-1, 3)
        assert ax.get_ylim() == (-1, 3)
    finally:
        plt.close(fig)


def test_plot_selected_labels_and_resizes_axes(stations: Stations) -> None:
    """Selected markers can expand axes previously limited to a small area."""
    fig, ax = plt.subplots()
    try:
        with pytest.raises(ValueError, match="select_upstream"):
            stations.plot_selected(ax)

        stations.select_upstream(station_code=103)
        ax.set_xlim(-0.5, 0.5)
        ax.set_ylim(-0.5, 0.5)
        assert stations.plot_selected(ax) is ax
        assert {item.get_text() for item in ax.texts} == {"103"}
        selected_coordinate = 2
        assert ax.get_xlim()[1] > selected_coordinate
        assert ax.get_ylim()[1] > selected_coordinate
    finally:
        plt.close(fig)


def test_create_upstream_dissolves_watersheds(stations: Stations) -> None:
    """Both input routes yield the same single upstream polygon and CRS."""
    from_cobacia = stations.create_upstream(cobacia="120")
    from_station = stations.create_upstream(station_code=101)

    assert len(from_cobacia) == 1
    assert from_cobacia.crs == stations.hydrography.watersheds.crs
    assert from_cobacia.geometry.iloc[0].equals(box(0, 0, 2, 1))
    assert from_station.geometry.iloc[0].equals(from_cobacia.geometry.iloc[0])
    expected_area_km2 = 4.0
    assert from_station["area_nuareacont_km2"].iloc[0] == expected_area_km2
    assert stations.upstream_area is from_station

    with pytest.raises(ValueError, match="exactly one"):
        stations.create_upstream()
    with pytest.raises(ValueError, match="exactly one"):
        stations.create_upstream(cobacia="120", station_code=101)
    with pytest.raises(ValueError, match="Station code"):
        stations.create_upstream(station_code=999)
    with pytest.raises(ValueError, match="not found"):
        stations.create_upstream(cobacia="999")
