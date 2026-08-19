"""Utils module."""

import json
from pathlib import Path
from typing import Literal, TypedDict, cast

import geopandas as gpd
import pandas as pd

BASE_FOLDER = "/data/CN3S/basins/"

FREQ = Literal["D", "M"]


class BasinData(TypedDict):
    """Dictionary with the contents of a basin folder."""

    station: str
    area: float
    prec: pd.DataFrame
    q: pd.DataFrame
    shp: gpd.GeoDataFrame


def load_data(basin: str, freq: FREQ) -> tuple[Path, BasinData]:
    """
    Open a Basin (by name) and return a dictionary with the data.

    Args:
        basin: Name of the basin.
        freq: Frequency of the data ("D" for daily, "M" for monthly).

    Returns:
        tuple[Path, BasinData]: Path to the basin folder and dictionary with the contents 
        of the folder.

    """
    # Check if the basin folder exists
    path = Path(BASE_FOLDER) / basin
    assert path.exists(), f"Path {path} does not exist"

    # Open the metadata file
    metadata_path = path / "metadata.json"
    with metadata_path.open("r") as f:
        metadata = json.load(f)

    station = metadata["station"]

    freq_str = "Daily" if freq == "D" else "Monthly"

    # Open precipitation
    metadata["prec"] = pd.read_parquet(path / f"{freq_str}_Prec_{station}.parquet")

    # Open discharge
    metadata["q"] = pd.read_parquet(path / f"{freq_str}_Q_{station}.parquet")

    # Open the catchment shapefile
    metadata["shp"] = gpd.read_parquet(path / f"DA_Station_{station}.parquet")

    return path, cast("BasinData", metadata)
