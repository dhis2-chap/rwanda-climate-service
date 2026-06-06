"""Lapse-rate elevation correction for gridded temperature data."""

from __future__ import annotations

import xarray as xr

from open_climate_service.process import process

# Standard environmental lapse rate: 6.5 K per 1000 m
_LAPSE_RATE_K_PER_M = 6.5e-3


@process(
    summary="Correct temperature for elevation using the environmental lapse rate",
    description=(
        "Bilinearly interpolates coarse temperature to the elevation grid, then "
        "applies the standard environmental lapse rate (6.5 K km⁻¹) to correct "
        "for the difference between the pixel's actual elevation and the coarse "
        "grid's reference elevation.  Pass a fine-resolution DEM to downscale "
        "temperature; pass the same-resolution DEM for a plain elevation correction.\n\n"
        "Formula: T_out = T_interp − lapse_rate × (elev − elev_coarse)\n"
        "where elev_coarse is the DEM resampled to the temperature grid."
    ),
)
def lapse_rate_downscale(
    temperature: xr.DataArray,
    elevation: xr.DataArray,
    lapse_rate: float = _LAPSE_RATE_K_PER_M,
) -> xr.DataArray:
    """Apply lapse-rate elevation correction to temperature.

    Parameters
    ----------
    temperature:
        Air temperature in °C, at any grid resolution (typically CHELSA ~1 km).
    elevation:
        Terrain elevation in metres.  The output grid matches the elevation grid.
        Use a coarser DEM for a plain elevation correction or a finer DEM to
        downscale temperature to a higher resolution.
    lapse_rate:
        Environmental lapse rate in K m⁻¹ (default 0.0065, i.e. 6.5 K km⁻¹).

    Returns
    -------
    xr.DataArray
        Temperature in °C on the elevation grid, corrected for actual elevation.
    """
    import numpy as _np
    # Squeeze time-dim from static elevation so interp sees only (y, x)
    elev_2d = elevation
    for dim in list(elev_2d.dims):
        if dim not in ("y", "x") and elev_2d.sizes[dim] == 1:
            elev_2d = elev_2d.isel({dim: 0}, drop=True)

    elev_y = elev_2d.y.values   # target fine-grid y coords
    elev_x = elev_2d.x.values   # target fine-grid x coords

    # Coarse temperature grid coords (for reference elevation)
    temp_1d = temperature.isel(t=0, drop=True) if "t" in temperature.dims else temperature
    temp_y = temp_1d.y.values
    temp_x = temp_1d.x.values

    # All numpy from here to avoid xarray's grid-alignment join on y/x, which
    # would intersect elevation coords with temperature coords and yield 0 points.

    # 1. Reference elevation: fine DEM → coarse temperature grid → back to fine grid.
    #    This is what CHELSA "assumed" about the terrain at each CHELSA pixel,
    #    then upsampled to the full-resolution output.
    elev_fine_np = elev_2d.values.astype("float32")       # (ny_fine, nx_fine)
    elev_coarse_tmp = elev_2d.interp(y=temp_y, x=temp_x, method="linear")  # (ny_coarse, nx_coarse)
    elev_coarse_fine = elev_coarse_tmp.interp(y=elev_y, x=elev_x, method="linear")  # back to fine
    elev_coarse_np = elev_coarse_fine.values.astype("float32")  # (ny_fine, nx_fine)

    # Elevation anomaly (fine − coarse): positive where actual terrain > CHELSA reference
    delta_elev = elev_fine_np - elev_coarse_np   # (ny_fine, nx_fine)

    # 2. Interpolate temperature to the fine grid, slice-by-slice.
    if "t" in temperature.dims:
        n_t = temperature.sizes["t"]
        temp_fine_np = _np.full((n_t, len(elev_y), len(elev_x)), _np.nan, dtype="float32")
        for i in range(n_t):
            sl = temperature.isel(t=i, drop=True).interp(y=elev_y, x=elev_x, method="linear")
            temp_fine_np[i] = sl.values.astype("float32")

        # 3. Lapse-rate correction (all numpy; delta_elev broadcast over t)
        corrected_np = (temp_fine_np - lapse_rate * delta_elev[_np.newaxis]).astype("float32")
        corrected = xr.DataArray(
            corrected_np,
            dims=["t", "y", "x"],
            coords={"t": temperature.t.values, "y": elev_y, "x": elev_x},
            attrs=dict(temperature.attrs),
        )
    else:
        temp_fine_np = temperature.interp(y=elev_y, x=elev_x, method="linear").values.astype("float32")
        corrected_np = (temp_fine_np - lapse_rate * delta_elev).astype("float32")
        corrected = xr.DataArray(
            corrected_np,
            dims=["y", "x"],
            coords={"y": elev_y, "x": elev_x},
            attrs=dict(temperature.attrs),
        )

    corrected.attrs["long_name"] = corrected.attrs.get("long_name", "temperature") + " (lapse-rate corrected)"
    corrected.attrs["lapse_rate_K_per_m"] = lapse_rate
    return corrected
