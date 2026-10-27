# Frame ↔ user journey mapping

Cross-reference between [user journeys](user-journeys.md) and [workspace frames](dialogue-interface.md). Use this to spot **gaps** (journey steps with no UI home) and **redundancies** (overlapping frames to merge or specialize).

**Legend:** **P** = primary surface for that step, **S** = supporting, **—** = not needed, **(C)** = chat panel only (no workspace frame).

---

## Journeys at a glance

| ID | Journey |
|----|---------|
| J1 | Plan & draft |
| J2 | Store, retrieve, edit |
| J3 | Book & confirm |
| J4 | Documents (email / vault) |
| J5 | Pre-trip & packing |
| J6 | On-trip (today) |
| J7 | Disruption & alternatives |
| J8 | After trip & learn |

---

## Matrix: journey step → frames

### J1 — Plan & draft

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 1.1 | New trip, clarifying questions | **(C)**, `interactive_form` **P** | Trip shell may start from shell chrome before thread exists. |
| 1.2 | Itinerary skeleton | `map` **P**, `trip_timeline` **P** | Spatial + day structure together. |
| 1.3 | Ranked options | `diagram` **P**, `interactive_form` **S**, `map` **S** | Comparison table / option cards; map highlights districts. |
| 1.4 | Preference signals | **(C)**, `interactive_form` **S** | Quick taps (“walkable”, thumbs)—could stay chat-only. |
| 1.5 | Save draft | **(C)**, `agent_tasks` **S** | Persist is backend; optional task frame for long saves. |

