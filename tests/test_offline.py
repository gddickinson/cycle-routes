"""Offline basemap serving, tile maths and personal-data backup (no downloads)."""

import gzip
import json
import sqlite3

from cycleroutes import config
from cycleroutes.offline import backup
from cycleroutes.offline.basemap import LocalBasemap, basemap_path, tiles_for_bbox
from cycleroutes.tracking.nmea import Fix
from cycleroutes.tracking.store import RideStore
from cycleroutes.community.store import CommunityStore


def test_tiles_for_bbox_grows_with_zoom():
    bbox = (30.23, -97.80, 30.34, -97.68)
    assert len(tiles_for_bbox(*bbox, 0)) == 1
    assert len(tiles_for_bbox(*bbox, 14)) > len(tiles_for_bbox(*bbox, 12)) >= 1


def _fake_basemap(name: str) -> None:
    path = basemap_path(name)
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE tiles (z INTEGER, x INTEGER, y INTEGER, data BLOB, PRIMARY KEY (z, x, y))")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO tiles VALUES (12, 941, 1692, ?)", (gzip.compress(b"vector tile"),))
    info = {"tiles": 1, "bytes": 30, "max_zoom": 15, "built": 0, "source": "test", "compression": 2,
            "attribution": "test"}
    db.execute("INSERT INTO meta VALUES ('info', ?)", (json.dumps(info),))
    db.commit()
    db.close()


def test_local_basemap_and_tile_endpoint(client):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _fake_basemap("test")
    try:
        assert LocalBasemap("test").tile(12, 941, 1692)
        res = client.get("/tiles/12/941/1692.mvt")
        assert res.status_code == 200 and res.content == b"vector tile"   # gzip decoded by the client
        assert client.get("/tiles/3/1/1.mvt").status_code == 204
        status = client.get("/api/offline/status").json()
        assert status["basemap"]["tiles"] == 1
        m = client.get("/api/offline/manifest?min_zoom=10").json()
        assert m["tiles"] == ["/tiles/12/941/1692.mvt"] and "/api/offline/status" in m["api"] and "/api/suggested?mode=bike" in m["api"]
    finally:
        basemap_path("test").unlink(missing_ok=True)


def test_backup_roundtrip(tmp_path):
    src = tmp_path / "a.sqlite"
    rides, community = RideStore(src), CommunityStore(src)
    rid = rides.start("Morning ride")
    rides.add_fixes(rid, [Fix(30.0, -97.0, 1_700_000_000), Fix(30.001, -97.0, 1_700_000_030)])
    community.add_place("Home", 30.0, -97.0)
    community.add_favourite("Commute", {"start": [30, -97], "end": [30.1, -97]})
    community.report_hazard("pothole", 30.0, -97.0, "deep")
    data = backup.export_json(src)
    assert len(data["tables"]["points"]) == 2

    dst = tmp_path / "b.sqlite"
    RideStore(dst), CommunityStore(dst)          # empty database with the schema
    RideStore(dst).start("Existing ride")        # ids must not clash
    counts = backup.import_json(dst, json.loads(backup.dumps(data)))
    assert counts["rides"] == 1 and counts["points"] == 2 and counts["places"] == 1
    restored = RideStore(dst)
    names = sorted(r["name"] for r in restored.rides())
    assert names == ["Existing ride", "Morning ride"]
    morning = next(r for r in restored.rides() if r["name"] == "Morning ride")
    assert len(restored.points(morning["id"])) == 2
