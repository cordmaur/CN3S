"""Basin-first overview of filtered telemetric stations."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely import make_valid, union_all
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon

from .stations import Stations

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from shapely.geometry import Point
    from shapely.geometry.base import BaseGeometry

    from .hydrography import Hydrography


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    """Extract polygons from a possibly repaired basin geometry."""
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return [part for item in geometry.geoms for part in _polygon_parts(item)]
    return []


class BasinOverview:
    """Load one basin and list its qualifying, watershed-referenced stations."""

    def __init__(
        self,
        basin_path: str | Path,
        stations_path: str | Path,
        hydrography: Hydrography,
    ) -> None:
        """
        Build an overview from two GeoParquet paths and an existing network.

        Args:
            basin_path: GeoParquet containing one or more basin polygons.
            stations_path: Telemetric station GeoParquet path.
            hydrography: Loaded watershed and reach network.

        """
        self.basin_path = Path(basin_path)
        basin = gpd.read_parquet(self.basin_path)
        if basin.empty or basin.geometry.isna().any():
            msg = "basin must contain non-null polygon geometry"
            raise ValueError(msg)
        basin = basin.set_crs("EPSG:4674") if basin.crs is None else basin.to_crs("EPSG:4674")

        parts: list[Polygon] = []
        for geometry in basin.geometry:
            repaired = make_valid(geometry) if not geometry.is_valid else geometry
            parts.extend(_polygon_parts(repaired))
        if not parts:
            msg = "basin contains no usable polygon geometry"
            raise ValueError(msg)
        polygon = union_all(parts)
        self.basin = gpd.GeoDataFrame(
            {"basin": [self.basin_path.stem]}, geometry=[polygon], crs="EPSG:4674"
        )
        self.hydrography = hydrography
        self.stations = Stations(stations_path, hydrography)
        self.stations.assign_cobacia()
        self.selected = self.stations.stations.loc[
            self.stations.stations.geometry.intersects(polygon)
        ].copy()

    @property
    def station_count(self) -> int:
        """Return the number of qualifying grouped stations in the basin."""
        return len(self.selected)

    def summary(self) -> pd.DataFrame:
        """
        Return source, filter, grouping, basin, and watershed assignment counts.

        Returns:
            Two-column table with ``measure`` and ``count`` values.

        """
        return pd.DataFrame(
            {
                "measure": [
                    "Source records",
                    "Records after RHN/responsible/status filter",
                    "Unique station keys after grouping",
                    "Stations inside basin",
                    "Stations assigned to a watershed",
                ],
                "count": [
                    self.stations.source_count,
                    self.stations.filtered_count,
                    len(self.stations.stations),
                    self.station_count,
                    int(self.selected["assignment_status"].eq("assigned").sum()),
                ],
            }
        )

    def station_table(self) -> pd.DataFrame:
        """
        Return a compact table for inspecting the selected station records.

        Returns:
            Table with identifiers, source fields, Otto assignment, and coordinates.

        """
        columns = [
            "ESTCODIGO",
            "ESTNOME",
            "ESTSTATUS",
            "cobacia",
            "dsversao",
            "assignment_status",
        ]
        available = [column for column in columns if column in self.selected.columns]
        table = self.selected[available].copy().reset_index()
        table["longitude"] = self.selected.geometry.x.to_numpy()
        table["latitude"] = self.selected.geometry.y.to_numpy()
        return pd.DataFrame(table).sort_values("ESTCODIGOADICIONAL").reset_index(drop=True)

    def plot(self, ax: Axes, *, labels: bool = True, reaches: bool = True) -> Axes:
        """
        Draw the basin, hydrography, and selected station markers on an axes.

        Args:
            ax: Matplotlib axes to draw on.
            labels: Whether to annotate points with `ESTCODIGOADICIONAL`.
            reaches: Whether to show reaches in the basin viewport.

        Returns:
            The supplied axes.

        """
        self.basin.plot(ax=ax, facecolor="#e6f1f8", edgecolor="#22577a", linewidth=1.4)
        bounds = self.basin.total_bounds
        padding_x = max((bounds[2] - bounds[0]) * 0.03, 0.01)
        padding_y = max((bounds[3] - bounds[1]) * 0.03, 0.01)
        xlim = (bounds[0] - padding_x, bounds[2] + padding_x)
        ylim = (bounds[1] - padding_y, bounds[3] + padding_y)
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        if reaches:
            self.hydrography.plot_reaches(ax, pos="all", zorder=2)
        if not self.selected.empty:
            self.selected.plot(ax=ax, color="#bd3f1f", markersize=28, zorder=5)
            if labels:
                coincident: defaultdict[tuple[float, float], int] = defaultdict(int)
                offsets = [(3, 3), (3, -12), (3, 17), (3, -25)]
                for code, geometry in self.selected.geometry.items():
                    station_point = cast("Point", geometry)
                    rounded_point = (round(station_point.x, 5), round(station_point.y, 5))
                    offset = offsets[coincident[rounded_point] % len(offsets)]
                    coincident[rounded_point] += 1
                    ax.annotate(
                        str(code),
                        (station_point.x, station_point.y),
                        xytext=offset,
                        textcoords="offset points",
                        fontsize=7.5,
                        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.7, "pad": 0.15},
                        zorder=6,
                    )
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_title(f"{self.basin_path.stem}: {self.station_count} RHN stations")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        return ax

    def figure(self, *, labels: bool = True, reaches: bool = True) -> Figure:
        """Return a ready-to-display basin and station map."""
        fig, ax = plt.subplots(figsize=(10, 10))
        self.plot(ax, labels=labels, reaches=reaches)
        fig.tight_layout()
        return fig
