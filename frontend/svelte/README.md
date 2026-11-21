# FOGG browser frontend (Svelte)

This is FOGG's browser frontend, built with SvelteKit as a static SPA.

Requires Node.js 20+ and npm.

Chat streams can include `evaluation_progress` events with a wave ID, phase and status, and `evaluation_comment` events with a wave ID and display-safe comment. Progress appears alongside tool activity; comments appear above the composer for two seconds. Internal evaluation details and failures are not displayed.

The clear button and `/clear` open a confirmation slider. Completing it deletes the user's conversation via `DELETE /v1/users/{user_id}/messages`; the saved map layout is retained. Map movement is persisted through the layout sync API.

## Run locally

```bash
cd frontend/svelte
npm install
npm run dev
```

The default development port is `8081`. The app reads `AGENT_API_BASE_URL` from the repo root `.env` (default `http://127.0.0.1:18080`) and uses `AGENT_USER_ID` when set (default `fogg-local-user`, the local identity UID). API requests include a bearer token: in development the default is the dummy `fogg-local-dummy-token`. You can override these values in a local `frontend/svelte/.env.local` file:

```dotenv
VITE_AGENT_API_BASE_URL=http://127.0.0.1:18080
VITE_AGENT_USER_ID=fogg-local-user
VITE_AGENT_BEARER_TOKEN=fogg-local-dummy-token
```

These values are embedded in browser code and are not secrets. The dummy token does not authenticate a user; production authentication must obtain a real user token at runtime and use its UID in the API path. Production builds have no default token. The agent's CORS configuration must permit the `Authorization` header. When opening the dev UI from a phone on your LAN, set the API URL to the development computer's LAN address (for example, `http://192.168.1.20:18080`), not `127.0.0.1`; the agent must be reachable from the phone and allow the frontend origin. Use HTTPS endpoints when the deployed site uses HTTPS.

## Build

```bash
npm run check
npm run build
npm run preview
```

This is a SvelteKit static SPA (`ssr = false`) with no server-side rendering. Static builds include an `index.html` fallback for client-side routing. The map uses Leaflet with OSM tiles; route and place overlays can be added through layers without coupling them to chat updates.

Type `/tools` in the composer to inspect tool status, enable or disable configured tools, and provide provider credentials. Tools are grouped by credential pathway: Google Maps, Web Search (`web_search` and `web_extract`), and Local tools. Each group can be toggled together, with individual tool controls inside the group. Credential fields show whether a key is configured but never return its saved value. Provider credentials can be shared by several tools.
