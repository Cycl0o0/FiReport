<script setup lang="ts">
import { ref, reactive, onMounted, watch, computed } from 'vue'
import { useLang } from '~/composables/useLang'

const { lang, toggle, t } = useLang()

// same-origin in prod (nginx proxies /api); override for local dev if needed
const API = ''

// ---- state -----------------------------------------------------------------
const mapEl = ref<HTMLElement | null>(null)
const mapReady = ref(false)
const mapkitError = ref(false)
const days = ref(1) // 1 | 2 | 7
const layers = reactive({ fires: true, danger: false, risk: false })
const stats = ref<any>(null)
const selected = ref<any>(null)
const loading = ref(true)
const lastUpdate = ref<number | null>(null)
const sheet = ref(false) // mobile bottom-sheet expanded state
const prefecture = ref<any>(null) // live préfecture communiqués + evacuated communes

// ---- Gironde wildfire safety notice ---------------------------------------
// Official civil-safety guidance (sapeurs-pompiers / préfecture de la Gironde).
// Bump SAFETY_KEY when the wording changes so a prior dismissal is voided.
const SAFETY_KEY = 'fireport-alert-gironde-2026-07'
const showSafety = ref(false)
const AID_URL = 'https://www.bordeaux-metropole.fr/actualites/incendies-en-gironde-accueil-personnes-evacuees-collecte-dons'
const L = (o: { fr: string; en: string }) => o[lang.value]

const safety = {
  badge:   { fr: 'Incendie exceptionnel', en: 'Exceptional wildfire' },
  region:  { fr: 'Gironde · vigilance noire', en: 'Gironde · black-level alert' },
  title:   { fr: 'Les bons réflexes', en: 'The right reflexes' },
  intro:   {
    fr: 'Un feu de forêt majeur touche l’ouest de la Gironde. Voici les consignes officielles de sécurité.',
    en: 'A major wildfire is hitting western Gironde. Here are the official safety instructions.',
  },
  do_h:    { fr: 'À faire', en: 'Do' },
  dont_h:  { fr: 'À éviter', en: 'Avoid' },
  do: [
    { fr: 'Se confiner : fermer portes, fenêtres et volets, boucher les aérations.', en: 'Shelter inside: close doors, windows and shutters, block air vents.' },
    { fr: 'Respirer à travers un linge humide face aux fumées.', en: 'Breathe through a damp cloth against the smoke.' },
    { fr: 'Écouter France Bleu Gironde (100.1 FM) et les alertes FR-Alert.', en: 'Tune to France Bleu Gironde (100.1 FM) and FR-Alert warnings.' },
    { fr: 'Dégager les accès et se signaler aux secours si vous êtes isolé.', en: 'Keep access clear and signal to rescuers if you are cut off.' },
    { fr: 'Préparer un sac : papiers, médicaments, eau, lampe, chargeur.', en: 'Pack a go-bag: ID, medication, water, torch, charger.' },
  ],
  dont: [
    { fr: 'Ne pas prendre la route sans consigne : vous gêneriez les secours.', en: 'Don’t drive off without instruction — you would block the rescue services.' },
    { fr: 'Ne pas aller chercher les enfants à l’école : ils y sont protégés.', en: 'Don’t collect children from school — they are protected there.' },
    { fr: 'Ne pas téléphoner sauf urgence vitale : les réseaux sont saturés.', en: 'Don’t phone except for a life-threatening emergency — networks are saturated.' },
    { fr: 'Ne pas s’approcher du feu ni des zones sinistrées.', en: 'Don’t go near the fire or the affected areas.' },
    { fr: 'Aucune flamme, cigarette ou barbecue à proximité.', en: 'No flame, cigarette or barbecue nearby.' },
  ],
  emergency:    { fr: 'Numéros d’urgence', en: 'Emergency numbers' },
  em_fire:      { fr: 'Pompiers', en: 'Fire brigade' },
  em_eu:        { fr: 'Urgences (UE)', en: 'Emergencies (EU)' },
  em_deaf:      { fr: 'SMS sourds/malentendants', en: 'SMS deaf / hard of hearing' },
  aid_cta:      { fr: 'Accueil des évacués & dons', en: 'Evacuee support & donations' },
  source:       { fr: 'Consignes : préfecture de la Gironde', en: 'Guidance: Gironde prefecture' },
  close:        { fr: 'J’ai compris', en: 'Got it' },
  reopen:       { fr: 'Sécurité', en: 'Safety' },
}

function openSafety() { showSafety.value = true }
function closeSafety() {
  showSafety.value = false
  try { localStorage.setItem(SAFETY_KEY, '1') } catch { /* ignore */ }
}

let map: any = null
let fireOverlays: any[] = []
let effisOverlay: any = null
let riskOverlays: any[] = []
let firesCache: any = null

const RISK_COLORS = ['#3f3f46', '#22c55e', '#eab308', '#f97316', '#ef4444'] // idx 0..4

// ---- helpers ---------------------------------------------------------------
async function api(path: string) {
  const r = await fetch(API + path)
  if (!r.ok) throw new Error(path + ' ' + r.status)
  return r.json()
}

