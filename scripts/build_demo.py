"""Build the default demo region with verbose logging (dev helper)."""
import logging

import osmnx as ox

from cycleroutes import config
from cycleroutes.data.region import build_region

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logging.getLogger("rasterio").setLevel(logging.WARNING)
ox.settings.log_console = True
build_region(**config.DEFAULT_REGION)
