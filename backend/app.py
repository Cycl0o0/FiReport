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
import html as _html
import io
import math
import os
import re
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

# Préfecture de la Gironde — official press releases (live situation updates).
# Overridable via env so the current month / département stay config-driven.
PREF_BASE  = os.environ.get("PREF_BASE", "https://www.gironde.gouv.fr")
PREF_INDEX = os.environ.get(
    "PREF_INDEX",
    "/Actualites/Communiques-de-presse/Communiques-de-presse-2026/Juillet-2026",
)
PREF_KEYWORDS = re.compile(r"incendie|feu[x]?\b|saumos|évacu|evacu|fr-alert|vigilance", re.I)
_PREF_COMMUNE_RE = re.compile(r"communes?\s+(?:de|du|des|d’|d')\s+(.+?)(?:\s*[:–-]|$)", re.I)

# The préfecture site (DataDome) drops requests from datacenter IPs, so a live
# scrape usually fails from the VPS. This is a hand-verified snapshot of the
# official communiqués used as a fallback — clearly flagged `stale` with an
# `as_of` date and always shown alongside the live source link.
_PREF_FALLBACK_URL = PREF_BASE + PREF_INDEX + "/"
PREF_FALLBACK = {
    "as_of": "2026-07-26",
    "evacuated": ["Saint-Aubin-de-Médoc", "Saint-Médard-en-Jalles", "Martignas-sur-Jalle",
                  "Saint-Jean-d’Illac", "Le Haillan", "Eysines (ext. rocade)",
                  "Mérignac (ext. rocade)", "Marcheprime", "Le Barp", "Biganos", "Mios", "Cestas"],
    "items": [
        {"title": "Incendie de Gironde : point de situation à 2h ce dimanche 26 juillet",
         "date": "2026-07-26", "url": _PREF_FALLBACK_URL + "Incendie-de-Gironde-point-de-situation-a-2h-ce-dimanche-26-juillet"},
        {"title": "Incendie en Gironde : déclenchement de FR-Alert pour l’évacuation des nouvelles communes",
         "date": "2026-07-25", "url": _PREF_FALLBACK_URL + "Incendie-en-Gironde-declenchement-de-FR-Alert-pour-l-evacuation-des-nouvelles-communes"},
        {"title": "FR-Alert pour l’évacuation des communes du Haillan, Eysines ext rocade et Mérignac ext rocade",
         "date": "2026-07-25", "url": _PREF_FALLBACK_URL + "FR-Alert-pour-l-evacuation-des-communes-du-Haillan-Eysines-ext-rocade-et-Merignac-ext-rocade"},
        {"title": "Incendie de Saumos : point de situation à 21h ce samedi 25 juillet",
         "date": "2026-07-25", "url": _PREF_FALLBACK_URL + "Incendie-de-Saumos-point-de-situation-a-21h-ce-samedi-25-juillet"},
        {"title": "Évacuations des communes de Marcheprime, Le Barp, Biganos, Mios, Cestas",
         "date": "2026-07-25", "url": _PREF_FALLBACK_URL + "Evacuations-des-communes-de-Marcheprime-Le-Barp-Biganos-Mios-Cestas"},
        {"title": "Incendie de Saumos : point de situation à 13h ce samedi 25 juillet",
         "date": "2026-07-25", "url": _PREF_FALLBACK_URL + "Incendie-de-Saumos-point-de-situation-a-13h-ce-samedi-25-juillet"},
    ],
}

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


# --------------------------------------------------------------------------- #
# Préfecture de la Gironde — live official communiqués + evacuated communes
# Scrapes the DSFR "communiqués de presse" listing (title + date + link). Best
# effort: any failure returns an empty feed so the panel degrades gracefully to
# its link-out. Titles/URLs are official; the evacuated-commune list is derived
# from evacuation communiqué titles and is advisory (verify at the source).
# --------------------------------------------------------------------------- #
def _pref_cards(page_html):
    titles = re.findall(r'class="fr-card__link"\s+href="([^"]+)"[^>]*>(.*?)</a>', page_html, re.S)
    dates = re.findall(r'fr-card__detail[^>]*>(.*?)</p>', page_html, re.S)
    out = []
    for i, (href, txt) in enumerate(titles):
        title = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt))).strip()
        raw = _html.unescape(re.sub(r"<[^>]+>", " ", dates[i])) if i < len(dates) else ""
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", raw)
        iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
        url = href if href.startswith("http") else PREF_BASE + href
        if title:
            out.append({"title": title, "date": iso, "url": url})
    return out


def fetch_prefecture():
    cached = cache_get("prefecture")
    if cached is not None:
        return cached
    result = {"items": [], "evacuated": [], "source_url": PREF_BASE + PREF_INDEX,
              "updated": _now_epoch()}
    try:
        r = requests.get(PREF_BASE + PREF_INDEX, headers=UA, timeout=15)
        r.raise_for_status()
        pages = [r.text]
        # newest releases live on the last pagination page (list is date-ascending)
        m = re.search(r'fr-pagination__link--last"[^>]*href="([^"]+)"', r.text)
        if m:
            moff = re.search(r"/\(offset\)/(\d+)", _html.unescape(m.group(1)))
            last_off = int(moff.group(1)) if moff else 0
            for off in (last_off, last_off - 10):  # cover same-day bursts
                if off <= 0:
                    continue
                rr = requests.get(f"{PREF_BASE}{PREF_INDEX}/(offset)/{off}", headers=UA, timeout=15)
                if rr.ok:
                    pages.append(rr.text)

        seen, cards = set(), []
        for ph in pages:
            for c in _pref_cards(ph):
                if c["url"] in seen:
                    continue
                seen.add(c["url"])
                cards.append(c)

        fire = [c for c in cards if PREF_KEYWORDS.search(c["title"])]
        fire.sort(key=lambda c: c["date"], reverse=True)

        evac = []
        for c in fire:
            if re.search(r"évacu|evacu", c["title"], re.I):
                mm = _PREF_COMMUNE_RE.search(c["title"])
                if mm:
                    for n in re.split(r",|\bet\b", mm.group(1)):
                        n = n.strip(" .")
                        if n and len(n) < 40 and n.lower() not in [e.lower() for e in evac]:
                            evac.append(n)
            if len(evac) >= 8:
                break

        result["items"] = fire[:6]
        result["evacuated"] = evac[:8]
        result["stale"] = False
    except Exception as exc:  # noqa: BLE001 — degrade to the curated snapshot
        app.logger.warning("prefecture scrape failed: %s", exc)

    if not result["items"]:
        # live source unreachable (bot-protected) — serve the verified snapshot
        result["items"] = PREF_FALLBACK["items"]
        result["evacuated"] = PREF_FALLBACK["evacuated"]
        result["as_of"] = PREF_FALLBACK["as_of"]
        result["stale"] = True

    # short TTL when stale so a source that comes back is picked up quickly
    return cache_set("prefecture", result, 900 if not result.get("stale") else 300)


@app.route("/api/prefecture")
def prefecture():
    return jsonify(fetch_prefecture())


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
