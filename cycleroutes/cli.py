"""Command line: build regions, generate/rate routes and loops, export, serve.

Examples:
  cycleroutes build --name austin --lat 30.2625 --lon -97.7463 --radius 4000
  cycleroutes route --from 30.2672,-97.7431 --to 30.2500,-97.7700
  cycleroutes loop --start 30.2625,-97.7463 --km 20 --profile scenic --pdf loop.pdf
  cycleroutes catalog
  cycleroutes serve --host 0.0.0.0 --https   (phone GPS over Wi-Fi)
  cycleroutes gps                             (find a USB GPS receiver)
  cycleroutes screenshots --out screenshots/
"""

import argparse
import json
import logging
import os
from pathlib import Path

from cycleroutes import config


def _latlon(text: str) -> tuple[float, float]:
    lat, lon = (float(v) for v in text.split(","))
    return lat, lon


def _print_table(rows: list[tuple[str, dict]]) -> None:
    keys = ["overall", "safety", "fun", "traffic", "hills", "speed", "surface"]
    print(f"{'route':<16}{'km':>6}{'min':>6}{'climb':>7}  " + "".join(f"{k[:7]:>8}" for k in keys))
    for name, s in rows:
        print(f"{name:<16}{s['distance_km']:>6.1f}{s['duration_min']:>6.0f}{s['ascent_m']:>6}m  "
              + "".join(f"{s['ratings'][k]:>8.1f}" for k in keys))


def _export(route, stats, title, args) -> None:
    from cycleroutes.export.formats import to_gpx
    from cycleroutes.export.print_map import route_pdf
    if args.gpx:
        Path(args.gpx).write_text(to_gpx(route, title))
        print(f"GPX written to {args.gpx}")
    if args.pdf:
        Path(args.pdf).write_bytes(route_pdf(route, stats, title))
        print(f"Printable map written to {args.pdf}")


def cmd_build(args) -> None:
    from cycleroutes.data.region import build_region
    build_region(args.name, args.lat, args.lon, args.radius)


def cmd_route(args) -> None:
    from cycleroutes.data.region import load_region
    from cycleroutes.routing.rating import rate
    from cycleroutes.routing.router import Router
    router = Router(load_region(args.region).graph)
    start, end = _latlon(args.start), _latlon(args.end)
    routes = router.alternatives(start, end) if args.profile == "all" \
        else [router.route(start, end, args.profile)]
    fastest = router.route(start, end, "fastest").time_s
    rated = [(r, rate(r, fastest_time_s=fastest)) for r in routes]
    _print_table([(r.profile, s) for r, s in rated])
    if args.json:
        print(json.dumps([s for _, s in rated], indent=2))
    best_route, best_stats = max(rated, key=lambda rs: rs[1]["ratings"]["overall"])
    _export(best_route, best_stats, f"{config.PROFILES[best_route.profile].label} route", args)


def cmd_loop(args) -> None:
    from cycleroutes.data.region import load_region
    from cycleroutes.routing.loops import generate_loops
    from cycleroutes.routing.router import Router
    router = Router(load_region(args.region).graph)
    loops = generate_loops(router, _latlon(args.start), args.km, args.profile, args.count)
    _print_table([(f"loop {i + 1}", s) for i, (_, s) in enumerate(loops)])
    route, stats = loops[0]
    _export(route, stats, f"{stats['distance_km']} km {config.PROFILES[args.profile].label} loop", args)


def cmd_catalog(args) -> None:
    from cycleroutes.data.region import load_region
    from cycleroutes.routing.catalog import build_catalog
    from cycleroutes.routing.router import Router
    region = load_region(args.region)
    rides = build_catalog(region, Router(region.graph))
    print(f"{len(rides)} suggested rides saved")


def cmd_screenshots(args) -> None:
    from cycleroutes.devtools.screenshots import print_summary, run
    out = Path(args.out)
    shots = run(out, url=args.url, region=args.region)
    if not print_summary(shots, out):
        raise SystemExit(1)


def cmd_sources(args) -> None:
    """Apply extra open data (3DEP, crashes, traffic counts, canopy, noise...) to a built region."""
    from cycleroutes.data.region import load_region, save_region
    from cycleroutes.data.sources.apply import apply_all
    region = load_region(args.region)
    report = apply_all(region, refresh=args.refresh, only=set(args.only.split(",")) if args.only else None)
    save_region(region)
    for name, result in report.items():
        print(f"{name:10s} {result}")


def cmd_amenities(args) -> None:
    from cycleroutes.data.amenities import fetch_amenities
    from cycleroutes.data.region import load_region
    geo = fetch_amenities(args.region, load_region(args.region).bbox)
    print(f"{len(geo['features'])} amenities saved")


