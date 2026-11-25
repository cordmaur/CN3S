"""Delineate a station basin from BHO drainage polygons."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import geopandas as gpd
import pandas as pd

from .columns import HydrographyColumns
from .otto import Otto

if TYPE_CHECKING:
    from pathlib import Path


def delineate_watershed(
    path: str | Path, latitude: float, longitude: float
) -> tuple[str, float, gpd.GeoDataFrame]:
    """
    Find the outlet polygon and dissolve its upstream BHO drainage areas.

    Args:
        path: BHO 2017 drainage-area GeoParquet.
        latitude: Hidro inventory latitude in decimal degrees (EPSG:4326).
        longitude: Hidro inventory longitude in decimal degrees (EPSG:4326).

    Returns:
        Outlet cobacia, sum of local contribution areas in km², and a one-row
        basin GeoDataFrame in the input CRS with its BHO version.

    """
    cols = HydrographyColumns()
    areas = gpd.read_parquet(
        path, columns=["cobacia", "cocursodag", "dsversao", "nuareacont", "geometry"]
    )
    if areas.crs is None:
        msg = "O GeoParquet de áreas de drenagem precisa declarar o CRS."
        raise ValueError(msg)
    point = gpd.GeoSeries(gpd.points_from_xy([longitude], [latitude]), crs=4326).to_crs(areas.crs)
    # A point can touch a polygon edge; accept it only if the outlet is unambiguous.
    hits = areas.sindex.query(point.iloc[0], predicate="within")
    if not hits.size:
        hits = areas.sindex.query(point.iloc[0], predicate="intersects")
    if hits.size != 1:
        msg = f"As coordenadas da estação correspondem a {hits.size} polígonos de drenagem."
        raise ValueError(msg)

    outlet = areas.iloc[hits[0]]
    code = str(outlet["cobacia"])
    if pd.isna(outlet["cocursodag"]):
        # In BHO 2017 50k, polygons without a watercourse drain only their local area.
        upstream = areas.iloc[hits]
    else:
        upstream = Otto.get_upstream(
            areas, code, str(outlet["cocursodag"]), cols, version=outlet["dsversao"]
        )
    local_areas = upstream["nuareacont"]
    if upstream.empty or local_areas.isna().any() or (local_areas <= 0).any():
        msg = f"Áreas de contribuição inválidas na bacia {code}."
        raise ValueError(msg)
    basin = cast("gpd.GeoDataFrame", upstream[["geometry"]].dissolve())
    basin["dsversao"] = outlet["dsversao"]
    return code, float(local_areas.sum()), basin
