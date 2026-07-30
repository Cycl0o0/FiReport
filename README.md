# FiReport

Real-time wildfire map for France: https://fireport.cyclooo.fr

Shows NASA FIRMS fire detections on an Apple MapKit satellite map, with the EFFIS
fire weather index as an overlay and the Météo-France "météo des forêts" risk level
per department. FR/EN, works on mobile.

## Data sources

- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/): active fire detections, VIIRS (NOAA-20/21, S-NPP) + MODIS
- [EFFIS / Copernicus](https://forest-fire.emergency.copernicus.eu/): Fire Weather Index (WMS)
- [Météo-France](https://meteofrance.com/meteo-des-forets): department risk for today / tomorrow
- [BDIFF](https://bdiff.agriculture.gouv.fr/) and [Prométhée](https://www.promethee.com/): historical stats

Base map: Apple MapKit JS (satellite / hybrid).

## Layout

- `frontend/`: Nuxt 3 + Tailwind, built as a static site with `nuxt generate`.
  Fires are drawn as canvas circle overlays, rescaled per zoom so they keep a
  constant on-screen size.
- `backend/`: Flask behind gunicorn. Proxies the data sources and signs the
  Apple MapKit JS token server side so no key reaches the client.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/mapkit-token` | Apple MapKit JS ES256 JWT |
| `GET /api/fires?days=1\|2\|5` | FIRMS detections as GeoJSON (NRT range is 1-5 days) |
| `GET /api/effis/{z}/{x}/{y}.png` | EFFIS FWI tile (XYZ to WMS proxy) |
| `GET /api/risk` | Météo des forêts department risk |
| `GET /api/prefecture` | Préfecture de la Gironde communiqués + evacuated communes |
| `GET /api/stats` | Live aggregate stats |
| `GET /api/health` | Liveness + which sources are configured |

## Running locally

Backend:

```bash
cd backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in your own keys
./venv/bin/python app.py   # 127.0.0.1:5004
```

You need a free NASA FIRMS map key (https://firms.modaps.eosdis.nasa.gov/api/map_key/)
and an Apple MapKit JS key (.p8 with the MapKit JS service enabled and your domain
added, plus its Key ID and Team ID).

Frontend:

```bash
cd frontend
npm install
npm run dev        # dev server
npm run generate   # static build in .output/public
```

Serve `frontend/.output/public` as static files and reverse-proxy `/api/` to the backend.

## Attribution

Fire data courtesy of NASA FIRMS, fire weather from EFFIS / Copernicus, department
risk from Météo-France. Not affiliated with or endorsed by any of them.

## License

[AGPL-3.0](LICENSE)
