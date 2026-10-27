# Python code review

**Date:** 2026-10-27  
**Scope:** `src/gmaps/`, `tests/`, `benchmarks/`, `scripts/sync_google_maps_api_docs.py`, `docs/google-maps-api/free_tier_caps.py`  
**Summary:** No xhigh/high security issues. Several **moderate** maintainability and quota/cache behavior items worth addressing as FOGG grows.

## Global standards checklist

| Rule file | Status | Applied |
|-----------|--------|---------|
| `~/.cursor/rules/clean-code.mdc` | **read** | Naming, SRP, redundant control flow in decorator |
| `~/.cursor/rules/security-standards.mdc` | **read** | API key from env; sync script appends key to URL (dev-only); no secrets in logs |
| `~/.cursor/rules/python-standards.mdc` | **read** | Type hints, Pydantic models, tenacity on HTTP; broad `except Exception` at documented boundaries |
| `~/.cursor/rules/python-tests.mdc` | **read** | pytest, fakeredis mocks, async markers; tests lack `tests/__init__.py` (optional) |
| `~/.cursor/rules/fastapi-standards.mdc` | **read** | **deferred** — no FastAPI routes in repo |
| `fogg/.cursor/rules/collaboration.mdc` | **read** | Review-only pass |
| `fogg/.cursor/rules/git-commits.mdc` | **read** | Not applicable to code quality |
| `fogg/.cursor/rules/security-standards.mdc` | **read** | Same themes as global security (`.env-template` present) |

### Tooling

| Command | Result |
|---------|--------|
| `uv run ruff check src tests benchmarks scripts` | **not run** — `ruff` not in dev dependencies ( `[tool.ruff]` present in `pyproject.toml`) |
| `uv run ruff format … --check` | **not run** — same |
| `agents_layout.sh check-imports` | **skipped** — no `agents-harness-conventions` script in this repo |

---

## Findings

# src/gmaps/quota/decorator.py

## Line 68–71: clean-code/redundant try-except
Correction urgency: low

```python
            try:
                result = await inner(*args, **kwargs)
            except Exception:
                raise
```

The non-enforce branch wraps `inner()` in a try/except that only re-raises. Remove the try/except and call `await inner(...)` directly to reduce noise.

## Line 49–63: python-standards/broad except for refund
Correction urgency: moderate

```python
                try:
                    result = await inner(*args, **kwargs)
                except Exception:
                    await usage_store.refund(events)
                    raise
```

Refunding on any `Exception` is reasonable for quota accuracy (including `KeyboardInterrupt` if not careful). Prefer catching **`BaseException`** only for refund+reraise documentation, or a tuple of expected failures (`GoogleMapsApiError`, `httpx.HTTPError`, `ValidationError`) plus a final fallback that still refunds for unknown errors from Google/transport. Document why refund must run on cancel if you keep broad catch.

## Line 49: clean-code/billable events when tracking off
Correction urgency: low

`resolve_billable_events()` runs even when both enforcement and tracking are disabled. Short-circuit after reading settings to skip classifier work on hot paths in prod.

---

# src/gmaps/ (quota + cache interaction)

## Architectural: moderate/quota charged on cache hit
Correction urgency: moderate

The decorator reserves/records **before/after** the client function; `transport.google_post` may return from Redis **without HTTP**. Local quota still increments, which misaligns with “stay under Google free tier” if the goal is billable Google events only.

**Suggested correction:** expose cache hit from transport (return flag or context var) and skip `try_reserve` / `record` on hit; or document that FOGG quota means “logical agent calls” not Google billable events.

---

# src/gmaps/quota/store.py

## Line 143–145: python-standards/broad except in SQLite transaction
Correction urgency: low

```python
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
```

Acceptable for “always rollback on failure” if `GmapsQuotaExceededError` during check triggers rollback (it raises inside the try). Consider `except BaseException` with comment, or re-raise `GmapsQuotaExceededError` without treating as DB error. Current code rolls back then re-raises quota errors — correct behavior.

## Line 307–308: python-standards/sequential reserve fallback
Correction urgency: moderate

`_try_reserve_sequential` check-then-`INCRBY` pipeline is not atomic on real Redis (only used when `EVAL` unavailable, e.g. fakeredis). Document that production relies on Lua; tests may not catch concurrent over-cap races.

---

# src/gmaps/http_retry.py

## Line 113–125: python-standards/broad Exception handler
Correction urgency: low

Catches all non-`HTTPStatusError` exceptions after tenacity exhausts. Appropriate at HTTP boundary; ensure non-network bugs (`TypeError`, `ValueError`) are not retried by tenacity (they are not in `is_retryable_google_error` — good). No change required unless you want separate handling for programming errors vs network.

---

# src/gmaps/transport.py

## Line 98–101: python-standards/broad except wrapper
Correction urgency: low

Wraps unexpected errors as `GoogleMapsApiError`. Consistent with public API; optional `logging.exception` for unknown errors (careful not to log response bodies with PII).

---

# pyproject.toml

## Dev dependencies: python-standards/ruff not installed
Correction urgency: moderate

`[tool.ruff]` is configured but `ruff` is missing from `[project.optional-dependencies] dev`. CI and reviewers cannot run the configured linter.

**Suggested correction:** add `ruff>=0.8.0` (or current) to dev deps and document `uv run ruff check src tests`.

---

# tests/test_quota_enforcement.py

## Line 97: python-tests/private store API
Correction urgency: low

```python
    key = store._counter_key(period, "places_text_search_pro")
```

Tests reach into `RedisUsageStore._counter_key`. Prefer a public helper or set up state via `try_reserve` / client calls only.

---

# benchmarks/harness.py

## Line 107–108: clean-code/global tenacity patch
Correction urgency: moderate

```python
            http_retry_module.wait_exponential_jitter = lambda **_kwargs: wait_fixed(0)
```

Mutates module global; restored in `teardown` on success path. If `setup` fails mid-way or tests run in parallel, jitter could leak. Prefer `monkeypatch` fixture or patch object on the module for the benchmark process only.

---

# scripts/sync_google_maps_api_docs.py

## Line 15–24: python-standards/sys.path import hack
Correction urgency: low

Inserts `docs/google-maps-api` on `sys.path` to import `free_tier_caps`. Acceptable for a script; alternative is packaging caps as a small shared module under `src/` to avoid path mutation.

## Line 68–70: security-standards/API key in query string
Correction urgency: low

Discovery fetch appends `key=` to URL (Google’s pattern). Dev-only script; ensure logs never print `request_url`. Current code does not log URL — OK.

---

# docs/google-maps-api/free_tier_caps.py vs src/gmaps/quota/caps.py

## DRY: two sources of numeric caps
Correction urgency: low

Human-oriented OpenAPI extensions vs runtime `SKU_FREE_CAP`. Risk of drift when Google updates caps. Consider generating one from the other or a shared JSON source of truth.

---

## Clean areas

- Pydantic request models with strict `extra=forbid` and field masks.
- Tenacity retry whitelist (429/5xx/network) with explicit logging.
- Secrets via `GmapsSettings` / `.env-template`; `.env` gitignored.
- pytest coverage for transport, retry logs, quota block/refund/warn.
- No bare `except:` in scope.

## Recommended next review

After adding `ruff` to dev deps, agent code under `agents/`, or changes to quota/cache semantics — re-run this skill and compare `docs/CODEREVIEW.md` dates.
