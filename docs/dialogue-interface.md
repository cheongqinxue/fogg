# FOGG — dialogue-first interface model

How we conceptualize the UI so **frontend**, **agent harness**, and **backend** stay aligned. All [user journeys](user-journeys.md) happen **through conversation with the agent**; maps, calendars, and forms are not separate “apps” but **frames** the agent opens in a shared workspace.

**Status:** conceptual (pre-implementation). Bookings initiated purely in dialogue are **future**; this doc still defines the shell they must fit.

---

## Design intent

| Principle | Meaning |
|-----------|---------|
| **Dialogue primary** | User intent enters as messages; the agent responds with text **and** structured UI updates. **Every** complementary surface (drawer, frames, modals) is **invokable from dialogue**—“show my trips”, “open bookings board”—not only from chrome menus. |
| **Persistent context** | Chat history + workspace state = resumable trip planning, not ephemeral chat. |
| **Agent-driven layout** | The agent proposes frames; the user can pin, dismiss, or interact; user actions feed back as events. |
| **Extensible frame catalog** | New surface types (calendar, map, alerts) register without redesigning the shell. |
| **Panel layout evolves** | **v1:** two panels (chat \| workspace). **Later:** N panels, user/agent rearrange. |

---

## Layout (v1)

```text
┌─────────────────────────────────────────────────────────────────┐
│  Trip / session chrome (optional: title, status, sync indicator) │
├──────────────────────┬──────────────────────────────────────────┤
│  CHAT PANEL          │  WORKSPACE PANEL                          │
│  (history only)      │  (display + interaction)                  │
│                      │                                           │
│  scrollable turns    │  ┌─────────────┐  ┌─────────────┐        │
│  user + agent        │  │   frame A   │  │   frame B   │        │
│  search · fork · …   │  │  (e.g. map) │  │ (e.g. cal)  │        │
│                      │  └─────────────┘  └─────────────┘        │
│                      │  [+ agent may add/remove/reorder frames]   │
└──────────────────────┴──────────────────────────────────────────┘
```

- **Chat panel:** only the **message timeline** (no embedded maps or widgets in the transcript long-term—agent *refers* to frames: “See the map on the right”).
- **Workspace panel:** one or more **frames** in a layout the agent (or user) controls.

**Future:** panels become first-class **slots** in a layout graph (e.g. chat top-left, workspace bottom, third panel for raw documents). v1 hard-codes two slots to ship faster.

### Complementary UI (drawer, chrome)—still dialogue-gated

Traditional patterns remain, but they are **second-class visually, not second-class in access**:

| Surface | Role | How dialogue reaches it |
|---------|------|-------------------------|
| **Trip drawer** | Switch/create/archive trips; see status at a glance | User asks or agent suggests → `shell.open_trip_drawer` *or* workspace frame `trip_board` (same data, user/agent choice) |
| **Session chrome** | Trip title, sync, connection | Reflects active trip from thread context |
| **Workspace frames** | Rich work surfaces | Agent `upsert_frame` or user “pin board” via chat command |

**Trip board:** one **domain model** (list of trips + filters), two **presentations**: slide-over drawer (fast switch) and optional **`trip_board` frame** in the workspace when the conversation is *about* comparing or choosing trips (“which trip were we fixing?”). Dialogue stays the spine; drawer/frame are projections.

---

## Core concepts

### Session

A **session** is an ongoing engagement bound to a user (and usually a **Trip**). It owns:

- one active **conversation thread** (or a pointer to it),
- one **workspace** snapshot,
- permissions and provider tokens (scoped server-side).

Sessions are durable: closing the app resumes the same thread + workspace.

### Conversation thread

A **thread** is ordered **turns**:

- **User turn:** text (+ optional attachments, voice later).
- **Agent turn:** streamed text + **side effects** (frame commands, tool calls, task progress).

Threads support:

| Capability | Purpose |
|------------|---------|
| **Search** | Find “when did we pick the hotel in Gion?” across full history. |
| **Fork** | Branch from turn *T* to explore “what if we leave a day earlier?” without destroying the main line. |
| **Save / snapshot** | Named checkpoint (itinerary v3 + workspace layout) for revisit or compare. |
| **Revisit** | Open old thread or fork read-only or continue. |

