"""Implement the Otto class for ottocodification processing."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import geopandas as gpd
import pandas as pd

if TYPE_CHECKING:
    from .columns import HydrographyColumns


class Otto:
    """Provide general methods to work with the otto hydrography."""

    @staticmethod
    def get_upstream(
        reaches: gpd.GeoDataFrame,
        otto_code: str,
        river_code: str,
        col_map: HydrographyColumns,
        version: str | None = None,
    ) -> gpd.GeoDataFrame:
        """Get reaches upstream the specified basin code.

        Note that the reach with the corresponding otto_code is included.
        The DataFrame should have the basin code column for the upstream query to work.

        Args:
            reaches: Reaches GeoDataFrame.
            otto_code: Basin code value.
            river_code: River code value.
            col_map: mapping of column names.
            version: Optional version of the reaches to consider.

        Returns:
            GeoDataFrame with upstream reaches.

        """
        # first, filter the reaches by the correct base version
        # get the correct version for the otto code if it is not provided
        if version is None:
            version = Otto.guess_version(reaches, otto_code, col_map)

        reaches = reaches[reaches["dsversao"] == version]

        upstream = reaches[reaches["dsversao"] == version]
        upstream = reaches[reaches[col_map.otto_code].str.startswith(river_code)]
        upstream = upstream.query(f"{col_map.otto_code} >= '{otto_code}'")

        return upstream

    @staticmethod
    def guess_version(
        reaches: gpd.GeoDataFrame, otto_code: str, col_map: HydrographyColumns
    ) -> str:
        """Guess the version of the reaches based on the otto code.

        Args:
            reaches: Reaches GeoDataFrame. Should have basin code and version fields.
            otto_code: Basin code to find the version for.
            col_map: Mapping of column names.

        Returns:
            Version string.

        """
        versions = reaches[reaches[col_map.otto_code] == otto_code]["dsversao"].unique()
        if len(versions) == 0:
            msg = f"No version found for otto_code {otto_code}"
            raise ValueError(msg)

        if len(versions) > 1:
            msg = f"Multiple versions found for otto_code {otto_code}: {versions}"
            raise ValueError(msg)

        return versions[0]

    @staticmethod
    def get_downstream(
        reaches: gpd.GeoDataFrame,
        otto_code: str,
        col_map: HydrographyColumns,
        max_lenght: float | None = None,
        version: str | None = None,
    ) -> gpd.GeoDataFrame:
        """Get features downstream of the given basin code.

        Args:
            reaches: Reaches GeoDataFrame. Should have basin code, source node,
                target node, and downstream code fields.
            otto_code: Reach code to start the downstream walk.
            col_map: Optional mapping of column names.
            max_lenght: Maximum accumulated reach length to consider.
            version: Optional version of the reaches to consider.

        Returns:
            GeoDataFrame with downstream features selected.

        """
        # Before doing anything, filter the reaches by the correct base version.
        if version is None:
            version = Otto.guess_version(reaches, otto_code, col_map)

        reaches = reaches[reaches["dsversao"] == version]

        row = downstream = reaches.query(f"{col_map.otto_code} == '{otto_code}'")

        # Track the total lenght
        while not row.empty and not pd.isna(row[col_map.downstream_code].iloc[0]):
            downstream = pd.concat([downstream, row], axis=0)  # type: ignore[assignment]
            row = reaches.query(f"{col_map.source_node} == {row[col_map.target_node].iloc[0]}")

            if max_lenght and downstream[col_map.reach_length].sum() > max_lenght:
                break

        return cast("gpd.GeoDataFrame", downstream.drop_duplicates())

    @staticmethod
    def get_combined_upstream(
        reaches: gpd.GeoDataFrame,
        to_search: gpd.GeoDataFrame,
        col_map: HydrographyColumns,
    ) -> gpd.GeoDataFrame:
        """Select upstream reaches for all reaches listed in to_search.

        The to_search DataFrame should have river code and basin code columns.

        Args:
            reaches: Reaches GeoDataFrame.
            to_search: DataFrame with columns for river code and basin code.
            col_map: Optional mapping of column names.

        Returns:
            GeoDataFrame with all upstream reaches.

        """
        search_df = to_search.sort_values([col_map.river_code, col_map.otto_code]).copy()
        upstream = gpd.GeoDataFrame(columns=reaches.columns, crs=reaches.crs)

        while len(search_df) > 0:
            row = search_df.iloc[0]
            search_df = search_df.drop(index=row.name)
            ups = Otto.get_upstream(
                reaches,
                row[col_map.otto_code],
                row[col_map.river_code],
                col_map,
                row.get("dsversao", None),
            )

            upstream = pd.concat([upstream, ups])  # type: ignore[assignment]

            search_df = search_df[~search_df[col_map.otto_code].isin(upstream[col_map.otto_code])]

        return cast("gpd.GeoDataFrame", upstream)

    @staticmethod
    def get_combined_downstream(
        reaches: gpd.GeoDataFrame,
        to_search: gpd.GeoDataFrame,
        col_map: HydrographyColumns,
        max_lenght: float | None = None,
    ) -> gpd.GeoDataFrame:
        """Select downstream reaches for all reaches listed in to_search.

        The to_search DataFrame should have the basin code column.
        Processes starts from the most-upstream reach and prunes already-visited
        codes after each step to avoid redundant walks.

        Args:
            reaches: Reaches GeoDataFrame.
            to_search: DataFrame with basin code column identifying starting reaches.
            col_map: Mapping of column names.
            max_lenght: Maximum accumulated reach length to consider.

        Returns:
            GeoDataFrame with all downstream reaches.

        """
        search_df = to_search.sort_values(
            [col_map.river_code, col_map.otto_code], ascending=False
        ).copy()
        downstream = gpd.GeoDataFrame(columns=reaches.columns, crs=reaches.crs)

        while len(search_df) > 0:
            row = search_df.iloc[0]
            search_df = search_df.drop(index=row.name)

            downs = Otto.get_downstream(
                reaches,
                row[col_map.otto_code],
                col_map,
                max_lenght=max_lenght,
                version=row.get("dsversao", None),
            )

            downstream = pd.concat([downstream, downs])  # type: ignore[assignment]

            search_df = search_df[
                ~search_df[col_map.otto_code].isin(downstream[col_map.otto_code])
            ]

        return cast("gpd.GeoDataFrame", downstream.drop_duplicates())

    @staticmethod
    def get_touching(
        gdf: gpd.GeoDataFrame,
        obj: gpd.GeoDataFrame,
        buffer: float = 1e-3,
        auto_increase: bool = False,
    ) -> gpd.GeoDataFrame:
        """Return features in gdf that touch obj, considering a buffer.

        The procedure calculates the convex hull and applies the buffer.
        If auto_increase is True, the buffer increases until a touch is found.

        Args:
            gdf: GeoDataFrame with features to filter.
            obj: Object to be intersected.
            buffer: Buffer in degrees. 1 deg ≈ 111 km. Defaults to 1e-3 (≈100 m).
            auto_increase: Automatically increase buffer size to force a touch.

        Returns:
            GeoDataFrame with features that touch obj.

        """
        hull = obj.dissolve().convex_hull
        mult = 1.0
        features = gpd.GeoDataFrame(columns=gdf.columns, crs=gdf.crs)

        while len(features) == 0:
            buffered_hull = gpd.GeoDataFrame(geometry=hull.buffer(buffer * mult), crs=gdf.crs)
            features = gdf.sjoin(buffered_hull, how="left", predicate="intersects")
            features = features[~pd.isna(features["index_right"])]
            mult = mult * 2
            if not auto_increase:
                break

        return features
