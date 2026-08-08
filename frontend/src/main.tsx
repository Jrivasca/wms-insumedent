import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { registerSW } from 'virtual:pwa-register';
import App from './App';
import { AuthProvider } from './store/auth';
import './index.css';

// PWA auto-update. With registerType 'autoUpdate' the new service worker takes
// control (skipWaiting + clientsClaim) and reloads open tabs as soon as a new
// build is detected. Browsers only check for a new SW on navigation, so we also
// poll every minute and whenever the tab regains focus — otherwise an installed
// (standalone) PWA can stay on a stale version after a deploy, which is exactly
// what bit us with the scanner. nginx serves sw.js with Cache-Control: no-cache.
if ('serviceWorker' in navigator) {
  registerSW({
    immediate: true,
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return;
      setInterval(() => registration.update().catch(() => undefined), 60 * 1000);
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') registration.update().catch(() => undefined);
      });
    },
  });
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
