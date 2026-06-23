#!/usr/bin/env python3
"""
FirePort backend — real-time wildfire data for France.

Endpoints
  GET /api/health                  -> liveness + which sources are configured
  GET /api/mapkit-token            -> Apple MapKit JS ES256 JWT (satellite map)
  GET /api/fires?days=1|2|7        -> NASA FIRMS active fire detections as GeoJSON
  GET /api/effis/<z>/<x>/<y>.png   -> EFFIS Fire Weather Index WMS tile (XYZ proxy)
  GET /api/risk                    -> Meteo-France "Meteo des forets" risk choropleth
  GET /api/stats                   -> live aggregate stats (FIRMS + MDF) + source links

Data sources
  - NASA FIRMS (VIIRS NOAA-20/21 + S-NPP, MODIS)   active fire detection
  - EFFIS / Copernicus  WMS  ecmwf007.fwi          fire weather index (danger)
  - Meteo-France "Meteo des forets"                department risk J+1 / J+2
  - BDIFF / Promethee                              historical reference (link-out)
"""
import csv
import gzip
import io
import math
import os
import threading
import time

import jwt as pyjwt
import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# Config (env, with sane defaults)
# --------------------------------------------------------------------------- #
FIRMS_MAP_KEY       = os.environ.get("FIRMS_MAP_KEY", "")
APPLE_MAPS_KEY_PATH = os.environ.get("APPLE_MAPS_KEY_PATH", "/opt/fireport/backend/MapsKey.p8")
APPLE_MAPS_KEY_ID   = os.environ.get("APPLE_MAPS_KEY_ID", "")
APPLE_MAPS_TEAM_ID  = os.environ.get("APPLE_MAPS_TEAM_ID", "")
MAPKIT_ORIGIN       = os.environ.get("MAPKIT_ORIGIN", "")

# France metropolitaine + Corse: west,south,east,north
FRANCE_BBOX = os.environ.get("FRANCE_BBOX", "-5,41,10,52")

FIRMS_SOURCES = [
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
]

EFFIS_WMS   = "https://maps.effis.emergency.copernicus.eu/effis"
EFFIS_LAYER = "mf010.fwi"  # Fire Weather Index layer on this WMS endpoint

MDF_CSV_GZ   = "https://object.files.data.gouv.fr/meteofrance/data/BULLETIN/MDF/mdf_2026.csv.gz"
MDF_GEOJSON  = "https://static.data.gouv.fr/resources/archive-meteo-des-forets/20251218-123448/departements.geojson"

UA = {"User-Agent": "FirePort/1.0 (+https://fireport.cyclooo.fr)"}

# --------------------------------------------------------------------------- #
# Tiny thread-safe TTL cache
# --------------------------------------------------------------------------- #
_cache: dict[str, tuple[float, object]] = {}
_clock = time.monotonic  # monotonic so it survives wall-clock jumps
_lock = threading.Lock()


def cache_get(key):
    with _lock:
        hit = _cache.get(key)
        if hit and _clock() < hit[0]:
            return hit[1]
    return None


def cache_set(key, value, ttl):
    with _lock:
        _cache[key] = (_clock() + ttl, value)
    return value


# --------------------------------------------------------------------------- #
# Apple MapKit JS token
# --------------------------------------------------------------------------- #
def _now_epoch():
    # time.time() is fine here; only used for JWT iat/exp
    return int(time.time())


def make_mapkit_token():
    cached = cache_get("mapkit_token")
    if cached:
        return cached
    with open(APPLE_MAPS_KEY_PATH, "r") as fh:
        private_key = fh.read()
    iat = _now_epoch()
    token = pyjwt.encode(
        {"iss": APPLE_MAPS_TEAM_ID, "iat": iat, "exp": iat + 1800, "origin": MAPKIT_ORIGIN},
        private_key,
        algorithm="ES256",
        headers={"kid": APPLE_MAPS_KEY_ID, "typ": "JWT"},
    )
    # PyJWT >=2 returns str
    return cache_set("mapkit_token", token, 1500)  # refresh well before 1800s expiry


@app.route("/api/mapkit-token")
def mapkit_token():
    try:
        return jsonify({"token": make_mapkit_token(), "origin": MAPKIT_ORIGIN})
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("mapkit token failed")
        return jsonify({"error": "mapkit_token_failed", "detail": str(exc)}), 500


