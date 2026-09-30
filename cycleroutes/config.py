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
DEFAULT_REGION = {"name": "austin", "lat": 30.2800, "lon": -97.7400, "radius_m": 10000}
OVERPASS_MAX_QUERY_AREA_M2 = 6e7   # split big downloads into ~7.7 km squares (public servers time out)

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

# Downloadable OpenStreetMap extracts (build from a file instead of the Overpass API).
# bbox = (south, west, north, east) coverage; add entries for other cities.
EXTRACTS = {
    "bbbike-austin": {"provider": "BBBike", "name": "Austin",
                      "url": "https://download.bbbike.org/osm/bbbike/Austin/Austin.osm.pbf",
                      "bbox": (30.10, -97.99, 30.71, -97.54), "updated": "weekly"},
}

# --- Extra open data sources (see cycleroutes/data/sources/) --------------------
USGS_3DEP_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
DEM_3DEP_RES_M = 5.0          # bare-earth lidar DEM resampled to 5 m
AUSTIN_SOCRATA = "https://data.austintexas.gov/resource"
AUSTIN_CRASHES = "y2wy-tgr5"            # Vision Zero crash records (TxDOT CRIS)
AUSTIN_BIKE_FACILITIES = "23hw-a95n"    # bike facilities + city "level of comfort"
AUSTIN_COUNTER_FLOWS = "4mh3-39w2"      # active-transportation counter sites
AUSTIN_COUNTER_COUNTS = "u4i6-pw3h"
AUSTIN_SIDEWALKS = "vchz-d9ng"          # sidewalk inventory with condition ratings
AUSTIN_WZDX_URL = "https://data.austintexas.gov/download/d9mm-cjw9"   # work zones (WZDx 4.x)
AUSTIN_BBOX = (30.05, -98.10, 30.55, -97.50)                       # where the Austin sources apply
TXDOT_AADT_URLS = [
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_AADT_Annuals_(Public_View)/FeatureServer/0",
    "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_5_Year_Statewide_AADT_Traffic_Counts/FeatureServer/0",
]
TEXAS_BBOX = (25.8, -106.7, 36.6, -93.5)
CANOPY_TILE_URL = ("https://dataforgood-fb-data.s3.amazonaws.com/forests/v2/global/"
                   "dinov3_global_chm_v2_ml3/chm/{quadkey}.tif")     # Meta/WRI 1 m canopy height
CANOPY_TREE_M = 3.0           # canopy taller than this counts as shade
NOISE_TILE_URL = ("https://tiles.arcgis.com/tiles/xOi1kZaI0eWDREZv/arcgis/rest/services/"
                  "NTAD_Noise_2022_CONUS_aviation_road/MapServer")    # US DOT noise map
OVERTURE_PLACES = ("s3://overturemaps-us-west-2/release/2026-09-23.1/theme=places/type=place/*")
GBFS_URL = "https://austin.publicbikesystem.net/customer/gbfs/v3.0/gbfs.json"   # CapMetro Bikeshare
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
PROTOMAPS_BUILDS_URL = "https://build-metadata.protomaps.dev/builds.json"
PROTOMAPS_BUILD_URL = "https://build.protomaps.com/{key}"   # daily OSM vector build (ODbL)
OFFLINE_MAX_ZOOM = 15      # deepest vector zoom; the map over-zooms beyond it
CRASH_YEARS = 7
CRASH_RADIUS_M = 20.0

# OSM way tags kept on graph edges (beyond osmnx defaults).
EXTRA_WAY_TAGS = [
    "cycleway", "cycleway:left", "cycleway:right", "cycleway:both",
    "bicycle", "surface", "smoothness", "lit", "segregated",
    "bridge", "tunnel", "oneway:bicycle", "sidewalk",
    "mtb:scale", "footway", "foot", "trail_visibility",
]

# Walking network: osmnx "walk" filter plus shared-use paths tagged as cycleways that allow
# pedestrians, and pedestrian areas' edges. Tags useful for walking are kept too.
WALK_EXTRA_FILTERS = [
    '["highway"="cycleway"]["foot"~"yes|designated|permissive"]["access"!~"private|no"]',
]
WALK_EXTRA_TAGS = ["sac_scale", "wheelchair", "incline", "crossing", "tactile_paving", "kerb",
                   "trail_visibility", "sidewalk:left", "sidewalk:right", "sidewalk:both"]
WALK_BASE_KMH = 4.8
TOBLER_FLAT_KMH = 5.0

