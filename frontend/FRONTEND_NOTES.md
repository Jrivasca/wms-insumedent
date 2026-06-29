# WMS Insumedent — Frontend

React 18 + Vite 5 + TypeScript + TailwindCSS 3 + react-router-dom v6 PWA for the
Insumedent Warehouse Management System. Camera + HID barcode scanning included.

## Run

```bash
cp .env.example .env        # set VITE_API_URL if backend is not on http://localhost:8000
npm install
npm run dev -- --host       # serves on 0.0.0.0:5173
```

Docker (dev container): `docker build -t wms-frontend . && docker run -p 5173:5173 wms-frontend`.
The image runs `npm run dev -- --host 0.0.0.0`. Bind mounts are expected to be handled by compose.

## Verified

- `tsc` (strict) passes clean — `npm run build` succeeds and generates the PWA
  service worker (`sw.js`) + `manifest.webmanifest` via `vite-plugin-pwa`.
- Dev server boots and returns HTTP 200 on port 5173 with `--host`.

## Architecture

- `src/api/http.ts` — axios instance. `baseURL = (VITE_API_URL ?? http://localhost:8000) + /api/v1`.
  Request interceptor attaches `Authorization: Bearer <token>` from `localStorage['wms_token']`.
  Response interceptor: on 401 clears token + user and redirects to `/login` (skips redirect
  when already on `/login` to avoid loops). `errorMessage()` extracts FastAPI-style `detail`.
- `src/api/*.ts` — one typed module per domain (auth, products, inventory, orders, picking,
  packing, warehouses, dispatch, integrations, syncJobs, users), matching the API contract.
- `src/store/auth.ts` — React Context `AuthProvider` + `useAuth()` hook. Persists token under
  `wms_token` and user under `wms_user`. Exposes `login`/`logout`/`refresh`/`currentUser`.
  Helpers `isOperario()` / `isSupervisor()` drive role-based UI. (Written with `createElement`
  so the file stays `.ts`, not `.tsx`.)
- `src/components/BarcodeScanner.tsx` — always-focused, self-refocusing text input for HID
  scanners (fires `onScan` on Enter, clears). "Cámara" toggle uses `@zxing/browser`
  `BrowserMultiFormatReader.decodeFromVideoDevice` (auto-selects back camera). Duplicate reads
  debounced (~1.2s). WebAudio beep + `navigator.vibrate(50)` on each scan. Colored
  border/banner from the `feedback` prop (green/red/yellow). Stream cleaned up on toggle/unmount.
- `src/components/Layout.tsx` — role-aware nav. Supervisor/admin see the full menu; operarios
  (picker/packer/operario) see only "Mis tareas de picking/packing". Responsive sidebar (desktop)
  / hamburger top bar (mobile). Shows current user name/role + logout.
- `src/components/ProtectedRoute.tsx`, `StatusBadge.tsx`, `Async.tsx` (Loading/Error/Empty/PageHeader).
- `src/App.tsx` — all routes wrapped in `ProtectedRoute` + `Layout`. `SupervisorOnly` guard
  redirects operarios away from management routes to `/my/picking`. `/` redirects operarios to
  their tasks and renders the dashboard for supervisors.

## Operario execution screens

- `PickingTaskPage` (`/my/picking/:id`) and `PackingTaskPage` (`/my/packing/:id`) are
  mobile-first with large touch targets. They show the current line, a quantity stepper, the
  scanner, progress bar, full line list with color states (green=complete, red=missing/error,
  yellow=just-completed warning), "marcar faltante" with a mandatory reason modal (picking),
  bulto creation + active-package selection (packing), and complete/partial actions.

## Assumptions / deviations

- API base path `/api/v1` is appended in `http.ts`; `VITE_API_URL` should be the bare origin
  (e.g. `http://localhost:8000`), matching `.env.example`.
- `picking scan` and `packing scan` responses may include the updated `task`. The screens use it
  when present and otherwise re-fetch the task to keep quantities authoritative.
- Scan feedback color: success = green, rejected/error = red; when a line reaches its required
  quantity after an OK scan the banner flips to yellow (warning) as a "line complete" cue.
- `mark-missing` uses the line's `sku` (per contract). Reason is required client-side.
- Inventory adjustment/transfer forms take `product_id` directly (free text) since there is no
  product picker endpoint optimized for it; bodega/ubicación use dropdowns from their lists.
- `assigned_to=me` is sent verbatim for "my tasks" lists, per the contract note.
- Roles treated as operario: `picker`, `packer`, `operario`. Supervisor/management: `admin`,
  `supervisor`. Unknown roles default to the supervisor nav but management routes are still
  guarded by `SupervisorOnly`.
- PWA manifest is defined inline in `vite.config.ts` (vite-plugin-pwa, `registerType: autoUpdate`)
  rather than a hand-written `public/manifest.webmanifest`. `public/icon.svg` is the app icon.
- `tsconfig.node.json` is a `composite` project reference (Vite default) — it intentionally does
  not set `noEmit`, otherwise `tsc -b` errors. `noUnusedLocals`/`noUnusedParameters` are false.