function fmtTime(epoch: number | null) {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleTimeString(lang.value === 'fr' ? 'fr-FR' : 'en-GB', {
    hour: '2-digit', minute: '2-digit',
  })
}

// ---- MapKit bootstrap ------------------------------------------------------
function waitForMapKit(): Promise<any> {
  return new Promise((resolve, reject) => {
    let tries = 0
    const id = setInterval(() => {
      if ((window as any).mapkit && (window as any).mapkit.init) {
        clearInterval(id); resolve((window as any).mapkit)
      } else if (++tries > 120) { clearInterval(id); reject(new Error('mapkit-timeout')) }
    }, 100)
  })
}

async function initMap() {
  let mapkit: any
  try {
    mapkit = await waitForMapKit()
  } catch {
    mapkitError.value = true; return
  }

  mapkit.init({
    authorizationCallback: (done: (t: string) => void) => {
      fetch(API + '/api/mapkit-token')
        .then((r) => r.json())
        .then((d) => { if (d.token) done(d.token); else mapkitError.value = true })
        .catch(() => { mapkitError.value = true })
    },
    language: lang.value,
  })

  try {
    map = new mapkit.Map(mapEl.value, {
      mapType: mapkit.Map.MapTypes.Hybrid, // satellite + labels
      showsCompass: mapkit.FeatureVisibility.Hidden,
      showsZoomControl: true,
      showsMapTypeControl: false,
      colorScheme: mapkit.Map.ColorSchemes.Dark,
      isRotationEnabled: false,
    })
    map.region = new mapkit.CoordinateRegion(
      new mapkit.Coordinate(46.6, 2.6),
      new mapkit.CoordinateSpan(9.5, 13),
    )
    map.addEventListener('select', (e: any) => {
      const item = e.overlay || e.annotation
      if (item && item.data && item.coordinate) {
        selected.value = { ...item.data, lat: item.coordinate.latitude, lon: item.coordinate.longitude }
      }
    })
    map.addEventListener('deselect', () => { selected.value = null })
    // keep fire dots a roughly constant on-screen size across zoom levels
    map.addEventListener('region-change-end', rescaleFires)
    mapReady.value = true
  } catch (err) {
    mapkitError.value = true
    return
  }

  await refreshFires()
  applyEffis()
  if (layers.risk) await loadRisk()
}

// ---- FIRMS fire detections -------------------------------------------------
// Rendered as canvas CircleOverlays (geographic) — these are painted with the
// map so they never drift during zoom gestures (annotations, DOM or native, do
// drift here with ~hundreds of points). Geographic circles would bloat on zoom,
// so we rescale each circle's metre-radius on every zoom-end to keep a roughly
// constant on-screen size.
function metersPerPixel() {
  const r = map.region
  const w = mapEl.value?.clientWidth || window.innerWidth || 1
  const latRad = (r.center.latitude * Math.PI) / 180
  return (r.span.longitudeDelta * 111320 * Math.cos(latRad)) / w
}

function targetRadiusM(frp: number, mpp: number) {
  const px = Math.max(5, Math.min(12, 4 + Math.sqrt(frp || 1) * 0.9)) // on-screen px
  return px * mpp
}

const isMobile = () => (typeof window !== 'undefined' && window.innerWidth < 768)
const MOBILE_CAP = 200 // cap rendered fires on phones (Safari canvas perf)
let lastSpan = 0

function makeFireOverlay(feature: any) {
  const mapkit = (window as any).mapkit
  const [lon, lat] = feature.geometry.coordinates
  const p = feature.properties
  const hot = p.confidence === 'high' || (p.frp || 0) > 20
  const style = new mapkit.Style({
    lineWidth: 0, // no stroke — cheaper per circle on mobile
    fillColor: hot ? '#ef4444' : '#fb923c',
    fillOpacity: 0.82,
  })
  return new mapkit.CircleOverlay(new mapkit.Coordinate(lat, lon), 3000, { style, data: p })
}

// rescale only when the zoom actually changed — region-change-end also fires on
// pans, and rescaling 200+ overlays on every pan is what made Safari lag
function rescaleFires() {
  if (!map || !fireOverlays.length) return
  const span = map.region.span.longitudeDelta
  if (lastSpan && Math.abs(span - lastSpan) / lastSpan < 0.02) return
  lastSpan = span
  const mpp = metersPerPixel()
  for (const ov of fireOverlays) ov.radius = targetRadiusM(ov.data?.frp || 1, mpp)
}

function addFireOverlays(fc: any) {
  let feats = fc.features
  if (isMobile() && feats.length > MOBILE_CAP) {
    feats = [...feats].sort((a: any, b: any) => (b.properties.frp || 0) - (a.properties.frp || 0)).slice(0, MOBILE_CAP)
  }
  lastSpan = 0 // force a rescale pass for the fresh overlays
  fireOverlays = feats.map(makeFireOverlay)
  if (fireOverlays.length) map.addOverlays(fireOverlays)
  rescaleFires()
}

async function refreshFires() {
  if (!map) return
  loading.value = true
  try {
    const fc = await api(`/api/fires?days=${days.value}`)
    firesCache = fc
    if (fireOverlays.length) { map.removeOverlays(fireOverlays); fireOverlays = [] }
    if (layers.fires) addFireOverlays(fc)
    lastUpdate.value = fc.updated
  } catch (e) { /* keep previous */ }
  loading.value = false
}

