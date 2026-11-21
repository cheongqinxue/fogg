# Travel agent HTTP API (v1)

FastAPI app: `api.app` (package `api/` under [`agent/src/api/`](../agent/src/api/)). Clients call **`/v1/...`** on the **agent** base URL only.

| Context | Base URL (examples) |
|---------|---------------------|
| Host dev (`run-agent-debug.sh`) | `http://127.0.0.1:8080` |
| Docker (`COMPOSE_PORT_AGENT`) | `http://127.0.0.1:18080` |

The Svelte browser client uses `AGENT_API_BASE_URL` (scheme + host + port **without** `/v1`). Bruno collection: [`agent/bruno/FOGG-Agent`](../agent/bruno/FOGG-Agent).

### Identity

User-scoped routes resolve the caller's internal `account_id` from the bearer token.
The path value must match the authenticated account. Layout, chat transcripts, tool
settings, and credentials use that account ID.

In dev and test, `IDENTITY_BACKEND=password` enables the browser onboarding flow.
It issues opaque FOGG session tokens with a 12-hour lifetime. The browser sends
`Authorization: Bearer <access_token>`. `IDENTITY_BACKEND=local` remains an explicit
development stub for callers that use the fixed development account without login.

Google login is disabled in the browser. With `IDENTITY_BACKEND=google`, the
token exchange verifies Google sign-in through the configured Identity Platform
project. It maps the verified issuer and subject to a FOGG account and issues
the same FOGG session token used for password sign-in. The app API checks FOGG
sessions in Postgres, so a provider ID token cannot authenticate an app request.

### Password sign-in and onboarding

| Method | Path | Request and response |
|--------|------|----------------------|
| POST | `/v1/auth/register` | Creates the profile and returns a session with HTTP 201. |
| POST | `/v1/auth/login` | Accepts `email` and `password`. Returns a session with HTTP 200. |
| POST | `/v1/auth/google` | Accepts `{"id_token":"<Identity Platform ID token>"}` in Google mode and returns a FOGG session. |
| GET | `/v1/auth/session` | Returns `{"account_id":"<uuid>"}` for a valid session. |
| DELETE | `/v1/auth/session` | Revokes the supplied bearer session and returns HTTP 204. |

Registration takes `email`, `password` (15–256 characters), `name`,
`home_formatted_address`, and `home_country_code` (ISO two-letter code).
`gender` and `immigration_statuses` are optional. Each immigration entry has
`country_code` and `kind` (`citizenship` or `permanent_resident`).

Registration, password login, and Google exchange return `account_id`,
`access_token`, and `expires_at`.
Passwords are salted and hashed and the server stores session token hashes.

### Implementation tracker

Each row is one deliverable. Check **Agent** when the FastAPI / LangGraph side lands; check **UI** when the browser client handles it. Use `[x]` when done.

| Item | Agent | UI |
|------|:-----:|:---:|
| `GET /v1/health` | [x] | [ ] |
| `GET /v1/tools/status` (tool configuration readiness) | [x] | [x] |
| LangGraph **checkpoint** (path `account_id` → `configurable.thread_id`; Postgres) | [x] | [ ] |
| `POST /v1/users/{account_id}/chat/stream` — `assistant_delta`, `assistant_done` (basic) | [x] | [x] |
| `POST /v1/users/{account_id}/chat/stream` — `tool_call_start` / `tool_call_end` | [x] | [x] |
| Web: true SSE streaming (`fetch` + `ReadableStream`, not buffered) | — | [x] |
| Layout document schema v1 (local cache + thread state) | [x] | [x] |
| `revision` + `layout_hash` generation and compare | [x] | [x] |
| `POST /v1/users/{account_id}/layout/sync` | [x] | [x] |
| `GET /v1/users/{account_id}/layout` (revision / hash only) | [x] | [x] |
| `GET /v1/users/{account_id}/messages` (UI chat restore) | [x] | [x] |
| `DELETE /v1/users/{account_id}/messages` (clear transcript + checkpoints; keep layout) | [x] | [x] |
| `client_context` on `POST /v1/users/{account_id}/chat` (+ stream) | [x] | [x] |
| LLM layout digest from `client_context` + server layout | [x] | — |
| SSE `client_command` (emit) | [x] | [x] |
| Command `map.set_viewport` (apply + validate) | [x] | [x] |
| Confirm agent command via `layout/sync` (`applied`) | [x] | [x] |
| User viewport `proposed_delta` via `layout/sync` (debounced) | [x] | [x] |
| Tool **`map_set_viewport`** → SSE `client_command` only | [x] | — |
| Agent **adjudicates** map moves (no `client_command` without tool) | [x] | — |
| `sync_mode: full` on failure / desync | [ ] | [x] |
| Offline `pending_deltas` queue + reconnect flush | — | [ ] |
| `assistant_done` — `layout_revision` + `layout_hash` | [x] | [x] |
| Reconcile without jarring UI (animated map / panels) | — | [ ] |

