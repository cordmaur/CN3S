"""Selection and plotting of hydrological stations."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

import geopandas as gpd
import pandas as pd

from .otto import Otto

_COORDINATE_TOLERANCE = 0.01

if TYPE_CHECKING:
    from pathlib import Path

    from matplotlib.axes import Axes

    from .hydrography import Hydrography


class Stations:
    """Load station GeoParquet and relate its points to a hydrography network."""

    def __init__(self, stations_path: str | Path, hydrography: Hydrography) -> None:
        """
        Load telemetric or Otto-referenced station records from a GeoParquet file.

        Args:
            stations_path: Station GeoParquet path.
            hydrography: Loaded hydrography used to identify upstream reaches.

        Raises:
            ValueError: If required station fields or geometry are invalid.

        """
        loaded = gpd.read_parquet(stations_path)
        if "geometry_st" in loaded.columns:
            loaded = loaded.set_geometry("geometry_st")
        if loaded.geometry.isna().any() or loaded.geometry.is_empty.any():
            msg = "stations must have non-empty point geometry"
            raise ValueError(msg)
        if not loaded.geom_type.eq("Point").all():
            msg = "stations must contain only point geometry"
            raise ValueError(msg)
        loaded = loaded.set_crs("EPSG:4674") if loaded.crs is None else loaded.to_crs("EPSG:4674")

        self.source_count = len(loaded)
        self.filtered_count = len(loaded)
        self.is_telemetric = "ESTCODIGOADICIONAL" in loaded.columns
        if self.is_telemetric:
            prepared = self._prepare_telemetric(loaded)
        else:
            prepared = self._prepare_otto(loaded)

        self.stations: gpd.GeoDataFrame = prepared
        self.hydrography = hydrography
        self.selected: gpd.GeoDataFrame | None = None
        self.upstream_area: gpd.GeoDataFrame | None = None

    def _prepare_telemetric(self, loaded: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Filter source rows, then keep one row per ANA-style station key."""
        required = {
            "ESTRESPONSAVEL",
            "OGMORGAO",
            "ESTCODIGO",
            "ESTCODIGOADICIONAL",
            "ESTLATITUDE",
            "ESTLONGITUDE",
        }
        missing = required.difference(loaded.columns)
        if missing:
            msg = f"telemetric stations are missing columns: {sorted(missing)}"
            raise ValueError(msg)

        responsible = pd.to_numeric(loaded["ESTRESPONSAVEL"], errors="coerce").eq(1)
        organization = loaded["OGMORGAO"].astype("string").str.strip().eq("RHN").fillna(value=False)
        status = pd.to_numeric(loaded["ESTSTATUS"], errors="coerce").eq(0)
        filtered = loaded.loc[responsible & organization & status].copy()
        self.filtered_count = len(filtered)
        keys = filtered["ESTCODIGOADICIONAL"].astype("string").str.strip()
        if keys.isna().any() or keys.eq("").any():
            msg = "qualifying stations must have non-empty ESTCODIGOADICIONAL"
            raise ValueError(msg)
        filtered["ESTCODIGOADICIONAL"] = keys
        record_codes = pd.to_numeric(filtered["ESTCODIGO"], errors="coerce")
        if record_codes.isna().any() or record_codes.duplicated().any():
            msg = "qualifying ESTCODIGO values must be numeric and unique"
            raise ValueError(msg)
        filtered["_record_code"] = record_codes

        latitude = pd.to_numeric(filtered["ESTLATITUDE"], errors="coerce")
        longitude = pd.to_numeric(filtered["ESTLONGITUDE"], errors="coerce")
        if latitude.isna().any() or longitude.isna().any():
            msg = "qualifying station coordinates must be numeric"
            raise ValueError(msg)
        if ((filtered.geometry.x - longitude).abs() > _COORDINATE_TOLERANCE).any() or (
            (filtered.geometry.y - latitude).abs() > _COORDINATE_TOLERANCE
        ).any():
            msg = "station geometry does not match ESTLATITUDE/ESTLONGITUDE"
            raise ValueError(msg)

        prepared = filtered.sort_values("_record_code", kind="stable")
        prepared = prepared.drop_duplicates("ESTCODIGOADICIONAL", keep="last")
        prepared = prepared.drop(columns="_record_code").set_index("ESTCODIGOADICIONAL")
        return prepared

    @staticmethod
    def _prepare_otto(loaded: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Keep the established Otto-referenced station schema available from files."""
        if "cobacia" not in loaded.columns:
            msg = "stations must contain cobacia or the telemetric station schema"
            raise ValueError(msg)
        if "CÓDIGO" in loaded.columns:
            loaded = loaded.set_index("CÓDIGO")
        elif loaded.index.name != "CÓDIGO":
            msg = "Otto-referenced stations must contain a CÓDIGO column or index"
            raise ValueError(msg)
        if loaded.index.has_duplicates or loaded.index.hasnans:
            msg = "CÓDIGO must uniquely identify each station"
            raise ValueError(msg)
        return loaded

    def assign_cobacia(self) -> gpd.GeoDataFrame:
        """
        Assign watershed `cobacia` and version to each station point.

        Returns:
            Station GeoDataFrame with `cobacia`, `dsversao`, and assignment status.

        """
        cols = self.hydrography.cols
        watersheds = self.hydrography.watersheds
        required = {cols.otto_code, "dsversao"}
        missing = required.difference(watersheds.columns)
        if missing:
            msg = f"watersheds are missing columns: {sorted(missing)}"
            raise ValueError(msg)
        watersheds = (
            watersheds.set_crs("EPSG:4674")
            if watersheds.crs is None
            else watersheds.to_crs("EPSG:4674")
        )

        station_points = self.stations[[self.stations.geometry.name]]
        candidates = watersheds[[cols.otto_code, "dsversao", watersheds.geometry.name]]
        inside = gpd.sjoin(station_points, candidates, how="left", predicate="within")
        matched = inside.loc[inside["index_right"].notna()]
        missing_codes = self.stations.index.difference(matched.index)
        if len(missing_codes):
            boundary = gpd.sjoin(
                station_points.loc[missing_codes], candidates, how="left", predicate="intersects"
            )
            matched = cast(
                "gpd.GeoDataFrame",
                pd.concat([matched, boundary.loc[boundary["index_right"].notna()]]),
            )

        reaches = self.hydrography.reaches
        reach_pairs = set(
            zip(reaches[cols.otto_code].astype(str), reaches["dsversao"].astype(str), strict=True)
        )
        assigned: dict[object, tuple[str | None, str | None, str]] = {}
        for station_code in self.stations.index:
            if station_code not in matched.index:
                assigned[station_code] = (None, None, "unmatched")
                continue
            rows = matched.loc[[station_code]]
            pairs = {
                (str(code), str(version))
                for code, version in zip(rows[cols.otto_code], rows["dsversao"], strict=True)
            }
            if len(pairs) != 1:
                assigned[station_code] = (None, None, "ambiguous")
                continue
            code, version = pairs.pop()
            status = "assigned" if (code, version) in reach_pairs else "reach_missing"
            assigned[station_code] = (code, version, status)

        for name, position in (("cobacia", 0), ("dsversao", 1), ("assignment_status", 2)):
            self.stations[name] = [assigned[code][position] for code in self.stations.index]
        return self.stations

    def _resolve_target(
        self,
        cobacia: str | int | None,
        station_code: str | int | None,
    ) -> tuple[str, str, str]:
        """
        Resolve one input to a cobacia, river code, and reach version.

        Args:
            cobacia: Otto code of the target reach.
            station_code: Code of the station at the target reach.

        Returns:
            Target cobacia, river code, and network version.

        Raises:
            ValueError: If the input is ambiguous or cannot be found.

        """
        if (cobacia is None) == (station_code is None):
            msg = "Provide exactly one of cobacia or station_code"
            raise ValueError(msg)

        station_version: str | None = None
        if station_code is not None:
            if "cobacia" not in self.stations:
                msg = "Station cobacia is unavailable; call assign_cobacia first"
                raise ValueError(msg)
            station_matches = self.stations.loc[
                self.stations.index.astype(str) == str(station_code)
            ]
            if len(station_matches) != 1:
                msg = f"Station code {station_code} must identify exactly one station"
                raise ValueError(msg)
            cobacia = station_matches["cobacia"].iloc[0]

            status = station_matches.get("assignment_status")
            if status is not None and status.iloc[0] != "assigned":
                msg = f"Station code {station_code} has no usable cobacia assignment"
                raise ValueError(msg)
            if "dsversao" in station_matches and pd.notna(station_matches["dsversao"].iloc[0]):
                station_version = str(station_matches["dsversao"].iloc[0])

        if pd.isna(cobacia):
            msg = "No cobacia is available for the selected station"
            raise ValueError(msg)

        code = str(cobacia)
        cols = self.hydrography.cols
        reaches = self.hydrography.reaches
        matching_code = reaches.loc[reaches[cols.otto_code].astype(str).eq(code)]
        if matching_code.empty:
            msg = f"Cobacia {code} was not found in the reach network"
            raise ValueError(msg)
        version = station_version or Otto.guess_version(reaches, code, cols)
        matching = matching_code.loc[matching_code["dsversao"].astype(str).eq(version)]
        if matching.empty:
            msg = f"Cobacia {code} with version {version} was not found in the reach network"
            raise ValueError(msg)

        river_code = str(matching[cols.river_code].iloc[0])
        return code, river_code, version

    def select_upstream(
        self,
        cobacia: str | int | None = None,
        *,
        station_code: str | int | None = None,
    ) -> None:
        """
        Save stations upstream of a cobacia or station, including the starting reach.

        Args:
            cobacia: Otto code of the downstream reach.
            station_code: Station code whose cobacia identifies the downstream reach.

        Raises:
            ValueError: If neither or both codes are given, or a code cannot be found.

        """
        code, river_code, version = self._resolve_target(cobacia, station_code)
        cols = self.hydrography.cols
        reaches = self.hydrography.reaches
        upstream = Otto.get_upstream(reaches, code, river_code, cols, version=version)
        upstream_codes = set(upstream[cols.otto_code])
        mask = self.stations["cobacia"].astype("string").isin(upstream_codes)
        self.selected = self.stations.loc[mask].copy()

    def create_upstream(
        self,
        cobacia: str | int | None = None,
        *,
        station_code: str | int | None = None,
    ) -> gpd.GeoDataFrame:
        """
        Dissolve all watersheds upstream of a cobacia or station into one area.

        Args:
            cobacia: Otto code of the downstream watershed.
            station_code: Station code whose cobacia identifies the watershed.

        Returns:
            One-row GeoDataFrame with the dissolved upstream geometry.

        Raises:
            ValueError: If input is invalid or no upstream watersheds are found.

        """
        code, river_code, version = self._resolve_target(cobacia, station_code)
        watersheds = Otto.get_upstream(
            self.hydrography.watersheds,
            code,
            river_code,
            self.hydrography.cols,
            version=version,
        )
        if watersheds.empty:
            msg = f"No upstream watersheds found for cobacia {code}"
            raise ValueError(msg)

        if "nuareacont" not in watersheds.columns:
            msg = "Watersheds must contain nuareacont to calculate contribution area"
            raise ValueError(msg)
        contributions = watersheds["nuareacont"].astype(float)
        if contributions.isna().any() or (contributions < 0).any():
            msg = "Upstream nuareacont values must be non-negative and present"
            raise ValueError(msg)
        area_km2 = float(contributions.sum())
        if not math.isfinite(area_km2) or area_km2 <= 0:
            msg = "Summed upstream nuareacont area must be positive and finite"
            raise ValueError(msg)

        area = cast(
            "gpd.GeoDataFrame",
            watersheds[[self.hydrography.watersheds.geometry.name]].dissolve(),
        )
        area["area_nuareacont_km2"] = area_km2
        self.upstream_area = area
        return area

    def plot_selected(self, ax: Axes) -> Axes:
        """
        Plot and label selected stations, allowing the axes to autoscale.

        Args:
            ax: Matplotlib axes to draw on.

        Returns:
            The supplied axes.

        Raises:
            ValueError: If no selection has been made yet.

        """
        if self.selected is None:
            msg = "No stations selected; call select_upstream first"
            raise ValueError(msg)
        if self.selected.empty:
            return ax

        self._plot_stations(self.selected, ax, color="red")
        ax.autoscale(enable=True)
        return ax

    def plot(self, ax: Axes) -> Axes:
        """
        Plot and label every station in the current axis bounds.

        Args:
            ax: Matplotlib axes whose bounds define the visible stations.

        Returns:
            The supplied axes.

        """
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        xmin, xmax = sorted(xlim)
        ymin, ymax = sorted(ylim)
        visible = self.stations.cx[xmin:xmax, ymin:ymax]  # type: ignore[misc]
        if visible.empty:
            return ax

        self._plot_stations(visible, ax, color="grey")
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        return ax

    @staticmethod
    def _plot_stations(stations: gpd.GeoDataFrame, ax: Axes, color: str) -> None:
        """
        Draw station markers and code labels.

        Args:
            stations: Stations to draw.
            ax: Matplotlib axes to draw on.
            color: Marker color.

        """
        stations.plot(ax=ax, color=color, markersize=20, zorder=9)
        for code, geometry in stations.geometry.items():
            point = geometry.representative_point()
            x, y = point.coords[0]
            ax.annotate(
                str(code),
                (x, y),
                xytext=(3, 3),
                textcoords="offset points",
                zorder=10,
            )
