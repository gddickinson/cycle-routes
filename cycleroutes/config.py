"""Central configuration: paths, defaults, data-source URLs and routing profiles.

Every tunable number the rest of the package uses lives here, so there is exactly
one place to change a default.
"""

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
WEB_DIR = PROJECT_ROOT / "web"

USER_AGENT = "CycleRoutes-prototype/0.1 (+https://github.com/gddickinson/cycle-routes)"

# Default demo region: central Austin, TX (the pyNav default map centre).
DEFAULT_REGION = {"name": "austin", "lat": 30.2900, "lon": -97.7400, "radius_m": 6000}

# --- Data sources -------------------------------------------------------------
# Overpass endpoints tried in order (public servers are often busy).
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
# Copernicus GLO-30 DEM, 1x1 degree Cloud-Optimised GeoTIFFs on AWS open data.
COPERNICUS_DEM_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM/"
    "Copernicus_DSM_COG_10_{ns}{lat:02d}_00_{ew}{lon:03d}_00_DEM.tif"
)

# OSM way tags kept on graph edges (beyond osmnx defaults).
EXTRA_WAY_TAGS = [
    "cycleway", "cycleway:left", "cycleway:right", "cycleway:both",
    "bicycle", "surface", "smoothness", "lit", "segregated",
    "bridge", "tunnel", "oneway:bicycle", "sidewalk",
]

# Features that make a ride pleasant (buffer distance in metres from the road).
SCENIC_TAGS = {
    "leisure": ["park", "nature_reserve", "garden", "golf_course"],
    "natural": ["water", "wood", "scrub", "grassland", "wetland"],
    "landuse": ["forest", "grass", "meadow", "recreation_ground"],
    "waterway": ["river", "stream", "canal"],
    "tourism": ["viewpoint"],
}
SCENIC_BUFFER_M = 40

# --- Scoring defaults ---------------------------------------------------------
# Assumed speed limits (km/h) when OSM has no maxspeed tag.
DEFAULT_SPEED_KMH = {
    "trunk": 90, "primary": 70, "secondary": 60, "tertiary": 50,
    "unclassified": 50, "residential": 40, "service": 25,
    "living_street": 15, "road": 50,
}
BASE_CYCLING_SPEED_KMH = 20.0
MAX_DOWNHILL_SPEED_KMH = 35.0
TRAFFIC_SIGNAL_DELAY_S = 15.0
# service=* values that make poor through routes: (speed km/h, routing cost multiplier)
AWKWARD_SERVICE = {"parking_aisle": (10, 3.0), "driveway": (10, 3.0), "drive-through": (8, 5.0)}
DEM_SAMPLE_SPACING_M = 25.0
CLIMB_NOISE_THRESHOLD_M = 2.0  # ignore DEM wiggles smaller than this
DEM_OPENING_PX = 5            # ~150 m window: strips buildings/trees from the surface model

# Traffic-stress colours shared by the web map and printed maps.
LTS_COLORS = {1: "#1a7f37", 2: "#72b043", 3: "#f0a202", 4: "#d1343a"}
LTS_LABELS = {1: "Very low stress (paths, calm streets)", 2: "Low stress",
              3: "Moderate stress (confident riders)", 4: "High stress (busy/fast roads)"}

# --- GPS tracking & navigation ------------------------------------------------
GPS_BAUDRATE = 115200                      # matches hardware/gps_i2c_serial sketch
IP_GEOLOCATION_URL = "http://ip-api.com/json/"
RIDES_DB = DATA_DIR / "rides.sqlite"
OFF_ROUTE_M = 40.0         # further than this from the route counts as off-route...
OFF_ROUTE_FIXES = 3        # ...for this many consecutive fixes
ARRIVE_M = 30.0            # within this of the finish = arrived
MAX_ACCURACY_M = 60.0      # fixes worse than this are recorded but not used to navigate

# --- Loop generation ----------------------------------------------------------
LOOP_DETOUR_FACTOR = 1.3   # road distance / straight-line distance
LOOP_BEARINGS = 8          # candidate directions tried per loop request
LOOP_REUSE_PENALTY = 4.0   # cost multiplier for re-riding an edge in the same loop
LOOP_DISTANCE_TOLERANCE = 0.3


@dataclass(frozen=True)
class Profile:
    """Routing preference weights (0 = ignore, higher = care more)."""

    label: str
    description: str
    safety: float = 0.0
    fun: float = 0.0
    traffic: float = 0.0
    hills: float = 0.0
    surface: float = 0.0
    time: bool = False              # base cost on travel time rather than distance
    lts_penalty: dict = field(default_factory=dict)  # {lts: multiplier}

    def weights(self) -> dict:
        return {"safety": self.safety, "fun": self.fun, "traffic": self.traffic,
                "hills": self.hills, "surface": self.surface}


PROFILES = {
    "fastest": Profile("Fastest", "Quickest ride, whatever the roads", time=True),
    "safest": Profile("Safest", "Protected lanes and calm streets first",
                      safety=4, traffic=1.5, lts_penalty={3: 2.0, 4: 6.0}),
    "family": Profile("Family", "Low-stress streets only, where possible",
                      safety=5, traffic=2, hills=1, lts_penalty={3: 6.0, 4: 30.0}),
    "scenic": Profile("Scenic & fun", "Parks, water, greenways and quiet lanes",
                      fun=3, safety=1.5, traffic=1, lts_penalty={4: 3.0}),
    "flattest": Profile("Flattest", "Avoid climbing", hills=4, safety=1),
    "quiet": Profile("Quietest", "Least motor traffic", traffic=4, safety=1),
    "balanced": Profile("Balanced", "A bit of everything",
                        safety=1.5, fun=1, traffic=1, hills=1, surface=0.5,
                        lts_penalty={4: 2.0}),
}
DEFAULT_PROFILE = "balanced"
