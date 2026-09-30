import json

import pytest

from cycleroutes.routing.router import Router
from cycleroutes.tracking.navigator import Navigator
from cycleroutes.tracking.nmea import Fix, NmeaParser, checksum_ok, estimate_accuracy_m, to_nmea_rmc
from cycleroutes.tracking.store import RideStore, ride_csv, ride_gpx, track_stats

from conftest import node_latlon

RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"
GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"


def test_nmea_rmc_gga():
    p = NmeaParser()
    assert p.feed(GGA) is None                      # quality data only
    fix = p.feed(RMC)
    assert fix.latitude == pytest.approx(48.1173, abs=1e-4)
    assert fix.longitude == pytest.approx(11.5167, abs=1e-4)
    assert fix.speed_kmh == pytest.approx(22.4 * 1.852, abs=0.01)
    assert fix.altitude == 545.4 and fix.satellites == 8 and fix.hdop == 0.9
    assert fix.accuracy_m == pytest.approx(4.0)


def test_nmea_rejects_bad_checksum_and_void_fix():
    p = NmeaParser()
    assert not checksum_ok(RMC[:-2] + "00")
    assert p.feed(RMC[:-2] + "00") is None
    assert p.feed("$GPRMC,123519,V,,,,,,,230394,,*00") is None
    assert p.feed("garbage") is None


def test_nmea_multi_constellation_and_roundtrip():
    fix = Fix(30.2672, -97.7431, 1_700_000_000, speed_kmh=18.0, heading=90.0)
    sentence = to_nmea_rmc(fix)
    assert checksum_ok(sentence)
    parsed = NmeaParser().feed(sentence.replace("$GPRMC", "$GNRMC", 1).rsplit("*", 1)[0])
    assert parsed.latitude == pytest.approx(30.2672, abs=1e-5)
    assert parsed.longitude == pytest.approx(-97.7431, abs=1e-5)
    assert parsed.speed_kmh == pytest.approx(18.0, abs=0.1)


def test_accuracy_estimate():
    assert estimate_accuracy_m(0, 0, 0) == 999.0
    assert estimate_accuracy_m(1, 9, 1.0) < estimate_accuracy_m(1, 4, 12.0)


@pytest.fixture(scope="module")
def route(region):
    return Router(region.graph).route(node_latlon(region, 0, 0), node_latlon(region, 5, 5), "balanced")


def test_navigator_progress_offroute_and_arrival(route):
    nav = Navigator(route)
    coords = route.coords()
    mid = coords[len(coords) // 2]
    p = nav.update(Fix(mid[1], mid[0], 0))
    assert 0.2 < p.fraction < 0.8 and not p.off_route
    assert p.next_cue is not None and p.remaining_m < nav.total_m

    far = Fix(mid[1] + 0.003, mid[0] + 0.003, 1)    # ~450 m away
    assert not nav.update(far).off_route             # one bad fix is tolerated
    nav.update(far)
    assert nav.update(far).off_route
    assert nav.along_m == pytest.approx(p.along_m)   # progress not corrupted

    end = coords[-1]
    done = nav.update(Fix(end[1], end[0], 2))
    assert done.arrived and done.remaining_m < 1


def _fake_ride(route, seconds_per_point=40):   # ~200 m per 40 s = 18-20 km/h
    return [Fix(lat, lon, 1_700_000_000 + i * seconds_per_point, accuracy_m=5)
            for i, (lon, lat) in enumerate(route.coords())]


def test_store_stats_and_exports(tmp_path, route):
    store = RideStore(tmp_path / "r.sqlite")
    rid = store.start("Test ride")
    store.add_fixes(rid, _fake_ride(route))
    pts = store.points(rid)
    stats = track_stats(pts)
    assert stats["distance_km"] == pytest.approx(route.length_m / 1000, rel=0.06)  # grid edges are ~200 m
    assert stats["moving_min"] > 0
    assert "<trkpt" in ride_gpx(store.ride(rid), pts) and "<time>" in ride_gpx(store.ride(rid), pts)
    assert ride_csv(pts).splitlines()[0].startswith("time_utc,latitude")
    store.finish(rid, json.dumps(stats))
    assert store.rides()[0]["n_points"] == len(pts)
    assert store.delete(rid) and store.points(rid) == []


def test_serial_provider_reads_virtual_port():
    """SerialGPSProvider on a pseudo-terminal fed with NMEA, as a USB GPS would be."""
    import os
    import time
    serial = pytest.importorskip("serial")  # noqa: F841
    from cycleroutes.tracking.providers import SerialGPSProvider
    master, slave = os.openpty()
    gps = SerialGPSProvider(os.ttyname(slave))
    try:
        deadline = time.time() + 5
        while gps.latest() is None and time.time() < deadline:
            os.write(master, (GGA + "\r\n" + RMC + "\r\n").encode())
            time.sleep(0.2)
        fix = gps.latest()
        assert fix is not None and fix.satellites == 8
        assert fix.latitude == pytest.approx(48.1173, abs=1e-4)
    finally:
        gps.close()
        os.close(master)


def test_spikes_removed_but_fast_travel_kept():
    base = {"ele": None, "speed_kmh": None, "heading": None, "accuracy_m": 5}
    pts = [dict(base, t=i * 10, lat=30.0 + i * 0.0005, lon=-97.0) for i in range(6)]  # ~20 km/h
    spiky = pts[:3] + [dict(base, t=25, lat=30.05, lon=-97.0)] + pts[3:]             # 5 km jump & back
    assert track_stats(spiky)["spikes_removed"] == 1
    assert track_stats(spiky)["distance_km"] == pytest.approx(track_stats(pts)["distance_km"], abs=0.01)
    fast = [dict(base, t=i, lat=30.0 + i * 0.001, lon=-97.0) for i in range(6)]      # ~400 km/h steady
    assert track_stats(fast)["distance_km"] > 0.5 and track_stats(fast)["spikes_removed"] == 0