**Fork model:** new thread id, `parent_thread_id` + `fork_at_turn_id`. Trip may link multiple threads; one marked **canonical** for bookings/docs.

### Workspace

The **workspace** is the right-hand **frame stack or grid**. It is JSON-serializable state, versioned with the thread (or linked by `workspace_revision`).

- Agent emits **frame operations** (add, update, remove, focus, reorder).
- User interactions emit **frame events** (date picked, pin dropped, checkbox toggled) → backend → agent loop.

### Frame

A **frame** is a typed, bounded UI region with its own state schema.

| Field (conceptual) | Description |
|--------------------|-------------|
| `frame_id` | Stable id within workspace. |
| `frame_type` | Registry key, e.g. `map`, `calendar`, `agent_tasks`. |
| `title` | Chrome label. |
| `payload` | Type-specific state (validated schema). |
| `provenance` | `agent` \| `user_pinned` \| `system`. |
| `focus` | Whether this frame receives primary emphasis. |

Frames are **not** general HTML; each type is a **prebuilt Flutter widget** (or web component) + contract.

#### Frame catalog (initial)

| `frame_type` | Role |
|--------------|------|
| `map` | OSM/Google basemap, route/place overlays tied to trip context. |
| `calendar` | Trip date range, segment blocks, drag-reschedule → events. |
| `todo_traveler` | User-facing checklist (packing, “call bank”, user todos)—distinct from agent work. |
| `packing_list` | Specialized list with templates and weather hints. |
| `alerts` | Active/disrupted watches and notifications summary. |
| `alert_config` | Create/edit watches (thresholds, channels, lookahead e.g. 48h weather). |
| `file_deposit` | Upload / forward target / unmatched docs queue; link to bookings. |
| `agent_tasks` | **Agent** background work: “fetching fares”, “parsing email”, progress + cancel. |
| `trip_timeline` | Day-by-day itinerary strip (may merge with calendar later). |
| `diagram` | Static or slow-changing visuals (Mermaid, mode graphs, comparison tables). |
| `interactive_form` | Confirmations, disambiguation (“which of these three hotels?”). |

New types register in a **frame registry** (frontend + backend schema version).

**Journey coverage:** see **[frame-journey-map.md](frame-journey-map.md)** for step-by-step mapping, gaps (`bookings_board`, document library, pre-trip summary), and redundancies (`calendar` vs `trip_timeline`, packing vs todo).

### Panel (future generalization)

A **panel** is a container slot:

- `panel_kind`: `chat` \| `workspace` \| (later) `document`, `debug`, etc.
- `layout`: position/size in split view.
- **Chat panel** hosts exactly one component: **thread viewer** (+ search/fork chrome).
- **Workspace panel** hosts a **frame layout engine** (stack, tabs, or grid).

v1: two fixed panels. v2: **layout profile** stored per user or per trip (“research” vs “on-trip compact”).

---

## Agent ↔ UI protocol (conceptual)

Agent turns produce two streams:

1. **Narrative** — markdown/plain text in chat (streamed).
2. **Workspace ops** — declarative commands applied idempotently where possible.

Example ops (names illustrative):

```text
workspace.upsert_frame { frame_id, frame_type, payload }
workspace.remove_frame   { frame_id }
workspace.focus_frame    { frame_id }
workspace.reorder_frames { frame_ids[] }
```

User actions:

```text
frame.event { frame_id, event_type, payload }  →  agent + persistence
```

**Backend** owns authoritative workspace + thread storage; clients apply ops and optimistic UI; reconcile on reconnect.

**Why split chat vs workspace:** keeps history **searchable and forkable** without scraping embedded widgets; frames hold **structured state** for tools (map camera, selected segment id) that shouldn't be re-parsed from prose.

---

## Mapping journeys to dialogue + frames

| Journey (see [user-journeys.md](user-journeys.md)) | Typical dialogue | Typical frames |
|----------------------------------------------------|------------------|----------------|
| Plan trip | “5 days Kyoto, mid budget” | `map`, `trip_timeline`, `interactive_form` (clarifiers) |
| Edit / store | “Move day 3 temple to afternoon” | `calendar`, `map`, `trip_timeline` |
| Book (later) | “Book the JAL option” | `interactive_form`, `agent_tasks`, `file_deposit` |
| Documents | “Here’s my hotel email” (attach) | `file_deposit`, `agent_tasks` |
| Pre-trip | “What’s weather before hiking day?” | `alerts`, `alert_config`, `calendar` |
| Today | “What’s next?” | `trip_timeline`, `map`, `alerts` |
| Disruption | Agent push + user reply | `alerts`, `map`, `interactive_form` (pick alternative) |

