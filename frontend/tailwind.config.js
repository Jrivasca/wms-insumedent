/** @type {import('tailwindcss').Config} */
// Sistema visual "control operacional de alta señal": navegación grafito, cian como color de
// interacción, fondo gris muy claro, superficies blancas y color con significado (ámbar =
// advertencia, rojo = error/destructivo, verde = correcto). Los códigos (SKU, ubicaciones,
// folios) van en monoespaciada.
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Color de interacción (cian). `brand` se mantiene por compatibilidad con las
        // pantallas existentes.
        brand: {
          DEFAULT: '#0891b2',
          dark: '#0e7490',
          darker: '#155e75',
          soft: '#ecfeff',
          border: '#a5f3fc',
        },
        // Navegación y áreas de trabajo oscuras.
        graphite: {
          950: '#0b1220',
          900: '#111827',
          800: '#1b2433',
          700: '#2b3648',
          600: '#3f4b60',
          400: '#8b97ab',
          200: '#c9d1de',
        },
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'Liberation Mono', 'monospace'],
      },
      borderRadius: {
        card: '0.625rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.08)',
        raised: '0 4px 12px rgba(16, 24, 40, 0.08)',
        nav: '0 -1px 0 rgba(16, 24, 40, 0.08)',
      },
      spacing: {
        touch: '2.75rem', // 44px: mínimo táctil para pantallas de bodega
      },
    },
  },
  plugins: [],
};
