import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg', 'push-sw.js'],
      manifest: {
        name: 'Selarix WMS',
        short_name: 'Selarix',
        description: 'Selarix WMS — Warehouse Management System',
        theme_color: '#1e293b',
        background_color: '#0f172a',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          {
            src: 'icon.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        // Push/notificationclick handlers live in a static script the generated
        // service worker imports (keeps the generateSW + autoUpdate setup intact).
        importScripts: ['/push-sw.js'],
      },
    }),
  ],
  server: {
    host: true,
    port: 5173,
  },
});
