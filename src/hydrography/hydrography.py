"""
Module containing the Hydrography class.

The Hydrography class initializes with watersheds and reaches,
and has methods to calculate the hydrography of the watershed and reach network.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

import geopandas as gpd
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.legend import Legend

from .columns import HGM_COLUMNS, HGM_LABELS, HydrographyColumns
from .otto import Otto

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib import pyplot as plt


PathLike = str | Path


def load_geospatial_gdf(path: PathLike, crs: str) -> gpd.GeoDataFrame:
    """
    Read a GeoParquet or vector file and project it to the requested CRS.

    Args:
        path: Path to the geospatial file.
        crs: Target coordinate reference system.

    Returns:
        Loaded and projected geospatial data.

    """
    file_path = Path(path)
    gdf = (
        gpd.read_parquet(file_path)
        if file_path.suffix.lower() == ".parquet"
        else gpd.read_file(file_path)
    )
    return gdf.set_crs(crs) if gdf.crs is None else gdf.to_crs(crs)

logger = logging.getLogger(__name__)

# Define a ScopeType for use in multiple methods
ScopeType = Literal["watersheds", "reaches", "hgm"]
PositionType = Literal["touching", "upstream", "downstream", "all"]


class Hydrography:
    """Handle hydrographic data and operations."""

    # Define reaches colors and width factors, by PositionType
    REACHES_COLORS: ClassVar = {
        "touching": {"color": "blue", "width_factor": 1.0},
        "upstream": {"color": "blue", "width_factor": 1.0},
        "downstream": {"color": "blue", "width_factor": 1.2},
        "all": {"color": "royalblue", "width_factor": 1.0},
    }

    # Define reservoir polygon styling per DSOPERA value.
    # "Regulariza" and "Regulariza_ONS" share the same color and legend label.
    RESERVOIRS_CONFIG: ClassVar = {
        "colors": {
            "Fio d'água": "steelblue",
            "Regulariza": "orange",
            "Regulariza_ONS": "orange",
        },
        "labels": {
            "Fio d'água": "Fio d'água",
            "Regulariza": "Regulariza / ONS",
            "Regulariza_ONS": "Regulariza / ONS",
        },
        "edgecolor": "grey",
        "alpha": 0.7,
    }

    def __init__(
        self,
        watersheds_path: PathLike,
        reaches_path: PathLike,
        hgm_path: PathLike | None = None,
        reservoirs_path: PathLike | None = None,
        crs: str = "epsg:4674",
    ) -> None:
        """
        Initialize Hydrography object.

        Args:
            watersheds_path: Path to watershed shapefile or parquet.
            reaches_path: Path to river reaches shapefile or parquet.
            hgm_path: Path to hydrogeomorphology (HGM) data file. Default is None.
            reservoirs_path: Path to the reservoir polygons file. Default is None.
            crs: The coordinate reference system. Default is 'epsg:4674'.

        """
        logger.info("Initializing Hydrography object")
        self.reaches_path = reaches_path
        self.watersheds_path = watersheds_path
        self.hgm_path = hgm_path
        self.reaches: gpd.GeoDataFrame
        self.watersheds: gpd.GeoDataFrame
        self.reservoirs: gpd.GeoDataFrame | None
        self.crs = crs

        self.cols = HydrographyColumns()

        # To store selected reaches and watersheds
        self.selected: dict[str, gpd.GeoDataFrame] = {}

        self._load_reaches(reaches_path, crs)
        self._load_watersheds(watersheds_path, crs)
        self.hgm = None
        if hgm_path is not None:
            self._load_hgm(hgm_path, crs)
        self.reservoirs = None
        if reservoirs_path is not None:
            self._load_reservoirs(reservoirs_path, crs)

    def _load_hgm(self, hgm_path: PathLike, crs: str) -> None:
        """
        Load the hydrogeomorphology (HGM) data.

        Args:
            hgm_path: Path to the HGM shapefile/parquet.
            crs: CRS to reproject the data.

        """
        # Read the HGM data
        self.hgm = load_geospatial_gdf(hgm_path, crs)

    def _load_reaches(self, reaches_path: PathLike, crs: str) -> None:
        """
        Load the river reaches.

        Args:
            reaches_path: Path to the river reaches shapefile/parquet.
            crs: CRS to reproject the data.

        """
        # Read the reaches
        self.reaches = load_geospatial_gdf(reaches_path, crs)

        # Create a linewidth for the rivers, through the log of areamont
        nuareamont = self.reaches[self.cols.upstream_area].astype(float)
        self.reaches["nuareamont_log"] = np.log10(nuareamont + 1)
        max_val: float = float(nuareamont.max()) if not nuareamont.empty else 1.0
        self.reaches["linewidth"] = (2 * nuareamont / max_val).astype(float)

        # cast cobacia and cocursodag as string
        self.reaches[self.cols.otto_code] = self.reaches[self.cols.otto_code].astype(str)
        self.reaches[self.cols.river_code] = self.reaches[self.cols.river_code].astype(str)

    def _load_watersheds(self, watersheds_path: PathLike, crs: str) -> None:
        """
        Load the watersheds.

        Args:
            watersheds_path: Path to the watershed shapefile/parquet.
            crs: CRS to reproject the data.

        """
        # Read the watersheds
        self.watersheds = load_geospatial_gdf(watersheds_path, crs)

        # cast cobacia and cocursodag as string
        self.watersheds[self.cols.otto_code] = self.watersheds[self.cols.otto_code].astype(str)

    def _load_reservoirs(self, reservoirs_path: PathLike, crs: str) -> None:
        """
        Load the reservoir polygons.

        Args:
            reservoirs_path: Path to the reservoir polygons file (parquet or shapefile).
            crs: CRS to reproject the data.

        """
        self.reservoirs = load_geospatial_gdf(reservoirs_path, crs)

    # ---------- Plotting Functions ----------
    def plot_reaches(self, ax: plt.Axes, pos: PositionType, zorder: int = 0) -> None:
        """
        Plot the reaches based on the selected position.

        Args:
            ax: Matplotlib axes to plot on.
            pos: Position type for reaches to plot.
            zorder: Drawing order. Default is 0.

        """
        # if pos is "all", plot all reaches, but limit ax to current viewport extents
        if pos == "all":
            reaches = self.reaches

            # Filter reaches within the ax limits
            xmin, xmax, ymin, ymax = ax.axis()
            reaches = reaches.cx[xmin:xmax, ymin:ymax]

        else:
            subset_key = f"{pos}_reaches"

            if subset_key not in self.selected:
                msg = f"No {pos} reaches selected. Run `select_reaches` first."
                raise ValueError(msg)

            reaches = self.selected[subset_key]

        # Skip if there are no reaches to plot
        if len(reaches) == 0:
            return

        color = Hydrography.REACHES_COLORS[pos]["color"]
        width_factor = Hydrography.REACHES_COLORS[pos]["width_factor"]

        # Set the linewidth based on the width factor
        linewidth = width_factor * reaches["nuareamont_log"] / 5
        reaches.plot(ax=ax, color=color, linewidth=linewidth, zorder=zorder)

    def plot_watersheds(
        self,
        ax: plt.Axes,
        color: str = "Blue",
        alpha: float = 0.2,
        zorder: int = 0,
    ) -> None:
        """
        Plot the watersheds.

        Args:
            ax: The matplotlib axes to plot on.
            color: The color of the watersheds. Default is 'Blue'.
            alpha: The transparency of the watersheds. Default is 0.2.
            zorder: The drawing order of the watersheds. Default is 0.

        """
        subset_key = "upstream_watersheds"

        if subset_key not in self.selected:
            msg = "No upstream watersheds selected. Run `select_reaches` first."
            raise ValueError(msg)

        watersheds = self.selected[subset_key]

        # Skip if there are no watersheds to plot
        if len(watersheds) == 0:
            return

        watersheds.plot(ax=ax, facecolor=color, alpha=alpha, zorder=zorder)

    def plot_selected(self, ax: plt.Axes, zorder: int = 0) -> None:
        """
        Plot the selected reaches and watersheds on the given axes.

        Args:
            ax: The matplotlib axes to plot on.
            zorder: The drawing order of the plotted features. Default is 0.

        """
        # Plot touching reaches
        self.plot_reaches(ax, pos="touching", zorder=zorder)

        # Plot upstream reaches
        self.plot_reaches(ax, pos="upstream", zorder=zorder)

        # Plot downstream reaches
        self.plot_reaches(ax, pos="downstream", zorder=zorder)

        # Plot upstream watersheds
        self.plot_watersheds(ax, zorder=zorder - 1)

    def plot_reservoirs(self, ax: plt.Axes) -> None:
        """
        Plot reservoir polygons colored by DSOPERA type.

        Uses fixed colors from RESERVOIRS_CONFIG so category colors are consistent
        regardless of which DSOPERA values appear in the current viewport. Adds a
        legend to the upper-left corner without overwriting any previously created
        legend artists.

        Args:
            ax: Matplotlib axes to plot on.

        """
        if self.reservoirs is None:
            return

        # Clip to current viewport
        xmin, xmax, ymin, ymax = ax.axis()
        res = self.reservoirs.cx[xmin:xmax, ymin:ymax]

        if res.empty:
            return

        colors = res["DSOPERA"].map(Hydrography.RESERVOIRS_CONFIG["colors"]).fillna("grey")
        res.plot(
            color=colors,
            edgecolor=Hydrography.RESERVOIRS_CONFIG["edgecolor"],
            alpha=Hydrography.RESERVOIRS_CONFIG["alpha"],
            ax=ax,
        )

        # Build deduplicated legend handles (Regulariza and Regulariza_ONS share one entry)
        present_dsopera = res["DSOPERA"].unique()
        seen_labels: dict[str, str] = {}
        for dsopera in Hydrography.RESERVOIRS_CONFIG["labels"]:
            if dsopera not in present_dsopera:
                continue
            label = Hydrography.RESERVOIRS_CONFIG["labels"][dsopera]
            color = Hydrography.RESERVOIRS_CONFIG["colors"][dsopera]
            if label not in seen_labels:
                seen_labels[label] = color

        patches = [
            mpatches.Patch(facecolor=color, edgecolor="darkgrey", label=label)
            for label, color in seen_labels.items()
        ]

        # Use Legend constructor directly so the active axis legend is not replaced
        reservoir_legend = Legend(
            ax,
            patches,
            [p.get_label() for p in patches],
            title="Reservatórios",
            loc="upper left",
            frameon=True,
        )
        ax.add_artist(reservoir_legend)

    # ---------- Other Methods ----------
    def get_river_code(self, otto_code: str) -> str:
        """
        Get the river code for a given Otto code.

        Args:
            otto_code: The Otto code to look up.

        Returns:
            The river code associated with the Otto code.

        """
        if self.reaches is None or self.cols.river_code not in self.reaches.columns:
            msg = "Reaches data not loaded or missing river_code column."
            raise ValueError(msg)

        # Get the row with the matching Otto code
        row = self.reaches[self.reaches[self.cols.otto_code] == otto_code]

        if row.empty:
            msg = f"Otto code {otto_code} not found in reaches data."
            raise ValueError(msg)

        return row[self.cols.river_code].iloc[0]

    # ---------- Select Functions ----------
    def get_touching(
        self,
        scope: ScopeType,
        obj: gpd.GeoDataFrame,
        buffer: float,
        auto_increase: bool = True,
    ) -> gpd.GeoDataFrame:
        """
        Get the reaches or watersheds that touch the object.

        Args:
            scope: Either 'watersheds' or 'reaches'.
            obj: Object to get the touching reaches.
            buffer: Buffer to apply to the object (in degrees).
            auto_increase: Increase the buffer until there is a reach. Default is True.

        Returns:
            Reaches or watersheds that touch the object.

        """
        # Select the correct GeoDataFrame based on scope
        if scope not in ScopeType.__args__:
            msg = f"Invalid scope: {scope}. Must be {ScopeType.__args__}."
            raise ValueError(msg)

        # Check if scope is 'hgm'
        if scope == "hgm":
            if self.hgm is None:
                msg = "HGM data not loaded. Provide a valid HGM path."
                raise ValueError(msg)
            gdf = self.hgm
        # Otherwise, use the reaches or watersheds
        else:
            # Use the appropriate GeoDataFrame based on scope
            gdf = self.watersheds if scope == "watersheds" else self.reaches

        return Otto.get_touching(gdf, obj, buffer, auto_increase)

    def get_upstream(
        self,
        scope: ScopeType,
        reaches: gpd.GeoDataFrame,
        max_distance: float | None = None,
    ) -> gpd.GeoDataFrame:
        """
        Get the upstream reaches or watersheds of the object.

        Args:
            scope: Either 'watersheds' or 'reaches'.
            reaches: Reaches to get the upstream reaches for.
            max_distance: Maximum distance for clipping (in km). Default is None.

        Returns:
            Upstream reaches or watersheds.

        """
        gdf = self.watersheds if scope == "watersheds" else self.reaches
        upstream = Otto.get_combined_upstream(gdf, reaches, col_map=self.cols)

        if max_distance is not None and len(upstream) > 0:
            upstream = self.apply_max_distance(reaches, upstream, max_distance)

        return upstream

    def get_downstream(
        self,
        scope: ScopeType,
        reaches: gpd.GeoDataFrame,
        max_distance: float | None = None,
    ) -> gpd.GeoDataFrame:
        """
        Get the downstream reaches or watersheds of the object.

        Args:
            scope: Either 'watersheds' or 'reaches'.
            reaches: Reaches to get the downstream reaches for.
            max_distance: Maximum distance for clipping. Default is None.

        Returns:
            Downstream reaches or watersheds.

        """
        gdf = self.watersheds if scope == "watersheds" else self.reaches
        downstream = Otto.get_combined_downstream(
            gdf,
            reaches,
            col_map=self.cols,
            max_lenght=max_distance,
        )

        return downstream

    def apply_max_distance(
        self,
        aoi: gpd.GeoDataFrame,
        features: gpd.GeoDataFrame,
        max_distance: float,
    ) -> gpd.GeoDataFrame:
        """
        Cut the features in a given distance from aoi.

        Args:
            aoi: Area of interest GeoDataFrame.
            features: Features to clip.
            max_distance: Maximum distance for clipping.

        Returns:
            Clipped features within maximum distance.

        """
        distance = float(max_distance / 111)

        buffer = aoi.geometry.buffer(distance)
        features = gpd.clip(
            features.drop_duplicates(),
            buffer,
        ).copy()

        return features

    def select_reaches(
        self,
        boundary: gpd.GeoDataFrame,
        buffer: float = 1e-2,
        auto_increase: bool = True,
        max_downstream_distance: float | None = None,
        max_upstream_distance: float | None = None,
    ) -> None:
        """
        Select reaches and watersheds upstream and downstream of a boundary.

        This method identifies river reaches that touch the provided boundary,
        then calculates upstream and downstream reaches and watersheds.
        The selected data is stored internally in the class and can be accessed
        via the selected_data attribute.

        In addition to reaches and watersheds, we will also select the reaches in the
        hydromorphology (HGM) database that are touching the boundary.
        This allows us to analyze the hydromorphology of the selected reaches.
        Note that the selected HGM reach is the downstream-most reach.

        Args:
            boundary: Any GeoDataFrame containing a boundary (urban area, municipality, etc.)
            buffer: Buffer around the boundary to identify touching reaches (in degrees)
            auto_increase: Whether to increase the buffer until reaches are found
            max_downstream_distance: Maximum distance for downstream reaches (in km)
            max_upstream_distance: Maximum distance for upstream reaches (in km). Default is None.

        """
        dt = datetime.now()  # noqa: DTZ005
        logger.info("Starting to select touching reaches: %s", dt)

        # Clear current selected data
        self.selected = {}

        # Get reaches touching the boundary
        self.selected["touching_reaches"] = self.get_touching(
            scope="reaches",
            obj=boundary,
            buffer=buffer,
            auto_increase=auto_increase,
        )

        # Get the downsream-most reach in the HGM database
        now = datetime.now()  # noqa: DTZ005
        logger.info("Select downstream-most reach in HGM database: %s (%s)", now, now - dt)
        if self.hgm is not None:
            reaches = self.get_touching(
                scope="hgm",
                obj=boundary,
                buffer=buffer,
                auto_increase=auto_increase,
            )
            if not reaches.empty:
                # Get the downstream-most reach
                reaches = reaches.sort_values(
                    by=self.cols.upstream_area,
                    ascending=False,
                )
                self.selected["hgm_reach"] = reaches.iloc[0:1]

        # Get upstream reaches and watersheds
        dt = now
        now = datetime.now()  # noqa: DTZ005
        logger.info("Select upstream watersheds: %s (%s)", now, now - dt)
        self.selected["upstream_watersheds"] = self.get_upstream(
            scope="watersheds",
            reaches=self.selected["touching_reaches"],
            max_distance=max_upstream_distance,
        )

        dt = now
        now = datetime.now()  # noqa: DTZ005
        logger.info("Select upstream reaches: %s (%s)", now, now - dt)
        self.selected["upstream_reaches"] = self.get_upstream(
            scope="reaches",
            reaches=self.selected["touching_reaches"],
            max_distance=max_upstream_distance,
        )

        # Get downstream reaches
        dt = now
        now = datetime.now()  # noqa: DTZ005
        logger.info("Select downstream reaches: %s (%s)", now, now - dt)
        self.selected["downstream_reaches"] = self.get_downstream(
            scope="reaches",
            reaches=self.selected["touching_reaches"],
            max_distance=max_downstream_distance,
        )

    # ---------- Getters ----------
    def get_hgm_info(self) -> pd.DataFrame | None:
        """
        Get information about the HGM reach.

        If HGM data is not loaded, returns an empty dictionary.

        Args:
            as_html: If True, return HTML formatted string. Default is False.

        Returns:
            Dictionary with HGM reach information or HTML string if as_html is True.

        """
        # Get the HGM reach from selected data
        hgm_reach = self.selected.get("hgm_reach", None)
        if hgm_reach is None or hgm_reach.empty:
            return None

        # Get only the configured columns
        hgm_reach = hgm_reach[list(HGM_COLUMNS)]

        # Rename columns to match the HydrographyColumns mapping
        hgm_reach = hgm_reach.rename(columns=HGM_LABELS)

        return hgm_reach

    def __repr__(self) -> str:
        """
        Return a string representation of the Hydrography object.

        Returns:
            String representation of the Hydrography object.

        """
        s = "Hydrography class with the following files loaded:\n"
        s += str(self.watersheds_path) + "\n"
        s += str(self.reaches_path)
        return s
