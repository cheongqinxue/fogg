# Latency optimization & system performance

How FOGG manages **perceived** and **actual** latency, how we **measure** a baseline before scale bites, and which **tests** (unit → system) tell us how each piece affects the end-to-end experience.

**Related:** [`dialogue-interface.md`](dialogue-interface.md) (async frames, reasoning while work runs), [`domain/domain-model.md`](domain/domain-model.md) (draft/commit, plan topology), [`gmaps-client.md`](gmaps-client.md) (external API cost), [`google-maps-alignment.md`](google-maps-alignment.md).

---

## Goals

1. **User-visible:** Chat and frames stay responsive; heavy work runs **concurrently** and lands in map/diagram/task frames when ready ([anticipatory planning](#anticipatory-and-concurrent-work)).
2. **Engineering:** Fixed **units of work**, **budgets** (p50/p95), and **capacity cliffs** (CPU/RAM/concurrency) documented before production traffic.
3. **System understanding:** Each major component has **targeted tests**; a small **scenario matrix** shows how combinations affect outcomes—not only micro-optimizing Postgres ↔ graph handoff.

---

## System map (what affects the outcome)

End-to-end latency is the sum of independent subsystems. Measure and budget each; do not collapse into a single “API latency” metric.

| Piece | Role in FOGG | Typical bottleneck |
|-------|----------------|-------------------|
| **Client (Svelte/browser)** | Thread UI, frame render, map tiles | Map decode, large GeoJSON, unnecessary DOM/map updates |
| **API / harness** | Auth, orchestration, tool dispatch | Serial tool calls, payload size |
| **LLM** | Dialogue, tool selection | Tokens, round-trips (separate budget from CPU) |
| **Plan store (Postgres v1)** | Entities, edges, commit, reservations | Over-fetch, N+1, unbounded subgraph load |
| **Plan graph port (future)** | Topology traverse, diff, impact | Same bounds as edges; optional secondary graph |
| **Planner / scorer (Python)** | Utility, reordering, patches | RAM if subgraph too large; CPU for search |
| **Background jobs** | Speculative matrix, proposals | Worker concurrency × job memory |
| **gmaps** | Routes, matrix, Places | Network, quota, mock vs real latency |
| **Cache / quota** | Redis or SQLite quota, response cache | Hit rate, stampede on cold cache |
| **Postgres (general)** | Catalog, messages, prefs | Connection pool, slow queries |

**Rule (plan loading):** No user-facing path may load more than **one draft/version edge set** plus **entity rows referenced by those edges** (and explicit small candidate sets for planner). Violations show up as RAM and p95 spikes—test for them.

---

## Units of work

Define scenarios by **workload type** and **graph size** (edge + referenced entity counts).

| Workload | Description | Blocks chat? |
|----------|-------------|--------------|
| **W1 — Light turn** | Read draft/version topology + hydrate entities; no Google | Should not |
| **W2 — Heavy turn** | W1 + small batch of `computeRoutes` / matrix | Ideally stream/reason first |
| **W3 — Speculative job** | Subgraph + planner + matrix (anticipation) | No (background) |
| **W4 — Commit** | Validate home loop, version snapshot, reservation stale scan | Short; user expects wait |
| **W5 — Frame payload** | Build map/timeline/diagram DTO (polylines, ordering) | Partial OK (skeleton first) |

**Size classes (synthetic):**

| Class | Edges (approx.) | Use |
|-------|-----------------|-----|
| **S** | ~30 | Typical trip |
| **M** | ~100 | Stress planning |
| **L** | ~300 | Capacity cliff / abuse guard |

---

## Anticipatory and concurrent work

**Intent:** Optimize **perceived** latency, not only PG→graph conversion.

- **Anticipatory transfer:** From conversation flow (partial slots, accepted suggestions, “what if”), start **cheap** work early (resolve place ids, open draft, cache legs); gate **expensive** work (matrix, full utility) on confidence or one clarifying turn.
- **Dialogue masking:** Quick reply with reasoning + skeleton frames (`map`, `diagram`, `agent_tasks`); patch when jobs complete. Tag jobs with `(thread_id, turn_id, draft_id)`; **discard** stale results if the user pivots.
- **Guardrails:** Cap concurrent speculative jobs per thread; show draft/version on frames so late results do not overwrite a newer fork.

System tests must include **W3 under concurrency** (multiple jobs, discards, frame patch ordering).

---

## Baseline methodology

### Environment record (re-run when this changes)

Document for each baseline run:

- Host: vCPU, RAM, OS
- Postgres version and deployment (local vs managed)
- Python/git SHA, `gmaps` config (mock vs live Google)
- Client: mobile Safari vs mobile Chrome (for E2E later)

### Metrics to collect

| Metric | Where |
|--------|--------|
| Wall time p50/p95 per workload × size | Tests, load runner |
| Process RSS / peak delta per job | Worker during W3 stairs |
| Span breakdown | `plan.load_subgraph`, `gmaps.*`, `planner.*`, `plan.commit` |
| Postgres | `pg_stat_statements` top queries (edge fetch, entity batch) |
| Queue | Job age, concurrency, discard rate |
| gmaps | Quota used, cache hit rate, mock latency tier |

### Concurrency stairs (capacity cliff)

On one worker, run **W3** at sizes S/M with concurrent job count **1 → 5 → 10**. Plot p95 wall time and max RSS. Record max safe concurrency before SLO break—that drives production worker limits.

### Golden budgets (placeholder until first run)

Replace `TBD` after baseline table is filled:

| Workload | Size | p95 server wall (target) |
|----------|------|---------------------------|
| W1 | S | TBD (e.g. &lt; 200 ms) |
| W2 | S | TBD (Google-bound) |
| W3 | S | TBD (non-blocking; e.g. &lt; 30 s) |
| W4 | S | TBD (e.g. &lt; 500 ms) |
| W5 | S | TBD |

Store results in [Baseline results](#baseline-results) (below) or a dated appendix in CI artifacts.

---

## Test strategy (by layer)

Pytest markers today: `unit`, `integration`, `benchmark`, `simulated_google` ([`pyproject.toml`](../pyproject.toml)). Proposed additions for this doc (implement when harness exists):

| Marker | Purpose |
|--------|---------|
| `perf` | Timed scenarios; non-gating in CI unless promoted |
| `system` | Multi-component path (DB + gmaps mock + planner stub) |

### Component tests (what each tells you)

**Postgres / plan store**

- Indexed fetch of edges by `(trip_id, draft_id | version_id)` at S/M/L—assert row counts and p95 from `perf` tests.
- Entity batch `WHERE id = ANY(...)` vs N+1—regression test.
- Commit transaction: version insert + edge snapshot + stale flags—correctness + timing at S.

**Plan graph port (when implemented)**

- Same scenarios via `PlanGraph` API; Postgres adapter vs in-memory fake—planner tests without DB.
- `diff`, `timeline`, `impact` on fixed fixtures—CPU bound; size L optional.

**gmaps**

- Existing: `benchmark`, `simulated_google` ([`AGENTS.md`](../AGENTS.md)—`benchmarks/`).
- Matrix vs single `computeRoutes`—separate budgets; quota exhaustion behavior.

**Planner / scorer**

- Fixed fixture subgraphs S/M: score-only and propose-3-alternatives—time and peak memory (stdlib `tracemalloc` or `/usr/bin/time`).
- Assert candidate count caps (no Cartesian explosion).

**Background job runner (when implemented)**

- Enqueue → complete → callback; discarded job when `turn_id` superseded.
- Concurrency limit enforced.

**API / harness**

- Tool chain: light path issues no Google call (mock assert).
- Payload size limits for frame DTOs at M.

**Client (later E2E)**

- Time to first skeleton frame vs time to full polyline patch.
- Map layer with N markers—frame rate / jank (profile mode), separate from server doc but same journey IDs as [`frame-journey-map.md`](frame-journey-map.md).

### System scenarios (combinations)

Run these to understand **interaction**, not isolated microbench:

| ID | Scenario | Components | Primary signal |
|----|----------|------------|----------------|
| **SYS-1** | User asks “what’s tomorrow?” on committed version S | PG, W1, W5 | p95 W1+W5 |
| **SYS-2** | User accepts hotel option → heavy legs | PG, gmaps mock 200 ms, W2 | p95 vs Google mock tier |
| **SYS-3** | Anticipation starts W3; user pivots topic | Jobs, discard, frames | No stale patch applied |
| **SYS-4** | Commit after edit S | PG W4, reservations | Transaction time + stale count |
| **SYS-5** | 10 users × 1 W3 each (staggered) | Workers, PG pool, gmaps | RSS cliff, p95 queue wait |
| **SYS-6** | Cold quota/cache | gmaps quota store | Stampede latency |
| **SYS-7** | L-size subgraph abuse attempt | API guard + PG | Reject or cap; no OOM |

**Load mix (later):** k6/Locust—~70% SYS-1, ~20% W1 chat, ~10% W3 trigger; ramp until golden budget breaks.

---

## Instrumentation (production-oriented)

- **Tracing:** OpenTelemetry (or equivalent) spans on workloads W1–W5; attributes: `edge_count`, `entity_count`, `candidate_count`, `trip_id`, `draft_id`, `version_id`.
- **Metrics:** Request/job duration histograms; worker RSS; queue depth; gmaps quota and cache hits.
- **Logs:** No secrets; aggregate slow-query log sampling—not per-edge debug in prod.

---

## CI and cadence

| Job | Gate? | Content |
|-----|-------|---------|
| `pytest -m unit` | pre-commit | Fast correctness |
| `pytest -m integration` | PR optional | Redis/quota paths |
| `pytest -m benchmark` | manual / nightly | gmaps regressions |
| `pytest -m perf` (future) | nightly, non-gating | W1–W4 S/M tables published as artifact |
| Load SYS-5 | pre-release manual | Capacity report |

---

## Deliverables checklist

- [ ] **This doc** — workloads, scenarios, markers (updated as code lands).
- [ ] **Baseline results** section filled after first `perf` run (date + SHA + table).
- [ ] **One concurrent job script** (or pytest module)—prints p95 and peak RSS for W3 stairs.
- [ ] **Span names** stable in harness for dashboards.
- [ ] **Production limits** doc snippet: max speculative jobs per worker, max subgraph size L rejected.

---

## Baseline results

_Fill after first measurement run._

| Date | SHA | Environment | Notes |
|------|-----|-------------|-------|
| | | | |

_Workload × size p50/p95 table: TBD._

---

## Non-goals

- Treating Postgres↔graph **synchronous** handoff as the main optimization target; graph DB remains optional projection ([`domain/domain-model.md`](domain/domain-model.md) draft/commit).
- Using production Google quota for every CI run—use mocks/`simulated_google` with tiered latency.
- DEBUG logging of request bodies or credentials ([security standards](../.cursor/rules/security-standards.mdc)).

---

## Related docs

- [`dialogue-interface.md`](dialogue-interface.md) — frames, async UX
- [`user-journeys.md`](user-journeys.md) — J7 disruption, reminders & monitors
- [`gmaps-client.md`](gmaps-client.md) — quota and cache knobs
