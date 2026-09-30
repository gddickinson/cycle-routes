"""Cycle Routes: automatically generated, rated cycling routes from open data.

Subpackages: data (download/enrich), scoring, routing, tracking (GPS), community,
export, services, api, devtools. See INTERFACE.md for the full map.
"""

import os as _os
from pathlib import Path as _Path


def _use_bundled_geo_data() -> None:
    """Point GDAL/PROJ at the data shipped with rasterio.

    A conda environment active in the shell (e.g. GDAL_DATA/PROJ_DATA from another
    install) would otherwise make rasterio load an incompatible proj.db.
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec("rasterio")
        if spec is None or spec.origin is None:
            return
        base = _Path(spec.origin).parent
        for var, sub in (("PROJ_DATA", "proj_data"), ("PROJ_LIB", "proj_data"), ("GDAL_DATA", "gdal_data")):
            if (base / sub).is_dir():
                _os.environ[var] = str(base / sub)
        _os.environ.pop("GDAL_DRIVER_PATH", None)
    except Exception:  # never block import over this
        pass


_use_bundled_geo_data()