The agent **orchestrates** which frames are visible; the user can **pin** a frame so the agent doesn’t remove it casually.

---

## Backend architecture implications

| Concern | Approach |
|---------|----------|
| **API shape** | Trip-scoped **session API**: send message, SSE/WebSocket for stream, fetch thread pages, fetch/apply workspace revision. |
| **Persistence** | Threads (turns), workspace snapshots, fork metadata, search index (turn text + frame titles). |
| **Agent harness** | `agents/` runs tool loop; tools return **structured results** → mapped to frame ops + chat citations. |
| **Tools vs frames** | Tools = backend capabilities (gmaps, weather, email parse). Frames = user-visible projection of tool results. |
| **Tasks** | Long jobs (email ingest, route matrix) → `agent_tasks` frame + job id; chat gets short summary when done. |
| **Auth** | User identity on every thread/workspace; no frame payload with secrets (API keys stay server-side). |
| **Versioning** | `frame_type` + schema version in payload for forward-compatible clients. |

Avoid: storing only screenshots of UI. Store **frame payloads** and regenerate widgets on load.

---

## Frontend architecture implications (Flutter)

| Concern | Approach |
|---------|----------|
| **Shell** | `DialogueShell`: two-pane layout; panel boundaries fixed in v1. |
| **Chat pane** | `ThreadView` + search/fork/snapshot actions; virtualized list; markdown agent text. |
| **Workspace pane** | `WorkspaceView` + `FrameHost` per type from registry. |
| **State** | Client holds `threadId`, `workspaceRevision`, local cache; merges streamed ops. |
| **Map** | Existing `FoggMap` lives inside `MapFrame`, driven by payload (viewport, overlays). |
| **Extensibility** | `FrameRegistry.register(type, builder, schemaValidator)`. |
| **Platform** | Same shell on web/Android/iOS; workspace layout may collapse to tabs on narrow width (chat \| workspace toggle). |

Responsive rule: **narrow = single visible panel** with toggle; workspace frames still exist in state when hidden.

---

## Chat history: search, fork, save, revisit

| Feature | Behavior |
|---------|----------|
| **Search** | Full-text on user + agent messages; optional filters (date, trip, has booking). Frame titles/types indexed separately. |
| **Fork** | UI: “Branch from here” on a turn → new thread, copy workspace snapshot at that revision (or reset workspace—user choice). |
| **Save** | Named snapshot: `{ thread_checkpoint, workspace_revision, label }` on trip. |
| **Revisit** | Thread list on trip; open read-only or continue; show fork tree lightly (v2). |

Canonical thread for **documents and bookings** should be explicit to avoid split-brain.

---

## Bookings through dialogue (no checkout)

User may say “help me book this” in chat; the agent **does not** capture payment or act as merchant.

- **`bookings_board`**: what’s ready, links out, status, cancel-by dates.
- **`interactive_form`**: record confirmation numbers, choose which segment was booked.
- **`document_vault`** + **`agent_tasks`**: ingest tickets after the fact.

**Out of scope:** in-app checkout, cards, wallets, PCI ([user-journeys.md](user-journeys.md#non-goals-explicit)). Protocol does not reserve `booking_checkout` frame types.

---

## Open decisions

1. **One thread per trip** vs **many threads per trip** (recommend: many with one canonical).
2. **Workspace revision** on every agent op vs batched at end of turn.
3. **User edits frame** (drag calendar block) — immediate persist vs “Apply” batch.
4. **Offline** — which frames work offline (packing list, today timeline) vs agent-required online.
5. **N-panel layout** — config format (JSON layout DSL vs predefined profiles only).

---

## Related docs

- [User journeys & phases](user-journeys.md)
- [AGENTS.md](../AGENTS.md) — repo layout (`frontend/`, `backend/`, future `agents/`)
- [gmaps client](gmaps-client.md) — map **data**; map **frame** consumes backend summaries, not raw keys in client

When implementation starts, add a short **Frame protocol** section to AGENTS.md linking here and listing implemented `frame_type` values.