# --------------------------------------------------------------------------- #
# NASA FIRMS active fire detections -> GeoJSON
# --------------------------------------------------------------------------- #
def _conf_bucket(instrument, confidence):
    """Normalise confidence across VIIRS (l/n/h) and MODIS (0-100) to low/nominal/high."""
    c = (confidence or "").strip().lower()
    if c in ("l", "n", "h"):
        return {"l": "low", "n": "nominal", "h": "high"}[c]
    try:
        v = float(c)
    except ValueError:
        return "nominal"
    if v < 30:
        return "low"
    if v < 80:
        return "nominal"
    return "high"


def fetch_firms(days):
    key = f"fires_{days}"
    cached = cache_get(key)
    if cached is not None:
        return cached
    if not FIRMS_MAP_KEY:
        return {"type": "FeatureCollection", "features": [], "count": 0,
                "error": "FIRMS_MAP_KEY not configured"}

    features = []
    seen = set()
    errors = []
    for src in FIRMS_SOURCES:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/{src}/{FRANCE_BBOX}/{days}"
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.status_code != 200 or r.text.startswith("Invalid"):
                errors.append(f"{src}:{r.status_code}")
                continue
            reader = csv.DictReader(io.StringIO(r.text))
            for row in reader:
                try:
                    lat = float(row["latitude"]); lon = float(row["longitude"])
                except (KeyError, ValueError):
                    continue
                # de-dupe near-identical detections shared across sensors
                dkey = (round(lat, 3), round(lon, 3), row.get("acq_date"), row.get("acq_time"))
                if dkey in seen:
                    continue
                seen.add(dkey)
                try:
                    frp = float(row.get("frp") or 0)
                except ValueError:
                    frp = 0.0
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "frp": round(frp, 2),
                        "confidence": _conf_bucket(row.get("instrument"), row.get("confidence")),
                        "satellite": row.get("satellite", ""),
                        "instrument": row.get("instrument", ""),
                        "acq_date": row.get("acq_date", ""),
                        "acq_time": row.get("acq_time", ""),
                        "daynight": row.get("daynight", ""),
                        "bright": row.get("bright_ti4") or row.get("brightness") or "",
                    },
                })
        except requests.RequestException as exc:
            errors.append(f"{src}:err")
            app.logger.warning("FIRMS %s failed: %s", src, exc)

    fc = {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "days": days,
        "bbox": FRANCE_BBOX,
        "updated": _now_epoch(),
    }
    if errors:
        fc["partial_errors"] = errors
    return cache_set(key, fc, 600)  # 10 min — FIRMS NRT updates roughly hourly


@app.route("/api/fires")
def fires():
    try:
        days = int(request.args.get("days", 1))
    except ValueError:
        days = 1
    days = max(1, min(days, 5))  # FIRMS NRT area API allows [1..5]
    return jsonify(fetch_firms(days))


# --------------------------------------------------------------------------- #
# EFFIS Fire Weather Index WMS tile proxy (XYZ -> WMS GetMap, EPSG:3857)
# --------------------------------------------------------------------------- #
R_EARTH = 6378137.0


def _tile_to_3857(z, x, y):
    n = 2 ** z
    def lon_deg(xt): return xt / n * 360.0 - 180.0
    def lat_deg(yt): return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / n))))
    west, east = lon_deg(x), lon_deg(x + 1)
    north, south = lat_deg(y), lat_deg(y + 1)

    def mx(l): return R_EARTH * math.radians(l)
    def my(la):
        la = max(min(la, 85.05112878), -85.05112878)
        return R_EARTH * math.log(math.tan(math.pi / 4 + math.radians(la) / 2))
    return mx(west), my(south), mx(east), my(north)


@app.route("/api/effis/<int:z>/<int:x>/<int:y>.png")
def effis_tile(z, x, y):
    key = f"effis_{z}_{x}_{y}"
    cached = cache_get(key)
    if cached is not None:
        return Response(cached, mimetype="image/png")
    minx, miny, maxx, maxy = _tile_to_3857(z, x, y)
    params = {
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
        "LAYERS": EFFIS_LAYER, "STYLES": "",
        "SRS": "EPSG:3857",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": 256, "HEIGHT": 256,
        "FORMAT": "image/png", "TRANSPARENT": "true",
    }
    try:
        r = requests.get(EFFIS_WMS, params=params, headers=UA, timeout=20)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            cache_set(key, r.content, 3600)  # FWI is a daily product
            return Response(r.content, mimetype="image/png")
        app.logger.warning("EFFIS tile bad response %s %s", r.status_code, r.headers.get("content-type"))
    except requests.RequestException as exc:
        app.logger.warning("EFFIS tile failed: %s", exc)
    # transparent 1x1 fallback so the map layer never breaks
    blank = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
    )
    return Response(blank, mimetype="image/png")


