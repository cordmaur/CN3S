"""Cached CDS rainfall downloads for historical CN3S forecast comparisons."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import earthkit.data as ekd
import pandas as pd
import rioxarray  # noqa: F401 -- register the spatial xarray accessor
import xarray as xr

if TYPE_CHECKING:
    from pathlib import Path


def download_issue_forecasts(
    folder: Path,
    initialization: pd.Timestamp,
    systems: dict[str, str],
    *,
    leads: list[int],
    area: list[float],
    download_missing: bool = True,
) -> pd.DataFrame:
    """
    Download one issue's ensemble precipitation and matching hindcast means.

    Args:
        folder: Issue-specific cache with prec/ and hindcast/ subfolders.
        initialization: Nominal CDS initialization month, labeled at month start.
        systems: CDS originating centre to its archived system identifier.
        leads: CDS monthly leads; lead 1 is the initialization month itself.
        area: Geographic bounding box [north, west, south, east] in EPSG:4326 degrees.
        download_missing: Retrieve missing or mismatched cache entries when True;
            otherwise require a complete cache matching the requested parameters.

    Returns:
        Manifest of centre, system, product, cache path and whether it was reused.
        Files follow load_forecast_grids naming and contain 30-day-equivalent
        precipitation in mm, as in notebook 03. This scale cancels in the
        forecast/hindcast ratio; corrected totals use observed calendar-month mm.
        Existing files are reused only when their complete CDS request matches.
        Requires configured CDS credentials and dataset terms already accepted.

    """
    rows = []
    for centre, system in systems.items():
        for product, product_type in (
            ("prec", "ensemble_mean"),
            ("hindcast", "hindcast_climate_mean"),
        ):
            request = {
                "originating_centre": centre,
                "system": system,
                "variable": "total_precipitation",
                "product_type": product_type,
                "year": [str(initialization.year)],
                "month": [f"{initialization.month:02d}"],
                "leadtime_month": [str(lead) for lead in leads],
                "area": area,
                "data_format": "grib",
            }
            signature = json.dumps(request, sort_keys=True)
            path = folder / product / f"{centre}_{initialization:%Y%m}.nc2"
            reused = False
            if path.exists():
                with xr.open_dataset(path) as cached:
                    reused = cached.attrs.get("cds_request") == signature
            if not reused:
                if not download_missing:
                    msg = f"Missing or mismatched CDS cache: {path}. Enable download_missing."
                    raise FileNotFoundError(msg)
                print(f"Downloading {initialization:%Y-%m}: {centre} system {system}, {product}")
                fields = ekd.from_source(
                    "cds",
                    "seasonal-monthly-single-levels",
                    request=request,
                )
                # Retain notebook 03's scale, with explicit corrected units in the cache.
                dataset = (fields.to_xarray() * (1000 * 30 * 24 * 60 * 60)).squeeze(drop=True)
                if dataset.sizes.get("step") != len(leads):
                    msg = f"Unexpected number of CDS monthly leads for {centre}: {dataset.sizes}"
                    raise ValueError(msg)
                dataset = dataset.rio.write_crs("EPSG:4326")
                dataset["tprate"].attrs = {"units": "mm / 30 days"}
                dataset.attrs["cds_request"] = signature
                path.parent.mkdir(parents=True, exist_ok=True)
                # Publish the cache only after a complete write, so interrupted runs can resume.
                temporary = path.with_suffix(".part.nc")
                dataset.to_netcdf(temporary, engine="netcdf4")
                temporary.replace(path)
            else:
                print(f"Cached {initialization:%Y-%m}: {centre} system {system}, {product}")
            rows.append(
                {
                    "centre": centre,
                    "system": system,
                    "product": product,
                    "path": str(path),
                    "reused": reused,
                },
            )
    return pd.DataFrame(rows)
