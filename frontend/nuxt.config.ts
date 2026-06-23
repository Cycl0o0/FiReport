// https://nuxt.com/docs/api/configuration/nuxt-config
const SITE_URL = 'https://fireport.cyclooo.fr'

export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  devtools: { enabled: false },

  modules: ['@nuxtjs/tailwindcss'],

  css: ['~/assets/css/main.css'],

  ssr: true,

  runtimeConfig: {
    public: { siteUrl: SITE_URL },
  },

  nitro: {
    prerender: {
      crawlLinks: false,
      routes: ['/'],
    },
  },

  app: {
    head: {
      title: 'FiReport — Feux de forêt en France en temps réel',
      htmlAttrs: { lang: 'fr' },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'theme-color', content: '#0a0a0b' },
        { name: 'robots', content: 'index, follow' },
        {
          name: 'description',
          content:
            'FiReport — carte temps réel des feux de forêt en France : détections NASA FIRMS, indice de danger EFFIS, risque Météo des forêts. Real-time France wildfire map.',
        },
        { property: 'og:title', content: 'FiReport — France wildfire monitor' },
        {
          property: 'og:description',
          content: 'Real-time wildfire detections, fire weather danger and department risk for France.',
        },
        { property: 'og:type', content: 'website' },
        { property: 'og:url', content: SITE_URL },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'canonical', href: SITE_URL },
      ],
      script: [
        // Apple MapKit JS (all-in-one) — initialised manually in app.vue once loaded
        { src: 'https://cdn.apple-mapkit.com/mk/5.x.x/mapkit.js', defer: true, crossorigin: 'anonymous' },
      ],
    },
  },
})