# --------------------------------------------------------------------------- #
# Meteo-France "Meteo des forets" department risk choropleth
# --------------------------------------------------------------------------- #
def _load_dept_geojson():
    cached = cache_get("dept_geojson")
    if cached is not None:
        return cached
    r = requests.get(MDF_GEOJSON, headers=UA, timeout=30)
    r.raise_for_status()
    gj = r.json()
    return cache_set("dept_geojson", gj, 86400)  # boundaries never change


def _load_mdf_latest():
    """Return (date, {dep_code: {'j1':int,'j2':int,'nom':str}})."""
    r = requests.get(MDF_CSV_GZ, headers=UA, timeout=30)
    r.raise_for_status()
    text = gzip.decompress(r.content).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    if not rows:
        return None, {}
    latest = max(row["date"] for row in rows)
    out = {}
    for row in rows:
        if row["date"] != latest:
            continue
        try:
            j1 = int(row["niveau_j1"]); j2 = int(row["niveau_j2"])
        except (KeyError, ValueError):
            continue
        out[row["num_dep"]] = {"j1": j1, "j2": j2, "nom": row.get("nom_dep", "")}
    return latest, out


def build_risk():
    cached = cache_get("risk")
    if cached is not None:
        return cached
    try:
        gj = _load_dept_geojson()
        date, levels = _load_mdf_latest()
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("risk build failed")
        return {"error": "risk_unavailable", "detail": str(exc)}

    # shallow-copy features, attach risk props (don't mutate cached geojson)
    feats = []
    histo = {1: 0, 2: 0, 3: 0, 4: 0}
    for f in gj.get("features", []):
        code = f.get("properties", {}).get("code")
        lvl = levels.get(code)
        props = {
            "code": code,
            "nom": f["properties"].get("nom", ""),
            "niveau": lvl["j1"] if lvl else 0,
            "niveau_j2": lvl["j2"] if lvl else 0,
        }
        if lvl:
            histo[lvl["j1"]] = histo.get(lvl["j1"], 0) + 1
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": props})

    result = {
        "type": "FeatureCollection",
        "features": feats,
        "date": date,
        "histogram": histo,
        "high": histo.get(3, 0) + histo.get(4, 0),
        "extreme": histo.get(4, 0),
    }
    return cache_set("risk", result, 3600)


@app.route("/api/risk")
def risk():
    return jsonify(build_risk())


# --------------------------------------------------------------------------- #
# Aggregate stats (live FIRMS + MDF) + historical source links
# --------------------------------------------------------------------------- #
@app.route("/api/stats")
def stats():
    fires_24h = fetch_firms(1)
    fires_5d = fetch_firms(5)
    r = build_risk()

    feats = fires_24h.get("features", [])
    max_frp = 0.0
    hottest = None
    total_frp = 0.0
    for f in feats:
        frp = f["properties"].get("frp", 0) or 0
        total_frp += frp
        if frp > max_frp:
            max_frp = frp
            hottest = f["geometry"]["coordinates"]

    return jsonify({
        "active_24h": fires_24h.get("count", 0),
        "active_5d": fires_5d.get("count", 0),
        "max_frp": round(max_frp, 1),
        "total_frp": round(total_frp, 1),
        "hottest": hottest,
        "risk_date": r.get("date"),
        "high_risk_departments": r.get("high", 0),
        "extreme_risk_departments": r.get("extreme", 0),
        "risk_histogram": r.get("histogram", {}),
        "updated": _now_epoch(),
        "sources": {
            "firms": "https://firms.modaps.eosdis.nasa.gov/",
            "effis": "https://forest-fire.emergency.copernicus.eu/",
            "meteo_des_forets": "https://meteofrance.com/meteo-des-forets",
            "bdiff": "https://bdiff.agriculture.gouv.fr/",
            "promethee": "https://www.promethee.com/",
        },
    })


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "firms": bool(FIRMS_MAP_KEY),
        "mapkit_key": os.path.exists(APPLE_MAPS_KEY_PATH),
        "origin": MAPKIT_ORIGIN,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5004, debug=True)