function toggleFiresLayer() {
  if (!map || !firesCache) return
  if (layers.fires) addFireOverlays(firesCache)
  else if (fireOverlays.length) { map.removeOverlays(fireOverlays); fireOverlays = [] }
}

// ---- EFFIS fire-danger tile overlay ----------------------------------------
function applyEffis() {
  if (!map) return
  const mapkit = (window as any).mapkit
  if (layers.danger) {
    if (!effisOverlay) {
      effisOverlay = new mapkit.TileOverlay(`${API}/api/effis/{z}/{x}/{y}.png`, { opacity: 0.55 })
    }
    map.addTileOverlay(effisOverlay)
  } else if (effisOverlay) {
    map.removeTileOverlay(effisOverlay)
  }
}

// ---- Météo des forêts department risk choropleth ---------------------------
function buildRiskOverlays(geojson: any) {
  const mapkit = (window as any).mapkit
  const out: any[] = []
  for (const f of geojson.features) {
    const lvl = f.properties.niveau || 0
    if (!lvl) continue
    const style = new mapkit.Style({
      lineWidth: 0.6,
      strokeColor: '#000000',
      strokeOpacity: 0.25,
      fillColor: RISK_COLORS[lvl] || RISK_COLORS[0],
      fillOpacity: 0.32,
    })
    const geom = f.geometry
    const polys = geom.type === 'MultiPolygon' ? geom.coordinates : [geom.coordinates]
    for (const poly of polys) {
      const rings = poly.map((ring: number[][]) =>
        ring.map(([lon, lat]) => new mapkit.Coordinate(lat, lon)))
      const ov = new mapkit.PolygonOverlay(rings, { style, data: f.properties })
      out.push(ov)
    }
  }
  return out
}

async function loadRisk() {
  if (!map) return
  try {
    if (!riskOverlays.length) {
      const gj = await api('/api/risk')
      if (gj.features) riskOverlays = buildRiskOverlays(gj)
    }
    map.addItems(riskOverlays)
  } catch (e) { /* ignore */ }
}

function toggleRiskLayer() {
  if (!map) return
  if (layers.risk) loadRisk()
  else if (riskOverlays.length) map.removeItems(riskOverlays)
}

// ---- stats -----------------------------------------------------------------
async function loadStats() {
  try { stats.value = await api('/api/stats') } catch (e) { /* ignore */ }
}

async function loadPrefecture() {
  try { prefecture.value = await api('/api/prefecture') } catch (e) { /* keep previous */ }
}

function prefDate(iso: string) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return d && m ? `${d}/${m}` : iso
}

// ---- reactions -------------------------------------------------------------
watch(days, () => { refreshFires(); loadStats() })
watch(() => layers.fires, toggleFiresLayer)
watch(() => layers.danger, applyEffis)
watch(() => layers.risk, toggleRiskLayer)

const periodLabel = computed(() => (days.value === 1 ? '24h' : days.value === 2 ? '48h' : '7d'))

onMounted(async () => {
  try { if (!localStorage.getItem(SAFETY_KEY)) showSafety.value = true } catch { showSafety.value = true }
  loadPrefecture()
  await loadStats()
  await initMap()
  // periodic refresh every 5 min
  setInterval(() => { refreshFires(); loadStats(); loadPrefecture() }, 300000)
})
</script>

