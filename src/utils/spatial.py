"""Spatial utility functions for geospatial data processing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import box

if TYPE_CHECKING:
    import matplotlib.pyplot as plt

    from utils.core import PathLike

DEFAULT_SAMPLE_ROWS = 5


def calc_aspects_lims(
    shp: gpd.GeoDataFrame,
    aspect: float = 1.0,
    percent_buffer: float = 0,
    fixed_buffer: float = 0.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Calculate viewport limits for a GeoDataFrame with optional buffer and aspect ratio.

    Args:
        shp: GeoDataFrame to calculate viewport limits for.
        aspect: Aspect ratio as lim_x/lim_y.
        percent_buffer: Buffer around bounds as percentage.
        fixed_buffer: Buffer around bounds in CRS units.

    Returns:
        Tuple containing x limits (xmin, xmax) and y limits (ymin, ymax).

    """
    # first, let's get the bounding box
    xmin, ymin, xmax, ymax = calc_bounds(
        shp=shp,
        percent_buffer=percent_buffer,
        fixed_buffer=fixed_buffer,
    )

    # calc the sizes in each dimension
    size_x = xmax - xmin
    size_y = ymax - ymin

    actual_aspect = size_x / size_y

    # if actual aspect is smaller, that means width has to be increased
    if actual_aspect < aspect:
        # we have to increase X accordingly
        delta = size_y * aspect - size_x
        xmin -= delta / 2
        xmax += delta / 2

    # if actual aspect is greater, that means height has to be increased
    else:
        # we have to increase Y axis accordingly
        delta = size_x / aspect - size_y
        ymin -= delta / 2
        ymax += delta / 2

    # return the limits
    return (xmin, xmax), (ymin, ymax)


def calc_bounds(
    shp: gpd.GeoDataFrame,
    percent_buffer: float = 0,
    fixed_buffer: float = 0.0,
) -> tuple[float, float, float, float]:
    """Return the total bounds of a GeoDataFrame with optional buffer.

    Args:
        shp: GeoDataFrame to calculate bounds for.
        percent_buffer: Buffer as percentage of maximum size.
        fixed_buffer: Buffer as fixed distance in projection units.

    Returns:
        Tuple containing (xmin, ymin, xmax, ymax) bounds.

    """
    # get the bounding box of the total shape
    bbox = box(*shp.total_bounds)

    if fixed_buffer != 0:
        bbox = bbox.buffer(fixed_buffer)
    elif percent_buffer != 0:
        xmin, ymin, xmax, ymax = bbox.bounds
        delta_x = xmax - xmin
        delta_y = ymax - ymin
        diag = (delta_x**2 + delta_y**2) ** 0.5
        bbox = bbox.buffer(percent_buffer * diag)

    return bbox.bounds


def load_geospatial_gdf(path: PathLike, crs: str) -> gpd.GeoDataFrame:
    """Load a geospatial file as a GeoDataFrame and reproject to the given CRS.

    Args:
        path: Path to the geospatial file (parquet or shapefile).
        crs: Coordinate reference system to use.

    Returns:
        GeoDataFrame with the specified CRS.

    """
    path_path: Path = Path(path)
    gdf = (
        gpd.read_parquet(path_path)
        if path_path.suffix == ".parquet"
        else gpd.read_file(path_path, engine="pyogrio", use_arrow=True)
    )
    gdf = gdf.set_crs(crs) if gdf.crs is None else gdf.to_crs(crs)
    return gdf


def read_geoparquet_sample(
    path: PathLike,
    n_rows: int = DEFAULT_SAMPLE_ROWS,
) -> gpd.GeoDataFrame:
    """Read the first rows of a GeoParquet file without loading the whole file.

    Args:
        path: Path to the GeoParquet file.
        n_rows: Maximum number of top rows to read.

    Returns:
        GeoDataFrame containing the sampled rows and preserved GeoParquet metadata.

    """
    path_path = Path(path)
    parquet_file = pq.ParquetFile(path_path)
    try:
        batch = next(parquet_file.iter_batches(batch_size=n_rows))
        table = pa.Table.from_batches([batch], schema=batch.schema)
    except StopIteration:
        table = pa.Table.from_batches([], schema=parquet_file.schema_arrow)

    frame = table.to_pandas()
    metadata = parquet_file.metadata.metadata or {}
    geo_metadata_bytes = metadata.get(b"geo")
    if geo_metadata_bytes is None:
        msg = f"{path_path} does not contain GeoParquet metadata."
        raise ValueError(msg)

    geo_metadata = json.loads(geo_metadata_bytes)
    geometry_col = geo_metadata["primary_column"]
    geometry_config = geo_metadata["columns"][geometry_col]
    if geometry_config.get("encoding") != "WKB":
        msg = f"{path_path} uses unsupported geometry encoding: {geometry_config.get('encoding')}"
        raise ValueError(msg)

    frame[geometry_col] = shapely.from_wkb(frame[geometry_col].to_numpy())
    return gpd.GeoDataFrame(
        frame,
        geometry=geometry_col,
        crs=geometry_config.get("crs"),
    )


def write_geoparquet_sample(
    source_path: PathLike,
    output_path: PathLike,
    n_rows: int = DEFAULT_SAMPLE_ROWS,
) -> None:
    """Write a small GeoParquet sample from the top rows of a source file.

    Args:
        source_path: Path to the source GeoParquet file.
        output_path: Path where the sampled GeoParquet file should be written.
        n_rows: Maximum number of top rows to write.

    """
    output_path_path = Path(output_path)
    output_path_path.parent.mkdir(parents=True, exist_ok=True)
    read_geoparquet_sample(source_path, n_rows=n_rows).to_parquet(output_path_path)


def set_aspect_ratio(
    aspect: float,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> tuple[float, float, float, float]:
    """Define new extents to guarantee the aspect ratio.

    Args:
        aspect: Desired aspect ratio (width/height).
        xmin: Minimum x value.
        ymin: Minimum y value.
        xmax: Maximum x value.
        ymax: Maximum y value.

    Returns:
        Tuple of new (xmin, ymin, xmax, ymax) with the specified aspect ratio.

    """
    cx_, cy_ = (xmin + xmax) / 2, (ymin + ymax) / 2
    width, height = (xmax - xmin), (ymax - ymin)
    if width / height >= aspect:
        height = width / aspect
    else:
        width = height * aspect
    return (
        cx_ - width / 2,
        cy_ - height / 2,
        cx_ + width / 2,
        cy_ + height / 2,
    )


def resize_axes(ax: plt.Axes, aspect: float | None) -> tuple[float, float, float, float]:
    """Resize the given axes to a specific aspect ratio.

    Args:
        ax: Matplotlib Axes object.
        aspect: Desired aspect ratio.

    Returns:
        Tuple of new (xmin, ymin, xmax, ymax) bounds.

    """
    if aspect is None:
        width, height = ax.figure.get_size_inches()
        final_aspect = width / height
    else:
        final_aspect = aspect

    xmin, xmax, ymin, ymax = ax.axis()
    bounds = set_aspect_ratio(final_aspect, xmin, ymin, xmax, ymax)
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    return bounds


def update_area(gdf: gpd.GeoDataFrame) -> None:
    """Create the 'area_km2' column in the dataframe.

    Args:
        gdf: GeoDataFrame to update.

    """
    # Project to equal-area CRS and calculate area in km2
    gdf_equal_area = gdf.to_crs("ESRI:54034")
    gdf["area_km2"] = gdf_equal_area.geometry.area / 1e6
