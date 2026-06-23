# 🔥 FiReport

**Real-time wildfire map for France.** Live satellite fire detections on an Apple MapKit
satellite map, with a fire-weather danger overlay and department-level risk — four official
data sources stitched into one ember-glass dashboard. Bilingual (EN/FR), mobile-ready.

Live: **[fireport.cyclooo.fr](https://fireport.cyclooo.fr)**

## Data sources

| Need | Source |
|---|---|
| Active fire detections (live) | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — VIIRS (NOAA-20/21, S-NPP) + MODIS |
| Fire-weather danger overlay | [EFFIS / Copernicus](https://forest-fire.emergency.copernicus.eu/) — Fire Weather Index (WMS) |
| Department risk (J / J+1) | [Météo-France « Météo des forêts »](https://meteofrance.com/meteo-des-forets) |
| Historical statistics | [BDIFF](https://bdiff.agriculture.gouv.fr/) · [Prométhée](https://www.promethee.com/) |

Base map: **Apple MapKit JS** (satellite / hybrid).

## Architecture

- **Frontend** — Nuxt 3 + Tailwind, static (`nuxt generate`). Single-page dashboard, glassmorphism,
  EN/FR toggle, responsive bottom-sheet on mobile. Fires drawn as canvas `CircleOverlay`s
  (glued to the map, rescaled per zoom to keep a constant on-screen size).
- **Backend** — Flask + gunicorn. Proxies and stitches the data sources, signs the Apple MapKit JS
  token server-side so no secret reaches the client.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/mapkit-token` | Apple MapKit JS ES256 JWT |
| `GET /api/fires?days=1\|2\|5` | FIRMS detections → GeoJSON (NRT range is 1–5 days) |
| `GET /api/effis/{z}/{x}/{y}.png` | EFFIS Fire Weather Index WMS tile (XYZ → WMS proxy) |
| `GET /api/risk` | Météo des forêts department risk choropleth |
| `GET /api/stats` | Live aggregate stats |
| `GET /api/health` | Liveness + which sources are configured |

## Run locally

### Backend

```bash
cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in your own keys
./venv/bin/python app.py      # serves on 127.0.0.1:5004
```

You need:
- a free **NASA FIRMS** map key — https://firms.modaps.eosdis.nasa.gov/api/map_key/
- an **Apple MapKit JS** key (`.p8`) with the *MapKit JS* service enabled and your domain added,
  plus its Key ID and Team ID.

### Frontend

```bash
cd frontend
npm install
npm run dev        # dev server
npm run generate   # static build → .output/public
```

Serve `frontend/.output/public` as static files and reverse-proxy `/api/` to the Flask backend.

## Attribution

Fire data courtesy of **NASA FIRMS**. Fire-weather danger from the **EFFIS / Copernicus** programme.
Department risk from **Météo-France**. This project is not affiliated with or endorsed by any of them.

## License

[GNU AGPL-3.0](LICENSE) © Cycl0o0
