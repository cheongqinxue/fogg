# FOGG browser frontend (Svelte)

This is FOGG's browser frontend, built with SvelteKit as a static SPA.

Requires Node.js 20+ and npm.

## Run locally

```bash
cd frontend/svelte
npm install
npm run dev
```

The default development port is `8081`. The app reads `AGENT_API_BASE_URL` from the repo root `.env` (default `http://127.0.0.1:18080`) and uses `AGENT_USER_ID` when set (default `default`). You can override either value with `VITE_AGENT_API_BASE_URL` and `VITE_AGENT_USER_ID` in a local `frontend/svelte/.env.local` file:

```dotenv
VITE_AGENT_API_BASE_URL=http://127.0.0.1:18080
VITE_AGENT_USER_ID=default
```

These values are public browser configuration, not secrets. When opening the dev UI from a phone on your LAN, set the API URL to the development computer's LAN address (for example, `http://192.168.1.20:18080`), not `127.0.0.1`; the agent must be reachable from the phone and allow the frontend origin. Use HTTPS endpoints when the deployed site uses HTTPS.

## Build

```bash
npm run check
npm run build
npm run preview
```

This is a SvelteKit static SPA (`ssr = false`) with no server-side rendering. Static builds include an `index.html` fallback for client-side routing. The map uses Leaflet with OSM tiles; route and place overlays can be added through layers without coupling them to chat updates.
