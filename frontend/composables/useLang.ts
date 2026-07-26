import { useState } from '#app'

export type Lang = 'fr' | 'en'

const DICT: Record<string, { fr: string; en: string }> = {
  tagline:        { fr: 'Feux de forêt · France · temps réel', en: 'Wildfires · France · real-time' },
  live:           { fr: 'EN DIRECT', en: 'LIVE' },
  active_fires:   { fr: 'Feux actifs', en: 'Active fires' },
  layers:         { fr: 'Couches', en: 'Layers' },
  layer_fires:    { fr: 'Détections (FIRMS)', en: 'Detections (FIRMS)' },
  layer_danger:   { fr: 'Indice de danger (EFFIS)', en: 'Fire danger index (EFFIS)' },
  layer_risk:     { fr: 'Risque départemental', en: 'Department risk' },
  period:         { fr: 'Période', en: 'Time range' },
  p_24h:          { fr: '24 h', en: '24h' },
  p_48h:          { fr: '48 h', en: '48h' },
  p_7d:           { fr: '5 j', en: '5d' },
  stat_active:    { fr: 'Feux actifs (24 h)', en: 'Active fires (24h)' },
  stat_week:      { fr: 'Détections (5 j)', en: 'Detections (5d)' },
  stat_high:      { fr: 'Départements à risque élevé', en: 'High-risk departments' },
  stat_maxfrp:    { fr: 'Feu le plus intense (FRP)', en: 'Most intense fire (FRP)' },
  legend_fires:   { fr: 'Intensité du feu', en: 'Fire intensity' },
  legend_low:     { fr: 'Faible', en: 'Low' },
  legend_high:    { fr: 'Élevée', en: 'High' },
  legend_risk:    { fr: 'Risque (Météo des forêts)', en: 'Risk (Météo des forêts)' },
  risk_1:         { fr: 'Faible', en: 'Low' },
  risk_2:         { fr: 'Modéré', en: 'Moderate' },
  risk_3:         { fr: 'Élevé', en: 'High' },
  risk_4:         { fr: 'Très élevé', en: 'Very high' },
  sel_title:      { fr: 'Détection sélectionnée', en: 'Selected detection' },
  sel_frp:        { fr: 'Puissance radiative (FRP)', en: 'Fire radiative power (FRP)' },
  sel_conf:       { fr: 'Confiance', en: 'Confidence' },
  sel_sat:        { fr: 'Satellite', en: 'Satellite' },
  sel_when:       { fr: 'Acquisition', en: 'Acquired' },
  conf_low:       { fr: 'faible', en: 'low' },
  conf_nominal:   { fr: 'nominale', en: 'nominal' },
  conf_high:      { fr: 'élevée', en: 'high' },
  sources:        { fr: 'Sources', en: 'Sources' },
  hist_title:     { fr: 'Historique & stats', en: 'History & stats' },
  hist_note:      { fr: 'Données officielles historiques :', en: 'Official historical data:' },
  updated:        { fr: 'Mis à jour', en: 'Updated' },
  loading:        { fr: 'Chargement…', en: 'Loading…' },
  mapkit_err_t:   { fr: 'Carte Apple indisponible', en: 'Apple map unavailable' },
  mapkit_err_d:   {
    fr: 'Activez « MapKit JS » sur votre clé Apple Maps et ajoutez le domaine du site dans l’Apple Developer portal.',
    en: 'Enable “MapKit JS” for your Apple Maps key and add the site domain in the Apple Developer portal.',
  },
  none_active:    { fr: 'Aucune détection sur la période', en: 'No detection in this period' },
  pref_title:     { fr: 'Préfecture de la Gironde', en: 'Gironde Prefecture' },
  pref_live:      { fr: 'en direct', en: 'live' },
  pref_snapshot:  { fr: 'au', en: 'as of' },
  pref_evac:      { fr: 'Communes évacuées', en: 'Evacuated communes' },
  pref_evac_note: { fr: 'D’après les communiqués — vérifiez auprès des autorités.', en: 'From official releases — verify with the authorities.' },
  pref_updates:   { fr: 'Derniers communiqués', en: 'Latest press releases' },
  pref_all:       { fr: 'Tous les communiqués', en: 'All press releases' },
  pref_source:    { fr: 'Préfecture de la Gironde', en: 'Gironde Prefecture' },
  pref_empty:     { fr: 'Flux momentanément indisponible.', en: 'Feed temporarily unavailable.' },
}

export function useLang() {
  const lang = useState<Lang>('lang', () => 'fr')
  const toggle = () => { lang.value = lang.value === 'fr' ? 'en' : 'fr' }
  const t = (key: string) => {
    const e = DICT[key]
    return e ? e[lang.value] : key
  }
  return { lang, toggle, t }
}