### J2 — Store, retrieve, edit

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 2.1 | List / find trips | **Shell** ⚠️ | No frame type—trip picker lives outside workspace or needs new frame. |
| 2.2 | Resume trip | `map` **S**, `trip_timeline` **P**, **(C) revisit** **P** | Thread + workspace reload. |
| 2.3 | Edit day / segment | `calendar` **P**, `map` **S**, `trip_timeline` **P** | Drag-reschedule vs list edit—both may update same model. |
| 2.4 | Compare versions | `diagram` **P** (`kind: itinerary_diff`) | Two itinerary version ids from [versioning](../user-journeys.md#itinerary-versioning). |
| 2.5 | Save itinerary vN | **(C)**, `agent_tasks` **S** | Versioning invisible unless agent narrates. |

**Chat panel:** search **P** (J2), fork **S** (explore edits), save snapshot **S**.

### J3 — Book & confirm

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 3.1 | Ready-to-book checklist | ⚠️ **Gap** | Needs booking-oriented surface (see `bookings_board` proposal). |
| 3.2 | Book externally | `interactive_form` **S** (links), **(C)** **P** | Deep links; no payment frame yet. |
| 3.3 | Enter confirmation | `interactive_form` **P**, `file_deposit` **S**, `agent_tasks` **P** | Parse/create booking records. |
| 3.4 | Cancellation deadlines | `trip_timeline` **S**, `calendar` **S**, ⚠️ | Deadlines on segments—easy to miss without booking board. |

### J4 — Documents

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 4.1 | Ingest (forward / upload) | `file_deposit` **P**, `agent_tasks` **P**, **(C)** **S** | Attach in chat feeds deposit. |
| 4.2 | Auto-match bookings | `file_deposit` **P**, `agent_tasks` **S** | Queue: matched vs review. |
| 4.3 | Confirm match | `interactive_form` **P** | Disambiguation. |
| 4.4 | Browse / view docs | ⚠️ **Gap** | Deposit is ingest-heavy; library/viewer not defined (see `document_vault`). |
| 4.5 | Surface doc on travel day | `trip_timeline` **S**, ⚠️ vault **P** | “Today” needs one-tap open PDF. |

### J5 — Pre-trip & packing

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 5.1 | Pre-trip dashboard | ⚠️ **Gap** | Countdown, missing docs, open bookings—no `pre_trip_summary` frame. |
| 5.2 | Enable watches | `alert_config` **P** | |
| 5.3 | 48h weather review | `alerts` **P**, `map` **S**, `diagram` **S** | Impact tags; map for geography. |
| 5.4 | Accept/dismiss hints | **(C)**, `interactive_form` **S** | Preference signals. |
| — | Packing | `packing_list` **P**, `todo_traveler` **S** | Overlap—see redundancies. |

### J6 — On-trip (today)

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 6.1 | Today-only schedule | `trip_timeline` **P** (`scope: today`) | First-class filter, not a separate frame type. |
| 6.2 | Next step + nav | `map` **P**, `trip_timeline` **P**, ⚠️ vault **S** | Doc shortcut from vault gap. |
| 6.3 | Mark done / skipped | `trip_timeline` **P**, `interactive_form` **S** | |
| 6.4 | Serendipity note | **(C)** **P**, `map` **S** | Journal pin could be map event → chat. |

### J7 — Disruption & alternatives

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 7.1 | Alert received | `alerts` **P**, **(C)** **P** | Push opens session; narrative in chat. |
| 7.2 | Impact detail | `alerts` **P**, `trip_timeline` **P**, `diagram` **S** | Knock-on conflicts. |
| 7.3 | Alternatives | `interactive_form` **P**, `map` **S**, `diagram` **P** | 2–3 options with deltas. |
| 7.4 | Commit choice | `interactive_form` **P**, `agent_tasks` **S** | Replan + booking tasks. |
| 7.5 | Dismiss | **(C)** **P** | Learning signal—no frame. |

**Chat panel:** fork **P** when exploring alternatives without losing canonical thread.

### J8 — After trip

| Step | Intent | Frames | Notes |
|------|--------|--------|-------|
| 8.1 | Complete trip | **Shell** / **(C)** **S** | Status change. |
| 8.2 | Feedback | **(C)**, `interactive_form` **P** | Short survey. |
| 8.3 | Clone as template | **(C)** **P**, `trip_timeline` **S** | New J1 thread; optional preview frame. |

**Chat panel:** revisit **P**, search **S**.

---

## Matrix: frame → journeys (coverage)

| Frame | J1 | J2 | J3 | J4 | J5 | J6 | J7 | J8 | Load |
|-------|----|----|----|----|----|----|----|-----|------|
| **(C) chat** | P | P | P | S | S | P | P | P | core |
| `interactive_form` | P | S | P | P | S | S | P | P | core |
| `map` | P | S | — | — | S | P | S | — | core |
| `trip_timeline` | P | P | S | S | S | P | P | S | core |
| `calendar` | — | P | S | — | S | — | S | — | medium |
| `diagram` | P | P | — | — | S | — | P | — | medium |
| `agent_tasks` | S | S | P | P | — | — | S | — | medium |
| `file_deposit` | — | — | S | P | — | — | — | — | medium |
| `alerts` | — | — | — | — | P | S | P | — | medium |
| `alert_config` | — | — | — | — | P | — | S | — | low |
| `packing_list` | — | — | — | — | P | — | — | — | low |
| `todo_traveler` | — | — | — | — | S | S | — | — | low |

Frames with **no primary (P)** row in any journey step: `todo_traveler` (only S), `alert_config` (only P in J5—actually P in J5). `packing_list` only J5.

---

## Chat panel capabilities → journeys

| Capability | Journeys | Role |
|------------|----------|------|
| Message history | all | Primary narrative |
| Search | J2, J4, J8 | Find decisions, confirmations |
| Fork | J2, J7 | What-if without losing canonical plan |
| Save snapshot | J2, J7 | Checkpoints before risky changes |
| Revisit | J2, J8 | Resume or read-only archive threads |

No gap: chat capabilities cover fork/revisit/search across edit and disruption journeys.

---

## Gaps (journey need, no clear frame)

| Gap | Affected journeys | Steps | Proposal |
|-----|-------------------|-------|----------|
| **Trip list / switch trip** | J2, J8 | 2.1, 8.3 | **`trip_board`** (workspace frame) + **drawer**—same API; opened from dialogue (“show my trips”) or chrome. Dialogue-first, not menu-first. |
| **Bookings board** | J3, J5 | 3.1, 3.4, 5.1 | New `bookings_board`: segments by booking status, PNR, cancel-by dates, external links. |
| **Document vault (view)** | J4, J6 | 4.4, 4.5, 6.2 | Extend `file_deposit` with **Ingest \| Library** tabs *or* new `document_vault` frame. |
| **Pre-trip summary** | J5 | 5.1 | New `pre_trip_summary`: countdown, gaps (no doc, no booking), watch status—or agent composes from multiple frames (heavier). |
| *(resolved)* itinerary diff | J2 | 2.4 | **`diagram`** + `itinerary_diff`; versions in domain model. |
| *(resolved)* today | J6 | 6.1 | **`trip_timeline`** + `scope: today`. |

**Severity for MVP (Phase A–B):** trip list (shell), bookings board, document library, timeline+map cover most of J1–J2; J3–J4 stay awkward without bookings board + vault view.

---

## Redundancies & merge candidates

| Overlap | Frames involved | Journeys | Recommendation |
|---------|-----------------|----------|----------------|
| **Day schedule vs month grid** | `trip_timeline`, `calendar` | J2, J3, J5, J6, J7 | Keep both: timeline = **narrative order**, calendar = **time-grid edit**. Share one segment model. Consider **single frame** with view toggle (`list \| week`) later. |
| **User checklists** | `todo_traveler`, `packing_list` | J5, J6 | **Merge:** `packing_list` as template/mode of `todo_traveler`, or one `checklist` frame with `kind: packing \| general`. |
| **Comparison visuals** | `diagram`, `interactive_form` | J1, J7 | Not redundant: diagram = **read-only compare**; form = **commit choice**. Often shown together. |
| **Alerts feed vs config** | `alerts`, `alert_config` | J5, J7 | Paired lifecycle—keep separate (monitor vs setup). |
| **Ingest vs browse docs** | `file_deposit` only | J4 | **Split modes** inside one frame type before adding a second type. |
| **Agent work vs user todos** | `agent_tasks`, `todo_traveler` | J3–J4 vs J5 | Keep separate—different trust model and cancel semantics. |
| **Pre-trip dashboard vs composite** | (gap) vs alerts+timeline+deposit | J5 | Prefer **one** `pre_trip_summary` aggregating APIs over agent opening 4 frames every time. |

---

## Suggested frame catalog v2 (after gap pass)

| Frame | Status |
|-------|--------|
| Existing 11 types | Keep; clarify schemas |
| `bookings_board` | **Add** — J3, J5 |
| `document_vault` | **Add** *or* `file_deposit` dual-mode — J4, J6 |
| `pre_trip_summary` | **Add** — J5 (optional v1: agent stacks existing frames) |
| `trip_board` | **Add** — same data as drawer; invokable from chat (J2, J8) |
---

## Accepted patterns (no extra frame types)

### Today (`trip_timeline`)

On-trip, Alex asks “what’s today?” → agent sets **`trip_timeline`** payload **`scope: today`** (only segments on the local calendar day). Full trip uses `scope: full`. A dedicated `today` frame is **not planned** unless UX outgrows one widget.

### Itinerary versioning + diff

Backend stores **itinerary v1, v2, …** on each material save ([user-journeys.md](user-journeys.md#itinerary-versioning)). Compare in UI via **`diagram`** with **`kind: itinerary_diff`** and two version ids. Revert (if offered) = agent writes a **new** version restoring selected segments, not time travel deleting history.

### Booking checkout — **out of scope**

No in-app payment, wallets, or merchant checkout. J3 = **`bookings_board`** + external links + manual confirmation / **`document_vault`**. Do not design `booking_checkout` frames or PCI paths.

---

## Complexity: what actually ships first

You do **not** build every frame at once. Suggested **conversation MVP** (one trip, one thread):

1. **Chat panel** + search (stub ok)
2. **`map`** + **`trip_timeline`**
3. **`interactive_form`** (clarifying questions)
4. **`trip_board`** / drawer (same backend list)
5. Agent emits frame ops over a single WebSocket

Add **`bookings_board`**, **`document_vault`**, **`pre_trip_summary`**, **`alerts`** when their journeys (J3–J7) start. Deferred items stay payload tricks on existing frames.


---

## Journey coverage scorecard

| Journey | Covered by current catalog? | Blockers |
|---------|----------------------------|----------|
| J1 Plan | **Yes** | — |
| J2 Edit | **Mostly** | Trip list (shell), diff (diagram) |
| J3 Book | **Partial** | No bookings board; deadlines scattered |
| J4 Docs | **Partial** | Ingest yes; library/viewer weak |
| J5 Pre-trip | **Partial** | No summary dashboard; checklist overlap |
| J6 Today | **Yes** | Doc open depends on vault gap |
| J7 Disrupt | **Yes** | — |
| J8 After | **Yes** | Trip list (shell) |

---

## Maintenance

When adding a frame type: update this matrix, [dialogue-interface.md](dialogue-interface.md) catalog, and journey steps in [user-journeys.md](user-journeys.md) if needed.