def cmd_gps(args) -> None:
    """Find serial GPS receivers, or stream fixes from one (Ctrl+C to stop)."""
    import time as _time
    from cycleroutes.tracking.providers import SerialGPSProvider, discover_serial_gps
    if not args.port:
        ports = discover_serial_gps()
        print("\n".join(ports) if ports else "No serial GPS found (is it plugged in and sending NMEA?)")
        return
    gps = SerialGPSProvider(args.port, args.baud)
    last = None
    try:
        while True:
            fix = gps.latest()
            if fix and fix is not last:
                print(json.dumps(fix.to_dict()))
                last = fix
            _time.sleep(0.5)
    except KeyboardInterrupt:
        gps.close()


def _self_signed_cert() -> tuple[str, str]:
    """Create (once) a self-signed certificate so phones allow GPS over the LAN."""
    import subprocess
    cert, key = config.DATA_DIR / "dev-cert.pem", config.DATA_DIR / "dev-key.pem"
    if not cert.exists():
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
                        "-subj", "/CN=cycleroutes.local", "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True)
    return str(cert), str(key)


def cmd_serve(args) -> None:
    import uvicorn
    os.environ["CYCLEROUTES_REGION"] = args.region
    if args.serial_gps:
        os.environ["CYCLEROUTES_SERIAL_GPS"] = "1"
    if args.ip_location:
        os.environ["CYCLEROUTES_IP_LOCATION"] = "1"
    ssl = {}
    if args.https:
        cert, key = _self_signed_cert()
        ssl = {"ssl_certfile": cert, "ssl_keyfile": key}
        print("HTTPS with a self-signed certificate: your phone will warn once - accept it to continue.")
    uvicorn.run("cycleroutes.api.app:app", host=args.host, port=args.port, **ssl)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="cycleroutes", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = config.DEFAULT_REGION

    b = sub.add_parser("build", help="download + score a region")
    b.add_argument("--name", default=d["name"])
    b.add_argument("--lat", type=float, default=d["lat"])
    b.add_argument("--lon", type=float, default=d["lon"])
    b.add_argument("--radius", type=float, default=d["radius_m"], help="metres")
    b.set_defaults(func=cmd_build)

    for name, func, helptext in (("route", cmd_route, "A-to-B routes"),
                                 ("loop", cmd_loop, "round-trip rides")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--region", default=d["name"])
        if name == "route":
            s.add_argument("--from", dest="start", required=True, help="lat,lon")
            s.add_argument("--to", dest="end", required=True, help="lat,lon")
            s.add_argument("--profile", default="all", choices=["all", *config.PROFILES])
            s.add_argument("--json", action="store_true")
        else:
            s.add_argument("--start", required=True, help="lat,lon")
            s.add_argument("--km", type=float, default=15)
            s.add_argument("--profile", default="scenic", choices=list(config.PROFILES))
            s.add_argument("--count", type=int, default=3)
        s.add_argument("--gpx", help="write the top route as GPX")
        s.add_argument("--pdf", help="write the top route as a printable PDF")
        s.set_defaults(func=func)

    c = sub.add_parser("catalog", help="pre-generate suggested rides")
    c.add_argument("--region", default=d["name"])
    c.set_defaults(func=cmd_catalog)

    sh = sub.add_parser("screenshots", help="drive the web app headlessly: screenshots + checks")
    sh.add_argument("--region", default=d["name"])
    sh.add_argument("--url", help="use a running server instead of starting one")
    sh.add_argument("--out", default="screenshots", help="output folder (report.html inside)")
    sh.set_defaults(func=cmd_screenshots)

    v = sub.add_parser("serve", help="run the web app")
    v.add_argument("--region", default=d["name"])
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--https", action="store_true", help="self-signed HTTPS (phones need it for GPS)")
    v.add_argument("--serial-gps", action="store_true", help="scan for a USB/serial NMEA GPS receiver")
    v.add_argument("--ip-location", action="store_true",
                   help="offer IP geolocation as a source (sends this machine's IP to ip-api.com)")
    v.set_defaults(func=cmd_serve)

    so = sub.add_parser("sources", help="apply extra open data (elevation, crashes, traffic, shade, noise)")
    so.add_argument("--region", default=d["name"])
    so.add_argument("--refresh", action="store_true", help="download again instead of using the cache")
    so.add_argument("--only", help="comma list: elevation,canopy,noise,aadt,comfort,crashes,counters,stops")
    so.set_defaults(func=cmd_sources)

    am = sub.add_parser("amenities", help="(re)fetch bike shops, water, toilets, parking for a region")
    am.add_argument("--region", default=d["name"])
    am.set_defaults(func=cmd_amenities)

    g = sub.add_parser("gps", help="list serial GPS receivers, or stream fixes from --port")
    g.add_argument("--port", help="e.g. /dev/tty.usbmodem101")
    g.add_argument("--baud", type=int, default=config.GPS_BAUDRATE)
    g.set_defaults(func=cmd_gps)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose or args.cmd in ("build", "catalog", "sources")
                        else logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("rasterio").setLevel(logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