# Extra ways added to the osmnx "bike" network: trails that allow bikes but are tagged
# as footways (common for greenbelt trails), and anything with a mountain-bike grade.
TRAIL_FILTERS = [
    '["highway"~"footway|path|bridleway"]["bicycle"~"yes|designated|permissive"]'
    '["footway"!~"sidewalk|crossing"]["access"!~"private|no"]',
    '["highway"~"path|track|footway|bridleway"]["mtb:scale"]["bicycle"!~"no"]["access"!~"private|no"]',
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
    shade: float = 0.0
    crossings: float = 1.0          # penalty for unsignalised crossings of busy roads
    prefer: str = ""                # "trails" or "mtb": strongly favour those ways
    time: bool = False              # base cost on travel time rather than distance
    lts_penalty: dict = field(default_factory=dict)  # {lts: multiplier}

    def weights(self) -> dict:
        return {"safety": self.safety, "fun": self.fun, "traffic": self.traffic,
                "hills": self.hills, "surface": self.surface, "shade": self.shade}


PROFILES = {
    "fastest": Profile("Fastest", "Quickest ride, whatever the roads", time=True, crossings=0.3),
    "safest": Profile("Safest", "Protected lanes and calm streets first",
                      safety=4, traffic=1.5, crossings=3, lts_penalty={3: 2.0, 4: 6.0}),
    "family": Profile("Family", "Low-stress streets only, where possible",
                      safety=5, traffic=2, hills=1, crossings=4, lts_penalty={3: 6.0, 4: 30.0}),
    "scenic": Profile("Scenic & fun", "Parks, water, greenways and quiet lanes",
                      fun=3, safety=1.5, traffic=1, shade=1, crossings=1.5, lts_penalty={4: 3.0}),
    "flattest": Profile("Flattest", "Avoid climbing", hills=4, safety=1),
    "quiet": Profile("Quietest", "Least motor traffic and noise", traffic=4, safety=1, crossings=2),
    "trails": Profile("Trails & greenways", "Car-free trails and greenways wherever possible",
                      fun=2, safety=1, crossings=2, prefer="trails", lts_penalty={3: 2.0, 4: 6.0}),
    "mtb": Profile("Mountain-bike trails", "Unpaved and singletrack trails (loops)",
                   fun=1, crossings=1, prefer="mtb", lts_penalty={3: 2.0, 4: 6.0}),
    "shady": Profile("Shadiest", "Most tree cover - for hot days", shade=4, safety=1.5, traffic=1,
                     lts_penalty={4: 3.0}),
    "balanced": Profile("Balanced", "A bit of everything",
                        safety=1.5, fun=1, traffic=1, hills=1, surface=0.5, shade=0.5,
                        crossings=1.5, lts_penalty={4: 2.0}),
}
DEFAULT_PROFILE = "balanced"

# Walking trip types (same Profile fields; "lts" on a walking graph is pedestrian stress).
WALK_PROFILES = {
    "commute": Profile("Commute", "Direct and safe - the sensible way to work", time=True, safety=1.5,
                       crossings=2, lts_penalty={4: 3.0}),
    "urban": Profile("Urban adventure", "Lively streets, cafés, shops and street life",
                     fun=2, safety=1, crossings=1.5, prefer="lively", lts_penalty={4: 3.0}),
    "tourist": Profile("Sightseeing", "Past landmarks, museums, parks and viewpoints",
                       fun=2, safety=1, crossings=1.5, prefer="sights", lts_penalty={4: 3.0}),
    "hike": Profile("Hike", "Trails and nature; hills welcome", fun=2, prefer="trails",
                    lts_penalty={3: 2.0, 4: 6.0}),
    "green": Profile("Green & quiet", "Parks, water and quiet streets", fun=2, traffic=3, safety=1,
                     prefer="nature", crossings=2, lts_penalty={3: 2.0, 4: 6.0}),
    "shady": Profile("Shady stroll", "Most tree cover - for hot days", shade=4, safety=1, traffic=1,
                     lts_penalty={4: 3.0}),
    "accessible": Profile("Step-free", "Wheelchair & stroller friendly: no steps, gentle slopes, smooth",
                          hills=3, safety=2, surface=3, crossings=3, prefer="accessible", lts_penalty={4: 3.0}),
    "safest": Profile("Safest", "Sidewalks, low traffic, safe crossings", safety=4, traffic=2, crossings=4,
                      lts_penalty={3: 3.0, 4: 10.0}),
    "balanced": Profile("Balanced", "A bit of everything", safety=1.5, fun=1.5, traffic=1, hills=0.5,
                        shade=0.5, crossings=1.5, lts_penalty={4: 2.0}),
}
DEFAULT_WALK_PROFILE = "balanced"
MODES = {"bike": PROFILES, "walk": WALK_PROFILES}
AVOID_PENALTY = 40.0        # "avoid" road types: 40x cost - used only when nothing else connects
INFRA_ONLY_PENALTY = 5.0    # "bike lanes & trails only": streets without bike space cost 5x
PREFER_PENALTY = {"trails": 3.0, "mtb": 4.0, "lively": 1.8, "sights": 1.8, "nature": 2.5, "accessible": 50.0}   # cost multiplier for ways that aren't what the profile seeks
CROSSING_COST_M = 80.0      # an unsignalised crossing of a busy road ~ 80 m of extra riding
FAMILY_MAX_DETOUR = 1.8     # family route longer than this x fastest -> relax and warn
HOT_APPARENT_C = 30.0       # feels-like temperature above which shade is sought