<template>
  <div class="relative h-[100dvh] w-full overflow-hidden bg-[#07060a]">
    <!-- Map -->
    <div ref="mapEl" class="absolute inset-0 z-0"></div>

    <!-- ambient glows (desktop only — blur is GPU-heavy on mobile Safari) -->
    <div class="pointer-events-none absolute inset-0 z-0 hidden md:block">
      <div class="ambient-glow absolute left-1/4 top-1/4 h-96 w-96 rounded-full bg-amber-500/10 blur-[120px]"></div>
      <div class="ambient-glow absolute bottom-1/4 right-1/4 h-96 w-96 rounded-full bg-red-500/10 blur-[120px]" style="animation-delay:-4s"></div>
    </div>

    <!-- Header -->
    <header class="absolute left-1/2 top-3 z-40 flex max-w-[calc(100vw-1rem)] -translate-x-1/2 items-center gap-2 rounded-full glass px-3 py-2 md:top-4 md:gap-3 md:px-5 md:py-2.5">
      <div class="flex items-center gap-2 md:gap-2.5">
        <div class="rounded-lg bg-gradient-to-br from-amber-500/30 to-red-500/30 p-1.5">
          <svg viewBox="0 0 32 32" class="h-5 w-5"><path fill="#fb923c" d="M16 4c1.6 3.4.4 5.6-1.4 7.6-1.9 2.1-4.2 4.3-4.2 7.7A5.6 5.6 0 0 0 16 25a5.6 5.6 0 0 0 5.6-5.7c0-1.7-.7-3-1.5-4.2.2 1.4-.4 2.6-1.3 3.1.6-2.2-.3-4.4-1.7-6.2C15.4 9.8 14.8 6.7 16 4z"/></svg>
        </div>
        <div class="leading-tight">
          <h1 class="text-sm font-extrabold tracking-tight text-amber-50 md:text-base">Fi<span class="text-amber-400">R</span>eport</h1>
          <p class="hidden text-[10px] text-amber-200/60 sm:block">{{ t('tagline') }}</p>
        </div>
      </div>
      <div class="hidden h-7 w-px bg-amber-500/20 sm:block"></div>
      <div class="flex items-center gap-1.5 rounded-full bg-red-500/15 px-2.5 py-1 md:gap-2 md:px-3">
        <span class="relative flex h-2 w-2">
          <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
          <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
        </span>
        <span class="whitespace-nowrap text-xs font-semibold text-red-200">
          {{ stats ? stats.active_24h : '—' }} <span class="hidden sm:inline">{{ t('active_fires') }}</span>
        </span>
      </div>
      <button @click="toggle"
              class="rounded-full border border-amber-500/30 px-2.5 py-1 text-xs font-semibold text-amber-100 transition hover:bg-amber-500/15">
        {{ lang === 'fr' ? 'EN' : 'FR' }}
      </button>
    </header>

    <!-- Left control column (desktop) -->
    <div class="absolute left-4 top-20 z-20 hidden max-h-[calc(100dvh-6rem)] w-64 space-y-2.5 overflow-y-auto scroll-thin md:block">
    <div class="rounded-2xl glass p-4">
      <h2 class="mb-3 flex items-center gap-2 text-sm font-bold text-amber-50">
        <svg class="h-4 w-4 text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/></svg>
        {{ t('layers') }}
      </h2>
      <div class="space-y-2.5">
        <label v-for="l in [['fires','layer_fires','#fb923c'],['danger','layer_danger','#f97316'],['risk','layer_risk','#22c55e']]"
               :key="l[0]"
               class="flex cursor-pointer items-center justify-between">
          <span class="flex items-center gap-2 text-sm" :class="(layers as any)[l[0]] ? 'text-amber-50' : 'text-amber-200/40'">
            <span class="h-2.5 w-2.5 rounded-full" :style="{ background: (layers as any)[l[0]] ? (l[2] as string) : 'transparent', boxShadow: (layers as any)[l[0]] ? `0 0 6px ${l[2]}` : 'none', border: '1px solid '+l[2] }"></span>
            {{ t(l[1] as string) }}
          </span>
          <input type="checkbox" v-model="(layers as any)[l[0]]" class="peer sr-only">
          <span class="relative h-4 w-8 rounded-full bg-white/15 transition peer-checked:bg-amber-500/80">
            <span class="absolute left-0.5 top-0.5 h-3 w-3 rounded-full bg-white transition" :class="(layers as any)[l[0]] ? 'translate-x-4' : ''"></span>
          </span>
        </label>
      </div>

      <div class="mt-4 border-t border-amber-500/20 pt-3">
        <h3 class="mb-2 flex items-center gap-2 text-sm font-bold text-amber-50">
          <svg class="h-4 w-4 text-amber-400" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
          {{ t('period') }}
        </h3>
        <div class="grid grid-cols-3 gap-1.5">
          <button v-for="opt in [[1,'p_24h'],[2,'p_48h'],[5,'p_7d']]" :key="opt[0]"
                  @click="days = opt[0] as number"
                  class="rounded-lg px-2 py-1.5 text-xs font-semibold transition"
                  :class="days === opt[0] ? 'bg-amber-500/80 text-black' : 'bg-white/5 text-amber-200/70 hover:bg-white/10'">
            {{ t(opt[1] as string) }}
          </button>
        </div>
      </div>
    </div>

    <!-- Préfecture live feed (desktop) -->
    <div class="rounded-2xl glass p-4">
      <div class="mb-2.5 flex items-center justify-between gap-2">
        <h2 class="flex items-center gap-1.5 text-sm font-bold text-amber-50">
          <span v-if="prefecture && !prefecture.stale" class="relative flex h-2 w-2">
            <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
            <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
          </span>
          {{ t('pref_title') }}
        </h2>
        <span v-if="prefecture" class="shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide"
              :class="prefecture.stale ? 'bg-amber-500/15 text-amber-300' : 'bg-red-500/15 text-red-300'">
          {{ prefecture.stale ? `${t('pref_snapshot')} ${prefDate(prefecture.as_of)}` : t('pref_live') }}
        </span>
      </div>

      <template v-if="prefecture && prefecture.items && prefecture.items.length">
        <div v-if="prefecture.evacuated && prefecture.evacuated.length" class="mb-3">
          <p class="mb-1.5 text-[11px] font-semibold text-orange-300">{{ t('pref_evac') }}</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="c in prefecture.evacuated" :key="c"
                  class="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[10px] font-medium text-red-100">{{ c }}</span>
          </div>
          <p class="mt-1.5 text-[9px] leading-tight text-amber-200/40">{{ t('pref_evac_note') }}</p>
        </div>

        <p class="mb-1.5 text-[11px] font-semibold text-amber-200/70">{{ t('pref_updates') }}</p>
        <ul class="space-y-2">
          <li v-for="(it, i) in prefecture.items" :key="i">
            <a :href="it.url" target="_blank" rel="noopener" class="group flex gap-2">
              <span class="mt-px shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[9px] font-semibold tabular-nums text-amber-200/70">{{ prefDate(it.date) }}</span>
              <span class="line-clamp-2 text-[11px] leading-snug text-amber-50/85 transition group-hover:text-amber-50">{{ it.title }}</span>
            </a>
          </li>
        </ul>
        <a :href="prefecture.source_url" target="_blank" rel="noopener"
           class="mt-2.5 inline-flex items-center gap-1 text-[10px] font-semibold text-amber-300 transition hover:text-amber-200">{{ t('pref_all') }} →</a>
      </template>
      <p v-else class="text-[11px] leading-snug text-amber-200/50">
        {{ t('pref_empty') }}
        <a :href="(prefecture && prefecture.source_url) || 'https://www.gironde.gouv.fr/'" target="_blank" rel="noopener"
           class="text-amber-300 underline transition hover:text-amber-200">{{ t('pref_source') }} →</a>
      </p>
    </div>
    </div>

    <!-- Right stat cards (desktop) -->
    <div class="absolute right-4 top-20 z-20 hidden w-60 space-y-2.5 md:block">
      <div class="relative overflow-hidden rounded-xl glass p-3.5">
        <p class="text-[11px] font-medium text-amber-200/60">{{ t('stat_active') }}</p>
        <p class="text-2xl font-bold text-amber-50">{{ stats ? stats.active_24h : '—' }}</p>
      </div>
      <div class="rounded-xl glass p-3.5">
        <p class="text-[11px] font-medium text-amber-200/60">{{ t('stat_week') }}</p>
        <p class="text-2xl font-bold text-amber-50">{{ stats ? stats.active_5d : '—' }}</p>
      </div>
      <div class="rounded-xl glass p-3.5">
        <p class="text-[11px] font-medium text-amber-200/60">{{ t('stat_high') }}</p>
        <p class="text-2xl font-bold text-orange-300">{{ stats ? stats.high_risk_departments : '—' }}<span v-if="stats && stats.extreme_risk_departments" class="ml-1 text-sm text-red-400">({{ stats.extreme_risk_departments }} ⚠)</span></p>
      </div>
      <div class="rounded-xl glass p-3.5">
        <p class="text-[11px] font-medium text-amber-200/60">{{ t('stat_maxfrp') }}</p>
        <p class="text-2xl font-bold text-amber-50">{{ stats ? stats.max_frp : '—' }} <span class="text-xs font-normal text-amber-200/50">MW</span></p>
      </div>
    </div>

    <!-- Legend (desktop, bottom-right) -->
    <div class="absolute bottom-16 right-4 z-20 hidden rounded-xl glass p-3 md:block">
      <h3 class="mb-2 text-[11px] font-bold text-amber-50">{{ layers.risk ? t('legend_risk') : t('legend_fires') }}</h3>
      <div v-if="!layers.risk" class="flex items-center gap-2">
        <span class="text-[10px] text-amber-200/70">{{ t('legend_low') }}</span>
        <span class="h-2 w-24 rounded-full" style="background:linear-gradient(90deg,#fb923c,#ef4444,#b91c1c)"></span>
        <span class="text-[10px] text-amber-200/70">{{ t('legend_high') }}</span>
      </div>
      <div v-else class="space-y-1">
        <div v-for="(lab,i) in ['risk_1','risk_2','risk_3','risk_4']" :key="lab" class="flex items-center gap-2">
          <span class="h-3 w-3 rounded" :style="{ background: RISK_COLORS[i+1] }"></span>
          <span class="text-[10px] text-amber-200/80">{{ t(lab) }}</span>
        </div>
      </div>
    </div>

    <!-- Selected detection (bottom-left) -->
    <transition name="fade">
      <div v-if="selected" class="absolute left-2 right-2 top-[4.75rem] z-40 rounded-xl glass p-4 md:left-4 md:right-auto md:top-auto md:bottom-16 md:w-64">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-xs font-bold text-amber-50">{{ t('sel_title') }}</h3>
          <button @click="selected = null" class="text-amber-200/50 hover:text-amber-100">✕</button>
        </div>
        <dl class="space-y-1 text-xs">
          <div class="flex justify-between"><dt class="text-amber-200/60">{{ t('sel_frp') }}</dt><dd class="font-semibold text-amber-50">{{ selected.frp }} MW</dd></div>
          <div class="flex justify-between"><dt class="text-amber-200/60">{{ t('sel_conf') }}</dt><dd class="font-semibold text-amber-50">{{ t('conf_' + selected.confidence) }}</dd></div>
          <div class="flex justify-between"><dt class="text-amber-200/60">{{ t('sel_sat') }}</dt><dd class="font-semibold text-amber-50">{{ selected.instrument }} {{ selected.satellite }}</dd></div>
          <div class="flex justify-between"><dt class="text-amber-200/60">{{ t('sel_when') }}</dt><dd class="font-semibold text-amber-50">{{ selected.acq_date }}</dd></div>
          <div class="pt-1 text-[10px] text-amber-200/40">{{ selected.lat.toFixed(3) }}, {{ selected.lon.toFixed(3) }}</div>
        </dl>
      </div>
    </transition>

    <!-- Footer (desktop) -->
    <footer class="absolute bottom-4 left-1/2 z-30 hidden -translate-x-1/2 items-center gap-3 rounded-full glass px-5 py-2 md:flex">
      <p class="text-xs text-amber-200/80">
        Made with <span class="text-red-400">♥</span> by <span class="font-semibold text-amber-50">Cycl0o0</span>
      </p>
      <span class="h-4 w-px bg-amber-500/20"></span>
      <a href="https://github.com/Cycl0o0/FiReport" target="_blank" rel="noopener"
         class="flex items-center gap-1 text-xs text-amber-200/80 transition hover:text-amber-50" aria-label="Source on GitHub">
        <svg viewBox="0 0 24 24" class="h-3.5 w-3.5 fill-current"><path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.2.8-.5v-1.7c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17 4.6 18 4.9 18 4.9c.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.6.8.5A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5Z"/></svg>
        Source
      </a>
      <span class="h-4 w-px bg-amber-500/20"></span>
      <span class="text-[10px] text-amber-200/50">{{ t('updated') }} {{ fmtTime(lastUpdate) }}</span>
    </footer>

    <!-- loading hint (desktop) -->
    <div v-if="loading && mapReady" class="absolute bottom-4 left-4 z-30 hidden rounded-full glass px-3 py-1 text-[10px] text-amber-200/70 md:block">
      {{ t('loading') }}
    </div>

    <!-- Safety-notice trigger (persistent) -->
    <button
      @click="openSafety"
      class="group absolute left-3 top-3 z-40 flex items-center gap-1.5 rounded-full border border-red-500/40 bg-red-950/50 px-2.5 py-1.5 text-xs font-semibold text-red-100 backdrop-blur-md transition hover:bg-red-900/60 md:left-4 md:top-4 md:px-3 md:py-2"
      :aria-label="L(safety.reopen)"
    >
      <span class="relative flex h-2 w-2">
        <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
        <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
      </span>
      <svg viewBox="0 0 24 24" class="h-3.5 w-3.5 fill-none stroke-current" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
      <span>{{ L(safety.reopen) }}</span>
    </button>

    <!-- ===== Safety notice modal ===== -->
    <transition name="modal">
      <div
        v-if="showSafety"
        class="fixed inset-0 z-[100] flex items-end justify-center bg-black/70 p-3 backdrop-blur-sm sm:items-center sm:p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="safety-title"
        @click.self="closeSafety"
      >
        <div class="safety-card relative flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl">
          <!-- top accent -->
          <div class="h-1 w-full shrink-0" style="background:linear-gradient(90deg,#ef4444,#fb923c,#ef4444)"></div>

          <button
            @click="closeSafety"
            class="absolute right-3 top-3 z-10 grid h-7 w-7 place-items-center rounded-full text-amber-200/60 transition hover:bg-white/10 hover:text-amber-50"
            :aria-label="lang === 'fr' ? 'Fermer' : 'Close'"
          >✕</button>

          <div class="flex-1 overflow-y-auto scroll-thin px-5 py-4 sm:px-6 sm:py-5">
            <!-- header -->
            <div class="flex items-center gap-2">
              <span class="relative flex h-2.5 w-2.5">
                <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-75"></span>
                <span class="relative inline-flex h-2.5 w-2.5 rounded-full bg-red-500"></span>
              </span>
              <span class="text-[11px] font-bold uppercase tracking-wider text-red-300">{{ L(safety.badge) }}</span>
              <span class="text-[11px] font-medium text-amber-200/60">— {{ L(safety.region) }}</span>
            </div>
            <h2 id="safety-title" class="mt-1.5 text-xl font-extrabold tracking-tight text-amber-50">{{ L(safety.title) }}</h2>
            <p class="mt-1 text-sm leading-snug text-amber-100/70">{{ L(safety.intro) }}</p>

            <!-- do / don't -->
            <div class="mt-4 grid gap-3 sm:grid-cols-2">
              <div class="rounded-xl border border-emerald-500/25 bg-emerald-500/[0.07] p-3.5">
                <h3 class="mb-2 flex items-center gap-1.5 text-sm font-bold text-emerald-300">
                  <svg viewBox="0 0 24 24" class="h-4 w-4 fill-none stroke-current" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m20 6-11 11-5-5"/></svg>
                  {{ L(safety.do_h) }}
                </h3>
                <ul class="space-y-1.5">
                  <li v-for="(item, i) in safety.do" :key="'do'+i" class="flex gap-2 text-[13px] leading-snug text-amber-50/90">
                    <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald-400"></span>
                    <span>{{ L(item) }}</span>
                  </li>
                </ul>
              </div>
              <div class="rounded-xl border border-red-500/25 bg-red-500/[0.07] p-3.5">
                <h3 class="mb-2 flex items-center gap-1.5 text-sm font-bold text-red-300">
                  <svg viewBox="0 0 24 24" class="h-4 w-4 fill-none stroke-current" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                  {{ L(safety.dont_h) }}
                </h3>
                <ul class="space-y-1.5">
                  <li v-for="(item, i) in safety.dont" :key="'dont'+i" class="flex gap-2 text-[13px] leading-snug text-amber-50/90">
                    <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-red-400"></span>
                    <span>{{ L(item) }}</span>
                  </li>
                </ul>
              </div>
            </div>

            <!-- emergency numbers -->
            <div class="mt-3 rounded-xl border border-amber-500/20 bg-white/[0.03] p-3.5">
              <h3 class="mb-2 text-[11px] font-bold uppercase tracking-wider text-amber-200/70">{{ L(safety.emergency) }}</h3>
              <div class="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p class="text-2xl font-extrabold leading-none text-amber-50">18</p>
                  <p class="mt-1 text-[10px] leading-tight text-amber-200/60">{{ L(safety.em_fire) }}</p>
                </div>
                <div class="border-x border-amber-500/15">
                  <p class="text-2xl font-extrabold leading-none text-amber-50">112</p>
                  <p class="mt-1 text-[10px] leading-tight text-amber-200/60">{{ L(safety.em_eu) }}</p>
                </div>
                <div>
                  <p class="text-2xl font-extrabold leading-none text-amber-50">114</p>
                  <p class="mt-1 text-[10px] leading-tight text-amber-200/60">{{ L(safety.em_deaf) }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- footer actions -->
          <div class="flex shrink-0 flex-col gap-2 border-t border-amber-500/15 px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <a
              :href="AID_URL" target="_blank" rel="noopener"
              class="inline-flex items-center justify-center gap-1.5 rounded-full bg-gradient-to-r from-amber-500 to-red-500 px-4 py-2 text-xs font-bold text-black transition hover:brightness-110"
            >
              <span class="text-sm">♥</span> {{ L(safety.aid_cta) }}
            </a>
            <button
              @click="closeSafety"
              class="rounded-full border border-amber-500/30 px-4 py-2 text-xs font-semibold text-amber-100 transition hover:bg-amber-500/15"
            >
              {{ L(safety.close) }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- ===== Mobile bottom sheet ===== -->
    <div class="absolute inset-x-0 bottom-0 z-30 md:hidden">
      <div class="glass rounded-t-2xl px-4 pt-1.5" style="padding-bottom:calc(env(safe-area-inset-bottom) + 0.5rem)">
        <!-- grab handle -->
        <button @click="sheet = !sheet" class="flex w-full flex-col items-center py-1.5" :aria-expanded="sheet">
          <span class="h-1 w-10 rounded-full bg-amber-200/40"></span>
        </button>

        <!-- peek: scrolling stat chips -->
        <div class="scroll-thin flex gap-2 overflow-x-auto pb-1">
          <div class="shrink-0 rounded-xl bg-white/5 px-3 py-1.5">
            <p class="text-[9px] text-amber-200/60">{{ t('stat_active') }}</p>
            <p class="text-lg font-bold leading-tight text-amber-50">{{ stats ? stats.active_24h : '—' }}</p>
          </div>
          <div class="shrink-0 rounded-xl bg-white/5 px-3 py-1.5">
            <p class="text-[9px] text-amber-200/60">{{ t('stat_week') }}</p>
            <p class="text-lg font-bold leading-tight text-amber-50">{{ stats ? stats.active_5d : '—' }}</p>
          </div>
          <div class="shrink-0 rounded-xl bg-white/5 px-3 py-1.5">
            <p class="text-[9px] text-amber-200/60">{{ t('stat_high') }}</p>
            <p class="text-lg font-bold leading-tight text-orange-300">{{ stats ? stats.high_risk_departments : '—' }}</p>
          </div>
          <div class="shrink-0 rounded-xl bg-white/5 px-3 py-1.5">
            <p class="text-[9px] text-amber-200/60">{{ t('stat_maxfrp') }}</p>
            <p class="text-lg font-bold leading-tight text-amber-50">{{ stats ? stats.max_frp : '—' }} <span class="text-[10px] font-normal text-amber-200/50">MW</span></p>
          </div>
        </div>

        <!-- expanded controls -->
        <div v-show="sheet" class="mt-3 space-y-4 pb-1">
          <!-- préfecture live feed -->
          <div v-if="prefecture && prefecture.items && prefecture.items.length" class="rounded-xl border border-red-500/20 bg-red-500/[0.05] p-3">
            <div class="mb-2 flex items-center gap-1.5">
              <span v-if="!prefecture.stale" class="relative flex h-2 w-2">
                <span class="live-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
                <span class="relative inline-flex h-2 w-2 rounded-full bg-red-500"></span>
              </span>
              <h3 class="text-xs font-bold text-amber-50">{{ t('pref_title') }}</h3>
              <span class="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide"
                    :class="prefecture.stale ? 'bg-amber-500/15 text-amber-300' : 'bg-red-500/15 text-red-300'">
                {{ prefecture.stale ? `${t('pref_snapshot')} ${prefDate(prefecture.as_of)}` : t('pref_live') }}
              </span>
            </div>
            <div v-if="prefecture.evacuated && prefecture.evacuated.length" class="mb-2.5">
              <p class="mb-1 text-[10px] font-semibold text-orange-300">{{ t('pref_evac') }}</p>
              <div class="flex flex-wrap gap-1">
                <span v-for="c in prefecture.evacuated" :key="'m'+c"
                      class="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[10px] font-medium text-red-100">{{ c }}</span>
              </div>
            </div>
            <ul class="space-y-1.5">
              <li v-for="(it, i) in prefecture.items.slice(0, 4)" :key="'mp'+i">
                <a :href="it.url" target="_blank" rel="noopener" class="flex gap-2">
                  <span class="mt-px shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[9px] font-semibold tabular-nums text-amber-200/70">{{ prefDate(it.date) }}</span>
                  <span class="line-clamp-2 text-[11px] leading-snug text-amber-50/85">{{ it.title }}</span>
                </a>
              </li>
            </ul>
            <a :href="prefecture.source_url" target="_blank" rel="noopener"
               class="mt-2 inline-flex text-[10px] font-semibold text-amber-300">{{ t('pref_all') }} →</a>
          </div>
          <!-- layers -->
          <div class="space-y-2.5">
            <label v-for="l in [['fires','layer_fires','#fb923c'],['danger','layer_danger','#f97316'],['risk','layer_risk','#22c55e']]"
                   :key="'m'+l[0]" class="flex cursor-pointer items-center justify-between py-0.5">
              <span class="flex items-center gap-2 text-sm" :class="(layers as any)[l[0]] ? 'text-amber-50' : 'text-amber-200/40'">
                <span class="h-2.5 w-2.5 rounded-full" :style="{ background: (layers as any)[l[0]] ? (l[2] as string) : 'transparent', boxShadow: (layers as any)[l[0]] ? `0 0 6px ${l[2]}` : 'none', border: '1px solid '+l[2] }"></span>
                {{ t(l[1] as string) }}
              </span>
              <input type="checkbox" v-model="(layers as any)[l[0]]" class="peer sr-only">
              <span class="relative h-5 w-9 rounded-full bg-white/15 transition peer-checked:bg-amber-500/80">
                <span class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition" :class="(layers as any)[l[0]] ? 'translate-x-4' : ''"></span>
              </span>
            </label>
          </div>
          <!-- period -->
          <div>
            <h3 class="mb-1.5 text-xs font-bold text-amber-200/70">{{ t('period') }}</h3>
            <div class="grid grid-cols-3 gap-1.5">
              <button v-for="opt in [[1,'p_24h'],[2,'p_48h'],[5,'p_7d']]" :key="'m'+opt[0]"
                      @click="days = opt[0] as number"
                      class="rounded-lg py-2 text-sm font-semibold transition"
                      :class="days === opt[0] ? 'bg-amber-500/80 text-black' : 'bg-white/5 text-amber-200/70'">
                {{ t(opt[1] as string) }}
              </button>
            </div>
          </div>
          <!-- legend -->
          <div>
            <h3 class="mb-1.5 text-xs font-bold text-amber-200/70">{{ layers.risk ? t('legend_risk') : t('legend_fires') }}</h3>
            <div v-if="!layers.risk" class="flex items-center gap-2">
              <span class="text-[10px] text-amber-200/70">{{ t('legend_low') }}</span>
              <span class="h-2 flex-1 rounded-full" style="background:linear-gradient(90deg,#fb923c,#ef4444,#b91c1c)"></span>
              <span class="text-[10px] text-amber-200/70">{{ t('legend_high') }}</span>
            </div>
            <div v-else class="grid grid-cols-2 gap-1">
              <div v-for="(lab,i) in ['risk_1','risk_2','risk_3','risk_4']" :key="'m'+lab" class="flex items-center gap-2">
                <span class="h-3 w-3 rounded" :style="{ background: RISK_COLORS[i+1] }"></span>
                <span class="text-[10px] text-amber-200/80">{{ t(lab) }}</span>
              </div>
            </div>
          </div>
          <!-- credit -->
          <div class="flex items-center justify-between border-t border-amber-500/15 pt-2">
            <p class="text-[11px] text-amber-200/80">Made with <span class="text-red-400">♥</span> by <span class="font-semibold text-amber-50">Cycl0o0</span></p>
            <a href="https://github.com/Cycl0o0/FiReport" target="_blank" rel="noopener"
               class="flex items-center gap-1 text-[11px] text-amber-200/80" aria-label="Source on GitHub">
              <svg viewBox="0 0 24 24" class="h-3.5 w-3.5 fill-current"><path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.2.8-.5v-1.7c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17 4.6 18 4.9 18 4.9c.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.6.8.5A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5Z"/></svg>
              Source
            </a>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
.fade-enter-active, .fade-leave-active { transition: opacity .2s, transform .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(8px); }

/* safety modal — a text-heavy panel needs a near-opaque backing over satellite */
.safety-card {
  background: linear-gradient(180deg, rgba(22, 12, 12, 0.97), rgba(10, 8, 12, 0.97));
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(251, 146, 60, 0.22);
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(239, 68, 68, 0.08);
}
.modal-enter-active, .modal-leave-active { transition: opacity .25s ease; }
.modal-enter-active .safety-card, .modal-leave-active .safety-card { transition: opacity .25s ease, transform .25s cubic-bezier(0.16, 1, 0.3, 1); }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-from .safety-card, .modal-leave-to .safety-card { opacity: 0; transform: translateY(16px) scale(0.98); }
@media (prefers-reduced-motion: reduce) {
  .modal-enter-active, .modal-leave-active,
  .modal-enter-active .safety-card, .modal-leave-active .safety-card { transition: none; }
}
</style>