## Client boundary

The **browser client must not** call backend services directly (Google Maps, trip store, Postgres, etc.). All product I/O goes **client → agent → backend**. The client keeps a **local layout cache** for instant UI and offline use; the **authoritative layout** for a `account_id` lives on the **agent** (layout store + checkpointer), updated via **`layout/sync`**.

**Map camera:** User gestures **move the client map immediately** and **report** what they did. The **agent** (LLM + tools) decides whether to **command** a new viewport on later turns. **Only** a successful **`map_set_viewport` tool** may emit **`client_command`** (`map.set_viewport`). Do not infer map moves from `tool_call_end` text or silent merge rules alone.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/health` | Liveness |
| `GET` | `/v1/tools/status` | Registered tools and required API-key configuration |
| `PUT` | `/v1/tools/{tool_name}/active` | Enable or disable a tool for the authenticated user |
| `PUT` | `/v1/tools/credentials` | Save or replace encrypted provider API keys for the authenticated user |
| `POST` | `/v1/users/{account_id}/chat` | One full agent turn (blocking) |
| `POST` | `/v1/users/{account_id}/chat/stream` | Same turn, **Server-Sent Events** |
| `POST` | `/v1/users/{account_id}/layout/sync` | Layout reconcile (user/agent deltas or full config) — [ ] Agent · [x] UI |
| `GET` | `/v1/users/{account_id}/layout` | Optional lightweight revision / hash check — [ ] Agent · [x] UI |
| `GET` | `/v1/users/{account_id}/messages` | User/assistant transcript for UI restore — [x] Agent · [x] UI |
| `GET` | `/v1/users/{account_id}/itineraries` | Saved itinerary summaries grouped by trip |
| `DELETE` | `/v1/users/{account_id}/messages` | Clear transcript and LangGraph thread history; preserve layout |

### Saved itineraries

`GET /v1/users/{account_id}/itineraries` returns an object with a `trips`
array. Only trips owned by the authenticated account and having at least one
saved itinerary appear. Each trip includes `trip_id`, `name`, nullable ISO
dates `starts_on` and `ends_on`, nullable `head_itinerary_version_id`, and an
`itineraries` array. Each itinerary has an `itinerary_version_id`, nullable
`name`, and a `status` of `valid`, `broken`, or `superseded`. The selected
version appears first, followed by versions in descending version order.

### Tool readiness

`GET /v1/tools/status` requires the normal bearer authentication and returns `api_server: "ready"` and one row for every registered agent tool. Each row includes its name, description, `active` state, `status`, setup message, and provider credential fields with configured flags. `status` is `"ready"` when required configuration is present, or `"needs_configuration"`. Readiness and activation are separate: users cannot enable a tool until it is ready. Local tools default active; key-backed tools default inactive unless a server environment key already configures them. A saved user key makes the tool ready but leaves it inactive until enabled.

Google Maps tools share one `google_maps` key. Both web tools share the configured Tavily, Exa, and Firecrawl provider keys. Credentials are scoped to the authenticated account, encrypted with the shared KMS helper before Postgres storage, and decrypted only at tool invocation. Saving a provider key again replaces the previous key. Keys are never returned by the API.

Save or replace one or more provider keys with `PUT /v1/tools/credentials`:

```json
{
  "credentials": {
    "google_maps": "<google-maps-key>",
    "tavily": "<tavily-key>"
  }
}
```

The accepted provider names are `google_maps`, `tavily`, `exa`, and `firecrawl`. The response contains only the provider names saved. Enable or disable a tool with `PUT /v1/tools/{tool_name}/active` and body `{"active": true}` or `{"active": false}`. Enabling a tool whose required credentials are missing returns HTTP `409`.

The status endpoint checks configuration only; it does not make billable provider calls or confirm that a provider is currently reachable. `map_set_viewport` and `echo_destination` do not require provider keys.

If the API server cannot be reached, the status endpoint cannot return a response. The UI should show server unavailability from the failed request/network state; it should not infer that every individual tool is misconfigured.

### Thread persistence (LangGraph checkpointer)

**Track:** [x] Agent chat history · [x] layout store

FOGG owns the internal `account_id`. New account chats use it as the value of
LangGraph's `configurable.thread_id`. Earlier conversations retain their existing
checkpoint identifiers so their saved history can still be loaded.

Set **`AGENT_DATABASE_URL`** or **`DATABASE_URL`** (same Postgres as the backend stub in compose). Checkpoint tables are created on startup via `checkpointer.setup()`. FastAPI **`lifespan`** in `api.app` calls `init_checkpointer()` before the graph singleton is built — run the agent via **`uvicorn api.app:app`**, not a bare graph import, so Postgres is wired.

`DELETE /v1/users/{account_id}/messages` removes that user's transcript rows and LangGraph checkpoint thread. It preserves the independent layout row, including the last saved viewport.

---

## Shared layout model

**Track:** [ ] Agent · [x] UI — layout document, `revision`, `layout_hash`

Both sides hold a **layout document** per `account_id` (URL path; stored under the same key in Postgres). The client copy is a **cache** (offline queue, optimistic UI). The server copy is **durable state** (revision/hash/document) used by tools, `client_context`, and digests.

The layout row is independent of chat history. Clearing a conversation does not reset its saved map viewport.

### Document (schema v1)

```json
{
  "schema_version": 1,
  "map": {
    "viewport": {
      "center": { "lat": 1.3521, "lng": 103.8198 },
      "zoom": 11.5
    }
  },
  "chrome": {
    "chat": { "mode": "preview" }
  },
  "workspace": {
    "slots": []
  }
}
```

| Field | Notes |
|-------|--------|
| `schema_version` | Layout JSON shape; bump when breaking |
| `map.viewport` | WGS84 `lat`/`lng`, optional `zoom` |
| `chrome.chat.mode` | `preview` \| `expanded` |
| `workspace.slots` | Future frames / panels (itinerary, etc.) |

### Revision and hash

| Field | Owner | Purpose |
|-------|--------|---------|
| `revision` | Server | Monotonic integer per `account_id`; increments on every accepted sync |
| `layout_hash` | Server | SHA-256 of **canonical** JSON (stable key order); integrity / “am I stale?” |

Clients store `revision` + `layout_hash` with the cached document. On desync, the **client detects** mismatch and calls **`layout/sync`**; the **server responds** with authoritative `revision`, `layout_hash`, and full `layout` when needed.

### Map camera — who does what (v1)

| Actor | Client UI | Agent thread | Canonical `layout` |
|--------|-----------|--------------|-------------------|
| **User pans/zooms** | Map moves at once | No conversation message is added | Debounced `layout/sync` `proposed_delta` persists the current viewport |
| **User sends chat** | — | Normal user message; model sees thread + `client_context` | Unchanged unless sync runs |
| **Agent should focus map** | — | Model calls tool **`map_set_viewport`** | Tool may update server layout when command is accepted |
| **Agent commands UI** | Apply **`client_command`** | Only emitted when **`map_set_viewport`** runs | Confirm with **`layout/sync`** `applied` |

**Adjudication:** The model receives the **current viewport** in each turn's `client_context` digest and decides whether to call **`map_set_viewport`**. It does not receive a history of pans. Policy text lives in **`SYSTEM_PROMPT`** in [`agent/src/master/agent.py`](../agent/src/master/agent.py) (focus inference, when to call the tool vs stay silent). Optional server guard: do not emit `client_command` if the tool’s target viewport is unchanged or invalid.

**`layout/sync`:** Used for debounced user viewport `proposed_delta`, **`applied`** acknowledgements after `client_command`, and **`sync_mode: full`** on desync. Viewport changes update layout only; they do not append conversation messages.

---

## `DELETE /v1/users/{account_id}/messages`

Clears the authenticated user's transcript and LangGraph checkpoint thread while preserving
the layout document and saved viewport. The operation is idempotent. The UI should ask the
user to confirm before calling it.

```json
{
  "cleared": true,
  "transcript_messages_removed": 12,
  "layout_preserved": true
}
```

---

## `POST /v1/users/{account_id}/chat` and `POST /v1/users/{account_id}/chat/stream` — request

**Track:** [x] Agent · [x] UI — accept and send `client_context`

The conversation partition key is the path segment **`account_id`** (not a JSON field). Future auth may derive it from a token instead of the client-supplied path.

```json
{
  "message": "User text for this turn.",
  "client_context": {
    "schema_version": 1,
    "revision": 12,
    "layout_hash": "a3f1…",
    "sync_status": "ok",
    "viewport_summary": {
      "center": { "lat": 1.35, "lng": 103.82 },
      "zoom": 11.5,
      "label": "Singapore"
    },
    "chat": { "mode": "preview" },
    "capabilities": ["map.set_viewport"]
  }
}
```

| Field | Required | Notes |
|-------|----------|--------|
| `message` | yes | Min length 1 |
| `client_context` | no | **Hint** for the model at turn start; not a substitute for `layout/sync` |

### `client_context` and the LLM

**Track:** [x] Agent · — — layout digest injection (system message, `kind: client_context`)

The agent injects a **short digest** from `client_context` + server layout (e.g. current viewport, chat mode, `sync_status`) into harness state / system context — **not** the full layout JSON every turn. The model receives the current viewport, not a history of viewport changes. Legacy synthetic viewport-action messages in old checkpoints are filtered from model input.

| `sync_status` | Meaning for the model |
|---------------|------------------------|
| `ok` | Client reports alignment with last known revision |
| `pending` | Local changes not yet acknowledged (e.g. user pan in flight) |
| `offline` | No sync possible; local cache only |
| `conflict` | Client is realigning after failed or rejected sync |

---

## `POST /v1/users/{account_id}/layout/sync`

**Track:** [x] Agent · [x] UI — endpoint client, throttled user deltas (animated realign [ ] UI)

**Client-initiated** reconcile. The client is responsible for noticing desync; the server returns the **canonical** layout.

### Request — delta (normal path)

After a **user** gesture (debounced):

```json
{
  "client_revision": 12,
  "proposed_delta": {
    "op": "map.set_viewport",
    "source": "user",
    "payload": {
      "center": { "lat": 35.68, "lng": 139.76 },
      "zoom": 10
    }
  }
}
```

Records **where the user is looking** on the server layout; does **not** ask the agent to run a turn.

After **agent** `client_command` (optimistic apply on client):

```json
{
  "client_revision": 12,
  "applied": {
    "command_id": "01jc9x…",
    "ok": true
  }
}
```

Apply failure:

```json
{
  "client_revision": 12,
  "applied": {
    "command_id": "01jc9x…",
    "ok": false,
    "error": "invalid_zoom"
  }
}
```

### Request — full config (failure / hard desync)

When sync fails, `accepted: false`, or client cannot trust partial state:

```json
{
  "sync_mode": "full",
  "client_revision": 12,
  "layout": { /* complete local document, schema v1 */ },
  "layout_hash": "local-sha256-optional",
  "last_error": "timeout",
  "pending_deltas": []
}
```

### Response (always)

```json
{
  "accepted": true,
  "revision": 14,
  "layout_hash": "b7c2…",
  "layout": { /* canonical document */ },
  "reject_reason": null
}
```

| Field | Notes |
|-------|--------|
| `accepted` | `false` if `client_revision` stale or delta rejected |
| `revision` | New server head; client **must** store |
| `layout_hash` | Compare to local cache |
| `layout` | Full doc when client should realign (always on `sync_mode: full` or conflict) |

**UX:** Client applies `layout` with **animation** where possible (map camera, panels). Avoid jarring full-screen swaps except on cold start or explicit reset.

### Offline

**Track:** — · [ ] UI — `pending_deltas` queue and reconnect flush ([ ] Agent to accept batch on sync)

Client queues `proposed_delta` / `applied` in `pending_deltas`. On reconnect, flush queue then call `layout/sync` (batch or `sync_mode: full`). Chat may use `sync_status: offline` until reconcile succeeds.

### Optional `GET /v1/users/{account_id}/layout`

**Track:** [ ] Agent · [x] UI — hash-only poll and desync trigger

Query: `?revision=12`. Response: `{ "revision", "layout_hash" }` only. If hash differs from local, client triggers full `layout/sync` without polling heavy payloads.

---

## `GET /v1/users/{account_id}/messages`

Returns the UI transcript from the independent Postgres conversation-history table. This store is separate from LangGraph checkpoint state: model/tool context can change without changing the persisted user-facing transcript. Only user and completed assistant messages are written; client-context digests and tool messages are excluded.

### Query parameters

| Parameter | Required | Meaning |
|-----------|----------|---------|
| `cursor` | No | Opaque `next_cursor` from the previous response. Fetches the next 50 messages older than that page's oldest message. Omit it to fetch the latest page. |

Malformed cursors return HTTP 400.

The page size is fixed at 50. Messages in every response are ordered **oldest → newest**, ready to append directly to the transcript. The UI requests older pages when the user scrolls to the top.

### Response

```json
{
  "messages": [
    {
      "id": "184",
      "role": "user",
      "text": "Plan a weekend in Tokyo.",
      "timestamp": "2026-11-15T03:20:00+00:00"
    }
  ],
  "has_more": true,
  "next_cursor": "MTg0"
}
```

| Field | Meaning |
|-------|---------|
| `messages[].id` | Stable database message ID, serialized as a string to avoid JavaScript integer precision loss. |
| `messages[].role` | `user` or `assistant`. |
| `messages[].text` | Plain text body. |
| `messages[].timestamp` | UTC timestamp assigned by Postgres when the message is inserted (ISO 8601 with offset). |
| `has_more` | Whether older messages exist before this page. |
| `next_cursor` | Cursor for the next older page; `null` when `has_more` is false. |

An empty transcript returns `{"messages": [], "has_more": false, "next_cursor": null}`. The endpoint does not run the LLM. The UI groups messages by calendar day in `Asia/Singapore` (SGT); timestamps remain UTC in the API.

The table and index are created automatically by the API lifespan at startup (`agent_chat_messages`). On first startup after this change, the API also performs an idempotent one-time backfill of each thread's current user-facing messages from LangGraph checkpoints; existing rows are not duplicated. Legacy messages did not store individual timestamps, so the backfill uses the checkpoint timestamp nearest each message's addition as an approximation. After backfill, transcript reads and new writes use only `agent_chat_messages`. Rebuild/restart the full Compose stack from the repo root with `./scripts/compose-up.sh full --build` to deploy this change.

---

## `POST /v1/users/{account_id}/chat` response

```json
{
  "state": {
    "messages": [ /* LangChain message dicts */ ]
  }
}
```

Messages are JSON objects with `type` (`human` \| `ai` \| `tool`, …) and `data` (including `content`, `tool_calls` when present). Use this shape for debugging. For transcript restore in the product UI, prefer **`GET …/messages`**; for live turns, prefer **`/v1/users/{account_id}/chat/stream`**.

---

## `POST /v1/users/{account_id}/chat/stream` — SSE

- **Response:** `Content-Type: text/event-stream`
- **Frame:** each event is one line `data: <json>` followed by a blank line.

Clients should parse each `data:` line as JSON and branch on **`type`**.

### Event families

| Family | `type` values | Role |
|--------|----------------|------|
| **Assistant** | `assistant_delta`, `assistant_done` | Chat transcript |
| **Tool** | `tool_call_start`, `tool_call_end` | Agent runtime observability |
| **Tool evaluation** | `evaluation_progress`, `evaluation_comment` | Limited-search progress and short judge comment |
| **Client** | `client_command` — [x] Agent · [x] UI | **Agent-initiated** UI ops from **`map_set_viewport` only**; apply + `layout/sync` `applied` |

Assistant and tool events are for **reading** and **debugging**. **`client_command`** is for **agent-requested** map moves only. Do not infer UI commands from `tool_call_end.output` alone. User pans persist through `layout/sync`; they are not SSE events.

### Event types

| `type` | When | Client use |
|--------|------|------------|
| `tool_call_start` | Tool execution started | Show “running tool …” |
| `tool_call_end` | Tool finished | Debug / optional status |
| `evaluation_progress` | Criteria generation or evaluation starts, completes, or fails | Show progress only; failed phases clear silently |
| `evaluation_comment` | A search-results wave has been evaluated | Show only the comment briefly; never display criteria, grade, or internal action |
| `client_command` — [x] Agent · [x] UI | **`map_set_viewport` tool** accepted | Apply on client → `layout/sync` `applied` |
| `assistant_delta` — [x] Agent · [x] UI | Model streamed text token(s) | Append `delta` to assistant bubble |
| `assistant_done` — [x] Agent · [x] UI | Graph finished this user turn | Stop loading; optional layout resync |

### `client_command`

**Track:** [x] Agent · [x] UI — SSE parse, `map.set_viewport`, `layout/sync` confirm

Deltas are patches on the **layout document**, not ad hoc map RPC.

```json
{
  "type": "client_command",
  "command_id": "01jc9x…",
  "base_revision": 12,
  "command": "map.set_viewport",
  "payload": {
    "center": { "lat": 35.6762, "lng": 139.6503 },
    "zoom": 11,
    "label": "Tokyo"
  },
  "source": {
    "tool": "map_set_viewport",
    "run_id": "01a1b6fd-…"
  }
}
```

| Field | Notes |
|-------|--------|
| `command_id` | Idempotency for `layout/sync` `applied` |
| `base_revision` | Apply only if it matches local server revision; else reconcile first |
| `command` | Namespaced: `map.set_viewport`, later `workspace.open_frame`, … |
| `payload` | Command-specific; validate on client |
| `source` | Optional link to tool / `run_id` |

Future commands reuse the same envelope (`map.show_route`, `ui.show_toast`, `workspace.open_frame`, …).

| Command | Agent | UI |
|---------|:-----:|:---:|
| `map.set_viewport` | [x] | [x] |
| `workspace.open_frame` | [ ] | [ ] |
| `map.show_route` | [ ] | [ ] |

### `tool_call_start`

```json
{
  "type": "tool_call_start",
  "name": "echo_destination",
  "arguments": { "name": "Tokyo" },
  "run_id": "01a1b6fd-038b-76ac-8a61-88a6b5a83ef2"
}
```

| Field | Type | Notes |
|-------|------|--------|
| `name` | string | Tool name (LangChain registered name) |
| `arguments` | object | Inputs passed to the tool |
| `run_id` | string \| null | LangGraph run id; pair with matching `tool_call_end` |

### `tool_call_end`

```json
{
  "type": "tool_call_end",
  "name": "echo_destination",
  "arguments": { "name": "Tokyo" },
  "output": "Noted destination: Tokyo",
  "tool_call_id": "call_fotkj0jr",
  "run_id": "01a1b6fd-038b-76ac-8a61-88a6b5a83ef2"
}
```

| Field | Type | Notes |
|-------|------|--------|
| `name` | string | Same tool as start |
| `arguments` | object | Same as start (echo of inputs) |
| `output` | string | Tool return value (message content) |
| `tool_call_id` | string \| null | Model tool call id when available |
| `run_id` | string \| null | Same correlation id as start |

### `evaluation_progress` and `evaluation_comment`

These events are emitted only when a batch contains more limited-concurrency tool calls
than the configured limit. `evaluation_progress` tracks criteria generation (concurrent
with the first tool wave) and judging (after a wave completes). `wave_id` correlates phases
and comments for each wave. Failed phases preserve tool results and fail open to the next
queued tool call.

The limited group is `places_text_search`, `places_search_nearby`, and `web_search`.
`AGENT_LIMITED_TOOL_MAX_CONCURRENCY` controls how many of these run in one wave (default
`1`). Tool-call priorities are positive, unique within a model response, and execute in
ascending order. For an overflowing batch, the local configured chat model creates criteria
once, then grades results after each wave. Grade A stops the queue; otherwise the judge
chooses whether to continue through queued calls or return feedback asking the master to
replan. Criteria-generation or evaluation failures preserve completed results and fail open
to queued calls. `AGENT_TOOL_JUDGE_MAX_ATTEMPTS` defaults to three attempts per judge
operation.

```json
{"type":"evaluation_progress","wave_id":"wave-1","phase":"criteria_generation","status":"started"}
{"type":"evaluation_progress","wave_id":"wave-1","phase":"judging","status":"started"}
{"type":"evaluation_comment","wave_id":"wave-1","comment":"The search found options, but their private bath arrangements still need confirmation."}
```

The browser displays only the short, display-safe `comment`, then fades it after two
seconds. Criteria, grades, continue/replan actions, internal rationale, and raw judge errors
are not part of the UI event payload.

### `assistant_delta`

```json
{
  "type": "assistant_delta",
  "delta": "Hello"
}
```

Only non-empty string chunks are sent. Empty model chunks and non-text graph events are omitted.

### `assistant_done`

**Track:** [x] Agent · [x] UI — `layout_revision` and `layout_hash` on event; client hash check

```json
{
  "type": "assistant_done",
  "layout_revision": 14,
  "layout_hash": "b7c2…"
}
```

| Field | Notes |
|-------|--------|
| `layout_revision` | Optional safety net if client `revision` lags — [x] Agent · [x] UI |
| `layout_hash` | Triggers client `layout/sync` when mismatched — [x] Agent · [x] UI |

Always sent once after the turn completes (including tool loops). Full `layout` in this event is optional; prefer **`layout/sync`** for large payloads.

### Example sequence (tool + map + reply)

**Track:** [x] Agent · [x] UI — end-to-end (`map_set_viewport` + `client_command`)

```
data: {"type":"tool_call_start","name":"map_set_viewport",…}

