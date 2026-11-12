"""The scoring and routing model's numbers, exported as JSON for the browser engine.

The JS port (static/*_engine.js and friends) holds only the formulas; every table and weight it uses comes from
here, i.e. from cycleroutes.config and the scoring/routing modules, so there is one place to change a number.
"""
from dataclasses import asdict

from cycleroutes import config
from cycleroutes.routing import loops, rating, router
from cycleroutes.routing.context import AVOID_TYPES, BIKE_AVOID, BIKE_TYPES
from cycleroutes.routing.directions import GENERIC_STREETS, JOG_MERGE_KM, TURN_THRESHOLD_DEG
from cycleroutes.scoring import edge_scores, lts, tags


def _profile(p: config.Profile) -> dict:
    d = asdict(p)
    d["lts_penalty"] = {str(k): v for k, v in p.lts_penalty.items()}
    return d


def model() -> dict:
    return {
        "tags": {"highway_order": tags.HIGHWAY_ORDER, "trail_words": list(tags.TRAIL_WORDS),
                 "city_infra": list(tags.CITY_INFRA), "default_speed_kmh": config.DEFAULT_SPEED_KMH},
        "lts": {"mph25": lts.MPH25, "mph30": lts.MPH30, "mph40": lts.MPH40,
                "off_road": sorted(lts.OFF_ROAD), "calm_streets": sorted(lts.CALM_STREETS)},
        "scores": {"lts_safety": {str(k): v for k, v in edge_scores.LTS_SAFETY.items()},
                   "quiet_by_highway": edge_scores.QUIET_BY_HIGHWAY,
                   "surface_quality": edge_scores.SURFACE_QUALITY,
                   "base_kmh": config.BASE_CYCLING_SPEED_KMH,
                   "max_downhill_kmh": config.MAX_DOWNHILL_SPEED_KMH,
                   "signal_delay_s": config.TRAFFIC_SIGNAL_DELAY_S,
                   "awkward_service": {k: list(v) for k, v in config.AWKWARD_SERVICE.items()}},
        "profiles": {k: _profile(p) for k, p in config.PROFILES.items()},
        "relaxed_family": _profile(router.RELAXED_FAMILY),
        "default_profile": config.DEFAULT_PROFILE,
        "bike_types": {k: {**asdict(b), "extra_lts_penalty": {str(x): y for x, y in b.extra_lts_penalty.items()}}
                       for k, b in BIKE_TYPES.items()},
        "avoid_types": {k: AVOID_TYPES[k][0] for k in BIKE_AVOID},
        "routing": {"time_to_metres": router.TIME_TO_METRES, "climb_cost_m": router.CLIMB_COST_M,
                    "max_snap_m": router.MAX_SNAP_M, "avoid_penalty": config.AVOID_PENALTY,
                    "infra_only_penalty": config.INFRA_ONLY_PENALTY, "prefer_penalty": config.PREFER_PENALTY,
                    "crossing_cost_m": config.CROSSING_COST_M, "family_max_detour": config.FAMILY_MAX_DETOUR,
                    "max_overlap": 0.9},
        "loops": {"detour_factor": config.LOOP_DETOUR_FACTOR, "bearings": config.LOOP_BEARINGS,
                  "reuse_penalty": config.LOOP_REUSE_PENALTY, "tolerance": config.LOOP_DISTANCE_TOLERANCE,
                  "rating_key": loops.PROFILE_RATING_KEY},
        "rating": {"min_grade_run_m": rating.MIN_GRADE_RUN_M},
        "directions": {"turn_threshold_deg": TURN_THRESHOLD_DEG, "generic_streets": sorted(GENERIC_STREETS),
                       "jog_merge_km": JOG_MERGE_KM},
        "lts_colors": {str(k): v for k, v in config.LTS_COLORS.items()},
        "lts_labels": {str(k): v for k, v in config.LTS_LABELS.items()},
        "safety_notice": config.SAFETY_NOTICE,
        "safety_notice_short": config.SAFETY_NOTICE_SHORT,
    }