data: {"type":"client_command","command":"map.set_viewport","command_id":"…","base_revision":12,"payload":{…}}

data: {"type":"tool_call_end","name":"map_set_viewport",…}

data: {"type":"assistant_delta","delta":"Here is Tokyo."}

data: {"type":"assistant_done","layout_revision":13,"layout_hash":"…"}
```

(Client calls `layout/sync` after applying `client_command`; may occur before or after `assistant_done`.)

### Browser client parsing

The Svelte client parses stream events in [`frontend/svelte/src/lib/agent.ts`](../frontend/svelte/src/lib/agent.ts) and keeps layout serialization, hashing, and local persistence in [`frontend/svelte/src/lib/layout.ts`](../frontend/svelte/src/lib/layout.ts).

---

## End-to-end flows (summary)

**Track:** [ ] Agent · [x] UI — full flows below (see master table at top)

**User sends chat**

1. Client reads local cache → `client_context` on `POST /v1/users/{account_id}/chat/stream`.
2. Model sees chat history and the current viewport digest; it may call **`map_set_viewport`**.
3. SSE: **`client_command`** only if that tool ran → client apply → `layout/sync` (`applied`).
4. `assistant_done` optional `layout_revision` / `layout_hash` → resync if mismatched.

**User pans map (no chat)**

1. Update local cache and map immediately.
2. Debounced **`POST …/layout/sync`** `proposed_delta` stores the current viewport in the layout row.
3. Store `revision` / `layout_hash`; no conversation message or `client_command` is added. On the next chat turn the model receives the current viewport only.

**Agent focuses map (during chat)**

1. Tool **`map_set_viewport`** (model decides based on thread + `client_context`).
2. Stream **`client_command`** → client applies camera → **`layout/sync`** `applied`.
3. Model may explain in `assistant_delta` in the same turn.

**Desync**

1. Client compares `revision` / `layout_hash` (or stale `base_revision` on command).
2. Client calls `layout/sync` (`sync_mode: full` on failure).
3. Server returns canonical layout; client animates into place.

---

## CORS

`CORS_ORIGINS` — comma-separated origins or `*` (default). See [`agent/README.md`](../agent/README.md).

## Versioning

All product routes live under **`/v1`**. A future **`/v2`** would be a separate router; do not assume unversioned paths. Layout `schema_version` is independent of HTTP `/v1`.
